from __future__ import annotations

import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "handoff_preflight.py"
SPEC = importlib.util.spec_from_file_location("handoff_preflight", SCRIPT)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)

ZERO = "sha256:" + "0" * 64
ONE = "sha256:" + "1" * 64
THREE = "sha256:" + "3" * 64


class HandoffPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PREFLIGHT.template()

    def test_template_is_complete_ready_and_fresh(self) -> None:
        result = PREFLIGHT.evaluate(self.source)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["review_depth"], "STANDARD")
        self.assertNotIn("manifest_fingerprint", self.source)
        self.assertEqual(
            {probe["category"] for probe in self.source["probe_results"]},
            {"schema", "types", "boundaries", "capacity", "derived-values", "immutability", "error-channel"},
        )
        first = PREFLIGHT.template()
        first["required_probe_categories"].append("extra")
        self.assertNotIn("extra", PREFLIGHT.template()["required_probe_categories"])

    def test_exact_fields_and_types_matrix(self) -> None:
        cases = [
            ("unknown", lambda item: item.update(unknown=1)),
            ("missing", lambda item: item.pop("executor_id")),
            ("schema bool", lambda item: item.update(schema_version=True)),
            ("repair bool", lambda item: item.update(repair_rounds=False)),
            ("repair range", lambda item: item.update(repair_rounds=4)),
            ("scopes tuple", lambda item: item.update(allowed_path_scopes=("src/core",))),
            ("results object", lambda item: item.update(acceptance_results={})),
        ]
        for label, mutate in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.source)
                mutate(candidate)
                with self.assertRaises(PREFLIGHT.PreflightError):
                    PREFLIGHT.evaluate(candidate)

    def test_identifier_digest_and_enum_matrix(self) -> None:
        cases = [
            ("uppercase id", lambda item: item.update(package_id="Core")),
            ("underscore id", lambda item: item.update(executor_id="luna_writer")),
            ("bad digest", lambda item: item.update(candidate_digest="sha256:" + "A" * 64)),
            ("risk enum", lambda item: item.update(review_risk="urgent")),
            ("acceptance status", lambda item: item["acceptance_results"][0].update(status="PASS")),
            ("probe category", lambda item: item["probe_results"][0].update(category="Types")),
        ]
        for label, mutate in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.source)
                mutate(candidate)
                with self.assertRaises(PREFLIGHT.PreflightError):
                    PREFLIGHT.evaluate(candidate)

    def test_path_normalization_scope_and_range_matrix(self) -> None:
        cases = [
            ("absolute", "/etc/passwd"),
            ("drive absolute", "C:/repo/file.py"),
            ("drive relative", "C:file.py"),
            ("backslash", "src\\core\\main.py"),
            ("empty segment", "src//main.py"),
            ("dot segment", "src/./main.py"),
            ("traversal", "src/../main.py"),
            ("control", "src/\x00main.py"),
            ("device", "src/CON.txt"),
            ("duplicate folded", "SRC/CORE/main.py"),
        ]
        for label, path in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.source)
                if label == "duplicate folded":
                    candidate["changed_paths"] = ["src/core/main.py", path]
                else:
                    candidate["changed_paths"] = [path]
                with self.assertRaises(PREFLIGHT.PreflightError):
                    PREFLIGHT.evaluate(candidate)
        candidate = copy.deepcopy(self.source)
        candidate["allowed_path_scopes"] = ["src/core", "src"]
        candidate["changed_paths"] = ["SRC/CORE/new.py"]
        self.assertEqual(PREFLIGHT.evaluate(candidate)["status"], "READY")
        candidate["allowed_path_scopes"] = ["src/core"]
        candidate["changed_paths"] = ["src/other.py"]
        self.assertEqual(PREFLIGHT.evaluate(candidate)["changed_path_violations"], ["src/other.py"])

        trailing_space = copy.deepcopy(self.source)
        trailing_space["changed_paths"] = ["src/core/file "]
        self.assertEqual(PREFLIGHT.evaluate(trailing_space)["status"], "READY")

        ordinary_colon = copy.deepcopy(self.source)
        ordinary_colon["changed_paths"] = ["src/core/normal:name.py"]
        self.assertEqual(PREFLIGHT.evaluate(ordinary_colon)["status"], "READY")

        spaced_device = copy.deepcopy(self.source)
        spaced_device["changed_paths"] = ["src/core/CON .txt"]
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(spaced_device)

        colon_device = copy.deepcopy(self.source)
        colon_device["changed_paths"] = ["src/core/nul:stream"]
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(colon_device)

    def test_surrogate_path_is_rejected_without_mutation(self) -> None:
        candidate = copy.deepcopy(self.source)
        candidate["changed_paths"] = ["src/core/\ud800.py"]
        before = copy.deepcopy(candidate)
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(candidate)
        self.assertEqual(candidate, before)

    def test_acceptance_and_probe_completeness_uniqueness_matrix(self) -> None:
        missing = copy.deepcopy(self.source)
        missing["acceptance_results"] = []
        result = PREFLIGHT.evaluate(missing)
        self.assertEqual(result["missing_acceptance_ids"], ["accept-core"])

        duplicate_acceptance = copy.deepcopy(self.source)
        duplicate_acceptance["acceptance_results"].append(copy.deepcopy(duplicate_acceptance["acceptance_results"][0]))
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(duplicate_acceptance)

        duplicate_probe = copy.deepcopy(self.source)
        duplicate_probe["probe_results"].append(copy.deepcopy(duplicate_probe["probe_results"][0]))
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(duplicate_probe)

        extra_category = copy.deepcopy(self.source)
        extra_category["probe_results"][0]["category"] = "not-required"
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(extra_category)

    def test_failed_and_stale_are_orthogonal_matrix(self) -> None:
        candidate = copy.deepcopy(self.source)
        candidate["acceptance_results"][0]["status"] = "FAILED"
        candidate["acceptance_results"][0]["candidate_digest"] = ONE
        candidate["probe_results"][0]["status"] = "FAILED"
        candidate["probe_results"][0]["candidate_digest"] = ONE
        result = PREFLIGHT.evaluate(candidate)
        self.assertEqual(result["failed_acceptance_ids"], ["accept-core"])
        self.assertEqual(result["failed_probe_ids"], ["probe-schema"])
        self.assertEqual(
            result["stale_evidence_ids"], ["acceptance:accept-core", "probe:probe-schema"]
        )
        self.assertEqual(result["status"], "HOLD")

    def test_fingerprint_and_blocker_derivation_matrix(self) -> None:
        base = PREFLIGHT.evaluate(self.source)
        shuffled = copy.deepcopy(self.source)
        shuffled["required_probe_categories"].reverse()
        shuffled["probe_results"].reverse()
        shuffled["changed_paths"].reverse()
        self.assertEqual(base["manifest_fingerprint"], PREFLIGHT.evaluate(shuffled)["manifest_fingerprint"])

        risk = copy.deepcopy(self.source)
        risk["risks"] = [
            {
                "risk_id": "risk-medium",
                "severity": "medium",
                "status": "OPEN",
                "evidence_digest": None,
                "candidate_digest": ZERO,
            }
        ]
        result = PREFLIGHT.evaluate(risk)
        self.assertEqual(result["open_risk_ids"], ["risk-medium"])
        self.assertEqual(result["review_depth"], "DEEP")

        risk["risks"][0]["status"] = "MITIGATED"
        risk["risks"][0]["evidence_digest"] = THREE
        result = PREFLIGHT.evaluate(risk)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["review_depth"], "STANDARD")

    def test_review_depth_matrix(self) -> None:
        targeted = copy.deepcopy(self.source)
        targeted["review_risk"] = "low"
        self.assertEqual(PREFLIGHT.evaluate(targeted)["review_depth"], "TARGETED")
        standard = copy.deepcopy(self.source)
        self.assertEqual(PREFLIGHT.evaluate(standard)["review_depth"], "STANDARD")
        deep = copy.deepcopy(targeted)
        deep["repair_rounds"] = 1
        self.assertEqual(PREFLIGHT.evaluate(deep)["review_depth"], "DEEP")

    def test_valid_and_invalid_input_are_immutable(self) -> None:
        valid = copy.deepcopy(self.source)
        before = copy.deepcopy(valid)
        PREFLIGHT.evaluate(valid)
        self.assertEqual(valid, before)

        invalid = copy.deepcopy(self.source)
        invalid["changed_paths"] = ["src/../escape.py"]
        before = copy.deepcopy(invalid)
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(invalid)
        self.assertEqual(invalid, before)

    def test_no_file_or_command_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            before = sorted(os.listdir(directory))
            PREFLIGHT.evaluate(self.source)
            after = sorted(os.listdir(directory))
            self.assertEqual(before, after)

    def test_supplied_fingerprint_must_match(self) -> None:
        candidate = copy.deepcopy(self.source)
        candidate["manifest_fingerprint"] = PREFLIGHT.evaluate(candidate)["manifest_fingerprint"]
        self.assertEqual(PREFLIGHT.evaluate(candidate)["status"], "READY")
        candidate["manifest_fingerprint"] = ONE
        with self.assertRaises(PREFLIGHT.PreflightError):
            PREFLIGHT.evaluate(candidate)


if __name__ == "__main__":
    unittest.main()
