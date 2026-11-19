"""patch_live_fix v34-premium — world-class homepage + stable /omni /play."""
from __future__ import annotations
import re
from typing import Optional

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# ---------- Premium homepage ----------
HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05060a">
<meta name="color-scheme" content="dark">
<title>TVibe Signal — Solana risk gate for AI agents</title>
<meta name="description" content="Free Solana mint risk filter. One request → verdict, reasons, unknowns. Measured in public. NFA.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #05060a;
  --surface: #0c0f17;
  --surface2: #111522;
  --border: rgba(255,255,255,0.08);
  --border-hover: rgba(255,255,255,0.16);
  --text: #f1f3f9;
  --muted: #8b95a8;
  --dim: #5c667a;
  --green: #14f195;
  --green-dim: rgba(20,241,149,0.12);
  --purple: #9945ff;
  --cyan: #00e8ff;
  --amber: #ffc14d;
  --rose: #ff4d6a;
  --radius: 14px;
  --radius-sm: 10px;
}
*,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
  min-height: 100dvh;
  -webkit-font-smoothing: antialiased;
}
/* ambient glow */
.ambient {
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(ellipse 90% 60% at 15% -15%, rgba(153,69,255,0.22), transparent 55%),
    radial-gradient(ellipse 70% 50% at 95% 10%, rgba(0,232,255,0.08), transparent 50%),
    radial-gradient(ellipse 50% 40% at 50% 110%, rgba(20,241,149,0.06), transparent 50%);
}
.shell {
  position: relative; z-index: 1;
  max-width: 680px;
  margin: 0 auto;
  padding: 28px 18px 64px;
}
/* header */
.brand {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 32px;
}
.brand-mark {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--purple), var(--cyan));
  display: grid; place-items: center;
  font-weight: 700; font-size: 13px; color: #000;
  letter-spacing: -0.02em;
}
.brand-name {
  font-size: 14px; font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--muted);
  text-transform: uppercase;
}
h1 {
  font-size: clamp(26px, 6vw, 34px);
  font-weight: 700;
  line-height: 1.18;
  letter-spacing: -0.025em;
  margin-bottom: 10px;
}
.lead {
  font-size: 15px;
  color: var(--muted);
  max-width: 480px;
  margin-bottom: 28px;
}
.lead a { color: var(--cyan); text-decoration: none; }
.lead a:hover { text-decoration: underline; }

/* card */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px;
  margin-bottom: 20px;
}
.card-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
}
#mint {
  width: 100%;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 14.5px;
  font-weight: 500;
  padding: 15px 16px;
  border-radius: var(--radius-sm);
  border: 1.5px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
#mint::placeholder { color: var(--dim); }
#mint:focus {
  border-color: rgba(0,232,255,0.45);
  box-shadow: 0 0 0 3px rgba(0,232,255,0.1);
}
.actions {
  display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap;
}
.btn {
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  padding: 11px 18px;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
  display: inline-flex; align-
... 