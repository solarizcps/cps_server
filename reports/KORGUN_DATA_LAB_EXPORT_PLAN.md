# KORGUN DATA LAB - EXPORT PLAN

**Tarih:** 2026-05-16T16:58:17.011094

## ONCELIK SIRASI

### 1. Proses_M (45 satir)
- Kategori: KUCUK (full export)
- ~0.03 MB
- Onerilen filtre: WHERE insDT >= '2026-01-01'

### 2. Urt_Emir (2,750 satir)
- Kategori: KUCUK (full export)
- ~2.62 MB
- Onerilen filtre: WHERE EmirTarihi >= '2026-01-01'

### 3. Model_M (3,145 satir)
- Kategori: KUCUK (full export)
- ~2.7 MB
- Onerilen filtre: WHERE Tarih >= '2026-01-01'

### 4. Cari_Kart (3,270 satir)
- Kategori: KUCUK (full export)
- ~14.81 MB
- Onerilen filtre: WHERE KartTar >= '2026-01-01'

### 5. Siparis_Kay (5,181 satir)
- Kategori: KUCUK (full export)
- ~16.55 MB
- Onerilen filtre: WHERE SipTar >= '2026-01-01'

### 6. Urt_con_gch (5,781 satir)
- Kategori: KUCUK (full export)
- ~6.89 MB
- Onerilen filtre: WHERE SendTar >= '2026-01-01'

### 7. StokKart (7,903 satir)
- Kategori: KUCUK (full export)
- ~36.18 MB
- Onerilen filtre: WHERE KARTTAR >= '2026-01-01'

### 8. Urt_Em_gch (8,896 satir)
- Kategori: KUCUK (full export)
- ~9.33 MB
- Onerilen filtre: WHERE SendTar >= '2026-01-01'

### 9. Siparis_Har (26,270 satir)
- Kategori: ORTA (full export batched)
- ~40.08 MB
- Onerilen filtre: WHERE TerminTarihi >= '2026-01-01'

### 10. Urt_Em2Em (67,425 satir)
- Kategori: ORTA (full export batched)
- ~35.37 MB
- Onerilen filtre: WHERE insDT >= '2026-01-01'

### 11. Urtx_con_gch (712,481 satir)
- Kategori: BUYUK (tarih filtreli)
- ~849.34 MB
- Onerilen filtre: WHERE SendTar >= '2026-01-01'

## RISK
| Risk | Onlem |
|---|---|
| Buyuk SELECT MSSQL yorar | WITH(NOLOCK), mesai disi |
| Hamachi kopar | Resume mantigi |
| Disk dolar | Parquet sikistirma |