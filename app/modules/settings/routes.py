from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
from app.shared.response import api_success, api_error
from app.modules.settings.service import SettingsService
from app.core.security import admin_required
from app.core.db import db_session
from app.modules.inventory.models import DailyProductionPlan
from app.shared.utils import utc_now
settings_bp = APIRouter()

@settings_bp.api_route('/order-limit', methods=['GET'])
def get_order_limit(request: Request):
    """Public endpoint — customers need to know the limit for frontend validation."""
    limit = SettingsService.get_order_limit()
    return api_success(data={'order_item_limit': limit})

@settings_bp.api_route('/order-limit', methods=['PUT'], dependencies=[Depends(admin_required)])
def set_order_limit(request: Request):
    data = request.state.payload or {}
    raw_value = data.get('order_item_limit')
    if raw_value is None:
        return api_error('Field order_item_limit is required', 400)
    try:
        value = int(raw_value)
    except (ValueError, TypeError):
        return api_error('Order limit harus berupa angka', 400)
    try:
        SettingsService.set_order_limit(value)
        return api_success(data={'order_item_limit': value}, message='Order limit berhasil diperbarui')
    except ValueError as e:
        return api_error(str(e), 400)

@settings_bp.api_route('/production-days', methods=['GET'])
def get_production_days(request: Request):
    days = SettingsService.get_active_production_days()
    return api_success(data={'active_production_days': days})

@settings_bp.api_route('/production-days', methods=['PUT'], dependencies=[Depends(admin_required)])
def set_production_days(request: Request):
    data = request.state.payload or {}
    days = data.get('active_production_days')
    if days is None or not isinstance(days, list):
        return api_error('Field active_production_days (list angka 0-6) wajib diisi', 400)
    try:
        updated = SettingsService.set_active_production_days(days)
        today = utc_now().date()
        future_plans = db_session.query(DailyProductionPlan).filter(DailyProductionPlan.plan_date >= today).all()
        for p in future_plans:
            if p.plan_date.weekday() not in updated:
                p.target_mika = 0
                p.target_vakum = 0
                p.target_online = 0
                p.target_offline = 0
                p.gilingan_mika = 0.0
                p.gilingan_vakum = 0.0
                p.total_gilingan = 0.0
            elif p.total_gilingan == 0:
                p.target_mika = 350
                p.target_vakum = 100
                p.target_online = 180
                p.target_offline = 270
                p.gilingan_mika = 30.0
                p.gilingan_vakum = 6.0
                p.total_gilingan = 36.0
        db_session.commit()
        return api_success(data={'active_production_days': updated}, message='Jadwal produksi mingguan berhasil diperbarui')
    except ValueError as e:
        return api_error(str(e), 400)
