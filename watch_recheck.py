"""TVibe Phase 3a — watchlist + scheduled recheck (client-side).

Stores snapshots in a local JSON file, re-calls /omni?view=agent after horizons,
logs CSV, optional Telegram when verdict/action changes.

Env:
  API_BASE     default https://signal-api-24q4.onrender.com
  WATCH_FILE   default watchlist.json
  LOG_CSV      default recheck_log.csv
  HORIZONS_H   default 1,6,24  (hours)
  GAP_S        default 4
  ONCE=1       process due items once and exit (good for cron)
  TG_TOKEN, TG_CHAT  optional alerts

Usage:
  python watch_recheck.py add <MINT> [<MINT>...]
  python watch_recheck.py list
  python watch_recheck.py run          # recheck due mints
  ONCE=1 python watch_recheck.py run   # for system cron every 15-30 min

NFA — snapshots only, not trade signals.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from typing import Any, Dict, List

import httpx

API = os.getenv("API_BASE", "https://signal-api-24q4.onrender.com").rstrip("/")
WATCH_FILE = os.getenv("WATCH_FILE", "watchlist.json")
LOG_CSV = os.getenv("LOG_CSV", "recheck_log.csv")
GAP = max(1.0, float(os.getenv("GAP_S", "4")))
ONCE = os.getenv("ONCE", "1").lower() in ("1", "true", "yes")
TG_TOKEN, TG_CHAT = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT")
HORIZONS = [
    int(x) for x in os.getenv("HORIZONS_H", "1,6,24").split(",") if x.strip().isdigit()
]
if not HORIZONS:
    HORIZONS = [1, 6, 24]


def load_watch() -> Dict[str, Any]:
    if not os.path.exists(WATCH_FILE):
        return {"mints": {}}
    with open(WATCH_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_watch(data: Dict[str, Any]) -> None:
    with open(WATCH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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
        print("tg_err", e.__class__.__name__, flush=True)


def fetch_agent(client: httpx.Client, mint: str) -> Dict[str, Any] | None:
    r = client.get(f"{API}/omni", params={"mint": mint, "view": "agent"}, timeout=45.0)
    if r.status_code in (429, 503, 504):
        print(f"{mint[:8]} http={r.status_code} — backoff", flush=True)
        time.sleep(min(30, 5 + r.status_code % 10))
        return None
    if r.status_code >= 400:
        print(f"{mint[:8]} http={r.status_code}", flush=True)
        return None
    d = r.json()
    return d if isinstance(d, dict) else None


def snapshot(d: Dict[str, Any]) -> Dict[str, Any]:
    dec = d.get("decision") if isinstance(d.get("decision"), dict) else {}
    return {
        "ts": int(time.time()),
        "action": d.get("action"),
        "verdict": dec.get("verdict") or d.get("verdict"),
        "filter_pass": (d.get("filter") or {}).get("pass")
        if isinstance(d.get("filter"), dict)
        else None,
        "risk_score": dec.get("risk_score")
        if dec.get("risk_score") is not None
        else d.get("risk_score"),
        "rules_version": d.get("rules_version"),
    }


def log_csv(mint: str, horizon_h: int | None, snap: Dict[str, Any], prev: Dict | None) -> None:
    new = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(
                [
                    "ts",
                    "mint",
                    "horizon_h",
                    "action",
                    "verdict",
                    "filter_pass",
                    "risk_score",
                    "prev_verdict",
                    "rules_version",
                ]
            )
        w.writerow(
            [
                snap["ts"],
                mint,
                horizon_h,
                snap.get("action"),
                snap.get("verdict"),
                snap.get("filter_pass"),
                snap.get("risk_score"),
                (prev or {}).get("verdict"),
                snap.get("rules_version"),
            ]
        )


def cmd_add(mints: List[str]) -> None:
    data = load_watch()
    store = data.setdefault("mints", {})
    with httpx.Client() as client:
        for mint in mints:
            mint = mint.strip()
            if len(mint) < 32:
                print("skip invalid", mint)
                continue
            d = fetch_agent(client, mint)
            if not d:
                print("add failed", mint[:8])
                continue
            snap = snapshot(d)
            entry = store.get(mint) or {
                "first_ts": snap["ts"],
                "last": snap,
                "history": [],
                "pending_horizons": list(HORIZONS),
            }
            if mint not in store:
                entry["first_ts"] = snap["ts"]
                entry["pending_horizons"] = list(HORIZONS)
            entry["last"] = snap
            entry.setdefault("history", []).append(snap)
            store[mint] = entry
            log_csv(mint, 0, snap, None)
            print(
                f"added {mint[:8]}… action={snap.get('action')} verdict={snap.get('verdict')} risk={snap.get('risk_score')}",
                flush=True,
            )
            time.sleep(GAP)
    save_watch(data)


def cmd_list() -> None:
    data = load_watch()
    for mint, e in (data.get("mints") or {}).items():
        last = e.get("last") or {}
        print(
            f"{mint} pending={e.get('pending_horizons')} last={last.get('verdict')} risk={last.get('risk_score')}"
        )


def cmd_run() -> None:
    data = load_watch()
    store = data.get("mints") or {}
    now = time.time()
    with httpx.Client() as client:
        for mint, e in list(store.items()):
            first = float(e.get("first_ts") or 0)
            pending: List[int] = list(e.get("pending_horizons") or [])
            due = [h for h in pending if now - first >= h * 3600]
            if not due:
                continue
            # one recheck can satisfy all due horizons at once
            d = fetch_agent(client, mint)
            if not d:
                time.sleep(GAP)
                continue
            snap = snapshot(d)
            prev = e.get("last")
            for h in due:
                log_csv(mint, h, snap, prev if isinstance(prev, dict) else None)
            if prev and isinstance(prev, dict):
                if prev.get("verdict") and prev.get("verdict") != snap.get("verdict"):
                    alert(
                        client,
                        f"TVibe recheck verdict: {prev.get('verdict')} -> {snap.get('verdict')}\n"
                        f"action={snap.get('action')} risk={snap.get('risk_score')}\n{mint}\n"
                        f"horizons_due={due}h\nNFA",
                    )
            e["last"] = snap
            e.setdefault("history", []).append(snap)
            e["pending_horizons"] = [h for h in pending if h not in due]
            # optional: roll next day horizon
            store[mint] = e
            print(
                f"recheck {mint[:8]}… due={due}h verdict={snap.get('verdict')} risk={snap.get('risk_score')}",
                flush=True,
            )
            time.sleep(GAP)
    data["mints"] = store
    save_watch(data)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    cmd = sys.argv[1].lower()
    if cmd == "add":
        cmd_add(sys.argv[2:])
    elif cmd == "list":
        cmd_list()
    elif cmd == "run":
        cmd_run()
        if not ONCE:
            print("ONCE=0 not looping — use external cron to call run", flush=True)
    else:
        print("unknown command", cmd)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
