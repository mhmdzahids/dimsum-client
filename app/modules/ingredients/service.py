from sqlalchemy.orm import Session
from app.modules.ingredients.models import Ingredient, ProductIngredient
from app.modules.products.models import Product
from app.shared.utils import generate_uuid, utc_now
from typing import List, Dict, Optional
import json


class IngredientService:
    """Service untuk manage ingredients dan recipes"""

    @staticmethod
    def get_all_ingredients(db: Session) -> List[Ingredient]:
        """Get all ingredients"""
        return db.query(Ingredient).order_by(Ingredient.name).all()

    @staticmethod
    def get_ingredient_by_id(db: Session, ingredient_id: str) -> Optional[Ingredient]:
        """Get ingredient by ID"""
        return db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()

    @staticmethod
    def create_ingredient(db: Session, name: str, unit: str, current_stock: float = 0.0, 
                         min_buffer_stock: float = 10.0, supplier_id: Optional[str] = None) -> Ingredient:
        """Create new ingredient"""
        ingredient = Ingredient(
            id=generate_uuid(),
            name=name,
            unit=unit,
            current_stock=current_stock,
            min_buffer_stock=min_buffer_stock,
            supplier_id=supplier_id,
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(ingredient)
        db.commit()
        db.refresh(ingredient)
        return ingredient

    @staticmethod
    def update_ingredient(db: Session, ingredient_id: str, **kwargs) -> Optional[Ingredient]:
        """Update ingredient"""
        ingredient = IngredientService.get_ingredient_by_id(db, ingredient_id)
        if not ingredient:
            return None
        
        allowed_fields = ['name', 'unit', 'current_stock', 'min_buffer_stock', 'supplier_id']
        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(ingredient, key, value)
        
        ingredient.updated_at = utc_now()
        db.commit()
        db.refresh(ingredient)
        return ingredient

    @staticmethod
    def delete_ingredient(db: Session, ingredient_id: str) -> bool:
        """Delete ingredient (will cascade delete recipes)"""
        ingredient = IngredientService.get_ingredient_by_id(db, ingredient_id)
        if not ingredient:
            return False
        
        db.delete(ingredient)
        db.commit()
        return True

    @staticmethod
    def get_product_recipe(db: Session, product_id: str) -> List[ProductIngredient]:
        """Get recipe (ingredients) for a product"""
        return db.query(ProductIngredient).filter(
            ProductIngredient.product_id == product_id
        ).all()

    @staticmethod
    def add_ingredient_to_product(db: Session, product_id: str, ingredient_id: str, 
                                 amount_per_pack: float = 0.0, unit_measure: str = 'pcs', 
                                 notes: Optional[str] = None) -> ProductIngredient:
        """Add ingredient to product recipe"""
        # Check if recipe already exists
        existing = db.query(ProductIngredient).filter(
            ProductIngredient.product_id == product_id,
            ProductIngredient.ingredient_id == ingredient_id
        ).first()
        
        if existing:
            # Update existing recipe
            existing.amount_per_pack = amount_per_pack
            existing.unit_measure = unit_measure
            existing.notes = notes
            existing.updated_at = utc_now()
            db.commit()
            db.refresh(existing)
            return existing
        
        # Create new recipe
        recipe = ProductIngredient(
            id=generate_uuid(),
            product_id=product_id,
            ingredient_id=ingredient_id,
            amount_per_pack=amount_per_pack,
            unit_measure=unit_measure,
            notes=notes,
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
        return recipe

    @staticmethod
    def remove_ingredient_from_product(db: Session, product_id: str, ingredient_id: str) -> bool:
        """Remove ingredient from product recipe"""
        recipe = db.query(ProductIngredient).filter(
            ProductIngredient.product_id == product_id,
            ProductIngredient.ingredient_id == ingredient_id
        ).first()
        
        if not recipe:
            return False
        
        db.delete(recipe)
        db.commit()
        return True

    @staticmethod
    def calculate_ingredients_needed(db: Session, product_id: str, quantity: int) -> Dict:
        """
        Calculate ingredients needed for producing X quantity of product
        Returns: {ingredient_id: {name, amount_needed, unit, current_stock, is_sufficient}}
        """
        recipe = IngredientService.get_product_recipe(db, product_id)
        result = {}
        
        for item in recipe:
            ingredient = item.ingredient
            amount_needed = float(item.amount_per_pack) * quantity
            current_stock = float(ingredient.current_stock) if ingredient.current_stock else 0.0
            
            result[ingredient.id] = {
                'ingredient_id': ingredient.id,
                'name': ingredient.name,
                'amount_needed': amount_needed,
                'unit': item.unit_measure,
                'current_stock': current_stock,
                'is_sufficient': current_stock >= amount_needed,
                'shortage': max(0, amount_needed - current_stock)
            }
        
        return result

    @staticmethod
    def calculate_ingredients_for_multiple_products(db: Session, product_targets: List[Dict]) -> Dict:
        """
        Calculate aggregated ingredients needed for multiple products
        product_targets: [{'product_id': '...', 'quantity': 100}, ...]
        Returns: {ingredient_id: {name, total_needed, unit, current_stock, is_sufficient, used_by: [products]}}
        """
        aggregated = {}
        
        for target in product_targets:
            product_id = target['product_id']
            quantity = target['quantity']
            
            # Get product info
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                continue
            
            # Calculate ingredients for this product
            ingredients_needed = IngredientService.calculate_ingredients_needed(db, product_id, quantity)
            
            # Aggregate
            for ing_id, data in ingredients_needed.items():
                if ing_id not in aggregated:
                    aggregated[ing_id] = {
                        'ingredient_id': ing_id,
                        'name': data['name'],
                        'total_needed': 0.0,
                        'unit': data['unit'],
                        'current_stock': data['current_stock'],
                        'used_by': []
                    }
                
                aggregated[ing_id]['total_needed'] += data['amount_needed']
                aggregated[ing_id]['used_by'].append({
                    'product_id': product_id,
                    'product_name': product.name,
                    'quantity': quantity,
                    'amount_needed': data['amount_needed']
                })
        
        # Calculate sufficiency
        for ing_id, data in aggregated.items():
            data['is_sufficient'] = data['current_stock'] >= data['total_needed']
            data['shortage'] = max(0, data['total_needed'] - data['current_stock'])
        
        return aggregated

    @staticmethod
    def check_insufficient_ingredients(db: Session, product_targets: List[Dict]) -> List[Dict]:
        """
        Check which ingredients are insufficient (kurang)
        Returns list of insufficient ingredients with shortage details
        """
        all_ingredients = IngredientService.calculate_ingredients_for_multiple_products(db, product_targets)
        insufficient = []
        
        for ing_id, data in all_ingredients.items():
            if not data['is_sufficient']:
                insufficient.append({
                    'ingredient_id': ing_id,
                    'name': data['name'],
                    'total_needed': data['total_needed'],
                    'current_stock': data['current_stock'],
                    'shortage': data['shortage'],
                    'unit': data['unit'],
                    'used_by': data['used_by']
                })
        
        return insufficient

    @staticmethod
    def update_ingredient_stock(db: Session, ingredient_id: str, quantity: float, operation: str = 'set') -> Optional[Ingredient]:
        """
        Update ingredient stock
        operation: 'set' (replace), 'add' (increase), 'subtract' (decrease)
        """
        ingredient = IngredientService.get_ingredient_by_id(db, ingredient_id)
        if not ingredient:
            return None
        
        if operation == 'set':
            ingredient.current_stock = quantity
        elif operation == 'add':
            ingredient.current_stock = float(ingredient.current_stock or 0) + quantity
        elif operation == 'subtract':
            ingredient.current_stock = float(ingredient.current_stock or 0) - quantity
        
        ingredient.updated_at = utc_now()
        db.commit()
        db.refresh(ingredient)
        return ingredient
