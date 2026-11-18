"""patch_live_fix.py — MINI v16 COMPLETE (paste-safe).
Replace ENTIRE content of patch_live_fix.py on GitHub with this file.
v16 COMPLETE = v15 + friendly No-pair error card + hero-hide fix (hero shares a card with the form):
Trader-first system (see reply for the app comparison):
COMPLETE = every verdict on the page is restyled, not just #out:
- CHECK result badge: FULL-WIDTH banner, color + ICON + word (reads in
  1s, in sunlight, even if red/green color-blind).
- Quick buttons "SOL • PASS" / "PEACEFROG • REVIEW" / "COA • REVIEW":
  solid verdict-color buttons (were dim gold text on dark brown).
- Static PASS chip in the SOL card: green chip + check icon.
- Labels "LIVE CORE" / "SOL / USD": brightened, spaced out.
- CAUTION split from REVIEW: CAUTION orange + warning sign, REVIEW amber
  + eye. AVOID red + no-entry sign, PASS green + check, SKIP gray.
- Blockers become chips (dark card, rounded) instead of faint gray lines.
- Numbers in monospace tabular font (Risk, Liquidity, Price line up);
  labels in system font. No webfont download: fast on phone.
- Hero block "SOL PASS / SOL Risk 0/100" hidden: SOL is not the token
  you are about to sell, so it no longer occupies the best slot.
- Mint input labelled TOKEN CẦN BÁN; after CHECK it shows the mint
  being sold (first 4 … last 4), so the slot belongs to your token.
"""
from __future__ import annotations
import json, re, time

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

READABLE = """<style id="tvibe-readable">
body{background:#0F1115!important}
#out{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;color:#F5F5F5!important;font-size:16px;line-height:1.65}
#out li{color:#E6E6E6!important;background:#1C1F26!important;padding:8px 12px!important;margin:6px 0!important;border-radius:8px!important;list-style:none!important}
#out ul{padding-left:0!important}
#out b{font-family:ui-monospace,"SF Mono","Roboto Mono",monospace!important;font-size:18px!important}
#out a{color:#5ED1FF!important;font-weight:700}
p{color:#D9D9D9!important}
#mint{color:#fff!important;font-family:ui-monospace,"SF Mono","Roboto Mono",monospace!important}
</style><script>(function(){var C={AVOID:["#FF3B30","#fff","\u26d4"],SKIP:["#6B7280","#fff","\u2298"],CAUTION:["#FF7A00","#000","\u26a0"],REVIEW:["#FFC107","#000","👁"],PASS:["#00D26A","#000","\u2713"]};function chip(el,t,block){el.dataset.tvibe="1";el.textContent=C[t][2]+" "+t;el.style.background=C[t][0];el.style.color=C[t][1];el.style.fontWeight="800";el.style.borderRadius="10px";el.style.letterSpacing="1px";if(block){el.style.display="block";el.style.fontSize="20px";el.style.padding="14px";el.style.textAlign="center";el.style.margin="10px 0";}else{el.style.display="inline-block";el.style.fontSize="16px";el.style.padding="6px 12px";}}function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
var PLAIN={very_low_liquidity:"Liquidity is very low",low_liquidity:"Liquidity is low",no_recent_trades:"No trades recently",dead_pool:"Pool looks dead",extreme_holder_concentration:"Top holders own most of the supply",dominant_holder:"One holder dominates",lp_unverified:"LP not verified",heavy_buying:"Heavy buying",high_turnover:"High turnover",new_pair:"Pair recently created",high_activity:"High activity",mint_revoked:"Mint authority revoked (good)",freeze_revoked:"Freeze authority revoked (good)"};
function endpointBlock(){if(document.getElementById("tvibe-endpoint-block"))return;var o=document.getElementById("out");if(!o||!o.parentNode)return;var d=document.createElement("div");d.id="tvibe-endpoint-block";d.style.cssText="background:#14171F;border-radius:10px;padding:14px;margin:12px 0;";d.innerHTML='<div style="font-size:12px;color:#8A8F98;letter-spacing:1px;text-transform:uppercase;">Endpoint for Agents</div><pre style="background:#0B0D12;border-radius:8px;padding:10px;overflow:auto;color:#5ED1FF;font-size:13px;margin:8px 0;">GET /omni?mint=TOKEN_MINT_ADDRESS</pre><div style="color:#D9D9D9;font-size:13px;">No API key \u2022 No signup \u2022 Instant JSON \u2022 Full spec: /agent.json</div>';o.parentNode.insertBefore(d,o.nextSibling);}
function errorCard(){var o=document.getElementById("out");if(!o)return;var links=[];var as=o.querySelectorAll("a");for(var j=0;j<as.length;j++){links.push(as[j].outerHTML);}o.dataset.tvibeError="1";o.innerHTML='<div style="background:#1C1F26;border-radius:10px;padding:14px;margin:10px 0;"><div style="font-size:18px;font-weight:800;color:#FFC107;">No pair found</div><div style="color:#D9D9D9;font-size:14px;line-height:1.6;margin-top:6px;">DexScreener has no Solana pair for this mint. This is about the TOKEN, not the API.</div><div style="color:#D9D9D9;font-size:14px;line-height:1.6;margin-top:8px;">Why this happens:<br/>\u2022 Brand-new token, no pair yet<br/>\u2022 Pair quoted in USDC<br/>\u2022 Wrong mint - copy it again from DexScreener / Solscan<br/>\u2022 DexScreener slow - press CHECK once more</div><div style="color:#D9D9D9;font-size:14px;line-height:1.6;margin-top:8px;">Is the API still alive? Press <b>COA \u2022 REVIEW</b> below. If COA returns AVOID, the API is fine - only this mint has no pair.</div><div style="margin-top:10px;">'+links.join(" ")+'</div></div>';}
function cardsResult(){var o=document.getElementById("out");if(!o)return;var tx=o.textContent||"";var vm=tx.match(/(PASS|REVIEW|CAUTION|AVOID|SKIP)/);var rm=tx.match(/Risk\s*(\d+)/);var lm=tx.match(/Liquidity\s*\$([\d,\.]+)/);var pm=tx.match(/Price\s*\$([\d\.]+)/);if(!vm||!rm||!lm||!pm)return;var v=vm[1],risk=parseInt(rm[1],10),liq=lm[1],pr=pm[1];var rl=risk>=60?"high":risk>=30?"medium":"low";var sigs=[];var lis=o.querySelectorAll("li");for(var i=0;i<lis.length;i++){var c=(lis[i].textContent||"").trim();if(c)sigs.push(c);}var links=[];var as=o.querySelectorAll("a");for(var j=0;j<as.length;j++){links.push(as[j].outerHTML);}var chips=sigs.map(function(c){var col=(v==="AVOID"||v==="SKIP")?"#FF3B30":(v==="CAUTION")?"#FF7A00":(v==="REVIEW")?"#FFC107":"#00D26A";return '<span style="display:inline-block;background:'+col+'22;color:'+col+';border:1px solid '+col+';border-radius:999px;padding:4px 10px;margin:3px;font-size:13px;font-weight:700;">'+esc(c)+'</span>';}).join("");var plain=sigs.map(function(c){return PLAIN[c]||c;}).join(" \u2022 ");var vcol=C[v][0],vfg=C[v][1];var card=function(l,val,extra){return '<div data-tvibe-card style="background:#1C1F26;border-radius:10px;padding:12px;"><div style="font-size:12px;color:#8A8F98;letter-spacing:1px;text-transform:uppercase;">'+l+'</div><div style="font-size:18px;font-weight:800;margin-top:4px;'+(extra||"")+'">'+val+'</div></div>';};o.dataset.tvibeCards="1";o.innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0;">'+card("Verdict",esc(C[v][2]+" "+v),"background:"+vcol+";color:"+vfg+";border-radius:8px;padding:6px 10px;display:inline-block;font-size:16px;")+card("Risk Score",risk+" ("+rl+")")+card("Liquidity","$"+esc(liq))+card("Price","$"+esc(pr))+'</div>'+(sigs.length?'<div style="font-size:12px;color:#8A8F98;letter-spacing:1px;text-transform:uppercase;margin-top:6px;">Flags</div><div style="margin:6px 0;">'+chips+'</div><div style="color:#D9D9D9;font-size:14px;line-height:1.5;">'+esc(plain)+'</div>':"")+'<div style="margin-top:10px;">'+links.join(" ")+'</div>';endpointBlock();}
function cleanHero(){var o=document.getElementById("out");var all=document.querySelectorAll("span,b,div");for(var i=0;i<all.length;i++){var el=all[i];if(el.dataset.tvibeHero)continue;if(o&&o.contains(el))continue;if((el.textContent||"").trim()!=="PASS")continue;el.dataset.tvibeHero="1";var card=null,cur=el;for(var k=0;k<6&&cur.parentElement;k++){cur=cur.parentElement;if(cur.querySelector("input"))break;if(o&&cur.contains(o))break;if((cur.textContent||"").indexOf("Risk")>=0){card=cur;}}if(card){card.dataset.tvibeHero="1";card.style.display="none";}else if(el.children.length===0){el.style.display="none";}}}function tokenLabel(){var inp=document.getElementById("mint");if(!inp)return;var lab=document.getElementById("tvibe-token-label");if(!lab){lab=document.createElement("div");lab.id="tvibe-token-label";lab.style.cssText="font-size:13px;letter-spacing:2px;color:#8A8F98;font-weight:700;margin:0 0 6px;";inp.parentNode.insertBefore(lab,inp);}var o=document.getElementById("out");var m=(inp.value||"").trim();if(o&&(o.textContent||"").indexOf("LIVE")>=0&&m){lab.textContent="TOKEN CẦN BÁN • "+m.slice(0,4)+"…"+m.slice(-4);}else{lab.textContent="TOKEN CẦN BÁN — DÁN MINT, BẤM CHECK";}}function paint(){cleanHero();var o=document.getElementById("out");if(o&&(o.textContent||"").indexOf("LIVE")>=0&&!o.dataset.tvibeCards){cardsResult();}if(o&&((o.textContent||"").indexOf("Not found")>=0||(o.textContent||"").indexOf("no Solana pair")>=0)&&!o.dataset.tvibeError){errorCard();}if(o&&!o.dataset.tvibeCards&&!o.dataset.tvibeError){var els=o.querySelectorAll("span,b,div");for(var i=0;i<els.length;i++){var el=els[i];if(el.dataset.tvibe)continue;var t=(el.textContent||"").trim().toUpperCase();if(C[t]&&el.children.length===0)chip(el,t,true);}}var all=document.querySelectorAll("span,b,div,button,a");for(var j=0;j<all.length;j++){var a2=all[j];if(a2.dataset.tvibe)continue;if(o&&o.contains(a2))continue;var tx=(a2.textContent||"").trim();var m=tx.match(/^(.+?)\s*[\u2022\u00b7]\s*(PASS|REVIEW|CAUTION|AVOID|SKIP)$/i);if(m&&a2.children.length===0){var v=m[2].toUpperCase();a2.dataset.tvibe="1";a2.textContent=m[1].trim()+" \u2022 "+C[v][2]+" "+v;a2.style.background=C[v][0];a2.style.color=C[v][1];a2.style.fontWeight="800";a2.style.padding="10px 14px";a2.style.borderRadius="8px";a2.style.display="inline-block";a2.style.margin="4px";continue;}var t2=tx.toUpperCase();if(C[t2]&&a2.children.length===0)chip(a2,t2,false);if(tx==="LIVE CORE"||tx==="SOL / USD"){a2.dataset.tvibe="1";a2.style.color="#B8B8B8";a2.style.letterSpacing="3px";a2.style.fontSize="12px";}}tokenLabel();}paint();if(window.MutationObserver){new MutationObserver(paint).observe(document.body,{childList:true,subtree:true,characterData:true});}})();</script>"""

AGENT_SPEC = {
  "service": "TVibe FILTER",
  "description": "Solana token signal API for AI agents. Give it a token mint, get a verdict plus the reasons. Not financial advice.",
  "base_url": "https://signal-api-24q4.onrender.com",
  "start_here": "GET /agent.json (this file) or GET /agent (same spec in Markdown). Then call /omni.",
  "endpoints": {
    "/omni": "MAIN endpoint. GET /omni?mint=<MINT>. Also accepts ?request=<MINT>. Returns JSON.",
    "/play": "Same builder as /omni. GET /play?mint=<MINT>.",
    "/stats": "Aggregate stats: tracked tokens, bad-in-24h share, avoid-vs-ok gap.",
    "/health": "Health check. Returns status plus version.",
    "/agent.json": "This spec, machine-readable.",
    "/agent": "Same spec in Markdown.",
    "/": "Human demo page: paste a mint, press CHECK. It calls /omni and renders the same JSON."
  },
  "request": {"mint": "Required. Solana token mint address, base58, 32-44 chars."},
  "response": {
    "always_http_200": True,
    "error_field": "If 'error' is present, the token could NOT be evaluated. Treat as SKIP. Never trade on an error response.",
    "fields": {
      "mint": "Echo of the requested mint.",
      "verdict": "PASS | REVIEW | CAUTION | AVOID | SKIP. See verdicts.",
      "risk": "Risk score 0-100. Higher = riskier. 0 = cleanest seen (SOL). 80 = dangerous (COA).",
      "liquidity": "Pool liquidity in USD. Below about $5,000 is very low.",
      "price": "Token price in USD.",
      "signals": "List of snake_case signal codes explaining the verdict. See signals glossary.",
      "nfa": "True. Not financial advice flag."
    }
  },
  "verdicts": {
    "PASS": "No hard blockers. Token passed the filters. Still do your own research.",
    "REVIEW": "Mixed signals. Look closer before deciding.",
    "CAUTION": "Material risks present. Only trade small size, or skip unless you know why.",
    "AVOID": "Hard blockers present (for example dominant holder, unverified LP, dead pool). Do not buy.",
    "SKIP": "No usable pair or no data. Cannot evaluate."
  },
  "signals": {
    "very_low_liquidity": "Liquidity extremely low. Hard to exit.",
    "low_liquidity": "Liquidity low.",
    "no_recent_trades": "No trades recently. Nobody is trading it.",
    "dead_pool": "Pool inactive or dead.",
    "extreme_holder_concentration": "Top holders own most of the supply.",
    "dominant_holder": "One holder dominates. Rug risk.",
    "lp_unverified": "LP not verified. Liquidity may not be locked.",
    "heavy_buying": "Unusually heavy buying.",
    "high_turnover": "High turnover.",
    "new_pair": "Pair recently created.",
    "high_activity": "High on-chain activity.",
    "mint_revoked": "Mint authority revoked. Good: supply cannot be inflated.",
    "freeze_revoked": "Freeze authority revoked. Good: holders cannot be frozen."
  },
  "rules_for_agents": [
    "Always check the 'error' field first. Error means SKIP, not a verdict.",
    "Verdict is driven by blockers/signals, not by the risk number alone. A low risk number with bad blockers can still be CAUTION or AVOID.",
    "AVOID means do not buy. CAUTION means small size or skip. PASS is not a buy recommendation.",
    "Re-check before trading. Liquidity and holders change fast.",
    "This API is a filter, not financial advice."
  ],
  "examples": {
    "curl_pass": "curl 'https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112'",
    "curl_any_token": "curl 'https://signal-api-24q4.onrender.com/omni?mint=<MINT>'"
  }
}

AGENT_MD = """# TVibe FILTER — agent spec
Solana token signal API for AI agents. Give it a mint, get a verdict plus reasons. Not financial advice.
Base URL: https://signal-api-24q4.onrender.com

## Quickstart
- Read this file: GET /agent  |  Machine-readable: GET /agent.json
- Check a token: GET /omni?mint=<MINT>  (also accepts ?request=<MINT>)
- Same builder: GET /play?mint=<MINT>
- Stats: GET /stats  |  Health: GET /health  |  Demo page: GET /

## Response
Always HTTP 200 JSON. If `error` is present, the token could NOT be evaluated -> treat as SKIP, never trade on it.
Fields: mint, verdict, risk (0-100, higher = riskier), liquidity (USD), price (USD), signals (snake_case codes), nfa=true.

## Verdicts
- PASS: no hard blockers, passed filters. Still DYOR.
- REVIEW: mixed signals, look closer.
- CAUTION: material risks. Small size or skip.
- AVOID: hard blockers (dominant holder, unverified LP, dead pool). Do not buy.
- SKIP: no usable pair or no data.

## Signals
- very_low_liquidity / low_liquidity: hard to exit.
- no_recent_trades: nobody trading it. dead_pool: pool inactive.
- extreme_holder_concentration / dominant_holder: few wallets own most supply, rug risk.
- lp_unverified: LP not verified, may not be locked.
- heavy_buying / high_turnover / new_pair / high_activity: activity signals.
- mint_revoked / freeze_revoked: authorities revoked, good.

## Rules
1. Check `error` first. 2. Verdict comes from blockers, not the risk number alone.
3. AVOID = do not buy. 4. Re-check before trading. 5. Filter, not financial advice.

## Example
curl 'https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112'
"""


async def _send(send, status, headers, body, ctype):
    await send({"type": "http.response.start", "status": status,
                "headers": list(headers) + [(b"content-type", ctype),
                                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})

async def _build(g, client, mint):
    """Call the real builder. NEVER raise — return error JSON instead."""
    try:
        b = g.get("build_omni")
        if callable(b):
            r = await b(client, mint)
            return r if isinstance(r, dict) else {"mint": mint, "error": "bad_packet", "nfa": True}
        s = g.get("build_signal")
        if callable(s):
            r = await s(client, mint, security=True)
            if isinstance(r, tuple) and r:
                r = r[0]
            return r if isinstance(r, dict) else {"mint": mint, "error": "empty", "nfa": True}
        return {"mint": mint, "error": "no_builder", "nfa": True}
    except Exception as e:
        return {"mint": mint, "error": f"upstream_or_no_pair: {e}"[:240],
                "action": "review", "verdict": "review", "nfa": True}

def _register(g):
    app = g.get("app")
    if app is None or not hasattr(app, "router"):
        return
    try:
        app.router.routes[:] = [r for r in app.router.routes
                                if getattr(r, "path", None) not in ("/omni", "/play")]
    except Exception:
        pass
    from fastapi import Query, Request

    @app.get("/omni", tags=["product"])
    async def omni_v9(request: Request, mint: str | None = Query(default=None)):
        m = (mint or request.query_params.get("mint")
             or request.query_params.get("request") or "").strip()
        if not MINT_RE.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                return await _build(g, client, m)
        except Exception as e:
            return {"mint": m, "error": f"upstream_or_no_pair: {e}"[:240],
                    "action": "review", "verdict": "review", "nfa": True}

    @app.get("/play", tags=["product"])
    async def play_v9(request: Request, mint: str | None = Query(default=None)):
        m = (mint or request.query_params.get("mint")
             or request.query_params.get("request") or "").strip()
        if not m:
            return {"error": "mint is required: /play?mint=<MINT>", "mint": None}
        if not MINT_RE.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                return await _build(g, client, m)
        except Exception as e:
            return {"mint": m, "error": f"upstream_or_no_pair: {e}"[:240],
                    "action": "review", "verdict": "review", "nfa": True}
    print("[patch_live_fix] /omni + /play registered (v16, builder wrapped)")

class LiveFixASGI:
    def __init__(self, inner, version, g=None):
        self.inner = inner
        self.version = version
        self.g = g or {}
    def __getattr__(self, name):
        return getattr(self.inner, name)
    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/agent.json", "/agent", "/spec"):
            if scope.get("path") == "/agent.json":
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            json.dumps(AGENT_SPEC).encode(), b"application/json")
            else:
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            AGENT_MD.encode("utf-8"), b"text/markdown; charset=utf-8")
            return
        if scope.get("type") == "http" and scope.get("path") == "/__main_status":
            body = json.dumps({"main_py": "v4", "patch_live_fix": "v16-mini",
                               "fix": "asgi omni/play + readable badges"}).encode()
            await _send(send, 200, [(b"cache-control", b"no-store")], body, b"application/json")
            return
        # v8: answer /omni + /play HERE at ASGI level. Route registration
        # in _register silently fails once the app is wrapped, leaving
        # /omni at FastAPI 404 {"detail": "Not Found"}. This bypasses
        # routing entirely — same trick that makes /__main_status work.
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/omni", "/play"):
            try:
                from urllib.parse import