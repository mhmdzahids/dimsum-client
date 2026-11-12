# Audit keamanan lokal — 15 Oktober 2026

Scope: aplikasi lokal FastAPI + PostgreSQL + React. VPS, data bisnis asli, dan
penggabungan sistem lain bukan kriteria penyelesaian audit ini. Database pengujian
menggunakan schema PostgreSQL terisolasi; pembayaran/WhatsApp tidak dikirim ke provider.

## Hasil eksekusi

- Backend: **220 passed**, 7 warning deprecation/legacy API.
- Frontend: **76 passed**, 12 file; build berhasil.
- Dependency: pip-audit requirements dan npm audit **0 known vulnerabilities** pada pemeriksaan ini.
- HTTP lokal: frontend 5173 HTTP 200, backend 5000 /health ok.
- Browser interaktif tidak tersedia (daftar browser kosong). Tes XSS UI memakai
  React DOM/happy-dom, bukan bukti pengujian Chromium/Firefox seluruh halaman.
- Sebelum perbaikan: suite tambahan 4 gagal/57 lulus; tiga kegagalan akses QR dan
  satu penerimaan token query. Setelah perbaikan dan perluasan: 77 kasus suite tambahan lulus.

## Temuan dan perbaikan

| Temuan | Perbaikan | Verifikasi |
| --- | --- | --- |
| IDOR QR pickup: mengetahui UUID order cukup untuk mengambil PNG QR | Endpoint QR sekarang memerlukan token header, pemilik, atau peran internal seperti detail order | Anonim/customer lain/token salah ditolak; token valid menghasilkan PNG |
| API menerima credential order melalui query URL | API hanya menerima X-Order-Token; link baru WhatsApp memakai fragment #token; frontend membersihkan token dari URL setelah menyimpannya | Query token ditolak; header token diterima |
| API client otomatis melampirkan bearer ke URL absolut eksternal | Kedua API client membatasi origin ke API terkonfigurasi dan menolak redirect | fetch tidak dipanggil untuk origin penyerang; redirect:error diuji |
| Token, duplikasi Zustand, PII, dan riwayat order tersimpan permanen | browserStorage memisahkan data privat ke sessionStorage; salinan localStorage lama dibuang; logout customer membersihkan PII/riwayat/store | Tes penyimpanan, migrasi salinan lama, logout; tes auth/guards tetap lulus |
| Pertahanan CSRF bergantung pada bearer saja | Mutasi dengan Origin di luar allowlist ditolak sebelum handler | Cookie-only, form lintas origin, dan origin asing dengan bearer valid ditolak |
| Referer frontend dan allowlist tunnel terlalu luas untuk scope lokal | Header no-referrer/nosniff/DENY pada Vite; hapus allowlist ngrok | HTTP lokal berjalan, build lulus |

## Matriks pengujian

| Kategori | Pengujian yang dijalankan | Hasil dan batas |
| --- | --- | --- |
| XSS | Payload img/onerror, svg/onload, script pada nama produk admin dan error API; review source raw HTML sinks | Payload menjadi teks, tidak terbentuk elemen executable. Tidak ditemukan dangerouslySetInnerHTML/document.write pada source aplikasi. Bukan pentest browser semua halaman. |
| CSRF | Form urlencoded, text/plain, JSON, cookie token, Origin asing dan preflight | Ditolak. Auth tetap bearer eksplisit, tidak bergantung cookie otomatis. |
| IDOR/otorisasi | Detail, QR, sync-payment, resend receipt dengan anonim/customer lain/token salah; 16 endpoint internal untuk anonim/customer; tes roles existing | Semua kasus lulus. QR valid tetap dapat diakses dengan header token. |
| Penyimpanan token | Salinan auth utama/Zustand, riwayat, PII, legacy storage, logout, tujuan request eksternal | Data privat tidak lagi disimpan permanen. sessionStorage masih dapat dibaca script same-origin; bukan proteksi penuh terhadap XSS. |
| Paparan data | Password hash/secret/traceback dalam respons, akses .env, cache header, QR privat, file permission | Kasus teruji lulus. .env dan backup lokal mode 600. |
| Broken authentication | JWT expired/forged/alg none/missing jti, akun nonaktif, auth_version, role demotion, revoke/logout, rate limit, guest takeover | Lulus. Google provider memakai mock; tidak mengklaim OAuth live teruji. |
| SQLi | Payload OR/UNION/DROP pada login dan order ID; review raw SQL app | Tidak bypass login/otorisasi. Raw SQL bisnis yang ditemukan menggunakan bound parameter untuk advisory lock. |
| Input/form | JSON array/null/object/bool pada email, extra field auth, panjang, email, nonfinite, batas request | Kasus teruji ditolak 4xx; bukan fuzzing seluruh kombinasi field. |
| Upload | SVG, HTML disguised JPG, nama traversal, decode/re-encode WebP, batas byte/pixel | Suite regresi lulus; parser fuzzing skala besar tidak dilakukan. |
| SSRF | Gateway localhost/metadata host/userinfo/host suffix/file scheme/port asing, transaction path, redirect, timeout | Ditolak/terkunci ke host gateway. OpenWA berasal konfigurasi server, bukan URL user; request memakai timeout dan tidak mengikuti redirect. |
| Webhook/transaksi | Signature palsu/valid, locking checkout/batch/pickup, rollback database | Suite regresi dan konkurensi lulus. Tidak memanggil provider eksternal. |
| Encryption | Salted bcrypt, verifikasi JWT/signature, secret wajib, file permission | Password di-hash; JWT ditandatangani, bukan dienkripsi. Disk/backup lokal belum dienkripsi oleh aplikasi. |

## Perubahan perilaku

- Sesi lama pada localStorage dibuang; pengguna perlu login ulang.
- Token dan riwayat privat mengikuti sesi tab. Menutup tab dapat mengakhiri akses
  lokal tersimpan; ini bukan lagi riwayat permanen antar-sesi browser.
- Link WhatsApp baru memakai fragment. Link query lama masih dibaca frontend dan
  dibersihkan, tetapi API langsung dengan ?token= tidak lagi didukung.
- Token URL yang sudah pernah masuk log/history sebelum perubahan tidak dapat
  dibersihkan secara retroaktif oleh perubahan kode ini.

## Batas yang tetap dicatat

Pengujian lokal di atas sudah dilaksanakan dan temuan yang diperbaiki sudah dites ulang.
Ini bukan klaim seluruh aplikasi bebas kerentanan. sessionStorage masih terpapar jika
XSS same-origin berhasil; pemindahan ke cookie HttpOnly membutuhkan rancangan sesi dan
CSRF tersendiri. Pemulihan akun guest terverifikasi belum dibuat. Lint frontend masih
memiliki temuan lama (audit ini menjalankan test/build, tidak menyelesaikan lint).
Browser interaktif tidak tersedia, sehingga pentest browser nyata seluruh alur belum
terverifikasi. Enkripsi disk/backup lokal tidak dikonfigurasi dalam pekerjaan ini.

## Reproduksi

```bash
TEST_DATABASE_URL='postgresql+psycopg:///dimsum_test?host=/home/bryan/.local/share/dimsum-postgresql/socket&port=55432' .venv/bin/python -m pytest -q
cd dimsum-frontend
npm test
npm run build
npm audit
```

Tes baru: `tests/test_security_extended.py`,
`dimsum-frontend/src/utils/__tests__/security.test.jsx`, dan kasus XSS tambahan pada
`dimsum-frontend/src/pages/__tests__/AdminProducts.test.jsx`.
