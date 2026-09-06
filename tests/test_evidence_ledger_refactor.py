from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "sol-luna" / "scripts"
FACADE = SCRIPTS / "evidence_ledger.py"
MODULES = {
    "evidence_schema.py": {
        "LedgerError", "redacted_ref", "require_string", "require_label", "require_digest",
        "non_negative_number", "safe_summary", "validate_timestamp", "validate_phase_map",
        "record_id", "record_binding_digest", "validate_record",
    },
    "evidence_store.py": {"load_records", "ledger_lock", "atomic_write_records", "append_record"},
    "evidence_receipts.py": {
        "_canonical_claim_digest", "_validate_verified_claim", "_validate_verified_receipt_index",
        "_normalize_verified_credit_receipts", "load_verified_credit_receipts",
        "_credit_record_is_independently_verified",
    },
    "evidence_analysis.py": {
        "comparable_metric", "fully_assessed", "median", "_cohort_identity_value",
        "_cohort_pair_output", "cohort_identity", "evidence_status", "task_family_feedback",
    },
}
CONSTANTS = {
    "evidence_schema.py": {
        "SCHEMA_VERSION", "MIN_MATCHED_PAIRS", "ROUTES", "OUTCOMES", "INDEPENDENT_RESULTS",
        "FAILURE_CLASSES", "CREDIT_KINDS", "CREDIT_VERIFICATIONS",
        "VERIFIED_RECEIPTS_SCHEMA_VERSION", "PHASES", "EFFORTS", "REVIEW_DEPTHS",
        "ALLOWED_FIELDS", "REQUIRED_FIELDS", "PRIVATE_PATH", "LABEL", "DIGEST",
    },
    "evidence_receipts.py": {"VERIFIED_CLAIM_FIELDS", "VERIFIED_INDEX_FIELDS"},
}


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class EvidenceLedgerRefactorTests(unittest.TestCase):
    def test_required_modules_exist_and_own_the_frozen_functions(self) -> None:
        for filename, expected in MODULES.items():
            path = SCRIPTS / filename
            self.assertTrue(path.is_file(), filename)
            defined = {node.name for node in parse(path).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            self.assertTrue(expected <= defined, f"{filename}: missing {sorted(expected - defined)}")

    def test_schema_and_receipt_constants_have_explicit_owners(self) -> None:
        for filename, expected in CONSTANTS.items():
            assigned: set[str] = set()
            for node in parse(SCRIPTS / filename).body:
                if isinstance(node, ast.Assign):
                    assigned.update(target.id for target in node.targets if isinstance(target, ast.Name))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    assigned.add(node.target.id)
            self.assertTrue(expected <= assigned, f"{filename}: missing {sorted(expected - assigned)}")

    def test_facade_is_thin_and_keeps_only_cli_construction(self) -> None:
        tree = parse(FACADE)
        defined = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual(defined, {"template", "parser", "main"})
        self.assertLessEqual(len(FACADE.read_text(encoding="utf-8").splitlines()), 260)

    def test_live_functions_are_not_duplicated_across_the_split(self) -> None:
        owners: dict[str, list[str]] = {}
        for filename in (*MODULES, "evidence_ledger.py"):
            for node in parse(SCRIPTS / filename).body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    owners.setdefault(node.name, []).append(filename)
        duplicates = {name: files for name, files in owners.items() if len(files) > 1}
        self.assertEqual(duplicates, {})

    def test_modules_do_not_import_the_facade(self) -> None:
        for filename in MODULES:
            for node in ast.walk(parse(SCRIPTS / filename)):
                if isinstance(node, ast.Import):
                    self.assertNotIn("evidence_ledger", {alias.name for alias in node.names})
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "evidence_ledger")

    def test_internal_dependency_graph_is_one_way(self) -> None:
        expected = {
            "evidence_schema.py": set(),
            "evidence_store.py": {"evidence_schema"},
            "evidence_receipts.py": {"evidence_schema"},
            "evidence_analysis.py": {"evidence_schema", "evidence_receipts"},
        }
        internal_names = {Path(filename).stem for filename in MODULES}
        for filename, required in expected.items():
            imported: set[str] = set()
            for node in ast.walk(parse(SCRIPTS / filename)):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names if alias.name in internal_names)
                elif isinstance(node, ast.ImportFrom) and node.module in internal_names:
                    imported.add(node.module)
            self.assertEqual(imported, required, filename)

    def test_import_by_file_preserves_the_public_surface(self) -> None:
        before = list(sys.path)
        spec = importlib.util.spec_from_file_location("evidence_ledger_refactor_acceptance", FACADE)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(sys.path, before)
        expected = set().union(*MODULES.values(), *CONSTANTS.values()) | {"template", "parser", "main"}
        self.assertTrue(expected <= set(dir(module)))

    def test_reexports_are_the_live_split_objects(self) -> None:
        inserted = False
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
            inserted = True
        try:
            spec = importlib.util.spec_from_file_location("evidence_ledger_identity_acceptance", FACADE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.validate_record.__module__, "evidence_schema")
            self.assertEqual(module.append_record.__module__, "evidence_store")
            self.assertEqual(module.load_verified_credit_receipts.__module__, "evidence_receipts")
            self.assertEqual(module.evidence_status.__module__, "evidence_analysis")
        finally:
            if inserted:
                sys.path.remove(str(SCRIPTS))


if __name__ == "__main__":
    unittest.main()
