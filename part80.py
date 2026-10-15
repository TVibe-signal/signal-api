# ---------- v2.59: Snapshot diff (/diff) ----------
VERSION = "2.59.0"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict, List, Optional

from fastapi import Query

_DIFF_SKIP = {"ts", "mint"}


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _ts_from_member(m: Any) -> Optional[int]:
    if isinstance(m, bytes):
        m = m.decode("utf-8", "ignore")
    tail = str(m).rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


async def _list_snapshot_ts(client, mint: str, limit: int = 300) -> List[int]:
    """Danh sách ts của snapshot, mới nhất trước."""
    zkey = SNAPSHOTS_ZSET.format(mint)
    res = await redis_pipe(client, [["ZREVRANGE", zkey, 0, limit - 1]])
    members = (res or [[]])[0] or []
    out: List[int] = []
    for m in members:
        t = _ts_from_member(m)
        if t is not None and t not in out:
            out.append(t)
    if not out:
        # dự phòng: index zset rỗng/khác định dạng -> quét trực tiếp key snap:{mint}:*
        try:
            cursor = "0"
            for _ in range(8):
                res = await redis_pipe(client, [["SCAN", cursor, "MATCH", f"snap:{mint}:*", "COUNT", 500]])
                part = (res or [None])[0]
                if not part or len(part) < 2:
                    break
                cursor, keys = str(part[0]), (part[1] or [])
                for k in keys:
                    t = _ts_from_member(k)
                    if t is not None and t not in out:
                        out.append(t)
                if cursor == "0":
                    break
            out.sort(reverse=True)
        except Exception:
            pass
    return out


def _nearest(ts_list: List[int], target: int) -> int:
    return min(ts_list, key=lambda t: abs(t - target))


def _owner_map(lst: Any) -> Dict[str, Any]:
    m: Dict[str, Any] = {}
    for it in lst or []:
        if isinstance(it, dict):
            k = it.get("owner") or it.get("address") or it.get("wallet")
            p = it.get("pct", it.get("percent", it.get("share")))
            if k:
                m[str(k)] = p
    return m


def _diff_owners(a: Any, b: Any) -> Optional[Dict[str, Any]]:
    ma, mb = _owner_map(a), _owner_map(b)
    if not ma and not mb:
        return None
    entered = [{"owner": k, "pct": mb[k]} for k in mb if k not in ma]
    left = [{"owner": k, "pct": ma[k]} for k in ma if k not in mb]
    changed = []
    for k in mb:
        if k in ma and _is_num(ma[k]) and _is_num(mb[k]) and abs(mb[k] - ma[k]) >= 0.5:
            changed.append({"owner": k, "from": ma[k], "to": mb[k], "delta": round(mb[k] - ma[k], 2)})
    return {"entered_top": entered, "left_top": left, "pct_changed": changed}


def _skip_key(k: Any) -> bool:
    s = str(k)
    return k in _DIFF_SKIP or s.startswith("_") or "private" in s.lower()


def _diff_snaps(a: dict, b: dict) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}
    for k in sorted(set(a) | set(b), key=str):
        if _skip_key(k):
            continue
        va, vb = a.get(k), b.get(k)
        if va == vb:
            continue
        if isinstance(va, list) and isinstance(vb, list) and (
            (va and isinstance(va[0], dict)) or (vb and isinstance(vb[0], dict))
        ):
            d = _diff_owners(va, vb)
            if d:
                changes[k] = d
                continue
        if _is_num(va) and _is_num(vb):
            e: Dict[str, Any] = {"from": va, "to": vb, "delta": round(vb - va, 4)}
            if va:
                e["pct"] = round((vb - va) / abs(va) * 100, 1)
            changes[k] = e
        elif isinstance(va, (dict, list)) or isinstance(vb, (dict, list)):
            changes[k] = {"changed": True}
        else:
            changes[k] = {"from": va, "to": vb}
    return changes


def _diff_notes(ch: Dict[str, Any]) -> List[Dict[str, str]]:
    """Suy luận (inference) từ các thay đổi đo được. Chỉ là dấu hiệu, không phải kết luận."""
    notes: List[Dict[str, str]] = []

    def add(signal: str, basis: str) -> None:
        notes.append({"kind": "inference", "signal": signal, "basis": basis})

    rs = ch.get("risk_score")
    if isinstance(rs, dict) and rs.get("delta") is not None:
        if rs["delta"] >= 10:
            add("risk_rising", f"risk_score rose by {rs['delta']} points")
        elif rs["delta"] <= -10:
            add("risk_falling", f"risk_score fell by {abs(rs['delta'])} points")
    v = ch.get("verdict")
    if isinstance(v, dict) and "from" in v:
        add("verdict_changed", f"verdict changed from {v['from']} to {v['to']}")
    lp = ch.get("lp_locked_pct")
    if isinstance(lp, dict) and lp.get("delta") is not None and lp["delta"] <= -5:
        add("lp_lock_dropping", f"lp_locked_pct fell by {abs(lp['delta'])} points")
    to = ch.get("top_owners")
    if isinstance(to, dict):
        if to.get("entered_top"):
            add("new_top_holders", f"{len(to['entered_top'])} new wallet(s) entered the top holders")
        if any((c.get("delta") or 0) <= -2 for c in to.get("pct_changed", [])):
            add("top_holders_reducing", "at least one top holder reduced its share by 2 points or more")
    return notes


def _brief(s: dict, mint: str) -> Dict[str, Any]:
    return {
        "evidence_id": f"snap:{mint}:{s.get('ts')}",
        "ts": s.get("ts"),
        "verdict": s.get("verdict"),
        "risk_score": s.get("risk_score"),
    }


async def compute_diff(client, mint: str, from_ts: Optional[int] = None, to_ts: Optional[int] = None,
                       since_h: Optional[float] = None) -> Dict[str, Any]:
    """Dùng chung cho route /diff và tool MCP get_diff. Ném HTTPException khi lỗi."""
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    if not PRED_ENABLED:
        raise HTTPException(status_code=503, detail="Snapshot store is not enabled")

    ts_list = await _list_snapshot_ts(client, mint)
    if len(ts_list) < 2:
        dbg: Dict[str, Any] = {}
        try:
            zkey = SNAPSHOTS_ZSET.format(mint)
            r2 = await redis_pipe(client, [["ZCARD", zkey], ["ZREVRANGE", zkey, 0, 2]])
            dbg = {
                "index_key": zkey,
                "index_size": (r2 or [None])[0],
                "index_sample": [repr(m)[:80] for m in ((r2 or [None, []])[1] or [])],
            }
        except Exception as e:
            dbg = {"index_error": repr(e)[:120]}
        raise HTTPException(status_code=404, detail={
            "error": "Fewer than two snapshots stored for this token",
            "available_snapshots": len(ts_list),
            "hint": "Query /signal for this mint again later; each signal pull stores a snapshot.",
            "debug": dbg,
        })

    new_ts = _nearest(ts_list, to_ts) if to_ts is not None else ts_list[0]
    if from_ts is not None:
        old_ts = _nearest(ts_list, from_ts)
    elif since_h is not None:
        old_ts = _nearest([t for t in ts_list if t != new_ts] or ts_list, new_ts - int(since_h * 3600))
    else:
        old_ts = next((t for t in ts_list if t < new_ts), ts_list[-1])
    if old_ts == new_ts:
        raise HTTPException(status_code=422, detail="Need two different snapshots; widen from/to or since_h")
    if old_ts > new_ts:
        old_ts, new_ts = new_ts, old_ts

    a = await _load_snapshot(client, mint, old_ts)
    b = await _load_snapshot(client, mint, new_ts)
    if not a or not b:
        raise HTTPException(status_code=404, detail="A snapshot listed in the index could not be loaded (expired or missing)")

    changes = _diff_snaps(a, b)
    gap = new_ts - old_ts
    unknowns = [{
        "id": "between_snapshots",
        "detail": "Only two points are compared. Absence of a change here does not mean nothing changed in between.",
    }]
    if gap > 24 * 3600:
        unknowns.append({"id": "wide_gap", "detail": f"The snapshots are {gap / 3600:.1f} hours apart."})

    out = {
        "mint": mint,
        "gap_s": gap,
        "gap_h": round(gap / 3600, 2),
        "available_snapshots": len(ts_list),
        "from": _brief(a, mint),
        "to": _brief(b, mint),
        "changes": changes,
        "changes_kind": "observation",
        "notes": _diff_notes(changes),
        "unknowns": unknowns,
        "generated_at": int(time.time()),
    }
    walker = globals().get("_walk_text")
    if callable(walker):
        try:
            walker(out, {})
        except Exception:
            pass
    return out


@app.get("/diff", tags=["signals"],
         summary="What changed for a token between two stored snapshots",
         description="Compares two stored snapshots. `changes` are measured field differences (observations). "
                     "`notes` are inferences drawn from them and can be wrong. Defaults to the two latest snapshots; "
                     "use since_h to compare the latest with a snapshot about N hours earlier, or from/to as unix timestamps.")
async def diff_route(
    request: Request,
    mint: str = Query(..., max_length=64, description="Solana token mint"),
    from_ts: Optional[int] = Query(None, alias="from", ge=0, description="Unix ts of the older snapshot (nearest match)"),
    to_ts: Optional[int] = Query(None, alias="to", ge=0, description="Unix ts of the newer snapshot (nearest match)"),
    since_h: Optional[float] = Query(None, gt=0, le=2160, description="Compare latest with the snapshot ~N hours earlier"),
):
    wait = rate_limited(client_ip(request), cost=1)
    if wait:
        raise too_many(wait)
    out = await compute_diff(request.app.state.client, mint, from_ts, to_ts, since_h)
    return JSONResponse(content=out, headers={"Cache-Control": "public, max-age=10"})


print(f"[part80] v{VERSION} snapshot diff loaded → GET /diff?mint=&since_h=")
