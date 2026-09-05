#!/usr/bin/env python3
"""Publish a non-Latest GitHub Release while preserving the proven release pin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PINNED_LATEST_TAG = "v0.1.1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTEMPT_INDEX = ROOT / "docs" / "benchmark" / "attempt-index.json"
ATTEMPT_CLASSIFICATIONS = {"new_direction", "retry_changed_premise"}


class ReleaseError(RuntimeError):
    """The guarded release operation could not preserve its contract."""


def find_gh(explicit: Path | None = None) -> Path:
    if explicit is not None:
        if explicit.is_file():
            return explicit.resolve()
        raise ReleaseError(f"GitHub CLI not found: {explicit}")

    discovered = shutil.which("gh")
    if discovered:
        return Path(discovered).resolve()

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "GitHub CLI"
        / "gh.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ReleaseError("GitHub CLI is installed but was not found on PATH or in a standard location")


def run_gh(gh: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        [str(gh), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown gh failure"
        raise ReleaseError(detail)
    return completed.stdout.strip()


def latest_tag(gh: Path, repository: str) -> str:
    value = run_gh(
        gh,
        ["api", f"repos/{repository}/releases/latest", "--jq", ".tag_name"],
    )
    if not value:
        raise ReleaseError("GitHub returned an empty latest release tag")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ReleaseError(f"{field} must be a non-empty list of non-empty strings")
    return value


def _meaningful_text(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < 20:
        raise ReleaseError(f"{field} must contain at least 20 non-whitespace characters")
    return value


def load_attempt_entry(index_path: Path, tag: str) -> tuple[dict[str, object], str]:
    if not index_path.is_file():
        raise ReleaseError(f"attempt index not found: {index_path}")
    try:
        raw = index_path.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"invalid attempt index: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ReleaseError("attempt index must be a schema-version 1 object")
    updated_through = document.get("updated_through")
    if not isinstance(updated_through, str) or not updated_through.strip():
        raise ReleaseError("attempt index updated_through must be non-empty")

    families = document.get("attempt_families")
    if not isinstance(families, list) or not families:
        raise ReleaseError("attempt index must contain attempt_families")
    family_ids: set[str] = set()
    indexed_versions: set[str] = set()
    indexed_mechanisms: set[str] = set()
    for family in families:
        if not isinstance(family, dict):
            raise ReleaseError("attempt_families entries must be objects")
        family_id = family.get("id")
        if not isinstance(family_id, str) or not family_id.strip() or family_id in family_ids:
            raise ReleaseError("attempt family ids must be unique non-empty strings")
        family_ids.add(family_id)
        versions = _string_list(family.get("versions"), f"attempt family {family_id} versions")
        duplicate_versions = sorted(set(versions) & indexed_versions)
        if duplicate_versions:
            raise ReleaseError(
                f"attempt versions must belong to one family: {', '.join(duplicate_versions)}"
            )
        indexed_versions.update(versions)
        mechanisms = _string_list(
            family.get("mechanism_ids"), f"attempt family {family_id} mechanism_ids"
        )
        duplicate_mechanisms = sorted(set(mechanisms) & indexed_mechanisms)
        if duplicate_mechanisms:
            raise ReleaseError(
                "mechanism ids must belong to one family: "
                + ", ".join(duplicate_mechanisms)
            )
        indexed_mechanisms.update(mechanisms)
        _string_list(family.get("evidence"), f"attempt family {family_id} evidence")
        for field in ("direction", "observed_result", "repeat_rule"):
            if not isinstance(family.get(field), str) or not family[field].strip():
                raise ReleaseError(f"attempt family {family_id} {field} must be non-empty")

    entries = document.get("release_entries")
    if not isinstance(entries, list):
        raise ReleaseError("attempt index release_entries must be a list")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("tag") == tag]
    if len(matches) != 1:
        raise ReleaseError(f"attempt index must contain exactly one release entry for {tag}")
    entry = matches[0]
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise ReleaseError("release entry id must be non-empty")

    reviewed = entry.get("history_reviewed_through")
    if not isinstance(reviewed, str) or not reviewed.strip():
        raise ReleaseError("history_reviewed_through must be non-empty")
    if reviewed != updated_through:
        raise ReleaseError(
            "history_reviewed_through must equal the attempt index updated_through"
        )
    refs = _string_list(entry.get("prior_art_refs"), "prior_art_refs")
    unknown = sorted(set(refs) - family_ids)
    if unknown:
        raise ReleaseError(f"prior_art_refs contain unknown attempt families: {', '.join(unknown)}")
    missing = sorted(family_ids - set(refs))
    if missing:
        raise ReleaseError(f"prior_art_refs omit attempt families: {', '.join(missing)}")
    _meaningful_text(entry.get("direction"), "release direction")
    candidate_mechanisms = set(_string_list(entry.get("mechanism_ids"), "mechanism_ids"))
    repeated_mechanisms = sorted(candidate_mechanisms & indexed_mechanisms)
    classification = entry.get("classification")
    if classification not in ATTEMPT_CLASSIFICATIONS:
        raise ReleaseError(
            "classification must be new_direction or retry_changed_premise"
        )
    changed_premise = entry.get("changed_premise")
    novelty_statement = entry.get("novelty_statement")
    if repeated_mechanisms:
        if classification != "retry_changed_premise":
            raise ReleaseError(
                "candidate mechanism overlaps prior attempts and must be retry_changed_premise: "
                + ", ".join(repeated_mechanisms)
            )
        if not isinstance(changed_premise, dict):
            raise ReleaseError("a repeated direction requires a structured changed_premise")
        required = {
            "prior_mechanism_ids",
            "falsified_assumption",
            "measurable_difference",
            "new_evidence",
        }
        if set(changed_premise) != required:
            raise ReleaseError(
                "changed_premise fields must be prior_mechanism_ids, "
                "falsified_assumption, measurable_difference, and new_evidence"
            )
        prior_mechanisms = set(
            _string_list(
                changed_premise.get("prior_mechanism_ids"),
                "changed_premise prior_mechanism_ids",
            )
        )
        if prior_mechanisms != set(repeated_mechanisms):
            raise ReleaseError(
                "changed_premise prior_mechanism_ids must equal every overlapping mechanism"
            )
        _meaningful_text(
            changed_premise.get("falsified_assumption"),
            "changed_premise falsified_assumption",
        )
        _meaningful_text(
            changed_premise.get("measurable_difference"),
            "changed_premise measurable_difference",
        )
        _string_list(changed_premise.get("new_evidence"), "changed_premise new_evidence")
        if novelty_statement is not None:
            raise ReleaseError("retry_changed_premise must use null novelty_statement")
    else:
        if classification != "new_direction":
            raise ReleaseError(
                "a candidate without an indexed mechanism overlap must be new_direction"
            )
        if changed_premise is not None:
            raise ReleaseError("new_direction must use null changed_premise")
        _meaningful_text(novelty_statement, "novelty_statement")
    _string_list(entry.get("evidence_refs"), "evidence_refs")
    if entry.get("decision") != "SHIP_EXPERIMENTAL":
        raise ReleaseError("release entry decision must be SHIP_EXPERIMENTAL")
    normal_path_cost = entry.get("normal_path_cost")
    if normal_path_cost not in {"none", "reduced", "measured"}:
        raise ReleaseError("normal_path_cost must be none, reduced, or measured")
    return entry, hashlib.sha256(raw).hexdigest()


def release_command(
    *, gh: Path, repository: str, tag: str, title: str, notes_file: Path
) -> list[str]:
    return [
        str(gh),
        "release",
        "create",
        tag,
        "--repo",
        repository,
        "--verify-tag",
        "--latest=false",
        "--title",
        title,
        "--notes-file",
        str(notes_file.resolve()),
    ]


def publish(
    *,
    gh: Path,
    repository: str,
    tag: str,
    title: str,
    notes_file: Path,
    attempt_index: Path,
    confirm: bool,
) -> dict[str, object]:
    if tag == PINNED_LATEST_TAG:
        raise ReleaseError(f"{PINNED_LATEST_TAG} is pinned and may not be republished by this tool")
    if not notes_file.is_file():
        raise ReleaseError(f"release notes file not found: {notes_file}")
    attempt_entry, attempt_index_sha256 = load_attempt_entry(attempt_index, tag)

    before = latest_tag(gh, repository)
    if before != PINNED_LATEST_TAG:
        raise ReleaseError(
            f"latest release drifted: expected {PINNED_LATEST_TAG}, observed {before}; refusing to publish"
        )

    command = release_command(
        gh=gh,
        repository=repository,
        tag=tag,
        title=title,
        notes_file=notes_file,
    )
    if confirm:
        run_gh(gh, command[1:])
        after = latest_tag(gh, repository)
        if after != PINNED_LATEST_TAG:
            raise ReleaseError(
                f"release was created but Latest changed to {after}; manual recovery is required"
            )
        status = "published"
    else:
        after = before
        status = "preview"

    return {
        "status": status,
        "repository": repository,
        "tag": tag,
        "latest_before": before,
        "latest_after": after,
        "pinned_latest": PINNED_LATEST_TAG,
        "attempt_entry_id": attempt_entry["id"],
        "attempt_index_sha256": attempt_index_sha256,
        "command": command,
        "writes_performed": confirm,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Create an ordinary GitHub Release without replacing pinned Latest v0.1.1."
    )
    result.add_argument("--repo", required=True, help="GitHub owner/repository")
    result.add_argument("--tag", required=True)
    result.add_argument("--title", required=True)
    result.add_argument("--notes-file", required=True, type=Path)
    result.add_argument(
        "--attempt-index",
        type=Path,
        default=DEFAULT_ATTEMPT_INDEX,
        help="history index containing the release's prior-attempt review",
    )
    result.add_argument("--gh", type=Path, help="explicit GitHub CLI executable")
    result.add_argument("--confirm", action="store_true", help="create the release after preflight")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        document = publish(
            gh=find_gh(args.gh),
            repository=args.repo,
            tag=args.tag,
            title=args.title,
            notes_file=args.notes_file,
            attempt_index=args.attempt_index,
            confirm=args.confirm,
        )
    except ReleaseError as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
