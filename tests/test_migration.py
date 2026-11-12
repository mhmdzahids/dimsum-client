import os
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, text, select, MetaData, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from app.core.db import Base, load_models
from app.modules.auth.models import User
from app.modules.products.models import Product
from app.modules.orders.models import Order, OrderItem
from scripts.transfer_sqlite import transfer


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requires PostgreSQL')
@pytest.mark.parametrize('case', ['valid', 'invalid_fk', 'demo_admin'])
def test_transfer_preserves_values_and_refuses_nonempty_target(tmp_path, case):
    invalid_fk = case == "invalid_fk"
    from app.modules.auth.service import AuthService
    load_models()
    source_path = tmp_path / 'source.db'
    source = create_engine(f'sqlite:///{source_path}')
    legacy = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in {'revoked_tokens', 'rate_limit_buckets'}:
            table.to_metadata(legacy)
    legacy.tables['users']._columns.remove(legacy.tables['users'].c.auth_version)
    legacy.create_all(source)
    user_id, product_id, order_id = (str(uuid4()) for _ in range(3))
    with source.begin() as conn:
        conn.execute(legacy.tables['users'].insert(), dict(id=user_id, email='migration@example.test',
                     password_hash=AuthService.hash_password('password123') if case == 'demo_admin' else 'preserved-hash',
                     full_name='Uji migrasi', role='admin' if case == 'demo_admin' else 'customer',
                     is_registered=True))
        conn.execute(Product.__table__.insert(), dict(id=product_id, name='Produk migrasi',
                     sku='MIGRATE-1', price=Decimal('12345.67'), stock_qty=10,
                     stock_offline=6, stock_online=4, is_active=True))
        conn.execute(Order.__table__.insert(), dict(id=order_id, customer_id=user_id,
                     total_amount=Decimal('12345.67'), status='paid', access_token='preserved-token'))
        conn.execute(OrderItem.__table__.insert(), dict(id=str(uuid4()), order_id=order_id,
                     product_id=str(uuid4()) if invalid_fk else product_id, quantity=1, unit_price=Decimal('12345.67')))
    source.dispose()
    original = source_path.read_bytes()
    url = make_url(os.environ['TEST_DATABASE_URL']).set(drivername='postgresql+psycopg')
    admin = create_engine(url)
    schema = 'migration_' + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    target = url.update_query_dict({'options': f'-csearch_path={schema}'})
    try:
        if invalid_fk or case == 'demo_admin':
            with pytest.raises(IntegrityError if invalid_fk else ValueError):
                transfer(source_path, target)
            engine = create_engine(target)
            with engine.connect() as conn:
                assert inspect(conn).get_table_names() == []
            engine.dispose()
            assert source_path.read_bytes() == original
            return
        counts = transfer(source_path, target)
        assert counts['users'] == counts['products'] == counts['orders'] == counts['order_items'] == 1
        with pytest.raises(ValueError, match='not empty'):
            transfer(source_path, target)
        assert source_path.read_bytes() == original
        engine = create_engine(target)
        with engine.connect() as conn:
            assert conn.execute(select(User.__table__.c.password_hash)).scalar_one() == 'preserved-hash'
        engine.dispose()
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
