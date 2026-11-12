# Dokumentasi Referensi Arsitektur Sistem Voucher / Kupon Promo

Dokumen ini disusun sebagai **panduan referensi teknis mandiri** agar Anda dapat mengadopsi atau mengimplementasikan sistem voucher/kupon ini ke dalam sistem internal pabrik Anda (`mdi-backend` / `SuperProduction`) dengan standar keamanan tinggi (pencegahan *race condition* dan *cyber attack*).

---

## 1. Skema Database (PostgreSQL & SQLAlchemy)

### A. DDL SQL (PostgreSQL murni)
```sql
CREATE TYPE voucher_discount_type AS ENUM ('fixed', 'percent');

CREATE TABLE vouchers (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    discount_type voucher_discount_type NOT NULL DEFAULT 'fixed',
    discount_value NUMERIC(12, 2) NOT NULL,
    min_spend NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    max_discount NUMERIC(12, 2) NULL,
    start_date TIMESTAMP WITHOUT TIME ZONE NULL,
    end_date TIMESTAMP WITHOUT TIME ZONE NULL,
    usage_limit INTEGER NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

CREATE INDEX idx_vouchers_code ON vouchers(code);
CREATE INDEX idx_vouchers_active_public ON vouchers(is_active, is_public);
```

### B. Model SQLAlchemy 2.0 (`models.py`)
```python
from sqlalchemy import Column, String, Numeric, Integer, Boolean, DateTime, Enum
from app.core.db import Base
from app.shared.utils import utc_now, generate_uuid

class Voucher(Base):
    __tablename__ = 'vouchers'
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(50), unique=True, nullable=False, index=True)
    discount_type = Column(Enum('fixed', 'percent', name='voucher_discount_type'), default='fixed', nullable=False)
    discount_value = Column(Numeric(12, 2), nullable=False)
    min_spend = Column(Numeric(12, 2), default=0.0, nullable=False)
    max_discount = Column(Numeric(12, 2), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    usage_limit = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_public = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
```

---

## 2. Business Logic & Proteksi Race Condition (`service.py`)

Kelemahan paling umum sistem voucher adalah **TOCTOU (Time-of-Check to Time-of-Use)**: ketika voucher hanya tersisa 1 kuota, 2 pengguna mengklik checkout bersamaan. Solusinya adalah **Row-Level Locking (`SELECT ... FOR UPDATE`)**.

```python
class VoucherService:
    @classmethod
    def calculate_discount(cls, voucher: Voucher, subtotal_float: float) -> dict:
        now = utc_now()

        # 1. Validasi Tanggal Mulai
        if voucher.start_date and now < voucher.start_date:
            raise ValueError("Kode promo belum dapat digunakan")

        # 2. Validasi Tanggal Kedaluwarsa
        if voucher.end_date and now > voucher.end_date:
            raise ValueError("Kode promo sudah kedaluwarsa")

        # 3. Validasi Batas Kuota Pemakaian
        if voucher.usage_limit is not None and voucher.used_count >= voucher.usage_limit:
            raise ValueError("Kuota pemakaian kode promo sudah habis")

        # 4. Validasi Minimal Belanja
        min_spend = float(voucher.min_spend or 0.0)
        if subtotal_float < min_spend:
            formatted_min = f"Rp{int(min_spend):,}".replace(',', '.')
            raise ValueError(f"Minimal belanja untuk promo ini adalah {formatted_min}")

        # 5. Perhitungan Diskon (Persen vs Nominal)
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
            'max_discount': float(voucher.max_discount) if voucher.max_discount is not None else None
        }

    @classmethod
    def lock_and_apply_voucher(cls, db_session, code: str, subtotal: float) -> tuple[Voucher, dict]:
        """
        Row-level lock atomik saat checkout. Mencegah eksploitasi kuota ganda.
        """
        norm_code = code.strip().upper()
        # Mengunci baris voucher sampai transaksi commit
        voucher = db_session.query(Voucher).with_for_update().filter(Voucher.code == norm_code).first()

        if not voucher or not voucher.is_active:
            raise ValueError("Kode promo tidak valid atau tidak aktif")

        discount_data = cls.calculate_discount(voucher, float(subtotal or 0.0))
        voucher.used_count += 1
        return voucher, discount_data

    @classmethod
    def restore_voucher_usage(cls, db_session, code: str):
        """
        Kompensasi: Mengembalikan kuota jika transaksi batal / kedaluwarsa.
        """
        if not code:
            return
        norm_code = code.strip().upper()
        voucher = db_session.query(Voucher).with_for_update().filter(Voucher.code == norm_code).first()
        if voucher and voucher.used_count > 0:
            voucher.used_count -= 1
```

---

## 3. Kontrak REST API

| Endpoint | Method | Hak Akses | Keterangan |
| :--- | :--- | :--- | :--- |
| `/api/vouchers/public` | `GET` | Publik (Buyer) | Menampilkan voucher yang aktif & `is_public=true` |
| `/api/vouchers/validate` | `POST` | Publik (Buyer) | Cek validitas kode promo & hitung diskon sebelum bayar |
| `/api/vouchers` | `GET` | Admin | List seluruh voucher termasuk private/nonaktif |
| `/api/vouchers` | `POST` | Admin | Buat voucher baru |
| `/api/vouchers/{id}` | `PUT` | Admin | Edit voucher / toggle status aktif |
| `/api/vouchers/{id}` | `DELETE` | Admin | Hapus voucher |

### Contoh Request Validasi Voucher (`POST /api/vouchers/validate`):
```json
{
  "code": "DIMSUM10",
  "subtotal": 50000
}
```

### Contoh Respons:
```json
{
  "success": true,
  "data": {
    "code": "DIMSUM10",
    "discount": 10000,
    "discount_type": "fixed",
    "discount_value": 10000.0,
    "min_spend": 20000.0,
    "max_discount": null
  }
}
```

---

## 4. Alur Integrasi Frontend (Checkout React)

1. **User Memasukkan Kode**: Komponen input kode voucher di [dimsum-frontend/src/pages/Checkout.jsx](file:///C:/Users/Zahid/Documents/Project/Dimsum-Client-2026-10-15/dimsum-client/dimsum-frontend/src/pages/Checkout.jsx).
2. **Kalkulasi Real-time**: Panggil `POST /api/vouchers/validate`. Jika valid, state `appliedVoucher` disimpan dan `subtotal` dikurangi nilai `discount`.
3. **Submit Order**: Saat buyer mengklik "Lanjut ke Pembayaran", kirim `voucher_code` bersama payload order.
4. **Proteksi Backend**: Backend tidak mempercayai nilai diskon dari frontend; backend menghitung ulang secara independen di server menggunakan `lock_and_apply_voucher()`.
