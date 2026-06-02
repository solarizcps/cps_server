# -*- coding: utf-8 -*-
"""
setup_sablon_geri_al.py
-----------------------
Toplu sablon uygulama geri alma:
  - Backend: POST /hedef/sablon/geri-al
    Secili emirlerin emir_alt_proses kayitlarindan kaynak='sablon:...' olanlari
    aktif=0 yapar (soft delete). 'manuel' olanlara dokunmaz.
  - Frontend: Toplu uygulama bari'nin yanina 'Sablon Geri Al' butonu

Idempotent + CPS_KURALLAR uyumlu.
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

ROUTES_MARKER = "# === FAZ 4.6 B3 sablon geri-al endpoint ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B3 sablon geri-al"


# =====================================================================
# 1) BACKEND: yeni endpoint
# =====================================================================
ROUTES_BLOCK = '''


# === FAZ 4.6 B3 sablon geri-al endpoint ===
# Toplu sablon uygulamasini geri al: secili emirlerin emir_alt_proses'inde
# kaynak='sablon:...' olanlari aktif=0 yapar. 'manuel' kayitlara dokunmaz.
@hedef_bp.route('/sablon/geri-al', methods=['POST'])
def hedef_sablon_geri_al():
    """POST /hedef/sablon/geri-al
    Body: {emir_no_listesi: [...], sablon_id: optional}
    Eger sablon_id verilirse, sadece o sablondan gelenler silinir.
    Verilmezse, tum sablon-kaynakli kayitlar (kaynak='sablon:%') silinir.
    """
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    emir_listesi = data.get('emir_no_listesi') or []
    sablon_id = data.get('sablon_id')  # opsiyonel

    if not isinstance(emir_listesi, list) or len(emir_listesi) == 0:
        return jsonify({'ok': False, 'mesaj': 'emir_no_listesi gerekli'}), 400

    # Emir no'lari string'e cevir (emir_alt_proses.emir_no TEXT)
    emir_strs = []
    for e in emir_listesi:
        s = str(e).strip()
        if s:
            emir_strs.append(s)
    if not emir_strs:
        return jsonify({'ok': False, 'mesaj': 'gecerli emir_no yok'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Sablon adi (eger sablon_id verilmis ise)
        sablon_kaynak_pattern = 'sablon:%'
        sablon_adi = None
        if sablon_id:
            try:
                sablon_id_int = int(sablon_id)
                row = conn.execute(
                    "SELECT sablon_adi FROM sablon WHERE id=?",
                    (sablon_id_int,)
                ).fetchone()
                if row:
                    sablon_adi = row['sablon_adi']
                    sablon_kaynak_pattern = 'sablon:' + sablon_adi
            except Exception:
                pass

        # Once kac kayit etkilenecek say
        placeholders = ','.join(['?'] * len(emir_strs))
        sayim = conn.execute(f"""
            SELECT COUNT(*) FROM emir_alt_proses
             WHERE emir_no IN ({placeholders})
               AND aktif = 1
               AND kaynak LIKE ?
        """, tuple(emir_strs) + (sablon_kaynak_pattern,)).fetchone()[0]

        # Soft delete
        cur = conn.execute(f"""
            UPDATE emir_alt_proses
               SET aktif = 0,
                   guncelleme = datetime('now','localtime'),
                   guncelleyen_id = ?,
                   guncelleyen_ad = ?
             WHERE emir_no IN ({placeholders})
               AND aktif = 1
               AND kaynak LIKE ?
        """, (uid, uad) + tuple(emir_strs) + (sablon_kaynak_pattern,))
        affected = cur.rowcount

        # Etkilenen emir sayisi (distinct)
        emir_sayim = conn.execute(f"""
            SELECT COUNT(DISTINCT emir_no) FROM emir_alt_proses
             WHERE emir_no IN ({placeholders})
               AND aktif = 0
               AND kaynak LIKE ?
               AND date(COALESCE(guncelleme, olusturma)) = date('now','localtime')
        """, tuple(emir_strs) + (sablon_kaynak_pattern,)).fetchone()[0]

        conn.commit()
        conn.close()

        return jsonify({
            'ok': True,
            'silinen_proses_sayisi': affected,
            'etkilenen_emir_sayisi': emir_sayim,
            'sablon_adi': sablon_adi or 'tum sablonlar',
            'mesaj': str(affected) + ' proses geri alindi (' +
                     str(emir_sayim) + ' emir).'
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
'''


# =====================================================================
# 2) FRONTEND: toplu uygula barina 'Geri Al' butonu
# =====================================================================
# Bulacagimiz pattern: 'Secili Emirlere Uygula' butonunun bulundugu yer
# (toplu uygula bari)

JS_OLD_TOPLU = """            html.push('<button class=\"uygulaBtn\" id=\"sb3TopluUygulaBtn\" disabled>Seçili Emirlere Uygula</button>');
            html.push('<span class=\"secim-info\" id=\"sb3SecimInfo\">0 emir seçili</span>');
            html.push('</div>');"""

JS_NEW_TOPLU = """            html.push('<button class=\"uygulaBtn\" id=\"sb3TopluUygulaBtn\" disabled>Seçili Emirlere Uygula</button>');
            html.push('<button class=\"uygulaBtn geriAlBtn\" id=\"sb3TopluGeriAlBtn\" disabled style=\"background:#dc2626;\">↶ Sablon Geri Al</button>');
            html.push('<span class=\"secim-info\" id=\"sb3SecimInfo\">0 emir seçili</span>');
            html.push('</div>');"""


# Secim guncelle: sb3TopluGeriAlBtn'i de enable/disable et
JS_OLD_SECIM = """    function _secimGuncelle() {
        var sonuc = document.getElementById('sb3Sonuc');
        if (!sonuc) return;
        var sayi = sonuc.querySelectorAll('.emir-chk:checked').length;
        var info = document.getElementById('sb3SecimInfo');
        if (info) info.textContent = sayi + ' emir seçili';
        var btn = document.getElementById('sb3TopluUygulaBtn');
        if (btn) btn.disabled = (sayi === 0);
    }"""

JS_NEW_SECIM = """    function _secimGuncelle() {
        var sonuc = document.getElementById('sb3Sonuc');
        if (!sonuc) return;
        var sayi = sonuc.querySelectorAll('.emir-chk:checked').length;
        var info = document.getElementById('sb3SecimInfo');
        if (info) info.textContent = sayi + ' emir seçili';
        var btn = document.getElementById('sb3TopluUygulaBtn');
        if (btn) btn.disabled = (sayi === 0);
        var gbtn = document.getElementById('sb3TopluGeriAlBtn');
        if (gbtn) gbtn.disabled = (sayi === 0);
    }"""


# Toplu Uygula butonunun event binding'ini bul, geri al binding'ini de ekle
JS_OLD_BINDING = """        var topluBtn = document.getElementById('sb3TopluUygulaBtn');
        if (topluBtn) {
            topluBtn.addEventListener('click', function () {
                var sel = document.getElementById('sb3TopluSablon');
                var sid = parseInt(sel.value, 10);
                if (!sid) {
                    _toast('uyari', 'Eksik', 'Önce bir şablon seç.');
                    return;
                }
                var secili = Array.prototype.map.call(
                    sonuc.querySelectorAll('.emir-chk:checked'),
                    function (c) { return c.dataset.emir; }
                );
                if (secili.length === 0) {
                    _toast('uyari', 'Eksik', 'En az 1 emir seç.');
                    return;
                }
                if (!confirm(secili.length + ' emire şablon uygulanacak. Onaylıyor musun?')) return;
                _uygula(secili, sid);
            });
        }
    }"""

JS_NEW_BINDING = """        var topluBtn = document.getElementById('sb3TopluUygulaBtn');
        if (topluBtn) {
            topluBtn.addEventListener('click', function () {
                var sel = document.getElementById('sb3TopluSablon');
                var sid = parseInt(sel.value, 10);
                if (!sid) {
                    _toast('uyari', 'Eksik', 'Önce bir şablon seç.');
                    return;
                }
                var secili = Array.prototype.map.call(
                    sonuc.querySelectorAll('.emir-chk:checked'),
                    function (c) { return c.dataset.emir; }
                );
                if (secili.length === 0) {
                    _toast('uyari', 'Eksik', 'En az 1 emir seç.');
                    return;
                }
                if (!confirm(secili.length + ' emire şablon uygulanacak. Onaylıyor musun?')) return;
                _uygula(secili, sid);
            });
        }

        // === FAZ 4.6 B3 sablon geri-al ===
        var geriBtn = document.getElementById('sb3TopluGeriAlBtn');
        if (geriBtn) {
            geriBtn.addEventListener('click', function () {
                var sel = document.getElementById('sb3TopluSablon');
                var sid = parseInt(sel.value, 10) || null;
                var secili = Array.prototype.map.call(
                    sonuc.querySelectorAll('.emir-chk:checked'),
                    function (c) { return c.dataset.emir; }
                );
                if (secili.length === 0) {
                    _toast('uyari', 'Eksik', 'En az 1 emir seç.');
                    return;
                }
                var sablonAdi = sid ? (
                    (_state.sablonlar.find(function(s){return s.id===sid;}) || {}).sablon_adi || ('#' + sid)
                ) : 'TÜM şablonlar';
                if (!confirm(secili.length + ' emirden ' + sablonAdi +
                    ' uygulamasi geri alinacak (manuel kayitlar korunur). Onaylıyor musun?')) return;
                _geriAl(secili, sid);
            });
        }
    }

    function _geriAl(emirNos, sablonId) {
        var btn = document.getElementById('sb3TopluGeriAlBtn');
        if (btn) btn.disabled = true;

        var body = { emir_no_listesi: emirNos };
        if (sablonId) body.sablon_id = sablonId;

        _api('/hedef/sablon/geri-al', {
            method: 'POST',
            body: JSON.stringify(body)
        }).then(function (r) {
            if (btn) btn.disabled = false;
            if (r.status >= 400 || !r.data || r.data.ok === false) {
                _toast('hata', 'Hata', (r.data && r.data.mesaj) || ('HTTP ' + r.status));
                return;
            }
            _toast('basari', 'Geri Alindi',
                (r.data.silinen_proses_sayisi || 0) + ' proses, ' +
                (r.data.etkilenen_emir_sayisi || 0) + ' emirden kaldirildi.');
            // Proses sayilarini yenile
            _yukleProsesSayilari(emirNos).then(function () { _renderTablolar(); });
        }).catch(function (e) {
            if (btn) btn.disabled = false;
            _toast('hata', 'Hata', e.message);
        });
    }"""


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_routes():
    print()
    print("=" * 64)
    print("1/2 ROUTES: /hedef/sablon/geri-al")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] Endpoint zaten ekli.")
        return True
    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += ROUTES_BLOCK
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False
    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Endpoint eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 JS: Geri Al butonu + secim binding")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] JS zaten ekli.")
        return True

    repls = [
        ("JS_OLD_TOPLU", JS_OLD_TOPLU, JS_NEW_TOPLU),
        ("JS_OLD_SECIM", JS_OLD_SECIM, JS_NEW_SECIM),
        ("JS_OLD_BINDING", JS_OLD_BINDING, JS_NEW_BINDING),
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
    print("  [OK] Geri Al butonu + binding eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B3 - Toplu Sablon Geri Al")
    print("=" * 64)
    print("CPS_KURALLAR uyum:")
    print("  ✓ Korgun dokunulmaz (mock_data.db SOFT DELETE)")
    print("  ✓ Manuel proseslere dokunmaz (sadece kaynak='sablon:%')")
    print("  ✓ Veri silinmez (aktif=0)")

    ok1 = patch_routes()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat (routes degisti)")
        print("  2) Browser Ctrl+F5")
        print("  3) /hedef/ -> SABLON -> 33558 -> Emirleri Getir")
        print()
        print("Beklenen:")
        print("  Toplu uygula bari'nda iki buton:")
        print("    [Secili Emirlere Uygula]  [↶ Sablon Geri Al] (kirmizi)")
        print()
        print("Test:")
        print("  1. Birkac emir secm")
        print("  2. Sablon sec (opsiyonel: secilirse sadece o sablon kaldirilir)")
        print("  3. 'Sablon Geri Al' tikla")
        print("  4. Confirm: 'X emirden Atki LCW geri alinacak (manuel korunur)'")
        print("  5. Onayla -> toast 'X proses kaldirildi'")
        print("  6. MEVCUT PROSES kolonu update")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
