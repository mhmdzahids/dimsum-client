import pytest
from datetime import datetime, timezone
from app.modules.products.models import Product
from app.modules.inventory.models import ProductionBatch, InventoryTransaction
from app.core.db import db_session
from app.shared.utils import generate_uuid, utc_now

@pytest.fixture
def product_with_batches(db, admin_headers):
    from app.modules.auth.models import User
    creator_id = db.query(User).filter_by(email="admin@dimsum.id").one().id
    uid = generate_uuid()[:8]
    product = Product(
        id=generate_uuid(),
        name=f'Dimsum Jumbo Test {uid}',
        sku=f'JUMBO-{uid}',
        price=30000.0,
        stock_qty=100,
        stock_offline=20,
        stock_online=80,
        min_buffer_stock=70,
        category='Dimsum Jumbo',
        is_active=True
    )
    db.add(product)
    db.commit()

    # Batch 1: completed 1 hour ago (oldest)
    b1 = ProductionBatch(
        id=generate_uuid(),
        product_id=product.id,
        batch_code=f'JUMBO-{uid}-20260921-01',
        lot_size=25,
        planned_lots=2,
        actual_lots=2,
        produced_qty=50,
        remaining_qty=50,
        status='completed',
        created_by=creator_id,
        completed_at=utc_now()
    )
    # Batch 2: completed recently (newer)
    b2 = ProductionBatch(
        id=generate_uuid(),
        product_id=product.id,
        batch_code=f'JUMBO-{uid}-20260921-02',
        lot_size=25,
        planned_lots=2,
        actual_lots=2,
        produced_qty=50,
        remaining_qty=50,
        status='completed',
        created_by=creator_id,
        completed_at=utc_now()
    )
    db.add_all([b1, b2])
    db.commit()

    return product, b1, b2

def test_stock_out_shopee_and_fifo_deduction(client, inventory_headers, product_with_batches, db):
    product, b1, b2 = product_with_batches
    prod_id = str(product.id)
    b1_id = str(b1.id)
    b2_id = str(b2.id)

    # Lala / Ayu deduct 75 pcs (3 lots) for Shopee marketplace dispatch
    payload = {
        'product_id': prod_id,
        'quantity': 75,
        'channel': 'shopee',
        'notes': 'Resi Shopee SPXID0928341'
    }
    res = client.post('/api/inventory/stock-out', json=payload, headers=inventory_headers)
    assert res.status_code == 200
    data = res.json()['data']

    assert data['quantity'] == 75
    assert data['channel'] == 'shopee'
    assert data['stock_remaining'] == 25  # 100 - 75 = 25

    # FIFO verification: Batch 1 should be completely exhausted (50 deducted, 0 left)
    reloaded_b1 = db_session.query(ProductionBatch).get(b1_id)
    assert reloaded_b1.remaining_qty == 0

    # Batch 2 should have 25 deducted, leaving 25 remaining
    reloaded_b2 = db_session.query(ProductionBatch).get(b2_id)
    assert reloaded_b2.remaining_qty == 25

    # Product stock in DB must match 25
    reloaded_prod = db_session.query(Product).get(prod_id)
    assert reloaded_prod.stock_qty == 25
    # Since stock (25) < min_buffer_stock (70), buffer_status must be 'critical'
    assert reloaded_prod.to_dict()['buffer_status'] == 'critical'

    # Check transactions created
    txns = db_session.query(InventoryTransaction).filter_by(product_id=prod_id, type='out').all()
    assert len(txns) == 2
    assert txns[0].channel == 'shopee'
    assert txns[1].channel == 'shopee'

def test_stock_out_by_lot_count(client, inventory_headers, product_with_batches, db):
    product, b1, b2 = product_with_batches

    # Deduct 1 lot (25 pcs) to TikTok Shop
    payload = {
        'product_id': product.id,
        'lots_count': 1,
        'channel': 'tiktok',
        'notes': 'TikTok Live Sale Batch 1'
    }
    res = client.post('/api/inventory/stock-out', json=payload, headers=inventory_headers)
    assert res.status_code == 200
    data = res.json()['data']

    assert data['quantity'] == 25
    assert data['channel'] == 'tiktok'
    assert data['stock_remaining'] == 75

def test_stock_out_insufficient_stock_fails(client, inventory_headers, product_with_batches):
    product, _, _ = product_with_batches

    # Request 200 pcs when only 100 pcs exist
    payload = {
        'product_id': product.id,
        'quantity': 200,
        'channel': 'po_b2b'
    }
    res = client.post('/api/inventory/stock-out', json=payload, headers=inventory_headers)
    assert res.status_code == 400
    assert 'Stok freezer tidak mencukupi' in res.json()['error']

def test_buffer_stock_alert_evaluation(db):
    uid = generate_uuid()[:6]
    p_safe = Product(
        id=generate_uuid(),
        name=f'Dimsum Safe {uid}',
        sku=f'SAFE-{uid}',
        price=20000,
        stock_qty=120,
        min_buffer_stock=70
    )
    p_warn = Product(
        id=generate_uuid(),
        name=f'Dimsum Warn {uid}',
        sku=f'WARN-{uid}',
        price=20000,
        stock_qty=85,
        min_buffer_stock=70
    )
    p_crit = Product(
        id=generate_uuid(),
        name=f'Dimsum Crit {uid}',
        sku=f'CRIT-{uid}',
        price=20000,
        stock_qty=30,
        min_buffer_stock=70
    )
    db.add_all([p_safe, p_warn, p_crit])
    db.commit()

    assert p_safe.to_dict()['buffer_status'] == 'safe'
    assert p_warn.to_dict()['buffer_status'] == 'warning'
    assert p_crit.to_dict()['buffer_status'] == 'critical'

def test_get_inventory_dashboard_summary(client, staff_headers):
    res = client.get('/api/inventory/dashboard/summary', headers=staff_headers)
    assert res.status_code == 200
    data = res.json()['data']

    assert 'total_stock_pcs' in data
    assert 'total_stock_lots' in data
    assert 'channel_distribution' in data
    assert 'today_production' in data
    assert 'critical_products' in data
    assert 'warning_products' in data

def test_role_permissions_for_stock_out(client, staff_headers, customer_headers, product_with_batches):
    product, _, _ = product_with_batches
    payload = {'product_id': product.id, 'quantity': 10, 'channel': 'offline'}

    # Kasir / Staff cannot perform manual channel stock out (Ayu/Lala or Admin only)
    res_staff = client.post('/api/inventory/stock-out', json=payload, headers=staff_headers)
    assert res_staff.status_code == 403

    # Customer cannot perform manual stock out
    res_cust = client.post('/api/inventory/stock-out', json=payload, headers=customer_headers)
    assert res_cust.status_code == 403
