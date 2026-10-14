# part60.py (v2.45.0) - Đặt SAU part59, TRƯỚC part7. (Thay cho part52 cũ của mình, trùng tên part52 RPC của bạn.)
# 1) Chặn rò rỉ: _private, _cluster, _hg bị bỏ khỏi kết quả công khai (operator đặt HG_INTERNAL.set(True) để xem).
# 2) Feature log ĐÚNG khoá của /signal (part46 đọc result["market"] không tồn tại nên liq/age/pc luôn = 0).
# 3) Signal shadow known_dumper_present / cluster_high_risk, lưu cùng feature, debate, adjusted_risk
#    vào hgsig:{mint}:{ts} (cùng khoá với sout:{mint}:{ts}) để đo precision/recall khi có nhãn.
# 4) Xếp hạng /signals chỉ theo risk_score (bỏ _private chưa huấn luyện và "conviction" vốn chỉ là verdict cũ của API).

VERSION = "2.45.0"
app.version = VERSION
app.openapi_schema = None

import contextvars
import json
import math
import os
import time

HG_INTERNAL = contextvars.ContextVar("hg_internal", default=False)
HG60_PRIVATE_KEYS = ("_private", "_cluster", "_hg")
HG60_SIMPLE_RANK = os.getenv("HG_SIMPLE_RANK", "true").lower() in ("1", "true", "yes")

HG60_MIN_N = 5            # số action mạnh (dump + accumulate) tối thiểu để chấm điểm 1 ví
HG60_DUMPER_RATE = 0.70
HG60_CL_MIN = 5           # số token đã chấm tối thiểu để tin tỉ lệ xấu của cluster
HG60_CL_RATE = 0.80
HG60_CACHE_S = 600
HG60_TTL = 90 * 86400
HG60_STATS = {"calls": 0, "computed": 0, "cache_hit": 0, "dumper": 0, "cluster": 0, "redis_fail": 0}
_HG60_CACHE = {}
_HG60_SEEN = set()


def _hg60_num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def hg_features(r):
    """Feature từ ĐÚNG khoá của /signal. Thiếu dữ liệu thì bỏ khoá (không điền số giả); partial/sec_ok cho biết độ đầy đủ."""
    pc = r.get("price_change_pct") or {}
    hq = r.get("holder_quality") or {}
    sec = r.get("security") or {}
    age = _hg60_num(r.get("pair_age_minutes"))
    raw = {"risk": r.get("risk_score"), "liq": r.get("liquidity_usd"), "fdv": r.get("fdv_usd"),
           "vol1h": r.get("volume_1h"), "age_h": None if age is None else age / 60,
           "pc5": pc.get("5m"), "pc1": pc.get("1h"), "pc6": pc.get("6h"), "pc24": pc.get("24h"),
           "bp5": r.get("buy_pressure_5m"), "spike5": r.get("volume_spike_ratio_5m"),
           "turn1": r.get("turnover_1h"), "hq": hq.get("score"), "hq_con": hq.get("concentration"),
           "hq_stab": hq.get("stability"), "hq_abs": hq.get("absorption"),
           "lp": sec.get("lp_locked_pct"), "rc": sec.get("rugcheck_score"), "top10": sec.get("top10_pct"),
           "cl_n": (r.get("_cluster") or {}).get("size")}
    x = {k: round(v, 4) for k, v in ((k, _hg60_num(v)) for k, v in raw.items()) if v is not None}
    x["partial"] = int(bool(r.get("partial")))
    x["sec_ok"] = int(bool(sec.get("available")))
    return x


def hg60_compute(wallets, fp, res):
    """Thuần tính toán. res = pipeline: HGETALL wc2:{w} từng ví, rồi (HGETALL cl2:{fp}, SCARD clm2:{fp})."""
    dumpers, scored = [], 0
    for w, r in zip(wallets, res):
        h = _hgx_hash(r)
        d, a = int(h.get("dump", 0)), int(h.get("accumulate", 0))
        n = d + a
        if n >= HG60_MIN_N:
            scored += 1
            if d / n >= HG60_DUMPER_RATE:
                dumpers.append({"w": w, "dump_rate": round(d / n, 3), "n": n})
    cl = None
    if fp and len(res) >= len(wallets) + 2:
        ch = _hgx_hash(res[len(wallets)])
        if ch:
            c = _hgx_cluster(fp, int(res[len(wallets) + 1] or 0), ch.get("first_seen"),
                             ch.get("n_judged"), ch.get("n_bad"))
            cl = {"id": c["id"], "size": c["size"], "n_judged": c["n_judged"], "bad_rate": c["bad_rate"]}
    risky = bool(cl and cl["n_judged"] >= HG60_CL_MIN and (cl["bad_rate"] or 0) >= HG60_CL_RATE)
    return {"v": 1, "known_dumper_present": bool(dumpers), "dumpers": dumpers[:3], "n_scored": scored,
            "cluster_high_risk": risky, "cluster": cl}


async def hg_signals(client, mint, result):
    """Signal nội bộ, hoặc None nếu thiếu dữ liệu / Redis lỗi (không cache kết quả lỗi)."""
    if not PRED_ENABLED or not client:
        return None
    HG60_STATS["calls"] += 1
    now = time.time()
    hit = _HG60_CACHE.get(mint)
    if hit and now - hit[0] < HG60_CACHE_S:
        HG60_STATS["cache_hit"] += 1
        return hit[1]
    tops = hgx_pairs((result.get("holder_quality") or {}).get("top_owners"))[:5]
    wallets = [w for w, _ in tops]
    fp = (result.get("_cluster") or {}).get("fingerprint") or ""
    if not wallets and not fp:
        return None
    cmds = [["HGETALL", f"wc2:{w}"] for w in wallets]
    if fp:
        cmds += [["HGETALL", f"cl2:{fp}"], ["SCARD", f"clm2:{fp}"]]
    res = await redis_pipe(client, cmds)
    if not res:
        HG60_STATS["redis_fail"] += 1
        return None
    sig = hg60_compute(wallets, fp, res)
    HG60_STATS["computed"] += 1
    HG60_STATS["dumper"] += int(sig["known_dumper_present"])
    HG60_STATS["cluster"] += int(sig["cluster_high_risk"])
    if len(_HG60_CACHE) > 2000:
        _HG60_CACHE.clear()
    _HG60_CACHE[mint] = (now, sig)
    return sig


def hg60_record(result, sig):
    dec = result.get("decision") or {}
    deb = result.get("debate") or {}
    conv = (result.get("community") or {}).get("conviction") or {}
    return {"v": 2, "t": result.get("_snap_ts"), "ver": dec.get("verdict") or result.get("verdict"),
            "r": result.get("risk_score"), "f": sorted(result.get("flags") or []), "x": hg_features(result),
            "hg": sig, "deb": deb.get("meta_verdict"), "agr": deb.get("agreement"),
            "adj": (result.get("_private") or {}).get("adjusted_risk"), "cv": conv.get("dominant")}


async def _hg60_persist(client, mint, ts, rec):
    k = (mint, ts)
    if not ts or k in _HG60_SEEN:
        return
    if len(_HG60_SEEN) > 5000:
        _HG60_SEEN.clear()
    _HG60_SEEN.add(k)
    await redis_pipe(client, [["SET", f"hgsig:{mint}:{ts}", json.dumps(rec, separators=(",", ":"), default=str),
                               "NX", "EX", HG60_TTL]])


# ---------- ghi đè part53: xếp hạng chỉ theo risk_score ----------
_rank_score_prev = globals().get("_rank_score")


def _rank_score(r):
    if not HG60_SIMPLE_RANK and _rank_score_prev:
        return _rank_score_prev(r)
    return float(r.get("risk_score") or 50)


# ---------- gắn vào pipeline (ngoài cùng) ----------
_build_signal_hg60 = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_signal_hg60(client, mint, security, prefetched)
    try:
        sig = await hg_signals(client, mint, result)
        if sig is not None:
            result["_hg"] = sig
        await _hg60_persist(client, mint, result.get("_snap_ts"), hg60_record(result, sig))
    except Exception:
        pass
    if isinstance(result, dict) and not HG_INTERNAL.get():
        result = {k: v for k, v in result.items() if k not in HG60_PRIVATE_KEYS}   # bản sao: không đụng cache
    return result, status
