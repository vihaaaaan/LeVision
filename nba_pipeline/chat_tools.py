from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .data_service import (
    get_game_play_by_play as ds_get_game_play_by_play,
    get_player_game_stat_by_date as ds_get_player_game_stat_by_date,
    get_player_last_n_games_stat as ds_get_player_last_n_games_stat,
    get_team_recent_games as ds_get_team_recent_games,
)
from .query_executor import execute_structured_query
from .query_planner import plan_query, repair_structured_query
from .query_schema import validate_structured_query
from .settings import Settings

LOGGER = logging.getLogger("nba_pipeline.chat_tools")


def get_player_last_n_games_stat(
    player_name: str,
    stat_name: str,
    n: int,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    return ds_get_player_last_n_games_stat(
        player_query=player_name,
        stat_name=stat_name,
        n=n,
        settings=settings,
    )


def get_player_game_stat_by_date(
    player_name: str,
    stat_name: str,
    target_date: str,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    return ds_get_player_game_stat_by_date(
        player_query=player_name,
        stat_name=stat_name,
        target_date=target_date,
        settings=settings,
    )


def get_team_recent_games(
    team_name: str,
    n: int,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    return ds_get_team_recent_games(team_query=team_name, n=n, settings=settings)


def get_game_play_by_play(
    team_name: Optional[str] = None,
    event_id: Optional[str] = None,
    target_date: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    return ds_get_game_play_by_play(
        team_name=team_name,
        event_id=event_id,
        target_date=target_date,
        settings=settings,
    )


def _detect_final_two_only(query: str) -> bool:
    lower = query.lower()
    return "final 2 minute" in lower or "last 2 minute" in lower


def _clock_seconds(play: dict[str, Any]) -> Optional[int]:
    clock = play.get("clock")
    display = None
    if isinstance(clock, dict):
        display = clock.get("displayValue") or clock.get("value")
    elif clock is not None:
        display = clock
    if display is None:
        display = play.get("clockDisplayValue")
    if display is None:
        return None

    text = str(display).strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    return minutes * 60 + seconds


def _filter_final_two_minutes(plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_period = 0
    for play in plays:
        period = play.get("period")
        number = None
        if isinstance(period, dict):
            number = period.get("number")
        elif isinstance(period, int):
            number = period
        if isinstance(number, int):
            max_period = max(max_period, number)

    filtered: list[dict[str, Any]] = []
    for play in plays:
        period = play.get("period")
        number = None
        if isinstance(period, dict):
            number = period.get("number")
        elif isinstance(period, int):
            number = period

        if max_period and isinstance(number, int) and number != max_period:
            continue

        seconds_left = _clock_seconds(play)
        if seconds_left is not None and seconds_left <= 120:
            filtered.append(play)

    return filtered


def _format_stat_game_row(game: dict[str, Any]) -> str:
    date_text = str(game.get("date") or "")[:10] or "unknown-date"
    opponent = str(game.get("opponent") or "UNK")
    value = game.get("stat_value", game.get("value"))
    game_id = game.get("game_id") or game.get("event_id") or "unknown"
    return f"- {date_text} vs {opponent}: {value} (game {game_id})"


def _format_stat_result(payload: dict[str, Any]) -> str:
    player = payload.get("player") or {}
    stat = payload.get("stat") or {}
    player_name = str(player.get("name") or "Player")
    stat_label = str(stat.get("label") or stat.get("field") or "stat")

    operation = str(payload.get("operation") or "")
    if operation == "game_log":
        games = payload.get("games") or []
        if not games:
            return f"I could not find {player_name}'s {stat_label} for that scope."

        lines = [f"{player_name} {stat_label} ({len(games)} games):"]
        for game in games:
            if isinstance(game, dict):
                lines.append(_format_stat_game_row(game))
        return "\n".join(lines)

    if operation == "latest_game":
        game = payload.get("game")
        if not isinstance(game, dict):
            return f"I could not find a latest game for {player_name}."
        return f"Latest game for {player_name} {stat_label}:\n{_format_stat_game_row(game)}"

    if operation in {"sum", "average", "max_single_game", "min_single_game"}:
        aggregate = payload.get("aggregate") or {}
        if not isinstance(aggregate, dict) or aggregate.get("status") != "ok":
            return f"I could not compute {operation} for {player_name} {stat_label}."

        value = aggregate.get("value")
        if operation == "sum":
            sample_size = aggregate.get("sample_size")
            return f"{player_name} total {stat_label}: {value} across {sample_size} games."

        if operation == "average":
            sample_size = aggregate.get("sample_size")
            try:
                numeric_value = float(value)
                rendered = f"{numeric_value:.2f}"
            except (TypeError, ValueError):
                rendered = str(value)
            return f"{player_name} average {stat_label}: {rendered} across {sample_size} games."

        game = aggregate.get("game")
        if not isinstance(game, dict):
            return f"I could not find a {operation} game for {player_name} {stat_label}."

        direction = "highest" if operation == "max_single_game" else "lowest"
        return (
            f"{player_name} {direction} {stat_label} game: {value}\n"
            f"{_format_stat_game_row(game)}"
        )

    return "I could not format this stat response."


def _format_game_lookup_result(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if not isinstance(result, dict):
        return "I could not find matching games."

    team = result.get("team") or {}
    team_label = team.get("abbreviation") or team.get("name") or "Team"
    games = result.get("games") or []
    if not games:
        return f"I could not find recent games for {team_label}."

    lines = [f"Recent games for {team_label}:"]
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = game.get("game_id") or game.get("event_id")
        date_text = str(game.get("date") or "")[:10]
        opponent = game.get("opponent") or "UNK"
        status = game.get("status") or "unknown"
        home_points = game.get("home_points")
        away_points = game.get("away_points")
        score = (
            f"{away_points}-{home_points}"
            if away_points is not None and home_points is not None
            else "N/A"
        )
        lines.append(
            f"- {date_text} vs {opponent} ({status}), score {score}, event {event_id}"
        )

    return "\n".join(lines)


def _format_play_by_play_result(payload: dict[str, Any], final_two_only: bool = False) -> str:
    result = payload.get("result") or {}
    event_id = result.get("event_id")
    plays = result.get("plays") or []
    if not isinstance(plays, list):
        plays = []

    if final_two_only:
        plays = _filter_final_two_minutes([row for row in plays if isinstance(row, dict)])
    else:
        plays = [row for row in plays if isinstance(row, dict)]

    if not plays:
        scope = "final 2 minutes" if final_two_only else "play-by-play"
        return f"I could not find {scope} data for event {event_id}."

    lines = [
        (
            f"Final 2 minutes for event {event_id} (showing up to 25 plays):"
            if final_two_only
            else f"Play-by-play for event {event_id} (showing up to 25 plays):"
        )
    ]

    for play in plays[:25]:
        text = play.get("text") or play.get("shortText") or "(no text)"
        clock = None
        period = None

        if isinstance(play.get("clock"), dict):
            clock = play["clock"].get("displayValue")
        if isinstance(play.get("period"), dict):
            period = play["period"].get("number")

        prefix = ""
        if period is not None:
            prefix += f"Q{period} "
        if clock:
            prefix += f"{clock} "
        lines.append(f"- {prefix.strip()} {text}".strip())

    return "\n".join(lines)


def _format_execution_result(payload: dict[str, Any], final_two_only: bool = False) -> str:
    status = str(payload.get("status") or "")
    if status == "clarification":
        message = str(payload.get("message") or "I need clarification.")
        candidates = payload.get("candidates") or []
        if isinstance(candidates, list) and candidates:
            candidate_list = ", ".join(str(item) for item in candidates[:6])
            return f"{message} Candidates: {candidate_list}."
        return message

    if status == "error":
        return str(payload.get("message") or "NBA query execution failed.")

    if status == "no_data":
        if payload.get("result_type") == "stat_query":
            return _format_stat_result(payload)
        return str(payload.get("message") or "No data matched the query.")

    result_type = str(payload.get("result_type") or "")
    if result_type == "stat_query":
        return _format_stat_result(payload)
    if result_type == "play_by_play_query":
        return _format_play_by_play_result(payload, final_two_only=final_two_only)
    if result_type == "game_lookup":
        return _format_game_lookup_result(payload)

    return "I could not format the NBA tool result."


def answer_query(query: str, settings: Optional[Settings] = None) -> dict[str, Any]:
    if not query.strip():
        return {
            "matched": False,
            "query": query,
            "answer": None,
            "tool": None,
            "args": None,
            "result": None,
        }

    final_two_only = _detect_final_two_only(query)
    LOGGER.debug("structured_flow raw_query=%s", query)

    try:
        plan = plan_query(query)
    except Exception as exc:
        LOGGER.error("Planner failed for query: %s (%s)", query, exc)
        return {
            "matched": True,
            "query": query,
            "tool": "structured_query_planner",
            "args": None,
            "result": None,
            "answer": None,
            "error": str(exc),
        }

    if not plan.matched or not plan.query:
        return {
            "matched": False,
            "query": query,
            "tool": None,
            "args": None,
            "result": None,
            "answer": None,
            "planner_reason": plan.reason,
            "planner_raw": plan.raw,
        }

    repaired_query = repair_structured_query(plan.query, query)
    LOGGER.debug("structured_flow repaired_query=%s", repaired_query.to_dict())
    if repaired_query.intent == "stat_query" and repaired_query.entity_type == "player":
        if not repaired_query.player:
            return {
                "matched": True,
                "query": query,
                "tool": "structured_query_executor",
                "args": repaired_query.to_dict(),
                "result": None,
                "answer": None,
                "error": "I could not determine which player you meant. Please include the player name.",
            }

    try:
        validated_query = validate_structured_query(repaired_query)
    except Exception as exc:
        LOGGER.error("Structured query validation failed after repair: %s", exc)
        return {
            "matched": True,
            "query": query,
            "tool": "structured_query_validation",
            "args": repaired_query.to_dict(),
            "result": None,
            "answer": None,
            "error": f"Structured query validation failed: {exc}",
        }

    LOGGER.debug("structured_flow validated_query=%s", validated_query.to_dict())
    LOGGER.debug(
        "structured_flow execution_route intent=%s operation=%s scope=%s",
        validated_query.intent,
        validated_query.operation,
        validated_query.scope.type,
    )

    try:
        execution = execute_structured_query(validated_query, settings=settings)
    except Exception as exc:
        LOGGER.error("Executor crashed for query: %s (%s)", query, exc)
        return {
            "matched": True,
            "query": query,
            "tool": "structured_query_executor",
            "args": validated_query.to_dict(),
            "result": None,
            "answer": None,
            "error": str(exc),
        }

    status = str(execution.get("status") or "")
    if status == "error":
        return {
            "matched": True,
            "query": query,
            "tool": "structured_query_executor",
            "args": validated_query.to_dict(),
            "result": execution,
            "answer": None,
            "error": str(execution.get("message") or "NBA query execution failed."),
        }

    answer = _format_execution_result(execution, final_two_only=final_two_only)
    return {
        "matched": True,
        "query": query,
        "tool": "structured_query_executor",
        "args": validated_query.to_dict(),
        "plan": validated_query.to_dict(),
        "planner_reason": plan.reason,
        "result": execution,
        "answer": answer,
    }
