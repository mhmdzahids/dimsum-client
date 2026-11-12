import json
import pytest
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.core.db import db_session

def test_register_success(client):
    res = client.post('/api/auth/register', json={
        'identifier': 'newuser@dimsum.id',
        'full_name': 'New User Test',
        'password': 'password123'
    })
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    assert 'token' in data['data']
    assert data['data']['user']['email'] == 'newuser@dimsum.id'
    assert data['data']['user']['full_name'] == 'New User Test'
    assert data['data']['user']['role'] == 'customer'

def test_register_duplicate_identifier(client):
    # Attempting to register the same user again should fail with 400
    res = client.post('/api/auth/register', json={
        'identifier': 'newuser@dimsum.id',
        'full_name': 'Duplicate User',
        'password': 'password123'
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err_msg = (data.get('error') or data.get('message') or '').lower()
    assert 'sudah terdaftar' in err_msg

def test_register_invalid_identifier(client):
    res = client.post('/api/auth/register', json={
        'identifier': 'not-an-email-or-phone',
        'full_name': 'Invalid ID',
        'password': 'password123'
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err_msg = (data.get('error') or data.get('message') or '').lower()
    assert 'tidak valid' in err_msg

def test_register_short_password(client):
    res = client.post('/api/auth/register', json={
        'identifier': 'shortpw@dimsum.id',
        'full_name': 'Short PW',
        'password': '123'
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    err_msg = (data.get('error') or data.get('message') or '').lower()
    assert 'minimal 6 karakter' in err_msg

def test_register_missing_fields(client):
    res = client.post('/api/auth/register', json={
        'identifier': 'incomplete@dimsum.id'
    })
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False

def test_login_success(client):
    res = client.post('/api/auth/login', json={
        'identifier': 'newuser@dimsum.id',
        'password': 'password123'
    })
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert 'token' in data['data']
    assert data['data']['user']['email'] == 'newuser@dimsum.id'

def test_login_invalid_password(client):
    res = client.post('/api/auth/login', json={
        'identifier': 'newuser@dimsum.id',
        'password': 'wrongpassword'
    })
    assert res.status_code == 401
    data = res.json()
    assert data['success'] is False
    err_msg = (data.get('error') or data.get('message') or '').lower()
    assert 'tidak sesuai' in err_msg or 'salah' in err_msg or 'invalid' in err_msg

def test_login_nonexistent_user(client):
    res = client.post('/api/auth/login', json={
        'identifier': 'doesnotexist@dimsum.id',
        'password': 'somepassword'
    })
    assert res.status_code == 401
    data = res.json()
    assert data['success'] is False

def test_admin_login(client, admin_headers):
    # admin user is ensured by admin_headers fixture
    res = client.post('/api/auth/login', json={
        'identifier': 'admin@dimsum.id',
        'password': 'password123'
    })
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert data['data']['user']['role'] == 'admin'

def test_me_authenticated(client, customer_headers):
    res = client.get('/api/auth/me', headers=customer_headers)
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert data['data']['email'] == 'customer.test@dimsum.id'

def test_me_unauthenticated(client):
    res = client.get('/api/auth/me')
    assert res.status_code == 401
    data = res.json()
    assert data['success'] is False

def test_me_invalid_token(client):
    res = client.get('/api/auth/me', headers={'Authorization': 'Bearer invalid.token.value'})
    assert res.status_code == 401
    data = res.json()
    assert data['success'] is False

def test_logout_and_token_revocation(client):
    # Register & login user to get a fresh token
    client.post('/api/auth/register', json={
        'identifier': 'revoketest@dimsum.id',
        'full_name': 'Revoke Test',
        'password': 'password123'
    })
    login_res = client.post('/api/auth/login', json={
        'identifier': 'revoketest@dimsum.id',
        'password': 'password123'
    })
    token = login_res.json()['data']['token']
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    # Verify token works
    res_me = client.get('/api/auth/me', headers=headers)
    assert res_me.status_code == 200

    # Logout
    res_logout = client.post('/api/auth/logout', headers=headers)
    assert res_logout.status_code == 200
    assert res_logout.json()['success'] is True

    # Token should now be revoked and rejected
    res_me_after = client.get('/api/auth/me', headers=headers)
    assert res_me_after.status_code == 401

def test_update_profile(client, customer_headers):
    res = client.put('/api/auth/profile', headers=customer_headers, json={
        'full_name': 'Pelanggan Diperbarui'
    })
    assert res.status_code == 200
    data = res.json()
    assert data['success'] is True
    assert data['data']['full_name'] == 'Pelanggan Diperbarui'
