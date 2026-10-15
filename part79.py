# ---------- v2.58: Flag evidence labels (observation vs inference) ----------
VERSION = "2.58.0"
app.version = VERSION
app.openapi_schema = None

import os
from typing import Any, Dict, List

FLAG_LABELS = os.getenv("SI_FLAG_LABELS", "true").lower() in ("1", "true", "yes")

# Cờ do đo trực tiếp (on-chain / thị trường) -> observation
_OBS_EXACT = {
    "brand_new_pair", "no_recent_trades", "extreme_volume_spike",
    "transfer_fee_set", "transfer_fee_high", "transfer_fee_extreme",
    "transfer_hook_active", "permanent_delegate_active", "default_account_frozen",
    "low_liquidity", "mint_authority_active", "freeze_authority_active",
    "top_holders_concentrated", "whale_concentrated",
}
_OBS_PREFIX = ("transfer_", "permanent_", "default_account", "lp_", "holder_", "top10")
_OBS_PARTS = ("authority", "liquidity", "age")

# Cờ do heuristic / mô hình suy luận -> inference
_INF_PARTS = ("risk", "likely", "pattern", "suspect", "predict", "cluster", "dumper", "rug")

_BASIS = {
    "observation": "Measured directly from on-chain or market data at fetch time.",
    "inference": "Heuristic judgement built on observed data; can be wrong. Check the observations behind it.",
    "unknown": "Could not be verified. This is a gap in the evidence, not a finding that something is wrong.",
}


def _flag_id(f: Any) -> str:
    if isinstance(f, str):
        return f
    if isinstance(f, dict):
        for k in ("id", "flag", "name", "code"):
            if isinstance(f.get(k), str):
                return f[k]
    return ""


def _flag_kind(fid: str) -> str:
    x = fid.lower()
    if "unverified" in x or "unknown" in x:
        return "unknown"  # khoảng trống bằng chứng, không phải một phát hiện
    if x in _OBS_EXACT or x.startswith(_OBS_PREFIX):
        return "observation"
    if any(p in x for p in _INF_PARTS):
        return "inference"
    if any(p in x for p in _OBS_PARTS):
        return "observation"
    return "inference"  # không chắc thì không tự nhận là observation


def _label_flags(result: dict) -> dict:
    flags = result.get("flags") or result.get("risk_flags")
    if not isinstance(flags, list) or not flags:
        return result
    r = dict(result)  # không sửa object trong cache
    labelled: List[Dict[str, str]] = []
    n_obs = n_inf = n_unk = 0
    for f in flags:
        fid = _flag_id(f)
        if not fid:
            continue
        kind = _flag_kind(fid)
        if kind == "observation":
            n_obs += 1
        elif kind == "unknown":
            n_unk += 1
        else:
            n_inf += 1
        labelled.append({"flag": fid, "kind": kind, "basis": _BASIS[kind]})
    if labelled:
        r["flag_evidence"] = labelled
        r["evidence_counts"] = {
            "observations": n_obs,
            "inferences": n_inf,
            "unverified_flags": n_unk,
            "unknowns": len(r.get("unknowns") or []),
        }
    return r


_build_prev_labels = build_signal


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_labels(client, mint, security, *args, **kwargs)
    if not FLAG_LABELS:
        return res
    try:
        if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], dict):
            return _label_flags(res[0]), res[1]
        if isinstance(res, dict):
            return _label_flags(res)
    except Exception:
        pass
    return res


print(f"[part79] v{VERSION} flag evidence labels loaded (enabled={FLAG_LABELS})")
