# PostgreSQL dan migrasi FastAPI

## Kondisi lokal

PostgreSQL 18.6 + psycopg 3.3.6, database development `dimsum_dev`, schema Alembic
revision `0002`. Backend FastAPI menggunakan Uvicorn; Flask tidak dipakai lagi.
Runtime/data ada di `~/.local/share/dimsum-postgresql`, di luar repository.
Server database hanya mendengarkan Unix socket privat pengguna OS.

```bash
source .venv/bin/activate
scripts/postgres-local.sh status
scripts/postgres-local.sh start  # setelah reboot, jika belum berjalan
alembic upgrade head
uvicorn run:app --host 127.0.0.1 --port 5000 --no-proxy-headers
# Hentikan DB hanya setelah aplikasi yang menggunakannya dihentikan:
scripts/postgres-local.sh stop
```

Script kontrol PostgreSQL memakai runtime user-local di mesin ini. Pada mesin lain,
install PostgreSQL, buat user/database dengan izin sesuai, lalu konfigurasi
`DATABASE_URL` PostgreSQL dalam `.env`. SQLite ditolak oleh runtime dan tes API.
`APP_ENV` menggantikan `FLASK_ENV`; `FLASK_APP` tidak dipakai lagi.

## Schema dan database existing

- `0001`: baseline schema bisnis, snapshot eksplisit `op.create_table`/constraint.
- `0002`: versi kredensial user, revocation JWT persisten, counter rate limit,
  dan penonaktifan akun demo internal yang masih memakai password bawaan.
- Startup hanya menghubungkan database dan memeriksa revision; tidak melakukan DDL/seeding.
- Database baru: `alembic upgrade head`.
- Database PostgreSQL lama dari aplikasi ini, belum memakai Alembic: backup terlebih
  dahulu, lalu `python -m scripts.adopt_postgres`. Script menolak perbedaan schema,
  melakukan stamp baseline yang sudah diverifikasi, dan upgrade dalam transaksi.

Database lokal telah diadopsi dan di-upgrade. Backup sebelumnya disimpan dengan
izin privat di `~/.local/share/dimsum-backups/before-fastapi-20261014.dump`.
Backup tersebut berhasil direstore ke database uji terpisah (4 produk terverifikasi),
lalu database uji dihapus. Ini pengujian backup data development, bukan data bisnis asli.

## Transfer SQLite lama

Sumber SQLite asli teman pengguna belum tersedia. Data lokal tetap seed development.

1. Hentikan penulisan ke sumber; buat backup SQLite yang konsisten dengan backup API/`.backup`.
2. Simpan sumber read-only. Cocokkan schema dengan baseline aplikasi; script menolak
   kolom/tabel bisnis berbeda. Kolom `auth_version` dan tabel keamanan baru boleh belum ada.
3. Siapkan database PostgreSQL tujuan kosong. Jangan seed sebelum transfer.
4. Jalankan:

```bash
DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/EMPTY_DATABASE' \
  python -m scripts.transfer_sqlite --source /absolute/path/backup.db
```

Alat transfer membuka sumber read-only, menjalankan Alembic pada target, mengisi tabel
sesuai urutan FK, mempertahankan ID/hash/token/nilai, lalu membandingkan seluruh isi
kolom sumber per tabel sebelum commit. Tabel session/rate-limit tidak ditransfer;
JWT lama tidak berlaku pada kontrak sesi baru. Target yang sudah berisi data bisnis ditolak.
Kesalahan constraint membatalkan seluruh transaksi termasuk schema yang baru dibuat;
perilaku ini diuji menggunakan foreign key invalid. Satu tabel dimuat ke memori untuk
verifikasi, sehingga data sangat besar membutuhkan strategi transfer terpisah.

Sumber yang masih memiliki akun internal aktif dengan password demo ditolak; reset
atau nonaktifkan akun tersebut pada salinan sumber dahulu. Setelah transfer, lakukan
rekonsiliasi stok/SKU/lot/order/payment sebelum membuka layanan. Simpan backup untuk rollback;
jangan menyalakan aplikasi lama dan baru sebagai dua penulis aktif.

## Tes dan operasi

```bash
TEST_DATABASE_URL="postgresql+psycopg:///dimsum_test?host=$HOME/.local/share/dimsum-postgresql/socket&port=55432" python -m pytest -q
```

Tes memakai schema unik pada PostgreSQL, menjalankan Alembic dan membersihkannya.
Termasuk uji checkout bersamaan, nomor batch unik, pickup sekali, serta rollback transfer.
Jangan menggunakan database produksi untuk pengujian.

Untuk produksi masih perlu akun DB least privilege, TLS untuk koneksi jaringan,
backup terjadwal/terenkripsi, monitoring, staging, dan prosedur cutover teruji pada data asli.
Implementasi SQLAlchemy masih sinkron pada worker thread FastAPI; AsyncSession belum dipindahkan.
