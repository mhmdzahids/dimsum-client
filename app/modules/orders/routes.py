from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
import re
import logging
from app.shared.response import api_success, api_error
from app.modules.orders.service import OrderService
from app.core.security import admin_required, staff_or_admin_required
from app.core.limiter import rate_limit
logger = logging.getLogger(__name__)
orders_bp = APIRouter()
UUID_REGEX = re.compile('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

def is_order_authorized(order, req) -> bool:
    """Require an order header token, the authenticated owner, or internal role."""
    import hmac
    req_token = req.headers.get('X-Order-Token')
    if req_token and order.access_token:
        if hmac.compare_digest(str(order.access_token), str(req_token).strip()):
            return True
    auth_header = req.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1].strip()
        from app.modules.auth.service import AuthService
        payload = AuthService.decode_token(token)
        if payload:
            role = payload.get('role')
            user_id = payload.get('user_id')
            if role in ('admin', 'staff', 'checker', 'inventory'):
                return True
            if user_id and str(user_id) == str(order.customer_id):
                return True
    if not order.access_token:
        return False
    return False

@orders_bp.api_route('', methods=['POST'], dependencies=[Depends(rate_limit('5 per minute'))])
def create_order(request: Request):
    data = request.state.payload
    if not data or not data.get('items') or (not data.get('customer')):
        return api_error('Invalid request body or missing items/customer info', 400)
    customer_user_id = None
    if request.headers.get('Authorization'):
        from app.core.security import login_required
        customer_user_id = login_required(request)['user_id']
    try:
        order, paywuz_res = OrderService.create_order(customer_data=data['customer'], items=data['items'], notes=data.get('notes'), voucher_code=data.get('voucher_code'), pickup_time=data.get('pickup_time'), pickup_timestamp=data.get('pickup_timestamp'), order_type=data.get('order_type', 'pickup'), delivery_address=data.get('delivery_address'), customer_user_id=customer_user_id)
        return api_success(data={'order': order.to_dict(), 'paywuz': paywuz_res}, status=201, message='Order created successfully')
    except ValueError as e:
        return api_error(str(e), 400)
    except Exception as e:
        logger.exception('Internal error during order creation')
        return api_error('Internal server error during order creation. Please try again later.', 500)

@orders_bp.api_route('/{order_id}', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
def get_order(request: Request, order_id):
    if not UUID_REGEX.match(order_id):
        return api_error('Invalid order ID format', 400)
    order = OrderService.get_by_id(order_id)
    if not order:
        return api_error('Order not found', 404)
    if not is_order_authorized(order, request):
        return api_error('Akses ditolak. Token akses pesanan diperlukan atau tidak valid.', 403)
    if order.status == 'pending_payment':
        order = OrderService.sync_order_payment_status(order)
    order_dict = order.to_dict()
    if order.payment and order.payment.raw_webhook_payload and isinstance(order.payment.raw_webhook_payload, dict):
        creation = order.payment.raw_webhook_payload.get('paywuz_creation') or {}
        if creation.get('expiresAt'):
            order_dict['expires_at'] = creation.get('expiresAt')
    if order.status not in ['paid', 'fulfilling', 'completed']:
        order_dict['qr_token'] = None
    items_data = []
    for it in order.items:
        it_dict = it.to_dict()
        if it.product:
            it_dict['product_name'] = it.product.name
            it_dict['image_url'] = it.product.image_url
            it_dict['category'] = it.product.category
        items_data.append(it_dict)
    order_dict['items'] = items_data
    return api_success(data=order_dict)

@orders_bp.api_route('/{order_id}/sync-payment', methods=['POST'], dependencies=[Depends(rate_limit('5 per minute'))])
def sync_order_payment(request: Request, order_id):
    """
    Dedicated fallback endpoint for explicit manual refresh if customer clicks 'Refresh Status'.
    Strictly rate-limited to prevent API flooding.
    """
    if not UUID_REGEX.match(order_id):
        return api_error('Invalid order ID format', 400)
    order = OrderService.get_by_id(order_id)
    if not order:
        return api_error('Order not found', 404)
    if not is_order_authorized(order, request):
        return api_error('Akses ditolak. Token akses pesanan diperlukan atau tidak valid.', 403)
    if order.status == 'pending_payment':
        order = OrderService.sync_order_payment_status(order)
    return api_success(data=order.to_dict())

@orders_bp.api_route('', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def list_orders(request: Request):
    """
    Admin endpoint to view recent orders.
    """
    try:
        orders = OrderService.list_recent_orders(limit=50)
        results = []
        for o in orders:
            d = o.to_dict()
            items_list = []
            for it in o.items:
                it_dict = it.to_dict()
                if it.product:
                    it_dict['product_name'] = it.product.name
                    it_dict['current_stock'] = it.product.stock_qty
                items_list.append(it_dict)
            d['items'] = items_list
            results.append(d)
        return api_success(data=results)
    except Exception:
        logger.exception('Error listing admin orders')
        return api_error('Gagal memuat daftar pesanan', 500)

@orders_bp.api_route('/transactions', methods=['GET'], dependencies=[Depends(admin_required)])
def get_transactions(request: Request):
    """
    Super Admin / Owner endpoint: Retrieves comprehensive sales transactions
    across all channels (Web, POS Kasir, Shopee, TikTok, PO B2B) with KPIs and pagination.
    """
    page = int(request.query_params.get('page', 1))
    per_page = int(request.query_params.get('per_page', 15))
    channel = request.query_params.get('channel')
    search = request.query_params.get('search')
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    status = request.query_params.get('status')
    try:
        data = OrderService.get_transactions_history(page=page, per_page=per_page, channel=channel, search=search, start_date=start_date, end_date=end_date, status=status)
        return api_success(data=data)
    except Exception:
        logger.exception('Error getting transactions history')
        return api_error('Gagal memuat riwayat transaksi', 500)

@orders_bp.api_route('/check-qr/{qr_token}', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def check_order_qr(request: Request, qr_token):
    """
    Admin endpoint to preview order details via QR token before completing pickup.
    """
    try:
        order = OrderService.get_order_by_qr(qr_token)
        order_dict = order.to_dict()
        cust = order.customer
        raw_phone = order.customer_phone or (cust.phone if cust else '')
        raw_email = cust.email if cust and cust.email else ''
        order_dict['customer_phone'] = raw_phone if raw_phone and '@' not in raw_phone else '-'
        order_dict['customer_email'] = raw_email if raw_email and '@' in raw_email else raw_phone if raw_phone and '@' in raw_phone else '-'
        if not order_dict.get('customer_name') and cust and cust.full_name:
            order_dict['customer_name'] = cust.full_name
        items_list = []
        for it in order.items:
            it_dict = it.to_dict()
            if it.product:
                it_dict['product_name'] = it.product.name
                it_dict['current_stock'] = it.product.stock_qty
                it_dict['image_url'] = it.product.image_url
            items_list.append(it_dict)
        order_dict['items'] = items_list
        return api_success(data=order_dict)
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error checking QR order')
        return api_error('Gagal memeriksa kode QR pesanan', 500)

@orders_bp.api_route('/simulate-test', methods=['POST'], dependencies=[Depends(admin_required)])
def simulate_test_order(request: Request):
    """
    Admin test endpoint: quickly creates a paid order to test QR scanner and verify stock decrements.
    """
    data = request.state.payload or {}
    product_id = data.get('product_id')
    quantity = int(data.get('quantity', 1))
    customer_name = data.get('customer_name', 'Test Buyer')
    if not product_id:
        return api_error('ID Produk wajib dipilih', 400)
    try:
        order, product, stock_before, stock_after = OrderService.create_test_order(product_id=product_id, quantity=quantity, customer_name=customer_name)
        order_dict = order.to_dict()
        items_list = []
        for it in order.items:
            it_dict = it.to_dict()
            if it.product:
                it_dict['product_name'] = it.product.name
                it_dict['current_stock'] = it.product.stock_qty
            items_list.append(it_dict)
        order_dict['items'] = items_list
        return api_success(data={'order': order_dict, 'stock_test': {'product_id': product.id, 'product_name': product.name, 'stock_before': stock_before, 'stock_after': stock_after, 'decremented_by': quantity}}, status=201, message='Pesanan pengujian berhasil dibuat & stok telah dipotong!')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error creating test order')
        return api_error('Gagal membuat pesanan uji coba', 500)

@orders_bp.api_route('/verify', methods=['POST'], dependencies=[Depends(staff_or_admin_required), Depends(rate_limit('30 per minute'))])
def verify_pickup(request: Request):
    data = request.state.payload or {}
    qr_token = (data.get('qr_token') or '').strip()
    if not qr_token:
        return api_error('QR token wajib diisi', 400)
    try:
        staff_id = getattr(request.state, 'user_id', None)
        order = OrderService.verify_and_complete_pickup(qr_token, staff_id)
        order_dict = order.to_dict()
        items_list = []
        for it in order.items:
            it_dict = it.to_dict()
            if it.product:
                it_dict['product_name'] = it.product.name
                it_dict['current_stock'] = it.product.stock_qty
            items_list.append(it_dict)
        order_dict['items'] = items_list
        return api_success(data=order_dict, message='Pesanan berhasil diverifikasi dan diselesaikan. Stok tetap konsisten tanpa pemotongan ganda.')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error during pickup verification')
        return api_error('Terjadi kesalahan sistem saat memverifikasi pengambilan', 500)

@orders_bp.api_route('/{order_id}/qr.png', methods=['GET'])
def get_order_qr_image(request: Request, order_id):
    """
    Renders the order's pickup QR code directly as a PNG image.
    Enables customers opening the WhatsApp link to immediately view and scan the QR code.
    """
    if not UUID_REGEX.match(order_id):
        return api_error('Format ID pesanan tidak valid', 400)
    order = OrderService.get_by_id(order_id)
    if not order or not order.qr_token:
        return api_error('QR Code pesanan tidak ditemukan atau belum dibayar', 404)
    if not is_order_authorized(order, request):
        return api_error('Akses ditolak. Token akses pesanan diperlukan.', 403)
    from starlette.responses import Response
    from app.shared.whatsapp import WhatsAppService
    png_bytes = WhatsAppService.generate_qr_image_bytes(order.qr_token)
    return Response(png_bytes, media_type='image/png', headers={'Cache-Control': 'no-store'})

@orders_bp.api_route('/{order_id}/send-receipt', methods=['POST'], dependencies=[Depends(rate_limit('5 per minute'))])
def resend_order_receipt(request: Request, order_id):
    """
    Sends or resends order receipt and pickup QR code to the customer's WhatsApp.
    """
    if not UUID_REGEX.match(order_id):
        return api_error('Format ID pesanan tidak valid', 400)
    order = OrderService.get_by_id(order_id)
    if not order:
        return api_error('Pesanan tidak ditemukan', 404)
    if not is_order_authorized(order, request):
        return api_error('Akses ditolak. Token pesanan tidak valid.', 403)
    data = request.state.payload or {}
    phone = data.get('phone')
    try:
        res = OrderService.resend_order_whatsapp(order_id, phone=phone)
        if res.get('error'):
            return api_error(res['error'], 400, errors=res)
        return api_success(data=res, message='Receipt dan QR code berhasil dikirim ke WhatsApp')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception(f'Error resending WhatsApp receipt for order {order_id}')
        return api_error('Gagal mengirim receipt via WhatsApp', 500)

@orders_bp.api_route('/test-whatsapp', methods=['POST'], dependencies=[Depends(admin_required), Depends(rate_limit('10 per minute'))])
def test_whatsapp_connection(request: Request):
    """
    Admin test endpoint to verify OpenWA connectivity by sending a test message.
    """
    data = request.state.payload or {}
    phone = data.get('phone')
    message = data.get('message') or 'Halo! Ini adalah pesan uji coba dari Dimsum Store via OpenWA.'
    if not phone:
        return api_error('Nomor WhatsApp wajib diisi (contoh: 08123456789 atau 628123456789)', 400)
    from app.shared.whatsapp import WhatsAppService
    chat_id = WhatsAppService.format_phone_number(phone)
    if not chat_id:
        return api_error('Format nomor WhatsApp tidak valid', 400)
    res = WhatsAppService.send_text(chat_id, message)
    if res.get('success'):
        return api_success(data=res, message=f'Pesan uji coba berhasil dikirim ke {chat_id}')
    else:
        return api_error('Gagal mengirim pesan ke OpenWA', 502, errors=res)

@orders_bp.api_route('/pos', methods=['POST'], dependencies=[Depends(staff_or_admin_required), Depends(rate_limit('60 per minute'))])
def create_pos_order(request: Request):
    """
    Cashier Walk-In POS Order Creation Endpoint:
    Handles Cash (with change calc), QRIS (Paywuz), and Transfer.
    Atomically deducts stock with channel='offline' and logs cashier ID.
    """
    data = request.state.payload or {}
    items = data.get('items')
    if not items or not isinstance(items, list):
        return api_error('Daftar item belanja wajib diisi', 400)
    payment_method = data.get('payment_method')
    if not payment_method:
        return api_error('Metode pembayaran wajib dipilih (cash, qris, transfer)', 400)
    try:
        staff_id = getattr(request.state, 'user_id', None)
        order, payment_info = OrderService.create_pos_order(items=items, payment_method=payment_method, cashier_user_id=staff_id, customer_name=data.get('customer_name', ''), customer_phone=data.get('customer_phone'), order_type=data.get('order_type', 'dine_in'), cash_received=data.get('cash_received'), notes=data.get('notes'), bank_code=data.get('bank_code'))
        order_dict = order.to_dict()
        items_list = []
        for it in order.items:
            it_dict = it.to_dict()
            if it.product:
                it_dict['product_name'] = it.product.name
                it_dict['current_stock'] = it.product.stock_qty
            items_list.append(it_dict)
        order_dict['items'] = items_list
        return api_success(data={'order': order_dict, 'payment': payment_info}, status=201, message='Pesanan kasir berhasil diproses!')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error creating POS order')
        return api_error('Terjadi kesalahan saat memproses pesanan kasir', 500)

@orders_bp.api_route('/search-customer', methods=['GET'], dependencies=[Depends(staff_or_admin_required), Depends(rate_limit('30 per minute'))])
def search_customer_orders(request: Request):
    """
    Search customer orders by name, phone, or email for POS pickup verification.
    Returns list of pending/ready orders matching the search query.
    """
    query = request.query_params.get('q', '').strip()
    if not query or len(query) < 2:
        return api_error('Minimal 2 karakter untuk pencarian', 400)
    if len(query) > 100:
        return api_error('Query terlalu panjang', 400)
    try:
        results = OrderService.search_customer_for_pickup(query)
        return api_success(data=results, message=f'Ditemukan {len(results)} pesanan')
    except Exception:
        logger.exception('Error searching customer orders')
        return api_error('Gagal mencari pesanan', 500)

@orders_bp.api_route('/pending-alerts', methods=['GET'], dependencies=[Depends(staff_or_admin_required), Depends(rate_limit('60 per minute'))])
def get_pending_alerts(request: Request):
    """
    Lightweight POS cashier polling endpoint.
    Returns all paid web orders awaiting pickup — drives notification badge,
    audio chime, and browser desktop notification in AdminPOS.
    """
    try:
        results = OrderService.get_pending_alerts()
        return api_success(data={'count': len(results), 'orders': results}, message=f'{len(results)} pesanan menunggu disiapkan')
    except Exception:
        logger.exception('Error fetching pending alerts')
        return api_error('Gagal memuat notifikasi pesanan', 500)
