# -*- coding: utf-8 -*-
"""
NexGen Gerçek Veri Import Script'i
=====================================

Kaynak Excel'ler:
  - Copy of Nexgen Hammadde alımında çalıştığımız firmalar.xlsx
  - Nexgen elimizde olan hammadde 22.06.2026.xlsx

Bu script Excel'e bağımlı değildir — veriler aşağıda sabit tanımlanmıştır.
Excel yeniden değişirse veriyi burada güncelleyin.

Kullanım:
  python app/scripts/nexgen_gercek_veri_import.py           <- önizleme
  python app/scripts/nexgen_gercek_veri_import.py --confirm <- yaz

YAZILACAKLAR (sırayla):
  1) 8 gerçek tedarikçi
  2) 41 hammadde stok kartı (NEX-AA-BB kodlarıyla)
  3) Tedarikçi-stok eşleşmeleri (nexgen_tedarikci_stok)
  4) Açılış stok hareketleri (ACILIS_DEVIR — sadece KG > 0)

KURALLAR:
  - --confirm olmadan HİÇBİR KAYIT YAZILMAZ.
  - Idempotent: aynı kayıt zaten varsa SKIP geçer, hata vermez.
  - nexgen_stok_hareket için idempotent kontrol:
    aynı stok_kart_id + referans_tip=ACILIS_DEVIR varsa tekrar basmaz.
  - Önce bağımlılık kontrolü: nexgen_stok_aile tablosu mevcut olmalı (migration 051).
"""

import sqlite3
import os
import sys
from datetime import date

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
ACILIS_TARIH = '2026-06-22'
ACILIS_KULLANICI_ID = 1  # Adem

# ═══════════════════════════════════════════════════════════════
# 1) GERÇEK TEDARİKÇİLER
# ═══════════════════════════════════════════════════════════════
# (kod, ad, ulke, para_birimi, varsayilan_vade, notlar)
TEDARIKCILER = [
    ('URSA',   'Ursa',            'TR', 'TRY', 30, None),
    ('DERKIM', 'Derkim',          'TR', 'TRY', 30, None),
    ('MELOS',  'Melos',           'TR', 'TRY', 30, None),
    ('SANCAR', 'Sancar Kimya',    'TR', 'TRY', 30, None),
    ('PDL',    'PDL',             'TR', 'TRY', 30, None),
    ('DOGAN',  'Doğan Ticaret',   'TR', 'TRY', 30, None),
    ('AYDIN',  'Aydın Madencilik','TR', 'TRY', 30, None),
    ('ELKIM',  'Elkim Kauçuk',    'TR', 'TRY', 30, None),
]

# ═══════════════════════════════════════════════════════════════
# 2) GERÇEK STOK KARTLARI
# ═══════════════════════════════════════════════════════════════
# (nex_kod, ad, aa_kodu, kategori, alt_kategori, notlar)
# aa_kodu => nexgen_stok_aile.aa_kodu ile eşleşir
STOK_KARTLARI = [
    # ── EVA (01) ───────────────────────────────────────────────
    ('NEX-01-01', 'EVA 18',              '01', 'HAMMADDE', 'EVA',        None),
    ('NEX-01-02', 'EVA 22',              '01', 'HAMMADDE', 'EVA',        None),
    ('NEX-01-03', 'EVA 28',              '01', 'HAMMADDE', 'EVA',        None),
    ('NEX-01-04', 'EVA 33',              '01', 'HAMMADDE', 'EVA',        None),
    # ── POE (02) ───────────────────────────────────────────────
    ('NEX-02-01', 'POE',                 '02', 'HAMMADDE', 'POE',        None),
    # ── SBS (03) ───────────────────────────────────────────────
    ('NEX-03-01', 'SBS 1',               '03', 'HAMMADDE', 'SBS',        None),
    ('NEX-03-02', 'SBS 2',               '03', 'HAMMADDE', 'SBS',        None),
    # ── Peroksit / Ajan (04) ───────────────────────────────────
    ('NEX-04-01', 'ATR-312',             '04', 'KATKI',    'Peroksit',   None),
    ('NEX-04-02', 'DCP 99',              '04', 'KATKI',    'Peroksit',   None),
    ('NEX-04-03', 'DCP (BIBP 40)',       '04', 'KATKI',    'Peroksit',   None),
    ('NEX-04-04', 'TAIC 70',             '04', 'KATKI',    'Ajan',       None),
    # ── Yağlayıcı / Parafin (05) ──────────────────────────────
    ('NEX-05-01', 'Pewax',               '05', 'KATKI',    'Parafin',    None),
    ('NEX-05-02', 'Sterik Asit',         '05', 'KATKI',    'Yağlayıcı',  None),
    ('NEX-05-03', 'Sterik Asit 1801',    '05', 'KATKI',    'Yağlayıcı',  'Tip 1801'),
    ('NEX-05-04', 'Sterik Asit 1843',    '05', 'KATKI',    'Yağlayıcı',  'Tip 1843'),
    ('NEX-05-05', 'Çinko Sterat',        '05', 'KATKI',    'Yağlayıcı',  None),
    ('NEX-05-06', 'Çinko Sterat 2211',   '05', 'KATKI',    'Yağlayıcı',  'Tip 2211'),
    ('NEX-05-07', 'Lagonda',             '05', 'KATKI',    'Yağlayıcı',  None),
    # ── Dolgu (06) ─────────────────────────────────────────────
    ('NEX-06-01', 'Kalsit',              '06', 'KATKI',    'Dolgu',      None),
    # ── Yağ / Plastifiyan (07) ─────────────────────────────────
    ('NEX-07-01', 'Profor',              '07', 'HAMMADDE', 'Yağ',        None),
    ('NEX-07-02', 'NYPAR 315 Yağ',       '07', 'HAMMADDE', 'Plastifiyan','Çin kaynaklı'),
    # ── Pigment / Boya (08) ────────────────────────────────────
    ('NEX-08-01', 'P.Yellow 13 (1148)',  '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-02', 'P.Red 122',           '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-03', 'P.Red 48:2 BP',       '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-04', 'P.Red 48:3',          '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-05', 'Blue 15:1 Mavi Pigment','08','BOYA',    'Pigment',    None),
    ('NEX-08-06', 'Blue 15:3 Mavi Pigment','08','BOYA',    'Pigment',    None),
    ('NEX-08-07', 'Iron Oxide Red 130',  '08', 'BOYA',     'Demir Oksit',None),
    ('NEX-08-08', 'Iron Oxide Yellow 313','08','BOYA',     'Demir Oksit',None),
    ('NEX-08-09', 'Ultramarine Blue DTI-52','08','BOYA',   'Pigment',    None),
    ('NEX-08-10', 'HTA-301 Anatase Titanium Dioksit','08','BOYA','Beyazlatıcı',None),
    ('NEX-08-11', 'Pearlescent Silver 100','08','BOYA',    'Sedef',      None),
    ('NEX-08-12', 'Kahverengi 610 Pigment','08','BOYA',    'Pigment',    None),
    ('NEX-08-13', 'Kahverengi 600 Pigment','08','BOYA',    'Pigment',    'Tedarikçi belirlenecek'),
    ('NEX-08-14', 'Kahverengi 660 Pigment','08','BOYA',    'Pigment',    None),
    # ── FAZ-3D RF legacy import eksik pigmentler (08) ───────────
    ('NEX-08-15', 'Green 7',             '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-16', 'M.B 6501 Brown',      '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-17', 'M.B 8502 Black',      '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-18', 'Blue KNP 909',        '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-19', 'Orange 34',           '08', 'BOYA',     'Pigment',    None),
    ('NEX-08-20', 'Yellow 15',           '08', 'BOYA',     'Pigment',    None),
    # ── Karbon Siyah pigment (09) — kategori BOYA ────────────────
    ('NEX-09-01', 'N550',                '09', 'BOYA',     'Karbon Siyah',None),
    ('NEX-09-02', 'N330',                '09', 'BOYA',     'Karbon Siyah',None),
    # ── Recycle (10) ───────────────────────────────────────────
    ('NEX-10-01', 'Recycle Siyah',       '10', 'RECYCLE',  'Recycle',    None),
    ('NEX-10-02', 'Recycle Beyaz',       '10', 'RECYCLE',  'Recycle',    None),
    ('NEX-10-03', 'Recycle Karışık',     '10', 'RECYCLE',  'Recycle',    None),
]

# ═══════════════════════════════════════════════════════════════
# 3) TEDARİKÇİ-STOK EŞLEŞMELERİ
# ═══════════════════════════════════════════════════════════════
# (tedarikci_kodu, stok_nex_kodu, tercih_sirasi, notlar)
# Çin/Sıradışı tedarikçi eklenmez — notlar alanına yazılır
ESLESMELER = [
    # URSA
    ('URSA',   'NEX-07-01', 1, None),                        # Profor
    ('URSA',   'NEX-04-01', 1, None),                        # ATR-312
    ('URSA',   'NEX-04-02', 1, None),                        # DCP 99
    ('URSA',   'NEX-08-05', 1, None),                        # Blue 15:1 (15:1 Mavi)
    ('URSA',   'NEX-04-03', 1, None),                        # DCP(BIBP 40)
    ('URSA',   'NEX-04-04', 1, None),                        # TAIC 70
    # DERKIM
    ('DERKIM', 'NEX-02-01', 1, None),                        # POE
    ('DERKIM', 'NEX-07-01', 2, None),                        # Profor (alternatif)
    ('DERKIM', 'NEX-01-04', 1, None),                        # EVA 33
    ('DERKIM', 'NEX-01-03', 1, None),                        # EVA 28
    ('DERKIM', 'NEX-01-01', 1, None),                        # EVA 18
    ('DERKIM', 'NEX-01-02', 1, None),                        # EVA 22
    # POE alternatif kaynaklar — nota yazılıyor
    ('DERKIM', 'NEX-02-01', 1, None),                        # POE birincil (zaten var, SKIP)
    # EVA 28 ve 18 için Çin kaynağı nota
    # MELOS
    ('MELOS',  'NEX-05-07', 1, None),                        # Lagonda
    ('MELOS',  'NEX-05-06', 1, None),                        # Çinko Sterat 2211
    # SANCAR
    ('SANCAR', 'NEX-05-06', 2, None),                        # Çinko Sterat 2211 (alternatif)
    ('SANCAR', 'NEX-05-01', 1, None),                        # Pewax
    ('SANCAR', 'NEX-05-02', 1, None),                        # Sterik Asit
    ('SANCAR', 'NEX-05-05', 1, None),                        # Çinko Sterat
    # PDL
    ('PDL',    'NEX-03-01', 1, None),                        # SBS 1
    ('PDL',    'NEX-03-02', 1, None),                        # SBS 2
    ('PDL',    'NEX-07-02', 1, 'Çin kaynaklı ürün sağlanıyor'),  # NYPAR 315 Yağ
    # DOGAN
    ('DOGAN',  'NEX-05-02', 2, None),                        # Sterik Asit (alternatif)
    ('DOGAN',  'NEX-05-03', 1, None),                        # Sterik Asit 1801
    ('DOGAN',  'NEX-05-04', 1, None),                        # Sterik Asit 1843
    ('DOGAN',  'NEX-08-01', 1, None),                        # P.Yellow 13
    ('DOGAN',  'NEX-08-02', 1, None),                        # P.Red 122
    ('DOGAN',  'NEX-08-03', 1, None),                        # P.Red 48:2 BP
    ('DOGAN',  'NEX-08-04', 1, None),                        # P.Red 48:3
    ('DOGAN',  'NEX-08-05', 2, None),                        # Blue 15:1 (alternatif)
    ('DOGAN',  'NEX-08-06', 1, None),                        # Blue 15:3
    ('DOGAN',  'NEX-08-07', 1, None),                        # Iron Oxide Red 130
    ('DOGAN',  'NEX-08-08', 1, None),                        # Iron Oxide Yellow 313
    ('DOGAN',  'NEX-08-09', 1, None),                        # Ultramarine Blue
    ('DOGAN',  'NEX-08-10', 1, None),                        # HTA-301
    ('DOGAN',  'NEX-08-11', 1, None),                        # Pearlescent Silver
    ('DOGAN',  'NEX-08-12', 1, None),                        # Kahverengi 610
    ('DOGAN',  'NEX-08-14', 1, None),                        # Kahverengi 660
    # AYDIN
    ('AYDIN',  'NEX-06-01', 1, None),                        # Kalsit
    # ELKIM
    ('ELKIM',  'NEX-09-01', 1, None),                        # N550
    ('ELKIM',  'NEX-09-02', 1, None),                        # N330
    # EVA 18/28 için Çin ve Sıradışı — not olarak eklendi ayrıca:
    ('DERKIM', 'NEX-01-03', 1, 'Ayrıca Çin ve Sıradışı kaynaktan da alınabiliyor'),  # EVA28 revize
    ('DERKIM', 'NEX-01-01', 1, 'Ayrıca Çin ve Sıradışı kaynaktan da alınabiliyor'),  # EVA18 revize
]

# ═══════════════════════════════════════════════════════════════
# 4) AÇILIŞ STOK — Excel: Nexgen elimizde olan hammadde 22.06.2026
# ═══════════════════════════════════════════════════════════════
# (stok_nex_kodu, kg)  — sadece KG > 0 olanlar
ACILIS_STOK = [
    ('NEX-04-01', 1050.0),   # ATR-312
    ('NEX-04-02',   60.0),   # DCP 99
    ('NEX-08-05',   20.0),   # Blue 15:1 Mavi (15:1 Mavi)
    ('NEX-04-04',  125.0),   # TAIC 70
    ('NEX-05-07',   50.0),   # Lagonda
    ('NEX-02-01',25000.0),   # POE
    ('NEX-07-01', 9000.0),   # Profor
    ('NEX-01-03',12500.0),   # EVA 28
    ('NEX-01-01',11000.0),   # EVA 18
    ('NEX-05-05',  100.0),   # Çinko Sterat
    ('NEX-05-02',  150.0),   # Sterik Asit
    ('NEX-03-01',21375.0),   # SBS 1 (not: "Yeni gelenlerde dahil")
    ('NEX-03-02',21500.0),   # SBS 2
    ('NEX-07-02', 3939.0),   # NYPAR 315 Yağ
    ('NEX-08-01',   40.0),   # P.Yellow 13 (1148)
    ('NEX-08-02',   10.0),   # P.Red 122
    ('NEX-08-03',   20.0),   # P.Red 48:2 BP
    ('NEX-08-04',   25.0),   # P.Red 48:3
    ('NEX-08-06',  100.0),   # Blue 15:3 Mavi Pigment
    ('NEX-08-06',   10.0),   # Blue 15:3 Mavi Pigment (not: bu satır çift olabilir, idempotent korunur)
    ('NEX-08-07',   30.0),   # Iron Oxide Red 130
    ('NEX-08-08',   25.0),   # Iron Oxide Yellow 313
    ('NEX-08-09',   15.0),   # Ultramarine Blue
    ('NEX-08-12',   30.0),   # Kahverengi 610 Pigment
    ('NEX-08-13',   15.0),   # Kahverengi 600 Pigment
    ('NEX-08-14',   10.0),   # Kahverengi 660 Pigment
    ('NEX-06-01',15000.0),   # Kalsit
    ('NEX-09-01', 1100.0),   # N550
    ('NEX-09-02',  675.0),   # N330
]
# NOT: Excel'deki Blue 15:3 iki kez görünmüş gibi — gerçek değer 100 KG.
# Aşağıda idempotent kontrol nedeniyle ikincisi SKIP geçer.
# Gerçek değer 100 KG olarak alınacak (ilk satır).


# ═══════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════════

def on_izleme(cur):
    """Yazılacak kayıtların önizlemesini göster."""
    print("\n" + "=" * 65)
    print("NexGen Gerçek Veri Import — ÖNİZLEME")
    print("=" * 65)

    # Bağımlılık kontrolü
    aile_var = cur.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='nexgen_stok_aile'"
    ).fetchone()[0]
    esleme_var = cur.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='nexgen_tedarikci_stok'"
    ).fetchone()[0]

    if not aile_var or not esleme_var:
        print("\n  HATA: Migration 051 çalıştırılmamış!")
        print("  Önce: python app/migrations/051_nexgen_stok_aile_ve_esleme.py")
        return False

    # Mevcut sayılar
    n_ted = cur.execute("SELECT COUNT(*) FROM nexgen_tedarikci").fetchone()[0]
    n_kart = cur.execute("SELECT COUNT(*) FROM nexgen_stok_kart").fetchone()[0]
    n_esl = cur.execute("SELECT COUNT(*) FROM nexgen_tedarikci_stok").fetchone()[0]
    n_hrt = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]

    print(f"\n  Mevcut durum:")
    print(f"    nexgen_tedarikci       : {n_ted} kayıt")
    print(f"    nexgen_stok_kart       : {n_kart} kayıt")
    print(f"    nexgen_tedarikci_stok  : {n_esl} kayıt")
    print(f"    nexgen_stok_hareket    : {n_hrt} kayıt")

    # Yazılacaklar
    mevcut_ted = {r[0] for r in cur.execute("SELECT kod FROM nexgen_tedarikci").fetchall()}
    mevcut_kart = {r[0] for r in cur.execute("SELECT kod FROM nexgen_stok_kart").fetchall()}

    yeni_ted = [t for t in TEDARIKCILER if t[0] not in mevcut_ted]
    skip_ted = [t for t in TEDARIKCILER if t[0] in mevcut_ted]
    yeni_kart = [k for k in STOK_KARTLARI if k[0] not in mevcut_kart]
    skip_kart = [k for k in STOK_KARTLARI if k[0] in mevcut_kart]

    # Açılış stok — mevcut ACILIS_DEVIR var mı kontrol
    mevcut_acilis = set()
    for row in cur.execute(
        "SELECT sk.kod FROM nexgen_stok_hareket h "
        "JOIN nexgen_stok_kart sk ON sk.id = h.stok_kart_id "
        "WHERE h.referans_tip = 'ACILIS_DEVIR'"
    ).fetchall():
        mevcut_acilis.add(row[0])

    # Çakışma önlemi: aynı NEX kodu için sadece bir giriş
    gorulmus_acilis = set()
    yeni_acilis = []
    skip_acilis = []
    for kod, kg in ACILIS_STOK:
        if kod in gorulmus_acilis or kod in mevcut_acilis:
            skip_acilis.append((kod, kg, 'zaten var' if kod in mevcut_acilis else 'çift satır'))
        else:
            gorulmus_acilis.add(kod)
            yeni_acilis.append((kod, kg))

    toplam_acilis_kg = sum(kg for _, kg in yeni_acilis)

    # Eşleşme sayısı — benzersiz (tedarikci, stok) çiftleri
    eslesme_set = set()
    for ted_kod, stok_kod, sira, not_ in ESLESMELER:
        eslesme_set.add((ted_kod, stok_kod))
    yeni_eslesme_sayisi = len(eslesme_set)

    print(f"\n  İmport edilecekler:")
    print(f"    Tedarikçi eklenecek    : {len(yeni_ted):3d}  (skip: {len(skip_ted)})")
    print(f"    Stok kartı eklenecek   : {len(yeni_kart):3d}  (skip: {len(skip_kart)})")
    print(f"    Eşleşme eklenecek      : ~{yeni_eslesme_sayisi:3d}  (mevcut duplicate'ler skip)")
    print(f"    Açılış hareketi        : {len(yeni_acilis):3d}  (skip: {len(skip_acilis)})")
    print(f"    Toplam açılış KG       : {toplam_acilis_kg:,.0f} KG")

    if yeni_ted:
        print(f"\n  Eklenecek tedarikçiler:")
        for t in yeni_ted:
            print(f"    {t[0]:10s}  {t[1]}")

    if yeni_kart:
        print(f"\n  Eklenecek stok kartları ({len(yeni_kart)} adet):")
        for k in yeni_kart[:10]:
            print(f"    {k[0]:12s}  {k[1]}")
        if len(yeni_kart) > 10:
            print(f"    ... ve {len(yeni_kart)-10} tane daha")

    uyarilar = [k for k in STOK_KARTLARI if 'belirlenecek' in (k[5] or '')]
    if uyarilar:
        print(f"\n  Uyarılar:")
        for k in uyarilar:
            print(f"    {k[0]:12s}  {k[1]:35s}  NOT: {k[5]}")

    return True


def tedarikci_ekle(con, cur):
    eklendi = skip = 0
    for kod, ad, ulke, pb, vade, notlar in TEDARIKCILER:
        mev = cur.execute("SELECT id FROM nexgen_tedarikci WHERE kod=?", (kod,)).fetchone()
        if mev:
            skip += 1
        else:
            cur.execute("""
                INSERT INTO nexgen_tedarikci
                  (kod, ad, ulke, para_birimi, varsayilan_vade, notlar, aktif, olusturan_id)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (kod, ad, ulke, pb, vade, notlar, ACILIS_KULLANICI_ID))
            eklendi += 1
    con.commit()
    print(f"  Tedarikçi: {eklendi} eklendi, {skip} skip")
    return eklendi


def stok_kart_ekle(con, cur):
    eklendi = skip = hata = 0
    for nex_kod, ad, aa_kodu, kategori, alt_kat, notlar in STOK_KARTLARI:
        mev = cur.execute("SELECT id FROM nexgen_stok_kart WHERE kod=?", (nex_kod,)).fetchone()
        if mev:
            skip += 1
            continue
        aile = cur.execute("SELECT id FROM nexgen_stok_aile WHERE aa_kodu=?", (aa_kodu,)).fetchone()
        if not aile:
            print(f"    HATA: aa_kodu={aa_kodu} bulunamadı — {nex_kod} atlandı")
            hata += 1
            continue
        cur.execute("""
            INSERT INTO nexgen_stok_kart
              (kod, ad, kategori, birim, minimum_stok, kritik_stok,
               alt_kategori, notlar, aktif, aile_id, olusturan_id)
            VALUES (?, ?, ?, 'KG', 0, 0, ?, ?, 1, ?, ?)
        """, (nex_kod, ad, kategori, alt_kat, notlar, aile['id'], ACILIS_KULLANICI_ID))
        eklendi += 1
    con.commit()
    print(f"  Stok kartı: {eklendi} eklendi, {skip} skip, {hata} hata")
    return eklendi


def esleme_ekle(con, cur):
    eklendi = skip = hata = 0
    gorulmus = set()
    for ted_kod, stok_kod, sira, notlar in ESLESMELER:
        anahtar = (ted_kod, stok_kod)
        if anahtar in gorulmus:
            # Çift tanımlama — son not'u al ama ekleme
            skip += 1
            continue
        gorulmus.add(anahtar)

        ted = cur.execute("SELECT id FROM nexgen_tedarikci WHERE kod=?", (ted_kod,)).fetchone()
        stok = cur.execute("SELECT id FROM nexgen_stok_kart WHERE kod=?", (stok_kod,)).fetchone()

        if not ted:
            print(f"    HATA: tedarikci kod={ted_kod} bulunamadı")
            hata += 1
            continue
        if not stok:
            print(f"    HATA: stok kod={stok_kod} bulunamadı")
            hata += 1
            continue

        mev = cur.execute(
            "SELECT id FROM nexgen_tedarikci_stok WHERE tedarikci_id=? AND stok_kart_id=?",
            (ted['id'], stok['id'])
        ).fetchone()
        if mev:
            skip += 1
            continue

        cur.execute("""
            INSERT INTO nexgen_tedarikci_stok
              (tedarikci_id, stok_kart_id, tercih_sirasi, aktif, notlar)
            VALUES (?, ?, ?, 1, ?)
        """, (ted['id'], stok['id'], sira, notlar))
        eklendi += 1

    con.commit()
    print(f"  Eşleşme: {eklendi} eklendi, {skip} skip, {hata} hata")
    return eklendi


def acilis_hareket_ekle(con, cur):
    eklendi = skip = hata = 0
    gorulmus = set()

    for stok_kod, kg in ACILIS_STOK:
        if stok_kod in gorulmus:
            skip += 1
            continue
        gorulmus.add(stok_kod)

        stok = cur.execute("SELECT id FROM nexgen_stok_kart WHERE kod=?", (stok_kod,)).fetchone()
        if not stok:
            print(f"    HATA: stok kod={stok_kod} bulunamadı")
            hata += 1
            continue

        # Idempotent: bu kart için ACILIS_DEVIR zaten var mı?
        mev = cur.execute(
            "SELECT id FROM nexgen_stok_hareket "
            "WHERE stok_kart_id=? AND referans_tip='ACILIS_DEVIR'",
            (stok['id'],)
        ).fetchone()
        if mev:
            skip += 1
            continue

        cur.execute("""
            INSERT INTO nexgen_stok_hareket
              (stok_kart_id, hareket_tipi, miktar_kg, onceki_stok, sonraki_stok,
               aciklama, referans_tip, referans_id,
               olusturan_id, olusturma_tarihi)
            VALUES (?, 'ACILIS_DEVIR', ?, 0, ?,
                    'NexGen sistem açılışı - Excel sayım 22.06.2026',
                    'ACILIS_DEVIR', NULL,
                    ?, ?)
        """, (stok['id'], kg, kg, ACILIS_KULLANICI_ID, ACILIS_TARIH + ' 00:00:00'))
        eklendi += 1

    con.commit()
    print(f"  Açılış hareketi: {eklendi} eklendi, {skip} skip, {hata} hata")
    return eklendi


def son_rapor(cur):
    print("\n" + "=" * 65)
    print("Son Durum")
    print("=" * 65)
    n_ted  = cur.execute("SELECT COUNT(*) FROM nexgen_tedarikci").fetchone()[0]
    n_kart = cur.execute("SELECT COUNT(*) FROM nexgen_stok_kart").fetchone()[0]
    n_esl  = cur.execute("SELECT COUNT(*) FROM nexgen_tedarikci_stok").fetchone()[0]
    n_hrt  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    toplam_kg = cur.execute(
        "SELECT COALESCE(SUM(miktar_kg),0) FROM nexgen_stok_hareket WHERE referans_tip='ACILIS_DEVIR'"
    ).fetchone()[0]

    print(f"  nexgen_tedarikci       : {n_ted}")
    print(f"  nexgen_stok_kart       : {n_kart}")
    print(f"  nexgen_tedarikci_stok  : {n_esl}")
    print(f"  nexgen_stok_hareket    : {n_hrt}")
    print(f"  Toplam açılış KG       : {toplam_kg:,.0f} KG")

    print("\n  Aile bazlı stok kartı dağılımı:")
    rows = cur.execute("""
        SELECT a.aa_kodu, a.ad, COUNT(sk.id) as n
        FROM nexgen_stok_aile a
        LEFT JOIN nexgen_stok_kart sk ON sk.aile_id = a.id
        GROUP BY a.id ORDER BY a.aa_kodu
    """).fetchall()
    for r in rows:
        print(f"    {r[0]}  {r[1]:30s}  {r[2]} kart")


def main():
    confirm = '--confirm' in sys.argv

    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    devam = on_izleme(cur)
    if not devam:
        con.close()
        sys.exit(1)

    if not confirm:
        print("\n" + "=" * 65)
        print("İŞLEM YAPILMADI — Önizleme tamamlandı.")
        print("Yazmak için: python app/scripts/nexgen_gercek_veri_import.py --confirm")
        print("=" * 65)
        con.close()
        return

    print("\n" + "=" * 65)
    print("IMPORT BAŞLIYOR")
    print("=" * 65)

    print("\n[1] Tedarikçiler:")
    tedarikci_ekle(con, cur)

    print("\n[2] Stok Kartları:")
    stok_kart_ekle(con, cur)

    print("\n[3] Tedarikçi-Stok Eşleşmeleri:")
    esleme_ekle(con, cur)

    print("\n[4] Açılış Stok Hareketleri:")
    acilis_hareket_ekle(con, cur)

    son_rapor(cur)

    con.close()
    print("\nImport tamamlandı.")


if __name__ == '__main__':
    main()
