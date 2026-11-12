import html
import secrets
import logging
from app.core.db import db_session
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.models import Payment
from app.modules.payments.service import PaywuzService
from app.modules.products.models import Product
from app.modules.inventory.models import InventoryTransaction
from app.shared.utils import utc_now, generate_uuid, sanitize_customer_name, sanitize_text_field

logger = logging.getLogger(__name__)

DEFAULT_PACKAGING_FEE = 0.0
DEFAULT_DELIVERY_FEE = 10000.0

class OrderService:
    @staticmethod
    def search_customer_for_pickup(query: str):
        """
        Search orders by customer name, phone, email, or order ID.
        Filters relevant orders including paid, processing, completed, and pending.
        """
        search_like = f"%{query.strip()}%"
        
        from app.modules.auth.models import User
        
        orders = db_session.query(Order).outerjoin(User, Order.customer_id == User.id)\
            .filter(
                (Order.customer_name.ilike(search_like)) |
                (Order.customer_phone.ilike(search_like)) |
                (Order.id.ilike(search_like)) |
                (User.full_name.ilike(search_like)) | 
                (User.phone.ilike(search_like)) | 
                (User.email.ilike(search_like))
            )\
            .filter(Order.status.in_(['paid', 'processing', 'completed', 'pending_payment', 'pending']))\
            .order_by(Order.created_at.desc())\
            .limit(15)\
            .all()
            
        results = []
        for o in orders:
            u = o.customer
            name = o.customer_name or (u.full_name if u else 'Pelanggan')
            
            raw_phone = o.customer_phone or (u.phone if u else '')
            raw_email = (u.email if u and u.email else '')
            
            phone = raw_phone if (raw_phone and '@' not in raw_phone) else '-'
            email = raw_email if (raw_email and '@' in raw_email) else (raw_phone if (raw_phone and '@' in raw_phone) else '-')
            
            results.append({
                'id': o.id,
                'customer_name': name,
                'phone': phone,
                'email': email,
                'qr_token': o.qr_token or o.access_token or o.id,
                'status': o.status,
                'total_amount': float(o.total_amount or 0.0),
                'order_number': str(o.id)[:8].upper(),
                'pickup_time': o.pickup_time or 'Pick Up',
                'created_at': o.created_at.strftime('%d/%m/%Y %H:%M') if o.created_at else ''
            })
        return results

    @staticmethod
    def get_pending_alerts():
        """
        Lightweight endpoint for POS cashier polling.
        Returns all 'paid' web orders (order_type='pickup') that are awaiting pickup.
        Used to drive real-time notification badge and audio alert in AdminPOS.
        """
        from app.modules.auth.models import User
        
        orders = db_session.query(Order).outerjoin(User, Order.customer_id == User.id)\
            .filter(Order.status == 'paid')\
            .filter(Order.order_type.in_(['pickup', 'online']))\
            .order_by(Order.created_at.desc())\
            .limit(20)\
            .all()
        
        results = []
        for o in orders:
            u = o.customer
            name = o.customer_name or (u.full_name if u else 'Pelanggan')
            
            raw_phone = o.customer_phone or (u.phone if u else '')
            raw_email = (u.email if u and u.email else '')
            phone = raw_phone if (raw_phone and '@' not in raw_phone) else '-'
            email = raw_email if (raw_email and '@' in raw_email) else '-'
            
            # Build concise items summary for notification display
            items_summary_parts = []
            total_qty = 0
            for item in o.items:
                qty = item.quantity
                total_qty += qty
                pname = item.product.name if item.product else 'Item'
                items_summary_parts.append(f'{qty}x {pname}')
            items_summary = ', '.join(items_summary_parts[:3])
            if len(items_summary_parts) > 3:
                items_summary += f' +{len(items_summary_parts) - 3} lagi'
            
            results.append({
                'id': o.id,
                'order_number': str(o.id)[:8].upper(),
                'customer_name': name,
                'phone': phone,
                'email': email,
                'pickup_time': o.pickup_time or 'Hari ini',
                'total_amount': float(o.total_amount or 0.0),
                'items_summary': items_summary,
                'total_items': total_qty,
                'qr_token': o.qr_token or o.access_token or o.id,
                'created_at': o.created_at.strftime('%d/%m/%Y %H:%M') if o.created_at else '',
                'paid_at': o.paid_at.strftime('%H:%M') if o.paid_at else (
                    o.created_at.strftime('%H:%M') if o.created_at else ''
                ),
            })
        return results

    @classmethod
    def _restore_order_resources(cls, order):
        """
        Restores reserved product stock and voucher quota if an order is cancelled or expired.
        """
        from app.modules.vouchers.service import VoucherService
        try:
            for item in order.items:
                product = db_session.get(Product, item.product_id, with_for_update=True)
                if product:
                    if product.stock_offline is not None:
                        product.stock_offline += item.quantity
                    product.stock_qty = (product.stock_offline or 0) + (product.stock_online or 0) if (product.stock_offline is not None and product.stock_online is not None) else (product.stock_qty + item.quantity)
                    db_session.add(InventoryTransaction(
                        product_id=product.id,
                        type='in',
                        quantity=item.quantity,
                        reference_type='order',
                        reference_id=order.id,
                        stock_pool='offline'
                    ))
            if order.voucher_code:
                VoucherService.restore_voucher_usage(order.voucher_code)
        except Exception as e:
            logger.warning(f"Error restoring resources for order {order.id}: {e}")

    @classmethod
    def get_by_id(cls, order_id: str):
        order = db_session.get(Order, order_id)
        if not order:
            return None
            
        # Check if pending order has passed its expiration
        if order.status == 'pending_payment' and order.payment:
            expires_at = None
            if order.payment.raw_webhook_payload and isinstance(order.payment.raw_webhook_payload, dict):
                creation_info = order.payment.raw_webhook_payload.get('paywuz_creation') or {}
                exp_str = creation_info.get('expiresAt')
                if exp_str:
                    try:
                        from datetime import datetime
                        expires_at = datetime.fromisoformat(exp_str.replace('Z', '+00:00'))
                    except Exception:
                        pass
            if not expires_at and order.created_at:
                from datetime import timedelta
                # Fallback: 60 minutes after creation
                expires_at = order.created_at + timedelta(minutes=60)
                
            if expires_at:
                from app.shared.utils import utc_now
                current_time = utc_now()
                if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is not None:
                    from datetime import datetime, timezone
                    current_time = datetime.now(timezone.utc)
                if current_time > expires_at:
                    order.status = 'cancelled'
                    order.payment.status = 'failed'
                    cls._restore_order_resources(order)
                    try:
                        db_session.commit()
                    except Exception:
                        db_session.rollback()
                        
        return order

    @classmethod
    def validate_realtime_pickup(cls, pickup_str: str, pickup_timestamp=None) -> str:
        """
        Validates pickup time against real-world datetime (WIB = UTC+7) and store operating hours (08:00 - 22:00).
        """
        from datetime import datetime, timezone, timedelta
        import re

        if not pickup_str:
            return None

        raw_str = str(pickup_str).strip()
        if raw_str.lower() in ['pilih waktu pickup', '']:
            return None

        WIB = timezone(timedelta(hours=7))
        now_wib = datetime.now(timezone.utc).astimezone(WIB)

        # 1. If explicit timestamp is provided
        if pickup_timestamp is not None:
            try:
                ts = float(pickup_timestamp)
                if ts > 1e11:  # milliseconds
                    ts = ts / 1000.0
                target_dt = datetime.fromtimestamp(ts, tz=WIB)
                
                if target_dt.hour < 8 or target_dt.hour > 22 or (target_dt.hour == 22 and target_dt.minute > 0):
                    raise ValueError("Waktu pickup di luar jam operasional toko (08:00 - 22:00 WIB)")
                if target_dt < now_wib - timedelta(minutes=5):
                    raise ValueError("Waktu pickup yang dipilih sudah terlewat. Silakan pilih waktu yang akan datang.")
                if target_dt > now_wib + timedelta(days=7):
                    raise ValueError("Waktu pickup tidak boleh melebihi 7 hari ke depan.")
                return html.escape(raw_str, quote=True)
            except (ValueError, TypeError, OSError) as e:
                if "Waktu pickup" in str(e):
                    raise

        # 2. String parsing
        time_match = re.search(r'(\d{1,2})\s*:\s*(\d{2})', raw_str)
        if not time_match:
            raise ValueError("Format jam pickup tidak valid (contoh: 12:30)")

        hour = int(time_match.group(1))
        minute = int(time_match.group(2))

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Jam atau menit pickup tidak valid")

        if hour < 8 or hour > 22 or (hour == 22 and minute > 0):
            raise ValueError("Waktu pickup di luar jam operasional toko (08:00 - 22:00 WIB)")

        lower_str = raw_str.lower()
        if 'hari ini' in lower_str:
            target_dt = now_wib.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_dt < now_wib - timedelta(minutes=5):
                raise ValueError("Waktu pickup yang dipilih sudah terlewat. Silakan pilih waktu yang akan datang.")
        else:
            id_months = {
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mei': 5, 'may': 5,
                'jun': 6, 'jul': 7, 'agu': 8, 'aug': 8, 'sep': 9, 'okt': 10,
                'oct': 10, 'nov': 11, 'des': 12, 'dec': 12
            }
            date_match = re.search(r'(\d{1,2})\s+([A-Za-z]{3,4})(?:\s+(\d{4}))?', raw_str)
            if date_match:
                day = int(date_match.group(1))
                mon_str = date_match.group(2).lower()[:3]
                month = id_months.get(mon_str)
                year = int(date_match.group(3)) if date_match.group(3) else now_wib.year
                if month:
                    try:
                        target_dt = datetime(year, month, day, hour, minute, tzinfo=WIB)
                        if target_dt < now_wib - timedelta(minutes=5):
                            raise ValueError("Waktu pickup yang dipilih sudah terlewat. Silakan pilih waktu yang akan datang.")
                        if target_dt > now_wib + timedelta(days=7):
                            raise ValueError("Waktu pickup tidak boleh melebihi 7 hari ke depan.")
                    except ValueError as ve:
                        if "Waktu pickup" in str(ve):
                            raise

        return html.escape(raw_str, quote=True)

    @classmethod
    def create_order(cls, customer_data: dict, items: list, notes: str = None, voucher_code: str = None, pickup_time: str = None, pickup_timestamp = None, order_type: str = 'pickup', delivery_address: str = None, customer_user_id: str = None):
        from app.modules.auth.models import User
        from app.modules.auth.service import AuthService
        
        email = (customer_data.get('email') or '').strip()
        phone = (customer_data.get('phone') or '').strip()
        raw_name = (customer_data.get('name') or 'Guest').strip()
        clean_name = sanitize_customer_name(raw_name, default='Guest')
        name = html.escape(clean_name, quote=True)
        
        identifier = phone if phone else email
        if not identifier:
            raise ValueError("Phone or Email is required for checkout")
            
        if customer_user_id:
            customer = db_session.get(User, customer_user_id)
            if not customer or not customer.is_registered:
                raise ValueError('Customer account is not active')
        else:
            # Anonymous checkout must never attach to or change a registered identity
            # solely because the caller knows their email/phone.
            customer = User(email=f'guest-{generate_uuid()}@guest.invalid',
                            phone=None, full_name=name, role='customer',
                            password_hash='guest', is_registered=False)
            db_session.add(customer)
            db_session.flush()

        if not items or not isinstance(items, list) or len(items) == 0:
            raise ValueError("Keranjang belanja tidak boleh kosong")

        # --- Order Limit Validation ---
        from app.modules.settings.service import SettingsService
        order_limit = SettingsService.get_order_limit()
        total_qty = 0
        for item in items:
            try:
                total_qty += int(item.get('quantity', 0))
            except (ValueError, TypeError):
                pass
        if total_qty > order_limit:
            raise ValueError(f"Total item ({total_qty}) melebihi batas maksimum ({order_limit}) per transaksi")

        # Sort items by product_id to ensure consistent locking order (prevent DB deadlocks)
        sorted_items = sorted(items, key=lambda x: str(x.get('product_id', '')))

        # Fixed server-calculated packaging fee (never trusted from client)
        total_amount = DEFAULT_PACKAGING_FEE
        order_items_to_add = []
        stock_deductions = []
        
        for item in sorted_items:
            product_id = item.get('product_id')
            # Row-level lock on product
            product = db_session.get(Product, product_id, with_for_update=True)
            if not product:
                raise ValueError(f"Product {product_id} not found")
            if not product.is_active:
                raise ValueError(f"Product '{product.name}' is currently not available")
            
            try:
                qty = int(item.get('quantity', 0))
            except (ValueError, TypeError):
                raise ValueError(f"Invalid quantity for {product.name}")
                
            if qty <= 0:
                raise ValueError(f"Quantity for {product.name} must be greater than 0")
            if qty > 500:
                raise ValueError(f"Quantity for {product.name} exceeds maximum limit")
            avail_offline = product.stock_offline if product.stock_offline is not None else product.stock_qty
            if avail_offline < qty:
                raise ValueError(f"Insufficient stock for '{product.name}'. Available: {avail_offline}")
                
            unit_price = float(product.price)
            total_amount += unit_price * qty
            
            # Atomic stock deduction under row lock (prevents overselling)
            if product.stock_offline is not None:
                product.stock_offline -= qty
            product.stock_qty = (product.stock_offline or 0) + (product.stock_online or 0) if (product.stock_offline is not None and product.stock_online is not None) else (product.stock_qty - qty)
            
            order_items_to_add.append(OrderItem(
                product_id=product.id,
                quantity=qty,
                unit_price=unit_price
            ))
            stock_deductions.append((product.id, qty))
            
        # --- Notes Validation & Sanitization (Never Trust Front-End) ---
        sanitized_notes = None
        if notes is not None:
            if not isinstance(notes, str):
                raise ValueError("Catatan pesanan harus berupa teks")
            sanitized_notes = sanitize_text_field(notes, max_length=150)
            if sanitized_notes:
                sanitized_notes = html.escape(sanitized_notes, quote=True)

        # --- Fulfillment Type & Address/Pickup Validation ---
        sanitized_pickup = None
        sanitized_delivery_address = None
        is_delivery = (str(order_type or '').strip().lower() == 'delivery')

        if is_delivery:
            order_type = 'delivery'
            if not delivery_address or len(str(delivery_address).strip()) < 5:
                raise ValueError("Alamat pengiriman wajib diisi lengkap untuk pesanan delivery (minimal 5 karakter)")
            address_cleaned = sanitize_text_field(delivery_address, max_length=500)
            sanitized_delivery_address = html.escape(address_cleaned, quote=True)
            total_amount += DEFAULT_DELIVERY_FEE
        else:
            order_type = 'pickup'
            if pickup_time is not None:
                if not isinstance(pickup_time, str):
                    raise ValueError("Format waktu pickup harus berupa teks")
                sanitized_pickup = cls.validate_realtime_pickup(pickup_time, pickup_timestamp)

        # --- Server-side Atomic Voucher Validation & Row-Level Lock ---
        voucher_discount = 0.0
        applied_voucher_code = None
        if voucher_code:
            from app.modules.vouchers.service import VoucherService
            v_obj, voucher_res = VoucherService.lock_and_apply_voucher(voucher_code, total_amount)
            applied_voucher_code = v_obj.code
            voucher_discount = float(voucher_res['discount'])

        net_total = max(0.0, total_amount - voucher_discount)

        access_token = secrets.token_urlsafe(32)
        new_order = Order(
            customer_id=customer.id,
            total_amount=net_total,
            status='pending_payment',
            notes=sanitized_notes,
            order_type=order_type,
            delivery_address=sanitized_delivery_address,
            pickup_time=sanitized_pickup,
            voucher_code=applied_voucher_code,
            voucher_discount=voucher_discount,
            access_token=access_token,
            customer_phone=phone if phone else None,
            customer_name=clean_name
        )
        
        db_session.add(new_order)
        db_session.flush()
        
        for oi in order_items_to_add:
            oi.order_id = new_order.id
            db_session.add(oi)

        for prod_id, qty in stock_deductions:
            db_session.add(InventoryTransaction(
                product_id=prod_id,
                type='out',
                quantity=qty,
                reference_type='order',
                reference_id=new_order.id,
                channel='web',
                stock_pool='offline',
                created_by=customer.id
            ))
            
        # Create Paywuz QRIS
        try:
            c_name = customer.full_name or new_order.customer_name or name or 'Pelanggan Dimsum'
            c_phone = customer.phone or new_order.customer_phone or phone or '081234567890'
            c_email = customer.email if (customer.email and '@guest.invalid' not in customer.email) else (email or 'customer@makandimsum.com')
            paywuz_res = PaywuzService.create_qris_transaction(
                new_order.id,
                net_total,
                customer_name=c_name,
                phone=c_phone,
                email=c_email
            )
            
            # Ensure expiresAt is guaranteed in response
            if not paywuz_res.get('expiresAt'):
                from datetime import timedelta
                paywuz_res['expiresAt'] = (new_order.created_at + timedelta(minutes=60)).isoformat() + 'Z'
                
            payment_record = Payment(
                order_id=new_order.id,
                gateway='paywuz',
                gateway_ref_id=paywuz_res.get('id'),
                status='pending',
                raw_webhook_payload={'paywuz_creation': paywuz_res}
            )
            db_session.add(payment_record)
            db_session.commit()
            
            return new_order, paywuz_res
            
        except Exception as e:
            db_session.rollback()
            raise e

    @classmethod
    def handle_payment_webhook(cls, identifier: str, status: str, payload: dict):
        # 1. Look up by Order ID
        order = cls.get_by_id(identifier)
        payment = None
        
        if order:
            payment = db_session.query(Payment).filter_by(order_id=order.id).first()
        else:
            # 2. Look up by Paywuz gateway transaction ID
            payment = db_session.query(Payment).filter(
                (Payment.gateway_ref_id == identifier) | (Payment.order_id == identifier)
            ).first()
            if payment:
                order = payment.order
                
        if not order:
            raise ValueError(f"Order not found for identifier: {identifier}")
            
        if not payment:
            raise ValueError("Payment record not found")
            
        order = db_session.get(Order, order.id, with_for_update=True, populate_existing=True)
        payment = db_session.get(Payment, payment.id, with_for_update=True, populate_existing=True)
        payment.raw_webhook_payload = payload
        
        if payment.status == 'success':
            return order
            
        if status and status.lower() in ['success', 'settlement', 'settled', 'paid', 'capture']:
            payment.status = 'success'
            order.status = 'paid'
            order.paid_at = utc_now()
            # 256-bit cryptographically secure random token (43 chars)
            if not order.qr_token:
                order.qr_token = secrets.token_urlsafe(32)
            db_session.commit()

            # Send WhatsApp receipt and QR code to customer
            try:
                from app.shared.whatsapp import WhatsAppService
                WhatsAppService.send_order_receipt_and_qr(order)
            except Exception as e:
                logger.error(f"Failed to send WhatsApp receipt after webhook for order {order.id}: {e}")

            return order
            
        elif status and status.lower() in ['failed', 'expired', 'cancelled']:
            if order.status != 'cancelled':
                payment.status = 'failed'
                order.status = 'cancelled'
                cls._restore_order_resources(order)
            
        db_session.commit()
        return order

    @classmethod
    def sync_order_payment_status(cls, order):
        """
        Polls Paywuz API in real-time to check if a pending order has been settled.
        Runs when the customer is on the OrderStatus page or clicks Refresh Status.
        """
        if not order or order.status != 'pending_payment':
            return order

        payment = db_session.query(Payment).filter_by(order_id=order.id).first()
        if not payment:
            return order

        from app.modules.payments.service import PaywuzService
        tx_data = None
        try:
            if payment.gateway_ref_id:
                tx_data = PaywuzService.get_transaction(payment.gateway_ref_id)
                
            if not tx_data:
                tx_data = PaywuzService.get_transaction(order.id)
        except Exception as e:
            logger.warning(f"Manual payment inquiry to Paywuz failed: {e}")
            return order

        if tx_data and isinstance(tx_data, dict):
            status = tx_data.get('status', '')
            if status and status.lower() in ['success', 'settlement', 'settled', 'paid', 'capture']:
                payment.status = 'success'
                payment.raw_webhook_payload = tx_data
                order.status = 'paid'
                order.paid_at = utc_now()
                if not order.qr_token:
                    order.qr_token = secrets.token_urlsafe(32)
                db_session.commit()

                # Send WhatsApp receipt and QR code to customer
                try:
                    from app.shared.whatsapp import WhatsAppService
                    WhatsAppService.send_order_receipt_and_qr(order)
                except Exception as e:
                    logger.error(f"Failed to send WhatsApp receipt after payment sync for order {order.id}: {e}")

                return order
            elif status and status.lower() in ['failed', 'expired', 'cancelled']:
                if order.status != 'cancelled':
                    payment.status = 'failed'
                    order.status = 'cancelled'
                    cls._restore_order_resources(order)
                    db_session.commit()
                    return order

        return order

    @classmethod
    def get_transactions_history(
        cls,
        page: int = 1,
        per_page: int = 15,
        channel: str = None,
        search: str = None,
        start_date: str = None,
        end_date: str = None,
        status: str = None
    ):
        """
        Unified transactions aggregator for Super Admin / Owner.
        Combines web orders, POS cashier orders, and multi-channel stock-out sales (Shopee, TikTok, PO B2B).
        Includes comprehensive metrics and customer contact info.
        """
        from datetime import datetime, timezone, timedelta
        from app.modules.inventory.models import InventoryTransaction

        # 1. Fetch Orders
        order_query = db_session.query(Order).order_by(Order.created_at.desc())
        
        all_transactions = []

        # Process orders
        orders = order_query.all()
        for o in orders:
            is_pos = o.order_type in ('direct', 'dine_in', 'takeaway')
            ord_channel = 'offline' if is_pos else 'web'

            buyer_name = o.customer_name or (o.customer.full_name if o.customer else 'Pelanggan')
            buyer_phone = o.customer_phone or (o.customer.phone if o.customer else '')
            if not buyer_phone and o.customer and o.customer.email and '@' not in o.customer.email:
                buyer_phone = o.customer.email

            items_data = []
            total_qty = 0
            for it in (o.items or []):
                p_name = it.product.name if it.product else f"Produk #{it.product_id}"
                unit_p = float(it.unit_price or 0.0)
                sub_p = float(it.quantity * unit_p)
                total_qty += it.quantity
                items_data.append({
                    'product_id': it.product_id,
                    'product_name': p_name,
                    'quantity': it.quantity,
                    'unit_price': unit_p,
                    'subtotal': sub_p
                })

            pay_method = 'QRIS'
            if o.payment:
                pay_method = (o.payment.gateway or 'QRIS').upper()
            elif is_pos:
                if o.notes and 'transfer' in o.notes.lower():
                    pay_method = 'TRANSFER'
                elif o.notes and 'qris' in o.notes.lower():
                    pay_method = 'QRIS'
                else:
                    pay_method = 'CASH'

            all_transactions.append({
                'id': o.id,
                'source': 'order',
                'order_number': str(o.id)[:8].upper(),
                'buyer_name': buyer_name,
                'buyer_phone': buyer_phone,
                'channel': ord_channel,
                'channel_label': 'POS Kasir Toko' if ord_channel == 'offline' else 'Web Store',
                'items': items_data,
                'total_quantity': total_qty,
                'total_amount': float(o.total_amount or 0.0),
                'status': o.status,
                'payment_method': pay_method,
                'notes': o.notes or '',
                'created_at': o.created_at.isoformat() if o.created_at else None,
                '_sort_key': o.created_at or datetime.min
            })

        # Process manual inventory transactions (Shopee, TikTok, PO B2B, Offline)
        manual_txns = db_session.query(InventoryTransaction).filter(
            InventoryTransaction.type == 'out',
            InventoryTransaction.reference_type == 'manual',
            InventoryTransaction.channel.in_(['shopee', 'tiktok', 'po_b2b', 'offline'])
        ).order_by(InventoryTransaction.created_at.desc()).all()

        for mt in manual_txns:
            ch = mt.channel or 'other'
            label_map = {
                'shopee': 'Shopee',
                'tiktok': 'TikTok Shop',
                'po_b2b': 'PO B2B (Mitra)',
                'offline': 'Offline / Event'
            }
            channel_label = label_map.get(ch, ch.upper())
            
            p_name = mt.product.name if mt.product else f"Produk #{mt.product_id}"
            unit_p = float(mt.product.price) if (mt.product and mt.product.price) else 0.0
            sub_p = float(unit_p * mt.quantity)

            buyer_name = f"Pembeli {channel_label}"
            buyer_phone = ''
            if mt.notes:
                notes_str = mt.notes.strip()
                if 'buyer:' in notes_str.lower() or 'nama:' in notes_str.lower():
                    buyer_name = notes_str
                else:
                    buyer_name = f"{channel_label} ({notes_str[:30]})"

            all_transactions.append({
                'id': mt.id,
                'source': 'stock_out',
                'order_number': f"STK-{str(mt.id)[:6].upper()}",
                'buyer_name': buyer_name,
                'buyer_phone': buyer_phone,
                'channel': ch,
                'channel_label': channel_label,
                'items': [{
                    'product_id': mt.product_id,
                    'product_name': p_name,
                    'quantity': mt.quantity,
                    'unit_price': unit_p,
                    'subtotal': sub_p
                }],
                'total_quantity': mt.quantity,
                'total_amount': sub_p,
                'status': 'completed',
                'payment_method': channel_label,
                'notes': mt.notes or '',
                'created_at': mt.created_at.isoformat() if mt.created_at else None,
                '_sort_key': mt.created_at or datetime.min
            })

        # Sort all transactions descending by date
        all_transactions.sort(key=lambda x: x['_sort_key'], reverse=True)

        # Filters
        filtered = all_transactions

        # Channel filter
        if channel and channel != 'all':
            filtered = [t for t in filtered if t['channel'] == channel]

        # Status filter
        if status and status != 'all':
            filtered = [t for t in filtered if t['status'] == status]

        # Search filter
        if search and search.strip():
            kw = search.strip().lower()
            filtered = [
                t for t in filtered
                if kw in t['buyer_name'].lower()
                or (t['buyer_phone'] and kw in t['buyer_phone'].lower())
                or kw in t['order_number'].lower()
                or any(kw in it['product_name'].lower() for it in t['items'])
            ]

        # Date range filter
        if start_date:
            try:
                s_dt = datetime.fromisoformat(start_date)
                filtered = [t for t in filtered if t['_sort_key'] >= s_dt]
            except Exception:
                pass
        if end_date:
            try:
                e_dt = datetime.fromisoformat(end_date)
                e_dt = e_dt.replace(hour=23, minute=59, second=59)
                filtered = [t for t in filtered if t['_sort_key'] <= e_dt]
            except Exception:
                pass

        # Calculate KPIs
        successful_txns = [t for t in filtered if t['status'] in ('paid', 'completed')]
        total_revenue = sum(t['total_amount'] for t in successful_txns)
        total_items_sold = sum(t['total_quantity'] for t in successful_txns)
        
        now_utc = datetime.now(timezone.utc)
        today_wib = (now_utc + timedelta(hours=7)).date()
        today_successful = [
            t for t in successful_txns
            if t['_sort_key'] and (t['_sort_key'] + timedelta(hours=7)).date() == today_wib
        ]
        today_revenue = sum(t['total_amount'] for t in today_successful)
        today_count = len(today_successful)

        # Pagination
        total_records = len(filtered)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_data = filtered[start_idx:end_idx]

        for item in paginated_data:
            item.pop('_sort_key', None)

        total_pages = (total_records + per_page - 1) // per_page if per_page > 0 else 1

        return {
            'transactions': paginated_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_records': total_records,
                'total_pages': total_pages
            },
            'kpi': {
                'total_revenue': total_revenue,
                'total_transactions': len(successful_txns),
                'total_items_sold': total_items_sold,
                'today_revenue': today_revenue,
                'today_count': today_count
            }
        }

    @classmethod
    def list_recent_orders(cls, limit: int = 50):
        """
        List recent orders for admin dashboard.
        """
        return db_session.query(Order).order_by(Order.created_at.desc()).limit(limit).all()

    @classmethod
    def get_order_by_qr(cls, qr_token: str) -> Order:
        """
        Preview order details using its QR token without modifying order status.
        Supports lookup via QR token, access token, or order ID for seamless POS customer lookup.
        """
        if not qr_token or len(qr_token.strip()) < 8:
            raise ValueError("Kode token atau ID pesanan tidak valid")
        clean_token = qr_token.strip()
        order = db_session.query(Order).filter(
            (Order.qr_token == clean_token) |
            (Order.access_token == clean_token) |
            (Order.id == clean_token)
        ).first()
        if not order:
            raise ValueError("Pesanan dengan kode ini tidak ditemukan")
        return order

    @classmethod
    def create_test_order(cls, product_id: str, quantity: int = 1, customer_name: str = "Test Buyer"):
        """
        Creates an instant paid order for testing cashier QR scanning and verifying stock decrements.
        Uses the same atomic row-locking mechanism as standard order creation.
        """
        from app.modules.products.models import Product
        from app.modules.auth.models import User
        from app.modules.orders.models import OrderItem
        from app.modules.inventory.models import InventoryTransaction
        import secrets

        if quantity <= 0:
            raise ValueError("Jumlah item minimal 1")

        # 1. Lock product and verify stock
        product = db_session.query(Product).with_for_update().filter(Product.id == product_id).first()
        if not product:
            raise ValueError("Produk tidak ditemukan")

        stock_before = product.stock_qty
        avail_offline = product.stock_offline if product.stock_offline is not None else product.stock_qty
        if avail_offline < quantity:
            raise ValueError(f"Stok tidak mencukupi untuk '{product.name}'. Tersedia: {avail_offline}")

        # Deduct stock atomically
        if product.stock_offline is not None:
            product.stock_offline -= quantity
        product.stock_qty = (product.stock_offline or 0) + (product.stock_online or 0) if (product.stock_offline is not None and product.stock_online is not None) else (product.stock_qty - quantity)
        stock_after = product.stock_qty

        # 2. Get or create test user
        test_user = db_session.query(User).filter(User.email == 'testbuyer@dimsum.id').first()
        if not test_user:
            test_user = User(
                email='testbuyer@dimsum.id',
                password_hash='guest_not_applicable',
                full_name=customer_name or 'Test Buyer',
                role='customer',
                is_registered=False
            )
            db_session.add(test_user)
            db_session.flush()

        # 3. Create order in 'paid' status directly with qr_token
        order_id = generate_uuid()
        qr_token = secrets.token_urlsafe(24)
        access_token = secrets.token_urlsafe(32)
        unit_price = float(product.price)
        total_amount = unit_price * quantity

        new_order = Order(
            id=order_id,
            customer_id=test_user.id,
            status='paid',
            total_amount=total_amount,
            qr_token=qr_token,
            access_token=access_token,
            pickup_time="Hari ini, Tes Kasir",
            paid_at=utc_now(),
            notes="Pesanan Uji Coba Kasir & Stok"
        )
        db_session.add(new_order)

        item = OrderItem(
            order_id=order_id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price
        )
        db_session.add(item)

        inv_tx = InventoryTransaction(
            product_id=product.id,
            quantity=quantity,
            type='out',
            reference_type='order',
            reference_id=order_id,
            channel='web',
            created_by=test_user.id
        )
        db_session.add(inv_tx)

        try:
            db_session.commit()
            return new_order, product, stock_before, stock_after
        except Exception:
            db_session.rollback()
            raise

    @classmethod
    def create_pos_order(
        cls,
        items: list,
        payment_method: str,
        cashier_user_id: str,
        customer_name: str = '',
        customer_phone: str = None,
        order_type: str = 'dine_in',
        cash_received: float = None,
        notes: str = None,
        bank_code: str = None
    ):
        """
        Creates a walk-in POS order at the cashier counter.
        - Supports cash (with cash received and change calculation), QRIS (via Paywuz dynamic QR), and transfer.
        - Deducts stock atomically with FIFO ledger and records channel='offline'.
        - Prevents employee fraud by recording cashier_user_id and tying every sale to inventory.
        """
        from app.modules.auth.models import User
        from app.modules.auth.service import AuthService
        from app.modules.payments.models import Payment
        from app.modules.payments.service import PaywuzService

        if not items or not isinstance(items, list) or len(items) == 0:
            raise ValueError("Keranjang belanja kasir tidak boleh kosong")

        clean_payment_method = (payment_method or '').lower().strip()
        if clean_payment_method not in ('cash', 'qris', 'transfer'):
            raise ValueError("Metode pembayaran harus berupa 'cash', 'qris', atau 'transfer'")

        clean_order_type = (order_type or 'direct').lower().strip()
        if clean_order_type not in ('direct', 'takeaway', 'dine_in'):
            clean_order_type = 'direct'

        clean_customer_name = (customer_name or '').strip()[:100]
        clean_phone = (customer_phone or '').strip() if customer_phone else None

        # 1. Resolve or create customer account
        customer = None
        if clean_phone:
            customer = db_session.query(User).filter(User.phone == clean_phone).first()
        if not customer:
            pos_email = f"walkin_{clean_phone if clean_phone else 'cashier'}@dimsum.id"
            customer = db_session.query(User).filter(User.email == pos_email).first()
            if not customer:
                random_pw = secrets.token_hex(24)
                customer = User(
                    email=pos_email,
                    phone=clean_phone,
                    password_hash=f"pos_{AuthService.hash_password(random_pw)}",
                    full_name=clean_customer_name,
                    role='customer',
                    is_registered=False
                )
                db_session.add(customer)
                db_session.flush()

        # 2. Sort items by product_id to ensure consistent locking order (prevent deadlocks)
        sorted_items = sorted(items, key=lambda x: str(x.get('product_id', '')))
        
        total_amount = 0.0
        order_items_to_add = []

        for item in sorted_items:
            product_id = item.get('product_id')
            product = db_session.get(Product, product_id, with_for_update=True)
            if not product:
                raise ValueError(f"Produk dengan ID {product_id} tidak ditemukan")
            if not product.is_active:
                raise ValueError(f"Produk '{product.name}' sedang tidak aktif")

            try:
                qty = int(item.get('quantity', 0))
            except (ValueError, TypeError):
                raise ValueError(f"Jumlah untuk {product.name} tidak valid")

            if qty <= 0:
                raise ValueError(f"Jumlah untuk {product.name} harus lebih dari 0")
            avail_offline = product.stock_offline if product.stock_offline is not None else product.stock_qty
            if avail_offline < qty:
                raise ValueError(f"Stok tidak mencukupi untuk '{product.name}'. Tersedia: {avail_offline} pcs")

            unit_price = float(product.price)
            item_total = unit_price * qty
            total_amount += item_total

            order_items_to_add.append({
                'product': product,
                'quantity': qty,
                'unit_price': unit_price
            })

        # 3. Create Order
        order_id = generate_uuid()
        qr_token = secrets.token_urlsafe(24)
        access_token = secrets.token_urlsafe(32)
        now = utc_now()

        order_status = 'completed' if clean_payment_method == 'cash' else 'pending_payment'
        paid_at = now if order_status == 'completed' else None
        completed_at = now if order_status == 'completed' else None

        new_order = Order(
            id=order_id,
            customer_id=customer.id,
            status=order_status,
            total_amount=total_amount,
            qr_token=qr_token,
            access_token=access_token,
            customer_name=clean_customer_name,
            customer_phone=clean_phone,
            order_type=clean_order_type,
            pickup_time='Kasir Langsung (Beli di Tempat)',
            notes=(notes or '').strip()[:250] if notes else None,
            created_at=now,
            paid_at=paid_at,
            completed_at=completed_at
        )
        db_session.add(new_order)

        # 4. Attach Order Items and deduct stock atomically
        for it in order_items_to_add:
            order_item = OrderItem(
                id=generate_uuid(),
                order_id=order_id,
                product_id=it['product'].id,
                quantity=it['quantity'],
                unit_price=it['unit_price']
            )
            db_session.add(order_item)

            # Deduct product stock
            if it['product'].stock_offline is not None:
                it['product'].stock_offline -= it['quantity']
            it['product'].stock_qty = (it['product'].stock_offline or 0) + (it['product'].stock_online or 0) if (it['product'].stock_offline is not None and it['product'].stock_online is not None) else (it['product'].stock_qty - it['quantity'])

            # Record Inventory Transaction out
            inv_tx = InventoryTransaction(
                id=generate_uuid(),
                product_id=it['product'].id,
                quantity=it['quantity'],
                type='out',
                reference_type='order',
                reference_id=order_id,
                channel='offline',
                stock_pool='offline',
                notes=f"POS Kasir ({clean_order_type}) - Bayar: {clean_payment_method.upper()}",
                created_by=cashier_user_id,
                created_at=now
            )
            db_session.add(inv_tx)

        # 5. Handle Payment Record & Calculation
        payment_info = {
            'payment_method': clean_payment_method,
            'total_amount': total_amount
        }

        if clean_payment_method == 'cash':
            try:
                cash_val = float(cash_received) if cash_received is not None else 0.0
            except (ValueError, TypeError):
                raise ValueError("Nominal uang tunai yang diterima tidak valid")

            if cash_val < total_amount:
                raise ValueError(f"Uang tunai diterima (Rp{int(cash_val):,}) kurang dari total belanja (Rp{int(total_amount):,})")

            cash_change = cash_val - total_amount
            payment_info['cash_received'] = cash_val
            payment_info['cash_change'] = cash_change

            payment = Payment(
                id=generate_uuid(),
                order_id=order_id,
                gateway='cash',
                gateway_ref_id=f"CASH-{order_id[:8].upper()}",
                status='success',
                raw_webhook_payload={
                    'cash_received': cash_val,
                    'cash_change': cash_change,
                    'cashier_id': cashier_user_id,
                    'type': 'pos_cash'
                },
                created_at=now
            )
            db_session.add(payment)

        elif clean_payment_method == 'qris':
            paywuz_res = PaywuzService.create_qris_transaction(order_id, total_amount)
            payment_info['paywuz'] = paywuz_res

            payment = Payment(
                id=generate_uuid(),
                order_id=order_id,
                gateway='paywuz',
                gateway_ref_id=paywuz_res.get('id'),
                status='pending',
                raw_webhook_payload={
                    'paywuz_creation': paywuz_res,
                    'cashier_id': cashier_user_id,
                    'type': 'pos_qris'
                },
                created_at=now
            )
            db_session.add(payment)

        elif clean_payment_method == 'transfer':
            target_bank = (bank_code or 'BNIVA').upper().strip()
            if not target_bank.endswith('VA') and target_bank != 'VA':
                target_bank = f"{target_bank}VA"

            paywuz_res = PaywuzService.create_va_transaction(order_id, total_amount, bank_code=target_bank)
            payment_info['paywuz'] = paywuz_res

            payment = Payment(
                id=generate_uuid(),
                order_id=order_id,
                gateway='paywuz',
                gateway_ref_id=paywuz_res.get('id'),
                status='pending',
                raw_webhook_payload={
                    'paywuz_creation': paywuz_res,
                    'cashier_id': cashier_user_id,
                    'type': 'pos_transfer',
                    'bank_code': target_bank
                },
                created_at=now
            )
            db_session.add(payment)

        try:
            db_session.commit()
            
            if clean_phone and order_status == 'completed':
                try:
                    from app.shared.whatsapp import WhatsAppService
                    WhatsAppService.send_order_receipt_and_qr(new_order, force_phone=clean_phone)
                except Exception:
                    pass

            return new_order, payment_info
        except Exception:
            db_session.rollback()
            raise

    @classmethod
    def verify_and_complete_pickup(cls, qr_token: str, staff_user_id: str = None):
        """
        Atomic verification by cashier: validates QR token and marks order completed.
        Stock was already deducted and secured at order creation time.
        """
        if not qr_token or len(qr_token.strip()) < 8:
            raise ValueError("Kode token atau ID pesanan tidak valid")
            
        clean_token = qr_token.strip()
        order = db_session.query(Order).filter(
            (Order.qr_token == clean_token) |
            (Order.access_token == clean_token) |
            (Order.id == clean_token)
        ).with_for_update(of=Order).populate_existing().first()
        
        if not order:
            raise ValueError("Pesanan dengan kode ini tidak ditemukan")
            
        if order.status == 'completed':
            raise ValueError("Pesanan ini sudah pernah diambil (status: Selesai)")
            
        if order.status != 'paid':
            raise ValueError(f"Pesanan belum siap diambil (status saat ini: {order.status})")
            
        try:
            order.status = 'completed'
            order.completed_at = utc_now()
            db_session.commit()
            return order
        except Exception:
            db_session.rollback()
            raise

    @classmethod
    def resend_order_whatsapp(cls, order_id: str, phone: str = None):
        """
        Manually triggers sending order receipt and pickup QR code via WhatsApp.
        """
        order = cls.get_by_id(order_id)
        if not order:
            raise ValueError("Pesanan tidak ditemukan")
        if order.status not in ['paid', 'fulfilling', 'completed']:
            raise ValueError(f"Receipt dan QR hanya dapat dikirim untuk pesanan yang sudah dibayar (status: {order.status})")

        from app.shared.whatsapp import WhatsAppService
        return WhatsAppService.send_order_receipt_and_qr(order, force_phone=phone)

    @classmethod
    def cancel_order(cls, order_id: str, reason: str = None):
        """
        Cancels an order, releases reserved stock and restores vouchers.
        """
        order = db_session.get(Order, order_id, with_for_update=True, populate_existing=True)
        if not order:
            raise ValueError(f"Pesanan tidak ditemukan: {order_id}")
        if order.status == 'cancelled':
            return order
        if order.status in ['completed']:
            raise ValueError("Tidak dapat membatalkan pesanan yang sudah selesai")
        
        order.status = 'cancelled'
        if order.payment:
            order.payment.status = 'failed'
        cls._restore_order_resources(order)
        db_session.commit()
        return order

