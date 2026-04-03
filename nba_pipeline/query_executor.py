from __future__ import annotations

from dataclasses import asdict
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .data_service import (
    DataService,
    EntityAmbiguityError,
    EntityNotFoundError,
)
from .query_schema import ALLOWED_OPERATIONS, StructuredQuery
from .settings import Settings

LOGGER = logging.getLogger("nba_pipeline.query_executor")
LOCAL_TZ = ZoneInfo("America/New_York")


def _parse_local_datetime(value: Any) -> Optional[datetime]:
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


def _to_numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value or "").strip()
    if not text:
        return None

    text = text.replace(" ", "")
    if text.startswith("+"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def _sort_games_desc(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _key(row: dict[str, Any]) -> datetime:
        parsed = _parse_local_datetime(row.get("game_datetime_local"))
        if parsed is not None:
            return parsed

        date_text = str(row.get("date") or "").strip()
        if date_text:
            parsed_date = _parse_local_datetime(f"{date_text}T00:00:00-05:00")
            if parsed_date is not None:
                return parsed_date

        return datetime(1970, 1, 1, tzinfo=LOCAL_TZ)

    return sorted(games, key=_key, reverse=True)


def _extract_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("games"), list):
        return [row for row in payload["games"] if isinstance(row, dict)]

    result = payload.get("result")
    if isinstance(result, dict):
        return [result]

    return []


def _aggregate_games(
    operation: str,
    games: list[dict[str, Any]],
) -> dict[str, Any]:
    numeric_rows: list[tuple[dict[str, Any], float]] = []
    for row in games:
        numeric_value = _to_numeric(row.get("stat_value", row.get("value")))
        if numeric_value is None:
            continue
        numeric_rows.append((row, numeric_value))

    if not numeric_rows:
        return {
            "status": "no_data",
            "message": "No numeric stat values were available for the requested scope.",
            "games": games,
        }

    if operation == "sum":
        total = sum(item[1] for item in numeric_rows)
        return {
            "status": "ok",
            "operation": operation,
            "value": total,
            "sample_size": len(numeric_rows),
            "games": [item[0] for item in numeric_rows],
        }

    if operation == "average":
        average = sum(item[1] for item in numeric_rows) / len(numeric_rows)
        return {
            "status": "ok",
            "operation": operation,
            "value": average,
            "sample_size": len(numeric_rows),
            "games": [item[0] for item in numeric_rows],
        }

    if operation == "max_single_game":
        best_row, best_value = max(numeric_rows, key=lambda item: item[1])
        return {
            "status": "ok",
            "operation": operation,
            "value": best_value,
            "sample_size": len(numeric_rows),
            "game": best_row,
        }

    if operation == "min_single_game":
        best_row, best_value = min(numeric_rows, key=lambda item: item[1])
        return {
            "status": "ok",
            "operation": operation,
            "value": best_value,
            "sample_size": len(numeric_rows),
            "game": best_row,
        }

    raise ValueError(f"Unsupported aggregate operation '{operation}'")


def _execute_player_stat_query(
    service: DataService,
    query: StructuredQuery,
) -> dict[str, Any]:
    if not query.player:
        return {
            "status": "error",
            "error_type": "validation",
            "message": "player is required for stat_query",
            "query": query.to_dict(),
        }
    if not query.stat:
        return {
            "status": "error",
            "error_type": "validation",
            "message": "stat is required for stat_query",
            "query": query.to_dict(),
        }

    scope = query.scope
    if scope.type == "recent_games":
        payload = service.get_player_last_n_games_stat(
            player_query=query.player,
            stat_name=query.stat,
            n=scope.count or 1,
        )
    elif scope.type == "date":
        payload = service.get_player_game_stat_by_date(
            player_query=query.player,
            stat_name=query.stat,
            target_date=scope.date or "",
        )
    elif scope.type == "date_range":
        payload = service.get_player_stat_log_for_date_range(
            player_query=query.player,
            stat_name=query.stat,
            start_date=scope.start_date or "",
            end_date=scope.end_date or "",
            before_now=scope.before_now if scope.before_now is not None else True,
        )
    elif scope.type == "season":
        payload = service.get_player_season_stat_log(
            player_query=query.player,
            stat_name=query.stat,
            season=scope.season or "current",
        )
    elif scope.type == "specific_game":
        payload = service.get_player_game_stat_by_event_id(
            player_query=query.player,
            stat_name=query.stat,
            event_id=scope.game_id or "",
        )
    else:
        return {
            "status": "error",
            "error_type": "unsupported_scope",
            "message": f"Unsupported scope.type '{scope.type}' for stat query",
            "query": query.to_dict(),
        }

    games = _sort_games_desc(_extract_games(payload))
    count = scope.count if scope.type == "recent_games" else None
    if count is not None:
        games = games[:count]

    base_response: dict[str, Any] = {
        "status": "ok",
        "result_type": "stat_query",
        "query": query.to_dict(),
        "player": payload.get("player"),
        "stat": payload.get("stat"),
        "scope": payload.get("scope") or asdict(query.scope),
        "sources": payload.get("sources") or [],
    }

    if query.operation == "game_log":
        base_response["operation"] = "game_log"
        base_response["games"] = games
        base_response["returned_games"] = len(games)
        if not games:
            base_response["status"] = "no_data"
            base_response["message"] = "No completed games matched the requested scope."
        return base_response

    if query.operation == "latest_game":
        latest = games[0] if games else None
        base_response["operation"] = "latest_game"
        base_response["game"] = latest
        if latest is None:
            base_response["status"] = "no_data"
            base_response["message"] = "No completed games matched the requested scope."
        return base_response

    if query.operation in {"sum", "average", "max_single_game", "min_single_game"}:
        aggregate = _aggregate_games(query.operation, games)
        if aggregate.get("status") != "ok":
            return {
                **base_response,
                "status": "no_data",
                "operation": query.operation,
                "games": games,
                "message": aggregate.get("message")
                or "No numeric stat values were available for the requested scope.",
            }

        return {
            **base_response,
            "operation": query.operation,
            "aggregate": aggregate,
            "games": games,
        }

    return {
        "status": "error",
        "error_type": "unsupported_operation",
        "message": f"Unsupported operation '{query.operation}' for stat query",
        "query": query.to_dict(),
    }


def _execute_play_by_play_query(service: DataService, query: StructuredQuery) -> dict[str, Any]:
    scope = query.scope
    event_id = scope.game_id if scope.type == "specific_game" else None
    target_date = scope.date if scope.type == "date" else None

    if not event_id and not query.team:
        return {
            "status": "error",
            "error_type": "validation",
            "message": "play_by_play_query requires team or scope.game_id",
            "query": query.to_dict(),
        }

    payload = service.get_game_play_by_play(
        team_name=query.team,
        event_id=event_id,
        target_date=target_date,
    )

    return {
        "status": "ok",
        "result_type": "play_by_play_query",
        "query": query.to_dict(),
        "operation": "play_by_play",
        "result": payload,
    }


def _execute_game_lookup_query(service: DataService, query: StructuredQuery) -> dict[str, Any]:
    scope = query.scope

    if query.entity_type == "team" and scope.type == "recent_games":
        if not query.team:
            return {
                "status": "error",
                "error_type": "validation",
                "message": "team is required for team game_lookup",
                "query": query.to_dict(),
            }
        payload = service.get_team_recent_games(team_query=query.team, n=scope.count or 5)
        return {
            "status": "ok",
            "result_type": "game_lookup",
            "query": query.to_dict(),
            "operation": "game_log",
            "result": payload,
        }

    if query.entity_type == "game" and scope.type == "specific_game" and scope.game_id:
        payload = service.get_game_play_by_play(event_id=scope.game_id)
        return {
            "status": "ok",
            "result_type": "game_lookup",
            "query": query.to_dict(),
            "operation": "specific_game",
            "result": {
                "event_id": payload.get("event_id"),
                "play_count": payload.get("play_count"),
                "source": payload.get("source"),
            },
        }

    return {
        "status": "error",
        "error_type": "unsupported_query",
        "message": "Unsupported game_lookup query shape",
        "query": query.to_dict(),
    }


def execute_structured_query(
    query: StructuredQuery,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    operation = str(getattr(query, "operation", "") or "").strip()
    if not operation:
        return {
            "status": "error",
            "error_type": "validation",
            "message": "Structured query validation failed: operation is required",
            "query": query.to_dict(),
        }
    if operation not in ALLOWED_OPERATIONS:
        return {
            "status": "error",
            "error_type": "validation",
            "message": f"Structured query validation failed: unsupported operation '{operation}'",
            "query": query.to_dict(),
        }

    service = DataService(settings=settings)
    LOGGER.debug(
        "executor route intent=%s operation=%s scope=%s",
        query.intent,
        query.operation,
        query.scope.type,
    )

    try:
        if query.intent == "stat_query":
            return _execute_player_stat_query(service, query)
        if query.intent == "play_by_play_query":
            return _execute_play_by_play_query(service, query)
        if query.intent == "game_lookup":
            return _execute_game_lookup_query(service, query)

        return {
            "status": "error",
            "error_type": "unsupported_intent",
            "message": f"Unsupported intent '{query.intent}'",
            "query": query.to_dict(),
        }
    except EntityAmbiguityError as exc:
        LOGGER.info(
            "Entity ambiguity for query. type=%s query=%s candidates=%s",
            exc.entity_type,
            exc.query,
            exc.candidates,
        )
        return {
            "status": "clarification",
            "error_type": "entity_ambiguity",
            "query": query.to_dict(),
            "entity_type": exc.entity_type,
            "query_text": exc.query,
            "candidates": exc.candidates,
            "message": (
                f"I found multiple {exc.entity_type} matches for '{exc.query}'. "
                "Please clarify which one you mean."
            ),
        }
    except EntityNotFoundError as exc:
        return {
            "status": "error",
            "error_type": "entity_not_found",
            "query": query.to_dict(),
            "entity_type": exc.entity_type,
            "query_text": exc.query,
            "message": str(exc),
        }
    except Exception as exc:
        LOGGER.exception("Structured query execution failed")
        return {
            "status": "error",
            "error_type": "execution_failed",
            "query": query.to_dict(),
            "message": str(exc),
        }
