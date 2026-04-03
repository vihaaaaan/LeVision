from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

DEFAULT_ESPN_SUMMARY_URL = (
    "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
    "?region=us&lang=en&contentorigin=espn&event=400878154"
)

LOGGER = logging.getLogger("nba_pipeline.settings")


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
    configured_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, configured_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    # Keep our pipeline logs configurable, but prevent external dependency
    # debug noise from flooding CLI stderr.
    for noisy_logger in ("urllib3", "httpx", "httpcore", "hpack", "requests", "espn_supabase_sync"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def str_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on"}


def load_env_files() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    # Project runtime should prefer .env.local values over any test-only .env
    # files. Only fall back to .env when no .env.local exists.
    preferred_local_candidates = [
        repo_root / "levision-web" / ".env.local",
        Path.cwd() / ".env.local",
        repo_root / ".env.local",
    ]
    fallback_env_candidates = [
        Path.cwd() / ".env",
        repo_root / ".env",
    ]

    seen: set[Path] = set()
    loaded_local = False
    for env_file in preferred_local_candidates:
        resolved = env_file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)
            loaded_local = True
            break

    if loaded_local:
        return

    loaded_any = False
    for env_file in fallback_env_candidates:
        resolved = env_file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
            loaded_any = True

    if not loaded_any:
        load_dotenv(override=False)


def load_settings(
    url_override: Optional[str] = None,
    dry_run_override: Optional[bool] = None,
) -> Settings:
    load_env_files()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError(
            "Missing required env vars: SUPABASE_URL and/or SUPABASE_SERVICE_ROLE_KEY. "
            "Set them in your .env.local file."
        )

    env_url = os.getenv("ESPN_SUMMARY_URL", DEFAULT_ESPN_SUMMARY_URL)
    env_schema_mode = os.getenv("SCHEMA_MODE", "snake").strip().lower()
    if env_schema_mode not in {"quoted", "snake"}:
        raise ValueError("SCHEMA_MODE must be 'quoted' or 'snake'.")

    env_dry_run = str_to_bool(os.getenv("DRY_RUN", "false"))
    timeout_seconds = int(os.getenv("ESPN_TIMEOUT_SECONDS", "20"))
    retry_attempts = int(os.getenv("ESPN_RETRY_ATTEMPTS", "3"))

    settings = Settings(
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_key,
        espn_summary_url=url_override or env_url,
        schema_mode=env_schema_mode,
        dry_run=dry_run_override if dry_run_override is not None else env_dry_run,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
    )
    LOGGER.debug("Loaded settings with schema_mode=%s dry_run=%s", settings.schema_mode, settings.dry_run)
    return settings
