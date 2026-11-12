import re
import threading
from datetime import datetime, timezone, timedelta, date

_log_gilingan_lock = threading.Lock()

from sqlalchemy import func, text
from app.core.db import db_session
from app.modules.inventory.models import (
    ProductionBatch,
    InventoryTransaction,
    RawMaterial,
    RawMaterialTransaction,
    DailyProductionPlan,
    ProductionTarget,
    ProductionLot,
    DailyStockCheck
)
from app.modules.products.models import Product
from app.modules.ingredients.service import IngredientService
from app.modules.settings.service import SettingsService
from app.shared.utils import utc_now, generate_uuid
import json

class InventoryService:
    @staticmethod
    def generate_batch_code(product_sku: str, date_val: datetime = None) -> str:
        """
        Generates standard batch code: {SKU}-{YYYYMMDD}-{SEQ:02d}
        Example: DIMSUM-MINI-PAX-25-20261001-01
        """
        target_date = date_val or datetime.now(timezone.utc)
        date_str = target_date.strftime('%Y%m%d')
        clean_sku = re.sub(r'[^A-Za-z0-9\-]', '', product_sku.upper().strip())
        
        # Transaction-scoped lock serializes numbering across all API workers.
        db_session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                           {'key': f'batch:{clean_sku}:{date_str}'})
        prefix = f"{clean_sku}-{date_str}-"
        codes = db_session.query(ProductionBatch.batch_code).filter(
            ProductionBatch.batch_code.like(f"{prefix}%")
        ).all()
        seq = max((int(code.rsplit('-', 1)[1]) for (code,) in codes if code.rsplit('-', 1)[1].isdigit()), default=0) + 1
        return f"{prefix}{seq:02d}"

    @classmethod
    def create_production_plan(
        cls,
        product_id: str,
        planned_lots: int,
        notes: str,
        user_id: str,
        lot_size: int = None,
        expiry_date = None,
        daily_plan_id: str = None
    ) -> ProductionBatch:
        """
        Step 1 (Inventory Control - Ayu & Lala):
        Plans production for a given product by Pack count (Mika = 50 pcs, Vakum = 25 pcs).
        Does NOT increment physical stock yet until confirmed by Checker.
        """
        product = db_session.get(Product, product_id)
        if not product:
            raise ValueError('Produk tidak ditemukan.')

        try:
            planned_lots = int(planned_lots)
        except (ValueError, TypeError):
            raise ValueError('Jumlah rencana kemasan/pack harus berupa bilangan bulat.')

        if planned_lots <= 0 or planned_lots > 1000:
            raise ValueError('Jumlah rencana kemasan/pack harus antara 1 sampai 1.000 pack.')

        prod_dict = product.to_dict()
        expected_pack_size = prod_dict.get('pack_size', 25)
        if not lot_size or lot_size == 25:
            lot_size = expected_pack_size

        batch_code = cls.generate_batch_code(product.sku)
        clean_notes = (notes or '').strip()[:250] if notes else None

        batch = ProductionBatch(
            id=generate_uuid(),
            product_id=product.id,
            batch_code=batch_code,
            lot_size=lot_size,
            planned_lots=planned_lots,
            actual_lots=None,
            loose_qty=0,
            produced_qty=0,
            remaining_qty=0,
            status='planned',
            notes=clean_notes,
            created_by=user_id,
            planned_at=utc_now(),
            produced_at=utc_now(),
            expiry_date=expiry_date,
            daily_plan_id=daily_plan_id
        )

        db_session.add(batch)
        db_session.commit()
        return batch

    @classmethod
    def confirm_production_actual(
        cls,
        batch_id: str,
        actual_lots: int,
        checker_id: str,
        loose_qty: int = 0
    ) -> ProductionBatch:
        """
        Step 2 (Checker - Om Yosi / QC):
        Confirms actual production yield from kitchen.
        Calculates finished pack count = actual_lots.
        Atomically increases product stock by actual_lots (in Packs) and records inventory IN transaction.
        """
        try:
            actual_lots = int(actual_lots)
            loose_qty = int(loose_qty or 0)
        except (ValueError, TypeError):
            raise ValueError('Jumlah pack aktual dan sisa eceran harus berupa bilangan bulat.')

        if actual_lots < 0 or loose_qty < 0:
            raise ValueError('Jumlah pack aktual dan sisa eceran tidak boleh bernilai negatif.')

        # Atomic lock on batch and product
        batch = db_session.get(ProductionBatch, batch_id, with_for_update={'of': ProductionBatch})
        if not batch:
            raise ValueError('Batch produksi tidak ditemukan.')

        if loose_qty >= batch.lot_size:
            raise ValueError(f'Sisa eceran lepas maksimal {batch.lot_size - 1} pcs. Jika mencapai {batch.lot_size} pcs, masukkan sebagai tambahan 1 pack utuh.')

        if batch.status not in ('planned', 'in_progress'):
            raise ValueError(f'Batch ini sudah berstatus "{batch.status}" dan tidak dapat dikonfirmasi ulang.')

        total_packs_produced = actual_lots
        if total_packs_produced <= 0 and loose_qty <= 0:
            raise ValueError('Total produksi aktual yang dihasilkan harus lebih dari 0 pack.')

        product = db_session.get(Product, batch.product_id, with_for_update=True)
        if not product:
            raise ValueError('Produk terkait tidak ditemukan.')

        now = utc_now()
        batch.actual_lots = actual_lots
        batch.loose_qty = loose_qty
        batch.produced_qty = total_packs_produced
        batch.remaining_qty = total_packs_produced
        batch.status = 'completed'
        batch.checked_by = checker_id
        batch.completed_at = now
        batch.produced_at = now

        # Append IN transaction (in packs)
        txn = InventoryTransaction(
            id=generate_uuid(),
            product_id=product.id,
            batch_id=batch.id,
            type='in',
            quantity=total_packs_produced,
            reference_type='production',
            reference_id=batch.id,
            channel='production',
            stock_pool='both',
            created_by=checker_id,
            created_at=now
        )
        db_session.add(txn)

        # Allocate to pools: based on today's plan demand or default 60% offline / 40% online
        offline_ratio = 0.60
        today_plan = db_session.query(DailyProductionPlan).filter(DailyProductionPlan.plan_date == now.date()).first()
        if today_plan:
            off_target = today_plan.target_offline or 0
            on_target = today_plan.target_online or 0
            if (off_target + on_target) > 0:
                offline_ratio = off_target / (off_target + on_target)

        offline_packs = int(round(total_packs_produced * offline_ratio))
        online_packs = total_packs_produced - offline_packs

        # If product has legacy stock_qty without pools initialized, initialize first
        if (product.stock_offline or 0) == 0 and (product.stock_online or 0) == 0 and (product.stock_qty or 0) > 0:
            existing_offline = int(product.stock_qty * 0.6)
            product.stock_offline = existing_offline
            product.stock_online = product.stock_qty - existing_offline

        product.stock_offline = (product.stock_offline or 0) + offline_packs
        product.stock_online = (product.stock_online or 0) + online_packs
        product.stock_qty = product.stock_offline + product.stock_online
        db_session.commit()
        return batch

    @classmethod
    def cancel_production_plan(cls, batch_id: str, user_id: str, reason: str = None) -> ProductionBatch:
        batch = db_session.get(ProductionBatch, batch_id, with_for_update={'of': ProductionBatch})
        if not batch:
            raise ValueError('Batch produksi tidak ditemukan.')

        if batch.status != 'planned':
            raise ValueError('Hanya batch berstatus rencana ("planned") yang dapat dibatalkan.')

        batch.status = 'cancelled'
        if reason:
            existing_notes = batch.notes or ''
            batch.notes = f"{existing_notes} [Dibatalkan: {reason.strip()}]"[:250]

        db_session.commit()
        return batch

    @classmethod
    def list_batches(cls, status: str = None, product_id: str = None, limit: int = 50):
        query = db_session.query(ProductionBatch)
        if status:
            query = query.filter(ProductionBatch.status == status)
        if product_id:
            query = query.filter(ProductionBatch.product_id == product_id)

        batches = query.order_by(ProductionBatch.created_at.desc()).limit(limit).all()
        return batches

    @classmethod
    def get_batch_by_id(cls, batch_id: str) -> ProductionBatch:
        return db_session.get(ProductionBatch, batch_id)

    @classmethod
    def get_batch_by_code(cls, batch_code_or_payload: str) -> ProductionBatch:
        clean_code = (batch_code_or_payload or '').strip()
        if 'BATCH:' in clean_code:
            parts = clean_code.split('|')
            for part in parts:
                if part.startswith('BATCH:'):
                    clean_code = part.replace('BATCH:', '').strip()
                    break
        return db_session.query(ProductionBatch).filter(ProductionBatch.batch_code == clean_code).first()

    @classmethod
    def get_lot_stickers(cls, batch_id: str):
        """
        Generates printable QR sticker data for each lot in the batch.
        """
        batch = db_session.get(ProductionBatch, batch_id)
        if not batch:
            raise ValueError('Batch produksi tidak ditemukan.')

        if batch.status != 'completed':
            raise ValueError('Stiker label lot hanya dapat dicetak setelah batch selesai dikonfirmasi oleh Checker.')

        stickers = []
        prod_date_str = batch.completed_at.strftime('%Y-%m-%d %H:%M') if batch.completed_at else None
        exp_date_str = batch.expiry_date.strftime('%Y-%m-%d') if batch.expiry_date else 'Sesuai Penyimpanan Freezer'

        # Determine packaging type and storage
        pack_type = 'MIKA' if (batch.lot_size == 50 or 'MIKA' in (batch.product.sku if batch.product else '').upper()) else 'VAKUM'
        storage_info = 'Suhu Chiller / Konsumsi Segera' if pack_type == 'MIKA' else 'Freezer Beku (-18°C)'
        default_exp = '1 Minggu (Chiller)' if pack_type == 'MIKA' else '3 Bulan (Freezer)'
        exp_date_str = batch.expiry_date.strftime('%Y-%m-%d') if batch.expiry_date else default_exp

        # Generate 1 sticker per actual pack
        for i in range(1, (batch.actual_lots or 0) + 1):
            qr_payload = f"BATCH:{batch.batch_code}|{pack_type}:{i}/{batch.actual_lots}|QTY:{batch.lot_size}PCS|SKU:{batch.product.sku if batch.product else ''}"
            stickers.append({
                'lot_number': i,
                'total_lots': batch.actual_lots,
                'lot_size': batch.lot_size,
                'pack_type': pack_type,
                'storage_info': storage_info,
                'batch_code': batch.batch_code,
                'product_name': batch.product.name if batch.product else 'Dimsum',
                'product_sku': batch.product.sku if batch.product else '',
                'qr_payload': qr_payload,
                'produced_at': prod_date_str,
                'expiry_date': exp_date_str,
                'is_loose': False
            })

        # If there are loose pieces, add a loose label for internal kitchen tracking
        if batch.loose_qty and batch.loose_qty > 0:
            qr_payload = f"BATCH:{batch.batch_code}|{pack_type}:LOOSE|QTY:{batch.loose_qty}PCS|SKU:{batch.product.sku if batch.product else ''}"
            stickers.append({
                'lot_number': 'Sisa Eceran',
                'total_lots': batch.actual_lots,
                'lot_size': batch.loose_qty,
                'pack_type': pack_type,
                'storage_info': storage_info,
                'batch_code': batch.batch_code,
                'product_name': batch.product.name if batch.product else 'Dimsum',
                'product_sku': batch.product.sku if batch.product else '',
                'qr_payload': qr_payload,
                'produced_at': prod_date_str,
                'expiry_date': exp_date_str,
                'is_loose': True
            })

        return stickers

    @classmethod
    def list_transactions(cls, product_id: str = None, batch_id: str = None, limit: int = 100):
        query = db_session.query(InventoryTransaction)
        if product_id:
            query = query.filter(InventoryTransaction.product_id == product_id)
        if batch_id:
            query = query.filter(InventoryTransaction.batch_id == batch_id)

        return query.order_by(InventoryTransaction.created_at.desc()).limit(limit).all()

    VALID_CHANNELS = {'shopee', 'tiktok', 'po_b2b', 'offline', 'waste', 'web'}

    @classmethod
    def record_channel_stock_out(
        cls,
        product_id: str,
        quantity: int,
        channel: str,
        notes: str,
        user_id: str
    ):
        """
        Deducts stock from freezer for multi-channel sales (Shopee, TikTok, PO B2B, Offline, Waste)
        using FIFO allocation across active batches.
        """
        clean_channel = (channel or '').strip().lower()
        if clean_channel not in cls.VALID_CHANNELS:
            raise ValueError(f"Saluran pengeluaran tidak valid. Pilihan: {', '.join(sorted(cls.VALID_CHANNELS))}")

        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            raise ValueError("Jumlah produk yang dikeluarkan harus berupa bilangan bulat.")

        if qty <= 0:
            raise ValueError("Jumlah produk yang dikeluarkan harus lebih dari 0.")

        product = db_session.get(Product, product_id, with_for_update=True)
        if not product:
            raise ValueError("Produk tidak ditemukan.")

        current_stock = product.stock_qty or 0
        if current_stock < qty:
            raise ValueError(f"Stok freezer tidak mencukupi! Tersedia: {current_stock} pack, diminta keluar: {qty} pack.")

        # Determine target pool and validate pool quota
        if clean_channel in ('shopee', 'tiktok'):
            target_pool = 'online'
            avail_pool_stock = product.stock_online if product.stock_online is not None else current_stock
            if avail_pool_stock < qty:
                raise ValueError(f"Kuota stok online ({clean_channel.upper()}) tidak mencukupi! Tersedia: {avail_pool_stock} pack, diminta keluar: {qty} pack. Silakan lakukan transfer kuota dari stok offline terlebih dahulu.")
            product.stock_online = avail_pool_stock - qty
            product.stock_qty = (product.stock_offline or 0) + product.stock_online
        else:
            target_pool = 'offline'
            avail_pool_stock = product.stock_offline if product.stock_offline is not None else current_stock
            if avail_pool_stock < qty:
                raise ValueError(f"Kuota stok offline ({clean_channel.upper()}) tidak mencukupi! Tersedia: {avail_pool_stock} pack, diminta keluar: {qty} pack. Silakan lakukan transfer kuota dari stok online terlebih dahulu.")
            product.stock_offline = avail_pool_stock - qty
            product.stock_qty = product.stock_offline + (product.stock_online or 0)

        # FIFO deduction across completed batches
        batches = db_session.query(ProductionBatch).filter(
            ProductionBatch.product_id == product.id,
            ProductionBatch.status == 'completed',
            ProductionBatch.remaining_qty > 0
        ).order_by(ProductionBatch.completed_at.asc(), ProductionBatch.created_at.asc()).with_for_update(of=ProductionBatch).all()

        remaining_to_deduct = qty
        batches_affected = []
        now = utc_now()
        dispatch_id = generate_uuid()
        clean_notes = (notes or '').strip()[:250] if notes else None

        for b in batches:
            if remaining_to_deduct <= 0:
                break
            
            deduct_from_batch = min(b.remaining_qty, remaining_to_deduct)
            b.remaining_qty -= deduct_from_batch
            remaining_to_deduct -= deduct_from_batch
            batches_affected.append({
                'batch_id': b.id,
                'batch_code': b.batch_code,
                'deducted': deduct_from_batch,
                'batch_remaining': b.remaining_qty
            })

            # Record transaction linked to this batch
            txn = InventoryTransaction(
                id=generate_uuid(),
                product_id=product.id,
                batch_id=b.id,
                type='out',
                quantity=deduct_from_batch,
                reference_type='manual',
                reference_id=dispatch_id,
                channel=clean_channel,
                stock_pool=target_pool,
                notes=clean_notes,
                created_by=user_id,
                created_at=now
            )
            db_session.add(txn)

        # If there were not enough tracked batches (e.g. initial legacy stock before batching),
        # record the unbatched remainder
        if remaining_to_deduct > 0:
            txn = InventoryTransaction(
                id=generate_uuid(),
                product_id=product.id,
                batch_id=None,
                type='out',
                quantity=remaining_to_deduct,
                reference_type='manual',
                reference_id=dispatch_id,
                channel=clean_channel,
                stock_pool=target_pool,
                notes=clean_notes,
                created_by=user_id,
                created_at=now
            )
            db_session.add(txn)

        db_session.commit()

        return {
            'product_id': product.id,
            'product_name': product.name,
            'quantity': qty,
            'channel': clean_channel,
            'stock_pool': target_pool,
            'stock_offline': product.stock_offline,
            'stock_online': product.stock_online,
            'stock_remaining': product.stock_qty,
            'batches_affected': batches_affected,
            'buffer_status': product.to_dict().get('buffer_status')
        }

    @classmethod
    def rebalance_stock_pool(
        cls,
        product_id: str,
        from_pool: str,
        to_pool: str,
        quantity: int,
        reason: str,
        user_id: str
    ):
        """
        Soft rebalancing: transfers quota between 'offline' and 'online' stock pools for a product.
        Leaves total physical stock in freezer unchanged, but shifts dispatch permissions.
        """
        clean_from = (from_pool or '').strip().lower()
        clean_to = (to_pool or '').strip().lower()
        if clean_from not in ('offline', 'online') or clean_to not in ('offline', 'online'):
            raise ValueError("Pool asal dan tujuan harus 'offline' atau 'online'.")
        if clean_from == clean_to:
            raise ValueError("Pool asal dan tujuan tidak boleh sama.")

        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            raise ValueError("Jumlah transfer kuota harus berupa bilangan bulat.")

        if qty <= 0:
            raise ValueError("Jumlah transfer kuota harus lebih dari 0.")

        product = db_session.get(Product, product_id, with_for_update=True)
        if not product:
            raise ValueError("Produk tidak ditemukan.")

        current_from = getattr(product, f"stock_{clean_from}")
        if current_from is None:
            current_from = product.stock_qty or 0
        current_from = int(current_from)

        if current_from < qty:
            raise ValueError(f"Stok pada pool {clean_from.upper()} tidak mencukupi untuk ditransfer. Tersedia: {current_from} pack, diminta: {qty} pack.")

        if clean_from == 'offline':
            product.stock_offline = current_from - qty
            product.stock_online = (product.stock_online or 0) + qty
        else:
            product.stock_online = current_from - qty
            product.stock_offline = (product.stock_offline or 0) + qty

        product.stock_qty = (product.stock_offline or 0) + (product.stock_online or 0)

        # Record adjustment transaction in InventoryTransaction
        now = utc_now()
        clean_reason = (reason or 'Transfer kuota stok antar channel').strip()[:250]
        txn = InventoryTransaction(
            id=generate_uuid(),
            product_id=product.id,
            batch_id=None,
            type='adjustment',
            quantity=qty,
            reference_type='manual',
            reference_id=generate_uuid(),
            channel=None,
            stock_pool=clean_to,
            notes=f"Rebalance: Transfer {qty} pack dari pool {clean_from.upper()} ke {clean_to.upper()}. Alasan: {clean_reason}",
            created_by=user_id,
            created_at=now
        )
        db_session.add(txn)
        db_session.commit()

        return {
            'product_id': product.id,
            'product_name': product.name,
            'from_pool': clean_from,
            'to_pool': clean_to,
            'quantity': qty,
            'stock_offline': product.stock_offline,
            'stock_online': product.stock_online,
            'stock_remaining': product.stock_qty,
            'notes': clean_reason
        }

    @classmethod
    def get_inventory_dashboard_summary(cls):
        """
        Returns aggregated summary for admin dashboard:
        - Total inventory count in stock
        - Buffer stock alerts (critical & warning)
        - Channel dispatch distribution
        - Today's lot production progress
        """
        products = db_session.query(Product).filter(Product.is_active == True).all()
        products_dict = [p.to_dict() for p in products]

        total_stock = sum((p.stock_qty or 0) for p in products)
        total_stock_offline = sum((p.stock_offline or 0) for p in products)
        total_stock_online = sum((p.stock_online or 0) for p in products)
        critical_products = [p for p in products_dict if p.get('buffer_status') == 'critical']
        warning_products = [p for p in products_dict if p.get('buffer_status') == 'warning']

        # Channel distribution from inventory transactions (type='out')
        txns = db_session.query(
            InventoryTransaction.channel,
            func.sum(InventoryTransaction.quantity).label('total_qty')
        ).filter(
            InventoryTransaction.type == 'out'
        ).group_by(InventoryTransaction.channel).all()

        channel_stats = {
            'shopee': 0,
            'tiktok': 0,
            'po_b2b': 0,
            'offline': 0,
            'web': 0,
            'waste': 0
        }
        total_out = 0
        for ch, qty in txns:
            if ch in channel_stats:
                channel_stats[ch] = int(qty or 0)
            total_out += int(qty or 0)

        # Today's production lots
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_batches = db_session.query(ProductionBatch).filter(
            ProductionBatch.created_at >= today_start
        ).all()

        today_planned_lots = sum(b.planned_lots for b in today_batches if b.status != 'cancelled')
        today_completed_lots = sum((b.actual_lots or 0) for b in today_batches if b.status == 'completed')
        today_completed_qty = sum((b.produced_qty or 0) for b in today_batches if b.status == 'completed')

        # 7-Day movement trend for stock in vs out
        now = datetime.now(timezone.utc)
        movement_7d = []
        for i in range(6, -1, -1):
            d = now - timedelta(days=i)
            d_start = d.replace(hour=0, minute=0, second=0, microsecond=0)
            d_end = d_start + timedelta(days=1)

            in_qty = db_session.query(func.sum(InventoryTransaction.quantity)).filter(
                InventoryTransaction.type == 'in',
                InventoryTransaction.created_at >= d_start,
                InventoryTransaction.created_at < d_end
            ).scalar() or 0

            out_qty = db_session.query(func.sum(InventoryTransaction.quantity)).filter(
                InventoryTransaction.type == 'out',
                InventoryTransaction.created_at >= d_start,
                InventoryTransaction.created_at < d_end
            ).scalar() or 0

            movement_7d.append({
                'date': d.strftime('%Y-%m-%d'),
                'day': d.strftime('%d %b'),
                'inQty': int(in_qty),
                'outQty': int(out_qty)
            })

        total_pieces = sum(
            (p.stock_qty or 0) * (50 if ('mika' in (p.sku or '').lower() or 'mika' in (p.name or '').lower()) else 25)
            for p in products
        )

        return {
            'total_stock_pcs': total_stock,
            'total_stock_packs': total_stock,
            'total_stock_pieces': total_pieces,
            'total_stock_lots': total_stock,
            'total_stock_offline': total_stock_offline,
            'total_stock_online': total_stock_online,
            'products_count': len(products),
            'critical_count': len(critical_products),
            'warning_count': len(warning_products),
            'critical_products': critical_products,
            'warning_products': warning_products,
            'all_products': products_dict,
            'channel_distribution': channel_stats,
            'total_out_pcs': total_out,
            'movement_7d': movement_7d,
            'today_production': {
                'planned_lots': today_planned_lots,
                'completed_lots': today_completed_lots,
                'completed_pcs': today_completed_qty,
                'capacity_lots': 450,
                'max_capacity_lots': 520
            }
        }

    # ==========================================
    # RAW MATERIALS & INVENTORY CONTROL (AYU)
    # ==========================================

    @classmethod
    def seed_default_raw_materials_if_empty(cls):
        """
        Seeds standard raw materials from client operational meeting if table is empty.
        """
        count = db_session.query(RawMaterial).count()
        if count > 0:
            return

        default_materials = [
            {
                'code': 'RM-AYAM',
                'name': 'Daging Ayam Fillet / Mentah',
                'category': 'daging',
                'unit': 'kg',
                'stock_qty': 120.0,
                'min_buffer': 70.0,
                'safe_target': 300.0,
                'cost_per_unit': 42000.0,
                'storage_location': 'Freezer Daging Mentah',
                'notes': 'Bahan baku utama gilingan adonan (15 kg per gilingan)'
            },
            {
                'code': 'RM-KULIT-9',
                'name': 'Kulit Dimsum 9 cm (Kemasan Mika)',
                'category': 'kulit',
                'unit': 'kg',
                'stock_qty': 95.0,
                'min_buffer': 30.0,
                'safe_target': 150.0,
                'cost_per_unit': 25000.0,
                'storage_location': 'Chiller Kulit',
                'notes': 'Digunakan khusus Dimsum Wadah Mika (isi 50 pcs)'
            },
            {
                'code': 'RM-KULIT-10',
                'name': 'Kulit Dimsum 10 cm (Kemasan Vakum)',
                'category': 'kulit',
                'unit': 'kg',
                'stock_qty': 40.0,
                'min_buffer': 15.0,
                'safe_target': 80.0,
                'cost_per_unit': 26000.0,
                'storage_location': 'Chiller Kulit',
                'notes': 'Digunakan khusus Dimsum Vakum (isi 25 pcs)'
            },
            {
                'code': 'RM-TEPUNG',
                'name': 'Tepung Tapioka / Adonan',
                'category': 'tepung',
                'unit': 'karung',
                'stock_qty': 8.0,
                'min_buffer': 3.0,
                'safe_target': 20.0,
                'cost_per_unit': 280000.0,
                'storage_location': 'Gudang Kering',
                'notes': '1 karung = 25 kg. Minimal cadangan 3 karung'
            },
            {
                'code': 'RM-MINYAK',
                'name': 'Minyak Goreng & Minyak Wijen',
                'category': 'minyak_bumbu',
                'unit': 'liter',
                'stock_qty': 45.0,
                'min_buffer': 15.0,
                'safe_target': 100.0,
                'cost_per_unit': 18000.0,
                'storage_location': 'Gudang Kering',
                'notes': 'Kebutuhan adonan & pelumas cetakan'
            },
            {
                'code': 'RM-BUMBU',
                'name': 'Bumbu Racik Adonan Dimsum',
                'category': 'minyak_bumbu',
                'unit': 'kg',
                'stock_qty': 60.0,
                'min_buffer': 20.0,
                'safe_target': 120.0,
                'cost_per_unit': 35000.0,
                'storage_location': 'Gudang Kering',
                'notes': 'Campuran garam, gula, bawang, penyedap rasa'
            },
            {
                'code': 'RM-SAOS',
                'name': 'Saos Sambal Dimsum Sachet',
                'category': 'saos',
                'unit': 'dus',
                'stock_qty': 12.0,
                'min_buffer': 5.0,
                'safe_target': 25.0,
                'cost_per_unit': 110000.0,
                'storage_location': 'Gudang Kering',
                'notes': 'Target harian keluar 3 dus saos'
            },
            {
                'code': 'RM-AIR-ABU',
                'name': 'Air Abu Adonan Kulit',
                'category': 'lainnya',
                'unit': 'botol',
                'stock_qty': 85.0,
                'min_buffer': 20.0,
                'safe_target': 100.0,
                'cost_per_unit': 12000.0,
                'storage_location': 'Gudang Kering',
                'notes': 'Diorder berkala per 100 botol'
            },
            {
                'code': 'RM-TOPPING',
                'name': 'Topping Keju, Sosis, Jamur, Crabstick',
                'category': 'topping',
                'unit': 'kg',
                'stock_qty': 18.0,
                'min_buffer': 5.0,
                'safe_target': 30.0,
                'cost_per_unit': 65000.0,
                'storage_location': 'Chiller Topping',
                'notes': 'Topping varian dimsum'
            }
        ]

        for item in default_materials:
            mat = RawMaterial(
                id=generate_uuid(),
                code=item['code'],
                name=item['name'],
                category=item['category'],
                unit=item['unit'],
                stock_qty=item['stock_qty'],
                min_buffer=item['min_buffer'],
                safe_target=item['safe_target'],
                cost_per_unit=item['cost_per_unit'],
                storage_location=item['storage_location'],
                notes=item['notes'],
                is_active=True
            )
            db_session.add(mat)
        db_session.commit()

    @classmethod
    def get_raw_materials(cls, category=None, search=None):
        cls.seed_default_raw_materials_if_empty()
        query = db_session.query(RawMaterial).filter(RawMaterial.is_active == True)

        if category and category != 'all':
            query = query.filter(RawMaterial.category == category)
        if search:
            s = f"%{search.strip()}%"
            query = query.filter((RawMaterial.name.ilike(s)) | (RawMaterial.code.ilike(s)))

        materials = query.order_by(RawMaterial.name.asc()).all()
        mat_dicts = [m.to_dict() for m in materials]

        critical_count = sum(1 for m in mat_dicts if m.get('buffer_status') == 'critical')
        warning_count = sum(1 for m in mat_dicts if m.get('buffer_status') == 'warning')
        safe_count = sum(1 for m in mat_dicts if m.get('buffer_status') == 'safe')

        return {
            'materials': mat_dicts,
            'total_count': len(mat_dicts),
            'critical_count': critical_count,
            'warning_count': warning_count,
            'safe_count': safe_count,
            'counts': {
                'total': len(mat_dicts),
                'critical': critical_count,
                'warning': warning_count,
                'safe': safe_count
            }
        }

    @classmethod
    def get_raw_material_by_id(cls, material_id: str):
        material = db_session.get(RawMaterial, material_id)
        if not material or not material.is_active:
            raise ValueError('Bahan baku tidak ditemukan.')
        return material

    @classmethod
    def create_raw_material(cls, data: dict, user_id: str = None):
        code = (data.get('code') or '').strip().upper()
        name = (data.get('name') or '').strip()
        category = data.get('category', 'lainnya')
        unit = (data.get('unit') or 'kg').strip().lower()

        if not code or not name:
            raise ValueError('Kode dan nama bahan baku wajib diisi.')

        existing = db_session.query(RawMaterial).filter_by(code=code).first()
        if existing:
            raise ValueError(f'Bahan baku dengan kode "{code}" sudah ada.')

        stock_qty = float(data.get('stock_qty') or 0.0)
        min_buffer = float(data.get('min_buffer') or 0.0)
        safe_target = float(data.get('safe_target') or (min_buffer * 2.0))
        cost_per_unit = float(data.get('cost_per_unit') or 0.0)

        material = RawMaterial(
            id=generate_uuid(),
            code=code,
            name=name,
            category=category,
            unit=unit,
            stock_qty=max(0.0, stock_qty),
            min_buffer=max(0.0, min_buffer),
            safe_target=max(0.0, safe_target),
            cost_per_unit=max(0.0, cost_per_unit),
            storage_location=data.get('storage_location'),
            notes=data.get('notes'),
            is_active=True
        )
        db_session.add(material)

        # Record initial stock transaction if > 0
        if stock_qty > 0:
            tx = RawMaterialTransaction(
                id=generate_uuid(),
                material_id=material.id,
                type='in',
                quantity=stock_qty,
                previous_stock=0.0,  # Initial stock was 0 before this transaction
                new_stock=stock_qty,
                reference_type='manual',
                notes='Saldo awal bahan baku',
                created_by=user_id
            )
            db_session.add(tx)

        db_session.commit()
        return material.to_dict()

    @classmethod
    def update_raw_material(cls, material_id: str, data: dict):
        material = cls.get_raw_material_by_id(material_id)

        if 'name' in data and data['name']:
            material.name = data['name'].strip()
        if 'category' in data and data['category']:
            material.category = data['category']
        if 'unit' in data and data['unit']:
            material.unit = data['unit'].strip().lower()
        if 'min_buffer' in data:
            material.min_buffer = max(0.0, float(data['min_buffer']))
        if 'safe_target' in data:
            material.safe_target = max(0.0, float(data['safe_target']))
        if 'cost_per_unit' in data:
            material.cost_per_unit = max(0.0, float(data['cost_per_unit']))
        if 'storage_location' in data:
            material.storage_location = data['storage_location']
        if 'notes' in data:
            material.notes = data['notes']

        db_session.commit()
        return material.to_dict()

    @classmethod
    def record_raw_material_transaction(
        cls,
        material_id: str,
        tx_type: str,
        quantity: float,
        reference_type: str = 'manual',
        notes: str = None,
        user_id: str = None,
        batch_gilingan: int = None,
        reference_id: str = None
    ):
        """
        Records IN (belanja/restock) or OUT (pemakaian produksi) atomically.
        """
        material = db_session.get(RawMaterial, material_id, with_for_update=True)
        if not material or not material.is_active:
            raise ValueError('Bahan baku tidak ditemukan.')

        try:
            qty = float(quantity)
        except (ValueError, TypeError):
            raise ValueError('Jumlah kuantitas harus berupa angka valid.')

        if qty <= 0:
            raise ValueError('Jumlah kuantitas harus lebih dari 0.')

        if tx_type not in ('in', 'out', 'adjustment'):
            raise ValueError('Tipe transaksi harus "in", "out", atau "adjustment".')

        # Normalize reference_type (map 'restock' -> 'purchase' to match DB Enum)
        if reference_type == 'restock':
            reference_type = 'purchase'
        elif reference_type not in ('purchase', 'production_usage', 'waste', 'manual'):
            reference_type = 'manual'

        current_stock = material.stock_qty or 0.0
        previous_stock = current_stock  # Store before modification

        if tx_type == 'out':
            if current_stock < qty:
                raise ValueError(
                    f'Stok {material.name} tidak mencukupi (Tersedia: {current_stock} {material.unit}, Dibutuhkan: {qty} {material.unit}).'
                )
            material.stock_qty = current_stock - qty
        elif tx_type == 'in':
            material.stock_qty = current_stock + qty
        elif tx_type == 'adjustment':
            material.stock_qty = qty  # Set new absolute count

        new_stock = material.stock_qty  # Store after modification

        tx = RawMaterialTransaction(
            id=generate_uuid(),
            material_id=material.id,
            type=tx_type,
            quantity=qty,
            previous_stock=previous_stock,
            new_stock=new_stock,
            reference_type=reference_type,
            reference_id=reference_id,
            batch_gilingan=batch_gilingan,
            notes=notes,
            created_by=user_id
        )
        db_session.add(tx)
        db_session.commit()

        return {
            'transaction': tx.to_dict(),
            'updated_stock': material.stock_qty,
            'material': material.to_dict()
        }

    @classmethod
    def get_raw_material_transactions(cls, material_id: str = None, action: str = None, limit: int = 50):
        cls.seed_default_raw_materials_if_empty()
        query = db_session.query(RawMaterialTransaction)

        if material_id:
            query = query.filter(RawMaterialTransaction.material_id == material_id)
        if action:
            query = query.filter(RawMaterialTransaction.type == action)

        txs = query.order_by(RawMaterialTransaction.created_at.desc()).limit(limit).all()
        return [t.to_dict() for t in txs]

    @classmethod
    def check_production_readiness(cls, target_gilingan: int = 36):
        """
        BOM & Readiness Calculator for Ayu (Inventory Control):
        Checks if current stock in raw_materials is sufficient for target_gilingan production.
        Target standar: 36 gilingan/hari (30 Mika + 6 Vakum).
        """
        cls.seed_default_raw_materials_if_empty()
        try:
            tg = int(target_gilingan or 36)
        except (ValueError, TypeError):
            tg = 36

        if tg <= 0:
            tg = 36

        # Ratio: 30 Mika (83.33%), 6 Vakum (16.67%)
        ratio_mika = 30 / 36
        ratio_vakum = 6 / 36

        gilingan_mika = tg * ratio_mika
        gilingan_vakum = tg * ratio_vakum

        # BOM Standard Requirements:
        # 1. Daging Ayam: 15 kg per gilingan
        req_daging = tg * 15.0  # 36 * 15 = 540 kg
        # 2. Kulit Dimsum 9cm: 3 kg per gilingan Mika (90 kg untuk 30 gilingan)
        req_kulit_9 = gilingan_mika * 3.0
        # 3. Kulit Dimsum 10cm: 5 kg per gilingan Vakum (30 kg untuk 6 gilingan)
        req_kulit_10 = gilingan_vakum * 5.0
        # 4. Tepung: ~2 karung per 36 gilingan
        req_tepung = max(1.0, round((tg / 36.0) * 2.0, 1))
        # 5. Minyak: ~1.2 liter per gilingan
        req_minyak = round(tg * 1.2, 1)
        # 6. Bumbu: ~1.6 kg per gilingan
        req_bumbu = round(tg * 1.6, 1)
        # 7. Saos: 3 dus per 36 gilingan
        req_saos = max(1.0, round((tg / 36.0) * 3.0, 1))
        # 8. Topping: ~3 kg per 36 gilingan
        req_topping = max(1.0, round((tg / 36.0) * 3.0, 1))

        bom_definitions = {
            'RM-AYAM': {'name': 'Daging Ayam Mentah', 'req': req_daging, 'unit': 'kg', 'notes': '15 kg / gilingan'},
            'RM-KULIT-9': {'name': 'Kulit Dimsum 9 cm (Mika)', 'req': req_kulit_9, 'unit': 'kg', 'notes': '3 kg / gilingan mika'},
            'RM-KULIT-10': {'name': 'Kulit Dimsum 10 cm (Vakum)', 'req': req_kulit_10, 'unit': 'kg', 'notes': '5 kg / gilingan vakum'},
            'RM-TEPUNG': {'name': 'Tepung Tapioka / Adonan', 'req': req_tepung, 'unit': 'karung', 'notes': '2 karung / 36 gilingan'},
            'RM-MINYAK': {'name': 'Minyak Goreng & Wijen', 'req': req_minyak, 'unit': 'liter', 'notes': '1.2 liter / gilingan'},
            'RM-BUMBU': {'name': 'Bumbu Racik Adonan', 'req': req_bumbu, 'unit': 'kg', 'notes': '1.6 kg / gilingan'},
            'RM-SAOS': {'name': 'Saos Sambal Dimsum', 'req': req_saos, 'unit': 'dus', 'notes': '3 dus / 36 gilingan'},
            'RM-TOPPING': {'name': 'Topping Aneka Rasa', 'req': req_topping, 'unit': 'kg', 'notes': '3 dus/kg / 36 gilingan'}
        }

        materials = db_session.query(RawMaterial).filter(RawMaterial.is_active == True).all()
        mat_map = {m.code: m for m in materials}

        readiness_items = []
        overall_ready = True
        shortage_items_count = 0

        for code, spec in bom_definitions.items():
            mat = mat_map.get(code)
            current_stock = mat.stock_qty if mat else 0.0
            required_qty = spec['req']
            unit = mat.unit if mat else spec['unit']
            name = mat.name if mat else spec['name']

            is_ready = current_stock >= required_qty
            deficit = max(0.0, required_qty - current_stock)

            if not is_ready:
                overall_ready = False
                shortage_items_count += 1

            fulfillment_percent = min(100, int((current_stock / required_qty * 100))) if required_qty > 0 else 100

            readiness_items.append({
                'material_id': mat.id if mat else None,
                'code': code,
                'name': name,
                'unit': unit,
                'required_qty': required_qty,
                'required': required_qty,
                'current_stock': current_stock,
                'is_ready': is_ready,
                'status': 'SIAP' if is_ready else 'KURANG',
                'notes': spec.get('notes', ''),
                'deficit': deficit,
                'fulfillment_percent': fulfillment_percent,
                'storage_location': mat.storage_location if mat else 'Gudang'
            })

        deficits = [
            {
                'material_id': it['material_id'],
                'code': it['code'],
                'name': it['name'],
                'unit': it['unit'],
                'required': it['required_qty'],
                'current_stock': it['current_stock'],
                'deficit': it['deficit']
            }
            for it in readiness_items if not it['is_ready']
        ]

        return {
            'target_gilingan': tg,
            'estimated_finished_packs': int(tg * 12.5),  # 36 gilingan menghasilkan ~450 pack
            'overall_ready': overall_ready,
            'overall_status': 'SIAP' if overall_ready else 'KURANG',
            'shortage_count': shortage_items_count,
            'deficits': deficits,
            'items': readiness_items,
            'checked_at': utc_now().isoformat()
        }

    # =========================================================================
    # PRODUCTION PLANNING MINGGUAN (TUGAS LALA & PPSI)
    # =========================================================================

    @classmethod
    def get_weekly_production_plans(cls, start_date_str: str = None) -> dict:
        """
        Retrieves or initializes a 7-day production plan (Monday to Sunday).
        Connects target finished goods (Mika/Vakum) with H-1 Raw Material readiness.
        """
        day_names = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']

        today = utc_now().date()
        current_week_monday = today - timedelta(days=today.weekday())  # Current week Monday
        max_future_monday = current_week_monday + timedelta(days=14)   # Max 2 weeks ahead

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError('Format tanggal harus YYYY-MM-DD.')
            # Enforce max 2 weeks ahead rule
            if start_date > max_future_monday:
                start_date = max_future_monday
        else:
            start_date = current_week_monday

        dates = [start_date + timedelta(days=i) for i in range(7)]

        # Fetch existing plans
        existing_plans = db_session.query(DailyProductionPlan).filter(
            DailyProductionPlan.plan_date.in_(dates)
        ).all()
        plan_map = {p.plan_date: p for p in existing_plans}

        plans_to_return = []
        is_new_created = False
        
        active_production_days = SettingsService.get_active_production_days()

        for idx, d in enumerate(dates):
            p = plan_map.get(d)
            if not p:
                if today <= d <= (max_future_monday + timedelta(days=6)):
                    # Check if today is an active production day
                    is_active = d.weekday() in active_production_days
                    
                    if is_active:
                        p = DailyProductionPlan(
                            id=generate_uuid(),
                            plan_date=d,
                            day_of_week=day_names[idx],
                            target_mika=350,
                            target_vakum=100,
                            target_online=180,
                            target_offline=270,
                            gilingan_mika=30.0,
                            gilingan_vakum=6.0,
                            total_gilingan=36.0,
                            status='scheduled',
                            batches_generated=False
                        )
                    else:
                        p = DailyProductionPlan(
                            id=generate_uuid(),
                            plan_date=d,
                            day_of_week=day_names[idx],
                            target_mika=0,
                            target_vakum=0,
                            target_online=0,
                            target_offline=0,
                            gilingan_mika=0.0,
                            gilingan_vakum=0.0,
                            total_gilingan=0.0,
                            status='scheduled',
                            batches_generated=False
                        )
                    db_session.add(p)
                    is_new_created = True
                else:
                    # For past days or out-of-range days, do not persist dummy plans
                    p = DailyProductionPlan(
                        id=generate_uuid(),
                        plan_date=d,
                        day_of_week=day_names[idx],
                        target_mika=0,
                        target_vakum=0,
                        target_online=0,
                        target_offline=0,
                        gilingan_mika=0.0,
                        gilingan_vakum=0.0,
                        total_gilingan=0.0,
                        status='completed',
                        batches_generated=False
                    )
            plans_to_return.append(p)

        if is_new_created:
            db_session.commit()

        # Check raw material readiness and batches for each day
        enriched_plans = []
        date_str_list = [d.strftime('%Y%m%d') for d in dates]

        # Query all batches matching these dates
        all_batches = db_session.query(ProductionBatch).filter(
            ProductionBatch.status != 'cancelled'
        ).all()

        for p in plans_to_return:
            p_dict = p.to_dict()
            p_date_str = p.plan_date.strftime('%Y%m%d')
            p_date_obj = p.plan_date

            # Filter batches associated with this day
            day_batches = [
                b for b in all_batches
                if p_date_str in (b.batch_code or '') or (b.planned_at and b.planned_at.date() == p_date_obj)
            ]

            # Calculate actual production yield if confirmed
            actual_mika = sum(
                (b.actual_lots or 0) for b in day_batches
                if b.status == 'completed' and (b.lot_size == 50 or 'MIKA' in (b.product.sku if b.product else '').upper())
            )
            actual_vakum = sum(
                (b.actual_lots or 0) for b in day_batches
                if b.status == 'completed' and (b.lot_size == 25 or 'VAKUM' in (b.product.sku if b.product else '').upper())
            )

            # Check readiness for required gilingan
            readiness = cls.check_production_readiness(target_gilingan=int(p.total_gilingan or 36))
            p_dict['readiness'] = {
                'overall_ready': readiness.get('overall_ready', True),
                'shortage_count': readiness.get('shortage_count', 0),
                'deficits': [
                    {'name': it['name'], 'deficit': it['deficit'], 'unit': it['unit']}
                    for it in readiness.get('items', []) if not it['is_ready']
                ]
            }

            p_dict['actual_produced_mika'] = actual_mika
            p_dict['actual_produced_vakum'] = actual_vakum
            p_dict['total_actual_packs'] = actual_mika + actual_vakum
            p_dict['batches'] = [b.to_dict() for b in day_batches]
            p_dict['is_past'] = (p.plan_date < today)
            p_dict['is_today'] = (p.plan_date == today)
            p_dict['is_future'] = (p.plan_date > today)
            enriched_plans.append(p_dict)

        # Check if there is any REAL recorded production data prior to start_date
        # Real recorded data = actual batches OR plans that had batches generated / custom notes
        has_past_batches = db_session.query(ProductionBatch).filter(
            ProductionBatch.planned_at < datetime.combine(start_date, datetime.min.time()),
            ProductionBatch.status != 'cancelled'
        ).first() is not None

        has_past_plans = db_session.query(DailyProductionPlan).filter(
            DailyProductionPlan.plan_date < start_date,
            (DailyProductionPlan.batches_generated == True) | 
            ((DailyProductionPlan.notes != None) & (DailyProductionPlan.notes != ''))
        ).first() is not None

        can_navigate_backward = has_past_batches or has_past_plans
        can_navigate_forward = (start_date < max_future_monday)

        return {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': (start_date + timedelta(days=6)).strftime('%Y-%m-%d'),
            'has_past_data': can_navigate_backward,
            'can_navigate_backward': can_navigate_backward,
            'can_navigate_forward': can_navigate_forward,
            'max_future_date': max_future_monday.strftime('%Y-%m-%d'),
            'current_week_start': current_week_monday.strftime('%Y-%m-%d'),
            'plans': enriched_plans,
            'weekly_totals': cls._calculate_weekly_totals(enriched_plans)
        }

    @classmethod
    def _calculate_weekly_totals(cls, enriched_plans):
        totals = {
            'target_mika': 0,
            'target_vakum': 0,
            'total_packs': 0,
            'total_gilingan': 0,
            'target_online': 0,
            'target_offline': 0,
            'product_targets': []
        }
        
        target_map = {}
        
        for p in enriched_plans:
            totals['target_mika'] += p.get('target_mika', 0)
            totals['target_vakum'] += p.get('target_vakum', 0)
            totals['total_packs'] += p.get('total_target_packs', 0)
            totals['total_gilingan'] += p.get('total_gilingan', 0)
            totals['target_online'] += p.get('target_online', 0)
            totals['target_offline'] += p.get('target_offline', 0)
            
            for pt in p.get('product_targets', []):
                pid = pt['product_id']
                if pid not in target_map:
                    target_map[pid] = {
                        'product_name': pt['product_name'],
                        'pack_size': pt['pack_size'],
                        'total_quantity': 0
                    }
                target_map[pid]['total_quantity'] += pt['target_quantity']
                
        totals['product_targets'] = list(target_map.values())
        totals['total_gilingan'] = round(totals['total_gilingan'], 1)
        return totals

    @classmethod
    def upsert_daily_production_plan(cls, plan_date_str: str, data: dict, user_id: str = None) -> dict:
        """
        Updates target quantities and demand allocations for a specific day.
        Supports both legacy (target_mika/target_vakum) and new (product_targets) formats.
        Automatically converts finished pack targets into dough gilingan requirement.
        """
        try:
            p_date = datetime.strptime(plan_date_str, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Format tanggal harus YYYY-MM-DD.')

        plan = db_session.query(DailyProductionPlan).filter(
            DailyProductionPlan.plan_date == p_date
        ).first()

        day_names = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
        day_name = day_names[p_date.weekday()]

        if not plan:
            plan = DailyProductionPlan(
                id=generate_uuid(),
                plan_date=p_date,
                day_of_week=day_name,
                created_by=user_id
            )
            db_session.add(plan)

        # Handle product_targets (new dynamic format)
        if 'product_targets' in data:
            # Clear existing targets
            db_session.query(ProductionTarget).filter_by(plan_id=plan.id).delete()
            
            product_targets = data.get('product_targets', [])
            total_packs = 0
            total_pieces = 0
            
            for target_data in product_targets:
                product_id = target_data.get('product_id')
                target_quantity = max(0, int(target_data.get('target_quantity', 0)))
                
                if not product_id or target_quantity <= 0:
                    continue
                
                # Get product to fetch pack_size
                product = db_session.get(Product, product_id)
                if not product:
                    continue
                
                pack_size = product.pack_size or 25
                
                # Calculate ingredients needed for this target
                ingredients_needed = IngredientService.calculate_ingredients_needed(
                    db_session, product_id, target_quantity
                )
                
                new_target = ProductionTarget(
                    plan_id=plan.id,
                    product_id=product_id,
                    target_quantity=target_quantity,
                    pack_size=pack_size,
                    ingredients_needed=json.dumps(ingredients_needed) if ingredients_needed else None
                )
                db_session.add(new_target)
                
                total_packs += target_quantity
                total_pieces += target_quantity * pack_size
            
            # Update legacy columns for backward compatibility
            # Assume 1 gilingan produces ~11.66 packs on average (or use custom ratio)
            plan.total_gilingan = round(total_packs / 11.66, 1) if total_packs > 0 else 0.0
            plan.target_mika = 0  # Set to 0 when using dynamic targets
            plan.target_vakum = 0
            plan.gilingan_mika = 0.0
            plan.gilingan_vakum = 0.0
        
        # Handle legacy format (target_mika/target_vakum)
        else:
            target_mika = max(0, int(data.get('target_mika', plan.target_mika or 350)))
            target_vakum = max(0, int(data.get('target_vakum', plan.target_vakum or 100)))

            plan.target_mika = target_mika
            plan.target_vakum = target_vakum

            # Convert to dough gilingan:
            # 350 Mika ≈ 30 gilingan (rasio: 350 / 30 ≈ 11.66 mika per gilingan)
            # 100 Vakum ≈ 6 gilingan (rasio: 100 / 6 ≈ 16.66 vakum per gilingan)
            plan.gilingan_mika = round((target_mika / 350.0) * 30.0, 1) if target_mika > 0 else 0.0
            plan.gilingan_vakum = round((target_vakum / 100.0) * 6.0, 1) if target_vakum > 0 else 0.0
            plan.total_gilingan = round(plan.gilingan_mika + plan.gilingan_vakum, 1)

        # Update stock pool allocations (Online vs Offline)
        plan.target_online = max(0, int(data.get('target_online', plan.target_online or 0)))
        plan.target_offline = max(0, int(data.get('target_offline', plan.target_offline or 0)))

        if 'notes' in data:
            plan.notes = (data['notes'] or '').strip()[:500]
        if 'status' in data and data['status'] in ('draft', 'scheduled', 'in_progress', 'completed'):
            plan.status = data['status']

        db_session.commit()
        return plan.to_dict()

    @classmethod
    def generate_batches_from_plan(cls, plan_id: str, user_id: str = None) -> dict:
        """
        Creates ProductionBatch entries from the daily plan.
        Supports both legacy (target_mika/target_vakum) and new (product_targets) formats.
        Batches immediately enter Checker queue (Om Yosi).
        """
        plan = db_session.get(DailyProductionPlan, plan_id)
        if not plan:
            raise ValueError('Rencana produksi harian tidak ditemukan.')

        if plan.plan_date < utc_now().date():
            raise ValueError('Tidak dapat memulai produksi untuk tanggal yang sudah lewat.')

        created_batches = []
        
        # Use dynamic product targets if available, otherwise fall back to legacy format
        if plan.targets and len(plan.targets) > 0:
            # Generate batches for each product target
            for target in plan.targets:
                if target.target_quantity <= 0:
                    continue
                
                product = db_session.get(Product, target.product_id)
                if not product:
                    continue
                
                pack_size = product.pack_size or target.pack_size or 25
                
                # Calculate already generated lots for this product
                gen_qty = 0
                for batch in plan.batches.all():
                    if batch.product_id == target.product_id:
                        gen_qty += batch.planned_lots or 0
                
                delta_qty = target.target_quantity - gen_qty
                if delta_qty <= 0:
                    continue
                
                product_name = product.name or "Produk"
                notes = f"Rencana Lala ({plan.day_of_week}, {plan.plan_date}) - Target {delta_qty} {product_name} ({pack_size} pcs/unit)"
                
                if gen_qty > 0:
                    notes = f"Rencana Lala ({plan.day_of_week}, {plan.plan_date}) - Susulan Target {delta_qty} {product_name} ({pack_size} pcs/unit)"
                
                batch = cls.create_production_plan(
                    product_id=target.product_id,
                    planned_lots=delta_qty,
                    notes=notes,
                    user_id=user_id or plan.created_by,
                    lot_size=pack_size,
                    daily_plan_id=plan.id
                )
                created_batches.append(batch)
        else:
            # Legacy format: Mika and Vakum only
            products = db_session.query(Product).filter(Product.is_active == True).all()
            if not products:
                raise ValueError('Tidak ada produk aktif di katalog untuk dibuatkan rencana batch.')

            # Match Mika Product (50 pcs)
            mika_product = next(
                (p for p in products if 'MIKA-50' in (p.sku or '').upper() or '50' in (p.sku or '').upper() or 'MIKA' in (p.name or '').upper()),
                None
            )
            # Match Vakum / Pax Product (25 pcs)
            vakum_product = next(
                (p for p in products if 'VAKUM' in (p.sku or '').upper() or 'PAX-25' in (p.sku or '').upper() or '25' in (p.sku or '').upper()),
                None
            )

            if not mika_product:
                mika_product = products[0]
            if not vakum_product:
                vakum_product = products[1] if len(products) > 1 else products[0]

            gen_mika = sum(b.planned_lots for b in plan.batches.filter_by(lot_size=50).all()) if plan.batches else 0
            gen_vakum = sum(b.planned_lots for b in plan.batches.filter_by(lot_size=25).all()) if plan.batches else 0
            
            delta_mika = (plan.target_mika or 0) - gen_mika
            delta_vakum = (plan.target_vakum or 0) - gen_vakum

            # 1. Generate Mika Batch (Only if delta > 0)
            if delta_mika > 0:
                mika_notes = f"Rencana Lala ({plan.day_of_week}, {plan.plan_date}) - Susulan Target {delta_mika} Mika (50 pcs/wadah)" if gen_mika > 0 else f"Rencana Lala ({plan.day_of_week}, {plan.plan_date}) - Target {plan.target_mika} Mika (50 pcs/wadah)"
                b_mika = cls.create_production_plan(
                    product_id=mika_product.id,
                    planned_lots=delta_mika,
                    notes=mika_notes,
                    user_id=user_id or plan.created_by,
                    lot_size=50,
                    daily_plan_id=plan.id
                )
                created_batches.append(b_mika)

            # 2. Generate Vakum Batch (Only if delta > 0)
            if delta_vakum > 0:
                vakum_notes = f"Rencana Lala ({plan.day_of_week}, {plan.plan_date}) - Susulan Target {delta_vakum} Vakum (25 pcs/pack)" if gen_vakum > 0 else f"Rencana Lala ({plan.day_of_week}, {plan.plan_date}) - Target {plan.target_vakum} Vakum (25 pcs/pack)"
                b_vakum = cls.create_production_plan(
                    product_id=vakum_product.id,
                    planned_lots=delta_vakum,
                    notes=vakum_notes,
                    user_id=user_id or plan.created_by,
                    lot_size=25,
                    daily_plan_id=plan.id
                )
                created_batches.append(b_vakum)

        plan.batches_generated = True
        plan.status = 'in_progress'
        db_session.commit()

        return {
            'plan_id': plan.id,
            'plan_date': plan.plan_date.strftime('%Y-%m-%d'),
            'batches_created': [b.to_dict() for b in created_batches]
        }




    # =========================================================================
    # PRODUKSI 1 (P1) - LOT TRACKING & CHECKLIST HARIAN (TUGAS AYU / IC)
    # =========================================================================

    @classmethod
    def log_gilingan(cls, jumlah_gilingan, notes=None, tanggal_str=None, user_id=None, force=False):
        import json
        with _log_gilingan_lock:
            db_session.expire_all()
            try:
                jumlah = int(jumlah_gilingan)
            except (ValueError, TypeError):
                raise ValueError('Jumlah gilingan harus berupa bilangan bulat.')
            if jumlah <= 0 or jumlah > 200:
                raise ValueError('Jumlah gilingan harus antara 1 sampai 200.')
            if tanggal_str:
                try:
                    tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError('Format tanggal harus YYYY-MM-DD.')
            else:
                tanggal = utc_now().date()

            # EC-1 & EC-8: Proteksi duplikasi gilingan harian (cek apakah tanggal ini sudah pernah dicatat)
            existing_lots = db_session.query(ProductionLot).filter(
                ProductionLot.tanggal == tanggal
            ).all()
            if existing_lots and not force:
                total_recorded = sum(l.actual_gilingan or 0 for l in existing_lots)
                raise ValueError(
                    f'Gilingan untuk tanggal {tanggal.strftime("%d/%m/%Y")} sudah pernah dicatat '
                    f'({total_recorded} gilingan, {len(existing_lots)} kali). '
                    f'Aktifkan konfirmasi (force=True) jika ini shift tambahan.'
                )

            plan_today = db_session.query(DailyProductionPlan).filter(
                DailyProductionPlan.plan_date == tanggal
            ).first()
            target_gilingan = int(plan_today.total_gilingan) if plan_today else 36
            gilingan_mika = jumlah * (30 / 36)
            gilingan_vakum = jumlah * (6 / 36)
            bom_deductions = {
                'RM-AYAM':    {'qty': round(jumlah * 15.0, 2)},
                'RM-KULIT-9': {'qty': round(gilingan_mika * 3.0, 2)},
                'RM-KULIT-10':{'qty': round(gilingan_vakum * 5.0, 2)},
                'RM-TEPUNG':  {'qty': round((jumlah / 36.0) * 2.0, 2)},
                'RM-MINYAK':  {'qty': round(jumlah * 1.2, 2)},
                'RM-BUMBU':   {'qty': round(jumlah * 1.6, 2)},
                'RM-SAOS':    {'qty': round((jumlah / 36.0) * 3.0, 2)},
                'RM-TOPPING': {'qty': round((jumlah / 36.0) * 3.0, 2)},
            }
            materials = db_session.query(RawMaterial).filter(RawMaterial.is_active == True).all()
            mat_map = {m.code: m for m in materials}
            deducted_items = []
            skipped_items = []
            shortage_items = []
            lot_ref_id = generate_uuid()
            tanggal_fmt = tanggal.strftime('%d/%m/%Y')
            for code, spec in bom_deductions.items():
                mat = mat_map.get(code)
                qty = spec['qty']
                if qty <= 0:
                    continue
                if not mat:
                    skipped_items.append({'code': code, 'reason': 'Bahan tidak ditemukan'})
                    continue
                current_stock = mat.stock_qty or 0.0
                if current_stock < qty:
                    shortage_items.append({
                        'material': mat.name,
                        'code': code,
                        'unit': mat.unit,
                        'requested': qty,
                        'available': current_stock,
                        'deficit': round(qty - current_stock, 2)
                    })
                actual_deduct = min(qty, current_stock)
                previous_stock = current_stock
                mat.stock_qty = max(0.0, current_stock - qty)
                new_stock = mat.stock_qty
                tx = RawMaterialTransaction(
                    id=generate_uuid(), material_id=mat.id, type='out',
                    quantity=actual_deduct,
                    previous_stock=previous_stock,
                    new_stock=new_stock,
                    reference_type='production_usage',
                    reference_id=lot_ref_id, batch_gilingan=jumlah,
                    notes=f'Pemakaian P1: {jumlah} Gilingan ({tanggal_fmt})',
                    created_by=user_id
                )
                db_session.add(tx)
                deducted_items.append({'material': mat.name, 'code': code, 'unit': mat.unit,
                    'deducted': actual_deduct, 'stock_before': current_stock, 'stock_after': mat.stock_qty})
            lot = ProductionLot(id=generate_uuid(), tanggal=tanggal, target_gilingan=target_gilingan,
                actual_gilingan=jumlah, notes=(notes or '').strip()[:500] if notes else None, created_by=user_id)
            db_session.add(lot)
            db_session.commit()
            return {
                'lot': lot.to_dict(),
                'deducted_items': deducted_items,
                'skipped_items': skipped_items,
                'shortage_items': shortage_items,
                'has_shortage': len(shortage_items) > 0,
                'summary': {
                    'jumlah_gilingan': jumlah,
                    'target_gilingan': target_gilingan,
                    'daging_dipakai_kg': jumlah * 15,
                    'status': 'achieved' if jumlah >= target_gilingan else 'below_target'
                }
            }

    @classmethod
    def get_production_log(cls, limit=30, tanggal_str=None):
        query = db_session.query(ProductionLot).order_by(ProductionLot.tanggal.desc())
        if tanggal_str:
            try:
                tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date()
                query = query.filter(ProductionLot.tanggal == tanggal)
            except ValueError:
                pass
        lots = query.limit(limit).all()
        total_target = sum(l.target_gilingan or 36 for l in lots)
        total_actual = sum(l.actual_gilingan or 0 for l in lots)
        days_below = sum(1 for l in lots if (l.actual_gilingan or 0) < (l.target_gilingan or 36))
        return {'logs': [l.to_dict() for l in lots], 'summary': {
            'total_records': len(lots), 'total_target_gilingan': total_target,
            'total_actual_gilingan': total_actual, 'total_gap': total_actual - total_target,
            'days_below_target': days_below, 'days_achieved': len(lots) - days_below,
            'overall_achievement_percent': min(100, int((total_actual / total_target) * 100)) if total_target > 0 else 100}}

    @classmethod
    def submit_daily_stock_check(cls, tanggal_str, target_gilingan, notes=None, user_id=None):
        import json
        try:
            tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Format tanggal harus YYYY-MM-DD.')
        readiness = cls.check_production_readiness(target_gilingan=int(target_gilingan or 36))
        shortage_items = [{'name': item['name'], 'deficit': item['deficit'], 'unit': item['unit']}
            for item in readiness.get('items', []) if not item['is_ready']]
        check = DailyStockCheck(id=generate_uuid(), tanggal=tanggal, target_gilingan=int(target_gilingan or 36),
            all_items_sufficient=readiness.get('overall_ready', False), shortage_count=len(shortage_items),
            shortage_items=json.dumps(shortage_items) if shortage_items else None,
            notes=(notes or '').strip()[:500] if notes else None, checked_by=user_id)
        db_session.add(check)
        db_session.commit()
        return {'check': check.to_dict(), 'readiness_detail': readiness,
            'message': (f'Cek H-1 selesai! Semua bahan mencukupi untuk {target_gilingan} gilingan.'
                if readiness.get('overall_ready')
                else f'Cek H-1 selesai! {len(shortage_items)} bahan KURANG. Segera lakukan restock!')}

    @classmethod
    def get_latest_daily_check(cls, tanggal_str=None):
        """Ambil DailyStockCheck terakhir untuk tanggal tertentu (default: hari ini)."""
        from datetime import date as date_type
        if tanggal_str:
            try:
                tanggal = datetime.strptime(tanggal_str, '%Y-%m-%d').date()
            except ValueError:
                tanggal = date_type.today()
        else:
            tanggal = date_type.today()

        check = (
            db_session.query(DailyStockCheck)
            .filter(DailyStockCheck.tanggal == tanggal)
            .order_by(DailyStockCheck.created_at.desc())
            .first()
        )
        return {'check': check.to_dict() if check else None, 'tanggal': tanggal.strftime('%Y-%m-%d')}
