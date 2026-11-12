# Panduan serah terima — 15 Oktober 2026

Paket source aplikasi lokal: FastAPI + Uvicorn + PostgreSQL dan React/Vite.
Flask sudah tidak digunakan. Baca SECURITY_TEST_REPORT.md untuk hasil audit terbaru
beserta batas verifikasinya. Dokumentasi lama dipertahankan sebagai riwayat.

## Isi dan kebutuhan

- Backend: app/, migrations/, scripts/, tests/, requirements.txt, alembic.ini.
- Frontend: dimsum-frontend/ termasuk source, asset, package-lock dan tes.
- Konfigurasi contoh: .env.example (backend dan frontend).
- Tidak berisi .env aktif, password admin, database/backup, virtualenv,
  node_modules, riwayat Git, atau file upload pengguna.
- Lingkungan yang dipakai saat pengujian: Python 3.14.4, PostgreSQL 18.6,
  Node.js 22.22.1. Dependency diinstal kembali pada mesin penerima.

## Setup pada mesin baru

1. Instal Python, PostgreSQL, dan Node.js. Buat role PostgreSQL lokal beserta
   database kosong dimsum_dev dengan role tersebut sebagai pemilik. Gunakan
   password yang dibuat sendiri; jangan memakai placeholder CHANGE_ME.
2. Ekstrak ZIP, buka terminal pada folder dimsum-client, lalu jalankan:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell, sebagai pengganti perintah aktivasi di atas:
# .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Salin .env.example menjadi .env. Isi DATABASE_URL sesuai role/password/port
   PostgreSQL lokal. URL-encode karakter khusus pada password dalam URL.
   Isi SECRET_KEY dengan nilai acak yang dibuat pada mesin penerima:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

4. Jalankan migrasi, isi katalog development bila diperlukan, dan buat admin:

```bash
python -m alembic upgrade head
python seed.py
python -m scripts.create_admin --email admin@example.com
python -m uvicorn run:app --host 127.0.0.1 --port 5000 --no-proxy-headers
```

Gunakan email admin sendiri; password diminta secara interaktif. Tidak ada
password admin bawaan. seed.py opsional dan hanya untuk development.
Script scripts/postgres-local.sh khusus instalasi komputer pengembang, bukan
installer PostgreSQL untuk client. Pada mesin client gunakan layanan PostgreSQL
setempat; port contoh .env.example adalah 5432.

5. Pada terminal kedua:

```bash
cd dimsum-frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Buka http://127.0.0.1:5173. Health API: http://127.0.0.1:5000/health.
Jika memakai Google login, isi dimsum-frontend/.env dari contoh yang tersedia.

## Pengujian dan integrasi

Buat database test terpisah dan set TEST_DATABASE_URL dengan role pemiliknya,
lalu jalankan python -m pytest -q dari root. Tes membuat dan membersihkan schema
acak. Di folder frontend jalankan npm test dan npm run build.

Hasil pengujian terakhir sebelum pengemasan: 220 tes backend, 76 tes frontend
lulus; build berhasil; audit dependency tidak menemukan kerentanan yang diketahui.
Ini hasil lingkungan pengembang, bukan hasil instalasi mesin client.

Pembayaran/Google/WhatsApp live memerlukan konfigurasi provider sendiri.
Tes provider menggunakan mock; checkout pembayaran nyata tidak akan berfungsi
hanya dengan placeholder .env.example. OpenWA default nonaktif.

## Batas yang perlu diketahui

- Browser interaktif tidak tersedia saat audit terakhir; pengujian UI keamanan
  menggunakan React DOM/happy-dom, bukan pentest browser seluruh halaman.
- Token/PII berada dalam sessionStorage, masih dapat dibaca JavaScript same-origin.
  Sesi lama di localStorage dibuang dan pengguna perlu login ulang.
- Lint frontend belum bersih; enkripsi disk/backup dan pemulihan guest terverifikasi
  belum dikonfigurasi. Rincian ada pada SECURITY_TEST_REPORT.md.
- VPS dan data bisnis asli tidak termasuk scope serah terima lokal ini.

PACKAGE_MANIFEST.sha256 mencantumkan SHA-256 setiap file paket kecuali manifest
itu sendiri. Gunakan checksum ZIP di luar arsip untuk memeriksa transfer file.
