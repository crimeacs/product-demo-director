"""Measured subject framing for small-screen viewing, without invented UI detail.

Source rectangles and glyph heights must be measured from the actual footage.
This geometric estimate is advisory: it cannot establish contrast, comprehension,
compression quality, or whether the source text stays unchanged during a hold.
"""

from __future__ import annotations

import copy
import math

MAX_CAMERA_SCALE = 8
DEFAULT_DETAIL_SCREEN_RECT = {"x": 7, "y": 25, "width": 86, "height": 55}
# Authored decimal seconds and canonical frame/fps seconds can differ after JSON
# serialization or six-decimal staging. This is far below one picture frame.
TIME_EPSILON = 1e-6
# Opt-in editorial limits, expressed in the viewer's frame rather than capture
# pixels. These are camera budgets, not a verdict on the quality of the footage.
DEFAULT_MOTION_LIMITS = {"maxTravelScreensPerSec": 1.5, "maxZoomOctavesPerSec": 1.2}
SMOOTH_PEAK_SPEED = 1.875  # derivative maximum of the renderer's quintic smooth ease
OUTPUT_MAGNIFICATION_TOLERANCE = 1.05


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _valid_percent_rect(rect):
    return isinstance(rect, dict) and not any(
        not _number(rect.get(pos)) or not _number(rect.get(size))
        or rect[pos] < -1e-9 or rect[size] <= 0 or rect[pos] + rect[size] > 100 + 1e-9
        for pos, size in (("x", "width"), ("y", "height")))


def _detail_text_width(text):
    """Match render-math.ts; the renderer also checks its loaded font's bounds."""
    return sum(0.27 if char.isspace() else 0.29 if char in "ilI1|.,'!:;" else
               0.9 if char in "MW@%&" else 0.67 if char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" else
               1 if ord(char) > 0x024f else 0.55 for char in text)


def _detail_text_lines(text, width, font_size):
    lines = []
    for word in text.split():
        if _detail_text_width(word) * font_size * 1.1 > width:
            return None
        if lines and _detail_text_width(lines[-1] + " " + word) * font_size * 1.1 <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def _detail_copy_errors(shot, width, height):
    """Keep editorial copy out of the complete native source and inside the canvas."""
    screen = shot["framing"].get("screenRect", DEFAULT_DETAIL_SCREEN_RECT)
    if not _valid_percent_rect(screen):
        return []
    errors = []
    scale = min(width / 1920, height / 1080)
    title = shot.get("title") or ""
    if not isinstance(title, str):
        errors.append(("FRAMING_DETAIL_TITLE_INVALID", "A detail title must be text"))
    elif title.strip():
        available = width * screen["width"] / 100
        band_height = height * screen["y"] / 100 - 98 * scale
        for size in range(72, 59, -1):
            font_size = size * scale
            lines = _detail_text_lines(title, available, font_size)
            if lines and len(lines) <= 2 and len(lines) * font_size * 1.3 <= band_height:
                break
        else:
            errors.append(("FRAMING_DETAIL_TITLE_INVALID",
                           "Detail title cannot fit above its plate at a readable size; shorten it or lower screenRect"))
    caption = shot.get("caption", shot.get("vo") or "")
    if caption is False or caption is None:
        caption = ""
    if not isinstance(caption, str):
        errors.append(("FRAMING_DETAIL_CAPTION_INVALID", "A detail caption must be text"))
    elif caption.strip():
        font = shot.get("captionFontSize", (25 if shot.get("captionStyle") == "quote" else 23) * scale)
        top, bottom = shot.get("captionTop"), shot.get("captionBottom")
        if (not _number(font) or font <= 0 or top is not None and not _number(top)
                or bottom is not None and not _number(bottom)):
            errors.append(("FRAMING_DETAIL_CAPTION_INVALID", "Detail caption size and positions must be finite numbers"))
        else:
            text_height = font * 1.3 + 20 * scale
            band_top = height * (screen["y"] + screen["height"]) / 100 + 36 * scale
            band_bottom = height - 12 * scale
            top = top if top is not None else band_top if bottom is None else height - bottom - text_height
            lines = _detail_text_lines(caption, width - 164 * scale, font)
            if top < band_top - 1e-6 or top + text_height > band_bottom + 1e-6 or not lines:
                errors.append(("FRAMING_DETAIL_CAPTION_INVALID",
                               "Detail caption cannot fit below its plate; adjust screenRect, caption position, or text size"))
    return errors


def validate_framing(shot, *, width=1920, height=1080):
    """Validate authored measurements and reading windows; do not inspect media."""
    if "framing" not in shot:
        return []
    findings = []

    def error(code, message):
        findings.append({"severity": "error", "code": code, "message": message, "shot": shot.get("n")})

    framing = shot["framing"]
    if not isinstance(framing, dict):
        error("FRAMING_INVALID", "framing must be an object with measured source geometry and beats")
        return findings
    if shot.get("kind", "clip") != "clip":
        error("FRAMING_INVALID", "Measured framing applies to clip shots")
    presentation = framing.get("presentation", "camera")
    if presentation not in ("camera", "detail"):
        error("FRAMING_PRESENTATION_INVALID", "framing.presentation must be camera or detail")
    detail = presentation == "detail"
    if "entranceSec" in framing:
        if not detail or not _number(framing["entranceSec"]) or not 0 <= framing["entranceSec"] <= 1:
            error("FRAMING_DETAIL_ENTRANCE_INVALID", "framing.entranceSec must be between 0 and 1 for detail presentation; use 0 for a stationary plate")
    if "motion" in framing:
        motion = framing["motion"]
        if detail:
            error("FRAMING_MOTION_INVALID", "framing.motion applies only to camera presentation")
        if not isinstance(motion, dict) or any(key not in DEFAULT_MOTION_LIMITS for key in motion):
            error("FRAMING_MOTION_INVALID", "framing.motion must contain only maxTravelScreensPerSec and maxZoomOctavesPerSec")
        elif any(not _number(value) or not 0.01 <= value <= 100 for value in motion.values()):
            error("FRAMING_MOTION_INVALID", "Camera motion limits must be finite numbers between 0.01 and 100")
    if "screenRect" in framing:
        if not detail:
            error("FRAMING_PRESENTATION_INVALID", "framing.screenRect applies only to detail presentation")
        if not _valid_percent_rect(framing["screenRect"]):
            error("FRAMING_SCREEN_RECT_INVALID", "screenRect must fit within the output in x/y/width/height percentages")
    if detail and shot.get("annotations"):
        error("FRAMING_DETAIL_CONFLICT", "Detail presentation does not support source annotations; retain the complete native component")
    if detail:
        for code, message in _detail_copy_errors(shot, width, height):
            error(code, message)
    direction = shot.get("direction") or {}
    if isinstance(direction, dict) and direction.get("layout") == "stage":
        error("FRAMING_LAYOUT_INVALID", "Measured framing requires a fullbleed layout")
    for key in ("sourceWidth", "sourceHeight"):
        if not _number(framing.get(key)) or not 1 <= framing[key] <= 1_000_000:
            error("FRAMING_GEOMETRY_INVALID", f"framing.{key} must be the source display dimension between 1 and 1,000,000 pixels")
    for key, fallback in (("viewerWidthPx", 320), ("minTextPx", 12)):
        value = framing.get(key, fallback)
        if not _number(value) or not 1 <= value <= 1_000_000:
            error("FRAMING_READABILITY_INVALID", f"framing.{key} must be a finite number between 1 and 1,000,000 pixels")
    inset = framing.get("safeInsetPct", 6)
    if not _number(inset) or not 0 <= inset < 40:
        error("FRAMING_GEOMETRY_INVALID", "framing.safeInsetPct must be finite and between 0 and 40 (exclusive)")
    move = framing.get("transitionSec", 0.45)
    if not _number(move) or not 0 < move <= 3:
        error("FRAMING_TIMING_INVALID", "framing.transitionSec must be finite, positive, and at most 3 seconds")
        move = 0.45
    if shot.get("objectFit", "cover") not in ("cover", "contain"):
        error("FRAMING_GEOMETRY_INVALID", "Measured framing supports objectFit cover or contain")
    beats = framing.get("beats")
    if not isinstance(beats, list) or not beats:
        error("FRAMING_INVALID", "framing.beats must contain at least one measured reading window")
        return findings
    if detail and len(beats) != 1:
        error("FRAMING_DETAIL_TIMING_INVALID", "Detail presentation requires exactly one complete source rectangle for the whole shot")
    duration = shot.get("durSec", 2.5)
    previous_end = None
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            error("FRAMING_INVALID", "Every framing beat must be an object")
            continue
        at, end = beat.get("atSec"), beat.get("endSec")
        valid_times = (_number(at) and _number(end) and _number(duration)
                       and 0 <= at < min(end, duration) and end <= duration + TIME_EPSILON)
        if not valid_times:
            error("FRAMING_TIMING_INVALID", "Framing beats need 0 <= atSec < endSec <= shot duration")
        else:
            if index == 0 and at != 0:
                error("FRAMING_TIMING_INVALID", "The first framing beat must start at 0 so its initial view is explicit")
            if previous_end is not None and at - previous_end < move - 1e-9:
                error("FRAMING_TIMING_INVALID", "Leave at least transitionSec between reading windows for the camera move")
            previous_end = end
            if detail and (at != 0 or abs(end - duration) > TIME_EPSILON):
                error("FRAMING_DETAIL_TIMING_INVALID", "The detail reading window must span the whole shot, from 0 through durSec")
        rect = beat.get("rect")
        valid_rect = _valid_percent_rect(rect)
        if not valid_rect:
            error("FRAMING_RECT_INVALID", "Each framing rect must fit within the source in x/y/width/height percentages")
        elif all(_number(framing.get(key)) and framing[key] > 0 for key in ("sourceWidth", "sourceHeight")):
            if any(rect[size] / 100 * framing[dimension] < 1
                   for size, dimension in (("width", "sourceWidth"), ("height", "sourceHeight"))):
                error("FRAMING_RECT_INVALID", "A measured subject must cover at least one source display pixel on each axis")
        if "textHeightPx" in beat and (not _number(beat["textHeightPx"]) or not 1 <= beat["textHeightPx"] <= 1_000_000):
            error("FRAMING_READABILITY_INVALID", "textHeightPx must be a measured positive glyph height in source display pixels")
        if "label" in beat and (not isinstance(beat["label"], str) or not beat["label"].strip()
                                or len(beat["label"]) > 120):
            error("FRAMING_INVALID", "A framing label must be a nonempty description of at most 120 characters")
    return findings


def _axis_transform(viewport, offset, extent, scale, focus):
    """Match the renderer's full fitted-source bounds, including letterboxing."""
    low, high = viewport - (offset + extent) * scale, -offset * scale
    if low > high:
        return (low + high) / 2
    return max(low, min(high, viewport / 2 - focus * scale))


def _motion_budget(before, after, width, height, minimum_sec, limits, plane):
    """Budget apparent image travel, including zoom and source-bound clamping.

    Measure the source points at both viewport corners, not the full source's
    invisible corners or raw focus coordinates. A pan across two screen heights
    should cost the same time at 320px playback as at 1920px. The conservative
    derivative bounds also cover the renderer's cubic contain-fill interpolation.
    No source timing, reading window, or action is changed by this calculation.
    """
    sa, xa, ya = before
    sb, xb, yb = after
    ds = sb - sa
    points = {( (x - tx) / scale, (y - ty) / scale)
              for scale, tx, ty in (before, after)
              for x in (0, width) for y in (0, height)}
    travel = max(math.hypot((ds * x + xb - xa) / width,
                           (ds * y + yb - ya) / height) for x, y in points)

    def axis_derivatives(a, b, viewport, offset, extent):
        if min(sa, sb) * extent >= viewport:
            return [b - a]
        center_slope = -(offset + extent / 2) * ds
        if max(sa, sb) * extent <= viewport:
            return [center_slope]
        covered_scale, covered_axis = (sa, a) if sa > sb else (sb, b)
        center = viewport / 2 - (offset + extent / 2) * covered_scale
        # Available overflow runs monotonically from zero to one. Taking both
        # derivative endpoints bounds its squared term throughout the crossing.
        edge_slope = center_slope + 3 * (covered_axis - center) * extent * ds / (extent * covered_scale - viewport)
        return [center_slope, edge_slope]

    left, top, plane_width, plane_height = plane
    dx = axis_derivatives(xa, xb, width, left, plane_width)
    dy = axis_derivatives(ya, yb, height, top, plane_height)
    max_flow = max(math.hypot((ds * x + vx) / width, (ds * y + vy) / height)
                   for x, y in points for vx in dx for vy in dy)
    # Scale is interpolated linearly in eased time. Dividing by the smaller
    # endpoint scale bounds log2(scale)'s instantaneous derivative; log2(end /
    # start) alone would underestimate the peak for a large push.
    zoom = abs(math.log2(sb / sa))
    zoom_speed = SMOOTH_PEAK_SPEED * abs(ds) / (min(sa, sb) * math.log(2))
    travel_speed = SMOOTH_PEAK_SPEED * max_flow
    required = max(minimum_sec, travel_speed / limits["maxTravelScreensPerSec"],
                   zoom_speed / limits["maxZoomOctavesPerSec"])
    return {"travelScreens": travel, "zoomOctaves": zoom, "requiredSec": required,
            "travelSpeedNumerator": travel_speed, "zoomSpeedNumerator": zoom_speed}


def _compile_detail(shot, width, height):
    """Fit a complete native component into a designed plate, never a viewport crop."""
    framing = shot["framing"]
    beat = framing["beats"][0]
    rect = copy.deepcopy(beat["rect"])
    screen = copy.deepcopy(framing.get("screenRect", DEFAULT_DETAIL_SCREEN_RECT))
    source_width, source_height = framing["sourceWidth"], framing["sourceHeight"]
    crop_width, crop_height = source_width * rect["width"] / 100, source_height * rect["height"] / 100
    available_width, available_height = width * screen["width"] / 100, height * screen["height"] / 100
    scale = min(available_width / crop_width, available_height / crop_height)
    plate_width, plate_height = crop_width * scale, crop_height * scale
    left = width * screen["x"] / 100 + (available_width - plate_width) / 2
    top = height * screen["y"] / 100 + (available_height - plate_height) / 2
    viewer_width, minimum = framing.get("viewerWidthPx", 320), framing.get("minTextPx", 12)
    viewer_scale = scale * viewer_width / width
    glyph_height = beat.get("textHeightPx")
    projected_text = glyph_height * viewer_scale if glyph_height is not None else None
    base_fit = (min if shot.get("objectFit", "cover") == "contain" else max)(
        width / source_width, height / source_height)
    equivalent_scale = scale / base_fit
    findings = []

    def finding(code, message, severity="warning"):
        findings.append({"severity": severity, "code": code, "message": message,
                         "shot": shot.get("n"), "beat": 0})

    if projected_text is None:
        finding("FRAMING_TEXT_UNMEASURED", "No glyph height was measured; text legibility is unknown.", "info")
    elif projected_text + 1e-6 < minimum:
        finding("FRAMING_TEXT_TOO_SMALL",
                f"The complete detail projects text to {projected_text:.1f}px at {viewer_width:g}px viewing width, below {minimum:g}px; select a smaller complete component or capture larger UI.")
    if viewer_scale > 1 + 1e-6:
        finding("FRAMING_SOURCE_MAGNIFIED",
                f"The source pixels are enlarged {viewer_scale:.2f}× at {viewer_width:g}px viewing width; inspect pixelation or recapture at higher density.")
    if scale > OUTPUT_MAGNIFICATION_TOLERANCE + 1e-6:
        finding("FRAMING_OUTPUT_MAGNIFIED",
                f"The native detail is enlarged {scale:.2f}× in the {width:g}×{height:g} export "
                f"({1 / scale:.2f} source pixels per output pixel). Capture more native pixels or reduce its output size; a smaller preview can hide softness.")
    source_detail = {"sourceRect": rect, "screenRect": screen,
                     "entranceSec": framing.get("entranceSec", 0.4), "radiusPx": 0}
    direction = shot.get("direction")
    alignment = direction.get("align") if isinstance(direction, dict) else None
    if alignment in ("left", "center"):
        source_detail["titleAlign"] = alignment
    row = {"label": beat.get("label", "Native source detail"), "atSec": 0, "endSec": shot["durSec"],
           "rect": copy.deepcopy(rect),
           # Review compatibility only: a detail plate never applies a camera transform.
           "camera": {"scale": equivalent_scale, "focusX": rect["x"] + rect["width"] / 2,
                      "focusY": rect["y"] + rect["height"] / 2},
           "sourceTextHeightPx": glyph_height, "projectedTextPx": projected_text,
           "requiredScale": minimum / (glyph_height * base_fit * viewer_width / width) if glyph_height else None,
           "fitScale": equivalent_scale, "subjectVisible": True, "safeAreaMet": True,
           "sourceToOutputScale": scale, "sourceToViewerScale": viewer_scale,
           "sourcePixelsPerOutputPixel": 1 / scale,
           "projectedRectPx": {"x": left * viewer_width / width, "y": top * viewer_width / width,
                               "width": plate_width * viewer_width / width,
                               "height": plate_height * viewer_width / width}}
    status = ("needs-review" if any(item["severity"] == "warning" for item in findings)
              else "unknown" if projected_text is None else "clear-declared")
    return [], {"schemaVersion": 1, "advisory": True, "presentation": "detail", "status": status,
                "viewerWidthPx": viewer_width, "minTextPx": minimum,
                "sourceDetail": source_detail, "beats": [row], "findings": findings}


def compile_framing(shot, production=None, *, width=1920, height=1080):
    """Fill safe space with each measured subject, then report achieved legibility.

    A whole subject has priority over magnifying one line and clipping its context.
    If the text target and whole rectangle cannot both fit, report that tradeoff;
    the author must choose a smaller truthful subject or capture a larger UI.
    """
    errors = validate_framing(shot, width=width, height=height)
    if errors:
        raise ValueError("; ".join(f"{item['code']}: {item['message']}" for item in errors))
    if "framing" not in shot:
        return [], None
    framing = shot["framing"]
    if framing.get("presentation") == "detail":
        return _compile_detail(shot, width, height)
    production = production or {}
    limit = min(MAX_CAMERA_SCALE, production.get("maxZoomScale", MAX_CAMERA_SCALE))
    source_width, source_height = framing["sourceWidth"], framing["sourceHeight"]
    fit = min if shot.get("objectFit", "cover") == "contain" else max
    source_scale = fit(width / source_width, height / source_height)
    plane_width, plane_height = source_width * source_scale, source_height * source_scale
    left, top = (width - plane_width) / 2, (height - plane_height) / 2
    inset = framing.get("safeInsetPct", 6) / 100
    viewer_width, minimum = framing.get("viewerWidthPx", 320), framing.get("minTextPx", 12)
    move = framing.get("transitionSec", 0.45)
    rows, findings, camera = [], [], []
    motion_limits = ({**DEFAULT_MOTION_LIMITS, **framing["motion"]}
                     if "motion" in framing else None)
    moves = []

    def finding(code, message, index, severity="warning"):
        findings.append({"severity": severity, "code": code, "message": message,
                         "shot": shot.get("n"), "beat": index})

    previous_pose = previous_transform = previous_end = None
    for index, beat in enumerate(framing["beats"]):
        rect = beat["rect"]
        x, y = left + plane_width * rect["x"] / 100, top + plane_height * rect["y"] / 100
        w, h = plane_width * rect["width"] / 100, plane_height * rect["height"] / 100
        fit_scale = min(width * (1 - 2 * inset) / w, height * (1 - 2 * inset) / h)
        scale = max(1, min(limit, fit_scale))
        fx, fy = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        tx = _axis_transform(width, left, plane_width, scale, x + w / 2)
        ty = _axis_transform(height, top, plane_height, scale, y + h / 2)
        projected = {"x": x * scale + tx, "y": y * scale + ty,
                     "width": w * scale, "height": h * scale}
        epsilon = 1e-6
        visible = (projected["x"] >= -epsilon and projected["y"] >= -epsilon
                   and projected["x"] + projected["width"] <= width + epsilon
                   and projected["y"] + projected["height"] <= height + epsilon)
        safe = (projected["x"] >= width * inset - epsilon and projected["y"] >= height * inset - epsilon
                and projected["x"] + projected["width"] <= width * (1 - inset) + epsilon
                and projected["y"] + projected["height"] <= height * (1 - inset) + epsilon)
        text_height = beat.get("textHeightPx")
        output_scale = source_scale * scale
        viewer_scale = output_scale * viewer_width / width
        projected_text = (text_height * source_scale * scale * viewer_width / width
                          if text_height is not None else None)
        required = (minimum / (text_height * source_scale * viewer_width / width)
                    if text_height is not None else None)
        pose = {"scale": scale, "focusX": fx, "focusY": fy, "ease": "smooth"}
        at, end = beat["atSec"], min(beat["endSec"], shot.get("durSec", 2.5))
        if previous_pose is not None:
            move_sec = move
            if motion_limits is not None:
                budget = _motion_budget(previous_transform, (scale, tx, ty), width, height,
                                        move, motion_limits, (left, top, plane_width, plane_height))
                available = at - previous_end
                move_sec = min(available, budget["requiredSec"])
                feasible = budget["requiredSec"] <= available + TIME_EPSILON
                moves.append({"fromBeat": index - 1, "toBeat": index,
                              "startSec": at - move_sec, "endSec": at,
                              "durationSec": move_sec, "availableSec": available,
                              "requiredSec": budget["requiredSec"], "feasible": feasible,
                              "travelScreens": budget["travelScreens"], "zoomOctaves": budget["zoomOctaves"],
                              "peakTravelScreensPerSecBound": budget["travelSpeedNumerator"] / move_sec,
                              "peakZoomOctavesPerSecBound": budget["zoomSpeedNumerator"] / move_sec})
                if not feasible:
                    finding("FRAMING_MOTION_BUDGET_EXCEEDED",
                            f"Camera move needs {budget['requiredSec']:.2f}s but only {available:.2f}s exists between reading holds. "
                            "Reduce travel, widen the view, or author a cut; reading holds and source actions were preserved.", index)
            start_move = at - move_sec
            # A long gap holds the previous view until the deliberate camera move.
            if start_move > camera[-1]["atSec"] + 1e-9:
                camera.append({"atSec": start_move, **previous_pose})
        camera.extend([{"atSec": at, **pose}, {"atSec": end, **pose}])
        previous_pose = pose
        previous_transform = (scale, tx, ty)
        previous_end = end
        rows.append({"label": beat.get("label", f"Subject {index + 1}"), "atSec": at, "endSec": end,
                     "rect": copy.deepcopy(rect), "camera": copy.deepcopy(pose),
                     "sourceTextHeightPx": text_height, "projectedTextPx": projected_text,
                     "sourceToOutputScale": output_scale, "sourceToViewerScale": viewer_scale,
                     "sourcePixelsPerOutputPixel": 1 / output_scale,
                     "requiredScale": required, "fitScale": fit_scale if math.isfinite(fit_scale) else None,
                     "subjectVisible": visible, "safeAreaMet": safe,
                     "projectedRectPx": {key: value * viewer_width / width for key, value in projected.items()}})
        if not visible:
            finding("FRAMING_SUBJECT_CLIPPED", "The complete declared subject cannot fit at scale 1 with this source fit; change the fit or subject.", index)
        elif not safe:
            finding("FRAMING_SAFE_AREA_MISSED", "The source edge prevents the declared subject from keeping the requested inset.", index)
        if projected_text is None:
            finding("FRAMING_TEXT_UNMEASURED", "No glyph height was measured; text legibility is unknown.", index, "info")
        elif projected_text + epsilon < minimum:
            finding("FRAMING_TEXT_TOO_SMALL",
                    f"Measured text projects to {projected_text:.1f}px at {viewer_width:g}px viewing width, below {minimum:g}px; choose a tighter subject or capture larger UI.", index)
        if output_scale > OUTPUT_MAGNIFICATION_TOLERANCE + epsilon:
            finding("FRAMING_OUTPUT_MAGNIFIED",
                    f"The native source is enlarged {output_scale:.2f}× in the {width:g}×{height:g} export "
                    f"({1 / output_scale:.2f} source pixels per output pixel). Capture more native pixels or reduce zoom; a smaller preview can hide softness.", index)
    status = ("needs-review" if any(item["severity"] == "warning" for item in findings)
              else "unknown" if any(row["projectedTextPx"] is None for row in rows) else "clear-declared")
    report = {"schemaVersion": 1, "advisory": True, "presentation": "camera", "status": status,
              "viewerWidthPx": viewer_width, "minTextPx": minimum,
              "safeInsetPct": inset * 100, "maxZoomScale": limit, "beats": rows, "findings": findings}
    if motion_limits is not None:
        report["motion"] = {"mode": "distance-aware", "limits": motion_limits, "moves": moves,
                            "status": "within-budget" if all(item["feasible"] for item in moves) else "needs-review"}
    return camera, report
