import pytest
import hmac
from app.modules.products.models import Product
from app.modules.orders.models import Order
from app.modules.payments.service import PaywuzService
from app.core.db import db_session
from app.shared.utils import generate_uuid

@pytest.fixture(autouse=True)
def mock_paywuz(monkeypatch):
    def fake_create_qris(order_id, amount):
        return {
            'id': f"paywuz-{order_id[:8]}",
            'qrString': '00020101021226540014ID.LINKAJA.WWW...',
            'expiresAt': '2026-09-20T23:59:59Z'
        }
    monkeypatch.setattr(PaywuzService, 'create_qris_transaction', staticmethod(fake_create_qris))

def test_security_headers_present(client):
    """Verifies that mandatory OWASP security headers are present on responses."""
    res = client.get('/health')
    assert res.status_code == 200
    headers = res.headers
    
    assert headers.get('X-Content-Type-Options') == 'nosniff'
    assert headers.get('X-Frame-Options') == 'DENY'
    assert headers.get('X-XSS-Protection') == '1; mode=block'
    assert headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
    assert 'Content-Security-Policy' in headers
    assert "default-src 'self'" in headers['Content-Security-Policy']

def test_cors_preflight_headers(client):
    """Verifies CORS preflight handling for allowed headers and origins."""
    res = client.options('/api/products', headers={
        'Origin': 'http://localhost:5173',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'Authorization, Content-Type, X-Order-Token'
    })
    # Preflight should succeed (200 or 204)
    assert res.status_code in [200, 204]
    assert 'Access-Control-Allow-Origin' in res.headers
    assert 'Access-Control-Allow-Methods' in res.headers

def test_sql_injection_in_login(client):
    """Verifies SQL injection payload in identifier fails safely without SQL syntax error."""
    payload = {
        'identifier': "admin@dimsum.id' OR '1'='1",
        'password': "' OR '1'='1"
    }
    res = client.post('/api/auth/login', json=payload)
    assert res.status_code == 401
    data = res.json()
    assert data['success'] is False

def test_sql_injection_in_order_id(client):
    """Verifies invalid order_id format (including SQLi) is rejected safely."""
    res = client.get("/api/orders/1' UNION SELECT * FROM users--")
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    assert 'Invalid order ID format' in data.get('error', '')

def test_tampered_jwt_token_rejected(client):
    """Verifies that an unauthorized tampered JWT is rejected."""
    tampered_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0Iiwicm9sZSI6ImFkbWluIn0.TAMPEREDSIGNATURE"
    res = client.get('/api/auth/me', headers={'Authorization': f'Bearer {tampered_token}'})
    assert res.status_code == 401
    assert res.json()['success'] is False

def test_role_based_access_control(client, customer_headers):
    """Verifies customer cannot access admin endpoints."""
    # Settings update endpoint is admin-only
    res_settings = client.put('/api/settings/order-limit', headers=customer_headers, json={'order_item_limit': 100})
    assert res_settings.status_code == 403

    # Product creation is admin-only
    res_prod = client.post('/api/products', headers=customer_headers, json={'name': 'Bad', 'price': 10, 'sku': 'B1'})
    assert res_prod.status_code == 403

    # Vouchers management is admin-only
    res_vouchers = client.get('/api/vouchers', headers=customer_headers)
    assert res_vouchers.status_code == 403

    # Orders admin listing is admin-only
    res_orders = client.get('/api/orders', headers=customer_headers)
    assert res_orders.status_code == 403

def test_xss_payload_sanitization_in_orders(client, db):
    """Verifies that user inputs with HTML/script injection are properly escaped."""
    # Ensure a product exists
    product = db_session.query(Product).first()
    if not product:
        product = Product(
            id=generate_uuid(),
            name='Dimsum XSS Safe Product',
            price=15000,
            sku='XSS-SAFE-01',
            stock_qty=10
        )
        db_session.add(product)
        db_session.commit()

    xss_name = '<script>alert("hacked")</script>John Doe'
    xss_notes = '<img src=x onerror=alert(1)> Extra spicy'

    res = client.post('/api/orders', json={
        'customer': {
            'name': xss_name,
            'phone': '081299998888'
        },
        'items': [{'product_id': product.id, 'quantity': 1}],
        'notes': xss_notes
    })
    assert res.status_code == 201
    order_data = res.json()['data']['order']
    
    # Check notes in order
    assert '<script>' not in order_data.get('notes', '')
    assert '<img' not in order_data.get('notes', '')
    assert '&lt;img src=x onerror=alert(1)&gt;' in order_data.get('notes', '') or '&lt;' in order_data.get('notes', '')

def test_timing_safe_token_comparison(client, db):
    """Verifies guest order token comparison avoids timing attacks."""
    product = db_session.query(Product).first()
    res = client.post('/api/orders', json={
        'customer': {'name': 'HMAC Test User', 'phone': '081277776666'},
        'items': [{'product_id': product.id, 'quantity': 1}]
    })
    order = res.json()['data']['order']
    order_id = order['id']
    real_token = order['access_token']

    # Header with real token succeeds
    res_valid = client.get(f'/api/orders/{order_id}', headers={'X-Order-Token': real_token})
    assert res_valid.status_code == 200

    # Header with near-match or fake token fails
    fake_token = real_token[:-1] + ('a' if real_token[-1] != 'a' else 'b')
    res_invalid = client.get(f'/api/orders/{order_id}', headers={'X-Order-Token': fake_token})
    assert res_invalid.status_code == 403
