#!/usr/bin/env python3
"""Publish a non-Latest GitHub Release while preserving the proven release pin."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PINNED_LATEST_TAG = "v0.1.1"


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
    confirm: bool,
) -> dict[str, object]:
    if tag == PINNED_LATEST_TAG:
        raise ReleaseError(f"{PINNED_LATEST_TAG} is pinned and may not be republished by this tool")
    if not notes_file.is_file():
        raise ReleaseError(f"release notes file not found: {notes_file}")

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
            confirm=args.confirm,
        )
    except ReleaseError as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
