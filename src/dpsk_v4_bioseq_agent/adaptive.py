"""AIMD adaptive concurrency limiter, shared across threads.

Gates in-flight HTTP calls. Starts at `init`, additively increases (+1) after a run of
clean successes, multiplicatively decreases (halve) on a 429/5xx throttle, clamped to
[lo, hi]. Pair it with retry-with-backoff in the request layer (see llm._request).
"""
import threading, time


class AdaptiveLimiter:
    def __init__(self, init=10, lo=3, hi=20, increase_after=8, cooldown_s=4.0):
        self.limit = max(lo, min(hi, init))
        self.lo, self.hi = lo, hi
        self.increase_after = increase_after
        self.cooldown_s = cooldown_s
        self.active = 0
        self._succ = 0
        self._last_throttle = 0.0
        self._cv = threading.Condition()
        self.stats = {"throttles": 0, "max_limit": self.limit, "min_limit": self.limit,
                      "calls": 0}

    # ---- concurrency gate ----
    def acquire(self):
        with self._cv:
            while self.active >= self.limit:
                self._cv.wait(timeout=0.5)
            self.active += 1

    def release(self):
        with self._cv:
            self.active -= 1
            self._cv.notify()

    # ---- AIMD feedback ----
    def on_success(self):
        with self._cv:
            self.stats["calls"] += 1
            self._succ += 1
            if (self._succ >= max(self.increase_after, self.limit)
                    and (time.time() - self._last_throttle) > self.cooldown_s
                    and self.limit < self.hi):
                self.limit += 1
                self.stats["max_limit"] = max(self.stats["max_limit"], self.limit)
                self._succ = 0
                self._cv.notify_all()

    def on_throttle(self):
        with self._cv:
            self.stats["throttles"] += 1
            self._last_throttle = time.time()
            self._succ = 0
            new = max(self.lo, self.limit // 2)
            if new < self.limit:
                self.limit = new
                self.stats["min_limit"] = min(self.stats["min_limit"], self.limit)

    def snapshot(self):
        with self._cv:
            return {"limit": self.limit, "active": self.active, **self.stats}
