"""patch_live_fix.py — LAST loader step for TVibe Signal free tier. [FIXED]

Fixes vs original (v3 — patch can no longer die halfway):
    v3 root cause: _ensure_play() used Query(alias="request") TOGETHER WITH
    `request: Request`. FastAPI treats that as a conflicting "request"
    param and route registration can raise -> apply() aborted BEFORE the
    ASGI wrapper (the bulletproof fix) was ever installed -> server kept
    running the OLD broken /omni, still 422. v3 removes the alias entirely
    (mint is read from query_params, which sees both ?mint= and ?request=)
    and apply() now try/excepts EVERY step, so one bad route can never
    prevent the ASGI wrapper from installing.
1. 422 on CHECK — the old homepage check() called an endpoint whose handler
   was declared as `def play(request)` / `def xxx(request)` WITHOUT `: Request`
   annotation. FastAPI then treats `request` as a REQUIRED QUERY param, so
   `GET /play?mint=...` -> 422 [{"loc":["query","request"],"msg":"Field required"}].
   Fix: (a) register a tolerant /play here that accepts BOTH ?mint= and
   ?request=, (b) make the homepage check() always call /omni?mint=...
2. Homepage was NEVER patched on the live page — _patch_html() returned
   unchanged unless the exact string "function fill(m){...}" was present.
   The live page in the screenshot uses a CHECK button, not fill(), so the
   old buggy check() survived. Fix: patch ANY `function check(){...}`,
   and inject LIVE_JS when the page has #mint / #out but no check().
3. /health NameError mcp_error — handled in main.py (setdefault), this file
   keeps the never-500 fallback.
"""
from __future__ import annotations
import json, re, time

LIVE_JS = r"""
async function check(){
  const m=(document.getElementById('mint').value||'').trim();
  const out=document.getElementById('out');
  const esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(ch){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch];});};
  const num=function(v,dec){if(v==null||v==='')return '—';const n=Number(v);return isFinite(n)?n.toLocaleString('en-US',{maximumFractionDigits:dec}):esc(v);};
  if(!m){out.innerHTML='<b>Paste a mint first.</b>';return;}
  if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){out.innerHTML='<b>That does not look like a Solana mint (32-44 base58 chars). Paste the full address.</b>';return;}
  const q=encodeURIComponent(m);
  const links='<a href="/omni?mint='+q+'" target="_blank" style="color:#00F0FF">Open /omni JSON →</a> <a href="/play?mint='+q+'" target="_blank" style="color:#00F0FF">Open /play →</a>';
  out.innerHTML='<b>Checking live…</b> (first request can take a few seconds)';
  try{
    const ctl=new AbortController();
    const to=setTimeout(function(){ctl.abort();},45000);
    const r=await fetch('/omni?mint='+q,{cache:'no-store',signal:ctl.signal});
    clearTimeout(to);
    const d=await r.json().catch(function(){return {};});
    if(!r.ok){
      let msg=d.detail||d.error||d.message||'';
      if(typeof msg!=='string')msg=JSON.stringify(msg);
      if(r.status===429)msg='Rate limited — retry in a few seconds.';
      else if(!msg)msg='No pair found or upstream unavailable. Retry in a few seconds.';
      out.innerHTML='<b style="color:#FF4D8D">Error '+r.status+'</b><br><span style="color:#aaa">'+esc(msg).slice(0,160)+'</span><br>'+links;
      return;
    }
    const dec=(d.decision&&typeof d.decision==='object')?d.decision:{};
    if(d.error&&!dec.verdict&&!d.verdict){
      out.innerHTML='<b style="color:#FF4D8D">Could not score this token</b><br><span style="color:#aaa">'+esc(d.error).slice(0,160)+'</span><br>'+links;
      return;
    }
    const raw=String(dec.verdict||(typeof d.verdict==='string'?d.verdict:'')||(typeof d.action==='string'?d.action:'')||'').toLowerCase();
    const passOk=!(d.filter&&d.filter.pass===false);
    let label;
    if(raw==='ok'||raw==='pass'){label=passOk?'PASS':'REVIEW';}
    else if(raw==='avoid'||raw==='skip'){label='SKIP';}
    else if(raw==='caution'||raw==='review'){label='REVIEW';}
    else{label=raw?raw.toUpperCase():'—';}
    const c=label==='PASS'?'#00FF9D':label==='REVIEW'?'#FFD166':label==='SKIP'?'#FF4D8D':'#00F0FF';
    const risk=(dec.risk_score!=null)?dec.risk_score:(d.risk_score!=null?d.risk_score:'—');
    const liq=(d.liquidity_usd!=null)?d.liquidity_usd:((d.pair&&d.pair.liquidity&&d.pair.liquidity.usd)!=null?d.pair.liquidity.usd:null);
    const price=(d.price_usd!=null)?d.price_usd:((d.pair&&d.pair.priceUsd)!=null?d.pair.priceUsd:null);
    const pick=function(a,b){return (a&&a.length)?a:(b||[]);};
    const blockers=pick(dec.blockers,d.blockers).slice(0,4);
    const cautions=pick(dec.cautions,d.cautions).slice(0,4);
    const unknowns=pick(dec.unknowns,d.unknowns).slice(0,3);
    const li=function(arr,col){return arr.map(function(x){return '<li style="color:'+col+'">'+esc(typeof x==='string'?x:JSON.stringify(x))+'</li>';}).join('');};
    const list=li(blockers,'#FF4D8D')+li(cautions,'#FFD166')+li(unknowns,'#aaa');
    out.innerHTML='<span style="display:inline-block;padding:6px 12px;font-weight:800;background:'+c+';color:#000">'+esc(label)+'</span> '
      +'<b>LIVE — Risk '+esc(risk)+' • Liquidity $'+num(liq,0)+' • Price $'+num(price,8)+'</b>'
      +(list?'<ul style="margin:8px 0">'+list+'</ul>':'<br>')+links;
  }catch(e){
    out.innerHTML='<b style="color:#FF4D8D">'+(e&&e.name==='AbortError'?'Timed out — server may be waking up, try again.':'Network error — try again.')+'</b><br>'+esc(e);
  }
}
"""

_SIGNATURE = "function fill(m){document.getElementById('mint').value=m;check();}"
_CHECK_RE = re.compile(r"(?:async\s+)?function check\(\)\{.*?(?=</script>)", re.S)
# Also match: function check(){...} followed by </script> OR next function / end
_CHECK_RE2 = re.compile(r"(?:async\s+)?function check\s*\(\)\s*\{", re.S)

def _patch_html(text: str) -> str:
    if not text:
        return text
    # 1) Old behaviour: exact fill() signature page
    if _SIGNATURE in text:
        new_text, n = _CHECK_RE.subn(lambda _m: LIVE_JS.strip(), text, count=1)
        if n:
            return new_text
    # 2) FIX: ANY page with a check() function (CHECK-button page in screenshot)
    # Replace from "function check()" up to the matching closing of that function.
    # Simple robust approach: replace up to </script> if check() is the last function,
    # otherwise fall back to regex above.
    if "function check" in text:
        new_text, n = _CHECK_RE.subn(lambda _m: LIVE_JS.strip(), text, count=1)
        if n:
            return new_text
        # check() is not followed by </script> on this page — splice by brace counting
        m = _CHECK_RE2.search(text)
        if m:
            i, depth = m.start(), 0
            j = text.find("{", m.start())
            k = j
            while k < len(text):
                if text[k] == "{":
                    depth += 1
                elif text[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if depth == 0:
                return text[:i] + LIVE_JS.strip() + text[k+1:]
    # 3) FIX: page has #mint / #out but NO check() at all — inject LIVE_JS
    if 'id="mint"' in text or "id='mint'" in text:
        if "</script>" in text:
            return text.replace("</script>", "<script>\n" + LIVE_JS.strip() + "\n</script>", 1)
        if "</body>" in text:
            return text.replace("</body>", "<script>\n" + LIVE_JS.strip() + "\n</script></body>", 1)
    # 4) last resort: same text replacements as before
    new_text = text.replace("Demo preview — open /omni for the live verdict.", "LIVE — calling /omni...")
    return new_text.replace("Demo preview", "LIVE")

def _ensure_omni(g: dict) -> None:
    """Register /omni if missing. Prefer existing build_omni / build_signal."""
    app = g.get("app")
    if app is None:
        print("[patch_live_fix] no app — skip /omni")
        return
    # FIX v2: DO NOT skip when /omni already exists. The existing /omni is
    # the broken one: its handler was declared as `def omni(request)` with
    # NO `: Request` annotation, so FastAPI treats `request` as a REQUIRED
    # query param -> GET /omni?mint=... returns 422 missing [query, request].
    # Remove ALL old /omni routes and register the fixed one below.
    try:
        before = len(app.router.routes)
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/omni"]
        print(f"[patch_live_fix] removed {before - len(app.router.routes)} old /omni route(s)")
    except Exception as e:
        print(f"[patch_live_fix] could not remove old /omni: {e}")
    from fastapi import Query, Request, HTTPException
    MINT_RE = g.get("MINT_RE") or re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    rate_limited = g.get("rate_limited")
    client_ip = g.get("client_ip") or (lambda r: "unknown")
    build_omni = g.get("build_omni")
    build_signal = g.get("build_signal")
    agent_view = g.get("_tvibe_agent_view")
    async def _fallback_build(client, mint: str):
        if callable(build_omni):
            return await build_omni(client, mint)
        if callable(build_signal):
            result = await build_signal(client, mint, security=True)
            if isinstance(result, tuple) and result:
                result = result[0]
            return result if isinstance(result, dict) else {"mint": mint, "error": "empty"}
        return {"mint": mint, "error": "no_builder", "action": "skip", "nfa": True}
    def _to_agent(pkt: dict) -> dict:
        if callable(agent_view):
            try:
                return agent_view(pkt)
            except Exception:
                pass
        dec = pkt.get("decision") if isinstance(pkt.get("decision"), dict) else {}
        f = pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
        verdict = (dec.get("verdict") or pkt.get("verdict") or "caution")
        verdict = verdict.lower() if isinstance(verdict, str) else "caution"
        pass_ = f.get("pass")
        blockers = list(dec.get("blockers") or pkt.get("blockers") or [])
        if pass_ is True and not blockers and verdict not in ("avoid", "skip"):
            action = "pass"
        elif verdict in ("avoid", "skip") or blockers:
            action = "skip"
        else:
            action = "review"
        return {"mint": pkt.get("mint"), "action": action, "verdict": verdict,
                "filter": {"pass": bool(pass_) if pass_ is not None else False},
                "risk_score": dec.get("risk_score") if dec.get("risk_score") is not None else pkt.get("risk_score"),
                "liquidity_usd": pkt.get("liquidity_usd"),
                "unknowns": list(dec.get("unknowns") or pkt.get("unknowns") or [])[:6],
                "blockers": blockers[:6], "valid_for_s": 30, "nfa": True}
    @app.get("/omni", tags=["product"])
    async def omni_live_fix(
        request: Request,  # NOTE: annotated : Request — FastAPI does NOT treat this as a query param
        mint: str | None = Query(default=None),
        view: str = Query("full", description="full | agent"),
    ):
        # v3: mint optional here. Old callers may send ?request=<mint> only.
        # Reading from query_params sees BOTH names without any alias collision.
        if not mint:
            mint = (request.query_params.get("mint") or request.query_params.get("request") or "").strip()
        try:
            if callable(rate_limited):
                wait = rate_limited(client_ip(request), cost=4)
                if wait:
                    raise HTTPException(status_code=429, detail=f"rate limited, retry after {wait}s",
                                        headers={"Retry-After": str(int(wait))})
        except HTTPException:
            raise
        except Exception:
            pass
        mint = (mint or "").strip()
        if not MINT_RE.match(mint):
            raise HTTPException(status_code=400, detail="Invalid Solana token mint address")
        client = getattr(request.app.state, "client", None)
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                pkt = await _fallback_build(client, mint)
        else:
            pkt = await _fallback_build(client, mint)
        if not isinstance(pkt, dict):
            pkt = {"mint": mint, "error": "bad_packet", "nfa": True}
        if (view or "").strip().lower() in ("agent", "compact", "action"):
            return _to_agent(pkt)
        return pkt
    print("[patch_live_fix] /omni registered (fallback)")

def _ensure_play(g: dict) -> None:
    """FIX 1 — tolerant /play.

    The 422 came from a handler declared like `def play(request)` with NO
    `: Request` annotation: FastAPI treats bare `request` as a required
    QUERY param. This replacement accepts ?mint= (what the frontend sends)
    AND ?request= (what the old buggy callers sent), so neither 422s.
    It delegates to the SAME builder as /omni, so /play and /omni agree.
    """
    app = g.get("app")
    if app is None:
        return
    # Drop any old broken /play route(s) so ours is the only one.
    try:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/play"]
    except Exception:
        pass
    from fastapi import Query, Request, HTTPException
    MINT_RE = g.get("MINT_RE") or re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    build_omni = g.get("build_omni")
    build_signal = g.get("build_signal")
    async def _build(client, mint: str):
        if callable(build_omni):
            return await build_omni(client, mint)
        if callable(build_signal):
            result = await build_signal(client, mint, security=True)
            if isinstance(result, tuple) and result:
                result = result[0]
            return result if isinstance(result, dict) else {"mint": mint, "error": "empty"}
        return {"mint": mint, "error": "no_builder", "nfa": True}
    @app.get("/play", tags=["product"])
    async def play_fixed(
        request: Request,  # annotated -> NOT a query param
        mint: str | None = Query(default=None),
        view: str = Query("full"),
    ):
        # v3: NO Query(alias="request") here — that alias + `request: Request`
        # could make FastAPI reject the whole route and kill apply().
        # query_params sees both ?mint= and ?request= with zero alias risk.
        _mint = (mint or "").strip()
        if not _mint:
            _mint = (request.query_params.get("mint") or request.query_params.get("request") or "").strip()
        if not _mint:
            raise HTTPException(status_code=422, detail="mint is required: /play?mint=<MINT>")
        if not MINT_RE.match(_mint):
            raise HTTPException(status_code=400, detail="Invalid Solana token mint address")
        client = getattr(request.app.state, "client", None)
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                pkt = await _build(client, _mint)
        else:
            pkt = await _build(client, _mint)
        return pkt if isinstance(pkt, dict) else {"mint": _mint, "error": "bad_packet", "nfa": True}
    print("[patch_live_fix] /play registered (tolerant: ?mint= or ?request=)")

class LiveFixASGI:
    """Pure ASGI wrapper: patches GET / (live check) and guards GET /health."""
    def __init__(self, inner, version="?"):
        self.inner = inner
        self.version = version
    def __getattr__(self, name):
        return getattr(self.inner, name)
    async def __call__(self, scope, receive, send):
        # FIX v2 (bulletproof): rewrite query string for broken endpoints.
        # Any handler declared as `def xxx(request)` without `: Request`
        # makes FastAPI demand ?request=... -> 422. The frontend only sends
        # ?mint=..., so inject the missing param at ASGI level before the
        # inner app ever sees the request. Works for /omni, /play, /signal
        # no matter which file registered the broken route, or in what order.
        if scope.get("type") == "http" and scope.get("method") == "GET" and scope.get("path") in ("/omni", "/play", "/signal", "/signals"):
            try:
                from urllib.parse import parse_qsl, urlencode
                qs = scope.get("query_string", b"").decode("latin-1")
                params = parse_qsl(qs, keep_blank_values=True)
                keys = {k for k, _ in params}
                mint = dict(params).get("mint") or dict(params).get("request") or ""
                if mint and "request" not in keys:
                    params.append(("request", mint))
                if mint and "mint" not in keys:
                    params.append(("mint", mint))
                scope = dict(scope)
                scope["query_string"] = urlencode(params).encode("latin-1")
            except Exception as e:
                print(f"[patch_live_fix] query rewrite failed (non-fatal): {e}")
        if (scope.get("type") != "http" or scope.get("method") != "GET"
                or scope.get("path") not in ("/", "/health")):
            return await self.inner(scope, receive, send)
        path = scope["path"]
        start = None
        chunks = []
        err = None
        async def cap(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
        try:
            await self.inner(scope, receive, cap)
        except Exception as e:
            err = e
        status = start["status"] if start else 500
        headers = list(start["headers"]) if start else []
        body = b"".join(chunks)
        hd = {k.lower(): v for k, v in headers}
        ctype = hd.get(b"content-type", b"").decode("latin-1").lower()
        encoded = b"content-encoding" in hd
        if path == "/health":
            if err is not None or start is None or status >= 500:
                note = (repr(err) if err is not None else "health_handler_status_%s" % status)[:240]
                print("[patch_live_fix] /health failed -> fallback:", note)
                out = {"status": "degraded", "version": str(self.version), "ts": int(time.time()),
                       "loader": "main", "health_error": note}
                return await _send(send, 200, [(b"cache-control", b"no-store")],
                                   json.dumps(out).encode(), b"application/json")
            if "json" in ctype and not encoded:
                try:
                    data = json.loads(body.decode("utf-8", "ignore"))
                    if isinstance(data, dict):
                        data.setdefault("loader", "main")
                        body = json.dumps(data).encode()
                except Exception:
                    pass
        else:
            if err is not None and start is None:
                raise err
            if status == 200 and "text/html" in ctype and not encoded:
                text = body.decode("utf-8", "ignore")
                patched = _patch_html(text)
                if patched != text:
                    body = patched.encode("utf-8")
        keep = [(k, v) for k, v in headers if k.lower() not in (b"content-length",)]
        await send({"type": "http.response.start", "status": status,
                    "headers": keep + [(b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

async def _send(send, status, headers, body, ctype):
    await send({"type": "http.response.start", "status": status,
                "headers": list(headers) + [(b"content-type", ctype), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})

def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
 