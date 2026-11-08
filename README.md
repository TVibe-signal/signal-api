# TVibe client helpers (Fibonacci backoff)

- `retry_fib.py` — sleep ladder 1,2,3,5,8,13s on 429/503/502
- `gate.py` — `safe_to_buy` fail-closed + fib retries
- `warmer.py` — watchlist warmer with same backoff

```bash
pip install httpx
python gate.py <MINT>
EVERY_S=900 python warmer.py
```

Not deployed on Render. NFA.
