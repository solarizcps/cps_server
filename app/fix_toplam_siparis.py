# -*- coding: utf-8 -*-
"""
fix_toplam_siparis.py
---------------------
Toplam = distinct sipariş Miktar TOPLAMI (her ana emir 30x sayilmasin).

Mevcut bug: 30 ana emir x 7000 = 210.000 (yanlis - her emir ayri siparis sayilmis)
Dogru: 33558(7000) + 33638(7000) = 14.000

Backend zaten siparis bilgisini donuyor (Siparis_Har 2 satir).
Frontend toplam hesabini distinct SipNo'ya gore yapsin.

Yani backend'den distinct SipNo+Miktar listesi gelmeli.
Bunun icin yeni endpoint ya da mevcut endpoint'e ek alan.

EN BASIT: backend get_siparis_emirleri zaten Siparis_Har'i tarayip
ana emirleri ureteti. Distinct siparis miktarini da donelim.
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

KORGUN_MARKER = "# === FAZ 4.6 toplam siparis fix ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 toplam siparis fix"


# =====================================================================
# 1) BACKEND: Siparis_Har'dan distinct SipNo+Miktar topla, return'e ekle
# =====================================================================

# get_siparis_emirleri'nin SON return blokuna 'siparis_miktari' alani ekle.
# Helper'in return blogu:
KORGUN_OLD = '''            cur.close()
            return {
                'ok': True,
                'siparis_no': str(sip_no_int),
                'emir_sayisi': len(emirler),
                'ana_sayisi': len(ana_dicts),
                'alt_sayisi': len(yari_dicts),
                'emirler': emirler,
            }'''

KORGUN_NEW = '''            # === FAZ 4.6 toplam siparis fix ===
            # Distinct siparis Miktar toplami (asil siparis adedi)
            siparis_kalemleri = []
            siparis_toplam = 0.0
            try:
                cur.execute("""
                    SELECT sh.SipNo, sh.SKOD, sh.Miktar
                      FROM Siparis_Har sh
                     WHERE sh.SipNo = %s
                       AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                """, (sip_no_int,))
                for r in cur.fetchall():
                    miktar = float(r[2] or 0)
                    siparis_toplam += miktar
                    siparis_kalemleri.append({
                        'SipNo': int(r[0]) if r[0] is not None else None,
                        'SKOD': r[1],
                        'Miktar': miktar
                    })
            except Exception:
                pass

            cur.close()
            return {
                'ok': True,
                'siparis_no': str(sip_no_int),
                'emir_sayisi': len(emirler),
                'ana_sayisi': len(ana_dicts),
                'alt_sayisi': len(yari_dicts),
                'siparis_toplam': siparis_toplam,
                'siparis_kalemleri': siparis_kalemleri,
                'emirler': emirler,
            }'''


# =====================================================================
# 2) FRONTEND: _ozetGuncelle toplam hesabini siparis_toplam'a gore yap
# =====================================================================

JS_OLD = """    function _ozetGuncelle() {
        var box = document.getElementById('sb3Info');
        if (!box) return;
        var toplam = 0;
        (_state.emirler || []).forEach(function (e) {
            var m = (e.EmirMiktari != null ? e.EmirMiktari
                : e.HedefMiktar != null ? e.HedefMiktar
                : 0);
            toplam += Number(m) || 0;
        });
        box.innerHTML =
            '<strong>Sipariş ' + (_state.sipnoSon || '') + '</strong> &nbsp;•&nbsp; ' +
            '<span style=\"color:#16a34a;font-weight:600;\">' + (_state.emirSayi || 0) + ' emir</span> ' +
            '(<span style=\"color:#15803d;\">' + (_state.anaSayi || 0) + ' ana</span> / ' +
            '<span style=\"color:#1e40af;\">' + (_state.altSayi || 0) + ' alt</span>) ' +
            '&nbsp;•&nbsp; ' +
            '<span style=\"color:#7c3aed;font-weight:600;\">Toplam: ' +
            toplam.toLocaleString('tr-TR') + ' çift</span>';
    }"""

JS_NEW = """    function _ozetGuncelle() {
        var box = document.getElementById('sb3Info');
        if (!box) return;
        // === FAZ 4.6 toplam siparis fix ===
        // Toplam = backend'den gelen siparis_toplam (distinct Siparis_Har.Miktar)
        var toplam = Number(_state.siparisToplam || 0);
        box.innerHTML =
            '<strong>Sipariş ' + (_state.sipnoSon || '') + '</strong> &nbsp;•&nbsp; ' +
            '<span style=\"color:#16a34a;font-weight:600;\">' + (_state.emirSayi || 0) + ' emir</span> ' +
            '(<span style=\"color:#15803d;\">' + (_state.anaSayi || 0) + ' ana</span> / ' +
            '<span style=\"color:#1e40af;\">' + (_state.altSayi || 0) + ' alt</span>) ' +
            '&nbsp;•&nbsp; ' +
            '<span style=\"color:#7c3aed;font-weight:600;\">Sipariş: ' +
            toplam.toLocaleString('tr-TR') + ' çift</span>';
    }"""


# Ana fetch sonrasi siparisToplam'i state'e kaydet
JS_OLD_INFO_SET = """            _state.sipnoSon = sipno;
            _state.anaSayi = r.data.ana_sayisi || 0;
            _state.altSayi = r.data.alt_sayisi || 0;
            _state.emirSayi = r.data.emir_sayisi || _state.emirler.length;
            _ozetGuncelle();"""

JS_NEW_INFO_SET = """            _state.sipnoSon = sipno;
            _state.anaSayi = r.data.ana_sayisi || 0;
            _state.altSayi = r.data.alt_sayisi || 0;
            _state.emirSayi = r.data.emir_sayisi || _state.emirler.length;
            _state.siparisToplam = r.data.siparis_toplam || 0;
            _state.siparisKalemleri = r.data.siparis_kalemleri || [];
            _ozetGuncelle();"""


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def main():
    print("=" * 64)
    print("FAZ 4.6 - Toplam siparis fix")
    print("=" * 64)
    print("Mantik: Toplam = distinct Siparis_Har.Miktar TOPLAMI")
    print("        (her ana emir 30 kere sayilmasin)")

    # Backend
    print()
    print("1/2 KORGUN: siparis_toplam alani")
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} yok.")
        return 1
    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()
    if KORGUN_MARKER in src:
        print("  [BILGI] Backend zaten ekli.")
    elif KORGUN_OLD not in src:
        print("  [HATA] Eski return bloku bulunamadi.")
        return 1
    elif src.count(KORGUN_OLD) > 1:
        print("  [HATA] Eski blok cogul.")
        return 1
    else:
        new_src = src.replace(KORGUN_OLD, KORGUN_NEW, 1)
        try:
            ast.parse(new_src)
        except SyntaxError as e:
            print(f"  [HATA] parse: {e}")
            return 1
        bp = backup(KORGUN_PY)
        print(f"  [OK] Yedek: {bp}")
        with open(KORGUN_PY, 'w', encoding='utf-8') as f:
            f.write(new_src)
        print("  [OK] siparis_toplam ve siparis_kalemleri eklendi.")

    # Frontend
    print()
    print("2/2 JS: toplam hesabi siparis_toplam")
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return 1
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        jsrc = f.read()
    if JS_MARKER in jsrc:
        print("  [BILGI] JS zaten ekli.")
        return 0

    if JS_OLD not in jsrc:
        print("  [HATA] _ozetGuncelle pattern bulunamadi.")
        return 1
    if JS_OLD_INFO_SET not in jsrc:
        print("  [HATA] state set pattern bulunamadi.")
        return 1

    new_jsrc = jsrc.replace(JS_OLD, JS_NEW, 1)
    new_jsrc = new_jsrc.replace(JS_OLD_INFO_SET, JS_NEW_INFO_SET, 1)
    new_jsrc += "\n/* " + JS_MARKER + " */\n"

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_jsrc)
    print("  [OK] _ozetGuncelle siparis_toplam kullanir.")

    print()
    print("YAPILACAK:")
    print("  1) CPS sunucusunu yeniden baslat (Korgun degisikligi)")
    print("  2) Browser Ctrl+F5")
    print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
    print()
    print("Beklenen:")
    print("  Sipariş 33558 • 55 emir (30 ana / 25 alt) • Sipariş: 14.000 çift")
    print("  (210.000 degil!)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
