from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "credit_model.py"
RATE_CARD_PATH = ROOT / ".agents" / "skills" / "sol-luna" / "references" / "credit-rate-card.v1.json"
SPEC = importlib.util.spec_from_file_location("credit_model", SCRIPT)
assert SPEC and SPEC.loader
CREDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CREDIT)
RATE_CARD = json.loads(RATE_CARD_PATH.read_text(encoding="utf-8"))


def estimate_input(*phases: dict, as_of: str = "2026-08-28") -> dict:
    return {
        "schema_version": 1,
        "rate_card_id": RATE_CARD["rate_card_id"],
        "rate_card_digest": CREDIT.rate_card_fingerprint(RATE_CARD),
        "as_of": as_of,
        "phases": list(phases),
    }


def phase(
    model: str = "gpt-5.6-sol",
    *,
    phase_id: str = "execution",
    input_tokens: object = 0,
    cached_input_tokens: object = 0,
    output_tokens: object = 0,
) -> dict:
    return {
        "phase_id": phase_id,
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
    }


class CreditModelTests(unittest.TestCase):
    def test_exact_multi_phase_example_and_breakdowns(self) -> None:
        source = estimate_input(
            phase(input_tokens=1_000_000, cached_input_tokens=250_000, output_tokens=100_000),
            phase(
                "gpt-5.6-luna",
                phase_id="worker",
                input_tokens=2_000_000,
                cached_input_tokens=1_000_000,
                output_tokens=500_000,
            ),
        )
        result = CREDIT.estimate(source, RATE_CARD)
        # Sol: 75 + 2.5 + 50 = 127.5; Luna: 5 + 0.5 + 15 = 20.5.
        self.assertEqual(result["total_credits"], "148")
        self.assertEqual([item["total_credits"] for item in result["by_phase"]], ["127.5", "20.5"])
        self.assertEqual([item["model"] for item in result["by_model"]], ["gpt-5.6-luna", "gpt-5.6-sol"])
        self.assertEqual(result["unit"], "purchased ChatGPT credits")
        self.assertFalse(result["applicability"]["included_plan_allowance_compatible"])
        self.assertFalse(result["applicability"]["plan_limit_percentage_convertible"])
        self.assertFalse(result["applicability"]["token_provenance_verified"])
        self.assertFalse(result["applicability"]["delivery_phase_completeness_verified"])
        self.assertFalse(result["applicability"]["automatic_model_execution_allowed"])

    def test_sol_luna_rate_ratios_are_preserved(self) -> None:
        sol = CREDIT.estimate(estimate_input(phase(input_tokens=1_000_000)), RATE_CARD)
        luna = CREDIT.estimate(
            estimate_input(phase("gpt-5.6-luna", input_tokens=1_000_000)), RATE_CARD
        )
        self.assertEqual(sol["total_credits"], "100")
        self.assertEqual(luna["total_credits"], "5")

        sol_output = CREDIT.estimate(estimate_input(phase(output_tokens=1_000_000)), RATE_CARD)
        luna_output = CREDIT.estimate(
            estimate_input(phase("gpt-5.6-luna", output_tokens=1_000_000)), RATE_CARD
        )
        self.assertEqual(sol_output["total_credits"], "500")
        self.assertEqual(luna_output["total_credits"], "30")

        sol_cached = CREDIT.estimate(
            estimate_input(phase(input_tokens=1_000_000, cached_input_tokens=1_000_000)), RATE_CARD
        )
        luna_cached = CREDIT.estimate(
            estimate_input(
                phase(
                    "gpt-5.6-luna",
                    input_tokens=1_000_000,
                    cached_input_tokens=1_000_000,
                )
            ),
            RATE_CARD,
        )
        self.assertEqual(sol_cached["total_credits"], "10")
        self.assertEqual(luna_cached["total_credits"], "0.5")

    def test_cached_input_is_subset_and_charged_once(self) -> None:
        result = CREDIT.estimate(
            estimate_input(phase(input_tokens=1_000_000, cached_input_tokens=900_000)), RATE_CARD
        )
        detail = result["by_phase"][0]
        self.assertEqual(detail["uncached_input_tokens"], 100_000)
        self.assertEqual(detail["input_credits"], "10")
        self.assertEqual(detail["cached_input_credits"], "9")
        self.assertEqual(result["total_credits"], "19")

    def test_cached_input_cannot_exceed_total_input(self) -> None:
        with self.assertRaisesRegex(CREDIT.CreditModelError, "cannot exceed"):
            CREDIT.estimate(
                estimate_input(phase(input_tokens=1, cached_input_tokens=2)), RATE_CARD
            )

    def test_unknown_fields_fail_closed_at_every_input_level(self) -> None:
        top = estimate_input(phase())
        top["total_tokens"] = 0
        with self.assertRaisesRegex(CREDIT.CreditModelError, "unsupported fields"):
            CREDIT.estimate(top, RATE_CARD)

        nested = estimate_input(phase())
        nested["phases"][0]["credits"] = 0
        with self.assertRaisesRegex(CREDIT.CreditModelError, "unsupported fields"):
            CREDIT.estimate(nested, RATE_CARD)

    def test_unknown_model_and_duplicate_phase_fail_closed(self) -> None:
        with self.assertRaisesRegex(CREDIT.CreditModelError, "unknown model"):
            CREDIT.estimate(estimate_input(phase("gpt-5.6-mystery")), RATE_CARD)
        with self.assertRaisesRegex(CREDIT.CreditModelError, "duplicate phase_id"):
            CREDIT.estimate(estimate_input(phase(), phase()), RATE_CARD)

    def test_missing_fields_fail_closed(self) -> None:
        source = estimate_input(phase())
        del source["phases"][0]["output_tokens"]
        with self.assertRaisesRegex(CREDIT.CreditModelError, "missing fields"):
            CREDIT.estimate(source, RATE_CARD)

    def test_negative_non_integer_boolean_and_nonfinite_tokens_fail_closed(self) -> None:
        invalid_values = (-1, 1.5, True, float("nan"), float("inf"), float("-inf"))
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(CREDIT.CreditModelError):
                    CREDIT.estimate(estimate_input(phase(input_tokens=value)), RATE_CARD)

    def test_nonfinite_and_negative_rates_fail_closed(self) -> None:
        for value in ("-1", "NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                card = copy.deepcopy(RATE_CARD)
                card["models"]["gpt-5.6-sol"]["input_credits_per_million_tokens"] = value
                with self.assertRaises(CREDIT.CreditModelError):
                    CREDIT.validate_rate_card(card)

    def test_rate_card_schema_extra_field_and_unsupported_unit_fail_closed(self) -> None:
        wrong_version = copy.deepcopy(RATE_CARD)
        wrong_version["schema_version"] = 2
        with self.assertRaisesRegex(CREDIT.CreditModelError, "schema_version"):
            CREDIT.validate_rate_card(wrong_version)

        extra = copy.deepcopy(RATE_CARD)
        extra["api_dollars_per_credit"] = 1
        with self.assertRaisesRegex(CREDIT.CreditModelError, "unsupported fields"):
            CREDIT.validate_rate_card(extra)

        nested_extra = copy.deepcopy(RATE_CARD)
        nested_extra["models"]["gpt-5.6-sol"]["api_price"] = "1"
        with self.assertRaisesRegex(CREDIT.CreditModelError, "unsupported fields"):
            CREDIT.validate_rate_card(nested_extra)

        missing = copy.deepcopy(RATE_CARD)
        del missing["source"]["observed_at"]
        with self.assertRaisesRegex(CREDIT.CreditModelError, "missing fields"):
            CREDIT.validate_rate_card(missing)

        wrong_unit = copy.deepcopy(RATE_CARD)
        wrong_unit["unit"] = "USD per 1M tokens"
        with self.assertRaisesRegex(CREDIT.CreditModelError, "unit"):
            CREDIT.validate_rate_card(wrong_unit)

    def test_rate_card_cannot_claim_included_plan_percentage_conversion(self) -> None:
        for field in ("included_plan_allowance_compatible", "plan_limit_percentage_convertible"):
            with self.subTest(field=field):
                card = copy.deepcopy(RATE_CARD)
                card["scope"][field] = True
                with self.assertRaises(CREDIT.CreditModelError):
                    CREDIT.validate_rate_card(card)
        card = copy.deepcopy(RATE_CARD)
        card["scope"]["billing_context"] = "included_plan"
        with self.assertRaisesRegex(CREDIT.CreditModelError, "purchased_credits"):
            CREDIT.validate_rate_card(card)

    def test_rate_card_digest_binding_and_fingerprint_change(self) -> None:
        original = CREDIT.rate_card_fingerprint(RATE_CARD)
        self.assertRegex(original, r"^sha256:[0-9a-f]{64}$")
        source = estimate_input(phase())
        source["rate_card_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(CREDIT.CreditModelError, "does not match"):
            CREDIT.estimate(source, RATE_CARD)

        changed = copy.deepcopy(RATE_CARD)
        changed["models"]["gpt-5.6-luna"]["output_credits_per_million_tokens"] = "31"
        self.assertNotEqual(CREDIT.rate_card_fingerprint(changed), original)

    def test_rate_card_id_binding(self) -> None:
        source = estimate_input(phase())
        source["rate_card_id"] = "another-rate-card"
        with self.assertRaisesRegex(CREDIT.CreditModelError, "rate_card_id"):
            CREDIT.estimate(source, RATE_CARD)

    def test_expiry_date_boundary_is_inclusive(self) -> None:
        result = CREDIT.estimate(estimate_input(phase(), as_of="2026-11-21"), RATE_CARD)
        self.assertEqual(result["as_of"], "2026-11-21")
        with self.assertRaisesRegex(CREDIT.CreditModelError, "expired"):
            CREDIT.estimate(estimate_input(phase(), as_of="2026-11-22"), RATE_CARD)
        with self.assertRaisesRegex(CREDIT.CreditModelError, "not yet valid"):
            CREDIT.estimate(estimate_input(phase(), as_of="2026-08-27"), RATE_CARD)

    def test_total_tokens_cannot_replace_classified_token_fields(self) -> None:
        source = estimate_input(phase())
        source["phases"] = [{"phase_id": "execution", "model": "gpt-5.6-sol", "total_tokens": 1_000_000}]
        with self.assertRaises(CREDIT.CreditModelError):
            CREDIT.estimate(source, RATE_CARD)

    def test_output_preserves_sub_micro_credit_precision(self) -> None:
        result = CREDIT.estimate(
            estimate_input(
                phase(
                    "gpt-5.6-luna",
                    input_tokens=1,
                    cached_input_tokens=1,
                )
            ),
            RATE_CARD,
        )
        self.assertEqual(result["total_credits"], "0.0000005")
        self.assertEqual(result["by_phase"][0]["cached_input_credits"], "0.0000005")

    def test_internal_calculation_preserves_more_than_default_decimal_precision(self) -> None:
        tokens = 10**80 + 1
        result = CREDIT.estimate(estimate_input(phase(input_tokens=tokens)), RATE_CARD)
        self.assertEqual(result["total_credits"], f"{10**76}.0001")

    def test_cli_fingerprint_and_estimate(self) -> None:
        fingerprint = subprocess.run(
            [sys.executable, str(SCRIPT), "fingerprint", "--rate-card", str(RATE_CARD_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(fingerprint.returncode, 0, fingerprint.stderr)
        fingerprint_output = json.loads(fingerprint.stdout)
        self.assertFalse(fingerprint_output["automatic_model_execution_allowed"])

        source = estimate_input(phase(input_tokens=10, output_tokens=2))
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "usage.json"
            input_path.write_text(json.dumps(source), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "estimate",
                    "--rate-card",
                    str(RATE_CARD_PATH),
                    "--input",
                    str(input_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["total_credits"], "0.002")
        self.assertFalse(output["applicability"]["automatic_model_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
