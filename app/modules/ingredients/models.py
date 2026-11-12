from app.core.db import Base, db_session
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship


class Ingredient(Base):
    """Master bahan baku (ingredients)"""
    __tablename__ = 'ingredients'

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    unit = Column(String(20), nullable=False)  # kg, pcs, liter, dus, etc.
    current_stock = Column(Numeric(10, 2), default=0.00)
    min_buffer_stock = Column(Numeric(10, 2), default=10.00)
    supplier_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Relationships
    product_ingredients = relationship('ProductIngredient', back_populates='ingredient', cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.id:
            from uuid import uuid4
            self.id = str(uuid4())
        from datetime import datetime
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'unit': self.unit,
            'current_stock': float(self.current_stock) if self.current_stock else 0.0,
            'min_buffer_stock': float(self.min_buffer_stock) if self.min_buffer_stock else 10.0,
            'supplier_id': self.supplier_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ProductIngredient(Base):
    """Recipe - relasi antara product dan bahan baku"""
    __tablename__ = 'product_ingredients'

    id = Column(String(36), primary_key=True)
    product_id = Column(String(36), ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    ingredient_id = Column(String(36), ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False)
    amount_per_pack = Column(Numeric(10, 3), nullable=False)  # ex: 0.5 kg tepung per pack
    unit_measure = Column(String(20), nullable=False)  # kg, pcs, etc.
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Relationships
    product = relationship('Product')
    ingredient = relationship('Ingredient', back_populates='product_ingredients')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.id:
            from uuid import uuid4
            self.id = str(uuid4())
        from datetime import datetime
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'ingredient_id': self.ingredient_id,
            'ingredient_name': self.ingredient.name if self.ingredient else None,
            'amount_per_pack': float(self.amount_per_pack) if self.amount_per_pack else 0.0,
            'unit_measure': self.unit_measure,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
