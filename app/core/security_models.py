from sqlalchemy import Column, String, DateTime, Integer
from app.core.db import Base


class RevokedToken(Base):
    __tablename__ = 'revoked_tokens'
    digest = Column(String(64), primary_key=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class RateLimitBucket(Base):
    __tablename__ = 'rate_limit_buckets'
    key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
