# Wholesome Shorts local production workflow

A safe, dependency-light Python CLI for producing **original English wholesome micro-stories with a meaningful visual twist**. It validates a complete creative package and exactly five manually supplied MP4 scenes, then uses FFmpeg to create a reviewable local vertical MP4. It deliberately has **no upload or publishing feature**.

The included bicycle-kindness pilot is the repository's quality reference. It contains a logline, 50–70-word voice-over, adult character bible, five distinct plans, keyframe and image-to-video prompts, honest titles, description, hashtags, and disclosure. Copy it, then create an original variation rather than presenting the pilot as a real event.

## Safety and privacy

- Every character must be at least 25. Avoid copyrighted characters, celebrities, brands, politics, medical claims, violence, dangerous activities, and child-directed framing.
- Every visual prompt must preserve the required 9:16/identity/no-text/no-logo/no-watermark/no-extra-character/no-morphing safeguards.
- Scene 5 must explicitly name scene 1–4 and explain how it reinterprets that action. Automated validation catches structural omissions; a human must still judge originality, distinctness, honesty, visual continuity, and whether the twist is genuinely meaningful.
- `YOUTUBE_API_KEY` is only checked from the process environment, is never displayed, and is not needed. `.env`, source videos, voice-over media, and outputs are ignored by Git. There is no YouTube API or network code.

## Prerequisites

- Python 3.11 or newer
- FFmpeg supplied by the installed `imageio-ffmpeg` dependency. A system installation is optional.
- Five clips named **exactly** `scene_01.mp4` through `scene_05.mp4`; each must be longer than zero and no more than 8 seconds. Clips should contain an audio stream (silence is acceptable) for the current concat exporter.

## Windows setup (PowerShell)

1. Install Python from python.org, enabling **Add Python to PATH**.
2. From this repository, run these exact commands; `pip install -e .` installs a private FFmpeg binary through `imageio-ffmpeg`, so no system-wide FFmpeg setup is required:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
wholesome-shorts init episodes\my_episode
```

Edit `episodes\my_episode\package.json`; manually place the five scene files there. Then:

```powershell
# Confirm that exactly five expected clips exist before validation.
Get-ChildItem .\episodes\my_episode\scene_*.mp4 | Sort-Object Name | Select-Object Name, Length

# Validate package structure, clip names, and the eight-second limit.
wholesome-shorts --config .\config.toml validate .\episodes\my_episode

# Export the finished 1080x1920 review video and metadata locally.
wholesome-shorts --config .\config.toml export .\episodes\my_episode --output .\output\my_episode

# Inspect the generated files. Playback or file Properties can confirm dimensions.
Get-ChildItem .\output\my_episode
```

Resolution order is `--ffmpeg`, `$env:FFMPEG_BINARY`, `ffmpeg` on `PATH`, then the binary installed by `imageio-ffmpeg`. To select a portable executable explicitly in PowerShell:

```powershell
wholesome-shorts --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" --config .\config.toml validate .\episodes\my_episode
wholesome-shorts --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" --config .\config.toml export .\episodes\my_episode --output .\output\my_episode
```

If PowerShell blocks activation, use `.\.venv\Scripts\python -m wholesome_shorts.cli ...` instead of changing machine policy. Do **not** put API keys in `config.toml`. If a future local integration needs the key, set it only for the current process with `$env:YOUTUBE_API_KEY = "..."`; this version never uploads.

## macOS/Linux setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
wholesome-shorts init episodes/my_episode
# Edit package.json and manually add scene_01.mp4 ... scene_05.mp4
wholesome-shorts validate episodes/my_episode
wholesome-shorts export episodes/my_episode
```

The output folder contains `final.mp4`, the validated `package.json`, and creator-friendly `metadata.txt`. Review all three locally before manually using any platform. The exporter normalizes visuals to 1080×1920 at 30 fps, letterboxing rather than cropping. `config.toml` controls the local episode/output paths and duration settings; safety invariants remain enforced by the application.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests do not require real video or network access. A real export requires FFmpeg and five user-created clips.
The integration test creates five colored clips, exports them, verifies 1080×1920 dimensions, and samples the center pixel of each segment to prove red, green, blue, yellow, and magenta scene order. It is skipped only when no usable FFmpeg binary can be resolved.
