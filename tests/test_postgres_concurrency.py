from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from app.modules.products.models import Product
from app.modules.payments.service import PaywuzService
from app.modules.auth.models import User
from app.modules.orders.models import Order
from app.core.db import db_session


def concurrent_calls(call):
    barrier = Barrier(2)
    def worker():
        barrier.wait(timeout=10)
        return call()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        return [future.result(timeout=20) for future in futures]


def test_concurrent_checkout_cannot_oversell(client, db, monkeypatch):
    product = Product(id=str(uuid4()), name='Concurrent stock', sku=uuid4().hex,
                      price=10000, stock_qty=1, stock_online=0, stock_offline=1)
    db.add(product)
    db.commit()
    product_id = product.id
    monkeypatch.setattr(PaywuzService, 'create_qris_transaction',
                        lambda order_id, amount: {'id': order_id, 'qrString': 'TEST'})
    responses = concurrent_calls(lambda: client.post('/api/orders', json={
        'customer': {'name': 'Concurrency Test', 'phone': '081234567800'},
        'items': [{'product_id': product_id, 'quantity': 1}]}))
    assert sorted(r.status_code for r in responses) == [201, 400], [r.json() for r in responses]
    db.expire_all()
    assert db.get(Product, product_id).stock_qty == 0


def test_concurrent_batch_numbers_are_unique(client, db, inventory_headers):
    product = Product(id=str(uuid4()), name='Concurrent batch', sku=uuid4().hex, price=10000, stock_qty=0)
    db.add(product)
    db.commit()
    product_id = product.id
    responses = concurrent_calls(lambda: client.post('/api/inventory/production/plan',
            headers=inventory_headers, json={'product_id': product_id, 'planned_lots': 1}))
    assert [r.status_code for r in responses] == [201, 201]
    assert len({r.json()['data']['batch_code'] for r in responses}) == 2


def test_pickup_cannot_complete_twice(client, db, staff_headers):
    user = User(id=str(uuid4()), email=f'{uuid4().hex}@example.test', full_name='Pickup',
                password_hash='guest', is_registered=False, role='customer')
    db.add(user)
    db.flush()
    token = uuid4().hex
    order = Order(id=str(uuid4()), customer_id=user.id, status='paid', total_amount=10000, qr_token=token)
    db.add(order)
    db.commit()
    responses = concurrent_calls(lambda: client.post('/api/orders/verify',
                          headers=staff_headers, json={'qr_token': token}))
    assert sorted(r.status_code for r in responses) == [200, 400]
