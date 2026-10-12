# ---------- part42: v2.29.0 - judging with GeckoTerminal fallback + liquidity at 1h/6h marks ----------
VERSION = "2.29.0"
app.version = VERSION
app.openapi_schema = None

JUDGE_GT_MAX = max(3, int(os.getenv("JUDGE_GT_MAX", "12")))
JUDGE_RETRY_S = 900


async def _judge_pairs(client, mints):
    """Dex first (one call). If it fails, GeckoTerminal one token at a time.
    Returns (pairs, via, covered) or None. covered is None when Dex answered for everyone."""
    t0 = time.time()
    try:
        resp = await client.get(DEX_URL.format(mint=",".join(mints)))
        resp.raise_for_status()
        pairs = resp.json().get("pairs") or []
        src_log("dexscreener", True, t0)
        return pairs, "dex", None
    except (httpx.HTTPError, ValueError):
        src_log("dexscreener", False, t0)
    order = ([SOL_MINT] if SOL_MINT in mints else []) + [m for m in mints if m != SOL_MINT]
    pairs, covered = [], set()
    for m in order[:JUDGE_GT_MAX]:
        try:
            got = await _gt_fetch(client, m)
        except Exception:
            got = None
        if got:
            pairs += list(got)
            covered.add(m)
        await asyncio.sleep(0.4)
    if not covered:
        return None
    return pairs, "gecko", covered


def _judge_one(d, pair):
    p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
    if pair is None:
        return -100.0, 0.0
    p1 = float(pair.get("priceUsd") or 0)
    l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
    ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
    liq_ratio = l1 / l0 if l0 > 0 else 1.0
    return ret, liq_ratio


async def _load_due(client, zset):
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", zset, "-inf", now, "LIMIT", 0, RESOLVE_BATCH]])
    ids = (got or [[]])[0] or []
    if not ids:
        return now, [], {}, []
    hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
    if hashes is None:
        return now, [], {}, []
    cmds, preds = [], {}
    for pid, h in zip(ids, hashes):
        d = to_dict(h)
        if d.get("mint"):
            preds[pid] = d
        else:
            cmds.append(["ZREM", zset, pid])
    return now, ids, preds, cmds


async def _resolve_due_24h(client: httpx.AsyncClient) -> int:
    now, ids, preds, cmds = await _load_due(client, "due")
    if not ids:
        return 0
    best: Dict[str, Optional[dict]] = {}
    sol1: Optional[float] = None
    via, covered = "dex", None
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        ask = mints if SOL_MINT in mints else mints + [SOL_MINT]
        res = await _judge_pairs(client, ask)
        if res is None:
            if cmds:
                await redis_pipe(client, cmds)
            return 0
        pairs, via, covered = res
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
        sp = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == SOL_MINT], SOL_MINT)
        try:
            sol1 = float(sp.get("priceUsd")) if sp else None
        except (TypeError, ValueError):
            sol1 = None
    recent = []
    judged = 0
    for pid, d in preds.items():
        age = now - int(d.get("ts") or 0)
        if d["mint"] in MAJOR_ASSETS or age > PRED_HORIZON_S * 3:
            cmds += [["ZREM", "due", pid], ["DEL", f"pred:{pid}"]]
            continue
        if covered is not None and d["mint"] not in covered:
            cmds.append(["ZADD", "due", now + JUDGE_RETRY_S, pid])
            continue
        cmds += [["ZREM", "due", pid], ["DEL", f"pred:{pid}"]]
        judged += 1
        ret, liq_ratio = _judge_one(d, best.get(d["mint"]))
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        sol0 = float(d.get("sol") or 0)
        sol_ret = (sol1 / sol0 - 1) * 100 if (sol1 and sol0 > 0) else None
        xret = ret - sol_ret if sol_ret is not None else None
        v, c = d.get("verdict", "?"), d.get("conf", "?")
        bucket = min(9, int(float(d.get("score") or 0)) // 10)
        day = time.strftime("%Y%m%d", time.gmtime(int(d.get("ts") or 0)))
        flags_t = [f for f in (d.get("flags") or "").split(",") if f in RISK_WEIGHTS]
        src = d.get("src") or "untagged"
        groups = ["all", f"v:{v}:{c}", f"rb:{bucket}", f"d:{day}", f"src:{src}", f"srcv:{src}:{v}"]
        groups += [f"f:{f}" for f in flags_t] + [f"fd:{f}:{day}" for f in flags_t]
        base_pred = "avoid" if BASELINE_FLAGS & set((d.get("flags") or "").split(",")) else "ok"
        groups += [f"vd:{v}:{c}:{day}", f"bl:{base_pred}", f"bd:{base_pred}:{day}"]
        groups += [f"sh:{rn}:{sv}" for rn, sv in _parse_shadow(d.get("shadow"))]
        for g in groups:
            cmds.append(["HINCRBY", "st", f"{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "st", f"{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "st", f"v:{v}:{c}:ret", round(ret, 2)])
        if xret is not None:
            cmds += [["HINCRBYFLOAT", "st", f"v:{v}:{c}:xret", round(xret, 2)], ["HINCRBY", "st", f"v:{v}:{c}:xn", 1]]
        recent.append(json.dumps({"token": d.get("token"), "mint": d["mint"], "verdict": v,
                                  "risk_score": float(d.get("score") or 0), "return_pct": round(ret, 1),
                                  "sol_return_pct": round(sol_ret, 1) if sol_ret is not None else None,
                                  "excess_return_pct": round(xret, 1) if xret is not None else None,
                                  "bad_outcome": bad, "age_h": round(age / 3600, 1), "src": src}))
        d["via"] = via
        cmds += _dataset_cmds(d, v, src, ret, liq_ratio, bad)
    for item in recent:
        cmds.append(["LPUSH", "recent", item])
    if recent:
        cmds.append(["LTRIM", "recent", 0, 49])
    if via == "gecko" and judged:
        cmds.append(["HINCRBY", "jmeta", "gecko_judged", judged])
        print(f"[part42] judged {judged} via GeckoTerminal (Dex down)")
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)


async def _resolve_early_one(client: httpx.AsyncClient, hours: int, zset: str) -> int:
    now, ids, preds, cmds = await _load_due(client, zset)
    if not ids:
        return 0
    best: Dict[str, Optional[dict]] = {}
    covered = None
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        res = await _judge_pairs(client, mints)
        if res is None:
            if cmds:
                await redis_pipe(client, cmds)
            return 0
        pairs, _via, covered = res
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
    pre = f"h{hours}"
    for pid, d in preds.items():
        age = now - int(d.get("ts") or 0)
        if d["mint"] in MAJOR_ASSETS or age > hours * 3600 * 3:
            cmds.append(["ZREM", zset, pid])
            continue
        if covered is not None and d["mint"] not in covered:
            cmds.append(["ZADD", zset, now + JUDGE_RETRY_S, pid])
            continue
        cmds.append(["ZREM", zset, pid])
        ret, liq_ratio = _judge_one(d, best.get(d["mint"]))
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        v = d.get("verdict", "?")
        groups = ["all", f"v:{v}", f"src:{d.get('src') or 'untagged'}"]
        groups += [f"sh:{rn}:{sv}" for rn, sv in _parse_shadow(d.get("shadow"))]
        for g in groups:
            cmds.append(["HINCRBY", "sth", f"{pre}:{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "sth", f"{pre}:{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "sth", f"{pre}:v:{v}:ret", round(ret, 2)])
        if DATASET_ENABLED:
            cmds.append(["HSET", f"pred:{pid}", f"ret_h{hours}", str(round(ret, 2)),
                         f"lr_h{hours}", str(round(liq_ratio, 3))])
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)


_dataset_cmds_prev = _dataset_cmds


def _dataset_cmds(d, v, src, ret, liq_ratio, bad):
    cmds = _dataset_cmds_prev(d, v, src, ret, liq_ratio, bad)
    try:
        if cmds and cmds[0][0] == "LPUSH":
            row = json.loads(cmds[0][2])
            for h, _ in _EARLY:
                row[f"liq_ratio_h{h}"] = _num(d.get(f"lr_h{h}"))
            row["judged_via"] = d.get("via") or "dex"
            cmds[0][2] = json.dumps(row, separators=(",", ":"))
    except Exception:
        pass
    return cmds


print(f"[part42] v{VERSION} judging with Gecko fallback, liquidity kept at the early marks")