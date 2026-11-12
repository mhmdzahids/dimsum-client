"""Explicit development catalog seed; never creates an account."""
from app.core.db import db_session, init_db
from app.core.config import Config
from app.shared.utils import generate_uuid

def seed_products():
    if Config.ENV == 'production':
        raise RuntimeError('Demo data is prohibited in production')
    
    from app.modules.products.models import Product
    # Clean up existing products to keep strictly 2 products: Dimsum Mika & Dimsum Vakum
    db_session.query(Product).delete()
    
    default_products = [
        Product(
            id=generate_uuid(),
            name='Dimsum Mika (50 Pcs)',
            description='Dimsum premium olahan daging ayam asli dengan topping lezat, disajikan dalam kemasan mika higienis isi 50 pcs. Cocok untuk acara keluarga, catering, atau reseller.',
            weight='50 Pcs / Mika',
            category='Dimsum Mika',
            price=45000.00,
            original_price=50000.00,
            sku='FG_MIKA',
            unit='mika',
            pack_size=50,
            unit_label='Mika (Isi 50 Pcs)',
            stock_qty=50,
            min_buffer_stock=20,
            is_active=True
        ),
        Product(
            id=generate_uuid(),
            name='Dimsum Vakum (25 Pcs)',
            description='Dimsum kemasan beku kedap udara (vakum) isi 25 pcs lengkap dengan saos cocolan khas. Menjaga kesegaran dan cita rasa maksimal, tahan lama di freezer.',
            weight='25 Pcs / Pack',
            category='Dimsum Vakum',
            price=50000.00,
            original_price=55000.00,
            sku='FG_VAKUM',
            unit='vakum',
            pack_size=25,
            unit_label='Pack Vakum (Isi 25 Pcs)',
            stock_qty=35,
            min_buffer_stock=15,
            is_active=True
        )
    ]
    db_session.add_all(default_products)
    db_session.commit()
    print(f"Berhasil seeding {len(default_products)} produk buyer: Dimsum Mika (Stok 50) & Dimsum Vakum (Stok 35).")

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
                min_spend=40000.0,
                is_active=True
            ),
            Voucher(
                id=generate_uuid(),
                code='PROMOHEMAT',
                discount_type='fixed',
                discount_value=5000.0,
                min_spend=30000.0,
                is_active=True
            ),
            Voucher(
                id=generate_uuid(),
                code='DIMSUMENAK',
                discount_type='percentage',
                discount_value=10.0,
                min_spend=45000.0,
                is_active=True
            ),
        ]
        for v in default_vouchers:
            db_session.add(v)
        db_session.commit()
        print(f"Berhasil seeding {len(default_vouchers)} voucher diskon.")

if __name__ == '__main__':
    init_db()
    try:
        seed_products()
    finally:
        db_session.remove()
