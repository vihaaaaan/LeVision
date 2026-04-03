#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from typing import Optional

from nba_pipeline.data_service import (
    init_supabase,
    is_team_stats_schema_error,
    upsert_rows,
)
from nba_pipeline.espn_client import (
    create_http_session,
    fetch_espn_summary,
    parse_event_id_from_url,
    resolve_summary_url_with_prompt,
    set_event_id_in_url,
)
from nba_pipeline.espn_parser import parse_all_rows, parse_team_statistics
from nba_pipeline.settings import Settings, configure_logging, load_settings, str_to_bool

LOGGER = logging.getLogger("espn_supabase_sync")


def print_dry_run_preview(table: str, rows: list[dict[str, object]]) -> None:
    LOGGER.info("[DRY_RUN] Table %s would upsert %s row(s).", table, len(rows))
    for idx, row in enumerate(rows[:2], start=1):
        LOGGER.info("[DRY_RUN] %s sample row %s: %s", table, idx, json.dumps(row, default=str))


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

