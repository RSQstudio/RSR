"""Vault Manager — manages symlinks between vault and active skill directories.

Safety rules:
  - NEVER deletes files from vault (read-only source of truth)
  - Never replaces real files or unmanaged symlinks in active/
  - Always-keep skills are immune to deactivation
  - Activates requested skills before removing stale router-managed links
  - Auto-logs all reconciles to usage tracker

Architecture:
  vault/   → READ-ONLY source  (all routed skills live here)
  active/  → router-managed symlinks plus preserved real always-on skills

The agent's skill loader reads from active/. The vault is invisible to the agent.
"""

from __future__ import annotations

import json
import logging
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
    except OSError:
        log.debug("Could not write usage log", exc_info=True)


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


def _real_skill_dirs(active_dir: Path) -> dict[str, Path]:
    """Return unmanaged real skill directories currently present in active/."""
    if not active_dir.is_dir():
        return {}
    return {
        entry.name: entry
        for entry in active_dir.iterdir()
        if not entry.is_symlink() and entry.is_dir() and (entry / "SKILL.md").is_file()
    }


def get_active_skills(active_path: str | Path) -> list[str]:
    """List all valid skills presently loaded from the active directory."""
    active = Path(active_path).expanduser()
    return sorted(set(_skill_symlinks(active)) | set(_real_skill_dirs(active)))


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


def _is_valid_skill_name(name: str) -> bool:
    """Accept only one safe directory component as a skill name."""
    return bool(name) and name not in {".", ".."} and Path(name).name == name and "\x00" not in name


def find_skill_in_vault(
    vault_path: str | Path,
    skill_name: str,
) -> Path | None:
    """Find a skill directory in the vault by name. Returns the vault path or None."""
    vault = Path(vault_path).expanduser()
    if not _is_valid_skill_name(skill_name) or not vault.is_dir():
        return None
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

    result: dict[str, list[str]] = {
        "activated": [],
        "already_active": [],
        "not_found": [],
        "invalid": [],
        "conflicts": [],
    }

    for name in skill_names:
        if not _is_valid_skill_name(name):
            result["invalid"].append(name)
            log.error("Refused unsafe skill name: %r", name)
            continue

        src = find_skill_in_vault(vault, name)
        if src is None:
            result["not_found"].append(name)
            log.warning("Skill not found in vault: %s", name)
            continue

        dst = active / name
        if dst.is_symlink():
            try:
                if dst.resolve(strict=True) == src.resolve(strict=True):
                    result["already_active"].append(name)
                    continue
            except OSError:
                pass
            result["conflicts"].append(name)
            log.error("Refused to replace existing symlink: %s", dst)
            continue
        if dst.exists():
            result["conflicts"].append(name)
            log.error("Refused to replace real active path: %s", dst)
            continue

        if dry_run:
            result["activated"].append(name)
            log.info("[DRY RUN] Would symlink: %s → %s", src, dst)
        else:
            dst.symlink_to(src, target_is_directory=True)
            result["activated"].append(name)
            log.info("Activated: %s", name)

    return result


def _is_managed_symlink(path: Path, vault_dir: Path) -> bool:
    """Return whether a live skill symlink points to a skill inside this vault."""
    try:
        target = path.resolve(strict=True)
        vault = vault_dir.resolve(strict=True)
    except OSError:
        return False
    return target.is_relative_to(vault) and (target / "SKILL.md").is_file()


def deactivate_skills(
    active_path: str | Path,
    skill_names: list[str],
    always_keep: list[str] | None = None,
    dry_run: bool = False,
    vault_path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove symlinks from active/ for the given skills.

    Respects always_keep — those are never deactivated.
    Returns:
        {"deactivated": [...], "protected": [...], "not_found": [...]}
    """
    always_keep = always_keep or []
    active = Path(active_path).expanduser()
    vault = Path(vault_path).expanduser() if vault_path is not None else None

    result: dict[str, list[str]] = {
        "deactivated": [],
        "protected": [],
        "not_found": [],
        "unmanaged": [],
    }
    current = _skill_symlinks(active)

    for name in skill_names:
        if name in always_keep:
            result["protected"].append(name)
            continue

        if name not in current:
            result["not_found"].append(name)
            continue

        symlink = current[name]
        if vault is None or not _is_managed_symlink(symlink, vault):
            result["unmanaged"].append(name)
            log.error("Refused to remove unmanaged symlink: %s", symlink)
            continue
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
    vault_path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove all router-managed symlinks from active/, except always_keep skills."""
    always_keep = always_keep or []
    active = Path(active_path).expanduser()
    current = _skill_symlinks(active)

    to_remove = [name for name in current if name not in always_keep]
    return deactivate_skills(active, to_remove, always_keep, dry_run, vault_path)


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
    real_active = _real_skill_dirs(active)
    current_names = set(current)
    loaded_names = current_names | set(real_active)

    # Desired = matcher output + always-keep
    target = set(desired_skills) | set(always_keep)

    # Real skill folders are user-managed until the configured sweep archives them.
    # Never replace or deactivate them during reconciliation.
    to_activate = target - loaded_names
    to_deactivate = current_names - target
    # Always-keep is immune from deactivation
    to_deactivate = to_deactivate - set(always_keep)

    result: dict[str, Any] = {
        "activated": [],
        "deactivated": [],
        "protected": sorted(set(always_keep) & loaded_names),
        "unchanged": sorted(target & loaded_names),
    }

    # Activate first (safest: add before remove)
    if to_activate:
        act_result = activate_skills(vault_path, active_path, sorted(to_activate), dry_run)
        result["activated"] = act_result["activated"]
        result.setdefault("not_found", []).extend(act_result["not_found"])

    # Deactivate stale skills
    if to_deactivate:
        deact_result = deactivate_skills(active_path, sorted(to_deactivate), always_keep, dry_run, vault_path)
        result["deactivated"] = deact_result["deactivated"]
        result.setdefault("not_found", []).extend(deact_result["not_found"])
        result.setdefault("unmanaged", []).extend(deact_result["unmanaged"])

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
    deact_parser.add_argument("--vault", default="~/.hermes/skills-vault")
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
        result = deactivate_skills(args.active, args.skills, args.keep, args.dry_run, args.vault)
        print(_json.dumps(result, indent=2))

    elif args.cmd == "reconcile":
        result = reconcile(args.vault, args.active, args.skills, args.keep, args.dry_run)
        print(_json.dumps(result, indent=2))