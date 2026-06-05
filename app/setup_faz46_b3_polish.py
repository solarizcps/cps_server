# -*- coding: utf-8 -*-
"""
setup_faz46_b3_polish.py
------------------------
3 duzeltme tek seferde:
  1) ANA emirler icin EmirMiktari = SUM(Giren) (alt ile tutarli)
     Fallback: Siparis_Har.Miktar (eger Urt_Em_gch'de hareket yoksa)
  2) Siparis ozet paneli: emir sayisi + toplam cift adet
  3) RKOD: BedKod ile karismasin - sadece <100 olan degerler

Backend (korgun.py):
  - Ana emir bloku: 'EmirMiktari' = emir_giren_map.get(...) or hm_f
  - RKOD batch SQL: WHERE RKOD < 100 filtre

Frontend (hedef.js):
  - sb3-info'ya emir sayisi + toplam adet ekle
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

KORGUN_MARKER = "# === FAZ 4.6 B3 polish ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 polish"


# =====================================================================
# 1) BACKEND: ana emir EmirMiktari + RKOD filtre
# =====================================================================

# Mevcut ana emir append (timeout fix v2'den):
KORGUN_OLD_ANA = '''            # parent_cari_map: yari mamul emirler ana emir cari_adi'sini paylassin
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

KORGUN_NEW_ANA = '''            # === FAZ 4.6 B3 polish ===
            # Ana emir EmirMiktari = SUM(Giren) (alt ile tutarli, gercek lot miktari)
            # Fallback: Siparis_Har.Miktar (Urt_Em_gch'de hareket yoksa)
            # Bu blokun sonunda emir_giren_map ile guncellenecek
            parent_cari_map = {}
            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                hm_f = float(hm) if hm is not None else None
                ca = d.get('CariAdi')
                if ca == '-' or not ca:
                    ca = None
                emir_no_int = int(d['EmirNo'])
                parent_cari_map[emir_no_int] = ca
                # Ilk olarak Siparis_Har'i koy, asagida giren_map ile override edilecek
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': hm_f,                     # Siparis_Har bilgisi (fallback)
                    'SiparisMiktari': hm_f,                  # ham siparis miktari (fallback'i ayri tut)
                    'EmirMiktari': hm_f,                     # asagida update
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                    'CariAdi': ca,
                    'RKOD': None,
                })'''


# RKOD SQL: WHERE RKOD < 100 (BedKod genelde 1000+, RKOD genelde 1-99)
KORGUN_OLD_BATCH = '''            # === FAZ 4.6 B3 fix_timeout v2 ===
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
                    emir_rkod_map[e_no] = r[2]'''

KORGUN_NEW_BATCH = '''            # === FAZ 4.6 B3 fix_timeout v2 + polish ===
            # Tek batch: SUM(Giren) hem ana hem alt icin gercek miktar
            # RKOD: <100 filtre (BedKod 1000+ ile karismasin)
            tum_emir_nos = [int(d['EmirNo']) for d in ana_dicts] + \\
                           [int(d['EmirNo']) for d in yari_dicts]
            emir_giren_map = {}
            emir_rkod_map = {}
            if tum_emir_nos:
                placeholders = ','.join(['%s'] * len(tum_emir_nos))
                cur.execute(f"""
                    SELECT EmirNo,
                           COALESCE(SUM(Giren), 0) AS toplam_giren,
                           MAX(CASE WHEN RKOD IS NOT NULL AND RKOD < 100
                                    THEN RKOD ELSE NULL END) AS rkod_temiz
                    FROM Urt_Em_gch
                    WHERE EmirNo IN ({placeholders})
                    GROUP BY EmirNo
                """, tuple(tum_emir_nos))
                for r in cur.fetchall():
                    e_no = int(r[0])
                    emir_giren_map[e_no] = float(r[1] or 0)
                    emir_rkod_map[e_no] = r[2]

            # Ana emirlerin EmirMiktari'ni SUM(Giren) ile guncelle
            # Fallback: Siparis_Har.Miktar (zaten EmirMiktari=hm_f olarak set edilmisti)
            for em in emirler:
                if em.get('EmirTip') == 'ana':
                    giren = emir_giren_map.get(em['EmirNo'])
                    if giren and giren > 0:
                        em['EmirMiktari'] = giren  # gercek emir miktari
                    # else: ana emirde hareket yok -> SiparisMiktari fallback olarak EmirMiktari kalsin'''


# =====================================================================
# 2) FRONTEND: siparis ozet panel (sb3Info)
# =====================================================================

# Mevcut sb3Info atamasi:
JS_OLD_INFO = """            document.getElementById('sb3Info').textContent =
                'Sipariş ' + sipno + ' — ' +
                (r.data.ana_sayisi || 0) + ' ana / ' +
                (r.data.alt_sayisi || 0) + ' alt = ' +
                (r.data.emir_sayisi || _state.emirler.length) + ' emir';"""

JS_NEW_INFO = """            // === FAZ 4.6 B3 polish ===
            var _toplamCift = 0;
            _state.emirler.forEach(function (e) {
                var m = (e.EmirMiktari != null ? e.EmirMiktari
                    : e.HedefMiktar != null ? e.HedefMiktar
                    : 0);
                _toplamCift += Number(m) || 0;
            });
            var _anaSayi = r.data.ana_sayisi || 0;
            var _altSayi = r.data.alt_sayisi || 0;
            var _emirSayi = r.data.emir_sayisi || _state.emirler.length;
            document.getElementById('sb3Info').innerHTML =
                '<strong>Sipariş ' + sipno + '</strong> &nbsp;•&nbsp; ' +
                '<span style=\"color:#16a34a;font-weight:600;\">' + _emirSayi + ' emir</span> ' +
                '(<span style=\"color:#15803d;\">' + _anaSayi + ' ana</span> / ' +
                '<span style=\"color:#1e40af;\">' + _altSayi + ' alt</span>) ' +
                '&nbsp;•&nbsp; ' +
                '<span style=\"color:#7c3aed;font-weight:600;\">Toplam: ' +
                _toplamCift.toLocaleString('tr-TR') + ' çift</span>';"""


# =====================================================================
# Helpers
# =====================================================================

def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_korgun():
    print()
    print("=" * 64)
    print("1/2 KORGUN: ana emir SUM(Giren) + RKOD<100 filtre")
    print("=" * 64)
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} yok.")
        return False

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER in src:
        print("  [BILGI] Polish zaten ekli.")
        return True

    if KORGUN_OLD_ANA not in src:
        print("  [HATA] KORGUN_OLD_ANA bulunamadi.")
        return False
    if src.count(KORGUN_OLD_ANA) > 1:
        print("  [HATA] KORGUN_OLD_ANA cogul.")
        return False
    if KORGUN_OLD_BATCH not in src:
        print("  [HATA] KORGUN_OLD_BATCH bulunamadi.")
        return False
    if src.count(KORGUN_OLD_BATCH) > 1:
        print("  [HATA] KORGUN_OLD_BATCH cogul.")
        return False

    new_src = src.replace(KORGUN_OLD_ANA, KORGUN_NEW_ANA, 1)
    new_src = new_src.replace(KORGUN_OLD_BATCH, KORGUN_NEW_BATCH, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Ana emir SUM(Giren) override + RKOD<100 filtre.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: siparis ozet panel")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] JS polish zaten ekli.")
        return True

    if JS_OLD_INFO not in src:
        print("  [HATA] JS_OLD_INFO bulunamadi.")
        return False
    if src.count(JS_OLD_INFO) > 1:
        print("  [HATA] JS_OLD_INFO cogul.")
        return False

    new_src = src.replace(JS_OLD_INFO, JS_NEW_INFO, 1)
    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Siparis ozet panel guncellendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 POLISH")
    print("=" * 64)
    print("CPS_KURALLAR uyum:")
    print("  ✓ Korgun read-only")
    print("  ✓ Mevcut akis bozulmuyor")

    ok1 = patch_korgun()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  Ust panel:")
        print("    Siparis 33558 • 55 emir (30 ana / 25 alt) • Toplam: 26.400 çift")
        print()
        print("  ANA emirler:")
        print("    109772 -> EMIR CIFT ADET = 480 (eskiden 7000 idi)")
        print("    Tum ana emirler kendi SUM(Giren) miktarini gosterir")
        print()
        print("  RKOD:")
        print("    Sadece kucuk sayilar (1, 4, 7) - 2413 ve benzerleri gitti")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
