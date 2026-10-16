"""HTTP-Zugriff mit höflichem Takt, Wiederholung und Zeitbudget."""
import time
import requests

from . import config


class BudgetExceeded(Exception):
    pass


class Http:
    def __init__(self, budget_min: float):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9",
        })
        self.deadline = time.monotonic() + budget_min * 60
        self._last = 0.0
        self.requests = 0
        self.errors = 0

    def time_left(self) -> float:
        return self.deadline - time.monotonic()

    def check_budget(self, reserve_sec: float = 60):
        if self.time_left() < reserve_sec:
            raise BudgetExceeded()

    def _pace(self):
        wait = config.REQUEST_PAUSE_SEC - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def request(self, method: str, url: str, *, retries: int = 2, **kw):
        """Liefert Response oder None. 404 gilt als endgültig (kein Retry)."""
        kw.setdefault("timeout", config.REQUEST_TIMEOUT)
        for attempt in range(retries + 1):
            self.check_budget(reserve_sec=30)
            self._pace()
            self.requests += 1
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code == 404:
                    return None
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                self.errors += 1
                if attempt == retries:
                    print(f"    ✗ {method} {url} → {e}")
                    return None
                time.sleep(3 * (attempt + 1))
        return None

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
