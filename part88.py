# ---------- v2.66: Surface residuals + offline export in product/llms ----------
VERSION = "2.66.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

# ---- enrich /product ----
_product_prev = globals().get("product_payload")


def product_payload() -> dict:
    base = {
        "name": "TVibex402",
        "one_liner": (
            "TVibex402 omni: one call for verdict, debate, community, regime, DNA, "
            "counterfactual, time-to-death, pre-rug and attention residuals. Measured in public."
        ),
        "primary_call": "GET /omni?mint=ADDRESS",
        "mcp": "omni(mint)",
        "prove_it": [
            "GET /stats",
            "GET /benchmark/prerug",
            "GET /residuals/stats",
            "GET /si/journal/public",
            "GET /accuracy/story",
        ],
        "entity": ["GET /si/core", "GET /si/focus", "GET /si/journal", "GET /si/breath/status"],
        "experimental": [
            "GET /residuals?mint=",
            "GET /residuals/stats",
            "GET /benchmark/prerug/status",
        ],
        "disclaimer": "Heuristics, not financial advice.",
        "version": VERSION,
    }
    if callable(_product_prev):
        try:
            old = _product_prev()
            if isinstance(old, dict):
                old = dict(old)
                old["one_liner"] = base["one_liner"]
                prove = list(old.get("prove_it") or [])
                for x in base["prove_it"]:
                    if x not in prove:
                        prove.append(x)
                old["prove_it"] = prove
                old["experimental"] = base["experimental"]
                old["version"] = VERSION
                return old
        except Exception:
            pass
    return base


@app.get("/product", tags=["product"])
async def product_v266(request: Request):
    return product_payload()


# ---- append residuals section to llms if LLMS head exists ----
_llms_extra = """

## Attention residuals (experimental)
Every signal/omni may include `attention_residuals`: input-dependent weights (alpha) over
risk, debate, historical, community and regime layers (AttnRes-style, heuristic — not a neural net).
- residual_verdict is advisory; decision.verdict stays primary.
- GET /residuals?mint=ADDRESS — inspect fusion for one mint
- GET /residuals/stats — after outcomes resolve, did residual beat base?
"""

_llms_prev = globals().get("llms_txt_body") or globals().get("LLMS_OMNI_HEAD")


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms_txt_v266():
    body = ""
    if callable(_llms_prev):
        try:
            body = await _llms_prev() if asyncio.iscoroutinefunction(_llms_prev) else _llms_prev()
        except Exception:
            body = str(globals().get("LLMS_OMNI_HEAD") or "")
    elif isinstance(_llms_prev, str):
        body = _llms_prev
    else:
        body = str(globals().get("LLMS_OMNI_HEAD") or "# TVibex402\n")
    if "Attention residuals" not in body:
        body = body.rstrip() + _llms_extra
    return body


print(f"[part88] v{VERSION} product + llms residual surface")