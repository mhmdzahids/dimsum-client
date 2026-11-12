import urllib.request
import json
from urllib.parse import urlsplit, quote

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect())

def payment_base_url():
    url = Config.PAYWUZ_API_URL.rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.paywuz.id" or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise ValueError("Invalid payment gateway configuration")
    return url

from app.core.config import Config

import logging

logger = logging.getLogger(__name__)

class PaywuzService:
    @staticmethod
    def create_transaction(
        order_id: str,
        amount: float,
        payment_method: str = "QRIS",
        customer_name: str = None,
        phone: str = None,
        email: str = None,
        metadata: dict = None
    ):
        url = f"{payment_base_url()}/transactions"
        
        meta = metadata.copy() if metadata else {}
        if customer_name and str(customer_name).strip():
            meta["customerName"] = str(customer_name).strip()[:100]
        elif "customerName" not in meta:
            meta["customerName"] = "Pelanggan Dimsum"

        if phone and str(phone).strip():
            meta["phone"] = str(phone).strip()
        elif "phone" not in meta:
            meta["phone"] = "081234567890"

        if email and str(email).strip():
            meta["email"] = str(email).strip()
        elif "email" not in meta:
            meta["email"] = "customer@makandimsum.com"

        payload = {
            "orderId": order_id,
            "amount": int(amount),
            "paymentMethod": payment_method,
            "metadata": meta
        }
        
        data = json.dumps(payload).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f'Bearer {Config.PAYWUZ_API_KEY}')
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        
        try:
            with opener.open(req, timeout=10) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                return res_json.get('data', {})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8')
            logger.error(f"Paywuz HTTP {e.code}: {err_body}")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get('message') or err_json.get('error') or "Payment gateway rejected the request"
                raise ValueError(err_msg)
            except (json.JSONDecodeError, TypeError):
                raise ValueError("Payment gateway rejected the request")
        except Exception as e:
            logger.error(f"Paywuz connection error: {e}")
            raise ValueError("Payment gateway unavailable")

    @staticmethod
    def create_qris_transaction(
        order_id: str,
        amount: float,
        customer_name: str = None,
        phone: str = None,
        email: str = None,
        metadata: dict = None
    ):
        return PaywuzService.create_transaction(
            order_id,
            amount,
            payment_method="QRIS",
            customer_name=customer_name,
            phone=phone,
            email=email,
            metadata=metadata
        )

    @staticmethod
    def create_va_transaction(
        order_id: str,
        amount: float,
        bank_code: str = "BNIVA",
        customer_name: str = None,
        phone: str = None,
        email: str = None,
        metadata: dict = None
    ):
        return PaywuzService.create_transaction(
            order_id,
            amount,
            payment_method=bank_code,
            customer_name=customer_name,
            phone=phone,
            email=email,
            metadata=metadata
        )

    @staticmethod
    def get_transaction(transaction_id: str):
        if not transaction_id or not Config.PAYWUZ_API_KEY:
            return None
            
        url = f"{payment_base_url()}/transactions/{quote(str(transaction_id), safe='')}"
        req = urllib.request.Request(url, method='GET')
        req.add_header('Authorization', f'Bearer {Config.PAYWUZ_API_KEY}')
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        
        try:
            with opener.open(req, timeout=10) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                return res_json.get('data', res_json)
        except Exception:
            return None
