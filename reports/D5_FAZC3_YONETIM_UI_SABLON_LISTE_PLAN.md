# D5 FAZ C.3 — YÖNETİM UI SABLON LİSTE PLAN

**Tarih:** 2026-05-18 06:55
**Sprint:** D5 Faz C.3 (Yönetim UI - Şablon Liste)
**Amaç:** Mevcut backend için frontend HTML/JS oluşturmak
**Durum:** RECON tamamlandı, plan hazır

---

## 1. ÖZET

Sablon backend endpoint'leri **ZATEN VAR** (4 CRUD endpoint).
Sidebar'da **Şablon menüsü ZATEN VAR**.
**Eksik olan:** Frontend (HTML + JS).

Bu sprint sadece frontend ekler. Backend'e dokunmaz.

---

## 2. KRİTİK RECON BULGULARI

### 2.1 Mevcut Backend Endpoint'leri (DOKUNULMAZ)

```python
# app/modules/hedef/routes.py:

@hedef_bp.route('/sablon')                              # L54  - UI sayfa
@hedef_bp.route('/sablon/liste',     methods=['GET'])   # L746 - liste API
@hedef_bp.route('/sablon/ekle',      methods=['POST'])  # L797 - ekle API
@hedef_bp.route('/sablon/guncelle/<int:sid>',           # L841 - güncelle
                                     methods=['POST'])
@hedef_bp.route('/sablon/sil/<int:sid>',                # L888 - soft sil
                                     methods=['POST'])
```

### 2.2 Mevcut UI Hatası

`@hedef_bp.route('/sablon')` (L54) → `render_template('hedef/index.html')` döndürüyor.
**Bu YANLIŞ** — yönetim sayfası değil, anasayfa açıyor.

### 2.3 Sidebar'da Mevcut Link

```html
<!-- templates/base.html L726 -->
<a href="/hedef/sablon" class="si {% if '/hedef/sablon' in rp %}active{% endif %}" 
   title="Şablon / Proses">
```

Sidebar link aktif. Tıklanıyor ama içerik yok (anasayfa açıyor).

### 2.4 Mevcut DB Yapısı (C.1+C.2 Sonrası)

```
sablon          : 5 kayıt (4 aktif, 1 pasif)
sablon_proses   : 14 kayıt
sablon_eslesme  : 5 kayıt (C.2'de eklendi)
emir_alt_proses : 2273 (sablon_id 140 dolu)
```

---

## 3. C.3 KAPSAM

### 3.1 Yapılacaklar

1. ✏️ `routes.py` L58'de TEK SATIR değişir:
   - `render_template('hedef/index.html')` → `render_template('hedef/sablon.html')`

2. ➕ Yeni dosya: `app/templates/hedef/sablon.html`
   - base.html extend
   - Şablon listesi (kart yapısı)
   - Detay modal (read-only)

3. ➕ Yeni dosya: `app/static/hedef/sablon.js` (veya inline)
   - `/hedef/sablon/liste` GET
   - Liste render
   - Detay modal aç/kapa

### 3.2 Yapılmayacaklar (C.4'te)

- Sablon ekle/düzenle/sil butonları (sadece görsel, disabled)
- Eşleşme kuralları CRUD (C.4)
- Eşleşme test (C.4 sonrası)

---

## 4. UI MOCKUP

### 4.1 Liste Sayfası

```
┌─────────────────────────────────────────────────────────────────┐
│  ŞABLON YÖNETİMİ                                                │
│  Toplam: 5 şablon (4 aktif, 1 pasif)        [+ Yeni Şablon]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ #1  Atki LCW                                  ● Aktif     │  │
│  │  4 proses | 30 kayıt | 2 eşleşme kuralı                  │  │
│  │  Prosesler: Çapak → Rivet Takma → Tampon Baski →          │  │
│  │  Eşleşme: müşteri=LCW (öncelik 25), varsayilan=default    │  │
│  │  [Detay]  [Düzenle]  [Sil]                                │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ #2  İlham                                     ● Pasif     │  │
│  │  3 proses | 0 kayıt | 0 eşleşme kuralı                   │  │
│  │  ...                                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ #3  Aşağı iş indirme                          ● Aktif     │  │
│  │  1 proses | 22 kayıt | 1 eşleşme kuralı                  │  │
│  │  Prosesler: aşagı iş indirme                              │  │
│  │  Eşleşme: tip=Y (öncelik 100)                             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ #4  Lcw atkı                                  ● Aktif     │  │
│  │  5 proses | 65 kayıt | 1 eşleşme kuralı                  │  │
│  │  ...                                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ #5  Esem                                      ● Aktif     │  │
│  │  1 proses | 23 kayıt | 1 eşleşme kuralı                  │  │
│  │  ...                                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Detay Modal (Tıklayınca)

```
┌──────────────────────────────────────────────────────┐
│  Şablon Detayı: Atki LCW                       [X]   │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ID: 1     Durum: Aktif                              │
│  Oluşturan: admin                                    │
│  Oluşturma: 2026-04-22                               │
│                                                      │
│  ── Prosesler (sıra) ──                              │
│  1. Çapak                                            │
│  2. Rivet Takma                                      │
│  3. Tampon Baski                                     │
│  4. Atki Silme                                       │
│                                                      │
│  ── Eşleşme Kuralları ──                             │
│  • müşteri = 'LCW'   öncelik 25                      │
│  • varsayilan = 'default' öncelik 999                │
│                                                      │
│  ── Kullanım ──                                      │
│  Şu anda 30 emir_alt_proses kaydında kullanılıyor   │
│                                                      │
│                                          [Kapat]     │
└──────────────────────────────────────────────────────┘
```

---

## 5. BACKEND TEK SATIR DEĞİŞİKLİK

**Önce:**
```python
@hedef_bp.route('/sablon')
@hedef_yetkili
def sablon():
    """Sablon listesi - UI.2'de ayri sayfa."""
    return render_template('hedef/index.html')   # ← YANLIŞ
```

**Sonra:**
```python
@hedef_bp.route('/sablon')
@hedef_yetkili
def sablon():
    """Sablon listesi - UI.2'de ayri sayfa."""
    return render_template('hedef/sablon.html')  # ← DOĞRU
```

**Etki:** Sadece /hedef/sablon URL'i. Diğer endpoint'ler etkilenmez.

---

## 6. RİSK ANALİZİ

| Risk | Değer | Önlem |
|---|---|---|
| Mevcut endpoint'i bozma | DÜŞÜK | Sadece L58 template adı değişir |
| Backend uyumsuzluk | YOK | API zaten doğru, sadece tüketici eklenecek |
| Yetki bypass | DÜŞÜK | @hedef_yetkili decoratör mevcut |
| Saha personeli etkisi | YOK | /personel-giris, /hedef ana, /kaydet hiç etkilenmez |
| Davranış değişimi | YOK | Yeni sayfa (eskiden boştu) |
| Rollback | KOLAY | 1 satır geri al |

**Genel risk: DÜŞÜK**

---

## 7. SONRAKİ ADIMLAR (Faz C.4'e Hazırlık)

C.3 tamamlandıktan sonra C.4'te:
- Backend: `sablon_eslesme` CRUD endpoint'leri (4 yeni)
- Frontend: Sablon detay sayfasında eşleşme yönetimi
- Frontend: "Yeni Şablon" formu aktif (proses listesi)
- Frontend: Sablon düzenleme formu

---

## 8. SON KARAR

```
D5 FAZ C.3:
──────────────────────────────────────────
  Yeni endpoint               : YOK (mevcudu kullan)
  Backend değişiklik          : 1 satır (template adı)
  Yeni dosya                  : 2 (sablon.html + sablon.js)
  Risk seviyesi               : DÜŞÜK
  Süre tahmini                : 2 saat
  Saha etkisi                 : YOK
  Rollback                    : 1 satır geri al
  Patch'e hazır               : EVET
──────────────────────────────────────────
```

---

## 9. ONAY GEREKLİ — 3 Soru

### Soru 1: Eşleşme Bilgisi Gösterimi
- **A:** Liste sayfasında özet (sayı + ilk eşleşme) ← **Önerim**
- **B:** Sadece detay modalında göster
- **C:** Hiç gösterme (sadece sablon+proses)

### Soru 2: Aksiyon Butonları (C.3'te)
- **A:** [Detay] aktif, [Düzenle][Sil] disabled görünür ← **Önerim**
- **B:** Sadece [Detay], diğerleri hiç görünmez
- **C:** Hepsi aktif (riskli, C.4 hazır değil)

### Soru 3: Yetki
- **A:** Mevcut `@hedef_yetkili` yeterli ← **Önerim**
- **B:** Yeni yetki ekle (`hedef.sablon_yonetim`)
- **C:** Sadece admin görür

---

## Önerim Özet

```
1: A (özet bilgi)
2: A (disabled ile görsel hazırlık)
3: A (mevcut yetki)
```

---

**Oluşturan:** D5 Faz C.3 Recon + Plan
**Önceki belge:** D5_FAZC2_SABLON_ESLESME_PLAN.md
**Sonraki belge (onay sonrası):** D5_FAZC3_UYGULAMA_RAPORU.md
