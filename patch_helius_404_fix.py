"""
TVibe FIX 404 for v48 EN - Reorder routes so /helius_status works.
Root cause: core_final registers /{mint} and /{path:path} catch-all.
Any route added AFTER them is unreachable -> plain "Not Found".
[full48] is applied AFTER rescue-v44, so its routes land after catch-all.
This fix moves all fixed routes before catch-all, like rescue-v44 does.

Usage in app.py - AFTER the v48 lines:
    import patch_tvibe_full_v48_en as _full
    _full.apply(g)

    import patch_helius_404_fix as _fix404
    _fix404.apply(g)

    app = g.get("app")
"""

def apply(g: dict) -> None:
    try:
        app = g.get("app")
        if app is None:
            print("[fix404-helius] no app, skip")
            return

        router = getattr(app, "router", None)
        routes = list(getattr(router, "routes", []) or getattr(app, "routes", []) or [])
        if not routes:
            print("[fix404-helius] no routes")
            return

        def is_catch(r):
            raw = getattr(r, "path", "") or ""
            if raw in ("/{mint}", "/{path:path}", "/{path}"):
                return True
            if "path:path" in raw:
                return True
            if raw == "/{mint}":
                return True
            return False

        def is_fixed_helius(r):
            raw = getattr(r, "path", "") or ""
            return raw in (
                "/helius_status", "/proof_helius", "/proof_helius_json",
                "/unified", "/unified_json", "/compare_old_new",
                "/proof9", "/proof9_json", "/kernel9_status",
                "/pro", "/pro_json", "/pro_status", "/omni", "/omni_pro",
                "/store_check", "/ping", "/health", "/stats",
            )

        fixed = []
        catch = []
        others = []
        for r in routes:
            if is_catch(r):
                catch.append(r)
            elif is_fixed_helius(r):
                fixed.append(r)
            else:
                others.append(r)

        # Priority: fixed helius/pro first, then other fixed, then catch-all last
        # Keep original order inside each group to avoid breaking existing logic.
        new_order = fixed + others + catch

        # Apply to both router and app if they share the list
        try:
            if router is not None:
                router.routes = new_order
            app.routes = new_order
        except Exception:
            # Fallback: clear and re-add
            try:
                router.routes.clear()
                router.routes.extend(new_order)
            except Exception as e:
                print(f"[fix404-helius] reorder failed: {e}")
                return

        print(f"[fix404-helius] reordered routes={len(new_order)} fixed={len(fixed)} catch={len(catch)} - /helius_status now before /{{mint}}")
        # Verify
        paths = [getattr(r, "path", "") for r in new_order]
        if "/helius_status" in paths:
            idx_helius = paths.index("/helius_status")
            idx_catch = min([paths.index(p) for p in paths if p in ("/{mint}", "/{path:path}")], default=9999)
            print(f"[fix404-helius] check: /helius_status at {idx_helius}, catch-all at {idx_catch}, OK={idx_helius < idx_catch}")
        else:
            print("[fix404-helius] WARNING: /helius_status still not in routes - check if v48 applied before this fix")

    except Exception as e:
        print(f"[fix404-helius] FAILED: {e}")
