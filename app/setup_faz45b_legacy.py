# -*- coding: utf-8 -*-
"""
setup_faz45b_legacy_mode.py
---------------------------
FAZ 4.5b - Legacy mode:
  - proses_kodu numeric DEGILSE 'legacy' say
  - gecersiz_proses listesinden cikar
  - Ayri 'legacy_kayitlar' bolumunde bilgi amacli goster
  - toplam_uyari sayisina dahil DEGIL
  - Hesaplamalara (PLAN/RAPOR) dokunulmaz, dahil olmaya devam

DOKUNMAZ:
  - mock_data.db veri (eski kayitlar oldugu gibi kalir)
  - PLAN/RAPOR hesabi (legacy kayitlar onayli ise toplama girer)
  - uretim_kaydet (zaten int(proses_kodu) yapip string'i 400'le reddediyor)
  - Diger endpoint/kontroller
"""

import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

BE_MARKER = "# === FAZ 4.5b: legacy_kayitlar ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.5b legacy mode"


# =====================================================================
# 1) BACKEND - hedef_dogrulama'daki gecersiz_proses sorgusunu degistir
#    + ayri legacy_kayitlar listesi ekle
# =====================================================================

# Mevcut sorguyu (FAZ 4.5'te eklenen) degistir.
# proses_kodu sadece tum karakterleri 0-9 ise 'numeric'.
# SQLite'da: proses_kodu GLOB '[0-9]*' AND proses_kodu NOT GLOB '*[^0-9]*'

BE_OLD = '''        # 3) Gecersiz proses (emir_alt_proses'te olmayan veya pasif)
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
        gecersiz_proses = [dict(r) for r in cur.fetchall()]'''

BE_NEW = '''        # 3) Gecersiz proses (sadece NUMERIC proses_kodu icin emir_alt_proses kontrol)
        # === FAZ 4.5b: legacy_kayitlar ===
        # proses_kodu tamamen 0-9 ise numeric kabul edilir.
        # Numeric olup emir_alt_proses'te yoksa -> gecersiz_proses (uyari)
        # Numeric DEGILSE -> legacy_kayitlar (bilgi amacli, uyari sayilmaz)
        cur.execute("""
            SELECT u.id, u.emir_no, u.proses_kodu, u.proses_adi,
                   u.miktar, u.personel_ad, u.onay_durum, u.olusturma
              FROM uretim_kayit u
              LEFT JOIN emir_alt_proses ap
                ON CAST(ap.id AS TEXT) = u.proses_kodu
               AND ap.emir_no = CAST(u.emir_no AS TEXT)
               AND ap.aktif = 1
             WHERE ap.id IS NULL
               AND u.proses_kodu IS NOT NULL
               AND u.proses_kodu != ''
               AND u.proses_kodu GLOB '[0-9]*'
               AND u.proses_kodu NOT GLOB '*[^0-9]*'
             ORDER BY u.id DESC
             LIMIT 100
        """)
        gecersiz_proses = [dict(r) for r in cur.fetchall()]

        # Legacy kayitlar (string proses_kodu, eski format)
        cur.execute("""
            SELECT u.id, u.emir_no, u.proses_kodu, u.proses_adi,
                   u.miktar, u.personel_ad, u.onay_durum, u.olusturma
              FROM uretim_kayit u
             WHERE u.proses_kodu IS NOT NULL
               AND u.proses_kodu != ''
               AND (u.proses_kodu NOT GLOB '[0-9]*'
                    OR u.proses_kodu GLOB '*[^0-9]*')
             ORDER BY u.id DESC
             LIMIT 100
        """)
        legacy_kayitlar = [dict(r) for r in cur.fetchall()]'''

# JSON return blokuna legacy_kayitlar ekle
BE_OLD_RET = '''    return jsonify({
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
    })'''

BE_NEW_RET = '''    return jsonify({
        'ok': True, 'success': True,
        'eski_bekleyen': eski_bekleyen,
        'duplicate_adaylar': duplicate_adaylar,
        'gecersiz_proses': gecersiz_proses,
        'hedefsiz_kayitlar': hedefsiz_kayitlar,
        'legacy_kayitlar': legacy_kayitlar,
        'legacy_sayisi': len(legacy_kayitlar),
        'toplam_uyari': toplam,
        'korgun_hatasi': korgun_hatasi,
        'parametreler': {
            'eski_bekleyen_esik_saat': 24,
            'duplicate_window_sn': 60,
        },
    })'''


# =====================================================================
# 2) FRONTEND - modal'a legacy bloku ekle
# =====================================================================

JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.5b: Legacy mode
   - Modal'a 5. blok 'Legacy Kayitlar' (gri, bilgi amacli)
   - Modal sayisini 'toplam_uyari' (4 blok) + 'legacy_sayisi' ayri goster
   - window.uyariModalAc'i override eder (eski v4.5 modal yerine)
   ==================================================================== */
(function () {
    'use strict';

    if (!document.getElementById('legacyStyles45b')) {
        var s = document.createElement('style');
        s.id = 'legacyStyles45b';
        s.textContent = [
            '.uyari-blok h3.legacy { color:#6b7280; background:#f3f4f6; }',
            '.uyari-blok .legacy-rozet { display:inline-block; background:#9ca3af; color:#fff; padding:2px 6px; border-radius:4px; font-size:9px; font-weight:700; letter-spacing:0.5px; margin-left:4px; }',
            '.uyari-blok tr.legacy-row { color:#6b7280; background:#fafafa; }',
            '.uyari-blok tr.legacy-row td.text { font-style:italic; }',
            '.uyari-modal-legacy-sayisi { font-size:11px; color:#6b7280; margin-left:8px; padding:2px 8px; background:#f3f4f6; border-radius:10px; }'
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

    function _modalKapat() {
        var m = document.getElementById('uyariModal45');
        if (m && m.parentNode) m.parentNode.removeChild(m);
    }

    function _renderBlok(baslik, kolonlar, rows, keys, numKeys, opts) {
        opts = opts || {};
        var bos = !rows || rows.length === 0;
        var html = '<div class="uyari-blok">';
        html += '<h3' + (opts.legacy ? ' class="legacy"' : (bos ? ' class="bos"' : '')) + '>' +
                _esc(baslik) + ' (' + (rows ? rows.length : 0) + ')' +
                (bos ? ' ✓' : '') +
                (opts.legacy ? ' <span class="legacy-rozet">LEGACY</span>' : '') +
                '</h3>';
        if (bos) {
            html += '<div class="uyari-blok-bos">' +
                    (opts.legacy ? 'Eski format kayit yok.' : 'Bu kategoride uyarı yok.') +
                    '</div></div>';
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
            html += '<tr' + (opts.legacy ? ' class="legacy-row"' : '') + '>';
            for (var k = 0; k < keys.length; k++) {
                var key = keys[k];
                var num = numKeys[key] === true;
                var v = r[key];
                if (key === 'onay_durum') {
                    html += '<td class="text">' + _durum(v) + '</td>';
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

    function _renderModal(data) {
        _modalKapat();
        var modal = document.createElement('div');
        modal.className = 'uyari-modal';
        modal.id = 'uyariModal45';
        modal.addEventListener('click', function (e) {
            if (e.target === modal) _modalKapat();
        });

        var legacySayisi = data.legacy_sayisi || (data.legacy_kayitlar || []).length;

        var html = '<div class="uyari-modal-icerik">';
        html += '<div class="uyari-modal-header">';
        html += '<span class="uyari-modal-icon">⚠</span>';
        html += '<h2>Veri Doğrulama</h2>';
        html += '<span class="uyari-modal-toplam">Toplam ' +
                (data.toplam_uyari || 0) + ' uyarı</span>';
        if (legacySayisi > 0) {
            html += '<span class="uyari-modal-legacy-sayisi">' +
                    legacySayisi + ' legacy kayıt</span>';
        }
        html += '<button class="uyari-modal-kapat" onclick="document.getElementById(\'uyariModal45\').remove()">×</button>';
        html += '</div>';

        html += _renderBlok(
            'Eski Bekleyen Kayıtlar (24 saatten fazla)',
            ['ID', 'EMİR', 'PROSES', 'MİKTAR', 'PERSONEL', 'OLUŞTURMA'],
            data.eski_bekleyen || [],
            ['id', 'emir_no', 'proses_adi', 'miktar', 'personel_ad', 'olusturma'],
            { miktar: true }
        );

        html += _renderBlok(
            'Duplicate Adaylar (aynı emir+proses+personel+miktar tekrarı)',
            ['EMİR', 'PROSES KODU', 'PROSES ADI', 'PERSONEL', 'MİKTAR', 'ADET', 'ID LİSTESİ', 'İLK', 'SON'],
            data.duplicate_adaylar || [],
            ['emir_no', 'proses_kodu', 'proses_adi', 'personel_ad', 'miktar', 'adet', 'id_listesi', 'ilk_kayit', 'son_kayit'],
            { miktar: true, adet: true }
        );

        html += _renderBlok(
            'Geçersiz Proses Kodu (numeric ama emir_alt_proses\'te yok)',
            ['ID', 'EMİR', 'PROSES KODU', 'PROSES ADI', 'MİKTAR', 'PERSONEL', 'DURUM', 'OLUŞTURMA'],
            data.gecersiz_proses || [],
            ['id', 'emir_no', 'proses_kodu', 'proses_adi', 'miktar', 'personel_ad', 'onay_durum', 'olusturma'],
            { miktar: true }
        );

        html += _renderBlok(
            'Hedefsiz Emirlerdeki Kayıtlar (Korgun\'da hedef yok)',
            ['ID', 'EMİR', 'PROSES', 'MİKTAR', 'PERSONEL', 'DURUM', 'NEDEN', 'OLUŞTURMA'],
            data.hedefsiz_kayitlar || [],
            ['id', 'emir_no', 'proses_adi', 'miktar', 'personel_ad', 'onay_durum', '_neden', 'olusturma'],
            { miktar: true }
        );

        html += _renderBlok(
            'Legacy Kayıtlar (eski string proses_kodu, kontrol dışı)',
            ['ID', 'EMİR', 'PROSES KODU', 'PROSES ADI', 'MİKTAR', 'PERSONEL', 'DURUM', 'OLUŞTURMA'],
            data.legacy_kayitlar || [],
            ['id', 'emir_no', 'proses_kodu', 'proses_adi', 'miktar', 'personel_ad', 'onay_durum', 'olusturma'],
            { miktar: true },
            { legacy: true }
        );

        html += '</div>';
        modal.innerHTML = html;
        document.body.appendChild(modal);
    }

    // Eski v4.5 fonksiyonunun yerine yeni modal acici
    window.uyariModalAc = function () {
        // _state v4.5 IIFE'sinde tutuluyor; biz fetch tekrar yapalim
        fetch('/hedef/dogrulama', {
            method: 'GET', credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        }).then(function (r) {
            return r.text().then(function (t) {
                var d; try { d = JSON.parse(t); } catch (_) { d = null; }
                return { status: r.status, data: d };
            });
        }).then(function (r) {
            if (r.status >= 400 || !r.data || r.data.ok === false) {
                alert('Doğrulama yüklenemedi.');
                return;
            }
            _renderModal(r.data);
        }).catch(function (e) {
            console.error('legacy modal fetch:', e);
            alert('Sunucuya ulaşılamadı.');
        });
    };

    console.log('[CPS LOCAL] FAZ 4.5b legacy mode yuklendi.');
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


def patch_backend():
    print()
    print("=" * 64)
    print("1/2 BACKEND: modules/hedef/routes.py (legacy filtre)")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} bulunamadi.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if BE_MARKER in src:
        print("  [BILGI] FAZ 4.5b zaten ekli.")
        return True

    if BE_OLD not in src:
        print("  [HATA] BE_OLD blok bulunamadi.")
        return False
    if src.count(BE_OLD) > 1:
        print("  [HATA] BE_OLD birden fazla.")
        return False
    if BE_OLD_RET not in src:
        print("  [HATA] BE_OLD_RET blok bulunamadi.")
        return False
    if src.count(BE_OLD_RET) > 1:
        print("  [HATA] BE_OLD_RET birden fazla.")
        return False

    new_src = src.replace(BE_OLD, BE_NEW, 1).replace(BE_OLD_RET, BE_NEW_RET, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] gecersiz_proses sadece numeric, legacy_kayitlar ayri.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: static/js/hedef.js (legacy modal)")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] FAZ 4.5b JS zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Modal override: legacy_kayitlar 5. blok eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.5b - LEGACY MODE")
    print("=" * 64)
    print("Plan:")
    print("  - proses_kodu numeric DEGIL ise legacy")
    print("  - gecersiz_proses listesinden cikar (sadece numeric kalir)")
    print("  - 5. blok 'Legacy Kayitlar' (gri, bilgi amacli)")
    print("  - toplam_uyari sayisi DUSER (3 -> 0 beklenen)")
    print()

    ok1 = patch_backend()
    ok2 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2:
        print("HEPSI TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print()
        print("Beklenen JSON (http://127.0.0.1:5057/hedef/dogrulama):")
        print('  toplam_uyari    : 0  (eski 3 kayit artik gecersiz_proses\'te DEGIL)')
        print('  legacy_sayisi   : 3  (Monta/Enjeksiyon/Kesim)')
        print('  legacy_kayitlar : 3 satir (id 1,2,3)')
        print('  gecersiz_proses : []')
        print()
        print("UI:")
        print("  - Sari banner gizli (toplam_uyari=0)")
        print("  - Modal acmak icin: window.uyariModalAc() console'da")
        print("  - Modal'da 5 blok, sonuncusu gri 'LEGACY' rozetli")
        print()
        print("Hesaplamalar BOZULMAZ:")
        print("  - PLAN/RAPOR'da legacy onayli kayitlar TOPLAMA dahil")
        print("  - 1.490 toplam, 4 kayit aynen kalir")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
