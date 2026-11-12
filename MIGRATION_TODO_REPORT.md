# Scope aktif dan pembaruan — 15 Oktober 2026

**Scope aktif hanya aplikasi lokal yang belum beroperasi.** VPS, data bisnis asli,
dan penggabungan repository produksi lain bukan pekerjaan wajib pada permintaan ini.
Checklist produksi historis di bawah tidak boleh dianggap sebagai blocker migrasi lokal.

- Migrasi lokal: FastAPI + PostgreSQL selesai dan aplikasi berjalan.
- Audit lanjutan: sudah dijalankan; **220 tes backend, 76 tes frontend lulus**, build berhasil.
- Temuan baru yang diperbaiki: QR IDOR, token query API, pengiriman bearer ke origin
  eksternal, persistensi token/PII, serta penolakan Origin asing untuk mutasi.
- Rincian bukti, perubahan perilaku dan batas audit: [SECURITY_TEST_REPORT.md](SECURITY_TEST_REPORT.md).
- Sisa batas lokal: sesi token masih readable oleh JavaScript, browser interaktif
  tidak tersedia untuk pentest nyata seluruh halaman, lint frontend belum dibenahi,
  dan enkripsi disk/backup lokal belum dikonfigurasi.

---

# To-do Report: Migrasi Project Dimsum ke Sistem Produksi

## Status terbaru — 14 Oktober 2026 (setelah port FastAPI dan remediasi)

**Backend lokal sudah FastAPI + Uvicorn + PostgreSQL. Flask tidak dipakai lagi.**
Pernyataan ini menggantikan status tahap sebelumnya yang masih mempertahankan Flask.
Migrasi data bisnis asli, penggabungan sistem produksi terpisah, dan deployment VPS
masih belum selesai. Tidak ada klaim bahwa seluruh target report awal sudah terpenuhi.

### Ringkasan hasil

| Bidang | Status sekarang | Bukti / batas |
| --- | --- | --- |
| Runtime backend | **Selesai lokal** | Seluruh router native FastAPI, Uvicorn aktif port 5000; Flask/extensions dihapus dari code imports, requirements dan virtualenv. |
| Database runtime | **Selesai lokal** | PostgreSQL saja; Config dan init_db menolak SQLite. SQLite hanya input alat transfer offline. |
| Migrasi schema | **Selesai untuk schema saat ini** | Alembic 0001/0002; startup tanpa DDL/seed; database lokal sudah diadopsi/di-upgrade. |
| SQLAlchemy async penuh | **Belum** | Service sinkron dijalankan endpoint FastAPI pada worker thread, session terisolasi per request. |
| Validasi | **Sebagian sesuai scope keamanan** | Pydantic strict auth/checkout dan validasi body umum; body schemas/OpenAPI seluruh endpoint belum lengkap. |
| Transfer data | **Alat teruji, data asli belum** | SQLite read-only → PostgreSQL kosong; perbandingan isi dan rollback kegagalan FK teruji. |
| Backup/restore lokal | **Selesai diuji** | Backup sebelum FastAPI direstore ke database terpisah; 4 produk terverifikasi. Ini data development. |
| Remediasi audit awal | **Selesai untuk temuan yang dibuktikan** | 9 kegagalan audit awal sudah diperbaiki; 23 kasus regresi keamanan kini masuk suite standar dan lulus. |
| Konkurensi | **3 skenario lulus** | Checkout tidak oversell, nomor batch unik, pickup tidak dapat diselesaikan dua kali. |
| Frontend lokal | **Berjalan, build/test lulus** | Proxy ke FastAPI HTTP 200; 50 tes frontend lulus, build berhasil. |
| Dependency audit | **Bersih pada audit terakhir** | npm audit dan pip-audit requirements: 0 kerentanan yang diketahui. |
| Lint frontend | **Belum lulus** | 304 error, 19 warning; tidak disembunyikan atau dinonaktifkan aturannya. |
| Payment/Google/WhatsApp nyata | **Belum E2E** | Tes memakai mock; perlu kredensial dan sandbox/provider. |
| Data bisnis asli | **Belum tersedia** | Belum transfer/reconcile data teman pengguna; lokal masih seed development. |
| Penggabungan sistem / VPS | **Belum** | Belum ERD terpadu, LotTracking/custody mapping, staging, TLS, monitoring atau cutover produksi. |

### Checklist pekerjaan selesai pada sesi ini

- [x] Ganti Flask/Blueprint/request globals/JSON response/decorators dengan native FastAPI routers, Request, Depends dan Starlette responses.
- [x] Ganti Flask-Bcrypt dengan bcrypt dan Flask-Limiter dengan counter atomik PostgreSQL.
- [x] Pindahkan entrypoint/Procfile ke Uvicorn dan hapus package Flask/extensions dari virtualenv.
- [x] Pertahankan kontrak URL `/api/...` yang digunakan React/Vite.
- [x] Terapkan request-scoped SQLAlchemy session yang terpisah pada request bersamaan.
- [x] Wajibkan PostgreSQL dan SECRET_KEY, hapus fallback SQLite/secret runtime.
- [x] Buat baseline Alembic dan migrasi keamanan; hentikan DDL dan seed akun saat startup.
- [x] Backup database development, validasi schema existing, jalankan adoption/upgrade Alembic, uji restore backup ke DB terpisah.
- [x] Hapus bootstrap admin default; nonaktifkan akun demo dengan password bawaan tanpa menghapus datanya; sediakan CLI provisioning/reset eksplisit.
- [x] Tutup IDOR pesanan legacy, role JWT stale, revocation memori, dan guest account takeover.
- [x] Lindungi identitas terdaftar dari perubahan melalui checkout anonim dan batasi akses recipe/inventory internal.
- [x] Wajibkan HMAC webhook di semua mode; hapus fallback unsigned/API inquiry; pasang timeout, host HTTPS gateway, path quoting dan penolakan redirect.
- [x] Validasi input auth/checkout, ukuran request, JSON nonfinite/nesting, serta image upload decode/re-encode/pixel limit.
- [x] Terapkan nomor batch dengan advisory lock dan row lock pada pickup/webhook/cancel; uji tiga kasus konkurensi.
- [x] Pertahankan transfer SQLite sebagai alat offline read-only; gunakan Alembic untuk target, uji preservasi data dan rollback FK invalid.
- [x] Masukkan security audit ke suite default; 128 tes backend lulus.
- [x] Perbarui dependency frontend serta PyJWT/python-dotenv; audit vulnerability dependency tidak menemukan temuan tersisa pada pemeriksaan ini.
- [x] Jalankan frontend build dan 50 tes frontend; catat kegagalan lint secara eksplisit.
- [x] Jalankan aplikasi lokal: frontend 5173, FastAPI 5000, health/OpenAPI/proxy produk HTTP 200; katalog 4 produk terverifikasi di browser.

### Perubahan yang perlu diketahui pengguna

1. Akun demo lama dengan password bawaan tidak dapat login lagi. Provisioning/reset harus eksplisit lewat
   `python -m scripts.create_admin --email admin@dimsum.id --reset-existing`; password diminta secara privat.
2. JWT lama sebelum migrasi tidak memenuhi kontrak sesi baru; pengguna harus login ulang.
3. Klaim akun guest via register kini ditolak; workflow verifikasi/pemulihan identitas perlu dibuat tersendiri.
4. Webhook pembayaran unsigned tidak lagi diterima meski development. Pembayaran nyata belum dikonfigurasi/diuji.
5. `APP_ENV` menggantikan `FLASK_ENV`; menjalankan aplikasi menggunakan Uvicorn, bukan Flask CLI.

### Pekerjaan berikutnya

- [ ] Dapatkan backup database asli, cocokkan schema dan volume, lakukan rehearsal transfer serta rekonsiliasi stok/SKU/lot/order/payment.
- [ ] Selesaikan lint frontend (304 error/19 warning) dan pengujian browser semua peran/scan/perangkat.
- [ ] Selesaikan body schemas Pydantic/OpenAPI seluruh endpoint dan AsyncSession jika target awal async penuh tetap diwajibkan.
- [ ] Uji integrasi sandbox Paywuz/Google/OpenWA dengan konfigurasi sebenarnya; jangan menganggap mock sebagai keberhasilan provider.
- [ ] Rancang pemulihan akun guest yang memverifikasi kepemilikan; tinjau token frontend localStorage/query token guest dan retensi log.
- [ ] Lanjutkan ERD/mapping sistem produksi gabungan bila repository target disediakan.
- [ ] Siapkan VPS/staging/TLS, akun DB least privilege, encrypted backup terjadwal, monitoring, dan cutover/rollback produksi.

### Artefak

- [Setup dan operasi FastAPI](README.md)
- [Migrasi PostgreSQL dan backup](POSTGRESQL.md)
- [Audit/remediasi dan batas verifikasi](SECURITY_AUDIT.md)
- [Alembic baseline](migrations/versions/0001_initial.py) dan [migrasi keamanan](migrations/versions/0002_security.py)
- [Adopsi PostgreSQL legacy](scripts/adopt_postgres.py), [transfer SQLite offline](scripts/transfer_sqlite.py), [provisioning admin](scripts/create_admin.py)
- [Tes migrasi](tests/test_migration.py), [tes keamanan](tests/test_security_audit.py), [tes konkurensi](tests/test_postgres_concurrency.py)

Hasil di atas berasal dari eksekusi 14 Oktober 2026. Tes backend masih menghasilkan
7 warning deprecation/legacy API. Tidak ada klaim bebas celah atau siap produksi.
Report disimpan di root repository, dengan salinan di Downloads. Jadikan versi root
sebagai sumber pembaruan berikutnya.

## Rencana akhir asli dan status parsial

Checklist berikut mempertahankan target awal FastAPI async + sistem produksi gabungan
+ VPS. `[x]` berarti item telah ditangani pada aplikasi yang tersedia; catatan setiap
bagian membatasi cakupannya. `[ ]` mencakup item yang baru selesai sebagian.

## Tujuan

Memigrasikan fitur website pada `C:\Users\Zahid\Documents\Project\dimsum` agar menjadi bagian dari sistem di repository ini, dengan **FastAPI + PostgreSQL + VPS Linux** sebagai platform akhir.

Sistem produksi yang sudah ada tetap menjadi dasar untuk proses produksi, pelacakan lot, perpindahan barang, dan POS. Fitur customer dan admin dari Project Dimsum ditambahkan tanpa membuat sumber data stok, akun, atau transaksi kedua.

## Target Stack dan Batasan

- Backend: Python + FastAPI, async, SQLAlchemy 2 async, Pydantic v2.
- Database: PostgreSQL pada VPS. SQLite hanya untuk kebutuhan development/test lokal bila sesuai.
- Frontend: React + Vite. Pertahankan Zustand yang sudah dipakai; gunakan TanStack Query untuk server state bila dipertahankan dari Project Dimsum.
- Deployment: VPS Linux, Nginx sebagai reverse proxy/static server, Uvicorn untuk FastAPI.
- Jangan membawa Flask, Flask-SQLAlchemy, Passenger/cPanel, atau MySQL/MariaDB sebagai runtime produksi final.
- Jangan menggandakan tabel atau proses yang sudah dimiliki sistem produksi sebelum pemetaan dan keputusan model datanya disetujui.

## To-do

### 1. Inventarisasi dan pemetaan fitur

**Status sekarang:** Sebagian: modul Flask di workspace telah dipindahkan. Matriks penggabungan dengan repository produksi/volume data asli belum tersedia.


- [ ] Daftar semua fitur Project Dimsum yang akan tetap dipakai: katalog/customer, akun, order, pembayaran, pickup, admin, inventory, batch produksi, chat, voucher, banner, dan integrasi lainnya.
- [ ] Tandai setiap fitur sebagai **migrasi**, **diganti oleh fitur di sistem ini**, atau **tidak masuk scope gabungan**.
- [ ] Petakan seluruh endpoint Flask, blueprint, model, job/background process, webhook, dan integrasi eksternal ke domain FastAPI yang sesuai.
- [ ] Petakan halaman dan alur frontend lama ke bagian aplikasi produksi: customer, admin, produksi, gudang, dan POS.
- [ ] Catat data yang perlu dipertahankan dari database Project Dimsum serta relasi dan volume datanya.
- [ ] Buat daftar kompatibilitas dan keputusan yang belum final sebelum mengubah kode atau skema database.

### 2. Tentukan model data terpadu

**Status sekarang:** Belum: schema bisnis yang ada dipertahankan. LotTracking/custody/ERD sistem produksi gabungan belum dipetakan atau disetujui.


- [ ] Tetapkan satu model `Product`/SKU untuk produk yang dijual dan hubungkan ke lot produk jadi yang dibuat oleh alur produksi.
- [ ] Tentukan apakah `production_batches` Project Dimsum akan dimigrasikan menjadi `LotTracking` atau direpresentasikan sebagai entitas terpisah yang memiliki relasi eksplisit ke `LotTracking`.
- [ ] Tambahkan relasi produk/SKU pada lot produk jadi bila dibutuhkan agar lot FG dapat dipilih untuk order, POS, dan fulfillment.
- [ ] Definisikan quantity hasil produksi, quantity tersedia, quantity tertahan/reserved, quantity terjual/terpenuhi, serta unit secara konsisten.
- [ ] Tetapkan **satu sumber kebenaran stok**. Perubahan stok produksi, penjualan POS, order, pickup, retur, dan adjustment harus mengubah sumber yang sama dan tercatat satu kali.
- [ ] Petakan `inventory_transactions` lama dan `custody_transfer_logs` yang ada: tentukan fungsi masing-masing dan cegah satu kejadian bisnis menghasilkan pengurangan stok ganda.
- [ ] Petakan produk, batch, transaksi inventory, order/order items, payment, user/customer/admin, voucher, dan data lain yang disepakati.
- [ ] Tetapkan aturan status order, payment, fulfillment, lot, dan stok serta transisi yang diizinkan.
- [ ] Tetapkan aturan hubungan QR order dengan QR lot/batch. QR order tidak boleh diterima sebagai kode lot, dan kode lot tidak boleh menggantikan token order.
- [ ] Buat ERD atau dokumentasi skema target dan minta persetujuan pemilik sistem sebelum migrasi data.

### 3. Satukan autentikasi dan otorisasi

**Status sekarang:** FastAPI dependencies, role DB aktual, revocation persisten, auth_version dan penutupan guest takeover sudah diterapkan. Akun demo dinonaktifkan. Penyatuan identitas dengan sistem produksi lain dan workflow OTP/reset guest belum dikerjakan.


- [x] Ganti autentikasi Flask dengan mekanisme autentikasi yang konsisten di FastAPI.
- [ ] Satukan identitas dan aturan akses untuk customer, admin, staff/kasir, operator produksi, inventory/checker, dan supervisor.
- [x] Pertahankan batas akses customer vs admin/operator; validasi otorisasi dilakukan di backend, bukan hanya dengan menyembunyikan halaman frontend.
- [x] Samakan format token, masa berlaku, refresh/logout, hashing password, dan sumber secret di environment.
- [x] Hapus akun/password demo dan secret fallback yang tertanam di kode dari jalur runtime produksi.
- [ ] Tentukan pemetaan akun Project Dimsum lama ke user target, termasuk penanganan email/username duplikat dan password/reset saat migrasi.
- [ ] Pastikan seluruh operasi audit lot dan transaksi mencatat identitas pengguna yang terautentikasi, bukan operator ID yang bebas dikirim client.

### 4. Migrasikan backend dari Flask ke FastAPI

**Status sekarang:** Router seluruh modul sudah native FastAPI; Flask telah dihapus. Prefix /api/... dipertahankan agar frontend kompatibel. SQLAlchemy masih sinkron di worker thread, bukan AsyncSession; schemas Pydantic auth/checkout dan validasi umum tersedia, belum seluruh body OpenAPI.


- [ ] Port modul Flask secara bertahap ke router FastAPI dengan prefix API yang konsisten, misalnya `/api/v1/auth`, `/api/v1/products`, `/api/v1/orders`, `/api/v1/payments`, `/api/v1/inventory`, dan `/api/v1/chat`.
- [ ] Reimplementasikan route, service, validation, error handling, CORS, upload, dan webhook menggunakan pola yang sudah dipakai backend FastAPI ini.
- [ ] Ganti Marshmallow schema dengan Pydantic v2 request/response schemas.
- [ ] Migrasikan operasi database sinkron ke SQLAlchemy async; hindari mencampur session sync Flask dan async session FastAPI pada request yang sama.
- [ ] Pindahkan business logic ke service/domain layer agar route order, POS, produksi, dan stok menggunakan operasi bisnis yang sama.
- [ ] Pastikan operasi gabungan seperti produksi lot, update stok, checkout, pickup scan, dan POS sale berjalan dalam transaksi database atomik.
- [ ] Terapkan locking/konkurensi database pada operasi stok dan fulfillment untuk mencegah oversell atau scan ganda.
- [ ] Buat endpoint idempotent atau mekanisme idempotency untuk webhook pembayaran dan permintaan scan/fulfillment yang dapat terkirim ulang.
- [x] Terapkan verifikasi signature webhook payment provider sebelum mengubah status payment/order.
- [ ] Pertahankan validasi dan rate limit pada endpoint sensitif seperti login, order verification, pickup scan, dan webhook sesuai pola FastAPI yang dipilih.
- [ ] Evaluasi fitur OpenWA/WhatsApp dan live chat lama; pindahkan hanya yang disepakati serta buat worker/service VPS terpisah bila membutuhkan proses polling/background.
- [x] Pastikan tidak ada route atau import runtime yang masih membutuhkan Flask setelah cutover.

### 5. Migrasikan database ke PostgreSQL

**Status sekarang:** Runtime dan tes API PostgreSQL saja; Alembic 0001/0002, adoption baseline tervalidasi, transfer SQLite read-only, rollback FK invalid, backup/restore development dan locking batch teruji. Transfer data bisnis asli serta rekonsiliasi belum bisa dilakukan tanpa sumber.


- [x] Jadikan konfigurasi PostgreSQL sebagai konfigurasi target VPS; SQLite tidak boleh menjadi fallback produksi yang tidak disengaja.
- [x] Buat Alembic migrations untuk skema target. Jangan mengandalkan `create_all()` atau migrasi `ALTER TABLE` ad hoc saat aplikasi startup di production.
- [ ] Tinjau seluruh tipe data dan constraint untuk PostgreSQL: primary key, foreign key, unique, index, numeric/quantity, timestamp/timezone, dan JSON bila diperlukan.
- [x] Pastikan urutan nomor lot/batch aman terhadap request bersamaan dan memiliki constraint database yang mencegah duplikasi.
- [ ] Buat script migrasi data dari SQLite/MySQL lama ke PostgreSQL, termasuk pemetaan ID dan relasi ke tabel target.
- [ ] Buat backup sumber data sebelum migrasi dan prosedur restore yang sudah diuji.
- [ ] Jalankan migrasi percobaan pada salinan data dan laporkan jumlah record sumber vs target, data yang dilewati, serta alasan setiap pengecualian.
- [ ] Validasi rekonsiliasi total stok per SKU, sisa per lot/batch, transaksi inventory, jumlah/status order, dan payment setelah migrasi.
- [ ] Simpan data lama sebagai arsip read-only sampai rekonsiliasi dan cutover dinyatakan berhasil.

### 6. Integrasikan frontend

**Status sekarang:** Frontend lama berjalan melalui proxy FastAPI, 50 tes dan build lulus. Dependency audit bersih setelah upgrade. Lint masih 304 error/19 warning. Integrasi dengan frontend sistem produksi lain dan uji perangkat scanner belum selesai.


- [ ] Tentukan struktur aplikasi akhir: satu SPA dengan route dan layout terpisah atau dua frontend terpisah di domain/subdomain yang sama; gunakan backend dan database yang sama.
- [ ] Jika disatukan menjadi satu SPA, integrasikan React Router hanya satu kali dan pindahkan navigasi produksi berbasis hash dengan hati-hati agar deep link yang ada tidak rusak.
- [ ] Pisahkan route/layout dan menu berdasarkan peran untuk customer, admin, produksi, gudang, dan POS.
- [ ] Pertahankan desain responsif dan workflow operator/scan yang ada; integrasi halaman customer/admin tidak boleh mengganggu layar shop-floor.
- [ ] Ganti URL endpoint Flask lama dengan base URL/API FastAPI yang terversi; jangan menaruh credential database, API secret, atau secret server di bundle frontend.
- [ ] Selaraskan skema request/response frontend dengan Pydantic API, termasuk format error, pagination, tanggal, dan status.
- [ ] Audit key `localStorage`/Zustand serta cache TanStack Query agar token atau data satu jenis pengguna tidak terbawa ke pengguna/peran lain pada perangkat bersama.
- [ ] Pastikan login/logout menghapus cache sensitif dan alur token kadaluarsa memberi pesan yang jelas.
- [ ] Verifikasi kamera/scanner, cetak QR/barcode, POS, navigasi kembali, dan deep link pada perangkat operator yang didukung.

### 7. Integrasikan alur bisnis utama

**Status sekarang:** Alur backend yang ada diuji, termasuk checkout bersamaan tanpa oversell dan pickup sekali. Belum penerimaan E2E sistem produksi gabungan atau payment provider nyata.


- [ ] Uji alur **produksi selesai → lot FG tercatat → stok siap jual bertambah** tanpa duplikasi update stok.
- [ ] Uji alur **order → payment terverifikasi → stok/reservasi → pickup scan → order selesai** dengan pencatatan transaksi dan audit yang konsisten.
- [ ] Uji alur **POS scan produk FG → quantity → stok freezer berkurang → transaksi tercatat**.
- [ ] Tetapkan apakah order online mereservasi stok saat order dibuat/dibayar atau hanya saat fulfillment, serta bagaimana pembatalan/refund mengembalikan stok.
- [ ] Pastikan scan lot hanya dapat memenuhi SKU dan kuantitas order yang sesuai, dan satu unit/batch tidak dapat dipenuhi melebihi remaining quantity.
- [ ] Pastikan transaksi order/POS tidak mengubah status custody lot dengan cara yang bertentangan dengan workflow produksi.
- [ ] Pastikan discrepancy produksi tetap dicatat dan tidak menghalangi POS/order kecuali aturan bisnis menyatakan sebaliknya.
- [ ] Pertahankan audit trail untuk perubahan status lot, perpindahan custody, transaksi stok, pembayaran, fulfillment, dan adjustment.

### 8. Pengujian dan kriteria penerimaan

**Status sekarang:** 128 tes backend lulus, termasuk 23 regresi keamanan, 3 konkurensi, dan 3 kasus transfer. 50 tes frontend/build lulus. Audit npm dan Python bersih pada eksekusi terakhir. Lint dan pengujian produksi/data asli masih belum selesai.


- [x] Tambahkan/port unit test untuk service, validasi, aturan status, kalkulasi stok, dan otorisasi.
- [x] Tambahkan integration test dengan PostgreSQL untuk constraint, transaksi rollback, locking, dan perilaku konkurensi stok.
- [ ] Tambahkan test end-to-end untuk login tiap peran, produksi, scan lot, order/payment, pickup, POS, dan logout.
- [ ] Uji webhook payment dengan signature valid, tidak valid, duplikat, dan urutan event yang berbeda.
- [ ] Uji error path: lot tidak dikenal, status lot salah, SKU tidak cocok, stok kurang, token order invalid, request scan ulang, dan database failure.
- [ ] Jalankan seluruh test dan build/lint frontend/backend yang relevan; catat hasil dan isu yang belum selesai.
- [ ] Kriteria lulus: tidak ada dua sumber stok aktif; jumlah stok dapat direkonsiliasi; order/POS/pickup tidak menyebabkan stok negatif atau pengurangan ganda; hak akses dan audit tercatat benar.

### 9. Deployment dan cutover VPS

**Status sekarang:** Belum deployment VPS. FastAPI/Uvicorn aktif lokal, PostgreSQL lokal dimigrasikan dengan backup. Dokumen operasi lokal tersedia; staging/TLS/monitoring/backup terjadwal/cutover produksi belum dibuat.


- [ ] Siapkan VPS Linux, PostgreSQL, Nginx, domain/TLS, firewall, dan akun service dengan least privilege.
- [ ] Jalankan FastAPI dengan Uvicorn melalui process manager yang sesuai (mis. systemd); Nginx meneruskan request API dan menyajikan frontend.
- [ ] Siapkan environment variables terpisah untuk dev/test/production; simpan secret di luar repository dan jangan masukkan ke frontend build.
- [ ] Konfigurasikan CORS hanya untuk domain frontend yang disetujui, trusted proxy, HTTPS, upload storage, dan batas ukuran request.
- [ ] Siapkan health check, structured logging, rotasi log, backup PostgreSQL terjadwal, monitoring disk/resource, dan prosedur restore.
- [ ] Buat staging VPS atau staging environment sebelum cutover production.
- [ ] Tetapkan freeze window, backup final, migrasi data final, smoke test, pemantauan, dan kriteria rollback sebelum perpindahan.
- [ ] Lakukan cutover hanya setelah rekonsiliasi data dan acceptance test disetujui; simpan aplikasi/database lama read-only untuk rollback sementara.
- [ ] Dokumentasikan cara deploy, menjalankan migration, restore backup, mengelola secret, dan rollback.

## Artefak yang harus diserahkan oleh pelaksana migrasi

**Status sekarang:** Artefak lokal tersedia: native FastAPI routers, Alembic, transfer script, tes, audit dan panduan. Paket integrasi produksi akhir, rekonsiliasi data asli, async penuh, serta deployment VPS belum lengkap.


- [ ] Matriks fitur: dipindah/diganti/tidak dipindah.
- [ ] ERD dan keputusan sumber kebenaran stok yang disetujui.
- [ ] FastAPI routers/services/schemas beserta test.
- [x] Alembic migrations dan script migrasi data ke PostgreSQL.
- [ ] Laporan rekonsiliasi data sebelum/sesudah migrasi.
- [ ] Frontend terintegrasi beserta hasil build/lint/test.
- [ ] Konfigurasi deployment VPS tanpa secret yang committed.
- [ ] Checklist cutover/rollback dan panduan operasional singkat.

## Referensi

- Sistem produksi dan API: `backend/app/main.py`, `backend/app/models.py`, `backend/app/routers/production1.py`, `backend/app/routers/production2.py`.
- Spesifikasi sistem produksi: `desain_system.md`.
- Project sumber migrasi: `C:\Users\Zahid\Documents\Project\dimsum\docs\02-tech-architecture-spec.md`, `back-end/app`, dan `front-end/src`.
