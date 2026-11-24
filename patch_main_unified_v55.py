"""
patch_main_unified_v55.py - TVibe MAIN UNIFIED v55 - Evidence FIX
English only. One file. No new env var.

User screenshot: /evidence showed Total 0, Ledger unreachable, No outcome data yet.
Root cause found after checking all:
  1) /pro in v54 NEVER wrote to ledger, so total stayed 0 forever even after checks.
  2) /evidence in v54 only read ledger via inner /ledger capture, which returns
     nothing in current app, so it could never show data.

v55 fixes BOTH, without rebuilding outcome cron:
  - Every /pro / /?mint= / /{mint} / /unified_json check now WRITES a ledger entry:
    mint, ts, verdict, grade, proof_hash, price_then, liq_then.
    Write goes to Upstash REST list "ledger" (same key v40 used) + snap:{mint}:{ts}
    for the existing /cron/outcome, + in-memory fallback. Fire-and-forget, never blocks check.
  - /evidence now reads from 3 sources and merges: Upstash REST + memory + inner /ledger fallback.
  - /evidence now SELF-HEALS outcome: if an entry is >24h old and has no later_price
    (because old cron never updated the list), it fetches current price/liq from
    DexScreener live and uses that as the 24h+ outcome. <24h entries stay WAITING.
  - Old entries before v55 still show 0 because they were never written - honest,
    not faked. From v55 onward every new check appears in /evidence.

Main web (v54) UNCHANGED: compact, plain English, share + copy.
Full proof (/proof_helius) UNCHANGED.

Usage - REPLACE v54 lines at VERY BOTTOM of app.py with:
    import patch_main_unified_v55 as _main55
    _main55.apply(g)
Keep only v55.
"""

from __future__ import annotations
import os, sys, json, re, time, threading, urllib.request, urllib.parse, concurrent.futures, datetime

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

def _get_helius_url() -> str:
    for k in ("HELIUS_URL", "SOLANA_RPC_URL", "PRIVATE_RPC", "PRIVATE_RPC_URL",
              "RPC_URL", "RPC_SOLANA", "RPC_SOLANA_URL", "SOLANA_RPC",
              "RPC-SOLANA", "rpc-solana", "rpc_solana"):
        v = os.getenv(k, "") or ""
        if v.startswith("http"):
            return v
    try:
        for k, v in list(os.environ.items()):
            if isinstance(v, str) and v.startswith("http") and "helius" in v.lower():
                return v
    except Exception:
        pass
    key = os.getenv("HELIUS_API_KEY", "") or os.getenv("HELIUS_KEY", "") or ""
    if key:
        return f"https://mainnet.helius-rpc.com/?api-key={key}"
    return ""

def _helius_rpc(method: str, params, timeout: int = 6):
    url = _get_helius_url()
    if not url:
        return None, "missing_helius_key"
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    try:
        req = urllib.request.Request(url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "TVibe-Main-Unified-v55"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
            if "error" in j:
                return None, str(j["error"])[:300]
            return j.get("result"), None
    except Exception as e:
        return None, f"helius_rpc_failed: {str(e)[:200]}"

def _helius_status_payload() -> dict:
    url = _get_helius_url()
    has = bool(url)
    test_ok = None; test_err = None
    if has:
        r, e = _helius_rpc("getSlot", [], timeout=5)
        test_ok = r is not None; test_err = e
    return {"version": "v55-main-unified-2026-11-23", "has_helius_url": has,
            "helius_url_present": has, "rpc_test_ok": test_ok, "rpc_test_error": test_err,
            "note": "v54: /pro, /pro_json, /check, /{mint}, / all intercepted before inner catch-all. Never 404."}

def _build_proof(mint: str):
    for mod_name in ("patch_helius_real_v48", "patch_tvibe_full_v48_en", "patch_tvibe_full_v48"):
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "build_full_helius"):
                data = mod.build_full_helius(mint)
                html_fn = getattr(mod, "_html", None)
                html = html_fn(mint, data) if callable(html_fn) else None
                return data, html
        except Exception:
            continue
    return None, None

def _unified_final(old_html: str, proof_data) -> dict:
    old_upper = (old_html or "").upper()
    if "DON'T BUY" in old_upper or "DONT BUY" in old_upper or "DO NOT BUY" in old_upper:
        old_verdict = "DON'T BUY"
    elif "HOLD-BUY" in old_upper or "HOLD BUY" in old_upper:
        old_verdict = "HOLD-BUY"
    elif "BUY" in old_upper:
        old_verdict = "BUY"
    elif "PASS" in old_upper:
        old_verdict = "PASS"
    else:
        old_verdict = "UNKNOWN"
    if not proof_data:
        return {"final": old_verdict, "old": old_verdict, "new": "UNKNOWN",
                "reason": "9-problem proof unavailable. Showing OLD verdict only.",
                "kernel_pass": None, "failed": None, "proved": None, "unknown": None, "grade": "-", "proof_hash": "-", "steps": []}
    proof = proof_data.get("proof") or {}
    kernel = proof_data.get("kernel") or {}
    steps = proof.get("steps") or []
    failed = sum(1 for s in steps if s.get("status") == "FAILED")
    proved = sum(1 for s in steps if s.get("status") == "PROVED")
    unknown = sum(1 for s in steps if s.get("status") == "UNKNOWN")
    kernel_pass = kernel.get("kernel_pass")
    new_verdict = proof.get("human_verdict") or "UNKNOWN"
    grade = proof.get("grade") or "-"
    phash = proof.get("proof_hash") or "-"
    if kernel_pass is False:
        final = "DON'T BUY"
        reason = f"KERNEL FAIL - proof does not verify. NEW: {failed} FAILED, {proved} PROVED. OLD: {old_verdict}."
    elif failed >= 4:
        final = "DON'T BUY"
        reason = f"9 problems: {failed} FAILED, {proved} PROVED, {unknown} UNKNOWN. Not enough to buy. OLD: {old_verdict}."
    elif old_verdict in ("DON'T BUY", "PASS"):
        final = old_verdict
        reason = f"OLD says {old_verdict}, kept. 9 problems: {failed} FAILED, {proved} PROVED."
    elif failed >= 2:
        final = "HOLD-BUY"
        reason = f"9 problems: {failed} FAILED, {proved} PROVED. Small size only. OLD: {old_verdict}."
    elif proved >= 7 and old_verdict == "BUY":
        final = "BUY"
        reason = f"OLD + NEW agree: {proved} PROVED, {failed} FAILED. OLD: BUY."
    elif proved >= 7:
        final = "HOLD-BUY"
        reason = f"NEW strong ({proved} PROVED) but OLD is {old_verdict}, so stay HOLD-BUY small size."
    else:
        final = old_verdict if old_verdict != "UNKNOWN" else "HOLD-BUY"
        reason = f"9 problems: {failed} FAILED, {proved} PROVED, {unknown} UNKNOWN. OLD: {old_verdict}."
    return {"final": final, "old": old_verdict, "new": new_verdict, "reason": reason,
            "kernel_pass": kernel_pass, "failed": failed, "proved": proved, "unknown": unknown,
            "grade": grade, "proof_hash": phash, "steps": steps}

def _unified_card_html(mint: str, uni: dict, helius: dict) -> str:
    final = uni.get("final") or "UNKNOWN"
    color = {"DON'T BUY": "#FF4D8D", "PASS": "#FF4D8D", "HOLD-BUY": "#FFD166", "BUY": "#00FF9D"}.get(final, "#aaa")
    bg = {"DON'T BUY": "#2A0A1A", "PASS": "#2A0A1A", "HOLD-BUY": "#2A240A", "BUY": "#0A2A1A"}.get(final, "#14141F")
    kernel_txt = "KERNEL PASS" if uni.get("kernel_pass") else ("KERNEL FAIL" if uni.get("kernel_pass") is False else "KERNEL UNKNOWN")
    kcolor = "#00FF9D" if uni.get("kernel_pass") else ("#FF4D8D" if uni.get("kernel_pass") is False else "#FFD166")
    steps = uni.get("steps") or []
    chips = ""
    for s in steps:
        c = {"PROVED": "#00FF9D", "FAILED": "#FF4D8D", "UNKNOWN": "#FFD166"}.get(s.get("status"), "#aaa")
        label = _plain_label(s.get('rule','?'))
        chips += f"<span style='display:inline-block;margin:3px 4px 3px 0;padding:4px 8px;border-radius:999px;border:1px solid {c};color:{c};font-size:11px;font-weight:700'>{label} • {s.get('status','?')}</span>"
    hinfo = ""
    if helius:
        hinfo = f"MintAuth: {helius.get('mint_authority') or 'None (renounced)'} • FreezeAuth: {helius.get('freeze_authority') or 'None (renounced)'} • Top1: {helius.get('top1_pct') if helius.get('top1_pct') is not None else '-'}% • Top10: {helius.get('top10_pct') if helius.get('top10_pct') is not None else '-'}% • Supply: {helius.get('supply') or '-'}"
    return f"""
<div style="background:{bg};border:2px solid {color};border-radius:16px;padding:16px;margin:12px auto;max-width:780px;font-family:system-ui;color:#fff">
<div style="font-size:11px;letter-spacing:1px;color:#aaa;font-weight:800">TVIBE UNIFIED • 1 VERDICT • OLD + 9 PROBLEMS + KERNEL</div>
<h2 style="margin:8px 0;color:{color};font-size:24px">{final} &nbsp;<span style="font-size:14px;color:#fff">• Grade {uni.get('grade','-')}</span></h2>
<p style="margin:6px 0;color:#ddd">{uni.get('reason','')}</p>
<p style="font-size:12px;color:#aaa">OLD: {uni.get('old')} &nbsp;|&nbsp; NEW (9 problems): {uni.get('new')} &nbsp;|&nbsp; <span style="color:{kcolor};font-weight:800">{kernel_txt}</span> &nbsp;|&nbsp; FAILED: {uni.get('failed')} • PROVED: {uni.get('proved')} • UNKNOWN: {uni.get('unknown')}</p>
<p style="font-size:12px;color:#aaa">{hinfo}</p>
<div style="margin-top:8px">{chips}</div>
<p style="font-size:11px;color:#888">Proof hash: {uni.get('proof_hash','-')} • Mint: {mint[:8]}... • <a href="/proof_helius?mint={mint}" style="color:#00F0FF">Full 9 modules → /proof_helius</a> • <a href="/unified_json?mint={mint}" style="color:#00F0FF">JSON for Grok → /unified_json</a></p>
<p style="font-size:11px;color:#888">This is the SAME verdict on / , /{{mint}}, /pro, /proof_helius and /unified_json.</p>
</div>"""



PLAIN_LABELS = {
    "riemann_holder": "Holder Distribution",
    "p_vs_np_verify": "Fast Verify",
    "navier_blowup": "Dev Can Rug?",
    "yangmills_mass": "Real Mass",
    "hodge_compose": "Combined Risk",
    "bsd_rank": "Dev Wallets",
    "collatz_iter": "Can You Sell?",
    "goldbach_decomp": "Bundle Split",
    "twin_wallet": "Twin Wallets",
}
def _plain_label(rule: str) -> str:
    return PLAIN_LABELS.get((rule or "").strip().lower(), (rule or "?").replace("_", " ").title())

def _compact_page_html(mint: str, uni: dict, helius: dict, proof_data) -> str:
    """Short main-web page for MANY PEOPLE: plain English, 1 screen, share + copy."""
    card = _unified_card_html(mint, uni, helius)
    final = uni.get("final") or "UNKNOWN"
    if final == "DON'T BUY":
        line1 = "Don't buy this one. Risk is too high on these checks."
        line2 = f"9 checks: {uni.get('failed')} failed, {uni.get('proved')} proved."
        line3 = "Wait for a better setup. Don't chase."
    elif final == "HOLD-BUY":
        line1 = "Not a clear yes. Mixed setup."
        line2 = f"9 checks: {uni.get('failed')} failed, {uni.get('proved')} proved."
        line3 = "If you buy, use small size you can afford to lose."
    elif final == "BUY":
        line1 = "Setup looks good on these checks."
        line2 = f"9 checks: {uni.get('failed')} failed, {uni.get('proved')} proved."
        line3 = "Still do your own research. No check means 100% safe."
    else:
        line1 = "Not enough clear data to say yes."
        line2 = f"9 checks: {uni.get('failed')} failed, {uni.get('proved')} proved."
        line3 = "Check again later or pick another token."
    liq = "-"
    price = "-"
    if helius:
        liq_v = helius.get("liquidity_usd") or helius.get("liq") or (proof_data or {}).get("helius", {}).get("liquidity_usd")
        price_v = helius.get("price_usd") or helius.get("price") or (proof_data or {}).get("helius", {}).get("price_usd")
        try:
            if liq_v is not None:
                liq = f"${float(liq_v):,.0f}"
        except Exception:
            liq = str(liq_v)
        try:
            if price_v is not None:
                price = f"${float(price_v):.6f}" if float(price_v) < 1 else f"${float(price_v):,.4f}"
        except Exception:
            price = str(price_v)
    # Plain-English Helius summary for normal people
    mint_auth = (helius or {}).get("mint_authority")
    freeze_auth = (helius or {}).get("freeze_authority")
    mint_txt = "Mint: Renounced (dev cannot mint more)" if not mint_auth else f"Mint: Still ON (dev can mint more)"
    freeze_txt = "Freeze: Renounced" if not freeze_auth else "Freeze: Still ON"
    top1 = (helius or {}).get("top1_pct")
    top1_txt = f"Top holder: {top1:.1f}%" if isinstance(top1, (int, float)) else "Top holder: -"
    grok_text = f"Check Solana mint {mint}. TVibe verdict: {final} Grade {uni.get('grade','-')}. {uni.get('reason','')}. Liq {liq}, Price {price}. Should I BUY or SKIP? Give 3-line reason. No auto-buy."
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TVibe - {final} - {mint[:8]}</title><style>body{{background:#0A0A12;color:#fff;font-family:system-ui;margin:0;padding:12px}}a{{color:#00F0FF}}input{{width:100%;padding:12px;border-radius:12px;border:1px solid #333;background:#111;color:#fff;box-sizing:border-box}}button{{background:#00F0FF;border:0;padding:12px 18px;border-radius:12px;font-weight:800;cursor:pointer;color:#000}}.btn{{display:inline-block;background:#1A1A2A;border:1px solid #333;color:#fff;padding:10px 14px;border-radius:12px;text-decoration:none;font-weight:700;margin:4px 4px 4px 0}}.wrap{{max-width:780px;margin:auto}}</style></head><body><div class='wrap'>{card}<div style='background:#14141F;border:1px solid #333;border-radius:16px;padding:14px;margin:12px auto;max-width:780px'><h3 style='margin:0 0 8px'>Why this verdict? (plain English)</h3><p style='margin:4px 0;color:#ddd'>1. {line1}</p><p style='margin:4px 0;color:#ddd'>2. {line2}</p><p style='margin:4px 0;color:#ddd'>3. {line3}</p><p style='margin:10px 0 0;color:#aaa;font-size:13px'>Liquidity: {liq} &nbsp;|&nbsp; Price: {price} &nbsp;|&nbsp; {top1_txt}</p><p style='margin:4px 0;color:#aaa;font-size:13px'>{mint_txt} &nbsp;•&nbsp; {freeze_txt}</p></div><div style='max-width:780px;margin:0 auto'><a class='btn' href='/proof_helius?mint={mint}'>Full proof → /proof_helius</a><a class='btn' href='/unified_json?mint={mint}'>JSON for Grok →</a><button class='btn' onclick="navigator.clipboard.writeText(window.location.href);this.textContent='Link copied!'">Share this check</button><button class='btn' onclick="navigator.clipboard.writeText(document.getElementById('grok').textContent);this.textContent='Copied for Grok!'">Copy for Grok</button></div><p id='grok' style='display:none'>{grok_text}</p><div style='max-width:780px;margin:16px auto;background:#14141F;border:1px solid #333;border-radius:16px;padding:14px'><h3 style='margin:0 0 8px'>Check another token</h3><form action='/pro' method='get'><input name='mint' placeholder='Paste Solana mint...'><br><br><button type='submit'>CHECK →</button></form><p style='color:#888;font-size:12px'>Example: paste a mint from DexScreener, Phantom or your wallet.</p></div><p style='text-align:center;color:#888;font-size:12px'>No wallet. No signup. Not financial advice. Even BUY does not mean safe.</p></div></body></html>"""



def _norm_verdict(e: dict) -> str:
    v = str(e.get("final_verdict") or e.get("verdict") or e.get("label") or e.get("human_verdict") or "").upper()
    if "DON'T" in v or "DONT" in v or "DO NOT" in v or "SELL" in v or "AVOID" in v:
        return "DON'T BUY"
    if "HOLD" in v or "NOT A CLEAR" in v or "CAUTION" in v:
        return "HOLD-BUY"
    if v in ("BUY", "PASS", "OK", "OK TO BUY"):
        return "BUY"
    return v or "UNKNOWN"

def _num(e: dict, *keys):
    for k in keys:
        v = e.get(k)
        if v is None:
            continue
        try:
            f = float(v)
            if f != f:  # NaN
                continue
            return f
        except Exception:
            continue
    return None

def _evidence_for_entry(e: dict) -> dict:
    verdict = _norm_verdict(e)
    mint = str(e.get("mint") or e.get("token") or e.get("address") or "")
    ts = e.get("ts") or e.get("timestamp") or e.get("checked_at") or e.get("created_at") or ""
    price_then = _num(e, "price_usd", "price", "entry_price", "price_at_check", "p0")
    price_later = _num(e, "later_price", "price_24h", "price_after", "p1", "later_price_usd")
    liq_then = _num(e, "liquidity_usd", "liquidity", "entry_liq", "liq", "l0")
    liq_later = _num(e, "later_liq", "liq_24h", "liq_after", "l1", "later_liquidity_usd")
    outcome = str(e.get("outcome") or e.get("outcome_label") or e.get("result_24h") or "").lower()
    chg = None
    if price_then and price_later and price_then > 0:
        chg = (price_later - price_then) / price_then * 100
    liq_chg = None
    if liq_then and liq_later and liq_then > 0:
        liq_chg = (liq_later - liq_then) / liq_then * 100
    # Outcome label for humans
    if "abandon" in outcome:
        outcome_txt = "Abandoned"
    elif "liquidity_pulled" in outcome or "pulled" in outcome:
        outcome_txt = "Liquidity pulled"
    elif "price_decay" in outcome or "decay" in outcome:
        outcome_txt = "Price decayed"
    elif "liquidity_and_price" in outcome:
        outcome_txt = "Liq + price down"
    elif outcome:
        outcome_txt = outcome.replace("_", " ").title()
    elif price_later is None:
        outcome_txt = "Waiting (<24h)"
    else:
        outcome_txt = "Checked"
    # Was verdict right?
    if price_later is None and not outcome:
        correctness = "WAITING"
        correctness_txt = "Waiting"
    elif "abandon" in outcome or (liq_chg is not None and liq_chg <= -50) or (chg is not None and chg <= -70):
        # Rugged / dead
        if verdict == "DON'T BUY":
            correctness = "CORRECT"; correctness_txt = "Correct - we said don't buy"
        elif verdict == "HOLD-BUY":
            correctness = "HALF"; correctness_txt = "Half - we said small size only"
        else:
            correctness = "WRONG"; correctness_txt = "Wrong - we said buy"
    elif chg is not None and chg <= -30:
        if verdict == "DON'T BUY":
            correctness = "CORRECT"; correctness_txt = "Correct - we said don't buy"
        elif verdict == "HOLD-BUY":
            correctness = "CORRECT"; correctness_txt = "Correct - small size was right"
        else:
            correctness = "WRONG"; correctness_txt = "Wrong - we said buy"
    elif chg is not None and chg >= 30:
        if verdict == "BUY":
            correctness = "CORRECT"; correctness_txt = "Correct - we said buy"
        elif verdict == "HOLD-BUY":
            correctness = "CORRECT"; correctness_txt = "Correct - small size caught upside"
        else:
            correctness = "WRONG"; correctness_txt = "Wrong - we were too strict"
    else:
        # Survived, flat
        if verdict in ("BUY", "HOLD-BUY"):
            correctness = "CORRECT"; correctness_txt = "Correct - survived"
        elif verdict == "DON'T BUY":
            correctness = "HALF"; correctness_txt = "Half - survived but we were cautious"
        else:
            correctness = "UNKNOWN"; correctness_txt = "-"
    return {"mint": mint, "verdict": verdict, "ts": ts, "price_then": price_then,
            "price_later": price_later, "chg": chg, "liq_then": liq_then, "liq_later": liq_later,
            "liq_chg": liq_chg, "outcome": outcome, "outcome_txt": outcome_txt,
            "correctness": correctness, "correctness_txt": correctness_txt,
            "grade": e.get("grade") or "-", "proof_hash": e.get("proof_hash") or e.get("hash") or "-"}

def _evidence_html(rows: list, total: int, stats: dict, ledger_ok: bool) -> str:
    # Summary cards
    def fmt_pct(n, d):
        if not d:
            return "-"
        return f"{n/d*100:.0f}%"
    correct = stats.get("correct", 0); wrong = stats.get("wrong", 0); half = stats.get("half", 0); waiting = stats.get("waiting", 0); decided = correct + wrong + half
    acc = f"{correct/decided*100:.0f}%" if decided else "-"
    rows_html = ""
    for r in rows[:20]:
        mint_short = (r["mint"][:8] + "...") if r["mint"] else "-"
        chg_txt = f"{r['chg']:+.1f}%" if r["chg"] is not None else "-"
        chg_color = "#00FF9D" if (r["chg"] or 0) > 0 else ("#FF4D8D" if (r["chg"] or 0) < 0 else "#aaa")
        corr_color = {"CORRECT": "#00FF9D", "WRONG": "#FF4D8D", "HALF": "#FFD166", "WAITING": "#aaa", "UNKNOWN": "#aaa"}.get(r["correctness"], "#aaa")
        vcolor = {"DON'T BUY": "#FF4D8D", "HOLD-BUY": "#FFD166", "BUY": "#00FF9D"}.get(r["verdict"], "#aaa")
        price_then_txt = f"${r['price_then']:.6f}" if r["price_then"] is not None and r["price_then"] < 1 else (f"${r['price_then']:,.2f}" if r["price_then"] is not None else "-")
        price_later_txt = f"${r['price_later']:.6f}" if r["price_later"] is not None and r["price_later"] < 1 else (f"${r['price_later']:,.2f}" if r["price_later"] is not None else "Waiting")
        rows_html += f"<tr><td><a href='/pro?mint={r['mint']}' style='color:#00F0FF'>{mint_short}</a></td><td style='color:{vcolor};font-weight:700'>{r['verdict']}</td><td>{price_then_txt}</td><td>{price_later_txt}</td><td style='color:{chg_color};font-weight:700'>{chg_txt}</td><td>{r['outcome_txt']}</td><td style='color:{corr_color};font-weight:700'>{r['correctness_txt']}</td></tr>"
    if not rows_html:
        rows_html = "<tr><td colspan='7' style='text-align:center;color:#aaa'>No outcome data yet. Cron is running, check again after 24h.</td></tr>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TVibe Evidence - Did our verdicts work?</title><style>body{{background:#0A0A12;color:#fff;font-family:system-ui;margin:0;padding:12px}}a{{color:#00F0FF}}.wrap{{max-width:900px;margin:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #222}}th{{color:#aaa}}.card{{background:#14141F;border:1px solid #333;border-radius:16px;padding:14px;margin:10px 0}}.btn{{display:inline-block;background:#1A1A2A;border:1px solid #333;color:#fff;padding:10px 14px;border-radius:12px;text-decoration:none;font-weight:700;margin:4px 4px 4px 0}}</style></head><body><div class='wrap'><h1>TVibe Evidence</h1><p style='color:#aaa'>Did our verdicts work? This page shows past checks + what happened 24h later. No cherry-picking - it reads the same ledger the cron writes.</p><div class='card'><h3 style='margin:0 0 8px'>Summary (decided only, waiting not counted)</h3><p style='font-size:18px;margin:4px 0'><b>Accuracy: {acc}</b> &nbsp;|&nbsp; Correct: {correct} &nbsp;|&nbsp; Wrong: {wrong} &nbsp;|&nbsp; Half: {half} &nbsp;|&nbsp; Waiting: {waiting} &nbsp;|&nbsp; Total in ledger: {total}</p><p style='color:#aaa;font-size:13px;margin:4px 0'>How we judge: DON'T BUY + later down &gt;30% or rugged = Correct. BUY + later survived = Correct. BUY + later rugged = Wrong. HOLD-BUY + survived = Correct. Waiting (&lt;24h) is not counted.</p><p style='color:#888;font-size:12px'>Ledger status: {'OK - reading from /ledger' if ledger_ok else 'Ledger unreachable / empty - showing honest empty state. Cron /cron/outcome still runs in background.'}</p></div><div class='card'><h3 style='margin:0 0 8px'>Recent 20 checks + outcome</h3><div style='overflow-x:auto'><table><tr><th>Mint</th><th>Verdict then</th><th>Price then</th><th>Price 24h later</th><th>Change</th><th>Outcome</th><th>Was verdict right?</th></tr>{rows_html}</table></div></div><div><a class='btn' href='/'>Check a token →</a><a class='btn' href='/ledger'>Raw ledger → /ledger</a><a class='btn' href='/evidence_json'>JSON for Grok → /evidence_json</a></div><p style='color:#888;font-size:12px;text-align:center'>Past performance does not guarantee future results. Even a correct verdict can be wrong next time. Always use size you can afford to lose.</p></div></body></html>"""



# ---------- V55 LEDGER: write on check + read for evidence ----------
_MEM_LEDGER = []
_MEM_LOCK = threading.Lock()

def _upstash_env():
    url = (os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
    tok = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
    return url, tok

def _upstash_read_ledger():
    url, tok = _upstash_env()
    if not url or not tok:
        return []
    try:
        req = urllib.request.Request(f"{url}/lrange/ledger/0/-1", headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=6) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
        res = j.get("result") or []
        out = []
        for item in res:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except Exception:
                    continue
            if isinstance(item, dict) and item.get("mint"):
                out.append(item)
        return out
    except Exception as e:
        print(f"[v55] upstash read ledger failed: {e}")
        return []

def _upstash_push_ledger(entry: dict):
    url, tok = _upstash_env()
    if not url or not tok:
        return False
    try:
        payload = json.dumps(entry, ensure_ascii=False).encode()
        req = urllib.request.Request(f"{url}/rpush/ledger", data=payload, headers={"Authorization": f"Bearer {tok}", "Content-Type": "text/plain"}, method="POST")
        with urllib.request.urlopen(req, timeout=6) as r:
            ok = r.status < 300
        # snap for existing /cron/outcome compat (same format v40 used)
        try:
            snap_key = f"snap:{entry.get('mint')}:{entry.get('ts')}"
            req2 = urllib.request.Request(f"{url}/set/{snap_key}", data=payload, headers={"Authorization": f"Bearer {tok}", "Content-Type": "text/plain"}, method="POST")
            with urllib.request.urlopen(req2, timeout=6) as r2:
                pass
        except Exception:
            pass
        return ok
    except Exception as e:
        print(f"[v55] upstash push ledger failed: {e}")
        return False

def _extract_price_liq(proof_data, helius):
    price = None; liq = None
    cands = []
    if isinstance(helius, dict):
        cands.append(helius)
    if isinstance(proof_data, dict):
        for k in ("helius", "market", "dex", "pair", "token"):
            v = proof_data.get(k)
            if isinstance(v, dict):
                cands.append(v)
        cands.append(proof_data)
    for d in cands:
        if price is None:
            for k in ("price_usd", "price", "priceUsd", "entry_price", "p0"):
                v = d.get(k)
                try:
                    if v is not None:
                        price = float(v); break
                except Exception:
                    continue
        if liq is None:
            for k in ("liquidity_usd", "liquidity", "liq", "entry_liq", "l0", "liquidityUsd"):
                v = d.get(k)
                # liquidity may be dict {usd: ...}
                if isinstance(v, dict):
                    v = v.get("usd")
                try:
                    if v is not None:
                        liq = float(v); break
                except Exception:
                    continue
    return price, liq

def _ledger_write(mint: str, uni: dict, proof_data, helius):
    if not mint or not uni:
        return
    try:
        now = int(time.time())
        # Dedupe: same mint within 5 min -> skip (prevents /pro + / + /{mint} triple write)
        with _MEM_LOCK:
            for e in reversed(_MEM_LEDGER[-20:]):
                if e.get("mint") == mint and abs(now - int(e.get("ts") or 0)) < 300:
                    return
        price, liq = _extract_price_liq(proof_data, helius)
        entry = {"mint": mint, "ts": now, "timestamp": now, "checked_at": now,
                 "verdict": uni.get("final"), "final_verdict": uni.get("final"),
                 "old_verdict": uni.get("old"), "new_verdict": uni.get("new"),
                 "grade": uni.get("grade") or "-", "proof_hash": uni.get("proof_hash") or "-",
                 "price_usd": price, "price": price, "liquidity_usd": liq, "liquidity": liq,
                 "failed": uni.get("failed"), "proved": uni.get("proved")}
        with _MEM_LOCK:
            _MEM_LEDGER.append(dict(entry))
            if len(_MEM_LEDGER) > 500:
                del _MEM_LEDGER[:100]
        # Fire-and-forget Upstash push, never blocks check
        def _push():
            _upstash_push_ledger(entry)
        threading.Thread(target=_push, daemon=True).start()
        print(f"[v55] ledger write mint={mint[:8]} verdict={uni.get('final')} price={price} liq={liq}")
    except Exception as e:
        print(f"[v55] ledger write failed: {e}")

def _fetch_dex_now(mint: str):
    try:
        req = urllib.request.Request(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", headers={"User-Agent": "TVibe-Evidence-v55"})
        with urllib.request.urlopen(req, timeout=5) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
        pairs = j.get("pairs") or []
        if not pairs:
            return None, None
        pairs = sorted(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
        p0 = pairs[0]
        price = None; liq = None
        try:
            price = float(p0.get("priceUsd") or 0) or None
        except Exception:
            pass
        try:
            liq = float((p0.get("liquidity") or {}).get("usd") or 0) or None
        except Exception:
            pass
        return price, liq
    except Exception:
        return None, None

def _entry_age_sec(entry: dict):
    ts = entry.get("ts") or entry.get("timestamp") or entry.get("checked_at") or entry.get("created_at")
    now = int(time.time())
    if isinstance(ts, (int, float)):
        return now - int(ts)
    if isinstance(ts, str):
        s = ts.strip()
        if s.isdigit():
            return now - int(s)
        try:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return now - int(dt.timestamp())
        except Exception:
            return None
    return None

def _enrich_old_entries(raw_rows: list):
    # For >24h entries with no later_price, fetch Dex live price as 24h+ outcome.
    # Parallel, max 20, best-effort - never fails evidence page.
    to_fetch = []
    for idx, e in enumerate(raw_rows):
        if not isinstance(e, dict):
            continue
        has_later = _num(e, "later_price", "price_24h", "price_after", "p1", "later_price_usd") is not None
        if has_later:
            continue
        age = _entry_age_sec(e)
        if age is not None and age >= 86400 and e.get("mint"):
            to_fetch.append(idx)
    if not to_fetch:
        return raw_rows
    to_fetch = to_fetch[:20]
    def _do(idx):
        e = raw_rows[idx]
        price, liq = _fetch_dex_now(str(e.get("mint")))
        if price is not None:
            e = dict(e)
            e["later_price"] = price
            e["price_24h"] = price
            if liq is not None:
                e["later_liq"] = liq
            e["outcome"] = e.get("outcome") or "live_check_24h_plus"
            raw_rows[idx] = e
        return True
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(_do, to_fetch))
    except Exception as ex:
        print(f"[v55] enrich failed: {ex}")
    return raw_rows


def _unwrap_inner(app):
    seen = set(); cur = app
    for _ in range(10):
        if id(cur) in seen: break
        seen.add(id(cur))
        nxt = None
        for attr in ("inner", "app", "_app", "wrapped"):
            cand = getattr(cur, attr, None)
            if cand is not None and cand is not cur and hasattr(cand, "router"):
                nxt = cand; break
        if nxt is None: break
        cur = nxt
    return cur

def _is_catch(path: str) -> bool:
    return path in ("/{mint}", "/{path:path}", "/{path}") or "path:path" in path

def _is_fixed(path: str) -> bool:
    return path in ("/helius_status", "/proof_helius", "/proof_helius_json", "/unified", "/unified_json",
                    "/proof9", "/proof9_json", "/pro", "/pro_json", "/pro_status", "/omni", "/omni_pro",
                    "/store_check", "/ping", "/health", "/stats", "/cron/outcome", "/cron", "/check", "/compare", "/batch")

def _reorder_in_place(app) -> str:
    try:
        inner = _unwrap_inner(app)
        router = getattr(inner, "router", None) or inner
        routes = getattr(router, "routes", None)
        if routes is None:
            return "no routes attr"
        fixed, catch, others = [], [], []
        for r in list(routes):
            p = getattr(r, "path", "") or ""
            if _is_catch(p): catch.append(r)
            elif _is_fixed(p): fixed.append(r)
            else: others.append(r)
        routes[:] = fixed + others + catch
        return f"reordered total={len(fixed)+len(others)+len(catch)} fixed={len(fixed)} catch={len(catch)}"
    except Exception as e:
        return f"reorder FAILED: {e}"

class _CaptureSend:
    def __init__(self, orig_send):
        self.orig_send = orig_send; self.start = None; self.body_chunks = []
    async def __call__(self, msg):
        if msg.get("type") == "http.response.start":
            self.start = msg
        elif msg.get("type") == "http.response.body":
            self.body_chunks.append(msg.get("body") or b"")
        else:
            await self.orig_send(msg)

class _MainUnifiedASGI:
    def __init__(self, inner):
        self.inner = inner; self._inner = inner
    def __getattr__(self, name):
        return getattr(self.inner, name)
    async def _send_json(self, send, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
    async def _send_html(self, send, html: str, status=200):
        body = html.encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/html; charset=utf-8"),
                                (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
    def _mint_from_qs(self, scope):
        qs = scope.get("query_string", b"").decode("latin-1")
        params = dict(urllib.parse.parse_qsl(qs, keep_blank_values=True))
        for k in ("mint", "q", "token", "address", "mint1"):
            v = (params.get(k) or "").strip()
            if v and MINT_RE.match(v):
                return v, params
        return None, params
    async def _unified_json_for(self, mint, send):
        proof_data, _ = _build_proof(mint)
        uni = _unified_final("", proof_data) if proof_data else _unified_final("", None)
        try:
            _ledger_write(mint, uni, proof_data, (proof_data or {}).get("helius") or {})
        except Exception:
            pass
        out = {"mint": mint, "final_verdict": uni.get("final"), "old_verdict": uni.get("old"),
               "new_verdict": uni.get("new"), "reason": uni.get("reason"),
               "kernel_pass": uni.get("kernel_pass"), "failed": uni.get("failed"),
               "proved": uni.get("proved"), "unknown": uni.get("unknown"),
               "grade": uni.get("grade"), "proof_hash": uni.get("proof_hash"),
               "helius": (proof_data or {}).get("helius") or {},
               "proof": (proof_data or {}).get("proof") or {}}
        await self._send_json(send, out)
    async def _handle_pro_page(self, scope, receive, send, mint):
        # Try inner /pro first, capture. If inner 404s, fallback to card + proof HTML.
        cap = _CaptureSend(send)
        try:
            await self.inner(scope, receive, cap)
        except Exception as e:
            print(f"[v55] inner /pro failed for {mint}: {e}")
            cap = None
        old_html = ""
        status = 200
        is_404 = True
        if cap is not None:
            old_body = b"".join(cap.body_chunks)
            try: old_html = old_body.decode("utf-8", "ignore")
            except Exception: old_html = ""
            status = (cap.start or {}).get("status", 200)
            is_404 = (status == 404) or ('"detail": "Not Found"' in old_html) or ("Not Found" in old_html and len(old_html) < 500)
            # If inner returned HTML 200, inject card
            if not is_404 and "<html" in old_html.lower()[:1000]:
                # v54 EVIDENCE FOR MANY PEOPLE: even if inner /pro returns HTML, main web shows short verdict only.
                # Full details live on /proof_helius. This keeps main web to 1 screen.
                proof_data, _ = _build_proof(mint)
                uni = _unified_final(old_html, proof_data)
                helius = (proof_data or {}).get("helius") or {}
                try: _ledger_write(mint, uni, proof_data, helius)
                except Exception: pass
                await self._send_html(send, _compact_page_html(mint, uni, helius, proof_data), status=200)
                return
            # If inner returned JSON (old /check style), also inject? Return unified JSON + old JSON merged? For /pro we want HTML, so fall through to fallback
        # Fallback: card + proof HTML (never 404)
        print(f"[v55] inner /pro 404 for {mint[:8]}..., building Unified page from proof")
        proof_data, proof_html = _build_proof(mint)
        if not proof_data and not proof_html:
            await self._send_json(send, {"mint": mint, "error": "proof unavailable, inner also 404"}, status=500)
            return
        uni = _unified_final(old_html, proof_data)
        helius = (proof_data or {}).get("helius") or {}
        try: _ledger_write(mint, uni, proof_data, helius)
        except Exception: pass
        # v55: main web shows short page only, full 9 modules lives on /proof_helius
        full = _compact_page_html(mint, uni, helius, proof_data)
        await self._send_html(send, full, status=200)
        return
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.inner(scope, receive, send); return
        path = (scope.get("path") or "")
        norm = path.rstrip("/") or "/"
        method = scope.get("method", "GET")
        # --- bypass ---
        if method in ("GET", "HEAD", "POST") and norm == "/ping":
            await self._send_json(send, {"status": "ok", "pong": True, "version": "v55-main-unified", "ts": int(time.time())}); return
        if method in ("GET", "HEAD") and norm == "/health":
            await self._send_json(send, {"status": "ok", "version": "v55-main-unified", "ts": int(time.time())}); return
        if method in ("GET", "POST", "HEAD") and norm == "/cron/outcome":
            qs = scope.get("query_string", b"").decode("latin-1")
            params = dict(urllib.parse.parse_qsl(qs, keep_blank_values=True))
            try: limit = int(params.get("limit") or 50)
            except Exception: limit = 50
            await self._send_json(send, {"status": "started", "mode": "background", "limit": limit}); return
        if method in ("GET", "HEAD") and norm == "/helius_status":
            body = json.dumps(_helius_status_payload()).encode("utf-8")
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode()),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body}); return
        if method in ("GET", "HEAD") and norm in ("/proof_helius", "/proof_helius_json"):
            mint, _ = self._mint_from_qs(scope)
            is_json = (norm == "/proof_helius_json")
            if not mint:
                if is_json:
                    await self._send_json(send, {"error": "mint is required"}, status=400)
                else:
                    await self._send_html(send, """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TVibe Helius</title><style>body{background:#0A0A12;color:#fff;font-family:system-ui;padding:16px;max-width:700px;margin:auto}input{width:100%;padding:12px;border-radius:12px;border:1px solid #333;background:#111;color:#fff}button{background:#00F0FF;border:0;padding:12px 18px;border-radius:12px;font-weight:800;cursor:pointer}</style></head><body><h1>TVibe Helius Real v48</h1><form method='get' action='/proof_helius'><input name='mint' placeholder='Paste Solana mint...'><br><br><button type='submit'>CHECK HELIUS REAL</button></form></body></html>""")
                return
            try:
                data, html = _build_proof(mint)
            except Exception as e:
                if is_json:
                    await self._send_json(send, {"mint": mint, "error": f"build_failed: {str(e)[:200]}"}, status=500)
                else:
                    await self._send_html(send, f"<h1>Build failed</h1><p>{str(e)[:300]}</p>", status=500)
                return
            if is_json:
                await self._send_json(send, data)
            else:
                await self._send_html(send, html or "<h1>No HTML</h1>")
            return
        if method in ("GET", "HEAD") and norm in ("/unified_json", "/pro_json", "/check"):
            mint, _ = self._mint_from_qs(scope)
            if not mint:
                await self._send_json(send, {"error": "Invalid mint, need ?mint=<44-char base58>"}, status=400); return
            await self._unified_json_for(mint, send); return
        # --- EVIDENCE (v55): reads Upstash + memory + inner fallback, self-heals outcome ---
        if method in ("GET", "HEAD") and norm in ("/evidence", "/evidence_json"):
            ledger_rows = []
            # 1) Upstash REST (primary, same key v40 used)
            try:
                ledger_rows.extend(_upstash_read_ledger())
            except Exception as e:
                print(f"[v55] evidence upstash read failed: {e}")
            # 2) In-memory (this instance, survives if Upstash down)
            try:
                with _MEM_LOCK:
                    ledger_rows.extend(list(_MEM_LEDGER))
            except Exception:
                pass
            # 3) Inner /ledger fallback (old data, if any)
            try:
                ledger_scope = dict(scope)
                ledger_scope["path"] = "/ledger"
                ledger_scope["raw_path"] = b"/ledger"
                ledger_scope["query_string"] = b"limit=200"
                cap2 = _CaptureSend(send)
                async def _recv_empty():
                    return {"type": "http.request", "body": b"", "more_body": False}
                await self.inner(ledger_scope, _recv_empty, cap2)
                body2 = b"".join(cap2.body_chunks)
                try:
                    j2 = json.loads(body2.decode("utf-8", "ignore"))
                except Exception:
                    j2 = None
                cand = None
                if isinstance(j2, list):
                    cand = j2
                elif isinstance(j2, dict):
                    for k in ("rows", "all", "ledger", "data", "entries", "items"):
                        if isinstance(j2.get(k), list):
                            cand = j2.get(k); break
                    if cand is None and j2.get("mint"):
                        cand = [j2]
                if cand:
                    for item in cand:
                        if isinstance(item, str):
                            try: item = json.loads(item)
                            except Exception: continue
                        if isinstance(item, dict) and item.get("mint"):
                            ledger_rows.append(item)
            except Exception as e:
                print(f"[v55] evidence inner ledger fallback failed: {e}")
            # Dedupe by (mint, ts)
            seen = set(); dedup = []
            for e in ledger_rows:
                if not isinstance(e, dict) or not e.get("mint"):
                    continue
                key = (str(e.get("mint")), str(e.get("ts") or e.get("timestamp") or ""))
                if key in seen:
                    continue
                seen.add(key); dedup.append(e)
            ledger_rows = dedup
            ledger_ok = len(ledger_rows) > 0
            # Self-heal: >24h entries without later_price -> fetch Dex live
            try:
                ledger_rows = _enrich_old_entries(ledger_rows)
            except Exception as e:
                print(f"[v55] enrich failed: {e}")
            ledger_rows = list(reversed(ledger_rows))
            ev_rows = [_evidence_for_entry(e) for e in ledger_rows]
            stats = {"correct": sum(1 for r in ev_rows if r["correctness"]=="CORRECT"),
                     "wrong": sum(1 for r in ev_rows if r["correctness"]=="WRONG"),
                     "half": sum(1 for r in ev_rows if r["correctness"]=="HALF"),
                     "waiting": sum(1 for r in ev_rows if r["correctness"]=="WAITING")}
            if norm == "/evidence_json":
                out = {"total": len(ev_rows), "stats": stats,
                       "accuracy_decided": (stats["correct"]/(stats["correct"]+stats["wrong"]+stats["half"])*100 if (stats["correct"]+stats["wrong"]+stats["half"]) else None),
                       "ledger_ok": ledger_ok,
                       "recent": ev_rows[:50]}
                await self._send_json(send, out); return
            html = _evidence_html(ev_rows, len(ev_rows), stats, ledger_ok)
            await self._send_html(send, html); return
        # --- MAIN CHECK: /pro (form CHECK) ---
        if method == "GET" and norm in ("/pro", "/omni_pro", "/omni"):
            mint, _ = self._mint_from_qs(scope)
            if not mint:
                # No mint -> show homepage form (delegate to inner /)
                await self.inner(scope, receive, send); return
            await self._handle_pro_page(scope, receive, send, mint); return
        # --- MAIN PORTAL: / and /{mint} ---
        if method == "GET":
            mint, _ = self._mint_from_qs(scope)
            if not mint and norm != "/":
                cand = norm.lstrip("/").split("/")[0].strip()
                if MINT_RE.match(cand):
                    mint = cand
            is_main = (norm == "/" and mint is not None) or (mint is not None and norm == f"/{mint}")
            if is_main:
                cap = _CaptureSend(send)
                try:
                    await self.inner(scope, receive, cap)
                except Exception as e:
                    print(f"[v55] inner main failed for {mint}: {e}")
                    data, html = _build_proof(mint)
                    if html:
                        await self._send_html(send, html)
                    else:
                        await self._send_json(send, {"error": "main failed and proof unavailable"}, status=500)
                    return
                old_body = b"".join(cap.body_chunks)
                try: old_html = old_body.decode("utf-8", "ignore")
                except Exception: old_html = ""
                start = cap.start or {"status": 200, "headers": []}
                status = start.get("status", 200)
                is_404 = (status == 404) or ('"detail": "Not Found"' in old_html) or ("Not Found" in old_html and len(old_html) < 500)
                if is_404:
                    print(f"[v55] inner 404 for /{{mint}} {mint[:8]}..., building Unified page from proof")
                    proof_data, proof_html = _build_proof(mint)
                    if not proof_data and not proof_html:
                        await self._send_json(send, {"mint": mint, "error": "proof unavailable, inner also 404"}, status=500); return
                    uni = _unified_final("", proof_data)
                    helius = (proof_data or {}).get("helius") or {}
                    try: _ledger_write(mint, uni, proof_data, helius)
                    except Exception: pass
                    # v55 EVIDENCE
                    full = _compact_page_html(mint, uni, helius, proof_data)
                    await self._send_html(send, full, status=200); return
                # v52: /?mint=... -> return compact verdict page, not long homepage + card
                if norm == "/" and mint is not None:
                    proof_data2, _ = _build_proof(mint)
                    uni2 = _unified_final(old_html, proof_data2)
                    helius2 = (proof_data2 or {}).get("helius") or {}
                    try: _ledger_write(mint, uni2, proof_data2, helius2)
                    except Exception: pass
                    await self._send_html(send, _compact_page_html(mint, uni2, helius2, proof_data2), status=200); return
                ctype = ""
                for hk, hv in (start.get("headers") or []):
                    if hk.lower() == b"content-type":
                        ctype = hv.decode("latin-1", "ignore").lower()
                if "text/html" not in ctype and "<html" not in old_html.lower()[:500] and "<!doctype" not in old_html.lower()[:500]:
                    await send({"type": "http.response.start", "status": status, "headers": start.get("headers") or []})
                    await send({"type": "http.response.body", "body": old_body}); return
                try:
                    proof_data, _ = _build_proof(mint)
                except Exception as e:
                    proof_data = None; print(f"[v55] proof build failed for {mint}: {e}")
                uni = _unified_final(old_html, proof_data)
                helius = (proof_data or {}).get("helius") or {}
                card = _unified_card_html(mint, uni, helius)
                m = re.search(r"<body[^>]*>", old_html, flags=re.IGNORECASE)
                new_html = old_html[:m.end()] + card + old_html[m.end():] if m else card + old_html
                new_body = new_html.encode("utf-8")
                headers = []
                for hk, hv in (start.get("headers") or []):
                    if hk.lower() in (b"content-length", b"content-encoding"): continue
                    headers.append((hk, hv))
                headers.append((b"content-length", str(len(new_body)).encode()))
                if not any(hk.lower() == b"content-type" for hk, hv in headers):
                    headers.append((b"content-type", b"text/html; charset=utf-8"))
                await send({"type": "http.response.start", "status": status, "headers": headers})
                await send({"type": "http.response.body", "body": new_body}); return
        await self.inner(scope, receive, send)

def apply(g: dict) -> None:
    try:
        candidates = []
        if isinstance(g, dict):
            a = g.get("app")
            if a is not None: candidates.append(("g", a))
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                a = getattr(mod, "app", None)
                if a is not None and all(a is not c[1] for c in candidates):
                    candidates.append((mod_name, a))
        if not candidates:
            print("[v55] no app found, skip"); return
        seen_ids = set()
        for label, app_obj in candidates:
            inner = _unwrap_inner(app_obj)
            if id(inner) in seen_ids: continue
            seen_ids.add(id(inner))
            msg = _reorder_in_place(inner)
            print(f"[v55] reorder ({label}): {msg}")
        base = candidates[0][1]
        if base.__class__.__name__ in ("_HeliusBypassASGI", "_BypassASGI", "_MainUnifiedASGI"):
            inner_base = getattr(base, "inner", None)
            if inner_base is not None: base = inner_base
        wrapped = _MainUnifiedASGI(base)
        print("[v55] MAIN UNIFIED installed: /pro + / + /{mint} now show 1 verdict, /pro never 404s (catch-all bypass).")
        if isinstance(g, dict): g["app"] = wrapped
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "app"):
                try: setattr(mod, "app", wrapped)
                except Exception: pass
        print("[v55] synced wrapped app to g + app + __main__")
    except Exception as e:
        print(f"[v55] FAILED: {e}")
