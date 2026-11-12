import pytest
from app.core.db import db_session
from app.modules.products.models import Product
from app.modules.inventory.models import InventoryTransaction
from app.modules.payments.service import PaywuzService

@pytest.fixture(autouse=True)
def mock_paywuz(monkeypatch):
    def fake_create_qris(order_id, amount):
        return {
            'id': f"paywuz-{order_id[:8]}",
            'qr_string': f"00020101021226...PAYWUZ-{order_id[:8]}",
            'expiresAt': '2026-10-01T12:00:00Z',
            'amount': amount
        }
    def fake_create_va(order_id, amount, bank_code='BNIVA'):
        return {
            'id': f"paywuz-va-{order_id[:8]}",
            'paymentMethod': bank_code,
            'paymentNumber': '0097010886130',
            'totalPayment': amount + 3400,
            'expiresAt': '2026-10-01T12:00:00Z',
            'amount': amount
        }
    monkeypatch.setattr(PaywuzService, 'create_qris_transaction', staticmethod(fake_create_qris))
    monkeypatch.setattr(PaywuzService, 'create_va_transaction', staticmethod(fake_create_va))

def test_pos_order_cash_success(client, staff_headers):
    # Setup product with 50 stock
    prod = db_session.query(Product).first()
    if not prod:
        prod = Product(
            name="Dimsum Siomay Udang",
            price=25000,
            sku="DS-UDG-POS",
            stock_qty=50,
            is_active=True
        )
        db_session.add(prod)
        db_session.commit()
    else:
        prod.stock_qty = 50
        db_session.commit()

    initial_stock = prod.stock_qty
    qty = 2
    total_amount = float(prod.price) * qty
    cash_received = 60000

    payload = {
        'items': [{'product_id': prod.id, 'quantity': qty}],
        'payment_method': 'cash',
        'cash_received': cash_received,
        'customer_name': 'Budi Walk-In',
        'customer_phone': '081234567890',
        'order_type': 'dine_in',
        'notes': 'Kukus hangat'
    }

    res = client.post('/api/orders/pos', headers=staff_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    
    order = data['data']['order']
    payment = data['data']['payment']

    assert order['status'] == 'completed'
    assert float(order['total_amount']) == total_amount
    assert payment['cash_received'] == 60000
    assert payment['cash_change'] == 60000 - total_amount

    # Verify stock decremented
    reloaded_prod = db_session.get(Product, prod.id)
    assert reloaded_prod.stock_qty == initial_stock - qty

    # Verify inventory transaction logged with channel='offline'
    tx = db_session.query(InventoryTransaction).filter_by(
        reference_id=order['id'],
        channel='offline'
    ).first()
    assert tx is not None
    assert tx.type == 'out'
    assert tx.quantity == qty

def test_pos_order_cash_insufficient_fails(client, staff_headers):
    prod = db_session.query(Product).first()
    prod.stock_qty = 30
    db_session.commit()

    payload = {
        'items': [{'product_id': prod.id, 'quantity': 1}],
        'payment_method': 'cash',
        'cash_received': float(prod.price) - 5000  # Less than total
    }

    res = client.post('/api/orders/pos', headers=staff_headers, json=payload)
    assert res.status_code == 400
    data = res.json()
    assert data['success'] is False
    assert 'kurang dari total' in data['error']

def test_pos_order_qris_success(client, staff_headers):
    prod = db_session.query(Product).first()
    prod.stock_qty = 20
    db_session.commit()

    payload = {
        'items': [{'product_id': prod.id, 'quantity': 1}],
        'payment_method': 'qris',
        'customer_name': 'QRIS Buyer'
    }

    res = client.post('/api/orders/pos', headers=staff_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    order = data['data']['order']
    payment = data['data']['payment']
    assert order['status'] == 'pending_payment'
    assert 'paywuz' in payment

def test_pos_order_forbidden_for_customer(client, customer_headers):
    prod = db_session.query(Product).first()
    payload = {
        'items': [{'product_id': prod.id, 'quantity': 1}],
        'payment_method': 'cash',
        'cash_received': 50000
    }
    res = client.post('/api/orders/pos', headers=customer_headers, json=payload)
    assert res.status_code == 403

def test_pos_order_transfer_va_success(client, staff_headers):
    prod = db_session.query(Product).first()
    prod.stock_qty = 15
    db_session.commit()

    payload = {
        'items': [{'product_id': prod.id, 'quantity': 1}],
        'payment_method': 'transfer',
        'bank_code': 'BCAVA',
        'customer_name': 'Transfer Buyer'
    }

    res = client.post('/api/orders/pos', headers=staff_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data['success'] is True
    order = data['data']['order']
    payment = data['data']['payment']
    assert order['status'] == 'pending_payment'
    assert 'paywuz' in payment
    assert payment['paywuz']['paymentNumber'] == '0097010886130'
