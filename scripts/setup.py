#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Edmund Dai
# SPDX-License-Identifier: Apache-2.0
"""Preview, install, update, diagnose, and roll back Sol-Luna managed assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

STATE_SCHEMA = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = REPO_ROOT / ".agents" / "skills" / "sol-luna"
AGENT_SOURCE = REPO_ROOT / ".codex" / "agents"
OLD_SKILL_RELATIVE = Path("skills") / "sol-luna"
OLD_AGENT_NAME = "luna-worker.toml"


class SetupError(ValueError):
    """A setup operation is unsafe, conflicted, or inconsistent."""


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def bytes_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def remove_empty_parents(path: Path, stop: Path) -> None:
    stop = stop.resolve(strict=False)
    current = path.resolve(strict=False)
    while current != stop:
        try:
            current.relative_to(stop)
        except ValueError as exc:
            raise SetupError("cleanup path escapes its declared root") from exc
        try:
            current.rmdir()
        except (FileNotFoundError, OSError):
            break
        current = current.parent


def is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def assert_safe_target(path: Path, root: Path) -> None:
    root = root.resolve(strict=False)
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SetupError("managed target escapes its declared install root") from exc
    if candidate == root:
        raise SetupError("a managed file may not equal the install root")
    current = root
    for part in candidate.relative_to(root).parts[:-1]:
        current = current / part
        if current.exists() and is_link_like(current):
            raise SetupError("managed target traverses a symlink or reparse point")
    if path.exists() and is_link_like(path):
        raise SetupError("managed target is a symlink or reparse point")


def validate_roots(codex_home: Path, skills_home: Path) -> tuple[Path, Path]:
    codex = codex_home.resolve(strict=False)
    skills = skills_home.resolve(strict=False)
    for name, root in (("codex_home", codex), ("skills_home", skills)):
        if root == Path(root.anchor) or root == REPO_ROOT.resolve():
            raise SetupError(f"{name} is too broad or points at the source repository")
        if root.exists() and is_link_like(root):
            raise SetupError(f"{name} may not be a symlink or reparse point")
    return codex, skills


def managed_assets(codex_home: Path, skills_home: Path) -> list[dict[str, Any]]:
    codex, skills = validate_roots(codex_home, skills_home)
    assets: list[dict[str, Any]] = []
    for source in sorted(SKILL_SOURCE.rglob("*")):
        if source.is_file() and "__pycache__" not in source.parts and source.suffix not in {".pyc", ".pyo"}:
            relative = source.relative_to(SKILL_SOURCE)
            target = skills / "sol-luna" / relative
            assert_safe_target(target, skills)
            assets.append({"kind": "skill", "source": source, "target": target, "relative": relative.as_posix()})
    for source in sorted(AGENT_SOURCE.glob("*.toml")):
        target = codex / "agents" / source.name
        assert_safe_target(target, codex)
        assets.append({"kind": "agent", "source": source, "target": target, "relative": source.name})
    return assets


def source_fingerprint(assets: list[Mapping[str, Any]]) -> str:
    rows = [f"{item['kind']}:{item['relative']}:{digest(item['source'])}" for item in assets]
    return bytes_digest("\n".join(rows).encode("utf-8"))


def source_fingerprint_for_state(assets: list[Mapping[str, Any]], installed: Mapping[str, Any]) -> str:
    selected = [item for item in assets if str(item["target"]) in installed]
    return source_fingerprint(selected)


def installed_fingerprint_for_state(assets: list[Mapping[str, Any]], installed: Mapping[str, Any]) -> str:
    """Rebuild a legacy state's fingerprint from its path allowlist and hashes."""
    rows = [
        f"{item['kind']}:{item['relative']}:{installed[str(item['target'])]}"
        for item in assets
        if str(item["target"]) in installed
    ]
    return bytes_digest("\n".join(rows).encode("utf-8"))


def state_path(codex_home: Path) -> Path:
    return codex_home / "sol-luna-install-state.json"


def load_state(codex_home: Path) -> dict[str, Any] | None:
    path = state_path(codex_home)
    if not path.exists():
        return None
    if is_link_like(path):
        raise SetupError("install state may not be a symlink or reparse point")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot read install state: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
        raise SetupError("install state has an unsupported schema")
    return state


def tree_manifest(path: Path) -> list[str]:
    """Return a deterministic, file-only manifest for an exact tree."""
    if not path.exists():
        return []
    if not path.is_dir() or is_link_like(path):
        raise SetupError("legacy skill path is not a normal directory")
    rows: list[str] = []
    for item in sorted(path.rglob("*")):
        if item.is_dir():
            if is_link_like(item):
                raise SetupError("legacy skill tree contains a symlink or reparse point")
            continue
        if is_link_like(item):
            raise SetupError("legacy skill tree contains a symlink or reparse point")
        rows.append(f"{item.relative_to(path).as_posix()}:{digest(item)}")
    return rows


def _expected_map(codex: Path, skills: Path) -> dict[str, Path]:
    return {str(item["target"]): item["target"] for item in managed_assets(codex, skills)}


def _validate_migration_record(codex: Path, migration: Mapping[str, Any], backup_root: Path) -> None:
    if migration.get("legacy_skill") is None or migration.get("legacy_agent") is None:
        raise SetupError("install state migration record is incomplete")
    legacy_skill = Path(str(migration["legacy_skill"])).resolve(strict=False)
    legacy_agent = Path(str(migration["legacy_agent"])).resolve(strict=False)
    source_root = migration.get("source_skills_home")
    if not isinstance(source_root, str) or not source_root:
        raise SetupError("install state migration source root is invalid")
    expected_skill = Path(source_root).resolve(strict=False) / "sol-luna"
    if legacy_skill != expected_skill or legacy_agent != codex / "agents" / OLD_AGENT_NAME:
        raise SetupError("install state migration paths are not exact")
    for field, name in (("legacy_skill_backup", "legacy-skill"), ("legacy_agent_backup", "agents/" + OLD_AGENT_NAME), ("state_backup", "legacy-state")):
        value = migration.get(field)
        if value is not None:
            observed = Path(str(value)).resolve(strict=False)
            assert_safe_target(observed, backup_root)
            if observed != backup_root / name:
                raise SetupError(f"install state {field} does not match the exact backup path")
    agent_backups = migration.get("agent_backups", {})
    if not isinstance(agent_backups, Mapping):
        raise SetupError("install state agent backup map is invalid")
    for target_value, backup_value in agent_backups.items():
        target = Path(str(target_value)).resolve(strict=False)
        if target != codex / "agents" / target.name:
            raise SetupError("install state agent backup target is invalid")
        backup = Path(str(backup_value)).resolve(strict=False)
        assert_safe_target(backup, backup_root)
        if backup != backup_root / "agents" / target.name:
            raise SetupError("install state agent backup path is invalid")
    for field in ("legacy_skill_tree_fingerprint", "legacy_agent_backup_hash", "state_backup_hash"):
        value = migration.get(field)
        if value is not None and (not isinstance(value, str) or not value.startswith("sha256:")):
            raise SetupError(f"install state {field} is invalid")


def validate_state_for_write(
    codex_home: Path,
    skills_home: Path,
    state: Mapping[str, Any],
    *,
    verify_files: bool = False,
    allow_subset: bool = False,
) -> tuple[Path, dict[str, Path | None]]:
    """Validate state paths and maps before any lifecycle write."""
    codex, skills = validate_roots(codex_home, skills_home)
    if Path(str(state.get("codex_home", ""))).resolve(strict=False) != codex:
        raise SetupError("install state codex_home does not match the requested root")
    if Path(str(state.get("skills_home", ""))).resolve(strict=False) != skills:
        raise SetupError("install state skills_home does not match the requested root")
    expected = _expected_map(codex, skills)
    expected_hashes = {str(item["target"]): digest(item["source"]) for item in managed_assets(codex, skills)}
    installed = state.get("installed")
    previous = state.get("previous")
    if not isinstance(installed, Mapping) or not isinstance(previous, Mapping):
        raise SetupError("install state managed-file maps are invalid")
    if set(installed) != set(previous):
        raise SetupError("install state does not register exactly the current managed assets")
    if not set(installed).issubset(set(expected)) or (not allow_subset and set(installed) != set(expected)):
        raise SetupError("install state names an unknown or unregistered managed asset")
    backup_value = state.get("backup_root")
    if not isinstance(backup_value, str) or not backup_value:
        raise SetupError("install state backup root is invalid")
    backup_root = Path(backup_value).resolve(strict=False)
    backup_base = codex / "sol-luna-backups"
    if backup_base.exists() and is_link_like(backup_base):
        raise SetupError("backup root may not be a symlink or reparse point")
    assert_safe_target(backup_root, backup_base)
    normalized_previous: dict[str, Path | None] = {}
    for target_value, expected_hash in installed.items():
        target = expected[target_value]
        assert_safe_target(target, codex if target.is_relative_to(codex) else skills)
        if not isinstance(expected_hash, str) or not expected_hash.startswith("sha256:"):
            raise SetupError("install state managed-file hash is invalid")
        if verify_files and not allow_subset and expected_hash != expected_hashes[target_value]:
            raise SetupError("install state managed-file hash is not source-bound")
        if verify_files and (not target.exists() or is_link_like(target) or digest(target) != expected_hash):
            raise SetupError("managed installation has drifted or missing files")
        old_backup = previous[target_value]
        if old_backup is None:
            normalized_previous[target_value] = None
        else:
            if not isinstance(old_backup, str):
                raise SetupError("install state backup path is invalid")
            backup = Path(old_backup).resolve(strict=False)
            assert_safe_target(backup, backup_root)
            normalized_previous[target_value] = backup
    if verify_files:
        assets = managed_assets(codex, skills)
        expected_fp = (installed_fingerprint_for_state(assets, installed) if allow_subset
                       else source_fingerprint_for_state(assets, installed))
        if state.get("source_fingerprint") != expected_fp:
            raise SetupError("install state source fingerprint is stale")
    migration = state.get("migration")
    if migration is not None:
        if not isinstance(migration, Mapping):
            raise SetupError("install state migration record is invalid")
        _validate_migration_record(codex, migration, backup_root)
    return backup_root, normalized_previous


def _state_bytes(codex: Path) -> bytes | None:
    path = state_path(codex)
    return path.read_bytes() if path.exists() else None


def _legacy_candidates(codex: Path) -> list[Path]:
    # Report these as conflicts when no trusted state identifies a source;
    # never copy or remove them by inference.
    return [codex / OLD_SKILL_RELATIVE, codex.parent / ".agents" / OLD_SKILL_RELATIVE]


def preview(codex_home: Path, skills_home: Path, *, require_installed: bool = False) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    state = load_state(codex)
    if require_installed and (not state or state.get("status") != "installed"):
        raise SetupError("update requires a valid installed state")
    if require_installed and state:
        validate_state_for_write(codex, skills, state)
    tracked = state.get("installed", {}) if state and state.get("status") == "installed" else {}
    assets = managed_assets(codex, skills)
    operations: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for asset in assets:
        target = asset["target"]
        source_hash = digest(asset["source"])
        target_key = str(target)
        if not target.exists():
            action = "create"
        elif is_link_like(target):
            action = "conflict"
            conflicts.append(f"{asset['kind']}:{asset['relative']}")
        else:
            current_hash = digest(target)
            if current_hash == source_hash:
                action = "unchanged"
            elif tracked.get(target_key) == current_hash:
                action = "replace-managed"
            else:
                action = "conflict"
                conflicts.append(f"{asset['kind']}:{asset['relative']}")
        operations.append({"kind": asset["kind"], "relative": asset["relative"], "action": action,
                           "source_hash": source_hash, "target": target_key})
    for legacy in _legacy_candidates(codex):
        if legacy.exists() and legacy.resolve(strict=False) != (skills / "sol-luna").resolve(strict=False):
            conflicts.append("legacy:" + str(legacy))
    return {"schema_version": STATE_SCHEMA, "mode": "update" if require_installed else "install",
            "source_fingerprint": source_fingerprint(assets), "operations": operations,
            "conflicts": sorted(set(conflicts)), "safe_to_apply": not conflicts, "writes_performed": False}


def _old_state_context(codex: Path, requested_skills: Path) -> tuple[dict[str, Any] | None, Path | None, bytes | None]:
    state = load_state(codex)
    if not state or state.get("status") != "installed":
        return state, None, _state_bytes(codex)
    old_value = state.get("skills_home")
    if not isinstance(old_value, str) or not old_value:
        raise SetupError("managed state has no trusted skills_home")
    old_skills = Path(old_value).resolve(strict=False)
    if old_skills == requested_skills:
        raise SetupError("migration target is the already-recorded skills root")
    validate_state_for_write(codex, old_skills, state, verify_files=True, allow_subset=True)
    return state, old_skills, _state_bytes(codex)


def migration_plan(codex_home: Path, skills_home: Path) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    state, old_skills, state_bytes = _old_state_context(codex, skills)
    conflicts: list[str] = []
    operations: list[dict[str, Any]] = []
    if old_skills is None:
        for candidate in _legacy_candidates(codex):
            if candidate.exists():
                conflicts.append("untrusted-legacy-source:" + str(candidate))
        body = {"schema_version": STATE_SCHEMA, "mode": "migrate", "from_skills_home": None,
                "to_skills_home": str(skills), "source_fingerprint": None, "operations": operations,
                "conflicts": sorted(set(conflicts)), "safe_to_apply": False, "writes_performed": False}
        body["plan_fingerprint"] = bytes_digest(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
        return body
    old_skill = old_skills / "sol-luna"
    old_assets = managed_assets(codex, old_skills)
    new_assets = managed_assets(codex, skills)
    old_installed = state.get("installed", {}) if isinstance(state, Mapping) else {}
    registered_skill: set[str] = set()
    registered_skill_rows: set[str] = set()
    for target_value, expected_hash in old_installed.items():
        target = Path(str(target_value)).resolve(strict=False)
        try:
            relative = target.relative_to(old_skill).as_posix()
        except ValueError:
            continue
        registered_skill.add(relative)
        registered_skill_rows.add(f"{relative}:{expected_hash}")
    manifest = tree_manifest(old_skill)
    observed_skill = {row.split(":", 1)[0] for row in manifest}
    if observed_skill != registered_skill or set(manifest) != registered_skill_rows:
        conflicts.append("legacy-skill-contains-unregistered-or-missing-files")
    old_agent = codex / "agents" / OLD_AGENT_NAME
    for asset in new_assets:
        target = asset["target"]
        if target.exists():
            # Agent assets intentionally keep their codex/agents target during
            # a skills-root migration.  They are safe only when the old state
            # registered the exact path and its recorded hash still matches.
            key = str(target)
            if asset["kind"] == "agent" and key in old_installed and not is_link_like(target) and digest(target) == old_installed[key]:
                action = "retain-managed"
            else:
                conflicts.append("target-conflict:" + str(target))
                action = "conflict"
        else:
            action = "create"
        operations.append({"kind": asset["kind"], "relative": asset["relative"], "action": action,
                           "target": str(target), "source_hash": digest(asset["source"])})
    operations.append({"kind": "legacy-skill", "action": "retire", "target": str(old_skill),
                       "tree": manifest, "tree_fingerprint": bytes_digest("\n".join(manifest).encode())})
    for target_value in old_installed:
        target = Path(str(target_value))
        if target.parent == codex / "agents" and target.exists() and is_link_like(target):
            conflicts.append("legacy-agent-link:" + str(target))
    if old_agent.exists():
        operations.append({"kind": "legacy-agent", "action": "retain-managed-target", "target": str(old_agent),
                           "existing_hash": digest(old_agent) if not is_link_like(old_agent) else None})
    body = {"schema_version": STATE_SCHEMA, "mode": "migrate", "from_skills_home": str(old_skills),
            "to_skills_home": str(skills), "source_fingerprint": source_fingerprint(new_assets),
            "source_state_fingerprint": bytes_digest(state_bytes or b""), "operations": operations,
            "conflicts": sorted(set(conflicts)), "safe_to_apply": not conflicts, "writes_performed": False}
    body["plan_fingerprint"] = bytes_digest(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return body


def _copy_tree_checked(source: Path, destination: Path) -> None:
    tree_manifest(source)
    shutil.copytree(source, destination, symlinks=False)


def _remove_known_tree(path: Path, expected_root: Path) -> None:
    if not path.exists():
        return
    if is_link_like(path) or path.resolve(strict=False) != (expected_root / "sol-luna").resolve(strict=False):
        raise SetupError("refusing to remove an unexpected legacy tree")
    shutil.rmtree(path)


def migrate(codex_home: Path, skills_home: Path, plan_fingerprint: str) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    state, old_skills, old_state_bytes = _old_state_context(codex, skills)
    if old_skills is None or state is None:
        raise SetupError("migration requires a trusted installed state recording the old skills_home")
    plan = migration_plan(codex, skills)
    if not plan.get("safe_to_apply"):
        raise SetupError(f"refusing conflicted migration: {plan['conflicts']}")
    if plan.get("plan_fingerprint") != plan_fingerprint:
        raise SetupError("migration plan fingerprint is stale or incorrect")
    assets = managed_assets(codex, skills)
    old_skill = old_skills / "sol-luna"
    legacy_manifest = tree_manifest(old_skill)
    old_agent = codex / "agents" / OLD_AGENT_NAME
    operation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup_root = codex / "sol-luna-backups" / operation_id
    new_skill_targets = {a["target"] for a in assets if a["kind"] == "skill"}
    written: list[Path] = []
    removed_old = False
    try:
        _copy_tree_checked(old_skill, backup_root / "legacy-skill")
        agent_backups: dict[str, str] = {}
        for asset in assets:
            if asset["kind"] != "agent" or not asset["target"].exists():
                continue
            backup = backup_root / "agents" / asset["target"].name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset["target"], backup)
            agent_backups[str(asset["target"])] = str(backup)
        if old_state_bytes is not None:
            atomic_write(backup_root / "legacy-state", old_state_bytes)
        for asset in assets:
            target = asset["target"]
            atomic_write(target, asset["source"].read_bytes())
            written.append(target)
        _remove_known_tree(old_skill, old_skills)
        removed_old = True
        migration = {"legacy_skill": str(old_skill), "legacy_agent": str(old_agent),
                     "source_skills_home": str(old_skills),
                     "legacy_skill_backup": str(backup_root / "legacy-skill"),
                     "legacy_agent_backup": agent_backups.get(str(old_agent)),
                     "agent_backups": agent_backups,
                     "state_backup": str(backup_root / "legacy-state") if old_state_bytes is not None else None,
                     "legacy_skill_tree_fingerprint": bytes_digest("\n".join(legacy_manifest).encode()),
                     "legacy_agent_backup_hash": digest(Path(agent_backups[str(old_agent)])) if str(old_agent) in agent_backups else None,
                     "state_backup_hash": bytes_digest(old_state_bytes) if old_state_bytes is not None else None}
        new_state = {"schema_version": STATE_SCHEMA, "status": "installed", "operation_id": operation_id,
                     "installed_at": datetime.now(timezone.utc).isoformat(),
                     "source_fingerprint": source_fingerprint(assets), "codex_home": str(codex),
                     "skills_home": str(skills), "installed": {str(a["target"]): digest(a["source"]) for a in assets},
                     "previous": {str(a["target"]): None for a in assets}, "backup_root": str(backup_root),
                     "migration": migration}
        atomic_write(state_path(codex), (json.dumps(new_state, indent=2, sort_keys=True) + "\n").encode())
        result = doctor(codex)
        if result["status"] != "healthy":
            raise SetupError("post-migration Doctor did not verify the managed state")
    except Exception:
        for target in reversed(written):
            if target.exists() and not is_link_like(target):
                target.unlink()
                remove_empty_parents(target.parent, skills if target in new_skill_targets else codex)
        if removed_old and (backup_root / "legacy-skill").exists() and not old_skill.exists():
            shutil.copytree(backup_root / "legacy-skill", old_skill)
        for backup_value in agent_backups.values() if "agent_backups" in locals() else ():
            backup = Path(backup_value)
            target = codex / "agents" / backup.name
            if backup.exists():
                atomic_write(target, backup.read_bytes())
        if old_state_bytes is not None:
            atomic_write(state_path(codex), old_state_bytes)
        elif state_path(codex).exists():
            state_path(codex).unlink()
        raise
    return {"status": "migrated", "operation_id": operation_id, "doctor": result,
            "plan_fingerprint": plan_fingerprint}


def apply(codex_home: Path, skills_home: Path, *, update: bool = False) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    prior_state = load_state(codex)
    validated_backup: Path | None = None
    validated_previous: dict[str, Path | None] = {}
    if update:
        if not prior_state or prior_state.get("status") != "installed":
            raise SetupError("update requires a valid installed state")
        validated_backup, validated_previous = validate_state_for_write(
            codex, skills, prior_state, allow_subset=True
        )
    plan = preview(codex, skills, require_installed=update)
    if plan["conflicts"]:
        raise SetupError(f"refusing conflicted setup: {plan['conflicts']}")
    assets = managed_assets(codex, skills)
    operation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup_root = validated_backup if update and validated_backup else codex / "sol-luna-backups" / operation_id
    previous: dict[str, str | None] = ({key: str(value) if value is not None else None for key, value in validated_previous.items()}
                                       if update and prior_state else {})
    old_state_bytes = _state_bytes(codex)
    written: list[Path] = []
    try:
        for asset in assets:
            target = asset["target"]
            key = str(target)
            if key not in previous and target.exists():
                backup = backup_root / asset["kind"] / asset["relative"]
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                previous[key] = str(backup)
            elif key not in previous:
                previous[key] = None
            if target.exists() and digest(target) == digest(asset["source"]):
                continue
            atomic_write(target, asset["source"].read_bytes())
            written.append(target)
        new_state = {"schema_version": STATE_SCHEMA, "status": "installed", "operation_id": operation_id,
                     "installed_at": datetime.now(timezone.utc).isoformat(), "source_fingerprint": source_fingerprint(assets),
                     "codex_home": str(codex), "skills_home": str(skills),
                     "installed": {str(a["target"]): digest(a["source"]) for a in assets}, "previous": previous,
                     "backup_root": str(backup_root)}
        if update and prior_state and isinstance(prior_state.get("migration"), Mapping):
            # Keep the migration recovery record across updates; otherwise an
            # update would make the pre-migration installation unreachable.
            new_state["migration"] = prior_state["migration"]
        atomic_write(state_path(codex), (json.dumps(new_state, indent=2, sort_keys=True) + "\n").encode())
    except Exception:
        for target in reversed(written):
            backup_value = previous.get(str(target))
            if backup_value and Path(backup_value).exists():
                atomic_write(target, Path(backup_value).read_bytes())
            elif target.exists() and not is_link_like(target):
                target.unlink()
        if old_state_bytes is not None:
            atomic_write(state_path(codex), old_state_bytes)
        elif state_path(codex).exists():
            state_path(codex).unlink()
        raise
    result = doctor(codex)
    if result["status"] != "healthy":
        raise SetupError("post-install Doctor did not verify the managed state")
    return {"status": "installed", "operation_id": operation_id, "doctor": result}


def doctor(codex_home: Path) -> dict[str, Any]:
    codex = codex_home.resolve(strict=False)
    state = load_state(codex)
    if not state or state.get("status") != "installed":
        return {"status": "not-installed", "checked": 0, "missing": [], "drifted": []}
    try:
        if Path(str(state.get("codex_home", ""))).resolve(strict=False) != codex:
            raise SetupError("state codex_home does not match the requested root")
        skills = Path(str(state.get("skills_home", ""))).resolve(strict=False)
        validate_roots(codex, skills)
        expected = _expected_map(codex, skills)
        installed = state.get("installed", {})
        if not isinstance(installed, Mapping) or not set(installed).issubset(set(expected)):
            raise SetupError("state managed-file map is invalid")
        backup_root = Path(str(state.get("backup_root", ""))).resolve(strict=False)
        assert_safe_target(backup_root, codex / "sol-luna-backups")
        migration = state.get("migration")
        if migration is not None:
            if not isinstance(migration, Mapping):
                raise SetupError("state migration record is invalid")
            _validate_migration_record(codex, migration, backup_root)
    except SetupError:
        return {"status": "drifted", "source_fingerprint": state.get("source_fingerprint"),
                "checked": 0, "missing": [], "drifted": ["invalid managed state"],
                "operation_id": state.get("operation_id")}
    missing: list[str] = []
    drifted: list[str] = []
    migration = state.get("migration")
    if isinstance(migration, Mapping) and migration.get("legacy_skill"):
        if Path(str(migration["legacy_skill"])).exists():
            drifted.append("duplicate legacy skill")
    for target_value, expected_hash in installed.items():
        target = expected[target_value]
        if not target.exists():
            missing.append(target.name)
        elif is_link_like(target) or digest(target) != expected_hash:
            drifted.append(target.name)
    try:
        if state.get("source_fingerprint") != source_fingerprint_for_state(managed_assets(codex, skills), installed):
            drifted.append("source fingerprint")
    except (OSError, SetupError):
        drifted.append("source fingerprint")
    status = "healthy" if not missing and not drifted else "drifted"
    return {"status": status, "source_fingerprint": state.get("source_fingerprint"),
            "checked": len(installed), "missing": sorted(set(missing)), "drifted": sorted(set(drifted)),
            "operation_id": state.get("operation_id")}


def rollback(codex_home: Path, skills_home: Path) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    state = load_state(codex)
    if not state or state.get("status") != "installed":
        raise SetupError("rollback requires a valid installed state")
    _, previous = validate_state_for_write(codex, skills, state)
    migration = state.get("migration")
    if isinstance(migration, Mapping) and migration.get("state_backup"):
        conflicts = []
        for target_value, installed_hash in state["installed"].items():
            target = Path(target_value)
            if target.exists() and (is_link_like(target) or digest(target) != installed_hash):
                conflicts.append(target.name)
        if conflicts:
            raise SetupError(f"rollback refuses user-modified managed files: {sorted(conflicts)}")
        legacy_skill = Path(str(migration["legacy_skill"])).resolve(strict=False)
        legacy_agent = Path(str(migration["legacy_agent"])).resolve(strict=False)
        if legacy_skill.exists():
            raise SetupError("rollback refuses legacy path conflict")
        backup_root = Path(str(state["backup_root"])).resolve(strict=False)
        _validate_migration_record(codex, migration, backup_root)
        skill_backup = Path(str(migration["legacy_skill_backup"]))
        if not skill_backup.is_dir() or is_link_like(skill_backup):
            raise SetupError("migration legacy skill backup is missing or unsafe")
        if migration.get("legacy_skill_tree_fingerprint"):
            if bytes_digest("\n".join(tree_manifest(skill_backup)).encode()) != migration["legacy_skill_tree_fingerprint"]:
                raise SetupError("migration legacy skill backup has drifted")
        agent_backups = migration.get("agent_backups", {})
        agent_backup = migration.get("legacy_agent_backup")
        if agent_backup:
            agent_backup_path = Path(str(agent_backup))
            if not agent_backup_path.is_file() or is_link_like(agent_backup_path):
                raise SetupError("migration legacy agent backup is missing or unsafe")
            if migration.get("legacy_agent_backup_hash") and digest(agent_backup_path) != migration["legacy_agent_backup_hash"]:
                raise SetupError("migration legacy agent backup has drifted")
        for target_value, backup_value in agent_backups.items():
            backup_path = Path(str(backup_value))
            if not backup_path.is_file() or is_link_like(backup_path):
                raise SetupError("migration agent backup is missing or unsafe")
        state_backup = Path(str(migration["state_backup"]))
        if not state_backup.is_file() or is_link_like(state_backup):
            raise SetupError("migration state backup is missing or unsafe")
        if migration.get("state_backup_hash") and digest(state_backup) != migration["state_backup_hash"]:
            raise SetupError("migration state backup has drifted")
        removed = 0
        for target_value in sorted(state["installed"], reverse=True):
            target = Path(target_value)
            if target.exists() and target.is_relative_to(skills):
                target.unlink()
                remove_empty_parents(target.parent, skills)
                removed += 1
            elif target.exists() and target.is_relative_to(codex / "agents") and target_value not in agent_backups:
                target.unlink()
                remove_empty_parents(target.parent, codex)
                removed += 1
        shutil.copytree(skill_backup, legacy_skill)
        for target_value, backup_value in agent_backups.items():
            target = Path(str(target_value))
            atomic_write(target, Path(str(backup_value)).read_bytes())
        atomic_write(state_path(codex), state_backup.read_bytes())
        return {"status": "rolled-back", "restored": 2 if agent_backup else 1, "removed": removed}
    conflicts = []
    for target_value, installed_hash in state.get("installed", {}).items():
        target = Path(target_value)
        if target.exists() and (is_link_like(target) or digest(target) != installed_hash):
            conflicts.append(target.name)
    if conflicts:
        raise SetupError(f"rollback refuses user-modified managed files: {sorted(conflicts)}")
    restored = 0
    removed = 0
    for target_value in sorted(state.get("installed", {}), reverse=True):
        target = Path(target_value)
        backup = previous.get(target_value)
        if backup and backup.exists():
            atomic_write(target, backup.read_bytes())
            restored += 1
        elif target.exists():
            target.unlink()
            removed += 1
            remove_empty_parents(target.parent, codex if target.is_relative_to(codex) else skills)
    state["status"] = "rolled-back"
    state["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(state_path(codex), (json.dumps(state, indent=2, sort_keys=True) + "\n").encode())
    return {"status": "rolled-back", "restored": restored, "removed": removed}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage a bounded Sol-Luna installation lifecycle.")
    result.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    result.add_argument("--skills-home", type=Path, default=None)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("preview")
    sub.add_parser("migration-preview")
    migrate_command = sub.add_parser("migrate")
    migrate_command.add_argument("--confirm", action="store_true")
    migrate_command.add_argument("--plan-fingerprint", required=True)
    for name in ("install", "update", "rollback"):
        command = sub.add_parser(name)
        command.add_argument("--confirm", action="store_true")
    sub.add_parser("doctor")
    return result


def main() -> int:
    args = parser().parse_args()
    skills_home = args.skills_home if args.skills_home is not None else args.codex_home / "skills"
    try:
        if args.command == "preview":
            output = preview(args.codex_home, skills_home)
        elif args.command == "migration-preview":
            output = migration_plan(args.codex_home, skills_home)
        elif args.command == "doctor":
            output = doctor(args.codex_home)
        elif not args.confirm:
            raise SetupError(f"{args.command} requires --confirm after reviewing preview")
        elif args.command == "install":
            output = apply(args.codex_home, skills_home)
        elif args.command == "migrate":
            output = migrate(args.codex_home, skills_home, args.plan_fingerprint)
        elif args.command == "update":
            output = apply(args.codex_home, skills_home, update=True)
        else:
            output = rollback(args.codex_home, skills_home)
    except (OSError, SetupError) as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
