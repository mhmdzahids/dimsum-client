from sqlalchemy import Column, String, Integer, Float, Boolean, Enum, DateTime, ForeignKey, Date
from sqlalchemy.orm import relationship, object_session
import json
from app.core.db import Base
from app.shared.models import SerializableMixin
from app.shared.utils import utc_now, generate_uuid


class ProductionBatch(Base, SerializableMixin):
    __tablename__ = 'production_batches'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    daily_plan_id = Column(String(36), ForeignKey('daily_production_plans.id'), nullable=True)
    batch_code = Column(String(64), unique=True, nullable=False)
    
    # Lot specifications (1 Lot = 25 products default)
    lot_size = Column(Integer, default=25, nullable=False)
    planned_lots = Column(Integer, default=1, nullable=False)
    actual_lots = Column(Integer, nullable=True)
    loose_qty = Column(Integer, default=0, nullable=False)
    
    produced_qty = Column(Integer, default=0, nullable=False)
    remaining_qty = Column(Integer, default=0, nullable=False)
    
    status = Column(
        Enum('planned', 'in_progress', 'completed', 'cancelled', name='batch_status'),
        default='planned',
        nullable=False
    )
    notes = Column(String(255), nullable=True)
    
    created_by = Column(String(36), ForeignKey('users.id'), nullable=False)
    checked_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    planned_at = Column(DateTime, default=utc_now, nullable=False)
    produced_at = Column(DateTime, default=utc_now, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    product = relationship('Product', lazy='joined')
    creator = relationship('User', foreign_keys=[created_by], lazy='joined')
    checker = relationship('User', foreign_keys=[checked_by], lazy='joined')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.product:
            d['product_name'] = self.product.name
            d['product_sku'] = self.product.sku
            d['product_stock'] = self.product.stock_qty
            prod_dict = self.product.to_dict()
            d['packaging_type'] = prod_dict.get('packaging_type', 'mika' if self.lot_size == 50 else 'vakum')
            d['unit_label'] = prod_dict.get('unit_label', f"Pack (Isi {self.lot_size} Pcs)")
        else:
            d['packaging_type'] = 'mika' if self.lot_size == 50 else 'vakum'
            d['unit_label'] = f"Pack (Isi {self.lot_size} Pcs)"

        # Alias packs for clarity
        d['planned_packs'] = self.planned_lots
        d['actual_packs'] = self.actual_lots
        d['total_pieces'] = ((self.actual_lots or 0) * (self.lot_size or 25)) + (self.loose_qty or 0)

        if self.creator:
            d['creator_name'] = self.creator.full_name
        if self.checker:
            d['checker_name'] = self.checker.full_name
        return d


class InventoryTransaction(Base, SerializableMixin):
    __tablename__ = 'inventory_transactions'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('production_batches.id'), nullable=True)
    type = Column(Enum('in', 'out', 'adjustment', name='inventory_transaction_type'), nullable=False)
    quantity = Column(Integer, nullable=False)
    reference_type = Column(Enum('production', 'order', 'manual', name='inventory_reference_type'), nullable=False)
    reference_id = Column(String(36), nullable=True)
    channel = Column(String(50), nullable=True)  # 'web', 'shopee', 'tiktok', 'po_b2b', 'offline', 'waste'
    stock_pool = Column(String(20), default='offline', nullable=True)  # 'offline', 'online', 'both'
    notes = Column(String(255), nullable=True)
    created_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    product = relationship('Product', lazy='joined')
    batch = relationship('ProductionBatch', lazy='joined')
    creator = relationship('User', foreign_keys=[created_by], lazy='joined')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.product:
            d['product_name'] = self.product.name
            d['product_sku'] = self.product.sku
        if self.batch:
            d['batch_code'] = self.batch.batch_code
        if self.creator:
            d['creator_name'] = self.creator.full_name
        d['stock_pool'] = self.stock_pool or 'offline'
        return d


class RawMaterial(Base, SerializableMixin):
    __tablename__ = 'raw_materials'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    category = Column(
        Enum('daging', 'kulit', 'tepung', 'minyak_bumbu', 'saos', 'topping', 'lainnya', name='raw_material_category'),
        default='lainnya',
        nullable=False
    )
    unit = Column(String(20), nullable=False)  # 'kg', 'karung', 'liter', 'botol', 'dus', 'pack'
    stock_qty = Column(Float, default=0.0, nullable=False)
    min_buffer = Column(Float, default=0.0, nullable=False)
    safe_target = Column(Float, default=0.0, nullable=False)
    cost_per_unit = Column(Float, default=0.0, nullable=False)
    storage_location = Column(String(100), nullable=True)  # e.g. 'Freezer Daging', 'Gudang Kering', 'Chiller'
    notes = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    transactions = relationship('RawMaterialTransaction', back_populates='material', cascade='all, delete-orphan', lazy='dynamic')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        stock = self.stock_qty or 0.0
        min_buf = self.min_buffer or 0.0
        safe = self.safe_target or (min_buf * 2.0 if min_buf > 0 else 100.0)

        if stock <= min_buf:
            d['buffer_status'] = 'critical'
            d['buffer_label'] = f'Kritis (≤ {min_buf} {self.unit})'
        elif stock <= (min_buf * 1.5):
            d['buffer_status'] = 'warning'
            d['buffer_label'] = f'Mendekati Batas (≤ {min_buf * 1.5:.1f} {self.unit})'
        else:
            d['buffer_status'] = 'safe'
            d['buffer_label'] = f'Aman (> {min_buf * 1.5:.1f} {self.unit})'

        # Kesiapan persentase terhadap target aman
        d['buffer_percent'] = min(100, int((stock / safe * 100))) if safe > 0 else 100

        # Backward-compatible aliases for UI components
        d['current_stock'] = stock
        d['minimum_stock'] = min_buf
        d['safety_stock'] = safe
        return d


class RawMaterialTransaction(Base, SerializableMixin):
    __tablename__ = 'raw_material_transactions'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    material_id = Column(String(36), ForeignKey('raw_materials.id'), nullable=False)
    type = Column(Enum('in', 'out', 'adjustment', name='raw_material_tx_type'), nullable=False)
    quantity = Column(Float, nullable=False)
    previous_stock = Column(Float, nullable=True)  # Stock before transaction
    new_stock = Column(Float, nullable=True)  # Stock after transaction
    reference_type = Column(
        Enum('purchase', 'production_usage', 'waste', 'manual', name='raw_material_ref_type'),
        default='manual',
        nullable=False
    )
    reference_id = Column(String(64), nullable=True)
    batch_gilingan = Column(Integer, nullable=True)
    notes = Column(String(255), nullable=True)
    created_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    material = relationship('RawMaterial', back_populates='transactions', lazy='joined')
    creator = relationship('User', foreign_keys=[created_by], lazy='joined')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.material:
            d['material_name'] = self.material.name
            d['material_unit'] = self.material.unit
            d['material_category'] = self.material.category
        if self.creator:
            d['creator_name'] = self.creator.full_name
        return d


class DailyProductionPlan(Base, SerializableMixin):
    __tablename__ = 'daily_production_plans'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_date = Column(Date, unique=True, nullable=False)
    day_of_week = Column(String(20), nullable=False)  # 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'

    # Target Finished Goods (Packs)
    target_mika = Column(Integer, default=350, nullable=False)   # 50 pcs/pack
    target_vakum = Column(Integer, default=100, nullable=False)  # 25 pcs/pack

    # Stock Pool Allocations (Online & Offline)
    target_online = Column(Integer, default=180, nullable=False)
    target_offline = Column(Integer, default=270, nullable=False)

    # Conversion to Raw Dough Gilingan (Produksi 1)
    # 350 mika ≈ 30 gilingan; 100 vakum ≈ 6 gilingan; Total = 36 gilingan
    gilingan_mika = Column(Float, default=30.0, nullable=False)
    gilingan_vakum = Column(Float, default=6.0, nullable=False)
    total_gilingan = Column(Float, default=36.0, nullable=False)

    status = Column(
        Enum('draft', 'scheduled', 'in_progress', 'completed', name='daily_plan_status'),
        default='scheduled',
        nullable=False
    )
    notes = Column(String(500), nullable=True)
    batches_generated = Column(Boolean, default=False, nullable=False)

    created_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    creator = relationship('User', foreign_keys=[created_by], lazy='joined')
    batches = relationship('ProductionBatch', backref='daily_plan', lazy='dynamic', foreign_keys='ProductionBatch.daily_plan_id')
    targets = relationship('ProductionTarget', back_populates='plan', cascade='all, delete-orphan')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.plan_date:
            d['plan_date'] = self.plan_date.strftime('%Y-%m-%d')
        if self.creator:
            d['creator_name'] = self.creator.full_name
        d['total_target_packs'] = (self.target_mika or 0) + (self.target_vakum or 0)
        d['total_target_pieces'] = ((self.target_mika or 0) * 50) + ((self.target_vakum or 0) * 25)
        d['total_channel_demand'] = (self.target_online or 0) + (self.target_offline or 0)
        
        # Calculate generated batches
        gen_mika = sum(b.planned_lots for b in self.batches.filter_by(lot_size=50).all()) if object_session(self) is not None else 0
        gen_vakum = sum(b.planned_lots for b in self.batches.filter_by(lot_size=25).all()) if object_session(self) is not None else 0
        d['generated_mika'] = gen_mika
        d['generated_vakum'] = gen_vakum
        d['total_target_packs_generated'] = gen_mika + gen_vakum

        # Include targets if available
        if hasattr(self, 'targets') and self.targets:
            d['targets'] = [t.to_dict() for t in self.targets]
            if len(self.targets) > 0:
                d['total_target_packs'] = sum(t.target_quantity or 0 for t in self.targets)
                d['total_target_pieces'] = sum((t.target_quantity or 0) * (t.pack_size or 25) for t in self.targets)
        else:
            d['targets'] = []
        
        return d


class ProductionTarget(Base, SerializableMixin):
    __tablename__ = 'production_targets'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_id = Column(String(36), ForeignKey('daily_production_plans.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    target_quantity = Column(Integer, default=0, nullable=False)
    pack_size = Column(Integer, default=25, nullable=False)
    ingredients_needed = Column(String(5000), nullable=True)
    status = Column(String(20), default='pending')

    plan = relationship('DailyProductionPlan', back_populates='targets')
    product = relationship('Product', lazy='joined')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.product:
            d['product_name'] = self.product.name
            d['product_sku'] = self.product.sku
            d['unit_label'] = getattr(self.product, 'unit_label', f"Pack ({self.pack_size} pcs)")
        if self.ingredients_needed:
            try:
                d['ingredients_needed_parsed'] = json.loads(self.ingredients_needed)
            except Exception:
                d['ingredients_needed_parsed'] = {}
        return d


class ProductionRealization(Base, SerializableMixin):
    """
    Production realization logging - bertahap/gradual progress tracking.
    Mencatat realisasi produksi per hari per target, bisa bertahap (multiple entries).
    """
    __tablename__ = 'production_realizations'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    target_id = Column(String(36), ForeignKey('production_targets.id'), nullable=False)
    tanggal = Column(Date, nullable=False)
    batch_number = Column(Integer, default=1, nullable=False)  # Urutan batch dalam satu hari
    batch_code = Column(String(64), nullable=True)  # Kode batch opsional
    
    # Progress logging
    produced_qty = Column(Integer, default=0, nullable=False)
    notes = Column(String(500), nullable=True)
    
    # Status tracking
    status = Column(
        Enum('pending', 'in_progress', 'completed', 'overproduced', name='realization_status'),
        default='pending',
        nullable=False
    )
    
    created_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    
    # Relationships
    target = relationship('ProductionTarget', backref='realizations', lazy='joined')
    creator = relationship('User', foreign_keys=[created_by], lazy='joined')
    
    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.tanggal:
            d['tanggal'] = self.tanggal.strftime('%Y-%m-%d')
        if self.creator:
            d['creator_name'] = self.creator.full_name
        
        # Calculate progress relative to target
        if self.target and self.target.product:
            d['target_quantity'] = self.target.target_quantity
            d['product_name'] = self.target.product.name
            d['unit_label'] = getattr(self.target.product, 'unit_label', f"Pack ({self.target.pack_size} pcs)")
            d['batch_name'] = f"Batch {self.batch_number}"
        
        return d


class ProductionLot(Base, SerializableMixin):
    """
    Produksi 1 (P1) daily lot logging.
    Mencatat realisasi gilingan per hari vs target planning.
    1 lot = 1 gilingan = ±15 kg daging mentah.
    Dibuat oleh Ayu (Inventory Control) setelah produksi berlangsung.
    """
    __tablename__ = 'production_lots'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tanggal = Column(Date, nullable=False)
    target_gilingan = Column(Integer, default=36, nullable=False)
    actual_gilingan = Column(Integer, nullable=False)
    notes = Column(String(500), nullable=True)
    created_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    creator = relationship('User', foreign_keys=[created_by], lazy='joined')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.tanggal:
            d['tanggal'] = self.tanggal.strftime('%Y-%m-%d')
        if self.creator:
            d['creator_name'] = self.creator.full_name
        d['gap_gilingan'] = (self.actual_gilingan or 0) - (self.target_gilingan or 36)
        d['achievement_percent'] = (
            min(100, int(((self.actual_gilingan or 0) / (self.target_gilingan or 36)) * 100))
            if (self.target_gilingan or 0) > 0 else 100
        )
        d['status'] = 'achieved' if (self.actual_gilingan or 0) >= (self.target_gilingan or 36) else 'below_target'
        return d


class DailyStockCheck(Base, SerializableMixin):
    """
    Checklist digital harian Ayu — pengganti papan fisik/clipboard BC.
    Dicatat H-1 sebelum produksi atau pagi hari sebelum shift mulai.
    """
    __tablename__ = 'daily_stock_checks'

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tanggal = Column(Date, nullable=False)
    target_gilingan = Column(Integer, default=36, nullable=False)
    all_items_sufficient = Column(Boolean, default=False, nullable=False)
    shortage_count = Column(Integer, default=0, nullable=False)
    shortage_items = Column(String(1000), nullable=True)  # JSON list bahan kurang
    notes = Column(String(500), nullable=True)
    checked_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    checker = relationship('User', foreign_keys=[checked_by], lazy='joined')

    def to_dict(self, **kwargs):
        d = super().to_dict(**kwargs)
        if self.tanggal:
            d['tanggal'] = self.tanggal.strftime('%Y-%m-%d')
        if self.checker:
            d['checker_name'] = self.checker.full_name
        try:
            d['shortage_items_list'] = json.loads(self.shortage_items) if self.shortage_items else []
        except Exception:
            d['shortage_items_list'] = []
        return d
