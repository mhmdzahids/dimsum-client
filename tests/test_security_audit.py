"""Security regression checks for the remediated findings.
Included in the default pytest suite.
"""
import io
from urllib.parse import urlsplit
from uuid import uuid4
import pytest
from PIL import Image
from app.core.config import Config
from app.core.security import revoke_token, verify_token
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.orders.models import Order
from app.modules.payments.service import PaywuzService


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('External network is prohibited during security audit')
    monkeypatch.setattr('urllib.request.urlopen', blocked)


def make_user(db, role='customer', password_hash=None, registered=True):
    user = User(id=str(uuid4()), email=f'{uuid4().hex}@example.test',
                full_name='Audit User', role=role,
                password_hash=password_hash or AuthService.hash_password('Audit-password-42'),
                is_registered=registered)
    db.add(user)
    db.commit()
    return user


def test_password_is_salted_hash():
    one = AuthService.hash_password('Audit-password-42')
    two = AuthService.hash_password('Audit-password-42')
    assert one != two
    assert one != 'Audit-password-42'
    assert AuthService.check_password(one, 'Audit-password-42')
    assert not AuthService.check_password(one, 'wrong')


def test_profile_does_not_expose_password(client, customer_headers):
    res = client.get('/api/auth/me', headers=customer_headers)
    assert res.status_code == 200
    assert 'password_hash' not in res.json()['data']


def test_role_demotion_invalidates_old_admin_privileges(client, db):
    user = make_user(db, role='admin')
    token = AuthService.generate_token(user.id, 'admin')
    user.role = 'customer'
    db.commit()
    res = client.get('/api/auth/users', headers={'Authorization': f'Bearer {token}'})
    assert res.status_code == 403


def test_logout_survives_worker_restart(client, db):
    user = make_user(db)
    token = AuthService.generate_token(user.id, user.role)
    revoke_token(token)
    assert verify_token(token) is None
    # Simulate another worker/restart, which has no in-memory blacklist.
    from app.core.db import db_session
    db_session.remove()
    assert verify_token(token) is None


def test_guest_account_cannot_be_claimed_without_identity_verification(client, db):
    user = make_user(db, password_hash='guest', registered=False)
    res = client.post('/api/auth/register', json={
        'email': user.email, 'full_name': 'Other Person', 'password': 'Other-password-42'})
    assert res.status_code in (400, 403, 409)


def test_legacy_order_requires_authorization(client, db):
    user = make_user(db)
    order = Order(id=str(uuid4()), customer_id=user.id, status='completed',
                  total_amount=10000, access_token=None, customer_phone='081200001111')
    db.add(order)
    db.commit()
    res = client.get(f'/api/orders/{order.id}')
    assert res.status_code in (401, 403)


def test_other_customer_cannot_read_protected_order(client, db, customer_headers):
    user = make_user(db)
    order = Order(id=str(uuid4()), customer_id=user.id, status='completed',
                  total_amount=10000, access_token=uuid4().hex)
    db.add(order)
    db.commit()
    res = client.get(f'/api/orders/{order.id}', headers=customer_headers)
    assert res.status_code == 403


@pytest.mark.parametrize('body', [['not', 'an', 'object'], {'email': 123, 'password': 'secret'}])
def test_login_bad_input_is_4xx(client, body):
    assert client.post('/api/auth/login', json=body).status_code in (400, 401, 422)


def test_oversized_password_is_validation_error(client):
    res = client.post('/api/auth/register', json={
        'email': f'{uuid4().hex}@example.test', 'full_name': 'Audit User', 'password': 'x' * 100})
    assert res.status_code in (400, 422)


def test_cross_origin_form_cannot_change_admin_data(client):
    res = client.post('/api/products', data={'name': 'CSRF'},
                      headers={'Origin': 'https://attacker.example'})
    assert res.status_code == 403


def test_untrusted_origin_does_not_receive_cors_permission(client):
    res = client.options('/api/products', headers={
        'Origin': 'https://attacker.example', 'Access-Control-Request-Method': 'POST'})
    assert 'Access-Control-Allow-Origin' not in res.headers


def test_upload_requires_admin(client):
    assert client.post('/api/banners', files={'image': ('a.jpg', io.BytesIO(b'abc'), 'image/jpeg')}).status_code == 401


def test_svg_upload_rejected(client, admin_headers):
    res = client.post('/api/banners', headers={'Authorization': admin_headers['Authorization']},
                      files={'image': ('a.svg', io.BytesIO(b'<svg onload="alert(1)"></svg>'), 'image/svg+xml')})
    assert res.status_code == 400


def test_fake_image_is_validation_error(client, admin_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    res = client.post('/api/banners', headers={'Authorization': admin_headers['Authorization']},
                      files={'image': ('a.jpg', io.BytesIO(b'<script>alert(1)</script>'), 'image/jpeg')})
    assert not list(tmp_path.iterdir())
    assert res.status_code == 400


def test_upload_reencodes_and_contains_path(client, admin_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2)).save(buffer, 'PNG')
    buffer.seek(0)
    res = client.post('/api/banners', headers={'Authorization': admin_headers['Authorization']},
                      files={'image': ('../../audit.png', buffer, 'image/png')})
    assert res.status_code == 201
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].suffix == '.webp'
    assert Image.open(files[0]).format == 'WEBP'
    client.delete('/api/banners/' + res.json()['data']['id'], headers=admin_headers)


def test_transaction_identifier_cannot_replace_destination(monkeypatch):
    seen = []
    def capture(req, *args, **kwargs):
        seen.append(req.full_url)
        raise OSError('Mock request: no network')
    monkeypatch.setattr(Config, 'PAYWUZ_API_KEY', 'audit-placeholder')
    monkeypatch.setattr(Config, 'PAYWUZ_API_URL', 'https://api.paywuz.id/v1')
    monkeypatch.setattr('app.modules.payments.service.opener.open', capture)
    PaywuzService.get_transaction('http://127.0.0.1:9999/private')
    assert len(seen) == 1
    assert urlsplit(seen[0]).hostname == 'api.paywuz.id'


def test_payment_client_sets_timeout(monkeypatch):
    captured = []
    def capture(req, *args, **kwargs):
        captured.append(kwargs)
        raise OSError('Mock request: no network')
    monkeypatch.setattr(Config, 'PAYWUZ_API_KEY', 'audit-placeholder')
    monkeypatch.setattr('app.modules.payments.service.opener.open', capture)
    PaywuzService.get_transaction('audit-transaction')
    assert captured and captured[0].get('timeout', 0) > 0


def test_development_webhook_does_not_accept_unsigned_payload(monkeypatch):
    from app.modules.payments.routes import verify_webhook_signature
    monkeypatch.setattr(Config, 'ENV', 'development')
    monkeypatch.setattr(Config, 'PAYWUZ_WEBHOOK_SECRET', '')
    monkeypatch.setattr(Config, 'PAYWUZ_API_KEY', '')
    assert verify_webhook_signature(b'{"status":"success"}', {}) is False


def test_login_rate_limit_is_enforced(client, monkeypatch):
    monkeypatch.setattr(Config, 'RATELIMIT_ENABLED', True)
    statuses = [client.post('/api/auth/login', json={'email': 'absent@example.test', 'password': 'bad'}).status_code for _ in range(6)]
    assert statuses == [401, 401, 401, 401, 401, 429]


def test_request_body_size_limit(client, monkeypatch):
    monkeypatch.setattr(Config, 'MAX_CONTENT_LENGTH', 32)
    assert client.post('/api/auth/login', content=b'x' * 33).status_code == 413


def test_anonymous_users_cannot_read_recipe_inventory(client):
    assert client.get('/api/ingredients').status_code == 401


def test_checkout_does_not_modify_registered_identity(client, db, monkeypatch):
    user = make_user(db)
    original_name = user.full_name
    user_id, email = user.id, user.email
    from app.modules.products.models import Product
    product = Product(id=str(uuid4()), name='Identity test', sku=uuid4().hex,
                      price=10000, stock_qty=10)
    db.add(product)
    db.commit()
    monkeypatch.setattr(PaywuzService, 'create_qris_transaction',
                        lambda order_id, amount: {'id': order_id, 'qrString': 'TEST'})
    res = client.post('/api/orders', json={'customer': {'name': 'Impersonator', 'email': email,
                      'phone': '081200001234'}, 'items': [{'product_id': product.id, 'quantity': 1}]})
    assert res.status_code == 201
    assert res.json()['data']['order']['customer_id'] != user_id
    assert db.get(User, user_id).full_name == original_name
    assert db.get(User, user_id).phone is None
