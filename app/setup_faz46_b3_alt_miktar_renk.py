# -*- coding: utf-8 -*-
"""
setup_faz46_b3_alt_miktar_renk.py
---------------------------------
B3 - Alt emirler icin EmirMiktari + RKOD ekle.

Mantik:
  - Her alt emir Urt_Em_gch'den FisNo'larini ceker
  - En cok kayit sayan FisNo'yu (=SipNo) secer (GROUP BY COUNT DESC)
  - O SipNo'nun Siparis_Har.Miktar'i = EmirMiktari
  - Ayni FisNo'daki RKOD'lardan en cok kayit alani = RKOD
  - TOPLAMA YOK

Yapilan:
  1) modules/common/korgun.py: get_siparis_emirleri'da alt emir batch
     sorgusu eklenir
  2) static/js/hedef.js:
     - Tabloya RENK kolonu (CARI ile EMIR CIFT ADET arasina)
     - Alt emirlerde miktar artik gorunur
     - thead/tbody col-* class'lar guncel

CPS_KURALLAR:
  ✓ Korgun read-only (yalnizca SELECT)
  ✓ Sablon hedef uretmez (sadece bilgi gosterimi)
  ✓ uretim_kaydet/PLAN/RAPOR/ONAYLAR/GECMIS dokunulmaz
  ✓ Toplama yok - her emir tek siparise bagli gosterilir
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

KORGUN_MARKER = "# === FAZ 4.6 B3 alt emir miktar+renk ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 alt-miktar-renk"


# =====================================================================
# 1) BACKEND: alt emir dict olustugu yeri replace et
# =====================================================================

KORGUN_OLD = '''            for d in yari_dicts:
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

KORGUN_NEW = '''            # === FAZ 4.6 B3 alt emir miktar+renk ===
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


# Ayrica ana emirler icin de RKOD ekleyelim (Urt_Em_gch'den batch)
KORGUN_OLD_ANA = '''            # parent_cari_map: yari mamul emirler ana emir cari_adi'sini paylassin
            parent_cari_map = {}
            for d in ana_dicts:
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
                })'''

KORGUN_NEW_ANA = '''            # Ana emirler icin RKOD batch (Urt_Em_gch'den en cok kayit)
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


# =====================================================================
# 2) FRONTEND: tabloya RENK kolonu ekle
# =====================================================================

# THEAD: CARI'den sonra RENK ekle, kolon sayisi 9 -> 10
JS_OLD_THEAD = """            p.push('<table class=\"sb3-table sablon-emir-table\"><thead><tr>',
                '<th class=\"col-check\"><input type=\"checkbox\" data-grupchk=\"' + grupKey + '\"></th>',
                '<th class=\"col-emir\">EMİR</th>',
                '<th class=\"col-tip\">TİP</th>',
                '<th class=\"col-model\">MODEL / ÜRÜN</th>',
                '<th class=\"col-cari\">CARİ</th>',
                '<th class=\"col-adet num\">EMİR ÇİFT ADET</th>',
                '<th class=\"col-proses num\">MEVCUT PROSES</th>',
                '<th class=\"col-lokasyon\">LOKASYON</th>',
                '<th class=\"col-aksiyon aks\">ŞABLON UYGULA</th>',
                '</tr></thead><tbody>');"""

JS_NEW_THEAD = """            p.push('<table class=\"sb3-table sablon-emir-table\"><thead><tr>',
                '<th class=\"col-check\"><input type=\"checkbox\" data-grupchk=\"' + grupKey + '\"></th>',
                '<th class=\"col-emir\">EMİR</th>',
                '<th class=\"col-tip\">TİP</th>',
                '<th class=\"col-model\">MODEL / ÜRÜN</th>',
                '<th class=\"col-cari\">CARİ</th>',
                '<th class=\"col-renk\">RENK</th>',
                '<th class=\"col-adet num\">EMİR ÇİFT ADET</th>',
                '<th class=\"col-proses num\">MEVCUT PROSES</th>',
                '<th class=\"col-lokasyon\">LOKASYON</th>',
                '<th class=\"col-aksiyon aks\">ŞABLON UYGULA</th>',
                '</tr></thead><tbody>');"""


# TBODY: cari'den sonra renk td ekle
JS_OLD_ROW = """                    '<td class=\"col-cari\" title=\"' + _esc(cariFull || '-') + '\">' + _esc(cariFull || '-') + '</td>',
                    '<td class=\"col-adet num\">' + hedef + '</td>',"""

JS_NEW_ROW = """                    '<td class=\"col-cari\" title=\"' + _esc(cariFull || '-') + '\">' + _esc(cariFull || '-') + '</td>',
                    '<td class=\"col-renk\">' + (e.RKOD != null && e.RKOD !== '' ? '<span class=\"renk-rozet\">' + _esc(e.RKOD) + '</span>' : '-') + '</td>',
                    '<td class=\"col-adet num\">' + hedef + '</td>',"""


# CSS: col-renk + renk-rozet stili ekle
CSS_OLD = """'#sb3Panel table.sablon-emir-table .col-cari { width:140px; max-width:160px; overflow:hidden; text-overflow:ellipsis; color:var(--text2); font-size:11px; }',"""

CSS_NEW = """'#sb3Panel table.sablon-emir-table .col-cari { width:140px; max-width:160px; overflow:hidden; text-overflow:ellipsis; color:var(--text2); font-size:11px; }',
            '#sb3Panel table.sablon-emir-table .col-renk { width:64px; text-align:center; }',
            '#sb3Panel .renk-rozet { display:inline-block; min-width:28px; padding:2px 8px; border-radius:10px; background:#e0e7ff; color:#3730a3; font-weight:700; font-size:11px; font-family:var(--mono); }',"""


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
    print("1/2 KORGUN: alt emir miktar+renk + ana emir RKOD")
    print("=" * 64)
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} bulunamadi.")
        return False

    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()

    if KORGUN_MARKER in src:
        print("  [BILGI] Patch zaten ekli.")
        return True

    # Replace 1: alt emir bloku
    if KORGUN_OLD not in src:
        print("  [HATA] KORGUN_OLD (alt emir bloku) bulunamadi.")
        print("  Onceki B3 patch'leri uygulanmamis olabilir.")
        return False
    if src.count(KORGUN_OLD) > 1:
        print("  [HATA] KORGUN_OLD cogul.")
        return False

    new_src = src.replace(KORGUN_OLD, KORGUN_NEW, 1)

    # Replace 2: ana emir bloku
    if KORGUN_OLD_ANA not in new_src:
        print("  [HATA] KORGUN_OLD_ANA (ana emir bloku) bulunamadi.")
        return False
    if new_src.count(KORGUN_OLD_ANA) > 1:
        print("  [HATA] KORGUN_OLD_ANA cogul.")
        return False

    new_src = new_src.replace(KORGUN_OLD_ANA, KORGUN_NEW_ANA, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Alt emir miktar+RKOD batch + ana emir RKOD eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: tabloya RENK kolonu")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] JS RENK kolonu zaten ekli.")
        return True

    # Replace
    repls = [
        ("JS_OLD_THEAD", JS_OLD_THEAD, JS_NEW_THEAD),
        ("JS_OLD_ROW", JS_OLD_ROW, JS_NEW_ROW),
        ("CSS_OLD", CSS_OLD, CSS_NEW),
    ]
    new_src = src
    for ad, old, new in repls:
        if old not in new_src:
            print(f"  [HATA] {ad} bulunamadi.")
            return False
        if new_src.count(old) > 1:
            print(f"  [HATA] {ad} cogul.")
            return False
        new_src = new_src.replace(old, new, 1)
        print(f"  [OK] {ad}")
    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] RENK kolonu eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - Alt emir miktar + Renk")
    print("=" * 64)
    print("Mantik (TOPLAMA YOK):")
    print("  - Alt emir Urt_Em_gch'den en cok FisNo'lu kayit secilir")
    print("  - O FisNo (=SipNo)'in Siparis_Har.Miktar'i alinir (TEK siparis)")
    print("  - RKOD: en cok kayit alan renk kodu")

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
        print("  3) /hedef/ -> SABLON -> Siparis 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  - Tablo 10 kolon: SEC | EMIR | TIP | MODEL | CARI | RENK | EMIR CIFT ADET | PROSES | LOKASYON | UYGULA")
        print("  - ANA: ornek 7000 (degismedi)")
        print("  - ALT 109815: 7000 (en cok kayit FisNo'nun Siparis_Har miktari)")
        print("  - RENK: kucuk mavi rozet (orn '4', '1') veya '-' yoksa")
        print()
        print("JSON test:")
        print("  fetch('/hedef/siparis/emirler?sipno=33558',{credentials:'include'})")
        print("    .then(r=>r.json()).then(d=>console.log(d.emirler.find(e=>e.EmirNo===109815)))")
        print("  // Beklenen: EmirMiktari=7000, RKOD=4 (veya benzeri)")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
