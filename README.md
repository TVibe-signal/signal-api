# TVibe → pay-skills (free listing)

Core API stays **free** (no x402 / no pricing block on risk routes).

## What to do

1. Fork https://github.com/solana-foundation/pay-skills
2. Copy this folder into the fork:
   `providers/tvibe/signal/PAY.md`
   `providers/tvibe/signal/openapi.json`
3. Install pay CLI (see https://pay.sh/docs ) then:

```bash
pay catalog check providers/tvibe/signal/PAY.md
```

4. Fix any CI complaints (description length, probe, category).
5. Open a PR to `solana-foundation/pay-skills` with title like:
   `Add tvibe/signal — free Solana risk gate for agents`

## Notes

- **Omit `pricing:`** on endpoints → free; if you add pricing, CI expects HTTP 402.
- Public instance: fair use; high volume → self-host.
- Optional: Render paid plan only stabilizes uptime for probes — not required to list.

## Local package layout

```
providers/tvibe/signal/
  PAY.md
  openapi.json
```
