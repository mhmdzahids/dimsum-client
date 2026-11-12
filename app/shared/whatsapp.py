import re
import io
import base64
import logging
import requests
from datetime import datetime, timezone, timedelta
import qrcode
from app.core.config import Config
from app.shared.utils import sanitize_customer_name

logger = logging.getLogger(__name__)

class WhatsAppService:
    WIB = timezone(timedelta(hours=7))
    _cached_session_id = None

    @classmethod
    def get_session_id(cls) -> str:
        """
        Returns the resolved session UUID. If Config.OPENWA_SESSION_ID is a name (e.g. 'makan-dimsum-indonesia'),
        queries /api/sessions and automatically resolves it to its actual UUID.
        """
        if cls._cached_session_id:
            return cls._cached_session_id

        raw_id = (Config.OPENWA_SESSION_ID or '').strip()
        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
        if uuid_pattern.match(raw_id):
            cls._cached_session_id = raw_id
            return raw_id

        # Query /api/sessions to resolve by name
        endpoint = f"{Config.OPENWA_API_URL}/api/sessions"
        try:
            res = requests.get(endpoint, headers=cls._get_headers(), timeout=10, allow_redirects=False)
            if res.status_code == 200:
                sessions = res.json()
                if isinstance(sessions, list):
                    for s in sessions:
                        if s.get('name') == raw_id or s.get('id') == raw_id:
                            resolved = s.get('id')
                            cls._cached_session_id = resolved
                            logger.info(f"Resolved OpenWA session name '{raw_id}' to UUID: {resolved}")
                            return resolved
                    if len(sessions) > 0 and 'id' in sessions[0]:
                        fallback = sessions[0]['id']
                        cls._cached_session_id = fallback
                        logger.warning(f"Session name '{raw_id}' not found. Falling back to active session: {fallback}")
                        return fallback
        except Exception as e:
            logger.error(f"Failed to auto-resolve OpenWA session name: {e}")

        return raw_id

    @classmethod
    def format_phone_number(cls, raw_phone: str) -> str:
        """
        Normalizes any phone number into OpenWA JID format: <country_code><number>@c.us
        Supports Indonesian & international formats:
        - 08123456789 -> 628123456789@c.us
        - +62 812-3456-7890 -> 6281234567890@c.us
        - 628123456789 -> 628123456789@c.us
        - 628123456789@c.us -> 628123456789@c.us
        """
        if not raw_phone:
            return None

        phone = str(raw_phone).strip()

        if phone.endswith('@c.us'):
            phone = phone[:-5]

        # Remove spaces, dashes, dots, parentheses, and plus sign
        digits = re.sub(r'[\s\-\.\(\)\+]', '', phone)

        if not digits.isdigit():
            return None

        # Convert local 08xx to international 628xx
        if digits.startswith('08'):
            digits = '62' + digits[1:]
        elif digits.startswith('8'):
            digits = '62' + digits

        if len(digits) < 9 or len(digits) > 16:
            return None

        return f"{digits}@c.us"

    @classmethod
    def generate_qr_image_bytes(cls, token_data: str) -> bytes:
        """
        Generates raw PNG bytes for a QR code.
        """
        if not token_data:
            raise ValueError("Token data cannot be empty")

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(token_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    @classmethod
    def generate_qr_base64(cls, token_data: str) -> str:
        """
        Generates a high-quality PNG QR Code in-memory and returns it as a base64 string.
        """
        png_bytes = cls.generate_qr_image_bytes(token_data)
        return base64.b64encode(png_bytes).decode('utf-8')

    @classmethod
    def _get_headers(cls) -> dict:
        headers = {
            "Content-Type": "application/json"
        }
        if Config.OPENWA_API_KEY:
            headers["X-API-Key"] = Config.OPENWA_API_KEY
        return headers

    @classmethod
    def send_text(cls, chat_id: str, text: str) -> dict:
        """
        Sends a text message via OpenWA POST /api/sessions/:sessionId/messages/send-text
        """
        if not Config.OPENWA_ENABLED:
            logger.info("OpenWA is disabled in config. Skipping send_text.")
            return {"success": False, "skipped": True, "reason": "OpenWA is disabled"}

        session_id = cls.get_session_id()
        endpoint = f"{Config.OPENWA_API_URL}/api/sessions/{session_id}/messages/send-text"
        payload = {
            "chatId": chat_id,
            "text": text
        }

        try:
            res = requests.post(endpoint, json=payload, headers=cls._get_headers(), timeout=15, allow_redirects=False)
            if res.status_code in [200, 201]:
                logger.info(f"OpenWA text message sent successfully to {chat_id}")
                return {"success": True, "data": res.json() if res.content else None}
            else:
                logger.error(f"OpenWA send-text failed ({res.status_code}): {res.text}")
                return {"success": False, "error": res.text, "status_code": res.status_code}
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error connecting to OpenWA ({endpoint}): {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def send_image(cls, chat_id: str, base64_data: str, caption: str = "") -> dict:
        """
        Sends an image via OpenWA POST /api/sessions/:sessionId/messages/send-image
        """
        if not Config.OPENWA_ENABLED:
            logger.info("OpenWA is disabled in config. Skipping send_image.")
            return {"success": False, "skipped": True, "reason": "OpenWA is disabled"}

        session_id = cls.get_session_id()
        endpoint = f"{Config.OPENWA_API_URL}/api/sessions/{session_id}/messages/send-image"
        payload = {
            "chatId": chat_id,
            "base64": base64_data,
            "mimetype": "image/png",
            "caption": caption
        }

        try:
            res = requests.post(endpoint, json=payload, headers=cls._get_headers(), timeout=6, allow_redirects=False)
            if res.status_code in [200, 201]:
                logger.info(f"OpenWA image sent successfully to {chat_id}")
                return {"success": True, "data": res.json() if res.content else None}
            else:
                logger.warning(f"OpenWA send-image returned ({res.status_code}): {res.text}")
                return {"success": False, "error": res.text, "status_code": res.status_code}
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error connecting to OpenWA image endpoint ({endpoint}): {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def format_receipt_text(cls, order, customer_name: str = None) -> str:
        """
        Formats order details into a clean digital receipt layout using line breaks
        so text never collides or wraps awkwardly on mobile screens.
        """
        raw_name = customer_name or getattr(order, 'customer_name', None) or "Pelanggan"
        name = sanitize_customer_name(raw_name, default="Pelanggan")
        short_id = str(order.id)[:8].upper()

        order_time = order.created_at
        if order_time:
            if order_time.tzinfo is None:
                order_time = order_time.replace(tzinfo=timezone.utc)
            order_time_wib = order_time.astimezone(cls.WIB)
            date_str = order_time_wib.strftime("%d/%m/%Y - %H:%M WIB")
        else:
            date_str = "-"

        is_delivery = (str(order.order_type).lower() == 'delivery')
        DIVIDER = "======================="

        lines = [
            "*NOTA ELEKTRONIK*",
            "",
            "*MAKAN DIMSUM INDONESIA*",
            "Cabang Utama (Bekasi Timur)",
            "WhatsApp: 0852-8339-2465",
            "",
            DIVIDER,
            "No. Pesanan :",
            f"*#{short_id}*",
            "",
            "Pelanggan :",
            f"*{name}*",
            "",
            "Tanggal Pemesanan :",
            f"{date_str}",
            "",
            "Layanan :"
        ]

        if not is_delivery:
            lines.append("*Pickup (Ambil di Outlet)*")
            if order.pickup_time:
                lines.append(f"Waktu Ambil: _{order.pickup_time}_")
        else:
            lines.append("*Delivery (Pesan Antar)*")
            if order.delivery_address:
                lines.extend([
                    "",
                    "Alamat Pengiriman :",
                    f"_{order.delivery_address}_"
                ])

        if order.notes:
            lines.extend([
                "",
                "Catatan :",
                f"_{order.notes}_"
            ])

        lines.extend([
            "",
            DIVIDER,
            "Menu Pesanan :",
            ""
        ])

        subtotal = 0.0
        for item in (order.items or []):
            qty = item.quantity
            price = float(item.unit_price)
            item_subtotal = qty * price
            subtotal += item_subtotal

            prod_name = item.product.name if getattr(item, 'product', None) else f"Menu #{item.product_id}"
            clean_prod_name = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50-\u2b55\u200d\ufe0f]', '', str(prod_name)).strip()
            
            qty_unit = "Pax" if "pax" in clean_prod_name.lower() else "Pcs"
            item_calc = f"  {qty} {qty_unit} x Rp {price:,.0f} = Rp {item_subtotal:,.0f}".replace(',', '.')
            lines.extend([
                f"- {clean_prod_name}",
                item_calc,
                ""
            ])

        lines.extend([
            DIVIDER,
            "Status Pembayaran :",
            "*LUNAS (QRIS)*",
            "",
            DIVIDER
        ])

        discount = float(order.voucher_discount or 0.0)
        delivery_fee = 10000.0 if is_delivery else 0.0
        final_total = float(order.total_amount)

        sub_str = f"Rp {subtotal:,.0f}".replace(',', '.')
        lines.append(f"Subtotal  = {sub_str}")

        if delivery_fee > 0:
            ongkir_str = f"Rp {delivery_fee:,.0f}".replace(',', '.')
            lines.append(f"Ongkir    = {ongkir_str}")

        if discount > 0:
            disc_str = f"-Rp {discount:,.0f}".replace(',', '.')
            v_code = f" ({order.voucher_code})" if order.voucher_code else ""
            lines.append(f"Diskon{v_code} = {disc_str}")

        total_str = f"Rp {final_total:,.0f}".replace(',', '.')
        lines.extend([
            "-----------------------",
            f"Total     = *{total_str}*",
            "",
            DIVIDER
        ])

        public_base = (getattr(Config, 'PUBLIC_URL', '') or '').rstrip('/')
        if not is_delivery:
            lines.extend([
                "*VERIFIKASI PENGAMBILAN*",
                "Tunjukkan QR Code yang dikirimkan atau buka tautan berikut kepada kasir:",
                ""
            ])
            if public_base:
                # Include access_token in the link so guests can view their QR without login
                order_link = f"{public_base}/order-status?id={order.id}"
                if order.access_token:
                    order_link += f"#token={order.access_token}"
                lines.extend([
                    order_link,
                    ""
                ])
            lines.extend([
                "- Harap simpan bukti nota ini saat pengambilan pesanan.",
                "- Periksa pesanan Anda sebelum meninggalkan outlet."
            ])
        else:
            lines.extend([
                "*INFORMASI PENGIRIMAN*",
                "Pesanan Anda sedang disiapkan dan akan segera diantarkan oleh kurir.",
                ""
            ])
            if public_base:
                order_link = f"{public_base}/order-status?id={order.id}"
                if order.access_token:
                    order_link += f"#token={order.access_token}"
                lines.extend([
                    "Pantau status pesanan:",
                    order_link,
                    ""
                ])
            lines.append("- Mohon pastikan nomor WhatsApp aktif untuk konfirmasi penerimaan.")

        lines.extend([
            "",
            "Terima kasih telah memesan di Makan Dimsum Indonesia!",
            "",
            "-----------------------",
            "_Pesan ini dikirim otomatis oleh sistem (no-reply). Mohon tidak membalas pesan ini._"
        ])

        return "\n".join(lines)

    @classmethod
    def send_order_receipt_and_qr(cls, order, force_phone: str = None) -> dict:
        """
        Sends the receipt text followed by the pickup QR Code image to the customer.
        Safe and non-blocking: catches network errors so order processing is never halted.
        """
        from app.modules.auth.models import User
        from app.core.db import db_session

        results = {
            "receipt_sent": False,
            "qr_sent": False,
            "order_id": str(order.id)
        }

        # 1. Determine customer phone and name
        raw_phone = force_phone
        customer_name = "Pelanggan"

        if not raw_phone:
            if getattr(order, 'customer_phone', None):
                raw_phone = order.customer_phone

            if getattr(order, 'customer_name', None):
                customer_name = order.customer_name

            customer = getattr(order, 'customer', None)
            if not customer and order.customer_id:
                try:
                    customer = db_session.query(User).get(order.customer_id)
                except Exception as e:
                    logger.warning(f"Could not load customer for order {order.id}: {e}")

            if customer:
                if not getattr(order, 'customer_name', None) and customer.full_name:
                    customer_name = customer.full_name
                if not raw_phone:
                    raw_phone = customer.phone
                    if not raw_phone and customer.email and not '@' in customer.email:
                        raw_phone = customer.email

        customer_name = sanitize_customer_name(customer_name, default="Pelanggan")

        chat_id = cls.format_phone_number(raw_phone)
        if not chat_id:
            logger.warning(f"Order {order.id}: No valid WhatsApp phone number found for customer (raw='{raw_phone}')")
            results["error"] = "Nomor WhatsApp tidak valid atau tidak ditemukan"
            return results

        results["chat_id"] = chat_id

        # 2. Send Receipt Text Message (Contains full receipt + QR links)
        receipt_text = cls.format_receipt_text(order, customer_name)
        text_res = cls.send_text(chat_id, receipt_text)
        results["receipt_sent"] = text_res.get("success", False)
        if not results["receipt_sent"]:
            results["receipt_error"] = text_res.get("error")

        # 3. Attempt sending QR Code Image via send-image
        is_pickup = (str(order.order_type).lower() != 'delivery')
        if is_pickup and order.qr_token:
            try:
                qr_base64 = cls.generate_qr_base64(order.qr_token)
                short_id = str(order.id)[:8].upper()
                caption = (
                    f"*QR PENGAMBILAN #{short_id}*\n\n"
                    f"Pelanggan: *{customer_name}*\n"
                    f"Tunjukkan QR ini ke kasir saat pengambilan pesanan.\n\n"
                    f"_Pesan otomatis (no-reply)._"
                )
                img_res = cls.send_image(chat_id, qr_base64, caption=caption)
                results["qr_sent"] = img_res.get("success", False)
                if not results["qr_sent"]:
                    results["qr_warning"] = "Image media send returned 500 on OpenWA VPS, receipt text with QR links was delivered."
            except Exception as e:
                logger.warning(f"Error generating or sending QR code image for order {order.id}: {e}")
                results["qr_error"] = str(e)
        else:
            results["qr_skipped"] = True

        return results
