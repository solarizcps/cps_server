# -*- coding: utf-8 -*-
"""
CPS DEV - FAZ 7 ADIM 3: HTML UI
================================

YAPILACAK:
  1. YENI: templates/yonetim/proses_kategori.html
     - Tablo: kategori | proses_kod | proses_adi | sira | std_saniye
     - Inline edit (sure hucresi tiklanabilir)
     - Yeni proses ekleme formu
  
  2. routes.py'a HTML render endpoint:
     GET /yonetim/proses-kategori → render_template
  
  3. templates/yonetim/panel.html'e link ekle:
     "Proses Tanimlari" karti (mevcut hk-grid icine 5. eleman)

DOKUNULMAYAN:
  - panel.html'in mevcut 4 karti (Kullanicilar, Roller, Kur, Audit Log)
  - base.html sidebar (riski azaltmak icin)
  - Mevcut /yonetim/kullanici, /yonetim/rol, /yonetim/kur, /yonetim/log
  - Diger templates/yonetim/* dosyalari

Idempotent: 'FAZ 7' marker varsa SKIP.
Yedek: routes.py + panel.html
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_TEMPLATE = PROJECT_ROOT / "templates" / "yonetim" / "proses_kategori.html"
TARGET_PANEL = PROJECT_ROOT / "templates" / "yonetim" / "panel.html"
TARGET_ROUTES = PROJECT_ROOT / "modules" / "yonetim" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# 1. HTML TEMPLATE - proses_kategori.html
# ============================================================
TEMPLATE_HTML = r'''{% extends "base.html" %}
{% block title %}Proses Tanımları — Solariz CPS{% endblock %}

{% block content %}

<div class="page-header">
  <div>
    <div class="page-title">⚙ Proses Tanımları & Standart Süreler</div>
    <div class="page-sub">Her proses için kaç saniyede bir adet yapılır (normal hız) — risk ve performans hesabının temeli</div>
  </div>
</div>

<div class="oz-card" style="margin-bottom:14px;">
  <div class="oz-hdr">
    <span class="oz-hdr-t">Yeni Proses Ekle</span>
  </div>
  <div class="oz-body">
    <div id="ekleHata" style="display:none; padding:10px 14px; background:#fee2e2; color:#991b1b; border-radius:6px; font-size:13px; margin-bottom:10px;"></div>
    <div id="ekleBasari" style="display:none; padding:10px 14px; background:#dcfce7; color:#166534; border-radius:6px; font-size:13px; margin-bottom:10px;"></div>
    <div style="display:grid; grid-template-columns:1.2fr 2fr 1fr 0.8fr 1.2fr 1fr; gap:8px; align-items:end;">
      <div>
        <label style="display:block; font-size:11px; color:var(--text3); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px;">Proses Kodu*</label>
        <input id="yeniKod" type="text" maxlength="20" placeholder="örn: 60" style="width:100%; padding:7px 10px; border:1px solid var(--border); border-radius:6px; font-size:13px;">
      </div>
      <div>
        <label style="display:block; font-size:11px; color:var(--text3); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px;">Proses Adı*</label>
        <input id="yeniAdi" type="text" maxlength="100" placeholder="örn: Çapak" style="width:100%; padding:7px 10px; border:1px solid var(--border); border-radius:6px; font-size:13px;">
      </div>
      <div>
        <label style="display:block; font-size:11px; color:var(--text3); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px;">Kategori*</label>
        <select id="yeniKategori" style="width:100%; padding:7px 10px; border:1px solid var(--border); border-radius:6px; font-size:13px;">
          <option value="ATKI">ATKI</option>
          <option value="GOVDE">GOVDE</option>
          <option value="MAMUL">MAMUL</option>
        </select>
      </div>
      <div>
        <label style="display:block; font-size:11px; color:var(--text3); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px;">Sıra</label>
        <input id="yeniSira" type="number" min="0" max="999" value="1" style="width:100%; padding:7px 10px; border:1px solid var(--border); border-radius:6px; font-size:13px;">
      </div>
      <div>
        <label style="display:block; font-size:11px; color:var(--text3); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px;">Std Süre (sn/adet)</label>
        <input id="yeniSure" type="number" min="0" max="7200" step="0.1" placeholder="örn: 35" style="width:100%; padding:7px 10px; border:1px solid var(--border); border-radius:6px; font-size:13px;">
      </div>
      <div>
        <button id="ekleBtn" style="width:100%; padding:8px 12px; background:var(--sol-dark); color:#fff; border:none; border-radius:6px; font-size:13px; font-weight:600; cursor:pointer;">+ Ekle</button>
      </div>
    </div>
    <div style="margin-top:8px; font-size:11px; color:var(--text3);">
      💡 Kategoriler: <strong>ATKI</strong> (taban-altı), <strong>GOVDE</strong> (yan-üst), <strong>MAMUL</strong> (montaj-bitirme)
    </div>
  </div>
</div>

<div class="oz-card">
  <div class="oz-hdr">
    <span class="oz-hdr-t">Mevcut Prosesler</span>
    <span id="kayitSayi" style="font-size:11px; color:var(--text3);"></span>
  </div>
  <div class="oz-body" style="padding:0;">
    <div id="updateHata" style="display:none; padding:10px 14px; background:#fee2e2; color:#991b1b; font-size:13px;"></div>
    <div id="updateBasari" style="display:none; padding:10px 14px; background:#dcfce7; color:#166534; font-size:13px;"></div>
    <div class="tbl-wrap">
      <table id="prosesTable" style="width:100%;">
        <thead>
          <tr>
            <th class="text" style="width:90px;">KATEGORİ</th>
            <th class="text" style="width:80px;">KOD</th>
            <th class="text">PROSES ADI</th>
            <th class="num" style="width:60px;">SIRA</th>
            <th class="num" style="width:160px;">STANDART SÜRE (sn/adet)</th>
            <th class="text" style="width:80px;">DURUM</th>
          </tr>
        </thead>
        <tbody id="prosesBody">
          <tr><td colspan="6" style="text-align:center; padding:30px; color:var(--text3);">Yükleniyor...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<style>
  .pk-edit-cell {
    cursor:pointer;
    padding:4px 8px;
    border-radius:4px;
    transition:background .15s;
  }
  .pk-edit-cell:hover {
    background:#fef3c7;
  }
  .pk-edit-cell.editing {
    padding:2px;
    background:#fff;
    border:1px solid var(--sol-dark);
  }
  .pk-edit-cell input {
    width:100%;
    padding:4px 6px;
    border:none;
    outline:none;
    font-size:13px;
    text-align:right;
  }
  .pk-cat-atki  { background:#dbeafe; color:#1e40af; }
  .pk-cat-govde { background:#fef3c7; color:#92400e; }
  .pk-cat-mamul { background:#dcfce7; color:#166534; }
  .pk-badge {
    display:inline-block;
    padding:2px 8px;
    border-radius:4px;
    font-size:10.5px;
    font-weight:600;
    letter-spacing:.3px;
  }
  .pk-row-tamam { background:#f0fdf4; }
  .pk-row-eksik { background:#fffbeb; }
  .pk-saniye-deger {
    font-family:var(--mono, monospace);
    font-weight:600;
  }
  .pk-saniye-null {
    color:#9ca3af;
    font-style:italic;
  }
  table#prosesTable td {
    padding:8px 10px;
    border-bottom:0.5px solid var(--border);
    font-size:13px;
  }
  table#prosesTable th {
    background:#f9fafb;
    padding:10px;
    font-size:11px;
    text-transform:uppercase;
    letter-spacing:.5px;
    color:var(--text2);
    border-bottom:1px solid var(--border);
  }
  table#prosesTable th.num, table#prosesTable td.num { text-align:right; }
</style>

<script>
(function() {
  "use strict";

  function escHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showMsg(elId, msg, isErr) {
    var el = document.getElementById(elId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    if (isErr) {
      el.style.background = '#fee2e2';
      el.style.color = '#991b1b';
    } else {
      el.style.background = '#dcfce7';
      el.style.color = '#166534';
    }
    setTimeout(function() { el.style.display = 'none'; }, 4000);
  }

  function listele() {
    fetch('/yonetim/proses-kategori/liste', { credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data.ok) {
          throw new Error(data.mesaj || 'Liste yuklenemedi');
        }
        renderTablo(data.kayitlar || []);
      })
      .catch(function(err) {
        var body = document.getElementById('prosesBody');
        if (body) {
          body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:#c62828;">Hata: ' + escHtml(err.message) + '</td></tr>';
        }
      });
  }

  function renderTablo(rows) {
    var body = document.getElementById('prosesBody');
    var sayac = document.getElementById('kayitSayi');
    if (!body) return;
    
    if (sayac) {
      var dolu = rows.filter(function(r) { return r.standart_saniye !== null; }).length;
      sayac.textContent = rows.length + ' proses (' + dolu + ' süre tanımlı, ' + (rows.length - dolu) + ' eksik)';
    }
    
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--text3);">Henüz proses yok</td></tr>';
      return;
    }
    
    var html = '';
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var catClass = 'pk-cat-' + (r.kategori || '').toLowerCase();
      var rowClass = (r.standart_saniye !== null) ? 'pk-row-tamam' : 'pk-row-eksik';
      var sureGoster = (r.standart_saniye !== null)
        ? '<span class="pk-saniye-deger">' + r.standart_saniye + '</span>'
        : '<span class="pk-saniye-null">tanımsız</span>';
      var durumIco = (r.standart_saniye !== null) ? '✓' : '○';
      var durumColor = (r.standart_saniye !== null) ? '#166534' : '#9ca3af';
      
      html += '<tr class="' + rowClass + '" data-kod="' + escHtml(r.proses_kod) + '">'
            + '<td><span class="pk-badge ' + catClass + '">' + escHtml(r.kategori) + '</span></td>'
            + '<td><strong>' + escHtml(r.proses_kod) + '</strong></td>'
            + '<td>' + escHtml(r.proses_adi) + '</td>'
            + '<td class="num">' + escHtml(r.sira) + '</td>'
            + '<td class="num"><div class="pk-edit-cell" data-orig="' + (r.standart_saniye !== null ? r.standart_saniye : '') + '" title="Tıkla, düzenle, Enter ile kaydet">' + sureGoster + '</div></td>'
            + '<td style="text-align:center; color:' + durumColor + '; font-size:18px; font-weight:bold;">' + durumIco + '</td>'
            + '</tr>';
    }
    body.innerHTML = html;
    
    // Inline edit baglanti
    var editCells = body.querySelectorAll('.pk-edit-cell');
    for (var i = 0; i < editCells.length; i++) {
      editCells[i].addEventListener('click', cellEditBasla);
    }
  }

  function cellEditBasla(e) {
    var cell = e.currentTarget;
    if (cell.classList.contains('editing')) return;
    
    var orig = cell.getAttribute('data-orig') || '';
    var tr = cell.closest('tr');
    var kod = tr.getAttribute('data-kod');
    
    cell.classList.add('editing');
    cell.innerHTML = '<input type="number" min="0" max="7200" step="0.1" value="' + orig + '" placeholder="boş = NULL">';
    var inp = cell.querySelector('input');
    inp.focus();
    inp.select();
    
    function bitir(kaydet) {
      var yeni = inp.value.trim();
      if (kaydet && yeni !== orig) {
        kaydet_sure(kod, yeni, cell);
      } else {
        cell.classList.remove('editing');
        // Geri eski hali
        var orgVal = orig === '' ? null : parseFloat(orig);
        cell.innerHTML = (orgVal !== null)
          ? '<span class="pk-saniye-deger">' + orgVal + '</span>'
          : '<span class="pk-saniye-null">tanımsız</span>';
      }
    }
    
    inp.addEventListener('keydown', function(ev) {
      if (ev.key === 'Enter') bitir(true);
      else if (ev.key === 'Escape') bitir(false);
    });
    inp.addEventListener('blur', function() { bitir(true); });
  }

  function kaydet_sure(kod, yeniDeger, cell) {
    var body = (yeniDeger === '' || yeniDeger === null)
      ? JSON.stringify({ standart_saniye: null })
      : JSON.stringify({ standart_saniye: parseFloat(yeniDeger) });
    
    fetch('/yonetim/proses-kategori/' + encodeURIComponent(kod) + '/sure', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        showMsg('updateBasari', data.mesaj || 'Kaydedildi', false);
        listele();
      } else {
        showMsg('updateHata', data.mesaj || 'Hata', true);
        cell.classList.remove('editing');
        listele();
      }
    })
    .catch(function(err) {
      showMsg('updateHata', 'Hata: ' + err.message, true);
      cell.classList.remove('editing');
      listele();
    });
  }

  function ekleProses() {
    var kod = document.getElementById('yeniKod').value.trim();
    var adi = document.getElementById('yeniAdi').value.trim();
    var kategori = document.getElementById('yeniKategori').value;
    var sira = parseInt(document.getElementById('yeniSira').value || '0');
    var sureRaw = document.getElementById('yeniSure').value.trim();
    var sure = sureRaw === '' ? null : parseFloat(sureRaw);
    
    if (!kod) { showMsg('ekleHata', 'Proses kodu gerekli', true); return; }
    if (!adi) { showMsg('ekleHata', 'Proses adı gerekli', true); return; }
    if (!kategori) { showMsg('ekleHata', 'Kategori seç', true); return; }
    
    fetch('/yonetim/proses-kategori/yeni', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        proses_kod: kod, proses_adi: adi, kategori: kategori,
        sira: sira, standart_saniye: sure
      })
    })
    .then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
    .then(function(res) {
      if (res.data.ok) {
        showMsg('ekleBasari', res.data.mesaj || 'Eklendi', false);
        document.getElementById('yeniKod').value = '';
        document.getElementById('yeniAdi').value = '';
        document.getElementById('yeniSure').value = '';
        listele();
      } else {
        showMsg('ekleHata', res.data.mesaj || 'Hata', true);
      }
    })
    .catch(function(err) {
      showMsg('ekleHata', 'Hata: ' + err.message, true);
    });
  }

  // Init
  document.addEventListener('DOMContentLoaded', function() {
    listele();
    var btn = document.getElementById('ekleBtn');
    if (btn) btn.addEventListener('click', ekleProses);
    
    // Enter ile ekle
    ['yeniKod', 'yeniAdi', 'yeniSira', 'yeniSure'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) {
        el.addEventListener('keydown', function(ev) {
          if (ev.key === 'Enter') ekleProses();
        });
      }
    });
  });
})();
</script>

{% endblock %}
'''


# ============================================================
# 2. ROUTES.PY - render endpoint append
# ============================================================
NEW_ROUTE = '''

# === FAZ 7 - HTML render endpoint ===
@yonetim_bp.route('/proses-kategori', methods=['GET'])
def faz7_proses_kategori_sayfa():
    """Proses kategori yonetim sayfasi (HTML)."""
    if not _faz7_admin_kontrol():
        try:
            from flask import redirect, url_for
            return redirect(url_for('auth.giris'))
        except Exception:
            from flask import redirect
            return redirect('/giris')
    try:
        from flask import render_template
        return render_template('yonetim/proses_kategori.html')
    except Exception as e:
        from flask import jsonify as _jsonify
        return _jsonify({'ok': False, 'mesaj': f'{type(e).__name__}: {str(e)[:200]}'}), 500
# === FAZ 7 ROUTE SONU ===
'''


# ============================================================
# 3. PANEL.HTML - yeni hk-i kart ekleme
# ============================================================
OLD_PANEL_BLOCK = '''      <a class="hk-i" href="/yonetim/log">
        <div class="hk-ic" style="background:#fee2e2; color:var(--red);">📋</div>
        <div class="hk-ad">Audit Log</div>
        <div class="hk-sub">tüm değişiklikler</div>
      </a>
    </div>'''

NEW_PANEL_BLOCK = '''      <a class="hk-i" href="/yonetim/log">
        <div class="hk-ic" style="background:#fee2e2; color:var(--red);">📋</div>
        <div class="hk-ad">Audit Log</div>
        <div class="hk-sub">tüm değişiklikler</div>
      </a>
      <a class="hk-i" href="/yonetim/proses-kategori">
        <div class="hk-ic" style="background:#fef9c3; color:#854d0e;">⚙</div>
        <div class="hk-ad">Proses Tanımları</div>
        <div class="hk-sub">standart süreler — FAZ 7</div>
      </a>
    </div>'''


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 7 ADIM 3: HTML UI")
    print("=" * 60)

    # ============================================================
    # 1. TEMPLATE DOSYASI
    # ============================================================
    print()
    print("=== 1. TEMPLATE DOSYASI ===")
    
    if TARGET_TEMPLATE.exists():
        existing = TARGET_TEMPLATE.read_text(encoding="utf-8")
        if 'FAZ 7' in existing or 'pk-edit-cell' in existing or 'prosesBody' in existing:
            print(f"  [SKIP] Template zaten var ({TARGET_TEMPLATE.stat().st_size} byte)")
        else:
            backup = TARGET_TEMPLATE.with_suffix(f".html.YEDEK_FAZ7_{ts}")
            shutil.copy2(str(TARGET_TEMPLATE), str(backup))
            print(f"  [OK] Eski template yedek alindi: {backup.name}")
            TARGET_TEMPLATE.write_text(TEMPLATE_HTML, encoding="utf-8")
            print(f"  [OK] Yazildi: {TARGET_TEMPLATE.stat().st_size} byte")
    else:
        TARGET_TEMPLATE.write_text(TEMPLATE_HTML, encoding="utf-8")
        print(f"  [OK] YENI: {TARGET_TEMPLATE.stat().st_size} byte")

    # ============================================================
    # 2. ROUTES.PY - render endpoint append
    # ============================================================
    print()
    print("=== 2. ROUTES.PY - HTML RENDER ENDPOINT ===")
    
    routes_content = TARGET_ROUTES.read_text(encoding="utf-8")
    
    if 'faz7_proses_kategori_sayfa' in routes_content:
        print("  [SKIP] Render endpoint zaten var")
    else:
        # Yedek
        rb = TARGET_ROUTES.with_suffix(f".py.YEDEK_FAZ7_RENDER_{ts}")
        shutil.copy2(str(TARGET_ROUTES), str(rb))
        print(f"  [OK] Yedek: {rb.name}")
        
        # Append
        new_routes = routes_content.rstrip() + NEW_ROUTE
        TARGET_ROUTES.write_text(new_routes, encoding="utf-8")
        new_size = TARGET_ROUTES.stat().st_size
        print(f"  [OK] Render endpoint eklendi (boyut: {new_size} byte)")
        
        # Syntax check
        try:
            compile(new_routes, str(TARGET_ROUTES), 'exec')
            print("  [OK] Python syntax dogru")
        except SyntaxError as e:
            print(f"  [HATA] SyntaxError: {e}")
            return 1

    # ============================================================
    # 3. PANEL.HTML - link ekle
    # ============================================================
    print()
    print("=== 3. PANEL.HTML - LINK EKLEME ===")
    
    panel_content = TARGET_PANEL.read_text(encoding="utf-8")
    
    if 'proses-kategori' in panel_content or 'Proses Tanımları' in panel_content:
        print("  [SKIP] Link zaten var")
    else:
        # Anchor kontrol
        anchor_count = panel_content.count(OLD_PANEL_BLOCK)
        if anchor_count != 1:
            print(f"  [HATA] Anchor bulunamadi (count={anchor_count})")
            print("  panel.html'deki Audit Log kart yapisi degismis olabilir")
            return 1
        print("  [OK] Anchor bulundu")
        
        # Yedek
        pb = TARGET_PANEL.with_suffix(f".html.YEDEK_FAZ7_{ts}")
        shutil.copy2(str(TARGET_PANEL), str(pb))
        print(f"  [OK] Yedek: {pb.name}")
        
        # Replace
        new_panel = panel_content.replace(OLD_PANEL_BLOCK, NEW_PANEL_BLOCK, 1)
        TARGET_PANEL.write_text(new_panel, encoding="utf-8")
        print(f"  [OK] Link kart eklendi")

    # ============================================================
    # GENEL DOGRULAMA
    # ============================================================
    print()
    print("=== GENEL DOGRULAMA ===")
    
    # Template
    if TARGET_TEMPLATE.exists():
        t = TARGET_TEMPLATE.read_text(encoding="utf-8")
        for needle in ['prosesBody', 'pk-edit-cell', '/yonetim/proses-kategori/liste',
                       '/yonetim/proses-kategori/yeni', 'kategori', 'standart_saniye']:
            if needle in t:
                print(f"  [OK] Template: {needle}")
            else:
                print(f"  [HATA] Template eksik: {needle}")
                return 1
    
    # Routes
    r = TARGET_ROUTES.read_text(encoding="utf-8")
    for needle in ['faz7_proses_kategori_sayfa', "@yonetim_bp.route('/proses-kategori'",
                   'render_template', 'faz7_proses_kategori_liste']:
        if needle in r:
            print(f"  [OK] Routes: {needle}")
        else:
            print(f"  [HATA] Routes eksik: {needle}")
            return 1
    
    # Panel
    p = TARGET_PANEL.read_text(encoding="utf-8")
    if 'proses-kategori' in p and 'Proses Tanımları' in p:
        print("  [OK] Panel: link mevcut")
    
    # 4 mevcut kart korundu (Kullanıcılar, Roller, Kur, Audit Log)
    for needle in ['/yonetim/kullanici', '/yonetim/rol', '/yonetim/kur', '/yonetim/log']:
        if needle in p:
            print(f"  [OK] Mevcut link korundu: {needle}")

    print()
    print("=" * 60)
    print("[OK] FAZ 7 ADIM 3 UI TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("  2. Tarayicida Ctrl+Shift+R")
    print("  3. /yonetim/ acin")
    print("  4. 5. kart 'Proses Tanımları' tıkla")
    print("  5. /yonetim/proses-kategori sayfasi acilir")
    print("  6. 10 proses listede gorunur, std_saniye NULL")
    print("  7. Tikla, sure gir (orn 35), Enter -> kaydolur")
    print("  8. Yeni proses formu ile Capak/Rivet ekle")
    print()
    print("Adem buradan 27 yillik standart sureleri girebilir.")
    print("FAZ 7 ADIM 1+2+3 TAMAMLANDI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
