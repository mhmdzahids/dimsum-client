from app.core.db import db_session
from app.modules.products.models import Product

class ProductService:
    @staticmethod
    def get_all(only_active: bool = True):
        query = db_session.query(Product)
        if only_active:
            query = query.filter(Product.is_active.is_(True))
        return query.all()

    @staticmethod
    def get_by_id(product_id: str):
        return db_session.get(Product, product_id)

    @staticmethod
    def get_by_sku(sku: str):
        return db_session.query(Product).filter_by(sku=sku).first()

    @classmethod
    def create(cls, name: str, price: float, sku: str, category: str = None, is_active: bool = True, stock_qty: int = 0, min_buffer_stock: int = 70, unit: str = 'pack', pack_size: int = 25, unit_label: str = None):
        if cls.get_by_sku(sku):
            raise ValueError(f"Product with SKU '{sku}' already exists.")
        
        # Auto-generate unit_label if not provided
        if not unit_label:
            unit_label = f"{unit.title()} (Isi {pack_size} Pcs)"
            
        new_product = Product(
            name=name,
            price=price,
            sku=sku,
            category=category,
            is_active=is_active,
            stock_qty=0,
            min_buffer_stock=min_buffer_stock,
            unit=unit,
            pack_size=pack_size,
            unit_label=unit_label
        )
        db_session.add(new_product)
        db_session.commit()
        return new_product

    ALLOWED_UPDATE_FIELDS = {
        'name', 'description', 'weight', 'category', 'price', 'sku', 'image_url', 
        'is_active', 'is_discount', 'discount_percent', 'original_price', 'min_buffer_stock',
        'unit', 'pack_size', 'unit_label'
    }

    @classmethod
    def update(cls, product_id: str, **kwargs):
        import html
        product = cls.get_by_id(product_id)
        if not product:
            raise ValueError("Product not found")
            
        if 'sku' in kwargs and kwargs['sku'] != product.sku:
            if cls.get_by_sku(kwargs['sku']):
                raise ValueError(f"Product with SKU '{kwargs['sku']}' already exists.")

        # Handle discount logic if provided
        if 'is_discount' in kwargs:
            is_disc = bool(kwargs['is_discount'])
            product.is_discount = is_disc
            
            if is_disc:
                disc_pct = int(kwargs.get('discount_percent', product.discount_percent or 0))
                if disc_pct < 1 or disc_pct > 99:
                    raise ValueError("Persentase diskon harus antara 1% dan 99%")
                product.discount_percent = disc_pct
                
                orig_price = kwargs.get('original_price', product.original_price)
                if orig_price is not None:
                    orig_val = float(orig_price)
                    if orig_val <= 0:
                        raise ValueError("Harga awal harus lebih besar dari 0")
                    product.original_price = round(orig_val, 2)
                    # Automatically calculate active selling price based on discount
                    product.price = round(orig_val * (1.0 - (disc_pct / 100.0)), 2)
            else:
                # Disabling discount: restore price to original_price if available
                if product.original_price and float(product.original_price) > 0:
                    product.price = product.original_price
                product.discount_percent = 0
                product.original_price = None

        for key, value in kwargs.items():
            if key in ('is_discount', 'discount_percent', 'original_price'):
                continue  # Handled above
            if key in cls.ALLOWED_UPDATE_FIELDS and hasattr(product, key):
                if isinstance(value, str) and key in {'name', 'description', 'weight', 'category'}:
                    value = html.escape(value.strip(), quote=True)
                setattr(product, key, value)
                
        db_session.commit()
        return product
    @classmethod
    def save_image(cls, product_id: str, file):
        import os
        import uuid
        from app.core.config import Config
        
        product = cls.get_by_id(product_id)
        if not product:
            raise ValueError("Product not found")

        from pathlib import Path
        from app.shared.uploads import save_image
        products_upload_folder = str(Path(__file__).resolve().parents[2] / 'static' / 'uploads' / 'products')
        unique_filename = save_image(file, products_upload_folder)

        if product.image_url:
            old_filename = product.image_url.split('/')[-1]
            old_path = os.path.join(products_upload_folder, old_filename)
            if os.path.exists(old_path):
                os.remove(old_path)
        
        product.image_url = f"/static/uploads/products/{unique_filename}"
        db_session.commit()
        return product

    @classmethod
    def delete(cls, product_id: str):
        product = cls.get_by_id(product_id)
        if not product:
            raise ValueError("Product not found")
            
        db_session.delete(product)
        db_session.commit()
        return True
