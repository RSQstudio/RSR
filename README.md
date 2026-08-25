# RSQ Skill Router

> Keep the full skill library on disk. Give the agent the small set it needs for the task in front of it.

RSQ Skill Router is a local Python CLI for agents that use `SKILL.md`-style skills. It indexes a read-only vault, matches a task against that index, and maintains an active skills directory with symlinks.

The agent reads the active directory. The full library stays out of its working context until it is relevant.

**What it does**

- indexes `SKILL.md` metadata from a vault
- routes a task to a bounded set of matching skills
- activates and deactivates symlinks in the active skills directory
- protects selected always-on skills
- records routing activity for local maintenance reports

RSQ Skill Router is not a hosted service, an LLM, or a replacement for your agent framework. It is a local control plane for a large skill library.

![Vault to active context](diagrams/vault-architecture.svg)

## The operating model

A skill library has two locations:

| Location | Purpose | What the router may change |
|---|---|---|
| **Vault** | The complete source library | Nothing during normal routing |
| **Active directory** | The skills the agent can load now | Symlinks only |

The installer moves existing real skill folders into the vault once. After that, normal routing creates or removes only symlinks in the active directory.

![Component map](diagrams/component-architecture.svg)

## Install

### Requirements

- Python 3.10 or newer
- Git
- At least one directory containing `SKILL.md` skills
- GitHub access to this repository while it remains private

### Install from source

This is the most transparent path.

```bash
git clone https://github.com/RED-NTWRK/RSR.git ~/.rsq-skill-router
cd ~/.rsq-skill-router
python3 -m pip install .
skill-router install
```

The installer detects a supported agent, asks which skills must remain active, moves the remaining real skill folders into a vault, and builds the first index.

### Bootstrap installer

The repository also includes a bootstrap script. It clones the repository into `~/.rsq-skill-router`, creates `~/.local/bin/skill-router`, and starts the setup wizard.

```bash
curl -fsSL https://raw.githubusercontent.com/RED-NTWRK/RSR/main/install.sh | bash
```

Review `install.sh` before using it in a managed environment. It changes local skill locations and may add `~/.local/bin` to your shell startup file.

## First task

After installation, inspect the state and test routing without changing the active set:

```bash
skill-router status
skill-router route "write a cold email sequence for enterprise prospects"
```

Activate the selected skills for a real task:

```bash
skill-router reconcile "write a cold email sequence for enterprise prospects"
```

If the index does not exist yet, build it first:

```bash
skill-router index
```

`reconcile` matches the task, activates the new symlinks, then removes stale symlinks. It activates before it deactivates.

## Agent integration

Installation prepares the vault, index, configuration, and CLI. It does **not** install a native pre-turn hook into every agent framework.

For a compatible agent to route automatically, make this repository's `SKILL.md` available in that agent's active skill directory. For Hermes Agent:

```bash
mkdir -p ~/.hermes/skills/rsq-skill-router
cp ~/.rsq-skill-router/SKILL.md ~/.hermes/skills/rsq-skill-router/SKILL.md
```

`SKILL.md` instructs the agent to run `skill-router reconcile "<current task>"` before it starts work. Other frameworks can use the same file in their documented skill directory, provided `paths.active` points to that directory.

The installer recognizes common skill locations for Hermes, Claude Code, Codex, Cursor, GitHub Copilot, Windsurf, Cline, OpenClaw, Aider, and Continue. If detection chooses the wrong directory, provide the correct path during the interactive install or set it explicitly in the configuration file.

## Commands

| Command | Effect |
|---|---|
| `skill-router install` | Runs the interactive setup wizard |
| `skill-router index` | Rebuilds the local skill index from the vault |
| `skill-router route "<task>"` | Shows matches without changing active skills |
| `skill-router route --auto "<task>"` | Routes and reconciles in one command |
| `skill-router reconcile "<task>"` | Routes and reconciles the active set |
| `skill-router activate <skill>...` | Activates named vault skills directly |
| `skill-router status` | Shows vault, active, and index state |
| `skill-router config` | Prints the current configuration and validates paths |
| `skill-router cron sweep --dry-run` | Previews the maintenance sweep |
| `skill-router cron setup` | Adds the sweep and report jobs to the user crontab |
| `skill-router cron report` | Prints a usage report from the local log |

## How matching works

The default matcher is deterministic and local.

1. It identifies likely fields from task keywords.
2. It scores skills in those fields using normalized keyword overlap.
3. A name match weighs 3×, indexed keywords weigh 2×, and description text weighs 1×.
4. It returns the highest-scoring skills above the configured threshold, capped at the configured maximum.

This is deliberately simple. It is inspectable, cheap to run, and gives you a clean place to add semantic matching later if the keyword index stops being sufficient.

## Configuration

The installer writes its configuration to `~/.config/skill-router/config.yaml`. A minimal configuration looks like this:

```yaml
paths:
  vault: "auto"
  active: "auto"
  index_cache: "~/.cache/skill-router/index.json"

matching:
  strategy: "keyword"
  max_active_skills: 15
  min_confidence: 0.3
  multi_field: true

always_keep:
  - rsq-skill-router

logging:
  level: "info"
  json_format: true
```

Use `auto` paths when the installer should resolve the active and vault directories from the detected agent. Set explicit absolute paths when you manage several agents or profiles on the same machine.

## Safety boundaries

- The vault is the source of truth. Normal routing does not modify or delete vault skills.
- The router removes only symlinks that it owns in the active directory. It refuses to delete a real active skill folder.
- Skills in `always_keep` are not deactivated during reconciliation.
- Reconciliation adds required links before removing stale ones.
- `cron sweep` is state-changing because it can move newly added real skills from the active directory into the vault. Run it with `--dry-run` before enabling it in an unfamiliar environment.

## Repository layout

```text
RSR/
├── SKILL.md                  # Instructions consumed by compatible agents
├── config.yaml               # Default configuration template
├── install.sh                # Bootstrap installer
├── diagrams/                 # README architecture diagrams
└── src/
    ├── agent_detector.py     # Finds known agent skill directories
    ├── indexer.py            # Builds and reads the skill index
    ├── matcher.py            # Routes task text to skill names
    ├── vault_manager.py      # Performs guarded symlink operations
    ├── installer.py          # Interactive setup wizard
    ├── cron.py               # Sweep, report, and crontab support
    └── skill_router_cli.py   # CLI entry point
```

## Development

Run the CLI directly from a source checkout:

```bash
python3 src/skill_router_cli.py --help
python3 -m compileall -q src
```

## Roadmap

- semantic matching for low-confidence keyword results
- usage-aware ranking and deactivation policy
- framework-native lifecycle hooks where the target framework supports them

## License

MIT © RSQ, 2026
