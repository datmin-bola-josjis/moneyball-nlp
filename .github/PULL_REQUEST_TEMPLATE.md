## Apa yang berubah

<!-- Ringkas: apa dan mengapa. Bukan sekadar daftar file. -->

## Tahap pipeline

<!-- Centang yang relevan -->

- [ ] A — populasi dan sampel
- [ ] B — retrieval teks
- [ ] C — entity linking dan filter
- [ ] D — NLP
- [ ] E — skoring dan validasi
- [ ] F — output dan visualisasi
- [ ] Dokumen / config / tooling

## Checklist

- [ ] `make check` lolos (config valid + test hijau)
- [ ] Tidak ada join berdasarkan nama — memakai `player_id`
- [ ] Tidak ada market value dipakai untuk memfilter populasi
- [ ] Data mentah di `data/raw/` tidak ditimpa
- [ ] Tidak ada kredensial, `.env`, atau data mentah di diff ini
- [ ] Perubahan ambang dicatat di `docs/decisions.md`
- [ ] Nama kolom skema tidak berubah (kalau berubah: sudah disetujui tim)

## Bukti

<!-- Perintah yang dijalankan + hasilnya. Untuk pekerjaan data: jumlah baris,
     cakupan tanggal, dan contoh output. Angka harus bisa ditelusuri ke skrip. -->

```text
$ make check
...
```

## Catatan untuk reviewer

<!-- Bagian yang paling perlu diperiksa, atau hal yang masih menggunakan asumsi. -->
