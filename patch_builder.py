"""patch_builder.py — TVibe deep verdict engine (Filter Core).

Applied by main.py BEFORE patch_live_fix. Sets g["full_builder"] and
g["omni_impl"] to _build().

Sources (all public, keyless): DexScreener, RugCheck, Jupiter.
Scoring is points-based and transparent: every flag carries its reason,
and the packet lists blockers / cautions / positives / unknowns.

Rules that never bend:
- PASS needs authorities verified (RugCheck OK + mint + freeze revoked).
- If RugCheck is down, the verdict caps at REVIEW — never PASS on hope.
- Two-stage check (Filter v4): a first-seen PASS waits 15 min -> REVIEW.
- No source may crash the engine: every fetch is guarded, every field
  access is defensive. A dead source degrades, never kills.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEX = "https://api.dexscreener.com/latest/dex/tokens/"
RUG = "https://api.rugcheck.xyz/v1/tokens/"
JUP = "https://quote-api.jup.ag/v6/quote"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
UA = {"User-Agent": "TVibe-FILTER/1.0"}
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_FIRST_SEEN = {}


def _get(url, timeout=6):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore") or "{}")
    except Exception:
        return None


def _num(x):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except Exception:
        return None


def _pick(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _dex_parse(raw, mint):
    pairs = []
    for p in ((raw or {}).get("pairs") or []):
        if not isinstance(p, dict):
            continue
        bt = p.get("baseToken") or {}
        if (bt.get("address") if isinstance(bt, dict) else None) == mint:
            pairs.append(p)
    if not pairs:
        return None
    lo = lambda p: (_num((p.get("liquidity") or {}).get("usd")) if isinstance(p.get("liquidity"), dict) else None) or 0
    best = max(pairs, key=lo)
    txns = best.get("txns") or {}
    tx5 = txns.get("m5") if isinstance(txns, dict) else None
    tx5 = tx5 if isinstance(tx5, dict) else {}
    try:
        created = float(best.get("pairCreatedAt")) if best.get("pairCreatedAt") is not None else None
    except Exception:
        created = None
    vol = best.get("volume") or {}
    qt = best.get("quoteToken") or {}
    return {"pair": best.get("dexId"), "quote": qt.get("symbol") if isinstance(qt, dict) else None,
            "liquidity": lo(best), "price": _num(best.get("priceUsd")),
            "volume24": _num(vol.get("h24")) if isinstance(vol, dict) else None,
            "age_h": ((time.time() * 1000 - created) / 3600000) if created else None,
            "trades5m": (_num(tx5.get("buys")) or 0) + (_num(tx5.get("sells")) or 0)}


def _rug_parse(raw):
    r = raw or {}
    if not isinstance(r, dict) or r.get("error") or not any(
            k in r for k in ("score", "score_normalised", "risks", "tokenMeta",
                             "mintAuthority", "freezeAuthority", "topHolders")):
        return None
    meta = r.get("tokenMeta") or {}
    top = r.get("topHolders") or []
    top_pct = _num(_pick(top[0], "pct", "percent")) if top and isinstance(top[0], dict) else None
    lp_pct = None
    for mk in (r.get("markets") or []):
        if isinstance(mk, dict):
            lp = mk.get("lp") or {}
            if isinstance(lp, dict):
                lp_pct = _num(_pick(lp, "lpLockedPct", "lockedPct"))
                if lp_pct is not None:
                    break
    rn = _num(_pick(r, "score_normalised", "scoreNormalized"))
    sc = _num(r.get("score"))
    if rn is None and sc is not None:
        rn = sc / 100.0 if sc > 100 else sc
    if rn is not None:
        rn = max(0.0, min(100.0, rn))
    return {"score": rn, "risks": r.get("risks") or [],
            "mint_auth": _pick(r, "mintAuthority", "mint_authority"),
            "freeze_auth": _pick(r, "freezeAuthority", "freeze_authority"),
            "mint_known": ("mintAuthority" in r) or ("mint_authority" in r),
            "freeze_known": ("freezeAuthority" in r) or ("freeze_authority" in r),
            "top_pct": top_pct, "holders": _num(r.get("totalHolders")),
            "lp_pct": lp_pct, "decimals": _num(meta.get("decimals")) if isinstance(meta, dict) else None}


def _jup(mint, price, decimals):
    if not price or price <= 0 or decimals is None or decimals < 0 or decimals > 18:
        return None
    try:
        amount = int(100.0 / price * (10 ** int(decimals)))
    except Exception:
        return None
    if amount <= 0:
        return None
    q = _get(JUP + "?inputMint=" + mint + "&outputMint=" + USDC + "&amount=" + str(amount) + "&slippageBps=100", timeout=5) or {}
    out = _num(q.get("outAmount"))
    if out is None:
        return None
    received = out / 1e6
    return {"sell_usd": 100.0, "received_usd": round(received, 2),
            "slippage_pct": round(max(0.0, (100.0 - received) / 100.0 * 100.0), 2)}


def _build(mint):
    mint = (mint or "").strip()
    try:
        if not MINT_RE.match(mint):
            return {"mint": mint, "verdict": "SKIP", "error": "invalid_mint",
                    "note": "Not a Solana mint (32-44 base58 chars).", "nfa": True, "engine": "full"}
        try:
            with ThreadPoolExecutor(max_workers=2) as ex:
                df = ex.submit(_get, DEX + mint)
                rf = ex.submit(_get, RUG + mint + "/report")
                dex_raw = df.result() or {}
                rug_raw = rf.result() or {}
        except Exception:
            dex_raw, rug_raw = {}, {}
        dx = _dex_parse(dex_raw, mint)
        if dx is None:
            return {"mint": mint, "verdict": "SKIP", "error": "no_pair",
                    "note": "DexScreener returned no pairs for this mint.",
                    "nfa": True, "engine": "full"}
        rg = _rug_parse(rug_raw)
        jp = _jup(mint, dx["price"], rg["decimals"] if rg else None)
        risk, blockers, cautions, positives, unknowns, signals = 0, [], [], [], [], []
        liq, price = dx["liquidity"], dx["price"]
        # --- authorities (RugCheck) ---
        if rg is not None:
            if rg["mint_known"]:
                if rg["mint_auth"]:
                    risk += 35; blockers.append("Mint authority still active — dev can mint more tokens"); signals.append("mint_active")
                else:
                    positives.append("Mint authority revoked"); signals.append("mint_revoked")
            else:
                unknowns.append("Mint authority unknown")
            if rg["freeze_known"]:
                if rg["freeze_auth"]:
                    risk += 20; cautions.append("Freeze authority still active — holders can be frozen"); signals.append("freeze_active")
                else:
                    positives.append("Freeze authority revoked"); signals.append("freeze_revoked")
            else:
                unknowns.append("Freeze authority unknown")
            if rg["score"] is not None:
                risk += rg["score"] * 0.3
            for rs in rg["risks"]:
                if not isinstance(rs, dict):
                    continue
                nm = rs.get("name") or "RugCheck risk"
                lv = str(rs.get("level") or "").lower()
                if lv == "danger":
                    risk += 8; blockers.append("RugCheck: " + str(nm))
                elif lv == "warn":
                    risk += 4; cautions.append("RugCheck: " + str(nm))
            tp = rg["top_pct"]
            if tp is not None:
                if tp > 50:
                    risk += 25; blockers.append("Top holder owns %.0f%% — extreme concentration" % tp); signals.append("dominant_holder")
                elif tp > 20:
                    risk += 15; cautions.append("Top holder owns %.0f%% — concentration risk" % tp); signals.append("dominant_holder")
                elif tp < 10:
                    positives.append("No dominant holder"); signals.append("holders_distributed")
            lp = rg["lp_pct"]
            if lp is not None:
                if lp < 50:
                    risk += 10; cautions.append("LP lock below 50%"); signals.append("lp_low_lock")
                elif lp >= 90:
                    positives.append("LP mostly locked"); signals.append("lp_locked")
            else:
                unknowns.append("LP lock status unknown")
        else:
            unknowns.append("RugCheck unavailable — authorities not verified")
        # --- market (DexScreener) ---
        if liq < 5000:
            risk += 25; cautions.append("Liquidity extremely low — hard to exit"); signals.append("very_low_liquidity")
        elif liq < 20000:
            risk += 15; cautions.append("Liquidity low"); signals.append("low_liquidity")
        elif liq < 100000:
            risk += 5
        else:
            positives.append("Healthy liquidity")
        if dx["trades5m"] == 0:
            risk += 10; cautions.append("No recent trades"); signals.append("no_recent_trades")
        ah = dx["age_h"]
        if ah is not None:
            if ah < 1:
                risk += 15; cautions.append("Pair created less than 1h ago"); signals.append("new_pair")
            elif ah < 24:
                risk += 10; cautions.append("Pair created less than 24h ago"); signals.append("new_pair")
            elif ah > 24 * 7:
                positives.append("Pair older than 7 days")
        # --- exit (Jupiter) ---
        if jp is not None:
            if jp["slippage_pct"] > 5:
                risk += 15; cautions.append("Exit slippage %.1f%% on a $100 sell" % jp["slippage_pct"]); signals.append("high_exit_slippage")
            elif jp["slippage_pct"] <= 2:
                positives.append("Low exit slippage"); signals.append("low_exit_slippage")
        else:
            unknowns.append("Exit cost not checked")
        risk = max(0, min(100, int(round(risk))))
        auth_ok = bool(rg and rg["mint_known"] and rg["freeze_known"] and not rg["mint_auth"] and not rg["freeze_auth"])
        if blockers and risk >= 65:
            verdict = "AVOID"
        elif blockers or risk >= 60:
            verdict = "CAUTION"
        elif risk >= 35:
            verdict = "REVIEW"
        elif auth_ok:
            verdict = "PASS"
        else:
            verdict = "REVIEW"
        # --- two-stage check (Filter v4): first-seen PASS waits 15 min ---
        note = None
        if verdict == "PASS":
            now = time.time()
            first = _FIRST_SEEN.get(mint)
            if first is None:
                _FIRST_SEEN[mint] = now
                first = now
            if len(_FIRST_SEEN) > 2000:
                for _k in [_k for _k, _v in _FIRST_SEEN.items() if now - _v > 3600]:
                    del _FIRST_SEEN[_k]
            if now - first < 900:
                verdict = "REVIEW"; risk = max(risk, 35)
                cautions.append("First seen less than 15 min ago — two-stage check, re-check after 15 min")
                signals.append("two_stage_hold")
                note = "First seen less than 15 min ago — two-stage check, re-check after 15 min."
        elif not auth_ok and verdict == "REVIEW" and risk < 35 and not blockers:
            note = "Authorities not fully verified — verdict capped at REVIEW."
        return {"mint": mint, "verdict": verdict, "risk": risk, "risk_score": risk,
                "liquidity": liq, "liquidity_usd": liq, "price": price, "price_usd": price,
                "volume24": dx["volume24"], "pair": dx["pair"], "quote": dx["quote"],
                "signals": signals, "blockers": blockers, "cautions": cautions,
                "positives": positives, "unknowns": unknowns,
                "authorities": {"mint": ("active" if rg and rg["mint_auth"] else "revoked" if rg and rg["mint_known"] else "unknown"),
                                "freeze": ("active" if rg and rg["freeze_auth"] else "revoked" if rg and rg["freeze_known"] else "unknown")},
                "holders": {"top_pct": rg["top_pct"] if rg else None, "total": rg["holders"] if rg else None},
                "lp": {"locked_pct": rg["lp_pct"] if rg else None},
                "exit_cost": jp, "note": note,
                "sources": {"dexscreener": True, "rugcheck": rg is not None, "jupiter": jp is not None},
                "nfa": True, "engine": "full"}
    except Exception as e:
        return {"mint": mint, "verdict": "SKIP", "error": "builder_failed",
                "detail": repr(e)[:200], "nfa": True, "engine": "full"}


def apply(g: dict) -> None:
    g["full_builder"] = _build
    g["omni_impl"] = _build
    print("[patch_builder] deep engine ready (DexScreener + RugCheck + Jupiter)")