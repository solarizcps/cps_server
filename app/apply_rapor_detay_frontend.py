# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF RAPOR DETAY FRONTEND (FAZ 6.2)
================================================

YAPILACAK:
  static/js/hedef.js dosyasının SONUNA bağımsız IIFE bloğu eklenir.
  
  IIFE blogu:
    - window.__faz62_rapor_detay guard (idempotent)
    - raporFiltreleBtn click intercept
    - data-tab="rapor" tıklama intercept
    - GET /hedef/rapor (mevcut endpoint, kayit_listesi alanı kullanılır)
    - pane-rapor altına yeni 'rapor-detay-div' enjekte eder
    - Detay tablo: emir, proses, miktar, personel, tarih, saat, onay, usta, not

DOKUNULMAYAN:
  - Mevcut 9 rapor fonksiyonu (renderRaporRows, _yukleRapor, _renderRapor vs)
  - 2 mevcut /hedef/rapor fetch noktası
  - Mevcut raporBody render mantığı
  - 3 ozet kart (personel/proses/emir bazlı)
  - Sapma, Onaylar, Geçmiş, Plan, Sablon vb diğer sekmeler
  - Backend (zaten FAZ 6.2 ile kayit_listesi dönüyor)

Idempotent: 'FAZ 6.2 - Rapor Detay Liste' marker varsa SKIP.
Yedek: hedef.js.YEDEK_FAZ62_<ts>
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_JS = PROJECT_ROOT / "static" / "js" / "hedef.js"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# IIFE BLOK - hedef.js sonuna eklenecek
# ============================================================
IIFE_BLOCK = '''

/* ============================================================
   FAZ 6.2 - Rapor Detay Liste (IIFE - mevcut kodu etkilemez)
   ============================================================ */
(function() {
    "use strict";
    if (window.__faz62_rapor_detay) return;
    window.__faz62_rapor_detay = true;

    var DETAY_DIV_ID = 'rapor-detay-div-faz62';
    var loading = false;
    var lastBas = null;
    var lastBit = null;

    function escHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function getOrCreateDetayDiv() {
        var existing = document.getElementById(DETAY_DIV_ID);
        if (existing) return existing;

        var paneRapor = document.getElementById('pane-rapor');
        if (!paneRapor) return null;

        var div = document.createElement('div');
        div.id = DETAY_DIV_ID;
        div.style.cssText = 'margin-top:24px;padding:16px;background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;';
        paneRapor.appendChild(div);
        return div;
    }

    function renderDetayTable(rows) {
        var div = getOrCreateDetayDiv();
        if (!div) return;

        if (!rows || rows.length === 0) {
            div.innerHTML = '<h3 style="margin:0 0 12px 0;font-size:14px;font-weight:600;color:#333;">Detay Liste</h3>'
                + '<div style="text-align:center;color:#888;padding:20px;font-size:13px;">Detay kaydi yok</div>';
            return;
        }

        var html = '<h3 style="margin:0 0 12px 0;font-size:14px;font-weight:600;color:#333;">'
                 + 'Detay Liste <span style="font-weight:400;color:#888;">(' + rows.length + ' kayit)</span></h3>';
        html += '<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">';
        html += '<table style="width:100%;min-width:780px;border-collapse:collapse;font-size:12px;">';
        html += '<thead><tr style="background:#f0f0f0;border-bottom:2px solid #ccc;">'
              + '<th style="text-align:left;padding:8px 8px;white-space:nowrap;">Emir</th>'
              + '<th style="text-align:left;padding:8px 8px;white-space:nowrap;">Proses</th>'
              + '<th style="text-align:right;padding:8px 8px;white-space:nowrap;">Miktar</th>'
              + '<th style="text-align:left;padding:8px 8px;white-space:nowrap;">Personel</th>'
              + '<th style="text-align:left;padding:8px 8px;white-space:nowrap;">Tarih</th>'
              + '<th style="text-align:left;padding:8px 8px;white-space:nowrap;">Saat</th>'
              + '<th style="text-align:center;padding:8px 8px;white-space:nowrap;">Onay</th>'
              + '<th style="text-align:left;padding:8px 8px;white-space:nowrap;">Usta</th>'
              + '<th style="text-align:left;padding:8px 8px;">Not</th>'
              + '</tr></thead><tbody>';

        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            var durum = r.onay_durum || '';
            var durumColor = '#999';
            var durumBg = '#f5f5f5';
            if (durum === 'onaylandi') {
                durumColor = '#2e7d32';
                durumBg = '#e8f5e9';
            } else if (durum === 'bekliyor') {
                durumColor = '#e65100';
                durumBg = '#fff3e0';
            } else if (durum === 'reddedildi') {
                durumColor = '#c62828';
                durumBg = '#ffebee';
            }
            var note = r.not_metin || r.usta_not || '';

            html += '<tr style="border-bottom:1px solid #eee;">'
                  + '<td style="padding:6px 8px;font-weight:500;">' + escHtml(r.emir_no) + '</td>'
                  + '<td style="padding:6px 8px;">' + escHtml(r.proses_adi || '-') + '</td>'
                  + '<td style="padding:6px 8px;text-align:right;font-weight:600;color:#1976d2;">' + escHtml(r.miktar) + '</td>'
                  + '<td style="padding:6px 8px;">' + escHtml(r.personel_ad) + '</td>'
                  + '<td style="padding:6px 8px;color:#555;">' + escHtml(r.tarih) + '</td>'
                  + '<td style="padding:6px 8px;color:#555;">' + escHtml(r.saat) + '</td>'
                  + '<td style="padding:6px 8px;text-align:center;">'
                  + '<span style="display:inline-block;padding:2px 8px;border-radius:10px;background:' + durumBg + ';color:' + durumColor + ';font-size:11px;font-weight:500;">'
                  + escHtml(durum)
                  + '</span></td>'
                  + '<td style="padding:6px 8px;color:#555;">' + escHtml(r.usta_ad || '-') + '</td>'
                  + '<td style="padding:6px 8px;color:#666;font-size:11px;">' + escHtml(note) + '</td>'
                  + '</tr>';
        }
        html += '</tbody></table></div>';
        div.innerHTML = html;
    }

    function loadDetay() {
        if (loading) return;
        loading = true;

        try {
            var inpBas = document.getElementById('raporTarihBas');
            var inpBit = document.getElementById('raporTarihBit');
            var bas = (inpBas && inpBas.value) || '';
            var bit = (inpBit && inpBit.value) || '';
            var url = '/hedef/rapor';
            var params = [];
            if (bas) params.push('baslangic=' + encodeURIComponent(bas));
            if (bit) params.push('bitis=' + encodeURIComponent(bit));
            if (params.length) url += '?' + params.join('&');

            lastBas = bas;
            lastBit = bit;

            // Loading goster
            var div = getOrCreateDetayDiv();
            if (div) {
                div.innerHTML = '<div style="text-align:center;color:#888;padding:20px;font-size:13px;">Detay liste yukleniyor...</div>';
            }

            fetch(url, { credentials: 'same-origin' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var rows = (data && data.kayit_listesi) || [];
                    renderDetayTable(rows);
                })
                .catch(function(err) {
                    console.warn('FAZ 6.2 rapor detay yukleme hatasi:', err);
                    var div2 = getOrCreateDetayDiv();
                    if (div2) {
                        div2.innerHTML = '<div style="color:#c62828;padding:12px;font-size:13px;">Detay liste yuklenemedi</div>';
                    }
                })
                .finally(function() {
                    loading = false;
                });
        } catch (e) {
            loading = false;
            console.warn('FAZ 6.2 hata:', e);
        }
    }

    function setupListeners() {
        // 1. Filtrele butonu intercept
        var btn = document.getElementById('raporFiltreleBtn');
        if (btn && !btn.__faz62_bound) {
            btn.__faz62_bound = true;
            btn.addEventListener('click', function() {
                setTimeout(loadDetay, 350); // Mevcut render bitsin
            });
        }

        // 2. Tab tiklamalarini izle (rapor sekmesine geçince yükle)
        document.addEventListener('click', function(e) {
            var target = e.target && (e.target.closest && e.target.closest('[data-tab="rapor"], [data-sekme="rapor"], [data-target="rapor"]'));
            if (target) {
                setTimeout(loadDetay, 600);
            }
        }, true);

        // 3. Sayfa yuklendiginde rapor sekmesi zaten aktifse yukle
        var paneRapor = document.getElementById('pane-rapor');
        if (paneRapor) {
            var aktif = paneRapor.classList && (paneRapor.classList.contains('active') || paneRapor.classList.contains('show'));
            if (aktif) {
                setTimeout(loadDetay, 800);
            }
        }
    }

    // DOM hazır olduğunda baglan
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupListeners);
    } else {
        setupListeners();
    }

    // Diagnostik: console.info ile bildir
    try { console.info('[FAZ 6.2] Rapor Detay Liste aktif'); } catch (e) {}
})();
/* === FAZ 6.2 SONU === */
'''


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF RAPOR DETAY FRONTEND (FAZ 6.2)")
    print("=" * 60)

    if not TARGET_JS.exists():
        print(f"  [HATA] dosya yok: {TARGET_JS}")
        return 1

    content = TARGET_JS.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT
    # ============================================================
    if 'FAZ 6.2 - Rapor Detay Liste' in content or '__faz62_rapor_detay' in content:
        print()
        print("  [SKIP] FAZ 6.2 marker var, IIFE zaten eklenmis.")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    # Mevcut render fonksiyonlari hala var mi (paranoia check)
    paranoia_checks = [
        '_renderRapor',
        '_yukleRapor',
        'raporlariYukle',
        '/hedef/rapor',
    ]
    for check in paranoia_checks:
        if check in content:
            print(f"  [OK] '{check}' mevcut (dokunulmayacak)")
        else:
            print(f"  [UYARI] '{check}' yok - yine de devam")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_JS.with_suffix(f".js.YEDEK_FAZ62_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_JS), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA - DOSYA SONUNA APPEND
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    # Sonunda \n var mi kontrol et
    if not content.endswith('\n'):
        new_content = content + '\n' + IIFE_BLOCK
    else:
        new_content = content + IIFE_BLOCK

    print("  [OK] IIFE blogu hedef.js sonuna eklendi")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_JS.write_text(new_content, encoding="utf-8")
    new_size = TARGET_JS.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: +{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_JS.read_text(encoding="utf-8")

    checks = [
        ('FAZ 6.2 - Rapor Detay Liste', 'Marker var'),
        ('__faz62_rapor_detay', 'Idempotent guard'),
        ('rapor-detay-div-faz62', 'Detay div ID'),
        ('kayit_listesi', 'Backend alani okuyor'),
        ('raporFiltreleBtn', 'Filtrele buton intercept'),
        ('data-tab="rapor"', 'Tab listener'),
        ('pane-rapor', 'pane-rapor hedefi'),
        ('escHtml', 'XSS escape fonksiyonu'),
        # Mevcut kod KORUNDU
        ('_renderRapor', 'Mevcut _renderRapor korundu'),
        ('_yukleRapor', 'Mevcut _yukleRapor korundu'),
        ('raporlariYukle', 'Mevcut raporlariYukle korundu'),
        ('renderRaporRows', 'Mevcut renderRaporRows korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # IIFE blok kapalı mı (paranoia)
    iife_open = final.count('(function() {\n    "use strict";\n    if (window.__faz62_rapor_detay)')
    iife_close = final.count('/* === FAZ 6.2 SONU === */')
    print(f"  IIFE blok: open={iife_open}, close={iife_close}")
    if iife_open != 1 or iife_close != 1:
        print("  [HATA] IIFE blok dengesi bozuk")
        all_ok = False
    else:
        print("  [OK] IIFE blok dengesi tamam")

    # JavaScript brace dengesi (kabaca)
    open_braces = final.count('{')
    close_braces = final.count('}')
    print(f"  Brace toplam: {{={open_braces}, }}={close_braces}, fark={open_braces - close_braces}")
    # Az fark normal (regex/string icinde olabilir), 5'ten fazla fark sorun
    if abs(open_braces - close_braces) > 5:
        print("  [UYARI] Brace dengesi sapmis olabilir")

    if not all_ok:
        return 1

    # ============================================================
    # NODE SYNTAX CHECK (varsa)
    # ============================================================
    print()
    print("=== JS SYNTAX CHECK (Node.js varsa) ===")
    import subprocess
    try:
        result = subprocess.run(
            ['node', '--check', str(TARGET_JS)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print("  [OK] Node.js syntax kontrol PASS")
        else:
            print(f"  [HATA] Node.js syntax: {result.stderr[:300]}")
            return 1
    except FileNotFoundError:
        print("  [SKIP] Node.js yok, syntax kontrol atlandi")
    except Exception as e:
        print(f"  [SKIP] Node.js hata: {e}")

    print()
    print("=" * 60)
    print("[OK] FAZ 6.2 FRONTEND IIFE BLOK EKLENDI")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Tarayicida Ctrl+Shift+R")
    print("  2. /hedef/ acin")
    print("  3. RAPOR sekmesi tikla")
    print("  4. FILTRELE tikla")
    print("  5. Mevcut 3 kart + ALTINDA 'Detay Liste' tablo gorunur")
    print("  6. Tablo: emir | proses | miktar | personel | tarih | saat | onay | usta | not")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item static\\js\\{backup_path.name} static\\js\\hedef.js -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
