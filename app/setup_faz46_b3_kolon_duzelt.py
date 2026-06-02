# -*- coding: utf-8 -*-
"""
setup_faz46_b3_kolon_duzelt.py
------------------------------
B3 kolon adi duzeltme:
  - Frontend baslik: HEDEF -> EMIR CIFT ADET
  - Backend: HedefMiktar yaninda EmirMiktari alani da donusun (geri uyumlu)
  - Veri akisi degismez, sadece etiket dogrulanir.

CPS_KURALLAR:
  ✓ Korgun read-only
  ✓ Mevcut sablon uygulama akisi bozulmuyor
  ✓ JSON yapisi geri uyumlu (HedefMiktar hala donuyor)
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

KORGUN_MARKER = "# === FAZ 4.6 B3 EmirMiktari alias ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 kolon-duzelt"


# =====================================================================
# 1) BACKEND: ana emirler dict'ine EmirMiktari alias ekle
# =====================================================================
KORGUN_OLD = """            for d in ana_dicts:
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
                })  # === FAZ 4.6 B3 cari ekli ==="""

KORGUN_NEW = """            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                hm_f = float(hm) if hm is not None else None
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
                    # NOT: HedefMiktar terim olarak yaniltici, ama Siparis_Har.Miktar = emir cift adetidir
                    'HedefMiktar': hm_f,
                    'EmirMiktari': hm_f,  # === FAZ 4.6 B3 EmirMiktari alias ===
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                    'CariAdi': ca,
                })"""


# =====================================================================
# 2) FRONTEND: kolon basligi ve veri bind
# =====================================================================

# Baslik degistir
JS_OLD_TH = "'<th class=\"num\" style=\"width:100px;\">HEDEF</th>',"
JS_NEW_TH = "'<th class=\"num\" style=\"width:120px;\">EMİR ÇİFT ADET</th>',"

# Veri bind: e.HedefMiktar -> e.EmirMiktari (HedefMiktar fallback)
JS_OLD_BIND = """                var hedef = (e.HedefMiktar != null) ? _fmt(e.HedefMiktar) : '-';"""
JS_NEW_BIND = """                var _miktar = (e.EmirMiktari != null) ? e.EmirMiktari
                    : (e.HedefMiktar != null ? e.HedefMiktar : null);
                var hedef = (_miktar != null) ? _fmt(_miktar) : '-';"""

# JS marker'i panel HTML'inden baska bir yere koymak icin (idempotency)
# Yorum satiri olarak panelin h3'unun yanina koyacagiz - basit: yorum ekle


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
    print("1/2 KORGUN: EmirMiktari alias ekle")
    print("=" * 64)
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} bulunamadi.")
        return False

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER in src:
        print("  [BILGI] EmirMiktari alias zaten var.")
        return True

    if KORGUN_OLD not in src:
        print("  [HATA] KORGUN_OLD bulunamadi (B3 cari patch'i uygulanmamis olabilir).")
        return False
    if src.count(KORGUN_OLD) > 1:
        print("  [HATA] Birden fazla esleme.")
        return False

    new_src = src.replace(KORGUN_OLD, KORGUN_NEW, 1)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] EmirMiktari alani eklendi (HedefMiktar geri uyumlu).")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: kolon basligi + veri bind")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] JS kolon-duzelt zaten ekli.")
        return True

    # Replacements
    if JS_OLD_TH not in src:
        print("  [HATA] JS_OLD_TH bulunamadi.")
        return False
    if src.count(JS_OLD_TH) > 1:
        print("  [HATA] JS_OLD_TH cogul.")
        return False
    if JS_OLD_BIND not in src:
        print("  [HATA] JS_OLD_BIND bulunamadi.")
        return False
    if src.count(JS_OLD_BIND) > 1:
        print("  [HATA] JS_OLD_BIND cogul.")
        return False

    new_src = src.replace(JS_OLD_TH, JS_NEW_TH, 1)
    new_src = new_src.replace(JS_OLD_BIND, JS_NEW_BIND, 1)
    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Kolon: 'HEDEF' -> 'EMIR CIFT ADET'")
    print("  [OK] Veri bind: e.EmirMiktari oncelikli, e.HedefMiktar fallback")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 KOLON DUZELTME")
    print("=" * 64)

    ok1 = patch_korgun()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat (Korgun degisikligi)")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON -> Siparis No 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  - Kolon basligi: 'EMİR ÇİFT ADET' (HEDEF degil)")
        print("  - Deger: 7.000 (dogru, ayni veri)")
        print()
        print("JSON test:")
        print("  fetch('/hedef/siparis/emirler?sipno=33558',{credentials:'include'})")
        print("    .then(r=>r.json()).then(d=>console.log(d.emirler[0]))")
        print("  // Beklenen: hem EmirMiktari hem HedefMiktar alani var")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
