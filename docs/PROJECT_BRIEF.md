# WarungWise — Project Brief

> **Tagline:** *Smarter Stock. Less Waste. Better Decisions.*  
> **Status:** Perencanaan — implementasi dan pengujian belum dimulai.

## 1. Ringkasan proyek

WarungWise adalah aplikasi web inventaris untuk warung dan toko kelontong kecil di Indonesia. Aplikasi dirancang untuk membantu pengguna mengelola produk, stok per batch, tanggal kedaluwarsa, penjualan, pergerakan stok, dan rekomendasi restock berbasis aturan yang dapat dijelaskan.

Versi awal berjalan secara lokal dan tidak memerlukan API eksternal berbayar, layanan AI berbayar, integrasi pembayaran, atau layanan cloud. Data sintetis dapat digunakan untuk demonstrasi, dengan label yang jelas bahwa data tersebut bukan bukti validasi bisnis nyata.

## 2. Masalah yang dituju

Pencatatan persediaan secara manual dapat membuat pemilik warung terlambat mengetahui stok yang hampir habis, kesulitan membedakan batch dengan tanggal kedaluwarsa berbeda, membeli barang terlalu banyak, dan tidak mempunyai ringkasan transaksi yang konsisten untuk membantu keputusan pembelian.

WarungWise akan menghubungkan catatan inventaris dan pergerakan stok dengan informasi yang mudah ditindaklanjuti. Aplikasi tidak menjanjikan pengurangan kerugian yang telah terbukti sebelum ada evaluasi lapangan.

## 3. Target pengguna dan konteks penggunaan

- Pemilik warung atau toko kelontong kecil.
- Pengelola yang mencatat barang masuk dan penjualan.
- Staf yang memeriksa batch, barang mendekati kedaluwarsa, serta barang rusak atau kedaluwarsa.

Asumsi versi pertama: satu warung, satu pengguna lokal, antarmuka berbahasa Indonesia, dan transaksi menggunakan Rupiah (IDR).

## 4. Sasaran produk

1. Menyediakan katalog produk yang dapat ditambah, dilihat, diedit, dicari, dan diarsipkan.
2. Mencatat penerimaan stok pada tingkat batch, termasuk tanggal penerimaan dan tanggal kedaluwarsa jika tersedia.
3. Menjaga agar transaksi dan perubahan stok konsisten, dapat ditelusuri, serta tidak menghasilkan stok negatif.
4. Memisahkan stok layak jual dari stok yang sudah kedaluwarsa atau perlu perhatian.
5. Menyediakan ringkasan penjualan dan rekomendasi restock yang menerangkan dasar perhitungannya.
6. Menghasilkan aplikasi lokal yang dapat dijalankan, diuji, dan dijelaskan oleh pengembangnya.

## 5. Ruang lingkup implementasi

### MVP — fondasi fungsional

MVP harus diselesaikan dan diuji sebelum fitur pelaporan lanjutan dikembangkan.

- CRUD produk, pencarian, validasi, dan pengarsipan tanpa menghilangkan riwayat transaksi.
- Penerimaan stok dan batch; setiap batch dapat memiliki tanggal kedaluwarsa berbeda.
- Pencatatan penjualan, penyesuaian stok, serta pembuangan barang rusak atau kedaluwarsa.
- Riwayat pergerakan stok yang dapat diaudit.
- Validasi stok layak jual dan pencegahan stok negatif.
- Tampilan dasar stok rendah serta status kedaluwarsa.

### Target fitur versi final

- Dashboard dari data database: produk aktif, stok rendah, batch mendekati kedaluwarsa, batch kedaluwarsa, dan ringkasan transaksi.
- Rekomendasi restock berbasis rata-rata penjualan harian, lead time, stok pengaman, dan stok layak jual.
- Laporan penjualan dan nilai barang yang tercatat rusak atau kedaluwarsa.
- Filter laporan dan ekspor CSV.
- Antarmuka responsif, aksesibilitas dasar, empty states, pesan sukses/error, dan konfirmasi tindakan penting.
- Pengujian otomatis untuk aturan bisnis utama serta dokumentasi menjalankan aplikasi.

### Di luar ruang lingkup versi pertama

Login dan role management, multi-cabang, sinkronisasi cloud, integrasi pemasok/marketplace/pembayaran, aplikasi mobile native, pemindaian barcode, serta prediksi machine learning. Fitur-fitur tersebut hanya akan dipertimbangkan jika alur inti telah stabil dan ada alasan yang jelas.

## 6. Teknologi

- Python untuk aturan bisnis dan backend.
- Flask untuk routing aplikasi web.
- SQLite untuk penyimpanan data lokal.
- HTML5, CSS3, Bootstrap, JavaScript, dan Jinja untuk antarmuka.
- Python standard library untuk ekspor CSV jika mencukupi.
- Dependensi tambahan hanya akan dipakai jika memiliki manfaat yang jelas dan dicantumkan secara akurat.

## 7. Aturan bisnis awal

1. **Stok per batch:** stok tersedia dihitung dari sisa tiap batch, bukan dari satu angka agregat yang tidak dapat ditelusuri.
2. **FEFO:** untuk barang yang memiliki tanggal kedaluwarsa, pengurangan stok diprioritaskan dari batch dengan tanggal kedaluwarsa paling awal yang masih valid (*First Expired, First Out*). Tanggal penerimaan menjadi pemecah seri.
3. **Batch kedaluwarsa:** batch yang sudah kedaluwarsa tidak boleh dipakai untuk memenuhi penjualan. Barang tersebut perlu dicatat sebagai penyesuaian/pembuangan yang dapat ditelusuri.
4. **Transaksi atomik:** pengurangan/penambahan stok dan penulisan riwayat harus berhasil bersama atau dibatalkan bersama jika operasi gagal.
5. **Pendapatan dan laba:** pendapatan tidak sama dengan laba. Estimasi laba kotor perlu memperhitungkan harga modal yang relevan. Nilai kerugian barang dibuang dihitung dari jumlah yang dicatat dibuang dan biaya modal yang berlaku, bukan dari peringatan kedaluwarsa saja.
6. **Rekomendasi transparan:** rekomendasi adalah estimasi, bukan prediksi pasti. Jika data penjualan tidak cukup, aplikasi harus menyatakan keterbatasan tersebut.

Rumus awal:

    target_stok = (rata_rata_penjualan_harian * lead_time_hari) + stok_pengaman
    saran_restock = max(0, target_stok - stok_layak_jual)

Stok layak jual mengecualikan batch yang kedaluwarsa atau tidak layak dijual. Versi pertama belum memperhitungkan pesanan pembelian yang belum diterima.

## 8. Kriteria keberhasilan yang dapat diuji

- Produk dapat dibuat, diedit, dicari, dan diarsipkan tanpa merusak riwayat.
- Penerimaan stok menambah batch dan mencatat pergerakan.
- Penjualan mengurangi stok dengan aturan FEFO dan penjualan melebihi stok layak jual ditolak.
- Operasi gagal tidak meninggalkan perubahan stok parsial.
- Peringatan kedaluwarsa mengikuti tanggal setiap batch.
- Barang rusak/kedaluwarsa yang dibuang dicatat dan perhitungan nilainya dapat ditelusuri.
- Rekomendasi restock cocok dengan rumus dan menangani produk tanpa data penjualan yang memadai.
- Laporan dan CSV cocok dengan data database serta filter yang dipilih.
- Input yang tidak valid ditangani dengan aman dan jelas.
- Aplikasi dapat diinisialisasi dan dijalankan lokal mengikuti dokumentasi, tanpa API berbayar.

Kriteria ini adalah target pengujian, **bukan klaim bahwa implementasi telah selesai atau tes telah lulus**.

## 9. Roadmap milestone

1. Project brief dan penetapan ruang lingkup.
2. Requirements, user flow, serta validasi tiap alur.
3. Desain skema database, relasi, constraints, dan transaksi.
4. Fondasi Flask, koneksi SQLite, konfigurasi, dan template dasar.
5. Manajemen produk dan validasi.
6. Penerimaan stok dan pelacakan batch.
7. Penjualan, FEFO, penyesuaian, dan pergerakan stok.
8. Dashboard serta peringatan kedaluwarsa.
9. Rekomendasi restock dan pengujian batas kasus.
10. Laporan, filter, dan ekspor CSV.
11. Penyempurnaan UI responsif dan aksesibilitas.
12. Pengujian otomatis/manual dan review keamanan.
13. README berdasarkan implementasi nyata dan video demo maksimal tiga menit.
14. Submission sesuai pedoman CS50x 2026 dan verifikasi Gradebook.

Setiap milestone mempunyai gerbang review: fitur harus dapat dijelaskan dan diuji sebelum tahap selanjutnya dimulai.

## 10. Risiko dan mitigasi

| Risiko | Mitigasi |
|---|---|
| Ruang lingkup melebar | Selesaikan MVP lebih dulu; tunda fitur noninti. |
| Stok tidak sinkron | Gunakan transaksi database dan satu aturan perhitungan stok per batch. |
| Rekomendasi menyesatkan | Jelaskan rumus, asumsi, dan keterbatasan data. |
| Kehilangan data | Dokumentasikan backup dan inisialisasi tanpa menghapus database yang sudah ada. |
| Klaim pengujian tidak akurat | Laporkan hasil aktual; jangan menyatakan tes lulus sebelum dijalankan. |
| Risiko rahasia masuk repository | Jangan commit token, password, database pengguna nyata, atau data sensitif. |

## 11. Kepatuhan dan transparansi

Pedoman resmi CS50x 2026 menjadi rujukan utama untuk persyaratan proyek dan submission: https://cs50.harvard.edu/x/project/.

Bantuan AI harus diungkapkan secara jujur sesuai bentuk bantuan yang benar-benar digunakan. Dokumen perencanaan ini disusun dengan bantuan ChatGPT berdasarkan spesifikasi proyek yang diberikan pemilik proyek. Pemilik proyek perlu meninjau, mengadaptasi, dan memahami keputusan desain sebelum implementasi. Komentar pada kode akan disesuaikan dengan bantuan AI yang benar-benar digunakan pada bagian tersebut.

Tidak ada klaim riset pengguna, validasi lapangan, hasil tes, atau hasil bisnis yang dinyatakan telah terjadi pada tahap perencanaan ini.
