from sqlalchemy import Column, String, Numeric, Integer, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.orm import validates, relationship
from app.core.db import Base
from app.shared.models import SerializableMixin
from app.shared.utils import utc_now, generate_uuid

class Product(Base, SerializableMixin):
    __tablename__ = 'products'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    weight = Column(String(100), nullable=True)
    category = Column(String(100), nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    original_price = Column(Numeric(12, 2), nullable=True)
    is_discount = Column(Boolean, default=False, nullable=False)
    discount_percent = Column(Integer, default=0, nullable=False)
    sku = Column(String(64), unique=True, nullable=False)
    image_url = Column(String(500), nullable=True)
    
    # Unit and packaging configuration
    unit = Column(String(20), default='pack', nullable=False)  # 'pack', 'mika', 'vakum', 'pcs', 'kg', 'custom'
    pack_size = Column(Integer, default=25, nullable=False)  # Number of pieces per unit (for pack/mika/vakum)
    unit_label = Column(String(50), nullable=True)  # Display label: "Mika (Isi 50 Pcs)", "Pack Vakum (Isi 25 Pcs)", etc.
    
    stock_qty = Column(Integer, default=0, nullable=False)
    stock_offline = Column(Integer, default=0, nullable=False)
    stock_online = Column(Integer, default=0, nullable=False)
    min_buffer_stock = Column(Integer, default=70, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    @validates('stock_qty')
    def validate_stock_qty(self, key, value):
        if value is not None:
            val_int = int(value)
            cur_pool = (self.stock_offline or 0) + (self.stock_online or 0)
            if cur_pool != val_int:
                self.stock_offline = int(val_int * 0.6)
                self.stock_online = val_int - self.stock_offline
            return val_int
        return value

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if 'stock_qty' in kwargs and kwargs.get('stock_qty') is not None:
            total = int(kwargs['stock_qty'])
            if 'stock_offline' not in kwargs or kwargs['stock_offline'] is None:
                self.stock_offline = int(total * 0.6)
            if 'stock_online' not in kwargs or kwargs['stock_online'] is None:
                self.stock_online = total - (self.stock_offline or 0)

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        stock_off = self.stock_offline or 0
        stock_on = self.stock_online or 0
        total_pool = stock_off + stock_on
        if total_pool == 0 and (self.stock_qty or 0) > 0:
            stock = self.stock_qty or 0
            stock_off = int(stock * 0.6)
            stock_on = stock - stock_off
        else:
            stock = total_pool if (self.stock_offline is not None or self.stock_online is not None) else (self.stock_qty or 0)

        d['stock_offline'] = stock_off
        d['stock_online'] = stock_on
        d['stock_qty'] = stock
        min_buf = self.min_buffer_stock or 70

        # Dynamic packaging info from database
        d['packaging_type'] = self.unit
        d['pack_size'] = self.pack_size or 25
        d['unit_label'] = self.unit_label or f"{self.unit.title()} (Isi {self.pack_size} Pcs)"

        if stock < min_buf:
            d['buffer_status'] = 'critical'
            d['buffer_label'] = f'Stok Kritis (< {min_buf} pack)'
        elif stock <= 100:
            d['buffer_status'] = 'warning'
            d['buffer_label'] = f'Mendekati Batas Aman ({min_buf}-100 pack)'
        else:
            d['buffer_status'] = 'safe'
            d['buffer_label'] = 'Stok Aman (> 100 pack)'
        return d

