from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re
from typing import Any, Literal, Optional

Intent = Literal["stat_query", "play_by_play_query", "game_lookup"]
EntityType = Literal["player", "team", "game"]
Operation = Literal[
    "game_log",
    "max_single_game",
    "min_single_game",
    "average",
    "sum",
    "latest_game",
    "play_by_play",
]
ScopeType = Literal["recent_games", "season", "date", "date_range", "specific_game"]
StatName = Literal[
    "points",
    "assists",
    "rebounds",
    "steals",
    "blocks",
    "turnovers",
    "minutes",
    "fouls",
    "plus_minus",
]


ALLOWED_INTENTS = {"stat_query", "play_by_play_query", "game_lookup"}
ALLOWED_ENTITY_TYPES = {"player", "team", "game"}
ALLOWED_OPERATIONS = {
    "game_log",
    "max_single_game",
    "min_single_game",
    "average",
    "sum",
    "latest_game",
    "play_by_play",
}
ALLOWED_SCOPE_TYPES = {"recent_games", "season", "date", "date_range", "specific_game"}
ALLOWED_STATS = {
    "points",
    "assists",
    "rebounds",
    "steals",
    "blocks",
    "turnovers",
    "minutes",
    "fouls",
    "plus_minus",
}

STAT_SYNONYMS: dict[str, str] = {
    "point": "points",
    "pts": "points",
    "scoring": "points",
    "score": "points",
    "assist": "assists",
    "ast": "assists",
    "rebound": "rebounds",
    "reb": "rebounds",
    "stl": "steals",
    "blk": "blocks",
    "turnover": "turnovers",
    "to": "turnovers",
    "minute": "minutes",
    "min": "minutes",
    "pf": "fouls",
    "plusminus": "plus_minus",
    "plus_minus": "plus_minus",
    "+/-": "plus_minus",
}

OPERATION_SYNONYMS: dict[str, str] = {
    "highest": "max_single_game",
    "max": "max_single_game",
    "season_high": "max_single_game",
    "lowest": "min_single_game",
    "min": "min_single_game",
    "mean": "average",
    "total": "sum",
    "latest": "latest_game",
}


@dataclass(slots=True)
class QueryScope:
    type: ScopeType
    count: Optional[int] = None
    season: Optional[str] = None
    date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    before_now: Optional[bool] = None
    game_id: Optional[str] = None


@dataclass(slots=True)
class StructuredQuery:
    intent: Intent
    entity_type: EntityType
    player: Optional[str]
    team: Optional[str]
    stat: Optional[StatName]
    operation: Operation
    scope: QueryScope

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_entity_name(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"['’]s\b", "", text, flags=re.IGNORECASE)
    text = text.strip(" ,.!?\"'")
    return text or None


def _normalize_stat(stat_value: Any) -> Optional[str]:
    if stat_value is None:
        return None
    text = _normalize_text(stat_value)
    if not text:
        return None
    text = text.replace(" ", "_")
    text = STAT_SYNONYMS.get(text, text)
    return text


def _normalize_operation(operation_value: Any) -> str:
    text = _normalize_text(operation_value)
    text = text.replace(" ", "_")
    return OPERATION_SYNONYMS.get(text, text)


def _normalize_scope_type(scope_type: Any) -> str:
    text = _normalize_text(scope_type)
    text = text.replace(" ", "_")
    return text


def _require_date(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"scope.{field} is required")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"scope.{field} must be YYYY-MM-DD") from exc
    return text


def _to_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = _normalize_text(value)
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def parse_structured_query(data: dict[str, Any]) -> StructuredQuery:
    if not isinstance(data, dict):
        raise ValueError("Planner output must be a JSON object")

    intent = _normalize_text(data.get("intent"))
    if intent not in ALLOWED_INTENTS:
        raise ValueError(f"Unsupported intent '{intent}'")

    entity_type = _normalize_text(data.get("entity_type"))
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise ValueError(f"Unsupported entity_type '{entity_type}'")

    player = _normalize_entity_name(data.get("player"))
    team = _normalize_entity_name(data.get("team"))

    stat_raw = _normalize_stat(data.get("stat"))
    stat: Optional[str] = stat_raw
    if intent == "stat_query":
        if stat not in ALLOWED_STATS:
            raise ValueError(f"Unsupported stat '{stat_raw}'")
    else:
        stat = None

    operation = _normalize_operation(data.get("operation"))
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(f"Unsupported operation '{operation}'")

    scope_input = data.get("scope") or {}
    if not isinstance(scope_input, dict):
        raise ValueError("scope must be an object")

    scope_type = _normalize_scope_type(scope_input.get("type"))
    if scope_type not in ALLOWED_SCOPE_TYPES:
        raise ValueError(f"Unsupported scope.type '{scope_type}'")

    count = None
    raw_count = scope_input.get("count")
    if raw_count is not None and str(raw_count).strip() != "":
        try:
            count = int(raw_count)
        except (TypeError, ValueError) as exc:
            raise ValueError("scope.count must be an integer") from exc
        if count <= 0:
            raise ValueError("scope.count must be > 0")

    season = str(scope_input.get("season") or "").strip() or None
    date = str(scope_input.get("date") or "").strip() or None
    start_date = str(scope_input.get("start_date") or "").strip() or None
    end_date = str(scope_input.get("end_date") or "").strip() or None
    before_now = _to_optional_bool(scope_input.get("before_now"))
    game_id = str(scope_input.get("game_id") or "").strip() or None

    if scope_type == "recent_games":
        if count is None:
            raise ValueError("scope.count is required for recent_games")
        if before_now is None:
            before_now = True

    if scope_type == "season":
        season = season or "current"

    if scope_type == "date":
        date = _require_date(date, "date")

    if scope_type == "date_range":
        start_date = _require_date(start_date, "start_date")
        end_date = _require_date(end_date, "end_date")

    if scope_type == "specific_game" and not game_id:
        raise ValueError("scope.game_id is required for specific_game")

    if intent == "stat_query" and entity_type != "player":
        # Keep executor deterministic and narrow for now.
        raise ValueError("stat_query currently requires entity_type='player'")

    if intent == "play_by_play_query":
        operation = "play_by_play"
        stat = None

    if intent == "play_by_play_query" and not team and not game_id and scope_type != "specific_game":
        raise ValueError("play_by_play_query needs team or scope.game_id")

    return StructuredQuery(
        intent=intent,
        entity_type=entity_type,
        player=player,
        team=team,
        stat=stat,  # type: ignore[arg-type]
        operation=operation,  # type: ignore[arg-type]
        scope=QueryScope(
            type=scope_type,  # type: ignore[arg-type]
            count=count,
            season=season,
            date=date,
            start_date=start_date,
            end_date=end_date,
            before_now=before_now,
            game_id=game_id,
        ),
    )


def coerce_structured_query(data: dict[str, Any]) -> StructuredQuery:
    if not isinstance(data, dict):
        data = {}

    scope_input = data.get("scope")
    if not isinstance(scope_input, dict):
        scope_input = {}

    raw_count = scope_input.get("count")
    count: Optional[int]
    try:
        count = int(raw_count) if raw_count is not None and str(raw_count).strip() != "" else None
    except (TypeError, ValueError):
        count = None

    player_value = data.get("player")
    if player_value is None:
        player_value = data.get("name")
    if player_value is None:
        player_value = data.get("player_name")

    team_value = data.get("team")
    if team_value is None:
        team_value = data.get("team_name")

    return StructuredQuery(
        intent=_normalize_text(data.get("intent")) or "stat_query",  # type: ignore[arg-type]
        entity_type=_normalize_text(data.get("entity_type")) or "player",  # type: ignore[arg-type]
        player=_normalize_entity_name(player_value),
        team=_normalize_entity_name(team_value),
        stat=_normalize_stat(data.get("stat")),  # type: ignore[arg-type]
        operation=_normalize_operation(data.get("operation")),  # type: ignore[arg-type]
        scope=QueryScope(
            type=_normalize_scope_type(scope_input.get("type")) or "recent_games",  # type: ignore[arg-type]
            count=count,
            season=str(scope_input.get("season") or "").strip() or None,
            date=str(scope_input.get("date") or "").strip() or None,
            start_date=str(scope_input.get("start_date") or "").strip() or None,
            end_date=str(scope_input.get("end_date") or "").strip() or None,
            before_now=_to_optional_bool(scope_input.get("before_now")),
            game_id=str(scope_input.get("game_id") or "").strip() or None,
        ),
    )


def validate_structured_query(query: StructuredQuery) -> StructuredQuery:
    return parse_structured_query(query.to_dict())
