"""patch_live_fix.py — v21, the polished one (paste-safe, complete replacement).
API: /omni + /play at ASGI layer — inner fails or errors -> DexScreener
fallback, always HTTP 200, never PASS. Fallback math fully guarded.
Homepage: injects polished check() + English-only static text — 4-card grid, TOKEN TO SELL label,
plain-English flags, error cards, agent links. Also probe, query
rewrite, /health never-500, /agent + /agent.json.
"""
from __future__ import annotations
import asyncio, json, re, time
import urllib.request

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/"

AGENT_SPEC = {
  "service": "TVibe FILTER",
  "description": "Solana token signal API for AI agents. Give it a mint, get a verdict plus reasons. Not financial advice.",
  "base_url": "https://signal-api-24q4.onrender.com",
  "start_here": "GET /agent.json (this file) or GET /agent (Markdown). Then call /omni.",
  "endpoints": {"/omni": "MAIN. GET /omni?mint=<MINT>. Also accepts ?request=<MINT>.", "/play": "Same builder as /omni. GET /play?mint=<MINT>.", "/stats": "Aggregate stats.", "/health": "Health check.", "/agent.json": "This spec.", "/agent": "Same spec in Markdown."},
  "request": {"mint": "Required. Solana token mint, base58, 32-44 chars."},
  "response": {"always_http_200": True, "error_field": "If 'error' is present, the token could NOT be evaluated. Treat as SKIP.",
    "fields": {"mint": "Echo.", "verdict": "PASS | REVIEW | CAUTION | AVOID | SKIP.", "risk": "Risk score 0-100.", "liquidity": "Pool liquidity USD.", "price": "Price USD.", "signals": "Codes explaining the verdict.", "nfa": True, "fallback": "True when answered by the direct DexScreener fallback."}},
  "verdicts": {"PASS": "No hard blockers. Still DYOR.", "REVIEW": "Mixed signals.", "CAUTION": "Material risks. Small size or skip.", "AVOID": "Hard blockers. Do not buy.", "SKIP": "No usable pair or no data."},
  "signals": {"very_low_liquidity": "Liquidity extremely low. Hard to exit.", "low_liquidity": "Liquidity low.", "no_recent_trades": "No trades recently.", "dead_pool": "Pool inactive or dead.", "dominant_holder": "One holder dominates. Rug risk.", "lp_unverified": "LP not verified.", "new_pair": "Pair recently created.", "mint_revoked": "Mint authority revoked. Good.", "freeze_revoked": "Freeze authority revoked. Good."},
  "rules_for_agents": ["Check 'error' first. Error means SKIP.", "Verdict comes from blockers/signals, not the risk number alone.", "AVOID means do not buy. PASS is not a buy recommendation.", "Re-check before trading.", "Fallback answers (fallback=true) never return PASS."],
}

AGENT_MD = """# TVibe FILTER — agent spec
Solana token signal API. Give it a mint, get a verdict plus reasons. Not financial advice.
Base URL: https://signal-api-24q4.onrender.com
Quickstart: GET /agent (this) | GET /agent.json (machine) | GET /omni?mint=<MINT> | GET /play | GET /stats | GET /health
Response: always HTTP 200 JSON. If `error` is present -> SKIP, never trade on it.
Fields: mint, verdict, risk (0-100), liquidity (USD), price (USD), signals, nfa=true, fallback (bool).
Verdicts: PASS no hard blockers (still DYOR) | REVIEW mixed | CAUTION material risks | AVOID hard blockers, do not buy | SKIP no usable pair.
Rules: 1. Check `error` first. 2. Verdict from blockers, not risk number alone. 3. AVOID = do not buy. 4. Re-check before trading. 5. Fallback never returns PASS.
"""


_HOME_JS = r"""
async function check(){
var m=(document.getElementById('mint').value||'').trim(),o=document.getElementById('out');
if(!o)return;
var e=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
var n=function(v,d){if(v==null||v==='')return'—';var x=Number(v);return isFinite(x)?x.toLocaleString('en-US',{maximumFractionDigits:d}):e(v);};
var sh=function(x){return x.length>10?x.slice(0,4)+'…'+x.slice(-4):x;};
var F={'very_low_liquidity':'Liquidity extremely low — hard to exit','low_liquidity':'Liquidity low','no_recent_trades':'No recent trades','dead_pool':'Pool dead / inactive','dominant_holder':'One holder owns too much — rug risk','lp_unverified':'LP not verified','new_pair':'Pair recently created','mint_revoked':'Mint authority revoked — good','freeze_revoked':'Freeze authority revoked — good','no_pair':'No pair'};
var ft=function(x){return F[x]||String(x);};
if(!m){o.innerHTML='<b>Paste a mint first.</b>';return;}
if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){o.innerHTML='<b>Not a mint — 32-44 base58 chars, paste the full address.</b>';return;}
var q=encodeURIComponent(m);
var links='<a href="/omni?mint='+q+'" target="_blank" style="color:#00F0FF">Open /omni JSON →</a> <a href="/play?mint='+q+'" target="_blank" style="color:#00F0FF">Open /play →</a>';
var ag='<div style="margin-top:10px;font-size:12px;color:#888">Agent endpoints: <a href="/agent.json" target="_blank" style="color:#00F0FF">/agent.json</a> • <a href="/agent" target="_blank" style="color:#00F0FF">/agent</a> • <a href="/stats" target="_blank" style="color:#00F0FF">/stats</a></div>';
var head='<div style="font-size:15px;margin-bottom:8px">TOKEN TO SELL: <b style="font-family:monospace">'+e(sh(m))+'</b></div>';
o.innerHTML=head+'<b>Checking…</b> (first request can take a few seconds)';
try{
var c=new AbortController(),t=setTimeout(function(){c.abort();},45000);
var r=await fetch('/omni?mint='+q,{cache:'no-store',signal:c.signal});
clearTimeout(t);
var d=await r.json().catch(function(){return{};});
if(!r.ok||d.error){
var msg=d.detail||d.error||d.message||'';
if(typeof msg!=='string')msg=JSON.stringify(msg);
var isPair=d.error==='no_pair';
o.innerHTML=head+'<div style="border:1px solid #555;background:#1a1a1a;padding:12px"><b style="font-size:18px">'+(isPair?'NO PAIR':'COULD NOT SCORE')+'</b><br><span style="color:#ccc">'+(isPair?'This token has no pair on DexScreener — not tradable yet, skip it.':e(msg).slice(0,200))+'</span></div><br>'+links+ag;
return;}
var dec=(d.decision&&typeof d.decision==='object')?d.decision:{};
var raw=String(dec.verdict||d.verdict||d.action||'').toLowerCase();
var passOk=!(d.filter&&d.filter.pass===false);
var label=raw==='ok'||raw==='pass'?(passOk?'PASS':'REVIEW'):raw==='avoid'?'AVOID':raw==='skip'?'SKIP':raw==='caution'?'CAUTION':raw==='review'?'REVIEW':raw?raw.toUpperCase():'—';
var col={PASS:['#00D26A','#000'],REVIEW:['#FFC107','#000'],CAUTION:['#FF7A00','#000'],AVOID:['#FF3B30','#fff'],SKIP:['#8A8F98','#000']}[label]||['#00F0FF','#000'];
var risk=dec.risk_score!=null?dec.risk_score:(d.risk_score!=null?d.risk_score:(d.risk!=null?d.risk:null));
var rn=(risk==null||risk==='')?null:Number(risk);
var band=rn==null?'—':rn>=60?'HIGH':rn>=30?'MED':'LOW';
var liq=d.liquidity_usd!=null?d.liquidity_usd:(d.liquidity!=null?d.liquidity:((d.pair&&d.pair.liquidity&&d.pair.liquidity.usd)!=null?d.pair.liquidity.usd:null));
var price=d.price_usd!=null?d.price_usd:(d.price!=null?d.price:((d.pair&&d.pair.priceUsd)!=null?d.pair.priceUsd:null));
var pk=function(a,b){return(a&&a.length)?a:(b||[]);};
var fl=pk(dec.blockers,d.blockers).concat(pk(dec.cautions,d.cautions)).concat(pk(dec.unknowns,d.unknowns)).concat(d.signals||[]);
fl=fl.filter(function(x,i){return fl.indexOf(x)===i;}).slice(0,6);
var card=function(t,v,ss){return'<div style="border:1px solid #333;background:#14161c;padding:10px"><div style="font-size:11px;color:#888;letter-spacing:1px">'+t+'</div><div style="font-size:20px;font-weight:800;font-family:monospace;margin:4px 0">'+v+'</div><div style="font-size:12px;color:#aaa">'+ss+'</div></div>';};
var grid='<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0">'
+card('VERDICT','<span style="display:inline-block;padding:4px 10px;background:'+col[0]+';color:'+col[1]+'">'+e(label)+'</span>','')
+card('RISK',(rn==null?'—':e(rn)+'/100'),'Level: '+band)
+card('LIQUIDITY','$'+n(liq,0),'')
+card('PRICE','$'+n(price,8),'')+'</div>';
var flHtml=fl.length?'<ul style="margin:8px 0;padding-left:18px">'+fl.map(function(x){return'<li style="color:#ddd">'+e(ft(typeof x==='string'?x:JSON.stringify(x)))+'</li>';}).join('')+'</ul>':'';
var note=d.fallback?'<div style="font-size:12px;color:#FFC107;margin-top:6px">Fallback result — mint/freeze not verified here, so no PASS.</div>':'';
o.innerHTML=head+'<div style="font-size:16px;font-weight:800">LIVE</div>'+grid+flHtml+note+'<br>'+links+ag;
}catch(err){
o.innerHTML=head+'<div style="border:1px solid #555;background:#1a1a1a;padding:12px"><b>'+(err&&err.name==='AbortError'?'Timed out — server may be waking up, hit CHECK again.':'Network error — try again.')+'</b></div><br>'+links+ag;}
}
setTimeout(function(){if(window.check!==check)window.check=check;},1000);
""".encode("utf-8")



async def _send(send, status, headers, body, ctype):
    await send({"type": "http.response.start", "status": status,
                "headers": list(headers) + [(b"content-type", ctype),
                                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class LiveFixASGI:
    def __init__(self, inner, version):
        self.inner = inner
        self.version = version

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET" and scope.get("path") in ("/agent.json", "/agent", "/spec"):
            if scope.get("path") == "/agent.json":
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            json.dumps(AGENT_SPEC).encode(), b"application/json")
            else:
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            AGENT_MD.encode("utf-8"), b"text/markdown; charset=utf-8")
            return
        if scope.get("type") == "http" and scope.get("path") == "/__main_status":
            body = json.dumps({"main_py": "v4", "patch_live_fix": "v21",
                               "fix": "omni DexScreener fallback"}).encode()
            await _send(send, 200, [(b"cache-control", b"no-store")], body, b"application/json")
            return
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/omni", "/play", "/signal", "/signals"):
            try:
                from urllib.parse import parse_qsl, urlencode
                qs = scope.get("query_string", b"").decode("latin-1")
                params = parse_qsl(qs, keep_blank_values=True)
                keys = {k for k, _ in params}
                d = dict(params)
                mint = d.get("mint") or d.get("request") or ""
                if mint and "request" not in keys:
                    params.append(("request", mint))
                if mint and "mint" not in keys:
                    params.append(("mint", mint))
                scope = dict(scope)
                scope["query_string"] = urlencode(params).encode("latin-1")
            except Exception as e:
                print(f"[patch_live_fix] query rewrite failed (non-fatal): {e}")
        # 2b) /omni + /play: never 404/500 — inner fails or errors -> fallback.
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/omni", "/play"):
            try:
                from urllib.parse import parse_qsl as _pq
                _qs = scope.get("query_string", b"").decode("latin-1")
                _d = dict(_pq(_qs, keep_blank_values=True))
                _mint = (_d.get("mint") or _d.get("request") or "").strip()
            except Exception:
                _mint = ""
            if _mint and MINT_RE.match(_mint):
                _start, _chunks = None, []

                async def _cap2(message):
                    nonlocal _start
                    if message["type"] == "http.response.start":
                        _start = message
                    elif message["type"] == "http.response.body":
                        _chunks.append(message.get("body", b""))

                try:
                    await asyncio.wait_for(self.inner(scope, receive, _cap2), timeout=30)
                except Exception as _e:
                    print("[patch_live_fix] omni inner failed:", repr(_e)[:200])
                    _start = None
                _status = _start["status"] if _start else 500
                _body = b"".join(_chunks)
                _ok = False
                if _status == 200:
                    try:
                        _pkt0 = json.loads(_body.decode("utf-8", "ignore"))
                        _ok = isinstance(_pkt0, dict) and not _pkt0.get("error") and _pkt0.get("verdict")
                    except Exception:
                        _ok = False
                if _ok:
                    _h = list(_start["headers"]) if _start else []
                    _keep = [(k, v) for k, v in _h if k.lower() != b"content-length"]
                    await send({"type": "http.response.start", "status": _status,
                                "headers": _keep + [(b"content-length", str(len(_body)).encode())]})
                    await send({"type": "http.response.body", "body": _body})
                    return
                _pkt = await asyncio.to_thread(_dex_fallback_sync, _mint)
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            json.dumps(_pkt).encode(), b"application/json")
                return
            return await self.inner(scope, receive, send)
        if (scope.get("type") != "http" or scope.get("method") != "GET"
                or scope.get("path") not in ("/", "/health")):
            return await self.inner(scope, receive, send)
        path = scope["path"]
        start, chunks, err = None, [], None

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
        if path == "/" and status < 400 and b"</body>" in body:
            try:
                _ct = b""
                for _k, _v in headers:
                    if _k.lower() == b"content-type":
                        _ct = _v
                if b"text/html" in _ct:
                    body = body.replace(b"in English or Vietnamese", b"in English")
                    body = body.replace(b"</body>", b"<script>\n" + _HOME_JS + b"\n</script></body>", 1)
            except Exception as _e:
                print("[patch_live_fix] home inject failed (non-fatal):", repr(_e)[:200])
        if path == "/health" and (err is not None or start is None or status >= 500):
            note = (repr(err) if err is not None else "health_handler_status_%s" % status)[:240]
            out = {"status": "degraded", "version": str(self.version), "ts": int(time.time()),
                   "loader": "main", "health_error": note}
            await _send(send, 200, [(b"cache-control", b"no-store")],
                        json.dumps(out).encode(), b"application/json")
            return
        keep = [(k, v) for k, v in headers if k.lower() != b"content-length"]
        await send({"type": "http.response.start", "status": status,
                    "headers": keep + [(b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def _dex_fallback_sync(mint):
    """Direct DexScreener query. Never raises. Conservative verdicts only."""
    try:
        req = urllib.request.Request(DEX_URL + mint, headers={"User-Agent": "TVibe-FILTER/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", "ignore")
        data = json.loads(raw) if raw else {}
    except Exception as e:
        return {"mint": mint, "verdict": "SKIP", "error": "fallback_upstream_failed",
                "detail": repr(e)[:200], "nfa": True, "fallback": True}
    try:
        if not isinstance(data, dict):
            data = {}
        pairs = [p for p in (data.get("pairs") or []) if isinstance(p, dict)
                 and ((p.get("baseToken") or {}).get("address") if isinstance(p.get("baseToken") or {}, dict) else None) == mint]
        if not pairs:
            return {"mint": mint, "verdict": "SKIP", "error": "no_pair",
                    "note": "DexScreener returned no pairs for this mint (fallback path).",
                    "nfa": True, "fallback": True}

        def _liq(p):
            lo = p.get("liquidity") or {}
            return (lo.get("usd") or 0) if isinstance(lo, dict) else 0
        best = max(pairs, key=_liq)
        liq = _liq(best) or 0
        price = best.get("priceUsd")
        signals = []
        if liq < 5000:
            signals.append("very_low_liquidity")
        elif liq < 20000:
            signals.append("low_liquidity")
        txns = best.get("txns") or {}
        tx5 = txns.get("m5") if isinstance(txns, dict) else None
        if not isinstance(tx5, dict):
            tx5 = {}
        if ((tx5.get("buys") or 0) + (tx5.get("sells") or 0)) == 0:
            signals.append("no_recent_trades")
        try:
            created_ms = float(best.get("pairCreatedAt")) if best.get("pairCreatedAt") is not None else None
        except Exception:
            created_ms = None
        if created_ms and (time.time() * 1000 - created_ms) < 86400000:
            signals.append("new_pair")
        if liq < 5000:
            verdict, risk = "CAUTION", 60
        elif liq < 20000:
            verdict, risk = "CAUTION", 45
        else:
            verdict, risk = "REVIEW", 30
        try:
            price = float(price) if price is not None else None
        except Exception:
            price = None
        qt = best.get("quoteToken") or {}
        return {"mint": mint, "verdict": verdict, "risk": risk, "risk_score": risk,
                "liquidity": liq, "liquidity_usd": liq, "price": price, "price_usd": price,
                "signals": signals, "pair": best.get("dexId"),
                "quote": (qt.get("symbol") if isinstance(qt, dict) else None),
                "nfa": True, "fallback": True,
                "note": "Fallback verdict from DexScreener direct: authorities not verified here, so PASS is never returned."}
    except Exception as e:
        return {"mint": mint, "verdict": "SKIP", "error": "fallback_compute_failed",
                "detail": repr(e)[:200], "nfa": True, "fallback": True}


async def _dex_fallback(client, mint):
    return await asyncio.to_thread(_dex_fallback_sync, mint)


# No FastAPI route registration: the ASGI wrapper answers /omni + /play itself.
def _omni_impl_sync(mint):
    """Sync fallback for main.py FIX 1."""
    try:
        return _dex_fallback_sync((mint or "").strip())
    except Exception as _e:
        return {"mint": mint, "verdict": "SKIP", "error": "omni_impl_failed",
                "detail": repr(_e)[:200], "nfa": True}


def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
    g.setdefault("omni_impl", _omni_impl_sync)
    app = g.get("app")
    if app is not None and not isinstance(app, LiveFixASGI):
        version = g.get("VERSION") or getattr(app, "version", None) or "live-fix"
        g["app"] = LiveFixASGI(app, version)
    print("[patch_live_fix] applied v21 (omni fallback + agent spec + asgi wrapper)")
