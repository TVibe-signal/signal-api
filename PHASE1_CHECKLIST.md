# Phase 1 — Agent distribution checklist

Goal: more **real callers** (agents/bots/users), not more heuristics.

## 1. Repo (do once)

- [ ] `examples/gate.py` + `examples/warmer.py` + `examples/README.md` on `main`
- [ ] `docs/AGENTS.md` (how to call `/omni?view=agent`, MCP, errors)
- [ ] `docs/DATA_FEEDER.md` (ops nurture only, NFA)
- [ ] `docs/OPS.md` (cron + env)
- [ ] README links: Agents · Ops · Data feeder · examples · NFA

## 2. Live endpoints (already on 3.0.12 — verify)

- [ ] `GET /llms.txt`
- [ ] `GET /.well-known/agent-card.json`
- [ ] `GET /agent/playbook`
- [ ] `GET /mcp` (MCP streamable HTTP)
- [ ] `GET /rules` + `GET /stats`

## 3. Telegram bot

- [ ] Only risk check via API (`view=agent` preferred)
- [ ] Always NFA line — never “buy this”
- [ ] Link on web: https://t.me/Gotvibesolbot

## 4. Optional announcement (X)

Short post template — see `docs/X_AGENT_ONBOARD.md`.

## 5. Done when

- At least one **external** path is documented and working (MCP or Tele or examples)
- Public instance not hammered (seed max 40, cron = ping only)

**Not in Phase 1:** new scoring rules, SI features, second app.
