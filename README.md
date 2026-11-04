# TVibe Signal

Free open-source **Solana token risk API** for agents and humans.

**Not financial advice.**

- **Live:** https://signal-api-24q4.onrender.com  
- **Docs (all-in-one):** [docs/README.md](docs/README.md)  
- **X:** https://x.com/realTVibe · **Telegram:** https://t.me/Gotvibesolbot  

```text
GET /omni?mint=<MINT>&view=agent
GET /stats · GET /rules · GET /ops/tradeoff · GET /ops/falsifiability
MCP https://signal-api-24q4.onrender.com/mcp
```

### Deploy

- Build: `pip install -r requirements.txt`
- Start: `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
- Env: see [docs/README.md](docs/README.md) § Ops

### Layout

`main.py` · `core.py` · `features.py` · `extensions.py` · `docs/` · `examples/`
