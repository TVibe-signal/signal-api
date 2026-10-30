# TVibe client examples (not server code)

These scripts run **on your machine / bot host**. Do **not** put them inside the Render `signal-api` process.

| File | Role |
|------|------|
| `gate.py` | `safe_to_buy(mint) -> (ok, reason)` fail-closed policy helper |
| `warmer.py` | Warm `/omni`, CSV log, optional Telegram on verdict change |

**NFA.** TVibe is a heuristic risk API. `safe_to_buy` is *your* policy on top of it — not a guarantee.

## Install

```bash
pip install httpx
```

## gate.py

```bash
export API_BASE=https://signal-api-24q4.onrender.com
export MAX_RISK=30
export MIN_LIQ=50000
export MAX_LOSS_PCT=5
python gate.py <MINT>
```

Uses `GET /omni?view=agent` then optional `GET /exit`. Requires `filter.pass` when `REQUIRE_PASS=1`.

## warmer.py

```bash
export WATCH_MINTS=mint1,mint2
# or mints.txt
export EVERY_S=900   # 15 min — be kind on free tier (avoid 180)
export GAP_S=4
export ONCE=1        # one pass
python warmer.py
```

Optional: `TG_TOKEN`, `TG_CHAT` for verdict-change alerts.

## Fair use

- Prefer self-host API for tight loops
- Public instance: few mints, `EVERY_S>=900`, respect 429
