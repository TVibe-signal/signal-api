# part126.py - Ensure the Phase B filter (and late fields) on /omni responses (v2.99.2, reviewed)
# /signal already gets filter.* through build_signal; /omni used a path that skipped the final wrappers.
# Review fixes vs v2.99.1:
#   - the wrapper was always async: if the /omni handler is a plain (sync) function FastAPI would have received an
#     un-awaited coroutine. The wrapper now matches the handler type.
#   - when it rebuilds a JSONResponse it keeps the original headers (cache-control etc.).
import functools
import inspect
import json
from typing import Optional


def _enrich_payload(body: dict, policy: Optional[str] = None) -> dict:
    if not isinstance(body, dict):
        return body
    if callable(globals().get("_ensure_shadow_cluster")):
        try:
            _ensure_shadow_cluster(body)
        except Exception:
            pass
    if "system_stress" not in body and callable(globals().get("circuit_status")):
        try:
            st = circuit_status()
            body["system_stress"] = {"state": st.get("state"), "reason": st.get("reason"),
                                     "note": "When open/half, prefer smaller size or wait; data may be stale or partial."}
        except Exception:
            pass
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


def _policy_from(args, kwargs) -> Optional[str]:
    request = kwargs.get("request")
    if request is None:
        for a in args:
            if hasattr(a, "query_params"):
                request = a
                break
    try:
        if request is not None:
            return request.query_params.get("policy") or request.query_params.get("filter_policy")
    except Exception:
        pass
    return None


def _post(res, policy):
    if isinstance(res, dict):
        return _enrich_payload(res, policy)
    body = getattr(res, "body", None)
    if body is not None and hasattr(res, "media_type"):
        try:
            data = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
            if isinstance(data, dict):
                from fastapi.responses import JSONResponse
                headers = {k: v for k, v in dict(getattr(res, "headers", {}) or {}).items()
                           if k.lower() not in ("content-length", "content-type")}
                return JSONResponse(_enrich_payload(data, policy), status_code=getattr(res, "status_code", 200),
                                    headers=headers)
        except Exception as e:
            print("[part126] omni response wrap:", e)
    return res


def _make_wrapper(endpoint):
    if inspect.iscoroutinefunction(endpoint):
        @functools.wraps(endpoint)
        async def wrapped(*args, **kwargs):
            policy = _policy_from(args, kwargs)
            res = await endpoint(*args, **kwargs)
            return _post(res, policy)
    else:
        @functools.wraps(endpoint)
        def wrapped(*args, **kwargs):
            policy = _policy_from(args, kwargs)
            return _post(endpoint(*args, **kwargs), policy)
    wrapped._tvibe_filter_wrapped = True
    return wrapped


def _wrap_omni_endpoint() -> bool:
    try:
        for route in list(app.routes):
            if (getattr(route, "path", None) or "").rstrip("/") != "/omni":
                continue
            endpoint = getattr(route, "endpoint", None)
            if not callable(endpoint):
                continue
            if getattr(endpoint, "_tvibe_filter_wrapped", False):
                return True
            wrapped = _make_wrapper(endpoint)
            route.endpoint = wrapped
            dep = getattr(route, "dependant", None)
            if dep is not None:
                dep.call = wrapped
            print("[part126] wrapped GET /omni for the filter contract (%s)" % ("async" if inspect.iscoroutinefunction(endpoint) else "sync"))
            return True
    except Exception as e:
        print("[part126] wrap_omni:", e)
    return False


if not _wrap_omni_endpoint():
    print("[part126] /omni route not found or not patchable; /signal still carries filter.* via build_signal")

print("[part126] v2.99.2 /omni gets filter.* (and shadow/stress if helpers exist)")
