# CPS İK / PERSONEL 360 / PDKS DEVİR NOTU
Tarih: 19.06.2026

## SON STABLE NOKTA

Commit:
dabf3f2
IK PDKS: fix transfer create button action

GitHub main güncel.

---

# TAMAMLANAN FAZLAR

## FAZ-6B — PDKS Hafıza
Commit:
84037eb

Yapıldı:
- PDKS MySQL bağlantısı kuruldu
- CPS içine geçmiş veri alındı
- 1173 devam kaydı
- 37 izin kaydı

Artık:
PDKS kapanırsa geçmiş kaybolmaz.

Akış:
PDKS
↓
personel_devam
personel_izin
↓
Personel 360

---

## FAZ-6C — PDKS Aktarım Merkezi

Commit:
799a06c

Yapıldı:
- Personel ekranından ayrıldı
- Ayrı aktarım merkezi oluşturuldu

Durum:
129 PDKS personel
16 CPS bağlı
107 yeni aday
6 çift kayıt

---

## FAZ-7A — PDKS Kart Bağlantısı

Commit:
91a1e38

Personel 360 içine:
- PDKS durum
- PDKS ID
- Sicil

eklendi.

---

## FAZ-7B — Ana Personel Mimarisi

Commit:
a0809d3

KRİTİK KARAR:

ANA PERSONEL TABLOSU:
kullanici_profil

personel_kullanici sadece üretim/telefon
sistem_kullanici sadece CPS giriş

Bu karar bozulmayacak.

---

## FAZ-7C1 — Maaş Güvenliği

Commit:
7f5d92a

Yetkiler:

Admin:
hepsi

İK:
maaş
not
personel bilgi

Usta:
ekip
devam
performans

Usta maaş göremez.

---

## FAZ-7C2 — Rol Kontrol

Commit:
eae7519

Yetki açıkları kapatıldı.

---

## FAZ-7C3 — PDKS Modal UI

Commit:
6c48b73

Modal şeffaflık problemi düzeldi.

---

## FAZ-7C4 — Kontrollü Personel Kabul

Commit:
177df70

Yeni akış:

PDKS Yeni Aday
↓
CPS'e Al
↓
İK seçer:

- Üretim / İdari
- Departman
- Pozisyon

Sonra profil oluşturulur.

Toplu otomatik alma yapılmayacak.

---

## FAZ-7C5 — Onay Butonu Fix

Commit:
dabf3f2

Düzeltildi:
- Onayla & Oluştur click
- JS scope
- hata gösterimi
- modal scroll

---

# MEVCUT PERSONEL AKIŞI

Yeni personel:

PDKS
↓
PDKS Aktarım Merkezi
↓
İK kontrol
↓
CPS'e Al
↓
Personel 360

---

# SONRA DEVAM EDİLECEK İŞLER

## FAZ-7D-1

Minimum Personel Düzenleme

Yapılacak:

- Telefon
- Adres
- Departman değiştir
- Pozisyon değiştir
- İşe giriş tarihi
- Not

Maaş/dosya sonraya bırakıldı.

---

## GELECEK

Personel performansı Hedef modülü sonrası bağlanacak.

Örnek:

PDKS:
176 saat

Üretim:
5000 çift

Kalite:
% hata

Sonuç:
personel verim

---

# ÖNEMLİ KURAL

Hedef modülünden gelen üretim verisi olmadan performans ekranı geliştirilmez.

Önce:
Hedef / Sipariş Takip tamamlanacak.

SONRA:
Personel 360 performans bağlanacak.
