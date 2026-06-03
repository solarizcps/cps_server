# ENJEKSİYON ANAYASASI — 2026-06-03

## Temel Prensipler

### 1. A/B Bağımsız Slot Kuralı
A ve B slotları tamamen bağımsızdır.
- Her slotun ayrı `enj_ab_setup` kaydı vardır.
- Personel sayısı, aktif göz, KBÇ ve tur kapasitesi A ve B için ayrı ayrı tutulur.
- A'nın setup'ı değişmesi B'yi etkilemez, B'ninkisi A'yı etkilemez.

### 2. Setup Olmadan Tur Girişi Yok
Bir slot için `enj_ab_setup.durum='AKTIF'` kaydı yoksa o slota tur girişi kabul edilmez.
Setup eksikse kullanıcı bilgilendirilir.

### 3. Kalıp Seçince Setup Değiştir Modal Açılır
Panel üst kısmındaki kalıp input'una tıklandığında veya kalıp kodu değiştirildiğinde
"Setup Değiştir" modalı otomatik açılır.
Autocomplete veya inline düzenleme yapılmaz.

### 4. Snapshot Geçmişi Değiştirmez
`freeze_saatlik_snapshot()` çalıştıktan sonra o saatlik kaydın snapshot alanları
(`tur_kapasitesi_a_snapshot`, `tur_kapasitesi_b_snapshot`, `aktif_goz_a_snapshot`,
`kalip_basi_cift_a_snapshot`, `kalip_kod_a_snapshot`, vb.) bir daha değiştirilemez.
Yeni bir cevrim girişi snapshot kolonlarına dokunmaz, yalnızca `uretilen_a/b`'yi etkiler.

### 5. Üretim Hesabı
```
uretilen_a = cevrim_a × tur_kapasitesi_a_snapshot
uretilen_b = cevrim_b × tur_kapasitesi_b_snapshot
```
Snapshot alınmamış saatler için anlık `aktif_goz × KBÇ` kullanılır.
Snapshot alınmış saatlerde anlık değerler kullanılmaz.

### 6. Günlük Toplam
```
brut_cift = SUM(uretilen_a + uretilen_b)
```
Anlık KBÇ ile hesaplama yapılmaz. Tüm toplamlar saatlik `uretilen` değerlerinin SUM'ıdır.

### 7. Sıfır Üretim Doldurma (Mixed-Snapshot Fix)
`uretilen = 0` veya `NULL` iken `cevrim > 0` ise ve o slot için snapshot mevcutsa:
```
uretilen = cevrim × tur_kapasitesi_snapshot
```
Bu kural A-only-snapshot, B-only-snapshot ve her ikisi snapshot durumlarında bağımsız çalışır.
Mevcut `uretilen > 0` değerlerine kesinlikle dokunulmaz.

### 8. Max Tur Guard
Saatlik tur girişi üst sınırı:
```
max_tur = floor(3600 / pisme_suresi_sn × 1.15)
```
- Sunucu: HTTP 400 döner, kayıt yapılmaz.
- İstemci: Kullanıcıya uyarı toast gösterilir.
- Eski kayıtlara uygulanmaz.

### 9. Aktif İstasyon = Aktif Göz Senkronu
`PATCH /api/istasyon/<id>` ile bir istasyon aktif/pasif yapıldığında
`enj_ab_setup.aktif_goz_sayisi` o slotun canlı aktif istasyon sayısıyla otomatik güncellenir.
`/ab-ozet` endpoint'i her zaman güncel `aktif_goz_sayisi` döner.

### 10. Tur Kapasitesi Formülü
```
tur_kapasitesi = aktif_goz_sayisi × kalip_basi_cift
```
Bu değer setup kayıt edilirken hesaplanır ve snapshot olarak saatlik kayda yazılır.

### 11. Geçmiş Saatlik Kayıtlar Değişmez
Bir günlük rapor `taslak` aşamasındayken bile geçmiş saatlere ait `cevrim` ve `uretilen`
değerleri sonradan overwrite edilmez. Sadece `uretilen=0` boşlukları doldurulabilir.

### 12. UI/Modal Event Fix Korunur
Kalıp picker → Setup modal akışı, tablet iki sütun layout ve cache-busting versiyonları
bir sonraki UI değişikliğine kadar dokunulmadan korunur.

### 13. Tek Bug = Dar Patch Döngüsü
```
1 bug → 1 recon → 1 dar patch → 1 test → 1 commit
```
Patch tek dosyaya dokunur. Recon raporlanmadan patch uygulanmaz.
Test PASS olmadan commit alınmaz.

---

## Referans Commitler

| Hash | Açıklama |
|------|----------|
| `f3389ac` | ENJ: use frozen snapshot production totals in operation cards |
| `694a054` | ENJ: fill frozen snapshot production when cycles entered after freeze |
| `0bc8cb2` | ENJ: add hourly cycle count upper-bound validation |
| `3d29b04` | ENJ: sync active setup eye count after station toggle |
| `3430275` | ENJ: fill frozen production when only one slot has snapshot |

## Stabil Tag

`STABLE_ENJ_20260603_FINAL`
