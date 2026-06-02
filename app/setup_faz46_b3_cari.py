# -*- coding: utf-8 -*-
"""
setup_faz46_b3_cari_kolonu.py
-----------------------------
B3'e CARI (musteri) kolonu ekler.

Yapilan:
  1) modules/common/korgun.py
     get_siparis_emirleri() icindeki ana emirler SQL'ine
     Siparis_Kay -> Cari_Kart JOIN ekle, CariAdi alani doner.
     Alt (yari mamul) emirler ana emirin cari_adi'sini paylasir
     (parent emirden cari_adi'ni eslet).

  2) static/js/hedef.js
     B3 tablosuna CARI kolonu ekle (MODEL/URUN'den sonra,
     EMIR CIFT ADET'ten once). Uzun isim ellipsis + title.
     Kolon sirasi: SEC | EMIR | TIP | MODEL | CARI | HEDEF | PROSES | LOKASYON | UYGULA

DOKUNMAZ:
  - uretim_kaydet
  - PLAN/RAPOR/ONAYLAR/GECMIS
  - Diger Korgun fonksiyonlari (get_emir_ozet vs.)
  - Sablon liste UI (B2)
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

KORGUN_MARKER = "# === FAZ 4.6 B3 cari ekli ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 cari kolonu"


# =====================================================================
# 1) KORGUN: get_siparis_emirleri SQL guncelle
# =====================================================================
# Mevcut ana emirler SQL'ini Cari_Kart JOIN ile genislet
# Mevcut yari mamul SQL'ini de parent emir uzerinden cari_adi tasi

KORGUN_OLD_ANA = '''            # 1) Ana emirler (Tip='M')
            cur.execute("""
                SELECT DISTINCT
                    e.EmirNo, e.ModelKod, e.Tip,
                    ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                    e.Location,
                    LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                    e.YazSay,
                    sh.SipNo,
                    sh.Miktar AS HedefMiktar
                FROM Siparis_Har sh
                INNER JOIN Urt_Emir e ON e.ModelKod = sh.SKOD
                LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                WHERE sh.SipNo = %s
                  AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                  AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'M'
                ORDER BY e.EmirNo
            """, (sip_no_int,))'''

KORGUN_NEW_ANA = '''            # 1) Ana emirler (Tip='M') -- FAZ 4.6 B3: Cari_Kart JOIN ile CariAdi
            cur.execute("""
                SELECT DISTINCT
                    e.EmirNo, e.ModelKod, e.Tip,
                    ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                    e.Location,
                    LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                    e.YazSay,
                    sh.SipNo,
                    sh.Miktar AS HedefMiktar,
                    ISNULL(ck.CName, '-') AS CariAdi
                FROM Siparis_Har sh
                INNER JOIN Urt_Emir e ON e.ModelKod = sh.SKOD
                LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                WHERE sh.SipNo = %s
                  AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                  AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'M'
                ORDER BY e.EmirNo
            """, (sip_no_int,))'''

# Ana emirler dict olusumunda CariAdi'yi de ekle
KORGUN_OLD_ANA_DICT = '''            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                emirler.append({
                    'EmirNo': int(d['EmirNo']),
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': float(hm) if hm is not None else None,
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                })'''

KORGUN_NEW_ANA_DICT = '''            # parent_cari_map: yari mamul emirler ana emir cari_adi'sini paylassin
            parent_cari_map = {}
            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                ca = d.get('CariAdi')
                if ca == '-' or not ca:
                    ca = None
                parent_cari_map[int(d['EmirNo'])] = ca
                emirler.append({
                    'EmirNo': int(d['EmirNo']),
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': float(hm) if hm is not None else None,
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                    'CariAdi': ca,
                })  # === FAZ 4.6 B3 cari ekli ==='''

# Yari mamul emirler dict olusumunda parent_cari_map'ten cari_adi cek
KORGUN_OLD_ALT_DICT = '''            for d in yari_dicts:
                emirler.append({
                    'EmirNo': int(d['EmirNo']),
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': None,
                    'SipNo': sip_no_int,
                    'ParentEmirNo': int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None,
                })'''

KORGUN_NEW_ALT_DICT = '''            for d in yari_dicts:
                parent_no = int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None
                ca_alt = parent_cari_map.get(parent_no) if parent_no else None
                emirler.append({
                    'EmirNo': int(d['EmirNo']),
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': None,
                    'SipNo': sip_no_int,
                    'ParentEmirNo': parent_no,
                    'CariAdi': ca_alt,
                })'''


# =====================================================================
# 2) FRONTEND: tabloya CARI kolonu ekle
# =====================================================================

JS_OLD_THEAD = """            p.push('<table class=\"sb3-table\"><thead><tr>',
                '<th style=\"width:32px;\"><input type=\"checkbox\" data-grupchk=\"' + grupKey + '\"></th>',
                '<th>EMİR</th>',
                '<th>TİP</th>',
                '<th>MODEL</th>',
                '<th class=\"num\" style=\"width:100px;\">HEDEF</th>',
                '<th class=\"num\" style=\"width:90px;\">PROSES</th>',
                '<th>LOKASYON</th>',
                '<th class=\"aks\" style=\"width:280px;\">ŞABLON UYGULA</th>',
                '</tr></thead><tbody>');"""

JS_NEW_THEAD = """            p.push('<table class=\"sb3-table\"><thead><tr>',
                '<th style=\"width:32px;\"><input type=\"checkbox\" data-grupchk=\"' + grupKey + '\"></th>',
                '<th>EMİR</th>',
                '<th>TİP</th>',
                '<th>MODEL / ÜRÜN</th>',
                '<th style=\"max-width:160px;\">CARİ</th>',
                '<th class=\"num\" style=\"width:100px;\">HEDEF</th>',
                '<th class=\"num\" style=\"width:90px;\">PROSES</th>',
                '<th>LOKASYON</th>',
                '<th class=\"aks\" style=\"width:280px;\">ŞABLON UYGULA</th>',
                '</tr></thead><tbody>');"""

JS_OLD_TBODY = """                p.push('<tr data-emir=\"' + _esc(e.EmirNo) + '\">',
                    '<td><input type=\"checkbox\" class=\"emir-chk\" data-emir=\"' + _esc(e.EmirNo) + '\" data-grup=\"' + grupKey + '\"></td>',
                    '<td><strong>' + _esc(e.EmirNo) + '</strong>' +
                        (e.ParentEmirNo ? '<br><small style=\"color:var(--text3);\">parent: ' + _esc(e.ParentEmirNo) + '</small>' : '') +
                        '</td>',
                    '<td class=\"tip-rozet\">' + rozet + '</td>',
                    '<td>' + _esc(modelText) + '</td>',
                    '<td class=\"num\">' + hedef + '</td>',
                    '<td class=\"num\">' + _esc(prsTxt) + '</td>',
                    '<td>' + _esc(e.Location || '-') + '</td>',"""

JS_NEW_TBODY = """                var cariFull = e.CariAdi || '';
                var cariKisa = cariFull;
                if (cariKisa.length > 22) cariKisa = cariKisa.substring(0, 22) + '...';
                p.push('<tr data-emir=\"' + _esc(e.EmirNo) + '\">',
                    '<td><input type=\"checkbox\" class=\"emir-chk\" data-emir=\"' + _esc(e.EmirNo) + '\" data-grup=\"' + grupKey + '\"></td>',
                    '<td><strong>' + _esc(e.EmirNo) + '</strong>' +
                        (e.ParentEmirNo ? '<br><small style=\"color:var(--text3);\">parent: ' + _esc(e.ParentEmirNo) + '</small>' : '') +
                        '</td>',
                    '<td class=\"tip-rozet\">' + rozet + '</td>',
                    '<td>' + _esc(modelText) + '</td>',
                    '<td class=\"sb3-cari\" title=\"' + _esc(cariFull || '-') + '\">' + _esc(cariKisa || '-') + '</td>',
                    '<td class=\"num\">' + hedef + '</td>',
                    '<td class=\"num\">' + _esc(prsTxt) + '</td>',
                    '<td>' + _esc(e.Location || '-') + '</td>',"""

# CSS sb3-cari ekle
CSS_OLD = """'#sb3Panel table.sb3-table td.tip-rozet span { display:inline-block; padding:2px 6px; border-radius:8px; font-size:9px; font-weight:700; letter-spacing:0.4px; }',"""

CSS_NEW = """'#sb3Panel table.sb3-table td.tip-rozet span { display:inline-block; padding:2px 6px; border-radius:8px; font-size:9px; font-weight:700; letter-spacing:0.4px; }',
            '#sb3Panel table.sb3-table td.sb3-cari { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text2); font-size:11px; }',"""


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
    print("1/2 KORGUN: modules/common/korgun.py")
    print("=" * 64)
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} bulunamadi.")
        return False

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER in src:
        print("  [BILGI] Korgun cari ekli zaten.")
        return True

    # 3 replacement
    if KORGUN_OLD_ANA not in src:
        print("  [HATA] KORGUN_OLD_ANA bulunamadi.")
        return False
    if src.count(KORGUN_OLD_ANA) > 1:
        print("  [HATA] KORGUN_OLD_ANA cogul.")
        return False
    if KORGUN_OLD_ANA_DICT not in src:
        print("  [HATA] KORGUN_OLD_ANA_DICT bulunamadi.")
        return False
    if src.count(KORGUN_OLD_ANA_DICT) > 1:
        print("  [HATA] KORGUN_OLD_ANA_DICT cogul.")
        return False
    if KORGUN_OLD_ALT_DICT not in src:
        print("  [HATA] KORGUN_OLD_ALT_DICT bulunamadi.")
        return False
    if src.count(KORGUN_OLD_ALT_DICT) > 1:
        print("  [HATA] KORGUN_OLD_ALT_DICT cogul.")
        return False

    new_src = src.replace(KORGUN_OLD_ANA, KORGUN_NEW_ANA, 1)
    new_src = new_src.replace(KORGUN_OLD_ANA_DICT, KORGUN_NEW_ANA_DICT, 1)
    new_src = new_src.replace(KORGUN_OLD_ALT_DICT, KORGUN_NEW_ALT_DICT, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Korgun: Cari_Kart JOIN + parent_cari_map eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] JS cari kolonu zaten ekli.")
        return True

    # 3 replacement
    if JS_OLD_THEAD not in src:
        print("  [HATA] JS_OLD_THEAD bulunamadi.")
        return False
    if src.count(JS_OLD_THEAD) > 1:
        print("  [HATA] JS_OLD_THEAD cogul.")
        return False
    if JS_OLD_TBODY not in src:
        print("  [HATA] JS_OLD_TBODY bulunamadi.")
        return False
    if src.count(JS_OLD_TBODY) > 1:
        print("  [HATA] JS_OLD_TBODY cogul.")
        return False
    if CSS_OLD not in src:
        print("  [HATA] CSS_OLD bulunamadi.")
        return False
    if src.count(CSS_OLD) > 1:
        print("  [HATA] CSS_OLD cogul.")
        return False

    new_src = src.replace(JS_OLD_THEAD, JS_NEW_THEAD, 1)
    new_src = new_src.replace(JS_OLD_TBODY, JS_NEW_TBODY, 1)
    new_src = new_src.replace(CSS_OLD, CSS_NEW, 1)

    # Marker ekleme - dosya sonuna kucuk yorum
    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] CARI kolonu eklendi (MODEL'den sonra).")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - CARI (musteri) kolonu ekle")
    print("=" * 64)
    print("CPS_KURALLAR:")
    print("  ✓ Korgun read-only (sadece SELECT genisletilir)")
    print("  ✓ CPS yazma yok")
    print("  ✓ Mevcut akis bozulmaz")

    ok1 = patch_korgun()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat (Korgun degisikligi icin)")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON -> Siparis No: 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  - Tabloda yeni CARI kolonu (MODEL'den sonra)")
        print("  - Ana emirler: cari_adi (Lc Waikiki vs.)")
        print("  - Alt emirler: parent emirin cari_adi'si (paylasiyor)")
        print("  - Uzun isim ellipsis (...), hover'da tam adi tooltip")
        print()
        print("Test:")
        print("  fetch('/hedef/siparis/emirler?sipno=33558',{credentials:'include'})")
        print("    .then(r=>r.json()).then(d=>console.log(d.emirler[0]))")
        print("  // Beklenen: CariAdi alani var")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
