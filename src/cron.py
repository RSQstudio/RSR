"""Cron jobs for Skill Router — background maintenance and reporting.

Jobs:
  - sweep   (every 24h): Find new skills in active/ → move to vault
  - report  (weekly):    Skill usage report — activation counts, tokens saved, dead skills

Usage:
  python -m src.cron sweep    # Run the 24h sweep
  python -m src.cron report   # Run the weekly report
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Support both `python -m src.cron` and direct execution
try:
    from . import agent_detector
    from .indexer import build_index
    from .vault_manager import get_active_skills, get_vault_skills
except ImportError:
    import agent_detector  # type: ignore[no-redef]
    from indexer import build_index  # type: ignore[no-redef]
    from vault_manager import (  # type: ignore[no-redef]
        get_active_skills,
        get_vault_skills,
    )


# ── Paths ─────────────────────────────────────────────────

def _config_file() -> Path:
    config_dir = Path("~/.config/skill-router").expanduser()
    for name in ("config.json", "config.yaml"):
        candidate = config_dir / name
        if candidate.exists():
            return candidate
    for name in ("config.json", "config.yaml"):
        candidate = Path(name)
        if candidate.exists():
            return candidate
    return config_dir / "config.json"


def _load_config() -> dict[str, Any]:
    if _config_file().suffix in (".yaml", ".yml"):
        try:
            import yaml
            with open(_config_file()) as f:
                return yaml.safe_load(f)
        except ImportError:
            pass
    if _config_file().exists():
        with open(_config_file()) as f:
            return json.load(f)
    return {"paths": {"vault": "auto", "active": "auto", "index_cache": "~/.cache/skill-router/index.json"}}


def _vault_path(config: dict[str, Any]) -> Path:
    raw = config.get("paths", {}).get("vault", "auto")
    if raw == "auto":
        return agent_detector.resolve_vault_dir()
    return Path(raw).expanduser()


def _active_path(config: dict[str, Any]) -> Path:
    raw = config.get("paths", {}).get("active", "auto")
    if raw == "auto":
        return agent_detector.resolve_skills_dir()
    return Path(raw).expanduser()


def _usage_log_path() -> Path:
    return Path("~/.cache/skill-router/usage.jsonl").expanduser()


# ── Sweep: auto-vault new skills ──────────────────────────

def sweep(config: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Scan active/ for newly added real skills and move them to vault.

    This runs every 24h via cron. It finds any SKILL.md folders that were added
    to active/ directly (not via symlink) and moves them into vault/_inbox/.
    Then rebuilds the index so they're searchable.
    """
    if config is None:
        config = _load_config()

    vault = _vault_path(config)
    active = _active_path(config)
    cache = Path(config.get("paths", {}).get("index_cache", "~/.cache/skill-router/index.json")).expanduser()
    result: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat(), "action": "sweep", "found": 0, "moved": [], "errors": []}

    if not active.is_dir():
        result["errors"].append(f"Active dir not found: {active}")
        return result

    # Real skills named in always_keep are user-selected persistent skills.
    # They remain directories in active/ and must never be swept into the vault.
    always_keep = set(config.get("always_keep", []))
    inbox = vault / "_inbox"

    for entry in sorted(active.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.is_symlink():
            continue  # Router-managed, skip

        skill_md = entry / "SKILL.md"
        if not skill_md.is_file() or entry.name in always_keep:
            continue

        result["found"] += 1
        dst = inbox / entry.name

        if dst.exists():
            result["errors"].append(f"Already in vault: {entry.name}")
            continue

        if dry_run:
            result["moved"].append(f"[DRY RUN] {entry.name}")
        else:
            shutil.move(str(entry), str(dst))
            result["moved"].append(entry.name)

    # Rebuild index if anything moved
    if result["moved"] and not dry_run:
        inbox.mkdir(parents=True, exist_ok=True)
        index = build_index(vault, cache)
        result["index"] = {"skills": index["total_skills"], "fields": len(index["fields"])}

    return result


# ── Usage tracking ────────────────────────────────────────

def log_usage(action: str, details: dict[str, Any] | None = None) -> None:
    """Log a router action to the usage log (JSON lines)."""
    log_path = _usage_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
    }
    if details:
        entry["details"] = details

    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _read_usage(days: int = 7) -> list[dict[str, Any]]:
    """Read usage log from the last N days."""
    log_path = _usage_log_path()
    if not log_path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries: list[dict[str, Any]] = []

    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
                if ts >= cutoff:
                    entries.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    return entries


# ── Weekly report ─────────────────────────────────────────

def report(config: dict[str, Any] | None = None, days: int = 7) -> str:
    """Generate a weekly usage report.

    Shows:
    - Skills activated/deactivated counts
    - Which skills were used most
    - Which skills were never touched
    - Estimated tokens saved vs. loading all 600
    - Vault size and growth
    """
    if config is None:
        config = _load_config()

    entries = _read_usage(days)
    vault = _vault_path(config)
    active = _active_path(config)

    # Aggregate stats
    activations: dict[str, int] = {}
    deactivations: dict[str, int] = {}
    reconciles = 0

    for entry in entries:
        action = entry.get("action", "")
        details = entry.get("details", {})

        if action == "reconcile":
            reconciles += 1
            for skill_name in details.get("activated", []):
                activations[skill_name] = activations.get(skill_name, 0) + 1
            for skill_name in details.get("deactivated", []):
                deactivations[skill_name] = deactivations.get(skill_name, 0) + 1
        elif action == "route":
            reconciles += 1
        elif action == "activate":
            for skill_name in details.get("activated", []):
                activations[skill_name] = activations.get(skill_name, 0) + 1

    # Current state
    vault_skills = get_vault_skills(vault)
    active_skills = get_active_skills(active)
    always_keep = config.get("always_keep", [])

    # Stats
    total_vault = len(vault_skills)
    total_active = len(active_skills)
    overhead_pct = total_active / max(total_vault, 1) * 100

    most_activated = sorted(activations.items(), key=lambda x: -x[1])[:10]
    never_used = [s for s in vault_skills if s not in activations and s not in always_keep][:10]

    # Token savings estimate
    avg_skill_tokens = 100  # ~100 tokens per skill description
    tokens_saved = (total_vault - total_active) * avg_skill_tokens
    total_skills_loaded_across_week = sum(activations.values())
    tokens_saved_cumulative = total_skills_loaded_across_week * avg_skill_tokens

    # Build report
    lines = []
    lines.append("═══════════════════════════════════════════")
    lines.append("  SKILL ROUTER — Weekly Report")
    lines.append(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d')}  |  Last {days} days")
    lines.append("═══════════════════════════════════════════")
    lines.append("")
    lines.append("── VAULT ──")
    lines.append(f"  Total skills:       {total_vault}")
    lines.append(f"  Active right now:   {total_active} ({overhead_pct:.0f}%)")
    lines.append(f"  Always-on:          {len(always_keep)}")
    lines.append("")
    lines.append("── USAGE ──")
    lines.append(f"  Reconciled tasks:   {reconciles}")
    lines.append(f"  Total activations:  {sum(activations.values())}")
    lines.append(f"  Unique skills used: {len(activations)}")
    lines.append("")
    lines.append("── TOP 10 SKILLS ──")
    if most_activated:
        for name, count in most_activated:
            bar = "█" * min(count, 30)
            lines.append(f"  {count:>3}  {bar:<30}  {name}")
    else:
        lines.append("  (no usage data yet)")
    lines.append("")
    lines.append("── NEVER USED (Top 10) ──")
    if never_used:
        for name in never_used:
            lines.append(f"  💤  {name}")
    else:
        lines.append("  (all skills have been used)")
    lines.append("")
    lines.append("── TOKEN SAVINGS ──")
    lines.append(f"  Per turn (avg):     {tokens_saved:,} tokens saved")
    lines.append(f"  Cumulative week:    {tokens_saved_cumulative:,} tokens not loaded")
    lines.append(f"  Equivalent to:      ~{tokens_saved_cumulative * 0.000001:.2f}¢ to $0.00 (model-dependent)")
    lines.append("")
    lines.append("── HEALTH ──")
    if total_active > 20:
        lines.append(f"  ⚠️  {total_active} active skills — consider reducing max_active_skills in config")
    if reconciles == 0:
        lines.append(f"  ⚠️  No reconciles in {days} days — is the router running?")
    if len(never_used) > total_vault * 0.5:
        lines.append(f"  ℹ️  {len(never_used)} unused skills — could be pruned or moved to cold storage")
    if not lines[-1].startswith("  ⚠️"):
        lines.append("  ✅ Router is healthy")
    lines.append("")
    lines.append("═══════════════════════════════════════════")

    return "\n".join(lines)


# ── Logging integration ───────────────────────────────────

def patch_vault_manager_for_logging() -> None:
    """Monkey-patch vault_manager.reconcile to auto-log usage.

    Call this once at module load if you want automatic usage tracking.
    """
    import vault_manager as vm
    _original_reconcile = vm.reconcile

    def _logged_reconcile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = _original_reconcile(*args, **kwargs)
        log_usage("reconcile", {
            "activated": result.get("activated", []),
            "deactivated": result.get("deactivated", []),
            "unchanged": len(result.get("unchanged", [])),
        })
        return result

    vm.reconcile = _logged_reconcile  # type: ignore[assignment]


# ── Cron job setup ────────────────────────────────────────

def setup_cron(config: dict[str, Any] | None = None, dry_run: bool = False) -> None:
    """Install cron jobs into the user's crontab.

    - 24h sweep: runs daily at 03:00 UTC — scans for new skills, moves to vault
    - Weekly report: runs Monday at 08:00 UTC — usage analytics
    """
    # This command is reached only through explicit setup; argv is fixed and shell is disabled.
    import subprocess  # nosec B404
    import sys

    script = Path(__file__).resolve()
    python = sys.executable

    try:
        result = subprocess.run(  # nosec B603, B607
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
        current = result.stdout.strip()
    except OSError:
        current = ""

    if "# skill-router-start" in current:
        print("✅ Cron jobs already installed.")
        print("   Run `crontab -e` to edit manually.")
        return

    new_entries = f"""
# skill-router-start — managed by Skill Router
# 24h sweep: auto-vault new skills (daily at 03:00 UTC)
0 3 * * * {python} {script} sweep >> ~/.cache/skill-router/cron.log 2>&1

# Weekly report: usage analytics (Monday at 08:00 UTC)
0 8 * * 1 {python} {script} report >> ~/.cache/skill-router/cron.log 2>&1
# skill-router-end
"""

    new_cron = (current.rstrip() + "\n" + new_entries).strip() + "\n"

    if dry_run:
        print("[DRY RUN] Would add to crontab:")
        print(new_entries)
        return

    proc = subprocess.run(  # nosec B603, B607
        ["crontab"], input=new_cron, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        print(f"⚠️  Failed: {proc.stderr}")
        print("Add manually with `crontab -e`:")
        print(new_entries)
        return

    result = subprocess.run(  # nosec B603, B607
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    if "skill-router" in result.stdout:
        print("✅ Cron jobs installed:")
        print("   • Daily sweep   (03:00 UTC) — auto-vault new skills")
        print("   • Weekly report (Mon 08:00 UTC) — usage analytics")
    else:
        print("⚠️  Verification failed. Check with `crontab -l`")


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Skill Router cron jobs")
    sub = parser.add_subparsers(dest="cmd")

    sweep_p = sub.add_parser("sweep", help="24h sweep: find new skills → vault")
    sweep_p.add_argument("--dry-run", action="store_true")

    report_p = sub.add_parser("report", help="Weekly usage report")
    report_p.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")

    args = parser.parse_args()

    if args.cmd == "sweep":
        result = sweep(dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    elif args.cmd == "report":
        print(report(days=args.days))
    else:
        parser.print_help()