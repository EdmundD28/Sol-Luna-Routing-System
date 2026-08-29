from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "net_substitution.py"


class NetSubstitutionTests(unittest.TestCase):
    def package(
        self,
        package_id: str,
        *,
        depends_on: list[str] | None = None,
        domain_id: str = "python",
        baseline: float = 100.0,
        execution: float = 20.0,
        first_pass: float = 1.0,
        defect: float = 0.01,
        replay: float = 0.0,
        overhead: float = 1.0,
        context_new: float = 2.0,
        context_retained: float = 0.5,
    ) -> dict:
        return {
            "package_id": package_id,
            "depends_on": depends_on or [],
            "domain_id": domain_id,
            "baseline_sol_credits": baseline,
            "baseline_sol_seconds": baseline * 10,
            "execution_credits": execution,
            "execution_seconds": execution * 4,
            "first_pass_probability": first_pass,
            "final_defect_probability": defect,
            "repair_probability": 0.0,
            "repair_credits": 0.0,
            "repair_seconds": 0.0,
            "terminal_failure_probability": 0.0,
            "terminal_recovery_credits": 0.0,
            "terminal_recovery_seconds": 0.0,
            "sol_planning_credits": overhead,
            "sol_planning_seconds": 5.0,
            "sol_coordination_credits": overhead,
            "sol_coordination_seconds": 5.0,
            "sol_review_credits": overhead,
            "sol_review_seconds": 5.0,
            "sol_integration_credits": overhead,
            "sol_integration_seconds": 5.0,
            "sol_replay_probability": replay,
            "new_context_credits": context_new,
            "new_context_seconds": 10.0,
            "retained_context_credits": context_retained,
            "retained_context_seconds": 2.0,
        }

    def source(self, packages: list[dict] | None = None, **overrides: object) -> dict:
        result = {
            "schema_version": 1,
            "packages": packages or [self.package("core")],
            "minimum_first_pass_probability": 0.8,
            "maximum_final_defect_probability": 0.05,
            "minimum_credit_savings_fraction": 0.1,
            "minimum_sol_labor_reduction": 0.1,
            "maximum_active_luna_writers": 1,
        }
        result.update(overrides)
        return result

    def evaluate(self, source: dict) -> dict:
        spec = __import__("importlib.util").util.spec_from_file_location("net_substitution", SCRIPT)
        assert spec and spec.loader
        module = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.evaluate(source)

    def test_high_baseline_low_cost_is_selected(self) -> None:
        source = self.source([
            self.package("small", baseline=20, execution=20),
            self.package("large", baseline=200, execution=15),
        ])
        result = self.evaluate(source)
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_candidate"]["luna_package_ids"], ["large"])
        self.assertGreater(result["selected_candidate"]["gross_delegated_baseline"], 0)

    def test_replay_and_overhead_can_make_cheap_luna_net_negative(self) -> None:
        package = self.package("risky", baseline=100, execution=1, replay=1.0, overhead=30)
        result = self.evaluate(self.source([package], minimum_credit_savings_fraction=0.0, minimum_sol_labor_reduction=0.0))
        self.assertEqual(result["route"], "SOL_ONLY")
        candidate = next(item for item in result["candidates"] if item["luna_package_ids"] == ["risky"])
        self.assertLess(candidate["net_route_savings"], 0)
        self.assertIn("credit_savings_below_floor", candidate["ineligible_reasons"])

    def test_splitting_does_not_create_extra_net_savings(self) -> None:
        whole = self.evaluate(self.source([self.package("whole", baseline=100, execution=20)]))
        split = self.evaluate(self.source([
            self.package("part-a", baseline=50, execution=10),
            self.package("part-b", baseline=50, execution=10, depends_on=["part-a"]),
        ]))
        self.assertLessEqual(split["selected_candidate"]["net_route_savings"], whole["selected_candidate"]["net_route_savings"])

    def test_luna_subset_can_skip_negative_unlock_package_when_sol_can_run_it(self) -> None:
        unlock = self.package("unlock", baseline=10, execution=20, overhead=4)
        dependent = self.package("dependent", baseline=200, execution=10, depends_on=["unlock"])
        result = self.evaluate(self.source([unlock, dependent], minimum_credit_savings_fraction=0.0, minimum_sol_labor_reduction=0.0))
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_candidate"]["luna_package_ids"], ["dependent"])

    def test_luna_subset_can_depend_on_sol_preparation_package(self) -> None:
        preparation = self.package("prep", baseline=10, execution=20)
        dependent = self.package("dependent", baseline=200, execution=10, depends_on=["prep"])
        result = self.evaluate(self.source(
            [preparation, dependent], minimum_credit_savings_fraction=0.0,
            minimum_sol_labor_reduction=0.0,
        ))
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_candidate"]["luna_package_ids"], ["dependent"])

    def test_luna_owned_recovery_is_not_counted_as_sol_labor(self) -> None:
        package = self.package("recoverable", baseline=100, execution=10)
        package.update({"repair_probability": 1.0, "repair_credits": 30, "repair_actor": "LUNA"})
        result = self.evaluate(self.source(
            [package], minimum_credit_savings_fraction=0.0,
            minimum_sol_labor_reduction=0.0,
        ))
        candidate = next(item for item in result["candidates"] if item["luna_package_ids"] == ["recoverable"])
        self.assertEqual(candidate["expected_sol_labor"], 4.0)
        self.assertEqual(candidate["expected_total_credits"], 46.0)
        self.assertEqual(candidate["expected_net_substitution"], 0.54)
        self.assertEqual(
            candidate["expected_net_substitution"],
            min(candidate["structural_net_substitution"], candidate["expected_sol_labor_reduction"]),
        )

    def test_retained_context_is_used_for_same_domain_worker(self) -> None:
        packages = [
            self.package("first", baseline=100, execution=5, context_new=20, context_retained=1),
            self.package("second", baseline=100, execution=5, depends_on=["first"], context_new=20, context_retained=1),
        ]
        result = self.evaluate(self.source(packages, maximum_active_luna_writers=1))
        selected = result["selected_candidate"]
        self.assertEqual(selected["context_reuse_count"], 1)
        self.assertEqual(selected["context_new_count"], 1)
        self.assertEqual(selected["expected_context_credits"], 21.0)
        self.assertEqual(selected["expected_context_seconds"], 12.0)
        self.assertLess(selected["context_reuse_fraction"], 1.0)

    def test_second_writer_is_not_selected_when_context_and_coordination_make_it_worse(self) -> None:
        packages = [
            self.package("first", baseline=100, execution=10, context_new=40),
            self.package("second", baseline=100, execution=10, context_new=40),
        ]
        result = self.evaluate(self.source(packages, maximum_active_luna_writers=2, minimum_credit_savings_fraction=0.0, minimum_sol_labor_reduction=0.0))
        self.assertEqual(result["route"], "SOL_LUNA")
        self.assertEqual(result["selected_candidate"]["active_writers"], 1)

    def test_quality_regression_is_hard_gate(self) -> None:
        result = self.evaluate(self.source([self.package("bad", first_pass=0.5, defect=0.2)]))
        self.assertEqual(result["route"], "SOL_ONLY")
        candidate = next(item for item in result["candidates"] if item["luna_package_ids"] == ["bad"])
        self.assertFalse(candidate["eligible"])
        self.assertIn("first_pass_probability_below_floor", candidate["ineligible_reasons"])

    def test_incremental_delegation_burden_ceiling_is_independent_gate(self) -> None:
        # One package has 4 credits of Sol overhead and 2 credits of context
        # against a 100-credit delegated Sol baseline: burden is exactly 0.06.
        package = self.package("burden", execution=1.0)
        at_ceiling = self.evaluate(self.source([package], maximum_incremental_delegation_burden_fraction=0.06))
        candidate = next(item for item in at_ceiling["candidates"] if item["luna_package_ids"] == ["burden"])
        self.assertEqual(candidate["incremental_delegation_burden_fraction"], 0.06)
        self.assertEqual(candidate["maximum_incremental_delegation_burden_fraction"], 0.06)
        self.assertTrue(candidate["eligible"])
        self.assertNotIn("incremental_delegation_burden_above_ceiling", candidate["ineligible_reasons"])

        below = self.evaluate(self.source([package], maximum_incremental_delegation_burden_fraction=0.07))
        below_candidate = next(item for item in below["candidates"] if item["luna_package_ids"] == ["burden"])
        self.assertTrue(below_candidate["eligible"])

        above = self.evaluate(self.source([package], maximum_incremental_delegation_burden_fraction=0.059))
        above_candidate = next(item for item in above["candidates"] if item["luna_package_ids"] == ["burden"])
        self.assertFalse(above_candidate["eligible"])
        self.assertIn("incremental_delegation_burden_above_ceiling", above_candidate["ineligible_reasons"])

    def test_incremental_delegation_burden_limit_is_strict_finite_fraction(self) -> None:
        for value in (True, -0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.evaluate(self.source(maximum_incremental_delegation_burden_fraction=value))

    def test_legacy_template_and_input_immutability(self) -> None:
        spec = __import__("importlib.util").util.spec_from_file_location("net_substitution", SCRIPT)
        assert spec and spec.loader
        module = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = module.template()
        original = copy.deepcopy(source)
        evaluated = module.evaluate(source)
        self.assertEqual(source, original)
        self.assertEqual(evaluated["schema_version"], 1)

    def test_input_order_does_not_change_selection(self) -> None:
        packages = [self.package("a", baseline=100, execution=10), self.package("b", baseline=80, execution=10)]
        first = self.evaluate(self.source(packages))
        second = self.evaluate(self.source(list(reversed(packages))))
        self.assertEqual(first["selected_candidate"], second["selected_candidate"])
        self.assertEqual(first["candidates"], second["candidates"])

    def test_invalid_cycle_unknown_nonfinite_and_boolean_are_rejected(self) -> None:
        cases = []
        cases.append(self.source([self.package("a", depends_on=["b"]), self.package("b", depends_on=["a"])]))
        cases.append(self.source([self.package("a", depends_on=["missing"])]))
        bad = self.package("bad")
        bad["execution_credits"] = float("inf")
        cases.append(self.source([bad]))
        bad = self.package("bad")
        bad["execution_credits"] = True
        cases.append(self.source([bad]))
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    self.evaluate(case)

    def test_unknown_fields_and_package_limit_fail_closed(self) -> None:
        source = self.source()
        source["unexpected"] = 1
        with self.assertRaises(ValueError):
            self.evaluate(source)
        packages = [self.package(f"p-{index}") for index in range(17)]
        with self.assertRaises(ValueError):
            self.evaluate(self.source(packages))

    def test_writer_limit_is_bounded_by_package_count_and_safe_cap(self) -> None:
        source = self.source([self.package("only")], maximum_active_luna_writers=2)
        with self.assertRaises(ValueError):
            self.evaluate(source)
        source = self.source([self.package("only")], maximum_active_luna_writers=10**9)
        with self.assertRaises(ValueError):
            self.evaluate(source)
        packages = [self.package(f"p-{index}") for index in range(11)]
        with self.assertRaises(ValueError):
            self.evaluate(self.source(packages, maximum_active_luna_writers=10))

    def test_no_eligible_candidate_returns_sol_only(self) -> None:
        result = self.evaluate(self.source([self.package("bad", baseline=10, execution=100)], minimum_credit_savings_fraction=0.9))
        self.assertEqual(result["route"], "SOL_ONLY")
        self.assertFalse(result["automatic_execution_allowed"])

    def test_cli_template_and_single_line_errors(self) -> None:
        template = subprocess.run([sys.executable, str(SCRIPT), "template"], capture_output=True, text=True, check=False)
        self.assertEqual(template.returncode, 0, template.stderr)
        payload = json.loads(template.stdout)
        evaluated = subprocess.run(
            [sys.executable, str(SCRIPT), "evaluate", "--input", "-"],
            input=json.dumps(payload), capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(evaluated.returncode, 0)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            evaluated = subprocess.run([sys.executable, str(SCRIPT), "evaluate", "--input", str(path)], capture_output=True, text=True, check=False)
            self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
            self.assertEqual(json.loads(evaluated.stdout)["automatic_execution_allowed"], False)
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            bad = subprocess.run([sys.executable, str(SCRIPT), "evaluate", "--input", str(path)], capture_output=True, text=True, check=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertNotIn("Traceback", bad.stderr)
            self.assertEqual(len(bad.stderr.splitlines()), 1)
            path.write_text('{"schema_version":1,"packages":[],"minimum_first_pass_probability":NaN}', encoding="utf-8")
            bad = subprocess.run([sys.executable, str(SCRIPT), "evaluate", "--input", str(path)], capture_output=True, text=True, check=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertNotIn("Traceback", bad.stderr)
            self.assertEqual(len(bad.stderr.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
