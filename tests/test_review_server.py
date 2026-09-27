from http.client import HTTPConnection
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.review_server import ReviewHandler, ReviewServer


class ReviewServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "out").mkdir(parents=True)
        self.media = b"0123456789"
        (self.project / "out" / "demo.mp4").write_bytes(self.media)
        (self.project / "out" / "review.html").write_text("<h1>Review</h1>")
        (self.project / "out" / "empty.mp4").touch()
        (self.root / "private.txt").write_text("private")
        self.logs = patch.object(ReviewHandler, "log_message")
        self.logs.start()
        self.addCleanup(self.logs.stop)
        self.server = ReviewServer(self.project, 0)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path="/out/demo.mp4", method="GET", headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_loopback_only_full_file_and_root_redirect(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, body = self.request()
        self.assertEqual((status, body), (200, self.media))
        self.assertEqual(headers["Content-Length"], "10")
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        status, headers, body = self.request("/?preview=yes")
        self.assertEqual((status, body), (302, b""))
        self.assertEqual(headers["Location"], "/out/review.html")

    def test_finite_open_suffix_and_clamped_byte_ranges(self):
        for value, expected, content_range in (
            ("bytes=2-5", b"2345", "bytes 2-5/10"),
            ("bytes=7-", b"789", "bytes 7-9/10"),
            ("bytes=-3", b"789", "bytes 7-9/10"),
            ("bytes=8-999", b"89", "bytes 8-9/10"),
            ("bytes=-999", self.media, "bytes 0-9/10"),
            ("bytes=0-0", b"0", "bytes 0-0/10"),
        ):
            with self.subTest(value=value):
                status, headers, body = self.request(headers={"Range": value})
                self.assertEqual((status, body), (206, expected))
                self.assertEqual(headers["Content-Length"], str(len(expected)))
                self.assertEqual(headers["Content-Range"], content_range)

    def test_malformed_and_unsatisfiable_ranges_return_416(self):
        for value in ("bytes=", "bytes=-", "bytes=oops", "bytes=10-", "bytes=8-2",
                      "bytes=-0", "bytes=+1-3", "bytes=1.5-3", "bytes=" + "9" * 5000 + "-"):
            with self.subTest(value=value[:40]):
                status, headers, body = self.request(headers={"Range": value})
                self.assertEqual((status, body), (416, b""))
                self.assertEqual(headers["Content-Range"], "bytes */10")
                self.assertEqual(headers["Content-Length"], "0")

    def test_unsupported_units_and_multi_ranges_fall_back_to_complete_get(self):
        for value in ("seconds=1-2", "bytes=0-1,4-5", "bytes=0-1, 4-5"):
            with self.subTest(value=value):
                status, headers, body = self.request(headers={"Range": value})
                self.assertEqual((status, body), (200, self.media))
                self.assertNotIn("Content-Range", headers)

    def test_head_returns_full_get_headers_without_a_body_and_ignores_range(self):
        for headers in ({}, {"Range": "bytes=2-5"}, {"Range": "bytes=bad"}):
            with self.subTest(headers=headers):
                status, response_headers, body = self.request(method="HEAD", headers=headers)
                self.assertEqual((status, body), (200, b""))
                self.assertEqual(response_headers["Content-Length"], "10")
                self.assertEqual(response_headers["Accept-Ranges"], "bytes")
                self.assertNotIn("Content-Range", response_headers)
        self.assertEqual(self.request("/missing", method="HEAD")[::2], (404, b""))

    def test_if_range_prevents_combining_old_cached_video_with_new_bytes(self):
        _, headers, _ = self.request()
        for validator in (headers["ETag"], headers["Last-Modified"]):
            with self.subTest(validator=validator):
                self.assertEqual(self.request(headers={"Range": "bytes=2-5", "If-Range": validator})[::2],
                                 (206, b"2345"))
        (self.project / "out" / "demo.mp4").write_bytes(b"new performance")
        status, response_headers, body = self.request(headers={"Range": "bytes=2-5", "If-Range": headers["ETag"]})
        self.assertEqual((status, body), (200, b"new performance"))
        self.assertNotIn("Content-Range", response_headers)

    def test_empty_files_are_valid_but_have_no_satisfiable_range(self):
        status, headers, body = self.request("/out/empty.mp4")
        self.assertEqual((status, body, headers["Content-Length"]), (200, b"", "0"))
        status, headers, body = self.request("/out/empty.mp4", headers={"Range": "bytes=0-"})
        self.assertEqual((status, body), (416, b""))
        self.assertEqual(headers["Content-Range"], "bytes */0")

    def test_directories_have_no_listing_and_missing_files_are_404(self):
        for path in ("/out", "/out/", "/missing"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"demo.mp4", body)

    def test_encoded_and_plain_traversal_cannot_leave_the_project(self):
        for path in ("/../private.txt", "/%2e%2e/private.txt", "/%2e%2e%2fprivate.txt",
                     "/out/../../private.txt", "/out/%00demo.mp4"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 403)
                self.assertNotEqual(body, b"private")

    def test_symlinks_cannot_escape_but_internal_symlinks_work(self):
        (self.project / "leak.txt").symlink_to(self.root / "private.txt")
        (self.project / "external").symlink_to(self.root, target_is_directory=True)
        (self.project / "preview.mp4").symlink_to(self.project / "out" / "demo.mp4")
        self.assertEqual(self.request("/leak.txt")[0], 403)
        self.assertEqual(self.request("/external/private.txt")[0], 403)
        self.assertEqual(self.request("/preview.mp4")[::2], (200, self.media))

    def test_query_strings_and_escaped_filenames_resolve_to_the_same_file(self):
        (self.project / "out" / "my demo.mp4").write_bytes(self.media)
        self.assertEqual(self.request("/out/my%20demo.mp4?v=123")[::2], (200, self.media))

    def test_mutating_methods_are_rejected_without_touching_files(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
            with self.subTest(method=method):
                status, headers, body = self.request(method=method)
                self.assertEqual((status, body), (405, b""))
                self.assertEqual(headers["Allow"], "GET, HEAD")
        self.assertEqual((self.project / "out" / "demo.mp4").read_bytes(), self.media)

    def test_foreign_hostname_is_rejected(self):
        self.assertEqual(self.request(headers={"Host": "untrusted.example"})[0], 403)

    def test_cli_reports_occupied_port_and_missing_project_without_tracebacks(self):
        entry = Path(__file__).resolve().parents[1] / "tools" / "review_server.py"
        for project, port, expected in (
            (self.project, self.server.server_port, "Cannot serve review on 127.0.0.1:"),
            (self.project / "missing", 0, "Project directory does not exist"),
        ):
            with self.subTest(project=project):
                result = subprocess.run([sys.executable, str(entry), "--project", str(project),
                                         "--port", str(port)], capture_output=True, text=True, timeout=3)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
