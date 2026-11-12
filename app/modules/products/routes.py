from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response, api_success, api_error
from app.modules.products.service import ProductService
from app.core.security import internal_or_admin_required
from app.core.limiter import rate_limit
from app.core.internal_client import InternalApiClient
import logging

logger = logging.getLogger(__name__)
products_bp = APIRouter()

@products_bp.api_route('/sync-status', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
def get_sync_status(request: Request):
    """Returns connectivity and configuration status with internal factory API."""
    status = InternalApiClient.check_connection()
    return api_success(data=status)

@products_bp.api_route('/sync', methods=['POST'], dependencies=[Depends(internal_or_admin_required)])
def trigger_sync(request: Request):
    """
    Trigger manual or webhook sync from internal factory system.
    Protected by X-API-Key / X-Internal-Key header or admin token.
    """
    try:
        result = InternalApiClient.sync_catalog()
        return api_success(data=result, message='Katalog produk, voucher, dan banner berhasil disinkronkan!')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.exception('Failed to sync catalog from internal API')
        return api_error(f"Gagal melakukan sinkronisasi: {str(e)}", 500)

@products_bp.api_route('', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
def get_products(request: Request):
    """Public customer endpoint: lists all available products."""
    products = ProductService.get_all()
    return api_success(data=[p.to_dict() for p in products])

@products_bp.api_route('/{product_id}', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
def get_product(request: Request, product_id):
    """Public customer endpoint: retrieves single product detail."""
    product = ProductService.get_by_id(product_id)
    if not product:
        return api_error('Product not found', 404)
    return api_success(data=product.to_dict())
