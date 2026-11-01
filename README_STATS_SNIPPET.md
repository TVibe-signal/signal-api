## Track record (read `/stats`)

Measured outcomes ~24h after each verdict (price −50%+, liquidity −70%+, or pair gone).

- **Base rate:** a random judged mint is already “bad” often (~70%+); read precision as **lift over base**, not as a guarantee.
- **Typical pattern:** `avoid` high bad-rate · `ok` much lower · `caution` near base — use `filter.pass` / `view=agent` `action` as a **gate**, not a buy signal.
- Compare within the same `rules_version`. **NFA.**

Live: `GET /stats` · policy: `GET /rules` · agents: `GET /agent/playbook`
