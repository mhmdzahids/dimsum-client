import hashlib
from datetime import datetime, timezone
import jwt
from fastapi import Request, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert
from app.core.config import Config
from app.core.db import db_session
from app.core.security_models import RevokedToken


def revoke_token(token: str):
    if not token:
        return
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'], options={'require': ['exp', 'sub']})
    except jwt.InvalidTokenError:
        return
    from sqlalchemy import delete
    db_session.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(timezone.utc)))
    db_session.execute(insert(RevokedToken).values(
        digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.fromtimestamp(payload['exp'], timezone.utc)
    ).on_conflict_do_nothing())
    db_session.commit()


def is_token_revoked(token: str) -> bool:
    return db_session.get(RevokedToken, hashlib.sha256(token.encode()).hexdigest()) is not None


def verify_token(token):
    if not token:
        return None
    try:
        decoded = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'],
                             options={'require': ['exp', 'iat', 'sub', 'jti']})
    except jwt.InvalidTokenError:
        return None
    if is_token_revoked(token):
        return None
    from app.modules.auth.models import User
    user = db_session.get(User, decoded['sub'], populate_existing=True)
    if not user or not user.is_registered:
        return None
    if decoded.get('auth_version', 0) != user.auth_version:
        return None
    decoded['role'] = user.role
    decoded['user_id'] = user.id
    return decoded


def login_required(request: Request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    payload = verify_token(token.strip()) if scheme == 'Bearer' else None
    if not payload:
        raise HTTPException(401, 'Token is invalid, expired, or revoked')
    request.state.token = token.strip()
    request.state.user_id = payload['user_id']
    request.state.user_role = payload['role']
    return payload


def require_roles(*roles):
    def dependency(payload=Depends(login_required)):
        if payload['role'] not in roles and payload['role'] != 'admin':
            raise HTTPException(403, 'Access denied')
        return payload
    return dependency


admin_required = require_roles('admin')
staff_or_admin_required = require_roles('staff', 'checker', 'inventory')
inventory_or_admin_required = require_roles('inventory')
checker_or_admin_required = require_roles('checker')
production_or_admin_required = require_roles('inventory', 'staff')


def internal_api_key_required(request: Request):
    """Verifies that the request comes from the internal factory system via X-API-Key or X-Internal-Key."""
    from app.core.config import Config
    key = request.headers.get('X-API-Key') or request.headers.get('X-Internal-Key')
    if not key or not Config.INTERNAL_API_KEY or key.strip() != Config.INTERNAL_API_KEY.strip():
        raise HTTPException(401, 'Unauthorized: Invalid or missing internal API key')
    return key


def internal_or_admin_required(request: Request):
    """Allows either the internal factory API key OR an authenticated admin user."""
    from app.core.config import Config
    key = request.headers.get('X-API-Key') or request.headers.get('X-Internal-Key')
    if key and Config.INTERNAL_API_KEY and key.strip() == Config.INTERNAL_API_KEY.strip():
        return {'role': 'internal_system'}
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme == 'Bearer' and token.strip():
        payload = verify_token(token.strip())
        if payload and payload.get('role') == 'admin':
            request.state.token = token.strip()
            request.state.user_id = payload['user_id']
            request.state.user_role = payload['role']
            return payload
    raise HTTPException(401, 'Unauthorized: Valid internal API key or admin authorization required')

