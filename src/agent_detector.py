"""Agent Detector — auto-detects AI agent frameworks and their skill directories.

Supports: Hermes Agent, Claude Code, OpenAI Codex, Cursor, GitHub Copilot,
Windsurf, OpenClaw, Cline, and any SKILL.md-compatible agent.

Usage:
    from agent_detector import detect_agent, list_agents
    
    agent = detect_agent()
    print(agent.skills_dir)  # → /home/user/.hermes/skills/
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class AgentInfo:
    name: str
    skills_dir: Path | None
    config_dir: Path | None
    cli_name: str
    priority: int  # Higher = more likely to be the active agent
    detected: bool = False
    evidence: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        status = "✓ detected" if self.detected else "not found"
        return f"{self.name} ({status}) — {self.skills_dir}"


# ── Agent Registry ────────────────────────────────────────
# Ordered by priority (most signal → least). First match wins.

AGENTS: list[AgentInfo] = [
    AgentInfo(
        name="Hermes Agent",
        skills_dir=Path.home() / ".hermes" / "skills",
        config_dir=Path.home() / ".hermes",
        cli_name="hermes",
        priority=100,
    ),
    AgentInfo(
        name="Claude Code",
        skills_dir=Path.home() / ".claude" / "skills",
        config_dir=Path.home() / ".claude",
        cli_name="claude",
        priority=95,
    ),
    AgentInfo(
        name="OpenAI Codex",
        skills_dir=Path.home() / ".codex" / "skills",
        config_dir=Path.home() / ".codex",
        cli_name="codex",
        priority=90,
    ),
    AgentInfo(
        name="Cursor",
        skills_dir=Path.cwd() / ".cursor" / "skills",
        config_dir=Path.cwd() / ".cursor",
        cli_name="cursor",
        priority=85,
    ),
    AgentInfo(
        name="GitHub Copilot",
        skills_dir=Path.home() / ".github" / "copilot" / "skills",
        config_dir=Path.home() / ".github" / "copilot",
        cli_name="copilot",
        priority=80,
    ),
    AgentInfo(
        name="Windsurf",
        skills_dir=Path.home() / ".windsurf" / "skills",
        config_dir=Path.home() / ".windsurf",
        cli_name="windsurf",
        priority=75,
    ),
    AgentInfo(
        name="Cline",
        skills_dir=Path.home() / ".cline" / "skills",
        config_dir=Path.home() / ".cline",
        cli_name="cline",
        priority=70,
    ),
    AgentInfo(
        name="OpenClaw",
        skills_dir=Path.home() / ".openclaw" / "skills",
        config_dir=Path.home() / ".openclaw",
        cli_name="openclaw",
        priority=65,
    ),
    AgentInfo(
        name="Aider",
        skills_dir=Path.home() / ".aider" / "skills",
        config_dir=Path.home() / ".aider",
        cli_name="aider",
        priority=60,
    ),
    AgentInfo(
        name="Continue",
        skills_dir=Path.home() / ".continue" / "skills",
        config_dir=Path.home() / ".continue",
        cli_name="continue",
        priority=55,
    ),
    AgentInfo(
        name="Generic (SKILL.md compatible)",
        skills_dir=Path.home() / ".agent-skills",
        config_dir=Path.home() / ".agent-skills",
        cli_name="agent",
        priority=10,
    ),
]


def _is_hermes_running() -> bool:
    """Check if Hermes gateway is active."""
    # This only probes a fixed local service status command; no shell or user input.
    import subprocess  # nosec B404
    try:
        result = subprocess.run(  # nosec B603, B607
            ["systemctl", "--user", "is-active", "hermes-gateway"],
            capture_output=True, text=True, timeout=3, check=False
        )
        return "active" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_claude_running() -> bool:
    """Check if Claude Code config exists."""
    return (Path.home() / ".claude").is_dir()


def _is_codex_running() -> bool:
    """Check if Codex config exists."""
    return (Path.home() / ".codex").is_dir()


def _detect_registered_agent(registered: AgentInfo) -> AgentInfo:
    """Collect independent local evidence for one registered agent."""
    agent = replace(registered, detected=False, evidence=[])

    if agent.name == "Hermes Agent" and _is_hermes_running():
        agent.evidence.append("hermes-gateway systemd service active")

    if shutil.which(agent.cli_name):
        agent.evidence.append("CLI executable found")

    if agent.skills_dir and agent.skills_dir.is_dir():
        has_skills = any(
            (agent.skills_dir / d / "SKILL.md").exists()
            for d in agent.skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        if has_skills:
            agent.evidence.append("skills directory with SKILL.md files found")

    if agent.config_dir and agent.config_dir.is_dir():
        agent.evidence.append("config directory found")

    agent.detected = bool(agent.evidence)
    return agent


def detect_agent() -> AgentInfo:
    """Auto-detect the highest-priority installed or active agent framework.

    Each framework is evaluated independently for a running service, CLI binary,
    skills directory, and config directory. The highest-priority positive match
    remains the default installation target.
    """
    candidates = [
        _detect_registered_agent(registered)
        for registered in sorted(AGENTS, key=lambda agent: -agent.priority)
    ]

    for agent in candidates:
        if agent.detected:
            return agent

    # Fallback: return Hermes as default (most common in RSQ ecosystem)
    # but mark it as undetected so the installer asks.
    return replace(AGENTS[0], detected=False, evidence=[])


def list_agents() -> list[AgentInfo]:
    """Return every registered agent with its own detection status."""
    return [_detect_registered_agent(registered) for registered in AGENTS]


def resolve_skills_dir(agent_hint: str | None = None) -> Path:
    """Resolve the skills directory to use.

    Priority:
    1. User-provided hint (agent name or explicit path)
    2. Auto-detection
    3. Generic fallback
    """
    if agent_hint:
        # Check if it's a path
        hint_path = Path(agent_hint).expanduser()
        if hint_path.is_dir():
            return hint_path

        # Check if it matches an agent name
        for agent in AGENTS:
            if agent_hint.lower() in agent.name.lower():
                return agent.skills_dir or Path.home() / ".agent-skills"

    # Auto-detect
    agent = detect_agent()
    if agent.detected and agent.skills_dir:
        return agent.skills_dir

    # Fallback
    return Path.home() / ".agent-skills"


def resolve_vault_dir(agent_hint: str | None = None) -> Path:
    """Resolve where the vault should live (alongside skills dir)."""
    skills = resolve_skills_dir(agent_hint)
    parent = skills.parent
    return parent / "skills-vault"


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("═══ Agent Detection ═══\n")

    detected = detect_agent()
    if detected.detected:
        print(f"  Active: {detected.name}")
        print(f"  Skills: {detected.skills_dir}")
        print(f"  Evidence: {', '.join(detected.evidence)}")
    else:
        print("  No agent detected. Run `skill-router install` for interactive setup.")

    print("\n  Available agents:")
    for agent in AGENTS:
        skills = agent.skills_dir
        exists = "✓" if skills and skills.is_dir() else "✗"
        print(f"    {exists} {agent.name:<25} {skills}")