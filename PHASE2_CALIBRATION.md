# Phase 2 — Calibration (evidence-based)

**Snapshot:** ~1601 resolved · `rules_version=2026.10.28.a` · app 3.0.12  
**Bad definition (~24h):** price −50%+ or liquidity −70%+ or pair gone  
**Base rate:** ~74% bad

## What the data says

| Verdict | n | Bad rate | Call |
|---------|---|----------|------|
| ok | ~135 | ~25% | Much better than base (lift ~0.34) |
| caution | ~843 | ~70% | Near base — correct as “not clear pass” |
| avoid | ~427 | ~94% | Strong precision — **do not loosen** |

- **avoid vs ok gap:** ~68.5 pts — separation is healthy  
- **Risk buckets:** 0–9 ~20% bad · 10–19 ~39% · 20–29 ~65% · 30+ ~86%+ — score ranks risk well  
- **1h:** overall bad ~29%; ok ~6% bad at 1h — early noise is lower; 24h is the contract to optimize  

### Flags (lift vs base)

High lift (informative): `very_low_liquidity`, `brand_new_pair`, `dump_risk`, `extreme_turnover`  
`/stats` also prints `suggested_weight` vs `prior_weight` — **suggestions are not auto-applied** (shadow / blended only until a versioned change).

## Phase 2 decisions (this cycle)

### DO NOT change (core)

1. **Do not lower avoid strictness** — 94% bad precision is the product moat  
2. **Do not promote wallet_intel escalate** — runs still tiny, serial/bundle ~0  
3. **Do not stealth-retune** weights without `RULES_VERSION` + `/rules` changelog  
4. **Do not chase** “ok bad rate → 0%” by blocking almost everything (kills recall / usefulness)

### DO (ops + agent policy)

1. Keep **SEED_MAX_PER_DAY=40**, cron = ping only  
2. Keep **mix-risk nurture** so `ok` sample size grows (n=135 still modest)  
3. **Stricter client gate (optional):** `MAX_RISK=20` in `examples/gate.py` for bots that want fewer false ok-passes (bucket 10–19 still ~39% bad at 24h)  
4. Agent message: `pass` + `risk_score>=20` → treat as **review** in human/bot policy even if rare edge cases pass filter  

### Only consider a **core** rule bump when

- `ok` full n **≥ 250–300** under same `rules_version`, **or**  
- A shadow rule on `/stats` beats live on avoid precision **and** does not crush ok count for 1–2 weeks  
- Then: **one** change → set `RULES_VERSION=2026.11.xx` → changelog line → measure again  

## Success for Phase 2

- [x] Read `/stats` and document (this file)  
- [ ] No reckless weight edit  
- [ ] Optional client `MAX_RISK=20` documented  
- [ ] Continue Phase 0 nurture + Phase 1 distribution  
- [ ] Revisit core calibration at ~2.5k–3k resolved or +2 weeks  

**NFA.** Stats guide the filter; they are not trade signals.
