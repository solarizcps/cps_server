# -*- coding: utf-8 -*-
"""
setup_faz46_b3_hizalama.py
--------------------------
B3 final UI/data align fix:
  - Tablo class adi: 'sb3-table' -> 'sablon-emir-table' eklenir (hem eski hem yeni class)
  - Her th/td'ye col-* class ekle
  - CSS: width, text-align, ellipsis, vertical-align
  - Veri bind alias zinciri: EmirMiktari || HedefMiktar || miktar || 0
  - PROSES kolonu da text-align center, sayi olarak
  - Mevcut akis bozulmaz

Idempotent.
"""

import os
import shutil
import datetime
import sys

CPS_ROOT = r"C:\cps_dev"
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 hizalama-final"


# =====================================================================
# REPLACEMENT 1: thead — tum th'lere col-* class ekle, ekstra class ile
# =====================================================================
JS_OLD_THEAD = """            p.push('<table class=\"sb3-table\"><thead><tr>',
                '<th style=\"width:32px;\"><input type=\"checkbox\" data-grupchk=\"' + grupKey + '\"></th>',
                '<th>EMİR</th>',
                '<th>TİP</th>',
                '<th>MODEL / ÜRÜN</th>',
                '<th style=\"max-width:160px;\">CARİ</th>',
                '<th class=\"num\" style=\"width:120px;\">EMİR ÇİFT ADET</th>',
                '<th class=\"num\" style=\"width:90px;\">PROSES</th>',
                '<th>LOKASYON</th>',
                '<th class=\"aks\" style=\"width:280px;\">ŞABLON UYGULA</th>',
                '</tr></thead><tbody>');"""

JS_NEW_THEAD = """            p.push('<table class=\"sb3-table sablon-emir-table\"><thead><tr>',
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


# =====================================================================
# REPLACEMENT 2: tbody — col-* class ekle, alias zinciri
# =====================================================================
JS_OLD_TBODY = """                var _miktar = (e.EmirMiktari != null) ? e.EmirMiktari
                    : (e.HedefMiktar != null ? e.HedefMiktar : null);
                var hedef = (_miktar != null) ? _fmt(_miktar) : '-';"""

JS_NEW_TBODY = """                var _miktar = (e.EmirMiktari != null ? e.EmirMiktari
                    : e.HedefMiktar != null ? e.HedefMiktar
                    : e.emir_cift_adet != null ? e.emir_cift_adet
                    : e.miktar != null ? e.miktar
                    : null);
                var hedef = (_miktar != null) ? _fmt(_miktar) : '-';"""


JS_OLD_ROW = """                var cariFull = e.CariAdi || '';
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

JS_NEW_ROW = """                var cariFull = e.CariAdi || '';
                p.push('<tr data-emir=\"' + _esc(e.EmirNo) + '\">',
                    '<td class=\"col-check\"><input type=\"checkbox\" class=\"emir-chk\" data-emir=\"' + _esc(e.EmirNo) + '\" data-grup=\"' + grupKey + '\"></td>',
                    '<td class=\"col-emir\"><strong>' + _esc(e.EmirNo) + '</strong>' +
                        (e.ParentEmirNo ? '<br><small style=\"color:var(--text3); font-weight:400;\">parent: ' + _esc(e.ParentEmirNo) + '</small>' : '') +
                        '</td>',
                    '<td class=\"col-tip tip-rozet\">' + rozet + '</td>',
                    '<td class=\"col-model\" title=\"' + _esc(e.ModelAdi || e.ModelKod || '') + '\">' + _esc(modelText) + '</td>',
                    '<td class=\"col-cari\" title=\"' + _esc(cariFull || '-') + '\">' + _esc(cariFull || '-') + '</td>',
                    '<td class=\"col-adet num\">' + hedef + '</td>',
                    '<td class=\"col-proses num\">' + _esc(prsTxt) + '</td>',
                    '<td class=\"col-lokasyon\">' + _esc(e.Location || '-') + '</td>',"""


# =====================================================================
# REPLACEMENT 3: aksiyon kolonu td class
# =====================================================================
JS_OLD_AKS = """                    '<td class=\"aks\">',
                    '<div class=\"sb3-row-sablon\">',"""

JS_NEW_AKS = """                    '<td class=\"col-aksiyon aks\">',
                    '<div class=\"sb3-row-sablon\">',"""


# =====================================================================
# REPLACEMENT 4: CSS — col-* width/align kurallari ekle
# =====================================================================
CSS_OLD = """'#sb3Panel table.sb3-table td.sb3-cari { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text2); font-size:11px; }',"""

CSS_NEW = """'#sb3Panel table.sb3-table td.sb3-cari { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text2); font-size:11px; }',
            '#sb3Panel table.sablon-emir-table { table-layout:fixed; }',
            '#sb3Panel table.sablon-emir-table th, #sb3Panel table.sablon-emir-table td { vertical-align:middle; white-space:nowrap; }',
            '#sb3Panel table.sablon-emir-table .num { text-align:right; font-variant-numeric:tabular-nums; }',
            '#sb3Panel table.sablon-emir-table .col-check { width:36px; text-align:center; }',
            '#sb3Panel table.sablon-emir-table .col-emir { width:90px; font-weight:700; }',
            '#sb3Panel table.sablon-emir-table .col-tip { width:80px; }',
            '#sb3Panel table.sablon-emir-table .col-model { min-width:300px; max-width:460px; overflow:hidden; text-overflow:ellipsis; }',
            '#sb3Panel table.sablon-emir-table .col-cari { width:140px; max-width:160px; overflow:hidden; text-overflow:ellipsis; color:var(--text2); font-size:11px; }',
            '#sb3Panel table.sablon-emir-table .col-adet { width:130px; padding-right:14px; }',
            '#sb3Panel table.sablon-emir-table .col-proses { width:120px; text-align:center; }',
            '#sb3Panel table.sablon-emir-table .col-lokasyon { width:90px; }',
            '#sb3Panel table.sablon-emir-table .col-aksiyon { width:260px; }',"""


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 HIZALAMA FINAL FIX")
    print("=" * 64)

    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return 1

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] Hizalama-final zaten ekli.")
        return 0

    # Replacements
    replacements = [
        ("JS_OLD_THEAD", JS_OLD_THEAD, JS_NEW_THEAD),
        ("JS_OLD_TBODY", JS_OLD_TBODY, JS_NEW_TBODY),
        ("JS_OLD_ROW", JS_OLD_ROW, JS_NEW_ROW),
        ("JS_OLD_AKS", JS_OLD_AKS, JS_NEW_AKS),
        ("CSS_OLD", CSS_OLD, CSS_NEW),
    ]

    new_src = src
    for ad, old, new in replacements:
        if old not in new_src:
            print(f"  [HATA] {ad} bulunamadi.")
            return 1
        if new_src.count(old) > 1:
            print(f"  [HATA] {ad} cogul ({new_src.count(old)}).")
            return 1
        new_src = new_src.replace(old, new, 1)
        print(f"  [OK] {ad} replace edildi.")

    new_src += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print()
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] B3 tablo hizalamasi tamamlandi.")
    print()
    print("YAPILACAK:")
    print("  1) Browser'da Ctrl+F5 (sunucu restart gerekmez)")
    print("  2) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
    print()
    print("Beklenen:")
    print("  - Kolonlar duzgun hizali, EMIR CIFT ADET sutunu basligin altinda")
    print("  - MEVCUT PROSES kolonu ortali (su an 0, sablon uygulanmamis)")
    print("  - CARI kolonu (Lc Waikiki) ellipsis ile, hover'da tam ad")
    print("  - MODEL hover'da tam isim")
    print()
    print("Test akisi:")
    print("  1. 109772 satirinda 'Atki LCW' sec, 'Uygula' tikla")
    print("  2. Toast: 'Sablon uygulandi: 4 proses eklendi'")
    print("  3. Tablo otomatik yenilenir, MEVCUT PROSES = 4 olur")
    print("  4. Ayni satirda tekrar 'Uygula' -> '0 eklendi, 4 zaten vardi'")
    return 0


if __name__ == '__main__':
    sys.exit(main())
