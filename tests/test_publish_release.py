from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_release.py"
SPEC = importlib.util.spec_from_file_location("publish_release", SCRIPT)
assert SPEC and SPEC.loader
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class PublishReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gh = Path("gh")
        self.repository = "EdmundD28/Sol-Luna-Routing-System"
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.notes = Path(self.temp.name) / "notes.md"
        self.notes.write_text("release notes\n", encoding="utf-8")

    def test_preview_preserves_latest_and_performs_no_write(self) -> None:
        with mock.patch.object(RELEASE, "latest_tag", return_value="v0.1.1"), mock.patch.object(
            RELEASE, "run_gh"
        ) as run:
            result = RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Contract repair",
                notes_file=self.notes,
                confirm=False,
            )
        self.assertEqual(result["status"], "preview")
        self.assertFalse(result["writes_performed"])
        self.assertEqual(result["latest_before"], "v0.1.1")
        self.assertIn("--latest=false", result["command"])
        run.assert_not_called()

    def test_confirm_checks_latest_before_and_after(self) -> None:
        with mock.patch.object(RELEASE, "latest_tag", side_effect=["v0.1.1", "v0.1.1"]) as latest, mock.patch.object(
            RELEASE, "run_gh", return_value="https://example.invalid/release"
        ) as run:
            result = RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Contract repair",
                notes_file=self.notes,
                confirm=True,
            )
        self.assertEqual(result["status"], "published")
        self.assertTrue(result["writes_performed"])
        self.assertEqual(latest.call_count, 2)
        self.assertIn("--latest=false", run.call_args.args[1])

    def test_latest_drift_refuses_before_release(self) -> None:
        with mock.patch.object(RELEASE, "latest_tag", return_value="v0.4.0"), mock.patch.object(
            RELEASE, "run_gh"
        ) as run:
            with self.assertRaisesRegex(RELEASE.ReleaseError, "latest release drifted"):
                RELEASE.publish(
                    gh=self.gh,
                    repository=self.repository,
                    tag="v0.4.1",
                    title="Contract repair",
                    notes_file=self.notes,
                    confirm=True,
                )
        run.assert_not_called()

    def test_pinned_release_cannot_be_republished(self) -> None:
        with self.assertRaisesRegex(RELEASE.ReleaseError, "pinned"):
            RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.1.1",
                title="Do not replace",
                notes_file=self.notes,
                confirm=True,
            )

    def test_run_gh_redacts_nothing_but_raises_without_traceback_contract(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["gh"], returncode=1, stdout="", stderr="network unavailable"
        )
        with mock.patch.object(RELEASE.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RELEASE.ReleaseError, "network unavailable"):
                RELEASE.run_gh(self.gh, ["api", "endpoint"])


if __name__ == "__main__":
    unittest.main()
