import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from wholesome_shorts.core import export_episode, probe_duration, resolve_ffmpeg


ROOT = Path(__file__).parents[1]
try:
    FFMPEG = resolve_ffmpeg()
except FileNotFoundError:
    FFMPEG = None


@unittest.skipUnless(FFMPEG, "a usable FFmpeg binary is required for integration test")
class FfmpegIntegrationTests(unittest.TestCase):
    """Exercise the real editor and verify that concat preserves scene order."""

    def test_exports_vertical_video_with_all_five_scenes_in_order(self):
        # Colors are deliberately far apart so lossy H.264 encoding cannot confuse them.
        colors = ("red", "lime", "blue", "yellow", "magenta")
        expected_rgb = ((255, 0, 0), (0, 255, 0), (0, 0, 255),
                        (255, 255, 0), (255, 0, 255))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            episode = root / "episode"
            output = root / "output"
            episode.mkdir()
            package = json.loads(
                (ROOT / "examples/bicycle_kindness/package.json").read_text(encoding="utf-8")
            )
            for index, color in enumerate(colors, 1):
                subprocess.run([
                    FFMPEG, "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=180x320:r=15:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(episode / f"scene_{index:02d}.mp4"),
                ], check=True)

            final = export_episode(episode, output, package, ffmpeg=FFMPEG)
            inspection = subprocess.run(
                [FFMPEG, "-hide_banner", "-i", str(final), "-f", "null", "-"],
                capture_output=True, text=True, check=False,
            )
            self.assertIn("1080x1920", inspection.stderr)
            self.assertAlmostEqual(probe_duration(final, ffmpeg=FFMPEG), 5.0, delta=0.35)

            for segment, expected in enumerate(expected_rgb):
                pixel = subprocess.run([
                    FFMPEG, "-loglevel", "error", "-ss", str(segment + 0.5),
                    "-i", str(final), "-vf", "scale=1:1", "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
                ], capture_output=True, check=True).stdout
                self.assertEqual(len(pixel), 3)
                self.assertTrue(all(abs(actual - wanted) < 35 for actual, wanted in zip(pixel, expected)),
                                f"scene {segment + 1}: got {tuple(pixel)}, expected {expected}")
