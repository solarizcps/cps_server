# -*- coding: utf-8 -*-
"""
setup_hedef_onaylar.py
----------------------
1) modules/hedef/routes.py'a 4 endpoint ekler (idempotent):
     GET  /hedef/onaylar/bekleyen
     GET  /hedef/gecmis?limit=200
     POST /hedef/onayla   { uretim_kayit_id, not }
     POST /hedef/reddet   { uretim_kayit_id, not }

2) static/js/hedef.js sonuna CPS-local override IIFE ekler (idempotent):
     onaylariYukle, gecmisYukle, renderOnayRows, renderGecmisRows,
     onaylaKayit, reddetOnayla, guncelleOnayBadge
   (Eski MES v2 fonksiyonlarinin yerine geçer; mevcut kodu bozmaz.)

DOKUNMAZ:
  - /uretim/* endpointleri
  - hedef_bp Blueprint tanimi, mevcut /hedef/, /hedef/sablon, /hedef/sapma
  - hedef.js icindeki PLAN/RAPOR/SAPMA fonksiyonlari
  - reddet modal HTML, _aktifReddetId, _showElem, reddetModalAc/Kapat
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
ROUTES_PATH = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
HEDEF_JS = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

BACKEND_MARKER = "# === CPS LOCAL HEDEF ONAY ENDPOINTS ==="
FRONTEND_MARKER = "[CPS LOCAL] Hedef onay endpoint override yuklendi"

# ----------------------------------------------------------------------
# BACKEND BLOCK — routes.py sonuna eklenecek
# ----------------------------------------------------------------------
BACKEND_BLOCK = '''


# === CPS LOCAL HEDEF ONAY ENDPOINTS ===
# Eklendi: setup_hedef_onaylar.py
# Veri kaynagi: mock_data.db.uretim_kayit (MES v2 KULLANILMIYOR)

def _hedef_db_path():
    import os as _os
    from flask import current_app
    candidates = [
        _os.path.join(current_app.root_path, 'mock_data.db'),
        _os.path.join(_os.path.dirname(current_app.root_path), 'mock_data.db'),
        _os.path.join(_os.getcwd(), 'mock_data.db'),
        r'C:\\cps_dev\\mock_data.db',
    ]
    for p in candidates:
        if _os.path.exists(p):
            return p
    return candidates[0]


def _hedef_usta_session():
    from flask import session
    uid = (session.get('user_id') or session.get('kullanici_id') or
           session.get('id') or 0)
    uad = (session.get('user_name') or session.get('kullanici_ad') or
           session.get('ad') or session.get('username') or 'Sistem')
    return uid, uad


@hedef_bp.route('/onaylar/bekleyen', methods=['GET'])
def hedef_onaylar_bekleyen():
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, emir_no, model_kod, model_adi,
                   miktar, proses_kodu, proses_adi,
                   personel_id, personel_ad,
                   tarih, saat, not_metin,
                   onay_durum, olusturma
              FROM uretim_kayit
             WHERE onay_durum = 'bekliyor'
             ORDER BY olusturma DESC, id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({
            'success': True, 'ok': True,
            'kayitlar': rows, 'kayit_sayisi': len(rows)
        })
    except Exception as e:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': str(e), 'kayitlar': []}), 500


@hedef_bp.route('/gecmis', methods=['GET'])
def hedef_gecmis():
    import sqlite3
    from flask import jsonify, request
    try:
        limit = int(request.args.get('limit', 200))
    except Exception:
        limit = 200
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, emir_no, model_kod, model_adi,
                   miktar, proses_kodu, proses_adi,
                   personel_id, personel_ad,
                   tarih, saat, not_metin,
                   onay_durum, usta_id, usta_ad, usta_not,
                   onay_tarihi, olusturma
              FROM uretim_kayit
             WHERE onay_durum IN ('onaylandi', 'reddedildi')
             ORDER BY onay_tarihi DESC, olusturma DESC, id DESC
             LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({
            'success': True, 'ok': True,
            'kayitlar': rows, 'kayit_sayisi': len(rows)
        })
    except Exception as e:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': str(e), 'kayitlar': []}), 500


@hedef_bp.route('/onayla', methods=['POST'])
def hedef_onayla():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    kayit_id = data.get('uretim_kayit_id') or data.get('id')
    not_metni = (data.get('not') or '').strip() or None
    if not kayit_id:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'uretim_kayit_id gerekli'}), 400
    usta_id, usta_ad = _hedef_usta_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE uretim_kayit
               SET onay_durum = 'onaylandi',
                   usta_id = ?, usta_ad = ?, usta_not = ?,
                   onay_tarihi = datetime('now', 'localtime')
             WHERE id = ? AND onay_durum = 'bekliyor'
        """, (usta_id, usta_ad, not_metni, kayit_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return jsonify({'success': False, 'ok': False,
                            'mesaj': 'Kayit bulunamadi veya zaten islem gormus'}), 404
        return jsonify({'success': True, 'ok': True,
                        'id': kayit_id, 'mesaj': 'Onaylandi'})
    except Exception as e:
        return jsonify({'success': False, 'ok': False, 'mesaj': str(e)}), 500


@hedef_bp.route('/reddet', methods=['POST'])
def hedef_reddet():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    kayit_id = data.get('uretim_kayit_id') or data.get('id')
    not_metni = (data.get('not') or '').strip()
    if not kayit_id:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'uretim_kayit_id gerekli'}), 400
    if not not_metni:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'Reddetme nedeni zorunlu'}), 400
    if len(not_metni) < 5:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'En az 5 karakter girilmeli'}), 400
    usta_id, usta_ad = _hedef_usta_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE uretim_kayit
               SET onay_durum = 'reddedildi',
                   usta_id = ?, usta_ad = ?, usta_not = ?,
                   onay_tarihi = datetime('now', 'localtime')
             WHERE id = ? AND onay_durum = 'bekliyor'
        """, (usta_id, usta_ad, not_metni, kayit_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return jsonify({'success': False, 'ok': False,
                            'mesaj': 'Kayit bulunamadi veya zaten islem gormus'}), 404
        return jsonify({'success': True, 'ok': True,
                        'id': kayit_id, 'mesaj': 'Reddedildi'})
    except Exception as e:
        return jsonify({'success': False, 'ok': False, 'mesaj': str(e)}), 500
'''


# ----------------------------------------------------------------------
# FRONTEND BLOCK — hedef.js sonuna eklenecek
# ----------------------------------------------------------------------
FRONTEND_BLOCK = r'''


/* ====================================================================
   CPS LOCAL OVERRIDE - Hedef Onaylar / Gecmis (mock_data.db)
   Eski MES v2 fonksiyonlarini overrride eder.
   Endpoint'ler:
     GET  /hedef/onaylar/bekleyen
     GET  /hedef/gecmis?limit=200
     POST /hedef/onayla   { uretim_kayit_id, not }
     POST /hedef/reddet   { uretim_kayit_id, not }
   Kolon sirasi: EMIR NO | MODEL | PROSES | MIKTAR | PERSONEL |
                 TARIH/SAAT | NOT | ISLEM
   ==================================================================== */
(function () {
    'use strict';

    function _cpsApi(path, options) {
        options = options || {};
        options.credentials = 'include';
        options.headers = options.headers || {};
        if (!options.headers['Content-Type']) {
            options.headers['Content-Type'] = 'application/json';
        }
        return fetch(path, options).then(function (resp) {
            return resp.text().then(function (t) {
                var data;
                try { data = JSON.parse(t); } catch (_) { data = { _raw: t }; }
                return { status: resp.status, data: data };
            });
        });
    }

    function _esc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _tarihSaat(k) {
        var t = k.tarih || '';
        var s = k.saat || '';
        if (t && s) return t + ' ' + s;
        return t || s || (k.olusturma || '');
    }

    function _renderOnaySatir(k) {
        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td>' + _esc(k.emir_no) + '</td>' +
            '<td>' + _esc(k.model_kod || k.model_adi || '') + '</td>' +
            '<td>' + _esc(k.proses_adi || '') + '</td>' +
            '<td><strong>' + _esc(k.miktar) + '</strong></td>' +
            '<td>' + _esc(k.personel_ad || '') + '</td>' +
            '<td style="font-family:var(--mono); font-size:12px;">' + _esc(_tarihSaat(k)) + '</td>' +
            '<td>' + _esc(k.not_metin || '') + '</td>' +
            '<td style="text-align:right; white-space:nowrap;">' +
                '<button class="h-btn-yeni" style="background:var(--green); padding:4px 10px; font-size:12px; margin-right:4px;" onclick="onaylaKayit(' + k.id + ')">ONAYLA</button>' +
                '<button class="h-btn-yeni" style="background:var(--red); padding:4px 10px; font-size:12px;" onclick="reddetModalAc(' + k.id + ')">REDDET</button>' +
            '</td>';
        return tr;
    }

    function _renderGecmisSatir(k) {
        var durumRenk = '';
        if (k.onay_durum === 'onaylandi') durumRenk = 'color:var(--green); font-weight:600;';
        else if (k.onay_durum === 'reddedildi') durumRenk = 'color:var(--red); font-weight:600;';
        var ustaNotEk = k.usta_not
            ? ' <span style="color:var(--text3); font-size:11px;">(' + _esc(k.usta_not) + ')</span>'
            : '';
        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td>' + _esc(k.emir_no) + '</td>' +
            '<td>' + _esc(k.model_kod || k.model_adi || '') + '</td>' +
            '<td>' + _esc(k.proses_adi || '') + '</td>' +
            '<td><strong>' + _esc(k.miktar) + '</strong></td>' +
            '<td>' + _esc(k.personel_ad || '') + '</td>' +
            '<td style="font-family:var(--mono); font-size:12px;">' + _esc(_tarihSaat(k)) + '</td>' +
            '<td style="' + durumRenk + '">' + _esc(k.onay_durum) + ustaNotEk + '</td>' +
            '<td style="font-family:var(--mono); font-size:11px; color:var(--text3);">' +
                _esc(k.onay_tarihi || '') + '<br>' + _esc(k.usta_ad || '') +
            '</td>';
        return tr;
    }

    window.renderOnayRows = function (rows) {
        var body = document.getElementById('onayBody');
        if (!body) return;
        body.innerHTML = '';
        if (!rows || rows.length === 0) {
            body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text3);">Bekleyen onay kaydı yok.</td></tr>';
            return;
        }
        for (var i = 0; i < rows.length; i++) {
            body.appendChild(_renderOnaySatir(rows[i]));
        }
    };

    window.renderGecmisRows = function (rows) {
        var body = document.getElementById('gecmisBody');
        if (!body) return;
        body.innerHTML = '';
        if (!rows || rows.length === 0) {
            body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text3);">Geçmiş kayıt yok.</td></tr>';
            return;
        }
        for (var i = 0; i < rows.length; i++) {
            body.appendChild(_renderGecmisSatir(rows[i]));
        }
    };

    window.onaylariYukle = function () {
        var body = document.getElementById('onayBody');
        if (body) body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--text3);">Yükleniyor...</td></tr>';
        _cpsApi('/hedef/onaylar/bekleyen', { method: 'GET' })
            .then(function (r) {
                if (r.status >= 400 || (r.data && r.data.ok === false)) {
                    if (body) body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--red);">Onay kayıtları yüklenemedi.</td></tr>';
                    return;
                }
                var kayitlar = (r.data && r.data.kayitlar) || [];
                window.renderOnayRows(kayitlar);
                window._onayYuklendi = true;
                if (typeof guncelleBadge === 'function') {
                    try { guncelleBadge(kayitlar.length); } catch (_) {}
                }
                console.log('CPS/onaylar', r.status, kayitlar.length);
            })
            .catch(function (e) {
                console.error('onaylar fetch:', e);
                if (body) body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--red);">Onay kayıtları yüklenemedi.</td></tr>';
            });
    };

    window.gecmisYukle = function () {
        var body = document.getElementById('gecmisBody');
        if (body) body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--text3);">Yükleniyor...</td></tr>';
        _cpsApi('/hedef/gecmis?limit=200', { method: 'GET' })
            .then(function (r) {
                if (r.status >= 400 || (r.data && r.data.ok === false)) {
                    if (body) body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--red);">Geçmiş yüklenemedi.</td></tr>';
                    return;
                }
                var kayitlar = (r.data && r.data.kayitlar) || [];
                window.renderGecmisRows(kayitlar);
                window._gecmisYuklendi = true;
                console.log('CPS/gecmis', r.status, kayitlar.length);
            })
            .catch(function (e) {
                console.error('gecmis fetch:', e);
                if (body) body.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--red);">Geçmiş yüklenemedi.</td></tr>';
            });
    };

    window.onaylaKayit = function (uretimId) {
        if (!confirm('Bu kaydı onaylamak istiyor musun?')) return;
        _cpsApi('/hedef/onayla', {
            method: 'POST',
            body: JSON.stringify({ uretim_kayit_id: uretimId, not: '' })
        }).then(function (r) {
            if (r.status >= 400 || (r.data && r.data.ok === false)) {
                alert((r.data && r.data.mesaj) || ('HTTP ' + r.status));
                return;
            }
            window._onayYuklendi = false;
            window._gecmisYuklendi = false;
            window.onaylariYukle();
            console.log('CPS/onayla', r.status, r.data);
        }).catch(function (e) {
            console.error('onayla fetch:', e);
            alert('Sunucuya ulaşılamadı: ' + e.message);
        });
    };

    window.reddetOnayla = function () {
        if (!window._aktifReddetId) return;
        var ta = document.getElementById('reddetNot');
        var notu = ta ? ta.value.trim() : '';
        if (!notu) {
            if (typeof _showElem === 'function') {
                _showElem('reddetNotError', 'Reddetme nedeni zorunlu - lütfen sebep yaz.', 5000);
            }
            if (ta) ta.focus();
            return;
        }
        if (notu.length < 5) {
            if (typeof _showElem === 'function') {
                _showElem('reddetNotError', 'En az 5 karakter girmelisin.', 5000);
            }
            return;
        }
        var btn = document.getElementById('reddetOnaylaBtn');
        if (btn) { btn.disabled = true; btn.textContent = 'Reddediliyor...'; }
        _cpsApi('/hedef/reddet', {
            method: 'POST',
            body: JSON.stringify({ uretim_kayit_id: window._aktifReddetId, not: notu })
        }).then(function (r) {
            if (btn) { btn.disabled = false; btn.textContent = 'REDDET'; }
            if (r.status >= 400 || (r.data && r.data.ok === false)) {
                if (typeof _showElem === 'function') {
                    _showElem('reddetNotError', (r.data && r.data.mesaj) || ('HTTP ' + r.status), 5000);
                }
                return;
            }
            if (typeof reddetModalKapat === 'function') reddetModalKapat();
            window._onayYuklendi = false;
            window._gecmisYuklendi = false;
            window.onaylariYukle();
            console.log('CPS/reddet', r.status, r.data);
        }).catch(function (e) {
            if (btn) { btn.disabled = false; btn.textContent = 'REDDET'; }
            console.error('reddet fetch:', e);
            if (typeof _showElem === 'function') {
                _showElem('reddetNotError', 'Sunucuya ulaşılamadı: ' + e.message, 5000);
            }
        });
    };

    window.guncelleOnayBadge = function () {
        _cpsApi('/hedef/onaylar/bekleyen', { method: 'GET' })
            .then(function (r) {
                if (r.data && (r.data.kayit_sayisi !== undefined || Array.isArray(r.data.kayitlar))) {
                    var n = r.data.kayit_sayisi !== undefined
                        ? r.data.kayit_sayisi
                        : r.data.kayitlar.length;
                    if (typeof guncelleBadge === 'function') {
                        try { guncelleBadge(n); } catch (_) {}
                    }
                }
            })
            .catch(function () {});
    };

    console.log('[CPS LOCAL] Hedef onay endpoint override yuklendi.');
})();
'''


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def backup(path):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_backend():
    print()
    print("=" * 64)
    print("BACKEND: modules/hedef/routes.py")
    print("=" * 64)
    if not os.path.exists(ROUTES_PATH):
        print(f"  [HATA] {ROUTES_PATH} bulunamadi.")
        return False

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if BACKEND_MARKER in src:
        print("  [BILGI] Backend zaten patchli (marker var). Atliyor.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += BACKEND_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] Yeni icerik parse edilemiyor: {e}")
        return False

    bp = backup(ROUTES_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] 4 endpoint eklendi: /onaylar/bekleyen, /gecmis, /onayla, /reddet")
    return True


def patch_frontend():
    print()
    print("=" * 64)
    print("FRONTEND: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(HEDEF_JS):
        print(f"  [HATA] {HEDEF_JS} bulunamadi.")
        return False

    with open(HEDEF_JS, 'r', encoding='utf-8') as f:
        src = f.read()

    if FRONTEND_MARKER in src:
        print("  [BILGI] Frontend zaten patchli (marker var). Atliyor.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += FRONTEND_BLOCK

    bp = backup(HEDEF_JS)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_JS, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] CPS local override IIFE eklendi (onaylariYukle, gecmisYukle, ...)")
    return True


def main():
    ok1 = patch_backend()
    ok2 = patch_frontend()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("HEPSI TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> ONAYLAR sekmesi")
        print("     -> Yukleniyor kisa sure, sonra 4 bekleyen kayit")
        print("     -> Her satirin sagi: ONAYLA + REDDET")
        print("  4) Bir kaydi ONAYLA -> liste yenilenir, GECMIS sekmesinde gorunur")
        print("  5) Bir kaydi REDDET -> not gir (>=5 karakter) -> liste yenilenir")
        print()
        print("Test sirasinda DevTools Console'a bak:")
        print("  [CPS LOCAL] Hedef onay endpoint override yuklendi.")
        print("  CPS/onaylar 200 N")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
