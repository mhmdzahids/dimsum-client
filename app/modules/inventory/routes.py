from fastapi import APIRouter, Request, Depends
from app.shared.response import json_response
import logging
import math
from app.shared.response import api_success, api_error
from app.modules.inventory.service import InventoryService
from app.modules.inventory.models import RawMaterialTransaction
from app.core.db import db_session
from app.core.security import staff_or_admin_required, inventory_or_admin_required, checker_or_admin_required
from app.core.limiter import rate_limit
logger = logging.getLogger(__name__)
inventory_bp = APIRouter()

@inventory_bp.api_route('/production/plan', methods=['POST'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('30 per minute'))])
def create_production_plan(request: Request):
    """
    Step 1: Ayu & Lala (Inventory Control) create a production plan by LOT count.
    """
    data = request.state.payload or {}
    product_id = data.get('product_id')
    planned_lots = data.get('planned_lots')
    notes = data.get('notes')
    lot_size = data.get('lot_size', 25)
    if not product_id:
        return api_error('ID Produk wajib dipilih', 400)
    if planned_lots is None:
        return api_error('Jumlah rencana lot wajib diisi', 400)
    try:
        user_id = getattr(request.state, 'user_id', None)
        batch = InventoryService.create_production_plan(product_id=product_id, planned_lots=planned_lots, notes=notes, user_id=user_id, lot_size=int(lot_size))
        return api_success(data=batch.to_dict(), status=201, message=f'Rencana produksi {batch.batch_code} ({batch.planned_lots} Lot) berhasil dibuat!')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error creating production plan')
        return api_error('Gagal membuat rencana produksi', 500)

@inventory_bp.api_route('/production/{batch_id}/confirm', methods=['POST'], dependencies=[Depends(checker_or_admin_required), Depends(rate_limit('30 per minute'))])
def confirm_production_actual(request: Request, batch_id):
    """
    Step 2: Om Yosi (Checker) validates actual finished lots from the kitchen.
    Atomically increments inventory stock and records transaction.
    """
    data = request.state.payload or {}
    actual_lots = data.get('actual_lots')
    loose_qty = data.get('loose_qty', 0)
    if actual_lots is None:
        return api_error('Jumlah lot aktual wajib diisi', 400)
    try:
        checker_id = getattr(request.state, 'user_id', None)
        batch = InventoryService.confirm_production_actual(batch_id=batch_id, actual_lots=actual_lots, checker_id=checker_id, loose_qty=loose_qty)
        return api_success(data=batch.to_dict(), message=f'Produksi {batch.batch_code} berhasil dikonfirmasi! {batch.produced_qty} produk masuk ke stok freezer.')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception(f'Error confirming production batch {batch_id}')
        return api_error('Gagal mengonfirmasi hasil produksi', 500)

@inventory_bp.api_route('/production/{batch_id}/cancel', methods=['POST'], dependencies=[Depends(inventory_or_admin_required)])
def cancel_production_plan(request: Request, batch_id):
    """
    Cancels a planned batch before it enters the kitchen.
    """
    data = request.state.payload or {}
    reason = data.get('reason')
    try:
        user_id = getattr(request.state, 'user_id', None)
        batch = InventoryService.cancel_production_plan(batch_id, user_id, reason)
        return api_success(data=batch.to_dict(), message=f'Rencana produksi {batch.batch_code} berhasil dibatalkan.')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception(f'Error cancelling production batch {batch_id}')
        return api_error('Gagal membatalkan rencana produksi', 500)

@inventory_bp.api_route('/batches', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def list_batches(request: Request):
    """
    List production batches with optional filters.
    """
    status = request.query_params.get('status')
    product_id = request.query_params.get('product_id')
    limit = int(request.query_params.get('limit', 50))
    try:
        batches = InventoryService.list_batches(status=status, product_id=product_id, limit=limit)
        return api_success(data=[b.to_dict() for b in batches])
    except Exception:
        logger.exception('Error listing production batches')
        return api_error('Gagal memuat daftar batch produksi', 500)

@inventory_bp.api_route('/batches/{batch_id}', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_batch_detail(request: Request, batch_id):
    try:
        batch = InventoryService.get_batch_by_id(batch_id)
        if not batch:
            return api_error('Batch produksi tidak ditemukan', 404)
        return api_success(data=batch.to_dict())
    except Exception:
        logger.exception(f'Error fetching batch {batch_id}')
        return api_error('Gagal memuat detail batch', 500)

@inventory_bp.api_route('/batches/code/{batch_code:path}', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def lookup_batch_by_code(request: Request, batch_code):
    """
    Looks up a batch by batch_code or by full Lot QR payload string.
    """
    try:
        batch = InventoryService.get_batch_by_code(batch_code)
        if not batch:
            return api_error('Batch produksi dengan kode ini tidak ditemukan', 404)
        return api_success(data=batch.to_dict())
    except Exception:
        logger.exception(f'Error looking up batch by code {batch_code}')
        return api_error('Gagal mencari batch produksi', 500)

@inventory_bp.api_route('/batches/{batch_id}/stickers', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_lot_stickers(request: Request, batch_id):
    """
    Generates QR code sticker data for each lot in the batch.
    """
    try:
        stickers = InventoryService.get_lot_stickers(batch_id)
        return api_success(data=stickers)
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception(f'Error getting stickers for batch {batch_id}')
        return api_error('Gagal memuat data stiker lot', 500)

@inventory_bp.api_route('/transactions', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def list_transactions(request: Request):
    """
    List inventory transactions history.
    """
    product_id = request.query_params.get('product_id')
    batch_id = request.query_params.get('batch_id')
    limit = int(request.query_params.get('limit', 100))
    try:
        txns = InventoryService.list_transactions(product_id=product_id, batch_id=batch_id, limit=limit)
        return api_success(data=[t.to_dict() for t in txns])
    except Exception:
        logger.exception('Error listing inventory transactions')
        return api_error('Gagal memuat riwayat transaksi inventory', 500)

@inventory_bp.api_route('/stock-out', methods=['POST'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('30 per minute'))])
def record_channel_stock_out(request: Request):
    """
    Deducts stock from freezer for multi-channel sales (Shopee, TikTok, PO B2B, Offline, Waste).
    Uses FIFO allocation across active batches.
    """
    data = request.state.payload or {}
    product_id = data.get('product_id')
    quantity = data.get('quantity')
    lots_count = data.get('lots_count')
    channel = data.get('channel')
    notes = data.get('notes')
    if not product_id:
        return api_error('ID Produk wajib dipilih', 400)
    if not channel:
        return api_error('Saluran pengeluaran wajib dipilih (Shopee, TikTok, PO, Offline, dll)', 400)
    final_qty = None
    if lots_count is not None and int(lots_count) > 0:
        final_qty = int(lots_count) * 25
    elif quantity is not None:
        final_qty = int(quantity)
    if not final_qty or final_qty <= 0:
        return api_error('Jumlah pengeluaran produk harus lebih dari 0', 400)
    try:
        user_id = getattr(request.state, 'user_id', None)
        result = InventoryService.record_channel_stock_out(product_id=product_id, quantity=final_qty, channel=channel, notes=notes, user_id=user_id)
        affected_batches = result.get('batches_affected', [])
        batch_count = len(affected_batches)
        batch_info = f' (dialokasikan dari {batch_count} lot/batch via FIFO)' if batch_count > 1 else ''
        return api_success(data=result, message=f"Berhasil mengeluarkan {final_qty} produk ke saluran {channel.upper()}{batch_info}! Sisa stok freezer: {result['stock_remaining']} pcs.")
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error recording channel stock out')
        return api_error('Gagal mencatat pengeluaran stok', 500)

@inventory_bp.api_route('/stock-rebalance', methods=['POST'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('30 per minute'))])
def rebalance_stock_pool(request: Request):
    """
    Transfers stock quota between 'offline' and 'online' allocation pools.
    Audited in inventory transactions as type='adjustment'.
    """
    data = request.state.payload or {}
    product_id = data.get('product_id')
    from_pool = data.get('from_pool')
    to_pool = data.get('to_pool')
    quantity = data.get('quantity')
    reason = data.get('reason')
    if not product_id:
        return api_error('ID Produk wajib dipilih', 400)
    if not from_pool or not to_pool:
        return api_error('Pool asal (from_pool) dan tujuan (to_pool) wajib diisi', 400)
    if quantity is None:
        return api_error('Jumlah transfer kuota wajib diisi', 400)
    try:
        user_id = getattr(request.state, 'user_id', None)
        result = InventoryService.rebalance_stock_pool(product_id=product_id, from_pool=from_pool, to_pool=to_pool, quantity=int(quantity), reason=reason, user_id=user_id)
        return api_success(data=result, message=f"Berhasil mentransfer {result['quantity']} pack dari kuota {result['from_pool'].upper()} ke {result['to_pool'].upper()}!")
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error rebalancing stock pool')
        return api_error('Gagal mentransfer kuota stok', 500)

@inventory_bp.api_route('/dashboard/summary', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_inventory_dashboard_summary(request: Request):
    """
    Aggregated stats for inventory dashboard (buffer stock alerts, channel distribution, today's lots).
    """
    try:
        summary = InventoryService.get_inventory_dashboard_summary()
        return api_success(data=summary)
    except Exception:
        logger.exception('Error loading inventory dashboard summary')
        return api_error('Gagal memuat ringkasan inventory', 500)

@inventory_bp.api_route('/raw-materials', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_raw_materials(request: Request):
    """
    Lists all raw materials with buffer stock indicators.
    """
    try:
        category = request.query_params.get('category')
        search = request.query_params.get('search')
        data = InventoryService.get_raw_materials(category=category, search=search)
        return api_success(data=data)
    except Exception:
        logger.exception('Error fetching raw materials')
        return api_error('Gagal memuat daftar bahan baku', 500)

@inventory_bp.api_route('/raw-materials', methods=['POST'], dependencies=[Depends(inventory_or_admin_required)])
def create_raw_material(request: Request):
    """
    Adds a new raw material to inventory control.
    """
    data = request.state.payload or {}
    user_id = getattr(request.state, 'user_id', None)
    try:
        mat = InventoryService.create_raw_material(data, user_id=user_id)
        return api_success(data=mat, message='Bahan baku berhasil ditambahkan.', status=201)
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error creating raw material')
        return api_error('Gagal menambahkan bahan baku', 500)

@inventory_bp.api_route('/raw-materials/{material_id}', methods=['PUT'], dependencies=[Depends(inventory_or_admin_required)])
def update_raw_material(request: Request, material_id):
    """
    Updates raw material buffer thresholds, price, or storage location.
    """
    data = request.state.payload or {}
    try:
        mat = InventoryService.update_raw_material(material_id, data)
        return api_success(data=mat, message='Bahan baku berhasil diperbarui.')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error updating raw material')
        return api_error('Gagal memperbarui bahan baku', 500)

@inventory_bp.api_route('/raw-materials/{material_id}/transaction', methods=['POST'], dependencies=[Depends(inventory_or_admin_required)])
def record_raw_material_transaction(request: Request, material_id):
    """
    Records Restock/Belanja (IN) or Pemakaian Produksi 1 (OUT).
    """
    data = request.state.payload or {}
    tx_type = data.get('type')
    quantity = data.get('quantity')
    reference_type = data.get('reference_type', 'manual')
    notes = data.get('notes')
    batch_gilingan = data.get('batch_gilingan')
    reference_id = data.get('reference_id')
    user_id = getattr(request.state, 'user_id', None)
    if not tx_type or quantity is None:
        return api_error('Tipe transaksi dan jumlah kuantitas wajib diisi.', 400)
    try:
        result = InventoryService.record_raw_material_transaction(material_id=material_id, tx_type=tx_type, quantity=quantity, reference_type=reference_type, notes=notes, user_id=user_id, batch_gilingan=batch_gilingan, reference_id=reference_id)
        verb = 'ditambahkan ke' if tx_type == 'in' else 'dikeluarkan dari'
        return api_success(data=result, message=f'Berhasil mencatat transaksi: {quantity} {verb} stok.')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error recording raw material transaction')
        return api_error('Gagal mencatat transaksi bahan baku', 500)

@inventory_bp.api_route('/raw-materials/transactions', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_raw_material_transactions(request: Request):
    """
    Lists recent raw material transactions with pagination.
    """
    try:
        material_id = request.query_params.get('material_id')
        action = request.query_params.get('action')
        page = max(1, int(request.query_params.get('page', 1)))
        limit = min(200, max(10, int(request.query_params.get('limit', 50))))
        offset = (page - 1) * limit
        total_query = db_session.query(RawMaterialTransaction.id)
        if material_id:
            total_query = total_query.filter(RawMaterialTransaction.material_id == material_id)
        if action and action != 'all':
            total_query = total_query.filter(RawMaterialTransaction.type == action)
        total = total_query.count()
        query = db_session.query(RawMaterialTransaction)
        if material_id:
            query = query.filter(RawMaterialTransaction.material_id == material_id)
        if action and action != 'all':
            query = query.filter(RawMaterialTransaction.type == action)
        txs = query.order_by(RawMaterialTransaction.created_at.desc()).offset(offset).limit(limit).all()
        transactions = [t.to_dict() for t in txs]
        total_pages = math.ceil(total / limit) if total > 0 else 1
        return api_success(data={'history': transactions, 'pagination': {'page': page, 'limit': limit, 'total': total, 'totalPages': total_pages, 'hasNext': page < total_pages, 'hasPrev': page > 1}})
    except Exception:
        logger.exception('Error fetching raw material transactions')
        return api_error('Gagal memuat log transaksi bahan baku', 500)

@inventory_bp.api_route('/raw-materials/readiness', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def check_production_readiness(request: Request):
    """
    BOM & Production Readiness Simulator for target gilingan.
    """
    try:
        target = int(request.query_params.get('target_gilingan', 36))
        readiness = InventoryService.check_production_readiness(target_gilingan=target)
        return api_success(data=readiness)
    except Exception:
        logger.exception('Error checking production readiness')
        return api_error('Gagal memeriksa kesiapan bahan baku produksi', 500)

@inventory_bp.api_route('/production/plans/weekly', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_weekly_production_plans(request: Request):
    """
    Retrieves or initializes weekly production calendar (7 days: Mon-Sun).
    """
    try:
        start_date = request.query_params.get('start_date')
        result = InventoryService.get_weekly_production_plans(start_date_str=start_date)
        return api_success(data=result)
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error fetching weekly production plans')
        return api_error('Gagal memuat kalender perencanaan produksi mingguan', 500)

@inventory_bp.api_route('/production/plans/daily', methods=['POST', 'PUT'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('30 per minute'))])
def upsert_daily_production_plan(request: Request):
    """
    Updates target and demand breakdown for a specific date.
    """
    data = request.state.payload or {}
    plan_date = data.get('plan_date')
    if not plan_date:
        return api_error('Tanggal rencana (plan_date: YYYY-MM-DD) wajib diisi', 400)
    try:
        user_id = getattr(request.state, 'user_id', None)
        updated = InventoryService.upsert_daily_production_plan(plan_date_str=plan_date, data=data, user_id=user_id)
        return api_success(data=updated, message=f'Rencana produksi tanggal {plan_date} berhasil diperbarui!')
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception(f'Error updating daily plan for {plan_date}')
        return api_error('Gagal memperbarui rencana produksi harian', 500)

@inventory_bp.api_route('/production/plans/{plan_id}/generate-batches', methods=['POST'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('15 per minute'))])
def generate_batches_from_plan(request: Request, plan_id):
    """
    Instantly converts a daily plan into ProductionBatch entries for Dimsum Mika & Vakum.
    """
    try:
        user_id = getattr(request.state, 'user_id', None)
        res = InventoryService.generate_batches_from_plan(plan_id=plan_id, user_id=user_id)
        return api_success(data=res, status=201, message=f"Batch produksi ({len(res['batches_created'])} batch) berhasil digenerate dan masuk antrean QC!")
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception(f'Error generating batches from plan {plan_id}')
        return api_error('Gagal membuat batch produksi dari rencana harian', 500)

@inventory_bp.api_route('/raw-materials/log-gilingan', methods=['POST'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('60 per minute'))])
def log_gilingan(request: Request):
    """Catat realisasi gilingan hari ini - otomatis kurangi BOM."""
    data = request.state.payload or {}
    jumlah_gilingan = data.get('jumlah_gilingan')
    notes = data.get('notes')
    tanggal_str = data.get('tanggal')
    force = bool(data.get('force', False))
    user_id = getattr(request.state, 'user_id', None)
    if jumlah_gilingan is None:
        return api_error('Jumlah gilingan wajib diisi.', 400)
    try:
        result = InventoryService.log_gilingan(jumlah_gilingan=jumlah_gilingan, notes=notes, tanggal_str=tanggal_str, user_id=user_id, force=force)
        lot = result.get('lot', {})
        return api_success(data=result, status=201, message=f"Berhasil mencatat {lot.get('actual_gilingan', 0)} gilingan! {len(result.get('deducted_items', []))} bahan baku dikurangi.")
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error logging gilingan')
        return api_error('Gagal mencatat lot gilingan produksi', 500)

@inventory_bp.api_route('/raw-materials/production-log', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_production_log(request: Request):
    """Riwayat lot harian Produksi 1 (target vs realisasi gilingan)."""
    try:
        limit = min(100, int(request.query_params.get('limit', 30)))
        tanggal_str = request.query_params.get('tanggal')
        result = InventoryService.get_production_log(limit=limit, tanggal_str=tanggal_str)
        return api_success(data=result)
    except Exception:
        logger.exception('Error fetching production log')
        return api_error('Gagal memuat riwayat log produksi', 500)

@inventory_bp.api_route('/raw-materials/daily-check', methods=['GET'], dependencies=[Depends(staff_or_admin_required)])
def get_latest_daily_check(request: Request):
    """Ambil cek stok harian terakhir (untuk ditampilkan di UI saat halaman load)."""
    try:
        from datetime import date
        tanggal_str = request.query_params.get('tanggal', date.today().strftime('%Y-%m-%d'))
        result = InventoryService.get_latest_daily_check(tanggal_str=tanggal_str)
        return api_success(data=result)
    except Exception:
        logger.exception('Error fetching latest daily check')
        return api_error('Gagal memuat data cek stok terakhir', 500)

@inventory_bp.api_route('/raw-materials/daily-check', methods=['POST'], dependencies=[Depends(inventory_or_admin_required), Depends(rate_limit('30 per minute'))])
def submit_daily_stock_check(request: Request):
    """Ayu submit cek fisik stok H-1 - pengganti papan checklist BC."""
    data = request.state.payload or {}
    tanggal_str = data.get('tanggal')
    target_gilingan = data.get('target_gilingan', 36)
    notes = data.get('notes')
    user_id = getattr(request.state, 'user_id', None)
    if not tanggal_str:
        from datetime import date
        tanggal_str = date.today().strftime('%Y-%m-%d')
    try:
        result = InventoryService.submit_daily_stock_check(tanggal_str=tanggal_str, target_gilingan=target_gilingan, notes=notes, user_id=user_id)
        return api_success(data=result, status=201, message=result.get('message', 'Cek stok berhasil.'))
    except ValueError as ve:
        return api_error(str(ve), 400)
    except Exception:
        logger.exception('Error submitting daily stock check')
        return api_error('Gagal menyimpan cek stok harian', 500)
