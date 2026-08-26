from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "lifecycle_contract.py"
SPEC = importlib.util.spec_from_file_location("lifecycle_contract", SCRIPT)
assert SPEC and SPEC.loader
LIFECYCLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIFECYCLE)


class LifecycleContractTests(unittest.TestCase):
    def test_clean_native_shape_reaches_acceptance_with_fresh_evidence(self) -> None:
        result = LIFECYCLE.replay(
            {
                "schema_version": 1,
                "package_id": "worker-package",
                "initial_effort": "medium",
                "events": [
                    {"type": "dispatch"},
                    {"type": "handoff", "authoritative_checks_passed": True},
                    {"type": "review_pass", "ownership_passed": True},
                ],
            }
        )
        self.assertEqual(result["status"], "ACCEPTED")

    def test_candidate_change_invalidates_acceptance_evidence(self) -> None:
        state = LIFECYCLE.initial_state("worker-package", "medium")
        state = LIFECYCLE.transition(state, {"type": "dispatch"})
        state = LIFECYCLE.transition(state, {"type": "handoff", "authoritative_checks_passed": True})
        state = LIFECYCLE.transition(state, {"type": "candidate_changed"})
        with self.assertRaisesRegex(LIFECYCLE.LifecycleError, "stale or missing"):
            LIFECYCLE.transition(state, {"type": "review_pass", "ownership_passed": True})
        state = LIFECYCLE.transition(state, {"type": "refresh_evidence"})
        self.assertEqual(
            LIFECYCLE.transition(state, {"type": "review_pass", "ownership_passed": True})["status"],
            "ACCEPTED",
        )

    def test_timeout_is_terminal_failure(self) -> None:
        state = LIFECYCLE.transition(LIFECYCLE.initial_state("worker-package", "high"), {"type": "dispatch"})
        state = LIFECYCLE.transition(state, {"type": "timeout"})
        self.assertEqual(state["status"], "FAILED")
        with self.assertRaises(LIFECYCLE.LifecycleError):
            LIFECYCLE.transition(state, {"type": "dispatch"})

    def test_continuation_obeys_one_repair_budget(self) -> None:
        state = LIFECYCLE.transition(LIFECYCLE.initial_state("worker-package", "high"), {"type": "dispatch"})
        state = LIFECYCLE.transition(
            state,
            {"type": "handoff", "authoritative_checks_passed": True, "continuation_ref": "thread:opaque"},
        )
        state = LIFECYCLE.transition(state, {"type": "review_fail"})
        state = LIFECYCLE.transition(state, {"type": "continue_repair", "new_evidence": True})
        state = LIFECYCLE.transition(
            state,
            {"type": "handoff", "authoritative_checks_passed": False, "continuation_ref": "thread:opaque"},
        )
        state = LIFECYCLE.transition(state, {"type": "review_fail"})
        with self.assertRaisesRegex(LIFECYCLE.LifecycleError, "one-repair"):
            LIFECYCLE.transition(state, {"type": "continue_repair", "new_evidence": True})

    def test_one_effort_escalation_then_sol_reclaim(self) -> None:
        state = LIFECYCLE.transition(LIFECYCLE.initial_state("worker-package", "high"), {"type": "dispatch"})
        state = LIFECYCLE.transition(state, {"type": "handoff", "authoritative_checks_passed": False})
        state = LIFECYCLE.transition(state, {"type": "review_fail"})
        state = LIFECYCLE.transition(state, {"type": "escalate", "next_effort": "xhigh"})
        state = LIFECYCLE.transition(state, {"type": "handoff", "authoritative_checks_passed": False})
        state = LIFECYCLE.transition(state, {"type": "review_fail"})
        with self.assertRaisesRegex(LIFECYCLE.LifecycleError, "budget exhausted"):
            LIFECYCLE.transition(state, {"type": "escalate", "next_effort": "max"})
        self.assertEqual(LIFECYCLE.transition(state, {"type": "sol_reclaim"})["status"], "SOL_RECLAIMED")


if __name__ == "__main__":
    unittest.main()
