# Dimsum API — FastAPI + PostgreSQL

Backend sekarang memakai **FastAPI + Uvicorn**, PostgreSQL, SQLAlchemy 2, dan
migrasi Alembic. Flask beserta extension-nya sudah dihapus dari runtime dan
requirements. Prefix API `/api/...` dan envelope respons dipertahankan untuk React/Vite.

SQLAlchemy service tetap sinkron dan dijalankan oleh endpoint sinkron FastAPI pada
worker thread; database session dipisahkan per request melalui ContextVar. Ini
bukan implementasi AsyncSession. Port async penuh pada rencana awal masih terpisah.

- [Panduan setup mesin client](CLIENT_HANDOFF.md)
- [Status migrasi dan pekerjaan tersisa](MIGRATION_TODO_REPORT.md)
- [Setup PostgreSQL, migrasi, backup, restore](POSTGRESQL.md)
- [Perbaikan keamanan, hasil tes, dan batas verifikasi](SECURITY_TEST_REPORT.md)

## Menjalankan lokal

```bash
source .venv/bin/activate
pip install -r requirements.txt
scripts/postgres-local.sh start  # hanya jika PostgreSQL belum berjalan
alembic upgrade head
uvicorn run:app --host 127.0.0.1 --port 5000 --no-proxy-headers
```

Pada terminal frontend:

```bash
cd dimsum-frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Frontend: `http://127.0.0.1:5173`; API: `http://127.0.0.1:5000`;
daftar endpoint OpenAPI: `/docs` dan `/openapi.json`. Validasi request custom tetap
berada pada Pydantic/route/service; dokumentasi body OpenAPI belum lengkap untuk semua endpoint.

`.env` lokal sudah dikonfigurasi. Untuk mesin baru, salin `.env.example`, isi
`DATABASE_URL`, `APP_ENV`, `ALLOWED_ORIGINS`, dan buat `SECRET_KEY` acak:

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

Startup memerlukan PostgreSQL dengan Alembic revision `0002` dan secret minimal
32 karakter. Startup **tidak** membuat tabel, menjalankan ALTER, atau membuat akun.
SQLite hanya didukung sebagai sumber alat transfer, bukan runtime atau backend tes API.

## Akun dan seed

Akun demo lama dengan password bawaan dinonaktifkan oleh migrasi keamanan, tanpa
menghapus pesanan atau akun. Tidak ada akun/password admin default yang dibuat otomatis.
Untuk menyediakan admin secara eksplisit, password diminta secara privat:

```bash
python -m scripts.create_admin --email admin@example.com
# Jika memang ingin memulihkan/mengganti kredensial akun lama:
python -m scripts.create_admin --email admin@dimsum.id --reset-existing
```

`python seed.py` hanya mengisi katalog/voucher development, tanpa akun, dan ditolak
pada production. `wipe_stock.py` hanya untuk database development disposable,
memerlukan `--confirm-reset`; jangan jalankan pada data yang perlu dipertahankan.

## Tes

```bash
export TEST_DATABASE_URL="postgresql+psycopg:///dimsum_test?host=$HOME/.local/share/dimsum-postgresql/socket&port=55432"
python -m pytest -q
cd dimsum-frontend
npm test
npm run build
npm run lint
npm audit
```

Pengujian API menggunakan schema PostgreSQL acak dan Alembic, lalu menghapus schema
tersebut. `tests/test_security_audit.py` kini termasuk suite standar. Rate limit
produksi memakai counter atomik PostgreSQL bersama lintas worker; tes khusus
mengaktifkannya untuk membuktikan pembatasan login.

Hasil terakhir: 220 tes backend lulus; 76 tes frontend lulus; build frontend lulus.
`npm audit` dan `pip-audit -r requirements.txt` tidak menemukan kerentanan yang diketahui
pada audit terakhir. Lint frontend masih gagal (304 error, 19 warning); detail dan
batas pengujian ada di report. Jangan mengartikan hasil ini sebagai jaminan bebas celah.

## Integrasi

Webhook Paywuz wajib HMAC SHA-256 dari raw body dengan `PAYWUZ_WEBHOOK_SECRET` di semua
mode; fallback unsigned/API inquiry tidak diterima. Client pembayaran memakai HTTPS,
host `api.paywuz.id`, timeout, serta menolak redirect. Jika provider memakai kontrak
lain, integrasikan dan uji sandbox secara eksplisit sebelum produksi.

WhatsApp/OpenWA dinonaktifkan pada konfigurasi lokal. Payment provider, Google OAuth,
dan WhatsApp belum diuji end-to-end menggunakan kredensial asli. Jangan mengharapkan
checkout pembayaran nyata berjalan sebelum integrasi tersebut dikonfigurasi.
