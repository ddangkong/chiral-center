"""Anonymous session ownership via a cookie-backed session ID."""

import json
import pathlib
import secrets
import threading

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


SESSION_COOKIE = "chiral_sid"
_MAX_AGE = 60 * 60 * 24 * 365  # 1 year
_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_OWNERSHIP_FILE = _DATA_DIR / "ownership.json"

_lock = threading.Lock()


def _load_ownership() -> dict[str, str]:
    if not _OWNERSHIP_FILE.exists():
        return {}
    try:
        return json.loads(_OWNERSHIP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ownership(data: dict[str, str]) -> None:
    tmp = _OWNERSHIP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_OWNERSHIP_FILE)


def _key(kind: str, resource_id: str) -> str:
    return f"{kind}:{resource_id}"


class SessionMiddleware(BaseHTTPMiddleware):
    """Issue a session cookie on first visit and attach it to request.state."""

    async def dispatch(self, request: Request, call_next):
        sid = request.cookies.get(SESSION_COOKIE)
        issue_new = False
        if not sid:
            sid = secrets.token_urlsafe(24)
            issue_new = True
        request.state.session_id = sid

        response = await call_next(request)

        if issue_new:
            response.set_cookie(
                key=SESSION_COOKIE,
                value=sid,
                httponly=True,
                samesite="lax",
                max_age=_MAX_AGE,
                path="/",
            )
        return response


def get_session_id(request: Request) -> str:
    """Return the current request session ID."""
    return getattr(request.state, "session_id", "") or ""


def register_owner(kind: str, resource_id: str, session_id: str) -> None:
    """Persist the owning session for a resource."""
    if not session_id or not resource_id:
        return
    with _lock:
        data = _load_ownership()
        data[_key(kind, resource_id)] = session_id
        _save_ownership(data)


def get_owner(kind: str, resource_id: str) -> str:
    """Return the owning session ID, or empty string when missing."""
    data = _load_ownership()
    return data.get(_key(kind, resource_id), "")


def is_owner(kind: str, resource_id: str, session_id: str) -> bool:
    """Ownerless resources are treated as private."""
    owner = get_owner(kind, resource_id)
    return bool(owner) and owner == session_id


def filter_owned_ids(kind: str, ids: list[str], session_id: str) -> list[str]:
    """Return only resource IDs owned by the current session."""
    if not ids:
        return []
    data = _load_ownership()
    out = []
    for rid in ids:
        owner = data.get(_key(kind, rid), "")
        if owner and owner == session_id:
            out.append(rid)
    return out


def remove_owner(kind: str, resource_id: str) -> None:
    with _lock:
        data = _load_ownership()
        k = _key(kind, resource_id)
        if k in data:
            del data[k]
            _save_ownership(data)
