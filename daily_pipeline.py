from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from wholesome_shorts.core import SCENES, ValidationError, validate_package

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.toml"


def settings() -> dict:
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    return data.get("automation", {})


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Ollama did not return a JSON object")
    return json.loads(text[start : end + 1])


def agent_prompt() -> str:
    return """Create ONE original English wholesome visual micro-story for a YouTube Short.
Return JSON only. Requirements: 50-70 word voice_over; exactly two adult characters aged 25+;
exactly five numbered scenes; each scene has distinct plan, detailed keyframe_prompt and motion_prompt;
scene 5 reinterprets one earlier scene. Every visual prompt must literally include: vertical 9:16,
stable identities, no visible text, no logos, no watermarks, no extra characters, no morphing.
Avoid celebrities, brands, copyrighted characters, politics, medical claims, violence, dangerous acts,
children and claims that the fictional event is real. Include three titles, description, 3-5 hashtags,
disclosure_note, tone, genre, mood, made_for_kids=false, contains_synthetic_media=true,
youtube_category="22". Use this exact top-level shape:
{logline, tone, genre, mood, voice_over, character_bible:[{name,age,appearance,temperament}],
scenes:[{number,plan,keyframe_prompt,motion_prompt,reinterpretation?}], titles:[...], description,
hashtags:[...], disclosure_note, made_for_kids, contains_synthetic_media, youtube_category}.
"""


def write_flow_handoff(folder: Path, package: dict) -> None:
    lines = [
        f"# Flow handoff: {folder.name}", "",
        "Create one 8-second vertical clip per scene. Use the image prompt first, then the motion prompt.",
        "Download and name the results exactly scene_01.mp4 through scene_05.mp4.", "",
    ]
    for scene in package["scenes"]:
        lines += [f"## Scene {scene['number']}", "", "Image prompt:",
                  scene["keyframe_prompt"], "", "Motion prompt:",
                  scene["motion_prompt"], ""]
    (folder / "READY_FOR_FLOW.md").write_text("\n".join(lines), encoding="utf-8")


def plan_next() -> Path:
    cfg = settings()
    model = str(cfg.get("ollama_model", "qwen3:4b"))
    episodes = ROOT / "episodes"
    episodes.mkdir(exist_ok=True)
    last_error = ""
    for attempt in range(1, 4):
        result = subprocess.run(
            ["ollama", "run", model, agent_prompt()], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Ollama failed")
        try:
            package = extract_json(result.stdout)
            validate_package(package)
            slug = datetime.now().strftime("episode_%Y_%m_%d_%H%M")
            folder = episodes / slug
            folder.mkdir(exist_ok=False)
            (folder / "package.json").write_text(
                json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            write_flow_handoff(folder, package)
            print(f"READY_FOR_FLOW: {folder}")
            return folder
        except (ValueError, json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            print(f"Agent attempt {attempt}/3 rejected: {last_error}", file=sys.stderr)
    raise RuntimeError(f"Agent could not create a valid package: {last_error}")


def pending_episode() -> Path | None:
    episodes = ROOT / "episodes"
    candidates = sorted(
        folder for folder in episodes.glob("episode_*")
        if folder.is_dir() and (folder / "package.json").is_file()
    )
    for folder in candidates:
        marker = ROOT / "output" / folder.name / "youtube_upload.json"
        if not marker.exists():
            return folder
    return None


def missing_scenes(folder: Path) -> list[str]:
    return [name for name in SCENES if not (folder / name).is_file()]


def ensure_disk_space(minimum_mb: int) -> None:
    free_mb = shutil.disk_usage(ROOT).free // (1024 * 1024)
    if free_mb < minimum_mb:
        raise RuntimeError(f"Only {free_mb} MB free; at least {minimum_mb} MB is required")


def run_once() -> int:
    cfg = settings()
    if not bool(cfg.get("automation_enabled", False)):
        print("STOPPED: automation_enabled is false in config.toml")
        return 2
    ensure_disk_space(int(cfg.get("minimum_free_mb", 1500)))
    folder = pending_episode() or plan_next()
    missing = missing_scenes(folder)
    if missing:
        print(f"WAITING_FOR_FLOW: {folder}")
        print("Missing:", ", ".join(missing))
        return 10
    output = ROOT / "output" / folder.name
    base = [sys.executable, "-m", "wholesome_shorts.cli", "--config", str(CONFIG)]
    run(base + ["validate", str(folder)])
    run(base + ["export", str(folder), "--output", str(output)])
    run(base + ["upload", str(folder), "--output", str(output), "--dry-run"])
    if not bool(cfg.get("publish_enabled", False)):
        print(f"READY_TO_UPLOAD: {output / 'final_captioned.mp4'}")
        return 0
    command = base + ["upload", str(folder), "--output", str(output),
                      "--client-secrets", str(ROOT / cfg.get("client_secrets", "client_secret.json")),
                      "--token-file", str(ROOT / cfg.get("token_file", "token.json"))]
    if bool(cfg.get("public_upload", False)):
        command.append("--publish")
    run(command)
    return 0


def status() -> int:
    cfg = settings()
    folder = pending_episode()
    print(f"automation_enabled={bool(cfg.get('automation_enabled', False))}")
    print(f"publish_enabled={bool(cfg.get('publish_enabled', False))}")
    if not folder:
        print("next=plan a new episode")
    elif missing_scenes(folder):
        print(f"next=finish Flow clips in {folder}")
        print("missing=" + ",".join(missing_scenes(folder)))
    else:
        print(f"next=validate/export/upload {folder}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed daily Shorts pipeline")
    parser.add_argument("command", choices=("plan-next", "run-once", "status"))
    args = parser.parse_args()
    try:
        return {"plan-next": lambda: (plan_next(), 0)[1],
                "run-once": run_once, "status": status}[args.command]()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
