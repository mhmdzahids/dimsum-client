import hmac
import hashlib
import json
import pytest
from app.core.config import Config
from app.core.db import db_session
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.orders.models import Order
from app.modules.payments.models import Payment
from app.modules.products.models import Product
from app.shared.utils import generate_uuid

def test_webhook_invalid_signature_rejected(client, db):
    Config.PAYWUZ_WEBHOOK_SECRET = 'super-secret-webhook-key'
    Config.ENV = 'production'  # Enforce strict signature checking
    try:
        payload = {'event': 'payment.success', 'data': {'id': 'pwz_123'}}
        body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Paywuz-Signature': 'invalid_signature_hex'
        }
        res = client.post('/api/payments/webhook', content=body, headers=headers)
        assert res.status_code == 403
    finally:
        Config.ENV = 'testing'

def test_webhook_valid_signature_accepted(client, db):
    secret = 'super-secret-webhook-key'
    Config.PAYWUZ_WEBHOOK_SECRET = secret
    Config.ENV = 'production'
    try:
        # Create a test customer
        customer = User(
            id=generate_uuid(),
            email='test.buyer.webhook@dimsum.id',
            password_hash=AuthService.hash_password('password123'),
            full_name='Test Buyer',
            role='customer'
        )
        db.add(customer)
        db.commit()

        # Create a test product & order
        product = Product(
            id=generate_uuid(),
            name='Dimsum Test Webhook',
            price=25000,
            sku='TEST-WH-01',
            stock_qty=50
        )
        db.add(product)
        db.commit()

        order = Order(
            id=generate_uuid(),
            customer_id=customer.id,
            customer_name='Test Buyer',
            customer_phone='081234567890',
            status='pending_payment',
            total_amount=25000
        )
        db.add(order)
        db.commit()

        payment = Payment(
            id=generate_uuid(),
            order_id=order.id,
            gateway='paywuz',
            gateway_ref_id='pwz_order_123',
            status='pending'
        )
        db.add(payment)
        db.commit()

        payload = {
            'event': 'payment.success',
            'data': {
                'id': 'pwz_order_123',
                'status': 'success',
                'referenceId': order.id,
                'amount': 25000
            }
        }
        body = json.dumps(payload).encode('utf-8')
        sig = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        headers = {
            'Content-Type': 'application/json',
            'X-Paywuz-Signature': sig
        }

        # First webhook invocation -> success
        res = client.post('/api/payments/webhook', content=body, headers=headers)
        assert res.status_code == 200

        # Check order status updated to paid and qr_token generated
        updated_order = db_session.query(Order).get(order.id)
        assert updated_order.status == 'paid'
        assert updated_order.qr_token is not None

        # Second webhook invocation (Idempotency test) -> should return 200 without error
        res_idempotent = client.post('/api/payments/webhook', content=body, headers=headers)
        assert res_idempotent.status_code == 200
        reloaded_order = db_session.query(Order).get(order.id)
        assert reloaded_order.status == 'paid'
    finally:
        Config.ENV = 'testing'
