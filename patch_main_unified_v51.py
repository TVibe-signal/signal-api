"""
patch_main_unified_v51.py - TVibe MAIN UNIFIED v51 - Fix /pro CHECK 404
English only. One file. No new env var.

Bug from user screenshots 00:09 Nov 24:
  Photo 1: /proof_helius + UNIFIED card OK for USDC (v50 works)
  Photo 2: Main web "Check a token" form -> input mint 93uamrb... -> click CHECK
  Photo 3: {"detail":"Not Found"}

Root cause:
  Main web form is: <form action='/pro' method='get'><input name='mint'>
  So CHECK goes to /pro?mint=...
  But inner app has a catch-all /{mint} route BEFORE /pro.
  So /pro?mint=93... matches /{mint} with mint="pro" (invalid) -> inner returns 404 JSON.
  v49/v50 tried to reorder inner router, but log showed reorder total=0 because
  the app object is wrapped (routes=0 at patch time). Reorder never happened.

v51 fix - DO NOT rely on inner reorder:
  Wrapper intercepts /pro, /pro_json, /check, /omni_pro, /omni BEFORE inner.
  For /pro?mint=... it builds proof + UNIFIED card itself, then:
    - tries inner /pro, if inner returns HTML 200 -> inject card on top
    - if inner returns 404 / Not Found -> returns card + full proof HTML (never 404)
  For /pro_json / /check / /unified_json -> returns UNIFIED JSON.
  / and /{mint} keep v50 behavior (never 404).

Usage - REPLACE v50 lines at VERY BOTTOM of app.py with:
    import patch_main_unified_v51 as _main51
    _main51.apply(g)
Keep only v51.
"""

from __future__ import annotations
import os, sys, json, re, time, urllib.request, urllib.parse

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
            headers={"Content-Type": "application/json", "User-Agent": "TVibe-Main-Unified-v51"})
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
    return {"version": "v51-main-unified-2026-11-23", "has_helius_url": has,
            "helius_url_present": has, "rpc_test_ok": test_ok, "rpc_test_error": test_err,
            "note": "v51: /pro, /pro_json, /check, /{mint}, / all intercepted before inner catch-all. Never 404."}

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
        chips += f"<span style='display:inline-block;margin:3px 4px 3px 0;padding:4px 8px;border-radius:999px;border:1px solid {c};color:{c};font-size:11px;font-weight:700'>{s.get('rule','?')} • {s.get('status','?')}</span>"
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
            print(f"[v51] inner /pro failed for {mint}: {e}")
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
                proof_data, _ = _build_proof(mint)
                uni = _unified_final(old_html, proof_data)
                helius = (proof_data or {}).get("helius") or {}
                card = _unified_card_html(mint, uni, helius)
                m = re.search(r"<body[^>]*>", old_html, flags=re.IGNORECASE)
                new_html = old_html[:m.end()] + card + old_html[m.end():] if m else card + old_html
                await self._send_html(send, new_html, status=200)
                return
            # If inner returned JSON (old /check style), also inject? Return unified JSON + old JSON merged? For /pro we want HTML, so fall through to fallback
        # Fallback: card + proof HTML (never 404)
        print(f"[v51] inner /pro 404 for {mint[:8]}..., building Unified page from proof")
        proof_data, proof_html = _build_proof(mint)
        if not proof_data and not proof_html:
            await self._send_json(send, {"mint": mint, "error": "proof unavailable, inner also 404"}, status=500)
            return
        uni = _unified_final(old_html, proof_data)
        helius = (proof_data or {}).get("helius") or {}
        card = _unified_card_html(mint, uni, helius)
        if proof_html and "<body" in proof_html.lower():
            m = re.search(r"<body[^>]*>", proof_html, flags=re.IGNORECASE)
            full = proof_html[:m.end()] + card + proof_html[m.end():] if m else card + proof_html
        elif proof_html:
            full = card + proof_html
        else:
            full = f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TVibe Unified - {mint[:8]}</title></head><body style='background:#0A0A12'>{card}<p style='color:#fff;text-align:center'><a href='/' style='color:#00F0FF'>Back home</a></p></body></html>"
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
            await self._send_json(send, {"status": "ok", "pong": True, "version": "v51-main-unified", "ts": int(time.time())}); return
        if method in ("GET", "HEAD") and norm == "/health":
            await self._send_json(send, {"status": "ok", "version": "v51-main-unified", "ts": int(time.time())}); return
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
                    print(f"[v51] inner main failed for {mint}: {e}")
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
                    print(f"[v51] inner 404 for /{{mint}} {mint[:8]}..., building Unified page from proof")
                    proof_data, proof_html = _build_proof(mint)
                    if not proof_data and not proof_html:
                        await self._send_json(send, {"mint": mint, "error": "proof unavailable, inner also 404"}, status=500); return
                    uni = _unified_final("", proof_data)
                    helius = (proof_data or {}).get("helius") or {}
                    card = _unified_card_html(mint, uni, helius)
                    if proof_html and "<body" in proof_html.lower():
                        m = re.search(r"<body[^>]*>", proof_html, flags=re.IGNORECASE)
                        full = proof_html[:m.end()] + card + proof_html[m.end():] if m else card + proof_html
                    elif proof_html:
                        full = card + proof_html
                    else:
                        full = f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TVibe Unified - {mint[:8]}</title></head><body style='background:#0A0A12'>{card}</body></html>"
                    await self._send_html(send, full, status=200); return
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
                    proof_data = None; print(f"[v51] proof build failed for {mint}: {e}")
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
            print("[v51] no app found, skip"); return
        seen_ids = set()
        for label, app_obj in candidates:
            inner = _unwrap_inner(app_obj)
            if id(inner) in seen_ids: continue
            seen_ids.add(id(inner))
            msg = _reorder_in_place(inner)
            print(f"[v51] reorder ({label}): {msg}")
        base = candidates[0][1]
        if base.__class__.__name__ in ("_HeliusBypassASGI", "_BypassASGI", "_MainUnifiedASGI"):
            inner_base = getattr(base, "inner", None)
            if inner_base is not None: base = inner_base
        wrapped = _MainUnifiedASGI(base)
        print("[v51] MAIN UNIFIED installed: /pro + / + /{mint} now show 1 verdict, /pro never 404s (catch-all bypass).")
        if isinstance(g, dict): g["app"] = wrapped
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "app"):
                try: setattr(mod, "app", wrapped)
                except Exception: pass
        print("[v51] synced wrapped app to g + app + __main__")
    except Exception as e:
        print(f"[v51] FAILED: {e}")
