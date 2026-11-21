"""Thin JSON HTTP client with disk cache, retries, and a polite rate limit."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class HttpClient:
    def __init__(
        self,
        cache_dir: Path,
        min_interval: float = 0.08,
        timeout: float = 20,
        retries: int = 3,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._lock = threading.Lock()
        self._last_request = 0.0

    def get_json(
        self,
        url: str,
        cache_key: str | None = None,
        use_cache: bool = True,
        params: dict | None = None,
        allow_404: bool = False,
    ) -> Any:
        cache_path = self.cache_dir / f"{cache_key}.json" if cache_key else None
        if use_cache and cache_path and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self._throttle()
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 404:
                    if allow_404:
                        return None
                    resp.raise_for_status()
                if resp.status_code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    last_error = RuntimeError(f"HTTP {resp.status_code} for {url}")
                    continue
                resp.raise_for_status()
                data = resp.json()
                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(data), encoding="utf-8")
                return data
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error

    def _throttle(self) -> None:
        with self._lock:
            wait = self.min_interval - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.time()
