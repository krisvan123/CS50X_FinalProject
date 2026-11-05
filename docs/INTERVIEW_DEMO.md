# WarungWise — Panduan Demo Interview (6 November 2026)

Panduan ini untuk menampilkan **data fiktif** dan menjelaskan aplikasi secara ringkas. Demo interaktif harus dilakukan dari laptop sendiri; deployment publik di Vercel bersifat **read-only** dan tidak menerima penyimpanan perubahan.

## Persiapan malam sebelumnya

1. Buka PowerShell di folder proyek yang berisi `app.py`, `run_demo.py`, dan `requirements.txt`. Jangan jalankan dari folder induknya.
2. Aktifkan virtual environment yang sudah terpasang (contoh perintah tepat ada di bawah).
3. Jika belum pernah memasang paket, jalankan `python -m pip install -r requirements.txt`.
4. Jalankan `python run_demo.py`. Skrip memakai `instance/warungwise-demo.db`, bukan database stok asli.
5. Kunjungi `http://127.0.0.1:5000` dan pastikan ada label **Local demo · sample data**.
6. Buka seluruh menu satu per satu dan pastikan tidak ada halaman error.
7. Siapkan backup internet/screen-sharing: saat aplikasi lokal ditampilkan, bagikan layar aplikasi browser.

### Perintah PowerShell yang disarankan

```powershell
cd "PATH_KE_FOLDER_REPO"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_demo.py
```

Jika `.venv` belum ada, buat sekali dengan `py -3.12 -m venv .venv`, lalu aktifkan dan instal paket. Jika PowerShell tidak mengizinkan aktivasi, jalankan `.\.venv\Scripts\python.exe run_demo.py` langsung.

Jangan menjalankan `init_db.py` untuk menghapus database yang sudah ada. `run_demo.py` tidak mereset perubahan pada database demo ketika dijalankan ulang.

## Alur live demo sekitar 4 menit

| Urutan | Halaman | Yang diperagakan | Poin penjelasan |
| --- | --- | --- | --- |
| 1 | Dashboard | Tunjukkan jumlah produk, stok rendah, dan batch mendekati kedaluwarsa | Angka diambil dari SQLite, bukan angka dekorasi |
| 2 | Products + Stock batches | Tunjukkan produk dengan dua batch dan tanggal kedaluwarsa berbeda | Expiry disimpan per *batch*, bukan hanya per produk |
| 3 | Settings | Ubah **Days before expiry** dari 30 ke 7, klik Save, kembali ke Dashboard | Pengaturan disimpan ke database dan memengaruhi peringatan |
| 4 | Sales → New sale | Catat penjualan kecil untuk produk yang memiliki dua batch layak jual | Sistem otomatis memprioritaskan batch yang lebih cepat kedaluwarsa (**FEFO**) |
| 5 | Movements | Cari riwayat pergerakan untuk penjualan tadi | Setiap perubahan stok memiliki catatan yang bisa diaudit |
| 6 | Reports | Lihat gross revenue, tren, dan ekspor CSV | Laporan berasal dari transaksi tersimpan; gross revenue bukan net profit |

Jika waktu sangat terbatas, tampilkan **Dashboard → Stock batches → Sale → Movements**. Jangan lakukan banyak transaksi uji coba di tengah interview. Pastikan produk yang akan dijual masih memiliki stok layak jual.

## Script singkat untuk menjelaskan teknologi

"WarungWise adalah aplikasi manajemen inventaris untuk warung. Saya menggunakan Python dan Flask untuk menangani request dan logika bisnis, Jinja untuk merender halaman HTML dari server, dan SQLite sebagai database lokal. Karena interface dirender langsung oleh Flask dengan Jinja, proyek ini belum membutuhkan REST API terpisah. Sistem memakai FEFO untuk membantu warung mengurangi risiko stok kedaluwarsa."

## Jawaban singkat pertanyaan potensial

**Kenapa tidak menggunakan React dan REST API?**  
Kebutuhan aplikasi ini masih satu operator dan berjalan lokal. Flask plus Jinja lebih sederhana untuk menghubungkan form, validasi, dan database tanpa menambah komunikasi API terpisah. Jika nanti dikembangkan ke aplikasi mobile atau banyak klien, REST API bisa menjadi pilihan.

**Kenapa SQLite?**  
Mudah dijalankan secara lokal, tidak memerlukan server database, dan cukup untuk prototipe satu warung. Untuk multi-user skala besar, perlu peninjauan database serta arsitektur concurrency.

**Apa bedanya FEFO dan FIFO?**  
FIFO memakai stok yang masuk lebih dulu. FEFO memprioritaskan stok yang tanggal kedaluwarsanya paling dekat, selama masih layak jual.

**Apakah rekomendasi restock menggunakan AI?**  
Belum. Rekomendasi dihitung dari aturan yang dapat dijelaskan: histori penjualan, lead time, safety stock, dan stok yang masih layak jual.

**Apakah aplikasi ini sudah production-ready?**  
Belum. Ini prototipe local-first yang sudah memiliki validasi dan pengujian otomatis; untuk dipakai publik dengan data asli masih diperlukan autentikasi, backup, pengujian keamanan, dan infrastruktur penyimpanan permanen.

## Cek terakhir

- [ ] Jalankan `python -m unittest discover -s tests -v` (atau cek GitHub Actions terbaru).
- [ ] Pastikan halaman Settings, Sales, Movements, dan Reports terbuka tanpa error.
- [ ] Lakukan satu penjualan percobaan dan pastikan jumlah stok berkurang dengan benar.
- [ ] Periksa menu pada resolusi layar presentasi dan tombol navigasi bisa diklik.
- [ ] Jangan membagikan data toko nyata: gunakan dataset demo fiktif.
- [ ] Jangan mengandalkan demo publik Vercel untuk penjualan atau mengubah Settings.
- [ ] Pastikan layar Teams atau share screen tidak menampilkan kredensial pribadi.

> Catatan: pengujian otomatis tidak menggantikan pengecekan manual browser di mesin presentasi.
