# Daily workflow

This project now has one controller: `daily_pipeline.py`.

## What is automatic

1. Ollama creates one original package with five image and motion prompts.
2. The package is validated before it is saved.
3. A `READY_FOR_FLOW.md` handoff is created inside the episode folder.
4. After five correctly named clips exist, the controller validates and exports the Short.
5. YouTube metadata is validated. Upload happens only when publishing is explicitly enabled.

## What remains manual

Google Flow is the manual handoff. Open `READY_FOR_FLOW.md`, create the five image-to-video scenes, then save them in that episode folder as:

- `scene_01.mp4`
- `scene_02.mp4`
- `scene_03.mp4`
- `scene_04.mp4`
- `scene_05.mp4`

The controller never bypasses Google login, confirmation screens, quotas, or CAPTCHAs.

## First safe run

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python daily_pipeline.py status
python daily_pipeline.py plan-next
```

Complete the Flow handoff, then enable local processing by changing only this line in `config.toml`:

```toml
automation_enabled = true
```

Run:

```powershell
python daily_pipeline.py run-once
```

It will export and stop at `READY_TO_UPLOAD`. Review the finished Short.

## Enable upload only after review

When the correct YouTube token and channel have already been tested, change:

```toml
publish_enabled = true
public_upload = true
```

Keep `client_secret.json` and `token.json` local. They are ignored by Git.

## Daily scheduling

Run this once from PowerShell after the safe manual run succeeds:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_daily_task.ps1
```

The task runs at 19:30 each day. The computer must be on. If Flow clips are missing, it exits safely and waits for them instead of uploading an incomplete video.
