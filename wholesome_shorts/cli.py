from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from pathlib import Path

from .core import (ValidationError, export_episode, load_package, probe_duration,
                   resolve_ffmpeg, validate_clips, validate_package)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="wholesome-shorts", description="Local Shorts review exporter (no upload support)")
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
        maximum = float(config["production"]["max_scene_seconds"])
        ffmpeg = resolve_ffmpeg(args.ffmpeg)
        package = load_package(args.episode / "package.json")
        validate_package(package)
        validate_clips(args.episode, maximum,
                       probe=lambda path: probe_duration(path, ffmpeg=ffmpeg))
        if args.command == "validate":
            print("Package and exactly five clips are valid. No files were uploaded.")
            return 0
        destination = args.output or Path(config["paths"]["output"]) / args.episode.name
        final = export_episode(args.episode, destination, package, maximum, ffmpeg=ffmpeg)
        print(f"Local review export: {final}")
        return 0
    except (ValidationError, FileNotFoundError, KeyError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
