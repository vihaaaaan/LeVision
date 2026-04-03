from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Optional
from zoneinfo import ZoneInfo

from supabase import Client, create_client

from .espn_client import (
    create_http_session,
    fetch_espn_summary,
    find_recent_team_events,
    find_team_events_in_date_range,
    find_team_event_ids_for_date,
    is_final_status,
    parse_espn_datetime_utc,
    set_event_id_in_url,
    to_eastern,
)
from .espn_parser import get_play_by_play_from_summary, parse_all_rows, parse_team_statistics
from .settings import Settings, load_settings

LOGGER = logging.getLogger("nba_pipeline.data_service")
LOCAL_TZ = ZoneInfo("America/New_York")


class EntityResolutionError(ValueError):
    """Base error for backend entity resolution."""


class EntityNotFoundError(EntityResolutionError):
    def __init__(self, entity_type: str, query: str):
        super().__init__(f"Could not resolve {entity_type} '{query}'")
        self.entity_type = entity_type
        self.query = query


class EntityAmbiguityError(EntityResolutionError):
    def __init__(self, entity_type: str, query: str, candidates: list[str]):
        super().__init__(f"Ambiguous {entity_type} '{query}'")
        self.entity_type = entity_type
        self.query = query
        self.candidates = candidates


STAT_ALIASES: dict[str, str] = {
    "points": "points",
    "point": "points",
    "pts": "points",
    "assists": "assists",
    "assist": "assists",
    "ast": "assists",
    "rebounds": "rebounds",
    "rebound": "rebounds",
    "reb": "rebounds",
    "rebs": "rebounds",
    "steals": "steals",
    "stl": "steals",
    "blocks": "blocks",
    "blk": "blocks",
    "turnovers": "turnovers",
    "turnover": "turnovers",
    "to": "turnovers",
    "minutes": "minutes",
    "mins": "minutes",
    "min": "minutes",
    "fouls": "fouls",
    "plusminus": "plusMinus",
    "plus_minus": "plusMinus",
    "+/-": "plusMinus",
    "plus": "plusMinus",
    "fgmade": "fgMade",
    "fgattempted": "fgAttempted",
    "threeptrmade": "threePtrMade",
    "threeptrattempted": "threePtrAttempted",
    "ftmade": "ftMade",
    "ftattempted": "ftAttempted",
}

STAT_FRIENDLY_LABELS: dict[str, str] = {
    "points": "points",
    "assists": "assists",
    "rebounds": "rebounds",
    "steals": "steals",
    "blocks": "blocks",
    "turnovers": "turnovers",
    "minutes": "minutes",
    "fouls": "fouls",
    "plusMinus": "plus/minus",
    "fgMade": "field goals made",
    "fgAttempted": "field goals attempted",
    "threePtrMade": "three-pointers made",
    "threePtrAttempted": "three-pointers attempted",
    "ftMade": "free throws made",
    "ftAttempted": "free throws attempted",
}


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def clean_entity_query(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"['’]s\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.!?\"'")
    return text


def similarity_score(query: str, candidate: str) -> float:
    query_norm = normalize_text(query)
    candidate_norm = normalize_text(candidate)
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0
    if candidate_norm.startswith(query_norm) or query_norm in candidate_norm:
        return 0.92
    if query_norm.startswith(candidate_norm):
        return 0.88
    return SequenceMatcher(None, query_norm, candidate_norm).ratio()


def parse_target_date(target_date: date | datetime | str) -> date:
    if isinstance(target_date, datetime):
        if target_date.tzinfo is None:
            target_date = target_date.replace(tzinfo=LOCAL_TZ)
        return target_date.astimezone(LOCAL_TZ).date()
    if isinstance(target_date, date):
        return target_date

    text = str(target_date or "").strip()
    if not text:
        raise ValueError("target_date is required")

    lower = text.lower()
    today = datetime.now(LOCAL_TZ).date()
    if lower == "today":
        return today
    if lower == "yesterday":
        return today - timedelta(days=1)

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
        "%B %d",
        "%b %d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=today.year)
                if parsed.date() > today + timedelta(days=1):
                    parsed = parsed.replace(year=today.year - 1)
            return parsed.date()
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {target_date}")


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
        if table == "team_statistics" and (
            "column" in error_text.lower() and "does not exist" in error_text.lower()
        ):
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
        or (
            "could not find the" in text
            and "column" in text
            and "team_statistics" in text
        )
        or (
            "column" in text
            and "does not exist" in text
            and "team_statistics" in text
        )
    )


class DataService:
    """Deterministic retrieval layer: Supabase-first with ESPN JSON fallback."""

    def __init__(self, settings: Optional[Settings] = None, client: Optional[Client] = None):
        self.settings = settings or load_settings()
        self.client = client or init_supabase(self.settings)
        self._teams_cache: Optional[list[dict[str, Any]]] = None
        self._players_cache: Optional[list[dict[str, Any]]] = None
        self._espn_session = create_http_session(retry_attempts=self.settings.retry_attempts)

    def __del__(self) -> None:
        session = getattr(self, "_espn_session", None)
        if session is None:
            return
        try:
            session.close()
        except Exception:
            return

    def _load_teams(self) -> list[dict[str, Any]]:
        if self._teams_cache is None:
            response = (
                self.client.table("teams")
                .select("id,location,name,abbreviation,color,alternate_color")
                .execute()
            )
            self._teams_cache = [row for row in (response.data or []) if isinstance(row, dict)]
        return self._teams_cache

    def _load_players(self) -> list[dict[str, Any]]:
        if self._players_cache is None:
            response = (
                self.client.table("players")
                .select("id,full_name,team_id,position,jersey_number")
                .execute()
            )
            self._players_cache = [row for row in (response.data or []) if isinstance(row, dict)]
        return self._players_cache

    def _invalidate_caches(self) -> None:
        self._teams_cache = None
        self._players_cache = None

    def _team_by_id(self, team_id: str) -> Optional[dict[str, Any]]:
        team_id_str = str(team_id)
        for team in self._load_teams():
            if str(team.get("id")) == team_id_str:
                return team
        return None

    def _current_local_time(self) -> datetime:
        return datetime.now(LOCAL_TZ)

    def _parse_datetime_to_local(self, value: Any) -> Optional[datetime]:
        utc_dt = parse_espn_datetime_utc(value)
        if utc_dt is not None:
            return to_eastern(utc_dt)

        text = str(value or "").strip()
        if not text:
            return None

        candidate = text
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TZ)
        return parsed.astimezone(LOCAL_TZ)

    def _normalize_game_date_for_storage(self, value: Any) -> Optional[str]:
        local_dt = self._parse_datetime_to_local(value)
        if local_dt is None:
            return None
        return local_dt.isoformat()

    def _team_label(
        self,
        team_id: Optional[str],
        fallback_teams: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[str]:
        if not team_id:
            return None

        team_id_str = str(team_id)
        team = self._team_by_id(team_id_str)
        if not team and fallback_teams:
            for row in fallback_teams:
                if not isinstance(row, dict):
                    continue
                if str(row.get("id") or "") == team_id_str:
                    team = row
                    break
        if not team:
            return None

        abbr = str(team.get("abbreviation") or "").strip()
        if abbr:
            return abbr.upper()
        location = str(team.get("location") or "").strip()
        name = str(team.get("name") or "").strip()
        full = f"{location} {name}".strip()
        if full:
            return full
        return None

    def _best_match(
        self,
        query: str,
        candidates: list[tuple[dict[str, Any], list[str]]],
        threshold: float,
    ) -> Optional[dict[str, Any]]:
        best_item: Optional[dict[str, Any]] = None
        best_score = 0.0

        for item, names in candidates:
            score = 0.0
            for candidate in names:
                score = max(score, similarity_score(query, candidate))
            if score > best_score:
                best_score = score
                best_item = item

        if not best_item or best_score < threshold:
            return None
        return best_item

    def resolve_team(self, team_query: str) -> dict[str, Any]:
        teams = self._load_teams()
        candidates: list[tuple[dict[str, Any], list[str]]] = []
        query_clean = normalize_text(team_query)

        for team in teams:
            location = str(team.get("location") or "").strip()
            name = str(team.get("name") or "").strip()
            abbr = str(team.get("abbreviation") or "").strip()
            names = [
                abbr,
                location,
                name,
                f"{location} {name}".strip(),
                f"{location}{name}".strip(),
            ]
            candidates.append((team, [n for n in names if n]))

        exact_matches: list[dict[str, Any]] = []
        for team, names in candidates:
            for candidate in names:
                if normalize_text(candidate) == query_clean:
                    exact_matches.append(team)
                    break

        if len(exact_matches) == 1:
            match = exact_matches[0]
        elif len(exact_matches) > 1:
            labels = [
                f"{str(item.get('location') or '').strip()} {str(item.get('name') or '').strip()}".strip()
                or str(item.get("abbreviation") or "")
                for item in exact_matches[:5]
            ]
            raise EntityAmbiguityError("team", team_query, labels)
        else:
            scored: list[tuple[float, dict[str, Any], str]] = []
            for team, names in candidates:
                best_name = ""
                best_score = 0.0
                for candidate in names:
                    score = similarity_score(team_query, candidate)
                    if score > best_score:
                        best_score = score
                        best_name = candidate
                scored.append((best_score, team, best_name))
            scored.sort(key=lambda x: x[0], reverse=True)
            if not scored or scored[0][0] < 0.82:
                raise EntityNotFoundError("team", team_query)

            top_score = scored[0][0]
            close = [item for item in scored if top_score - item[0] <= 0.03 and item[0] >= 0.82]
            if len(close) > 1:
                labels = [
                    f"{str(item[1].get('location') or '').strip()} {str(item[1].get('name') or '').strip()}".strip()
                    or str(item[1].get("abbreviation") or "")
                    for item in close[:5]
                ]
                raise EntityAmbiguityError("team", team_query, labels)
            match = scored[0][1]

        return {
            "id": str(match.get("id")),
            "abbreviation": str(match.get("abbreviation") or "").upper(),
            "location": match.get("location"),
            "name": match.get("name"),
        }

    def resolve_player_and_team(self, player_query: str) -> dict[str, Any]:
        players = self._load_players()
        player_query = clean_entity_query(player_query)
        query_clean = normalize_text(player_query)

        candidates: list[tuple[dict[str, Any], list[str]]] = []
        for player in players:
            full_name = str(player.get("full_name") or "").strip()
            tokens = [token for token in full_name.split() if token]
            aliases = [full_name]
            if tokens:
                aliases.append(tokens[0])
                aliases.append(tokens[-1])
                aliases.append("".join(tokens))
                aliases.append(f"{tokens[0]} {tokens[-1]}")
            candidates.append((player, aliases))

        exact_matches: list[dict[str, Any]] = []
        for player, aliases in candidates:
            normalized_aliases = [normalize_text(alias) for alias in aliases if alias]
            if query_clean in normalized_aliases:
                exact_matches.append(player)

        if len(exact_matches) == 1:
            match = exact_matches[0]
        elif len(exact_matches) > 1:
            labels = [str(item.get("full_name") or "") for item in exact_matches[:8]]
            raise EntityAmbiguityError("player", player_query, labels)
        else:
            scored: list[tuple[float, dict[str, Any]]] = []
            for player, aliases in candidates:
                best_score = 0.0
                for alias in aliases:
                    best_score = max(best_score, similarity_score(player_query, alias))
                scored.append((best_score, player))

            scored.sort(key=lambda x: x[0], reverse=True)
            if not scored or scored[0][0] < 0.86:
                raise EntityNotFoundError("player", player_query)

            top_score = scored[0][0]
            close = [item for item in scored if top_score - item[0] <= 0.025 and item[0] >= 0.84]
            if len(close) > 1:
                labels = [str(item[1].get("full_name") or "") for item in close[:8]]
                raise EntityAmbiguityError("player", player_query, labels)
            match = scored[0][1]

        team = None
        if match.get("team_id"):
            team = self._team_by_id(str(match.get("team_id")))

        return {
            "player_id": str(match.get("id")),
            "full_name": str(match.get("full_name") or ""),
            "team_id": str(match.get("team_id") or "") or None,
            "position": match.get("position"),
            "team": team,
            "team_abbreviation": str((team or {}).get("abbreviation") or "").upper() or None,
        }

    def _games_for_team_from_db(self, team_id: str, limit: int) -> list[dict[str, Any]]:
        columns = "id,date,status,home_team,away_team,home_points,away_points"
        home_resp = (
            self.client.table("games")
            .select(columns)
            .eq("home_team", team_id)
            .order("date", desc=True)
            .limit(limit)
            .execute()
        )
        away_resp = (
            self.client.table("games")
            .select(columns)
            .eq("away_team", team_id)
            .order("date", desc=True)
            .limit(limit)
            .execute()
        )

        deduped: dict[str, dict[str, Any]] = {}
        for row in (home_resp.data or []) + (away_resp.data or []):
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("id") or "").strip()
            if event_id:
                deduped[event_id] = row

        def _sort_key(row: dict[str, Any]) -> str:
            return str(row.get("date") or "")

        return sorted(deduped.values(), key=_sort_key, reverse=True)

    def _discover_recent_team_events(
        self,
        team_abbr: str,
        n: int,
        now_local: datetime,
        windows: Optional[list[int]] = None,
    ) -> list[dict[str, Any]]:
        search_windows = windows or [21, 30, 45]
        discovered: list[dict[str, Any]] = []

        for days_back in search_windows:
            events = find_recent_team_events(
                team_abbr=team_abbr,
                n=max(n * 4, n + 8),
                settings=self.settings,
                days_back=days_back,
                final_only=True,
                now_local=now_local,
            )

            filtered: list[dict[str, Any]] = []
            seen: set[str] = set()
            for event in events:
                event_id = str(event.get("event_id") or "").strip()
                if not event_id or event_id in seen:
                    continue
                local_dt = event.get("event_datetime_local")
                if not isinstance(local_dt, datetime):
                    continue
                if local_dt.tzinfo is None:
                    local_dt = local_dt.replace(tzinfo=LOCAL_TZ)
                local_dt = local_dt.astimezone(LOCAL_TZ)
                if local_dt > now_local:
                    continue
                if not is_final_status(event.get("status")):
                    continue
                seen.add(event_id)
                filtered.append(
                    {
                        "event_id": event_id,
                        "status": str(event.get("status") or ""),
                        "event_datetime_local": local_dt,
                        "event_datetime_utc": event.get("event_datetime_utc"),
                    }
                )

            filtered.sort(key=lambda x: x["event_datetime_local"], reverse=True)
            discovered = filtered
            if len(discovered) >= n:
                break

        return discovered

    def find_recent_team_event_ids(
        self,
        team_id: str,
        team_abbr: str,
        n: int,
        days_back: int = 21,
    ) -> list[str]:
        # Intentionally scoreboard-first for "recent" semantics. We do not trust
        # arbitrary historical DB ordering for last-N requests.
        now_local = self._current_local_time()
        events = self._discover_recent_team_events(
            team_abbr=team_abbr,
            n=n,
            now_local=now_local,
            windows=[days_back, 30, 45],
        )
        return [str(item["event_id"]) for item in events[:n]]

    def _find_team_event_ids_for_date(self, team_id: str, team_abbr: str, target_date: date) -> list[str]:
        start_iso = target_date.strftime("%Y-%m-%d")
        end_iso = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
        columns = "id,date,status,home_team,away_team"

        home_resp = (
            self.client.table("games")
            .select(columns)
            .eq("home_team", team_id)
            .gte("date", start_iso)
            .lt("date", end_iso)
            .order("date", desc=True)
            .execute()
        )
        away_resp = (
            self.client.table("games")
            .select(columns)
            .eq("away_team", team_id)
            .gte("date", start_iso)
            .lt("date", end_iso)
            .order("date", desc=True)
            .execute()
        )

        event_ids: list[str] = []
        seen: set[str] = set()
        for row in (home_resp.data or []) + (away_resp.data or []):
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("id") or "").strip()
            if event_id and event_id not in seen:
                event_ids.append(event_id)
                seen.add(event_id)

        if event_ids:
            return event_ids

        return find_team_event_ids_for_date(
            team_abbr=team_abbr,
            target_date=target_date,
            settings=self.settings,
        )

    def _get_game_row(self, event_id: str) -> Optional[dict[str, Any]]:
        response = (
            self.client.table("games")
            .select("id,date,status,home_team,away_team,home_points,away_points,venue")
            .eq("id", event_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        first = rows[0]
        return first if isinstance(first, dict) else None

    def _get_player_game_stats_row(self, player_id: str, event_id: str) -> Optional[dict[str, Any]]:
        response = (
            self.client.table("player_game_stats")
            .select("*")
            .eq("player_id", player_id)
            .eq("game_id", event_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        first = rows[0]
        return first if isinstance(first, dict) else None

    def _has_team_statistics(self, event_id: str) -> bool:
        response = (
            self.client.table("team_statistics")
            .select("team_id,game_id")
            .eq("game_id", event_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def _parse_row_counts(self, parsed: Optional[dict[str, Any]]) -> dict[str, int]:
        if not isinstance(parsed, dict):
            return {}
        counts: dict[str, int] = {}
        for table_name in ("teams", "games", "players", "player_game_stats", "team_statistics"):
            rows = parsed.get(table_name)
            counts[table_name] = len(rows) if isinstance(rows, list) else 0
        return counts

    def _fetch_summary_for_event(self, event_id: str) -> tuple[str, dict[str, Any]]:
        summary_url = set_event_id_in_url(self.settings.espn_summary_url, event_id)
        summary = fetch_espn_summary(
            url=summary_url,
            timeout_seconds=self.settings.timeout_seconds,
            retry_attempts=self.settings.retry_attempts,
            session=self._espn_session,
        )
        return summary_url, summary

    def ensure_game_ingested(
        self,
        event_id: str,
        required_player_id: Optional[str] = None,
        require_team_stats: bool = False,
        force_refresh: bool = False,
        include_summary: bool = False,
    ) -> dict[str, Any]:
        event_id = str(event_id).strip()
        if not event_id:
            raise ValueError("event_id is required")

        game_row = self._get_game_row(event_id)
        game_exists = game_row is not None
        game_is_final = is_final_status((game_row or {}).get("status"))

        needs_player_stats = False
        if required_player_id:
            stat_row = self._get_player_game_stats_row(required_player_id, event_id)
            needs_player_stats = stat_row is None

        needs_team_stats = require_team_stats and not self._has_team_statistics(event_id)

        fetch_reasons: list[str] = []
        if force_refresh:
            fetch_reasons.append("force_refresh")
        if not game_exists:
            fetch_reasons.append("game_missing")
        if needs_player_stats:
            fetch_reasons.append("required_player_stat_missing")
        if needs_team_stats:
            fetch_reasons.append("required_team_stats_missing")
        if game_exists and not game_is_final:
            fetch_reasons.append("game_not_final")

        should_fetch = bool(fetch_reasons)

        if not should_fetch:
            summary: Optional[dict[str, Any]] = None
            if include_summary:
                _, summary_payload = self._fetch_summary_for_event(event_id)
                summary = summary_payload if isinstance(summary_payload, dict) else None

            LOGGER.info(
                "event_id=%s ingestion=already_exists game_exists=%s final=%s include_summary=%s fetched_summary=%s",
                event_id,
                game_exists,
                game_is_final,
                include_summary,
                isinstance(summary, dict),
            )
            return {
                "event_id": event_id,
                "source": "espn_summary" if isinstance(summary, dict) else "supabase",
                "fetched": isinstance(summary, dict),
                "ingested": False,
                "game_existed": game_exists,
                "fetch_reasons": [],
                "row_counts": {},
                "upsert_results": {},
                "persistence_succeeded": True,
                "persistence_error": None,
                "game": game_row,
                "summary": summary,
                "parsed": None,
            }

        summary_url, summary = self._fetch_summary_for_event(event_id)
        parsed = parse_all_rows(
            summary=summary,
            source_url=summary_url,
            schema_mode=self.settings.schema_mode,
        )
        row_counts = self._parse_row_counts(parsed)
        upsert_results: dict[str, str] = {}
        persistence_succeeded = False
        persistence_error: Optional[str] = None

        for game_row_candidate in parsed.get("games", []):
            if not isinstance(game_row_candidate, dict):
                continue
            normalized = self._normalize_game_date_for_storage(game_row_candidate.get("date"))
            if normalized:
                game_row_candidate["date"] = normalized

        try:
            upsert_rows(
                client=self.client,
                table="teams",
                rows=parsed["teams"],
                conflict_target="id",
                schema_mode=self.settings.schema_mode,
            )
            upsert_results["teams"] = "ok"
            upsert_rows(
                client=self.client,
                table="games",
                rows=parsed["games"],
                conflict_target="id",
                schema_mode=self.settings.schema_mode,
            )
            upsert_results["games"] = "ok"
            upsert_rows(
                client=self.client,
                table="players",
                rows=parsed["players"],
                conflict_target="id",
                schema_mode=self.settings.schema_mode,
            )
            upsert_results["players"] = "ok"
            upsert_rows(
                client=self.client,
                table="player_game_stats",
                rows=parsed["player_game_stats"],
                conflict_target="player_id,game_id",
                schema_mode=self.settings.schema_mode,
            )
            upsert_results["player_game_stats"] = "ok"

            try:
                upsert_rows(
                    client=self.client,
                    table="team_statistics",
                    rows=parsed["team_statistics"],
                    conflict_target="team_id,game_id",
                    schema_mode=self.settings.schema_mode,
                )
                upsert_results["team_statistics"] = "ok"
            except RuntimeError as exc:
                if not is_team_stats_schema_error(str(exc)):
                    raise
                alternate_mode = "quoted" if self.settings.schema_mode == "snake" else "snake"
                alternate_rows = parse_team_statistics(
                    summary=summary,
                    game_id=event_id,
                    schema_mode=alternate_mode,
                )
                upsert_rows(
                    client=self.client,
                    table="team_statistics",
                    rows=alternate_rows,
                    conflict_target="team_id,game_id",
                    schema_mode=alternate_mode,
                )
                upsert_results["team_statistics"] = f"ok(schema_mode={alternate_mode})"
            persistence_succeeded = True
        except RuntimeError as exc:
            persistence_error = str(exc)
            LOGGER.warning(
                "event_id=%s ingestion_failed=true source=espn_summary error=%s",
                event_id,
                persistence_error,
            )
            LOGGER.warning(
                "event_id=%s using in-memory parsed payload for runtime if needed; persistence did not fully complete",
                event_id,
            )

        self._invalidate_caches()
        persisted_game_row = self._get_game_row(event_id=event_id)
        returned_game_row = (
            persisted_game_row
            if isinstance(persisted_game_row, dict)
            else (parsed["games"][0] if parsed.get("games") else None)
        )

        LOGGER.info(
            "event_id=%s ingestion=%s game_existed=%s fetch_reasons=%s parsed_rows=%s upserts=%s persistence_succeeded=%s",
            event_id,
            "newly_ingested" if not game_exists else "refreshed_existing_game",
            game_exists,
            fetch_reasons,
            row_counts,
            upsert_results,
            persistence_succeeded,
        )

        return {
            "event_id": event_id,
            "source": "espn_summary",
            "fetched": True,
            "ingested": persistence_succeeded,
            "game_existed": game_exists,
            "fetch_reasons": fetch_reasons,
            "row_counts": row_counts,
            "upsert_results": upsert_results,
            "persistence_succeeded": persistence_succeeded,
            "persistence_error": persistence_error,
            "game": returned_game_row,
            "summary": summary,
            "parsed": parsed,
        }

    def ensure_game_loaded(
        self,
        event_id: str,
        required_player_id: Optional[str] = None,
        require_team_stats: bool = False,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        return self.ensure_game_ingested(
            event_id=event_id,
            required_player_id=required_player_id,
            require_team_stats=require_team_stats,
            force_refresh=force_refresh,
            include_summary=False,
        )

    def _resolve_stat_field(self, stat_name: str) -> tuple[str, str]:
        key = normalize_text(stat_name)
        field = STAT_ALIASES.get(key)
        if not field:
            raise ValueError(f"Unsupported stat '{stat_name}'")
        return field, STAT_FRIENDLY_LABELS.get(field, field)

    def _extract_stat_value(self, row: dict[str, Any], stat_field: str) -> Any:
        if stat_field in row:
            return row.get(stat_field)

        fallback_map = {
            "plusMinus": ["plusminus", "plus_minus", "plusMinus"],
            "fgMade": ["fgmade", "fg_made", "fgMade"],
            "fgAttempted": ["fgattempted", "fg_attempted", "fgAttempted"],
            "threePtrMade": ["threeptrmade", "three_ptr_made", "threePtrMade"],
            "threePtrAttempted": ["threeptrattempted", "three_ptr_attempted", "threePtrAttempted"],
            "ftMade": ["ftmade", "ft_made", "ftMade"],
            "ftAttempted": ["ftattempted", "ft_attempted", "ftAttempted"],
        }
        candidates = fallback_map.get(stat_field, [])
        for candidate in candidates:
            if candidate in row:
                return row.get(candidate)
        return None

    def _build_game_context(
        self,
        game_row: Optional[dict[str, Any]],
        team_id: Optional[str],
        fallback_teams: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        if not game_row:
            return {}

        home_team = str(game_row.get("home_team") or "")
        away_team = str(game_row.get("away_team") or "")
        is_home = team_id is not None and team_id == home_team
        opponent_id = away_team if is_home else home_team
        opponent = self._team_label(opponent_id, fallback_teams=fallback_teams)
        local_dt = self._parse_datetime_to_local(game_row.get("date"))

        return {
            "date": local_dt.date().isoformat() if local_dt else None,
            "game_datetime_local": local_dt.isoformat() if local_dt else None,
            "status": game_row.get("status"),
            "home_team": home_team,
            "away_team": away_team,
            "home_points": game_row.get("home_points"),
            "away_points": game_row.get("away_points"),
            "opponent": opponent,
            "team_is_home": is_home,
        }

    def _find_player_stat_in_parsed_rows(
        self,
        parsed: Optional[dict[str, Any]],
        player_id: str,
        event_id: str,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(parsed, dict):
            return None
        rows = parsed.get("player_game_stats")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("player_id") or "") != str(player_id):
                continue
            if str(row.get("game_id") or "") != str(event_id):
                continue
            return row
        return None

    def _fetch_games_map(self, event_ids: list[str]) -> dict[str, dict[str, Any]]:
        deduped_ids = [str(event_id) for event_id in dict.fromkeys(event_ids) if str(event_id).strip()]
        if not deduped_ids:
            return {}

        games_map: dict[str, dict[str, Any]] = {}
        chunk_size = 100
        for index in range(0, len(deduped_ids), chunk_size):
            chunk = deduped_ids[index : index + chunk_size]
            response = (
                self.client.table("games")
                .select("id,date,status,home_team,away_team,home_points,away_points,venue,season")
                .in_("id", chunk)
                .execute()
            )
            for row in response.data or []:
                if not isinstance(row, dict):
                    continue
                event_id = str(row.get("id") or "").strip()
                if event_id:
                    games_map[event_id] = row
        return games_map

    def _resolve_player_event_stat_row(
        self,
        player_id: str,
        team_id: str,
        event_id: str,
        stat_field: str,
        now_local: datetime,
        range_start_local: Optional[datetime] = None,
        range_end_local: Optional[datetime] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        load_info: Optional[dict[str, Any]] = None
        source = "supabase"
        used_parsed_fallback = False

        stats_row = self._get_player_game_stats_row(player_id=player_id, event_id=event_id)
        value = self._extract_stat_value(stats_row or {}, stat_field) if stats_row else None
        if stats_row is None or value is None:
            load_info = self.ensure_game_ingested(event_id=event_id, required_player_id=player_id)
            source = str(load_info.get("source") or "espn_summary")
            stats_row = self._get_player_game_stats_row(player_id=player_id, event_id=event_id)
            value = self._extract_stat_value(stats_row or {}, stat_field) if stats_row else None
            if value is None:
                parsed_row = self._find_player_stat_in_parsed_rows(
                    parsed=load_info.get("parsed"),
                    player_id=player_id,
                    event_id=event_id,
                )
                if parsed_row is not None:
                    stats_row = parsed_row
                    value = self._extract_stat_value(parsed_row, stat_field)
                    used_parsed_fallback = True

        if stats_row is None or value is None:
            if isinstance(load_info, dict):
                LOGGER.warning(
                    "event_id=%s answer_source=none source=%s persistence_succeeded=%s persistence_error=%s",
                    event_id,
                    source,
                    bool(load_info.get("persistence_succeeded", True)),
                    load_info.get("persistence_error"),
                )
            return None, source

        game_row = self._get_game_row(event_id=event_id)
        if game_row is None and isinstance(load_info, dict):
            loaded_game = load_info.get("game")
            if isinstance(loaded_game, dict):
                game_row = loaded_game

        fallback_teams = None
        if isinstance(load_info, dict):
            parsed = load_info.get("parsed")
            if isinstance(parsed, dict) and isinstance(parsed.get("teams"), list):
                fallback_teams = [row for row in parsed["teams"] if isinstance(row, dict)]

        context = self._build_game_context(
            game_row=game_row,
            team_id=team_id,
            fallback_teams=fallback_teams,
        )
        opponent = context.get("opponent")
        if not isinstance(opponent, str) or not opponent.strip() or opponent.strip().isdigit():
            return None, source

        if not is_final_status(context.get("status")):
            return None, source

        local_dt = self._parse_datetime_to_local(
            context.get("game_datetime_local") or context.get("date")
        )
        if local_dt is None:
            return None, source
        if local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=LOCAL_TZ)
        local_dt = local_dt.astimezone(LOCAL_TZ)
        if local_dt > now_local:
            return None, source
        if range_start_local and local_dt < range_start_local:
            return None, source
        if range_end_local and local_dt > range_end_local:
            return None, source

        if load_info is None:
            answer_source = "db_only"
        else:
            answer_source = "after_ingestion"
            if used_parsed_fallback:
                answer_source = "after_ingestion_memory_fallback"
        LOGGER.info(
            "event_id=%s answer_source=%s source=%s ingested=%s game_existed=%s persistence_succeeded=%s",
            event_id,
            answer_source,
            source,
            bool(load_info.get("ingested")) if isinstance(load_info, dict) else False,
            bool(load_info.get("game_existed")) if isinstance(load_info, dict) else True,
            bool(load_info.get("persistence_succeeded", True)) if isinstance(load_info, dict) else True,
        )

        return (
            {
                "game_id": event_id,
                "event_id": event_id,
                "date": local_dt.date().isoformat(),
                "game_datetime_local": local_dt.isoformat(),
                "opponent": opponent.strip(),
                "stat_value": value,
                "value": value,
                "status": context.get("status"),
                "home_points": context.get("home_points"),
                "away_points": context.get("away_points"),
            },
            source,
        )

    def _current_season_window(self, now_local: datetime) -> tuple[datetime, datetime, str]:
        if now_local.month >= 10:
            start_year = now_local.year
        else:
            start_year = now_local.year - 1

        season_start = datetime(start_year, 10, 1, 0, 0, 0, tzinfo=LOCAL_TZ)
        season_end = datetime(start_year + 1, 7, 1, 0, 0, 0, tzinfo=LOCAL_TZ) - timedelta(seconds=1)
        season_label = f"{start_year}-{str(start_year + 1)[-2:]}"
        return season_start, min(season_end, now_local), season_label

    def get_player_last_n_games_stat(
        self,
        player_query: str,
        stat_name: str,
        n: int,
    ) -> dict[str, Any]:
        if n <= 0:
            raise ValueError("n must be > 0")

        resolved = self.resolve_player_and_team(player_query)
        player_id = resolved["player_id"]
        team_id = resolved.get("team_id")
        team_abbr = resolved.get("team_abbreviation")
        if not team_id or not team_abbr:
            raise ValueError(
                f"Player '{resolved['full_name']}' is missing a current team mapping in Supabase"
            )

        now_local = self._current_local_time()
        stat_field, stat_label = self._resolve_stat_field(stat_name)
        recent_events = self._discover_recent_team_events(
            team_abbr=team_abbr,
            n=n,
            now_local=now_local,
            windows=[21, 30, 45],
        )
        event_ids = [str(item["event_id"]) for item in recent_events]

        LOGGER.debug(
            "last_n resolve player=%s(%s) team=%s now_local=%s stat=%s requested_n=%s",
            resolved["full_name"],
            player_id,
            team_abbr,
            now_local.isoformat(),
            stat_field,
            n,
        )
        LOGGER.debug(
            "last_n discovered events=%s details=%s",
            event_ids,
            [
                {
                    "event_id": str(item.get("event_id")),
                    "status": str(item.get("status") or ""),
                    "event_datetime_local": (
                        item.get("event_datetime_local").isoformat()
                        if isinstance(item.get("event_datetime_local"), datetime)
                        else None
                    ),
                }
                for item in recent_events
            ],
        )

        games: list[dict[str, Any]] = []
        sources: set[str] = set()
        seen_event_ids: set[str] = set()
        event_lookup = {str(item["event_id"]): item for item in recent_events}

        for event_id in event_ids:
            if event_id in seen_event_ids:
                LOGGER.debug("last_n skipping duplicate event_id=%s", event_id)
                continue
            seen_event_ids.add(event_id)

            event_meta = event_lookup.get(event_id) or {}
            event_status = str(event_meta.get("status") or "")
            if not is_final_status(event_status):
                LOGGER.debug("last_n skipping non-final event_id=%s status=%s", event_id, event_status)
                continue

            event_local_dt = event_meta.get("event_datetime_local")
            if not isinstance(event_local_dt, datetime):
                LOGGER.debug("last_n skipping malformed event datetime event_id=%s", event_id)
                continue
            if event_local_dt.tzinfo is None:
                event_local_dt = event_local_dt.replace(tzinfo=LOCAL_TZ)
            event_local_dt = event_local_dt.astimezone(LOCAL_TZ)
            if event_local_dt > now_local:
                LOGGER.debug(
                    "last_n skipping future event_id=%s event_local=%s now_local=%s",
                    event_id,
                    event_local_dt.isoformat(),
                    now_local.isoformat(),
                )
                continue

            load_info: Optional[dict[str, Any]] = None
            stats_row = self._get_player_game_stats_row(player_id=player_id, event_id=event_id)
            value = self._extract_stat_value(stats_row or {}, stat_field) if stats_row else None
            used_parsed_fallback = False

            if stats_row is None or value is None:
                load_info = self.ensure_game_ingested(
                    event_id=event_id,
                    required_player_id=player_id,
                    require_team_stats=False,
                )
                sources.add(str(load_info.get("source") or "espn_summary"))
                stats_row = self._get_player_game_stats_row(player_id=player_id, event_id=event_id)
                value = self._extract_stat_value(stats_row or {}, stat_field) if stats_row else None
                if value is None:
                    parsed_row = self._find_player_stat_in_parsed_rows(
                        parsed=load_info.get("parsed"),
                        player_id=player_id,
                        event_id=event_id,
                    )
                    if parsed_row is not None:
                        stats_row = parsed_row
                        value = self._extract_stat_value(parsed_row, stat_field)
                        used_parsed_fallback = True
                LOGGER.debug(
                    "last_n event_id=%s source=espn_fallback value=%s",
                    event_id,
                    value,
                )
            else:
                sources.add("supabase")
                LOGGER.debug(
                    "last_n event_id=%s source=supabase value=%s",
                    event_id,
                    value,
                )

            if stats_row is None or value is None:
                if isinstance(load_info, dict):
                    LOGGER.warning(
                        "event_id=%s query=last_n answer_source=none source=%s persistence_succeeded=%s persistence_error=%s",
                        event_id,
                        load_info.get("source"),
                        bool(load_info.get("persistence_succeeded", True)),
                        load_info.get("persistence_error"),
                    )
                continue

            if load_info is None:
                LOGGER.info("event_id=%s query=last_n answer_source=db_only", event_id)
            else:
                answer_source = "after_ingestion_memory_fallback" if used_parsed_fallback else "after_ingestion"
                LOGGER.info(
                    "event_id=%s query=last_n answer_source=%s source=%s ingested=%s game_existed=%s persistence_succeeded=%s",
                    event_id,
                    answer_source,
                    load_info.get("source"),
                    bool(load_info.get("ingested")),
                    bool(load_info.get("game_existed")),
                    bool(load_info.get("persistence_succeeded", True)),
                )

            game_row = self._get_game_row(event_id=event_id)
            if game_row is None and isinstance(load_info, dict):
                loaded_game = load_info.get("game") if isinstance(load_info, dict) else None
                if isinstance(loaded_game, dict):
                    game_row = loaded_game
            fallback_teams = None
            if isinstance(load_info, dict):
                parsed = load_info.get("parsed")
                if isinstance(parsed, dict):
                    teams = parsed.get("teams")
                    if isinstance(teams, list):
                        fallback_teams = [row for row in teams if isinstance(row, dict)]

            context = self._build_game_context(
                game_row=game_row,
                team_id=team_id,
                fallback_teams=fallback_teams,
            )
            opponent = context.get("opponent")
            if not isinstance(opponent, str) or not opponent.strip() or opponent.strip().isdigit():
                LOGGER.debug(
                    "last_n skipping unresolved opponent event_id=%s opponent=%s",
                    event_id,
                    opponent,
                )
                continue

            context_local_dt = self._parse_datetime_to_local(
                context.get("game_datetime_local") or context.get("date")
            )
            local_dt = context_local_dt or event_local_dt
            if local_dt is None:
                LOGGER.debug("last_n skipping malformed local date event_id=%s", event_id)
                continue
            if local_dt > now_local:
                LOGGER.debug("last_n skipping local date in future event_id=%s", event_id)
                continue

            games.append(
                {
                    "game_id": event_id,
                    "event_id": event_id,
                    "date": local_dt.date().isoformat(),
                    "game_datetime_local": local_dt.isoformat(),
                    "opponent": opponent.strip(),
                    "stat_value": value,
                    "value": value,
                    "status": context.get("status"),
                }
            )
            if len(games) >= n:
                break

        games.sort(
            key=lambda row: self._parse_datetime_to_local(row.get("game_datetime_local"))
            or datetime(1970, 1, 1, tzinfo=LOCAL_TZ),
            reverse=True,
        )

        LOGGER.debug("last_n final rows=%s", games[:n])

        return {
            "player": {
                "id": player_id,
                "name": resolved["full_name"],
                "team_id": team_id,
                "team_abbreviation": team_abbr,
            },
            "stat": {
                "requested": stat_name,
                "field": stat_field,
                "label": stat_label,
            },
            "now_local": now_local.isoformat(),
            "requested_games": n,
            "returned_games": len(games[:n]),
            "games": games[:n],
            "sources": sorted(sources),
        }

    def get_player_stat_log_for_date_range(
        self,
        player_query: str,
        stat_name: str,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
        before_now: bool = True,
        discover_scoreboard: bool = True,
    ) -> dict[str, Any]:
        resolved = self.resolve_player_and_team(player_query)
        player_id = resolved["player_id"]
        team_id = resolved.get("team_id")
        team_abbr = resolved.get("team_abbreviation")
        if not team_id or not team_abbr:
            raise ValueError(
                f"Player '{resolved['full_name']}' is missing a current team mapping in Supabase"
            )

        stat_field, stat_label = self._resolve_stat_field(stat_name)
        start_day = parse_target_date(start_date)
        end_day = parse_target_date(end_date)
        if end_day < start_day:
            raise ValueError("end_date must be on or after start_date")

        now_local = self._current_local_time()
        range_start_local = datetime(
            start_day.year,
            start_day.month,
            start_day.day,
            0,
            0,
            0,
            tzinfo=LOCAL_TZ,
        )
        range_end_local = datetime(
            end_day.year,
            end_day.month,
            end_day.day,
            23,
            59,
            59,
            tzinfo=LOCAL_TZ,
        )
        if before_now:
            range_end_local = min(range_end_local, now_local)

        discovered_event_ids: list[str] = []
        if discover_scoreboard:
            team_events = find_team_events_in_date_range(
                team_abbr=team_abbr,
                start_date=start_day,
                end_date=end_day,
                settings=self.settings,
                final_only=True,
                now_local=now_local,
            )
            discovered_event_ids = [str(item["event_id"]) for item in team_events]

        pgs_response = (
            self.client.table("player_game_stats")
            .select("game_id")
            .eq("player_id", player_id)
            .execute()
        )
        db_game_ids = [str(row.get("game_id")) for row in (pgs_response.data or []) if isinstance(row, dict)]
        games_map = self._fetch_games_map(db_game_ids)

        db_range_ids: list[str] = []
        for game_id, game_row in games_map.items():
            local_dt = self._parse_datetime_to_local(game_row.get("date"))
            if local_dt is None:
                continue
            if local_dt.tzinfo is None:
                local_dt = local_dt.replace(tzinfo=LOCAL_TZ)
            local_dt = local_dt.astimezone(LOCAL_TZ)
            if local_dt < range_start_local or local_dt > range_end_local:
                continue
            if not is_final_status(game_row.get("status")):
                continue
            db_range_ids.append(game_id)

        if not discover_scoreboard and not db_range_ids:
            recent_seed_events = self._discover_recent_team_events(
                team_abbr=team_abbr,
                n=120,
                now_local=now_local,
                windows=[21, 30, 45],
            )
            for event in recent_seed_events:
                event_id = str(event.get("event_id") or "").strip()
                if not event_id:
                    continue
                event_local = event.get("event_datetime_local")
                if not isinstance(event_local, datetime):
                    continue
                if event_local.tzinfo is None:
                    event_local = event_local.replace(tzinfo=LOCAL_TZ)
                event_local = event_local.astimezone(LOCAL_TZ)
                if event_local < range_start_local or event_local > range_end_local:
                    continue
                discovered_event_ids.append(event_id)

        candidate_event_ids = list(dict.fromkeys(discovered_event_ids + db_range_ids))
        LOGGER.debug(
            "range_log resolve player=%s(%s) team=%s start=%s end=%s candidate_event_ids=%s",
            resolved["full_name"],
            player_id,
            team_abbr,
            range_start_local.isoformat(),
            range_end_local.isoformat(),
            candidate_event_ids,
        )

        games: list[dict[str, Any]] = []
        sources: set[str] = set()
        seen_ids: set[str] = set()
        unresolved_event_ids: list[str] = []
        for event_id in candidate_event_ids:
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            row, source = self._resolve_player_event_stat_row(
                player_id=player_id,
                team_id=team_id,
                event_id=event_id,
                stat_field=stat_field,
                now_local=now_local,
                range_start_local=range_start_local,
                range_end_local=range_end_local,
            )
            sources.add(source or "supabase")
            if row is None:
                unresolved_event_ids.append(event_id)
                continue
            games.append(row)

        games.sort(
            key=lambda row: self._parse_datetime_to_local(row.get("game_datetime_local"))
            or datetime(1970, 1, 1, tzinfo=LOCAL_TZ),
            reverse=True,
        )

        return {
            "player": {
                "id": player_id,
                "name": resolved["full_name"],
                "team_id": team_id,
                "team_abbreviation": team_abbr,
            },
            "stat": {
                "requested": stat_name,
                "field": stat_field,
                "label": stat_label,
            },
            "scope": {
                "type": "date_range",
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "before_now": before_now,
            },
            "returned_games": len(games),
            "games": games,
            "sources": sorted(sources),
            "event_ids": {
                "discovered": list(dict.fromkeys(discovered_event_ids)),
                "db_range": list(dict.fromkeys(db_range_ids)),
                "candidates": list(dict.fromkeys(candidate_event_ids)),
                "unresolved": unresolved_event_ids,
            },
        }

    def get_player_season_stat_log(
        self,
        player_query: str,
        stat_name: str,
        season: str = "current",
    ) -> dict[str, Any]:
        now_local = self._current_local_time()
        season_text = str(season or "current").strip().lower()

        if season_text == "current":
            season_start_local, season_end_local, season_label = self._current_season_window(now_local)
        else:
            match = re.fullmatch(r"(\d{4})(?:-(\d{2}|\d{4}))?", season_text)
            if not match:
                raise ValueError("season must be 'current' or like '2025-26'")
            start_year = int(match.group(1))
            season_start_local = datetime(start_year, 10, 1, 0, 0, 0, tzinfo=LOCAL_TZ)
            season_end_local = datetime(start_year + 1, 7, 1, 0, 0, 0, tzinfo=LOCAL_TZ) - timedelta(seconds=1)
            season_end_local = min(season_end_local, now_local)
            season_label = f"{start_year}-{str(start_year + 1)[-2:]}"

        result = self.get_player_stat_log_for_date_range(
            player_query=player_query,
            stat_name=stat_name,
            start_date=season_start_local.date().isoformat(),
            end_date=season_end_local.date().isoformat(),
            before_now=True,
            discover_scoreboard=True,
        )

        event_ids = result.get("event_ids") if isinstance(result.get("event_ids"), dict) else {}
        candidate_event_ids = event_ids.get("candidates") if isinstance(event_ids, dict) else []
        unresolved_event_ids = event_ids.get("unresolved") if isinstance(event_ids, dict) else []
        candidate_count = len(candidate_event_ids) if isinstance(candidate_event_ids, list) else 0
        returned_games = int(result.get("returned_games") or 0)

        if candidate_count >= 25 and returned_games <= 1:
            raise RuntimeError(
                "Season data appears incomplete after backfill attempt. "
                "Try again shortly or run a dedicated season sync."
            )

        if candidate_count >= 40 and isinstance(unresolved_event_ids, list) and len(unresolved_event_ids) > 20:
            raise RuntimeError(
                "Season query could not resolve enough player game rows; data completeness is insufficient."
            )

        return result | {
            "season": season_label,
            "scope": {"type": "season", "season": season_label},
        }

    def get_player_game_stat_by_date(
        self,
        player_query: str,
        stat_name: str,
        target_date: date | datetime | str,
    ) -> dict[str, Any]:
        resolved = self.resolve_player_and_team(player_query)
        player_id = resolved["player_id"]
        team_id = resolved.get("team_id")
        team_abbr = resolved.get("team_abbreviation")
        if not team_id or not team_abbr:
            raise ValueError(
                f"Player '{resolved['full_name']}' is missing a current team mapping in Supabase"
            )

        stat_field, stat_label = self._resolve_stat_field(stat_name)
        target_day = parse_target_date(target_date)
        now_local = self._current_local_time()

        event_ids = self._find_team_event_ids_for_date(
            team_id=team_id,
            team_abbr=team_abbr,
            target_date=target_day,
        )
        LOGGER.debug(
            "by_date resolve player=%s(%s) team=%s target_date=%s now_local=%s events=%s",
            resolved["full_name"],
            player_id,
            team_abbr,
            target_day.isoformat(),
            now_local.isoformat(),
            event_ids,
        )
        if not event_ids:
            return {
                "player": {
                    "id": player_id,
                    "name": resolved["full_name"],
                    "team_id": team_id,
                    "team_abbreviation": team_abbr,
                },
                "stat": {
                    "requested": stat_name,
                    "field": stat_field,
                    "label": stat_label,
                },
                "target_date": target_day.isoformat(),
                "result": None,
                "sources": ["supabase", "espn_scoreboard"],
            }

        sources: set[str] = set()
        for event_id in event_ids:
            load_info: Optional[dict[str, Any]] = None
            stats_row = self._get_player_game_stats_row(player_id=player_id, event_id=event_id)
            value = self._extract_stat_value(stats_row or {}, stat_field) if stats_row else None
            used_parsed_fallback = False
            if stats_row is None or value is None:
                load_info = self.ensure_game_ingested(event_id=event_id, required_player_id=player_id)
                sources.add(str(load_info.get("source") or "espn_summary"))
                stats_row = self._get_player_game_stats_row(player_id=player_id, event_id=event_id)
                value = self._extract_stat_value(stats_row or {}, stat_field) if stats_row else None
                if value is None:
                    parsed_row = self._find_player_stat_in_parsed_rows(
                        parsed=load_info.get("parsed"),
                        player_id=player_id,
                        event_id=event_id,
                    )
                    if parsed_row is not None:
                        stats_row = parsed_row
                        value = self._extract_stat_value(parsed_row, stat_field)
                        used_parsed_fallback = True
                LOGGER.debug(
                    "by_date event_id=%s source=espn_fallback value=%s",
                    event_id,
                    value,
                )
            else:
                sources.add("supabase")
                LOGGER.debug(
                    "by_date event_id=%s source=supabase value=%s",
                    event_id,
                    value,
                )

            if stats_row is None or value is None:
                if isinstance(load_info, dict):
                    LOGGER.warning(
                        "event_id=%s query=by_date answer_source=none source=%s persistence_succeeded=%s persistence_error=%s",
                        event_id,
                        load_info.get("source"),
                        bool(load_info.get("persistence_succeeded", True)),
                        load_info.get("persistence_error"),
                    )
                continue

            if load_info is None:
                LOGGER.info("event_id=%s query=by_date answer_source=db_only", event_id)
            else:
                answer_source = "after_ingestion_memory_fallback" if used_parsed_fallback else "after_ingestion"
                LOGGER.info(
                    "event_id=%s query=by_date answer_source=%s source=%s ingested=%s game_existed=%s persistence_succeeded=%s",
                    event_id,
                    answer_source,
                    load_info.get("source"),
                    bool(load_info.get("ingested")),
                    bool(load_info.get("game_existed")),
                    bool(load_info.get("persistence_succeeded", True)),
                )

            game_row = self._get_game_row(event_id=event_id)
            if game_row is None and isinstance(load_info, dict):
                loaded_game = load_info.get("game") if isinstance(load_info, dict) else None
                if isinstance(loaded_game, dict):
                    game_row = loaded_game

            fallback_teams = None
            if isinstance(load_info, dict):
                parsed = load_info.get("parsed")
                if isinstance(parsed, dict):
                    teams = parsed.get("teams")
                    if isinstance(teams, list):
                        fallback_teams = [row for row in teams if isinstance(row, dict)]

            context = self._build_game_context(
                game_row=game_row,
                team_id=team_id,
                fallback_teams=fallback_teams,
            )
            opponent = context.get("opponent")
            if not isinstance(opponent, str) or not opponent.strip() or opponent.strip().isdigit():
                LOGGER.debug(
                    "by_date skipping unresolved opponent event_id=%s opponent=%s",
                    event_id,
                    opponent,
                )
                continue

            local_dt = self._parse_datetime_to_local(
                context.get("game_datetime_local") or context.get("date")
            )
            if local_dt is None or local_dt > now_local:
                LOGGER.debug("by_date skipping malformed/future date event_id=%s", event_id)
                continue

            return {
                "player": {
                    "id": player_id,
                    "name": resolved["full_name"],
                    "team_id": team_id,
                    "team_abbreviation": team_abbr,
                },
                "stat": {
                    "requested": stat_name,
                    "field": stat_field,
                    "label": stat_label,
                },
                "target_date": target_day.isoformat(),
                "result": {
                    "game_id": event_id,
                    "event_id": event_id,
                    "date": local_dt.date().isoformat(),
                    "game_datetime_local": local_dt.isoformat(),
                    "opponent": opponent.strip(),
                    "stat_value": value,
                    "value": value,
                    "status": context.get("status"),
                },
                "sources": sorted(sources),
            }

        return {
            "player": {
                "id": player_id,
                "name": resolved["full_name"],
                "team_id": team_id,
                "team_abbreviation": team_abbr,
            },
            "stat": {
                "requested": stat_name,
                "field": stat_field,
                "label": stat_label,
            },
            "target_date": target_day.isoformat(),
            "result": None,
            "sources": sorted(sources),
        }

    def get_player_game_stat_by_event_id(
        self,
        player_query: str,
        stat_name: str,
        event_id: str,
    ) -> dict[str, Any]:
        resolved = self.resolve_player_and_team(player_query)
        player_id = resolved["player_id"]
        team_id = resolved.get("team_id")
        team_abbr = resolved.get("team_abbreviation")
        if not team_id or not team_abbr:
            raise ValueError(
                f"Player '{resolved['full_name']}' is missing a current team mapping in Supabase"
            )

        normalized_event_id = str(event_id).strip()
        if not normalized_event_id:
            raise ValueError("event_id is required")

        stat_field, stat_label = self._resolve_stat_field(stat_name)
        now_local = self._current_local_time()

        row, source = self._resolve_player_event_stat_row(
            player_id=player_id,
            team_id=team_id,
            event_id=normalized_event_id,
            stat_field=stat_field,
            now_local=now_local,
        )
        sources = [source] if source else []

        return {
            "player": {
                "id": player_id,
                "name": resolved["full_name"],
                "team_id": team_id,
                "team_abbreviation": team_abbr,
            },
            "stat": {
                "requested": stat_name,
                "field": stat_field,
                "label": stat_label,
            },
            "event_id": normalized_event_id,
            "result": row,
            "sources": sorted(set(sources)),
        }

    def get_team_recent_games(self, team_query: str, n: int) -> dict[str, Any]:
        if n <= 0:
            raise ValueError("n must be > 0")

        team = self.resolve_team(team_query)
        team_id = str(team["id"])
        team_abbr = str(team["abbreviation"])
        now_local = self._current_local_time()
        recent_events = self._discover_recent_team_events(
            team_abbr=team_abbr,
            n=n,
            now_local=now_local,
            windows=[30, 45],
        )
        event_ids = [str(item["event_id"]) for item in recent_events]

        games: list[dict[str, Any]] = []
        sources: set[str] = set()
        event_lookup = {str(item["event_id"]): item for item in recent_events}
        for event_id in event_ids:
            game_row = self._get_game_row(event_id)
            load_info: Optional[dict[str, Any]] = None
            used_fallback_game = False
            if game_row is None or not is_final_status(game_row.get("status")):
                load_info = self.ensure_game_ingested(event_id=event_id)
                sources.add(str(load_info.get("source") or "espn_summary"))
                game_row = self._get_game_row(event_id)
                if game_row is None:
                    loaded_game = load_info.get("game") if isinstance(load_info, dict) else None
                    if isinstance(loaded_game, dict):
                        game_row = loaded_game
                        used_fallback_game = True
                fallback_teams = None
                if isinstance(load_info, dict):
                    parsed = load_info.get("parsed")
                    if isinstance(parsed, dict) and isinstance(parsed.get("teams"), list):
                        fallback_teams = [row for row in parsed["teams"] if isinstance(row, dict)]
            else:
                sources.add("supabase")
                fallback_teams = None

            context = self._build_game_context(
                game_row=game_row,
                team_id=team_id,
                fallback_teams=fallback_teams,
            )
            opponent = context.get("opponent")
            if not isinstance(opponent, str) or not opponent.strip() or opponent.strip().isdigit():
                continue

            local_dt = self._parse_datetime_to_local(
                context.get("game_datetime_local") or context.get("date")
            )
            if local_dt is None:
                meta_local = event_lookup.get(event_id, {}).get("event_datetime_local")
                if isinstance(meta_local, datetime):
                    local_dt = meta_local.astimezone(LOCAL_TZ)
            if local_dt is None or local_dt > now_local:
                continue

            if load_info is None:
                LOGGER.info("event_id=%s query=team_recent_games answer_source=db_only", event_id)
            else:
                answer_source = "after_ingestion_memory_fallback" if used_fallback_game else "after_ingestion"
                LOGGER.info(
                    "event_id=%s query=team_recent_games answer_source=%s source=%s ingested=%s game_existed=%s persistence_succeeded=%s",
                    event_id,
                    answer_source,
                    load_info.get("source"),
                    bool(load_info.get("ingested")),
                    bool(load_info.get("game_existed")),
                    bool(load_info.get("persistence_succeeded", True)),
                )

            games.append(
                {
                    "game_id": event_id,
                    "event_id": event_id,
                    "date": local_dt.date().isoformat(),
                    "game_datetime_local": local_dt.isoformat(),
                    "opponent": opponent.strip(),
                    "status": context.get("status"),
                    "home_points": context.get("home_points"),
                    "away_points": context.get("away_points"),
                }
            )

        return {
            "team": team,
            "requested_games": n,
            "returned_games": len(games),
            "games": games,
            "sources": sorted(sources),
        }

    def get_game_play_by_play(
        self,
        team_name: Optional[str] = None,
        event_id: Optional[str] = None,
        target_date: Optional[date | datetime | str] = None,
    ) -> dict[str, Any]:
        resolved_team: Optional[dict[str, Any]] = None
        resolved_event_id = str(event_id).strip() if event_id else ""

        if not resolved_event_id:
            if not team_name:
                raise ValueError("team_name or event_id is required for play-by-play")

            resolved_team = self.resolve_team(team_name)
            team_id = str(resolved_team["id"])
            team_abbr = str(resolved_team["abbreviation"])

            if target_date is not None:
                event_ids = self._find_team_event_ids_for_date(
                    team_id=team_id,
                    team_abbr=team_abbr,
                    target_date=parse_target_date(target_date),
                )
            else:
                event_ids = self.find_recent_team_event_ids(
                    team_id=team_id,
                    team_abbr=team_abbr,
                    n=1,
                    days_back=10,
                )

            if not event_ids:
                raise ValueError("Could not find a matching game event id")
            resolved_event_id = event_ids[0]

        load_info = self.ensure_game_ingested(event_id=resolved_event_id, include_summary=True)
        summary = load_info.get("summary")

        if not isinstance(summary, dict):
            raise RuntimeError(f"Could not load ESPN summary payload for event_id={resolved_event_id}")

        plays = get_play_by_play_from_summary(summary)
        LOGGER.info(
            "event_id=%s query=play_by_play answer_source=%s ingested=%s game_existed=%s persistence_succeeded=%s",
            resolved_event_id,
            load_info.get("source") if isinstance(load_info, dict) else "espn_summary",
            bool(load_info.get("ingested")) if isinstance(load_info, dict) else False,
            bool(load_info.get("game_existed")) if isinstance(load_info, dict) else False,
            bool(load_info.get("persistence_succeeded", True)) if isinstance(load_info, dict) else True,
        )

        return {
            "event_id": resolved_event_id,
            "team": resolved_team,
            "target_date": parse_target_date(target_date).isoformat()
            if target_date is not None
            else None,
            "play_count": len(plays),
            "plays": plays,
            "source": load_info.get("source") if isinstance(load_info, dict) else "espn_summary",
        }


# Convenience wrappers for direct imports from chat tools.
def get_player_last_n_games_stat(
    player_query: str,
    stat_name: str,
    n: int,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    service = DataService(settings=settings)
    return service.get_player_last_n_games_stat(player_query=player_query, stat_name=stat_name, n=n)


def get_player_game_stat_by_date(
    player_query: str,
    stat_name: str,
    target_date: date | datetime | str,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    service = DataService(settings=settings)
    return service.get_player_game_stat_by_date(
        player_query=player_query,
        stat_name=stat_name,
        target_date=target_date,
    )


def get_player_game_stat_by_event_id(
    player_query: str,
    stat_name: str,
    event_id: str,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    service = DataService(settings=settings)
    return service.get_player_game_stat_by_event_id(
        player_query=player_query,
        stat_name=stat_name,
        event_id=event_id,
    )


def get_team_recent_games(
    team_query: str,
    n: int,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    service = DataService(settings=settings)
    return service.get_team_recent_games(team_query=team_query, n=n)


def get_game_play_by_play(
    team_name: Optional[str] = None,
    event_id: Optional[str] = None,
    target_date: Optional[date | datetime | str] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    service = DataService(settings=settings)
    return service.get_game_play_by_play(team_name=team_name, event_id=event_id, target_date=target_date)
