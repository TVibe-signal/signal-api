"""patch_filter_v4.py - TVibe Filter v4.1: hard vetoes + stronger scoring.
Safe: wraps build_signal, never deletes old logic. Only upgrades pass->review/skip, never skip->pass.
Apply via main.py: import patch_filter_v4; patch_filter_v4.apply(globals())
"""
import math

def apply(g):
    app = g.get("app")
    orig_build = g.get("build_signal")
    VERSION = g.get("VERSION", "3.0.28")
    if orig_build is None:
        print("[filter_v4] skipped: build_signal missing")
        return

    # --- Thresholds distilled from RugCheck / GMGN / Cabal-Hunter / irene / Pump sniper ---
    T = {
        "liq_min_usd": 10000,        # <10k = no real exit
        "lp_lock_min": 50,            # <50% = Risk (RugCheck), >=90% = No issue
        "lp_lock_strong": 90,
        "top10_warn": 50,             # Top10 >50% = concentration flag
        "top10_hard": 60,             # Top10 >60% = Risk (Bitget/GMGN)
        "top10_veto": 80,             # Top10 >80% + dev/insider = veto
        "dev_hold_warn": 10,
        "dev_hold_hard": 30,
        "rug_ratio_warn": 0.25,
        "rug_ratio_hard": 0.30,       # irene MAX_RUG_RATIO
        "bundler_warn": 0.20,
        "vol_liq_wash": 12.0,         # MemeScout: vol1h >12x liq = wash / fake
        "vol_liq_warn": 8.0,
        "mcap_max_hype": 500000,      # >500k needs stronger proof
    }

    async def build_signal_v4(*args, **kwargs):
        out = await orig_build(*args, **kwargs)
        try:
            if not isinstance(out, dict):
                return out
            # --- Extract signals from existing output (tolerant to shape changes) ---
            sec = out.get("security") or out.get("sec") or {}
            dex = out.get("dex") or out.get("market") or {}
            filt = out.get("filter") or {}
            # Normalize keys (code uses many aliases)
            def pick(*names, default=None):
                for src in (out, sec, dex, filt):
                    if not isinstance(src, dict):
                        continue
                    for n in names:
                        if n in src and src[n] is not None:
                            return src[n]
                return default
            liq = float(pick("liquidity_usd", "liq_usd", "liq", "liquidity", default=0) or 0)
            lp_lock = pick("lp_locked_pct", "lp_lock_pct", "lpLockedPct", "lp_locked", default=None)
            lp_lock = float(lp_lock) if lp_lock is not None else None
            top10 = float(pick("top10_pct", "top10_holder_pct", "top10", default=0) or 0)
            dev_hold = float(pick("dev_hold_pct", "dev_holdings", "dev_pct", default=0) or 0)
            rug_ratio = pick("rug_ratio", "rugRatio", default=None)
            rug_ratio = float(rug_ratio) if rug_ratio is not None else None
            bundler = pick("bundler_rate", "bundler_pct", default=None)
            bundler = float(bundler) if bundler is not None else None
            vol1h = float(pick("vol1h", "volume_1h", "vol_1h", default=0) or 0)
            honeypot = bool(pick("is_honeypot", "honeypot", "honeypot_risk_heuristic", default=False))
            mint_auth = pick("mint_authority_active", "mint_auth", "mint_authority", default=None)
            freeze_auth = pick("freeze_authority_active", "freeze_auth", "freeze_authority", default=None)
            # mint_auth may be bool or string; normalize: True = still active = dangerous
            mint_active = mint_auth is True or (isinstance(mint_auth, str) and mint_auth.lower() in ("true", "active", "enabled"))
            freeze_active = freeze_auth is True or (isinstance(freeze_auth, str) and freeze_auth.lower() in ("true", "active", "enabled"))
            rug_label = str(pick("rugcheck_label", "rug_label", "rugcheck", default="")).lower()
            # --- Vetoes: pass -> review/skip only ---
            vetoes = []
            unknowns = list(out.get("unknowns") or [])
            if honeypot:
                vetoes.append("honeypot")
            if mint_active and freeze_active and (lp_lock is not None and lp_lock < T["lp_lock_min"]):
                vetoes.append("mint+freeze active + LP unlocked")
            if lp_lock is not None and lp_lock < T["lp_lock_min"] and (rug_label in ("danger", "high") or (rug_ratio is not None and rug_ratio >= T["rug_ratio_hard"])):
                vetoes.append("LP unlocked + RugCheck danger/high rug_ratio")
            if top10 >= T["top10_veto"] and dev_hold >= T["dev_hold_warn"]:
                vetoes.append("top10>=80% + dev holds")
            if rug_ratio is not None and rug_ratio >= 0.5:
                vetoes.append("rug_ratio>=0.5")
            if liq > 0 and vol1h > 0 and (vol1h / max(liq, 1)) >= T["vol_liq_wash"]:
                # Wash / fake volume: do not trust price, force review (not auto-pass)
                vetoes.append("vol1h/liq>=12 wash suspect")
            # --- Extra v4.1 signals: deployer / bundler / fresh wallets ---
            deployer_rugs = pick("deployer_rug_count", "creator_rug_count", "deployer_rugs", default=None)
            deployer_rugs = int(deployer_rugs) if deployer_rugs is not None else None
            fresh_pct = pick("fresh_wallet_pct", "fresh_pct", default=None)
            fresh_pct = float(fresh_pct) if fresh_pct is not None else None
            if deployer_rugs is not None and deployer_rugs >= 1:
                vetoes.append(f"deployer rugged {deployer_rugs} time(s) before")
            if fresh_pct is not None and fresh_pct >= 70:
                vetoes.append("fresh wallets >=70% (sybil/bundled)")
            # --- Score adjustments (additive, transparent) ---
            reasons = list(out.get("reasons") or [])
            score_adj = 0
            if lp_lock is not None:
                if lp_lock >= T["lp_lock_strong"]:
                    score_adj += 5
                elif lp_lock < T["lp_lock_min"]:
                    score_adj -= 15; reasons.append("LP lock <50%")
            if top10 >= T["top10_hard"]:
                score_adj -= 12; reasons.append(f"Top10 {top10:.0f}% >=60%")
            elif top10 >= T["top10_warn"]:
                score_adj -= 6; reasons.append(f"Top10 {top10:.0f}% >=50%")
            if dev_hold >= T["dev_hold_hard"]:
                score_adj -= 10; reasons.append(f"Dev holds {dev_hold:.0f}% >=30%")
            if rug_ratio is not None and rug_ratio >= T["rug_ratio_warn"]:
                score_adj -= 8; reasons.append(f"rug_ratio {rug_ratio:.2f} >=0.25")
            if bundler is not None and bundler >= T["bundler_warn"]:
                score_adj -= 8; reasons.append(f"bundler {bundler:.2f} >=20%")
            if liq > 0 and liq < T["liq_min_usd"]:
                score_adj -= 10; reasons.append(f"Liq ${liq:,.0f} < $10k")
            # Apply
            action = out.get("action")
            if vetoes:
                # Strong vetoes -> skip, wash-only -> review
                if any("wash" in v for v in vetoes) and len(vetoes) == 1:
                    new_action = "review"
                else:
                    new_action = "skip"
                if action == "pass":
                    out["action"] = new_action
                    if isinstance(filt, dict):
                        filt["pass"] = False
                out["filter_v4_vetoes"] = vetoes
                reasons.append("filter_v4 veto: " + "; ".join(vetoes))
            out["reasons"] = reasons
            if isinstance(out.get("score"), (int, float)):
                out["score"] = max(0, min(100, out["score"] + score_adj))
            out["filter_version"] = "v4.1"
            out["filter_v4"] = {"thresholds": T, "score_adj": score_adj, "vetoes": vetoes}
            # Unknowns: missing LP lock / holder data must block sizing (never pass on unknown)
            if lp_lock is None and action == "pass":
                if "lp_lock" not in unknowns:
                    unknowns.append("lp_lock")
                out["action"] = "review"
                if isinstance(filt, dict):
                    filt["pass"] = False
            out["unknowns"] = unknowns
            return out
        except Exception as e:
            # Never break /omni because filter_v4 failed
            try:
                out["filter_v4_error"] = str(e)[:120]
            except Exception:
                pass
            return out

    g["build_signal"] = build_signal_v4
    # Also patch _stats / rules endpoint if it exposes thresholds - keep version tag
    try:
        if app is not None:
            print(f"[filter_v4] applied v4.1 over build_signal, VERSION={VERSION}")
        else:
            print("[filter_v4] applied v4.1 (no app)")
    except Exception:
        pass
