from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "frontier_planner.py"
SPEC = importlib.util.spec_from_file_location("frontier_planner", SCRIPT)
assert SPEC and SPEC.loader
PLANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANNER)


def package(
    package_id: str,
    *,
    executor: str = "LUNA",
    domain_id: str = "routing",
    dependencies: list[str] | None = None,
    baseline: float = 10,
    predicted: float = 2,
    incremental: float = 1,
    seconds: float = 30,
    critical: bool = False,
    status: str = "PENDING",
    repair: dict | None = None,
) -> dict:
    return {
        "package_id": package_id,
        "executor": executor,
        "domain_id": domain_id,
        "dependencies": dependencies or [],
        "path_scopes": [f"src/{package_id}"],
        "acceptance_ids": [f"accept-{package_id}"],
        "baseline_sol_weight": baseline,
        "predicted_executor_weight": predicted,
        "incremental_sol_weight": incremental,
        "expected_seconds": seconds,
        "critical_path": critical,
        "status": status,
        "repair": repair,
    }


def source(packages: list[dict] | None = None, *, writer_cap: int = 1) -> dict:
    return {
        "schema_version": 1,
        "controller_id": "sol-controller",
        "writer_cap": writer_cap,
        "packages": packages or [package("core-a")],
    }


def repair(**overrides) -> dict:
    value = {
        "attempts_used": 0,
        "attempts_max": 2,
        "remaining_cost_weight": 1,
        "next_cost_weight": 0.5,
        "marginal_net_substitution": 1,
        "new_evidence": True,
    }
    value.update(overrides)
    return value


class FrontierPlannerTests(unittest.TestCase):
    def test_template_is_complete_evaluable_and_replay_only(self) -> None:
        template = PLANNER.template()
        result = PLANNER.plan(template)
        self.assertEqual(result["luna_envelope"]["package_ids"], ["core-a"])
        self.assertFalse(result["automatic_execution_allowed"])
        self.assertEqual(
            set(result),
            {
                "schema_version",
                "status",
                "plan_fingerprint",
                "luna_envelope",
                "sol_ready_package_ids",
                "review_package_ids",
                "repair_package_ids",
                "blocked_package_reasons",
                "running_luna_package_ids",
                "tail_wait_allowed",
                "automatic_execution_allowed",
            },
        )

    def test_domain_selection_and_package_order_follow_all_tie_breakers(self) -> None:
        packages = [
            package("route-wide", baseline=8, predicted=2, incremental=1, seconds=10),
            package("route-critical", baseline=4, predicted=1, incremental=1, seconds=20, critical=True),
            package("docs-critical", domain_id="docs", baseline=9, predicted=1, incremental=1, seconds=40, critical=True),
        ]
        result = PLANNER.plan(source(list(reversed(packages))))
        self.assertEqual(result["luna_envelope"]["domain_id"], "routing")
        self.assertEqual(
            result["luna_envelope"]["package_ids"],
            ["route-critical", "route-wide"],
        )
        self.assertEqual(result["luna_envelope"]["total_net_substitution"], 7.0)
        self.assertEqual(result["luna_envelope"]["total_expected_seconds"], 30.0)

    def test_domain_id_is_final_stable_tie_breaker(self) -> None:
        result = PLANNER.plan(
            source(
                [
                    package("z-package", domain_id="z-domain"),
                    package("a-package", domain_id="a-domain"),
                ]
            )
        )
        self.assertEqual(result["luna_envelope"]["domain_id"], "a-domain")

    def test_sol_ready_ignores_nonpositive_substitution_but_luna_does_not(self) -> None:
        result = PLANNER.plan(
            source(
                [
                    package("sol-work", executor="SOL", baseline=1, predicted=3),
                    package("luna-work", baseline=1, predicted=3),
                ]
            )
        )
        self.assertEqual(result["sol_ready_package_ids"], ["sol-work"])
        self.assertEqual(
            result["blocked_package_reasons"],
            {"luna-work": ["nonpositive-net-substitution"]},
        )

    def test_blocked_reasons_include_dependency_and_luna_value_gate(self) -> None:
        result = PLANNER.plan(
            source(
                [
                    package("upstream", status="RUNNING"),
                    package(
                        "downstream",
                        dependencies=["upstream"],
                        baseline=1,
                        predicted=1,
                    ),
                    package("sol-downstream", executor="SOL", dependencies=["upstream"]),
                ]
            )
        )
        self.assertEqual(
            result["blocked_package_reasons"],
            {
                "downstream": [
                    "dependency-not-terminal",
                    "nonpositive-net-substitution",
                ],
                "sol-downstream": ["dependency-not-terminal"],
            },
        )

    def test_review_and_only_eligible_luna_repair_are_recommended(self) -> None:
        packages = [
            package("handoff", status="HANDOFF"),
            package("eligible", status="FAILED", repair=repair()),
            package("sol-failed", executor="SOL", status="FAILED", repair=repair()),
            package("no-evidence", status="FAILED", repair=repair(new_evidence=False)),
            package("spent", status="FAILED", repair=repair(attempts_used=2)),
            package("zero-cost", status="FAILED", repair=repair(next_cost_weight=0)),
            package("over-budget", status="FAILED", repair=repair(next_cost_weight=2)),
            package("no-margin", status="FAILED", repair=repair(marginal_net_substitution=0)),
        ]
        result = PLANNER.plan(source(packages))
        self.assertEqual(result["review_package_ids"], ["handoff"])
        self.assertEqual(result["repair_package_ids"], ["eligible"])

    def test_full_writer_pool_suppresses_envelope_and_permits_true_tail_wait(self) -> None:
        result = PLANNER.plan(
            source(
                [
                    package("active", status="RUNNING"),
                    package("next", dependencies=["active"]),
                ]
            )
        )
        self.assertIsNone(result["luna_envelope"])
        self.assertEqual(result["running_luna_package_ids"], ["active"])
        self.assertTrue(result["tail_wait_allowed"])

    def test_tail_wait_is_false_when_controller_has_any_queue(self) -> None:
        packages = [
            package("active", status="RUNNING"),
            package("sol-ready", executor="SOL"),
        ]
        self.assertFalse(PLANNER.plan(source(packages))["tail_wait_allowed"])

    def test_done_requires_every_package_to_be_terminal(self) -> None:
        done = source(
            [
                package("accepted", status="ACCEPTED"),
                package("reclaimed", dependencies=["accepted"], status="RECLAIMED"),
            ]
        )
        result = PLANNER.plan(done)
        self.assertEqual(result["status"], "DONE")
        self.assertIsNone(result["luna_envelope"])
        self.assertFalse(result["tail_wait_allowed"])

    def test_fingerprint_is_order_independent_and_supplied_value_is_verified(self) -> None:
        first_package = package("first")
        first_package["path_scopes"] = ["src/first/z", "src/first/a"]
        first_package["acceptance_ids"] = ["accept-first-z", "accept-first-a"]
        second_package = package("second", dependencies=["first"])
        first = source([first_package, second_package])
        second = copy.deepcopy(first)
        second["packages"].reverse()
        second["packages"][1]["path_scopes"].reverse()
        second["packages"][1]["acceptance_ids"].reverse()
        fingerprint = PLANNER.plan(first)["plan_fingerprint"]
        self.assertEqual(PLANNER.plan(second)["plan_fingerprint"], fingerprint)
        second["plan_fingerprint"] = fingerprint
        self.assertEqual(PLANNER.plan(second)["plan_fingerprint"], fingerprint)
        second["plan_fingerprint"] = "sha256:" + "0" * 64
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(second)

    def test_plan_does_not_mutate_valid_or_invalid_input(self) -> None:
        valid = source()
        before = copy.deepcopy(valid)
        PLANNER.plan(valid)
        self.assertEqual(valid, before)
        invalid = source()
        invalid["packages"][0]["dependencies"] = ["missing"]
        before = copy.deepcopy(invalid)
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(invalid)
        self.assertEqual(invalid, before)

    def test_top_and_package_fields_are_exact(self) -> None:
        top = source()
        top["unexpected"] = 1
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(top)
        item = source()
        item["packages"][0]["unexpected"] = 1
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(item)
        missing = source()
        del missing["packages"][0]["repair"]
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(missing)

    def test_identifiers_numbers_booleans_and_counts_fail_closed(self) -> None:
        mutations = [
            ("controller_id", "UPPER"),
            ("writer_cap", True),
            ("writer_cap", 9),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                item = source()
                item[field] = value
                with self.assertRaises(PLANNER.FrontierError):
                    PLANNER.plan(item)
        for field, value in (
            ("baseline_sol_weight", 0),
            ("expected_seconds", 0),
            ("predicted_executor_weight", -1),
            ("incremental_sol_weight", True),
            ("baseline_sol_weight", float("inf")),
            ("critical_path", 1),
        ):
            with self.subTest(field=field, value=value):
                item = source()
                item["packages"][0][field] = value
                with self.assertRaises(PLANNER.FrontierError):
                    PLANNER.plan(item)

    def test_package_acceptance_and_dependency_ids_are_unique_and_known(self) -> None:
        duplicate_package = source([package("same"), package("same")])
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(duplicate_package)
        duplicate_acceptance = source([package("one"), package("two")])
        duplicate_acceptance["packages"][1]["acceptance_ids"] = ["accept-one"]
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(duplicate_acceptance)
        unknown = source([package("one", dependencies=["missing"])])
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(unknown)
        repeated = source([package("one"), package("two", dependencies=["one", "one"])])
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(repeated)

    def test_cycles_and_self_dependencies_are_rejected(self) -> None:
        for packages in (
            [package("one", dependencies=["one"])],
            [package("one", dependencies=["two"]), package("two", dependencies=["one"])],
        ):
            with self.subTest(packages=packages):
                with self.assertRaises(PLANNER.FrontierError):
                    PLANNER.plan(source(packages))

    def test_nonpending_state_dependencies_running_executor_and_cap_are_checked(self) -> None:
        bad_state = source(
            [
                package("upstream"),
                package("active", dependencies=["upstream"], status="RUNNING"),
            ]
        )
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(bad_state)
        running_sol = source([package("active", executor="SOL", status="RUNNING")])
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(running_sol)
        over_cap = source(
            [package("one", status="RUNNING"), package("two", status="RUNNING")],
            writer_cap=1,
        )
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(over_cap)

    def test_repair_schema_counts_and_status_coupling_are_strict(self) -> None:
        nonfailed = source([package("one", repair=repair())])
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(nonfailed)
        failed_without = source([package("one", status="FAILED")])
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(failed_without)
        for overrides in (
            {"attempts_used": True},
            {"attempts_used": 3},
            {"new_evidence": 1},
            {"next_cost_weight": float("nan")},
            {"unexpected": 1},
        ):
            with self.subTest(overrides=overrides):
                item = source([package("one", status="FAILED", repair=repair(**overrides))])
                with self.assertRaises(PLANNER.FrontierError):
                    PLANNER.plan(item)

    def test_paths_must_be_normal_relative_non_device_and_nonoverlapping(self) -> None:
        invalid_paths = [
            "/absolute",
            "C:/drive",
            "src\\windows",
            "src/../escape",
            "src//double",
            "src/CON.txt",
            "src/control\x00",
        ]
        for path in invalid_paths:
            with self.subTest(path=path):
                item = source()
                item["packages"][0]["path_scopes"] = [path]
                with self.assertRaises(PLANNER.FrontierError):
                    PLANNER.plan(item)
        duplicate = source()
        duplicate["packages"][0]["path_scopes"] = ["src/a", "SRC/A"]
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(duplicate)
        overlap = source([package("one"), package("two")])
        overlap["packages"][0]["path_scopes"] = ["Source/Core"]
        overlap["packages"][1]["path_scopes"] = ["source/core/child"]
        with self.assertRaises(PLANNER.FrontierError):
            PLANNER.plan(overlap)


if __name__ == "__main__":
    unittest.main()
