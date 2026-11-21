"""In-memory JSON response cache with ETag / Cache-Control support."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from fastapi import Request
from fastapi.responses import Response

_LOCK = threading.Lock()
# cache_key -> (token, etag, body_bytes)
_CACHE: dict[str, tuple[str, str, bytes]] = {}
_MAX_ENTRIES = 256
CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"


def _etag_for(body: bytes) -> str:
    return '"' + hashlib.sha1(body).hexdigest()[:16] + '"'


def evict_token(token: str) -> None:
    """Drop entries whose freshness token no longer matches (board rebuilt)."""
    with _LOCK:
        stale = [k for k, (tok, _e, _b) in _CACHE.items() if tok != token]
        for k in stale:
            _CACHE.pop(k, None)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


def _lookup(cache_key: str, token: str) -> tuple[str, bytes] | None:
    with _LOCK:
        hit = _CACHE.get(cache_key)
        if hit and hit[0] == token:
            return hit[1], hit[2]
    return None


def _store(cache_key: str, token: str, etag: str, body: bytes) -> None:
    with _LOCK:
        _CACHE[cache_key] = (token, etag, body)
        if len(_CACHE) > _MAX_ENTRIES:
            extra = len(_CACHE) - _MAX_ENTRIES
            for key in list(_CACHE.keys())[:extra]:
                _CACHE.pop(key, None)


def json_response(
    request: Request,
    cache_key: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    build=None,
) -> Response:
    """Return a cached JSON body, or 304 when If-None-Match matches.

    `payload` is used when already computed. `build` is a zero-arg callable
    used only on a cache miss so we can skip filter work on a hit.
    """
    cached = _lookup(cache_key, token)
    if cached:
        etag, body = cached
    else:
        if payload is None:
            payload = build() if build else {}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        etag = _etag_for(body)
        _store(cache_key, token, etag, body)
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        "Vary": "Accept-Encoding",
    }
    inm = request.headers.get("if-none-match")
    if inm and inm == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json; charset=utf-8", headers=headers)
