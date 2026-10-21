# part126.py — Ensure Phase B filter (and late fields) on /omni responses
# /signal already has filter via build_signal; /omni used a path that skipped final wrappers.
VERSION = "2.99.1"
app.version = VERSION
app.openapi_schema = None

import inspect
from typing import Any, Callable, Optional


def _enrich_payload(body: dict, policy: Optional[str] = None) -> dict:
    if not isinstance(body, dict):
        return body
    # shadow_cluster
    if callable(globals().get("_ensure_shadow_cluster")):
        try:
            _ensure_shadow_cluster(body)
        except Exception:
            pass
    # system_stress
    if "system_stress" not in body and callable(globals().get("circuit_status")):
        try:
            st = circuit_status()
            body["system_stress"] = {
                "state": st.get("state"),
                "reason": st.get("reason"),
                "note": "When open/half, prefer smaller size or wait; data may be stale or partial.",
            }
        except Exception:
            pass
    # filter contract
    if callable(globals().get("attach_filter")):
        try:
            attach_filter(body, policy)
        except Exception as e:
            print("[part126] attach_filter:", e)
    elif callable(globals().get("build_filter_block")):
        try:
            body["filter"] = build_filter_block(body, policy)
        except Exception as e:
            print("[part126] build_filter_block:", e)
    return body


def _wrap_omni_endpoint():
    """Find the /omni route and wrap its endpoint so JSON gets filter.*"""
    try:
        for route in list(app.routes):
            path = getattr(route, "path", None) or ""
            if path.rstrip("/") != "/omni":
                continue
            endpoint = getattr(route, "endpoint", None)
            if not callable(endpoint):
                continue
            if getattr(endpoint, "_tvibe_filter_wrapped", False):
                return True

            async def _wrapped(*args, __endpoint=endpoint, **kwargs):
                # extract policy query if present
                policy = None
                request = kwargs.get("request")
                if request is None:
                    for a in args:
                        if hasattr(a, "query_params"):
                            request = a
                            break
                if request is not None:
                    try:
                        policy = request.query_params.get("policy") or request.query_params.get("filter_policy")
                    except Exception:
                        policy = None
                res = __endpoint(*args, **kwargs)
                if inspect.isawaitable(res):
                    res = await res
                # FastAPI may return dict or Response
                if isinstance(res, dict):
                    return _enrich_payload(res, policy)
                # JSONResponse
                body = getattr(res, "body", None)
                if body is not None and hasattr(res, "media_type"):
                    try:
                        import json
                        data = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
                        if isinstance(data, dict):
                            data = _enrich_payload(data, policy)
                            from fastapi.responses import JSONResponse
                            return JSONResponse(data, status_code=getattr(res, "status_code", 200))
                    except Exception as e:
                        print("[part126] omni response wrap:", e)
                return res

            _wrapped._tvibe_filter_wrapped = True
            try:
                route.endpoint = _wrapped
                # starlette may cache endpoint in other attrs
                if hasattr(route, "dependant") and route.dependant is not None:
                    route.dependant.call = _wrapped
            except Exception as e:
                print("[part126] route patch:", e)
                return False
            print("[part126] wrapped GET /omni for filter contract")
            return True
    except Exception as e:
        print("[part126] wrap_omni:", e)
    return False


_ok = _wrap_omni_endpoint()
if not _ok:
    # Fallback: middleware for /omni only
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse as SJSON
    import json

    class _OmniFilterMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            if request.url.path.rstrip("/") != "/omni":
                return response
            if response.status_code != 200:
                return response
            ctype = response.headers.get("content-type") or ""
            if "application/json" not in ctype:
                return response
            try:
                raw = b""
                async for chunk in response.body_iterator:
                    raw += chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode()
                data = json.loads(raw.decode())
                if isinstance(data, dict):
                    pol = request.query_params.get("policy") or request.query_params.get("filter_policy")
                    data = _enrich_payload(data, pol)
                    return SJSON(data, status_code=200)
            except Exception as e:
                print("[part126] middleware:", e)
            return response

    try:
        app.add_middleware(_OmniFilterMiddleware)
        print("[part126] middleware fallback on /omni")
    except Exception as e:
        print("[part126] middleware failed:", e)

print("[part126] v%s omni gets filter.* (and shadow/stress if helpers exist)" % VERSION)