# Phase 3a — Watchlist + recheck (thin)

**Client-only.** Does not run inside Render. Helps **horizon data** by re-calling TVibe after 1h / 6h / 24h.

## Scripts

| File | Role |
|------|------|
| `examples/watch_recheck.py` | add mints → local JSON → recheck when due |
| `examples/warmer.py` | optional continuous warm of a fixed list |

## Quick start

```bash
pip install httpx
cd examples

# first snapshot + schedule 1h,6h,24h rechecks
python watch_recheck.py add <MINT1> <MINT2>

python watch_recheck.py list

# run when horizons due (cron every 15–30 min on your PC/VPS)
ONCE=1 python watch_recheck.py run
```

Optional Telegram: `TG_TOKEN`, `TG_CHAT`.

## System cron example (Linux)

```cron
*/20 * * * * cd /path/to/examples && ONCE=1 /usr/bin/python3 watch_recheck.py run >> watch.log 2>&1
```

## Telegram bot (minimal product rule)

If you extend **Gotvibesolbot**:

1. `/watch <mint>` → call API `view=agent` + store mint + time (DB or file)
2. Job every 15–30 min → recheck due 1h/6h/24h
3. Message user only on **verdict/action change** + always **NFA**
4. Never “buy now”

Same logic as `watch_recheck.py`.

## Fair use

- Few mints; `GAP_S>=4`
- Prefer self-host API if watchlist is large
- Public free instance: respect 429

## NFA

Recheck logs measure change over time. They are **not** trade signals.
