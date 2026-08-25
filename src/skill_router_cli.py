"""Skill Router — intelligent skill loading for AI coding agents.

Keep your agent fast. 600 skills in the vault, only 5-15 in active memory.

Commands:
  skill-router index              Build/rebuild skill index from vault
  skill-router route <message>    Match user intent → skills (no filesystem changes)
  skill-router activate <skills>  Activate specific skills (or "route" for auto)
  skill-router status             Show what's active, vault size, last index
  skill-router reconcile          Full cycle: index → route → activate → deactivate
  skill-router config             Validate and show current config

Examples:
  skill-router index
  skill-router route "write a cold email for enterprise sales"
  skill-router route --auto "debug the payment reconciliation module"
  skill-router status
  skill-router reconcile "build a financial model for our Q3 projections"
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

if __package__:
    from . import agent_detector
    from .cron import report, setup_cron, sweep
    from .indexer import build_index, load_index
    from .installer import run_install
    from .matcher import SkillMatcher
    from .vault_manager import (
        activate_skills,
        get_active_skills,
        get_vault_skills,
        reconcile,
    )
else:
    import agent_detector
    from cron import report, setup_cron, sweep
    from indexer import build_index, load_index
    from installer import run_install
    from matcher import SkillMatcher
    from vault_manager import (
        activate_skills,
        get_active_skills,
        get_vault_skills,
        reconcile,
    )

# ── Config loading ───────────────────────────────────────

DEFAULT_CONFIG = {
    "paths": {
        "vault": "auto",          # "auto" → resolved by agent_detector
        "active": "auto",         # "auto" → resolved by agent_detector
        "index_cache": "~/.cache/skill-router/index.json",
    },
    "matching": {
        "strategy": "keyword",
        "max_active_skills": 15,
        "min_confidence": 0.3,
    },
    "always_keep": [],
}


def _merge_config(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge a user config over defaults without sharing mutable nested values."""
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load JSON or YAML configuration and fill omitted supported defaults."""
    search_paths = [
        Path(config_path) if config_path else None,
        Path("~/.config/skill-router/config.json").expanduser(),
        Path("~/.config/skill-router/config.yaml").expanduser(),
        Path("config.json"),
        Path("config.yaml"),
    ]

    for sp in search_paths:
        if not sp or not sp.exists():
            continue

        text = sp.read_text(encoding="utf-8")
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError(
                    f"YAML configuration requires PyYAML: {sp}. "
                    "Use JSON or install PyYAML."
                ) from exc
            loaded = yaml.safe_load(text)

        if not isinstance(loaded, dict):
            raise TypeError(f"Configuration root must be a mapping: {sp}")
        config = _merge_config(DEFAULT_CONFIG, loaded)
        if not isinstance(config.get("paths"), dict) or not isinstance(config.get("matching"), dict):
            raise TypeError(f"Configuration paths and matching sections must be mappings: {sp}")
        if not isinstance(config.get("always_keep"), list) or not all(isinstance(name, str) for name in config["always_keep"]):
            raise TypeError(f"Configuration always_keep must be a list of skill names: {sp}")
        return config

    return deepcopy(DEFAULT_CONFIG)


def _expand_path(path: str) -> Path:
    """Expand ~ and return absolute Path. 'auto' strings are resolved via agent_detector."""
    if path == "auto":
        return agent_detector.resolve_skills_dir()
    if path == "auto-vault":
        return agent_detector.resolve_vault_dir()
    return Path(path).expanduser().resolve()


def _resolve_vault(config: dict[str, Any]) -> Path:
    """Resolve vault path from config (handles 'auto')."""
    raw = config["paths"].get("vault", "auto")
    if raw == "auto":
        return agent_detector.resolve_vault_dir()
    return Path(raw).expanduser().resolve()


def _resolve_active(config: dict[str, Any]) -> Path:
    """Resolve active path from config (handles 'auto')."""
    raw = config["paths"].get("active", "auto")
    if raw == "auto":
        return agent_detector.resolve_skills_dir()
    return Path(raw).expanduser().resolve()


# ── Commands ─────────────────────────────────────────────

def cmd_index(config: dict[str, Any]) -> None:
    """Build skill index from vault."""

    vault = _resolve_vault(config)
    cache = _expand_path(config["paths"]["index_cache"])

    print(f"Indexing: {vault}")
    result = build_index(vault, cache)
    print(f"Done → {result['total_skills']} skills across {len(result['fields'])} fields")
    print(f"Index saved: {cache}")


def cmd_route(config: dict[str, Any], message: str, auto_activate: bool = False) -> None:
    """Match user intent to skills."""

    cache = _expand_path(config["paths"]["index_cache"])
    if not cache.exists():
        print("No index found. Run `skill-router index` first.")
        sys.exit(1)

    index = load_index(cache)
    strategy = config["matching"]["strategy"]
    min_conf = config["matching"]["min_confidence"]
    max_skills = config["matching"]["max_active_skills"]

    matcher = SkillMatcher(index, strategy=strategy, min_confidence=min_conf, max_results=max_skills)
    result = matcher.route(message)

    # Pretty output
    print(f"Intent: {result['intent_message']}")
    print(f"Top field: {result['top_field']}")
    print(f"Found in: {', '.join(result['fields_found'])}")
    print(f"Skills: {result['skill_count']}\n")

    for field, skills in result["recommendations"].items():
        print(f"  [{field}]")
        for s in skills:
            bar = "█" * int(s["score"] * 20) + "░" * (20 - int(s["score"] * 20))
            print(f"    {s['score']:.3f} {bar}  {s['name']}")

    if auto_activate:
        desired = [m["skill"] for m in result["all_matches"]]
        vault = _resolve_vault(config)
        active = _resolve_active(config)
        always_keep = config.get("always_keep", [])

        print(f"\n--- Reconciling: {len(desired)} desired skills ---")
        rec = reconcile(vault, active, desired, always_keep)
        print(f"Activated:   {len(rec['activated'])} {rec['activated']}")
        print(f"Deactivated: {len(rec['deactivated'])} {rec['deactivated']}")
        print(f"Protected:   {len(rec['protected'])} {rec['protected']}")
        print(f"Unchanged:   {len(rec['unchanged'])}")


def cmd_status(config: dict[str, Any]) -> None:
    """Show current router state."""

    vault = _resolve_vault(config)
    active = _resolve_active(config)
    cache = _expand_path(config["paths"]["index_cache"])

    active_skills = get_active_skills(active)
    vault_skills = get_vault_skills(vault)
    always_keep = config.get("always_keep", [])

    print("═══ Skill Router Status ═══\n")
    print(f"Vault:     {vault} → {len(vault_skills)} skills available")
    print(f"Active:    {active} → {len(active_skills)} skills loaded")
    print(f"Overhead:  {len(active_skills)}/{len(vault_skills)} ({len(active_skills)/max(len(vault_skills),1)*100:.0f}%)")
    print(f"Always keep: {len(always_keep)} → {', '.join(always_keep[:5])}" + ("..." if len(always_keep) > 5 else ""))

    if cache.exists():
        index = load_index(cache)
        age = index.get("built_at", "unknown")
        print(f"Index:     {cache} (built {age})")
        print(f"Fields:    {len(index.get('fields', {}))}")
    else:
        print("Index:     NOT BUILT — run `skill-router index`")

    # List active
    print("\nActive skills:")
    for s in sorted(active_skills):
        tag = " 🔒" if s in always_keep else ""
        print(f"  {s}{tag}")


def cmd_reconcile(config: dict[str, Any], message: str) -> None:
    """Full cycle: index → route → activate → deactivate."""
    cmd_route(config, message, auto_activate=True)


def cmd_activate(config: dict[str, Any], skills: list[str]) -> None:
    """Activate specific skills by name."""

    vault = _resolve_vault(config)
    active = _resolve_active(config)

    result = activate_skills(vault, active, skills)
    print(json.dumps(result, indent=2))


def cmd_install(config: dict[str, Any], non_interactive: bool = False) -> None:
    """Interactive install wizard — auto-detects agent, finds skills, lets user choose always-keep."""
    run_install(config, non_interactive=non_interactive)


def cmd_config(config: dict[str, Any]) -> None:
    """Print current config."""
    print(json.dumps(config, indent=2))

    # Validation
    vault = _resolve_vault(config)
    active = _resolve_active(config)

    errors = []
    if not vault.is_dir():
        errors.append(f"Vault not found: {vault}")
    if not active.is_dir():
        errors.append(f"Active dir not found: {active}")

    if errors:
        print("\n⚠️  Config errors:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("\n✅ Config valid")


def cmd_cron(config: dict[str, Any], cron_cmd: str, days: int = 7, dry_run: bool = False) -> None:
    """Cron jobs: sweep, report, setup."""

    if cron_cmd == "sweep":
        result = sweep(config, dry_run=dry_run)
        import json as _json
        print(_json.dumps(result, indent=2))
    elif cron_cmd == "report":
        print(report(config, days=days))
    elif cron_cmd == "setup":
        setup_cron(config, dry_run=dry_run)
    else:
        print("Usage: skill-router cron {sweep|report|setup}")


# ── CLI ──────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skill Router — intelligent skill loading for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  skill-router install
  skill-router index
  skill-router route "write a cold email"
  skill-router route --auto "debug the payment module"
  skill-router status
  skill-router reconcile "build a financial model"
  skill-router activate skill-a skill-b
  skill-router config
""",
    )
    parser.add_argument("--config", default=None, help="Path to JSON or YAML configuration file")

    sub = parser.add_subparsers(dest="command")

    install_parser = sub.add_parser("install", help="Interactive setup wizard")
    install_parser.add_argument("--yes", action="store_true", help="Non-interactive: accept all defaults")
    sub.add_parser("index", help="Build/rebuild skill index from vault")

    route_parser = sub.add_parser("route", help="Match user intent to skills")
    route_parser.add_argument("message", help="User input to match")
    route_parser.add_argument("--auto", action="store_true", help="Auto-activate matched skills")

    sub.add_parser("status", help="Show router state")

    rec_parser = sub.add_parser("reconcile", help="Full cycle: index → route → activate")
    rec_parser.add_argument("message", help="User input")

    act_parser = sub.add_parser("activate", help="Activate skills by name")
    act_parser.add_argument("skills", nargs="+", help="Skill names")

    sub.add_parser("config", help="Show config and validate")

    # Cron commands
    cron_parser = sub.add_parser("cron", help="Maintenance jobs")
    cron_sub = cron_parser.add_subparsers(dest="cron_cmd")
    cron_sweep = cron_sub.add_parser("sweep", help="24h sweep: auto-vault new skills")
    cron_sweep.add_argument("--dry-run", action="store_true")
    cron_report = cron_sub.add_parser("report", help="Weekly usage report")
    cron_report.add_argument("--days", type=int, default=7)
    cron_setup = cron_sub.add_parser("setup", help="Install cron jobs (24h sweep + weekly report)")
    cron_setup.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "install":
        cmd_install(config, non_interactive=getattr(args, "yes", False))
    elif args.command == "index":
        cmd_index(config)
    elif args.command == "route":
        cmd_route(config, args.message, auto_activate=args.auto)
    elif args.command == "status":
        cmd_status(config)
    elif args.command == "reconcile":
        cmd_reconcile(config, args.message)
    elif args.command == "activate":
        cmd_activate(config, args.skills)
    elif args.command == "config":
        cmd_config(config)
    elif args.command == "cron":
        cmd_cron(config, args.cron_cmd, getattr(args, "days", 7), getattr(args, "dry_run", False))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()