"""Atomic PostgreSQL rate limits shared by every API worker."""
import hashlib
import time
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from sqlalchemy.dialects.postgresql import insert
from app.core.config import Config
from app.core.security_models import RateLimitBucket


def rate_limit(spec, global_scope=False):
    maximum, _, unit = spec.split()
    maximum = int(maximum)
    seconds = {'minute': 60, 'hour': 3600}[unit]
    def dependency(request: Request):
        if not getattr(Config, 'RATELIMIT_ENABLED', True):
            return
        from app.core import db
        now = time.time()
        window = int(now // seconds)
        peer = request.client.host if request.client else 'unknown'
        path = '*' if global_scope else request.scope['route'].path
        key = hashlib.sha256(f'{peer}:{path}:{spec}:{window}'.encode()).hexdigest()
        stmt = insert(RateLimitBucket).values(key=key, count=1,
            expires_at=datetime.fromtimestamp((window + 1) * seconds, timezone.utc))
        stmt = stmt.on_conflict_do_update(index_elements=['key'],
                   set_={'count': RateLimitBucket.count + 1}).returning(RateLimitBucket.count)
        with db.engine.begin() as conn:
            from sqlalchemy import delete
            conn.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at < datetime.now(timezone.utc)))
            count = conn.execute(stmt).scalar_one()
        if count > maximum:
            raise HTTPException(429, 'Too many requests')
    return dependency
