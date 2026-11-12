import pytest
from app.modules.products.models import Product
from app.modules.inventory.models import ProductionBatch, InventoryTransaction
from app.core.db import db_session
from app.shared.utils import generate_uuid

@pytest.fixture
def sample_product(db):
    unique_suffix = generate_uuid()[:8]
    product = Product(
        id=generate_uuid(),
        name=f'Dimsum Vakum (1 Pax isi 25 Pcs) {unique_suffix}',
        sku=f'DIM-VAKUM-{unique_suffix}',
        price=20000.0,
        stock_qty=50,
        category='Dimsum Vakum',
        is_active=True
    )
    db.add(product)
    db.commit()
    return product

@pytest.fixture
def mika_product(db):
    unique_suffix = generate_uuid()[:8]
    product = Product(
        id=generate_uuid(),
        name=f'Dimsum Mika (1 Mika Isi 50 Pcs) {unique_suffix}',
        sku=f'DIMSUM-MIKA-50-{unique_suffix}',
        price=80000.0,
        stock_qty=100,
        category='Dimsum Mika',
        unit='mika',
        pack_size=50,
        is_active=True
    )
    db.add(product)
    db.commit()
    return product

def test_create_production_plan_by_inventory_control(client, inventory_headers, sample_product):
    # 1. Ayu / Lala create a production plan for 4 packs of Vakum
    payload = {
        'product_id': sample_product.id,
        'planned_lots': 4,
        'notes': 'Produksi harian reguler pagi'
    }
    res = client.post('/api/inventory/production/plan', json=payload, headers=inventory_headers)
    assert res.status_code == 201
    data = res.json()['data']
    
    assert data['planned_lots'] == 4
    assert data['lot_size'] == 25
    assert data['status'] == 'planned'
    assert data['produced_qty'] == 0
    assert data['remaining_qty'] == 0
    assert data['batch_code'].startswith(sample_product.sku.upper())

    # Physical product stock must remain unchanged at 50 (not yet in freezer)
    reloaded = db_session.get(Product, sample_product.id)
    assert reloaded.stock_qty == 50

def test_create_mika_plan_dynamic_pack_size_50(client, inventory_headers, mika_product):
    # Dimsum Mika should automatically resolve to pack_size = 50
    payload = {
        'product_id': mika_product.id,
        'planned_lots': 350,
        'notes': 'Target harian 350 Mika'
    }
    res = client.post('/api/inventory/production/plan', json=payload, headers=inventory_headers)
    assert res.status_code == 201
    data = res.json()['data']
    assert data['lot_size'] == 50
    assert data['packaging_type'] == 'mika'
    assert data['planned_lots'] == 350

def test_staff_and_customer_forbidden_from_planning(client, staff_headers, customer_headers, sample_product):
    payload = {'product_id': sample_product.id, 'planned_lots': 2}
    
    # Staff cannot plan production
    res_staff = client.post('/api/inventory/production/plan', json=payload, headers=staff_headers)
    assert res_staff.status_code == 403

    # Customer cannot plan production
    res_cust = client.post('/api/inventory/production/plan', json=payload, headers=customer_headers)
    assert res_cust.status_code == 403

def test_confirm_production_actual_by_checker(client, inventory_headers, checker_headers, sample_product):
    # 1. Plan 4 packs
    res_plan = client.post('/api/inventory/production/plan', json={
        'product_id': sample_product.id,
        'planned_lots': 4
    }, headers=inventory_headers)
    assert res_plan.status_code == 201
    batch_id = res_plan.json()['data']['id']

    initial_stock = sample_product.stock_qty

    # 2. Om Yosi (Checker) confirms actual output: exactly 4 packs completed
    confirm_payload = {
        'actual_lots': 4,
        'loose_qty': 0
    }
    res_confirm = client.post(f'/api/inventory/production/{batch_id}/confirm', json=confirm_payload, headers=checker_headers)
    assert res_confirm.status_code == 200
    batch_data = res_confirm.json()['data']

    assert batch_data['status'] == 'completed'
    assert batch_data['actual_lots'] == 4
    assert batch_data['produced_qty'] == 4  # 4 packs
    assert batch_data['remaining_qty'] == 4
    assert batch_data['total_pieces'] == 100  # 4 x 25

    # 3. Product stock in freezer must now atomically increase by 4 packs (1:1 with POS)
    reloaded_product = db_session.get(Product, sample_product.id)
    assert reloaded_product.stock_qty == initial_stock + 4

    # 4. Inventory transaction 'in' recorded
    txns = db_session.query(InventoryTransaction).filter_by(batch_id=batch_id).all()
    assert len(txns) == 1
    assert txns[0].type == 'in'
    assert txns[0].quantity == 4
    assert txns[0].reference_type == 'production'

def test_confirm_production_with_loose_qty(client, inventory_headers, checker_headers, sample_product):
    # Plan 3 packs
    res_plan = client.post('/api/inventory/production/plan', json={
        'product_id': sample_product.id,
        'planned_lots': 3
    }, headers=inventory_headers)
    batch_id = res_plan.json()['data']['id']
    initial_stock = sample_product.stock_qty

    # Checker confirms: 2 full packs + 7 loose pieces
    confirm_payload = {
        'actual_lots': 2,
        'loose_qty': 7
    }
    res_confirm = client.post(f'/api/inventory/production/{batch_id}/confirm', json=confirm_payload, headers=checker_headers)
    assert res_confirm.status_code == 200
    batch_data = res_confirm.json()['data']

    # 2 finished packs added to POS stock
    assert batch_data['produced_qty'] == 2
    assert batch_data['loose_qty'] == 7
    assert batch_data['total_pieces'] == (2 * 25) + 7
    reloaded_product = db_session.get(Product, sample_product.id)
    assert reloaded_product.stock_qty == initial_stock + 2

def test_get_lot_stickers_generation_for_mika(client, inventory_headers, checker_headers, staff_headers, mika_product):
    # Plan & confirm 2 Mika packs (50 pcs/mika)
    res_plan = client.post('/api/inventory/production/plan', json={
        'product_id': mika_product.id,
        'planned_lots': 2
    }, headers=inventory_headers)
    batch_id = res_plan.json()['data']['id']

    # Getting stickers before confirmation should fail with 400
    res_early_stickers = client.get(f'/api/inventory/batches/{batch_id}/stickers', headers=staff_headers)
    assert res_early_stickers.status_code == 400

    # Confirm 2 Mika + 15 loose pcs
    client.post(f'/api/inventory/production/{batch_id}/confirm', json={
        'actual_lots': 2,
        'loose_qty': 15
    }, headers=checker_headers)

    # Now fetch stickers
    res_stickers = client.get(f'/api/inventory/batches/{batch_id}/stickers', headers=staff_headers)
    assert res_stickers.status_code == 200
    stickers = res_stickers.json()['data']
    
    # 2 pack stickers + 1 loose sticker = 3 stickers
    assert len(stickers) == 3
    
    # First Mika sticker check
    st1 = stickers[0]
    assert st1['lot_number'] == 1
    assert st1['total_lots'] == 2
    assert st1['lot_size'] == 50
    assert st1['pack_type'] == 'MIKA'
    assert 'Chiller' in st1['storage_info']
    assert 'BATCH:' in st1['qr_payload']
    assert 'MIKA:1/2' in st1['qr_payload']
    assert 'QTY:50PCS' in st1['qr_payload']

    # Loose sticker check
    loose_st = stickers[2]
    assert loose_st['is_loose'] is True
    assert loose_st['lot_size'] == 15
    assert 'MIKA:LOOSE' in loose_st['qr_payload']

def test_cancel_production_plan(client, inventory_headers, checker_headers, sample_product):
    res_plan = client.post('/api/inventory/production/plan', json={
        'product_id': sample_product.id,
        'planned_lots': 2
    }, headers=inventory_headers)
    batch_id = res_plan.json()['data']['id']

    # Cancel plan
    res_cancel = client.post(f'/api/inventory/production/{batch_id}/cancel', json={
        'reason': 'Bahan baku ayam terlambat dari suplier Parung'
    }, headers=inventory_headers)
    assert res_cancel.status_code == 200
    assert res_cancel.json()['data']['status'] == 'cancelled'

    # Cannot confirm a cancelled batch
    res_confirm = client.post(f'/api/inventory/production/{batch_id}/confirm', json={
        'actual_lots': 2
    }, headers=checker_headers)
    assert res_confirm.status_code == 400

def test_lookup_batch_by_code_and_qr_payload(client, inventory_headers, staff_headers, sample_product):
    res_plan = client.post('/api/inventory/production/plan', json={
        'product_id': sample_product.id,
        'planned_lots': 3
    }, headers=inventory_headers)
    batch_data = res_plan.json()['data']
    batch_code = batch_data['batch_code']

    # 1. Direct code lookup
    res_lookup = client.get(f'/api/inventory/batches/code/{batch_code}', headers=staff_headers)
    assert res_lookup.status_code == 200
    assert res_lookup.json()['data']['batch_code'] == batch_code

    # 2. QR payload string lookup
    qr_payload = f"BATCH:{batch_code}|VAKUM:1/3|QTY:25PCS|SKU:{sample_product.sku}"
    res_qr_lookup = client.get(f'/api/inventory/batches/code/{qr_payload}', headers=staff_headers)
    assert res_qr_lookup.status_code == 200
    assert res_qr_lookup.json()['data']['batch_code'] == batch_code

    # 3. Not found
    res_404 = client.get('/api/inventory/batches/code/NONEXISTENT-CODE', headers=staff_headers)
    assert res_404.status_code == 404

def test_confirm_mika_loose_qty_exceeded_rejected(client, inventory_headers, checker_headers, mika_product):
    res_plan = client.post('/api/inventory/production/plan', json={
        'product_id': mika_product.id,
        'planned_lots': 2
    }, headers=inventory_headers)
    batch_id = res_plan.json()['data']['id']

    # Mika has lot_size=50. Loose qty 50 should fail (max is 49)
    res_confirm = client.post(f'/api/inventory/production/{batch_id}/confirm', json={
        'actual_lots': 2,
        'loose_qty': 50
    }, headers=checker_headers)
    assert res_confirm.status_code == 400
    assert 'Sisa eceran lepas maksimal 49 pcs' in res_confirm.json()['error']
