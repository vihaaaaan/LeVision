#!/usr/bin/env python3
"""Modal-based parallel OCR pipeline for extracting game clock and quarter from
basketball footage stored in Cloudflare R2.

Architecture:
  1. Download video from R2 + extract 1 FPS frames via ffmpeg (CPU Modal function)
  2. Fan-out OCR over frame batches using GPU T4 instances (parallel Modal function)
  3. Aggregate, smooth, and export clock_timeline.json
  4. Fetch play-by-play from NBA API using home/away team IDs + game date
  5. Run GameStateMachine to build second-by-second ground-truth timeline
  6. Merge OCR timeline with ground-truth → video_state_map
  7. Format and upload results to R2, POST completion webhook
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import unicodedata
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
    .add_local_file("data/nba/pbp_raw.json", "/nba_data/pbp_raw.json")
    .add_local_file("data/nba/player_boxscore.json", "/nba_data/player_boxscore.json")
    .add_local_file("data/nba/game_meta.json", "/nba_data/game_meta.json")
)

app = modal.App("basketball-clock-ocr", image=image)

# Shared volume so the extraction function and OCR functions can both see frames
volume = modal.Volume.from_name("clock-ocr-frames", create_if_missing=True)
VOLUME_MOUNT = "/mnt/frames"

R2_BUCKET = "gamefootage"
BATCH_SIZE = 30

QUARTER_MAP = {"1ST": 1, "2ND": 2, "3RD": 3, "4TH": 4, "OT": 5}
PERIOD_SECS = 720  # 12 min per NBA quarter

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
# ESPN team ID → (NBA API team ID, abbreviation)
# Static mapping — 30 teams, IDs never change, no network call needed.
# ---------------------------------------------------------------------------

_ESPN_TO_NBA: dict[str, tuple[int, str]] = {
    "1":  (1610612737, "ATL"),
    "2":  (1610612738, "BOS"),
    "3":  (1610612740, "NOP"),
    "4":  (1610612741, "CHI"),
    "5":  (1610612739, "CLE"),
    "6":  (1610612742, "DAL"),
    "7":  (1610612743, "DEN"),
    "8":  (1610612765, "DET"),
    "9":  (1610612744, "GSW"),
    "10": (1610612745, "HOU"),
    "11": (1610612754, "IND"),
    "12": (1610612746, "LAC"),
    "13": (1610612747, "LAL"),
    "14": (1610612748, "MIA"),
    "15": (1610612749, "MIL"),
    "16": (1610612750, "MIN"),
    "17": (1610612751, "BKN"),
    "18": (1610612752, "NYK"),
    "19": (1610612753, "ORL"),
    "20": (1610612755, "PHI"),
    "21": (1610612756, "PHX"),
    "22": (1610612757, "POR"),
    "23": (1610612758, "SAC"),
    "24": (1610612759, "SAS"),
    "25": (1610612760, "OKC"),
    "26": (1610612762, "UTA"),
    "27": (1610612764, "WAS"),
    "28": (1610612761, "TOR"),
    "29": (1610612763, "MEM"),
    "30": (1610612766, "CHA"),
}


def _espn_to_nba_team_id(espn_team_id: str) -> tuple[int, str]:
    result = _ESPN_TO_NBA.get(str(espn_team_id))
    if not result:
        raise ValueError(f"Unknown ESPN team ID: {espn_team_id}")
    return result


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
# Step 4 — Fetch play-by-play from NBA API (filtered to the correct game)
# ---------------------------------------------------------------------------


_NBA_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Host": "stats.nba.com",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def _nba_get(fn: Any, *args: Any, retries: int = 3, **kwargs: Any) -> Any:
    """Call an nba_api endpoint with browser headers and retries."""
    import time
    kwargs.setdefault("timeout", 60)
    kwargs.setdefault("headers", _NBA_HEADERS)
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if attempt == retries:
                raise
            wait = attempt * 3
            print(f"[WARN] nba_api attempt {attempt}/{retries} failed ({exc}); retrying in {wait}s…")
            time.sleep(wait)


def fetch_play_by_play(home_team_id: str, away_team_id: str, game_date: str) -> dict:
    """Fetch PBP + boxscore for the game, with R2 caching to avoid repeated NBA API hits."""
    from datetime import datetime, timezone
    from nba_api.stats.endpoints import LeagueGameFinder, PlayByPlayV3, BoxScoreTraditionalV3

    home_nba_id, home_abbrev = _espn_to_nba_team_id(home_team_id)
    away_nba_id, away_abbrev = _espn_to_nba_team_id(away_team_id)
    print(f"Resolved teams: {home_abbrev} (NBA {home_nba_id}) vs {away_abbrev} (NBA {away_nba_id})")

    dt = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
    date_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")

    # --- Check bundled data files first (baked into the image at deploy time) ---
    bundled_pbp  = Path("/nba_data/pbp_raw.json")
    bundled_box  = Path("/nba_data/player_boxscore.json")
    bundled_meta = Path("/nba_data/game_meta.json")
    if bundled_pbp.exists() and bundled_box.exists():
        meta = json.loads(bundled_meta.read_text()) if bundled_meta.exists() else {}
        result = {
            "game_meta":       meta,
            "pbp_raw":         json.loads(bundled_pbp.read_text()),
            "player_boxscore": json.loads(bundled_box.read_text()),
            "home_nba_id":     home_nba_id,
            "away_nba_id":     away_nba_id,
        }
        print("Using bundled PBP data (no NBA API call needed)")
        return result

    # --- Fetch from NBA API ---
    date_api = datetime.fromisoformat(game_date.replace("Z", "+00:00")).strftime("%m/%d/%Y")

    games_df = _nba_get(LeagueGameFinder,
                        date_from_nullable=date_api,
                        date_to_nullable=date_api).get_data_frames()[0]

    if games_df.empty:
        raise ValueError(f"No games found for date {date_api}")

    matching_game_id: str | None = None
    for _, row in games_df.iterrows():
        matchup = str(row.get("MATCHUP", "")).upper()
        if home_abbrev.upper() in matchup and away_abbrev.upper() in matchup:
            matching_game_id = str(row["GAME_ID"])
            break

    if not matching_game_id:
        matching_game_id = str(games_df["GAME_ID"].iloc[0])
        print(f"[WARN] Could not match {home_abbrev} vs {away_abbrev}; using {matching_game_id}")
    else:
        print(f"Matched game_id: {matching_game_id}")

    pbp_raw: list[dict] = []
    player_boxscore: list[dict] = []
    try:
        pbp_raw = _nba_get(PlayByPlayV3, game_id=matching_game_id).get_data_frames()[0].to_dict(orient="records")
        player_boxscore = _nba_get(BoxScoreTraditionalV3, game_id=matching_game_id).get_data_frames()[0].to_dict(orient="records")
    except Exception as e:
        print(f"[WARN] PBP/boxscore fetch failed for game {matching_game_id}: {e}")

    print(f"PBP events: {len(pbp_raw)}  |  Roster size: {len(player_boxscore)}")

    return {
        "game_meta": {"date": date_str, "game_id": matching_game_id},
        "pbp_raw": pbp_raw,
        "player_boxscore": player_boxscore,
        "home_nba_id": home_nba_id,
        "away_nba_id": away_nba_id,
    }


# ---------------------------------------------------------------------------
# GameStateMachine — inlined from state_machine.py
# ---------------------------------------------------------------------------


def _parse_iso_clock(clock_str: str) -> int:
    m = re.match(r"PT(\d+)M([\d.]+)S", str(clock_str))
    if m:
        return int(m.group(1)) * 60 + int(float(m.group(2)))
    return 0


def _remaining_to_clock_str(remaining: int) -> str:
    mn, s = divmod(max(remaining, 0), 60)
    return f"{mn:02d}:{s:02d}"


def _game_elapsed(period: int, remaining: int) -> int:
    return (period - 1) * PERIOD_SECS + (PERIOD_SECS - remaining)


def _norm(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


class GameStateMachine:
    """Replay NBA PBP events and produce a second-by-second state timeline."""

    def __init__(
        self,
        pbp: list[dict],
        boxscore: list[dict],
        home_team_id: int,
        away_team_id: int,
    ) -> None:
        self.home_id = home_team_id
        self.away_id = away_team_id
        self.on_court: dict[int, list[int]] = {home_team_id: [], away_team_id: []}
        self.stats: dict[int, dict[str, int]] = {}
        self.events_by_second: dict[int, list[str]] = {}
        self.recent_events_by_second: dict[int, list[str]] = {}
        self.current_game_sec: int = 0
        self.period = 1
        self.clock = "12:00"
        self._name_idx: dict[str, int] = {}
        self.timeline: dict[int, dict] = {}

        self._build_registry(pbp, boxscore)
        self._init_starters(boxscore)
        self._init_stats(boxscore)
        self._build_timeline(pbp)

    def _register(self, name: str, pid: int) -> None:
        if not name or not pid:
            return
        self._name_idx[_norm(name)] = pid
        parts = name.strip().split()
        if parts:
            self._name_idx[_norm(parts[-1])] = pid
        if len(parts) >= 2:
            abbrev = f"{parts[0][0]}. {' '.join(parts[1:])}"
            self._name_idx[_norm(abbrev)] = pid

    def _build_registry(self, pbp: list[dict], boxscore: list[dict]) -> None:
        for row in pbp:
            pid = row.get("personId")
            if not pid or pid == 0:
                continue
            self._register(row.get("playerName", ""), pid)
            self._register(row.get("playerNameI", ""), pid)
        for row in boxscore:
            pid = row.get("personId")
            if not pid:
                continue
            full = f"{row.get('firstName', '')} {row.get('familyName', '')}".strip()
            self._register(full, pid)
            self._register(row.get("familyName", ""), pid)

    def _lookup(self, name: str) -> int | None:
        key = _norm(name)
        pid = self._name_idx.get(key)
        if pid:
            return pid
        parts = key.split()
        if parts:
            return self._name_idx.get(parts[-1])
        return None

    def _init_starters(self, boxscore: list[dict]) -> None:
        for row in boxscore:
            pos = str(row.get("position", "")).strip()
            if pos not in ("G", "F", "C"):
                continue
            tid = row["teamId"]
            pid = row["personId"]
            if tid in self.on_court and pid not in self.on_court[tid]:
                self.on_court[tid].append(pid)
        for tid, lineup in self.on_court.items():
            print(f"  Starters team {tid}: {len(lineup)} players")
            if len(lineup) != 5:
                print(f"  [WARN] Expected 5 starters, got {len(lineup)}")

    def _init_stats(self, boxscore: list[dict]) -> None:
        for row in boxscore:
            pid = row.get("personId")
            if pid:
                self.stats[pid] = {"pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0}

    def build_recent_events(self, window: int = 5) -> None:
        all_event_secs = sorted(self.events_by_second.keys())
        if not all_event_secs:
            return
        max_sec = max(all_event_secs)
        rolling: list[str] = []
        for sec in range(max_sec + 1):
            if sec - 1 in self.events_by_second:
                rolling.extend(self.events_by_second[sec - 1])
            rolling = rolling[-window:]
            self.recent_events_by_second[sec] = list(rolling)

    def _build_timeline(self, pbp: list[dict]) -> None:
        bucket: dict[int, list[dict]] = {}
        for row in pbp:
            remaining = _parse_iso_clock(row.get("clock", "PT00M00.00S"))
            period = int(row.get("period", 1))
            gsec = _game_elapsed(period, remaining)
            bucket.setdefault(gsec, []).append(row)

        max_sec = max(bucket.keys()) if bucket else 2880
        prev_sec = 0
        current_state = self._snapshot()

        for gsec in sorted(bucket.keys()):
            for s in range(prev_sec, gsec):
                self.timeline[s] = {**current_state, "events": []}
            self.current_game_sec = gsec
            for row in bucket[gsec]:
                self.period = int(row.get("period", self.period))
                remaining = _parse_iso_clock(row.get("clock", "PT12M00.00S"))
                self.clock = _remaining_to_clock_str(remaining)
                self._apply(row)
            current_state = self._snapshot()
            self.timeline[gsec] = {**current_state, "events": self.events_by_second.get(gsec, [])}
            prev_sec = gsec + 1

        for s in range(prev_sec, max_sec + 1):
            self.timeline[s] = {**current_state, "events": []}

        print(f"  Timeline spans game_sec 0–{max_sec} ({len(self.timeline)} entries)")

        self.build_recent_events()
        for sec, entry in self.timeline.items():
            entry["recent_events"] = self.recent_events_by_second.get(sec, [])

    def _apply(self, row: dict) -> None:
        action = row.get("actionType", "")
        if action == "Substitution":
            self._do_sub(row)
        elif action == "Made Shot":
            self._do_made_shot(row)
        elif action == "Free Throw":
            if "MISS" not in row.get("description", "").upper():
                self._do_free_throw(row)
        elif action == "Rebound":
            self._do_rebound(row)
        elif action == "Turnover":
            self._do_turnover(row)
        elif action == "":
            self._do_unlabelled(row)
        elif action == "Missed Shot":
            self._add_event(self.current_game_sec, row.get("description", "")[:80])

    def _do_sub(self, row: dict) -> None:
        out_id = row.get("personId")
        team_id = row.get("teamId")
        desc = row.get("description", "")
        m = re.match(r"SUB:\s+(.+?)\s+FOR\s+", desc, re.IGNORECASE)
        if not m:
            return
        in_name = m.group(1).strip()
        in_id = self._lookup(in_name)
        lineup = self.on_court.get(team_id, [])
        if out_id and out_id in lineup:
            lineup.remove(out_id)
        if in_id and in_id not in lineup:
            lineup.append(in_id)
        elif not in_id:
            print(f"  [WARN] sub: couldn't resolve '{in_name}' in '{desc}'")

    def _do_made_shot(self, row: dict) -> None:
        pid = row.get("personId")
        if not pid or pid == 0:
            return
        desc = row.get("description", "")
        pts = 3 if "3PT" in desc else 2
        self._add(pid, "pts", pts)
        m = re.search(r"\((\w[\w .']+?)\s+\d+\s+AST\)", desc)
        if m:
            asst_id = self._lookup(m.group(1).strip())
            if asst_id:
                self._add(asst_id, "ast", 1)
        self._add_event(self.current_game_sec, desc[:80])

    def _do_free_throw(self, row: dict) -> None:
        pid = row.get("personId")
        if pid and pid != 0:
            self._add(pid, "pts", 1)

    def _do_rebound(self, row: dict) -> None:
        pid = row.get("personId")
        desc = row.get("description", "")
        if not pid or pid == 0 or "Team" in desc:
            return
        self._add(pid, "reb", 1)
        self._add_event(self.current_game_sec, desc[:80])

    def _do_turnover(self, row: dict) -> None:
        self._add_event(self.current_game_sec, row.get("description", "")[:80])

    def _do_unlabelled(self, row: dict) -> None:
        pid = row.get("personId")
        desc = row.get("description", "")
        if not pid or pid == 0:
            return
        if "BLOCK" in desc:
            self._add(pid, "blk", 1)
            self._add_event(self.current_game_sec, desc[:80])
        elif "STEAL" in desc:
            self._add(pid, "stl", 1)
            self._add_event(self.current_game_sec, desc[:80])

    def _add(self, pid: int, stat: str, value: int) -> None:
        if pid not in self.stats:
            self.stats[pid] = {"pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0}
        self.stats[pid][stat] += value

    def _add_event(self, sec: int, desc: str) -> None:
        if desc:
            self.events_by_second.setdefault(sec, []).append(desc)

    def _snapshot(self) -> dict:
        return {
            "period": self.period,
            "clock": self.clock,
            "on_court": copy.deepcopy(self.on_court),
            "stats": copy.deepcopy(self.stats),
        }


# ---------------------------------------------------------------------------
# OCR → ground-truth merge — inlined from merge_ocr.py
# ---------------------------------------------------------------------------


def _clock_remaining(clock_str: str) -> int:
    try:
        mn, s = clock_str.split(":")
        return int(mn) * 60 + int(s)
    except Exception:
        return PERIOD_SECS


def _ocr_to_game_sec(quarter: str | None, clock: str | None) -> int | None:
    if not quarter or not clock:
        return None
    period = QUARTER_MAP.get(str(quarter).upper())
    if period is None:
        return None
    remaining = _clock_remaining(clock)
    return (period - 1) * PERIOD_SECS + (PERIOD_SECS - remaining)


def _snap(target_sec: int, available: list[int]) -> int:
    return min(available, key=lambda s: abs(s - target_sec))


def _merge_ocr(
    ocr_timeline: list[dict],
    gt_timeline: dict[str, dict],
) -> dict[str, dict]:
    available_secs = sorted(int(k) for k in gt_timeline.keys())
    result: dict[str, dict] = {}
    null_count = 0
    drifts: list[int] = []

    for entry in ocr_timeline:
        vsec = entry["video_sec"]
        qtr = entry.get("quarter")
        clock = entry.get("clock")
        target = _ocr_to_game_sec(qtr, clock)

        if target is None:
            gsec = 0
            null_count += 1
        else:
            gsec = _snap(target, available_secs)
            drifts.append(abs(gsec - target))

        snapshot = dict(gt_timeline[str(gsec)])
        snapshot["ocr_clock"] = clock or "12:00"
        snapshot["ocr_quarter"] = qtr or "1ST"
        result[str(vsec)] = snapshot

    print(f"  Mapped {len(result)} video_secs | null-OCR: {null_count}")
    if drifts:
        print(f"  Clock drift avg={sum(drifts)/len(drifts):.1f}s  max={max(drifts)}s")

    return result


# ---------------------------------------------------------------------------
# Step 5 — Build game state (full pipeline: state machine + merge + format)
# ---------------------------------------------------------------------------


def build_game_state(timeline: list[dict[str, Any]], pbp_data: dict) -> dict[str, Any]:
    """Run GameStateMachine, merge with OCR timeline, and format final output."""
    pbp = pbp_data.get("pbp_raw", [])
    boxscore = pbp_data.get("player_boxscore", [])
    home_nba_id: int = pbp_data.get("home_nba_id", 0)
    away_nba_id: int = pbp_data.get("away_nba_id", 0)

    if not pbp or not boxscore:
        print("[WARN] No PBP/boxscore data — falling back to clock-only output")
        return {
            str(e["video_sec"]): {
                "game_clock": e.get("clock") or "00:00",
                "period": QUARTER_MAP.get(str(e.get("quarter", "")).upper(), 1),
                "home_team": {"on_court": [], "player_stats": {}},
                "visitor_team": {"on_court": [], "player_stats": {}},
                "events": [],
                "recent_events": [],
            }
            for e in timeline
        }

    # Build ground-truth second-by-second timeline
    print("Building GameStateMachine…")
    sm = GameStateMachine(pbp, boxscore, home_nba_id, away_nba_id)
    gt_timeline = {str(k): v for k, v in sm.timeline.items()}

    # Merge OCR timeline with ground truth
    print("Merging OCR timeline with ground truth…")
    video_state_map = _merge_ocr(timeline, gt_timeline)

    # Build team membership sets for stat assignment
    home_pids = {r["personId"] for r in boxscore if r.get("teamId") == home_nba_id}
    visitor_pids = {r["personId"] for r in boxscore if r.get("teamId") == away_nba_id}

    # Format final output
    print("Formatting output…")
    out: dict[str, Any] = {}

    for vsec_str, state in video_state_map.items():
        # Explicitly untyped so .get() accepts both int and str keys.
        # In-memory snapshots use int keys; JSON-round-tripped data uses str keys.
        on_court: dict = state.get("on_court", {})
        all_stats: dict = state.get("stats", {})

        home_court = on_court.get(home_nba_id) or on_court.get(str(home_nba_id)) or []
        visitor_court = on_court.get(away_nba_id) or on_court.get(str(away_nba_id)) or []

        ocr_clock = state.get("ocr_clock") or state.get("clock", "12:00")
        ocr_quarter = state.get("ocr_quarter") or "1ST"
        period = QUARTER_MAP.get(str(ocr_quarter).upper(), state.get("period", 1))

        home_court_set = {int(x) for x in home_court}
        visitor_court_set = {int(x) for x in visitor_court}

        home_stats: dict[str, dict] = {}
        visitor_stats: dict[str, dict] = {}

        for pid_str, pstats in all_stats.items():
            pid = int(pid_str)
            record = {
                "pts": pstats.get("pts", 0),
                "reb": pstats.get("reb", 0),
                "ast": pstats.get("ast", 0),
                "stl": pstats.get("stl", 0),
                "blk": pstats.get("blk", 0),
            }
            if pid in home_court_set or pid in home_pids:
                home_stats[str(pid)] = record
            elif pid in visitor_court_set or pid in visitor_pids:
                visitor_stats[str(pid)] = record

        out[vsec_str] = {
            "game_clock": ocr_clock,
            "period": period,
            "home_team": {
                "on_court": [int(x) for x in home_court],
                "player_stats": home_stats,
            },
            "visitor_team": {
                "on_court": [int(x) for x in visitor_court],
                "player_stats": visitor_stats,
            },
            "events": state.get("events", []),
            "recent_events": state.get("recent_events", []),
        }

    print(f"Game state built: {len(out)} video_secs")
    return out


# ---------------------------------------------------------------------------
# Step 6 — Upload results to R2
# ---------------------------------------------------------------------------


def upload_results(clip_id: str, timeline: list[dict], game_state: dict, pbp_data: dict) -> str:
    """Upload game_state.json, player_boxscore.json, and clock_timeline.json to R2."""
    s3 = _r2_client()
    results_key = f"results/{clip_id}/game_state.json"

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=results_key,
        Body=json.dumps(game_state, indent=2).encode(),
        ContentType="application/json",
    )

    # player_boxscore.json is fetched by the Next.js API for player name resolution
    s3.put_object(
        Bucket=R2_BUCKET,
        Key=f"results/{clip_id}/player_boxscore.json",
        Body=json.dumps(pbp_data.get("player_boxscore", []), indent=2).encode(),
        ContentType="application/json",
    )

    s3.put_object(
        Bucket=R2_BUCKET,
        Key=f"results/{clip_id}/clock_timeline.json",
        Body=json.dumps(timeline, indent=2).encode(),
        ContentType="application/json",
    )

    print(f"Uploaded results to R2 under results/{clip_id}/")
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
    """Full pipeline: download → OCR → fetch PBP → state machine → merge → upload → notify."""
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

        # Stage 3: fetch play-by-play (filtered to this exact game)
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "fetching_pbp"})
        pbp_data = fetch_play_by_play(home_team_id, away_team_id, game_date)
        print(f"PBP fetched: {len(pbp_data.get('pbp_raw', []))} events.")

        # Stage 4: run state machine + merge + format
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "merging"})
        game_state = build_game_state(timeline, pbp_data)

        # Stage 5: upload results
        _post_webhook(webhook_url, secret, {"event": "stage_update", "clip_id": clip_id, "stage": "uploading_results"})
        results_key = upload_results(clip_id, timeline, game_state, pbp_data)

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
