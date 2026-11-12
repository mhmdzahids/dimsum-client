import pytest
from app.modules.products.models import Product
from app.modules.inventory.models import InventoryTransaction
from app.shared.utils import generate_uuid, utc_now
from app.core.db import db_session

@pytest.fixture
def dual_pool_product(db):
    uid = generate_uuid()[:8]
    product = Product(
        id=generate_uuid(),
        name=f'Dimsum Dual Pool {uid}',
        sku=f'DUAL-{uid}',
        price=25000.0,
        stock_qty=100,
        stock_offline=60,
        stock_online=40,
        min_buffer_stock=70,
        category='Dimsum Ayam',
        is_active=True
    )
    db.add(product)
    db.commit()
    return product

def test_stock_out_channel_pool_isolation(client, inventory_headers, dual_pool_product, db):
    prod_id = str(dual_pool_product.id)

    # 1. Deduct 15 packs via Shopee (Online Pool)
    res = client.post('/api/inventory/stock-out', json={
        'product_id': prod_id,
        'quantity': 15,
        'channel': 'shopee',
        'notes': 'Pesanan flash sale Shopee'
    }, headers=inventory_headers)

    assert res.status_code == 200
    data = res.json()['data']
    assert data['stock_online'] == 25
    assert data['stock_offline'] == 60
    assert data['stock_remaining'] == 85
    assert data['stock_pool'] == 'online'

    # 2. Deduct 20 packs via PO B2B (Offline Pool)
    res2 = client.post('/api/inventory/stock-out', json={
        'product_id': prod_id,
        'quantity': 20,
        'channel': 'po_b2b',
        'notes': 'PO Katering MBG'
    }, headers=inventory_headers)

    assert res2.status_code == 200
    data2 = res2.json()['data']
    assert data2['stock_online'] == 25
    assert data2['stock_offline'] == 40
    assert data2['stock_remaining'] == 65
    assert data2['stock_pool'] == 'offline'

def test_online_pool_quota_exhaustion_protection(client, inventory_headers, dual_pool_product, db):
    prod_id = str(dual_pool_product.id)
    # stock_online is 40, stock_offline is 60 (total 100).
    # Requesting 45 for TikTok must fail because quota online is only 40!
    res = client.post('/api/inventory/stock-out', json={
        'product_id': prod_id,
        'quantity': 45,
        'channel': 'tiktok',
        'notes': 'TikTok Live surge'
    }, headers=inventory_headers)

    assert res.status_code == 400
    err_msg = res.json()['error']
    assert 'Kuota stok online (TIKTOK) tidak mencukupi' in err_msg
    assert 'Silakan lakukan transfer kuota dari stok offline' in err_msg

    # Verify stock remained untouched
    p = db.get(Product, prod_id)
    assert p.stock_online == 40
    assert p.stock_offline == 60

def test_rebalance_stock_pool_endpoint(client, inventory_headers, dual_pool_product, db):
    prod_id = str(dual_pool_product.id)

    # Transfer 20 packs from offline to online
    res = client.post('/api/inventory/stock-rebalance', json={
        'product_id': prod_id,
        'from_pool': 'offline',
        'to_pool': 'online',
        'quantity': 20,
        'reason': 'Persiapan flash sale TikTok'
    }, headers=inventory_headers)

    assert res.status_code == 200
    data = res.json()['data']
    assert data['stock_offline'] == 40
    assert data['stock_online'] == 60
    assert data['stock_remaining'] == 100

    # Verify audit transaction created
    tx = db.query(InventoryTransaction).filter(
        InventoryTransaction.product_id == prod_id,
        InventoryTransaction.type == 'adjustment'
    ).first()
    assert tx is not None
    assert tx.stock_pool == 'online'
    assert 'Rebalance: Transfer 20 pack dari pool OFFLINE ke ONLINE' in tx.notes

    # Now TikTok stock out of 50 packs should succeed!
    res2 = client.post('/api/inventory/stock-out', json={
        'product_id': prod_id,
        'quantity': 50,
        'channel': 'tiktok',
        'notes': 'TikTok Live surge after rebalance'
    }, headers=inventory_headers)

    assert res2.status_code == 200
    assert res2.json()['data']['stock_online'] == 10
    assert res2.json()['data']['stock_offline'] == 40

def test_rebalance_validation_errors(client, inventory_headers, dual_pool_product):
    prod_id = str(dual_pool_product.id)

    # Same pool error
    res = client.post('/api/inventory/stock-rebalance', json={
        'product_id': prod_id,
        'from_pool': 'offline',
        'to_pool': 'offline',
        'quantity': 5
    }, headers=inventory_headers)
    assert res.status_code == 400

    # Insufficient source quota
    res2 = client.post('/api/inventory/stock-rebalance', json={
        'product_id': prod_id,
        'from_pool': 'online',
        'to_pool': 'offline',
        'quantity': 999
    }, headers=inventory_headers)
    assert res2.status_code == 400
    assert 'tidak mencukupi' in res2.json()['error']
