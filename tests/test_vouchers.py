import pytest
from app.modules.vouchers.models import Voucher
from app.core.db import db_session
from app.shared.utils import generate_uuid

@pytest.fixture
def fixed_voucher(db):
    v = db_session.query(Voucher).filter_by(code='DIMSUMHEMAT').first()
    if not v:
        v = Voucher(
            id=generate_uuid(),
            code='DIMSUMHEMAT',
            discount_type='fixed',
            discount_value=10000,
            min_spend=50000,
            is_active=True,
            is_public=True
        )
        db_session.add(v)
        db_session.commit()
    return v

@pytest.fixture
def percent_voucher(db):
    v = db_session.query(Voucher).filter_by(code='DISC20').first()
    if not v:
        v = Voucher(
            id=generate_uuid(),
            code='DISC20',
            discount_type='percent',
            discount_value=20,
            min_spend=50000,
            max_discount=20000,
            is_active=True,
            is_public=True
        )
        db_session.add(v)
        db_session.commit()
    return v

def test_validate_voucher_success(client, fixed_voucher):
    res = client.post('/api/vouchers/validate', json={
        'code': 'DIMSUMHEMAT',
        'subtotal': 60000
    })
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert float(data['data']['discount']) == 10000.0
    assert data['data']['code'] == 'DIMSUMHEMAT'

def test_validate_voucher_below_min_spend(client, fixed_voucher):
    res = client.post('/api/vouchers/validate', json={
        'code': 'DIMSUMHEMAT',
        'subtotal': 30000
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err = (data.get('error') or '').lower()
    assert 'minimal belanja' in err

def test_validate_voucher_not_found(client):
    res = client.post('/api/vouchers/validate', json={
        'code': 'NOTREALVOUCHER',
        'subtotal': 100000
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err = (data.get('error') or '').lower()
    assert 'tidak ditemukan' in err or 'tidak valid' in err

def test_validate_percentage_voucher(client, percent_voucher):
    # Subtotal 80,000 -> 20% discount = 16,000 (below max 20,000)
    res = client.post('/api/vouchers/validate', json={
        'code': 'DISC20',
        'subtotal': 80000
    })
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert float(data['data']['discount']) == 16000.0

def test_validate_percentage_voucher_capped_by_max_discount(client, percent_voucher):
    # Subtotal 200,000 -> 20% discount = 40,000, capped at max_discount 20,000
    res = client.post('/api/vouchers/validate', json={
        'code': 'DISC20',
        'subtotal': 200000
    })
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert float(data['data']['discount']) == 20000.0

def test_list_public_vouchers(client, fixed_voucher):
    res = client.get('/api/vouchers/public')
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert isinstance(data['data'], list)
    codes = [v['code'] for v in data['data']]
    assert 'DIMSUMHEMAT' in codes

def test_create_voucher_admin(client, admin_headers):
    payload = {
        'code': 'NEWPROMO10',
        'discount_type': 'fixed',
        'discount_value': 10000,
        'min_spend': 50000,
        'is_public': True
    }
    res = client.post('/api/vouchers', headers=admin_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    assert data['data']['code'] == 'NEWPROMO10'

def test_create_voucher_forbidden_for_customer(client, customer_headers):
    res = client.post('/api/vouchers', headers=customer_headers, json={
        'code': 'HACKVOUCHER',
        'discount_type': 'fixed',
        'discount_value': 50000
    })
    assert res.status_code == 403

def test_toggle_voucher_admin(client, admin_headers):
    # Create voucher first
    create_res = client.post('/api/vouchers', headers=admin_headers, json={
        'code': 'TOGGLEME',
        'discount_type': 'fixed',
        'discount_value': 5000,
        'min_spend': 20000
    })
    voucher_id = create_res.json()['data']['id']

    # Toggle
    toggle_res = client.patch(f'/api/vouchers/{voucher_id}/toggle', headers=admin_headers)
    assert toggle_res.status_code == 200
    data = toggle_res.json()
    assert data['success'] is True
    assert data['data']['is_active'] is False

def test_delete_voucher_admin(client, admin_headers):
    create_res = client.post('/api/vouchers', headers=admin_headers, json={
        'code': 'DELETEME',
        'discount_type': 'fixed',
        'discount_value': 5000
    })
    voucher_id = create_res.json()['data']['id']

    del_res = client.delete(f'/api/vouchers/{voucher_id}', headers=admin_headers)
    assert del_res.status_code == 200
    assert del_res.json()['success'] is True
