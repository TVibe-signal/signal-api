import time
from collections import OrderedDict

CACHE_CONFIG = {
    "price":    {"ttl": 30,   "stale_max": 120},
    "rugcheck": {"ttl": 300,  "stale_max": 600},
    "metadata": {"ttl": 1800, "stale_max": 3600},
    "verdict":  {"ttl": 60,   "stale_max": 600},
    "error":    {"ttl": 30,   "stale_max": 30},
}
CACHE_SIZE = 1000

class LRUCache:
    def __init__(self, maxsize=CACHE_SIZE):
        self.store = OrderedDict()
        self.maxsize = maxsize
    def get(self, key):
        if key not in self.store:
            return None
        v = self.store.pop(key)
        self.store[key] = v
        return v
    def set(self, key, value):
        if key in self.store:
            self.store.pop(key)
        self.store[key] = value
        while len(self.store) > self.maxsize:
            self.store.popitem(last=False)

caches = {k: LRUCache() for k in CACHE_CONFIG}

def cache_get(layer, key):
    e = caches[layer].get(key)
    if not e:
        return None
    age = int(time.time() - e["ts"])
    if age > CACHE_CONFIG[layer]["ttl"]:
        return {"stale": True, "value": e["value"], "age_s": age}
    return {"stale": False, "value": e["value"], "age_s": age}

def cache_set(layer, key, value):
    caches[layer].set(key, {"ts": time.time(), "value": value})