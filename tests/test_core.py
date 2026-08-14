import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from copy import deepcopy
from pathlib import Path

from wholesome_shorts.core import (ValidationError, resolve_ffmpeg, validate_clips,
                                   validate_package, word_count)


ROOT = Path(__file__).parents[1]


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.package = json.loads((ROOT / "examples/bicycle_kindness/package.json").read_text(encoding="utf-8"))

    def test_approved_example_is_valid_and_voice_over_in_range(self):
        validate_package(self.package)
        self.assertTrue(50 <= word_count(self.package["voice_over"]) <= 70)

    def test_rejects_underage_character(self):
        package = deepcopy(self.package)
        package["character_bible"][0]["age"] = 24
        with self.assertRaisesRegex(ValidationError, "25"):
            validate_package(package)

    def test_rejects_duplicate_scene_and_missing_twist(self):
        package = deepcopy(self.package)
        package["scenes"][1]["plan"] = package["scenes"][0]["plan"]
        package["scenes"][4].pop("reinterpretation")
        with self.assertRaises(ValidationError):
            validate_package(package)

    def test_rejects_prompt_without_safeguards(self):
        package = deepcopy(self.package)
        package["scenes"][0]["motion_prompt"] = "camera moves"
        with self.assertRaisesRegex(ValidationError, "lacks"):
            validate_package(package)

    def test_clip_names_and_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for number in range(1, 6):
                (folder / f"scene_{number:02d}.mp4").touch()
            self.assertEqual(len(validate_clips(folder, probe=lambda _: 8.0)), 5)
            with self.assertRaisesRegex(ValidationError, "8.5"):
                validate_clips(folder, probe=lambda _: 8.5)

    @patch("wholesome_shorts.core.shutil.which")
    def test_ffmpeg_explicit_option_wins(self, which):
        which.side_effect = lambda value: "/explicit/ffmpeg.exe" if value == "chosen" else None
        with patch.dict("os.environ", {"FFMPEG_BINARY": "environment"}):
            self.assertEqual(resolve_ffmpeg("chosen"), "/explicit/ffmpeg.exe")
        which.assert_called_once_with("chosen")

    @patch("wholesome_shorts.core.shutil.which")
    def test_ffmpeg_environment_wins_over_path(self, which):
        which.side_effect = lambda value: "/env/ffmpeg.exe" if value == "environment" else "/path/ffmpeg"
        with patch.dict("os.environ", {"FFMPEG_BINARY": "environment"}):
            self.assertEqual(resolve_ffmpeg(), "/env/ffmpeg.exe")
        which.assert_called_once_with("environment")

    @patch("wholesome_shorts.core.shutil.which", return_value="/path/ffmpeg")
    def test_ffmpeg_path_wins_over_imageio(self, which):
        with patch.dict("os.environ", {}, clear=True), patch.dict("sys.modules", {"imageio_ffmpeg": Mock()}):
            self.assertEqual(resolve_ffmpeg(), "/path/ffmpeg")
        which.assert_called_once_with("ffmpeg")

    @patch("wholesome_shorts.core.shutil.which", return_value=None)
    def test_ffmpeg_falls_back_to_imageio(self, _which):
        imageio = Mock()
        imageio.get_ffmpeg_exe.return_value = "/bundled/ffmpeg.exe"
        with patch.dict("os.environ", {}, clear=True), patch.dict("sys.modules", {"imageio_ffmpeg": imageio}):
            self.assertEqual(resolve_ffmpeg(), "/bundled/ffmpeg.exe")
        imageio.get_ffmpeg_exe.assert_called_once_with()

    @patch("wholesome_shorts.core.shutil.which", return_value=None)
    def test_invalid_explicit_ffmpeg_does_not_silently_fall_back(self, _which):
        with patch("wholesome_shorts.core.Path.is_file", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "--ffmpeg"):
                resolve_ffmpeg("missing.exe")


if __name__ == "__main__":
    unittest.main()
