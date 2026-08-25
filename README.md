# RSQ Skill Router

**Intelligent skill loading for AI coding agents.** Keep your agent fast. 600 skills in the vault, only 5–15 in active memory.

An AI agent with 100 skills loaded burns ~10,000 tokens before the first prompt. At 600 skills, that's 60,000 tokens — half a context window. **RSQ Skill Router solves this** by keeping all skills in a read-only vault and activating only the ones relevant to the current task.

## Architecture

RSQ Skill Router uses a vault-based architecture — skills live in a read-only vault and are symlinked into the agent's active directory on demand.

```
┌─────────────────────────┐          ┌──────────────────────┐
│        VAULT            │          │       ACTIVE         │
│  (read-only source)     │  ROUTER  │  (agent reads here)  │
│                         │          │                      │
│  coding/      288       │─────────→│  cold-email-4-seq    │
│  consulting/  120       │  match   │  email-frameworks    │
│  finance/      37       │  intent  │  sales-seq-builder   │
│  marketing/    43       │          │  subject-lines       │
│  sales/        41       │  ─ ─ ─ → │  list-building       │
│  hr/           33       │ deactiv  │                      │
│  copywriting/  10       │  stale   │  🔒 caveman          │
│  cs/ 2  pm/ 1  fi/ 1   │          │  🔒 un-slop          │
│                         │          │  🔒 router           │
│  568 total              │          │  5–15 max (+always)  │
└─────────────────────────┘          └──────────────────────┘
```

**[📊 Full diagram →](https://htmlpreview.github.io/?https://github.com/RED-NTWRK/RSR/blob/main/diagrams/vault-architecture.html)**

## Component Architecture

Eight modules, one CLI. Install once, route forever.

```
  AGENT reads SKILL.md ──→  skill-router CLI
                                   │
          ┌────────────────────────┼──────────────────────┐
          │              │         │         │            │
     install.py     indexer.py  matcher.py  vault_mgr  cron.py
          │              │         │         │            │
   Interactive       Scans     Keyword    Symlink    24h sweep
   wizard           vault     scoring     ops       weekly rpt
          │              │         │         │            │
          └──────────────┴─────────┴─────────┴────────────┘
                                   │
                    ┌──────────────┼──────────────┐
               ~/.hermes/skills-vault/     ~/.hermes/skills/
               (read-only · 568 skills)    (symlinks · agent reads)
```

**[📊 Full diagram →](https://htmlpreview.github.io/?https://github.com/RED-NTWRK/RSR/blob/main/diagrams/component-architecture.html)**

## Install

### Option 1: curl + bash (recommended)

```bash
curl -sSL https://raw.githubusercontent.com/RED-NTWRK/RSR/main/install.sh | bash
```

Downloads the repo to `~/.rsq-skill-router/`, creates a `skill-router` CLI wrapper in `~/.local/bin/`, and launches the interactive setup wizard.

### Option 2: pip

```bash
pip install git+https://github.com/RED-NTWRK/RSR.git
```

Then run the wizard:
```bash
skill-router install
```

### Option 3: npx

```bash
npx rsq-skill-router install
```

Uses a thin Node wrapper — still requires `python3` on your system.

### Option 4: manual clone

```bash
git clone https://github.com/RED-NTWRK/RSR.git ~/rsq-skill-router
cd ~/rsq-skill-router
python3 src/skill_router_cli.py install
```

---

**That's it.** The router is loaded as an always-on skill after installation. From this point on, you just talk to your agent normally. The router handles everything invisibly:

```
You: "Write a cold email sequence for enterprise SaaS prospects"
     → Agent reads rsq-skill-router SKILL.md
     → Agent runs: skill-router reconcile "write a cold email sequence..."
     → Router activates: cold-email-4-sequence, email-writing-frameworks, etc.
     → Agent now has the right skills loaded — writes your email

You: "Build a financial model for Q3 projections"
     → Agent runs: skill-router reconcile "build a financial model..."
     → Previous sales skills deactivated, finance + consulting skills activated
     → Agent builds your model
```

**Commands you'll actually use** (agent handles the rest):

```bash
skill-router status          # See what's active
skill-router cron setup       # Install background maintenance
skill-router cron report      # Weekly usage analytics
```

**What the installer does:**

1. **Auto-detects your AI agent** — Hermes, Claude Code, Codex, Cursor, Copilot, Windsurf, Cline, OpenClaw, Aider, Continue, or any SKILL.md-compatible agent
2. **Finds your installed skills** — scans your agent's skills directory, lists every skill with its description
3. **Lets you pick always-on skills** — numbered menu, pick any combination (e.g. "1,3,7") or "all"
4. **Moves the rest into a read-only vault** — `~/.hermes/skills-vault/` (or your agent's equivalent)
5. **Builds a searchable index**
6. **Offers to install cron jobs** — 24h sweep + weekly usage report
7. **From that point on:** only symlinks from vault → active. Vault files are never touched again.

After install, your active skills directory contains only symlinks and your always-on skills. The router manages everything else.

## Framework Support

Works with **any AI agent that supports SKILL.md**. Auto-detects:

| Agent | Skills Directory |
|-------|-----------------|
| Hermes Agent | `~/.hermes/skills/` |
| Claude Code | `~/.claude/skills/` |
| OpenAI Codex | `~/.codex/skills/` |
| Cursor | `.cursor/skills/` |
| GitHub Copilot | `~/.github/copilot/skills/` |
| Windsurf | `~/.windsurf/skills/` |
| Cline | `~/.cline/skills/` |
| OpenClaw | `~/.openclaw/skills/` |
| Aider | `~/.aider/skills/` |
| Continue | `~/.continue/skills/` |
| Generic | `~/.agent-skills/` |

Don't see yours? Pass it explicitly: `skill-router install --skills-dir ~/my-skills`

**Output:**
```
Top field: sales
Found in: sales, copywriting
Skills: 8

  [sales]
    0.872 █████████████████░░░  cold-email
    0.741 ██████████████░░░░░░  outbound-engine
    0.683 █████████████░░░░░░░  list-building
  [copywriting]
    0.795 ████████████████░░░░  email-writing-frameworks
    0.712 ██████████████░░░░░░  subject-lines
    0.657 █████████████░░░░░░░  cold-email-templates-34

Activated:   5
Deactivated: 12
Protected:   8  (caveman, un-slop, ...)
Unchanged:   3
```

## Architecture

```
skill-router/
├── README.md
├── LICENSE
├── SKILL.md                  ← The router as an agent skill
├── config.yaml               ← Configuration
├── src/
│   ├── __init__.py
│   ├── indexer.py            ← Scans vault, builds keyword index
│   ├── matcher.py            ← Matches user intent → skills
│   ├── vault_manager.py      ← Manages symlinks with safety guarantees
│   └── skill_router_cli.py   ← CLI entry point
└── tests/
```

### Core Modules

| Module | Role |
|--------|------|
| **indexer** | Scans every `SKILL.md` in vault, extracts `name` + `description` + body keywords, writes `index.json` |
| **matcher** | Takes user message → weighted keyword scoring (name ×3, keywords ×2, description ×1) → ranked match list |
| **vault_manager** | Creates/removes symlinks between vault and active. Never touches real files. Respects `always_keep` |
| **CLI** | User-facing commands: `index`, `route`, `reconcile`, `status`, `activate`, `config` |

## Config

```yaml
paths:
  vault: "~/.hermes/skills-vault"        # Where ALL skills live
  active: "~/.hermes/skills"             # Where agent loads from
  index_cache: "~/.cache/skill-router/index.json"

matching:
  strategy: "keyword"              # keyword | semantic | hybrid
  max_active_skills: 15
  min_confidence: 0.3
  multi_field: true

always_keep:
  - caveman
  - caveman-help
  - un-slop
  - rsq-skill-router

index:
  auto_rebuild: "on_change"

logging:
  level: "info"
  json_format: true
```

## Safety Guarantees

- **Vault is read-only.** Skill Router never writes, modifies, or deletes files in the vault.
- **Active uses symlinks.** Skills are symlinked, not copied. A symlink is a pointer, not a duplicate.
- **Never touches real files.** `vault_manager` verifies a path is a symlink before unlinking. Real files are refused.
- **Always-keep is inviolable.** Skills in `always_keep` are immune to deactivation.
- **Atomic reconcile.** Activate new skills before deactivating old ones — no gap window with zero skills.
- **Dry-run mode.** All operations support `--dry-run` to preview without changing state.

## Comparison

| | Without Router | With Router |
|---|---|---|
| Skills loaded at startup | 50–600 | 5–15 |
| Context tokens burned on index | 5,000–60,000 | ~800 |
| Room for actual work | What's left | Almost all of it |
| Stale skills | Stay loaded forever | Auto-deactivated after 3 turns |
| Cross-field tasks | Manual selection | Auto-routed to both fields |

## Integrations

### Hermes Agent

Install as a skill:
```bash
cp SKILL.md ~/.hermes/skills/skill-router/SKILL.md
```

Then run reconciliation at session start:
```bash
python ~/RSQ/skill-router/src/skill_router_cli.py reconcile "initial session start"
```

### Claude Code / Codex / Cursor

The router works with any agent that supports symlinked skill directories. Configure `paths.active` to point to your agent's skills folder.

## License

MIT — RSQ, 2026

## Roadmap

- [ ] Semantic matching via sentence-transformers (fallback for low-confidence keyword matches)
- [ ] Usage tracking — which skills get used, frequency, deactivation decay
- [ ] Hermes plugin — native `before_turn` hook integration
- [ ] pip package — `pip install skill-router`