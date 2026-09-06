from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks.p107_fixture.vaultmove import Plan, VaultError, apply_plan, build_plan, plan_from_raw, plan_to_json

class VaultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "vault"
        self.root.mkdir()

    def note(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def error(self, code, path, moves):
        with self.assertRaises(VaultError) as caught:
            build_plan(self.root, moves)
        self.assertEqual((caught.exception.code, caught.exception.path), (code, path))

class ValidationTests(VaultCase):
    def test_invalid_root(self):
        missing = Path(self.tmp.name) / "missing"
        with self.assertRaises(VaultError) as caught: build_plan(missing, [])
        self.assertEqual((caught.exception.code, caught.exception.path), ("INVALID_PATH", ("root",)))

    def test_empty_plan_is_frozen_and_canonical(self):
        plan = build_plan(self.root, [])
        self.assertEqual(plan, Plan(1, ()))
        self.assertEqual(plan_to_json(plan), '{"entries":[],"schema_version":1}\n')
        with self.assertRaises(Exception):
            plan.entries += ()

    def test_move_input_is_detached(self):
        self.note("a.md", "A")
        raw = [{"source": "a.md", "target": "b.md"}]
        before = copy.deepcopy(raw)
        build_plan(self.root, raw)
        self.assertEqual(raw, before)

    def test_field_and_path_error_precedence(self):
        cases = [
            ([{"source": "a.md", "target": "b.md", "x": 1}], "UNKNOWN_FIELD", ("moves", 0, "x")),
            ([{"source": "../a.md", "target": "b.md"}], "INVALID_PATH", ("moves", 0, "source")),
            ([{"source": "a.md", "target": "a.md"}], "SAME_PATH", ("moves", 0, "target")),
        ]
        for raw, code, path in cases:
            with self.subTest(code=code): self.error(code, path, raw)

    def test_duplicate_and_case_collision_locations(self):
        self.note("a.md", "A"); self.note("b.md", "B")
        self.error("DUPLICATE_SOURCE", ("moves", 1, "source"), [{"source":"a.md","target":"x.md"},{"source":"a.md","target":"y.md"}])
        self.error("CASE_COLLISION", ("moves", 1, "target"), [{"source":"a.md","target":"X.md"},{"source":"b.md","target":"x.md"}])

    def test_missing_and_occupied_targets(self):
        self.note("a.md", "A"); self.note("occupied.md", "O")
        self.error("SOURCE_MISSING", ("moves",0,"source"), [{"source":"none.md","target":"x.md"}])
        self.error("TARGET_EXISTS", ("moves",0,"target"), [{"source":"a.md","target":"occupied.md"}])

    def test_rejects_path_shape_matrix(self):
        self.note("a.md", "A")
        for value in ("/a.md", "a\\b.md", "a//b.md", "./a.md", "a.txt", ""):
            with self.subTest(value=value):
                self.error("INVALID_PATH", ("moves",0,"target"), [{"source":"a.md","target":value}])

    def test_duplicate_target_location(self):
        self.note("a.md", "A"); self.note("b.md", "B")
        self.error("DUPLICATE_TARGET", ("moves",1,"target"), [{"source":"a.md","target":"x.md"},{"source":"b.md","target":"x.md"}])

    def test_case_colliding_vault_is_rejected(self):
        self.note("A.md", "A"); self.note("a.md", "a")
        with self.assertRaises(VaultError) as caught: build_plan(self.root, [])
        self.assertEqual(caught.exception.code, "CASE_COLLISION")

    def test_symlink_is_rejected_when_supported(self):
        target = self.note("target.md", "T"); link = self.root / "link.md"
        try: link.symlink_to(target)
        except OSError: self.skipTest("symlink creation unavailable")
        with self.assertRaises(VaultError) as caught: build_plan(self.root, [])
        self.assertEqual((caught.exception.code, caught.exception.path), ("SYMLINK", ("vault", "link.md")))

    def test_root_and_directory_symlinks_are_rejected_when_supported(self):
        real = Path(self.tmp.name) / "real"; real.mkdir(); root_link = Path(self.tmp.name) / "root-link"
        try: root_link.symlink_to(real, target_is_directory=True)
        except OSError: self.skipTest("directory symlink creation unavailable")
        with self.assertRaises(VaultError) as caught: build_plan(root_link, [])
        self.assertEqual((caught.exception.code, caught.exception.path), ("SYMLINK", ("root",)))
        child = self.root / "linked-dir"; child.symlink_to(real, target_is_directory=True)
        with self.assertRaises(VaultError) as caught: build_plan(self.root, [])
        self.assertEqual((caught.exception.code, caught.exception.path), ("SYMLINK", ("vault", "linked-dir")))

class LinkAndPlanTests(VaultCase):
    def test_rewrites_supported_inbound_forms(self):
        self.note("old.md", "target")
        self.note("index.md", "[[old]] [[old.md#h|L]] ![[old]] [M](old.md#h) ![I](old.md)")
        plan = build_plan(self.root, [{"source":"old.md","target":"dir/new.md"}])
        entry = next(x for x in plan.entries if x.source == "index.md")
        self.assertEqual(entry.rewritten_text, "[[dir/new]] [[dir/new.md#h|L]] ![[dir/new]] [M](dir/new.md#h) ![I](dir/new.md)")

    def test_moved_source_recalculates_relative_and_self_links(self):
        self.note("a/x.md", "[B](../b.md) [Self](x.md) [[a/x]]"); self.note("b.md", "B")
        plan = build_plan(self.root, [{"source":"a/x.md","target":"deep/x.md"},{"source":"b.md","target":"deep/b.md"}])
        entry = next(x for x in plan.entries if x.source == "a/x.md")
        self.assertEqual(entry.rewritten_text, "[B](b.md) [Self](x.md) [[deep/x]]")

    def test_code_urls_unresolved_and_unsupported_unchanged(self):
        text = "`[[old]]`\n```md\n[[old]]\n```\n[U](https://x/old.md) [R][old] [[missing]]"
        self.note("old.md", "O"); self.note("index.md", text)
        plan = build_plan(self.root, [{"source":"old.md","target":"new.md"}])
        self.assertIsNone(next((x for x in plan.entries if x.source == "index.md"), None))

    def test_crlf_and_final_newline_are_preserved(self):
        self.note("old.md", "O"); (self.root/"index.md").write_bytes(b"[[old]]\r\nnext\r\n")
        plan = build_plan(self.root, [{"source":"old.md","target":"new.md"}])
        entry = next(x for x in plan.entries if x.source == "index.md")
        self.assertEqual(entry.rewritten_text, "[[new]]\r\nnext\r\n")

    def test_tilde_fence_long_fence_inline_runs_and_escape(self):
        text = "~~~\n[[old]]\n~~~\n``[[old]]`` \\[[old]] [[old]]"
        self.note("old.md", "O"); self.note("index.md", text)
        plan = build_plan(self.root, [{"source":"old.md","target":"new.md"}])
        entry = next(x for x in plan.entries if x.source == "index.md")
        self.assertEqual(entry.rewritten_text, "~~~\n[[old]]\n~~~\n``[[old]]`` \\[[old]] [[new]]")

    def test_relative_link_normalizes_from_final_parent(self):
        self.note("docs/a.md", "[B](../b.md)"); self.note("b.md", "B")
        plan = build_plan(self.root, [{"source":"docs/a.md","target":"deep/nested/a.md"}])
        entry = next(x for x in plan.entries if x.source == "docs/a.md")
        self.assertEqual(entry.rewritten_text, "[B](../../b.md)")

    def test_relative_link_that_escapes_vault_is_unchanged(self):
        self.note("dir/a.md", "[Outside](../../outside.md)")
        plan = build_plan(self.root, [{"source":"dir/a.md","target":"deep/nested/a.md"}])
        entry = next(x for x in plan.entries if x.source == "dir/a.md")
        self.assertEqual(entry.rewritten_text, "[Outside](../../outside.md)")

    def test_plan_roundtrip_and_determinism(self):
        self.note("é.md", "[[é]]")
        raw = [{"source":"é.md","target":"目标.md"}]
        first = build_plan(self.root, raw); encoded = plan_to_json(first)
        self.assertEqual(plan_from_raw(json.loads(encoded)), first)
        self.assertEqual(plan_to_json(build_plan(self.root, raw)), encoded)
        self.assertIn("目标", encoded)

    def test_plan_parser_rejects_unknown_fields(self):
        with self.assertRaises(VaultError) as caught: plan_from_raw({"schema_version":1,"entries":[],"extra":1})
        self.assertEqual((caught.exception.code, caught.exception.path), ("UNKNOWN_FIELD", ("plan","extra")))

class ApplyTests(VaultCase):
    def test_empty_apply(self):
        self.assertEqual(apply_plan(self.root, build_plan(self.root, [])), ())

    def test_apply_simple_move_and_rewrite(self):
        self.note("old.md", "O"); self.note("index.md", "[[old]]")
        plan = build_plan(self.root, [{"source":"old.md","target":"dir/new.md"}])
        self.assertEqual(apply_plan(self.root, plan), ("dir/new.md", "index.md"))
        self.assertFalse((self.root/"old.md").exists())
        self.assertEqual((self.root/"index.md").read_text(encoding="utf-8"), "[[dir/new]]")

    def test_simultaneous_swap(self):
        self.note("a.md", "A [[b]]"); self.note("b.md", "B [[a]]")
        plan = build_plan(self.root, [{"source":"a.md","target":"b.md"},{"source":"b.md","target":"a.md"}])
        apply_plan(self.root, plan)
        self.assertEqual((self.root/"a.md").read_text(encoding="utf-8"), "B [[b]]")
        self.assertEqual((self.root/"b.md").read_text(encoding="utf-8"), "A [[a]]")

    def test_stale_source_writes_nothing(self):
        self.note("a.md", "A"); plan = build_plan(self.root,[{"source":"a.md","target":"b.md"}]); self.note("a.md", "changed")
        before = {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaises(VaultError) as caught: apply_plan(self.root, plan)
        self.assertEqual((caught.exception.code,caught.exception.path),("STALE_SOURCE",("vault","a.md")))
        after = {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after,before)

    def test_target_created_after_plan_writes_nothing(self):
        self.note("a.md", "A"); plan=build_plan(self.root,[{"source":"a.md","target":"b.md"}]); self.note("b.md","B")
        with self.assertRaises(VaultError) as caught: apply_plan(self.root,plan)
        self.assertEqual((caught.exception.code,caught.exception.path),("TARGET_EXISTS",("vault","b.md")))
        self.assertEqual((self.root/"a.md").read_text(encoding="utf-8"),"A")

    def test_identical_snapshot_can_apply_under_another_root(self):
        self.note("a.md", "A"); plan=build_plan(self.root,[{"source":"a.md","target":"b.md"}])
        other=Path(self.tmp.name)/"other"; other.mkdir(); (other/"a.md").write_text("A",encoding="utf-8")
        self.assertEqual(apply_plan(other,plan),("b.md",))

class CliTests(VaultCase):
    def run_cli(self,*args,stdin=None):
        return subprocess.run([sys.executable,"-m","benchmarks.p107_fixture.vaultmove.cli",*args],input=stdin,capture_output=True,text=True)

    def test_plan_file_and_apply_file(self):
        self.note("a.md", "A"); moves=Path(self.tmp.name)/"moves.json"; moves.write_text('[{"source":"a.md","target":"b.md"}]',encoding="utf-8")
        made=self.run_cli("plan","--root",str(self.root),"--moves",str(moves)); self.assertEqual(made.returncode,0,made.stderr)
        plan=Path(self.tmp.name)/"plan.json"; plan.write_text(made.stdout,encoding="utf-8")
        applied=self.run_cli("apply","--root",str(self.root),"--plan",str(plan))
        self.assertEqual((applied.returncode,json.loads(applied.stdout)),(0,{"applied":["b.md"]}))

    def test_malformed_stdin_is_structured(self):
        result=self.run_cli("plan","--root",str(self.root),"--moves","-",stdin="{")
        self.assertEqual(result.returncode,2); self.assertEqual(json.loads(result.stderr),{"error":{"code":"INVALID_JSON","path":["moves"]}}); self.assertEqual(result.stdout,"")

    def test_invalid_utf8_file_is_structured(self):
        bad=Path(self.tmp.name)/"bad.json"; bad.write_bytes(b"\xff")
        result=self.run_cli("plan","--root",str(self.root),"--moves",str(bad))
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stderr),{"error":{"code":"INVALID_UTF8","path":["moves"]}})

if __name__ == "__main__": unittest.main()
