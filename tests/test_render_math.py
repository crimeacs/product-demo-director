"""Run the engine's actual TypeScript frame/mix math without launching a browser."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class RenderMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = ENGINE / "node_modules" / "typescript" / "bin" / "tsc"
        if not shutil.which("node") or not compiler.exists():
            raise unittest.SkipTest("Install engine dependencies with npm ci to run render math tests")
        cls.output = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.output.cleanup)
        result = subprocess.run(["node", str(compiler), "src/render-math.ts", "--module", "commonjs",
                                 "--target", "ES2020", "--skipLibCheck", "--outDir", cls.output.name],
                                cwd=ENGINE, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.module = str(Path(cls.output.name) / "render-math.js")

    def check_node(self, script):
        prelude = "const assert = require('node:assert/strict'); const math = require(" + json.dumps(self.module) + ");\n"
        result = subprocess.run(["node", "-e", prelude + script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_detail_titles_fit_readable_bands_and_reject_impossible_placement(self):
        self.check_node("""
            const detail = {sourceRect: {x: 0, y: 0, width: 100, height: 100}};
            const text = 'A complete recorded control explains why the reviewer made this decision';
            const layout = math.detailTitleLayout(text, detail, 1920, 1080);
            assert.equal(layout.lines.join(' '), text);
            assert.equal(layout.lines.length, 2);
            assert.ok(layout.fontSize >= 60 && layout.fontSize <= 72);
            assert.ok(layout.top >= 54);
            assert.ok(layout.top + layout.height <= 226);
            assert.throws(() => math.detailTitleLayout('Complete control', {...detail,
                screenRect:{x:7,y:0,width:86,height:55}}, 1920, 1080), /Detail title cannot fit/);
            assert.throws(() => math.detailTitleLayout(text.repeat(5), detail, 1920, 1080), /Detail title cannot fit/);
            const small = math.detailTitleLayout(text, detail, 320, 180);
            assert.deepEqual(small.lines, layout.lines);
            assert.ok(Math.abs(small.fontSize * 6 - layout.fontSize) < 1e-8);
        """)

    def test_detail_captions_reserve_the_animated_plate_and_keep_all_words(self):
        self.check_node("""
            const detail = {sourceRect: {x:0,y:0,width:100,height:100}};
            const text = 'Separate recorded shopper test with all context preserved in its own caption band';
            const layout = math.detailCaptionLayout(text, detail, 1920, 1080, 72);
            assert.equal(layout.chunks.join(' '), text);
            assert.ok(layout.chunks.length > 1);
            assert.equal(layout.top, 900);
            assert.ok(layout.top >= 864 + 12 + 24);
            assert.ok(layout.top + layout.height <= 1068);
            const authored = math.detailCaptionLayout(text, detail, 1920, 1080, 72, 940);
            assert.equal(authored.top, 940);
            assert.throws(() => math.detailCaptionLayout(text, detail, 1920, 1080, 72, undefined, 108), /Detail caption cannot fit/);
            assert.throws(() => math.detailCaptionLayout(text, detail, 1920, 1080, 72, 1000), /Detail caption cannot fit/);
            assert.throws(() => math.detailCaptionLayout('W'.repeat(100), detail, 1920, 1080, 72), /Detail caption cannot fit/);
        """)

    def test_short_crossfades_finish_and_do_not_extend_past_the_next_shot(self):
        self.check_node("""
            const segments = [30, 2, 1, 60].map(durFrames => ({kind: 'title', durFrames, durSec: durFrames / 30}));
            const {rows, totalFrames} = math.timelineLayout(segments, 30);
            assert.equal(totalFrames, 93);
            assert.deepEqual(rows.map(r => r.fadeIn), [0, 1, 0, 9]);
            for (let i = 0; i < rows.length - 1; i++) {
                assert.ok(rows[i].start + rows[i].frames + rows[i].tail < rows[i+1].start + rows[i+1].frames);
            }
        """)

    def test_same_source_cuts_and_explicit_transitions(self):
        self.check_node("""
            const clip = {kind: 'clip', durSec: 1, src: 'app.mp4'};
            const {rows} = math.timelineLayout([clip, clip, {...clip, transition: 'xfade'}, {...clip, src: 'next.mp4', transition: 'cut'}], 30);
            assert.deepEqual(rows.map(r => r.fadeIn), [0, 0, 9, 0]);
            assert.equal(math.segmentFrames({kind: 'clip', durSec: 0.75}, 30), 23);
        """)

    def test_voice_windows_include_source_speech_and_end_when_vo_ends(self):
        self.check_node("""
            const windows = math.speechWindows([
                {kind: 'clip', durSec: 3, sound: true},
                {kind: 'title', durSec: 4, vo: 'vo.wav', voSec: 2},
                {kind: 'title', durSec: 2}
            ], 30, {src: 'master.wav', startAtSec: 8, durationSec: 5});
            assert.deepEqual(windows, [[0, 90], [90, 150], [240, 270]]);
            assert.deepEqual(math.speechWindows([{kind: 'clip', durSec: 1}], 30,
                {src: 'master.wav', startAtSec: 2}), []);
        """)

    def test_music_ducks_speech_and_fades_to_silence_on_last_picture(self):
        self.check_node("""
            assert.equal(math.musicGain(299, 300, 30, [], 0.2, 1.5), 0);
            assert.equal(math.musicGain(0, 1, 1, [], 0.2, 1.5), 0);
            assert.equal(math.musicGain(100, 300, 30, [[90, 120]], 1, 0), 0.45);
            assert.equal(math.musicGain(150, 300, 30, [[90, 120]], 1, 0), 1);
            assert.equal(math.musicGain(299, 300, 30, [], 0.2, 0), 0.2);
            for (let frames = 1; frames < 60; frames++) {
                for (let frame = 0; frame < frames; frame++) {
                    const gain = math.musicGain(frame, frames, 1, [[0, frames]], 0.2, 1.5);
                    assert.ok(Number.isFinite(gain) && gain >= 0 && gain <= 0.2);
                }
            }
        """)

    def test_authored_scale_and_focus_are_honored_without_exposing_edges(self):
        self.check_node("""
            assert.deepEqual(math.baseClipTransform({scale: 2, focusX: 75, focusY: 25}, 0, 30, 1920, 1080),
                {s: 2, x: -1920, y: 0});
            for (let frame = 0; frame < 60; frame++) {
                const t = math.baseClipTransform({startScale: 1, endScale: 2, panX: 80, panY: -80}, frame, 60, 1920, 1080);
                assert.ok(t.x <= 0 && t.x >= 1920 * (1 - t.s));
                assert.ok(t.y <= 0 && t.y >= 1080 * (1 - t.s));
            }
            assert.equal(math.baseClipTransform({startScale: 1, endScale: 2}, 59, 60, 1920, 1080).s, 2);
        """)

    def test_preserved_framing_is_immune_to_authored_camera_transforms(self):
        self.check_node("""
            assert.deepEqual(math.baseClipTransform({preserveFraming: true, scale: 2, startScale: 3,
                endScale: 4, panX: 50, focusX: 80}, 10, 60, 1920, 1080), {s: 1, x: 0, y: 0});
        """)

    def test_four_by_three_contain_maps_source_targets_and_annotations_inside_letterbox(self):
        self.check_node("""
            const plane = math.sourcePlane(1440, 1080, 1920, 1080, 'contain');
            assert.deepEqual(plane, {left: 240, top: 0, width: 1440, height: 1080});
            assert.deepEqual(math.sourceFocus(plane, 1920, 1080, 20, 75), {focusX: 27.5, focusY: 75});
            const annotation = {x: 20, y: 25, width: 30, height: 50};
            assert.deepEqual({
                left: plane.left + plane.width * annotation.x / 100,
                top: plane.top + plane.height * annotation.y / 100,
                width: plane.width * annotation.width / 100,
                height: plane.height * annotation.height / 100,
            }, {left: 528, top: 270, width: 432, height: 540});
            const focus = math.sourceFocus(plane, 1920, 1080, 25, 50);
            assert.deepEqual(math.baseClipTransform({scale: 2, ...focus}, 0, 30, 1920, 1080),
                {s: 2, x: -240, y: -540});
        """)

    def test_portrait_cover_keeps_full_source_plane_and_projects_cropped_targets(self):
        self.check_node("""
            const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);
            const plane = math.sourcePlane(1080, 1920, 1920, 1080, 'cover');
            near(plane.left, 0); near(plane.width, 1920);
            near(plane.height, 1920 * 16 / 9);
            near(plane.top, (1080 - plane.height) / 2);
            const center = math.sourceFocus(plane, 1920, 1080);
            near(center.focusX, 50); near(center.focusY, 50);
            const cropped = math.sourceFocus(plane, 1920, 1080, 50, 25);
            assert.ok(cropped.focusY < 0, 'covered points remain outside the output until camera bounds resolve them');
            near(cropped.focusY, 50 - (plane.height / 1080) * 25);
            const centerAnnotation = {y: 45, height: 10};
            near(plane.top + plane.height * centerAnnotation.y / 100,
                540 - plane.height * 0.05);
        """)

    def test_missing_source_dimensions_keep_legacy_full_frame_mapping(self):
        self.check_node("""
            for (const [sourceWidth, sourceHeight] of [[undefined, undefined], [1920, undefined],
                [0, 1080], [-1, 1080], [NaN, 1080], [1920, Infinity]]) {
                const plane = math.sourcePlane(sourceWidth, sourceHeight, 1920, 1080, 'contain');
                assert.deepEqual(plane, {left: 0, top: 0, width: 1920, height: 1080});
                assert.deepEqual(math.sourceFocus(plane, 1920, 1080, 12, 84), {focusX: 12, focusY: 84});
                assert.deepEqual(math.sourceFocus(plane, 1920, 1080), {focusX: 50, focusY: 50});
            }
            assert.deepEqual(math.sourcePlane(3840, 2160, 1920, 1080),
                {left: 0, top: 0, width: 1920, height: 1080});
        """)

    def test_large_captions_reduce_the_line_budget_at_smaller_output_widths(self):
        self.check_node("""
            assert.equal(math.captionCharacterBudget(1920, 23), 46, 'legacy labels stay unchanged');
            const large = math.captionCharacterBudget(1920, 72);
            assert.ok(large < 46 && large > 20, 'readable text must leave panel padding');
            assert.ok(math.captionCharacterBudget(1080, 72) < large);
            assert.equal(math.captionCharacterBudget(120, 72), 1);
        """)

    def test_detail_plate_fits_the_complete_native_roi_inside_the_output_box(self):
        self.check_node("""
            const g = math.detailPlateGeometry(1920, 1080, 1920, 1080, {
                sourceRect: {x:25,y:25,width:50,height:50},
                screenRect: {x:10,y:20,width:80,height:60},
            });
            assert.equal(g.scale,1.2);
            assert.deepEqual(g.plate,{left:384,top:216,width:1152,height:648});
            assert.deepEqual(g.video,{left:-576,top:-324,width:2304,height:1296});
            assert.equal(g.roi.left*g.scale+g.video.left,0);
            assert.equal(g.roi.top*g.scale+g.video.top,0);
            assert.equal((g.roi.left+g.roi.width)*g.scale+g.video.left,g.plate.width);
            assert.equal((g.roi.top+g.roi.height)*g.scale+g.video.top,g.plate.height);
        """)

    def test_detail_geometry_preserves_aspect_for_oriented_and_non_square_pixel_sources(self):
        self.check_node("""
            const near = (a,b) => assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
            for (const [sw,sh] of [[1080,1920],[2000,1000],[1000,2000],[1440,1080]]) {
                const g = math.detailPlateGeometry(sw,sh,1920,1080,{
                    sourceRect:{x:20,y:35,width:55,height:40}});
                near(g.plate.width/g.plate.height,g.roi.width/g.roi.height);
                near(g.video.width/g.video.height,sw/sh);
                assert.ok(g.plate.left>=g.bounds.left-1e-7 && g.plate.top>=g.bounds.top-1e-7);
                assert.ok(g.plate.left+g.plate.width<=g.bounds.left+g.bounds.width+1e-7);
                assert.ok(g.plate.top+g.plate.height<=g.bounds.top+g.bounds.height+1e-7);
                near(g.roi.left*g.scale+g.video.left,0);
                near(g.roi.top*g.scale+g.video.top,0);
            }
        """)

    def test_detail_geometry_rejects_missing_dimensions_or_incomplete_subject_rectangles(self):
        self.check_node("""
            const detail={sourceRect:{x:0,y:0,width:100,height:100}};
            for(const dimensions of [[undefined,1080],[1920,0],[NaN,1080],[1920,Infinity]]) {
                assert.throws(()=>math.detailPlateGeometry(...dimensions,1920,1080,detail),/dimensions/);
            }
            for(const rect of [{x:-1,y:0,width:50,height:50},{x:80,y:0,width:30,height:50},
                {x:0,y:0,width:0,height:50},{x:0,y:0,width:50,height:NaN}]) {
                assert.throws(()=>math.detailPlateGeometry(1920,1080,1920,1080,{sourceRect:rect}),/rectangles/);
                assert.throws(()=>math.detailPlateGeometry(1920,1080,1920,1080,{...detail,screenRect:rect}),/rectangles/);
            }
        """)


if __name__ == "__main__":
    unittest.main()
