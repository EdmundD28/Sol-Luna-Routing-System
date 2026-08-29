from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "compact_protocol.py"
SPEC = importlib.util.spec_from_file_location("compact_protocol", SCRIPT)
assert SPEC and SPEC.loader
PROTO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROTO)


D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def manifest() -> dict:
    return {
        "schema_version": 1,
        "package_id": "candidate-snapshot",
        "executor_id": "luna-01",
        "ownership_id": "own-01",
        "task_digest": D1,
        "allocation_digest": D2,
        "luna_effort": "high",
        "objective": "Unicode objective 雪; never put this prose in RUN",
        "write_scope": ["src/z.py", "src/a.py"],
        "acceptance_ids": ["accept-z", "accept-a"],
        "forbidden_actions": ["network", "commit"],
        "stop_conditions": ["scope", "failure"],
        "context_refs": [
            {"ref_id": "spec", "path": "docs/spec.md", "content_digest": D1, "kind": "acceptance"},
            {"ref_id": "api", "path": "src/api.py", "content_digest": D2, "kind": "interface"},
        ],
    }


class CompactProtocolTests(unittest.TestCase):
    def test_freeze_canonicalizes_and_binds_digest(self) -> None:
        frozen = PROTO.freeze_manifest(manifest())
        self.assertEqual(frozen["write_scope"], ["src/a.py", "src/z.py"])
        self.assertEqual(frozen["acceptance_ids"], ["accept-a", "accept-z"])
        self.assertRegex(frozen["manifest_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(PROTO.package_ref(frozen), "candidate-snapshot@" + frozen["manifest_digest"][7:19])
        altered = dict(frozen)
        altered["manifest_digest"] = D1
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.freeze_manifest(altered)

    def test_run_round_trip_binds_to_manifest_and_hides_prose(self) -> None:
        frozen = PROTO.freeze_manifest(manifest())
        line = PROTO.run_line(frozen)
        self.assertEqual(line.split("|")[0], "RUN")
        self.assertNotIn("Unicode", line)
        parsed = PROTO.parse_line(line, frozen)
        self.assertEqual(parsed["effort"], "high")
        self.assertEqual(parsed["acceptance_ids"], ["accept-a", "accept-z"])
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.parse_line(line.replace("OWN=own-01", "OWN=other"), frozen)

    def test_manifest_reference_exact_binding_and_shape(self) -> None:
        frozen = PROTO.freeze_manifest(manifest())
        line = PROTO.manifest_line(frozen)
        self.assertEqual(line, "MAN|" + PROTO.package_ref(frozen))
        self.assertEqual(PROTO.parse_line(line, frozen), {"record_type": "MAN", "package_ref": PROTO.package_ref(frozen)})
        self.assertEqual(PROTO.parse_line(line), {"record_type": "MAN", "package_ref": PROTO.package_ref(frozen)})
        with self.assertRaises(PROTO.ProtocolError): PROTO.parse_line("MAN|" + PROTO.package_ref(manifest()) + "|extra")
        altered = dict(frozen); altered["objective"] = "tampered"
        with self.assertRaises(PROTO.ProtocolError): PROTO.parse_line(line, altered)
        wrong = line.replace("candidate-snapshot", "other-package")
        with self.assertRaises(PROTO.ProtocolError): PROTO.parse_line(wrong, frozen)

    def test_ok_and_block_round_trip(self) -> None:
        frozen = PROTO.freeze_manifest(manifest())
        ok = PROTO.ok_line(frozen, D1, D2, 4, 4, 2, 0)
        parsed_ok = PROTO.parse_line(ok, frozen)
        self.assertEqual(parsed_ok["status"] if "status" in parsed_ok else parsed_ok["record_type"], "OK")
        self.assertEqual(parsed_ok["candidate_digest"], D1)
        block = PROTO.block_line(frozen, "NEEDS_INPUT", "docs/spec.md:12", ["ask-user"])
        parsed_block = PROTO.parse_line(block, frozen)
        self.assertEqual(parsed_block["reference"], "docs/spec.md:12")
        self.assertEqual(parsed_block["options"], ["ask-user"])

    def test_strict_rejection(self) -> None:
        bad = manifest()
        bad["schema_version"] = True
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.freeze_manifest(bad)
        for path in ("../escape", "C:/absolute", "src\\bad.py", "CON.txt", "src/a.py\n"):
            bad = manifest()
            bad["write_scope"] = [path]
            with self.assertRaises(PROTO.ProtocolError):
                PROTO.freeze_manifest(bad)
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.load_json_strict('{"a": 1, "a": 2}')
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.load_json_strict('{"a": NaN}')
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.parse_line("RUN|x@123456789abc|E=H|OWN=o|ACC=a,a|STOP=s")
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.parse_line("OK|x@123456789abc|C=" + "0" * 64 + "|PD=" + "1" * 64 + "|TEST=1/2|PATH=0|REPAIR=0|EX=0")
        with self.assertRaises(PROTO.ProtocolError):
            PROTO.parse_line("BLOCK|x@123456789abc|K=WAIT|REF=docs/x.md|OPT=")

    def test_cli_is_ascii_deterministic_and_errors_are_clean(self) -> None:
        payload = json.dumps(manifest(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        freeze = subprocess.run([sys.executable, "-B", str(SCRIPT), "freeze"], input=payload.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(freeze.returncode, 0, freeze.stderr)
        self.assertEqual(freeze.stdout.decode("ascii").count("\\u96ea"), 1)
        invalid = subprocess.run([sys.executable, "-B", str(SCRIPT), "parse", "--line", "RUN|bad|E=H"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(invalid.stdout, b"")
        self.assertEqual(invalid.stderr.count(b"\n"), 1)
        self.assertNotIn(str(ROOT).encode(), invalid.stderr)
        manifest_cli = subprocess.run([sys.executable, "-B", str(SCRIPT), "manifest", "--input", "-"], input=payload.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(manifest_cli.returncode, 0, manifest_cli.stderr)
        self.assertEqual(manifest_cli.stdout.decode("ascii").strip(), PROTO.manifest_line(manifest()))


if __name__ == "__main__":
    unittest.main()
