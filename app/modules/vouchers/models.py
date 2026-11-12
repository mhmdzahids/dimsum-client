from sqlalchemy import Column, String, Numeric, Integer, Boolean, DateTime, Enum
from app.core.db import Base
from app.shared.models import SerializableMixin
from app.shared.utils import utc_now, generate_uuid

class Voucher(Base, SerializableMixin):
    __tablename__ = 'vouchers'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(50), unique=True, nullable=False, index=True)
    discount_type = Column(Enum('fixed', 'percent', name='voucher_discount_type'), default='fixed', nullable=False)
    discount_value = Column(Numeric(12, 2), nullable=False)
    min_spend = Column(Numeric(12, 2), default=0.0, nullable=False)
    max_discount = Column(Numeric(12, 2), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    usage_limit = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_public = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
