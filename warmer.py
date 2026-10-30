"""TVibe cache warmer + CSV log + optional Telegram alert on verdict change.

Client-side only. Be gentle on the free public instance.

Env:
  API_BASE      default https://signal-api-24q4.onrender.com
  WATCH_MINTS   comma-separated mints (and/or mints.txt, one mint per line)
  EVERY_S       loop sleep seconds (default 900 — 15 min; avoid 180 on free)
  GAP_S         delay between mints (default 4)
  ONCE=1        single pass then exit
  VIEW=agent    agent | full (default agent)
  TG_TOKEN, TG_CHAT   optional Telegram alert
  LOG_CSV       default log.csv

NFA: logs risk snapshots only; not trading signals.
"""
from __future__ import annotations

import csv
import os
import time
from typing import Dict, List, Optional

import httpx

API = os.getenv("API_BASE", "https://signal-api-24q4.onrender.com").rstrip("/")
EVERY = max(60, int(os.getenv("EVERY_S", "900")))
GAP = max(1.0, float(os.getenv("GAP_S", "4")))
ONCE = os.getenv("ONCE", "").lower() in ("1", "true", "yes")
VIEW = (os.getenv("VIEW", "agent") or "agent").strip().lower()
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT = os.getenv("TG_CHAT")
LOG = os.getenv("LOG_CSV", "log.csv")

_last: Dict[str, str] = {}


def load_mints() -> List[str]:
    mints = [m.strip() for m in os.getenv("WATCH_MINTS", "").split(",") if m.strip()]
    if os.path.exists("mints.txt"):
        with open("mints.txt", encoding="utf-8") as f:
            mints += [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    # stable unique order
    return list(dict.fromkeys(mints))


def log_row(mint: str, d: dict) -> None:
    new_file = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(
                [
                    "ts",
                    "mint",
                    "action",
                    "verdict",
                    "filter_pass",
                    "risk_score",
                    "liquidity_usd",
                    "rules_version",
                ]
            )
        dec = d.get("decision") if isinstance(d.get("decision"), dict) else {}
        verdict = dec.get("verdict") or d.get("verdict")
        risk = dec.get("risk_score") if dec.get("risk_score") is not None else d.get("risk_score")
        fp = (d.get("filter") or {}).get("pass") if isinstance(d.get("filter"), dict) else None
        w.writerow(
            [
                int(time.time()),
                mint,
                d.get("action"),
                verdict,
                fp,
                risk,
                d.get("liquidity_usd"),
                d.get("rules_version"),
            ]
        )


def alert(client: httpx.Client, text: str) -> None:
    print("ALERT", text, flush=True)
    if not (TG_TOKEN and TG_CHAT):
        return
    try:
        client.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text[:3500]},
            timeout=15.0,
        )
    except Exception as e:
        print("telegram_error:", e.__class__.__name__, flush=True)


def warm_one(client: httpx.Client, mint: str) -> int:
    """Returns extra sleep seconds if rate-limited."""
    try:
        params = {"mint": mint}
        if VIEW == "agent":
            params["view"] = "agent"
        r = client.get(f"{API}/omni", params=params, timeout=45.0)
        if r.status_code in (429, 503, 504):
            wait = 5
            try:
                body = r.json()
                err = body.get("error") if isinstance(body.get("error"), dict) else {}
                wait = int(err.get("retry_after_s") or body.get("retry_after_s") or 5)
            except Exception:
                pass
            wait = min(max(wait, 5), 60)
            print(f"{mint[:8]} busy http={r.status_code} sleep={wait}s", flush=True)
            return wait

        d = r.json()
        if not isinstance(d, dict):
            print(f"{mint[:8]} bad_json", flush=True)
            return 0

        dec = d.get("decision") if isinstance(d.get("decision"), dict) else {}
        verdict = str(dec.get("verdict") or d.get("verdict") or "")
        action = d.get("action")
        risk = dec.get("risk_score") if dec.get("risk_score") is not None else d.get("risk_score")
        print(
            f"{mint[:8]} action={action} verdict={verdict} risk={risk}",
            flush=True,
        )
        log_row(mint, d)

        if verdict and _last.get(mint) and _last[mint] != verdict:
            alert(
                client,
                f"TVibe verdict change: {_last[mint]} -> {verdict}\n"
                f"risk={risk} action={action}\n{mint}\nNFA — snapshot only",
            )
        if verdict:
            _last[mint] = verdict
    except Exception as e:
        print(f"{mint[:8]} error:{e.__class__.__name__}", flush=True)
    return 0


def main() -> None:
    with httpx.Client() as client:
        while True:
            mints = load_mints()
            if not mints:
                print("No mints — set WATCH_MINTS or mints.txt", flush=True)
            for mint in mints:
                extra = warm_one(client, mint)
                time.sleep(GAP + extra)
            if ONCE:
                break
            time.sleep(EVERY)


if __name__ == "__main__":
    main()
