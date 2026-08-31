from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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

    def test_receipt_is_canonical_byte_sensitive_and_manifest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_bytes(b"a\x00\xff")
            (root / "src" / "z.py").write_bytes(b"z")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest(), ensure_ascii=False), encoding="utf-8")
            first = PROTO.build_receipt(str(manifest_path), str(root), ["src/z.py", "src/a.py"], 1, 1, 0)
            second = PROTO.build_receipt(str(manifest_path), str(root), ["src/a.py", "src/z.py"], 1, 1, 0)
            self.assertEqual(first, second)
            self.assertIn("|C=9e12e059538242922633c19f72643295d5f43280c67c8c67f5330bd15a1bbf9f|", first)
            self.assertIn("|PD=2ffdf4fa2dbb069a95f73683d1455545c74612bfa409befdddfd6ce5f400968c|", first)
            (root / "src" / "a.py").write_bytes(b"a\x00\xfe")
            changed = PROTO.build_receipt(str(manifest_path), str(root), ["src/a.py", "src/z.py"], 1, 1, 0)
            self.assertNotEqual(first.split("|C=")[1].split("|", 1)[0], changed.split("|C=")[1].split("|", 1)[0])
            self.assertEqual(first.split("|PD=")[1].split("|", 1)[0], changed.split("|PD=")[1].split("|", 1)[0])
            one_path = PROTO.build_receipt(str(manifest_path), str(root), ["src/a.py"], 1, 1, 0)
            self.assertNotEqual(changed.split("|C=")[1].split("|", 1)[0], one_path.split("|C=")[1].split("|", 1)[0])
            self.assertNotEqual(changed.split("|PD=")[1].split("|", 1)[0], one_path.split("|PD=")[1].split("|", 1)[0])
            altered = manifest()
            altered["objective"] = "changed"
            manifest_path.write_text(json.dumps(altered, ensure_ascii=False), encoding="utf-8")
            self.assertNotEqual(first.split("|")[1], PROTO.build_receipt(str(manifest_path), str(root), ["src/a.py"], 1, 1, 0).split("|")[1])

    def test_receipt_cli_matches_helper_and_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            target = root / "src" / "a.py"
            target.write_bytes(b"exact\x00bytes")
            manifest_path = root / "manifest.json"
            frozen = manifest()
            frozen["write_scope"] = ["src/a.py"]
            manifest_path.write_text(json.dumps(frozen), encoding="utf-8")
            before = target.read_bytes()
            command = [sys.executable, "-B", str(SCRIPT), "receipt", "--manifest", str(manifest_path),
                       "--root", str(root), "--path", "src/a.py", "--passed", "3", "--total", "3",
                       "--repair-count", "0"]
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.decode("ascii").strip(), PROTO.build_receipt(str(manifest_path), str(root), ["src/a.py"], 3, 3, 0))
            self.assertEqual(target.read_bytes(), before)
            rejected = subprocess.run(command[:-1] + ["-1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(rejected.stdout, b"")
            self.assertEqual(rejected.stderr.count(b"\n"), 1)

    def test_receipt_rejects_unsafe_targets_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_bytes(b"a")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")
            def receipt(paths, **kwargs):
                values = {"passed": 1, "total": 1, "repair_count": 0}
                values.update(kwargs)
                return PROTO.build_receipt(str(manifest_path), str(root), paths, **values)
            for bad in (["src/a.py", "src/A.py"], ["../escape"], ["C:/absolute"], ["src\\bad.py"], ["CON.txt"], ["src/a.py\n"]):
                with self.assertRaises(PROTO.ProtocolError):
                    receipt(bad)
            with self.assertRaises(PROTO.ProtocolError):
                receipt(["src/missing.py"])
            with self.assertRaises(PROTO.ProtocolError):
                receipt(["src"])
            (root / "outside.py").write_bytes(b"outside")
            with self.assertRaises(PROTO.ProtocolError):
                receipt(["outside.py"])
            with self.assertRaises(PROTO.ProtocolError):
                receipt(["src/a.py"], passed=0)
            with self.assertRaises(PROTO.ProtocolError):
                receipt(["src/a.py"], total=0)
            with self.assertRaises(PROTO.ProtocolError):
                PROTO.build_receipt(str(manifest_path), str(root / "missing"), ["src/a.py"], 1, 1, 0)
            root_file = root / "not-a-root"
            root_file.write_bytes(b"file")
            with self.assertRaises(PROTO.ProtocolError):
                PROTO.build_receipt(str(manifest_path), str(root_file), ["src/a.py"], 1, 1, 0)

    def test_receipt_rejects_symlink_target_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.py"
            target.write_bytes(b"target")
            link = root / "link.py"
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("symlinks are unavailable")
            frozen = manifest()
            frozen["write_scope"] = ["link.py"]
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(frozen), encoding="utf-8")
            with self.assertRaisesRegex(PROTO.ProtocolError, "symlink|reparse"):
                PROTO.build_receipt(str(manifest_path), str(root), ["link.py"], 1, 1, 0)

    @unittest.skipUnless(os.name == "nt", "Windows junctions are unavailable")
    def test_receipt_rejects_windows_junction_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            (target / "a.py").write_bytes(b"target")
            link = root / "link"
            created = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if created.returncode != 0:
                self.skipTest("Windows junction creation is unavailable")
            frozen = manifest()
            frozen["write_scope"] = ["link/a.py"]
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(frozen), encoding="utf-8")
            with self.assertRaisesRegex(PROTO.ProtocolError, "symlink|reparse"):
                PROTO.build_receipt(str(manifest_path), str(root), ["link/a.py"], 1, 1, 0)


if __name__ == "__main__":
    unittest.main()
