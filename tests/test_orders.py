import pytest
from app.modules.products.models import Product
from app.modules.orders.models import Order
from app.modules.payments.service import PaywuzService
from app.core.db import db_session
from app.shared.utils import generate_uuid

@pytest.fixture(autouse=True)
def mock_paywuz(monkeypatch):
    """Mocks Paywuz QRIS gateway to ensure tests are fast, offline, and reliable."""
    def fake_create_qris(order_id, amount):
        return {
            'id': f"paywuz-{order_id[:8]}",
            'qrString': '00020101021226540014ID.LINKAJA.WWW011893600914392290234502150000000000000005204581253033605802ID5911DIMSUM SHOP6007JAKARTA61051234062070703A016304D123',
            'expiresAt': '2026-09-20T23:59:59Z'
        }
    monkeypatch.setattr(PaywuzService, 'create_qris_transaction', staticmethod(fake_create_qris))

@pytest.fixture
def test_product(db):
    product = db_session.query(Product).filter_by(sku='TEST-ORD-01').first()
    if not product:
        product = Product(
            id=generate_uuid(),
            name='Dimsum Test Order Item',
            price=20000,
            sku='TEST-ORD-01',
            category='Steamed',
            stock_qty=25,
            is_active=True
        )
        db_session.add(product)
        db_session.commit()
    else:
        product.stock_qty = 25
        db_session.commit()
    return product

def test_create_order_success(client, test_product):
    prod_id = test_product.id
    payload = {
        'customer': {
            'name': 'Budi Santoso',
            'phone': '081298765432',
            'email': 'budi.santoso@example.com'
        },
        'items': [
            {'product_id': prod_id, 'quantity': 2}
        ],
        'notes': 'Tolong banyakin chili oil',
        'order_type': 'pickup'
    }
    res = client.post('/api/orders', json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    assert 'order' in data['data']
    order = data['data']['order']
    assert order['status'] == 'pending_payment'
    assert float(order['total_amount']) == 40000.0
    assert 'access_token' in order
    assert len(order['access_token']) > 20

    # Verify inventory was deducted
    updated_prod = db_session.query(Product).filter_by(id=prod_id).first()
    assert updated_prod.stock_qty == 23

def test_create_order_empty_cart_fails(client):
    res = client.post('/api/orders', json={
        'customer': {
            'name': 'Empty Cart User',
            'phone': '081298765432'
        },
        'items': []
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False

def test_create_order_exceed_order_limit_fails(client, test_product):
    prod_id = test_product.id
    # Setting limit is default 50. Requesting 51 items should fail.
    res = client.post('/api/orders', json={
        'customer': {
            'name': 'Greedy Customer',
            'phone': '081298765432'
        },
        'items': [
            {'product_id': prod_id, 'quantity': 51}
        ]
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err = (data.get('error') or '').lower()
    assert 'melebihi batas maksimum' in err

def test_create_order_insufficient_stock_fails(client, test_product):
    prod_id = test_product.id
    # test_product has stock 25. Requesting 30 should fail.
    res = client.post('/api/orders', json={
        'customer': {
            'name': 'Over Buyer',
            'phone': '081298765432'
        },
        'items': [
            {'product_id': prod_id, 'quantity': 30}
        ]
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err = (data.get('error') or '').lower()
    assert 'insufficient stock' in err or 'stok tidak mencukupi' in err

def test_get_order_authorized_with_token_header(client, test_product):
    # Create order first
    create_res = client.post('/api/orders', json={
        'customer': {'name': 'Auth Header Test', 'phone': '081200001111'},
        'items': [{'product_id': test_product.id, 'quantity': 1}]
    })
    order_data = create_res.json()['data']['order']
    order_id = order_data['id']
    token = order_data['access_token']

    # Get with X-Order-Token header
    res = client.get(f'/api/orders/{order_id}', headers={'X-Order-Token': token})
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert data['data']['id'] == order_id

def test_get_order_rejects_token_query_param(client, test_product):
    create_res = client.post('/api/orders', json={
        'customer': {'name': 'Query Param Test', 'phone': '081200002222'},
        'items': [{'product_id': test_product.id, 'quantity': 1}]
    })
    order_data = create_res.json()['data']['order']
    order_id = order_data['id']
    token = order_data['access_token']

    # Credentials in URLs are no longer accepted by the API.
    res = client.get(f'/api/orders/{order_id}?token={token}')
    assert res.status_code == 403

def test_get_order_forbidden_without_token(client, test_product):
    create_res = client.post('/api/orders', json={
        'customer': {'name': 'Unauthorized Test', 'phone': '081200003333'},
        'items': [{'product_id': test_product.id, 'quantity': 1}]
    })
    order_id = create_res.json()['data']['order']['id']

    # Request without token header or param
    res = client.get(f'/api/orders/{order_id}')
    assert res.status_code == 403
    data = res.json()
    assert data['success'] is False

def test_get_order_forbidden_with_wrong_token(client, test_product):
    create_res = client.post('/api/orders', json={
        'customer': {'name': 'Wrong Token Test', 'phone': '081200004444'},
        'items': [{'product_id': test_product.id, 'quantity': 1}]
    })
    order_id = create_res.json()['data']['order']['id']

    # Request with invalid token
    res = client.get(f'/api/orders/{order_id}', headers={'X-Order-Token': 'wrong-unauthorized-token'})
    assert res.status_code == 403
    data = res.json()
    assert data['success'] is False

def test_get_order_authorized_for_admin(client, test_product, admin_headers):
    create_res = client.post('/api/orders', json={
        'customer': {'name': 'Admin Access Test', 'phone': '081200005555'},
        'items': [{'product_id': test_product.id, 'quantity': 1}]
    })
    order_id = create_res.json()['data']['order']['id']

    # Admin requests order without order token
    res = client.get(f'/api/orders/{order_id}', headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert data['data']['id'] == order_id

def test_list_orders_admin(client, admin_headers, customer_headers):
    # Admin can list orders
    admin_res = client.get('/api/orders', headers=admin_headers)
    assert admin_res.status_code == 200
    assert admin_res.json()['success'] is True
    assert isinstance(admin_res.json()['data'], list)

    # Regular customer cannot list admin orders
    cust_res = client.get('/api/orders', headers=customer_headers)
    assert cust_res.status_code == 403

def test_transactions_superadmin_access(client, admin_headers, customer_headers):
    # Super Admin / Owner can access comprehensive transactions
    res = client.get('/api/orders/transactions', headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert 'transactions' in data['data']
    assert 'pagination' in data['data']
    assert 'kpi' in data['data']

    # Non-admin customer gets 403 Forbidden
    cust_res = client.get('/api/orders/transactions', headers=customer_headers)
    assert cust_res.status_code == 403
