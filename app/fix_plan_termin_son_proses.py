# -*- coding: utf-8 -*-
"""
fix_plan_termin_son_proses.py
-----------------------------
PLAN'a 2 yeni alan:
  - termin = ozet.get('termin_tarihi')  (get_emir_ozet zaten donuyor)
  - son_proses = batch SQL Urt_con_gch + Proses_M JOIN

Kurallar:
  - Sadece routes.py
  - Musteri alanini bozma (PLAN_MUSTERI_TEK_SATIR korunur)
  - Frontend dokunulmaz
  - DB dokunulmaz
  - Yeni endpoint yok
  - Hata olursa eski yanit doner (try/except)

Test edilen: 110626 -> termin=2023-11-10, son_proses=Kesim
"""
import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")

MARKER = "# === PLAN_TERMIN_PROSES_V1 ==="

# ===========================================================
# A) Mevcut musteri patch'inin oldugu blogu rahatla:
#    'musteri' satirinin yanina 'termin' ekle
# ===========================================================

ESKI = """        # === PLAN_MUSTERI_TEK_SATIR ===
        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'musteri': (ozet.get('cari_adi') if ok else None),
            'siparisler': siparisler_str,
            'hedef': hedef,
            'korgun_yapilan': korgun_yapilan,
            'cps_yapilan': cps_onayli,
            'cps_bekleyen': cps_bekleyen,
            'yapilan': toplam_yapilan,
            'kalan': kalan,
            'yuzde': yuzde,
        })"""

YENI = """        # === PLAN_MUSTERI_TEK_SATIR ===
        # === PLAN_TERMIN_PROSES_V1 ===
        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'musteri': (ozet.get('cari_adi') if ok else None),
            'termin': (ozet.get('termin_tarihi') if ok else None),
            'son_proses': None,  # asagidaki batch SQL ile doldurulur
            'siparisler': siparisler_str,
            'hedef': hedef,
            'korgun_yapilan': korgun_yapilan,
            'cps_yapilan': cps_onayli,
            'cps_bekleyen': cps_bekleyen,
            'yapilan': toplam_yapilan,
            'kalan': kalan,
            'yuzde': yuzde,
        })"""


# ===========================================================
# B) sort'tan ONCE batch SQL ekle (son_proses doldur)
# ===========================================================

ESKI_SORT = """    # En yeni emir ustte (emir_no buyukten kucuge)
    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)"""

YENI_SORT = """    # === PLAN_TERMIN_PROSES_V1 ===
    # Son proses icin TEK batch SQL (Urt_con_gch + Proses_M JOIN)
    # Hata olursa eski yanit doner (try/except).
    try:
        if sonuc:
            from modules.common import korgun as _kk_sp
            _emir_listesi = []
            for _x in sonuc:
                try:
                    _emir_listesi.append(int(_x['emir_no']))
                except Exception:
                    pass
            if _emir_listesi:
                _con = _kk_sp._baglan()
                try:
                    _cur = _con.cursor()
                    _ph = ','.join(['%s'] * len(_emir_listesi))
                    # Her emir icin en son EndTarih'li proses (Cikan>0)
                    _cur.execute(f\"\"\"
                        SELECT t.EmirNo, t.Proses, t.EndTarih, pm.Tanim
                          FROM (
                            SELECT EmirNo, Proses, EndTarih,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY EmirNo
                                       ORDER BY EndTarih DESC
                                   ) AS rn
                              FROM Urt_con_gch WITH(NOLOCK)
                             WHERE EmirNo IN ({_ph})
                               AND Cikan > 0
                          ) AS t
                          LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = t.Proses
                         WHERE t.rn = 1
                    \"\"\", tuple(_emir_listesi))
                    _proses_map = {}
                    for _r in _cur.fetchall():
                        _emirno_str = str(int(_r[0]))
                        _kod = _r[1]
                        _adi = _r[3]
                        # Tanim varsa Tanim, yoksa kod
                        _proses_map[_emirno_str] = _adi if _adi else _kod
                    _cur.close()
                finally:
                    _con.close()
                # sonuc listesine yaz
                for _x in sonuc:
                    _key = str(_x.get('emir_no'))
                    if _key in _proses_map:
                        _x['son_proses'] = _proses_map[_key]
    except Exception as _e:
        try:
            print(f'[PLAN_TERMIN_PROSES_V1 hata, son_proses bos]: {_e}')
        except Exception:
            pass

    # En yeni emir ustte (emir_no buyukten kucuge)
    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)"""


def main():
    if not os.path.exists(HEDEF_ROUTES):
        print(f"[HATA] {HEDEF_ROUTES} yok.")
        return 1

    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()

    if MARKER in src:
        print("[BILGI] PLAN_TERMIN_PROSES_V1 zaten ekli.")
        return 0

    if ESKI not in src:
        print("[HATA] PLAN_MUSTERI_TEK_SATIR bloku bulunamadi.")
        print("       Musteri patch'i once uygulanmis olmali.")
        return 1
    if src.count(ESKI) > 1:
        print("[HATA] Musteri bloku cogul.")
        return 1
    if ESKI_SORT not in src:
        print("[HATA] sort satiri bulunamadi.")
        return 1
    if src.count(ESKI_SORT) > 1:
        print("[HATA] sort cogul.")
        return 1

    new_src = src.replace(ESKI, YENI, 1)
    new_src = new_src.replace(ESKI_SORT, YENI_SORT, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"[HATA] parse: {e}")
        return 1

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = HEDEF_ROUTES + f'.bak_{ts}'
    shutil.copy2(HEDEF_ROUTES, bp)
    print(f"[OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("[OK] termin + son_proses batch eklendi.")
    print()
    print("YAPILACAK:")
    print("  Flask debug mode otomatik restart yapar.")
    print("  Tarayicida Ctrl+F5.")
    print()
    print("BEKLENEN PLAN:")
    print("  Musteri:    Lc Waikiki")
    print("  Termin:     2023-11-10 (Urt_Emir.TerTarih)")
    print("  Son Proses: Kesim")
    print()
    print("TEST (Console):")
    print("  fetch('/hedef/plan',{credentials:'include'})")
    print("    .then(r=>r.json())")
    print("    .then(d=>console.log({m:d.emirler[0].musteri, t:d.emirler[0].termin, sp:d.emirler[0].son_proses}))")
    print()
    print("ROLLBACK:")
    print(f'  copy "{bp}" "{HEDEF_ROUTES}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
