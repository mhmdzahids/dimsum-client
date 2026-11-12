import pytest
from app.modules.auth.models import User
from app.core.db import db_session

def test_customer_forbidden_from_admin_endpoints(client, customer_headers):
    # Customer cannot access internal user management
    res = client.get('/api/auth/users', headers=customer_headers)
    assert res.status_code == 403

    # Customer cannot create products
    res = client.post('/api/products', json={'name': 'Dimsum Hack', 'price': 1000, 'sku': 'HACK'}, headers=customer_headers)
    assert res.status_code == 403

    # Customer cannot list all orders via admin/staff endpoint
    res = client.get('/api/orders', headers=customer_headers)
    assert res.status_code == 403

def test_staff_permissions(client, staff_headers):
    # Staff CAN access orders list
    res = client.get('/api/orders', headers=staff_headers)
    assert res.status_code == 200

    # Staff CANNOT access user management (Admin only)
    res = client.get('/api/auth/users', headers=staff_headers)
    assert res.status_code == 403

    # Staff CANNOT create products (Admin only)
    res = client.post('/api/products', json={'name': 'Dimsum Hack', 'price': 1000, 'sku': 'HACK'}, headers=staff_headers)
    assert res.status_code == 403

def test_inventory_and_checker_permissions(client, inventory_headers, checker_headers):
    # Inventory can access orders list
    res = client.get('/api/orders', headers=inventory_headers)
    assert res.status_code == 200

    # Inventory CANNOT manage users
    res = client.get('/api/auth/users', headers=inventory_headers)
    assert res.status_code == 403

    # Checker can access orders list
    res = client.get('/api/orders', headers=checker_headers)
    assert res.status_code == 200

    # Checker CANNOT manage users
    res = client.get('/api/auth/users', headers=checker_headers)
    assert res.status_code == 403

def test_admin_user_management_flow(client, admin_headers):
    # 1. Admin lists internal users
    res = client.get('/api/auth/users', headers=admin_headers)
    assert res.status_code == 200
    data = res.json()['data']
    assert isinstance(data, list)

    # 2. Admin creates a new internal staff user
    new_user_payload = {
        'email': 'staff.baru@dimsum.id',
        'password': 'password123',
        'full_name': 'Staf Baru Toko',
        'role': 'staff',
        'phone': '081299990001'
    }
    res = client.post('/api/auth/users', json=new_user_payload, headers=admin_headers)
    assert res.status_code == 201
    created_user = res.json()['data']
    assert created_user['email'] == 'staff.baru@dimsum.id'
    assert created_user['role'] == 'staff'
    created_id = created_user['id']

    # 3. Admin updates role to checker
    res = client.put(f'/api/auth/users/{created_id}/role', json={'role': 'checker'}, headers=admin_headers)
    assert res.status_code == 200
    updated_user = res.json()['data']
    assert updated_user['role'] == 'checker'

    # 4. Invalid role rejected
    res = client.put(f'/api/auth/users/{created_id}/role', json={'role': 'superman'}, headers=admin_headers)
    assert res.status_code == 400

def test_admin_cannot_demote_self(client, admin_headers):
    # Admin gets own profile
    res = client.get('/api/auth/me', headers=admin_headers)
    assert res.status_code == 200
    admin_id = res.json()['data']['id']

    # Try demoting self to staff
    res = client.put(f'/api/auth/users/{admin_id}/role', json={'role': 'staff'}, headers=admin_headers)
    assert res.status_code == 400
    assert 'Admin tidak dapat mencabut hak admin' in res.json()['error']
