from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import asyncio
from dataclasses import dataclass
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
NARRATOR_VOICE = "en-US-AriaNeural"


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


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


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02d}:{centiseconds // 100 % 60:02d}.{centiseconds % 100:02d}"


def _caption_lines(words: list[str], max_chars: int = 28) -> str:
    """Wrap a short caption into no more than two frame-safe lines."""
    split = min(range(1, len(words) + 1), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    lines = [" ".join(words[:split]), " ".join(words[split:])]
    lines = [line for line in lines if line]
    if any(len(line) > max_chars for line in lines):
        raise ValidationError("A voice-over word is too long for the caption safe area")
    return r"\N".join(lines)


def write_ass(cues: list[SubtitleCue], path: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,2,90,90,500,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = [f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},Caption,,0,0,0,,{c.text}" for c in cues]
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


async def _edge_narration(text: str, audio_path: Path, voice: str = NARRATOR_VOICE) -> list[SubtitleCue]:
    """Synthesize narration and derive cue times from Edge TTS word boundaries."""
    import edge_tts

    boundaries: list[tuple[float, float, str]] = []
    with audio_path.open("wb") as audio:
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                boundaries.append((start, start + chunk["duration"] / 10_000_000, chunk["text"]))
    if not boundaries:
        raise ValidationError("Narration did not return synchronized word timing")
    cues: list[SubtitleCue] = []
    for index in range(0, len(boundaries), 7):
        group = boundaries[index:index + 7]
        end = boundaries[index + 7][0] if index + 7 < len(boundaries) else group[-1][1] + .15
        cues.append(SubtitleCue(group[0][0], end, _caption_lines([word[2] for word in group])))
    return cues


def generate_narration(text: str, audio_path: Path, voice: str = NARRATOR_VOICE) -> list[SubtitleCue]:
    return asyncio.run(_edge_narration(text, audio_path, voice))


def _ffmpeg_filter_path(path: Path) -> str:
    # FFmpeg's filter parser treats both drive colons and apostrophes specially.
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def export_episode(episode_dir: Path, output_dir: Path, package: dict[str, Any],
                   max_seconds: float = 8.0,
                   runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
                   ffmpeg: str | Path | None = None, narration: bool = True,
                   captions: bool = True,
                   narrator: Callable[[str, Path, str], list[SubtitleCue]] = generate_narration) -> Path:
    validate_package(package)
    executable = resolve_ffmpeg(ffmpeg)
    clips = validate_clips(episode_dir, max_seconds,
                           probe=lambda path: probe_duration(path, runner, executable))
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / "final_captioned.mp4"
    narration_file = output_dir / "narration.mp3"
    cues = narrator(package["voice_over"], narration_file, NARRATOR_VOICE) if narration or captions else []
    subtitle_file = output_dir / "captions.ass"
    if captions:
        write_ass(cues, subtitle_file)
    command = [executable, "-y"]
    for clip in clips:
        command.extend(["-i", str(clip)])
    filters = []
    for index in range(5):
        filters.append(
            f"[{index}:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=30,setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={max_seconds},trim=duration={max_seconds}[v{index}]"
        )
        filters.append(f"[{index}:a]apad=pad_dur={max_seconds},atrim=duration={max_seconds}[a{index}]")
    filters.append("".join(f"[v{i}][a{i}]" for i in range(5)) + "concat=n=5:v=1:a=1[vbase][abase]")
    video_label = "vbase"
    if captions:
        filters.append(f"[vbase]ass='{_ffmpeg_filter_path(subtitle_file)}'[vout]")
        video_label = "vout"
    if narration:
        command.extend(["-i", str(narration_file)])
        filters.extend(["[abase]volume=0.16[quiet]", "[5:a]loudnorm=I=-16:LRA=7:TP=-1.5[voice]",
                        "[quiet][voice]amix=inputs=2:duration=first:dropout_transition=0[aout]"])
        audio_label = "aout"
    else:
        filters.append("[abase]anull[aout]")
        audio_label = "aout"
    command.extend(["-filter_complex", ";".join(filters), "-map", f"[{video_label}]", "-map", f"[{audio_label}]",
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
