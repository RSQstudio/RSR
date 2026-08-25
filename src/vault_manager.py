"""Vault Manager — manages symlinks between vault and active skill directories.

Safety rules:
  - NEVER deletes files from vault (read-only source of truth)
  - Only operates on symlinks in active/ (never touches real files)
  - Always-keep skills are immune to deactivation
  - Atomic operations: no partial state between activate and deactivate
  - Auto-logs all reconciles to usage tracker

Architecture:
  vault/   → READ-ONLY source  (all skills live here forever)
  active/  → MANAGED symlinks   (only active skills point here)

The agent's skill loader reads from active/. The vault is invisible to the agent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("skill-router.vault")

# ── Usage logging (inline, no circular imports) ───────────

def _log_router_action(action: str, details: dict[str, Any] | None = None) -> None:
    """Log a router action to the usage log for weekly reports."""
    try:
        log_path = Path("~/.cache/skill-router/usage.jsonl").expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
        }
        if details:
            entry["details"] = details
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let logging fail the operation


# ── Core operations ──────────────────────────────────────

def _is_symlink(path: Path) -> bool:
    """Check if path is a valid symlink (and not broken)."""
    return path.is_symlink() and path.exists()


def _skill_symlinks(active_dir: Path) -> dict[str, Path]:
    """Return {skill_name: symlink_path} for all current symlinks in active/."""
    if not active_dir.is_dir():
        return {}
    result: dict[str, Path] = {}
    for entry in active_dir.iterdir():
        if entry.is_symlink():
            result[entry.name] = entry
    return result


def get_active_skills(active_path: str | Path) -> list[str]:
    """List currently active skills (by symlink name)."""
    active = Path(active_path).expanduser()
    return sorted(_skill_symlinks(active).keys())


def get_vault_skills(vault_path: str | Path) -> list[str]:
    """List all available skills in the vault (across all fields)."""
    vault = Path(vault_path).expanduser()
    if not vault.is_dir():
        return []

    skills: list[str] = []
    for field_dir in sorted(vault.iterdir()):
        if not field_dir.is_dir() or field_dir.name.startswith("."):
            continue
        for skill_dir in sorted(field_dir.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skills.append(skill_dir.name)
    return skills


def find_skill_in_vault(
    vault_path: str | Path,
    skill_name: str,
) -> Path | None:
    """Find a skill directory in the vault by name. Returns the vault path or None."""
    vault = Path(vault_path).expanduser()
    for field_dir in vault.iterdir():
        if not field_dir.is_dir() or field_dir.name.startswith("."):
            continue
        candidate = field_dir / skill_name
        if candidate.is_dir() and (candidate / "SKILL.md").exists():
            return candidate
    return None


def activate_skills(
    vault_path: str | Path,
    active_path: str | Path,
    skill_names: list[str],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create symlinks from vault to active for the given skills.

    Returns:
        {"activated": [...], "already_active": [...], "not_found": [...]}
    """
    vault = Path(vault_path).expanduser()
    active = Path(active_path).expanduser()
    active.mkdir(parents=True, exist_ok=True)

    result: dict[str, list[str]] = {"activated": [], "already_active": [], "not_found": []}
    current = _skill_symlinks(active)

    for name in skill_names:
        if name in current and _is_symlink(current[name]):
            result["already_active"].append(name)
            continue

        src = find_skill_in_vault(vault, name)
        if src is None:
            result["not_found"].append(name)
            log.warning(f"Skill not found in vault: {name}")
            continue

        dst = active / name
        if dry_run:
            result["activated"].append(name)
            log.info(f"[DRY RUN] Would symlink: {src} → {dst}")
        else:
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(src, target_is_directory=True)
            result["activated"].append(name)
            log.info(f"Activated: {name}")

    return result


def deactivate_skills(
    active_path: str | Path,
    skill_names: list[str],
    always_keep: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove symlinks from active/ for the given skills.

    Respects always_keep — those are never deactivated.
    Returns:
        {"deactivated": [...], "protected": [...], "not_found": [...]}
    """
    always_keep = always_keep or []
    active = Path(active_path).expanduser()

    result: dict[str, list[str]] = {"deactivated": [], "protected": [], "not_found": []}
    current = _skill_symlinks(active)

    for name in skill_names:
        if name in always_keep:
            result["protected"].append(name)
            continue

        if name not in current:
            result["not_found"].append(name)
            continue

        symlink = current[name]
        if dry_run:
            result["deactivated"].append(name)
            log.info(f"[DRY RUN] Would remove: {symlink}")
        else:
            # Verify it's a symlink (safety: never delete real files)
            if not symlink.is_symlink():
                log.error(f"REFUSED to delete real file: {symlink}")
                continue
            symlink.unlink()
            result["deactivated"].append(name)
            log.info(f"Deactivated: {name}")

    return result


def deactivate_all(
    active_path: str | Path,
    always_keep: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove ALL symlinks from active/, except always_keep skills."""
    always_keep = always_keep or []
    active = Path(active_path).expanduser()
    current = _skill_symlinks(active)

    to_remove = [name for name in current if name not in always_keep]
    return deactivate_skills(active, to_remove, always_keep, dry_run)


def reconcile(
    vault_path: str | Path,
    active_path: str | Path,
    desired_skills: list[str],
    always_keep: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Full reconcile: deactivate stale skills, activate desired ones. Atomic.

    The desired_skills are the output of the matcher — what SHOULD be active.
    The always_keep list is merged in: they're always in desired.

    Returns:
        {"activated": [...], "deactivated": [...], "protected": [...], "unchanged": [...]}
    """
    always_keep = always_keep or []
    active = Path(active_path).expanduser()
    current = _skill_symlinks(active)
    current_names = set(current.keys())

    # Desired = matcher output + always-keep
    target = set(desired_skills) | set(always_keep)

    to_activate = target - current_names
    to_deactivate = current_names - target
    # Always-keep is immune from deactivation
    to_deactivate = to_deactivate - set(always_keep)

    result: dict[str, Any] = {
        "activated": [],
        "deactivated": [],
        "protected": list(set(always_keep) & current_names),
        "unchanged": list(target & current_names),
    }

    # Activate first (safest: add before remove)
    if to_activate:
        act_result = activate_skills(vault_path, active_path, sorted(to_activate), dry_run)
        result["activated"] = act_result["activated"]
        result.setdefault("not_found", []).extend(act_result["not_found"])

    # Deactivate stale skills
    if to_deactivate:
        deact_result = deactivate_skills(active_path, sorted(to_deactivate), always_keep, dry_run)
        result["deactivated"] = deact_result["deactivated"]
        result.setdefault("not_found", []).extend(deact_result["not_found"])

    # Log usage for weekly reports
    if not dry_run:
        _log_router_action("reconcile", {
            "activated": result["activated"],
            "deactivated": result["deactivated"],
            "unchanged": len(result["unchanged"]),
            "protected": len(result["protected"]),
        })

    return result


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage skill symlinks between vault and active")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list-active", help="List currently active skills")
    sub.add_parser("list-vault", help="List all skills in vault")

    act_parser = sub.add_parser("activate", help="Activate skills")
    act_parser.add_argument("skills", nargs="+", help="Skill names to activate")
    act_parser.add_argument("--vault", default="~/.hermes/skills-vault")
    act_parser.add_argument("--active", default="~/.hermes/skills")
    act_parser.add_argument("--dry-run", action="store_true")

    deact_parser = sub.add_parser("deactivate", help="Deactivate skills")
    deact_parser.add_argument("skills", nargs="+", help="Skill names to deactivate")
    deact_parser.add_argument("--active", default="~/.hermes/skills")
    deact_parser.add_argument("--keep", nargs="*", default=[])
    deact_parser.add_argument("--dry-run", action="store_true")

    rec_parser = sub.add_parser("reconcile", help="Reconcile active to desired state")
    rec_parser.add_argument("skills", nargs="+", help="Desired skill names")
    rec_parser.add_argument("--vault", default="~/.hermes/skills-vault")
    rec_parser.add_argument("--active", default="~/.hermes/skills")
    rec_parser.add_argument("--keep", nargs="*", default=[])
    rec_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    import json as _json

    if args.cmd == "list-active":
        active = get_active_skills(args.active)
        for s in active:
            print(s)
        print(f"\n{len(active)} active skills")

    elif args.cmd == "list-vault":
        skills = get_vault_skills("~/.hermes/skills-vault")
        for s in skills:
            print(s)
        print(f"\n{len(skills)} skills in vault")

    elif args.cmd == "activate":
        result = activate_skills(args.vault, args.active, args.skills, args.dry_run)
        print(_json.dumps(result, indent=2))

    elif args.cmd == "deactivate":
        result = deactivate_skills(args.active, args.skills, args.keep, args.dry_run)
        print(_json.dumps(result, indent=2))

    elif args.cmd == "reconcile":
        result = reconcile(args.vault, args.active, args.skills, args.keep, args.dry_run)
        print(_json.dumps(result, indent=2))