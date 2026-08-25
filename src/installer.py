"""Interactive install wizard for Skill Router.

Walks the user through setup step by step — auto-detects their agent,
finds skills, lets them choose always-keep, creates vault, builds index.
Framework-agnostic: works with Hermes, Claude Code, Codex, Cursor, Copilot, etc.

Usage:
    skill-router install          # Interactive wizard
    skill-router install --yes    # Non-interactive: accept all defaults
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from . import agent_detector
from .indexer import build_index
from .vault_manager import activate_skills


# ── Helper: pretty printing ───────────────────────────────

def _header(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def _step(n: int, text: str) -> None:
    print(f"\n  [{n}] {text}")


def _input(prompt: str, default: str = "") -> str:
    """Prompt for input with default value. Empty = accept default."""
    if default:
        result = input(f"  {prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"  {prompt}: ").strip()


def _yesno(prompt: str, default: bool = True) -> bool:
    """Yes/no question. Enter = default."""
    yn = "Y/n" if default else "y/N"
    result = input(f"  {prompt} [{yn}]: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def _find_skills(directory: Path, ignore_symlinks: bool = True) -> list[tuple[str, Path, str]]:
    """Find all skill directories. Returns [(name, path, snippet), ...]."""
    results: list[tuple[str, Path, str]] = []
    if not directory.is_dir():
        return results

    for entry in sorted(directory.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if ignore_symlinks and entry.is_symlink():
            continue

        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue

        # Get first line of description
        snippet = ""
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
            for line in text.split("\n"):
                if line.startswith("description:"):
                    snippet = line.split(":", 1)[1].strip().strip('"').strip("'")[:80]
                    break
        except Exception:
            pass

        results.append((entry.name, entry, snippet))

    return results


def _router_skill_source() -> Path:
    """Find router instructions from a source or bootstrap installation."""
    candidates = (
        Path(__file__).resolve().parent.parent / "SKILL.md",
        Path.home() / ".rsq-skill-router" / "SKILL.md",
        Path.cwd() / "SKILL.md",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("RSQ Skill Router SKILL.md was not found")


def install_router_skill(source: Path, active_dir: Path) -> Path:
    """Install router instructions without replacing a user-managed copy."""
    destination = active_dir / "rsq-skill-router" / "SKILL.md"
    if destination.exists():
        return destination
    if destination.parent.is_symlink():
        raise RuntimeError(f"Refusing to write through symlinked router path: {destination.parent}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def choose_router_skill_installation(non_interactive: bool) -> bool:
    """Ask whether the router itself should remain available to the agent."""
    if non_interactive:
        return True
    return _yesno(
        "Install RSQ Skill Router as an always-on agent skill?",
        default=True,
    )


# ── Main install wizard ──────────────────────────────────

def run_install(
    config: dict[str, Any],
    non_interactive: bool = False,
) -> None:
    """Interactive installation wizard."""

    # ── Step 0: Welcome ──
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║             🧠  Skill Router — Installer                ║")
    print("║  Intelligent skill loading for AI coding agents         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("  Skill Router keeps your agent fast by storing skills")
    print("  in a vault and activating only the 5–15 you need right now.")
    print()
    print("  What we'll do:")
    print("    1. Detect your AI agent (Hermes, Claude Code, Cursor, etc.)")
    print("    2. Find your installed skills")
    print("    3. Pick skills to ALWAYS keep active")
    print("    4. Move the rest into a read-only vault")
    print("    5. Build a searchable index")
    print("    6. Install the router instructions in your active skills directory")
    print()

    if not non_interactive:
        input("  Press Enter to begin...")

    # ── Step 1: Detect agent ──
    _step(1, "Detecting your AI agent...")

    detected = agent_detector.detect_agent()

    if detected.detected:
        print(f"\n  ✓ Found: {detected.name}")
        if detected.evidence:
            for e in detected.evidence:
                print(f"    • {e}")
    else:
        print(f"\n  No agent auto-detected.")

    print()
    print("  Supported agents:")
    for agent in agent_detector.AGENTS:
        marker = " ←" if agent.name == detected.name and detected.detected else ""
        print(f"    {'✓' if agent.detected else ' '} {agent.name}{marker}")

    if non_interactive:
        chosen_skills_dir = detected.skills_dir if detected.skills_dir else Path.home() / ".agent-skills"
        chosen_vault_dir = agent_detector.resolve_vault_dir()
        print(f"\n  Non-interactive mode — using detected defaults.")
    else:
        default_dir = str(detected.skills_dir) if detected.skills_dir else "~/.agent-skills"
        custom = _input(f"\n  Skills directory path", default_dir)
        chosen_skills_dir = Path(custom).expanduser()
        chosen_skills_dir.mkdir(parents=True, exist_ok=True)

        default_vault = str(chosen_skills_dir.parent / "skills-vault")
        custom_vault = _input(f"  Vault directory path", default_vault)
        chosen_vault_dir = Path(custom_vault).expanduser()

    # ── Step 2: Find skills ──
    _step(2, f"Scanning {chosen_skills_dir}...")

    all_skills = _find_skills(chosen_skills_dir, ignore_symlinks=True)
    symlink_skills = _find_skills(chosen_skills_dir, ignore_symlinks=False)
    has_symlinks = len(symlink_skills) > len(all_skills)

    if not all_skills:
        print(f"\n  ⚠️  No real skill folders found in {chosen_skills_dir}")
        print(f"  Skill Router needs at least one SKILL.md-based skill to start.")
        print(f"  Install some skills first, then re-run `skill-router install`.")
        print(f"\n  Tip: npx skills add <user/repo> --global")
        sys.exit(0)

    if has_symlinks:
        sym_count = len(symlink_skills) - len(all_skills)
        print(f"\n  Found {len(all_skills)} real skill folders ({sym_count} symlinks skipped)")
    else:
        print(f"\n  Found {len(all_skills)} skill folders")

    # Print skill list
    print(f"\n  Your installed skills:")
    for i, (name, _, snippet) in enumerate(all_skills, 1):
        snip = f" — {snippet[:60]}..." if snippet and len(snippet) > 60 else (f" — {snippet}" if snippet else "")
        print(f"    {i:3}. {name}{snip}")

    # ── Step 3: Choose always-keep ──
    _step(3, "PICK YOUR ALWAYS-ON SKILLS")
    print()
    print("  These skills stay active 100% of the time — they are NEVER")
    print("  deactivated by the router, no matter what task you're doing.")
    print()
    print("  Common choices:")
    print("    • Communication helpers (caveman, un-slop, anti-slop)")
    print("    • The router itself (rsq-skill-router)")
    print("    • Essential tooling (caveman-help, caveman-commit)")
    print()

    if non_interactive:
        always_keep = config.get("always_keep", [])
        print(f"  Non-interactive mode — using config defaults: {', '.join(always_keep)}")
    else:
        # Build a numbered menu
        print("  Enter skill numbers (comma-separated, e.g. '1,3,7') to mark as always-on.")
        print("  Press Enter to accept none, or type 'all' for everything.")
        print()

        choice = _input("  Always-on skills", "")

        if choice.strip().lower() == "all":
            always_keep = [name for name, _, _ in all_skills]
            print(f"\n  ✓ Marked ALL {len(always_keep)} as always-on")
        elif choice.strip():
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
                always_keep = [all_skills[i][0] for i in indices if 0 <= i < len(all_skills)]
                print(f"\n  ✓ Marked {len(always_keep)} as always-on: {', '.join(always_keep)}")
            except (ValueError, IndexError):
                always_keep = []
                print("\n  ⚠️  Invalid input. No skills marked as always-on.")
        else:
            always_keep = []
            print(f"\n  No skills marked as always-on.")

    install_router = choose_router_skill_installation(non_interactive)
    if install_router:
        print("  Router instructions will stay active for task routing.")
    else:
        print("  Router instructions will not be installed.")

    # ── Step 4: Confirm & execute ──
    to_move = [(name, path) for name, path, _ in all_skills if name not in always_keep]
    to_keep = [(name, path) for name, path, _ in all_skills if name in always_keep]

    _header("SUMMARY")
    print(f"\n  Skills directory: {chosen_skills_dir}")
    print(f"  Vault directory:   {chosen_vault_dir}")
    print(f"  Always-on:         {len(to_keep)}")
    print(f"  Router skill:      {'install in active/' if install_router else 'skipped'}")
    for name, _ in to_keep:
        print(f"    🔒 {name}")
    print(f"  Moving to vault:   {len(to_move)}")
    for name, _ in to_move[:10]:
        print(f"    → {name}")
    if len(to_move) > 10:
        print(f"    ... and {len(to_move) - 10} more")

    if not to_move:
        print(f"\n  Nothing to move. Your active directory is already clean.")
        print(f"  Building index anyway...")
        chosen_vault_dir.mkdir(parents=True, exist_ok=True)
        index = build_index(chosen_vault_dir, Path(config["paths"]["index_cache"]).expanduser())
        print(f"  Index: {index['total_skills']} skills across {len(index['fields'])} fields")
        if install_router:
            try:
                destination = install_router_skill(_router_skill_source(), chosen_skills_dir)
                print(f"  Router skill: {destination}")
            except (FileNotFoundError, RuntimeError) as exc:
                print(f"  ⚠️  Router skill was not installed: {exc}")
        return

    if non_interactive:
        print(f"\n  Non-interactive mode — proceeding automatically.")
    else:
        proceed = _yesno(f"\n  Move {len(to_move)} skills into the vault?")
        if not proceed:
            print("  Cancelled.")
            sys.exit(0)

    # ── Step 5: Move files ──
    _step(5, "Moving skills into vault...")

    inbox = chosen_vault_dir / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    moved = 0
    for name, src_path in to_move:
        dst = inbox / name
        if dst.exists():
            print(f"  ⚠️  Already in vault: {name} (skipping)")
            continue
        shutil.move(str(src_path), str(dst))
        moved += 1
        if moved % 10 == 0 or moved <= 5 or moved == len(to_move):
            print(f"  ✓ {name}")

    print(f"\n  Moved: {moved} → vault/_inbox/")
    if to_keep:
        print(f"  Kept:  {len(to_keep)} in active/")

    # ── Step 6: Build index ──
    _step(6, "Building search index...")

    cache = Path(config["paths"]["index_cache"]).expanduser()
    index = build_index(chosen_vault_dir, cache)
    print(f"\n  ✓ Index built: {index['total_skills']} skills across {len(index['fields'])} fields")

    # ── Step 7: Activate always-keep ──
    if to_keep:
        _step(7, "Activating always-on skills...")
        result = activate_skills(chosen_vault_dir, chosen_skills_dir, [n for n, _ in to_keep])
        if result["activated"]:
            print(f"\n  ✓ Activated: {', '.join(result['activated'])}")
        if result.get("not_found"):
            print(f"  ⚠️  Not found in vault: {', '.join(result['not_found'])}")

    if install_router:
        _step(8, "Installing router instructions...")
        try:
            destination = install_router_skill(_router_skill_source(), chosen_skills_dir)
            print(f"  ✓ Router skill ready: {destination}")
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"  ⚠️  Router skill was not installed: {exc}")

    # ── Step 9: Success ──
    _header("🎉  INSTALL COMPLETE")
    print(f"""
  What just happened:
    • {moved} skills moved into the vault (read-only, safe storage)
    • {len(to_keep)} always-on skills remain active
    • Index built — searching {index['total_skills']} skills across {len(index['fields'])} fields

  Your vault:    {chosen_vault_dir}
  Your active:   {chosen_skills_dir}
  Index:         {cache}

  ── Next steps ──

  Try routing a task:
    skill-router route --auto "write a cold email sequence"

  See what's active:
    skill-router status

  Full reconcile (route + activate + deactivate):
    skill-router reconcile "build a financial model for Q3"

  Add new skills anytime:
    • Drop SKILL.md folders into your vault
    • Run `skill-router index` to re-index
    • Run `skill-router reconcile "your task"` to activate relevant ones

  ── Tips ──

  • Organize vault skills into subdirectories (coding/, finance/, etc.)
  • The router works better with organized fields
  • Always-on skills are NEVER deactivated — choose wisely
  • Run `skill-router config` to see current settings
""")

    # Also write the config file so the user doesn't need to configure manually
    config_dir = Path("~/.config/skill-router").expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"

    out_config = {
        "paths": {
            "vault": str(chosen_vault_dir),
            "active": str(chosen_skills_dir),
            "index_cache": str(cache),
        },
        "matching": config.get("matching", {}),
        "always_keep": always_keep,
        "index": config.get("index", {}),
        "logging": config.get("logging", {}),
        "agent": {"detected": detected.name, "framework": detected.cli_name},
    }

    import json
    config_file.write_text(json.dumps(out_config, indent=2))
    print(f"  💾 Config saved to {config_file}")

    # ── Offer cron setup ──
    print(f"\n  ── Background Maintenance ──")
    print(f"  Skill Router works best with two background jobs:")
    print(f"    • 24h sweep   — automatically moves new skills into the vault")
    print(f"    • Weekly report — shows which skills you actually use, tokens saved")
    print()

    if non_interactive:
        print("  Non-interactive mode — skipping cron setup.")
        print("  Run `skill-router cron setup` later to install.")
    else:
        setup = _yesno("  Install cron jobs now?", default=True)
        if setup:
            import subprocess, sys
            script = Path(__file__).resolve().parent / "cron.py"
            python = sys.executable
            try:
                result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                current = result.stdout.strip()
            except Exception:
                current = ""
            if "# skill-router-start" not in current:
                entries = f"""
# skill-router-start — managed by Skill Router
0 3 * * * {python} {script} sweep >> ~/.cache/skill-router/cron.log 2>&1
0 8 * * 1 {python} {script} report >> ~/.cache/skill-router/cron.log 2>&1
# skill-router-end
"""
                new_cron = (current.rstrip() + "\n" + entries).strip() + "\n"
                proc = subprocess.run(["crontab"], input=new_cron, capture_output=True, text=True)
                if proc.returncode == 0:
                    print("  ✅ Cron jobs installed — daily sweep + weekly report")
                else:
                    print(f"  ⚠️  cron install failed — run `skill-router cron setup` later")
            else:
                print("  ℹ️  Cron already installed.")
        else:
            print("  Skipped. Run `skill-router cron setup` anytime.")