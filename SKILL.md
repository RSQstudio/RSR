---
name: rsq-skill-router
description: |
  Loaded automatically at session start. Before responding to ANY user request,
  run skill-router reconcile to activate the right skills for the task.
  Trigger on every message — this skill MUST run first.
---

# RSQ Skill Router — Agent Instructions

You are the agent. This skill routes other skills. **This is the first thing you do on every turn.**

## Mandatory Rule

**Before executing any user request, run:**

```bash
skill-router reconcile "<the user's exact request>"
```

This activates the right skills from the vault. Don't skip this. Don't ask the user about it. Just do it.

## What Happens

1. You run `skill-router reconcile "user's message"`
2. The router matches the user's intent to the right field(s) and skills
3. It creates symlinks from vault → your active skills directory
4. It deactivates skills from previous tasks that are no longer relevant
5. The new skills are now available to you
6. You use them to fulfill the user's request

## Example

```
User: "Write a cold email sequence for enterprise SaaS prospects"

Agent (you):
  1. Run: skill-router reconcile "write a cold email sequence for enterprise SaaS prospects"
  2. Output shows: activated cold-email-4-sequence, email-writing-frameworks, etc.
  3. Now use those skills to write the email
  4. Deliver the result to the user
```

## Commands You Run

| Command | When |
|---------|------|
| `skill-router reconcile "user's request"` | **Every turn, before doing work** |
| `skill-router status` | When the user asks "what skills are active" |

The user never types these. You do. Automatically.

## Fields Available

The vault has 10 fields. The router auto-matches user intent to the right field:

| Field | Skills | Signal Keywords |
|-------|:------:|-----------------|
| coding | 288 | build, code, debug, refactor, api, python, react, docker, kubernetes |
| consulting | 120 | strategy, mece, hypothesis, m&a, due diligence, board deck, framework |
| marketing | 43 | campaign, seo, content, launch, brand, social media, ads |
| sales | 41 | pipeline, crm, abm, outbound, sdr, lead, linkedin, cold email |
| finance | 37 | accounting, tax, cash flow, p&l, cfo, budget, invoice, financial model |
| hr | 33 | recruiting, onboarding, performance, hris, compensation, compliance |
| copywriting | 10 | write, copy, email, subject line, hook, headline, storytelling |
| customer-support | 2 | ticket, triage, helpdesk, escalation, knowledge base |
| finops | 1 | cloud cost, aws, azure, billing, optimization |
| project-management | 1 | sprint, roadmap, timeline, milestone, risk, stakeholder |

## Multi-Field Routing

Some tasks span fields. The router handles this automatically:
- "Write a cold email" → copywriting + sales
- "Financial model + presentation" → finance + consulting
- "Create a campaign landing page" → marketing + coding
- "Audit sales pipeline" → sales + consulting