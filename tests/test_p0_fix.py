from verdict import build_verdict

def _calc(data):
    return "ok"

def test_sol_stale_low_confidence_must_not_pass():
    data = {"price_age_s": 313, "freshness": "stale", "dex_down": True, "gecko_down": True, "jupiter_down": True, "all_price_down": True, "data_confidence": 0.64, "asset_class": "major", "unknowns": ["Data is 313s old", "Exit cost not checked", "Community..."]}
    out = build_verdict("So11111111111111111111111111111111111111112", data, _calc)
    assert out["verdict"] == "ok"
    assert out["action"] == "review"
    assert out["filter"]["pass"] is False
    assert out["filter"]["pass_strict"] is False
    assert out["valid_for_s"] == 30
    assert out["unknowns"] == out["decision"]["unknowns"]

def test_fresh_high_confidence_can_pass():
    data = {"price_age_s": 10, "freshness": "fresh", "data_confidence": 0.95, "asset_class": "major", "unknowns": []}
    out = build_verdict("So11111111111111111111111111111111111111112", data, _calc)
    assert out["filter"]["pass"] is True

def test_community_insufficient():
    from verdict import build_community
    c = build_community([1] * 9)
    assert c["insufficient_samples"] is True