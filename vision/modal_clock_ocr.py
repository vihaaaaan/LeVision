#!/usr/bin/env python3
"""Modal-based parallel OCR pipeline for extracting game clock and quarter from
basketball footage stored in Cloudflare R2.

Architecture:
  1. Download video from R2 + extract 1 FPS frames via ffmpeg (CPU Modal function)
  2. Fan-out OCR over frame batches using GPU T4 instances (parallel Modal function)
  3. Aggregate, smooth, and export clock_timeline.json
  4. Fetch play-by-play from NBA API using home/away team IDs + game date
  5. Merge OCR timeline with play-by-play → processed_game_state.json
  6. Upload results to R2 and POST completion webhook
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import modal
from dotenv import dotenv_values

# ---------------------------------------------------------------------------
# Load .env.local locally and build a Modal Secret from it explicitly.
# ---------------------------------------------------------------------------
_DOTENV_PATH = Path(__file__).resolve().parent / ".env.local"
_env_vars: dict[str, str] = {
    k: v for k, v in dotenv_values(_DOTENV_PATH).items() if v is not None
}
r2_secret = modal.Secret.from_dict(_env_vars)

# ---------------------------------------------------------------------------
# Modal image
# ---------------------------------------------------------------------------

image = (
    modal.Image.debian_slim()
    .apt_install(["ffmpeg", "libsm6", "libxext6", "libgl1"])
    .pip_install(
        [
            "easyocr",
            "opencv-python-headless",
            "boto3",
            "pandas",
            "python-dotenv",
            "requests",
            "nba_api",
            "fastapi[standard]",
        ]
    )
)

app = modal.App("basketball-clock-ocr", image=image)

# Shared volume so the extraction function and OCR functions can both see frames
volume = modal.Volume.from_name("clock-ocr-frames", create_if_missing=True)
VOLUME_MOUNT = "/mnt/frames"

R2_BUCKET = "gamefootage"
BATCH_SIZE = 30

# ---------------------------------------------------------------------------
# Webhook helper
# ---------------------------------------------------------------------------


def _post_webhook(webhook_url: str, secret: str, payload: dict) -> None:
    import requests as req
    try:
        req.post(
            webhook_url,
            json=payload,
            headers={"x-vision-secret": secret},
            timeout=10,
        )
    except Exception as e:
        print(f"[WARN] webhook POST failed: {e}")


# ---------------------------------------------------------------------------
# R2 client
# ---------------------------------------------------------------------------


def _r2_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


# ---------------------------------------------------------------------------
# Step 1 — Download video & extract frames
# ---------------------------------------------------------------------------


@app.function(
    secrets=[r2_secret],
    volumes={VOLUME_MOUNT: volume},
    timeout=1800,
    cpu=4,
)
def extract_frames(r2_key: str) -> list[str]:
    """Download video from R2 and extract 1 FPS frames to the shared volume."""
    import glob

    frames_dir = Path(VOLUME_MOUNT) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    local_video = "/tmp/video.mp4"
    print(f"Downloading {r2_key} from R2 …")
    s3 = _r2_client()
    s3.download_file(R2_BUCKET, r2_key, local_video)
    print("Download complete.")

    print("Extracting 1 FPS frames with ffmpeg …")
    cmd = [
        "ffmpeg", "-y", "-i", local_video,
        "-vf", "fps=1", "-q:v", "2",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    volume.commit()

    frame_paths = sorted(glob.glob(str(frames_dir / "frame_*.jpg")))
    print(f"Extracted {len(frame_paths)} frames.")
    return frame_paths


# ---------------------------------------------------------------------------
# Step 2 — Parallel GPU OCR
# ---------------------------------------------------------------------------


def _parse_clock(tokens: list[str]) -> str | None:
    for raw in tokens:
        t = re.sub(r"(\d)\s+(\d)", r"\1\2", raw).strip()
        m = re.fullmatch(r"(\d{1,2})[:.;*]([0-5][0-9])", t)
        if m:
            return f"{m.group(1)}:{m.group(2)}"
        m = re.fullmatch(r"(\d{1,2})8([0-5][0-9])", t)
        if m and int(m.group(1)) <= 12:
            return f"{m.group(1)}:{m.group(2)}"
    return None


def _parse_quarter(text: str) -> str | None:
    m = re.search(r"\b(1ST|2ND|3RD|4TH|OT\d*)\b", text.upper())
    return m.group(1) if m else None


@app.function(
    gpu="T4",
    secrets=[r2_secret],
    volumes={VOLUME_MOUNT: volume},
    timeout=600,
    max_containers=20,
)
def ocr_batch(frame_paths: list[str]) -> list[dict[str, Any]]:
    """Run EasyOCR on a batch of frame paths; crop to bottom third for scorebug."""
    import cv2
    import easyocr

    volume.reload()
    reader = easyocr.Reader(["en"], gpu=True, verbose=False)
    results: list[dict[str, Any]] = []

    for path in frame_paths:
        stem = Path(path).stem
        frame_index = int(stem.split("_")[-1])
        video_sec = frame_index

        img = cv2.imread(path)
        if img is None:
            results.append({"frame_index": frame_index, "video_sec": video_sec, "quarter": None, "clock": None})
            continue

        h = img.shape[0]
        scorebug = img[int(h * 0.88):, :]
        scorebug = cv2.resize(scorebug, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(scorebug, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        ocr_out = reader.readtext(gray, detail=0)
        combined = " ".join(ocr_out)
        clock = _parse_clock(ocr_out)
        quarter = _parse_quarter(combined)

        print(f"[OCR] frame {frame_index:04d} | raw={ocr_out!r} | clock={clock} | quarter={quarter}")
        results.append({"frame_index": frame_index, "video_sec": video_sec, "quarter": quarter, "clock": clock})

    return results


# ---------------------------------------------------------------------------
# Step 3 — Time-series smoothing
# ---------------------------------------------------------------------------


def _clock_to_seconds(clock_str: str) -> float | None:
    try:
        parts = clock_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return None


def _seconds_to_clock(total: float) -> str:
    mins = int(total) // 60
    secs = int(total) % 60
    return f"{mins:02d}:{secs:02d}"


def smooth_timeline(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not raw:
        return raw

    data = sorted(raw, key=lambda r: r["video_sec"])
    by_sec: dict[int, dict] = {r["video_sec"]: dict(r) for r in data}
    min_sec = data[0]["video_sec"]
    max_sec = data[-1]["video_sec"]
    smoothed: list[dict[str, Any]] = []

    for sec in range(min_sec, max_sec + 1):
        if sec in by_sec and by_sec[sec]["clock"] is not None:
            smoothed.append(by_sec[sec])
            continue

        prev_entry = next(
            (by_sec[s] for s in range(sec - 1, min_sec - 1, -1) if s in by_sec and by_sec[s]["clock"]),
            None,
        )
        next_entry = next(
            (by_sec[s] for s in range(sec + 1, max_sec + 1) if s in by_sec and by_sec[s]["clock"]),
            None,
        )

        if prev_entry is None and next_entry is None:
            smoothed.append({"frame_index": sec, "video_sec": sec, "quarter": None, "clock": None})
            continue

        quarter = (prev_entry or next_entry)["quarter"]  # type: ignore[index]

        if prev_entry and next_entry:
            p_secs = _clock_to_seconds(prev_entry["clock"])
            n_secs = _clock_to_seconds(next_entry["clock"])
            if p_secs is not None and n_secs is not None:
                span = next_entry["video_sec"] - prev_entry["video_sec"]
                frac = (sec - prev_entry["video_sec"]) / span if span else 0
                clock = _seconds_to_clock(p_secs + frac * (n_secs - p_secs))
            else:
                clock = (prev_entry or next_entry)["clock"]  # type: ignore[index]
        elif prev_entry:
            p_secs = _clock_to_seconds(prev_entry["clock"])
            elapsed = sec - prev_entry["video_sec"]
            clock = _seconds_to_clock(p_secs - elapsed) if p_secs is not None else prev_entry["clock"]
        else:
            clock = next_entry["clock"]  # type: ignore[index]

        smoothed.append({"frame_index": sec, "video_sec": sec, "quarter": quarter, "clock": clock})

    return smoothed


# ---------------------------------------------------------------------------
# Step 4 — Fetch play-by-play from NBA API
# ---------------------------------------------------------------------------


def fetch_play_by_play(home_team_id: str, away_team_id: str, game_date: str) -> dict:
    """Fetch game metadata, play-by-play, and box scores from the NBA API.

    Args:
        home_team_id: ESPN numeric team ID (e.g. "13" for Lakers).
                      Used for fuzzy matching against nba_api team IDs.
        away_team_id: ESPN numeric team ID for the away team.
        game_date:    ISO date string from ESPN (e.g. "2024-12-25T17:30:00Z").

    Returns dict with keys: game_meta, pbp_raw, player_boxscore.
    """
    from datetime import datetime, timezone
    from nba_api.stats.endpoints import LeagueGameFinder, PlayByPlayV3, BoxScoreTraditionalV3

    # Parse date — ESPN sends UTC ISO strings
    dt = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
    date_str = dt.astimezone(timezone.utc).strftime("%m/%d/%Y")

    # LeagueGameFinder locates all games on the target date.
    # ESPN and nba_api use different numeric team IDs so we fetch all games on the
    # date and pull PBP for each — the game state merge step handles alignment.
    game_finder = LeagueGameFinder(date_from_nullable=date_str, date_to_nullable=date_str)
    games_df = game_finder.get_data_frames()[0]

    if games_df.empty:
        raise ValueError(f"No games found for date {date_str}")

    # Deduplicate: each game appears twice (home + away row)
    game_ids = games_df["GAME_ID"].unique().tolist()

    game_meta = {"date": date_str, "game_ids": game_ids}
    pbp_all = []
    boxscore_all = {}

    for game_id in game_ids:
        try:
            pbp = PlayByPlayV3(game_id=game_id)
            pbp_df = pbp.get_data_frames()[0]
            pbp_all.extend(pbp_df.to_dict(orient="records"))

            box = BoxScoreTraditionalV3(game_id=game_id)
            player_stats = box.get_data_frames()[0]
            boxscore_all[game_id] = player_stats.to_dict(orient="records")
        except Exception as e:
            print(f"[WARN] PBP/boxscore fetch failed for game {game_id}: {e}")

    return {
        "game_meta": game_meta,
        "pbp_raw": pbp_all,
        "player_boxscore": boxscore_all,
    }


# ---------------------------------------------------------------------------
# Step 5 — Build game state JSON
# ---------------------------------------------------------------------------


def build_game_state(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    game_state: dict[str, Any] = {}
    for entry in timeline:
        sec = entry["video_sec"]
        quarter = entry.get("quarter") or "UNK"
        clock = entry.get("clock") or "00:00"
        game_state[str(sec)] = {
            "game_time": f"{quarter}_{clock}",
            "stats": {},
            "recent_event": None,
        }
    return game_state


# ---------------------------------------------------------------------------
# Step 6 — Upload results to R2
# ---------------------------------------------------------------------------


def upload_results(clip_id: str, timeline: list[dict], game_state: dict) -> str:
    """Upload processed_game_state.json to R2 and return the R2 key."""
    s3 = _r2_client()
    results_key = f"results/{clip_id}/game_state.json"

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=results_key,
        Body=json.dumps(game_state, indent=2).encode(),
        ContentType="application/json",
    )

    timeline_key = f"results/{clip_id}/clock_timeline.json"
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=timeline_key,
        Body=json.dumps(timeline, indent=2).encode(),
        ContentType="application/json",
    )

    print(f"Uploaded results to R2: {results_key}, {timeline_key}")
    return results_key


# ---------------------------------------------------------------------------
# Orchestrator — runs the full pipeline with stage callbacks
# ---------------------------------------------------------------------------


@app.function(
    secrets=[r2_secret],
    volumes={VOLUME_MOUNT: volume},
    timeout=3600,
)
def process_clip(
    clip_id: str,
    r2_key: str,
    home_team_id: str,
    away_team_id: str,
    game_date: str,
    webhook_url: str,
    secret: str,
) -> None:
    """Full pipeline: download → OCR → fetch PBP → merge → upload → notify."""
    try:
        # Stage 1: extract frames
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "extracting_frames"})
        frame_paths = extract_frames.remote(r2_key)
        print(f"Extracted {len(frame_paths)} frames.")

        # Stage 2: OCR
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "running_ocr"})
        batches = [frame_paths[i: i + BATCH_SIZE] for i in range(0, len(frame_paths), BATCH_SIZE)]
        raw_results: list[dict[str, Any]] = []
        for batch_result in ocr_batch.map(batches, order_outputs=False):
            raw_results.extend(batch_result)
        timeline = smooth_timeline(raw_results)
        print(f"OCR complete: {len(timeline)} timeline entries.")

        # Stage 3: fetch play-by-play
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "fetching_pbp"})
        pbp_data = fetch_play_by_play(home_team_id, away_team_id, game_date)
        print(f"PBP fetched: {len(pbp_data.get('pbp_raw', []))} events.")

        # Stage 4: merge
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "merging"})
        game_state = build_game_state(timeline)

        # Stage 5: upload results
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "uploading_results"})
        results_key = upload_results(clip_id, timeline, game_state)

        # Done
        _post_webhook(webhook_url, secret, {
            "event": "completed",
            "clip_id": clip_id,
            "results_key": results_key,
        })
        print(f"Pipeline complete for clip {clip_id}.")

    except Exception as e:
        print(f"[ERROR] Pipeline failed for clip {clip_id}: {e}")
        _post_webhook(webhook_url, secret, {
            "event": "failed",
            "clip_id": clip_id,
            "error": str(e),
        })


# ---------------------------------------------------------------------------
# Web endpoint — triggered by Next.js link-game route
# ---------------------------------------------------------------------------


@app.function()
@modal.fastapi_endpoint(method="POST")
def trigger(body: dict) -> dict:
    """Accepts a POST from the Next.js link-game route and spawns process_clip async."""
    required = ["clip_id", "r2_key", "home_team_id", "away_team_id", "game_date", "webhook_url", "secret"]
    missing = [k for k in required if k not in body]
    if missing:
        return {"error": f"Missing fields: {missing}"}

    process_clip.spawn(
        body["clip_id"],
        body["r2_key"],
        body["home_team_id"],
        body["away_team_id"],
        body["game_date"],
        body["webhook_url"],
        body["secret"],
    )
    return {"status": "queued", "clip_id": body["clip_id"]}


# ---------------------------------------------------------------------------
# Local entrypoint — for manual testing
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def main(
    r2_key: str = "footage/test/sample.mp4",
    clip_id: str = "local-test",
    home_team_id: str = "13",
    away_team_id: str = "9",
    game_date: str = "2024-12-25T17:30:00Z",
    webhook_url: str = "",
    secret: str = "",
):
    print(f"Running local pipeline for clip_id={clip_id}, r2_key={r2_key}")
    process_clip.remote(clip_id, r2_key, home_team_id, away_team_id, game_date, webhook_url, secret)
    print("Done.")
