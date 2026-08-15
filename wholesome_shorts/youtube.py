"""Validated YouTube publishing for completed Shorts exports."""

from __future__ import annotations

import json
import os
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
DEFAULT_TOKEN_FILE = Path.home() / ".wholesome-shorts" / "token.json"
AI_DISCLOSURE = "Visuals and narration were AI-assisted."
MISLEADING_TITLE_PHRASES = ("you won't believe", "shocking truth", "100% real", "must see")


class UploadError(ValueError):
    """Raised when an upload cannot be performed safely."""


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    requested_privacy: str
    actual_privacy: str

    @property
    def forced_private(self) -> bool:
        return self.requested_privacy == "public" and self.actual_privacy == "private"


def _hashtags(package: dict[str, Any]) -> list[str]:
    values = package.get("hashtags", [])
    if not isinstance(values, list):
        raise UploadError("package hashtags must be a list")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r"#[A-Za-z0-9_]+", value):
            raise UploadError("Each publishing hashtag must start with # and contain only letters, numbers, or _")
        if value.casefold() not in {item.casefold() for item in result}:
            result.append(value)
    return result[:3]


def generate_upload_metadata(package: dict[str, Any], publish: bool = False) -> dict[str, Any]:
    """Generate English publishing metadata from the validated creative package."""
    titles = package.get("titles")
    title = titles[0].strip() if isinstance(titles, list) and titles and isinstance(titles[0], str) else ""
    if not title or len(title) > 100:
        raise UploadError("Generated YouTube title must be non-empty and at most 100 characters")
    if not re.search(r"[A-Za-z]", title):
        raise UploadError("Generated YouTube title must be in English")
    if any(phrase in title.casefold() for phrase in MISLEADING_TITLE_PHRASES):
        raise UploadError("Generated YouTube title contains misleading clickbait language")
    # Selecting an already-reviewed title option keeps the title tied to the story
    # instead of inventing claims that are absent from the package.
    if title not in titles:
        raise UploadError("Generated title must be one of the package's reviewed title options")

    description = package.get("description")
    if not isinstance(description, str) or not description.strip():
        raise UploadError("package description must be a non-empty English string")
    if not re.search(r"[A-Za-z]", description):
        raise UploadError("Generated YouTube description must be in English")
    hashtags = _hashtags(package)
    description_parts = [description.strip(), AI_DISCLOSURE]
    if hashtags:
        description_parts.append(" ".join(hashtags))
    generated_description = "\n\n".join(description_parts)
    if len(generated_description) > 5000:
        raise UploadError("Generated YouTube description exceeds 5,000 characters")

    made_for_kids = package.get("made_for_kids")
    if not isinstance(made_for_kids, bool):
        raise UploadError("package.json must define made_for_kids as true or false")
    contains_synthetic_media = package.get("contains_synthetic_media")
    if not isinstance(contains_synthetic_media, bool):
        raise UploadError("package.json must define contains_synthetic_media as true or false")
    category = package.get("youtube_category")
    if not isinstance(category, (str, int)) or not str(category).isdigit():
        raise UploadError("package.json must define youtube_category as a numeric category ID")
    tags = [tag.removeprefix("#") for tag in package.get("hashtags", [])]
    tags.extend(str(package.get(field, "")).strip() for field in ("genre", "mood"))
    tags = list(dict.fromkeys(tag for tag in tags if tag))
    return {
        "title": title,
        "description": generated_description,
        "tags": tags,
        "hashtags": hashtags,
        "category": str(category),
        "privacy_status": "public" if publish else "private",
        "made_for_kids": made_for_kids,
        "contains_synthetic_media": contains_synthetic_media,
        "ai_disclosure": AI_DISCLOSURE,
    }


def validate_upload(output_dir: Path, package: dict[str, Any], publish: bool = False) -> tuple[Path, Path, dict[str, Any]]:
    video = output_dir / "final_captioned.mp4"
    marker = output_dir / "youtube_upload.json"
    exported_package = output_dir / "package.json"
    export_metadata = output_dir / "metadata.json"
    completion_marker = output_dir / "export_complete.json"
    if not video.is_file() or video.stat().st_size == 0:
        raise UploadError(f"Upload video is missing or empty: {video}")
    if not exported_package.is_file() or not export_metadata.is_file() or not completion_marker.is_file():
        raise UploadError("Export completion files are missing; run a successful final export before uploading")
    try:
        completed_package = json.loads(exported_package.read_text(encoding="utf-8"))
        json.loads(export_metadata.read_text(encoding="utf-8"))
        completion = json.loads(completion_marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UploadError("Export completion files are invalid; re-run the final export") from error
    if completed_package != package:
        raise UploadError("package.json changed after export; re-export before uploading")
    if completion.get("video") != video.name:
        raise UploadError("Export completion marker does not match final_captioned.mp4")
    if marker.exists():
        try:
            video_id = json.loads(marker.read_text(encoding="utf-8"))["video_id"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise UploadError(f"Invalid duplicate-upload marker: {marker}") from error
        raise UploadError(f"This export was already uploaded as YouTube video {video_id}")
    return video, marker, generate_upload_metadata(package, publish)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _save_credentials(credentials: Any, token_file: Path) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = token_file.with_suffix(token_file.suffix + ".tmp")
    temporary.write_text(credentials.to_json(), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(token_file)
    os.chmod(token_file, 0o600)


def authorize(client_secrets: Path, token_file: Path = DEFAULT_TOKEN_FILE) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    if token_file.exists():
        credentials = Credentials.from_authorized_user_file(str(token_file), [YOUTUBE_UPLOAD_SCOPE])
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save_credentials(credentials, token_file)
    if not credentials or not credentials.valid:
        if not client_secrets.is_file():
            raise UploadError(f"OAuth Desktop App client file not found: {client_secrets}. Never commit it.")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), [YOUTUBE_UPLOAD_SCOPE])
        credentials = flow.run_local_server(port=0, open_browser=True)
        _save_credentials(credentials, token_file)
    return credentials


def upload_video(
    output_dir: Path, package: dict[str, Any], *, publish: bool = False,
    client_secrets: Path = Path("client_secret.json"), token_file: Path = DEFAULT_TOKEN_FILE,
    dry_run: bool = False, service_builder: Callable[..., Any] | None = None,
    media_upload_factory: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep, max_retries: int = 5,
) -> UploadResult | None:
    video, marker, metadata = validate_upload(output_dir, package, publish)
    _write_json_atomic(output_dir / "youtube_metadata.json", metadata)
    if dry_run:
        return None
    credentials = authorize(client_secrets, token_file)
    if service_builder is None or media_upload_factory is None:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
        builder, media_factory, http_error_types = service_builder or build, media_upload_factory or MediaFileUpload, (HttpError,)
    else:
        builder, media_factory, http_error_types = service_builder, media_upload_factory, ()
    youtube = builder("youtube", "v3", credentials=credentials, cache_discovery=False)
    body = {
        "snippet": {key: metadata[key] for key in ("title", "description", "tags")}
                   | {"categoryId": metadata["category"]},
        "status": {
            "privacyStatus": metadata["privacy_status"],
            "selfDeclaredMadeForKids": metadata["made_for_kids"],
            "containsSyntheticMedia": metadata["contains_synthetic_media"],
        },
    }
    media = media_factory(str(video), chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response, retries = None, 0
    retry_types = http_error_types + (OSError, socket.timeout)
    while response is None:
        try:
            _status, response = request.next_chunk()
            retries = 0
        except retry_types as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            if (isinstance(error, http_error_types) and status not in RETRIABLE_STATUS_CODES) or retries >= max_retries:
                raise UploadError(f"YouTube upload failed: {error}") from error
            sleeper(2 ** retries)
            retries += 1
    video_id = response.get("id") if isinstance(response, dict) else None
    actual_privacy = response.get("status", {}).get("privacyStatus") if isinstance(response, dict) else None
    if not video_id or actual_privacy not in {"private", "public", "unlisted"}:
        raise UploadError("YouTube response did not include a video ID and valid privacy status")
    result = UploadResult(str(video_id), metadata["privacy_status"], actual_privacy)
    _write_json_atomic(marker, {"video_id": result.video_id, "privacy_status": result.actual_privacy})
    return result
