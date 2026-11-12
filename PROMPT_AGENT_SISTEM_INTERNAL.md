# PROMPT TUGAS UNTUK AGENT AI (SISTEM INTERNAL PABRIK)

> **Petunjuk Penggunaan:**  
> Salin (*copy*) seluruh teks prompt di bawah ini, lalu tempel (*paste*) ke Agent AI (Cursor, Windsurf, Claude, Devin, ChatGPT, dll.) yang sedang mengerjakan repositori sistem internal pabrik Anda (`mdi-backend` / `mdi-frontend`).

---

```text
Halo Agent! Tolong tambahkan modul Diskon Produk, modul Voucher/Kupon Promo, modul Banner Promosi, dan sistem Autentikasi API Key ke dalam sistem backend & frontend internal pabrik ini.

### 📌 KONTEKS & TUJUAN
Sistem internal pabrik ini sudah memiliki manajemen produk dasar dan stok fisik. Namun, belum ada sistem diskon produk, sistem voucher/kupon promo, dan banner promosi.
Website toko buyer (e-commerce eksternal untuk pelanggan) akan diposisikan sebagai "read-only / checkout client" yang hanya mengonsumsi data katalog produk, diskon aktif, voucher yang tersedia, dan banner promosi dari sistem internal ini melalui REST API yang diamankan menggunakan API Key (`X-API-Key`).

Tugasmu adalah membangun backend dan frontend admin di sistem internal ini dengan spesifikasi berikut:

---

### TUGAS 1: Menambahkan Fitur Diskon pada Modul Produk

1. **Modifikasi Tabel/Model `products`**:
   Tambahkan kolom-kolom berikut pada model produk yang sudah ada:
   - `original_price` (Decimal/Numeric 12,2 - Nullable): Menyimpan harga normal (harga coret).
   - `is_discount` (Boolean - Default: False): Menandakan apakah produk sedang promo/diskon.
   - `discount_percent` (Integer - Default: 0): Nilai persentase diskon (1-100%).
   - `stock_online` (Integer - Default: 0): Alokasi stok khusus yang boleh dibeli oleh customer website.

2. **Logika Bisnis Perhitungan Harga**:
   - Jika `is_discount = True` dan `discount_percent > 0`:
     `price = round(original_price * (1 - (discount_percent / 100)))`
   - Jika `is_discount = False`:
     `price = original_price` dan `discount_percent = 0`.
   - Nominal hemat yang didapat customer: `original_price - price`.

3. **Frontend Admin Produk**:
   - Di tabel/kartu produk, tambahkan tombol "Pasang Diskon" / "Edit Diskon".
   - Sediakan modal dengan input:
     - Toggle Aktifkan Diskon (`is_discount`).
     - Input `original_price` (Harga Normal).
     - Input `discount_percent` (Persen Diskon, misal 20%).
     - Tampilan kalkulasi instan: "Harga setelah diskon: RpXX.XXX (Hemat RpXX.XXX)".

---

### TUGAS 2: Membangun Modul Voucher & Kupon Promo

1. **Tabel/Model Database `vouchers`**:
   Buat tabel dengan skema berikut:
   - `id`: UUID / String(36), Primary Key
   - `code`: String(50), Unique, Not Null, Index (otomatis uppercase, misal: 'DIMSUM10', 'DISKON20')
   - `discount_type`: Enum('fixed', 'percent'), Default 'fixed'
   - `discount_value`: Decimal(12,2), Not Null (nominal Rp jika fixed, persentase jika percent)
   - `min_spend`: Decimal(12,2), Default 0.00 (syarat minimal subtotal belanja)
   - `max_discount`: Decimal(12,2), Nullable (plafon potongan maksimal untuk tipe percent)
   - `start_date`: DateTime, Nullable (waktu mulai berlaku)
   - `end_date`: DateTime, Nullable (waktu kedaluwarsa)
   - `usage_limit`: Integer, Nullable (kuota maksimal pemakaian kupon)
   - `used_count`: Integer, Default 0 (jumlah yang sudah terpakai)
   - `is_active`: Boolean, Default True (toggle aktif/nonaktif)
   - `is_public`: Boolean, Default True (True = tampil di daftar promo publik; False = kode rahasia)
   - `created_at` & `updated_at`: DateTime

2. **Service Layer & Proteksi Race Condition (Wajib Aman)**:
   - **Validasi Kupon**:
     1. Periksa `is_active == True`.
     2. Periksa apakah waktu saat ini berada di antara `start_date` dan `end_date`.
     3. Periksa kuota: jika `usage_limit` tidak null, pastikan `used_count < usage_limit`.
     4. Periksa minimal belanja: pastikan `subtotal >= min_spend`.
   - **Rumus Potongan**:
     - Jika `discount_type == 'percent'`:
       `potongan = min((discount_value / 100) * subtotal, max_discount atau subtotal)`
     - Jika `discount_type == 'fixed'`:
       `potongan = min(discount_value, subtotal)`
   - **Row-Level Locking (Pencegahan Eksploitasi Kuota Ganda)**:
     Saat kupon diaplikasikan ke pesanan, kunci baris voucher di database menggunakan `SELECT ... FOR UPDATE` (atau row lock setara di ORM) sebelum menambahkan `used_count += 1`.
   - **Fungsi Rollback**:
     Sediakan fungsi untuk mengembalikan kuota (`used_count -= 1`) jika transaksi checkout batal atau kedaluwarsa.

3. **Frontend Admin Voucher**:
   - Halaman daftar voucher dengan filter (Aktif, Nonaktif, Publik, Privat).
   - Modal Tambah/Edit Voucher dengan form lengkap (Kode, Tipe Diskon, Nilai, Minimal Belanja, Maksimal Potongan, Kuota, Rentang Tanggal, Switch Publik/Privat).
   - Tombol copy kode voucher dan tombol toggle on/off status aktif.

---

### TUGAS 3: Membangun Modul Banner Promosi

1. **Tabel/Model Database `banners`**:
   - `id`: UUID / String(36), Primary Key
   - `title`: String(100), Nullable
   - `image_url`: String(255), Not Null (URL publik file banner)
   - `is_active`: Boolean, Default True
   - `created_at`: DateTime

2. **Upload & Storage**:
   - Endpoint upload banner menerima file gambar (JPG, PNG, WEBP, maks 5MB).
   - Simpan file ke direktori static/storage publik dan simpan URL-nya di database.

3. **Frontend Admin Banner**:
   - Tampilan preview banner yang sedang tayang.
   - Form upload file banner baru dengan preview sebelum upload.
   - Tombol hapus dan toggle aktif/nonaktif banner.

---

### TUGAS 4: Middleware Autentikasi API Key & Endpoint Khusus Buyer

Buat sistem proteksi API Key untuk mengamankan data yang akan dikonsumsi oleh website buyer.

1. **Mekanisme API Key**:
   - Simpan secret API Key di file environment `.env`, misalnya:
     `BUYER_CLIENT_API_KEY=mdi_live_9f8e7d6c5b4a321e0f`
   - Buat middleware/guard yang memverifikasi header HTTP:
     `X-API-Key: mdi_live_9f8e7d6c5b4a321e0f`
   - Jika header tidak ada atau nilainya tidak cocok, kembalikan response `401 Unauthorized`.

2. **Daftar Endpoint Khusus Buyer (Wajib Header `X-API-Key`)**:

   - **`GET /api/v1/public/products`**
     Mengembalikan seluruh produk aktif untuk katalog buyer.
     Format respons:
     ```json
     {
       "success": true,
       "data": [
         {
           "id": "uuid-produk",
           "name": "Dimsum Mini (1 Pax Isi 25 Pcs)",
           "sku": "DIMSUM-MINI-PAX-25",
           "price": 20000.0,
           "original_price": 25000.0,
           "is_discount": true,
           "discount_percent": 20,
           "stock_online": 40,
           "unit": "pack",
           "pack_size": 25,
           "image_url": "https://.../gambar.webp"
         }
       ]
     }
     ```

   - **`GET /api/v1/public/vouchers`**
     Mengembalikan daftar voucher yang `is_active = True` dan `is_public = True` untuk halaman promo buyer.
     Format respons:
     ```json
     {
       "success": true,
       "data": [
         {
           "code": "DIMSUM10",
           "discount_type": "fixed",
           "discount_value": 10000.0,
           "min_spend": 20000.0,
           "max_discount": null,
           "end_date": "2026-12-31T23:59:59Z"
         }
       ]
     }
     ```

   - **`POST /api/v1/public/vouchers/validate`**
     Endpoint validasi saat buyer checkout di keranjang.
     Request body:
     ```json
     {
       "code": "DIMSUM10",
       "subtotal": 50000.0
     }
     ```
     Response (jika valid):
     ```json
     {
       "success": true,
       "data": {
         "code": "DIMSUM10",
         "discount": 10000.0,
         "discount_type": "fixed",
         "discount_value": 10000.0,
         "min_spend": 20000.0,
         "max_discount": null
       }
     }
     ```
     Response (jika tidak valid / kedaluwarsa):
     ```json
     {
       "success": false,
       "error": "Minimal belanja untuk promo ini adalah Rp20.000"
     }
     ```

   - **`GET /api/v1/public/banners`**
     Mengembalikan daftar banner aktif untuk carousel beranda website buyer.
     Format respons:
     ```json
     {
       "success": true,
       "data": [
         {
           "id": "uuid-banner",
           "image_url": "https://.../banner1.webp"
         }
       ]
     }
     ```

Pastikan semua migrasi database (Alembic/Prisma/TypeORM/migration script) dibuat dan dijalankan dengan aman tanpa mengganggu tabel yang sudah ada. Terima kasih!
```
