"""Request dependencies resolved from the current HTTP/WebSocket application."""
from fastapi import Depends, Header, HTTPException
from starlette.requests import HTTPConnection

from ..auth import Session
from ..runtime import Runtime


def get_runtime(connection: HTTPConnection) -> Runtime:
    return connection.app.state.runtime


def require_session(authorization: str | None = Header(default=None), *, runtime: Runtime = Depends(get_runtime)) -> Session:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    session = runtime.auth_service.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="authentication required")
    return session


def require_permission(permission: str):
    def dependency(session: Session = Depends(require_session)) -> Session:
        if permission not in session.permissions:
            raise HTTPException(status_code=403, detail="permission denied")
        return session

    return dependency
