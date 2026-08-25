---
name: rsq-skill-router
description: |
  Skill Router — intelligent skill activation for AI agents. 
  Routes user intent → matching skills → activates them from vault. 
  Trigger on "route skills for", "what skills should I use for", 
  "activate skills for", "skill-router route", "skill-router reconcile",
  or when the agent needs to find the right skill for a task.
  This skill IS the router. Use it to manage which skills are active.
---

# Skill Router

You have access to a **Skill Router** system. Skills live in a vault at `~/RSQ/fields-skills/by-field/`. Only a subset are active at any time.

## What The Router Does

- **Indexes** all 576 skills across 10 fields
- **Matches** user intent to the right skills using keyword scoring
- **Activates** only the needed skills (symlinks from vault → active)
- **Deactivates** stale skills (removes unused symlinks)
- **Protects** always-keep skills (caveman, un-slop, etc.)

## Commands You Can Run

| Command | What It Does |
|---------|-------------|
| `python ~/RSQ/skill-router/src/skill_router_cli.py status` | Show active skills, vault size, index age |
| `python ~/RSQ/skill-router/src/skill_router_cli.py index` | Rebuild skill index |
| `python ~/RSQ/skill-router/src/skill_router_cli.py route "user message"` | Match intent → skills (read-only) |
| `python ~/RSQ/skill-router/src/skill_router_cli.py route --auto "user message"` | Match AND activate skills |
| `python ~/RSQ/skill-router/src/skill_router_cli.py reconcile "user message"` | Full cycle: route → activate → deactivate |
| `python ~/RSQ/skill-router/src/skill_router_cli.py activate skill-a skill-b` | Activate specific skills |

## When To Use

Run `skill-router reconcile` at the start of every session, and whenever the user's task changes significantly.

Example workflow:
1. User says "I need to write cold email sequences for enterprise prospects"
2. Run: `skill-router reconcile "write cold email sequences for enterprise prospects"`
3. Router activates: cold-email (master orchestrator), copywriting sub-skills, sales sequence builder
4. Now those skills are loaded in the agent's active skill directory
5. Agent uses them for the task

## Fields Available

The vault has 10 fields. The router matches the user's intent to the right field:

| Field | Skills | Signal Keywords |
|-------|:------:|-----------------|
| coding | 288 | build, code, debug, refactor, api, architecture, python, react, docker |
| consulting | 120 | strategy, mece, hypothesis, m&a, due diligence, board deck, framework |
| marketing | 43 | campaign, seo, content, launch, brand, social media, ads |
| sales | 41 | pipeline, crm, abm, outbound, sdr, lead, linkedin, cold email |
| finance | 37 | accounting, tax, cash flow, p&l, cfo, budget, invoice |
| hr | 33 | recruiting, onboarding, performance, hris, compensation, compliance |
| copywriting | 10 | write, copy, email, subject line, hook, headline, storytelling |
| customer-support | 2 | ticket, triage, helpdesk, escalation, knowledge base |
| finops | 1 | cloud cost, aws, azure, billing, optimization |
| project-management | 1 | sprint, roadmap, timeline, milestone, risk, stakeholder |

## Multi-Field Routing

Some tasks span fields. The router handles this:
- "Write a cold email" → copywriting + sales
- "Financial model + presentation" → finance + consulting
- "Campaign landing page with SEO" → marketing + coding
- "Audit sales pipeline" → sales + consulting