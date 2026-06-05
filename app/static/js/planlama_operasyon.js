/* =============================================================
   SOLARIZ CPS - PLANLAMA OPERASYON RAPORU JS
   F9.5.2 - UI Controller
   Yapi: IIFE, global namespace yok
   ============================================================= */

(function() {
  "use strict";

  // ============================================================
  // STATE
  // ============================================================
  // AKSAMA_AUTOREFRESH_V1 (15.05.2026): sebep lookup + 5sn polling
  var state = {
    tarih: null,
    vardiya: null,
    genel: null,
    secili_makine: null,
    // F9_5_4C: aktif detay sekme
    detay_aktif_sekme: "saatlik",
    makine_detay: null,
    auto_refresh_timer: null,
    auto_refresh_aktif: true,
    aksama_sebepleri: {},  // {id: "ad"} cache
    son_yukleme: 0,
  };
  
  var AUTO_REFRESH_MS = 5000;  // 5 saniye

  // ============================================================
  // UTIL
  // ============================================================
  function $(id) { return document.getElementById(id); }
  function $$(sel, root) { return (root || document).querySelectorAll(sel); }
  function fmt(n) {
    if (n === null || n === undefined) return null;
    return n.toLocaleString("tr-TR");
  }
  function fmtOrTire(n) {
    var r = fmt(n);
    return r !== null ? r : "—";
  }
  function bugun_iso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var g = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + g;
  }
  function aktif_vardiya() {
    var h = new Date().getHours();
    return (h >= 7 && h < 17) ? "gunduz" : "gece";
  }
  function durum_class(tip) {
    // TUMUYLA_AKTIF -> tumuyle-aktif
    return (tip || "").toLowerCase().replace(/_/g, "-");
  }

  // ============================================================
  // API
  // ============================================================
  function apiFetch(url) {
    return fetch(url, { credentials: "same-origin" })
      .then(function(r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }
  function apiGenel(tarih, vardiya) {
    return apiFetch("/planlama/api/operasyon/genel?tarih=" + tarih + "&vardiya=" + vardiya);
  }
  function apiMakine(mid, tarih, vardiya) {
    return apiFetch("/planlama/api/operasyon/makine/" + mid + "?tarih=" + tarih + "&vardiya=" + vardiya);
  }
  function apiTimeline(rapor_id) {
    return apiFetch("/planlama/api/operasyon/event-timeline/" + rapor_id);
  }
  // FIELD_TEST_READY: aksama sebep lookup
  function apiAksamaSebepleri() {
    return apiFetch("/enjeksiyon/api/aksama-sebepleri");
  }
  // AKSAMA_AUTOREFRESH_V1: sebep lookup endpoint
  function apiAksamaSebepleri() {
    return apiFetch("/enjeksiyon/api/aksama-sebepleri");
  }

  // ============================================================
  // RENDER: FILTRE & VARDIYA ILERLEME
  // ============================================================
  function renderFiltreVardiya(filtre) {
    $("or-vardiya-dk").textContent = filtre.vardiya_gecen_dk;
    $("or-vardiya-sure").textContent = filtre.vardiya_sure_dk;
    var yuzde = Math.round((filtre.vardiya_gecen_dk / filtre.vardiya_sure_dk) * 100);
    $("or-vardiya-yuzde").textContent = "%" + yuzde;
    
    // CANLI badge
    if (filtre.vardiya_aktif) {
      $("or-canli-badge").classList.remove("kapali");
    } else {
      $("or-canli-badge").classList.add("kapali");
    }
  }

  // ============================================================
  // RENDER: KPI SERIDI
  // ============================================================
  // F9_5_4A_KPI_BEGIN
// F9_5_5A_KPI_ICONS_BEGIN
function _kpiStripiYenidenInsa() {
  var s = document.getElementById("or-kpi-serit");
  if (!s) return;
  s.innerHTML = '<div class="or-kpi or-kpi-tip-tur"><div class="or-kpi-ikon or-kpi-ikon-tur"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Toplam tur</div><div class="or-kpi-deger" id="kpi-tur">—</div><div class="or-kpi-alt" id="kpi-tur-alt">—</div></div></div><div class="or-kpi or-kpi-tip-uretim"><div class="or-kpi-ikon or-kpi-ikon-uretim"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 22h20"/><path d="M6.36 17.4 4 17l-2-4 1.1-.55a2 2 0 0 1 1.8 0l.17.1a2 2 0 0 0 1.8 0L8 12 5 6l4-2 6 7"/><path d="M13 14 7 9.5 7 6"/><path d="M14 17 18 13l-2-2-4 4"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Toplam üretim</div><div class="or-kpi-deger" id="kpi-uretim">—</div><div class="or-kpi-alt" id="kpi-uretim-alt">—</div></div></div><div class="or-kpi or-kpi-tip-net"><div class="or-kpi-ikon or-kpi-ikon-net"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Net çift</div><div class="or-kpi-deger" id="kpi-net">—</div><div class="or-kpi-alt" id="kpi-net-alt">—</div></div></div><div class="or-kpi or-kpi-fire or-kpi-tip-fire" id="kpi-fire-kart"><div class="or-kpi-ikon or-kpi-ikon-fire"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">FIRE</div><div class="or-kpi-fire-ust"><span class="or-kpi-fire-cift" id="kpi-fire-cift">—</span><span class="or-kpi-fire-orani" id="kpi-fire-orani">—</span></div><div class="or-kpi-fire-alt" id="kpi-fire-bd">Teknik:— · Boş Atış:— · Yolluk:—</div></div></div><div class="or-kpi or-kpi-tip-verim"><div class="or-kpi-ikon or-kpi-ikon-verim"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 16l4-4 4 2 5-7"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Verim %</div><div class="or-kpi-deger" id="kpi-verim">—</div><div class="or-kpi-alt" id="kpi-verim-alt">—</div></div></div><div class="or-kpi or-kpi-tip-slot"><div class="or-kpi-ikon or-kpi-ikon-slot"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Aktif slot</div><div class="or-kpi-deger" id="kpi-aktif">—</div><div class="or-kpi-alt" id="kpi-aktif-alt">—</div></div></div><div class="or-kpi or-kpi-tip-makine"><div class="or-kpi-ikon or-kpi-ikon-makine"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M6 7V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v3"/><path d="M12 11v4"/><path d="M9 13h6"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Aktif makine</div><div class="or-kpi-deger" id="kpi-makine">—</div><div class="or-kpi-alt" id="kpi-makine-alt">—</div></div></div><div class="or-kpi or-kpi-tip-ariza"><div class="or-kpi-ikon or-kpi-ikon-ariza"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg></div><div class="or-kpi-icerik"><div class="or-kpi-label">Arıza dk</div><div class="or-kpi-deger" id="kpi-ariza">—</div><div class="or-kpi-alt" id="kpi-ariza-alt">—</div></div></div>';
}
// F9_5_5A_KPI_ICONS_END

function _f2a_setKpi(id, deger, alt, bos) {
  var e = document.getElementById(id);
  if (!e) return;
  if (bos) {
    e.textContent = "—";
    e.classList.add("bos");
  } else {
    if (typeof deger === "number") {
      e.textContent = (typeof fmt === "function") ? fmt(deger) : String(deger);
    } else {
      e.textContent = (deger == null) ? "—" : String(deger);
    }
    e.classList.remove("bos");
  }
  if (alt !== undefined) {
    var ea = document.getElementById(id + "-alt");
    if (ea) ea.textContent = (alt == null || alt === "") ? " " : alt;
  }
}

function _f2a_fmt(n) {
  if (n == null || isNaN(n)) return "—";
  return (typeof fmt === "function") ? fmt(n) : String(n);
}

function _f2a_renderFireBreakdown(t) {
  function p(v) { return (v && v > 0) ? v.toFixed(1) + "kg" : "—"; }
  return "Teknik:" + p(t.teknik_kg) + " · Boş Atış:" + p(t.bos_kg) + " · Yolluk:" + p(t.yolluk_kg);
}

function renderKpi(genel) {
  if (!document.getElementById("kpi-uretim")) {
    _kpiStripiYenidenInsa();
  }

  var t = {
    tur_a: 0, tur_b: 0,
    uretim_a: 0, uretim_b: 0,
    brut: 0, teorik: 0, net: 0,
    fire_cift: 0, teknik_kg: 0, bos_kg: 0, yolluk_kg: 0,
    ariza_dk: 0, ariza_olay: 0,
    slot_top: 0, slot_aktif: 0,
    makine_top: 0, makine_aktif: 0
  };
  var teorik_var = false, net_var = false;

  (genel.makineler || []).forEach(function(m) {
    t.makine_top++;
    // F9_5_5G_KPI_TANIM: Aktif makine = uretim>0 VEYA aktif_slot>0
    var _uretim_var = m.uretim && ((m.uretim.uretilen_a || 0) + (m.uretim.uretilen_b || 0)) > 0;
    var _aktif_slot_var = m.anlik_durum && m.anlik_durum.sayim && (m.anlik_durum.sayim.AKTIF || 0) > 0;
    if (_uretim_var || _aktif_slot_var) t.makine_aktif++;

    var u = m.uretim;
    if (u) {
      t.tur_a    += u.tur_a || 0;
      t.tur_b    += u.tur_b || 0;
      t.uretim_a += u.uretilen_a || 0;
      t.uretim_b += u.uretilen_b || 0;
      if (u.brut_cift != null)   t.brut += u.brut_cift;
      if (u.teorik_cift != null) { t.teorik += u.teorik_cift; teorik_var = true; }
      if (u.net_cift != null)    { t.net += u.net_cift; net_var = true; }
      if (u.fire_cift != null)   t.fire_cift += u.fire_cift;
      t.teknik_kg += u.teknik_fire_kg || 0;
      t.bos_kg    += u.bos_atis_kg || 0;
      t.yolluk_kg += u.yolluk_fire_kg || 0;
    }
    if (m.olay_ozet) {
      t.ariza_dk   += m.olay_ozet.ariza_toplam_dk || 0;
      t.ariza_olay += m.olay_ozet.ariza_sayi || 0;
    }
    if (m.anlik_durum) {
      t.slot_top   += m.anlik_durum.toplam_slot || 0;
      t.slot_aktif += (m.anlik_durum.sayim && m.anlik_durum.sayim.AKTIF) || 0;
    }
  });

  var fire_orani = (t.brut > 0) ? Math.round((t.fire_cift / t.brut) * 1000) / 10 : null;
  var fire_seviye = null;
  if (fire_orani != null) {
    if (fire_orani >= 6.0)      fire_seviye = "kirmizi";
    else if (fire_orani >= 3.0) fire_seviye = "sari";
    else                         fire_seviye = "normal";
  }

  var verim = (teorik_var && net_var && t.teorik > 0) ? Math.round((t.net / t.teorik) * 1000) / 10 : null;

  var slot_yuzde   = (t.slot_top > 0)   ? Math.round((t.slot_aktif / t.slot_top) * 100) : null;
  var makine_yuzde = (t.makine_top > 0) ? Math.round((t.makine_aktif / t.makine_top) * 100) : null;

  var tur_top = t.tur_a + t.tur_b;
  _f2a_setKpi("kpi-tur",    tur_top, "A:" + t.tur_a + " B:" + t.tur_b, tur_top === 0);
  _f2a_setKpi("kpi-uretim", t.brut,  "A:" + _f2a_fmt(t.uretim_a) + " B:" + _f2a_fmt(t.uretim_b), t.brut === 0);
  _f2a_setKpi("kpi-net",    net_var ? t.net : null, "", !net_var);
  _f2a_setKpi("kpi-verim",  verim != null ? "%" + verim : null, "Üretim verimi", verim == null);
  _f2a_setKpi("kpi-aktif",  t.slot_aktif + "/" + t.slot_top, slot_yuzde != null ? "%" + slot_yuzde : "—", t.slot_top === 0);
  _f2a_setKpi("kpi-makine", t.makine_aktif + "/" + t.makine_top, makine_yuzde != null ? "%" + makine_yuzde : "—", t.makine_top === 0);
  _f2a_setKpi("kpi-ariza",  t.ariza_dk, t.ariza_olay + " olay", t.ariza_dk === 0);

  var fc = document.getElementById("kpi-fire-cift");
  var fo = document.getElementById("kpi-fire-orani");
  var fb = document.getElementById("kpi-fire-bd");
  var fk = document.getElementById("kpi-fire-kart");
  if (fc) fc.textContent = (t.fire_cift > 0) ? _f2a_fmt(t.fire_cift) + " ç." : "0 ç.";
  if (fo) fo.textContent = (fire_orani != null) ? "%" + fire_orani : "—";
  if (fb) fb.textContent = _f2a_renderFireBreakdown(t);
  if (fk) {
    fk.classList.remove("seviye-normal", "seviye-sari", "seviye-kirmizi");
    if (fire_seviye) fk.classList.add("seviye-" + fire_seviye);
  }
}
// F9_5_4A_KPI_END

  // ============================================================
  // RENDER: MAKINE KART
  // ============================================================
  // F9_5_4B_TABLO_BEGIN
function _f2b_verimClass(v) {
  if (v == null) return "verim-bos";
  if (v >= 85) return "verim-yesil";
  if (v >= 70) return "verim-sari";
  return "verim-kirmizi";
}

function _f2b_fireClass(seviye) {
  return "seviye-" + (seviye || "normal");
}

function _f2b_sonOlaySozcuk(oz) {
  if (!oz) return "—";
  var az = oz.ariza_sayi || 0;
  var sz = oz.setup_sayi || 0;
  if (az === 0 && sz === 0) return "olay yok";
  var parts = [];
  if (az > 0) parts.push(az + " arıza");
  if (sz > 0) parts.push(sz + " kalıp dğ.");
  return parts.join(" · ");
}

function _f2b_abBlok(taraf, kalip_kod, renk_ad, tur, uretim, eski_fallback) {
  var kalip_kismi = kalip_kod
    ? '<span class="or-mak-kalip">' + kalip_kod + '</span>'
    : '<span class="or-mak-kalip or-bos">—</span>';
  var renk_kismi = renk_ad ? '<span class="or-mak-renk">● ' + renk_ad + '</span>' : '';
  var fallback_kismi = eski_fallback
    ? '<span class="or-mak-fallback" title="Saatlik kayıtta A/B ayrımı yok — tahmini bölündü">tahmini</span>'
    : '';
  var tur_str    = (tur != null && typeof fmt === "function") ? fmt(tur) : (tur != null ? String(tur) : "—");
  var uretim_str = (uretim != null && typeof fmt === "function") ? fmt(uretim) : (uretim != null ? String(uretim) : "—");

  return '<div class="or-mak-blok or-mak-blok-' + taraf.toLowerCase() + '">' +
    '<div class="or-mak-blok-bas">' +
      '<span class="or-mak-blok-etiket">' + taraf + '</span>' +
      kalip_kismi + renk_kismi + fallback_kismi +
    '</div>' +
    '<div class="or-mak-blok-deger">' +
      '<span class="or-deger-buyuk"><em>TUR</em> <strong>' + tur_str + '</strong></span>' +
      '<span class="or-deger-buyuk"><em>ÜRET</em> <strong>' + uretim_str + '</strong></span>' +
    '</div>' +
  '</div>';
}

function renderMakineKart(m) {
  var div = document.createElement("div");
  var durum_tip = m.anlik_durum ? m.anlik_durum.tip : "RAPOR_YOK";
  var durum_cls = durum_class(durum_tip);

  div.className = "or-mak-kart durum-" + durum_cls;
  div.dataset.makineId = m.makine_id;
  if (state.secili_makine === m.makine_id) div.classList.add("secili");

  var html = "";

  // UST
  html += '<div class="or-mak-ust">';
  html += '<div class="or-mak-ad">' + (m.makine_kod || "M?") + " · " + (m.makine_ad || "") + "</div>";
  html += '<div class="or-mak-ist-sayi">' + (m.istasyon_sayisi || 0) + " ist · " + (m.slot_sayisi || 0) + " slot</div>";
  html += "</div>";

  // DURUM BADGE
  var badge_metin = "Rapor açılmamış";
  var s = {};
  if (m.anlik_durum) {
    s = m.anlik_durum.sayim || {};
    var detay_net = (s.AKTIF || 0) + " ÇLŞ";
    if (s.SETUP)  detay_net += " • " + s.SETUP + " KLP";
    if (s.ARIZA)  detay_net += " • " + s.ARIZA + " ARZ";
    if (s.KAPALI) detay_net += " • " + s.KAPALI + " KPL";
    var tip_map = {
      TUMUYLA_AKTIF: "Tüm istasyonlar çalışıyor",
      TUMUYLA_KAPALI: "Tüm istasyonlar kapalı",
      HIBRIT: "Karışık Durum · " + detay_net,
      ARIZA_RISKI: "Arıza Riski · " + detay_net,
      TUMUYLA_ARIZA: "Tüm istasyonlar arızalı",
      TUMUYLA_SETUP: "Tüm istasyonlar kalıp değişiminde",
      ARIZA_VE_SETUP: "Arıza + Kalıp Değişim",
      DURUYOR: "Duruyor"
    };
    badge_metin = tip_map[m.anlik_durum.tip] || m.anlik_durum.tip;
  }
  html += '<div class="or-mak-durum-badge ' + durum_cls + '">' + badge_metin + "</div>";

  // RAPOR YOK ERKEN CIKIS
  if (!m.anlik_durum) {
    html += '<div style="padding:14px;text-align:center;background:#fafaf6;border-radius:4px;color:#888780;font-size:11px;">';
    html += "Bu makinede bugün " + (state.vardiya === "gunduz" ? "gündüz" : "gece") + " vardiyası için rapor açılmamış.";
    html += "</div>";
    div.innerHTML = html;
    div.style.cursor = "default";
    return div;
  }

  // SLOT BAR (mevcut korunuyor)
  var top = m.anlik_durum.toplam_slot || 1;
  var pct_a = (s.AKTIF / top) * 100;
  var pct_s = (s.SETUP / top) * 100;
  var pct_z = (s.ARIZA / top) * 100;
  var pct_k = (s.KAPALI / top) * 100;
  html += '<div class="or-slot-bar">';
  if (pct_a > 0) html += '<div class="or-slot-bar-aktif"  style="width:' + pct_a + '%"></div>';
  if (pct_s > 0) html += '<div class="or-slot-bar-setup"  style="width:' + pct_s + '%"></div>';
  if (pct_z > 0) html += '<div class="or-slot-bar-ariza"  style="width:' + pct_z + '%"></div>';
  if (pct_k > 0) html += '<div class="or-slot-bar-kapali" style="width:' + pct_k + '%"></div>';
  html += "</div>";

  // A/B BLOKLAR
  var u = m.uretim || {};
  var eski_fb = u.eski_sistem_fallback === true;
  // F9_5_4B_KALIP_OZET_BEGIN
  var ako = u.a_kalip_ozet, bko = u.b_kalip_ozet;
  function _renkAdGuzelles(s) {
    if (!s) return null;
    return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  }
  var a_kalip_str = ako ? (ako.kod + (ako.farkli_sayi > 0 ? " +" + ako.farkli_sayi : "")) : null;
  var b_kalip_str = bko ? (bko.kod + (bko.farkli_sayi > 0 ? " +" + bko.farkli_sayi : "")) : null;
  var a_renk_str = ako ? _renkAdGuzelles(ako.renk_ad) : null;
  var b_renk_str = bko ? _renkAdGuzelles(bko.renk_ad) : null;
  // F9_5_4B_KALIP_OZET_END
  html += '<div class="or-mak-ab">';
  html += _f2b_abBlok("A", a_kalip_str, a_renk_str, u.tur_a, u.uretilen_a, eski_fb);
  html += _f2b_abBlok("B", b_kalip_str, b_renk_str, u.tur_b, u.uretilen_b, eski_fb);
  html += '</div>';

  // OZET STRIP
  var verim_cls = _f2b_verimClass(u.verim_yuzde);
  var fire_cls  = _f2b_fireClass(u.fire_seviye);
  var fire_orani_str = (u.fire_orani != null) ? ' <small>(%' + u.fire_orani + ')</small>' : '';
  function f(v) { return (v != null && typeof fmt === "function") ? fmt(v) : (v != null ? String(v) : "—"); }

  html += '<div class="or-mak-ozet">';
  html +=   '<span class="or-mak-ozet-cell"><em>Toplam</em> ' + f(u.brut_cift) + '</span>';
  html +=   '<span class="or-mak-ozet-cell"><em>Teorik</em> ' + f(u.teorik_cift) + '</span>';
  html +=   '<span class="or-mak-ozet-cell or-fire ' + fire_cls + '"><em>Fire</em> ' + f(u.fire_cift) + fire_orani_str + '</span>';
  html +=   '<span class="or-mak-ozet-cell"><em>Net</em> ' + f(u.net_cift) + '</span>';
  html +=   '<span class="or-verim-badge ' + verim_cls + '">' + (u.verim_yuzde != null ? "%" + u.verim_yuzde : "—") + '</span>';
  html +=   '<span class="or-mak-ozet-cell or-son-olay"><em>Son</em> ' + _f2b_sonOlaySozcuk(m.olay_ozet) + '</span>';
  html += '</div>';

  // FOOTER: benzersiz aktif istasyon sayisi + toplam slot
  var aktif_oran = (m.anlik_durum.aktif_oran * 100).toFixed(0);
  var personel_str = (m.personel_sayisi != null && m.personel_sayisi > 0)
    ? ' · <em>Personel:</em> <strong>' + m.personel_sayisi + '</strong>'
    : '';
  // Aktif slotlardan benzersiz istasyon_no sayisi hesapla
  var _aktif_ist_set = {};
  (m.slotlar || []).forEach(function(sl) {
    if ((sl.durum || '').toUpperCase() === 'AKTIF' && sl.istasyon_no != null) {
      _aktif_ist_set[sl.istasyon_no] = true;
    }
  });
  var aktif_ist_sayi = Object.keys(_aktif_ist_set).length;
  var aktif_slot_sayi = s.AKTIF || 0;
  var ist_slot_str = aktif_ist_sayi > 0
    ? aktif_ist_sayi + ' istasyon / ' + aktif_slot_sayi + ' slot aktif'
    : aktif_slot_sayi + ' slot aktif';
  html += '<div class="or-mak-alt">';
  html += '<span class="or-mak-aktif-orani"><strong>' + ist_slot_str + '</strong> (%' + aktif_oran + ')' + personel_str + '</span>';
  html += '<button class="or-mak-detay-btn" data-makine-id="' + m.makine_id + '">Detay →</button>';
  html += "</div>";

  div.innerHTML = html;
  return div;
}
// F9_5_4B_TABLO_END

  function renderMakineler(genel) {
    var grid = $("or-makine-grid");
    grid.innerHTML = "";
    
    if (!genel.makineler || genel.makineler.length === 0) {
      grid.innerHTML = '<div class="or-yukleniyor">Makine verisi yok</div>';
      return;
    }
    
    genel.makineler.forEach(function(m) {
      grid.appendChild(renderMakineKart(m));
    });
    
    // Detay buton click
    $$(".or-mak-detay-btn", grid).forEach(function(b) {
      b.addEventListener("click", function(e) {
        e.stopPropagation();
        var mid = parseInt(this.dataset.makineId, 10);
        detayAc(mid);
      });
    });
  }

  // ============================================================
  // RENDER: UYARI OZET (alt bilgi)
  // ============================================================
  function renderUyariOzet(genel) {
    var sayim = { info: 0, warning: 0, error: 0 };
    genel.makineler.forEach(function(m) {
      (m.uyarilar || []).forEach(function(u) {
        if (sayim[u.seviye] !== undefined) sayim[u.seviye]++;
      });
    });
    
    var el = $("or-uyari-ozet");
    var html = "";
    if (sayim.warning > 0) {
      html += '<span class="or-uyari-item warning">⚠ ' + sayim.warning + " uyarı</span>";
    }
    if (sayim.info > 0) {
      html += '<span class="or-uyari-item info">ⓘ ' + sayim.info + " bilgi</span>";
    }
    // FIELD_TEST_READY: V1 sinirlamasi bilgi mesaji (korkutucu olmayan)
    html += '<span class="or-uyari-item info" title="V1: Anlık istasyon düzenine göre hesap. Vardiya içi kalıp değişimi için saatlik snapshot (V1.5) planlanıyor." style="border-left:2px solid #b4b2a9;padding-left:6px;margin-left:6px;">ℹ V1 Yaklaşık Hesap</span>';
    if (html.indexOf("uyari") < 0 && html.indexOf("bilgi") < 0) {
      html = '<span class="or-uyari-item info">Tüm veriler hazır</span>' + html;
    }
    el.innerHTML = html;
  }

  // ============================================================
  // DETAY PANELI
  // ============================================================
  function detayAc(makine_id) {
    state.secili_makine = makine_id;
    
    // Kartları yeniden render (secili classi guncel)
    $$(".or-mak-kart").forEach(function(k) {
      k.classList.toggle("secili", parseInt(k.dataset.makineId, 10) === makine_id);
    });
    
    var detay = $("or-detay");
    detay.style.display = "block";
    $("or-detay-icerik").innerHTML = '<div class="or-yukleniyor">Detay yükleniyor…</div>';
    
    apiMakine(makine_id, state.tarih, state.vardiya)
      .then(function(data) {
        state.makine_detay = data.makine;
        renderDetay(data.makine);
      })
      .catch(function(e) {
        $("or-detay-icerik").innerHTML = '<div class="or-yukleniyor" style="color:#a32d2d;">Detay yüklenemedi: ' + e.message + "</div>";
      });
  }

  // F9_5_4C_DETAY_SEKME_BEGIN

// F9_5_5C_HESAP_BLOK_BEGIN
function _f2c_renderM3HesapNotu(m) {
  // YENI: Gorsel uretim hesabi grid. "bagli" kelimesi kaldirildi.
  // Formul: aktif_yuva x KBC x tur = uretim
  var u = m.uretim || {};
  var slotlar = m.slotlar || [];
  if (!slotlar.length) return "";

  function _ozetTarafi(taraf) {
    var aktif = slotlar.filter(function(s) {
      return (s.slot || "").toUpperCase() === taraf && (s.durum || "").toUpperCase() === "AKTIF";
    });
    if (!aktif.length) return null;
    var ilk = aktif[0];
    var kbc = (ilk.kalip && ilk.kalip.kalip_basi_cift) || 0;
    if (!kbc) return null;
    return {
      aktif_yuva: aktif.length,
      kbc: kbc,
      kalip_kod: (ilk.kalip && ilk.kalip.kod) || (ilk.kalip && ilk.kalip.kalip_kod) || "—",
      renk_ad: ilk.renk_ad || null,
      farkli_sayi: 0
    };
  }

  function _renkAdGuzelles(s) {
    if (!s) return null;
    return s.charAt(0).toUpperCase() + s.slice(1).toLocaleLowerCase("tr-TR");
  }

  function _fmtSayi(v) {
    return (typeof fmt === "function" && v != null) ? fmt(v) : (v != null ? String(v) : "—");
  }

  var aOzet = _ozetTarafi("A");
  var bOzet = _ozetTarafi("B");

  var aGoster = (aOzet && (u.tur_a || 0) > 0 && (u.uretilen_a || 0) > 0);
  var bGoster = (bOzet && (u.tur_b || 0) > 0 && (u.uretilen_b || 0) > 0);

  if (!aGoster && !bGoster) return "";

  function _satir(taraf, ozet, tur, uretim) {
    var renk_ad = _renkAdGuzelles(ozet.renk_ad);
    var renk_html = renk_ad ? '<span class="or-uretim-kalip-renk">● ' + renk_ad + '</span>' : '';
    return '<div class="or-uretim-satir or-uretim-' + taraf.toLowerCase() + '">' +
      '<div class="or-uretim-etiket-bol"><span class="or-mak-blok-etiket or-uretim-etiket">' + taraf + '</span></div>' +
      '<div class="or-uretim-kalip-info">' +
        '<span class="or-uretim-kalip-kod">' + ozet.kalip_kod + '</span>' +
        renk_html +
      '</div>' +
      '<div class="or-uretim-formul">' +
        '<span class="or-uretim-carpan"><span class="or-uretim-carpan-sayi">' + ozet.aktif_yuva + '</span><span class="or-uretim-carpan-label">Aktif Yuva</span></span>' +
        '<span class="or-uretim-isaret">×</span>' +
        '<span class="or-uretim-carpan"><span class="or-uretim-carpan-sayi">' + ozet.kbc + '</span><span class="or-uretim-carpan-label">Çift/Tur</span></span>' +
        '<span class="or-uretim-isaret">×</span>' +
        '<span class="or-uretim-carpan"><span class="or-uretim-carpan-sayi">' + tur + '</span><span class="or-uretim-carpan-label">Tur</span></span>' +
        '<span class="or-uretim-isaret or-uretim-esit">=</span>' +
        '<span class="or-uretim-sonuc"><span class="or-uretim-sonuc-sayi">' + _fmtSayi(uretim) + '</span><span class="or-uretim-sonuc-label">Çift</span></span>' +
      '</div>' +
    '</div>';
  }

  var html = '<div class="or-uretim-hesabi">' +
    '<div class="or-uretim-hesabi-bas">ÜRETİM HESABI</div>';
  if (aGoster) html += _satir("A", aOzet, u.tur_a, u.uretilen_a);
  if (bGoster) html += _satir("B", bOzet, u.tur_b, u.uretilen_b);
  html += '</div>';

  return html;
}
// F9_5_5C_HESAP_BLOK_END

function _f2c_renderFire(m) {
  var u = m.uretim || {};
  var fire_cift = u.fire_cift || 0;
  var fire_orani = u.fire_orani;
  var fire_kg = u.fire_kg || 0;
  var teknik_kg = u.teknik_fire_kg || 0;
  var bos_kg = u.bos_atis_kg || 0;
  var yolluk_kg = u.yolluk_fire_kg || 0;
  var brut = u.brut_cift || 0;
  var net = u.net_cift;
  var net_kaynak = u.net_kaynak;
  var fire_seviye = u.fire_seviye || "normal";
  var f = function(v) { return (typeof fmt === "function" && v != null) ? fmt(v) : (v != null ? String(v) : "—"); };

  var toplam_bd = teknik_kg + bos_kg + yolluk_kg;
  function pct(v) { return toplam_bd > 0 ? Math.round((v / toplam_bd) * 100) : 0; }

  var html = '<div class="or-fire-detay">';

  // TOPLAM
  html += '<div class="or-fire-grup">';
  html +=   '<div class="or-fire-grup-bas">TOPLAM FİRE</div>';
  html +=   '<div class="or-fire-satir"><span>Fire çift</span><strong>' + f(fire_cift) + '</strong></div>';
  html +=   '<div class="or-fire-satir"><span>Fire oranı</span><strong>' + (fire_orani != null ? "%" + fire_orani : "—") + ' <em class="seviye-' + fire_seviye + '">' + fire_seviye + '</em></strong></div>';
  html +=   '<div class="or-fire-satir"><span>Fire kg</span><strong>' + (fire_kg ? fire_kg.toFixed(1) + " kg" : "—") + '</strong></div>';
  html += '</div>';

  // BREAKDOWN
  html += '<div class="or-fire-grup">';
  html +=   '<div class="or-fire-grup-bas">BREAKDOWN</div>';
  ["Teknik Fire", "Boş Atış", "Yolluk Fire"].forEach(function(ad, i) {
    var v = [teknik_kg, bos_kg, yolluk_kg][i];
    html += '<div class="or-fire-bd-satir">';
    html +=   '<span>' + ad + '</span>';
    html +=   '<strong>' + (v ? v.toFixed(1) + " kg" : "0.0 kg") + '</strong>';
    html +=   '<div class="or-bar"><div class="or-bar-doluluk" style="width:' + pct(v) + '%"></div></div>';
    html +=   '<em>%' + pct(v) + '</em>';
    html += '</div>';
  });
  html += '</div>';

  // NET HESAP
  html += '<div class="or-fire-grup">';
  html +=   '<div class="or-fire-grup-bas">NET HESAP</div>';
  html +=   '<div class="or-fire-satir"><span>Brüt çift</span><strong>' + f(brut) + '</strong></div>';
  html +=   '<div class="or-fire-satir"><span>Fire çift</span><strong>−' + f(fire_cift) + '</strong></div>';
  html +=   '<div class="or-fire-satir or-fire-net"><span>Net çift</span><strong>' + f(net) + ' <em>' + (net_kaynak || "—") + '</em></strong></div>';
  html += '</div>';

  html += '</div>';
  return html;
}

function _f2c_renderSaatlikGenisletilmis(saatlik, m) {
  if (!saatlik || !saatlik.detaylar) return '<div class="or-olay-bos">Saatlik veri yok</div>';
  var u = (m && m.uretim) || {};
  var gunluk_uretim = (u.uretilen_a || 0) + (u.uretilen_b || 0);
  var gunluk_fire = u.fire_cift || 0;
  var teorik = u.teorik_cift || 0;
  var gunluk_tur = (u.tur_a || 0) + (u.tur_b || 0);
  var f = function(v) { return (typeof fmt === "function" && v != null) ? fmt(v) : (v != null ? String(v) : "—"); };

  var prorate_var = (gunluk_fire > 0 && gunluk_uretim > 0);

  var html = "";
  if (prorate_var) {
    html += '<div class="or-saatlik-not">Fire değerleri günlük toplamdan prorate (yaklaşık)</div>';
  }
  html += '<table class="or-saatlik-tablo or-saatlik-genis">';
  html += '<thead><tr><th>Saat</th><th>A TUR</th><th>B TUR</th><th>Top</th><th>Üretim</th><th>Fire' + (prorate_var ? "*" : "") + '</th><th>Net</th><th>Verim</th></tr></thead>';
  html += "<tbody>";

  var top = { a: 0, b: 0, t: 0, uretim: 0, fire: 0, net: 0 };

  (saatlik.detaylar || []).forEach(function(d) {
    var a = d.cevrim_a || 0;
    var b = d.cevrim_b || 0;
    var t = a + b;
    var su = (d.uretilen_a || 0) + (d.uretilen_b || 0);
    var sf = (gunluk_uretim > 0 && gunluk_fire > 0) ? Math.round(gunluk_fire * (su / gunluk_uretim)) : 0;
    var sn = su - sf;
    var st = (gunluk_tur > 0 && teorik > 0) ? Math.round(teorik * (t / gunluk_tur)) : 0;
    var sv = (st > 0 && sn != null) ? Math.round((sn / st) * 100) : null;

    top.a += a; top.b += b; top.t += t;
    top.uretim += su; top.fire += sf; top.net += sn;

    var bos = (t === 0 && su === 0);
    html += '<tr' + (bos ? ' class="bos"' : '') + '>';
    html +=   '<td>' + (d.saat || "—") + '</td>';
    html +=   '<td>' + (a || "—") + '</td>';
    html +=   '<td>' + (b || "—") + '</td>';
    html +=   '<td>' + (t || "—") + '</td>';
    html +=   '<td>' + (su ? f(su) : "—") + '</td>';
    html +=   '<td>' + (sf || (gunluk_fire === 0 ? "—" : sf)) + '</td>';
    html +=   '<td>' + (sn > 0 ? f(sn) : "—") + '</td>';
    html +=   '<td>' + (sv != null ? "%" + sv : "—") + '</td>';
    html += '</tr>';
  });

  var top_verim = (teorik > 0 && top.net > 0) ? Math.round((top.net / teorik) * 100) : null;
  html += '<tr class="toplam">';
  html +=   '<td><strong>TOP</strong></td>';
  html +=   '<td><strong>' + top.a + '</strong></td>';
  html +=   '<td><strong>' + top.b + '</strong></td>';
  html +=   '<td><strong>' + top.t + '</strong></td>';
  html +=   '<td><strong>' + (top.uretim ? f(top.uretim) : "—") + '</strong></td>';
  html +=   '<td><strong>' + top.fire + '</strong></td>';
  html +=   '<td><strong>' + (top.net ? f(top.net) : "—") + '</strong></td>';
  html +=   '<td><strong>' + (top_verim != null ? "%" + top_verim : "—") + '</strong></td>';
  html += '</tr>';

  html += "</tbody></table>";
  return html;
}

function _f2c_sekmeIcerigiYukle(sekme) {
  var icerik = document.getElementById("or-detay-sekme-icerik");
  if (!icerik) return;
  var m = state.makine_detay;
  if (!m) {
    icerik.innerHTML = '<div class="or-yukleniyor">Veri yok</div>';
    return;
  }

  if (sekme === "istasyon") {
    var html = "";
    var hesap_notu = _f2c_renderM3HesapNotu(m);
    if (hesap_notu) html += hesap_notu;
    html += renderSlotGrid(m);
    icerik.innerHTML = html;
  }
  else if (sekme === "fire") {
    icerik.innerHTML = _f2c_renderFire(m);
  }
  else if (sekme === "saatlik") {
    icerik.innerHTML = _f2c_renderSaatlikGenisletilmis(m.saatlik, m);
  }
  else if (sekme === "olaylar") {
    var html2 = "";
    if (m.slot_dakika_dagilim) {
      html2 += '<div class="or-detay-bolum-baslik">İstasyon-Dakika Dağılımı</div>';
      html2 += renderSlotDakika(m.slot_dakika_dagilim);
    }
    html2 += '<div class="or-detay-bolum-baslik" style="margin-top:14px;">Olay Listesi</div>';
    html2 += '<div id="or-olay-liste-yuk" class="or-yukleniyor" style="padding:8px;">Yükleniyor…</div>';
    icerik.innerHTML = html2;
    // Lazy fetch
    apiTimeline(m.rapor_id)
      .then(function(data) {
        var liste = document.getElementById("or-olay-liste-yuk");
        if (liste) liste.outerHTML = renderOlayListesi(data.olaylar);
      })
      .catch(function() {
        var liste = document.getElementById("or-olay-liste-yuk");
        if (liste) liste.outerHTML = '<div class="or-olay-bos">Olaylar yüklenemedi</div>';
      });
  }
}

function _f2c_sekmeDegistir(sekme) {
  state.detay_aktif_sekme = sekme;
  var butonlar = document.querySelectorAll(".or-detay-sekme");
  for (var i = 0; i < butonlar.length; i++) {
    butonlar[i].classList.toggle("aktif", butonlar[i].dataset.sekme === sekme);
  }
  _f2c_sekmeIcerigiYukle(sekme);
}

function renderDetay(m) {
  state.makine_detay = m;
  state.detay_aktif_sekme = "saatlik";

  document.getElementById("or-detay-makine-ad").textContent = m.makine_kod + " · " + m.makine_ad + " · Detay";
  var durum_tip = m.anlik_durum ? m.anlik_durum.tip : "RAPOR_YOK";
  var durum_cls = durum_class(durum_tip);
  var badge = document.getElementById("or-detay-durum");
  badge.className = "or-detay-durum-badge " + durum_cls;
  badge.textContent = m.anlik_durum ? m.anlik_durum.detay : "Rapor yok";

  var v_dk = m.aralik ? m.aralik.gecen_dk : 0;
  var v_top = m.aralik ? m.aralik.sure_dk : 0;
  document.getElementById("or-detay-vardiya-dk").textContent = v_dk + "/" + v_top + " dk";

  if (!m.anlik_durum) {
    document.getElementById("or-detay-icerik").innerHTML = '<div style="padding:20px;text-align:center;color:#888;">Bu makinede rapor açılmamış.</div>';
    return;
  }

  // Sekme seridi + icerik kabi
  var aktif = state.detay_aktif_sekme;
  var sekmeler = [
    { id: "istasyon", ad: "İstasyon" },
    { id: "fire",     ad: "Fire" },
    { id: "saatlik",  ad: "Saatlik" },
    { id: "olaylar",  ad: "Olaylar" }
  ];
  var html = '<div class="or-detay-sekmeler">';
  sekmeler.forEach(function(s) {
    html += '<button type="button" class="or-detay-sekme' + (s.id === aktif ? ' aktif' : '') + '" data-sekme="' + s.id + '">' + s.ad + '</button>';
  });
  html += '</div>';
  html += '<div class="or-detay-sekme-icerik" id="or-detay-sekme-icerik"></div>';

  document.getElementById("or-detay-icerik").innerHTML = html;

  // Event bind
  var butonlar = document.querySelectorAll(".or-detay-sekme");
  for (var i = 0; i < butonlar.length; i++) {
    butonlar[i].addEventListener("click", function() {
      _f2c_sekmeDegistir(this.dataset.sekme);
    });
  }

  // Aktif sekme icerigi
  _f2c_sekmeIcerigiYukle(aktif);
}
// F9_5_4C_DETAY_SEKME_END
  function renderSlotGrid(m) {
    // ISTASYON_GRID_V4 (15.05.2026): Istasyon karti + A/B yan yana
    // Operator enjeksiyon ekranindaki ile ayni mantik
    if (!m.slotlar || m.slotlar.length === 0) return '<div class="or-olay-bos">Slot verisi yok</div>';
    
    var ist_sayi = m.istasyon_sayisi;
    var grid_cls = "or-istasyon-grid ist-" + ist_sayi;
    
    var html = '<div class="' + grid_cls + '">';
    
    for (var i = 1; i <= ist_sayi; i++) {
      html += '<div class="or-istasyon-kart">';
      html += '<div class="or-istasyon-baslik">İST ' + i + '</div>';
      html += '<div class="or-istasyon-slotlar">';
      
      ["A", "B"].forEach(function(slot_harf) {
        var slot = m.slotlar.find(function(s) {
          return s.istasyon_no === i && s.slot === slot_harf;
        });
        
        if (!slot) {
          // TERMINOLOGY_V1: KPL etiket + uzun tooltip
          html += '<div class="or-slot-mini s-kapali" title="İST' + i + '-' + slot_harf + ' • Kapalı">';
          html += '<span class="or-slot-mini-harf">' + slot_harf + '</span>';
          html += '<span class="or-slot-mini-durum">KPL</span>';
          html += '</div>';
          return;
        }
        
        var durum = (slot.durum || "KAPALI").toUpperCase();
        var cls, durum_label;
        
        // TERMINOLOGY_V1: operasyon dili kisaltma
        if (durum === "AKTIF") { cls = "s-aktif"; durum_label = "ÇLŞ"; }
        else if (durum === "SETUP") { cls = "s-setup"; durum_label = "KLP"; }
        else if (durum === "ARIZA") { cls = "s-ariza"; durum_label = "ARZ"; }
        else { cls = "s-kapali"; durum_label = "KPL"; }
        
        var kalip_kod = "";
        if (slot.kalip) {
          kalip_kod = slot.kalip.kod || slot.kalip.kalip_kod || ("#" + (slot.kalip.id || ""));
        }
        
        var durum_uzun = {
          "AKTIF": "Çalışıyor",
          "SETUP": "Kalıp Değişim",
          "ARIZA": "Arıza",
          "KAPALI": "Kapalı"
        }[durum] || durum;
        var tooltip = "İST" + i + "-" + slot_harf + " • " + durum_uzun + (kalip_kod ? " • " + kalip_kod : "");
        
        html += '<div class="or-slot-mini ' + cls + '" title="' + tooltip + '">';
        html += '<span class="or-slot-mini-harf">' + slot_harf + '</span>';
        html += '<span class="or-slot-mini-durum">' + durum_label + '</span>';
        if (kalip_kod && durum !== "KAPALI") {
          html += '<span class="or-slot-mini-kalip">' + kalip_kod + '</span>';
        }
        html += '</div>';
      });
      
      html += '</div>'; // /or-istasyon-slotlar
      html += '</div>'; // /or-istasyon-kart
    }
    
    html += "</div>"; // /or-istasyon-grid
    return html;
  }

  function renderSaatlikTablo(saatlik) {
    var html = '<table class="or-saatlik-tablo">';
    html += '<thead><tr><th>Saat</th><th>Tur</th><th>Durum</th></tr></thead>';
    html += "<tbody>";
    var top = 0;
    (saatlik.detaylar || []).forEach(function(d) {
      var bos = !d.tur_adet || d.tur_adet === 0;
      // AKSAMA_AUTOREFRESH_V1: durus durumlarinda sebep + aciklama goster
      var durum_txt;
      if (d.durum === "calisiyor") {
        durum_txt = "Çalışıyor";
      } else if (d.durum === "durus") {
        var sebep = "";
        if (d.aksama_sebep_id && state.aksama_sebepleri[d.aksama_sebep_id]) {
          sebep = state.aksama_sebepleri[d.aksama_sebep_id];
        } else if (d.aciklama) {
          sebep = d.aciklama;
        }
        durum_txt = sebep ? "Duruş · " + sebep : "Duruş";
      } else {
        durum_txt = d.durum || "—";
      }
      var renk = "";
      if (d.durum && d.durum !== "calisiyor") renk = "color:#a32d2d;";
      html += '<tr' + (bos ? ' class="bos"' : '') + '>';
      html += '<td>' + (d.saat || "—") + "</td>";
      html += '<td>' + (bos ? "—" : d.tur_adet) + "</td>";
      html += '<td style="' + renk + '">' + durum_txt + "</td>";
      html += "</tr>";
      if (d.tur_adet) top += d.tur_adet;
    });
    html += '<tr class="toplam"><td>Toplam</td><td>' + top + "</td><td></td></tr>";
    html += "</tbody></table>";
    return html;
  }

  function renderSlotDakika(sd) {
    if (!sd || !sd.toplam) return '<div class="or-olay-bos">Veri yok</div>';
    var top = sd.toplam || 1;
    function bar(ad, deger, cls) {
      var pct = ((deger || 0) / top) * 100;
      return '<div class="or-sd-blok ' + cls + '">' +
             '<div class="or-sd-ust"><span class="or-sd-etiket">' + ad + '</span><span class="or-sd-deger">' + (deger || 0) + ' dk · %' + pct.toFixed(0) + '</span></div>' +
             '<div class="or-sd-bar"><div class="or-sd-bar-fill" style="width:' + pct.toFixed(1) + '%;"></div></div>' +
             "</div>";
    }
    var html = '<div class="or-sd-liste">';
    html += bar("Çalışıyor", sd.AKTIF, "aktif");
    html += bar("Kalıp Değişim", sd.SETUP, "setup");
    html += bar("Arıza", sd.ARIZA, "ariza");
    html += bar("Kapalı", sd.KAPALI, "kapali");
    html += "</div>";
    html += '<div class="or-sd-toplam"><span>Toplam</span><span class="or-sd-toplam-deger">' + top + " istasyon-dk</span></div>";
    return html;
  }

  function renderOlayListesi(olaylar) {
    if (!olaylar || olaylar.length === 0) {
      return '<div class="or-olay-bos">Henüz olay yok</div>';
    }
    // Sadece SETUP_START/END ve ARIZA_START/END goster (V1)
    var filtreli = olaylar.filter(function(o) {
      return ["SETUP_START", "SETUP_END", "ARIZA_START", "ARIZA_END"].indexOf(o.tip) >= 0;
    });
    if (filtreli.length === 0) {
      return '<div class="or-olay-bos">Setup / arıza olayı yok</div>';
    }
    var html = '<div class="or-olay-liste">';
    filtreli.slice(0, 30).forEach(function(o) {
      var tip_cls = "diger";
      if (o.tip.indexOf("SETUP") === 0) tip_cls = "setup";
      else if (o.tip.indexOf("ARIZA") === 0) tip_cls = "ariza";
      
      // TERMINOLOGY_V1: olay tip uzun isim
      var tip_isim = {
        "SETUP_START": "Kalıp Değişim ▶",
        "SETUP_END": "Kalıp Değişim ✓",
        "ARIZA_START": "Arıza ▶",
        "ARIZA_END": "Arıza ✓"
      };
      var tip_kisa = tip_isim[o.tip] || o.tip.replace("_START", " ▶").replace("_END", " ✓");
      var zaman_kisa = (o.zaman || "").substring(11, 16);
      var ist = o.istasyon_label || "—";
      var detay = o.detay || {};
      var sure = detay.sure_dakika ? ' · <span class="or-olay-detay-sure">' + detay.sure_dakika + ' dk</span>' : "";
      
      html += '<div class="or-olay">';
      html += '<span class="or-olay-saat">' + zaman_kisa + "</span>";
      html += '<span class="or-olay-tip ' + tip_cls + '">' + tip_kisa + "</span>";
      html += '<span class="or-olay-metin">' + ist + sure + "</span>";
      html += "</div>";
    });
    html += "</div>";
    return html;
  }

  // ============================================================
  // YUKLEME AKISI
  // ============================================================
  function ana_yukle(sessiz) {
    // AKSAMA_AUTOREFRESH_V1: sessiz=true ise spinner gosterme (otomatik yenileme)
    state.son_yukleme = Date.now();
    var btn = $("or-btn-yenile");
    if (btn && !sessiz) btn.classList.add("donuyor");
    
    apiGenel(state.tarih, state.vardiya)
      .then(function(data) {
        if (!data.ok) throw new Error(data.hata || "Bilinmeyen hata");
        state.genel = data;
        renderFiltreVardiya(data.filtre);
        renderKpi(data);
        renderMakineler(data);
        renderUyariOzet(data);
        $("or-son-gun").textContent = data.olusturuldu || "—";
        
        // Eger detay panel acik ise, secili makineyi de guncelle (sessiz)
        if (state.secili_makine && document.getElementById("or-detay").style.display !== "none") {
          apiMakine(state.secili_makine, state.tarih, state.vardiya)
            .then(function(d) {
              state.makine_detay = d.makine;
              renderDetay(d.makine);
            })
            .catch(function() {});
        }
      })
      .catch(function(e) {
        if (!sessiz) {
          $("or-makine-grid").innerHTML = '<div class="or-yukleniyor" style="color:#a32d2d;">Hata: ' + e.message + "</div>";
        }
      })
      .finally(function() {
        if (btn) btn.classList.remove("donuyor");
      });
  }

  function filtre_uygula() {
    state.tarih = $("or-tarih").value || bugun_iso();
    state.vardiya = $("or-vardiya").value || aktif_vardiya();
    state.secili_makine = null;
    $("or-detay").style.display = "none";
    ana_yukle();
  }

  // ============================================================
  // INIT
  // ============================================================
  function init() {
    state.tarih = bugun_iso();
    state.vardiya = aktif_vardiya();
    $("or-tarih").value = state.tarih;
    $("or-vardiya").value = state.vardiya;
    
    $("or-btn-uygula").addEventListener("click", filtre_uygula);
    $("or-btn-yenile").addEventListener("click", ana_yukle);
    $("or-btn-detay-kapat").addEventListener("click", function() {
      $("or-detay").style.display = "none";
      state.secili_makine = null;
      $$(".or-mak-kart").forEach(function(k) { k.classList.remove("secili"); });
    });
    $("or-tarih").addEventListener("change", filtre_uygula);
    $("or-vardiya").addEventListener("change", filtre_uygula);
    
    // AKSAMA_AUTOREFRESH_V1: sebep listesi cache (tek seferlik)
    apiAksamaSebepleri()
      .then(function(data) {
        var liste = data.sebepler || data.data || data;
        if (Array.isArray(liste)) {
          liste.forEach(function(s) {
            if (s.id) state.aksama_sebepleri[s.id] = s.ad || s.name || "";
          });
        }
      })
      .catch(function() { /* Sessiz - sebep liste kritik degil */ });
    
    // AUTO REFRESH (5 sn) - sekme goruluyor + auto_refresh_aktif ise
    state.auto_refresh_timer = setInterval(function() {
      if (!state.auto_refresh_aktif) return;
      if (document.visibilityState !== "visible") return;
      // Manuel yenileme yapildi mi (cok yakin)? Skip et
      var simdi = Date.now();
      if (simdi - state.son_yukleme < 3000) return;
      ana_yukle(true);  // sessiz mod
    }, AUTO_REFRESH_MS);
    
    // Sekme degisikliklerinde
    document.addEventListener("visibilitychange", function() {
      if (document.visibilityState === "visible") {
        ana_yukle(true);  // sekmeye dondugunde anında guncelle
      }
    });
    
    ana_yukle();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
