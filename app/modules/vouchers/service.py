import logging
from app.core.db import db_session
from app.modules.vouchers.models import Voucher
from app.shared.utils import utc_now

logger = logging.getLogger(__name__)

class VoucherService:
    @staticmethod
    def get_by_code(code: str):
        if not code:
            return None
        norm_code = code.strip().upper()
        return db_session.query(Voucher).filter(Voucher.code == norm_code).first()

    @classmethod
    def calculate_discount(cls, voucher: Voucher, subtotal_float: float) -> dict:
        now = utc_now()
        # Check start date
        if voucher.start_date:
            s_date = voucher.start_date
            if hasattr(s_date, 'tzinfo') and s_date.tzinfo is None:
                now_cmp = now.replace(tzinfo=None)
            else:
                now_cmp = now
            if now_cmp < s_date:
                raise ValueError("Kode promo belum dapat digunakan")

        # Check expiry date
        if voucher.end_date:
            e_date = voucher.end_date
            if hasattr(e_date, 'tzinfo') and e_date.tzinfo is None:
                now_cmp = now.replace(tzinfo=None)
            else:
                now_cmp = now
            if now_cmp > e_date:
                raise ValueError("Kode promo sudah kedaluwarsa")

        # Check usage limit
        if voucher.usage_limit is not None and voucher.used_count >= voucher.usage_limit:
            raise ValueError("Kuota pemakaian kode promo sudah habis")

        # Check minimum spend
        min_spend = float(voucher.min_spend or 0.0)
        if subtotal_float < min_spend:
            formatted_min = f"Rp{int(min_spend):,}".replace(',', '.')
            raise ValueError(f"Minimal belanja untuk promo ini adalah {formatted_min}")

        # Calculate discount
        if voucher.discount_type == 'percent':
            raw_discount = (float(voucher.discount_value) / 100.0) * subtotal_float
            if voucher.max_discount is not None:
                raw_discount = min(raw_discount, float(voucher.max_discount))
            calculated_discount = min(raw_discount, subtotal_float)
        else:
            calculated_discount = min(float(voucher.discount_value), subtotal_float)

        return {
            'code': voucher.code,
            'discount': round(calculated_discount),
            'min_spend': min_spend,
            'discount_type': voucher.discount_type,
            'discount_value': float(voucher.discount_value),
            'max_discount': float(voucher.max_discount) if voucher.max_discount is not None else None,
            'end_date': voucher.end_date.isoformat() if voucher.end_date else None
        }

    @classmethod
    def validate_voucher(cls, code: str, subtotal: float) -> dict:
        """
        Read-only validation of voucher (used by /api/vouchers/validate).
        """
        if not code:
            raise ValueError("Kode voucher harus diisi")

        norm_code = code.strip().upper()
        voucher = cls.get_by_code(norm_code)

        if not voucher:
            raise ValueError("Kode promo tidak valid atau tidak ditemukan")

        if not voucher.is_active:
            raise ValueError("Kode promo sedang tidak aktif")

        return cls.calculate_discount(voucher, float(subtotal or 0.0))

    @classmethod
    def lock_and_apply_voucher(cls, code: str, subtotal: float) -> tuple[Voucher, dict]:
        """
        Atomic validation and usage increment with row-level lock (with_for_update).
        Prevents TOCTOU race conditions when concurrent requests claim the voucher.
        """
        if not code:
            raise ValueError("Kode voucher harus diisi")

        norm_code = code.strip().upper()
        voucher = db_session.query(Voucher).with_for_update().filter(Voucher.code == norm_code).first()

        if not voucher:
            raise ValueError("Kode promo tidak valid atau tidak ditemukan")

        if not voucher.is_active:
            raise ValueError("Kode promo sedang tidak aktif")

        result = cls.calculate_discount(voucher, float(subtotal or 0.0))
        voucher.used_count = (voucher.used_count or 0) + 1
        return voucher, result

    @classmethod
    def restore_voucher_usage(cls, code: str):
        """
        Restore voucher used_count when an order is cancelled or expired.
        """
        if not code:
            return
        norm_code = code.strip().upper()
        voucher = db_session.query(Voucher).with_for_update().filter(Voucher.code == norm_code).first()
        if voucher and voucher.used_count > 0:
            voucher.used_count -= 1

    @classmethod
    def list_all(cls):
        """
        List all vouchers ordered by created_at descending.
        """
        return db_session.query(Voucher).order_by(Voucher.created_at.desc()).all()

    @classmethod
    def list_public(cls):
        """
        List active vouchers meant for public display in customer app.
        Filters out expired, inactive, or exhausted vouchers, as well as hidden vouchers.
        """
        now = utc_now()
        vouchers = db_session.query(Voucher).filter(
            Voucher.is_active == True,
            Voucher.is_public == True
        ).order_by(Voucher.created_at.desc()).all()

        valid_vouchers = []
        for v in vouchers:
            # Check expiry
            if v.end_date:
                e_date = v.end_date
                now_cmp = now.replace(tzinfo=None) if hasattr(e_date, 'tzinfo') and e_date.tzinfo is None else now
                if now_cmp > e_date:
                    continue
            # Check start date
            if v.start_date:
                s_date = v.start_date
                now_cmp = now.replace(tzinfo=None) if hasattr(s_date, 'tzinfo') and s_date.tzinfo is None else now
                if now_cmp < s_date:
                    continue
            # Check usage limit
            if v.usage_limit is not None and v.used_count >= v.usage_limit:
                continue

            valid_vouchers.append(v)

        return valid_vouchers

    @classmethod
    def create_voucher(cls, data: dict) -> Voucher:
        """
        Admin method to create a new promotional voucher.
        """
        import re
        from datetime import datetime

        raw_code = (data.get('code') or '').strip().upper()
        if not raw_code:
            raise ValueError("Kode voucher wajib diisi")
        if not re.match(r'^[A-Z0-9_-]{3,50}$', raw_code):
            raise ValueError("Kode voucher harus 3-50 karakter alfanumerik (huruf besar, angka, strip, underscore)")

        # Check existing code
        existing = db_session.query(Voucher).filter(Voucher.code == raw_code).first()
        if existing:
            raise ValueError(f"Kode voucher '{raw_code}' sudah pernah dibuat")

        discount_type = data.get('discount_type', 'fixed')
        if discount_type not in ['fixed', 'percent']:
            raise ValueError("Tipe diskon harus 'fixed' (nominal) atau 'percent' (persentase)")

        try:
            discount_value = float(data.get('discount_value', 0))
            if discount_value <= 0:
                raise ValueError("Nilai diskon harus lebih besar dari 0")
            if discount_type == 'percent' and discount_value > 100:
                raise ValueError("Diskon persentase tidak boleh melebihi 100%")
        except (TypeError, ValueError) as e:
            if isinstance(e, ValueError) and str(e) in ["Nilai diskon harus lebih besar dari 0", "Diskon persentase tidak boleh melebihi 100%"]:
                raise
            raise ValueError("Nilai diskon tidak valid")

        try:
            min_spend = float(data.get('min_spend', 0.0) or 0.0)
            if min_spend < 0:
                raise ValueError("Minimal belanja tidak boleh bernilai negatif")
        except (TypeError, ValueError):
            raise ValueError("Minimal belanja tidak valid")

        max_discount = None
        if data.get('max_discount'):
            try:
                max_discount = float(data['max_discount'])
                if max_discount <= 0:
                    raise ValueError("Maksimal diskon harus lebih besar dari 0")
            except (TypeError, ValueError):
                raise ValueError("Maksimal diskon tidak valid")

        usage_limit = None
        if data.get('usage_limit'):
            try:
                usage_limit = int(data['usage_limit'])
                if usage_limit <= 0:
                    raise ValueError("Batas kuota pemakaian harus minimal 1")
            except (TypeError, ValueError):
                raise ValueError("Batas kuota pemakaian tidak valid")

        start_date = None
        if data.get('start_date'):
            try:
                start_date = datetime.fromisoformat(data['start_date'])
            except Exception:
                raise ValueError("Format tanggal mulai tidak valid")

        end_date = None
        if data.get('end_date'):
            try:
                end_date = datetime.fromisoformat(data['end_date'])
            except Exception:
                raise ValueError("Format tanggal berakhir tidak valid")

        if start_date and end_date and end_date < start_date:
            raise ValueError("Tanggal berakhir tidak boleh lebih awal dari tanggal mulai")

        is_active = bool(data.get('is_active', True))
        is_public = bool(data.get('is_public', True))

        voucher = Voucher(
            code=raw_code,
            discount_type=discount_type,
            discount_value=discount_value,
            min_spend=min_spend,
            max_discount=max_discount,
            usage_limit=usage_limit,
            start_date=start_date,
            end_date=end_date,
            is_active=is_active,
            is_public=is_public
        )
        try:
            db_session.add(voucher)
            db_session.commit()
            return voucher
        except Exception:
            db_session.rollback()
            raise

    @classmethod
    def toggle_active(cls, voucher_id: str) -> Voucher:
        """
        Toggle active/inactive status of a voucher.
        """
        voucher = db_session.query(Voucher).filter(Voucher.id == voucher_id).first()
        if not voucher:
            raise ValueError("Voucher tidak ditemukan")
        try:
            voucher.is_active = not voucher.is_active
            db_session.commit()
            return voucher
        except Exception:
            db_session.rollback()
            raise

    @classmethod
    def toggle_public(cls, voucher_id: str) -> Voucher:
        """
        Toggle public/hidden visibility status of a voucher.
        """
        voucher = db_session.query(Voucher).filter(Voucher.id == voucher_id).first()
        if not voucher:
            raise ValueError("Voucher tidak ditemukan")
        try:
            voucher.is_public = not voucher.is_public
            db_session.commit()
            return voucher
        except Exception:
            db_session.rollback()
            raise

    @classmethod
    def delete_voucher(cls, voucher_id: str) -> bool:
        """
        Delete a voucher.
        """
        voucher = db_session.query(Voucher).filter(Voucher.id == voucher_id).first()
        if not voucher:
            raise ValueError("Voucher tidak ditemukan")
        try:
            db_session.delete(voucher)
            db_session.commit()
            return True
        except Exception:
            db_session.rollback()
            raise

