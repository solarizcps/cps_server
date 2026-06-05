# D5 C.8 - FLAG=True CANLI ROLLOUT BASARI RAPORU

**Tarih:** 18.05.2026 10:13
**Sprint:** D5 C.8 - USE_CPS_NATIVE_PROSES FLAG flip (False -> True)
**Sonuc:** BASARILI - Lazy trigger canlida calisiyor, saha kesintisiz

---

## OZET

C.5 motor altyapisi + P4 lazy hook canliya alindi. FLAG=True ile lazy trigger calisiyor:
- CPS dolu emirler korundu (110393 BIREBIR ayni)
- CPS bos emirler otomatik trigger ile dolduruldu (111015 ilk gercek otomatik INSERT)
- Duplicate koruma calisti (2. cagri hook atladi)
- Audit zenginlesti (sablon_id INSERT'te yazildi)
- Saha dokunulmadi (uretim_kayit 1380)

---

## ATOMIC MOVE

| Detay | Deger |
|-------|-------|
| Yedek | app/config.py.YEDEK_C8_FLAG_20260518_101006 |
| Onceki hash | 2F6BFFBAECC77EF1 (P6 - FLAG False) |
| Yeni hash | **6CD32DCB1E1B3EBE** (FLAG True) |
| Sure | 0.21 ms |
| Tek satir degisim | L50: USE_CPS_NATIVE_PROSES = False -> True |
| AST + py_compile | PASS |
| Flask reload | 5 sn |

---

## TEST SONUCLARI (5/5 PASS)

### TEST A: /personel-giris/prosesler/110393 (CPS dolu)

**Amac:** FLAG=True iken CPS dolu emirler etkilenmemeli

| Olcum | Deger |
|-------|-------|
| Baseline (FLAG=False) | 982 byte, hash B9B1C8CC6C646AD5 |
| Post-C8 (FLAG=True) | 982 byte, hash B9B1C8CC6C646AD5 |
| Fark | **0 byte** |

**Sonuc:** BIREBIR AYNI. CPS dolu emirler korundu.

### TEST B: /personel-giris/prosesler/111015 (CPS bos, lazy trigger)

**Amac:** Lazy hook trigger calisip CPS'i dolduracak

| Olcum | Deger |
|-------|-------|
| Once | 3 byte ([]) - CPS yok, 5055 yok |
| Sonra | 244 byte - CPS_NATIVE_TRIGGERED |
| Yeni kayit | id=2282 |
| proses_adi | "Asagi is indirme" |
| kaynak | CPS_TRIGGER_C5:Asagi is indirme |
| sablon_id | 3 (audit kanitli) |
| aktif | 1 |
| veri_kaynagi | **CPS_NATIVE_TRIGGERED** (yeni tag) |
| Eslesme | tip=Y kurali (oncelik 100) |

**Sonuc:** Lazy hook **CANLI** tetiklendi. Otomatik INSERT basarili.

### TEST C: /personel-giris/prosesler/111015 (ikinci cagri)

**Amac:** Duplicate guard, hook atlamali, mevcut CPS okunmali

| Olcum | Deger |
|-------|-------|
| Boyut | 234 byte |
| Marker | CPS_NATIVE (TRIGGERED yok) |

**Sonuc:** Duplicate guard PASS. Hook atlandi, mevcut kayit dondurulur.

### TEST D: DB durumu

\\\
emir_alt_proses[111015]: 1 kayit
  id=2282 proses='Asagi is indirme' kaynak='CPS_TRIGGER_C5:Asagi is indirme'
  aktif=1 sablon_id=3 olusturan=Sistem(0)

GLOBAL CPS_TRIGGER aktif kayit: 1
uretim_kayit: 1380 satir, son: 2026-05-18 08:01:59
\\\

**Sonuc:** Sahanin uretim_kayit verisi DOKUNULMADI. Sadece CPS_TRIGGER kaydi eklendi.

### TEST E: Saha health + hash'ler

| Dosya | Hash | Durum |
|-------|------|-------|
| /health | 200 | STABIL |
| hedef/routes.py | 7EAC892167AFEAD1 | P6 KORUNDU |
| personel_giris/routes.py | F6D1953CC0243B0C | P4 KORUNDU |
| config.py | **6CD32DCB1E1B3EBE** | C.8 (yeni) |

---

## YENI DAVRANIS (FLAG=True)

\\\
GET /personel-giris/prosesler/<emir_no>
  |
  v
ADIM 1: CPS oku
  |
  +-- DOLU mu?
       EVET: CPS_NATIVE (degisiklik yok)  [CPS dolu emirler]
       HAYIR: ADIM 1.5 (lazy hook)
              |
              v
              FLAG=True? -> EVET
                Korgun meta cek
                _eslesme_bul -> sablon
                _sablon_uygula_internal -> INSERT
                CPS tekrar oku -> CPS_NATIVE_TRIGGERED
              FLAG=False? -> hook atla
              Hata? -> sessizce gec
              |
              v
              ADIM 2: 5055 fallback (eger trigger calismadiysa)
\\\

---

## CANLI METRIK (snapshot anindaki)

- uretim_kayit: 1380 (dokunulmadi)
- emir_alt_proses CPS_TRIGGER aktif: 1 (sadece 111015 testimiz)
- emir_alt_proses toplam: 594 distinct emir
- Saha mesai: pazartesi sabah, sessiz (08:01 son kayit)

---

## GOZLEM PLANI

### Izlenecek metrikler

1. **Trigger sayisi (saatlik)** - emir_alt_proses WHERE kaynak LIKE 'CPS_TRIGGER%' AND aktif=1
2. **Yeni distinct emir** - kac emir otomatik dolduruldu
3. **Yanlis eslesme sikayetleri** - saha personeli (Halil) geri bildirim
4. **5055 fallback orani** - LEGACY_5055_SNAPSHOT cevap orani
5. **Korgun latency** - hook icindeki get_emir_ozet cagri suresi
6. **/prosesler/<emir> response time** - mobil saha bekleme

### Hatali eslesme riskleri (P3 ve C.8 ile gozlenecek)

- **varsayilan kural cok genis**: 111006 gibi M emirler atki sablonu alacak
- **tip=Y kurali cesitli emirleri kapsiyor**: 111015 govde, ama Y tipi her emir Asagi is indirme aliyor
- **proses_adi varyantlari**: 5055'te 30 varyant, CPS'te 11 standart - mapping eksiklikleri

### Manuel mudahale komutlari (gerektiginde)

**Tek emiri geri al:**
\\\powershell
POST /hedef/sablon/geri-al
Body: {"emir_no_listesi": ["<emir_no>"]}
\\\

**FLAG=False'a geri don (acil rollback):**
\\\powershell
Copy-Item app\config.py.YEDEK_C8_FLAG_20260518_101006 app\config.py -Force
\\\

**Tum CPS_TRIGGER kayitlari listele:**
\\\sql
SELECT emir_no, COUNT(*), MAX(created_at)
FROM emir_alt_proses
WHERE kaynak LIKE 'CPS_TRIGGER%' AND aktif=1
GROUP BY emir_no;
\\\

---

## 5055 FALLBACK STATU

- **AKTIF KALACAK** (kapatma karar yok)
- /prosesler/<emir>: CPS bos + Korgun yok ise -> LEGACY_5055_SNAPSHOT
- Trigger hata verirse -> LEGACY_5055_SNAPSHOT
- Sigorta agi: 5055 hala canli sistem (port 5055), kapatilirsa D6 sprint'inde

---

## NEXT (gozlem sonrasi)

- **C.9** - final verify (24+ saat canli izleme sonrasi)
- **D6** - 5055 kapatma plani (cok ileride, sadece C.9 PASS sonrasi)
- **Iyilestirme** - sablon_eslesme kural genisletmesi, proses_adi mapping