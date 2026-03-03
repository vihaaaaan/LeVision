#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from supabase import Client, create_client
from urllib3.util.retry import Retry

DEFAULT_ESPN_URL = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
    "?region=us&lang=en&contentorigin=espn&event=400878154"
)

LOGGER = logging.getLogger("espn_supabase_sync")

DEFAULT_PLAYER_STAT_ORDER = [
    "minutes",
    "fieldGoalsMadeFieldGoalsAttempted",
    "threePointFieldGoalsMadeFieldGoalsAttempted",
    "freeThrowsMadeFreeThrowsAttempted",
    "offensiveRebounds",
    "defensiveRebounds",
    "rebounds",
    "assists",
    "fouls",
    "steals",
    "turnovers",
    "blocks",
    "plusMinus",
    "points",
]

TEAM_STAT_CANDIDATES: dict[str, list[str]] = {
    "field_goals": [
        "fieldGoalsMadeFieldGoalsAttempted",
        "fg",
        "fieldGoals",
    ],
    "field_goal_percentage": ["fieldGoalPercentage", "fieldGoalPct", "fgPct", "fgPercentage"],
    "three_point_field_goals": [
        "threePointFieldGoalsMadeThreePointFieldGoalsAttempted",
        "threePointFieldGoals",
        "3pt",
        "threePointFG",
    ],
    "three_point_percentage": [
        "threePointFieldGoalPercentage",
        "threePointFieldGoalPct",
        "threePointPercentage",
        "threePointPct",
        "threePointFGPct",
    ],
    "free_throws": ["freeThrowsMadeFreeThrowsAttempted", "ft", "freeThrows"],
    "free_throw_percentage": ["freeThrowPercentage", "freeThrowPct", "ftPct", "freeThrowsPct"],
    "total_rebounds": ["totalRebounds", "rebounds", "reb"],
    "offensive_rebounds": ["offensiveRebounds", "oreb"],
    "defensive_rebounds": ["defensiveRebounds", "dreb"],
    "assists": ["assists", "ast"],
    "steals": ["steals", "stl"],
    "blocks": ["blocks", "blk"],
    "turnovers": ["turnovers", "to", "tov"],
    "team_turnovers": ["teamTurnovers"],
    "total_turnovers": ["totalTurnovers"],
    "technical_fouls": ["technicalFouls"],
    "total_technical_fouls": ["totalTechnicalFouls"],
    "flagrant_fouls": ["flagrantFouls"],
    "turnover_points": ["turnoverPoints", "pointsOffTurnovers"],
    "fast_break_points": ["fastBreakPoints"],
    "points_in_paint": ["pointsInPaint", "paintPoints"],
    "fouls": ["fouls", "personalFouls", "pf"],
    "largest_lead": ["largestLead"],
}

TEAM_STAT_DB_COLUMNS: dict[str, dict[str, str]] = {
    "quoted": {
        "fg_made": "fgMade-fgAttempted",
        "field_goal_percentage": "fieldGoalPercentage",
        "three_point_fg_made": "threePointFgMade-threePointFgAttempted",
        "three_point_fg_percentage": "threePointFgPercentage",
        "free_throws_made": "freeThrowsMade-freeThrowsAttempted",
        "free_throw_percentage": "freeThrowPercentage",
        "total_rebounds": "totalRebounds",
        "offensive_rebounds": "offensiveRebounds",
        "defensive_rebounds": "defensiveRebounds",
        "assists": "assists",
        "steals": "steals",
        "blocks": "blocks",
        "turnovers": "turnovers",
        "team_turnovers": "teamTurnovers",
        "total_turnovers": "totalTurnovers",
        "technical_fouls": "technicalFouls",
        "total_technical_fouls": "totalTechnicalFouls",
        "flagrant_fouls": "flagrantFouls",
        "turnover_points": "turnoverPoints",
        "fast_break_points": "fastBreakPoints",
        "points_in_paint": "pointsInPaint",
        "fouls": "fouls",
        "largest_lead": "largestLead",
    },
    "snake": {
        "fg_made": "fg_made",
        "fg_attempted": "fg_attempted",
        "field_goal_percentage": "field_goal_percentage",
        "three_point_fg_made": "three_point_fg_made",
        "three_point_fg_attempted": "three_point_fg_attempted",
        "three_point_fg_percentage": "three_point_fg_percentage",
        "free_throws_made": "free_throws_made",
        "free_throws_attempted": "free_throws_attempted",
        "free_throw_percentage": "free_throw_percentage",
        "total_rebounds": "total_rebounds",
        "offensive_rebounds": "offensive_rebounds",
        "defensive_rebounds": "defensive_rebounds",
        "assists": "assists",
        "steals": "steals",
        "blocks": "blocks",
        "turnovers": "turnovers",
        "team_turnovers": "team_turnovers",
        "total_turnovers": "total_turnovers",
        "technical_fouls": "technical_fouls",
        "total_technical_fouls": "total_technical_fouls",
        "flagrant_fouls": "flagrant_fouls",
        "turnover_points": "turnover_points",
        "fast_break_points": "fast_break_points",
        "points_in_paint": "points_in_paint",
        "fouls": "fouls",
        "largest_lead": "largest_lead",
    },
}


@dataclass(slots=True)
class Settings:
    supabase_url: str
    supabase_service_role_key: str
    espn_summary_url: str
    schema_mode: str
    dry_run: bool
    timeout_seconds: int = 20
    retry_attempts: int = 3


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def str_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on"}


def load_env_files() -> None:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    loaded = False
    for env_file in candidates:
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
            loaded = True
    if not loaded:
        load_dotenv(override=False)


def load_settings(url_override: Optional[str], dry_run_override: Optional[bool]) -> Settings:
    load_env_files()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError(
            "Missing required env vars: SUPABASE_URL and/or SUPABASE_SERVICE_ROLE_KEY. "
            "Set them in your .env file."
        )

    env_url = os.getenv("ESPN_SUMMARY_URL", DEFAULT_ESPN_URL)
    env_schema_mode = os.getenv("SCHEMA_MODE", "snake").strip().lower()
    if env_schema_mode not in {"quoted", "snake"}:
        raise ValueError("SCHEMA_MODE must be 'quoted' or 'snake'.")

    env_dry_run = str_to_bool(os.getenv("DRY_RUN", "false"))
    return Settings(
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_key,
        espn_summary_url=url_override or env_url,
        schema_mode=env_schema_mode,
        dry_run=dry_run_override if dry_run_override is not None else env_dry_run,
    )


def create_http_session(retry_attempts: int) -> requests.Session:
    retry = Retry(
        total=retry_attempts,
        connect=retry_attempts,
        read=retry_attempts,
        status=retry_attempts,
        backoff_factor=0.4,
        allowed_methods=frozenset({"GET"}),
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_espn_summary(url: str, timeout_seconds: int, retry_attempts: int) -> dict[str, Any]:
    session = create_http_session(retry_attempts=retry_attempts)
    try:
        response = session.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch ESPN summary: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("ESPN response was not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected ESPN payload type. Expected a JSON object.")
    return payload


def get_competition(summary: dict[str, Any]) -> dict[str, Any]:
    header = summary.get("header") or {}
    competitions = header.get("competitions") or summary.get("competitions") or []
    if competitions and isinstance(competitions[0], dict):
        return competitions[0]
    return {}


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip()
    if text in {"", "-", "—", "--", "N/A", "NA", "DNP", "DNS", "null", "None"}:
        return None
    text = text.replace(",", "").replace("%", "")
    if ":" in text:
        text = text.split(":", 1)[0]
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def parse_minutes(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "-", "—", "--"}:
        return None
    if ":" in text:
        return safe_int(text.split(":", 1)[0])
    return safe_int(text)


def parse_plus_minus(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().replace("−", "-")
    if text.startswith("+"):
        text = text[1:]
    return safe_int(text)


def parse_made_attempted(value: Any) -> tuple[Optional[int], Optional[int]]:
    if value is None:
        return (None, None)
    if isinstance(value, dict):
        made = safe_int(value.get("made"))
        attempted = safe_int(value.get("attempted"))
        return made, attempted
    text = str(value).strip()
    if "-" in text:
        left, right = text.split("-", 1)
        return safe_int(left), safe_int(right)
    made = safe_int(text)
    return made, None


def bool_or_default(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def first_present(stat_map: dict[str, Any], candidates: list[str]) -> Any:
    for candidate in candidates:
        key = normalize_key(candidate)
        if key in stat_map:
            return stat_map[key]
    return None


def build_normalized_flat_map(*sources: Any) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, (dict, list)):
                continue
            normalized = normalize_key(key)
            if normalized:
                flat[normalized] = value
    return flat


def parse_event_id_from_url(url: str) -> Optional[str]:
    try:
        query = parse_qs(urlparse(url).query)
        event = query.get("event", [None])[0]
        return str(event) if event else None
    except Exception:
        return None


def set_event_id_in_url(url: str, event_id: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["event"] = event_id
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def resolve_summary_url_with_prompt(base_url: str, cli_game_id: Optional[str]) -> str:
    if cli_game_id:
        return set_event_id_in_url(base_url, cli_game_id.strip())

    current_event_id = parse_event_id_from_url(base_url) or ""
    prompt = f"Enter ESPN game event id [{current_event_id}]: " if current_event_id else "Enter ESPN game event id: "
    entered = input(prompt).strip()
    if not entered:
        return base_url
    return set_event_id_in_url(base_url, entered)


def build_teams_from_competitors(competition: dict[str, Any]) -> tuple[list[dict[str, Any]], Optional[str], Optional[str]]:
    competitors = competition.get("competitors") or []
    rows: dict[str, dict[str, Any]] = {}
    home_team: Optional[str] = None
    away_team: Optional[str] = None

    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        team = competitor.get("team") or {}
        team_id = str(team.get("id") or competitor.get("id") or "").strip()
        if not team_id:
            continue
        logo_url = None
        logos = team.get("logos") or []
        if logos and isinstance(logos[0], dict):
            logo_url = logos[0].get("href")

        location = (
            team.get("location")
            or team.get("displayLocation")
            or team.get("shortDisplayName")
            or team.get("displayName")
            or "Unknown"
        )
        row = {
            "id": team_id,
            "location": str(location),
            "name": team.get("name") or team.get("nickname"),
            "abbreviation": team.get("abbreviation"),
            "color": team.get("color"),
            "alternate_color": team.get("alternateColor"),
            "logo_url": logo_url,
        }
        rows[team_id] = row
        home_away = str(competitor.get("homeAway") or "").lower()
        if home_away == "home":
            home_team = team_id
        elif home_away == "away":
            away_team = team_id

    return list(rows.values()), home_team, away_team


def build_teams_from_boxscore(summary: dict[str, Any]) -> list[dict[str, Any]]:
    boxscore = summary.get("boxscore") or {}
    rows: dict[str, dict[str, Any]] = {}
    for team_block in boxscore.get("teams") or []:
        team = team_block.get("team") or {}
        team_id = str(team.get("id") or "").strip()
        if not team_id:
            continue
        logo_url = None
        logos = team.get("logos") or []
        if logos and isinstance(logos[0], dict):
            logo_url = logos[0].get("href")
        rows[team_id] = {
            "id": team_id,
            "location": str(
                team.get("location")
                or team.get("displayLocation")
                or team.get("shortDisplayName")
                or team.get("displayName")
                or "Unknown"
            ),
            "name": team.get("name") or team.get("nickname"),
            "abbreviation": team.get("abbreviation"),
            "color": team.get("color"),
            "alternate_color": team.get("alternateColor"),
            "logo_url": logo_url,
        }
    return list(rows.values())


def derive_season_text(summary: dict[str, Any], competition: dict[str, Any], game_date: Optional[str]) -> str:
    season = summary.get("season") or competition.get("season") or {}
    year = season.get("year")
    if year:
        return str(year)
    if game_date and len(game_date) >= 4:
        return game_date[:4]
    return "unknown"


def extract_points_from_stat_items(items: Any) -> Optional[int]:
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        label = normalize_key(
            item.get("name")
            or item.get("abbreviation")
            or item.get("displayName")
            or item.get("shortDisplayName")
            or item.get("label")
        )
        if label in {"points", "pts", "score"}:
            value = item.get("displayValue")
            if value is None:
                value = item.get("value")
            parsed = safe_int(value)
            if parsed is not None:
                return parsed
    return None


def extract_points(value: Any) -> Optional[int]:
    if isinstance(value, (str, int, float)):
        parsed = safe_int(value)
        if parsed is not None:
            return parsed
    if not isinstance(value, dict):
        return extract_points_from_stat_items(value)

    direct = safe_int(
        value.get("score")
        or value.get("points")
        or value.get("point")
        or value.get("totalPoints")
        or value.get("total")
    )
    if direct is not None:
        return direct

    for key in ("totals", "statistics", "stats", "linescores"):
        parsed = extract_points(value.get(key))
        if parsed is not None:
            return parsed
    return None


def extract_game_points(
    summary: dict[str, Any],
    competition: dict[str, Any],
    home_team: Optional[str],
    away_team: Optional[str],
) -> tuple[Optional[int], Optional[int]]:
    points_by_team: dict[str, int] = {}
    home_points: Optional[int] = None
    away_points: Optional[int] = None

    for competitor in competition.get("competitors") or []:
        if not isinstance(competitor, dict):
            continue
        team_id = str((competitor.get("team") or {}).get("id") or competitor.get("id") or "").strip()
        score = extract_points(competitor)
        if score is None:
            score = extract_points(competitor.get("totals"))
        if team_id and score is not None:
            points_by_team[team_id] = score

        home_away = str(competitor.get("homeAway") or "").lower()
        if home_away == "home" and score is not None:
            home_points = score
        if home_away == "away" and score is not None:
            away_points = score

    boxscore = summary.get("boxscore") or {}
    for team_block in boxscore.get("teams") or []:
        if not isinstance(team_block, dict):
            continue
        team_id = str(((team_block.get("team") or {}).get("id")) or "").strip()
        score = extract_points(team_block)
        if team_id and score is not None:
            points_by_team[team_id] = score

    if home_points is None and home_team:
        home_points = points_by_team.get(home_team)
    if away_points is None and away_team:
        away_points = points_by_team.get(away_team)

    return home_points, away_points


def build_game_row(
    summary: dict[str, Any],
    competition: dict[str, Any],
    event_id: str,
    home_team: Optional[str],
    away_team: Optional[str],
    teams: list[dict[str, Any]],
) -> dict[str, Any]:
    game_date = competition.get("date") or summary.get("gameInfo", {}).get("gameDate")
    status = (
        ((competition.get("status") or {}).get("type") or {}).get("name")
        or ((summary.get("status") or {}).get("type") or {}).get("name")
        or ((competition.get("status") or {}).get("type") or {}).get("description")
        or ((summary.get("status") or {}).get("type") or {}).get("description")
        or ((competition.get("status") or {}).get("type") or {}).get("state")
    )
    venue = ((competition.get("venue") or {}).get("fullName")) or (
        ((summary.get("gameInfo") or {}).get("venue") or {}).get("fullName")
    )

    team_ids = [str(t["id"]) for t in teams if t.get("id")]
    if not home_team and team_ids:
        home_team = team_ids[0]
    if not away_team and len(team_ids) > 1:
        away_team = team_ids[1]
    home_points, away_points = extract_game_points(
        summary=summary,
        competition=competition,
        home_team=home_team,
        away_team=away_team,
    )

    return {
        "id": str(event_id),
        "season": derive_season_text(summary=summary, competition=competition, game_date=game_date),
        "date": game_date,
        "status": status,
        "venue": venue,
        "home_team": home_team,
        "away_team": away_team,
        "home_points": home_points,
        "away_points": away_points,
    }


def build_player_stat_map(raw_stats: Any, stat_keys: Optional[list[str]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(raw_stats, dict):
        for key, value in raw_stats.items():
            result[normalize_key(key)] = value
        return result

    if isinstance(raw_stats, list):
        if stat_keys and len(stat_keys) == len(raw_stats):
            keys = stat_keys
        else:
            keys = DEFAULT_PLAYER_STAT_ORDER[: len(raw_stats)]
        for index, value in enumerate(raw_stats):
            key = keys[index] if index < len(keys) else f"stat_{index}"
            result[normalize_key(key)] = value
    return result


def parse_player_team_blocks(
    blocks: list[dict[str, Any]],
    game_id: str,
    players_by_id: dict[str, dict[str, Any]],
    player_stats_by_pk: dict[tuple[str, str], dict[str, Any]],
) -> None:
    for team_block in blocks:
        if not isinstance(team_block, dict):
            continue
        team = team_block.get("team") or {}
        team_id = str(team.get("id") or "").strip()
        for stat_group in team_block.get("statistics") or []:
            if not isinstance(stat_group, dict):
                continue
            raw_keys = stat_group.get("keys") or stat_group.get("labels") or []
            stat_keys = [str(k) for k in raw_keys] if isinstance(raw_keys, list) else None
            athletes = stat_group.get("athletes") or []
            if not isinstance(athletes, list):
                continue
            for athlete_entry in athletes:
                ingest_athlete_row(
                    athlete_entry=athlete_entry,
                    team_id=team_id,
                    game_id=game_id,
                    stat_keys=stat_keys,
                    players_by_id=players_by_id,
                    player_stats_by_pk=player_stats_by_pk,
                )


def parse_boxscore_team_athletes(
    summary: dict[str, Any],
    game_id: str,
    players_by_id: dict[str, dict[str, Any]],
    player_stats_by_pk: dict[tuple[str, str], dict[str, Any]],
) -> None:
    boxscore = summary.get("boxscore") or {}
    for team_block in boxscore.get("teams") or []:
        if not isinstance(team_block, dict):
            continue
        team = team_block.get("team") or {}
        team_id = str(team.get("id") or "").strip()
        for group in team_block.get("athletes") or []:
            if not isinstance(group, dict):
                continue
            raw_keys = group.get("keys") or group.get("labels") or []
            stat_keys = [str(k) for k in raw_keys] if isinstance(raw_keys, list) else None
            for athlete_entry in group.get("athletes") or []:
                ingest_athlete_row(
                    athlete_entry=athlete_entry,
                    team_id=team_id,
                    game_id=game_id,
                    stat_keys=stat_keys,
                    players_by_id=players_by_id,
                    player_stats_by_pk=player_stats_by_pk,
                )


def infer_dnp(athlete_entry: dict[str, Any], stat_map: dict[str, Any]) -> bool:
    did_not_play_flag = athlete_entry.get("didNotPlay")
    if did_not_play_flag is True:
        return True
    reason = str(
        athlete_entry.get("reason")
        or athlete_entry.get("didNotPlayReason")
        or athlete_entry.get("comment")
        or ""
    ).lower()
    if "dnp" in reason:
        return True
    minutes = first_present(stat_map, ["minutes", "min"])
    return str(minutes).strip() in {"", "-", "—", "--"}


def parse_player_shooting_splits(value_map: dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    fg_made, fg_attempted = parse_made_attempted(
        first_present(
            value_map,
            [
                "fieldGoalsMadeFieldGoalsAttempted",
                "fieldGoals",
                "fg",
                "fgmFga",
                "fgm-fga",
            ],
        )
    )
    if fg_made is None:
        fg_made = safe_int(first_present(value_map, ["fgMade", "fieldGoalsMade", "fgm"]))
    if fg_attempted is None:
        fg_attempted = safe_int(first_present(value_map, ["fgAttempted", "fieldGoalsAttempted", "fga"]))

    three_made, three_attempted = parse_made_attempted(
        first_present(
            value_map,
            [
                "threePointFieldGoalsMadeThreePointFieldGoalsAttempted",
                "threePointFieldGoalsMadeFieldGoalsAttempted",
                "threePointFieldGoals",
                "threePointers",
                "3pt",
            ],
        )
    )
    if three_made is None:
        three_made = safe_int(
            first_present(
                value_map,
                [
                    "threePtrMade",
                    "threePointMade",
                    "threePointersMade",
                    "threePointFieldGoalsMade",
                    "threePtMade",
                    "tpm",
                ],
            )
        )
    if three_attempted is None:
        three_attempted = safe_int(
            first_present(
                value_map,
                [
                    "threePtrAttempted",
                    "threePointAttempted",
                    "threePointersAttempted",
                    "threePointFieldGoalsAttempted",
                    "threePtAttempted",
                    "tpa",
                ],
            )
        )

    ft_made, ft_attempted = parse_made_attempted(
        first_present(
            value_map,
            [
                "freeThrowsMadeFreeThrowsAttempted",
                "freeThrows",
                "ft",
                "ftmFta",
                "ftm-fta",
            ],
        )
    )
    if ft_made is None:
        ft_made = safe_int(first_present(value_map, ["ftMade", "freeThrowsMade", "ftm"]))
    if ft_attempted is None:
        ft_attempted = safe_int(first_present(value_map, ["ftAttempted", "freeThrowsAttempted", "fta"]))

    return fg_made, fg_attempted, three_made, three_attempted, ft_made, ft_attempted


def ingest_athlete_row(
    athlete_entry: dict[str, Any],
    team_id: str,
    game_id: str,
    stat_keys: Optional[list[str]],
    players_by_id: dict[str, dict[str, Any]],
    player_stats_by_pk: dict[tuple[str, str], dict[str, Any]],
) -> None:
    if not isinstance(athlete_entry, dict):
        return

    athlete = athlete_entry.get("athlete") or {}
    player_id = str(athlete.get("id") or athlete_entry.get("id") or "").strip()
    if not player_id:
        return

    full_name = (
        athlete.get("fullName")
        or athlete.get("displayName")
        or athlete.get("shortName")
        or athlete_entry.get("name")
    )
    jersey_number = safe_int(athlete.get("jersey") or athlete_entry.get("jersey"))
    position = (
        ((athlete.get("position") or {}).get("abbreviation"))
        or ((athlete.get("position") or {}).get("name"))
        or ((athlete_entry.get("position") or {}).get("abbreviation"))
        or athlete_entry.get("position")
    )
    headshot = athlete.get("headshot")
    if isinstance(headshot, dict):
        headshot_url = headshot.get("href")
    else:
        headshot_url = headshot

    players_by_id[player_id] = {
        "id": player_id,
        "full_name": full_name or f"Unknown-{player_id}",
        "jersey_number": jersey_number,
        "position": position,
        "headshot_url": headshot_url,
        "team_id": team_id or None,
    }

    raw_stats = athlete_entry.get("stats") or athlete_entry.get("statistics") or []
    stat_map = build_player_stat_map(raw_stats=raw_stats, stat_keys=stat_keys)
    flat_map = build_normalized_flat_map(athlete_entry, athlete)
    value_map = {**stat_map, **flat_map}
    did_not_play = infer_dnp(athlete_entry=athlete_entry, stat_map=stat_map)
    reason = athlete_entry.get("reason") or athlete_entry.get("didNotPlayReason")

    if did_not_play:
        minutes = 0
        points = 0
        assists = 0
        turnovers = 0
        steals = 0
        blocks = 0
        rebounds = 0
        offensive_rebounds = 0
        defensive_rebounds = 0
        fouls = 0
        plus_minus = 0
        fg_made = 0
        fg_attempted = 0
        three_ptr_made = 0
        three_ptr_attempted = 0
        ft_made = 0
        ft_attempted = 0
    else:
        minutes = parse_minutes(first_present(value_map, ["minutes", "min"]))
        points = safe_int(first_present(value_map, ["points", "pts"]))
        assists = safe_int(first_present(value_map, ["assists", "ast"]))
        turnovers = safe_int(first_present(value_map, ["turnovers", "to", "tov"]))
        steals = safe_int(first_present(value_map, ["steals", "stl"]))
        blocks = safe_int(first_present(value_map, ["blocks", "blk"]))
        rebounds = safe_int(first_present(value_map, ["rebounds", "reb", "totalRebounds"]))
        offensive_rebounds = safe_int(
            first_present(value_map, ["offensiveRebounds", "oreb", "offReb"])
        )
        defensive_rebounds = safe_int(
            first_present(value_map, ["defensiveRebounds", "dreb", "defReb"])
        )
        if defensive_rebounds is None:
            if rebounds is not None and offensive_rebounds is not None:
                defensive_rebounds = max(rebounds - offensive_rebounds, 0)
        if rebounds is None and offensive_rebounds is not None and defensive_rebounds is not None:
            rebounds = offensive_rebounds + defensive_rebounds
        fouls = safe_int(first_present(value_map, ["fouls", "pf", "personalFouls"]))
        plus_minus = parse_plus_minus(first_present(value_map, ["plusMinus", "+/-", "plusminus"]))
        fg_made, fg_attempted, three_ptr_made, three_ptr_attempted, ft_made, ft_attempted = (
            parse_player_shooting_splits(value_map=value_map)
        )

    player_stats_by_pk[(player_id, game_id)] = {
        "player_id": player_id,
        "game_id": game_id,
        "starter": bool_or_default(athlete_entry.get("starter"), default=False),
        "did_not_play": did_not_play,
        "reason": reason,
        "ejected": bool_or_default(athlete_entry.get("ejected"), default=False),
        "minutes": minutes,
        "points": points,
        "assists": assists,
        "turnovers": turnovers,
        "steals": steals,
        "blocks": blocks,
        "rebounds": rebounds,
        "offensive_rebounds": offensive_rebounds,
        "defensive_rebounds": defensive_rebounds,
        "fouls": fouls,
        "plusMinus": plus_minus,
        "fgMade": fg_made,
        "fgAttempted": fg_attempted,
        "threePtrMade": three_ptr_made,
        "threePtrAttempted": three_ptr_attempted,
        "ftMade": ft_made,
        "ftAttempted": ft_attempted,
    }


def parse_players_and_stats(summary: dict[str, Any], game_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    players_by_id: dict[str, dict[str, Any]] = {}
    player_stats_by_pk: dict[tuple[str, str], dict[str, Any]] = {}
    boxscore = summary.get("boxscore") or {}

    player_blocks = boxscore.get("players")
    if isinstance(player_blocks, list):
        parse_player_team_blocks(
            blocks=player_blocks,
            game_id=game_id,
            players_by_id=players_by_id,
            player_stats_by_pk=player_stats_by_pk,
        )

    parse_boxscore_team_athletes(
        summary=summary,
        game_id=game_id,
        players_by_id=players_by_id,
        player_stats_by_pk=player_stats_by_pk,
    )

    return list(players_by_id.values()), list(player_stats_by_pk.values())


def collect_team_stat_map(stat_list: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for item in stat_list:
        if not isinstance(item, dict):
            continue
        value = item.get("displayValue")
        if value is None:
            value = item.get("value")
        aliases = [
            item.get("name"),
            item.get("abbreviation"),
            item.get("displayName"),
            item.get("shortDisplayName"),
            item.get("label"),
        ]
        for alias in aliases:
            key = normalize_key(alias)
            if key:
                stats[key] = value
    return stats


def build_team_statistics_row(
    team_id: str,
    game_id: str,
    stat_map: dict[str, Any],
    schema_mode: str,
) -> dict[str, Any]:
    fg_made, fg_attempted = parse_made_attempted(first_present(stat_map, TEAM_STAT_CANDIDATES["field_goals"]))
    three_made, three_attempted = parse_made_attempted(
        first_present(stat_map, TEAM_STAT_CANDIDATES["three_point_field_goals"])
    )
    ft_made, ft_attempted = parse_made_attempted(first_present(stat_map, TEAM_STAT_CANDIDATES["free_throws"]))

    parsed = {
        "field_goal_percentage": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["field_goal_percentage"])),
        "three_point_percentage": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["three_point_percentage"])),
        "free_throw_percentage": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["free_throw_percentage"])),
        "total_rebounds": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["total_rebounds"])),
        "offensive_rebounds": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["offensive_rebounds"])),
        "defensive_rebounds": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["defensive_rebounds"])),
        "assists": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["assists"])),
        "steals": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["steals"])),
        "blocks": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["blocks"])),
        "turnovers": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["turnovers"])),
        "team_turnovers": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["team_turnovers"])),
        "total_turnovers": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["total_turnovers"])),
        "technical_fouls": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["technical_fouls"])),
        "total_technical_fouls": safe_int(
            first_present(stat_map, TEAM_STAT_CANDIDATES["total_technical_fouls"])
        ),
        "flagrant_fouls": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["flagrant_fouls"])),
        "turnover_points": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["turnover_points"])),
        "fast_break_points": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["fast_break_points"])),
        "points_in_paint": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["points_in_paint"])),
        "fouls": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["fouls"])),
        "largest_lead": safe_int(first_present(stat_map, TEAM_STAT_CANDIDATES["largest_lead"])),
    }

    missing = [key for key, value in parsed.items() if value is None]
    if missing:
        LOGGER.info("Team %s missing team stats: %s", team_id, ", ".join(missing))

    largest_lead = parsed["largest_lead"] if parsed["largest_lead"] is not None else 0
    column_map = TEAM_STAT_DB_COLUMNS[schema_mode]
    row: dict[str, Any] = {"team_id": team_id, "game_id": game_id}

    row[column_map["fg_made"]] = fg_made if fg_made is not None else 0
    row[column_map["field_goal_percentage"]] = parsed["field_goal_percentage"]
    row[column_map["three_point_fg_made"]] = three_made if three_made is not None else 0
    row[column_map["three_point_fg_percentage"]] = parsed["three_point_percentage"]
    row[column_map["free_throws_made"]] = ft_made if ft_made is not None else 0
    row[column_map["free_throw_percentage"]] = parsed["free_throw_percentage"]
    row[column_map["total_rebounds"]] = parsed["total_rebounds"]
    row[column_map["offensive_rebounds"]] = parsed["offensive_rebounds"]
    row[column_map["defensive_rebounds"]] = parsed["defensive_rebounds"]
    row[column_map["assists"]] = parsed["assists"]
    row[column_map["steals"]] = parsed["steals"]
    row[column_map["blocks"]] = parsed["blocks"]
    row[column_map["turnovers"]] = parsed["turnovers"]
    row[column_map["team_turnovers"]] = parsed["team_turnovers"]
    row[column_map["total_turnovers"]] = parsed["total_turnovers"]
    row[column_map["technical_fouls"]] = parsed["technical_fouls"]
    row[column_map["total_technical_fouls"]] = parsed["total_technical_fouls"]
    row[column_map["flagrant_fouls"]] = parsed["flagrant_fouls"]
    row[column_map["turnover_points"]] = parsed["turnover_points"]
    row[column_map["fast_break_points"]] = parsed["fast_break_points"]
    row[column_map["points_in_paint"]] = parsed["points_in_paint"]
    row[column_map["fouls"]] = parsed["fouls"]
    row[column_map["largest_lead"]] = largest_lead

    if schema_mode == "snake":
        row[column_map["fg_attempted"]] = fg_attempted
        row[column_map["three_point_fg_attempted"]] = three_attempted
        row[column_map["free_throws_attempted"]] = ft_attempted
    elif fg_attempted is not None or three_attempted is not None or ft_attempted is not None:
        LOGGER.info(
            "SCHEMA_MODE=quoted stores only made values for combined made-attempted columns."
        )
    return row


def parse_team_statistics(
    summary: dict[str, Any],
    game_id: str,
    schema_mode: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    boxscore = summary.get("boxscore") or {}
    for team_block in boxscore.get("teams") or []:
        if not isinstance(team_block, dict):
            continue
        team = team_block.get("team") or {}
        team_id = str(team.get("id") or "").strip()
        if not team_id:
            continue
        stat_map = collect_team_stat_map(team_block.get("statistics") or [])
        row = build_team_statistics_row(
            team_id=team_id,
            game_id=game_id,
            stat_map=stat_map,
            schema_mode=schema_mode,
        )
        rows.append(row)
    return rows


def dedupe_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if value is not None:
            deduped[str(value)] = row
    return list(deduped.values())


def init_supabase(settings: Settings) -> Client:
    try:
        return create_client(settings.supabase_url, settings.supabase_service_role_key)
    except Exception as exc:
        raise RuntimeError(f"Failed to initialize Supabase client: {exc}") from exc


def upsert_rows(
    client: Client,
    table: str,
    rows: list[dict[str, Any]],
    conflict_target: str,
    schema_mode: str,
) -> None:
    if not rows:
        LOGGER.info("No rows to upsert for table %s", table)
        return
    try:
        response = client.table(table).upsert(rows, on_conflict=conflict_target).execute()
        returned = len(response.data) if getattr(response, "data", None) else 0
        LOGGER.info("Upserted %s rows into %s (response rows: %s)", len(rows), table, returned)
    except Exception as exc:
        error_text = str(exc)
        if table == "team_statistics" and ("column" in error_text.lower() and "does not exist" in error_text.lower()):
            suggested = "snake" if schema_mode == "quoted" else "quoted"
            LOGGER.warning(
                "Upsert failed for team_statistics due to missing columns. "
                "Current SCHEMA_MODE=%s. Try SCHEMA_MODE=%s. Error: %s",
                schema_mode,
                suggested,
                error_text,
            )
        raise RuntimeError(f"Upsert failed for {table}: {exc}") from exc


def is_team_stats_schema_error(error_text: str) -> bool:
    text = error_text.lower()
    return (
        "pgrst204" in text
        or ("could not find the" in text and "column" in text and "team_statistics" in text)
        or ("column" in text and "does not exist" in text and "team_statistics" in text)
    )


def print_dry_run_preview(table: str, rows: list[dict[str, Any]]) -> None:
    LOGGER.info("[DRY_RUN] Table %s would upsert %s row(s).", table, len(rows))
    for idx, row in enumerate(rows[:2], start=1):
        LOGGER.info("[DRY_RUN] %s sample row %s: %s", table, idx, json.dumps(row, default=str))


def parse_all_rows(summary: dict[str, Any], source_url: str, schema_mode: str) -> dict[str, list[dict[str, Any]]]:
    competition = get_competition(summary)
    teams, home_team, away_team = build_teams_from_competitors(competition)
    if not teams:
        teams = build_teams_from_boxscore(summary)

    event_id = (
        parse_event_id_from_url(source_url)
        or str(competition.get("id") or "").strip()
        or str((summary.get("header") or {}).get("id") or "").strip()
    )
    if not event_id:
        raise RuntimeError("Could not determine game/event id from URL or ESPN JSON.")

    game_row = build_game_row(
        summary=summary,
        competition=competition,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        teams=teams,
    )
    players, player_stats = parse_players_and_stats(summary=summary, game_id=event_id)
    team_stats = parse_team_statistics(summary=summary, game_id=event_id, schema_mode=schema_mode)

    return {
        "teams": dedupe_rows(teams, key="id"),
        "games": [game_row],
        "players": dedupe_rows(players, key="id"),
        "player_game_stats": player_stats,
        "team_statistics": team_stats,
    }


def run_sync(settings: Settings) -> None:
    LOGGER.info("Fetching ESPN summary from %s", settings.espn_summary_url)
    summary = fetch_espn_summary(
        url=settings.espn_summary_url,
        timeout_seconds=settings.timeout_seconds,
        retry_attempts=settings.retry_attempts,
    )

    parsed = parse_all_rows(
        summary=summary,
        source_url=settings.espn_summary_url,
        schema_mode=settings.schema_mode,
    )

    if settings.dry_run:
        LOGGER.info("DRY_RUN=true, no database writes will occur.")
        print_dry_run_preview("teams", parsed["teams"])
        print_dry_run_preview("games", parsed["games"])
        print_dry_run_preview("players", parsed["players"])
        print_dry_run_preview("player_game_stats", parsed["player_game_stats"])
        print_dry_run_preview("team_statistics", parsed["team_statistics"])
        return

    client = init_supabase(settings)
    upsert_rows(
        client=client,
        table="teams",
        rows=parsed["teams"],
        conflict_target="id",
        schema_mode=settings.schema_mode,
    )
    upsert_rows(
        client=client,
        table="games",
        rows=parsed["games"],
        conflict_target="id",
        schema_mode=settings.schema_mode,
    )
    upsert_rows(
        client=client,
        table="players",
        rows=parsed["players"],
        conflict_target="id",
        schema_mode=settings.schema_mode,
    )
    upsert_rows(
        client=client,
        table="player_game_stats",
        rows=parsed["player_game_stats"],
        conflict_target="player_id,game_id",
        schema_mode=settings.schema_mode,
    )
    try:
        upsert_rows(
            client=client,
            table="team_statistics",
            rows=parsed["team_statistics"],
            conflict_target="team_id,game_id",
            schema_mode=settings.schema_mode,
        )
    except RuntimeError as exc:
        if not is_team_stats_schema_error(str(exc)):
            raise
        alternate_mode = "quoted" if settings.schema_mode == "snake" else "snake"
        game_id = str(parsed["games"][0]["id"])
        LOGGER.warning(
            "Retrying team_statistics upsert with SCHEMA_MODE=%s (configured mode was %s).",
            alternate_mode,
            settings.schema_mode,
        )
        alternate_rows = parse_team_statistics(
            summary=summary,
            game_id=game_id,
            schema_mode=alternate_mode,
        )
        upsert_rows(
            client=client,
            table="team_statistics",
            rows=alternate_rows,
            conflict_target="team_id,game_id",
            schema_mode=alternate_mode,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch ESPN NBA summary JSON and upsert to Supabase tables."
    )
    parser.add_argument(
        "--url",
        help="Override ESPN summary URL.",
    )
    parser.add_argument(
        "--dry-run",
        choices=["true", "false"],
        help="Override DRY_RUN env var.",
    )
    parser.add_argument(
        "--game-id",
        help="Override ESPN event id. If omitted, script prompts for it.",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    dry_run_override = str_to_bool(args.dry_run) if args.dry_run is not None else None
    try:
        settings = load_settings(url_override=args.url, dry_run_override=dry_run_override)
        settings.espn_summary_url = resolve_summary_url_with_prompt(
            base_url=settings.espn_summary_url,
            cli_game_id=args.game_id,
        )
        run_sync(settings)
    except Exception as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
