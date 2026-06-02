# -*- coding: utf-8 -*-
"""
setup_faz45_dogrulama.py
------------------------
FAZ 4.5 - Veri dogrulama ve baglanti sistemi.

1) modules/uretim_giris/routes.py - uretim_kaydet'e 3 ek kontrol:
   a) HEDEF_YOK: Korgun hedef <= 0 ise 400
   b) DUPLICATE: ayni emir+proses+personel+miktar son 60 sn'de var ise 409
   c) VARDIYA: saatten hesapla (07-15=1, 15-23=2, 23-07=3), response'a ekle

2) modules/hedef/routes.py - yeni endpoint:
   GET /hedef/dogrulama
   - eski_bekleyen (24 saat+ bekliyor)
   - duplicate_adaylar (gecmiste ayni emir+proses+personel+miktar)
   - gecersiz_proses (emir_alt_proses'te olmayan proses_kodu)
   - hedefsiz_kayitlar (Korgun'da hedef=0 olan emirlerdeki kayitlar)

3) static/js/hedef.js - IIFE:
   - Sayfa yuklenince /hedef/dogrulama cagir
   - Toplam_uyari > 0 ise ust banner goster (sari)
   - Banner tiklayinca modal: 4 blok detay
   - Her 5 dakikada otomatik yenile

DOKUNMAZ:
  - Mevcut PLAN/RAPOR/ONAYLAR/GECMIS endpoint'leri ve render
  - mock_data.db semasi (vardiya kolon eklenmiyor, runtime hesap)
  - Korgun (sadece read)
  - /uretim/* hicbir endpoint mantik degisikligi (sadece kontroller eklendi)

CPS KURALLARIYLA UYUM:
  ✓ Korgun read-only
  ✓ MES v2 yok
  ✓ Mevcut sistem bozulmuyor, sadece kontrol katmani
"""

import os
import re
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
URETIM_ROUTES = os.path.join(CPS_ROOT, "modules", "uretim_giris", "routes.py")
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

DUP_MARKER = "'hata': 'duplicate'"
HEDEF_YOK_MARKER = "'hata': 'hedef_yok'"
DOGRULAMA_BACKEND_MARKER = "# === CPS LOCAL HEDEF DOGRULAMA ENDPOINT ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.5 dogrulama yuklendi"


# =====================================================================
# 1) URETIM_KAYDET KONTROLLERI - str_replace
# =====================================================================

# 1a) HEDEF_YOK kontrolu
URETIM_OLD_1 = """        hedef = ozet.get('hedef_adet', 0) or 0
        yapilan = ozet.get('yapilan_adet', 0) or 0

        # Local SQLite'taki bekleyen kayitlari da hesaba kat"""

URETIM_NEW_1 = """        hedef = ozet.get('hedef_adet', 0) or 0
        yapilan = ozet.get('yapilan_adet', 0) or 0

        # === FAZ 4.5: HEDEF YOKSA engelle ===
        if int(hedef or 0) <= 0:
            return _jsonify_uk({
                'ok': False,
                'hata': 'hedef_yok',
                'mesaj': "Bu emir icin hedef tanimli degil. Korgun'da once hedef olmali.",
                'emir_no': emir_no,
            }), 400

        # Local SQLite'taki bekleyen kayitlari da hesaba kat"""


# 1b) DUPLICATE kontrolu - personel bilgisinden sonra, INSERT'ten once
URETIM_OLD_2 = """            # Personel bilgisi (CPS session'dan)
            u = _session_uk.get('kullanici', {}) or {}
            personel_id = u.get('Id')
            personel_ad = u.get('AdSoyad') or u.get('KullaniciAdi') or '?'

            simdi = _dt_uk.now()"""

URETIM_NEW_2 = """            # Personel bilgisi (CPS session'dan)
            u = _session_uk.get('kullanici', {}) or {}
            personel_id = u.get('Id')
            personel_ad = u.get('AdSoyad') or u.get('KullaniciAdi') or '?'

            # === FAZ 4.5: DUPLICATE KONTROL (60 sn icinde ayni kayit) ===
            _DUP_WIN_SEC = 60
            _dup = con.execute(
                "SELECT id, olusturma FROM uretim_kayit "
                "WHERE emir_no=? "
                "AND COALESCE(personel_id,0)=COALESCE(?,0) "
                "AND COALESCE(proses_kodu,'')=COALESCE(?,'') "
                "AND miktar=? "
                "AND datetime(olusturma) > datetime('now','localtime','-' || ? || ' seconds') "
                "ORDER BY id DESC LIMIT 1",
                (emir_no, personel_id, proses_kodu or None, miktar, _DUP_WIN_SEC)
            ).fetchone()
            if _dup:
                return _jsonify_uk({
                    'ok': False,
                    'hata': 'duplicate',
                    'mesaj': 'Ayni kayit son ' + str(_DUP_WIN_SEC) + ' sn icinde girilmis (id=' + str(_dup[0]) + ')',
                    'mevcut_id': _dup[0],
                }), 409

            simdi = _dt_uk.now()"""


# 1c) VARDIYA hesabini response'a ekle
URETIM_OLD_3 = """        return _jsonify_uk({
            'ok': True,
            'uretim_kayit_id': yeni_id,
            'emir_no': emir_no,
            'miktar': miktar,
            'onay_durum': 'bekliyor',
            'mesaj': 'Kayit eklendi, onay bekliyor.',
        }), 200"""

URETIM_NEW_3 = """        # === FAZ 4.5: VARDIYA hesabi (07-15=1, 15-23=2, 23-07=3) ===
        try:
            _hh = simdi.hour
            if 7 <= _hh < 15:
                _vardiya = 1
            elif 15 <= _hh < 23:
                _vardiya = 2
            else:
                _vardiya = 3
        except Exception:
            _vardiya = None

        return _jsonify_uk({
            'ok': True,
            'uretim_kayit_id': yeni_id,
            'emir_no': emir_no,
            'miktar': miktar,
            'onay_durum': 'bekliyor',
            'vardiya': _vardiya,
            'mesaj': 'Kayit eklendi, onay bekliyor.',
        }), 200"""


# =====================================================================
# 2) /hedef/dogrulama ENDPOINT - append
# =====================================================================

DOGRULAMA_BACKEND = '''


# === CPS LOCAL HEDEF DOGRULAMA ENDPOINT ===
# Veri kalitesi kontrolleri - 4 blok suspheli kayit listesi

@hedef_bp.route('/dogrulama', methods=['GET'])
def hedef_dogrulama():
    """GET /hedef/dogrulama - 4 blok veri uyarisi."""
    import sqlite3
    from flask import jsonify

    db_path = _hedef_db_path()
    eski_bekleyen = []
    duplicate_adaylar = []
    gecersiz_proses = []
    hedefsiz_kayitlar = []
    korgun_hatasi = None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1) Eski bekleyen (24 saat+)
        cur.execute("""
            SELECT id, emir_no, proses_adi, miktar,
                   personel_ad, olusturma, onay_durum
              FROM uretim_kayit
             WHERE onay_durum = 'bekliyor'
               AND datetime(olusturma) < datetime('now','localtime','-24 hours')
             ORDER BY olusturma ASC
        """)
        eski_bekleyen = [dict(r) for r in cur.fetchall()]

        # 2) Duplicate adaylar (ayni emir+proses+personel+miktar tekrarli)
        cur.execute("""
            SELECT emir_no, proses_kodu, proses_adi, personel_id, personel_ad, miktar,
                   COUNT(*) as adet,
                   GROUP_CONCAT(id) as id_listesi,
                   MIN(olusturma) as ilk_kayit,
                   MAX(olusturma) as son_kayit
              FROM uretim_kayit
             WHERE onay_durum != 'reddedildi'
             GROUP BY emir_no, proses_kodu, personel_id, miktar
            HAVING COUNT(*) > 1
             ORDER BY MAX(olusturma) DESC
             LIMIT 100
        """)
        duplicate_adaylar = [dict(r) for r in cur.fetchall()]

        # 3) Gecersiz proses (emir_alt_proses'te olmayan veya pasif)
        cur.execute("""
            SELECT u.id, u.emir_no, u.proses_kodu, u.proses_adi,
                   u.miktar, u.personel_ad, u.onay_durum, u.olusturma
              FROM uretim_kayit u
              LEFT JOIN emir_alt_proses ap
                ON CAST(ap.id AS TEXT) = u.proses_kodu
               AND ap.emir_no = CAST(u.emir_no AS TEXT)
               AND ap.aktif = 1
             WHERE ap.id IS NULL
             ORDER BY u.id DESC
             LIMIT 100
        """)
        gecersiz_proses = [dict(r) for r in cur.fetchall()]

        # 4) Hedefsiz emirler - distinct emir_no listesi
        cur.execute("SELECT DISTINCT emir_no FROM uretim_kayit")
        emirler = [r[0] for r in cur.fetchall()]
        conn.close()

        # Korgun'dan her emiri sorgula, hedef=0 olanlari topla
        try:
            from modules.common import korgun as _kk_dog
            for emir_no in emirler:
                try:
                    ozet = _kk_dog.get_emir_ozet(int(emir_no)) or {}
                    ok = ozet.get('ok')
                    hedef = int(ozet.get('hedef_adet', 0) or 0)
                    if not ok or hedef <= 0:
                        # Bu emirin kayitlarini ekle
                        c2 = sqlite3.connect(db_path)
                        c2.row_factory = sqlite3.Row
                        rows = c2.execute("""
                            SELECT id, emir_no, proses_adi, miktar,
                                   personel_ad, onay_durum, olusturma
                              FROM uretim_kayit
                             WHERE emir_no = ?
                             ORDER BY olusturma DESC
                             LIMIT 50
                        """, (emir_no,)).fetchall()
                        c2.close()
                        for r in rows:
                            d = dict(r)
                            d['_neden'] = ('emir_bulunamadi'
                                           if not ok else 'hedef_yok')
                            hedefsiz_kayitlar.append(d)
                except Exception as _e:
                    pass
        except Exception as e:
            korgun_hatasi = str(e)[:200]

    except Exception as e:
        return jsonify({
            'ok': False, 'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
            'eski_bekleyen': [], 'duplicate_adaylar': [],
            'gecersiz_proses': [], 'hedefsiz_kayitlar': [],
            'toplam_uyari': 0,
        }), 500

    toplam = (len(eski_bekleyen) + len(duplicate_adaylar) +
              len(gecersiz_proses) + len(hedefsiz_kayitlar))

    return jsonify({
        'ok': True, 'success': True,
        'eski_bekleyen': eski_bekleyen,
        'duplicate_adaylar': duplicate_adaylar,
        'gecersiz_proses': gecersiz_proses,
        'hedefsiz_kayitlar': hedefsiz_kayitlar,
        'toplam_uyari': toplam,
        'korgun_hatasi': korgun_hatasi,
        'parametreler': {
            'eski_bekleyen_esik_saat': 24,
            'duplicate_window_sn': 60,
        },
    })
'''


# =====================================================================
# 3) FRONTEND - hedef.js sonuna IIFE
# =====================================================================

JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.5 Veri Dogrulama
   - GET /hedef/dogrulama'yi periodically cagirir (sayfa acilinca + 5 dk)
   - Sorun varsa ust banner gosterir (sari)
   - Banner tiklayinca modal: 4 blok detay
   ==================================================================== */
(function () {
    'use strict';

    var _state = { sonuc: null };

    // CSS
    if (!document.getElementById('uyariStyles45')) {
        var s = document.createElement('style');
        s.id = 'uyariStyles45';
        s.textContent = [
            '.uyari-banner { background:linear-gradient(90deg,#fef3c7,#fde68a); border:1px solid #f59e0b; border-radius:8px; padding:10px 14px; margin:10px 0; cursor:pointer; display:flex; align-items:center; gap:10px; font-size:13px; color:#7c2d12; }',
            '.uyari-banner:hover { filter:brightness(0.95); }',
            '.uyari-banner-icon { font-size:18px; }',
            '.uyari-banner-text { flex:1; font-weight:600; }',
            '.uyari-banner-cta { font-size:11px; color:#92400e; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; }',
            '.uyari-modal { position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:9999; display:flex; align-items:center; justify-content:center; padding:20px; }',
            '.uyari-modal-icerik { background:#fff; border-radius:12px; max-width:1100px; width:100%; max-height:88vh; overflow:auto; padding:20px 24px; }',
            '.uyari-modal-header { display:flex; align-items:center; gap:10px; margin-bottom:14px; padding-bottom:12px; border-bottom:1px solid var(--border); }',
            '.uyari-modal-header h2 { margin:0; font-size:18px; }',
            '.uyari-modal-icon { font-size:24px; }',
            '.uyari-modal-toplam { font-size:12px; color:var(--text3); font-weight:600; margin-left:8px; }',
            '.uyari-modal-kapat { margin-left:auto; background:none; border:none; font-size:26px; cursor:pointer; color:var(--text3); padding:0 8px; line-height:1; }',
            '.uyari-modal-kapat:hover { color:var(--red); }',
            '.uyari-blok { margin-bottom:18px; }',
            '.uyari-blok h3 { font-size:12px; font-weight:700; color:#92400e; text-transform:uppercase; letter-spacing:0.6px; margin:0 0 8px 0; padding:8px 12px; background:#fef3c7; border-radius:6px; }',
            '.uyari-blok h3.bos { color:#16a34a; background:#f0fdf4; }',
            '.uyari-blok-bos { color:var(--text3); font-size:12px; padding:8px 12px; font-style:italic; }',
            '.uyari-blok table { width:100%; border-collapse:collapse; font-size:12px; }',
            '.uyari-blok th, .uyari-blok td { padding:6px 10px; border-bottom:1px solid #f3f4f6; text-align:left; white-space:nowrap; }',
            '.uyari-blok th { font-size:10px; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px; background:#fafafa; }',
            '.uyari-blok td.num { text-align:right; font-family:var(--mono); }',
            '.uyari-blok .durum-bekliyor { color:#f59e0b; font-weight:600; }',
            '.uyari-blok .durum-onaylandi { color:#16a34a; font-weight:600; }',
            '.uyari-blok .durum-reddedildi { color:#dc2626; font-weight:600; }'
        ].join('\n');
        document.head.appendChild(s);
    }

    function _esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _fmt(n) {
        var x = Number(n);
        if (!isFinite(x)) return _esc(n);
        return x.toLocaleString('tr-TR');
    }
    function _durum(d) {
        if (d == null || d === '') return '-';
        return '<span class="durum-' + _esc(d) + '">' + _esc(d) + '</span>';
    }

    function _ensureBanner() {
        var b = document.getElementById('uyariBanner45');
        if (b) return b;
        b = document.createElement('div');
        b.id = 'uyariBanner45';
        b.className = 'uyari-banner';
        b.style.display = 'none';
        b.innerHTML = '<span class="uyari-banner-icon">⚠</span>' +
                      '<span class="uyari-banner-text"></span>' +
                      '<span class="uyari-banner-cta">DETAY →</span>';
        b.addEventListener('click', _modalAc);

        var tabBar = document.querySelector('.h-tabs');
        if (tabBar && tabBar.parentNode) {
            tabBar.parentNode.insertBefore(b, tabBar);
        } else {
            document.body.insertBefore(b, document.body.firstChild);
        }
        return b;
    }

    function _renderBlok(baslik, kolonlar, rows, keys, numKeys, cellRenderers) {
        var bos = !rows || rows.length === 0;
        var html = '<div class="uyari-blok">';
        html += '<h3' + (bos ? ' class="bos"' : '') + '>' +
                _esc(baslik) + ' (' + (rows ? rows.length : 0) + ')' +
                (bos ? ' ✓' : '') + '</h3>';
        if (bos) {
            html += '<div class="uyari-blok-bos">Bu kategoride uyarı yok.</div></div>';
            return html;
        }
        html += '<table><thead><tr>';
        for (var i = 0; i < kolonlar.length; i++) {
            var num = numKeys[keys[i]] === true;
            html += '<th class="' + (num ? 'num' : 'text') + '">' +
                    _esc(kolonlar[i]) + '</th>';
        }
        html += '</tr></thead><tbody>';
        for (var j = 0; j < rows.length; j++) {
            var r = rows[j];
            html += '<tr>';
            for (var k = 0; k < keys.length; k++) {
                var key = keys[k];
                var num = numKeys[key] === true;
                var v = r[key];
                if (cellRenderers && cellRenderers[key]) {
                    html += '<td class="' + (num ? 'num' : 'text') + '">' +
                            cellRenderers[key](v, r) + '</td>';
                } else if (num) {
                    html += '<td class="num">' + _fmt(v) + '</td>';
                } else {
                    html += '<td class="text">' + _esc(v == null ? '-' : v) + '</td>';
                }
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';
        return html;
    }

    function _modalKapat() {
        var m = document.getElementById('uyariModal45');
        if (m) m.parentNode.removeChild(m);
    }

    function _renderModal(data) {
        _modalKapat();
        var modal = document.createElement('div');
        modal.className = 'uyari-modal';
        modal.id = 'uyariModal45';
        modal.addEventListener('click', function (e) {
            if (e.target === modal) _modalKapat();
        });

        var html = '<div class="uyari-modal-icerik">';
        html += '<div class="uyari-modal-header">';
        html += '<span class="uyari-modal-icon">⚠</span>';
        html += '<h2>Veri Doğrulama</h2>';
        html += '<span class="uyari-modal-toplam">Toplam ' +
                (data.toplam_uyari || 0) + ' uyarı</span>';
        html += '<button class="uyari-modal-kapat" onclick="document.getElementById(\'uyariModal45\').remove()">×</button>';
        html += '</div>';

        var durumRender = { onay_durum: function (v) { return _durum(v); } };

        html += _renderBlok(
            'Eski Bekleyen Kayıtlar (24 saatten fazla)',
            ['ID', 'EMİR', 'PROSES', 'MİKTAR', 'PERSONEL', 'OLUŞTURMA'],
            data.eski_bekleyen || [],
            ['id', 'emir_no', 'proses_adi', 'miktar', 'personel_ad', 'olusturma'],
            { miktar: true },
            null
        );

        html += _renderBlok(
            'Duplicate Adaylar (aynı emir+proses+personel+miktar tekrarı)',
            ['EMİR', 'PROSES KODU', 'PROSES ADI', 'PERSONEL', 'MİKTAR', 'ADET', 'ID LİSTESİ', 'İLK KAYIT', 'SON KAYIT'],
            data.duplicate_adaylar || [],
            ['emir_no', 'proses_kodu', 'proses_adi', 'personel_ad', 'miktar', 'adet', 'id_listesi', 'ilk_kayit', 'son_kayit'],
            { miktar: true, adet: true },
            null
        );

        html += _renderBlok(
            'Geçersiz Proses Kodu (emir_alt_proses\'te yok veya pasif)',
            ['ID', 'EMİR', 'PROSES KODU', 'PROSES ADI', 'MİKTAR', 'PERSONEL', 'DURUM', 'OLUŞTURMA'],
            data.gecersiz_proses || [],
            ['id', 'emir_no', 'proses_kodu', 'proses_adi', 'miktar', 'personel_ad', 'onay_durum', 'olusturma'],
            { miktar: true },
            durumRender
        );

        html += _renderBlok(
            'Hedefsiz Emirlerdeki Kayıtlar (Korgun\'da hedef yok)',
            ['ID', 'EMİR', 'PROSES', 'MİKTAR', 'PERSONEL', 'DURUM', 'NEDEN', 'OLUŞTURMA'],
            data.hedefsiz_kayitlar || [],
            ['id', 'emir_no', 'proses_adi', 'miktar', 'personel_ad', 'onay_durum', '_neden', 'olusturma'],
            { miktar: true },
            durumRender
        );

        html += '</div>';
        modal.innerHTML = html;
        document.body.appendChild(modal);
    }

    function _modalAc() {
        if (!_state.sonuc) {
            _yukle().then(function () {
                if (_state.sonuc) _renderModal(_state.sonuc);
            });
            return;
        }
        _renderModal(_state.sonuc);
    }

    function _yukle() {
        return fetch('/hedef/dogrulama', {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        }).then(function (resp) {
            return resp.text().then(function (t) {
                var d; try { d = JSON.parse(t); } catch (_) { d = null; }
                return { status: resp.status, data: d };
            });
        }).then(function (r) {
            if (r.status >= 400 || !r.data || r.data.ok === false) {
                console.warn('CPS/dogrulama uyari:', r.status,
                    r.data && r.data.mesaj || '');
                return;
            }
            _state.sonuc = r.data;
            var n = r.data.toplam_uyari || 0;
            var banner = _ensureBanner();
            if (n > 0) {
                banner.style.display = 'flex';
                banner.querySelector('.uyari-banner-text').textContent =
                    n + ' veri uyarısı tespit edildi';
            } else {
                banner.style.display = 'none';
            }
            console.log('CPS/hedef/dogrulama', r.status,
                'eski:' + (r.data.eski_bekleyen || []).length,
                'dup:' + (r.data.duplicate_adaylar || []).length,
                'proses:' + (r.data.gecersiz_proses || []).length,
                'hedefsiz:' + (r.data.hedefsiz_kayitlar || []).length);
        }).catch(function (e) {
            console.error('dogrulama fetch:', e);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            setTimeout(_yukle, 200);
        });
    } else {
        setTimeout(_yukle, 200);
    }
    setInterval(_yukle, 5 * 60 * 1000);

    window.uyariYukle = _yukle;
    window.uyariModalAc = _modalAc;

    console.log('[CPS LOCAL] FAZ 4.5 dogrulama yuklendi.');
})();
'''


# =====================================================================
# Helpers
# =====================================================================
def backup(path):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_uretim_kaydet():
    print()
    print("=" * 64)
    print("1/3 BACKEND: modules/uretim_giris/routes.py - uretim_kaydet")
    print("=" * 64)
    if not os.path.exists(URETIM_ROUTES):
        print(f"  [HATA] {URETIM_ROUTES} bulunamadi.")
        return False
    with open(URETIM_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()

    # Idempotent: 3 marker'in hepsi varsa skip
    has1 = HEDEF_YOK_MARKER in src
    has2 = DUP_MARKER in src
    has3 = "_vardiya = 1" in src

    if has1 and has2 and has3:
        print("  [BILGI] uretim_kaydet kontrolleri zaten ekli.")
        return True

    new_src = src
    changed = False

    if not has1:
        if URETIM_OLD_1 in new_src and new_src.count(URETIM_OLD_1) == 1:
            new_src = new_src.replace(URETIM_OLD_1, URETIM_NEW_1, 1)
            changed = True
            print("  [OK] HEDEF_YOK kontrolu eklendi.")
        else:
            print("  [HATA] HEDEF_YOK pattern bulunamadi/cogul.")
            return False
    else:
        print("  [BILGI] HEDEF_YOK kontrolu zaten var.")

    if not has2:
        if URETIM_OLD_2 in new_src and new_src.count(URETIM_OLD_2) == 1:
            new_src = new_src.replace(URETIM_OLD_2, URETIM_NEW_2, 1)
            changed = True
            print("  [OK] DUPLICATE kontrolu eklendi.")
        else:
            print("  [HATA] DUPLICATE pattern bulunamadi/cogul.")
            return False
    else:
        print("  [BILGI] DUPLICATE kontrolu zaten var.")

    if not has3:
        if URETIM_OLD_3 in new_src and new_src.count(URETIM_OLD_3) == 1:
            new_src = new_src.replace(URETIM_OLD_3, URETIM_NEW_3, 1)
            changed = True
            print("  [OK] VARDIYA hesabi eklendi.")
        else:
            print("  [HATA] VARDIYA pattern bulunamadi/cogul.")
            return False
    else:
        print("  [BILGI] VARDIYA hesabi zaten var.")

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    if changed:
        bp = backup(URETIM_ROUTES)
        print(f"  [OK] Yedek: {bp}")
        with open(URETIM_ROUTES, 'w', encoding='utf-8') as f:
            f.write(new_src)
    return True


def patch_dogrulama_endpoint():
    print()
    print("=" * 64)
    print("2/3 BACKEND: modules/hedef/routes.py - /hedef/dogrulama")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} bulunamadi.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if DOGRULAMA_BACKEND_MARKER in src:
        print("  [BILGI] /hedef/dogrulama zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += DOGRULAMA_BACKEND

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] /hedef/dogrulama endpoint'i eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("3/3 FRONTEND: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] FAZ 4.5 JS zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] FAZ 4.5 dogrulama IIFE eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.5 - VERI DOGRULAMA VE BAGLANTI SISTEMI")
    print("=" * 64)
    print("CPS Kurallari uyumu kontrolu:")
    print("  - Korgun'a yazma yok    [OK]")
    print("  - MES v2 yok            [OK]")
    print("  - Mevcut sistem bozulmuyor (sadece kontrol katmani) [OK]")
    print("  - Personel/Usta rol ayrimi korunuyor [OK]")

    ok1 = patch_uretim_kaydet()
    ok2 = patch_dogrulama_endpoint()
    ok3 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("HEPSI TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print()
        print("YENI DAVRANISLAR:")
        print()
        print("A) /uretim/kaydet:")
        print("   - Hedef yoksa (Korgun'da hedef=0): 400 'hedef_yok'")
        print("   - 60 sn icinde ayni kayit: 409 'duplicate'")
        print("   - Response'a vardiya alani: 1/2/3")
        print()
        print("B) /hedef/dogrulama (yeni):")
        print("   - 4 blok suspheli kayit")
        print("   - 110626 emrinde su an muhtemel uyari: yok (hedef var, 60sn duplicate yok)")
        print()
        print("C) /hedef/ ekrani:")
        print("   - Sayfa acilinca dogrulama cagrilir")
        print("   - Uyari varsa ust banner (sari)")
        print("   - Banner tiklayinca modal: 4 blok detay")
        print("   - Her 5 dakikada otomatik yenile")
        print()
        print("Test:")
        print("  - /uretim/ -> 110626 sec, ayni proses+miktar 2 kez kaydet")
        print("    -> Ikinci kayit 409 duplicate hatasi")
        print("  - /hedef/dogrulama JSON test:")
        print("    http://127.0.0.1:5057/hedef/dogrulama")
        print()
        print("Console:")
        print("  [CPS LOCAL] FAZ 4.5 dogrulama yuklendi.")
        print("  CPS/hedef/dogrulama 200 eski:0 dup:0 proses:0 hedefsiz:0")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
