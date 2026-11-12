from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
"""
Production Realization API Routes (bertahap logging)
Phase 3: Detailed Production Realization
"""
import logging
from datetime import datetime
from app.shared.response import api_success, api_error
from app.modules.inventory.realization_service import ProductionRealizationService
from app.core.db import db_session
from app.core.security import staff_or_admin_required, production_or_admin_required
from app.core.limiter import rate_limit
logger = logging.getLogger(__name__)
realization_bp = APIRouter()

@realization_bp.api_route('/realizations', methods=['POST'], dependencies=[Depends(production_or_admin_required), Depends(rate_limit('30 per minute'))])
def create_realization(request: Request):
    """
    Create a new production realization entry (bertahap logging)
    
    Request body:
    {
        "target_id": "target-uuid",
        "tanggal": "2024-12-01",
        "produced_qty": 30,
        "batch_number": 1,
        "notes": "Batch pagi"
    }
    """
    data = request.state.payload or {}
    target_id = data.get('target_id')
    tanggal_str = data.get('tanggal')
    produced_qty = data.get('produced_qty')
    batch_number = data.get('batch_number')
    notes = data.get('notes')
    if not target_id:
        return api_error('ID target produksi wajib diisi', 400)
    if not tanggal_str:
        return api_error('Tanggal produksi wajib diisi', 400)
    if produced_qty is None:
        return api_error('Jumlah produksi wajib diisi', 400)
    try:
        tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date()
        user_id = getattr(request.state, 'user_id', None)
        realization = ProductionRealizationService.create_realization(target_id=target_id, tanggal=tanggal, produced_qty=produced_qty, batch_number=batch_number, notes=notes, created_by=user_id)
        return api_success(data=realization.to_dict(), status=201, message=f'Realization Batch {realization.batch_number} berhasil dicatat!')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error creating realization: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat mencatat realisasi', 500)

@realization_bp.api_route('/realizations/{realization_id}', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_realization(request: Request, realization_id):
    """Get production realization by ID"""
    try:
        realization = ProductionRealizationService.get_realization(realization_id)
        if not realization:
            return api_error('Realisasi produksi tidak ditemukan', 404)
        return api_success(data=realization.to_dict())
    except Exception as e:
        logger.error(f'Error fetching realization {realization_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat mengambil data realisasi', 500)

@realization_bp.api_route('/realizations/{realization_id}', methods=['PUT'], dependencies=[Depends(production_or_admin_required), Depends(rate_limit('30 per minute'))])
def update_realization(request: Request, realization_id):
    """
    Update production realization
    
    Request body (partial updates allowed):
    {
        "produced_qty": 35,
        "notes": "Diupdate setelah verifikasi",
        "status": "completed"
    }
    """
    data = request.state.payload or {}
    try:
        update_fields = {}
        if 'produced_qty' in data and data['produced_qty'] is not None:
            update_fields['produced_qty'] = data['produced_qty']
        if 'notes' in data:
            update_fields['notes'] = data['notes']
        if 'status' in data and data['status'] in ['pending', 'in_progress', 'completed', 'overproduced']:
            update_fields['status'] = data['status']
        if not update_fields:
            return api_error('Tidak ada field yang diupdate', 400)
        realization = ProductionRealizationService.update_realization(realization_id, **update_fields)
        return api_success(data=realization.to_dict(), message='Realisasi produksi berhasil diperbarui')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error updating realization {realization_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat memperbarui realisasi', 500)

@realization_bp.api_route('/realizations/{realization_id}', methods=['DELETE'], dependencies=[Depends(staff_or_admin_required)])
def delete_realization(request: Request, realization_id):
    """Delete production realization"""
    try:
        success = ProductionRealizationService.delete_realization(realization_id)
        if not success:
            return api_error('Realisasi produksi tidak ditemukan', 404)
        return api_success(message='Realisasi produksi berhasil dihapus')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error deleting realization {realization_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat menghapus realisasi', 500)

@realization_bp.api_route('/targets/{target_id}/realizations', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_realizations_for_target(request: Request, target_id):
    """
    Get all realizations for a production target
    
    Query params:
    - tanggal: Filter by date (YYYY-MM-DD)
    """
    try:
        tanggal_str = request.query_params.get('tanggal')
        tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date() if tanggal_str else None
        realizations = ProductionRealizationService.list_realizations_for_target(target_id, tanggal)
        return api_success(data=ProductionRealizationService.batch_realizations_as_json(realizations))
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error fetching realizations for target {target_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat mengambil daftar realisasi', 500)

@realization_bp.api_route('/targets/{target_id}/progress', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_target_progress(request: Request, target_id):
    """
    Get progress summary for a production target
    
    Query params:
    - tanggal: Filter by date (YYYY-MM-DD)
    """
    try:
        tanggal_str = request.query_params.get('tanggal')
        tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date() if tanggal_str else None
        progress = ProductionRealizationService.calculate_target_progress(target_id, tanggal)
        return api_success(data=progress)
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error fetching progress for target {target_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat menghitung progress', 500)

@realization_bp.api_route('/plans/{plan_id}/realizations', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_realizations_for_plan(request: Request, plan_id):
    """
    Get all realizations for a daily production plan
    
    Query params:
    - tanggal: Filter by date (YYYY-MM-DD)
    """
    try:
        tanggal_str = request.query_params.get('tanggal')
        tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date() if tanggal_str else None
        realizations = ProductionRealizationService.list_realizations_for_plan(plan_id, tanggal)
        return api_success(data=ProductionRealizationService.batch_realizations_as_json(realizations))
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error fetching realizations for plan {plan_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat mengambil daftar realisasi', 500)

@realization_bp.api_route('/plans/{plan_id}/daily-progress', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_plan_daily_progress(request: Request, plan_id):
    """
    Get aggregated daily progress for all targets in a plan
    
    Query params:
    - tanggal: Filter by date (YYYY-MM-DD)
    """
    try:
        tanggal_str = request.query_params.get('tanggal')
        tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date() if tanggal_str else None
        progress_list = ProductionRealizationService.get_plan_daily_progress(plan_id, tanggal)
        total_target = sum((p['target_quantity'] for p in progress_list))
        total_produced = sum((p['total_produced'] for p in progress_list))
        overall_percent = total_produced / total_target * 100 if total_target > 0 else 0
        return api_success(data={'daily_progress': progress_list, 'summary': {'total_target': total_target, 'total_produced': total_produced, 'overall_completion': round(overall_percent, 2), 'completed_targets': sum((1 for p in progress_list if p['status'] == 'completed')), 'in_progress_targets': sum((1 for p in progress_list if p['status'] == 'in_progress')), 'pending_targets': sum((1 for p in progress_list if p['status'] == 'pending'))}})
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception as e:
        logger.error(f'Error fetching daily progress for plan {plan_id}: {e}', exc_info=True)
        return api_error('Terjadi kesalahan saat menghitung progress harian', 500)
