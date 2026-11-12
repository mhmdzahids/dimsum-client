"""Explicit development catalog seed; never creates an account."""
from app.core.db import db_session, init_db
from app.core.config import Config
from app.shared.utils import generate_uuid

def seed_products():
    if Config.ENV == 'production':
        raise RuntimeError('Demo data is prohibited in production')
    # Seed default products if empty
    from app.modules.products.models import Product
    product_count = db_session.query(Product).count()
    if product_count == 0:
        default_products = [
            Product(
                id=generate_uuid(),
                name='Dimsum Mini (1 Pax Isi 25 Pcs)',
                description='Dimsum ukuran mini dengan gramasi 18-20 gram, tersaji dalam dua pilihan yaitu per-pax 25 pcs, dan per-mika 150 pcs, cocok untuk acara besar/dijual kembali.',
                weight='18-20 Gram/Pcs',
                category='Dimsum Mini',
                price=25000.00,
                sku='DIMSUM-MINI-PAX-25',
                stock_qty=100,
                is_active=True
            ),
            Product(
                id=generate_uuid(),
                name='Dimsum Mini (1 Mika Isi 150 Pcs)',
                description='Dimsum ukuran mini dengan gramasi 18-20 gram, tersaji dalam dua pilihan yaitu per-pax 25 pcs, dan per-mika 150 pcs, cocok untuk acara besar/dijual kembali.',
                weight='18-20 Gram/Pcs',
                category='Dimsum Mini',
                price=120000.00,
                sku='DIMSUM-MINI-MIKA-150',
                stock_qty=100,
                is_active=True
            ),
            Product(
                id=generate_uuid(),
                name='Dimsum Jumbo (1 Mika Isi 50 Pcs)',
                description='Dimsum ukuran jumbo dengan gramasi 34-36 gram, berisi 50 pcs cocok untuk acara besar/dijual kembali.',
                weight='34-36 Gram/Pcs',
                category='Dimsum Jumbo',
                price=80000.00,
                sku='DIMSUM-JUMBO-MIKA-50',
                stock_qty=100,
                is_active=True
            ),
            Product(
                id=generate_uuid(),
                name='Dimsum Vakum (1 Pax isi 25 Pcs)',
                description='Dimsum kemasan vakum higienis dan beku, siap kukus kapan saja.',
                weight='20-22 Gram/Pcs',
                category='Dimsum Vakum',
                price=20000.00,
                sku='DIMSUM-VAKUM-25',
                stock_qty=100,
                is_active=True
            )
        ]
        db_session.add_all(default_products)
        db_session.commit()

    # Seed default vouchers if empty
    from app.modules.vouchers.models import Voucher
    voucher_count = db_session.query(Voucher).count()
    if voucher_count == 0:
        default_vouchers = [
            Voucher(
                id=generate_uuid(),
                code='DIMSUM10',
                discount_type='fixed',
                discount_value=10000.0,
                min_spend=20000.0,
                is_active=True
            ),
            Voucher(
                id=generate_uuid(),
                code='PROMOHEMAT',
                discount_type='fixed',
                discount_value=5000.0,
                min_spend=15000.0,
                is_active=True
            ),
            Voucher(
                id=generate_uuid(),
                code='DIMSUMMERDEKA',
                discount_type='fixed',
                discount_value=5000.0,
                min_spend=15000.0,
                is_active=True
            ),
        ]
        for v in default_vouchers:
            db_session.add(v)
        db_session.commit()

if __name__ == '__main__':
    init_db()
    try:
        seed_products()
    finally:
        db_session.remove()
