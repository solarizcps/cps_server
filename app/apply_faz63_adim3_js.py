# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF OPERASYON JS (FAZ 6.3 ADIM 3)
==============================================

YAPILACAK:
  YENI dosya: static/js/hedef_operasyon.js
  
  IIFE pattern:
    - window.__faz63_operasyon_kpi guard (idempotent)
    - GET /hedef/operasyon-ozet fetch
    - 5 KPI kart render (kpi-band-faz63 div'ine)
    - 30 saniyede bir auto-refresh
    - Hata olunca ekrani bozma (sessiz handle)
    - Inline style (ADIM 4'te CSS dosyaya tasinir)

DOKUNULMAYAN:
  - Mevcut hedef.js (252KB)
  - darbogaz_uyari.js
  - hedef.css
  - HTML index.html (sadece <div> kullananiyor)

Idempotent: Dosya zaten varsa SKIP (fakat versiyonu eskiyse uyari ver)
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_JS = PROJECT_ROOT / "static" / "js" / "hedef_operasyon.js"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# JS ICERIK - hedef_operasyon.js
# ============================================================
JS_CONTENT = '''/* ================================================================
   CPS DEV - Hedef Operasyon KPI Bandi (FAZ 6.3)
   ----------------------------------------------------------------
   Bagimsiz IIFE - mevcut hedef.js'e dokunmaz.
   
   Veri kaynagi: GET /hedef/operasyon-ozet
   Render hedef: <div id="kpi-band-faz63">
   Refresh:      30 saniye
   ================================================================ */
(function() {
    "use strict";

    // Idempotent guard
    if (window.__faz63_operasyon_kpi) return;
    window.__faz63_operasyon_kpi = true;

    // === KONFIGURASYON ===
    var CFG = {
        endpoint: '/hedef/operasyon-ozet',
        refreshMs: 30000,         // 30 saniye
        targetId: 'kpi-band-faz63',
        timeoutMs: 8000           // 8 saniye fetch timeout
    };

    var state = {
        loading: false,
        lastFetch: 0,
        lastData: null,
        timerId: null,
        consecutiveErrors: 0
    };

    // === HELPERLAR ===
    function fmtNum(n) {
        if (n === null || n === undefined || isNaN(n)) return '0';
        n = Number(n);
        if (n >= 1000) return n.toLocaleString('tr-TR');
        return String(Math.round(n));
    }

    function escHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // === RENK KOSULLARI ===
    function renkBekleyen(n) {
        if (n > 15) return { color: '#c62828', bg: '#ffebee', etiket: 'YUKSEK' };
        if (n > 5)  return { color: '#ef6c00', bg: '#fff3e0', etiket: 'ARTIYOR' };
        return { color: '#1a1a1a', bg: 'transparent', etiket: 'kayit' };
    }

    function renkAktifPersonel(n) {
        if (n === 0) return { color: '#c62828', bg: '#ffebee', etiket: 'BOS' };
        if (n < 2)   return { color: '#ef6c00', bg: '#fff3e0', etiket: 'AZ' };
        return { color: '#1a1a1a', bg: 'transparent', etiket: 'kisi' };
    }

    function renkKritik(n) {
        if (n > 0) return { color: '#c62828', bg: '#ffebee', etiket: 'KRITIK!' };
        return { color: '#2e7d32', bg: '#e8f5e9', etiket: 'IYI' };
    }

    // === KART HTML ===
    function kartHtml(baslik, sayi, etiket, renk) {
        var bg = renk && renk.bg ? renk.bg : 'transparent';
        var color = renk && renk.color ? renk.color : '#1a1a1a';
        var textColor = renk && renk.color !== '#1a1a1a' ? renk.color : '#888';
        return ''
            + '<div class="faz63-kpi-card" style="'
            +   'flex: 1 1 0; min-width: 130px; padding: 10px 14px; '
            +   'background: ' + bg + '; '
            +   'border: 1px solid #e8e8e8; border-radius: 6px; '
            +   'box-shadow: 0 1px 2px rgba(0,0,0,.03);'
            + '">'
            +   '<div style="font-size: 10.5px; color: #888; font-weight: 600; '
            +     'text-transform: uppercase; letter-spacing: .6px; margin-bottom: 4px;">'
            +     escHtml(baslik)
            +   '</div>'
            +   '<div style="font-size: 26px; font-weight: 700; line-height: 1.1; '
            +     'color: ' + color + ';">' + escHtml(sayi) + '</div>'
            +   '<div style="font-size: 10px; color: ' + textColor + '; '
            +     'margin-top: 2px; font-weight: 500;">' + escHtml(etiket) + '</div>'
            + '</div>';
    }

    // === RENDER ===
    function render(data) {
        var target = document.getElementById(CFG.targetId);
        if (!target) return;

        if (!data || !data.kpi) {
            target.innerHTML = '';
            return;
        }

        var k = data.kpi;
        var rB = renkBekleyen(Number(k.bekleyen_onay) || 0);
        var rA = renkAktifPersonel(Number(k.aktif_personel) || 0);
        var rK = renkKritik(Number(k.kritik_darbogaz) || 0);

        var html = ''
            + '<div class="faz63-kpi-band" data-faz63="kpi-band" style="'
            +   'display: flex; gap: 8px; margin: 12px 0 16px 0; '
            +   'flex-wrap: nowrap; overflow-x: auto;'
            + '">'
            + kartHtml('Acik Is', fmtNum(k.acik_is), 'aktif emir', null)
            + kartHtml('Bekleyen Onay', fmtNum(k.bekleyen_onay), rB.etiket, rB)
            + kartHtml('Bugun Uretim', fmtNum(k.bugun_uretim), 'adet', null)
            + kartHtml('Aktif Personel', fmtNum(k.aktif_personel), rA.etiket, rA)
            + kartHtml('Kritik Darbogaz', fmtNum(k.kritik_darbogaz), rK.etiket, rK)
            + '</div>';

        target.innerHTML = html;
        state.lastData = data;
    }

    function renderHata() {
        // Hatada ekrani BOZMA - sadece sessiz duruyor
        // Eger hic veri yoksa kucuk bir "yukleme bekleniyor" mesaji
        var target = document.getElementById(CFG.targetId);
        if (target && !state.lastData) {
            target.innerHTML = ''
                + '<div style="margin: 8px 0; padding: 8px 12px; '
                +   'background: #fafafa; border: 1px dashed #ddd; '
                +   'border-radius: 6px; color: #999; font-size: 11.5px;">'
                +   'KPI bandi yukleniyor...'
                + '</div>';
        }
        // Eger lastData var ise, ekranda eski deger duruyor - dokunma
    }

    // === FETCH ===
    function fetchKpi() {
        if (state.loading) return;
        state.loading = true;

        // Timeout icin AbortController (modern browser)
        var ctrl = null;
        var timeoutId = null;
        try {
            if (window.AbortController) {
                ctrl = new AbortController();
                timeoutId = setTimeout(function() { ctrl.abort(); }, CFG.timeoutMs);
            }
        } catch (e) {}

        var fetchOpts = { credentials: 'same-origin' };
        if (ctrl) fetchOpts.signal = ctrl.signal;

        fetch(CFG.endpoint, fetchOpts)
            .then(function(r) {
                if (timeoutId) clearTimeout(timeoutId);
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function(data) {
                state.consecutiveErrors = 0;
                state.lastFetch = Date.now();
                render(data);
            })
            .catch(function(err) {
                state.consecutiveErrors++;
                // Sessiz hata - sadece ilk hata icin minimal log
                if (state.consecutiveErrors === 1) {
                    try { console.warn('[FAZ 6.3] KPI yuklenemedi:', err.message || err); } catch (e) {}
                }
                renderHata();
            })
            .finally(function() {
                state.loading = false;
            });
    }

    // === AUTO REFRESH ===
    function startAutoRefresh() {
        if (state.timerId) return;
        state.timerId = setInterval(fetchKpi, CFG.refreshMs);
    }

    function stopAutoRefresh() {
        if (state.timerId) {
            clearInterval(state.timerId);
            state.timerId = null;
        }
    }

    // === BASLAT ===
    function init() {
        var target = document.getElementById(CFG.targetId);
        if (!target) {
            // Hedef div yok - sessiz cik
            return;
        }
        // Ilk fetch
        fetchKpi();
        // Auto-refresh basla
        startAutoRefresh();

        // Sayfa gizli iken refresh yapma (pil tasarrufu)
        if (typeof document.hidden !== 'undefined') {
            document.addEventListener('visibilitychange', function() {
                if (document.hidden) {
                    stopAutoRefresh();
                } else {
                    fetchKpi();           // Geri donunce hemen yenile
                    startAutoRefresh();
                }
            });
        }
    }

    // DOM hazir olunca baslat
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Diagnostik
    try { console.info('[FAZ 6.3] Hedef Operasyon KPI bandi aktif (refresh:', CFG.refreshMs/1000, 'sn)'); } catch (e) {}
})();
'''


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF OPERASYON JS (FAZ 6.3 ADIM 3)")
    print("=" * 60)

    # Hedef klasor var mi
    target_dir = TARGET_JS.parent
    if not target_dir.exists():
        print(f"  [HATA] Klasor yok: {target_dir}")
        return 1

    print(f"  Hedef dosya: {TARGET_JS}")

    # ============================================================
    # IDEMPOTENT - Dosya zaten varsa kontrol
    # ============================================================
    if TARGET_JS.exists():
        existing = TARGET_JS.read_text(encoding="utf-8")
        if 'FAZ 6.3' in existing and '__faz63_operasyon_kpi' in existing:
            print()
            print("  [SKIP] hedef_operasyon.js zaten var (FAZ 6.3 markerli)")
            print(f"  Mevcut boyut: {TARGET_JS.stat().st_size} byte")
            print()
            print("  Yine de ustune yazmak icin script'i degistir.")
            print("=" * 60)
            return 0
        else:
            # Dosya var ama bizim degil - yedek al
            print()
            print(f"  [UYARI] Dosya var ama FAZ 6.3 markersiz. Yedekleniyor.")
            backup = TARGET_JS.with_suffix(f".js.YEDEK_FAZ63_{ts}")
            shutil.copy2(str(TARGET_JS), str(backup))
            print(f"  [OK] Yedek: {backup.name}")

    # ============================================================
    # DOSYAYI YAZ
    # ============================================================
    print()
    print("=== DOSYA YAZIMI ===")
    TARGET_JS.write_text(JS_CONTENT, encoding="utf-8")
    new_size = TARGET_JS.stat().st_size
    print(f"  [OK] Yazildi: {new_size} byte")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_JS.read_text(encoding="utf-8")

    checks = [
        ('FAZ 6.3', 'Marker var'),
        ('__faz63_operasyon_kpi', 'Idempotent guard'),
        ("'/hedef/operasyon-ozet'", 'Endpoint URL'),
        ("'kpi-band-faz63'", 'Hedef div ID'),
        ('refreshMs: 30000', 'Refresh 30 saniye'),
        ('function fmtNum', 'Sayi formatlama'),
        ('function escHtml', 'XSS escape'),
        ('function render', 'Render fonksiyonu'),
        ('function fetchKpi', 'Fetch fonksiyonu'),
        ('function init', 'Init fonksiyonu'),
        ('renkBekleyen', 'Bekleyen renk fonksiyonu'),
        ('renkAktifPersonel', 'Aktif personel renk fonksiyonu'),
        ('renkKritik', 'Kritik renk fonksiyonu'),
        ('visibilitychange', 'Pil tasarrufu (gizli iken durur)'),
        ('AbortController', 'Timeout destegi'),
        ('credentials:', 'Cookie auth'),
        ('Acik Is', 'KPI 1 baslik'),
        ('Bekleyen Onay', 'KPI 2 baslik'),
        ('Bugun Uretim', 'KPI 3 baslik'),
        ('Aktif Personel', 'KPI 4 baslik'),
        ('Kritik Darbogaz', 'KPI 5 baslik'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # IIFE blok dengesi
    iife_open = final.count('(function() {')
    print(f"  IIFE acik blok: {iife_open}")
    
    open_braces = final.count('{')
    close_braces = final.count('}')
    print(f"  Brace toplam: {{={open_braces}, }}={close_braces}, fark={open_braces - close_braces}")
    if abs(open_braces - close_braces) > 5:
        print("  [UYARI] Brace dengesi sapmis")
        all_ok = False

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
    print("[OK] FAZ 6.3 ADIM 3 JS DOSYA OLUSTURULDU")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART GEREKMEZ (sadece JS dosya)")
    print("  2. Tarayicida Ctrl+Shift+R")
    print("  3. /hedef/ acin")
    print("  4. Toolbar ALTINDA 5 KPI karti gorunmeli:")
    print("     [Acik Is] [Bekleyen Onay] [Bugun Uretim] [Aktif Personel] [Kritik Darbogaz]")
    print("  5. F12 Console -> '[FAZ 6.3] Hedef Operasyon KPI bandi aktif (refresh: 30 sn)'")
    print()
    print("ADIM 4: CSS (sticky + responsive + sade kurumsal)")
    print()
    print(f"Rollback (manuel):")
    print(f"  Remove-Item static\\js\\hedef_operasyon.js -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
