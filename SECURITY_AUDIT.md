# Pembaruan 15 Oktober 2026

Lihat [hasil pengujian keamanan lokal terbaru](SECURITY_TEST_REPORT.md).
220 tes backend dan 76 tes frontend lulus; temuan QR IDOR, token URL, tujuan
API eksternal, persistensi credential/PII, dan pertahanan Origin sudah ditangani.
Token kini berada dalam sessionStorage (tetap readable oleh same-origin JavaScript).
VPS dan data bisnis asli berada di luar scope aktif. Bagian berikut adalah catatan
historis 14 Oktober dan digantikan laporan terbaru bila statusnya berbeda.

---

# Audit dan remediasi keamanan — 14 Oktober 2026

## Hasil setelah remediasi

Backend telah dipindahkan ke FastAPI/Uvicorn + PostgreSQL. Flask dan extension-nya
sudah dihapus dari requirements serta virtual environment. Suite API menjalankan
Alembic pada schema PostgreSQL terisolasi; layanan eksternal dimock pada tes.

- **128 tes backend lulus**, termasuk 23 kasus audit/regresi keamanan, transfer
  data sintetis, rollback FK invalid, dan 3 skenario konkurensi. Ada 7 warning
  deprecation/legacy API; tidak ada kegagalan suite pada eksekusi terakhir.
- **50 tes frontend lulus**; build frontend berhasil.
- `npm audit`: **0 kerentanan yang diketahui** setelah memperbarui dependency transitif.
- `pip-audit -r requirements.txt`: **0 kerentanan yang diketahui** setelah memperbarui
  PyJWT ke 2.15.1 dan python-dotenv ke 1.2.4.
- Lint frontend **belum lulus: 304 error dan 19 warning**. Perubahan frontend pada
  sesi ini berupa lockfile dependency, bukan pembenahan seluruh source frontend.

Audit awal menghasilkan 9 kegagalan dari 19 pemeriksaan. Kesembilan kegagalan itu
sudah diperbaiki dan dites ulang. File audit kini bernama `tests/test_security_audit.py`
dan ikut discovery suite standar; tidak lagi terpisah/tersembunyi dari `pytest` default.

```bash
source .venv/bin/activate
export TEST_DATABASE_URL="postgresql+psycopg:///dimsum_test?host=$HOME/.local/share/dimsum-postgresql/socket&port=55432"
python -m pytest -q
python -m pytest tests/test_security_audit.py -q
python -m pytest tests/test_postgres_concurrency.py -q
```

## Status temuan awal

| ID | Temuan awal | Perbaikan dan bukti |
| --- | --- | --- |
| SEC-01 | Pesanan legacy tanpa token dapat dibaca anonim | Fallback allow dihapus; pesanan tanpa access token tetap membutuhkan pemilik terautentikasi atau peran internal. Tes anonim ditolak. |
| SEC-02 | JWT admin lama tetap berkuasa setelah role diturunkan | Verifier membaca user/role aktual dari DB setiap request. Perubahan role melalui service juga menaikkan auth_version; token lama tidak bisa refresh hak lama. Tes penurunan role menolak akses admin. |
| SEC-03 | Guest dapat diklaim lewat register tanpa verifikasi | Register menolak klaim akun guest existing. Tidak ada bypass OTP pura-pura; pemulihan guest perlu alur verifikasi identitas tersendiri. |
| SEC-04 | Logout hanya berlaku pada satu proses | Hash token dicatat di tabel revoked_tokens PostgreSQL dengan expiry; lookup dilakukan semua worker. Tes membuang session lokal dan memverifikasi token tetap ditolak melalui session DB baru. |
| SEC-05 | JSON array/identifier numerik menyebabkan 500 | Parsing JSON object, validasi Pydantic strict pada auth, batas panjang dan ukuran body. Kedua kasus kini 400; password oversize ditolak. |
| SEC-06 | Gambar palsu menyebabkan 500 | Decoder image errors menjadi 400, tidak disimpan. Banner dan produk memakai decoder/re-encoder WebP yang sama, batas 16 juta pixel dan body 5 MB, nama UUID tanpa path dari client. |
| SEC-07 | Client pembayaran tanpa timeout | Timeout 10 detik dipasang. HTTPS/host gateway dibatasi, transaction ID di-quote sebagai segmen path, redirect ditolak. Tes memverifikasi timeout dan destination. |
| SEC-08 | Webhook unsigned diterima di development | HMAC SHA-256 wajib di semua environment. Secret kosong/signature salah ditolak; fallback unsigned, bearer secret, dan API inquiry dihapus. Tes verifier development dan signature valid/invalid lulus. |

## Penguatan tambahan

- Startup tidak lagi membuat akun, mempromosikan role, mengubah schema, atau memakai
  password admin default. Alembic menonaktifkan akun demo internal existing yang masih
  menggunakan password bawaan, tanpa menghapus data. Provisioning/reset akun harus
  eksplisit melalui `python -m scripts.create_admin`; tidak ada password dalam argumen CLI.
- Runtime menolak database selain PostgreSQL dan membutuhkan SECRET_KEY minimal 32
  karakter; tidak ada secret fallback development di kode.
- JWT punya jti acak, exp/iat/sub wajib, auth_version, dan verifikasi akun aktif.
  Password change menaikkan versi sesi. Password disimpan sebagai salted bcrypt;
  hash dan auth_version tidak diserialisasi ke API pengguna.
- Checkout anonim memakai identitas guest terpisah dan tidak dapat mengganti nama/nomor
  atau mengaitkan order ke akun terdaftar hanya dengan mengetahui email/nomornya.
  Checkout terautentikasi menggunakan user dari bearer token yang sudah diverifikasi.
- Recipe/ingredient inventory memerlukan peran internal; permintaan anonim ditolak.
- CORS hanya memakai origin yang dikonfigurasi, tanpa fallback wildcard. Runtime lokal
  tidak mempercayai forwarded headers. Header no-store, nosniff, CSP/frame protections
  diterapkan; HSTS ditambahkan pada mode production (tetap membutuhkan TLS reverse proxy).
- Rate limit memakai counter PostgreSQL atomik bersama lintas worker, key berdasarkan
  IP/route template/time window. Tes login keenam ditolak 429. Bucket/token kedaluwarsa
  dibersihkan saat operasi terkait berjalan.
- Upload body dibatasi sebelum parsing multipart, field/file count dibatasi, image
  metadata tidak disalin ke hasil re-encode. SVG dan file HTML bernama JPG ditolak.
- Nomor batch memakai transaction advisory lock PostgreSQL. Row lock menjaga pickup
  dan webhook/cancel state; tes checkout bersamaan tidak oversell, batch mendapat nomor
  berbeda, serta pickup hanya bisa diselesaikan sekali.
- OpenWA requests memakai timeout dan tidak mengikuti redirect. Panggilan eksternal
  tidak dilakukan oleh audit lokal; destination konfigurasi tetap harus dijaga.

## Cakupan dan hal yang belum terbukti

| Kategori | Bukti lokal | Batas yang masih berlaku |
| --- | --- | --- |
| Encryption | Salted bcrypt, JWT signature, secret wajib, socket DB lokal privat | JWT bukan enkripsi. Enkripsi disk/backup/PII dan TLS produksi belum dipasang/diverifikasi. |
| XSS | Escaping payload order, SVG ditolak, gambar di-reencode, header proteksi | Belum pentest browser semua halaman. Token frontend masih di localStorage; XSS yang berhasil tetap berisiko mencurinya. |
| Form/input | JSON shape/tipe auth/checkout, panjang/nilai nonfinite, body/file limit, error 4xx | Belum fuzzing seluruh field seluruh endpoint; Pydantic body OpenAPI belum lengkap. |
| SQLi | Tes payload login/order ID dan ORM bound parameters | Bukan bukti matematis seluruh query aman; script administrasi tetap perlu akses terbatas. |
| Broken authentication | Role terbaru, token revoked persisten, guest claim ditolak, rate limit teruji | Workflow OTP/email verification/reset guest belum dibuat; Google OAuth belum E2E dengan kredensial asli. |
| CSRF | Mutasi admin memerlukan bearer header; form lintas origin tanpa bearer ditolak | Belum uji browser CSRF menyeluruh. Jika auth dipindah ke cookie kelak, perlu proteksi CSRF khusus. |
| Sensitive data exposure | IDOR legacy ditutup, password hash disembunyikan, inventory dibatasi, no-store | LocalStorage, query token guest yang sudah ada, retensi log, backup dan hosting perlu review produksi. |
| File upload | SVG/fake image/path traversal diuji, decode + WebP + batas pixel/body | Belum parser fuzzing atau uji deployment CDN/storage. |
| IDOR | Guest tanpa token dan customer lain ditolak; ownership berasal dari JWT | Matriks otorisasi seluruh resource pada sistem produksi gabungan belum diuji. |
| SSRF | Host HTTPS gateway tetap, path di-quote, redirect ditolak, timeout diuji | Belum audit DNS/egress firewall; gateway OpenWA memang dapat memakai alamat internal sesuai konfigurasi operator. |

Aplikasi belum dinyatakan siap produksi: sumber data asli belum dimigrasikan,
rekonsiliasi bisnis belum dilakukan, VPS/TLS belum disiapkan, integrasi pembayaran
nyata/Google/WhatsApp belum diuji, dan lint frontend masih gagal. Hasil audit dependency
berlaku untuk versi serta database advisory pada waktu pemeriksaan.
