import os
import re
import uuid
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path("/app/data")
VIDEOS = BASE / "videos"
CLIPS = BASE / "clips"
VIDEOS.mkdir(parents=True, exist_ok=True)
CLIPS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="NIMH Set-to-Trial-Reel Engine")
app.mount("/static", StaticFiles(directory="/app/app/static"), name="static")
app.mount("/media", StaticFiles(directory=str(CLIPS)), name="media")


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-4000:])
    return p.stdout


def safe_title(s):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-")[:80] or "nimh-set"


def download_set(url: str, job: Path):
    out = job / "source.%(ext)s"
    run([
        "yt-dlp", "--no-playlist", "--merge-output-format", "mp4",
        "-f", "bv*+ba/b", "-o", str(out), url
    ])
    mp4s = list(job.glob("source*.mp4"))
    if not mp4s:
        raise RuntimeError("The YouTube video could not be downloaded.")
    return mp4s[0]


def duration(path):
    return float(run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]).strip())


def audio_energy(path, seconds=90):
    wav = path.with_suffix(".wav")
    run([
        "ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
        "-t", str(seconds), "-f", "wav", str(wav)
    ])
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(wav), "-f", "s16le", "-acodec", "pcm_s16le", "-"
    ])
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if len(x) < 8000:
        return []
    frame = 8000 * 2
    vals = []
    for i in range(0, len(x)-frame, frame):
        rms = float(np.sqrt(np.mean(x[i:i+frame] ** 2)))
        vals.append((i / 8000.0, rms))
    wav.unlink(missing_ok=True)
    return vals


def make_clip(source, start, length, out):
    # Crop the centre 9:16 region and scale to 1080x1920.
    vf = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    run([
        "ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(source),
        "-t", f"{length:.2f}", "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)
    ])


def generate_candidates(source, job_id, count=10):
    dur = duration(source)
    # Scan the first 90 minutes, or the whole set if shorter.
    scan = min(dur, 90 * 60)
    vals = audio_energy(source, seconds=scan)
    if not vals:
        return []

    arr = np.array([v for _, v in vals], dtype=float)
    # Rank high-energy frames while enforcing spacing between picks.
    picks = []
    for idx in np.argsort(arr)[::-1]:
        t = vals[int(idx)][0]
        start = max(0.0, t - 10.0)
        if start + 30 > dur:
            start = max(0.0, dur - 30)
        if all(abs(start - p[0]) > 45 for p in picks):
            picks.append((start, float(arr[int(idx)])))
        if len(picks) >= count:
            break

    peak = max(arr) if len(arr) else 1.0
    results = []
    for rank, (start, score) in enumerate(picks, 1):
        cid = f"{job_id}-{rank:02d}"
        out = CLIPS / f"{cid}.mp4"
        make_clip(source, start, 30, out)
        results.append({
            "id": cid,
            "start": round(start, 1),
            "duration": 30,
            "score": round(min(100, score / peak * 100), 1),
            "url": f"/media/{cid}.mp4"
        })
    return results


@app.get("/", response_class=HTMLResponse)
def home():
    return Path("/app/app/static/index.html").read_text()


@app.post("/api/generate")
def generate(url: str = Form(...), count: int = Form(10)):
    if "youtube.com" not in url and "youtu.be" not in url:
        return JSONResponse({"error": "Please paste a YouTube URL."}, status_code=400)
    job_id = uuid.uuid4().hex[:10]
    job = VIDEOS / job_id
    job.mkdir(parents=True)
    try:
        source = download_set(url, job)
        clips = generate_candidates(source, job_id, max(3, min(count, 20)))
        return {"job_id": job_id, "clips": clips}
    except Exception as e:
        shutil.rmtree(job, ignore_errors=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/clip/{clip_id}")
def clip(clip_id: str):
    path = CLIPS / f"{clip_id}.mp4"
    if not path.exists():
        return JSONResponse({"error": "Clip not found"}, status_code=404)
    return FileResponse(path, media_type="video/mp4", filename=path.name)
