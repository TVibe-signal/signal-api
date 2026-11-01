# Client examples (not loaded by Render)

Run on your machine / bot host only.

| Script | Role |
|--------|------|
| `gate.py` | `safe_to_buy(mint)` fail-closed helper |
| `warmer.py` | Warm watchlist + CSV + optional Telegram |
| `watch_recheck.py` | Phase 3a horizons 1h/6h/24h |

```bash
pip install httpx
python gate.py <MINT>
```

**NFA.** Do not deploy these as the Render start process.
