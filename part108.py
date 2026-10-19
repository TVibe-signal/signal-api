# ---------- v2.90.1: Remaining plan — outcome labels + agent honesty (reviewed) ----------
# 1) resolve_due -> on_outcome_for_si / shadow_avoid / prerug labels (judged > 0)
# 2) decision.valid_for_s always set
# 3) would_change_my_mind filled from unknowns/blockers when empty
# 4) survival_note: pointer only (no new DNA/persona)
# Review fixes vs v2.90.0:
#   - never label a token "bad" because the price fetch FAILED (old code did: failed fetch -> pair None -> bad)
#   - SOL no longer added to the DexScreener request (it crowded out the real tokens and was never used)
#   - pick_best_pair errors fall back to the highest-liquidity pair instead of failing every token
#   - snapshots with no usable start price AND no start liquidity are skipped (cannot be judged)
#   - each snapshot is labelled at most once; callbacks are called once (no blind retry on TypeError)
VERSION = "2.90.1"
app.version = VERSION
app.openapi_schema = None

import inspect
import time
from typing import Any, Dict, List, Optional

_prev_resolve_108 = resolve_due
_LABELED_108: set = set()
_STAT_108 = {"labeled": 0, "bad": 0, "skipped_unjudgeable": 0, "skipped_fetch_failed": 0}


def _call_cb(cb, client, mint, bad, meta):
    """Call an outcome callback once, with the signature it actually has."""
    try:
        params = inspect.signature(cb).parameters.values()
    except (TypeError, ValueError):
        params = []
    plist = list(params)
    takes_meta = len(plist) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in plist)
    return cb(client, mint, bad, meta) if takes_meta else cb(client, mint, bad)


def _best_pair_108(pairs: list, mint: str) -> Optional[dict]:
    cand = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not cand:
        return None
    fn = globals().get("pick_best_pair")
    if callable(fn):
        try:
            r = fn(cand, mint)
            if r is not None:
                return r
        except Exception:
            pass

    def liq(p):
        try:
            return float((p.get("liquidity") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(cand, key=liq)


# ---- 1) Wrap resolve_due so labels actually land ----
async def resolve_due(client: "httpx.AsyncClient") -> int:
    snaps: List[dict] = []
    try:
        now = int(time.time())
        batch = int(globals().get("RESOLVE_BATCH") or 20)
        got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", now, "LIMIT", 0, batch]])
        ids = [i for i in ((got or [[]])[0] or []) if i not in _LABELED_108]
        if ids:
            hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
            for i, h in zip(ids, hashes or []):
                d = to_dict(h)
                if d.get("mint"):
                    d["_id"] = i
                    snaps.append(d)
    except Exception as e:
        print(f"[part108] pre-resolve: {e}")

    n = await _prev_resolve_108(client)
    if not snaps:
        return n

    try:
        mints = sorted({d["mint"] for d in snaps})
        best: Optional[Dict[str, Optional[dict]]] = None  # None = fetch failed -> do not label anything
        try:
            resp = await client.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(mints))
            if getattr(resp, "status_code", 200) != 200:
                raise RuntimeError(f"dexscreener status {resp.status_code}")
            pairs = (resp.json() or {}).get("pairs") or []
            if pairs:
                best = {m: _best_pair_108(pairs, m) for m in mints}
        except Exception as e:
            print(f"[part108] price fetch: {e}")
        if best is None:
            _STAT_108["skipped_fetch_failed"] += len(snaps)
            return n  # retry next cycle; a failed fetch is not evidence the token died

        bad_ret = float(globals().get("BAD_RETURN_PCT") or -50)
        bad_liq = float(globals().get("BAD_LIQ_RATIO") or 0.3)
        horizon = int(globals().get("PRED_HORIZON_S") or 86400)
        now = int(time.time())

        for d in snaps:
            mint, sid = d.get("mint"), d.get("_id")
            if not mint:
                continue
            if len(_LABELED_108) > 5000:
                _LABELED_108.clear()
            if sid is not None:
                _LABELED_108.add(sid)
            if now - int(float(d.get("ts") or 0)) > horizon * 3:
                continue
            try:
                p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
            except (TypeError, ValueError):
                p0, l0 = 0.0, 0.0
            if p0 <= 0 and l0 <= 0:
                _STAT_108["skipped_unjudgeable"] += 1  # snapshot has no start price/liquidity: cannot judge
                continue
            pair = best.get(mint)
            if pair is None:
                ret, liq_ratio = -100.0, 0.0  # pair is gone
            else:
                try:
                    p1 = float(pair.get("priceUsd") or 0)
                    l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
                except (TypeError, ValueError):
                    p1, l1 = 0.0, 0.0
                ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
                liq_ratio = l1 / l0 if l0 > 0 else 1.0
            bad = bool(ret <= bad_ret or liq_ratio <= bad_liq)
            _STAT_108["labeled"] += 1
            _STAT_108["bad"] += 1 if bad else 0

            names = ("on_outcome_for_si", "shadow_avoid_on_outcome", "prerug_on_outcome", "residual_on_outcome")
            for name in names:
                cb = globals().get(name)
                if callable(cb):
                    try:
                        await _call_cb(cb, client, mint, bad, {"source": "part108"})
                    except Exception as e:
                        print(f"[part108] {name}: {e}")
    except Exception as e:
        print(f"[part108] post-resolve: {e}")
    return n


# ---- 2–4) Honesty fields on every signal ----
def _valid_for_s(r: dict) -> int:
    conf = (r.get("data_quality") or {}).get("data_confidence")
    try:
        c = float(conf) if conf is not None else 0.7
    except (TypeError, ValueError):
        c = 0.7
    if c >= 0.95:
        return 120
    if c >= 0.8:
        return 60
    if c >= 0.6:
        return 30
    return 15


def _would_change(r: dict) -> List[str]:
    out: List[str] = []
    existing = r.get("would_change_my_mind")
    if isinstance(existing, list) and existing:
        return [str(x) for x in existing][:8]
    dec = r.get("decision") if isinstance(r.get("decision"), dict) else {}
    for u in (dec.get("unknowns") or [])[:4]:
        out.append(f"Resolve: {u}")
    for b in (dec.get("blockers") or [])[:3]:
        out.append(f"Blocker present: {b}")
    if not out:
        out.append("New on-chain evidence (mint/freeze/LP) or large liquidity change.")
        out.append("Clearer market data (end Dex rate-limit / full rugcheck).")
    return out[:8]


def _survival_note(r: dict) -> Optional[dict]:
    return {
        "basis": "measured_cohort",
        "note": "Use early_horizons / survival on /stats and card; not a per-token forecast.",
        "horizons": ["1h", "6h", "24h"],
    }


_build_prev_108 = build_signal


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_108(client, mint, security, *args, **kwargs)
    try:
        r, status = (res[0], res[1]) if isinstance(res, tuple) and len(res) == 2 else (res, "ok")
        if not isinstance(r, dict):
            return res
        dec = r.get("decision")
        if not isinstance(dec, dict):
            dec = {}
            r["decision"] = dec
        if dec.get("verdict") is None and r.get("verdict"):
            dec["verdict"] = r["verdict"]
        if dec.get("risk_score") is None and r.get("risk_score") is not None:
            dec["risk_score"] = r["risk_score"]
        vfs = _valid_for_s(r)
        dec["valid_for_s"] = vfs
        r["valid_for_s"] = vfs
        wcm = _would_change(r)
        r["would_change_my_mind"] = wcm
        dec["would_change_my_mind"] = wcm
        if not r.get("survival_meta"):
            r["survival_meta"] = _survival_note(r)
        return (r, status) if isinstance(res, tuple) else r
    except Exception as e:
        print(f"[part108] honesty wrap: {e}")
        return res


print(f"[part108] v{VERSION} resolve->labels (safe) . valid_for_s . would_change_my_mind")
