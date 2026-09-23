# NIMH Set-to-Trial-Reel Engine

A no-code-friendly web app for NotInMyHouze:
1. Paste a YouTube set URL.
2. Download the set.
3. Detect high-energy musical moments.
4. Generate vertical 9:16 clips.
5. Review and download clips.

## Important
Only process videos that NIMH owns or has permission to download and republish.

## Run
The intended deployment target is Railway. The app uses FFmpeg and yt-dlp inside the container.

## Current MVP
The clip-generation pipeline is implemented. Instagram publishing is deliberately left behind an integration boundary so that credentials/permissions are never hard-coded into the app. Connect an Instagram publishing/analytics provider before enabling automatic Trial Reel publishing.
