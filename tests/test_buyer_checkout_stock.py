import pytest
from app.modules.products.models import Product
from app.modules.orders.models import Order
from app.modules.inventory.models import InventoryTransaction
from app.modules.orders.service import OrderService
from app.modules.payments.service import PaywuzService
from app.core.db import db_session
from app.shared.utils import generate_uuid

@pytest.fixture(autouse=True)
def mock_paywuz(monkeypatch):
    def fake_create_qris(order_id, amount):
        return {
            'id': f"paywuz-{order_id[:8]}",
            'qrString': '00020101021226540014ID.LINKAJA.WWW011893600914392290234502150000000000000005204581253033605802ID5911DIMSUM SHOP6007JAKARTA61051234062070703A016304D123',
            'expiresAt': '2026-09-30T23:59:59Z'
        }
    monkeypatch.setattr(PaywuzService, 'create_qris_transaction', staticmethod(fake_create_qris))

@pytest.fixture
def product_single(db):
    product = db_session.query(Product).filter_by(sku='TEST-BUYER-01').first()
    if not product:
        product = Product(
            id=generate_uuid(),
            name='Dimsum Ayam Jamur (Test Single)',
            price=18000,
            sku='TEST-BUYER-01',
            category='Steamed',
            stock_qty=50,
            is_active=True
        )
        db_session.add(product)
        db_session.commit()
    else:
        product.stock_qty = 50
        db_session.commit()
    return product

@pytest.fixture
def product_pair(db):
    p1 = db_session.query(Product).filter_by(sku='TEST-BUYER-02A').first()
    if not p1:
        p1 = Product(
            id=generate_uuid(),
            name='Dimsum Keju Mozzarella (Test Multi 1)',
            price=22000,
            sku='TEST-BUYER-02A',
            category='Steamed',
            stock_qty=40,
            is_active=True
        )
        db_session.add(p1)
    else:
        p1.stock_qty = 40

    p2 = db_session.query(Product).filter_by(sku='TEST-BUYER-02B').first()
    if not p2:
        p2 = Product(
            id=generate_uuid(),
            name='Dimsum Udang Premium (Test Multi 2)',
            price=25000,
            sku='TEST-BUYER-02B',
            category='Steamed',
            stock_qty=30,
            is_active=True
        )
        db_session.add(p2)
    else:
        p2.stock_qty = 30

    db_session.commit()
    return p1, p2

def test_scenario_1_single_product_checkout_stock_deduction(client, product_single):
    """
    Skenario 1: Buyer checkout 1 varian produk (5 pcs).
    Ekspektasi: Stok awal 50 berkurang menjadi 45, transaksi stok tipe 'out' tercatat via channel 'web'.
    """
    prod_id = product_single.id
    prod_price = float(product_single.price)
    qty_to_buy = 5

    payload = {
        'customer': {
            'name': 'Buyer Skenario 1',
            'phone': '081211112222',
            'email': 'buyer1@dimsum.id'
        },
        'items': [
            {'product_id': prod_id, 'quantity': qty_to_buy}
        ],
        'order_type': 'pickup',
        'notes': 'Mohon disiapkan segera'
    }

    res = client.post('/api/orders', json=payload)
    assert res.status_code == 201
    data = res.json()['data']
    order = data['order']
    assert order['status'] == 'pending_payment'
    assert float(order['total_amount']) == float(prod_price * qty_to_buy)

    # 1. Verifikasi stok produk berkurang langsung di database
    reloaded_prod = db_session.query(Product).filter_by(id=prod_id).first()
    assert reloaded_prod.stock_qty == 50 - qty_to_buy
    assert reloaded_prod.stock_qty == 45

    # 2. Verifikasi transaksi inventory tercatat dengan channel 'web'
    txn = db_session.query(InventoryTransaction).filter_by(
        product_id=prod_id,
        reference_id=order['id'],
        type='out'
    ).first()
    assert txn is not None
    assert txn.quantity == qty_to_buy
    assert txn.channel == 'web'
    assert txn.reference_type == 'order'

def test_scenario_2_multi_product_checkout_atomic_deduction(client, product_pair):
    """
    Skenario 2: Buyer checkout beberapa varian sekaligus (keranjang belanja gabungan).
    Ekspektasi: Seluruh produk berkurang secara atomik sesuai kuantitas masing-masing.
    """
    p1, p2 = product_pair
    p1_id = p1.id
    p2_id = p2.id

    qty_p1 = 4
    qty_p2 = 6

    payload = {
        'customer': {
            'name': 'Buyer Keranjang Multi',
            'phone': '081233334444'
        },
        'items': [
            {'product_id': p1_id, 'quantity': qty_p1},
            {'product_id': p2_id, 'quantity': qty_p2}
        ],
        'order_type': 'pickup'
    }

    res = client.post('/api/orders', json=payload)
    assert res.status_code == 201
    order_id = res.json()['data']['order']['id']

    # Verifikasi kedua stok berkurang atomik
    reloaded_p1 = db_session.query(Product).filter_by(id=p1_id).first()
    reloaded_p2 = db_session.query(Product).filter_by(id=p2_id).first()
    assert reloaded_p1.stock_qty == 40 - qty_p1  # 40 - 4 = 36
    assert reloaded_p2.stock_qty == 30 - qty_p2  # 30 - 6 = 24

    # Verifikasi 2 log transaksi stok tercatat
    txns = db_session.query(InventoryTransaction).filter_by(reference_id=order_id).all()
    assert len(txns) == 2
    for t in txns:
        assert t.channel == 'web'
        assert t.type == 'out'

def test_scenario_3_insufficient_stock_prevents_checkout_and_no_deduction(client):
    """
    Skenario 3: Buyer memesan melebihi stok yang tersedia (stok = 3, pesan = 5).
    Ekspektasi: Request ditolak (HTTP 400), stok tidak berkurang sama sekali (tidak overselling).
    """
    limited_product = db_session.query(Product).filter_by(sku='TEST-BUYER-LIMIT').first()
    if not limited_product:
        limited_product = Product(
            id=generate_uuid(),
            name='Dimsum Sisa Sedikit',
            price=15000,
            sku='TEST-BUYER-LIMIT',
            stock_qty=3,
            is_active=True
        )
        db_session.add(limited_product)
        db_session.commit()
    else:
        limited_product.stock_qty = 3
        db_session.commit()

    prod_id = limited_product.id

    payload = {
        'customer': {'name': 'Buyer Kehabisan', 'phone': '081255556666'},
        'items': [{'product_id': prod_id, 'quantity': 5}]
    }

    res = client.post('/api/orders', json=payload)
    assert res.status_code == 400
    err_msg = res.json().get('error', '').lower()
    assert 'stok tidak mencukupi' in err_msg or 'insufficient stock' in err_msg

    # Stok tetap aman tidak berkurang
    reloaded = db_session.query(Product).filter_by(id=prod_id).first()
    assert reloaded.stock_qty == 3

    # Tidak ada transaksi keluar yang tercatat untuk attempt gagal ini
    txns = db_session.query(InventoryTransaction).filter_by(product_id=prod_id).count()
    assert txns == 0

def test_scenario_4_order_cancellation_restores_stock(client, product_single):
    """
    Skenario 4: Buyer memesan 4 pcs (stok berkurang 50 -> 46), namun kemudian pesanan dibatalkan/expired.
    Ekspektasi: Stok kembali dipulihkan (+4) menjadi 50, tercatat log transaksi masuk ('in').
    """
    prod_id = product_single.id

    res = client.post('/api/orders', json={
        'customer': {'name': 'Buyer Batal', 'phone': '081277778888'},
        'items': [{'product_id': prod_id, 'quantity': 4}],
        'order_type': 'pickup'
    })
    order_id = res.json()['data']['order']['id']

    # Cek stok saat pending payment
    p_pending = db_session.query(Product).filter_by(id=prod_id).first()
    assert p_pending.stock_qty == 46

    # Batalkan pesanan
    cancelled_order = OrderService.cancel_order(order_id, reason="Buyer membatalkan pesanan")
    assert cancelled_order.status == 'cancelled'

    # Verifikasi stok telah dipulihkan kembali ke 50
    p_restored = db_session.query(Product).filter_by(id=prod_id).first()
    assert p_restored.stock_qty == 50

    # Cek log transaksi 'in' sebagai pengembalian stok
    in_txn = db_session.query(InventoryTransaction).filter_by(
        reference_id=order_id,
        type='in'
    ).first()
    assert in_txn is not None
    assert in_txn.quantity == 4

def test_scenario_5_dashboard_summary_tracks_web_channel_stock_out(client, admin_headers, product_single):
    """
    Skenario 5: Verifikasi sinkronisasi dengan Ringkasan Dashboard Stok Admin.
    Ekspektasi: Dashboard menampilkan akumulasi pengeluaran stok kanal 'web' secara akurat.
    """
    prod_id = product_single.id

    # Checkout 3 pcs via web
    client.post('/api/orders', json={
        'customer': {'name': 'Buyer Web Sync', 'phone': '081299990000'},
        'items': [{'product_id': prod_id, 'quantity': 3}],
        'order_type': 'pickup'
    })

    # Panggil summary endpoint admin
    res_summary = client.get('/api/inventory/dashboard/summary', headers=admin_headers)
    assert res_summary.status_code == 200
    data = res_summary.json()['data']

    # Verifikasi distribusi kanal mencakup 'web'
    assert 'channel_distribution' in data
    web_pcs = data['channel_distribution'].get('web', 0)
    assert web_pcs >= 3
