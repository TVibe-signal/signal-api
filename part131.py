# part131.py — Phase D walk-forward checklist for score_35 (read-only, never promotes)
VERSION = "3.0.3"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict, List

_CACHE: Dict[str, Any] = {"ts": 0.0, "body": None}
_TTL = 120.0


async def _fetch_json(path: str) -> dict:
    try:
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://internal",
            timeout=35.0,
        ) as c:
            r = await c.get(path)
            if r.status_code == 200:
                j = r.json()
                return j if isinstance(j, dict) else {}
    except Exception as e:
        return {"_error": str(e)[:160]}
    return {"_error": "non-200"}


def _checklist(candidates: dict, stats: dict) -> dict:
    rules = candidates.get("rules") or {}
    s35 = rules.get("score_35") if isinstance(rules, dict) else None
    strong = list(candidates.get("strong_candidates") or [])
    judged = candidates.get("judged")
    scoring = stats.get("scoring") if isinstance(stats.get("scoring"), dict) else {}

    items: List[dict] = []

    def add(id_, ok, detail, required=True):
        items.append({"id": id_, "ok": bool(ok), "required": required, "detail": detail})

    add(
        "strong_candidate",
        "score_35" in strong and isinstance(s35, dict) and s35.get("pass") is True,
        "score_35 in strong_candidates and pass=true",
    )
    add("volume", (judged or 0) >= 800, "judged=%s (need >=800)" % judged)

    checks = (s35 or {}).get("checks") if isinstance(s35, dict) else {}
    checks = checks if isinstance(checks, dict) else {}
    add(
        "precision_lift",
        checks.get("precision_lower_bound_10pts_over_base") is True,
        "precision_pct=%s" % ((s35 or {}).get("precision_pct") if isinstance(s35, dict) else None),
    )
    add(
        "recall_lift",
        checks.get("recall_at_least_10pts_over_live") is True,
        "recall_pct=%s" % ((s35 or {}).get("recall_pct") if isinstance(s35, dict) else None),
    )
    add(
        "ok_group_safe",
        checks.get("ok_group_not_worse_than_live_plus_2") is True,
        "ok_bad_rate_pct=%s n=%s"
        % (
            (s35 or {}).get("ok_bad_rate_pct") if isinstance(s35, dict) else None,
            (s35 or {}).get("ok_n") if isinstance(s35, dict) else None,
        ),
    )

    scoring_mode = scoring.get("mode") or scoring.get("status") or scoring.get("state")
    if scoring_mode is not None:
        add(
            "scoring_not_static",
            str(scoring_mode).lower() not in ("static", "unavailable", "down"),
            "scoring=%s" % scoring_mode,
            required=False,
        )
    else:
        add("scoring_not_static", True, "scoring field not exposed — skip", required=False)

    add(
        "time_split_walk_forward",
        False,
        "Per-day / half-sample lift for score_35 not published — do not treat as done",
    )
    add(
        "shadow_only_period",
        True,
        "Live verdict unchanged until explicit versioned promote",
    )
    add(
        "public_changelog_ready",
        False,
        "Operator must write changelog + bump version before live rule change",
    )

    required = [x for x in items if x.get("required")]
    return {
        "rule": "score_35",
        "strong": "score_35" in strong,
        "metrics": {
            "judged": judged,
            "precision_pct": (s35 or {}).get("precision_pct") if isinstance(s35, dict) else None,
            "recall_pct": (s35 or {}).get("recall_pct") if isinstance(s35, dict) else None,
            "avoid_n": (s35 or {}).get("avoid_n") if isinstance(s35, dict) else None,
            "ok_n": (s35 or {}).get("ok_n") if isinstance(s35, dict) else None,
            "ok_bad_rate_pct": (s35 or {}).get("ok_bad_rate_pct") if isinstance(s35, dict) else None,
        },
        "items": items,
        "required_pass_count": sum(1 for x in required if x["ok"]),
        "required_total": len(required),
        "promote_allowed": False,
        "meaning": (
            "Walk-forward checklist blocks silent promote. "
            "score_35 may look strong on full sample; without time-split + changelog, live rules stay as-is."
        ),
        "next_operator_steps": [
            "Keep cron /ping (disable save response body), /si/breath, /seed healthy",
            "Re-check GET /stats/rule-candidates weekly",
            "When per-day shadow metrics exist, re-run this endpoint",
            "Only then: public changelog + version bump + explicit promote part",
        ],
    }


@app.get("/filter/walk-forward", tags=["agents"], include_in_schema=False)
@app.get("/stats/walk-forward", tags=["agents"], include_in_schema=False)
async def walk_forward_score35():
    now = time.time()
    if _CACHE["body"] and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["body"]
    cand = await _fetch_json("/stats/rule-candidates")
    stats = await _fetch_json("/stats")
    body = {
        "version": VERSION,
        "live_rules_unchanged": True,
        "checklist": _checklist(
            cand if isinstance(cand, dict) else {},
            stats if isinstance(stats, dict) else {},
        ),
        "errors": {
            "rule_candidates": cand.get("_error") if isinstance(cand, dict) else None,
            "stats": stats.get("_error") if isinstance(stats, dict) else None,
        },
        "note": "Read-only. Never changes decision.verdict or filter live policy.",
    }
    _CACHE["ts"] = now
    _CACHE["body"] = body
    return body


print("[part131] v%s GET /filter/walk-forward (score_35 checklist, no promote)" % VERSION)