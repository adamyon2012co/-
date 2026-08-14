from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import Any, Callable

SCENES = tuple(f"scene_{number:02d}.mp4" for number in range(1, 6))
SAFEGUARDS = (
    "vertical 9:16", "stable identities", "no visible text", "no logos",
    "no watermarks", "no extra characters", "no morphing",
)
BANNED = (
    "copyrighted character", "celebrity", "brand logo", "politician",
    "medical cure", "weapon", "violence", "dangerous stunt", "child",
)


class ValidationError(ValueError):
    """Raised when an episode cannot safely be produced."""


def resolve_ffmpeg(explicit: str | Path | None = None) -> str:
    """Find FFmpeg without requiring a machine-wide Windows installation."""
    requested = str(explicit) if explicit else os.environ.get("FFMPEG_BINARY")
    if requested:
        resolved = shutil.which(requested)
        if resolved:
            return resolved
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        source = "--ffmpeg" if explicit else "FFMPEG_BINARY"
        raise FileNotFoundError(f"FFmpeg from {source} does not exist or is not executable: {requested}")
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise FileNotFoundError(
            "FFmpeg was not found via --ffmpeg, FFMPEG_BINARY, PATH, or imageio-ffmpeg"
        ) from error


def load_package(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def validate_package(package: dict[str, Any]) -> None:
    required = {"logline", "voice_over", "character_bible", "scenes", "titles",
                "description", "hashtags", "disclosure_note"}
    missing = sorted(required - package.keys())
    if missing:
        raise ValidationError(f"Missing package fields: {', '.join(missing)}")
    count = word_count(package["voice_over"])
    if not 50 <= count <= 70:
        raise ValidationError(f"Voice-over must be 50–70 words; found {count}")
    characters = package["character_bible"]
    if not characters or any(int(character.get("age", 0)) < 25 for character in characters):
        raise ValidationError("Every character must be an adult aged 25+")
    scenes = package["scenes"]
    if len(scenes) != 5 or [scene.get("number") for scene in scenes] != [1, 2, 3, 4, 5]:
        raise ValidationError("Exactly five numbered scene plans are required")
    plans = [scene.get("plan", "").strip().casefold() for scene in scenes]
    if any(not plan for plan in plans) or len(set(plans)) != 5:
        raise ValidationError("All five scene plans must be non-empty and distinct")
    twist = scenes[4].get("reinterpretation", {})
    if twist.get("earlier_scene") not in {1, 2, 3, 4} or not twist.get("meaning", "").strip():
        raise ValidationError("Scene 5 must meaningfully reinterpret an earlier scene")
    for scene in scenes:
        for field in ("keyframe_prompt", "motion_prompt"):
            prompt = scene.get(field, "").casefold()
            absent = [item for item in SAFEGUARDS if item not in prompt]
            if absent:
                raise ValidationError(f"Scene {scene['number']} {field} lacks: {', '.join(absent)}")
    if len(package["titles"]) != 3 or any(not title.strip() for title in package["titles"]):
        raise ValidationError("Exactly three honest, non-empty titles are required")
    searchable = json.dumps(package).casefold()
    found = [term for term in BANNED if term in searchable]
    if found:
        raise ValidationError(f"Package contains blocked safety terms: {', '.join(found)}")


def probe_duration(path: Path, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
                   ffmpeg: str | Path | None = None) -> float:
    # FFmpeg itself reports container duration, avoiding a separate ffprobe dependency.
    result = runner([resolve_ffmpeg(ffmpeg), "-hide_banner", "-i", str(path), "-f", "null", "-"],
                    capture_output=True, text=True, check=False)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValidationError(f"Could not determine duration of {path.name}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def validate_clips(episode_dir: Path, max_seconds: float = 8.0,
                   probe: Callable[[Path], float] = probe_duration) -> list[Path]:
    expected = [episode_dir / name for name in SCENES]
    missing = [path.name for path in expected if not path.is_file()]
    if missing:
        raise ValidationError(f"Missing input clips: {', '.join(missing)}")
    unexpected = sorted(path.name for path in episode_dir.glob("scene_*.mp4") if path not in expected)
    if unexpected:
        raise ValidationError(f"Unexpected scene clips (exactly five allowed): {', '.join(unexpected)}")
    for path in expected:
        duration = probe(path)
        if duration <= 0 or duration > max_seconds + 0.001:
            raise ValidationError(f"{path.name} is {duration:.3f}s; allowed range is >0 to {max_seconds}s")
    return expected


def export_episode(episode_dir: Path, output_dir: Path, package: dict[str, Any],
                   max_seconds: float = 8.0,
                   runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
                   ffmpeg: str | Path | None = None) -> Path:
    validate_package(package)
    executable = resolve_ffmpeg(ffmpeg)
    clips = validate_clips(episode_dir, max_seconds,
                           probe=lambda path: probe_duration(path, runner, executable))
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / "final.mp4"
    command = [executable, "-y"]
    for clip in clips:
        command.extend(["-i", str(clip)])
    filters = []
    for index in range(5):
        filters.append(
            f"[{index}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=30,setsar=1[v{index}]"
        )
    filters.append("".join(f"[v{i}][{i}:a]" for i in range(5)) + "concat=n=5:v=1:a=1[v][a]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac",
                    "-movflags", "+faststart", str(final)])
    runner(command, check=True)
    (output_dir / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    (output_dir / "metadata.txt").write_text(
        f"TITLE OPTIONS\n" + "\n".join(f"- {title}" for title in package["titles"]) +
        f"\n\nDESCRIPTION\n{package['description']}\n\nHASHTAGS\n{' '.join(package['hashtags'])}"
        f"\n\nDISCLOSURE\n{package['disclosure_note']}\n", encoding="utf-8")
    return final


def youtube_api_key_is_configured() -> bool:
    """Check presence without reading from files or exposing the value."""
    return bool(os.environ.get("YOUTUBE_API_KEY"))
