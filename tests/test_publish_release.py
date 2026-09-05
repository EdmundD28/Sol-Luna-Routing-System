from __future__ import annotations

import importlib.util
import json
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
        self.index = Path(self.temp.name) / "attempt-index.json"
        self.write_index()

    def write_index(
        self,
        *,
        tag: str = "v0.4.1",
        classification: str = "new_direction",
        changed_premise: object | None = None,
        prior_art_refs: list[str] | None = None,
        candidate_mechanisms: list[str] | None = None,
    ) -> None:
        self.index.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "updated_through": "v0.4.0",
                    "attempt_families": [
                        {
                            "id": "guardrails",
                            "versions": ["v0.2.0"],
                            "direction": "Installation and evidence guardrails.",
                            "mechanism_ids": ["managed-installation"],
                            "evidence": ["docs/example.md"],
                            "observed_result": "Keep outside the normal path.",
                            "repeat_rule": "Only when the host contract changes.",
                        }
                    ],
                    "release_entries": [
                        {
                            "id": "release-entry",
                            "tag": tag,
                            "history_reviewed_through": "v0.4.0",
                            "prior_art_refs": prior_art_refs or ["guardrails"],
                            "direction": "Reject releases whose mechanism history was not reviewed.",
                            "mechanism_ids": candidate_mechanisms or ["release-history-gate"],
                            "classification": classification,
                            "changed_premise": changed_premise,
                            "novelty_statement": (
                                None
                                if classification == "retry_changed_premise"
                                else "No earlier family made history review a pre-network release gate."
                            ),
                            "evidence_refs": ["tests/test_publish_release.py"],
                            "decision": "SHIP_EXPERIMENTAL",
                            "normal_path_cost": "none",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

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
                attempt_index=self.index,
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
                attempt_index=self.index,
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
                    attempt_index=self.index,
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
                attempt_index=self.index,
                confirm=True,
            )

    def test_release_without_history_entry_refuses_before_network(self) -> None:
        self.write_index(tag="v0.9.0")
        with mock.patch.object(RELEASE, "latest_tag") as latest:
            with self.assertRaisesRegex(RELEASE.ReleaseError, "exactly one release entry"):
                RELEASE.publish(
                    gh=self.gh,
                    repository=self.repository,
                    tag="v0.4.1",
                    title="Unreviewed release",
                    notes_file=self.notes,
                    attempt_index=self.index,
                    confirm=False,
                )
        latest.assert_not_called()

    def test_repeated_direction_requires_changed_premise(self) -> None:
        self.write_index(
            classification="retry_changed_premise",
            candidate_mechanisms=["managed-installation"],
        )
        with self.assertRaisesRegex(RELEASE.ReleaseError, "changed_premise"):
            RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Repeated attempt",
                notes_file=self.notes,
                attempt_index=self.index,
                confirm=False,
            )

    def test_repeated_direction_cannot_claim_new_direction(self) -> None:
        self.write_index(candidate_mechanisms=["managed-installation"])
        with self.assertRaisesRegex(RELEASE.ReleaseError, "overlaps prior attempts"):
            RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Disguised repeated attempt",
                notes_file=self.notes,
                attempt_index=self.index,
                confirm=False,
            )

    def test_structured_changed_premise_allows_a_reviewed_retry(self) -> None:
        self.write_index(
            classification="retry_changed_premise",
            candidate_mechanisms=["managed-installation"],
            changed_premise={
                "prior_mechanism_ids": ["managed-installation"],
                "falsified_assumption": "The previous loader path was stable across host releases.",
                "measurable_difference": "The new host exposes a different authoritative discovery root.",
                "new_evidence": ["host-loader-contract-2026-09"],
            },
        )
        with mock.patch.object(RELEASE, "latest_tag", return_value="v0.1.1"):
            result = RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Changed loader premise",
                notes_file=self.notes,
                attempt_index=self.index,
                confirm=False,
            )
        self.assertEqual(result["status"], "preview")

    def test_unknown_prior_family_refuses(self) -> None:
        self.write_index(prior_art_refs=["missing-family"])
        with self.assertRaisesRegex(RELEASE.ReleaseError, "unknown attempt families"):
            RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Unknown history",
                notes_file=self.notes,
                attempt_index=self.index,
                confirm=False,
            )

    def test_omitted_prior_family_refuses(self) -> None:
        document = json.loads(self.index.read_text(encoding="utf-8"))
        document["attempt_families"].append(
            {
                "id": "older-routing",
                "versions": ["v0.3.0"],
                "direction": "An older routing experiment.",
                "mechanism_ids": ["old-routing"],
                "evidence": ["docs/older.md"],
                "observed_result": "Failed its economic gate.",
                "repeat_rule": "Retry only with a changed premise.",
            }
        )
        self.index.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(RELEASE.ReleaseError, "omit attempt families"):
            RELEASE.publish(
                gh=self.gh,
                repository=self.repository,
                tag="v0.4.1",
                title="Incomplete history review",
                notes_file=self.notes,
                attempt_index=self.index,
                confirm=False,
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
