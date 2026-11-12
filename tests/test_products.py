import pytest
from app.modules.products.models import Product
from app.core.db import db_session
from app.shared.utils import generate_uuid

def test_get_products_list(client):
    res = client.get('/api/products')
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert isinstance(data['data'], list)

def test_create_product_admin_success(client, admin_headers):
    payload = {
        'name': 'Dimsum Siomay Ayam Udang',
        'price': 25000,
        'sku': 'DS-AYM-001',
        'category': 'Steamed Dimsum',
        'is_active': True
    }
    res = client.post('/api/products', headers=admin_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    created = data['data']
    assert created['name'] == 'Dimsum Siomay Ayam Udang'
    assert float(created['price']) == 25000
    assert created['sku'] == 'DS-AYM-001'
    assert created['category'] == 'Steamed Dimsum'
    assert created['stock_qty'] == 0

def test_create_product_missing_fields(client, admin_headers):
    # Missing sku and price
    res = client.post('/api/products', headers=admin_headers, json={
        'name': 'Incomplete Product'
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False

def test_create_product_forbidden_for_customer(client, customer_headers):
    res = client.post('/api/products', headers=customer_headers, json={
        'name': 'Hacker Dimsum',
        'price': 1000,
        'sku': 'HACK-01'
    })
    assert res.status_code == 403
    data = res.json()
    assert data['success'] is False

def test_create_product_unauthorized(client):
    res = client.post('/api/products', json={
        'name': 'Unauthorized Dimsum',
        'price': 1000,
        'sku': 'UNAUTH-01'
    })
    assert res.status_code == 401
    data = res.json()
    assert data['success'] is False

def test_get_single_product_and_404(client, admin_headers):
    # First create a product
    create_res = client.post('/api/products', headers=admin_headers, json={
        'name': 'Hakau Udang Kristal',
        'price': 28000,
        'sku': 'HK-UDG-001'
    })
    product_id = create_res.json()['data']['id']

    # Get valid product
    res = client.get(f'/api/products/{product_id}')
    assert res.status_code == 200
    assert res.json()['data']['name'] == 'Hakau Udang Kristal'

    # Get non-existent product
    res_404 = client.get('/api/products/non-existent-uuid-1234')
    assert res_404.status_code == 404

def test_update_product_admin(client, admin_headers):
    create_res = client.post('/api/products', headers=admin_headers, json={
        'name': 'Pangsit Goreng Mayonais',
        'price': 22000,
        'sku': 'PG-MYO-001'
    })
    product_id = create_res.json()['data']['id']

    update_res = client.put(f'/api/products/{product_id}', headers=admin_headers, json={
        'name': 'Pangsit Goreng Mayonais Super',
        'price': 24000,
        'category': 'Fried Dimsum',
        'description': 'Pangsit renyah isi udang premium'
    })
    assert update_res.status_code == 200
    data = update_res.json()['data']
    assert data['name'] == 'Pangsit Goreng Mayonais Super'
    assert float(data['price']) == 24000
    assert data['category'] == 'Fried Dimsum'
    assert data['description'] == 'Pangsit renyah isi udang premium'

def test_update_product_forbidden_for_customer(client, customer_headers, admin_headers):
    create_res = client.post('/api/products', headers=admin_headers, json={
        'name': 'Lumpia Kulit Tahu',
        'price': 26000,
        'sku': 'LKT-001'
    })
    product_id = create_res.json()['data']['id']

    res = client.put(f'/api/products/{product_id}', headers=customer_headers, json={
        'price': 1000
    })
    assert res.status_code == 403

def test_delete_product_admin(client, admin_headers):
    create_res = client.post('/api/products', headers=admin_headers, json={
        'name': 'Product to Delete',
        'price': 15000,
        'sku': 'DEL-001'
    })
    product_id = create_res.json()['data']['id']

    del_res = client.delete(f'/api/products/{product_id}', headers=admin_headers)
    assert del_res.status_code == 200
    assert del_res.json()['success'] is True

    # Product should no longer be found
    get_res = client.get(f'/api/products/{product_id}')
    assert get_res.status_code == 404

def test_delete_product_forbidden_for_customer(client, customer_headers, admin_headers):
    create_res = client.post('/api/products', headers=admin_headers, json={
        'name': 'Product Protected',
        'price': 18000,
        'sku': 'PROT-001'
    })
    product_id = create_res.json()['data']['id']

    res = client.delete(f'/api/products/{product_id}', headers=customer_headers)
    assert res.status_code == 403
