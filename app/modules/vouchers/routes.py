from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response, api_success, api_error
from app.modules.vouchers.service import VoucherService
from app.core.limiter import rate_limit
import logging

logger = logging.getLogger(__name__)
vouchers_bp = APIRouter()

@vouchers_bp.api_route('', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
@vouchers_bp.api_route('/public', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
def list_public_vouchers(request: Request):
    """Public customer endpoint: retrieves active promotional vouchers."""
    try:
        vouchers = VoucherService.list_public()
        return api_success(data=[v.to_dict() for v in vouchers])
    except Exception:
        logger.exception('Error listing public vouchers')
        return api_error('Gagal memuat daftar voucher promo', 500)

@vouchers_bp.api_route('/validate', methods=['POST'], dependencies=[Depends(rate_limit('10 per minute'))])
def validate_voucher(request: Request):
    """
    Public customer checkout endpoint: validates promotional code.
    First tries remote validation via Internal Factory API (SSOT),
    then falls back to local database validation.
    """
    data = request.state.payload or {}
    code = (data.get('code') or '').strip()
    subtotal = data.get('subtotal', 0)
    if not code:
        return api_error('Kode promo harus diisi', 400)
    try:
        subtotal_float = float(subtotal)
    except (ValueError, TypeError):
        return api_error('Subtotal tidak valid', 400)

    # 1. Try remote validation on internal factory system
    try:
        from app.core.internal_client import InternalApiClient
        remote_result = InternalApiClient.validate_voucher_remote(code, subtotal_float)
        if remote_result:
            return api_success(data=remote_result, message='Kode promo berhasil divalidasi')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        pass

    # 2. Fallback to local cached database
    try:
        result = VoucherService.validate_voucher(code, subtotal_float)
        return api_success(data=result, message='Kode promo berhasil divalidasi')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.exception('Error validating voucher')
        return api_error('Terjadi kesalahan sistem saat memvalidasi promo', 500)
