"""Thread-safe single-job progress tracker -> atomic JSON the dashboard polls."""
import json
import os
import tempfile
import threading
import time


class Progress:
    def __init__(self, path, title, started_at, total=0):
        self.path = path
        self._lock = threading.Lock()
        self.state = {
            "title": title, "status": "running", "started_at": started_at,
            "updated_at": started_at, "total": total, "done": 0, "passed": 0,
            "limiter": {}, "category_split": {}, "by_type": {}, "items": [],
        }
        self._flush(started_at)

    def _flush(self, now):
        self.state["updated_at"] = now
        d = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def set_total(self, total, now):
        with self._lock:
            self.state["total"] = total
            self._flush(now)

    def set_status(self, status, now):
        with self._lock:
            self.state["status"] = status
            self._flush(now)

    def heartbeat(self, limiter_snap, now):
        with self._lock:
            self.state["limiter"] = limiter_snap
            self._flush(now)

    def add_item(self, item, now, limiter_snap=None):
        with self._lock:
            self.state["items"].append(item)
            self.state["done"] = len(self.state["items"])
            if isinstance(item.get("score"), (int, float)):
                self.state["passed"] = sum(1 for x in self.state["items"] if x.get("score") == 1.0)
            cat = item.get("category", "?")
            self.state["category_split"][cat] = self.state["category_split"].get(cat, 0) + 1
            t = item.get("type", "?")
            bt = self.state["by_type"].setdefault(t, {"n": 0, "pass": 0})
            bt["n"] += 1
            if item.get("score") == 1.0:
                bt["pass"] += 1
            if limiter_snap is not None:
                self.state["limiter"] = limiter_snap
            self._flush(now)


def heartbeat_loop(prog: "Progress", limiter, stop: threading.Event, interval: float = 2.0) -> None:
    """Refresh the limiter snapshot every ``interval`` seconds until ``stop`` is set.

    Run in a daemon thread:
        threading.Thread(target=heartbeat_loop, args=(prog, lim, stop), daemon=True).start()
    """
    while not stop.is_set():
        prog.heartbeat(limiter.snapshot(), time.time())
        stop.wait(interval)
