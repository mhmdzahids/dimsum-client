"""Explicit development-only reset for disposable PostgreSQL data.
Never runs on import, never opens a SQLite file.
"""
import argparse
from sqlalchemy import delete
from app.core.config import Config
from app.core.db import Base, init_db, db_session

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-reset', action='store_true')
    args = parser.parse_args()
    if not args.confirm_reset or Config.ENV != 'development':
        raise SystemExit('Requires --confirm-reset and APP_ENV=development')
    init_db()
    # Preserve users, catalog, recipes, settings and vouchers.
    names = {'raw_material_transactions', 'production_lots', 'daily_stock_checks',
             'production_targets', 'inventory_transactions', 'order_items', 'payments',
             'orders', 'production_batches', 'daily_production_plans', 'chat_messages'}
    try:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in names:
                db_session.execute(delete(table))
        from app.modules.products.models import Product
        from app.modules.inventory.models import RawMaterial
        db_session.query(Product).update({'stock_qty': 0, 'stock_offline': 0, 'stock_online': 0})
        db_session.query(RawMaterial).update({'stock_qty': 0})
        db_session.commit()
        print('Disposable development stock reset')
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.remove()
