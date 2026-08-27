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
    """Remove only empty directories below an exact root, stopping on content."""
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
    root = root.resolve()
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SetupError("managed target escapes its declared install root") from exc
    if candidate == root:
        raise SetupError("a managed file may not equal the install root")
    current = root
    relative = candidate.relative_to(root)
    for part in relative.parts[:-1]:
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
    return "sha256:" + hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def tree_manifest(path: Path) -> list[str]:
    """Return a deterministic, file-only manifest for an exact legacy tree."""
    if not path.exists():
        return []
    if not path.is_dir() or is_link_like(path):
        raise SetupError("legacy skill path is not a normal directory")
    rows = []
    for item in sorted(path.rglob("*")):
        if item.is_dir():
            if is_link_like(item):
                raise SetupError("legacy skill tree contains a symlink or reparse point")
            continue
        if is_link_like(item):
            raise SetupError("legacy skill tree contains a symlink or reparse point")
        rows.append(f"{item.relative_to(path).as_posix()}:{digest(item)}")
    return rows


def migration_plan(codex_home: Path, skills_home: Path) -> dict[str, Any]:
    """Build a non-mutating, state-bound takeover plan for legacy installs."""
    codex, skills = validate_roots(codex_home, skills_home)
    # The legacy tree is inside codex_home. If the requested new skills root
    # aliases that same tree, writing the new tree and retiring the old one
    # would be destructive and ambiguous; require an explicit safe layout.
    if skills == (codex / "skills").resolve(strict=False):
        raise SetupError("migration requires a skills root distinct from codex_home/skills")
    assets = managed_assets(codex, skills)
    old_skill = codex / OLD_SKILL_RELATIVE
    old_agent = codex / "agents" / OLD_AGENT_NAME
    operations: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for asset in assets:
        target = asset["target"]
        current = digest(target) if target.exists() and not is_link_like(target) else None
        action = "replace" if target.exists() else "create"
        if target.exists() and is_link_like(target):
            action = "conflict"
            conflicts.append(str(target))
        operations.append({"kind": asset["kind"], "relative": asset["relative"],
                           "action": action, "target": str(target),
                           "existing_hash": current, "source_hash": digest(asset["source"])})
    old_manifest = tree_manifest(old_skill)
    if old_skill.exists():
        operations.append({"kind": "legacy-skill", "action": "retire", "target": str(old_skill),
                           "tree": old_manifest, "tree_fingerprint": "sha256:" + hashlib.sha256("\n".join(old_manifest).encode()).hexdigest()})
    if old_agent.exists():
        if is_link_like(old_agent):
            conflicts.append(str(old_agent))
        agent_action = "replace" if old_agent in {a["target"] for a in assets} else "retire"
        operations.append({"kind": "legacy-agent", "action": agent_action, "target": str(old_agent),
                           "existing_hash": None if is_link_like(old_agent) else digest(old_agent)})
    body = {"schema_version": STATE_SCHEMA, "mode": "migrate",
            "source_fingerprint": source_fingerprint(assets), "operations": operations,
            "conflicts": sorted(conflicts), "safe_to_apply": not conflicts,
            "writes_performed": False}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body["plan_fingerprint"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return body


def state_path(codex_home: Path) -> Path:
    return codex_home / "sol-luna-install-state.json"


def load_state(codex_home: Path) -> dict[str, Any] | None:
    path = state_path(codex_home)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot read install state: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA:
        raise SetupError("install state has an unsupported schema")
    return state


def validate_state_for_write(
    codex_home: Path,
    skills_home: Path,
    state: Mapping[str, Any],
) -> tuple[Path, dict[str, Path | None]]:
    """Reject state-file path substitution before update or rollback writes."""
    codex, skills = validate_roots(codex_home, skills_home)
    if Path(str(state.get("codex_home", ""))).resolve(strict=False) != codex:
        raise SetupError("install state codex_home does not match the requested root")
    if Path(str(state.get("skills_home", ""))).resolve(strict=False) != skills:
        raise SetupError("install state skills_home does not match the requested root")

    expected_targets = {str(item["target"]): item["target"] for item in managed_assets(codex, skills)}
    installed = state.get("installed")
    previous = state.get("previous")
    if not isinstance(installed, Mapping) or not isinstance(previous, Mapping):
        raise SetupError("install state managed-file maps are invalid")
    unexpected = (set(installed) | set(previous)) - set(expected_targets)
    if unexpected:
        raise SetupError("install state names a file outside the current managed asset set")

    backup_base = codex / "sol-luna-backups"
    backup_root = Path(str(state.get("backup_root", ""))).resolve(strict=False)
    assert_safe_target(backup_root, backup_base)
    normalized_previous: dict[str, Path | None] = {}
    for target_value, backup_value in previous.items():
        target = expected_targets[target_value]
        assert_safe_target(target, codex if target_value.startswith(str(codex)) else skills)
        if backup_value is None:
            normalized_previous[target_value] = None
            continue
        backup = Path(str(backup_value))
        assert_safe_target(backup, backup_root)
        normalized_previous[target_value] = backup

    migration = state.get("migration")
    if migration is not None:
        if not isinstance(migration, Mapping):
            raise SetupError("install state migration record is invalid")
        expected_legacy = {
            "legacy_skill": codex / OLD_SKILL_RELATIVE,
            "legacy_agent": codex / "agents" / OLD_AGENT_NAME,
        }
        for field, expected in expected_legacy.items():
            observed = Path(str(migration.get(field, ""))).resolve(strict=False)
            if observed != expected.resolve(strict=False):
                raise SetupError(f"install state {field} does not match the exact legacy path")
        expected_backups = {
            "legacy_skill_backup": backup_root / "legacy-skill",
            "legacy_agent_backup": backup_root / "legacy-agent",
        }
        for field, expected in expected_backups.items():
            value = migration.get(field)
            if value is None:
                continue
            observed = Path(str(value)).resolve(strict=False)
            assert_safe_target(observed, backup_root)
            if observed != expected.resolve(strict=False):
                raise SetupError(f"install state {field} does not match the exact backup path")
    return backup_root, normalized_previous


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
        else:
            current_hash = digest(target)
            if current_hash == source_hash:
                action = "unchanged"
            elif tracked.get(target_key) == current_hash:
                action = "replace-managed"
            else:
                action = "conflict"
                conflicts.append(f"{asset['kind']}:{asset['relative']}")
        operations.append(
            {
                "kind": asset["kind"],
                "relative": asset["relative"],
                "action": action,
                "source_hash": source_hash,
                "target": target_key,
            }
        )
    # A legacy user-level skill is never silently shadowed or removed by the
    # ordinary lifecycle; only explicit migrate may retire this exact path.
    legacy_skill = codex / OLD_SKILL_RELATIVE
    if legacy_skill.exists():
        conflicts.append("legacy:" + str(legacy_skill))
    return {
        "schema_version": STATE_SCHEMA,
        "mode": "update" if require_installed else "install",
        "source_fingerprint": source_fingerprint(assets),
        "operations": operations,
        "conflicts": conflicts,
        "safe_to_apply": not conflicts,
        "writes_performed": False,
    }


def migrate(codex_home: Path, skills_home: Path, plan_fingerprint: str) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    existing_state_path = state_path(codex)
    existing_state = existing_state_path.read_bytes() if existing_state_path.exists() else None
    prior_state = load_state(codex)
    if prior_state and prior_state.get("status") == "installed":
        raise SetupError("migrate refuses an existing managed installation; use update")
    plan = migration_plan(codex, skills)
    if not plan.get("safe_to_apply"):
        raise SetupError(f"refusing conflicted migration: {plan['conflicts']}")
    if plan.get("plan_fingerprint") != plan_fingerprint:
        raise SetupError("migration plan fingerprint is stale or incorrect")
    assets = managed_assets(codex, skills)
    operation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup_root = codex / "sol-luna-backups" / operation_id
    previous: dict[str, str | None] = {}
    old_skill = codex / OLD_SKILL_RELATIVE
    old_agent = codex / "agents" / OLD_AGENT_NAME
    written: list[Path] = []
    retired: list[Path] = []
    legacy_skill_backed = old_skill.exists()
    legacy_agent_backed = old_agent.exists()
    try:
        if old_skill.exists():
            shutil.copytree(old_skill, backup_root / "legacy-skill")
        if old_agent.exists():
            (backup_root / "legacy-agent").parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_agent, backup_root / "legacy-agent")
        for asset in assets:
            target = asset["target"]
            key = str(target)
            if target.exists():
                previous[key] = str(backup_root / asset["kind"] / asset["relative"])
                Path(previous[key]).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, Path(previous[key]))
            else:
                previous[key] = None
            if not target.exists() or digest(target) != digest(asset["source"]):
                atomic_write(target, asset["source"].read_bytes())
                written.append(target)
        # Narrow, exact legacy paths only; no shell deletion is involved.
        if old_skill.exists():
            shutil.rmtree(old_skill)
            retired.append(old_skill)
        # luna-worker.toml is also a current managed target in this repository:
        # it is replaced above and must remain present as the new agent.
        managed_agent_targets = {a["target"] for a in assets if a["kind"] == "agent"}
        if old_agent.exists() and old_agent not in managed_agent_targets:
            old_agent.unlink()
            retired.append(old_agent)
        state = {"schema_version": STATE_SCHEMA, "status": "installed", "operation_id": operation_id,
                 "installed_at": datetime.now(timezone.utc).isoformat(),
                 "source_fingerprint": source_fingerprint(assets), "codex_home": str(codex),
                 "skills_home": str(skills), "installed": {str(a["target"]): digest(a["source"]) for a in assets},
                 "previous": previous, "backup_root": str(backup_root),
                 "migration": {"legacy_skill": str(old_skill), "legacy_agent": str(old_agent),
                                "legacy_skill_backup": str(backup_root / "legacy-skill") if (backup_root / "legacy-skill").exists() else None,
                                "legacy_agent_backup": str(backup_root / "legacy-agent") if (backup_root / "legacy-agent").exists() else None}}
        atomic_write(state_path(codex), (json.dumps(state, indent=2, sort_keys=True) + "\n").encode())
        result = doctor(codex)
        if result["status"] != "healthy":
            raise SetupError("post-migration Doctor did not verify the managed state")
    except Exception:
        for target in reversed(written):
            backup = previous.get(str(target))
            if backup and Path(backup).exists(): atomic_write(target, Path(backup).read_bytes())
            elif target.exists():
                target.unlink()
                root = codex if target.is_relative_to(codex) else skills
                remove_empty_parents(target.parent, root)
        # Restore the exact legacy trees if any later write, state update, or
        # health check fails. This keeps migration transactional.
        if legacy_skill_backed and not old_skill.exists() and (backup_root / "legacy-skill").exists():
            shutil.copytree(backup_root / "legacy-skill", old_skill)
        if legacy_agent_backed and not old_agent.exists() and (backup_root / "legacy-agent").exists():
            old_agent.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(old_agent, (backup_root / "legacy-agent").read_bytes())
        if existing_state is not None:
            atomic_write(existing_state_path, existing_state)
        elif existing_state_path.exists():
            existing_state_path.unlink()
        raise
    return {"status": "migrated", "operation_id": operation_id, "doctor": result, "plan_fingerprint": plan_fingerprint}


def apply(codex_home: Path, skills_home: Path, *, update: bool = False) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    prior_state = load_state(codex)
    validated_backup: Path | None = None
    validated_previous: dict[str, Path | None] = {}
    if update and prior_state:
        validated_backup, validated_previous = validate_state_for_write(codex, skills, prior_state)
    plan = preview(codex, skills, require_installed=update)
    if plan["conflicts"]:
        raise SetupError(f"refusing conflicted setup: {plan['conflicts']}")
    assets = managed_assets(codex, skills)
    operation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup_root = (
        validated_backup
        if update and validated_backup
        else codex / "sol-luna-backups" / operation_id
    )
    previous: dict[str, str | None] = (
        {key: str(value) if value is not None else None for key, value in validated_previous.items()}
        if update and prior_state
        else {}
    )
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
        installed = {str(asset["target"]): digest(asset["source"]) for asset in assets}
        state = {
            "schema_version": STATE_SCHEMA,
            "status": "installed",
            "operation_id": operation_id,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "source_fingerprint": source_fingerprint(assets),
            "codex_home": str(codex),
            "skills_home": str(skills),
            "installed": installed,
            "previous": previous,
            "backup_root": str(backup_root),
        }
        atomic_write(state_path(codex), (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except Exception:
        for target in reversed(written):
            backup_value = previous.get(str(target))
            if backup_value and Path(backup_value).exists():
                atomic_write(target, Path(backup_value).read_bytes())
            elif target.exists():
                target.unlink()
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
    missing: list[str] = []
    drifted: list[str] = []
    duplicate = codex / OLD_SKILL_RELATIVE
    if duplicate.exists():
        drifted.append("duplicate legacy skill")
    for target_value, expected_hash in state.get("installed", {}).items():
        target = Path(target_value)
        try:
            target.resolve(strict=False).relative_to(codex)
        except ValueError:
            skills = Path(state.get("skills_home", "")).resolve(strict=False)
            try:
                target.resolve(strict=False).relative_to(skills)
            except ValueError:
                drifted.append("managed target escaped recorded roots")
                continue
        if not target.exists():
            missing.append(target.name)
        elif is_link_like(target) or digest(target) != expected_hash:
            drifted.append(target.name)
    status = "healthy" if not missing and not drifted else "drifted"
    return {
        "status": status,
        "source_fingerprint": state.get("source_fingerprint"),
        "checked": len(state.get("installed", {})),
        "missing": sorted(missing),
        "drifted": sorted(drifted),
        "operation_id": state.get("operation_id"),
    }


def rollback(codex_home: Path, skills_home: Path) -> dict[str, Any]:
    codex, skills = validate_roots(codex_home, skills_home)
    state = load_state(codex)
    if not state or state.get("status") != "installed":
        raise SetupError("rollback requires a valid installed state")
    _, previous = validate_state_for_write(codex, skills, state)
    conflicts = []
    for target_value, installed_hash in state.get("installed", {}).items():
        target = Path(target_value)
        if target.exists() and (is_link_like(target) or digest(target) != installed_hash):
            conflicts.append(target.name)
    if conflicts:
        raise SetupError(f"rollback refuses user-modified managed files: {sorted(conflicts)}")
    migration = state.get("migration")
    if not isinstance(migration, Mapping):
        migration = {}
    legacy_skill = Path(str(migration.get("legacy_skill", codex / OLD_SKILL_RELATIVE)))
    legacy_agent = Path(str(migration.get("legacy_agent", codex / "agents" / OLD_AGENT_NAME)))
    if migration:
        managed_targets = {Path(value) for value in state.get("installed", {})}
        for legacy in (legacy_skill, legacy_agent):
            if legacy.exists() and legacy not in managed_targets:
                raise SetupError("rollback refuses legacy path conflict")
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
    skill_backup = migration.get("legacy_skill_backup")
    agent_backup = migration.get("legacy_agent_backup")
    if skill_backup:
        shutil.copytree(Path(skill_backup), legacy_skill)
        restored += 1
    if agent_backup:
        legacy_agent.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(agent_backup), legacy_agent)
        restored += 1
    state["status"] = "rolled-back"
    state["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(state_path(codex), (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {"status": "rolled-back", "restored": restored, "removed": removed}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage a bounded Sol-Luna installation lifecycle.")
    result.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    result.add_argument("--skills-home", type=Path, default=Path.home() / ".agents" / "skills")
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
    try:
        if args.command == "preview":
            output = preview(args.codex_home, args.skills_home)
        elif args.command == "migration-preview":
            output = migration_plan(args.codex_home, args.skills_home)
        elif args.command == "doctor":
            output = doctor(args.codex_home)
        elif not args.confirm:
            raise SetupError(f"{args.command} requires --confirm after reviewing preview")
        elif args.command == "install":
            output = apply(args.codex_home, args.skills_home)
        elif args.command == "migrate":
            output = migrate(args.codex_home, args.skills_home, args.plan_fingerprint)
        elif args.command == "update":
            output = apply(args.codex_home, args.skills_home, update=True)
        else:
            output = rollback(args.codex_home, args.skills_home)
    except (OSError, SetupError) as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
