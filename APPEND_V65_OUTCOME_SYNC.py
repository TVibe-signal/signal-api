# TVibe V65 - /cron/outcome SYNC - Fix background killed on Render free tier
# Problem: Old V3 route returned 200 immediately + background task.
# On Render free tier, background task is killed when request ends.
# Result: cron shows 200 OK in 1s every hour, but resolved stays 0, pending stays 50, no background logs.
# Fix: Do outcome work SYNCHRONOUSLY inside the request, limit 15 per run, log before return.
# No fake outcome. If original outcome function is not found, return honest status, write nothing.
# Usage: Append this file to app.py, commit, deploy ONCE, then do NOT deploy again for 7-14 days.
# Cron URL: https://signal-api-24q4.onrender.com/cron/outcome?key=YOUR_CRON_KEY&limit=15
# Cron schedule: every hour (already set in cron-job.org). Each run processes max 15 eligible entries.

import asyncio as _asyncio_v65
import inspect as _inspect_v65
import threading as _threading_v65
import time as _time_v65

try:
    _app_v65 = g.get("app") if isinstance(g, dict) else None
    if _app_v65 is None:
        _app_v65 = globals().get("app")
    if _app_v65 is None:
        _app_v65 = locals().get("app")
    print("[outcome-sync-v65] app found:", "yes" if _app_v65 is not None else "no")

    _lock_v65 = _threading_v65.Lock()
    _running_v65 = {"busy": False, "last_done": 0, "last_processed": 0}

    def _find_original_outcome_v65():
        # Try common names for original outcome worker in globals
        _candidates = []
        for _name, _obj in list(globals().items()):
            _lname = _name.lower()
            if "outcome" in _lname and callable(_obj):
                # Skip cron route itself and this patch helpers
                if "cron" in _lname or "v65" in _lname or "v3" in _lname:
                    continue
                _candidates.append((_name, _obj))
        # Prefer names that look like worker / fill / process
        for _pref in ["fill", "process", "run", "update", "worker", "do_"]:
            for _n, _o in _candidates:
                if _pref in _n.lower():
                    return _n, _o
        if _candidates:
            return _candidates[0]
        return None, None

    _orig_name_v65, _orig_fn_v65 = _find_original_outcome_v65()
    print(f"[outcome-sync-v65] original outcome fn: {_orig_name_v65 or 'NOT FOUND'}")

    # Remove old /cron/outcome routes so only sync version remains
    try:
        _routes_v65 = getattr(_app_v65, "routes", [])
        _before_v65 = len(_routes_v65)
        _routes_v65[:] = [r for r in list(_routes_v65) if getattr(r, "path", "") != "/cron/outcome"]
        _router_v65 = getattr(_app_v65, "router", None)
        if _router_v65 is not None:
            _rroutes_v65 = getattr(_router_v65, "routes", [])
            _rroutes_v65[:] = [r for r in list(_rroutes_v65) if getattr(r, "path", "") != "/cron/outcome"]
        print(f"[outcome-sync-v65] removed {_before_v65 - len(_routes_v65)} old /cron/outcome route(s)")
    except Exception as _e_rem_v65:
        print(f"[outcome-sync-v65] remove old route FAILED: {_e_rem_v65}")

    try:
        from fastapi import Request as _ReqV65
    except Exception:
        _ReqV65 = object

    @_app_v65.api_route("/cron/outcome", methods=["GET", "POST", "HEAD"])
    async def _cron_outcome_sync_v65(request: _ReqV65, limit: int = 15, key: str = "", cron_key: str = ""):
        # Limit guard: 1 to 20, default 15. Small batch keeps request within Render timeout.
        try:
            _qp_v65 = dict(getattr(request, "query_params", {}) or {})
            if "limit" in _qp_v65:
                limit = int(_qp_v65.get("limit") or limit)
        except Exception:
            pass
        limit = max(1, min(20, int(limit or 15)))

        # If a previous sync run is still inside this process, do not stack. Return honest status.
        with _lock_v65:
            if _running_v65["busy"]:
                print("[outcome-sync-v65] already_running, skip new run")
                return {"status": "already_running", "note": "previous sync outcome still running, try next cron run", "limit": limit}
            _running_v65["busy"] = True

        _start_v65 = _time_v65.time()
        _processed_v65 = 0
        _result_v65 = None
        _error_v65 = None
        try:
            if _orig_fn_v65 is None:
                # No original worker found. Do NOT fake outcome. Return honest status.
                print("[outcome-sync-v65] no original outcome worker found, wrote nothing")
                return {"status": "no_original_outcome", "note": "original outcome worker not found, no fake outcome written", "limit": limit, "processed": 0}
            # Call original worker SYNCHRONOUSLY and wait for it. This is the fix.
            # Old code used BackgroundTasks which Render kills. Here we await directly.
            try:
                if _inspect_v65.iscoroutinefunction(_orig_fn_v65):
                    _result_v65 = await _orig_fn_v65(limit=limit)
                else:
                    # Sync function: run in thread so we do not block event loop, but still wait.
                    _result_v65 = await _asyncio_v65.to_thread(_orig_fn_v65, limit)
            except TypeError:
                # Original fn may take no args or different signature. Try no-arg call.
                if _inspect_v65.iscoroutinefunction(_orig_fn_v65):
                    _result_v65 = await _orig_fn_v65()
                else:
                    _result_v65 = await _asyncio_v65.to_thread(_orig_fn_v65)
            # Extract processed count if result is dict
            if isinstance(_result_v65, dict):
                _processed_v65 = int(_result_v65.get("processed", 0) or _result_v65.get("updated", 0) or _result_v65.get("done", 0) or 0)
            _running_v65["last_processed"] = _processed_v65
            _running_v65["last_done"] = int(_time_v65.time())
            _dur_v65 = round(_time_v65.time() - _start_v65, 2)
            print(f"[outcome-sync-v65] done: processed={_processed_v65} limit={limit} duration={_dur_v65}s result={str(_result_v65)[:300]}")
            return {"status": "done", "processed": _processed_v65, "limit": limit, "duration_s": _dur_v65, "mode": "sync", "note": "synchronous outcome, no background, safe on Render free tier", "detail": _result_v65 if isinstance(_result_v65, dict) else str(_result_v65)[:300]}
        except Exception as _e_v65:
            _error_v65 = f"{type(_e_v65).__name__}: {str(_e_v65)[:400]}"
            print(f"[outcome-sync-v65] FAILED: {_error_v65}")
            return {"status": "failed", "error": _error_v65, "limit": limit, "processed": 0, "note": "sync outcome failed, no fake outcome written"}
        finally:
            with _lock_v65:
                _running_v65["busy"] = False

    print("[outcome-sync-v65] installed, sync mode, limit 15, no background")
except Exception as _e_top_v65:
    print(f"[outcome-sync-v65] FAILED to install (fail-open, app still runs): {_e_top_v65}")
