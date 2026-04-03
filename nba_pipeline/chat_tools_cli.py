from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from .chat_tools import (
    answer_query,
    get_game_play_by_play,
    get_player_game_stat_by_date,
    get_player_last_n_games_stat,
    get_team_recent_games,
)
from .settings import configure_logging, load_settings

LOGGER = logging.getLogger("nba_pipeline.chat_tools_cli")


def _print(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, default=str))
        return

    answer = payload.get("answer")
    if answer:
        print(answer)
        return

    error = payload.get("error")
    if error:
        print(f"Error: {error}")
        return

    print("No matching NBA tool for query.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic NBA chat tools.")
    parser.add_argument("--query", help="Natural-language query for tool inference.")
    parser.add_argument("--tool", help="Direct tool name to call.")
    parser.add_argument(
        "--args-json",
        default="{}",
        help="JSON object for direct tool arguments when using --tool.",
    )
    parser.add_argument("--json", action="store_true", help="Emit full JSON payload.")
    return parser.parse_args()


def _dispatch_direct(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool == "get_player_last_n_games_stat":
        result = get_player_last_n_games_stat(
            player_name=str(args.get("player_name") or ""),
            stat_name=str(args.get("stat_name") or "points"),
            n=int(args.get("n") or 5),
        )
        return {"matched": True, "tool": tool, "args": args, "result": result, "answer": None}

    if tool == "get_player_game_stat_by_date":
        result = get_player_game_stat_by_date(
            player_name=str(args.get("player_name") or ""),
            stat_name=str(args.get("stat_name") or "points"),
            target_date=str(args.get("target_date") or ""),
        )
        return {"matched": True, "tool": tool, "args": args, "result": result, "answer": None}

    if tool == "get_team_recent_games":
        result = get_team_recent_games(
            team_name=str(args.get("team_name") or ""),
            n=int(args.get("n") or 5),
        )
        return {"matched": True, "tool": tool, "args": args, "result": result, "answer": None}

    if tool == "get_game_play_by_play":
        result = get_game_play_by_play(
            team_name=args.get("team_name"),
            event_id=args.get("event_id"),
            target_date=args.get("target_date"),
        )
        return {"matched": True, "tool": tool, "args": args, "result": result, "answer": None}

    raise ValueError(f"Unknown tool '{tool}'")


def main() -> None:
    configure_logging()
    args = parse_args()

    try:
        load_settings()

        if args.tool:
            tool_args = json.loads(args.args_json)
            if not isinstance(tool_args, dict):
                raise ValueError("--args-json must decode to a JSON object")
            payload = _dispatch_direct(args.tool, tool_args)
        else:
            query = (args.query or "").strip()
            if not query:
                raise ValueError("Provide --query or --tool")
            payload = answer_query(query)

        _print(payload, as_json=args.json)
    except Exception as exc:
        error_payload = {
            "matched": False,
            "error": str(exc),
            "query": args.query,
            "tool": args.tool,
        }
        _print(error_payload, as_json=True if args.json else False)
        return


if __name__ == "__main__":
    main()
