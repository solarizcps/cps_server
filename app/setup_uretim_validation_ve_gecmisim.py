# -*- coding: utf-8 -*-
"""
setup_uretim_validation_ve_gecmisim.py
--------------------------------------
4A) modules/uretim_giris/routes.py:uretim_kaydet'e proses_id validasyonu ekle
4B) modules/uretim_giris/routes.py'a GET /uretim/gecmisim endpoint ekle
4C) static/js/uretim_giris.js'e GECMISIM lazy-load + render + yenile bagla

Tum islemler idempotent (marker kontrolu).

DOKUNMAZ:
  - GET /uretim/emir/<no>
  - GET /uretim/emir/<no>/prosesler
  - GET /uretim/proxy/<path>
  - mevcut /uretim/kaydet hedef-asimi/Korgun mantigi
  - /hedef/ endpoint'leri
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
ROUTES_PATH = os.path.join(CPS_ROOT, "modules", "uretim_giris", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "uretim_giris.js")

VALIDATION_MARKER = "# === Proses_id validasyonu (mock_data.db.emir_alt_proses) ==="
GECMISIM_MARKER = "# === CPS LOCAL /uretim/gecmisim ENDPOINT ==="
JS_MARKER = "[CPS LOCAL] /uretim/ gecmisim yukleyici hazir"


# ---------------------------------------------------------------------
# 4A) uretim_kaydet'e validasyon ekle
# ---------------------------------------------------------------------
# str_replace ile: 'gecersiz_miktar' return'unun hemen ardina, mevcut
# 'Korgun'dan emir bilgisi' yorum satirindan once.

VAL_OLD = """        try:
            miktar = int(miktar)
            if miktar <= 0: raise ValueError()
        except Exception:
            return _jsonify_uk({'ok': False, 'hata': 'gecersiz_miktar',
                                'mesaj': 'Miktar pozitif olmali'}), 400

        # Korgun'dan emir bilgisi (hedef/kalan icin)"""

VAL_NEW = """        try:
            miktar = int(miktar)
            if miktar <= 0: raise ValueError()
        except Exception:
            return _jsonify_uk({'ok': False, 'hata': 'gecersiz_miktar',
                                'mesaj': 'Miktar pozitif olmali'}), 400

        # === Proses_id validasyonu (mock_data.db.emir_alt_proses) ===
        if not proses_kodu:
            return _jsonify_uk({'ok': False, 'hata': 'proses_eksik',
                                'mesaj': 'Proses secimi zorunlu'}), 400
        try:
            _pid_int = int(proses_kodu)
        except Exception:
            return _jsonify_uk({'ok': False, 'hata': 'gecersiz_proses',
                                'mesaj': 'proses_kodu sayisal olmali'}), 400
        _con_chk = _sqlite_uk.connect(_Config_uk.MOCK_DB_PATH)
        try:
            _row_chk = _con_chk.execute(
                "SELECT id, proses_adi FROM emir_alt_proses "
                "WHERE id = ? AND emir_no = ? AND aktif = 1",
                (_pid_int, str(emir_no))
            ).fetchone()
        finally:
            _con_chk.close()
        if not _row_chk:
            return _jsonify_uk({'ok': False, 'hata': 'gecersiz_proses',
                                'mesaj': 'Bu proses bu emire ait degil veya pasif'}), 400
        # DB'deki ad ile override (frontend yanlis gondermisse bile guvende)
        if _row_chk[1]:
            proses_adi = _row_chk[1]

        # Korgun'dan emir bilgisi (hedef/kalan icin)"""


# ---------------------------------------------------------------------
# 4B) /uretim/gecmisim endpoint
# ---------------------------------------------------------------------
GECMISIM_BLOCK = '''


# === CPS LOCAL /uretim/gecmisim ENDPOINT ===
# Login olan personelin son uretim kayitlari (mock_data.db.uretim_kayit)

@uretim_giris_bp.route('/gecmisim', methods=['GET'])
@uretim_yetkili
def uretim_gecmisim():
    """GET /uretim/gecmisim - Login personelin son uretim kayitlari."""
    try:
        try:
            limit = int(_request_uk.args.get('limit', 50))
            if limit <= 0 or limit > 500:
                limit = 50
        except Exception:
            limit = 50

        u = _session_uk.get('kullanici', {}) or {}
        personel_id = u.get('Id')

        kayitlar = []
        if personel_id:
            con = _sqlite_uk.connect(_Config_uk.MOCK_DB_PATH)
            try:
                con.row_factory = _sqlite_uk.Row
                rows = con.execute("""
                    SELECT id, emir_no, model_kod, model_adi,
                           miktar, proses_kodu, proses_adi,
                           personel_id, personel_ad,
                           tarih, saat, not_metin,
                           onay_durum, usta_id, usta_ad, usta_not,
                           onay_tarihi, olusturma
                      FROM uretim_kayit
                     WHERE personel_id = ?
                     ORDER BY olusturma DESC, id DESC
                     LIMIT ?
                """, (personel_id, limit)).fetchall()
                kayitlar = [dict(r) for r in rows]
            finally:
                con.close()

        return _jsonify_uk({
            'ok': True, 'success': True,
            'kayitlar': kayitlar,
            'kayit_sayisi': len(kayitlar),
            'limit': limit
        }), 200
    except Exception as e:
        return _jsonify_uk({'ok': False, 'hata': 'sistem_hatasi',
                            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'}), 500
'''


# ---------------------------------------------------------------------
# 4C) Frontend: uretim_giris.js'e gecmisim yukleyici
# ---------------------------------------------------------------------
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL — /uretim/ GECMISIM yukleyici
   - Tab 'gecmis' tiklaninca lazy-load
   - gecmisYenileBtn ile manuel yenileme
   - Endpoint: GET /uretim/gecmisim
   ==================================================================== */
(function () {
    'use strict';

    function _ugEsc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _ugTarihSaat(k) {
        var t = k.tarih || '';
        var s = k.saat || '';
        if (t && s) return t + ' ' + s;
        return t || s || (k.olusturma || '');
    }

    function _ugDurumStil(durum) {
        if (durum === 'onaylandi') return { renk: '#10b981', txt: 'ONAYLANDI' };
        if (durum === 'reddedildi') return { renk: '#dc2626', txt: 'REDDEDİLDİ' };
        return { renk: '#f59e0b', txt: 'BEKLİYOR' };
    }

    function _ugRenderGecmisim(rows) {
        var listEl = document.getElementById('gecmisListe');
        if (!listEl) return;
        if (!rows || rows.length === 0) {
            listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#888;">Henüz üretim kaydın yok.</div>';
            return;
        }
        var html = '';
        for (var i = 0; i < rows.length; i++) {
            var k = rows[i];
            var ds = _ugDurumStil(k.onay_durum);
            var ustaNotEk = k.usta_not
                ? '<div style="margin-top:8px; padding:8px 10px; background:rgba(220,38,38,0.06); border-radius:6px; font-size:13px; line-height:1.4;"><strong style="color:#dc2626;">Usta notu:</strong> ' + _ugEsc(k.usta_not) + '</div>'
                : '';
            var notEk = k.not_metin
                ? '<div style="margin-top:6px; font-size:12px; color:#666; font-style:italic;">Not: ' + _ugEsc(k.not_metin) + '</div>'
                : '';
            var onayZamanEk = (k.onay_durum !== 'bekliyor' && k.onay_tarihi)
                ? '<div style="margin-top:4px; font-size:11px; color:#888; font-family:monospace;">' + _ugEsc(k.onay_tarihi) + (k.usta_ad ? ' • ' + _ugEsc(k.usta_ad) : '') + '</div>'
                : '';
            html +=
                '<div class="ug-gecmis-card" style="background:#fff; border-radius:12px; padding:14px 16px; margin-bottom:10px; box-shadow:0 2px 6px rgba(0,0,0,0.05); border-left:4px solid ' + ds.renk + ';">' +
                    '<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; gap:12px;">' +
                        '<div style="min-width:0;">' +
                            '<div style="font-weight:700; font-size:15px;">E.' + _ugEsc(k.emir_no) + '</div>' +
                            '<div style="font-size:12px; color:#666; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + _ugEsc(k.model_kod || '') + '</div>' +
                        '</div>' +
                        '<div style="background:' + ds.renk + '; color:#fff; padding:4px 10px; border-radius:12px; font-size:11px; font-weight:700; letter-spacing:0.5px; white-space:nowrap;">' + ds.txt + '</div>' +
                    '</div>' +
                    '<div style="display:grid; grid-template-columns:1fr 1fr; gap:8px 16px; font-size:13px;">' +
                        '<div><span style="color:#888;">Proses:</span> <strong>' + _ugEsc(k.proses_adi || '-') + '</strong></div>' +
                        '<div><span style="color:#888;">Miktar:</span> <strong>' + _ugEsc(k.miktar) + '</strong> çift</div>' +
                        '<div style="grid-column:1/-1; color:#888; font-family:monospace; font-size:12px;">' + _ugEsc(_ugTarihSaat(k)) + '</div>' +
                    '</div>' +
                    notEk + ustaNotEk + onayZamanEk +
                '</div>';
        }
        listEl.innerHTML = html;
    }

    function _ugGecmisimYukle() {
        var listEl = document.getElementById('gecmisListe');
        var errEl = document.getElementById('gecmisError');
        if (errEl) errEl.style.display = 'none';
        if (listEl) {
            listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#888;">Yükleniyor...</div>';
        }
        fetch('/uretim/gecmisim?limit=100', {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(function (resp) {
                return resp.text().then(function (t) {
                    var data;
                    try { data = JSON.parse(t); } catch (_) { data = null; }
                    return { status: resp.status, data: data };
                });
            })
            .then(function (r) {
                if (r.status >= 400 || !r.data || r.data.ok === false) {
                    if (listEl) {
                        listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#dc2626;">Geçmiş yüklenemedi.</div>';
                    }
                    window._gecmisimYuklendi = false;
                    return;
                }
                var kayitlar = (r.data && r.data.kayitlar) || [];
                _ugRenderGecmisim(kayitlar);
                window._gecmisimYuklendi = true;
                console.log('CPS/uretim/gecmisim', r.status, kayitlar.length);
            })
            .catch(function (e) {
                console.error('gecmisim fetch:', e);
                if (listEl) {
                    listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#dc2626;">Sunucuya ulaşılamadı.</div>';
                }
                window._gecmisimYuklendi = false;
            });
    }

    // Globale ac (button onclick veya disaridan cagri icin)
    window.gecmisimYukle = _ugGecmisimYukle;
    window.renderGecmisim = _ugRenderGecmisim;

    document.addEventListener('DOMContentLoaded', function () {
        // GECMISIM tab'i tiklaninca lazy-load
        var gt = document.querySelector('.ug-tab[data-tab="gecmis"]');
        if (gt) {
            gt.addEventListener('click', function () {
                if (!window._gecmisimYuklendi) {
                    _ugGecmisimYukle();
                }
            });
        }

        // Yenile butonu
        var rb = document.getElementById('gecmisYenileBtn');
        if (rb) {
            rb.addEventListener('click', function () {
                window._gecmisimYuklendi = false;
                _ugGecmisimYukle();
            });
        }
    });

    console.log('[CPS LOCAL] /uretim/ gecmisim yukleyici hazir.');
})();
'''


def backup(path):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_validation():
    print()
    print("=" * 64)
    print("4A) uretim_kaydet -> proses_id validasyonu")
    print("=" * 64)
    if not os.path.exists(ROUTES_PATH):
        print(f"  [HATA] {ROUTES_PATH} bulunamadi.")
        return False

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if VALIDATION_MARKER in src:
        print("  [BILGI] Validasyon zaten ekli (marker var).")
        return True

    if VAL_OLD not in src:
        print("  [HATA] Eslesen blok bulunamadi (VAL_OLD).")
        print("         uretim_kaydet handler degisikligi gerek.")
        return False

    if src.count(VAL_OLD) > 1:
        print("  [HATA] Eslesen blok birden fazla.")
        return False

    new_src = src.replace(VAL_OLD, VAL_NEW, 1)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] Yeni icerik parse edilemiyor: {e}")
        return False

    bp = backup(ROUTES_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Validasyon eklendi: proses_id zorunlu, emir_alt_proses kontrolu.")
    return True


def patch_gecmisim_endpoint():
    print()
    print("=" * 64)
    print("4B) GET /uretim/gecmisim endpoint")
    print("=" * 64)

    with open(ROUTES_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if GECMISIM_MARKER in src:
        print("  [BILGI] Endpoint zaten ekli (marker var).")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += GECMISIM_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] Yeni icerik parse edilemiyor: {e}")
        return False

    bp = backup(ROUTES_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(ROUTES_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] /uretim/gecmisim endpoint'i eklendi (limit=50, max 500).")
    return True


def patch_frontend():
    print()
    print("=" * 64)
    print("4C) FRONTEND: uretim_giris.js -> GECMISIM yukleyici")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False

    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    if JS_MARKER in src:
        print("  [BILGI] JS zaten patchli (marker var).")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] gecmisimYukle + render + tab/yenile event'leri eklendi.")
    return True


def main():
    ok1 = patch_validation()
    ok2 = patch_gecmisim_endpoint()
    ok3 = patch_frontend()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("HEPSI TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /uretim/ -> 110626 sorgu -> proses sec -> miktar -> KAYDET")
        print("     (Validasyon arkada calisir; proses zorunlu, emir_alt_proses'te")
        print("      kayitli olmaliydi -> hep gecerli proses sectigin icin sorun yok)")
        print("  4) GECMISIM sekmesine tikla -> 4 kayit gorulmeli (en yeni ustte)")
        print("     Kart-list goruntusu, durum renkleriyle (sari/yesil/kirmizi)")
        print("  5) Yenile butonu (kart sag uzerindeki refresh ikonu) -> tekrar yukler")
        print()
        print("Test sirasinda DevTools Console'a bak:")
        print("  [CPS LOCAL] /uretim/ gecmisim yukleyici hazir.")
        print("  CPS/uretim/gecmisim 200 N")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
