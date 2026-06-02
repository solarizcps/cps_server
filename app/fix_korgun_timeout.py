# -*- coding: utf-8 -*-
"""
fix_korgun_timeout_basit.py
---------------------------
Sorun: Onceki patch 4-5 ayri batch SQL ekledi, Korgun timeout veriyor.

Cozum:
  1) korgun.py'i en son calisan .bak_* yedekten geri yukle (cari + EmirMiktari alias)
  2) Tek basit batch SQL ekle:
       SELECT EmirNo, SUM(Giren), MAX(RKOD) ile en sik dolduruluyor
     Aslinda dahasi: TEK sorgu hem alt emirler hem ana emirler icin.
  3) Yari mamul (alt) emirler icin EmirMiktari = SUM(Giren)
     Cunku gercek emir kapanis miktari Urt_Em_gch'de (eski usta_panel.html mantigi)
  4) Ana emirler icin de ayni SUM(Giren) eklenebilir ama sablon B3'te
     ANA emirler icin Siparis_Har.Miktar gosteriliyor (degistirme - PLAN ile tutarli)
     SADECE alt emirleri duzelt.

Yari mamul oncelik:
  - alt emir EmirMiktari = SUM(Urt_Em_gch.Giren) WHERE EmirNo=alt_emir_no

Renk:
  - SUM(Giren) ile ayni batch'te en buyuk RKOD'u sec
  - Tek sorgu yeter

Hizli, tek atisla.
"""

import os
import shutil
import datetime
import sys
import ast
import re

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")

KORGUN_MARKER = "# === FAZ 4.6 B3 fix_timeout v2 ==="


# ---------------------------------------------------------------------
# Adim 1: Korgun.py'i son calisan haline getir
# ---------------------------------------------------------------------
# En son sorunlu olan patch (alt-miktar-renk) bunlari ekliyor:
#   - alt_fisno_map, alt_rkod_map (4 query)
#   - ana_rkod_map (1 query)
# Bunlari kaldirmak yerine, tum bloklari TEK basit blokla degistirelim.

# Ana emirler bloku (alt-miktar-renk patch'i ekledi: 'RKOD': ana_rkod_map.get(...))
# Hedef: yine RKOD doner ama TEK SQL'le, hem ana hem alt icin.

# Mevcut hatali blok (eklenen ama timeout ureten):
ESKI_HATALI_BLOK = '''            # === FAZ 4.6 B3 alt emir miktar+renk ===
            # Alt emirler icin Urt_Em_gch'den FisNo (SipNo) ve RKOD bilgisi cek
            # TOPLAMA YOK: her alt emir tek SipNo'ya baglanir (en cok kayit)
            alt_emir_nos = [int(d['EmirNo']) for d in yari_dicts]
            alt_fisno_map = {}   # emir_no -> {sip_no, kayit, miktar}
            alt_rkod_map = {}    # emir_no -> rkod (en cok)
            if alt_emir_nos:
                placeholders = ','.join(['%s'] * len(alt_emir_nos))
                # En cok kayit alan FisNo'yu sec
                cur.execute(f"""
                    SELECT EmirNo, FisNo, COUNT(*) AS k
                    FROM Urt_Em_gch
                    WHERE EmirNo IN ({placeholders})
                      AND FisNo IS NOT NULL
                    GROUP BY EmirNo, FisNo
                    ORDER BY EmirNo, COUNT(*) DESC, FisNo ASC
                """, tuple(alt_emir_nos))
                for r in cur.fetchall():
                    e_no, fis_no, k = int(r[0]), r[1], int(r[2])
                    if e_no not in alt_fisno_map:  # ilk satir = en cok kayit
                        alt_fisno_map[e_no] = {
                            'sip_no': fis_no, 'kayit': k, 'miktar': None
                        }

                # Secilen SipNo'lar icin Siparis_Har.Miktar
                sec_sips = list(set(v['sip_no'] for v in alt_fisno_map.values()
                                    if v.get('sip_no')))
                if sec_sips:
                    sip_ph = ','.join(['%s'] * len(sec_sips))
                    cur.execute(f"""
                        SELECT SipNo, SUM(Miktar) AS toplam_miktar
                        FROM Siparis_Har
                        WHERE SipNo IN ({sip_ph})
                          AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                        GROUP BY SipNo
                    """, tuple(sec_sips))
                    sip_miktar_map = {int(r[0]): float(r[1] or 0) for r in cur.fetchall()}
                    for e_no, info in alt_fisno_map.items():
                        sip = info.get('sip_no')
                        if sip is not None:
                            try:
                                info['miktar'] = sip_miktar_map.get(int(sip))
                            except Exception:
                                info['miktar'] = None

                # RKOD: en cok kayit alan RKOD
                cur.execute(f"""
                    SELECT EmirNo, RKOD, COUNT(*) AS k
                    FROM Urt_Em_gch
                    WHERE EmirNo IN ({placeholders})
                      AND RKOD IS NOT NULL
                    GROUP BY EmirNo, RKOD
                    ORDER BY EmirNo, COUNT(*) DESC, RKOD ASC
                """, tuple(alt_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    if e_no not in alt_rkod_map:
                        alt_rkod_map[e_no] = r[1]

            for d in yari_dicts:
                emir_no_int = int(d['EmirNo'])
                parent_no = int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None
                ca_alt = parent_cari_map.get(parent_no) if parent_no else None
                fis_info = alt_fisno_map.get(emir_no_int) or {}
                miktar = fis_info.get('miktar')
                sip_no_alt = fis_info.get('sip_no')
                rkod_alt = alt_rkod_map.get(emir_no_int)
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': miktar,           # alt emir tek SipNo Miktar
                    'EmirMiktari': miktar,           # alias (B3 kolon-duzelt)
                    'SipNo': int(sip_no_alt) if sip_no_alt is not None else sip_no_int,
                    'ParentEmirNo': parent_no,
                    'CariAdi': ca_alt,
                    'RKOD': rkod_alt,
                })'''

# Yeni TEMIZ blok: TEK basit batch SQL hem ana hem alt icin
YENI_BLOK = '''            # === FAZ 4.6 B3 fix_timeout v2 ===
            # Tek basit batch: tum emirler icin SUM(Giren) ve MAX(RKOD)
            tum_emir_nos = [int(d['EmirNo']) for d in ana_dicts] + \\
                           [int(d['EmirNo']) for d in yari_dicts]
            emir_giren_map = {}
            emir_rkod_map = {}
            if tum_emir_nos:
                placeholders = ','.join(['%s'] * len(tum_emir_nos))
                cur.execute(f"""
                    SELECT EmirNo,
                           COALESCE(SUM(Giren), 0) AS toplam_giren,
                           MAX(RKOD) AS rkod_ornek
                    FROM Urt_Em_gch
                    WHERE EmirNo IN ({placeholders})
                    GROUP BY EmirNo
                """, tuple(tum_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    emir_giren_map[e_no] = float(r[1] or 0)
                    emir_rkod_map[e_no] = r[2]

            # Yari mamul (alt) emirler - EmirMiktari = SUM(Giren)
            for d in yari_dicts:
                emir_no_int = int(d['EmirNo'])
                parent_no = int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None
                ca_alt = parent_cari_map.get(parent_no) if parent_no else None
                miktar_alt = emir_giren_map.get(emir_no_int)
                if miktar_alt == 0:
                    miktar_alt = None
                rkod_alt = emir_rkod_map.get(emir_no_int)
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': miktar_alt,
                    'EmirMiktari': miktar_alt,
                    'SipNo': sip_no_int,
                    'ParentEmirNo': parent_no,
                    'CariAdi': ca_alt,
                    'RKOD': rkod_alt,
                })'''


# Ana emir blokundaki ana_rkod_map de var (alt-miktar-renk patch'i ekledi)
# O da kaldirilacak/temizlenecek. Mevcut blok:
ESKI_ANA_BLOK = '''            # Ana emirler icin RKOD batch (Urt_Em_gch'den en cok kayit)
            ana_emir_nos = [int(d['EmirNo']) for d in ana_dicts]
            ana_rkod_map = {}
            if ana_emir_nos:
                ana_ph = ','.join(['%s'] * len(ana_emir_nos))
                cur.execute(f"""
                    SELECT EmirNo, RKOD, COUNT(*) AS k
                    FROM Urt_Em_gch
                    WHERE EmirNo IN ({ana_ph})
                      AND RKOD IS NOT NULL
                    GROUP BY EmirNo, RKOD
                    ORDER BY EmirNo, COUNT(*) DESC, RKOD ASC
                """, tuple(ana_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    if e_no not in ana_rkod_map:
                        ana_rkod_map[e_no] = r[1]

            # parent_cari_map: yari mamul emirler ana emir cari_adi'sini paylassin
            parent_cari_map = {}
            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                hm_f = float(hm) if hm is not None else None
                ca = d.get('CariAdi')
                if ca == '-' or not ca:
                    ca = None
                emir_no_int = int(d['EmirNo'])
                parent_cari_map[emir_no_int] = ca
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': hm_f,
                    'EmirMiktari': hm_f,
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                    'CariAdi': ca,
                    'RKOD': ana_rkod_map.get(emir_no_int),
                })'''

# Yeni ana blok: ana_rkod_map yok (tek batch yeni blokta zaten yapildi)
YENI_ANA_BLOK = '''            # parent_cari_map: yari mamul emirler ana emir cari_adi'sini paylassin
            # Ana emir RKOD ve EmirMiktari ana_dicts dongusunde set edilir
            # (RKOD asagidaki tek batch SQL ile aliniyor - timeout v2 cozumu)
            parent_cari_map = {}
            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                hm_f = float(hm) if hm is not None else None
                ca = d.get('CariAdi')
                if ca == '-' or not ca:
                    ca = None
                emir_no_int = int(d['EmirNo'])
                parent_cari_map[emir_no_int] = ca
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': hm_f,
                    'EmirMiktari': hm_f,
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                    'CariAdi': ca,
                    'RKOD': None,  # asagidaki tek batch SQL doldurur
                })'''


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - Korgun timeout fix (basit tek batch)")
    print("=" * 64)

    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} yok.")
        return 1

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER in src:
        print("  [BILGI] Fix v2 zaten ekli.")
        return 0

    # Replacements
    if ESKI_HATALI_BLOK not in src:
        print("  [HATA] ESKI_HATALI_BLOK bulunamadi (alt emir bloku).")
        print("  Onceki patch dogru uygulanmamis olabilir. Manuel inceleme gerek.")
        return 1
    if src.count(ESKI_HATALI_BLOK) > 1:
        print("  [HATA] ESKI_HATALI_BLOK cogul.")
        return 1
    if ESKI_ANA_BLOK not in src:
        print("  [HATA] ESKI_ANA_BLOK bulunamadi (ana emir bloku).")
        return 1
    if src.count(ESKI_ANA_BLOK) > 1:
        print("  [HATA] ESKI_ANA_BLOK cogul.")
        return 1

    # Once ana blok'u degistir (yeni icinde RKOD: None olarak ayarliyor)
    new_src = src.replace(ESKI_ANA_BLOK, YENI_ANA_BLOK, 1)

    # Sonra alt blok'u degistir
    new_src = new_src.replace(ESKI_HATALI_BLOK, YENI_BLOK, 1)

    # Yeni blokta RKOD'lari ana emirler icin de doldurmak gerek
    # Yeni blok 'tum_emir_nos' kullaniyor, ama ana_dicts dongusu ondan ONCE
    # calistigi icin emirler[] icindeki ana emirlerde RKOD: None kalacak.
    # Cozum: yeni blok sonunda ana emir RKOD'larini guncelle.
    EK_ANA_RKOD = '''
            # Ana emir RKOD'larini emir listesinde guncelle
            for em in emirler:
                if em.get('EmirTip') == 'ana':
                    em['RKOD'] = emir_rkod_map.get(em['EmirNo'])'''

    # YENI_BLOK sonuna EK_ANA_RKOD'u ekle
    # YENI_BLOK string'i tek bir try icinde basliyor, sonu yari_dicts dongusu sonunda.
    # Yari_dicts dongusunden sonra emir listesi dolu, oraya ek yapacagiz.
    # Aslinda YENI_BLOK stringinin sonu zaten yari_dicts dongusu. Bunun sonunda
    # ek SQL gerek yok cunku batch zaten yapildi. Sadece ana emirleri update etmek.

    # YENI_BLOK'un en sonuna ekle
    yeni_blok_sonu = "})"  # son satirin son karakterleri
    # Daha guvenli: YENI_BLOK string olarak src'de var simdi, onun bittigi yere ek koy
    # Ek aslinda yari_dicts for dongusu BITTIKTEN sonra olmali, yari_dicts dongusu
    # YENI_BLOK'un sonu. Yeni blok'tan sonra sonraki kod (emirler.sort() vs.) geliyor.
    # Kolay: YENI_BLOK sonuna append et ve yari_dicts'in en son '})' ardindan ekle.

    # Daha guvenli bir yol: yari_dicts for dongusu kapanisindan sonra eklenecek text
    # YENI_BLOK'un son satiri:
    yeni_son = """                    'RKOD': rkod_alt,
                })"""
    yeni_son_with_ana_update = yeni_son + EK_ANA_RKOD

    if yeni_son in new_src:
        new_src = new_src.replace(yeni_son, yeni_son_with_ana_update, 1)
        print("  [OK] Ana emir RKOD update kodu eklendi.")
    else:
        print("  [UYARI] Yeni blok sonu bulunamadi, ana emir RKOD'lari None kalacak.")

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return 1

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Korgun helper temizlendi: TEK basit batch SQL, hizli.")
    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat")
    print("  2) Browser'da Ctrl+F5")
    print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
    print()
    print("Beklenen:")
    print("  - HEMEN cevap (timeout yok)")
    print("  - Alt emirlerde EMIR CIFT ADET dolu (SUM(Giren) - 280, 480 gibi)")
    print("  - Ana emirlerde EMIR CIFT ADET 7000 (Siparis_Har.Miktar - oldugu gibi)")
    print("  - RKOD: ana ve alt emirlerde MAX(RKOD) - kucuk sayi (1-10)")
    print()
    print("Test:")
    print("  fetch('/hedef/siparis/emirler?sipno=33558',{credentials:'include'})")
    print("    .then(r=>r.json()).then(d=>console.table(d.emirler.slice(0,3)))")
    return 0


if __name__ == '__main__':
    sys.exit(main())
