from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
import hmac
import hashlib
import logging
from app.shared.response import api_success, api_error
from app.modules.orders.service import OrderService
from app.modules.payments.models import Payment
from app.core.config import Config
from app.core.limiter import rate_limit
from app.core.db import db_session
logger = logging.getLogger(__name__)
payments_bp = APIRouter()

def verify_webhook_signature(raw_body: bytes, headers: dict) -> bool:
    secret = Config.PAYWUZ_WEBHOOK_SECRET
    if not secret:
        return False
    received = headers.get('X-Paywuz-Signature') or headers.get('X-Webhook-Signature') or headers.get('X-Signature')
    if not received:
        return False
    expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)

@payments_bp.api_route('/webhook', methods=['POST'], dependencies=[Depends(rate_limit('60 per minute'))])
def handle_webhook(request: Request):
    from app.modules.payments.service import PaywuzService
    raw_data = request.state.raw_body
    payload = request.state.payload or {}
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in ('authorization', 'x-paywuz-signature', 'x-webhook-signature', 'x-signature', 'x-api-key', 'x-paywuz-secret', 'x-webhook-secret')}
    logger.info('Paywuz webhook received')
    if not verify_webhook_signature(raw_data, request.headers):
        return api_error('Invalid webhook signature', 403)
    data = payload.get('data', payload)
    if not isinstance(data, dict):
        return api_error('Invalid webhook data', 400)
    req_timestamp = request.headers.get('X-Timestamp') or request.headers.get('X-Paywuz-Timestamp') or data.get('timestamp') or payload.get('timestamp') or data.get('createdAt') or payload.get('createdAt')
    if req_timestamp:
        try:
            import time
            from datetime import datetime, timezone
            current_ts = time.time()
            ts_val = None
            if isinstance(req_timestamp, (int, float)):
                ts_val = float(req_timestamp)
                if ts_val > 100000000000.0:
                    ts_val = ts_val / 1000.0
            elif isinstance(req_timestamp, str):
                try:
                    ts_val = float(req_timestamp)
                    if ts_val > 100000000000.0:
                        ts_val = ts_val / 1000.0
                except ValueError:
                    dt = datetime.fromisoformat(req_timestamp.replace('Z', '+00:00'))
                    ts_val = dt.timestamp()
            import math
            if ts_val is None or not math.isfinite(ts_val):
                return api_error('Invalid webhook timestamp', 400)
            if ts_val is not None:
                drift = abs(current_ts - ts_val)
                if drift > 300:
                    logger.warning(f'Webhook rejected due to large timestamp drift: {drift:.1f}s')
                    return api_error('Webhook payload has expired (replay protection)', 400)
        except (ValueError, TypeError, OverflowError):
            return api_error('Invalid webhook timestamp', 400)
    identifier = data.get('orderId') or data.get('order_id') or payload.get('orderId') or payload.get('order_id') or data.get('id') or payload.get('id') or data.get('transaction_id')
    status = data.get('status') or payload.get('status')
    if not isinstance(identifier, str) or len(identifier) > 255 or not isinstance(status, str):
        return api_error('Invalid webhook identifier or status', 400)
    if not identifier:
        return api_error('Missing order or transaction identifier in payload', 400)
    try:
        OrderService.handle_payment_webhook(identifier, status, payload)
        return api_success(message='Webhook processed successfully')
    except ValueError as ve:
        logger.warning(f'Webhook processing error for identifier {identifier}: {str(ve)}')
        return api_error(str(ve), 400)
    except Exception as e:
        logger.exception(f'Unexpected error processing webhook for identifier {identifier}')
        return api_error('Internal server error during webhook processing', 500)
