from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "sol-luna" / "scripts" / "candidate_snapshot.py"
SPEC = importlib.util.spec_from_file_location("candidate_snapshot", SCRIPT)
assert SPEC and SPEC.loader
SNAPSHOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SNAPSHOT)


class CandidateSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Candidate Test")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def commit(self, message: str = "commit") -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def write(self, relative: str, data: bytes) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [os.environ.get("PYTHON", "python"), "-B", str(SCRIPT), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_modified_added_deleted_and_unicode_space_paths(self) -> None:
        self.write("modified.txt", b"old")
        self.write("deleted.txt", b"gone")
        self.commit()
        self.write("modified.txt", b"new\x00bytes")
        (self.repo / "deleted.txt").unlink()
        self.write("unicode 测试.txt", b"added")
        result = SNAPSHOT.build_snapshot(self.repo)
        self.assertEqual(set(result), {"schema_version", "base_commit", "entries", "candidate_digest"})
        self.assertTrue(all(set(entry) == {"path", "state", "kind", "mode", "content_digest"} for entry in result["entries"]))
        self.assertEqual([entry["path"] for entry in result["entries"]], ["deleted.txt", "modified.txt", "unicode 测试.txt"])
        by_path = {entry["path"]: entry for entry in result["entries"]}
        self.assertEqual(by_path["deleted.txt"]["state"], "deleted")
        self.assertIsNone(by_path["deleted.txt"]["content_digest"])
        self.assertEqual(by_path["modified.txt"]["state"], "modified")
        self.assertEqual(by_path["modified.txt"]["content_digest"], "sha256:" + hashlib.sha256(b"new\x00bytes").hexdigest())
        self.assertEqual(by_path["unicode 测试.txt"]["state"], "added")

    def test_build_snapshot_rejects_different_consecutive_captures(self) -> None:
        first = {"schema_version": 1, "base_commit": "a" * 40, "entries": []}
        second = {"schema_version": 1, "base_commit": "a" * 40, "entries": [{"path": "new.txt"}]}
        with patch.object(SNAPSHOT, "_capture_snapshot", side_effect=[first, second]):
            with self.assertRaisesRegex(SNAPSHOT.SnapshotError, "candidate changed during snapshot"):
                SNAPSHOT.build_snapshot(self.repo, "a" * 40)

    def test_windows_git_path_encoding_preserves_snow_character(self) -> None:
        committed = "space unicode \u96ea.txt"
        untracked = "untracked \u96ea.txt"
        self.write(committed, b"old")
        base = self.commit()
        self.write(committed, b"new")
        self.write(untracked, b"new")
        result = SNAPSHOT.build_snapshot(self.repo, base)
        self.assertEqual([entry["path"] for entry in result["entries"]], [committed, untracked])

    def test_windows_git_path_encoding_preserves_snow_in_independent_cli(self) -> None:
        committed = "space unicode \u96ea.txt"
        untracked = "untracked \u96ea.txt"
        self.write(committed, b"old")
        base = self.commit()
        self.write(committed, b"new")
        self.write(untracked, b"new")
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "snapshot", "--repo", str(self.repo), "--base", base],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual([entry["path"] for entry in payload["entries"]], [committed, untracked])

    def test_type_change_and_rename_are_delete_plus_add(self) -> None:
        self.write("kind.txt", b"content")
        self.write("rename.txt", b"rename")
        self.commit()
        (self.repo / "rename.txt").rename(self.repo / "renamed.txt")
        self.git("add", "--all")
        self.git("commit", "-qm", "rename")
        (self.repo / "renamed.txt").rename(self.repo / "renamed-again.txt")
        (self.repo / "kind.txt").unlink()
        try:
            os.symlink("renamed-again.txt", self.repo / "kind.txt")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        result = SNAPSHOT.build_snapshot(self.repo)
        by_path = {entry["path"]: entry for entry in result["entries"]}
        self.assertEqual(by_path["renamed.txt"]["state"], "deleted")
        self.assertEqual(by_path["renamed.txt"]["kind"], "file")
        self.assertEqual(by_path["renamed-again.txt"]["state"], "added")
        self.assertEqual(by_path["renamed-again.txt"]["kind"], "file")
        self.assertEqual(by_path["kind.txt"]["state"], "type_changed")
        self.assertEqual(by_path["kind.txt"]["kind"], "symlink")
        self.assertEqual(by_path["kind.txt"]["mode"], "120000")

    def test_ignored_files_and_staging_neutrality(self) -> None:
        self.write("tracked.txt", b"old")
        self.write("ignored.tmp", b"ignored")
        self.write(".gitignore", b"*.tmp\n")
        self.commit()
        self.write("tracked.txt", b"new")
        self.write("ignored.tmp", b"ignored changed")
        before = SNAPSHOT.build_snapshot(self.repo)
        self.git("add", "tracked.txt")
        after = SNAPSHOT.build_snapshot(self.repo)
        self.assertEqual(before, after)
        self.assertEqual([item["path"] for item in after["entries"]], ["tracked.txt"])

    def test_digest_is_canonical_and_verify_has_clean_channels(self) -> None:
        self.write("b.txt", b"b")
        self.write("a.txt", b"a")
        base = self.commit()
        self.write("a.txt", b"a2")
        result = SNAPSHOT.build_snapshot(self.repo)
        expected = result["candidate_digest"]
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(result["candidate_digest"], SNAPSHOT.candidate_digest(result))
        self.assertEqual(SNAPSHOT.canonical_bytes({"b": 1, "a": 2}), b'{"a":2,"b":1}')
        good = self.run_cli("verify", "--repo", str(self.repo), "--base", base, "--expected", expected)
        self.assertEqual(good.returncode, 0)
        self.assertEqual(good.stderr, b"")
        self.assertEqual(set(json.loads(good.stdout.decode())), {"schema_version", "status", "base_commit", "candidate_digest"})
        self.assertEqual(json.loads(good.stdout.decode())["candidate_digest"], expected)
        bad = self.run_cli("verify", "--repo", str(self.repo), "--expected", "sha256:" + "0" * 64)
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(bad.stdout, b"")
        self.assertNotIn(str(self.repo).encode(), bad.stderr)
        self.assertTrue(encoded)

    def test_base_drift_and_exact_byte_changes_change_digest(self) -> None:
        self.write("value.txt", b"one")
        first = self.commit("first")
        self.write("value.txt", b"two")
        second = self.commit("second")
        self.write("value.txt", b"three")
        from_first = SNAPSHOT.build_snapshot(self.repo, first)
        from_second = SNAPSHOT.build_snapshot(self.repo, second)
        self.assertNotEqual(from_first["candidate_digest"], from_second["candidate_digest"])
        self.write("value.txt", b"three\n")
        self.assertNotEqual(from_first["candidate_digest"], SNAPSHOT.build_snapshot(self.repo, first)["candidate_digest"])

    def test_symlink_is_hashed_without_following_target_when_supported(self) -> None:
        target = self.repo / "target.txt"
        self.write("target.txt", b"target")
        self.commit("symlink base")
        try:
            os.symlink("target.txt", self.repo / "link.txt")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        result = SNAPSHOT.build_snapshot(self.repo)
        link = next(entry for entry in result["entries"] if entry["path"] == "link.txt")
        self.assertEqual(link["kind"], "symlink")
        self.assertEqual(link["content_digest"], "sha256:" + hashlib.sha256(os.fsencode("target.txt")).hexdigest())
        target.write_bytes(b"changed")
        self.assertEqual(next(entry for entry in SNAPSHOT.build_snapshot(self.repo)["entries"] if entry["path"] == "link.txt")["content_digest"], link["content_digest"])

    def test_malformed_inputs_and_safe_path_helpers(self) -> None:
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.parse_expected_digest("sha256:" + "A" * 64)
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.normalize_repo_path("../escape")
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.normalize_repo_path("CON.txt")
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.load_json_strict('{"x": 1, "x": 2}')
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.load_json_strict('{"x": NaN}')
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.validate_snapshot({"schema_version": True, "base_commit": "a" * 40, "entries": []})
        with self.assertRaises(SNAPSHOT.SnapshotError):
            SNAPSHOT.validate_snapshot({"schema_version": 1, "base_commit": "a" * 40, "entries": [], "extra": 1})

    def test_unborn_missing_and_invalid_base_are_errors_without_output(self) -> None:
        unborn = self.run_cli("snapshot", "--repo", str(self.repo))
        self.assertNotEqual(unborn.returncode, 0)
        self.assertEqual(unborn.stdout, b"")
        self.assertTrue(unborn.stderr.startswith(b"error: "))
        missing = self.run_cli("snapshot", "--repo", str(self.repo / "missing"))
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, b"")
        self.write("x.txt", b"x")
        base = self.commit()
        invalid = self.run_cli("snapshot", "--repo", str(self.repo), "--base", "not-a-commit")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(invalid.stdout, b"")
        self.assertTrue(invalid.stderr.startswith(b"error: "))
        self.assertNotEqual(base, "")

    def test_snapshot_does_not_change_index(self) -> None:
        self.write("x.txt", b"x")
        self.commit()
        self.write("x.txt", b"changed")
        before = self.git("write-tree").stdout
        SNAPSHOT.build_snapshot(self.repo)
        after = self.git("write-tree").stdout
        self.assertEqual(before, after)

    def test_changed_gitlink_is_rejected(self) -> None:
        self.write("seed.txt", b"seed")
        first = self.commit("first")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{first},submodule")
        self.git("commit", "-qm", "gitlink")
        self.write("another.txt", b"another")
        self.git("add", "another.txt")
        self.git("commit", "-qm", "second")
        second = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{second},submodule")
        with self.assertRaisesRegex(SNAPSHOT.SnapshotError, "submodule"):
            SNAPSHOT.build_snapshot(self.repo)


if __name__ == "__main__":
    unittest.main()
