# ENJ CORE KURALLARI

## 1. Setup tek gerçek kaynaktır.

Üretim hesabı için tüm parametreler (aktif_göz, KBÇ, kalıp) aktif setup'tan alınır.
Canlı istasyon veya başka bir kaynak setup'un önüne geçemez.

## 2. Saatlik snapshot: aktif_göz × KBÇ

Saatlik kayıt freeze edildiği anda tur kapasitesi şu formülle donar:

```
tur_kapasitesi = aktif_goz_sayisi × kalip_basi_cift
```

Bu değer `enj_saatlik_kayit.tur_kapasitesi_{a|b}_snapshot` kolonuna yazılır.

## 3. Setup varsa: Live istasyon override YASAK.

`_slot_snapshot_from_setup()` içinde:
- Setup mevcutsa → **sadece** `setup.aktif_goz × setup.kalip_basi_cift` kullanılır.
- Live istasyon SUM'u hiçbir zaman setup'un önüne geçmez.

## 4. Live fallback: Sadece setup yoksa.

`get_active_setup()` `None` döndürdüğünde (setup hiç başlatılmamış) live fallback devreye girer:

```
tur_kap = SUM(COALESCE(istasyon.kalip_basi_cift, master.kalip_basi_cift, 0))
```

## 5. A ve B slot bağımsızdır.

Her slot kendi setup'ını, kendi snapshot'ını ve kendi üretim sayacını bağımsız tutar.
A'nın parametreleri B'yi etkilemez, B'nin parametreleri A'yı etkilemez.

## 6. Geçmiş üretim değişmez.

`freeze_saatlik_snapshot()` içinde:
- Snapshot zaten yazılmışsa (`tur_kapasitesi_*_snapshot IS NOT NULL`) → **atlar**.
- Geçmiş saatlik kayıtlar sonraki setup değişimlerinden etkilenmez.

## 7. Kalıp değişirse: Yeni saat yeni setup, eski saat eski snapshot.

Setup değişikliği yeni saatten itibaren geçerlidir.
Değişiklik öncesi freeze edilmiş saatler eski snapshot değerlerini korur.

## 8. Operasyon raporu: Snapshot okur.

Operasyon raporu ve günlük özet hesaplamaları `uretilen_{a|b}` alanlarını kullanır;
bu değerler freeze anındaki `tur_kapasitesi_*_snapshot` ile hesaplanmıştır.

## 9. Fire: Gramaj snapshot mantığına bağlıdır.

Fire çift hesabı (`toplam_fire_cift`) için `cift_agirlik_gr_snapshot` kullanılır.
Bu snapshot, setup oluşturulduğunda Kalıp Master'dan alınan gramaj değeridir.
Gramaj sonradan değişirse yeni setup'tan itibaren etkilidir; geçmiş fire hesapları değişmez.

---

**Stabil Nokta:** `STABLE_ENJ_CORE_SNAPSHOT_V1` — commit `14bfd13`
