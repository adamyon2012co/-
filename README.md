> **Daily production:** use [DAILY_WORKFLOW.md](DAILY_WORKFLOW.md) and `python daily_pipeline.py status`. The local agent prepares five image/motion prompts, then waits safely for the five manual Google Flow clips before export or upload. Publishing is disabled by default.

# Wholesome Shorts local production workflow

A safe Python CLI for producing **original English wholesome micro-stories with a meaningful visual twist**. It validates a complete creative package and exactly five manually supplied MP4 scenes, uses FFmpeg to create a reviewable local vertical MP4, and can upload an approved export to YouTube as **private only**.

The included bicycle-kindness pilot is the repository's quality reference. It contains a logline, 50–70-word voice-over, adult character bible, five distinct plans, keyframe and image-to-video prompts, honest titles, description, hashtags, and disclosure. Copy it, then create an original variation rather than presenting the pilot as a real event.

## Safety and privacy

- Every character must be at least 25. Avoid copyrighted characters, celebrities, brands, politics, medical claims, violence, dangerous activities, and child-directed framing.
- Every visual prompt must preserve the required 9:16/identity/no-text/no-logo/no-watermark/no-extra-character/no-morphing safeguards.
- Scene 5 must explicitly name scene 1–4 and explain how it reinterprets that action. Automated validation catches structural omissions; a human must still judge originality, distinctness, honesty, visual continuity, and whether the twist is genuinely meaningful.
- Upload authorization uses the official YouTube Data API v3, OAuth 2.0 Desktop App flow, and only the `https://www.googleapis.com/auth/youtube.upload` scope. The system browser opens for first-time consent.
- Uploads default to private. Public visibility is requested only with the explicit `--publish` flag; YouTube may force uploads from an unverified API project to remain private, which the CLI reports clearly.
- OAuth client files, saved tokens, `.env`, source videos, voice-over media, and outputs are ignored by Git. The refreshable token defaults to the per-user `~/.wholesome-shorts/token.json`, is written atomically, and is restricted to the current user where the operating system supports file modes.

## Prerequisites

- Python 3.11 or newer
- FFmpeg supplied by the installed `imageio-ffmpeg` dependency. A system installation is optional.
- An internet connection while `edge-tts` creates the English narration (no API key or paid account is required).
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

# Export narration, burned-in captions, and the finished 1080x1920 review video.
wholesome-shorts --config .\config.toml export .\episodes\my_episode --output .\output\my_episode

# Confirm the new file exists without replacing any earlier final.mp4.
Test-Path .\output\my_episode\final_captioned.mp4
Get-ChildItem .\output\my_episode
```

### Exact Windows PowerShell YouTube setup and private upload

1. In Google Cloud Console, create or select a project, enable **YouTube Data API v3**, configure its OAuth consent screen, and create an OAuth client with application type **Desktop app**. Download its JSON file. Do not paste secrets into `package.json`, source code, or a commit.
2. Save the downloaded file locally as `client_secret.json` in the repository root. That filename and other common OAuth/token filenames are covered by `.gitignore`. The file is local input only and is never supplied by this repository.
3. Add the required audience and synthetic-media declarations to the episode's `package.json`. The uploader generates the English title, description, tags, and up to three hashtags from the existing reviewed `titles`, `description`, `hashtags`, `genre`, and `mood` fields:

```json
"made_for_kids": false,
"contains_synthetic_media": true,
"youtube_category": "22"
```

After exporting, run these exact commands from the activated virtual environment:

```powershell
# Validate without opening a browser, reading credentials, contacting YouTube, or uploading.
wholesome-shorts --config .\config.toml upload .\episodes\my_episode --output .\output\my_episode --dry-run

# Authorize once in the system browser and upload with resumable transfer.
wholesome-shorts --config .\config.toml upload .\episodes\my_episode --output .\output\my_episode --client-secrets .\client_secret.json

# Only this explicit flag requests public visibility. Without it, uploads are private.
wholesome-shorts --config .\config.toml upload .\episodes\my_episode --output .\output\my_episode --client-secrets .\client_secret.json --publish
```

The browser authorization saves the refreshable token at `$HOME\.wholesome-shorts\token.json`; later uploads reuse and refresh it. To choose another secure, user-owned location, add `--token-file "$HOME\secure\youtube-token.json"`. Never add any client or token file to Git. Before OAuth, the validated generated copy (including the AI-assistance disclosure) is saved to `output\my_episode\youtube_metadata.json`. Temporary failures are retried with exponential backoff. Success prints the `https://www.youtube.com/watch?v=...` URL and atomically records the returned ID in `output\my_episode\youtube_upload.json`; that marker blocks accidental duplicates. The uploader requires the export completion marker and rejects a package changed since export, so a failed or stale final export cannot be uploaded.

The exporter automatically chooses **one voice for the entire episode** from the approved English Edge TTS set: `en-US-GuyNeural`, `en-US-JennyNeural`, `en-US-AriaNeural`, and `en-US-DavisNeural`. It considers `voice_over` plus optional `tone`, `genre`, and `mood` package fields, then applies a deliberately restrained speaking rate and pitch suited to signals such as warm/reflective, upbeat/playful, tense/mysterious, or dramatic/energetic. If selection fails, it uses `en-US-GuyNeural`.

To choose explicitly, add an approved voice to `package.json`, for example `"voice": "en-US-DavisNeural"`. An unapproved override safely falls back to `en-US-GuyNeural`. The output `metadata.json` records `voice`, `rate`, `pitch`, and a human-readable `selection_reason`, along with the publishing copy. Word-boundary events from that exact voice/rate/pitch synthesis request drive the two-line captions, so captions remain synchronized with the selected narration; narration is normalized and the clips remain audible at a reduced level. To disable either feature independently, run one of these exact commands:

```powershell
wholesome-shorts --config .\config.toml export .\episodes\my_episode --output .\output\my_episode --no-narration
wholesome-shorts --config .\config.toml export .\episodes\my_episode --output .\output\my_episode --no-captions
wholesome-shorts --config .\config.toml export .\episodes\my_episode --output .\output\my_episode --no-narration --no-captions
```

Resolution order is `--ffmpeg`, `$env:FFMPEG_BINARY`, `ffmpeg` on `PATH`, then the binary installed by `imageio-ffmpeg`. To select a portable executable explicitly in PowerShell:

```powershell
wholesome-shorts --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" --config .\config.toml validate .\episodes\my_episode
wholesome-shorts --ffmpeg "C:\Tools\ffmpeg\bin\ffmpeg.exe" --config .\config.toml export .\episodes\my_episode --output .\output\my_episode
```

If PowerShell blocks activation, use `.\.venv\Scripts\python -m wholesome_shorts.cli ...` instead of changing machine policy. Do **not** put API keys or OAuth secrets in `config.toml`; an API key cannot authorize uploads.

### Windows narration timing troubleshooting

Some Edge service responses (including those seen with `edge-tts` 7.2.8 on Windows) contain valid audio but no `WordBoundary` events. Older exporter versions stopped with `Narration did not return synchronized word timing` even though the equivalent `edge-tts --write-media ... --write-subtitles ...` command succeeded. The exporter now writes audio and collects word boundaries from the same streaming request. If that request contains audio but no boundaries, it uses the resolved FFmpeg binary to measure the MP3 and deterministically distributes the voice-over words across its duration for captions. An empty audio response still fails rather than producing a silent export.

If the fallback cannot inspect the MP3, confirm the resolved binary with `python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`, or provide a working binary through `--ffmpeg` or `$env:FFMPEG_BINARY`. Re-run the export; a separately generated `tts_test.mp3`/`tts_test.srt` is not required.

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

The output folder contains `final_captioned.mp4` (and never overwrites a pre-existing `final.mp4`), the validated `package.json`, narration/caption working files, creator-friendly `metadata.txt`, and machine-readable `metadata.json` including the narration choice. Review the result locally before manually using any platform. The exporter keeps all five scenes in filename order, normalizes visuals to 1080×1920 at 30 fps, letterboxes rather than crops, and pads each short clip's final frame and audio to the configured eight-second scene length for a roughly 40-second Short. `config.toml` controls the local episode/output paths and duration settings; safety invariants remain enforced by the application. The separate `upload` command is the only external-account action. It defaults to private and requires `--publish` to request public visibility.

## Tests

```bash
python -m unittest discover -s tests -v
```

Unit tests do not require network access; narration and YouTube API calls are mocked. A real narrated export requires FFmpeg, internet access to the free Edge speech service, and five user-created clips.
The integration test creates five colored clips, exports them, verifies 1080×1920 dimensions, and samples the center pixel of each segment to prove red, green, blue, yellow, and magenta scene order. It is skipped only when no usable FFmpeg binary can be resolved.
