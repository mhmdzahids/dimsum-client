from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response, api_success, api_error
from app.modules.banners.service import BannerService
from app.core.limiter import rate_limit
import logging

logger = logging.getLogger(__name__)
banners_bp = APIRouter()

@banners_bp.api_route('', methods=['GET'], dependencies=[Depends(rate_limit('60 per minute'))])
def get_banners(request: Request):
    """Public customer endpoint: retrieves active promotional banners for carousel."""
    try:
        banners = BannerService.get_all(active_only=True)
        return api_success(data=[b.to_dict() for b in banners])
    except Exception:
        logger.exception('Error fetching banners')
        return api_error('Gagal memuat banner promosi', 500)
