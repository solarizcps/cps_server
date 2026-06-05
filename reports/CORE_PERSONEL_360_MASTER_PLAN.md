# CORE PERSONEL 360 — MASTER PLAN

**Versiyon:** 1.0  
**Tarih:** 2026-06-05  
**Durum:** Planlama (kod yok)  
**Hazırlayan:** Claude / AI Geliştirme

---

## 1. AMAÇ

CPS sisteminde her personelin tek bir ekranda 360° görünmesini sağlamak:  
kimlik → organizasyon → görev → üretim → kalite → PDKS → izin → maaş/prim → uyarılar → notlar.

Mevcut sistem bilgiyi birden fazla yerde parçalı tutuyor:
- Yetki → `sistem_kullanici` + `sistem_rol`
- Saha kimliği → `personel_kullanici` + legacy `pers_kullanici`
- Organizasyon → `kullanici_profil` + `departman_master` + `ekip_master`
- Görev → `tasks`
- Bildirim → `bildirim_log`
- Üretim → `uretim_kayit`

Hedef: Bu parçaların tamamını **tek profil kartı** üzerinden okunabilir hale getirmek.  
Mimari değişmez — sadece yeni servis katmanı ve UI eklenir.

---

## 2. PERSONEL TİP HİYERARŞİSİ

```
CPS Personel Evreni
├── İDARİ PERSONEL
│   ├── Sistem Yöneticisi (SuperAdmin)
│   ├── Yönetim (RolId=1)
│   ├── Muhasebe / Finans
│   ├── Planlama
│   └── Diğer ofis rolleri
│
└── İMALAT PERSONELİ
    ├── Usta / Lider
    │   ├── Proses ustası (proses_usta_atama)
    │   └── Ekip lideri (ekip_master.lider_kullanici_profil_id)
    └── Saha Personeli
        ├── Aktif çalışan (personel_kullanici.aktif=1)
        └── Pasif / ayrılmış
```

### Personel Tip Kaynakları (Mevcut)

| Tip | Kaynak tablo | `Tip` değeri |
|-----|-------------|-------------|
| Sistem/İdari | `sistem_kullanici` | `sistem` |
| Usta | `usta_kullanici` (solariz_dev) veya `kullanici_profil.profil_tipi=SAHA_USTASI` | `usta` |
| Saha Personeli | `personel_kullanici` | `personel` |
| Fonksiyonel hesap | `sistem_kullanici` + özel rol | `sistem` |

### Yeni `profil_tipi` Standardı (Hedef)

```
YONETICI       → Genel müdür, fabrika müdürü
IDARI          → Ofis, muhasebe, planlama, İK
USTA           → Proses ustası, hat lideri
SAHA_PERSONEL  → Üretim çalışanı
FONKSIYONEL    → Sistem hesabı, bot, servis kullanıcısı
```

---

## 3. PERSONEL 360 PROFİL KARTI

Her profil kartı 10 bloktan oluşur:

### BLOK 1 — KİMLİK
| Alan | Kaynak |
|------|--------|
| Ad Soyad | `kullanici_profil.gercek_ad` |
| Sicil No | `personel_kullanici.sicil` |
| Profil tipi | `kullanici_profil.profil_tipi` |
| Fotoğraf | Gelecek: `personel_gorsel` |
| Telefon | Gelecek: `personel_iletisim.telefon` |
| Email | `sistem_kullanici.Email` |

### BLOK 2 — ORGANİZASYON
| Alan | Kaynak |
|------|--------|
| Departman | `departman_master.ad` via `kullanici_profil.departman_id` |
| Ekip | `ekip_master.ad` via `kullanici_ekip` |
| Ekip Rolü | `kullanici_ekip.rol` |
| Üst kişi (usta) | `usta_personel_iliskisi.usta_profil_id` |
| Proses yetkinlikleri | `kullanici_proses` + `proses_master_ref` |
| İşe başlama | Gelecek: `personel_kullanici.IseBaslamaTarih` |

### BLOK 3 — SİSTEM YETKİSİ
| Alan | Kaynak |
|------|--------|
| Sistem rol | `sistem_rol.Ad` |
| Modül yetkileri | `sistem_rol_yetki` özeti |
| Son giriş | `sistem_kullanici.SonGirisTarih` |
| Güven skoru | `personel_kullanici.GuvenSkoru` |

### BLOK 4 — GÖREV GEÇMİŞİ
| Alan | Kaynak |
|------|--------|
| Açık görevler | `tasks` WHERE `atanan_id` = profil, `durum != kapalı` |
| Tamamlanan görevler (son 30 gün) | `tasks` + `task_logs` |
| Geciken görevler | `tasks.bitis_tarihi < NOW()` |
| Görev puanı | Hesaplanan: tamamlanan / toplam |

### BLOK 5 — ÜRETİM PERFORMANSI
| Alan | Kaynak |
|------|--------|
| Bu ay toplam üretim | `uretim_kayit` SUM(miktar) |
| Ortalama günlük | Hesaplanan |
| En yüksek proses | GROUP BY proses |
| Vardiya bazlı dağılım | `uretim_kayit.vardiya` |
| Enjeksiyon katkısı | `enj_saatlik_kayit` (usta bağlantısı yapılacak) |

### BLOK 6 — KALİTE / HATA GEÇMİŞİ
| Alan | Kaynak |
|------|--------|
| Toplam fire | Gelecek: `kalite_hata_log` |
| Hata kategorileri | Gelecek: `kalite_hata_log.kategori` |
| Düzeltici aksiyonlar | Gelecek: `usta_aksiyon` |
| Kalite puanı | Hesaplanan |

### BLOK 7 — PDKS (Puantaj / Devam)
| Alan | Kaynak |
|------|--------|
| Bu ay devam | Gelecek: `pdks_kayit` |
| Geç gelme sayısı | Gelecek: `pdks_kayit.gecikme` |
| Erken çıkma | Gelecek |
| Fazla mesai | Gelecek |
| Toplam çalışma saati | Gelecek |

### BLOK 8 — İZİN YÖNETİMİ
| Alan | Kaynak |
|------|--------|
| Kalan yıllık izin | Gelecek: `izin_bakiye` |
| Kullanılan izin | Gelecek: `izin_kayit` |
| Bekleyen izin talepleri | Gelecek: `izin_talep` WHERE `durum=BEKLIYOR` |
| İzin geçmişi | Gelecek: `izin_kayit` |

### BLOK 9 — MAAŞ / PRİM
| Alan | Kaynak |
|------|--------|
| Baz maaş | Gelecek: `personel_maas.baz` (şifreli) |
| Bu ay prim | Gelecek: `prim_kayit` |
| Prim hesap kriterleri | Üretim + kalite + devam bağlantısı |
| Son ödeme tarihi | Gelecek |

### BLOK 10 — UYARI / BAŞARI / NOT
| Alan | Kaynak |
|------|--------|
| Aktif uyarılar | `bildirim_log.tip=UYARI` + okunmamış |
| Başarı rozetleri | Gelecek: `personel_rozet` |
| Yönetici notları | Gelecek: `personel_not` |
| Push gönderim geçmişi | `bildirim_log.push_gonderildi_mi=1` |
| Zaman çizelgesi | `sistem_audit` + `task_logs` + üretim olayları |

---

## 4. TABLO MODELİ

### Mevcut (kullanılacak)

```sql
kullanici_profil          -- merkez profil
sistem_kullanici          -- yetki/giriş
personel_kullanici        -- saha kimliği
departman_master          -- departman
ekip_master               -- ekip
kullanici_ekip            -- ekip üyeliği
kullanici_proses          -- yetkinlik
usta_personel_iliskisi    -- hiyerarşi
proses_master_ref         -- proses kataloğu
tasks / task_logs         -- görev
bildirim_log              -- bildirim/uyarı
uretim_kayit              -- üretim
sistem_audit              -- olay log
```

### Yeni Tablolar (Sprint'lere dağıtılacak)

```sql
-- SPRINT P1
personel_iletisim         -- telefon, email, acil kişi
personel_not              -- yönetici notu (yazarı, tarihi, içerik)
personel_rozet            -- başarı rozeti (tip, kazanım tarihi)

-- SPRINT P2
pdks_kayit                -- id, personel_id, tarih, giris_saati, cikis_saati,
                          -- gecikme_dk, erken_cikis_dk, mesai_dk, durum, kaynak
pdks_takvim               -- resmi tatil, vardiya şeması

-- SPRINT P3
izin_bakiye               -- personel_id, yil, yillik_hak, kullanilan, kalan
izin_talep                -- id, personel_id, baslangic, bitis, tip, durum, onaylayan_id
izin_kayit                -- onaylanmış ve gerçekleşmiş izinler

-- SPRINT P4
personel_maas             -- id, personel_id, donem, baz_maas (şifreli), para_birimi
prim_kayit                -- id, personel_id, donem, prim_tipi, tutar, hesap_kaynagi

-- SPRINT P5
kalite_hata_log           -- id, personel_id, tarih, hata_tipi, aciklama, duzeltme_id
personel_yildiz_gecmis    -- performans geçmişi
```

---

## 5. MEVCUT CORE İLE UYUM

| Kural | Uyum |
|-------|------|
| `kullanici_profil` merkez alınır | ✅ Tüm join'ler bu üzerinden |
| `sistem_kullanici` yetki için | ✅ Değişmez |
| `personel_kullanici` saha kimliği | ✅ `SistemKullaniciId` köprüsü korunur |
| ENJ snapshot mantığı | ✅ Dokunulmaz |
| RBAC / `@yetki_gerekli` | ✅ Profil API'si yetki korumalı |
| A/B slot bağımsızlığı | ✅ İlgisiz, korunur |

---

## 6. EKSİK TABLOLAR (Öncelik Sırası)

| # | Tablo | Öncelik | Bağımlılık |
|---|-------|---------|-----------|
| 1 | `personel_iletisim` | Yüksek | `kullanici_profil` |
| 2 | `personel_not` | Yüksek | `kullanici_profil`, `sistem_kullanici` |
| 3 | `pdks_kayit` | Yüksek | `personel_kullanici` |
| 4 | `izin_talep` + `izin_bakiye` | Orta | `personel_kullanici`, `kullanici_profil` |
| 5 | `prim_kayit` | Orta | `pdks_kayit`, `uretim_kayit` |
| 6 | `personel_maas` | Orta | `personel_kullanici` |
| 7 | `kalite_hata_log` | Düşük | `uretim_kayit` |
| 8 | `personel_rozet` | Düşük | `personel_kullanici` |

---

## 7. GÖREV / İZİN / MAAŞ / PRİM / PDKS BAĞLANTISI

```
personel_kullanici
    │
    ├── pdks_kayit           → çalışma saati, devam durumu
    │       │
    │       └── prim_kayit   → devam primi hesabı
    │
    ├── uretim_kayit         → üretim miktarı
    │       │
    │       └── prim_kayit   → üretim primi hesabı
    │
    ├── izin_talep           → izin talebi → izin_bakiye
    │
    ├── personel_maas        → baz maaş
    │
    └── prim_kayit           → toplam prim (devam + üretim + kalite)
```

**Prim Hesap Formülü (Öneri):**
```
toplam_prim = baz_prim
            + (uretim_adedi × birim_prim_katsayi)
            + (devam_puani × devam_prim_katsayi)
            - (hata_adedi × kesinti_katsayi)
```

---

## 8. TELEFON UYGULAMASI PUSH MANTIĞI

### Mevcut Altyapı
- `bildirim_log.push_gonderildi_mi` kolonu var
- Push token: henüz `personel_iletisim` tablosu yok

### Hedef Akış

```
Olay (üretim, görev, izin, PDKS) 
    │
    ├── tasks/notify.py → bildirim_log kayıt
    │
    └── push_service.py (yeni)
            │
            ├── personel_iletisim.push_token oku
            ├── FCM / APNs API çağrısı
            └── bildirim_log.push_gonderildi_mi = 1, push_zamani = NOW()
```

### Push Kategori Tipleri

| Tip | Tetikleyici |
|-----|------------|
| `GOREV_ATANDI` | tasks'a yeni atama |
| `GOREV_GECIKTI` | bitis_tarihi geçti, kapalı değil |
| `IZIN_ONAYLANDI` | izin_talep.durum = ONAY |
| `IZIN_REDDEDILDI` | izin_talep.durum = RED |
| `PDKS_GIRIS_YAPILMADI` | Mesai başlangıcı + X dk geçti |
| `PRIM_HESAPLANDI` | Ay sonu prim_kayit oluştu |
| `UYARI` | Yönetici notu / sistem uyarısı |

---

## 9. YÖNETİM EKRANLARI

### 9.1 Personel Listesi (`/yonetim/personel`)
- Tablo: ad, sicil, departman, ekip, tip, aktif, son giriş
- Filtre: tip, departman, ekip, aktif/pasif
- Aksiyon: profil aç, düzenle, pasifleştir

### 9.2 Personel 360 Kart (`/yonetim/personel/{id}`)
- 10 blok (yukarıdaki tasarım)
- Sekmeli layout: KİMLİK / ORG / GÖREV / ÜRETİM / PDKS / İZİN / MAAŞ / UYARI
- Hızlı aksiyonlar: Not ekle, Görev ata, İzin onayla

### 9.3 Ekip Yönetimi (`/yonetim/ekip`)
- Mevcut: `ekip_master` CRUD — genişletilecek
- Ekip performans özeti: üretim, devam, görev tamamlama

### 9.4 PDKS Özet (`/yonetim/pdks`)
- Günlük/haftalık devam tablosu
- Renk kodlu: geldi / geç / eksik / izinli
- Export: Excel

### 9.5 İzin Takip (`/yonetim/izin`)
- Bekleyen talepler → onayla / reddet
- Ekip takvimi görünümü

### 9.6 Prim Hesaplama (`/yonetim/prim`)
- Dönem seç → hesapla → onayla → kilitle
- Kriterleri düzenle (üretim katsayısı, devam katsayısı)

---

## 10. FAZ PLANI

### FAZ P0 — Temel Veri Temizliği (Ön koşul)
**Süre:** 1–2 gün  
**Kod yok, sadece veri:**
- `kullanici_profil` ile `personel_kullanici` arasındaki eksik köprüleri tamamla
- `profil_tipi` standardize et (SAHA_PERSONEL / USTA / IDARI)
- `departman_id` boş profilleri doldur

---

### FAZ P1 — Profil Kartı V1 (Sprint 1)
**Süre:** 3–5 gün

**Tablolar:** `personel_iletisim`, `personel_not`  
**Migration:** `app/migrations/020_personel_iletisim_not.py`

**Backend:**
- `GET /yonetim/api/personel/{profil_id}` → Blok 1+2+3 verileri
- `POST /yonetim/api/personel/{profil_id}/not` → Not ekle
- `GET /yonetim/api/personel` → Liste + filtre

**Frontend:**
- `/yonetim/personel` liste sayfası
- `/yonetim/personel/{id}` kart sayfası (KİMLİK + ORG + GÖREV sekmeleri)

---

### FAZ P2 — PDKS (Sprint 2)
**Süre:** 4–6 gün

**Tablolar:** `pdks_kayit`, `pdks_takvim`  
**Migration:** `app/migrations/021_pdks.py`

**Backend:**
- `POST /yonetim/api/pdks/giris` → Manuel veya QR girişi
- `GET /yonetim/api/pdks/ozet?donem=2026-06` → Özet
- `GET /yonetim/api/pdks/gunluk?tarih=2026-06-05` → Günlük tablo

**Frontend:**
- `/yonetim/pdks` özet ekranı
- Personel kartına PDKS sekmesi

---

### FAZ P3 — İzin Yönetimi (Sprint 3)
**Süre:** 3–4 gün

**Tablolar:** `izin_bakiye`, `izin_talep`, `izin_kayit`  
**Migration:** `app/migrations/022_izin.py`

**Backend:**
- `POST /personel-giris/api/izin-talep` → Personel talep açar
- `PATCH /yonetim/api/izin/{id}/onayla|reddet` → Yönetici onaylar
- `GET /yonetim/api/izin/bekleyenler` → Onay kuyruğu

---

### FAZ P4 — Maaş / Prim (Sprint 4)
**Süre:** 5–7 gün

**Tablolar:** `personel_maas`, `prim_kayit`  
**Migration:** `app/migrations/023_maas_prim.py`

**Not:** Maaş verisi şifreli tutulur. Sadece HR/Yönetim rolü görebilir.

---

### FAZ P5 — Telefon Push (Sprint 5)
**Süre:** 3–5 gün

**Tablolar:** `personel_iletisim.push_token` kolonu (P1'de oluşturuluyor)  
**Yeni servis:** `app/modules/push/service.py`

---

## 11. İLK UYGULANACAK SPRINT ÖNERİSİ

### Sprint P1-MINI (1–2 gün, minimum kod)

**Hedef:** Mevcut verileri hiç yeni tablo gerektirmeden tek ekranda göster.

**Yapılacak:**
1. `GET /yonetim/api/personel` → `kullanici_profil` + `personel_kullanici` + `departman_master` + `ekip_master` join
2. `GET /yonetim/api/personel/{id}` → KİMLİK + ORG + son 5 görev + son 10 üretim kaydı
3. `/yonetim/personel` liste sayfası (HTML template)
4. `/yonetim/personel/{id}` kart sayfası (3 sekme: KİMLİK, GÖREV, ÜRETİM)

**Yeni tablo yok.** Mevcut veri gösterilir.  
**Tahmini süre:** 1.5 gün  
**Risk:** Düşük — sadece SELECT sorguları + yeni template.

---

## 12. MEVCUT BAĞIMLILIKLAR VE RİSKLER

| Risk | Açıklama | Çözüm |
|------|----------|-------|
| `kullanici_profil` ↔ `personel_kullanici` köprüsü eksik | Bazı profillerde `kaynak_id` eşleşmiyor | FAZ P0 veri temizliği |
| `profil_tipi` standardize değil | Farklı değerler DB'de | Normalizasyon migration |
| Maaş verisi hassas | Tüm roller görmemeli | `@yetki_gerekli` + role bazlı filtre |
| PDKS QR gerektiriyorsa | Telefon donanımı gerekebilir | İlk faz manuel giriş |
| Push token altyapısı | FCM/APNs kayıt gerekli | Sprint P5'e ertele |
| ENJ/snapshot çekirdeği | Dokunulmamalı | Bu plan ENJ'e dokunmaz |

---

## 13. ÖZET

| Faz | İçerik | Süre | Öncelik |
|-----|--------|------|---------|
| P0 | Veri temizliği | 1–2 gün | Ön koşul |
| P1 | Profil kart V1 + not | 3–5 gün | YÜK |
| P2 | PDKS | 4–6 gün | YÜK |
| P3 | İzin | 3–4 gün | ORTA |
| P4 | Maaş/Prim | 5–7 gün | ORTA |
| P5 | Push | 3–5 gün | DÜŞÜK |

**Toplam tahmini:** 19–29 iş günü (paralel yürütülürse 10–15 gün)

---

**Anayasa Notu:**  
Bu plan ENJ_CORE_SNAPSHOT_V1 mimarisine dokunmaz.  
Enjeksiyon, Kalıp Master, Fire, Operasyon Raporu modülleri değişmez.  
Personel 360 tamamen ayrı bir katman olarak inşa edilir.
