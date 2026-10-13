import asyncio
import json
import os
import types

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = [1_000_000]


class FakeRedis:
    def __init__(self):
        self.d, self.z = {}, {}

    def cmd(self, op, key, *a):
        if op == "ZADD":
            self.z.setdefault(key, {})[a[1]] = a[0]
            return 1
        if op == "ZREM":
            return 1 if self.z.get(key, {}).pop(a[0], None) is not None else 0
        if op == "ZRANGEBYSCORE":
            hi = a[1]
            lim = a[3] if len(a) > 3 else 1000
            return [m for m, s in sorted(self.z.get(key, {}).items(), key=lambda x: x[1]) if s <= hi][:a[-1]]
        if op == "INCR":
            self.d[key] = int(self.d.get(key, 0)) + 1
            return self.d[key]
        if op == "EXPIRE":
            return 1
        raise NotImplementedError(op)

    async def pipe(self, client, cmds):
        return [self.cmd(*c) for c in cmds]

    async def get(self, client, key):
        return self.d.get(key)

    async def set(self, client, key, val, ttl=None):
        self.d[key] = val


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class Client:
    def __init__(self):
        self.script = {}

    async def get(self, url, timeout=0):
        r = self.script[url.rsplit("/", 1)[-1]].pop(0)
        if isinstance(r, Exception):
            raise r
        return r


R = FakeRedis()
CL = Client()
NOTED = []


async def fake_note(client, mint, bad):
    NOTED.append((mint, bad))
    return True


NS = {"app": types.SimpleNamespace(version="", openapi_schema=1), "PRED_ENABLED": True,
      "redis_pipe": R.pipe, "redis_get": R.get, "redis_set": R.set, "DEX_URL": "http://x/{mint}",
      "pick_best_pair": lambda pairs, mint: pairs[0] if pairs else None,
      "BAD_RETURN_PCT": -50.0, "BAD_LIQ_RATIO": 0.3, "hgx_note_outcome": fake_note,
      "PENDING_MULTI": "pm", "SNAP_OUTCOME_KEY": "sout:{}:{}",
      "MULTI_HORIZONS": {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}}
exec(compile(open(os.path.join(HERE, "part51.py"), encoding="utf-8").read(), "part51", "exec"), NS)
NS["time"] = types.SimpleNamespace(time=lambda: NOW[0])


def run(c):
    return asyncio.run(c)


def ok(price=1.0, liq=10000):
    pair = {"priceUsd": str(price)}
    if liq is not None:
        pair["liquidity"] = {"usd": liq}
    return Resp(200, {"pairs": [pair]})


GONE = Resp(200, {"pairs": None})


def setup(mint="M", ts=900_000, hz="1h", price=2.0, liq=20000, due_in=0):
    NOW[0] = ts + NS["MULTI_HORIZONS"][hz] + 100          # vừa quá hạn 100 giây
    R.d.clear(); R.z.clear(); NOTED.clear()
    for k in NS["HGX_STATS"]:
        NS["HGX_STATS"][k] = 0
    R.d[f"snap:{mint}:{ts}"] = json.dumps({"market": {"price": price, "liq": liq}})
    R.z["pm"] = {f"{mint}:{ts}:{hz}": NOW[0] - 10 + due_in}
    CL.script = {mint: []}


def out(mint="M", ts=900_000, hz="1h"):
    return (json.loads(R.d[f"snap:{mint}:{ts}"]).get("outcomes") or {}).get(hz)


def test_error_is_not_a_rug():
    setup()
    CL.script["M"] = [Resp(429), Exception("timeout"), Resp(200, {"oops": 1})]
    for _ in range(3):
        assert run(NS["resolve_multi_due"](CL)) == 0
        assert out() is None                                  # không có nhãn
        assert NS["HGX_STATS"]["retry"] >= 1
        assert R.z["pm"]["M:900000:1h"] == NOW[0] + 600       # hẹn thử lại
        NOW[0] += 601
    assert NOTED == []


def test_error_gives_up_after_6h():
    setup()
    NOW[0] += 7 * 3600
    CL.script["M"] = [Resp(500)]
    run(NS["resolve_multi_due"](CL))
    assert "M:900000:1h" not in R.z["pm"] and out() is None and NS["HGX_STATS"]["giveup"] == 1


def test_gone_needs_two_strikes():
    setup(hz="24h", ts=900_000)
    CL.script["M"] = [GONE, GONE]
    assert run(NS["resolve_multi_due"](CL)) == 0 and out(hz="24h") is None   # lần 1: hoãn
    NOW[0] += 901
    assert run(NS["resolve_multi_due"](CL)) == 1                              # lần 2: chốt
    o = out(hz="24h")
    assert o["bad"] and o["disappeared"] and o["return_pct"] == -100.0
    assert NOTED == [("M", True)]                                             # horizon 24h -> báo cluster
    assert "M:900000:24h" not in R.z["pm"]


def test_normal_outcomes():
    setup(price=2.0, liq=20000)
    CL.script["M"] = [ok(0.8, 15000)]                                         # -60%
    run(NS["resolve_multi_due"](CL))
    o = out()
    assert o["bad"] and o["return_pct"] == -60.0 and o["liq_ratio"] == 0.75 and not o["disappeared"]
    assert NOTED == []                                                        # 1h không báo cluster
    assert json.loads(R.d["sout:M:900000"])["1h"]["bad"]
    setup(price=2.0, liq=20000)
    CL.script["M"] = [ok(2.2, 4000)]                                          # liq còn 20% -> rug
    run(NS["resolve_multi_due"](CL))
    assert out()["bad"] and out()["liq_ratio"] == 0.2
    setup(price=2.0, liq=20000)
    CL.script["M"] = [ok(2.2, 18000)]
    run(NS["resolve_multi_due"](CL))
    assert out()["bad"] is False


def test_missing_liq_not_bad():
    setup(price=2.0, liq=0)                                                   # lúc chụp thiếu liq
    CL.script["M"] = [ok(2.1, 5000)]
    run(NS["resolve_multi_due"](CL))
    assert out()["bad"] is False and out()["liq_ratio"] is None
    setup(price=2.0, liq=20000)
    CL.script["M"] = [ok(2.1, None)]                                          # API không trả liq
    run(NS["resolve_multi_due"](CL))
    assert out()["bad"] is False and out()["liq_ratio"] is None
    setup(price=2.0, liq=20000)
    CL.script["M"] = [ok(2.1, 0)]                                             # liq = 0 thật -> đã rút
    run(NS["resolve_multi_due"](CL))
    assert out()["bad"] is True and out()["liq_ratio"] == 0.0


def test_missing_snapshot_and_bad_member_do_not_block():
    setup()
    R.d.pop("snap:M:900000")
    R.z["pm"]["broken-member"] = NOW[0] - 5
    CL.script["M"] = [ok()]
    assert run(NS["resolve_multi_due"](CL)) == 1
    assert R.z["pm"] == {} and NS["HGX_STATS"]["no_snap"] == 1 and NS["HGX_STATS"]["bad_member"] == 1
    setup(price=0)                                                            # snapshot thiếu giá
    CL.script["M"] = [ok()]
    run(NS["resolve_multi_due"](CL))
    assert out() is None and NS["HGX_STATS"]["no_price"] == 1 and R.z["pm"] == {}


def test_not_due_untouched():
    setup(due_in=5000)
    assert run(NS["resolve_multi_due"](CL)) == 0 and len(R.z["pm"]) == 1


if __name__ == "__main__":
    import sys
    bad = 0
    for n, f in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            f()
            print("ok  ", n)
        except Exception as e:                       # noqa
            bad += 1
            print("FAIL", n, type(e).__name__, e)
    sys.exit(1 if bad else 0)
