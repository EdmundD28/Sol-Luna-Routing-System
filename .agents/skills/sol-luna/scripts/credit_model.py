#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Estimate purchased ChatGPT credits from an auditable token-rate snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
RATE_CARD_SCHEMA_VERSION = 1
MILLION = Decimal(1_000_000)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

RATE_CARD_FIELDS = {
    "schema_version",
    "rate_card_id",
    "source",
    "unit",
    "validity",
    "scope",
    "models",
}
SOURCE_FIELDS = {"url", "observed_at"}
VALIDITY_FIELDS = {"not_before", "not_after", "not_after_inclusive", "reason"}
SCOPE_FIELDS = {
    "denomination",
    "billing_context",
    "included_plan_allowance_compatible",
    "plan_limit_percentage_convertible",
    "api_dollars_compatible",
    "automatic_model_execution_allowed",
}
RATE_FIELDS = {
    "input_credits_per_million_tokens",
    "cached_input_credits_per_million_tokens",
    "output_credits_per_million_tokens",
}
INPUT_FIELDS = {"schema_version", "rate_card_id", "rate_card_digest", "as_of", "phases"}
PHASE_FIELDS = {"phase_id", "model", "input_tokens", "cached_input_tokens", "output_tokens"}


class CreditModelError(ValueError):
    """The rate card or estimate input is not safe to use."""


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CreditModelError(f"{field} must be a JSON object")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    if missing:
        raise CreditModelError(f"{field} is missing fields: {sorted(missing)}")
    if extra:
        raise CreditModelError(f"{field} has unsupported fields: {sorted(extra)}")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\n" in value or "\r" in value:
        raise CreditModelError(f"{field} must be a non-empty, trimmed, single-line string")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _string(value, field)
    if not IDENTIFIER.fullmatch(result):
        raise CreditModelError(f"{field} must be a lowercase identifier")
    return result


def _date(value: Any, field: str) -> date:
    rendered = _string(value, field)
    if not ISO_DATE.fullmatch(rendered):
        raise CreditModelError(f"{field} must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(rendered)
    except ValueError as exc:
        raise CreditModelError(f"{field} must be a valid calendar date") from exc
    if parsed.isoformat() != rendered:
        raise CreditModelError(f"{field} must use canonical YYYY-MM-DD")
    return parsed


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise CreditModelError(f"{field} must be a boolean")
    return value


def _nonnegative_decimal_string(value: Any, field: str) -> Decimal:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise CreditModelError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CreditModelError(f"{field} must be a decimal string") from exc
    if not result.is_finite() or result < 0:
        raise CreditModelError(f"{field} must be finite and non-negative")
    return result


def _tokens(value: Any, field: str) -> int:
    # JSON booleans are integers in Python, so test them explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and not math.isfinite(value):
            raise CreditModelError(f"{field} must be finite")
        raise CreditModelError(f"{field} must be a non-negative integer")
    if value < 0:
        raise CreditModelError(f"{field} must be a non-negative integer")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _credit_amount(tokens: int, rate: str) -> Decimal:
    decimal_rate = Decimal(rate)
    required_precision = len(str(tokens)) + len(decimal_rate.as_tuple().digits) + 16
    with localcontext() as context:
        context.prec = max(64, required_precision)
        return Decimal(tokens) * decimal_rate / MILLION


def _exact_sum(*values: Decimal) -> Decimal:
    required_precision = sum(len(value.as_tuple().digits) for value in values) + 16
    with localcontext() as context:
        context.prec = max(64, required_precision)
        return sum(values, Decimal(0))


def validate_rate_card(source: Mapping[str, Any]) -> dict[str, Any]:
    source = _object(source, "rate_card")
    _exact_fields(source, RATE_CARD_FIELDS, "rate_card")
    if source["schema_version"] != RATE_CARD_SCHEMA_VERSION:
        raise CreditModelError("unsupported rate_card schema_version")

    source_info = _object(source["source"], "rate_card.source")
    _exact_fields(source_info, SOURCE_FIELDS, "rate_card.source")
    source_url = _string(source_info["url"], "rate_card.source.url")
    if source_url != "https://learn.chatgpt.com/docs/pricing":
        raise CreditModelError("rate_card.source.url is not the approved official source")
    observed_at = _date(source_info["observed_at"], "rate_card.source.observed_at")

    validity = _object(source["validity"], "rate_card.validity")
    _exact_fields(validity, VALIDITY_FIELDS, "rate_card.validity")
    not_before = _date(validity["not_before"], "rate_card.validity.not_before")
    not_after = _date(validity["not_after"], "rate_card.validity.not_after")
    if not_before < observed_at:
        raise CreditModelError("rate_card validity cannot begin before the price was observed")
    if not_after < not_before:
        raise CreditModelError("rate_card validity end precedes its start")
    if _boolean(validity["not_after_inclusive"], "rate_card.validity.not_after_inclusive") is not True:
        raise CreditModelError("only an inclusive rate_card validity boundary is supported")
    validity_reason = _string(validity["reason"], "rate_card.validity.reason")

    scope = _object(source["scope"], "rate_card.scope")
    _exact_fields(scope, SCOPE_FIELDS, "rate_card.scope")
    denomination = _string(scope["denomination"], "rate_card.scope.denomination")
    if denomination != "ChatGPT credits":
        raise CreditModelError("rate_card denomination must be ChatGPT credits")
    billing_context = _string(scope["billing_context"], "rate_card.scope.billing_context")
    if billing_context != "purchased_credits":
        raise CreditModelError("rate_card billing_context must be purchased_credits")
    if _boolean(
        scope["included_plan_allowance_compatible"],
        "rate_card.scope.included_plan_allowance_compatible",
    ) is not False:
        raise CreditModelError("purchased-credit rates cannot represent included plan allowance")
    if _boolean(
        scope["plan_limit_percentage_convertible"],
        "rate_card.scope.plan_limit_percentage_convertible",
    ) is not False:
        raise CreditModelError("the undisclosed plan-limit capacity prevents percentage conversion")
    if _boolean(scope["api_dollars_compatible"], "rate_card.scope.api_dollars_compatible") is not False:
        raise CreditModelError("API-dollar conversion is outside this credit model")
    if _boolean(
        scope["automatic_model_execution_allowed"],
        "rate_card.scope.automatic_model_execution_allowed",
    ) is not False:
        raise CreditModelError("automatic model execution must remain disabled")

    models_source = _object(source["models"], "rate_card.models")
    if not models_source:
        raise CreditModelError("rate_card.models must not be empty")
    models: dict[str, dict[str, str]] = {}
    for raw_model, raw_rates in models_source.items():
        model = _identifier(raw_model, "rate_card.models key")
        rates = _object(raw_rates, f"rate_card.models.{model}")
        _exact_fields(rates, RATE_FIELDS, f"rate_card.models.{model}")
        normalized_rates: dict[str, str] = {}
        for field in sorted(RATE_FIELDS):
            amount = _nonnegative_decimal_string(rates[field], f"rate_card.models.{model}.{field}")
            normalized_rates[field] = _decimal_text(amount)
        models[model] = normalized_rates

    unit = _string(source["unit"], "rate_card.unit")
    if unit != "ChatGPT credits per 1M tokens":
        raise CreditModelError("unsupported rate_card unit")
    return {
        "schema_version": RATE_CARD_SCHEMA_VERSION,
        "rate_card_id": _identifier(source["rate_card_id"], "rate_card.rate_card_id"),
        "source": {"url": source_url, "observed_at": observed_at.isoformat()},
        "unit": unit,
        "validity": {
            "not_before": not_before.isoformat(),
            "not_after": not_after.isoformat(),
            "not_after_inclusive": True,
            "reason": validity_reason,
        },
        "scope": {
            "denomination": denomination,
            "billing_context": billing_context,
            "included_plan_allowance_compatible": False,
            "plan_limit_percentage_convertible": False,
            "api_dollars_compatible": False,
            "automatic_model_execution_allowed": False,
        },
        "models": models,
    }


def rate_card_fingerprint(rate_card: Mapping[str, Any]) -> str:
    validated = validate_rate_card(rate_card)
    return "sha256:" + hashlib.sha256(_canonical_json(validated)).hexdigest()


def load_rate_card(path: Path) -> dict[str, Any]:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CreditModelError(f"cannot load rate card: {exc}") from exc
    return validate_rate_card(source)


def validate_input(
    source: Mapping[str, Any], rate_card: Mapping[str, Any], rate_card_digest: str
) -> dict[str, Any]:
    source = _object(source, "input")
    _exact_fields(source, INPUT_FIELDS, "input")
    if source["schema_version"] != SCHEMA_VERSION:
        raise CreditModelError("unsupported input schema_version")
    card_id = _identifier(source["rate_card_id"], "input.rate_card_id")
    if card_id != rate_card["rate_card_id"]:
        raise CreditModelError("input.rate_card_id does not match the loaded rate card")
    digest = _string(source["rate_card_digest"], "input.rate_card_digest")
    if not DIGEST.fullmatch(digest):
        raise CreditModelError("input.rate_card_digest must be sha256 followed by 64 lowercase hexadecimal characters")
    if digest != rate_card_digest:
        raise CreditModelError("input.rate_card_digest does not match the loaded rate card")

    as_of = _date(source["as_of"], "input.as_of")
    not_before = _date(rate_card["validity"]["not_before"], "rate_card.validity.not_before")
    not_after = _date(rate_card["validity"]["not_after"], "rate_card.validity.not_after")
    if as_of < not_before:
        raise CreditModelError("rate card is not yet valid for input.as_of")
    if as_of > not_after:
        raise CreditModelError("rate card has expired for input.as_of")

    raw_phases = source["phases"]
    if not isinstance(raw_phases, list) or not raw_phases:
        raise CreditModelError("input.phases must be a non-empty JSON array")
    phases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_phase in enumerate(raw_phases):
        phase = _object(raw_phase, f"input.phases[{index}]")
        _exact_fields(phase, PHASE_FIELDS, f"input.phases[{index}]")
        phase_id = _identifier(phase["phase_id"], f"input.phases[{index}].phase_id")
        if phase_id in seen:
            raise CreditModelError(f"duplicate phase_id: {phase_id}")
        seen.add(phase_id)
        model = _identifier(phase["model"], f"input.phases[{index}].model")
        if model not in rate_card["models"]:
            raise CreditModelError(f"unknown model in input.phases[{index}]: {model}")
        input_tokens = _tokens(phase["input_tokens"], f"input.phases[{index}].input_tokens")
        cached_tokens = _tokens(
            phase["cached_input_tokens"], f"input.phases[{index}].cached_input_tokens"
        )
        output_tokens = _tokens(phase["output_tokens"], f"input.phases[{index}].output_tokens")
        if cached_tokens > input_tokens:
            raise CreditModelError(
                f"input.phases[{index}].cached_input_tokens cannot exceed input_tokens"
            )
        phases.append(
            {
                "phase_id": phase_id,
                "model": model,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": output_tokens,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "rate_card_id": card_id,
        "rate_card_digest": digest,
        "as_of": as_of.isoformat(),
        "phases": phases,
    }


def _empty_breakdown(model: str | None = None, phase_id: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if model is not None:
        result["model"] = model
    if phase_id is not None:
        result["phase_id"] = phase_id
    result.update(
        {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "output_tokens": 0,
            "input_credits": Decimal(0),
            "cached_input_credits": Decimal(0),
            "output_credits": Decimal(0),
            "total_credits": Decimal(0),
        }
    )
    return result


def _render_breakdown(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _decimal_text(item) if isinstance(item, Decimal) else item
        for key, item in value.items()
    }


def estimate(source: Mapping[str, Any], rate_card: Mapping[str, Any]) -> dict[str, Any]:
    card = validate_rate_card(rate_card)
    digest = rate_card_fingerprint(card)
    estimate_input = validate_input(source, card, digest)
    by_phase: list[dict[str, Any]] = []
    by_model: dict[str, dict[str, Any]] = {}
    total = Decimal(0)

    for phase in estimate_input["phases"]:
        rates = card["models"][phase["model"]]
        uncached_tokens = phase["input_tokens"] - phase["cached_input_tokens"]
        input_credits = _credit_amount(uncached_tokens, rates["input_credits_per_million_tokens"])
        cached_credits = _credit_amount(
            phase["cached_input_tokens"], rates["cached_input_credits_per_million_tokens"]
        )
        output_credits = _credit_amount(phase["output_tokens"], rates["output_credits_per_million_tokens"])
        phase_total = _exact_sum(input_credits, cached_credits, output_credits)
        detail = _empty_breakdown(model=phase["model"], phase_id=phase["phase_id"])
        detail.update(
            {
                "input_tokens": phase["input_tokens"],
                "cached_input_tokens": phase["cached_input_tokens"],
                "uncached_input_tokens": uncached_tokens,
                "output_tokens": phase["output_tokens"],
                "input_credits": input_credits,
                "cached_input_credits": cached_credits,
                "output_credits": output_credits,
                "total_credits": phase_total,
            }
        )
        by_phase.append(_render_breakdown(detail))

        aggregate = by_model.setdefault(phase["model"], _empty_breakdown(model=phase["model"]))
        for field in ("input_tokens", "cached_input_tokens", "uncached_input_tokens", "output_tokens"):
            aggregate[field] += detail[field]
        for field in ("input_credits", "cached_input_credits", "output_credits", "total_credits"):
            aggregate[field] = _exact_sum(aggregate[field], detail[field])
        total = _exact_sum(total, phase_total)

    return {
        "schema_version": SCHEMA_VERSION,
        "rate_card_id": card["rate_card_id"],
        "rate_card_digest": digest,
        "as_of": estimate_input["as_of"],
        "unit": "purchased ChatGPT credits",
        "total_credits": _decimal_text(total),
        "by_model": [_render_breakdown(by_model[model]) for model in sorted(by_model)],
        "by_phase": by_phase,
        "source": {
            "url": card["source"]["url"],
            "observed_at": card["source"]["observed_at"],
            "validity": card["validity"],
        },
        "applicability": {
            "input_token_semantics": (
                "input_tokens includes cached_input_tokens; only the remainder is charged at the ordinary input rate"
            ),
            "denomination": "ChatGPT credits, never API dollars",
            "billing_context": "purchased_credits",
            "included_plan_allowance_compatible": False,
            "plan_limit_percentage_convertible": False,
            "estimate_not_receipt": True,
            "supplied_phases_only": True,
            "token_provenance_verified": False,
            "delivery_phase_completeness_verified": False,
            "automatic_model_execution_allowed": False,
        },
    }


def load_input(path: Path) -> Mapping[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), "input")
    except (OSError, json.JSONDecodeError) as exc:
        raise CreditModelError(f"cannot load estimate input: {exc}") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Estimate purchased ChatGPT credits from supplied classified token usage."
    )
    sub = result.add_subparsers(dest="command", required=True)
    estimate_parser = sub.add_parser("estimate")
    estimate_parser.add_argument("--rate-card", required=True, type=Path)
    estimate_parser.add_argument("--input", required=True, type=Path)
    fingerprint_parser = sub.add_parser("fingerprint")
    fingerprint_parser.add_argument("--rate-card", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        card = load_rate_card(args.rate_card)
        if args.command == "fingerprint":
            output = {
                "schema_version": RATE_CARD_SCHEMA_VERSION,
                "rate_card_id": card["rate_card_id"],
                "rate_card_digest": rate_card_fingerprint(card),
                "automatic_model_execution_allowed": False,
            }
        else:
            output = estimate(load_input(args.input), card)
    except CreditModelError as exc:
        print(f"credit model error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
