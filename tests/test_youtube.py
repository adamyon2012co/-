import json
import socket
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from wholesome_shorts.youtube import UploadError, generate_upload_metadata, upload_video

ROOT = Path(__file__).parents[1]


class YouTubeUploadTests(unittest.TestCase):
    def setUp(self):
        self.package = json.loads((ROOT / "examples/bicycle_kindness/package.json").read_text(encoding="utf-8"))

    def _output(self, root: str) -> Path:
        output = Path(root) / "output"
        output.mkdir()
        (output / "final_captioned.mp4").write_bytes(b"video")
        (output / "package.json").write_text(json.dumps(self.package), encoding="utf-8")
        (output / "metadata.json").write_text("{}", encoding="utf-8")
        (output / "export_complete.json").write_text(
            json.dumps({"video": "final_captioned.mp4"}), encoding="utf-8")
        return output

    def test_generates_english_metadata_disclosure_and_at_most_three_hashtags(self):
        metadata = generate_upload_metadata(self.package)
        self.assertEqual(metadata["title"], self.package["titles"][0])
        self.assertLessEqual(len(metadata["title"]), 100)
        self.assertIn("Visuals and narration were AI-assisted.", metadata["description"])
        self.assertEqual(metadata["hashtags"], self.package["hashtags"][:3])
        self.assertEqual(metadata["privacy_status"], "private")
        self.assertTrue(metadata["contains_synthetic_media"])

    def test_publish_explicitly_requests_public(self):
        self.assertEqual(generate_upload_metadata(self.package, publish=True)["privacy_status"], "public")

    def test_missing_made_for_kids_is_rejected(self):
        package = deepcopy(self.package)
        package.pop("made_for_kids")
        with self.assertRaisesRegex(UploadError, "made_for_kids"):
            generate_upload_metadata(package)

    @patch("wholesome_shorts.youtube.authorize", return_value=Mock())
    def test_resumable_upload_writes_metadata_and_duplicate_marker(self, _authorize):
        with tempfile.TemporaryDirectory() as directory:
            output = self._output(directory)
            request = Mock()
            request.next_chunk.side_effect = [
                (Mock(), None),
                (None, {"id": "abc123", "status": {"privacyStatus": "private"}}),
            ]
            service = Mock()
            service.videos.return_value.insert.return_value = request
            result = upload_video(output, self.package, service_builder=Mock(return_value=service),
                                  media_upload_factory=Mock(return_value=Mock()))
            self.assertEqual(result.video_id, "abc123")
            inserted = service.videos.return_value.insert.call_args.kwargs
            self.assertEqual(inserted["body"]["status"]["privacyStatus"], "private")
            self.assertFalse(inserted["body"]["status"]["selfDeclaredMadeForKids"])
            self.assertTrue(inserted["body"]["status"]["containsSyntheticMedia"])
            self.assertTrue((output / "youtube_metadata.json").is_file())
            self.assertEqual(json.loads((output / "youtube_upload.json").read_text())["video_id"], "abc123")
            with self.assertRaisesRegex(UploadError, "already uploaded"):
                upload_video(output, self.package, dry_run=True)

    @patch("wholesome_shorts.youtube.authorize", return_value=Mock())
    def test_reports_when_unverified_project_forces_public_request_private(self, _authorize):
        with tempfile.TemporaryDirectory() as directory:
            output = self._output(directory)
            request = Mock()
            request.next_chunk.return_value = (None, {"id": "forced", "status": {"privacyStatus": "private"}})
            service = Mock()
            service.videos.return_value.insert.return_value = request
            result = upload_video(output, self.package, publish=True,
                                  service_builder=Mock(return_value=service),
                                  media_upload_factory=Mock(return_value=Mock()))
            self.assertTrue(result.forced_private)

    @patch("wholesome_shorts.youtube.authorize")
    def test_dry_run_writes_metadata_without_authorizing(self, authorize):
        with tempfile.TemporaryDirectory() as directory:
            output = self._output(directory)
            self.assertIsNone(upload_video(output, self.package, dry_run=True))
            authorize.assert_not_called()
            self.assertTrue((output / "youtube_metadata.json").is_file())

    def test_missing_or_stale_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "final_captioned.mp4").write_bytes(b"video")
            with self.assertRaisesRegex(UploadError, "completion files"):
                upload_video(output, self.package, dry_run=True)
        with tempfile.TemporaryDirectory() as directory:
            output = self._output(directory)
            changed = deepcopy(self.package)
            changed["description"] += " changed"
            with self.assertRaisesRegex(UploadError, "changed after export"):
                upload_video(output, changed, dry_run=True)

    @patch("wholesome_shorts.youtube.authorize", return_value=Mock())
    def test_temporary_network_failure_is_retried(self, _authorize):
        with tempfile.TemporaryDirectory() as directory:
            output = self._output(directory)
            request = Mock()
            request.next_chunk.side_effect = [
                socket.timeout("temporary"),
                (None, {"id": "retry-id", "status": {"privacyStatus": "private"}}),
            ]
            service = Mock()
            service.videos.return_value.insert.return_value = request
            sleeper = Mock()
            result = upload_video(output, self.package, service_builder=Mock(return_value=service),
                                  media_upload_factory=Mock(return_value=Mock()), sleeper=sleeper)
            self.assertEqual(result.video_id, "retry-id")
            sleeper.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
