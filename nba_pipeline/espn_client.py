from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from zoneinfo import ZoneInfo

from .settings import Settings

LOGGER = logging.getLogger("nba_pipeline.espn_client")

SCOREBOARD_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
EASTERN_TZ = ZoneInfo("America/New_York")


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


def fetch_json(
    url: str,
    timeout_seconds: int,
    retry_attempts: int,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    active_session = session or create_http_session(retry_attempts=retry_attempts)
    owns_session = session is None
    try:
        response = active_session.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch ESPN payload: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("ESPN response was not valid JSON.") from exc
    finally:
        if owns_session:
            active_session.close()

    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected ESPN payload type. Expected a JSON object.")
    return payload


def fetch_espn_summary(
    url: str,
    timeout_seconds: int,
    retry_attempts: int,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    return fetch_json(
        url=url,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        session=session,
    )


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
    prompt = (
        f"Enter ESPN game event id [{current_event_id}]: "
        if current_event_id
        else "Enter ESPN game event id: "
    )
    entered = input(prompt).strip()
    if not entered:
        return base_url
    return set_event_id_in_url(base_url, entered)


def _normalize_date_to_scoreboard_format(target_date: date | datetime | str) -> str:
    if isinstance(target_date, datetime):
        return target_date.strftime("%Y%m%d")
    if isinstance(target_date, date):
        return target_date.strftime("%Y%m%d")

    text = str(target_date).strip()
    if not text:
        raise ValueError("date_str cannot be empty")

    cleaned = text.replace("-", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        return cleaned

    parsed_date = datetime.strptime(text, "%Y-%m-%d").date()
    return parsed_date.strftime("%Y%m%d")


def fetch_scoreboard_for_date(
    date_str: str,
    timeout_seconds: int,
    retry_attempts: int,
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    scoreboard_date = _normalize_date_to_scoreboard_format(date_str)
    url = f"{SCOREBOARD_BASE_URL}?dates={scoreboard_date}"
    return fetch_json(
        url=url,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        session=session,
    )


def extract_matching_events(scoreboard: dict[str, Any], team_abbr: str) -> list[dict[str, Any]]:
    team_abbr_norm = str(team_abbr or "").strip().lower()
    matches: list[dict[str, Any]] = []

    for event in scoreboard.get("events", []):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        competitions = event.get("competitions") or []
        if not event_id or not competitions or not isinstance(competitions, list):
            continue

        comp = competitions[0] if competitions else {}
        if not isinstance(comp, dict):
            continue
        competitors = comp.get("competitors") or []
        if not isinstance(competitors, list):
            continue

        found_team = False
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            team = competitor.get("team") or {}
            abbr = str(team.get("abbreviation") or "").strip().lower()
            if abbr == team_abbr_norm:
                found_team = True
                break

        if found_team:
            status_type = (((comp.get("status") or {}).get("type") or {}).get("name")) or ""
            matches.append(
                {
                    "event_id": event_id,
                    "date": event.get("date") or comp.get("date"),
                    "status": status_type,
                    "event": event,
                }
            )

    return matches


def parse_espn_datetime_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    parsed: Optional[datetime] = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            # Accept plain date values as midnight UTC.
            parsed = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def to_eastern(dt_value: datetime) -> datetime:
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(EASTERN_TZ)


def iter_dates_backwards(days_back: int) -> list[str]:
    today = datetime.now(EASTERN_TZ).date()
    return [
        (today - timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(days_back + 1)
    ]


def is_final_status(status: Any) -> bool:
    text = str(status or "").strip().lower()
    return text in {"final", "post", "completed", "status_final"} or "final" in text


def find_recent_team_events(
    team_abbr: str,
    n: int,
    settings: Settings,
    days_back: int = 21,
    final_only: bool = True,
    now_local: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    cutoff_local = now_local or datetime.now(EASTERN_TZ)
    session = create_http_session(retry_attempts=settings.retry_attempts)
    try:
        for date_str in iter_dates_backwards(days_back):
            scoreboard = fetch_scoreboard_for_date(
                date_str=date_str,
                timeout_seconds=settings.timeout_seconds,
                retry_attempts=settings.retry_attempts,
                session=session,
            )
            candidates.extend(extract_matching_events(scoreboard, team_abbr))
    finally:
        session.close()

    deduped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        event_id = str(item.get("event_id") or "").strip()
        if not event_id:
            continue
        if final_only and not is_final_status(item.get("status")):
            continue

        event_dt_utc = parse_espn_datetime_utc(item.get("date"))
        if event_dt_utc is None:
            continue
        event_dt_local = to_eastern(event_dt_utc)
        if event_dt_local > cutoff_local:
            continue

        candidate = {
            "event_id": event_id,
            "status": str(item.get("status") or ""),
            "event_datetime_utc": event_dt_utc,
            "event_datetime_local": event_dt_local,
            "event": item.get("event"),
        }

        current = deduped.get(event_id)
        if current is None or candidate["event_datetime_local"] > current["event_datetime_local"]:
            deduped[event_id] = candidate

    items = list(deduped.values())
    items.sort(key=lambda x: x["event_datetime_local"], reverse=True)
    return items[:n]


def find_recent_team_event_ids(
    team_abbr: str,
    n: int,
    settings: Settings,
    days_back: int = 21,
    final_only: bool = True,
) -> list[str]:
    items = find_recent_team_events(
        team_abbr=team_abbr,
        n=n,
        settings=settings,
        days_back=days_back,
        final_only=final_only,
        now_local=datetime.now(EASTERN_TZ),
    )
    return [str(item["event_id"]) for item in items]


def find_team_event_ids_for_date(
    team_abbr: str,
    target_date: date | datetime | str,
    settings: Settings,
) -> list[str]:
    date_str = _normalize_date_to_scoreboard_format(target_date)
    session = create_http_session(retry_attempts=settings.retry_attempts)
    try:
        scoreboard = fetch_scoreboard_for_date(
            date_str=date_str,
            timeout_seconds=settings.timeout_seconds,
            retry_attempts=settings.retry_attempts,
            session=session,
        )
    finally:
        session.close()
    matches = extract_matching_events(scoreboard, team_abbr)
    decorated: list[tuple[datetime, str]] = []
    for item in matches:
        event_id = str(item.get("event_id") or "").strip()
        if not event_id:
            continue
        event_dt_utc = parse_espn_datetime_utc(item.get("date"))
        if event_dt_utc is None:
            continue
        decorated.append((to_eastern(event_dt_utc), event_id))

    decorated.sort(key=lambda x: x[0], reverse=True)
    return [event_id for _, event_id in decorated]


def iter_dates_between(start_date: date, end_date: date) -> list[str]:
    if start_date > end_date:
        return []
    total_days = (end_date - start_date).days
    return [
        (start_date + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(total_days + 1)
    ]


def find_team_events_in_date_range(
    team_abbr: str,
    start_date: date,
    end_date: date,
    settings: Settings,
    final_only: bool = True,
    now_local: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    cutoff_local = now_local or datetime.now(EASTERN_TZ)
    candidates: list[dict[str, Any]] = []
    session = create_http_session(retry_attempts=settings.retry_attempts)
    try:
        for date_str in iter_dates_between(start_date, end_date):
            scoreboard = fetch_scoreboard_for_date(
                date_str=date_str,
                timeout_seconds=settings.timeout_seconds,
                retry_attempts=settings.retry_attempts,
                session=session,
            )
            candidates.extend(extract_matching_events(scoreboard, team_abbr))
    finally:
        session.close()

    deduped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        event_id = str(item.get("event_id") or "").strip()
        if not event_id:
            continue
        if final_only and not is_final_status(item.get("status")):
            continue

        event_dt_utc = parse_espn_datetime_utc(item.get("date"))
        if event_dt_utc is None:
            continue
        event_dt_local = to_eastern(event_dt_utc)
        if event_dt_local > cutoff_local:
            continue

        existing = deduped.get(event_id)
        candidate = {
            "event_id": event_id,
            "status": str(item.get("status") or ""),
            "event_datetime_utc": event_dt_utc,
            "event_datetime_local": event_dt_local,
            "event": item.get("event"),
        }
        if existing is None or candidate["event_datetime_local"] > existing["event_datetime_local"]:
            deduped[event_id] = candidate

    items = list(deduped.values())
    items.sort(key=lambda x: x["event_datetime_local"], reverse=True)
    return items
