from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from pathlib import Path

from .core import (ValidationError, export_episode, load_package, probe_duration,
                   resolve_ffmpeg, validate_clips, validate_package)
from .youtube import DEFAULT_TOKEN_FILE, UploadError, upload_video


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="wholesome-shorts", description="Local Shorts exporter with safe private YouTube uploads")
    result.add_argument("--config", type=Path, default=Path("config.toml"))
    result.add_argument("--ffmpeg", help="FFmpeg executable path (before env, PATH, and bundled fallback)")
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create an episode folder and editable package")
    init.add_argument("episode", type=Path)
    init.add_argument("--from-example", type=Path, default=Path("examples/bicycle_kindness/package.json"))
    check = sub.add_parser("validate", help="validate package and five local clips")
    check.add_argument("episode", type=Path)
    build = sub.add_parser("export", help="create final MP4 and metadata locally")
    build.add_argument("episode", type=Path)
    build.add_argument("--output", type=Path)
    build.add_argument("--no-narration", action="store_true", help="keep only the clips' original audio")
    build.add_argument("--no-captions", action="store_true", help="do not burn captions into the video")
    upload = sub.add_parser("upload", help="upload an exported Short privately to YouTube")
    upload.add_argument("episode", type=Path, help="episode folder containing package.json")
    upload.add_argument("--output", type=Path, help="export folder containing final_captioned.mp4")
    upload.add_argument("--client-secrets", type=Path, default=Path("client_secret.json"))
    upload.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    upload.add_argument("--dry-run", action="store_true", help="validate video and metadata without OAuth or upload")
    upload.add_argument("--publish", action="store_true", help="explicitly request public visibility")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            args.episode.mkdir(parents=True, exist_ok=False)
            shutil.copyfile(args.from_example, args.episode / "package.json")
            print(f"Created {args.episode}. Add scene_01.mp4 through scene_05.mp4, then edit package.json.")
            return 0
        config = tomllib.loads(args.config.read_text(encoding="utf-8"))
        package = load_package(args.episode / "package.json")
        validate_package(package)
        destination = args.output or Path(config["paths"]["output"]) / args.episode.name
        if args.command == "upload":
            result = upload_video(destination, package, client_secrets=args.client_secrets,
                                  token_file=args.token_file, dry_run=args.dry_run,
                                  publish=args.publish)
            if args.dry_run:
                print("Upload validation passed. No OAuth authorization or upload was performed.")
            else:
                print(f"Uploaded: https://www.youtube.com/watch?v={result.video_id}")
                if result.forced_private:
                    print("YouTube kept this upload private. API projects created after July 28, 2020 "
                          "must pass a YouTube audit before API uploads can be public.")
                else:
                    print(f"Visibility: {result.actual_privacy}")
            return 0
        maximum = float(config["production"]["max_scene_seconds"])
        ffmpeg = resolve_ffmpeg(args.ffmpeg)
        validate_clips(args.episode, maximum,
                       probe=lambda path: probe_duration(path, ffmpeg=ffmpeg))
        if args.command == "validate":
            print("Package and exactly five clips are valid. No files were uploaded.")
            return 0
        final = export_episode(args.episode, destination, package, maximum, ffmpeg=ffmpeg,
                               narration=not args.no_narration, captions=not args.no_captions)
        print(f"Local review export: {final}")
        return 0
    except (ValidationError, UploadError, FileNotFoundError, KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
