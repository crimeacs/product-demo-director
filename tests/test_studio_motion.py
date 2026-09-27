"""Exercise the authored motion math used by the renderer, without a browser."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[1] / "engine"


class StudioMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = ENGINE / "node_modules" / "typescript" / "bin" / "tsc"
        if not shutil.which("node") or not compiler.exists():
            raise unittest.SkipTest("Install engine dependencies with npm ci to run motion tests")
        cls.output = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.output.cleanup)
        result = subprocess.run(["node", str(compiler), "src/studio-motion.ts", "--module", "commonjs",
                                 "--target", "ES2020", "--strict", "--skipLibCheck", "--outDir", cls.output.name],
                                cwd=ENGINE, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.module = str(Path(cls.output.name) / "studio-motion.js")

    def check_node(self, script):
        prelude = "const assert = require('node:assert/strict'); const motion = require(" + json.dumps(self.module) + ");\n"
        result = subprocess.run(["node", "-e", prelude + script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shot_holds_land_on_authored_poses_and_are_frame_rate_independent(self):
        self.check_node("""
            const path = [
                {atSec: 2, scale: 2, focusX: 75, focusY: 25},
                {atSec: 0.5, scale: 1, focusX: 50, focusY: 50},
                {atSec: 3, scale: 2, focusX: 75, focusY: 25},
                {atSec: 4, scale: 1.4, focusX: 50, focusY: 50, ease: 'settle'},
            ];
            const sample = (seconds, fps = 30) => motion.cameraTransform(path, seconds * fps, fps, 1920, 1080);
            assert.deepEqual(sample(-1), {s: 1, x: 0, y: 0});
            assert.deepEqual(sample(2), {s: 2, x: -1920, y: 0});
            assert.deepEqual(sample(2.7), sample(2));
            assert.deepEqual(sample(20), sample(4));
            assert.deepEqual(sample(1.27, 24), sample(1.27, 60));
            assert.deepEqual(path.map(p => p.atSec), [2, 0.5, 3, 4]);
        """)

    def test_authored_eases_are_distinct_monotone_and_join_holds_without_a_bump(self):
        self.check_node("""
            assert.ok(motion.motionEase(0.5, 'drive') < motion.motionEase(0.5, 'smooth'));
            assert.ok(motion.motionEase(0.5, 'settle') > motion.motionEase(0.5, 'smooth'));
            for (const ease of ['smooth', 'drive', 'settle', 'linear']) {
                let previous = 0;
                for (let step = 0; step <= 1000; step++) {
                    const value = motion.motionEase(step / 1000, ease);
                    assert.ok(Number.isFinite(value) && value >= previous && value <= 1);
                    previous = value;
                }
                assert.equal(motion.motionEase(-0.1, ease), 0);
                assert.equal(motion.motionEase(1.1, ease), 1);
                if (ease === 'linear') continue;
                const dt = 0.0001;
                const start = motion.motionEase(dt, ease);
                const end = 1 - motion.motionEase(1 - dt, ease);
                assert.ok(start / dt < 0.00001 && end / dt < 0.00001, 'zero endpoint velocity');
                const startAcceleration = (motion.motionEase(2 * dt, ease) - 2 * start) / dt ** 2;
                const endAcceleration = (1 - 2 * motion.motionEase(1 - dt, ease)
                    + motion.motionEase(1 - 2 * dt, ease)) / dt ** 2;
                assert.ok(Math.abs(startAcceleration) < 0.02 && Math.abs(endAcceleration) < 0.02,
                    'zero endpoint acceleration');
            }
        """)

    def test_camera_moves_remain_inside_source_even_with_opposite_edge_focuses(self):
        self.check_node("""
            for (const [width, height] of [[1920, 1080], [1080, 1920], [800, 800]]) {
                for (const ease of ['smooth', 'drive', 'settle', 'linear']) {
                    const path = [
                        {atSec: 0, scale: 0.1, focusX: -500, focusY: 500},
                        {atSec: 1, scale: 9, focusX: 500, focusY: -500, ease},
                        {atSec: 2, scale: 1.15, focusX: -500, focusY: 500, ease},
                    ];
                    for (let frame = 0; frame <= 240; frame++) {
                        const t = motion.cameraTransform(path, frame, 120, width, height);
                        assert.ok(Object.values(t).every(Number.isFinite));
                        assert.ok(t.s >= 1 && t.s <= motion.MAX_CAMERA_SCALE);
                        assert.ok(t.x <= 0 && t.x >= width * (1 - t.s));
                        assert.ok(t.y <= 0 && t.y >= height * (1 - t.s));
                    }
                }
            }
        """)

    def test_explicit_closeups_preserve_the_authored_scale_up_to_eight(self):
        self.check_node("""
            assert.equal(motion.MAX_CAMERA_SCALE, 8);
            for (const scale of [3.5, 4, 6, 8]) {
                const pose = motion.cameraTransform([{atSec: 0, scale, focusX: 75, focusY: 25}],
                    0, 30, 1920, 1080);
                assert.equal(pose.s, scale, 'never silently flatten a readable closeup to 3x');
                assert.equal(1920 * .75 * pose.s + pose.x, 960);
                assert.equal(1080 * .25 * pose.s + pose.y, 540);
            }
            assert.equal(motion.cameraTransform([{atSec: 0, scale: 99}], 0, 30, 1920, 1080).s, 8);
        """)

    def test_cover_camera_can_reach_source_content_outside_the_initial_crop(self):
        self.check_node("""
            const plane = {left: 0, top: (1080 - 1920 * 16/9)/2, width: 1920, height: 1920*16/9};
            const sourceY = plane.top + plane.height * .25;
            const pose = motion.cameraTransform([{atSec: 0, scale: 4, focusX: 50,
                focusY: sourceY / 1080 * 100}], 0, 30, 1920, 1080, plane);
            assert.ok(pose.y > 0, 'source outside initial cover crop must be reachable');
            assert.ok(Math.abs(sourceY * pose.s + pose.y - 540) < 1e-8);
            assert.ok(plane.top * pose.s + pose.y <= 0);
            assert.ok((plane.top + plane.height) * pose.s + pose.y >= 1080);
        """)

    def test_contain_closeups_remove_letterbox_and_moves_never_expose_extra_edges(self):
        self.check_node("""
            for (const plane of [
                {left: 240, top: 0, width: 1440, height: 1080},
                {left: 656.25, top: 0, width: 607.5, height: 1080},
                {left: 0, top: 270, width: 1920, height: 540},
            ]) {
                const path = [{atSec: 0, scale: 1, focusX: -100, focusY: 200},
                    {atSec: 1, scale: 8, focusX: 200, focusY: -100},
                    {atSec: 2, scale: 1, focusX: 200, focusY: -100}];
                for (let frame = 0; frame <= 240; frame++) {
                    const pose = motion.cameraTransform(path, frame, 120, 1920, 1080, plane);
                    for (const [offset, extent, translation, viewport] of [
                        [plane.left, plane.width, pose.x, 1920], [plane.top, plane.height, pose.y, 1080]
                    ]) {
                        const first = offset * pose.s + translation;
                        const last = (offset + extent) * pose.s + translation;
                        if (extent * pose.s >= viewport) {
                            assert.ok(first <= 1e-8 && last >= viewport - 1e-8);
                        } else {
                            assert.ok(Math.abs(first - (viewport - last)) < 1e-8,
                                'unavoidable letterbox stays centered');
                        }
                    }
                }
            }
        """)

    def test_clamping_camera_to_source_does_not_create_a_mid_move_velocity_kink(self):
        self.check_node("""
            // Interpolating raw focus then clamping per frame would abruptly stop panning.
            const path = [
                {atSec: 0, scale: 1.1, focusX: 0, focusY: 50},
                {atSec: 1, scale: 2.8, focusX: 100, focusY: 50, ease: 'smooth'},
            ];
            const sample = t => motion.cameraTransform(path, t, 1, 1920, 1080);
            const dt = 0.0001;
            for (let step = 1; step < 100; step++) {
                const t = step / 100;
                const left = sample(t - dt), center = sample(t), right = sample(t + dt);
                const derivativeJump = ((right.x - center.x) - (center.x - left.x)) / dt;
                assert.ok(Math.abs(derivativeJump) < 3, `camera kink at ${t}`);
            }
        """)

    def test_contain_fill_threshold_joins_the_pan_without_a_velocity_kink(self):
        self.check_node("""
            const plane = {left: 240, top: 0, width: 1440, height: 1080};
            const path = [{atSec: 0, scale: 1, focusX: 0, focusY: 50},
                {atSec: 1, scale: 2, focusX: 100, focusY: 50, ease: 'linear'}];
            const sample = t => motion.cameraTransform(path, t, 1, 1920, 1080, plane);
            const crossing = 1/3, dt = 0.0001;
            const left = sample(crossing - dt), center = sample(crossing), right = sample(crossing + dt);
            const velocityJump = ((right.x - center.x) - (center.x - left.x)) / dt;
            assert.ok(Math.abs(velocityJump) < 0.01, `contain fill kink: ${velocityJump}`);
        """)

    def test_empty_duplicate_and_degenerate_paths_are_deterministic(self):
        self.check_node("""
            assert.deepEqual(motion.cameraTransform([], 0, 30, 1920, 1080), {s: 1, x: 0, y: 0});
            const path = [
                {atSec: 0, scale: 1, focusX: 50, focusY: 50},
                {atSec: 0, scale: 2, focusX: 75, focusY: 25},
                {atSec: NaN, scale: 3, focusX: 50, focusY: 50},
            ];
            assert.deepEqual(motion.cameraTransform(path, 0, 30, 1920, 1080), {s: 2, x: -1920, y: 0});
            const degenerate = motion.cameraTransform([
                {atSec: 0, scale: NaN, focusX: Infinity, focusY: NaN}
            ], NaN, 0, NaN, -20);
            assert.ok(Object.values(degenerate).every(Number.isFinite));
        """)

    def test_entry_spans_always_leave_a_fully_visible_picture_frame(self):
        self.check_node("""
            for (let shotFrames = 1; shotFrames < 80; shotFrames++) {
                const duration = motion.boundedTransitionFrames(18, shotFrames);
                assert.ok(duration >= 0 && duration < shotFrames);
                assert.equal(motion.transitionProgress(shotFrames - 1, duration), 1);
                if (duration > 0) assert.equal(motion.transitionProgress(0, duration), 0);
            }
            assert.equal(motion.boundedTransitionFrames(-12, 60), 0);
            assert.equal(motion.transitionProgress(0, 0), 1);
            assert.equal(motion.transitionProgress(-1, 8), 0);
            assert.equal(motion.transitionProgress(9, 8), 1);
        """)

    def test_masked_entries_never_dim_or_blur_ui_and_finish_at_identity(self):
        self.check_node(r"""
            for (const kind of ['reveal', 'push']) {
                for (let frame = 0; frame <= 30; frame++) {
                    const style = motion.transitionStyle(kind, motion.transitionProgress(frame, 18), 1920, 1080);
                    assert.equal(style.opacity, 1);
                    assert.ok(!/NaN|Infinity/.test(JSON.stringify(style)));
                    assert.ok(!('filter' in style));
                    const mask = Number(style.clipPath.match(/([0-9.]+)%/)[1]);
                    assert.ok(mask >= 0 && mask <= 100);
                    const displacement = Number(style.transform.match(/translate3d\(([0-9.]+)/)[1]);
                    assert.ok(displacement >= 0 && displacement <= 1920 * 0.06);
                    if (frame >= 18) {
                        assert.equal(mask, 0);
                        assert.equal(displacement, 0);
                    }
                }
                const start = motion.transitionStyle(kind, 0, 1920, 1080);
                assert.ok(start.clipPath.includes('100%'));
            }
        """)


if __name__ == "__main__":
    unittest.main()
