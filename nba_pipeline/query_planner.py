from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .query_schema import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_INTENTS,
    ALLOWED_OPERATIONS,
    ALLOWED_SCOPE_TYPES,
    ALLOWED_STATS,
    StructuredQuery,
    coerce_structured_query,
    validate_structured_query,
)
from .settings import load_env_files

LOGGER = logging.getLogger("nba_pipeline.query_planner")
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


@dataclass(slots=True)
class QueryPlan:
    matched: bool
    query: Optional[StructuredQuery] = None
    reason: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


STAT_PHRASE_PATTERN = (
    r"(?:points?|assists?|rebounds?|steals?|blocks?|turnovers?|minutes?|fouls?|"
    r"plus(?:\s|-)?minus|\+/-|scoring)"
)
PLAYER_INFERENCE_PATTERNS = [
    re.compile(
        rf"^\s*(?:what\s+was|what\s+were|how\s+many|show\s+me|tell\s+me|give\s+me)?\s*"
        rf"(?P<player>[A-Za-z][A-Za-z .'\-]{{1,50}}?)"
        rf"(?:['’]s)?\s+{STAT_PHRASE_PATTERN}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bfor\s+(?P<player>[A-Za-z][A-Za-z .'\-]{{1,50}})\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bfor\s+(?P<player>[A-Za-z][A-Za-z .'\-]{{1,50}})\b",
        re.IGNORECASE,
    ),
]
PLAYER_STOP_TOKENS = {
    "last",
    "past",
    "recent",
    "game",
    "games",
    "season",
    "this",
    "today",
    "yesterday",
    "over",
    "in",
    "on",
    "the",
    "of",
    "highest",
    "lowest",
    "average",
    "total",
    "sum",
    "max",
    "min",
}

VALID_OPERATIONS = {
    "game_log",
    "max_single_game",
    "min_single_game",
    "average",
    "sum",
    "latest_game",
    "play_by_play",
}
VALID_SCOPE_TYPES = {"recent_games", "season", "date", "date_range", "specific_game"}
VALID_STATS = {
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

STAT_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(points?|pts?|scoring|score)\b", re.IGNORECASE), "points"),
    (re.compile(r"\b(assists?|ast)\b", re.IGNORECASE), "assists"),
    (re.compile(r"\b(rebounds?|reb)\b", re.IGNORECASE), "rebounds"),
    (re.compile(r"\b(steals?|stl)\b", re.IGNORECASE), "steals"),
    (re.compile(r"\b(blocks?|blk)\b", re.IGNORECASE), "blocks"),
    (re.compile(r"\b(turnovers?|to)\b", re.IGNORECASE), "turnovers"),
    (re.compile(r"\b(minutes?|mins?|min)\b", re.IGNORECASE), "minutes"),
    (re.compile(r"\b(fouls?|pf)\b", re.IGNORECASE), "fouls"),
    (re.compile(r"\b(plus\s*minus|plus-minus|\+/-)\b", re.IGNORECASE), "plus_minus"),
]


def _planner_model() -> str:
    return (
        os.getenv("NBA_QUERY_PLANNER_MODEL")
        or os.getenv("LEVISION_OPENAI_MODEL")
        or "gpt-5-nano"
    )


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _normalize_text_for_repair(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_entity_name(value: Any) -> Optional[str]:
    text = _normalize_text_for_repair(value)
    if not text:
        return None
    text = re.sub(r"['’]s\b", "", text, flags=re.IGNORECASE)
    tokens = [token for token in re.split(r"\s+", text) if token]
    while len(tokens) > 1 and tokens[-1].lower() in PLAYER_STOP_TOKENS:
        tokens.pop()
    text = " ".join(tokens)
    text = text.strip(" ,.!?\"'")
    return text or None


def _is_plausible_player_name(value: str) -> bool:
    if not value:
        return False
    if any(char.isdigit() for char in value):
        return False
    words = [token for token in re.split(r"\s+", value) if token]
    if not words:
        return False
    if len(words) > 4:
        return False
    lowered = [token.lower() for token in words]
    if all(token in PLAYER_STOP_TOKENS for token in lowered):
        return False
    return True


def _infer_player_from_query(user_query: str) -> Optional[str]:
    normalized = _normalize_text_for_repair(user_query)
    if not normalized:
        return None

    for pattern in PLAYER_INFERENCE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        player = _normalize_entity_name(match.group("player"))
        if player and _is_plausible_player_name(player):
            return player

    return None


def _infer_stat_from_query(user_query: str) -> Optional[str]:
    for pattern, stat_name in STAT_HINTS:
        if pattern.search(user_query):
            return stat_name
    return None


def _infer_recent_games_count(user_query: str) -> Optional[int]:
    match = re.search(
        r"\b(?:last|past|recent|most\s+recent)\s+(\d{1,2})\s+games?\b",
        user_query,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        count = int(match.group(1))
    except ValueError:
        return None
    return count if count > 0 else None


def _infer_scope_type_from_query(user_query: str) -> Optional[str]:
    if re.search(r"\bthis\s+season\b", user_query, re.IGNORECASE):
        return "season"
    if re.search(r"\bon\s+\d{4}-\d{2}-\d{2}\b", user_query, re.IGNORECASE):
        return "date"
    if re.search(r"\b(last|past|recent|most\s+recent)\s+\d{1,2}\s+games?\b", user_query, re.IGNORECASE):
        return "recent_games"
    return None


def _infer_operation_from_query(user_query: str, intent: str) -> Optional[str]:
    if intent == "play_by_play_query":
        return "play_by_play"

    text = user_query.lower()
    if "highest" in text or "season high" in text or "max" in text:
        return "max_single_game"
    if "lowest" in text or "min" in text:
        return "min_single_game"
    if "average" in text or "avg" in text or "mean" in text:
        return "average"
    if "total" in text or "sum" in text:
        return "sum"
    if "latest game" in text or "last game" in text:
        return "latest_game"
    if re.search(r"\b(last|past|recent|most\s+recent)\s+\d{1,2}\s+games?\b", text):
        return "game_log"
    return "game_log" if intent == "stat_query" else None


def repair_structured_query(query: StructuredQuery, user_query: str) -> StructuredQuery:
    normalized_query_text = _normalize_text_for_repair(user_query)
    repaired_player = _normalize_entity_name(query.player)
    repaired_team = _normalize_entity_name(query.team)
    repaired_intent = str(query.intent or "").strip().lower()
    repaired_entity = str(query.entity_type or "").strip().lower()
    repaired_operation = str(query.operation or "").strip().lower()
    repaired_scope_type = str(query.scope.type or "").strip().lower()
    repaired_stat = str(query.stat or "").strip().lower() if query.stat is not None else None
    repaired_scope = query.scope

    if repaired_intent not in {"stat_query", "play_by_play_query", "game_lookup"}:
        if re.search(r"\bplay[- ]?by[- ]?play\b", normalized_query_text, re.IGNORECASE):
            repaired_intent = "play_by_play_query"
        else:
            repaired_intent = "stat_query"

    if repaired_entity not in {"player", "team", "game"}:
        repaired_entity = "player" if repaired_intent == "stat_query" else "team"

    if repaired_intent == "stat_query" and repaired_entity == "player" and not repaired_player:
        inferred_player = _infer_player_from_query(normalized_query_text)
        if inferred_player:
            repaired_player = inferred_player
            LOGGER.debug("Planner repair inferred player='%s' from query='%s'", inferred_player, user_query)

    if (
        repaired_intent == "play_by_play_query"
        and not repaired_team
        and repaired_scope_type == "date"
    ):
        match = re.search(r"\bfor\s+the\s+([A-Za-z .'\-]+?)\s+game\b", normalized_query_text, re.IGNORECASE)
        if match:
            candidate = _normalize_entity_name(match.group(1))
            if candidate:
                repaired_team = candidate

    if repaired_stat not in VALID_STATS and repaired_intent == "stat_query":
        inferred_stat = _infer_stat_from_query(normalized_query_text)
        if inferred_stat:
            repaired_stat = inferred_stat

    if repaired_scope_type not in VALID_SCOPE_TYPES:
        inferred_scope = _infer_scope_type_from_query(normalized_query_text)
        if inferred_scope:
            repaired_scope_type = inferred_scope
        elif repaired_intent == "stat_query":
            repaired_scope_type = "recent_games"
        else:
            repaired_scope_type = "specific_game" if repaired_scope.game_id else "recent_games"

    if repaired_scope_type == "recent_games":
        if repaired_scope.count is None or repaired_scope.count <= 0:
            repaired_scope.count = _infer_recent_games_count(normalized_query_text) or 5
        if repaired_scope.before_now is None:
            repaired_scope.before_now = True
    elif repaired_scope_type == "season":
        repaired_scope.season = repaired_scope.season or "current"

    if repaired_operation not in VALID_OPERATIONS:
        inferred_operation = _infer_operation_from_query(normalized_query_text, repaired_intent)
        if inferred_operation:
            repaired_operation = inferred_operation

    if repaired_intent == "play_by_play_query":
        repaired_operation = "play_by_play"
        repaired_stat = None

    if repaired_intent == "stat_query" and repaired_operation == "play_by_play":
        repaired_operation = "game_log"

    if repaired_intent == "stat_query" and repaired_scope_type == "season" and repaired_operation == "game_log":
        # Season prompts asking for extrema/aggregates should not silently degrade.
        if re.search(r"\b(highest|max|lowest|min|average|avg|total|sum)\b", normalized_query_text, re.IGNORECASE):
            repaired_operation = _infer_operation_from_query(normalized_query_text, repaired_intent) or "game_log"

    repaired_scope.type = repaired_scope_type  # type: ignore[assignment]

    return StructuredQuery(
        intent=repaired_intent,  # type: ignore[arg-type]
        entity_type=repaired_entity,  # type: ignore[arg-type]
        player=repaired_player,
        team=repaired_team,
        stat=repaired_stat,  # type: ignore[arg-type]
        operation=repaired_operation,  # type: ignore[arg-type]
        scope=repaired_scope,
    )


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(text)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("Planner response did not include JSON")

    depth = 0
    end = -1
    for idx in range(start, len(cleaned)):
        char = cleaned[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break

    if end < 0:
        raise ValueError("Planner response JSON was incomplete")

    parsed = json.loads(cleaned[start:end])
    if not isinstance(parsed, dict):
        raise ValueError("Planner response JSON must be an object")
    return parsed


def _system_prompt() -> str:
    return (
        "You are an NBA query planner. Convert user requests into strict JSON for a backend executor. "
        "Never answer with stats. Never browse ESPN. Never write SQL. "
        "Return ONLY a JSON object with this exact envelope: "
        "{\"should_handle\": boolean, \"reason\": string, \"query\": object|null}. "
        "Set should_handle=false for non-NBA or out-of-scope requests. "
        f"Allowed query.intent values: {sorted(ALLOWED_INTENTS)}. "
        f"Allowed query.entity_type values: {sorted(ALLOWED_ENTITY_TYPES)}. "
        f"Allowed query.operation values: {sorted(ALLOWED_OPERATIONS)}. "
        f"Allowed query.scope.type values: {sorted(ALLOWED_SCOPE_TYPES)}. "
        f"Allowed query.stat values: {sorted(ALLOWED_STATS)}. "
        "Map phrase variants semantically: 'scoring'->points, 'highest scoring game'->operation max_single_game, "
        "'last/past/most recent N games'->scope.type recent_games with scope.count N and scope.before_now true, "
        "'this season'->scope.type season with season 'current', 'play-by-play'->intent play_by_play_query and operation play_by_play. "
        "For stat_query use entity_type='player'. "
        "Do not invent players or teams; keep names as mentioned by user when present. "
        "Use YYYY-MM-DD for explicit dates when possible."
    )


def _planner_messages(user_query: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _system_prompt()},
        {
            "role": "user",
            "content": (
                "Plan this NBA request. "
                "If it is unrelated to NBA data retrieval, return should_handle=false. "
                f"User request: {user_query}"
            ),
        },
    ]


def _openai_plan_request(api_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    base_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    attempts = [
        {"response_format": {"type": "json_object"}},
        {},
    ]

    errors: list[str] = []

    for extra in attempts:
        payload = {**base_payload, **extra}
        response = requests.post(
            OPENAI_CHAT_COMPLETIONS_URL,
            headers=headers,
            json=payload,
            timeout=45,
        )

        response_text = response.text
        if not response.ok:
            errors.append(f"{response.status_code}: {response_text[:300]}")
            if extra and response.status_code == 400 and "response_format" in response_text:
                continue
            raise RuntimeError(f"Planner request failed: {response.status_code}: {response_text[:300]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("Planner returned non-JSON response") from exc

        choices = body.get("choices") or []
        content = (((choices[0] or {}).get("message") or {}).get("content") or "") if choices else ""
        if not isinstance(content, str) or not content.strip():
            errors.append("missing planner message content")
            continue

        parsed = _extract_json_object(content)
        return parsed

    raise RuntimeError(f"Planner could not parse response: {errors}")


def plan_query(user_query: str) -> QueryPlan:
    query_text = str(user_query or "").strip()
    if not query_text:
        return QueryPlan(matched=False, reason="empty_query")

    LOGGER.debug("structured_flow raw_query=%s", query_text)

    load_env_files()
    api_key = (
        os.getenv("NBA_QUERY_PLANNER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("LEVISION_CHAT_API_KEY")
    )
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for NBA query planning")

    model = _planner_model()
    planner_raw = _openai_plan_request(
        api_key=api_key,
        model=model,
        messages=_planner_messages(query_text),
    )
    LOGGER.debug("structured_flow planner_raw=%s", json.dumps(planner_raw, ensure_ascii=True, default=str))

    should_handle = _bool_value(planner_raw.get("should_handle"))
    reason = str(planner_raw.get("reason") or "").strip() or None

    if not should_handle:
        LOGGER.debug("Planner declined query. reason=%s query=%s", reason, query_text)
        return QueryPlan(matched=False, reason=reason, raw=planner_raw)

    query_payload = planner_raw.get("query")
    if not isinstance(query_payload, dict):
        raise ValueError("Planner returned should_handle=true but query was missing")

    coerced_query = coerce_structured_query(query_payload)
    repaired_query = repair_structured_query(coerced_query, query_text)
    LOGGER.debug(
        "structured_flow repaired_query=%s",
        json.dumps(repaired_query.to_dict(), ensure_ascii=True, default=str),
    )

    validated_query = validate_structured_query(repaired_query)
    LOGGER.debug(
        "structured_flow validated_query=%s",
        json.dumps(validated_query.to_dict(), ensure_ascii=True, default=str),
    )
    LOGGER.debug("Planner matched query=%s plan=%s", query_text, validated_query.to_dict())
    return QueryPlan(matched=True, query=validated_query, reason=reason, raw=planner_raw)
