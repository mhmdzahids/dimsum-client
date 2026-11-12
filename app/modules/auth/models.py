from sqlalchemy import Column, String, Enum, DateTime, Boolean, Integer
from app.core.db import Base
from app.shared.models import SerializableMixin
from app.shared.utils import utc_now, generate_uuid

class User(Base, SerializableMixin):
    __tablename__ = 'users'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum('customer', 'staff', 'checker', 'inventory', 'admin', name='user_roles'), default='customer', nullable=False)
    is_registered = Column(Boolean, default=True, nullable=False)
    auth_version = Column(Integer, nullable=False, default=0, server_default='0')
    created_at = Column(DateTime, default=utc_now, nullable=False)

    def to_dict(self, **kwargs):
        # NEVER expose password_hash
        return super().to_dict(exclude={'password_hash', 'auth_version'})
