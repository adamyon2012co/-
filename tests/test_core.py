import json
import tempfile
import unittest
import sys
import types
from unittest.mock import Mock, patch
from copy import deepcopy
from pathlib import Path

from wholesome_shorts.core import (ValidationError, resolve_ffmpeg, validate_clips,
                                   validate_package, word_count, SubtitleCue, write_ass,
                                   export_episode, APPROVED_VOICES,
                                   generate_narration, select_voice)
from wholesome_shorts.cli import parser


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

    def test_ass_captions_are_bold_outlined_and_limited_to_two_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "captions.ass"
            write_ass([SubtitleCue(1.25, 2.5, r"A clear first line\Nand a second")], target)
            contents = target.read_text(encoding="utf-8-sig")
            self.assertIn("Arial,72", contents)
            self.assertIn(",-1,0,0,0,100,100,0,0,1,5,0,2,90,90,500,1", contents)
            self.assertIn("0:00:01.25,0:00:02.50", contents)
            self.assertEqual(contents.count(r"\N"), 1)

    def _edge_module(self, chunks):
        module = types.ModuleType("edge_tts")
        instances = []

        class Communicate:
            def __init__(self, text, voice, rate="+0%", pitch="+0Hz"):
                self.text, self.voice = text, voice
                self.rate, self.pitch, self.stream_calls = rate, pitch, 0
                instances.append(self)

            async def stream(self):
                self.stream_calls += 1
                for chunk in chunks:
                    yield chunk

        module.Communicate = Communicate
        return module, instances

    def test_narration_collects_audio_and_ordered_word_boundaries_in_one_pass(self):
        chunks = [
            {"type": "audio", "data": b"first"},
            {"type": "WordBoundary", "offset": 10_000_000, "duration": 2_000_000, "text": "Hello"},
            {"type": "audio", "data": b"second"},
            {"type": "WordBoundary", "offset": 13_000_000, "duration": 4_000_000, "text": "world"},
        ]
        edge, instances = self._edge_module(chunks)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"edge_tts": edge}):
            audio = Path(directory) / "narration.mp3"
            cues = generate_narration("Hello world", audio)
            self.assertEqual(audio.read_bytes(), b"firstsecond")
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].stream_calls, 1)
        self.assertEqual((instances[0].rate, instances[0].pitch), ("+0%", "+0Hz"))
        self.assertEqual(cues, [SubtitleCue(1.0, 1.85, r"Hello\Nworld")])

    def test_voice_selection_uses_package_signals_and_restrained_prosody(self):
        package = deepcopy(self.package)
        package.update({"tone": "playful", "genre": "comedy", "mood": "joyful"})
        selection = select_voice(package)
        self.assertEqual(selection.voice, "en-US-JennyNeural")
        self.assertEqual((selection.rate, selection.pitch), ("+6%", "+2Hz"))
        self.assertIn("tone, genre, and mood", selection.reason)
        self.assertIn(selection.voice, APPROVED_VOICES)

    def test_voice_override_and_invalid_override_fallback(self):
        package = deepcopy(self.package)
        package["voice"] = "en-US-DavisNeural"
        self.assertEqual(select_voice(package).voice, "en-US-DavisNeural")
        package["voice"] = "not-an-approved-voice"
        fallback = select_voice(package)
        self.assertEqual(fallback.voice, "en-US-GuyNeural")
        self.assertIn("fell back", fallback.reason)

    @patch("wholesome_shorts.core.probe_duration", return_value=4.0)
    def test_narration_approximates_timings_when_audio_has_no_boundaries(self, probe):
        edge, instances = self._edge_module([{"type": "audio", "data": b"valid mp3"}])
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"edge_tts": edge}):
            audio = Path(directory) / "narration.mp3"
            cues = generate_narration("one two three four", audio, ffmpeg="resolved-ffmpeg")
        probe.assert_called_once_with(audio, ffmpeg="resolved-ffmpeg")
        self.assertEqual(instances[0].stream_calls, 1)
        self.assertEqual(cues, [SubtitleCue(0.0, 4.0, r"one two\Nthree four")])

    def test_narration_rejects_response_with_no_audio(self):
        edge, _instances = self._edge_module([
            {"type": "WordBoundary", "offset": 0, "duration": 1_000_000, "text": "Hello"}
        ])
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"edge_tts": edge}):
            with self.assertRaisesRegex(ValidationError, "did not return audio"):
                generate_narration("Hello", Path(directory) / "narration.mp3")

    def test_cli_can_disable_narration_and_captions(self):
        args = parser().parse_args(["export", "episode", "--no-narration", "--no-captions"])
        self.assertTrue(args.no_narration)
        self.assertTrue(args.no_captions)

    @patch("wholesome_shorts.core.resolve_ffmpeg", return_value="ffmpeg")
    def test_export_uses_voice_timing_ducks_audio_and_preserves_final_mp4(self, _resolve):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            episode, output = root / "episode", root / "output"
            episode.mkdir()
            output.mkdir()
            (output / "final.mp4").write_bytes(b"keep")
            for name in (f"scene_{number:02d}.mp4" for number in range(1, 6)):
                (episode / name).touch()
            package = json.loads((ROOT / "examples/bicycle_kindness/package.json").read_text())
            commands = []

            def runner(command, **kwargs):
                commands.append(command)
                if "-hide_banner" in command:
                    return Mock(stderr="Duration: 00:00:08.00")
                return Mock(returncode=0)

            def narrator(text, path, voice, rate, pitch):
                self.assertEqual(text, package["voice_over"])
                self.assertEqual(voice, "en-US-AriaNeural")
                self.assertEqual((rate, pitch), ("-2%", "+1Hz"))
                path.write_bytes(b"audio")
                return [SubtitleCue(0, 1, "Hello world")]

            final = export_episode(episode, output, package, runner=runner, narrator=narrator)
            self.assertEqual(final.name, "final_captioned.mp4")
            self.assertEqual((output / "final.mp4").read_bytes(), b"keep")
            filter_graph = commands[-1][commands[-1].index("-filter_complex") + 1]
            self.assertIn("volume=0.16", filter_graph)
            self.assertIn("loudnorm=I=-16", filter_graph)
            self.assertIn("concat=n=5", filter_graph)
            self.assertIn("ass=", filter_graph)
            metadata = json.loads((output / "metadata.json").read_text())
            self.assertEqual(metadata["voice"], "en-US-AriaNeural")
            self.assertEqual(metadata["rate"], "-2%")
            self.assertIn("automatic selection", metadata["selection_reason"])


if __name__ == "__main__":
    unittest.main()
