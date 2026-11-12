import pytest
from app.core.db import db_session
from app.modules.inventory.models import RawMaterial, RawMaterialTransaction
from app.shared.utils import generate_uuid

def test_get_raw_materials_auto_seeds(client, staff_headers):
    res = client.get('/api/inventory/raw-materials', headers=staff_headers)
    assert res.status_code == 200
    data = res.json()['data']
    assert data['total_count'] >= 9
    materials = data['materials']
    codes = [m['code'] for m in materials]
    assert 'RM-AYAM' in codes
    assert 'RM-KULIT-9' in codes
    assert 'RM-KULIT-10' in codes
    assert 'RM-TEPUNG' in codes

def test_create_raw_material(client, inventory_headers):
    unique_code = f"RM-TEST-{generate_uuid()[:6].upper()}"
    payload = {
        'code': unique_code,
        'name': 'Daging Sapi Giling Super',
        'category': 'daging',
        'unit': 'kg',
        'stock_qty': 50.0,
        'min_buffer': 20.0,
        'safe_target': 100.0,
        'cost_per_unit': 110000.0,
        'storage_location': 'Freezer Khusus'
    }
    res = client.post('/api/inventory/raw-materials', json=payload, headers=inventory_headers)
    assert res.status_code == 201
    mat = res.json()['data']
    assert mat['code'] == unique_code
    assert mat['stock_qty'] == 50.0
    assert mat['buffer_status'] == 'safe'

def test_record_restock_in_and_usage_out(client, inventory_headers):
    # 1. Fetch RM-AYAM
    res = client.get('/api/inventory/raw-materials?search=RM-AYAM', headers=inventory_headers)
    mat = res.json()['data']['materials'][0]
    mat_id = mat['id']
    initial_stock = mat['stock_qty']

    # 2. Record Restock (IN) 100 kg
    res_in = client.post(f'/api/inventory/raw-materials/{mat_id}/transaction', json={
        'type': 'in',
        'quantity': 100.0,
        'reference_type': 'purchase',
        'notes': 'Kiriman RPA Ciomas'
    }, headers=inventory_headers)
    assert res_in.status_code == 200
    assert res_in.json()['data']['updated_stock'] == initial_stock + 100.0

    # 3. Record Usage (OUT) 30 kg for 2 Gilingan
    res_out = client.post(f'/api/inventory/raw-materials/{mat_id}/transaction', json={
        'type': 'out',
        'quantity': 30.0,
        'reference_type': 'production_usage',
        'batch_gilingan': 2,
        'notes': 'Dipakai Produksi 1 (2 gilingan)'
    }, headers=inventory_headers)
    assert res_out.status_code == 200
    assert res_out.json()['data']['updated_stock'] == initial_stock + 70.0

def test_usage_out_insufficient_stock_fails(client, inventory_headers):
    res = client.get('/api/inventory/raw-materials?search=RM-TEPUNG', headers=inventory_headers)
    mat = res.json()['data']['materials'][0]
    mat_id = mat['id']

    # Current stock is ~8 karung, try to consume 999 karung
    res_fail = client.post(f'/api/inventory/raw-materials/{mat_id}/transaction', json={
        'type': 'out',
        'quantity': 999.0,
        'reference_type': 'production_usage'
    }, headers=inventory_headers)
    assert res_fail.status_code == 400
    assert 'tidak mencukupi' in res_fail.json()['error']

def test_check_production_readiness(client, staff_headers):
    # Test for default target 36 gilingan
    res = client.get('/api/inventory/raw-materials/readiness?target_gilingan=36', headers=staff_headers)
    assert res.status_code == 200
    data = res.json()['data']
    assert data['target_gilingan'] == 36
    assert data['estimated_finished_packs'] == 450

    items = {item['code']: item for item in data['items']}
    assert 'RM-AYAM' in items
    assert items['RM-AYAM']['required_qty'] == 540.0  # 36 x 15 kg
    assert 'deficit' in items['RM-AYAM']
    assert 'is_ready' in items['RM-AYAM']
    assert 'fulfillment_percent' in items['RM-AYAM']
