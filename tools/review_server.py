#!/usr/bin/env python3
"""Serve one review project on loopback with seekable video and no directory listings."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


def byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Return one inclusive byte range; ignore unsupported units and multipart ranges."""
    if not value:
        return None
    unit, separator, spec = value.partition("=")
    if unit.strip().lower() != "bytes":
        return None
    if "," in spec:
        return None  # A full response is the standard fallback for unsupported ranges.
    match = re.fullmatch(r"([0-9]*)-([0-9]*)", spec.strip()) if separator else None
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError("invalid or unsatisfiable byte range")
    first, last = match.groups()
    if not first:
        suffix = int(last)
        if suffix <= 0:
            raise ValueError("invalid byte suffix")
        return max(0, size - suffix), size - 1
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("unsatisfiable byte range")
    return start, end


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "DemoDirectorReview/1"

    def do_GET(self):
        self._serve(head=False)

    def do_HEAD(self):
        self._serve(head=True)

    def _reject_method(self):
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _reject_method

    def _serve(self, *, head: bool):
        # Binding loopback prevents network access; rejecting foreign Host values also
        # prevents a remote site's DNS name from being used to read project files.
        host = self.headers.get("Host", "").lower()
        port = self.server.server_port
        if host and host not in {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}:
            self.send_error(403, "Only localhost requests are accepted")
            return
        try:
            request_path = unquote(urlsplit(self.path).path, errors="strict")
            if "\x00" in request_path:
                raise ValueError("invalid path")
            path = (self.server.project / request_path.lstrip("/")).resolve()
            path.relative_to(self.server.project)
        except (OSError, ValueError, UnicodeError, RuntimeError):
            self.send_error(403, "Path is outside the review project or invalid")
            return
        if request_path == "/":
            self.send_response(302)
            self.send_header("Location", "/out/review.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            if not path.is_file():
                raise FileNotFoundError
            handle = path.open("rb")
        except (OSError, ValueError):
            self.send_error(404, "Project file not found")
            return
        with handle:
            details = os.fstat(handle.fileno())
            if not stat.S_ISREG(details.st_mode):
                self.send_error(404, "Project file not found")
                return
            size = details.st_size
            modified = self.date_time_string(details.st_mtime)
            etag = f'"{details.st_mtime_ns:x}-{size:x}"'
            try:
                # Range applies to GET only. HEAD describes the complete resource.
                if_range = self.headers.get("If-Range")
                can_range = not head and (not if_range or if_range in {etag, modified})
                selected = byte_range(self.headers.get("Range"), size) if can_range else None
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            start, end = selected if selected is not None else (0, size - 1)
            length = end - start + 1
            self.send_response(206 if selected is not None else 200)
            self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Last-Modified", modified)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            if selected is not None:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            handle.seek(start)
            try:
                while length > 0:
                    chunk = handle.read(min(64 * 1024, length))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Scrubbing cancels the previous video request normally.


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, project: Path, port: int = 8765):
        self.project = Path(project).resolve()
        if not self.project.is_dir():
            raise ValueError(f"Project directory does not exist: {self.project}")
        if not 0 <= port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
        super().__init__(("127.0.0.1", port), ReviewHandler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        server = ReviewServer(args.project, args.port)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot serve review on 127.0.0.1:{args.port}: {exc}\n")
    with server:
        print(f"Review: http://127.0.0.1:{server.server_port}/out/review.html", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
