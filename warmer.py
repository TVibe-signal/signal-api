"""TVibe cache warmer + CSV log + optional Telegram (client-side).

Fibonacci backoff on 429/503/502 between mint fetches.

Env:
  API_BASE, WATCH_MINTS, EVERY_S (default 900), GAP_S (default 4)
  ONCE=1, VIEW=agent, TG_TOKEN, TG_CHAT, LOG_CSV, HTTP_RETRIES (default 4)

NFA.
"""
from __future__ import annotations

import csv
import os
import time
from typing import Dict, List

import httpx

try:
    from retry_fib import fib_sleep
except ImportError:
    from examples.retry_fib import fib_sleep  # type: ignore

API = os.getenv("API_BASE", "https://signal-api-24q4.onrender.com").rstrip("/")
EVERY = max(60, int(os.getenv("EVERY_S", "900")))
GAP = max(1.0, float(os.getenv("GAP_S", "4")))
ONCE = os.getenv("ONCE", "").lower() in ("1", "true", "yes")
VIEW = (os.getenv("VIEW", "agent") or "agent").strip().lower()
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT = os.getenv("TG_CHAT")
LOG = os.getenv("LOG_CSV", "log.csv")
HTTP_RETRIES = max(0, int(os.getenv("HTTP_RETRIES", "4")))

_last: Dict[str, str] = {}


def load_mints() -> List[str]:
    mints = [m.strip() for m in os.getenv("WATCH_MINTS", "").split(",") if m.strip()]
    if os.path.exists("mints.txt"):
        with open("mints.txt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    mints.append(line)
    # dedupe keep order
    seen = set()
    out = []
    for m in mints:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def log_row(mint: str, d: dict) -> None:
    row = {
        "ts": int(time.time()),
        "mint": mint,
        "action": d.get("action"),
        "verdict": d.get("verdict"),
        "pass": (d.get("filter") or {}).get("pass") if isinstance(d.get("filter"), dict) else None,
        "risk_score": d.get("risk_score"),
    }
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def alert(client: httpx.Client, text: str) -> None:
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        client.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text[:3500]},
            timeout=20.0,
        )
    except Exception:
        pass


def warm_one(client: httpx.Client, mint: str) -> int:
    params = {"mint": mint}
    if VIEW == "agent":
        params["view"] = "agent"
    last_status = 0
    d = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            r = client.get(f"{API}/omni", params=params, timeout=45.0)
            last_status = r.status_code
            if r.status_code in (429, 503, 502) and attempt < HTTP_RETRIES:
                time.sleep(fib_sleep(attempt))
                continue
            if r.status_code != 200:
                print(mint[:8], "HTTP", r.status_code)
                return r.status_code
            d = r.json()
            if not isinstance(d, dict):
                print(mint[:8], "bad_json")
                return 500
            break
        except Exception as e:
            if attempt < HTTP_RETRIES:
                time.sleep(fib_sleep(attempt))
                continue
            print(mint[:8], "ERR", type(e).__name__)
            return 0
    if d is None:
        print(mint[:8], "HTTP", last_status or "fail")
        return last_status or 0

    log_row(mint, d)
    key = f"{d.get('action')}|{d.get('verdict')}|{(d.get('filter') or {}).get('pass')}"
    prev = _last.get(mint)
    _last[mint] = key
    print(
        mint[:8],
        d.get("action"),
        d.get("verdict"),
        "risk=",
        d.get("risk_score"),
        "pass=",
        (d.get("filter") or {}).get("pass") if isinstance(d.get("filter"), dict) else None,
    )
    if prev and prev != key:
        alert(client, f"TVibe change {mint[:12]}… {prev} → {key}")
    return 200


def main() -> None:
    mints = load_mints()
    if not mints:
        print("No mints. Set WATCH_MINTS or mints.txt")
        return
    print("warmer mints=", len(mints), "every", EVERY, "gap", GAP, "fib_retries", HTTP_RETRIES, "NFA")
    with httpx.Client() as client:
        while True:
            for m in mints:
                warm_one(client, m)
                time.sleep(GAP)
            if ONCE:
                break
            time.sleep(EVERY)


if __name__ == "__main__":
    main()
