# -*- coding: utf-8 -*-
"""proses_takip.html dosyasini garantili UTF-8 olarak yazar."""
import os

YOL = r'C:\cps_dev\templates\planlama\proses_takip.html'

HTML = r'''{% extends "base.html" %}
{% block title %}Planlama / Proses Takip · Solariz CPS{% endblock %}

{% block head %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/proses_takip.css') }}?v={{ range(100000, 999999) | random }}">
{% endblock %}

{% block content %}

<!-- ÜST BAŞLIK -->
<div class="pt-toolbar">
  <div class="pt-toolbar-left">
    <h1>📊 Planlama / Proses Takip</h1>
    <p>Korgun canlı üretim verisi — gerçek operasyon görünümü.</p>
  </div>
  <div class="pt-toolbar-right">
    <span class="pt-veri-kaynak" id="pt-veri-kaynak">—</span>
    <span class="pt-sorgu-suresi" id="pt-sorgu-suresi"></span>
  </div>
</div>

<!-- UYARI BANDI (mock fallback durumunda görünür) -->
<div id="pt-uyari-bandi" class="pt-uyari-bandi" style="display:none;">
  <span id="pt-uyari-mesaj"></span>
</div>

<!-- ANA YERLEŞİM: Sol filtre + Sağ tablo -->
<div class="pt-layout">

  <!-- ============ SOL FILTRE PANELI ============ -->
  <aside class="pt-filtre-paneli" id="pt-filtre-paneli">
    <div class="pt-filtre-baslik">
      <span>🔎 Filtreler</span>
      <button class="pt-toggle-btn" onclick="pt_filtre_toggle()" title="Gizle/Göster">◀</button>
    </div>

    <!-- LOKASYON -->
    <div class="pt-flt-grup">
      <div class="pt-flt-grup-baslik" onclick="pt_sec_toggle('pt-sec-lok')">
        <span>📍 Lokasyon <small>(zorunlu)</small></span>
        <span class="pt-flt-tumu" onclick="event.stopPropagation();pt_lok_tumu()">Tümü</span>
      </div>
      <div id="pt-sec-lok" class="pt-checklist">
        <label><input type="checkbox" class="pt-lok-cb" value="SA001"> SA001 - Şahin Taban (Ana Firma)</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SU001"> SU001 - Üretim Saha</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SU002"> SU002 - Yarı Mamul (Depo)</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SH001"> SH001 - Hammadde Depo</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SA002"> SA002 - Beyazıt Mağaza</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SARGE"> SARGE - Arge Ürün</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SD002"> SD002 - Solariz Lojistik Depo</label>
        <label><input type="checkbox" class="pt-lok-cb" value="SE001"> SE001 - E-Ticaret</label>
        <label><input type="checkbox" class="pt-lok-cb" value="YN001"> YN001 - Nexgen Kimya - Merkez</label>
        <label><input type="checkbox" class="pt-lok-cb" value="YN002"> YN002 - Nexgen Kimya - Hammadde</label>
        <label><input type="checkbox" class="pt-lok-cb" value="YP001"> YP001 - Pera Satış Pazarlama</label>
      </div>
    </div>

    <!-- PROSES -->
    <div class="pt-flt-grup">
      <div class="pt-flt-grup-baslik" onclick="pt_sec_toggle('pt-sec-prs')">
        <span>⚙️ Proses</span>
        <span class="pt-flt-tumu" onclick="event.stopPropagation();pt_prs_tumu()">Tümü</span>
      </div>
      <div id="pt-sec-prs" class="pt-checklist">
        <label><input type="checkbox" class="pt-pr-cb" data-p="Enjeksiyon"><span class="pt-renk" style="background:#6366f1"></span> Enjeksiyon</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Kesim"><span class="pt-renk" style="background:#f59e0b"></span> Kesim</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Saya"><span class="pt-renk" style="background:#ec4899"></span> Saya</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Mekval"><span class="pt-renk" style="background:#ef4444"></span> Mekval</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Monta"><span class="pt-renk" style="background:#10b981"></span> Monta</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Monta Başlayacak"><span class="pt-renk" style="background:#f97316"></span> Monta Başlayacak</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Temizleme"><span class="pt-renk" style="background:#06b6d4"></span> Temizleme</label>
        <label><input type="checkbox" class="pt-pr-cb" data-p="Eva Hazır"><span class="pt-renk" style="background:#8b5cf6"></span> Eva Hazır</label>
      </div>
    </div>

    <!-- DURUM -->
    <div class="pt-flt-grup">
      <div class="pt-flt-grup-baslik" onclick="pt_sec_toggle('pt-sec-drm')">
        <span>📌 Durum</span>
      </div>
      <div id="pt-sec-drm" class="pt-checklist">
        <label><input type="checkbox" id="pt-drm-basl"> Başlayacak</label>
        <label><input type="checkbox" id="pt-drm-devam"> Devam eden</label>
        <label><input type="checkbox" id="pt-drm-biten"> Biten</label>
      </div>
    </div>

    <!-- TARIH -->
    <div class="pt-flt-grup">
      <div class="pt-flt-grup-baslik" onclick="pt_sec_toggle('pt-sec-tarih')">
        <span>📅 Periyot</span>
      </div>
      <div id="pt-sec-tarih" class="pt-tarih-grup">
        <div class="pt-period-group">
          <button class="pt-period-btn aktif" data-period="bugun" onclick="pt_set_period(this)">Bugün</button>
          <button class="pt-period-btn" data-period="hafta" onclick="pt_set_period(this)">Hafta</button>
          <button class="pt-period-btn" data-period="ay" onclick="pt_set_period(this)">Ay</button>
        </div>
        <div class="pt-tarih-aralik">
          <input type="date" id="pt-tarih-bas" placeholder="Bas">
          <input type="date" id="pt-tarih-bit" placeholder="Bit">
        </div>
      </div>
    </div>

    <!-- SIP/EMIR -->
    <div class="pt-flt-grup">
      <input type="text" id="pt-sip-ara" placeholder="🔍 Sipariş no..." oninput="pt_uygula()">
      <input type="text" id="pt-emir-ara" placeholder="🔍 Emir no..." oninput="pt_uygula()">
      <input type="text" id="pt-model-ara" placeholder="🔍 Model / stok kodu..." oninput="pt_uygula()">
    </div>

    <!-- AKSİYON BUTONLARI -->
    <div class="pt-aksiyon">
      <button class="pt-btn-goster" onclick="pt_goster()">▶ Göster</button>
      <button class="pt-btn-sifirla" onclick="pt_sifirla()">↻ Sıfırla</button>
    </div>
  </aside>

  <!-- ============ SAĞ ANA PANEL ============ -->
  <main class="pt-ana-panel">

    <!-- ÜST ÖZET BANDI -->
    <div class="pt-ozet-bandi">
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Toplam kayıt</div><div class="pt-ozet-v" id="pt-oz-t">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Başlayacak</div><div class="pt-ozet-v pt-sari" id="pt-oz-b">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Devam eden</div><div class="pt-ozet-v pt-mavi" id="pt-oz-d">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Biten</div><div class="pt-ozet-v pt-yesil" id="pt-oz-k">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Toplam çift</div><div class="pt-ozet-v" id="pt-oz-tc">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Başl. çift</div><div class="pt-ozet-v pt-sari" id="pt-oz-bc">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Dev. çift</div><div class="pt-ozet-v pt-mavi" id="pt-oz-dc">—</div></div>
      <div class="pt-ozet-h"><div class="pt-ozet-lbl">Bit. çift</div><div class="pt-ozet-v pt-yesil" id="pt-oz-kc">—</div></div>
    </div>

    <!-- TABLO ALANI -->
    <div class="pt-tablo-kart">
      <div class="pt-tablo-scroll" id="pt-tablo-scroll">
        <table class="pt-tablo" id="pt-tablo">
          <thead><tr id="pt-thead"></tr></thead>
          <tbody id="pt-tbody">
            <tr><td colspan="11" class="pt-empty">📍 Önce <b>lokasyon seçin</b>, sonra <b>Göster</b> butonuna basın.</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pt-tablo-alt" id="pt-tablo-alt"></div>
    </div>

  </main>

</div>

{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/proses_takip.js') }}?v={{ range(100000, 999999) | random }}"></script>
{% endblock %}
'''

# Klasor varligini garantile
os.makedirs(os.path.dirname(YOL), exist_ok=True)

with open(YOL, 'w', encoding='utf-8') as f:
    f.write(HTML)

print(f"[OK] Yazildi: {YOL}")
print(f"[OK] Boyut: {os.path.getsize(YOL)} byte")

# Dogrulama
with open(YOL, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"[OK] Okundu: {len(icerik)} karakter")
print(f"[OK] '<!-- ÜST BAŞLIK -->' var mi: {'<!-- ÜST BAŞLIK -->' in icerik}")
print(f"[OK] '{{% extends' var mi: {'{% extends' in icerik}")