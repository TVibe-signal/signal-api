# ---------- part33: v2.20.0 - /explain: why this verdict, in plain words (English or Vietnamese) ----------
# Loads before part7. Built on the live engine: the English reasons come from REASONS, the points from ACTIVE_WEIGHTS (so they follow
# the auto-tuning), which flags force the verdict is read from the decision object the engine already produced, and the score
# rule is the engine's own: score = min(100, sum of the points of the flags that are scored). Nothing here changes /signal.
VERSION = "2.20.0"
app.version = VERSION
app.openapi_schema = None

_AVOID_AT, _CAUTION_AT = 50, 25   # the same lines add_verdict uses
_POSITIVE_FLAGS = {"holders_stable", "whale_accumulating", "dip_absorbed"}
_ROLE_ORDER = {"blocker": 0, "caution": 1, "scores": 2, "info": 3, "positive": 4}
_EN_EXTRA = {
    "very_new_pair": "Pair is very young, so there is little history",
    "new_pair": "Pair is young",
    "high_turnover": "Trading volume is high compared with liquidity",
    "heavy_selling": "Recent trades lean heavily to selling",
    "extreme_volume_spike": "Volume jumped abnormally in the last minutes",
    "transfer_fee_set": "The token has a transfer fee configured (a small one)",
}
_VI = {
    "mint_authority_active": "Quyền đúc (mint) còn hiệu lực: có thể tạo thêm token, làm loãng giá trị",
    "freeze_authority_active": "Quyền đóng băng còn hiệu lực: có thể khóa ví của người nắm giữ",
    "risky_token_extension": "Tiện ích Token-2022 có thể hạn chế hoặc đánh thuế khi chuyển token",
    "lp_not_locked": "Thanh khoản chưa bị khóa hay đốt: team có thể rút ra",
    "dump_risk": "Giá đang giảm rất nhanh",
    "extreme_holder_concentration": "10 ví lớn nhất nắm từ 80% nguồn cung trở lên",
    "very_low_liquidity": "Thanh khoản dưới 20 nghìn USD",
    "low_liquidity": "Thanh khoản dưới 50 nghìn USD",
    "high_holder_concentration": "10 ví lớn nhất nắm từ 50% nguồn cung trở lên",
    "dominant_holder": "Một ví nắm từ 20% nguồn cung trở lên",
    "lp_partially_locked": "Thanh khoản chỉ được khóa hoặc đốt một phần",
    "brand_new_pair": "Cặp giao dịch mới tạo chưa tới 1 giờ",
    "very_new_pair": "Cặp giao dịch còn rất mới nên ít lịch sử",
    "new_pair": "Cặp giao dịch còn mới",
    "extreme_turnover": "Khối lượng giao dịch cực lớn so với thanh khoản (nguy cơ rửa lệnh)",
    "high_turnover": "Khối lượng giao dịch cao so với thanh khoản",
    "heavy_selling": "Các giao dịch gần đây nghiêng mạnh về phía bán",
    "extreme_volume_spike": "Khối lượng tăng đột biến bất thường trong vài phút gần nhất",
    "lp_unverified": "Không xác minh được việc khóa hoặc đốt thanh khoản (pool PumpSwap)",
    "permanent_delegate_active": "Một địa chỉ ủy quyền vĩnh viễn có thể chuyển hoặc đốt token của bất kỳ ai",
    "transfer_fee_extreme": "Phí chuyển token từ 25% trở lên ở mỗi lần chuyển (như thuế khi bán)",
    "default_account_frozen": "Tài khoản token mới bị đóng băng mặc định: người nắm giữ không chuyển được cho đến khi bên phát hành mở",
    "transfer_fee_high": "Phí chuyển token từ 5% trở lên ở mỗi lần chuyển",
    "transfer_hook_active": "Một chương trình hook chạy ở mỗi lần chuyển và có thể chặn giao dịch",
    "transfer_fee_set": "Token có cấu hình phí chuyển (mức nhỏ)",
    "no_sell_route": "Không tìm thấy đường bán trên Jupiter khi kiểm tra cách đây vài phút",
    "high_exit_cost": "Bán ra sẽ mất một phần lớn giá trị vì phí và trượt giá (theo kiểm tra gần đây)",
    "holders_churning": "Các ví lớn nhất thay đổi liên tục",
    "whale_dumping": "Các ví lớn nhất có dấu hiệu giảm nắm giữ",
    "weak_absorption": "Giá giảm nhưng lực mua đỡ yếu",
    "holders_stable": "Các ví lớn nhìn chung không đổi (độ tin cậy cao hơn)",
    "whale_accumulating": "Các ví lớn nhất có dấu hiệu mua thêm",
    "dip_absorbed": "Giá giảm nhưng có lực mua đỡ tốt",
    "late_entry_risk": "Tăng trên 100% trong 1 giờ qua trên cặp dưới 1 ngày tuổi: vào muộn khi đang bơm",
    "one_sided_flow": "Hơn 90% giao dịch trong 5 phút gần nhất nằm về một phía, với mức hoạt động cao",
    "no_recent_trades": "Không có giao dịch nào trong 5 phút gần nhất: giá và báo giá bán kém tin cậy hơn",
}
_T = {
    "en": {
        "verdict": {"ok": "OK", "caution": "CAUTION", "avoid": "AVOID"},
        "blocked": "A blocking red flag forces AVOID whatever the score: ",
        "avoid_score": "The risk score {s} is at or above the avoid line ({a}).",
        "caution_flags": "These flags keep the verdict at CAUTION: ",
        "caution_score": "The risk score {s} is at or above the caution line ({c}).",
        "ok": "No blocking or caution flags, and the risk score is below the caution line ({c}).",
        "sum": "The score is the sum of the points of the scored flags, capped at 100: {t} points, shown as {s}.",
        "sum_capped": "The score is the sum of the points of the scored flags, capped at 100: {t} points, shown as 100.",
        "stay_avoid": "It stays AVOID while any of these is present: ",
        "to_leave_avoid": "To leave AVOID by score it must fall below {a}, which is {n} points less. The biggest contributors: ",
        "stay_caution": "It stays CAUTION while any of these flags is present: ",
        "to_leave_caution": "To reach OK the score must fall below {c}, which is {n} points less. The biggest contributors: ",
        "headroom": "{n} more points of risk would make it CAUTION.",
        "none": "no major red flags found",
        "head": "{v} (risk {s}/100). {r}.",
        "points": "pts",
        "disc": "Heuristic output, not financial advice.",
        "lang_note": None,
    },
    "vi": {
        "verdict": {"ok": "OK", "caution": "THẬN TRỌNG", "avoid": "TRÁNH"},
        "blocked": "Một cờ đỏ chặn buộc kết quả là TRÁNH dù điểm thế nào: ",
        "avoid_score": "Điểm rủi ro {s} bằng hoặc vượt ngưỡng tránh ({a}).",
        "caution_flags": "Các cờ này giữ kết quả ở mức THẬN TRỌNG: ",
        "caution_score": "Điểm rủi ro {s} bằng hoặc vượt ngưỡng thận trọng ({c}).",
        "ok": "Không có cờ chặn hay cờ thận trọng, và điểm rủi ro thấp hơn ngưỡng thận trọng ({c}).",
        "sum": "Điểm là tổng điểm của các cờ được tính, tối đa 100: {t} điểm, hiển thị là {s}.",
        "sum_capped": "Điểm là tổng điểm của các cờ được tính, tối đa 100: {t} điểm, hiển thị là 100.",
        "stay_avoid": "Vẫn là TRÁNH chừng nào còn bất kỳ cờ nào sau: ",
        "to_leave_avoid": "Để thoát mức TRÁNH theo điểm, điểm phải xuống dưới {a}, tức giảm {n} điểm. Đóng góp lớn nhất: ",
        "stay_caution": "Vẫn là THẬN TRỌNG chừng nào còn bất kỳ cờ nào sau: ",
        "to_leave_caution": "Để lên mức OK, điểm phải xuống dưới {c}, tức giảm {n} điểm. Đóng góp lớn nhất: ",
        "headroom": "Thêm {n} điểm rủi ro nữa sẽ chuyển thành THẬN TRỌNG.",
        "none": "không thấy cờ đỏ lớn",
        "head": "{v} (rủi ro {s}/100). {r}.",
        "points": "điểm",
        "disc": "Kết quả mang tính heuristic, không phải lời khuyên tài chính.",
        "lang_note": "Phần tích cực, cần lưu ý và chưa biết lấy từ engine nên vẫn bằng tiếng Anh.",
    },
}


def _en_text(flag: str) -> str:
    hyp = globals().get("HYPOTHESES") or {}
    return REASONS.get(flag) or hyp.get(flag) or _EN_EXTRA.get(flag) or flag.replace("_", " ")


def _flag_text(flag: str, lang: str) -> str:
    return (_VI.get(flag) if lang == "vi" else None) or _en_text(flag)


def build_explanation(sig: dict, lang: str = "en") -> dict:
    """Pure function: one signal in, one explanation out. Never invents a number: it reads what the engine produced."""
    lang = lang if lang in _T else "en"
    t = _T[lang]
    dec = sig.get("decision") or {}
    verdict = str(sig.get("verdict") or "unknown")
    score = int(sig.get("risk_score") or 0)
    not_scored = set(sig.get("flags_not_scored") or [])
    blockers, cautions = set(dec.get("blockers") or []), set(dec.get("cautions") or [])
    items = []
    for f in [x for x in (sig.get("flags") or []) if isinstance(x, str)]:
        counted = f not in not_scored
        pts = int(ACTIVE_WEIGHTS.get(f, 0)) if counted else 0
        en = _en_text(f)
        role = ("blocker" if en in blockers else "caution" if en in cautions else "positive" if f in _POSITIVE_FLAGS
                else "scores" if pts > 0 else "info")
        items.append({"flag": f, "role": role, "points": pts, "counted": counted, "text": _flag_text(f, lang)})
    items.sort(key=lambda i: (_ROLE_ORDER[i["role"]], -i["points"], i["flag"]))
    total = sum(i["points"] for i in items)
    hard = [i for i in items if i["role"] == "blocker"]
    soft = [i for i in items if i["role"] == "caution"]
    scored = [i for i in items if i["points"] > 0]
    top = ", ".join(f"{i['flag']} (+{i['points']})" for i in sorted(scored, key=lambda x: -x["points"])[:3])
    why, change = [], []
    if verdict == "avoid" and hard:
        why.append(t["blocked"] + "; ".join(i["text"] for i in hard) + ".")
        change.append(t["stay_avoid"] + ", ".join(i["flag"] for i in hard) + ".")
    elif verdict == "avoid":
        why.append(t["avoid_score"].format(s=score, a=_AVOID_AT))
        change.append(t["to_leave_avoid"].format(a=_AVOID_AT, n=score - _AVOID_AT + 1) + top + ".")
    elif verdict == "caution" and soft:
        why.append(t["caution_flags"] + "; ".join(i["text"] for i in soft) + ".")
        change.append(t["stay_caution"] + ", ".join(i["flag"] for i in soft) + ".")
    elif verdict == "caution":
        why.append(t["caution_score"].format(s=score, c=_CAUTION_AT))
        change.append(t["to_leave_caution"].format(c=_CAUTION_AT, n=score - _CAUTION_AT + 1) + top + ".")
    elif verdict == "ok":
        why.append(t["ok"].format(c=_CAUTION_AT))
        change.append(t["headroom"].format(n=max(0, _CAUTION_AT - score)))
    why.append((t["sum_capped"] if total > 100 else t["sum"]).format(t=total, s=score))
    main = (hard[0]["text"] if hard else soft[0]["text"] if soft else t["none"] if score < _CAUTION_AT else
            t["avoid_score" if verdict == "avoid" else "caution_score"].format(s=score, a=_AVOID_AT, c=_CAUTION_AT)).rstrip(".")
    return {
        "verdict": verdict, "risk_score": score, "scoring": sig.get("scoring"), "asset_class": dec.get("asset_class") or sig.get("asset_class"),
        "language": lang, "headline": t["head"].format(v=t["verdict"].get(verdict, verdict.upper()), s=score, r=main),
        "why": why, "flags": items, "points_total": total, "capped": total > 100, "what_would_change": change,
        "positives": list(dec.get("positives") or [])[:6], "unknowns": list(dec.get("unknowns") or [])[:6],
        "note": dec.get("note"), "language_note": t["lang_note"], "disclaimer": t["disc"],
    }


async def _explain(request: Request, mint: str, lang: str):
    wait = rate_limited(client_ip(request))
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    mint = (mint or "").strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    lang = (lang or "en").lower()[:4]
    sig, _status = await build_signal(request.app.state.client, mint, True)  # build_signal returns (result, cache status)
    if lang == "both":
        body = {"en": build_explanation(sig, "en"), "vi": build_explanation(sig, "vi")}
    else:
        body = build_explanation(sig, "vi" if lang.startswith("vi") else "en")
    return JSONResponse(content={"mint": mint, "token": sig.get("token"), "explanation": body, "generated_from": "live rules and weights"},
                        headers={"Cache-Control": "public, max-age=15"})


@app.get("/explain", tags=["signal"], summary="Why this verdict, in plain words (lang=en|vi|both)")
async def explain_query(request: Request, mint: str = "", lang: str = "en"):
    return await _explain(request, mint, lang)


@app.get("/explain/{mint}", tags=["signal"], include_in_schema=False)
async def explain_path(mint: str, request: Request, lang: str = "en"):
    return await _explain(request, mint, lang)


print(f"[part33] v{VERSION} /explain ready (lang=en|vi|both)")
