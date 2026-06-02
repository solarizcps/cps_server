/* ===========================================================
 * usta.js - MINI FAZ B (Faz 4.3 mantigi)
 * Sade is emri panel: ATANDI -> OKUNDU -> BASLADI -> TAMAMLANDI
 *
 * Backend endpoint'leri (gercek olanlar):
 *   GET  /usta/api/gorevler?durum=acik|hepsi
 *   POST /usta/api/gorev/<id>/okudu
 *   POST /usta/api/gorev/<id>/basladi
 *   POST /usta/api/gorev/<id>/bitti
 *
 * Hayalet endpoint cagirilmaz: /api/v2/usta/*
 * =========================================================== */

(function () {
  "use strict";

  // ============== STATE ==============
  var _aciKisleriYuklendi = false;
  var _onaylariYuklendi = false;

  // ============== HELPER'LAR ==============
  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function showError(elId, msg) {
    var el = $(elId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    setTimeout(function () { el.style.display = "none"; }, 5000);
  }

  function showSuccess(elId, msg) {
    var el = $(elId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    setTimeout(function () { el.style.display = "none"; }, 4000);
  }

  function fmtTarih(ts) {
    if (!ts) return "-";
    // "2026-05-06 18:55:24" -> "06.05.2026 18:55"
    var m = String(ts).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (!m) return ts;
    return m[3] + "." + m[2] + "." + m[1] + " " + m[4] + ":" + m[5];
  }

  // ============== API ==============
  async function apiFetch(path, options) {
    options = options || {};
    options.headers = options.headers || {};
    if (options.method === "POST") {
      options.headers["Content-Type"] = "application/json";
    }
    options.credentials = "same-origin";

    var resp = await fetch(path, options);
    var text = await resp.text();
    var data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (e) {
      data = { ok: false, hata: "parse_hatasi", mesaj: text.slice(0, 200) };
    }
    return { status: resp.status, data: data };
  }

  // ============== TAB DEGISTIRME ==============
  function setupTabs() {
    var tabs = document.querySelectorAll(".u-tab");
    var panes = document.querySelectorAll(".u-pane");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var hedef = tab.getAttribute("data-tab");
        tabs.forEach(function (t) { t.classList.remove("active"); });
        panes.forEach(function (p) { p.classList.remove("active"); });
        tab.classList.add("active");
        var pane = $("pane-" + hedef);
        if (pane) pane.classList.add("active");

        if (hedef === "isler" && !_aciKisleriYuklendi) acikIsleriYukle();
        if (hedef === "onay" && !_onaylariYuklendi) tamamlananlariYukle();
      });
    });
  }

  // ============== 1) ACIK ISLER (ATANDI/OKUNDU/BASLADI) ==============
  async function acikIsleriYukle() {
    var liste = $("islerList");
    if (liste) liste.innerHTML = '<div class="u-empty">Yukleniyor...</div>';

    try {
      var r = await apiFetch("/usta/api/gorevler?durum=acik");
      if (r.status === 401 || r.status === 403) {
        if (liste) liste.innerHTML = '<div class="u-empty">Oturum gecersiz. Sayfayi yenileyin.</div>';
        return;
      }
      if (r.status >= 400 || (r.data && r.data.ok === false)) {
        showError("islerError", (r.data && r.data.mesaj) || ("HTTP " + r.status));
        if (liste) liste.innerHTML = '<div class="u-empty">Yuklenemedi.</div>';
        return;
      }

      var gorevler = (r.data && r.data.gorevler) || [];
      renderIsler(gorevler);
      guncelleBadgeAtandi(r.data.atandi_sayisi || 0);
      _aciKisleriYuklendi = true;
      console.log("[USTA] acik isler:", gorevler.length, "(atandi:", r.data.atandi_sayisi || 0, ")");
    } catch (e) {
      console.warn("[USTA] acik-isler fetch error:", e.message);
      showError("islerError", "Sunucuya ulasilamadi: " + e.message);
      if (liste) liste.innerHTML = '<div class="u-empty">Baglanti hatasi.</div>';
    }
  }

  function durumButon(g) {
    // ATANDI -> OKUDUM, OKUNDU -> BASLADIM, BASLADI -> BITIRDIM
    if (g.durum === "ATANDI") {
      return '<button class="u-btn u-btn-primary" onclick="window.UstaPanel.okudu(' + g.id + ')">OKUDUM</button>';
    }
    if (g.durum === "OKUNDU") {
      return '<button class="u-btn u-btn-primary" onclick="window.UstaPanel.basladi(' + g.id + ')">BASLADIM</button>';
    }
    if (g.durum === "BASLADI") {
      return '<button class="u-btn u-btn-success" onclick="window.UstaPanel.bitti(' + g.id + ')">BITIRDIM</button>';
    }
    return "";
  }

  function durumClass(d) {
    if (d === "ATANDI") return "bekliyor";
    if (d === "OKUNDU") return "bekliyor";
    if (d === "BASLADI") return "bekliyor";
    if (d === "TAMAMLANDI") return "onaylandi";
    if (d === "IPTAL") return "reddedildi";
    return "bekliyor";
  }

  function renderIsler(gorevler) {
    var liste = $("islerList");
    if (!liste) return;
    liste.innerHTML = "";

    if (!gorevler || gorevler.length === 0) {
      liste.innerHTML = '<div class="u-empty">Su anda atanmis is yok.</div>';
      return;
    }

    gorevler.forEach(function (g) {
      var card = document.createElement("div");
      card.className = "u-card";

      var hedef = g.hedef_adet || 0;
      var kalan = g.kalan_adet;
      // kalan_adet null gelebilir - hedef_adet'i yedek olarak kullan
      var kalanGoster = (kalan !== null && kalan !== undefined) ? kalan : hedef;

      var oncelikLabel = "";
      if (g.oncelik && g.oncelik >= 80) oncelikLabel = '<span class="u-badge-kritik">KRITIK</span>';
      else if (g.oncelik && g.oncelik >= 60) oncelikLabel = '<span class="u-badge-yuksek">YUKSEK</span>';

      // Termin gecikme uyarisi
      var terminUyari = "";
      if (g.termin_durumu === "geciken" || g.termin_durumu === "yakin") {
        terminUyari = '<span class="u-badge-geciken">GECIKEN</span>';
      }

      card.innerHTML =
        '<div class="u-card-header">' +
          '<div class="u-card-emir">#' + escapeHtml(String(g.id)) +
          (g.emir_no ? ' / EMR ' + escapeHtml(String(g.emir_no)) : '') +
          '</div>' +
          '<div class="u-card-durum ' + durumClass(g.durum) + '">' + escapeHtml(g.durum || "-") + '</div>' +
        '</div>' +
        (g.model ? '<div class="u-card-model">' + escapeHtml(g.model) + '</div>' : '') +
        '<div class="u-card-info">' +
          '<span><span class="lbl">Siparis:</span> ' + escapeHtml(g.siparis_no || "-") + '</span>' +
          (g.musteri ? '<span><span class="lbl">Musteri:</span> ' + escapeHtml(g.musteri) + '</span>' : '') +
          (g.bant ? '<span><span class="lbl">Bant:</span> ' + escapeHtml(g.bant) + '</span>' : '') +
        '</div>' +
        '<div class="u-card-info">' +
          '<span><span class="lbl">Hedef:</span> ' + hedef + '</span>' +
          '<span><span class="lbl">Kalan:</span> <strong>' + kalanGoster + '</strong></span>' +
          (g.atanan_usta ? '<span><span class="lbl">Usta:</span> ' + escapeHtml(g.atanan_usta) + '</span>' : '') +
        '</div>' +
        (g.darbogaz ? '<div class="u-card-info"><span><span class="lbl">Darbogaz:</span> ' + escapeHtml(g.darbogaz) + '</span></div>' : '') +
        (g.talimat ? '<div class="u-card-info"><span><span class="lbl">Talimat:</span> ' + escapeHtml(g.talimat) + '</span></div>' : '') +
        (g.termin ? '<div class="u-card-info"><span><span class="lbl">Termin:</span> ' + escapeHtml(g.termin) + ' ' + terminUyari + '</span></div>' : '') +
        (oncelikLabel ? '<div class="u-card-info">' + oncelikLabel + '</div>' : '') +
        '<div class="u-card-actions">' +
          durumButon(g) +
        '</div>';

      liste.appendChild(card);
    });
  }

  // ============== 2) TAMAMLANANLAR (ONAY sekmesi - read-only) ==============
  async function tamamlananlariYukle() {
    var liste = $("onayList");
    if (liste) liste.innerHTML = '<div class="u-empty">Yukleniyor...</div>';

    try {
      var r = await apiFetch("/usta/api/gorevler?durum=hepsi");
      if (r.status >= 400 || (r.data && r.data.ok === false)) {
        showError("onayError", (r.data && r.data.mesaj) || ("HTTP " + r.status));
        if (liste) liste.innerHTML = '<div class="u-empty">Yuklenemedi.</div>';
        return;
      }
      var hepsi = (r.data && r.data.gorevler) || [];
      var tamam = hepsi.filter(function (g) { return g.durum === "TAMAMLANDI"; });
      renderTamamlananlar(tamam);
      guncelleBadge(0); // Onay sekmesinde badge yok artik (read-only)
      _onaylariYuklendi = true;
      console.log("[USTA] tamamlananlar:", tamam.length);
    } catch (e) {
      console.warn("[USTA] onay fetch error:", e.message);
      showError("onayError", "Sunucuya ulasilamadi: " + e.message);
      if (liste) liste.innerHTML = '<div class="u-empty">Baglanti hatasi.</div>';
    }
  }

  function renderTamamlananlar(gorevler) {
    var liste = $("onayList");
    if (!liste) return;
    liste.innerHTML = "";

    if (!gorevler || gorevler.length === 0) {
      liste.innerHTML = '<div class="u-empty">Tamamlanmis is yok.</div>';
      return;
    }

    gorevler.forEach(function (g) {
      var card = document.createElement("div");
      card.className = "u-card";
      card.innerHTML =
        '<div class="u-card-header">' +
          '<div class="u-card-emir">#' + escapeHtml(String(g.id)) +
          (g.emir_no ? ' / EMR ' + escapeHtml(String(g.emir_no)) : '') +
          '</div>' +
          '<div class="u-card-durum onaylandi">TAMAMLANDI</div>' +
        '</div>' +
        (g.model ? '<div class="u-card-model">' + escapeHtml(g.model) + '</div>' : '') +
        '<div class="u-card-info">' +
          '<span><span class="lbl">Siparis:</span> ' + escapeHtml(g.siparis_no || "-") + '</span>' +
          (g.musteri ? '<span><span class="lbl">Musteri:</span> ' + escapeHtml(g.musteri) + '</span>' : '') +
        '</div>' +
        '<div class="u-card-info">' +
          '<span><span class="lbl">Tamamlanma:</span> ' + escapeHtml(fmtTarih(g.tamamlanma_tarih)) + '</span>' +
          (g.atanan_usta ? '<span><span class="lbl">Usta:</span> ' + escapeHtml(g.atanan_usta) + '</span>' : '') +
        '</div>' +
        (g.usta_notu ? '<div class="u-card-info"><span><span class="lbl">Not:</span> ' + escapeHtml(g.usta_notu) + '</span></div>' : '');
      liste.appendChild(card);
    });
  }

  // ============== 3) DURUM GECISLERI (POST aksiyonlar) ==============
  async function durumGecis(id, endpoint, body) {
    if (!id) return;
    try {
      var r = await apiFetch("/usta/api/gorev/" + id + "/" + endpoint, {
        method: "POST",
        body: JSON.stringify(body || {})
      });
      if (r.status >= 400 || (r.data && r.data.ok === false)) {
        var msg = (r.data && r.data.mesaj) || ("HTTP " + r.status);
        showError("islerError", msg);
        return;
      }
      // Listeyi yenile
      _aciKisleriYuklendi = false;
      _onaylariYuklendi = false;
      await acikIsleriYukle();
      console.log("[USTA] durum gecisi OK:", id, endpoint);
    } catch (e) {
      console.warn("[USTA] durum gecisi error:", e.message);
      showError("islerError", "Islem basarisiz: " + e.message);
    }
  }

  function okudu(id) {
    durumGecis(id, "okudu");
  }

  function basladi(id) {
    durumGecis(id, "basladi");
  }

  async function bitti(id) {
    var notu = window.prompt("Bitti notu (opsiyonel):", "");
    if (notu === null) return; // iptal
    var body = notu.trim() ? { usta_notu: notu.trim() } : {};
    await durumGecis(id, "bitti", body);
  }

  // ============== BADGE (ATANDI sayisi) ==============
  function guncelleBadgeAtandi(n) {
    // Eger HTML'de "atandi badge" varsa burada updateler.
    // Mevcut HTML'de onayBadge var, onun anlami degisti.
    var b = $("onayBadge");
    if (!b) return;
    if (n > 0) {
      b.textContent = String(n);
      b.classList.add("active");
    } else {
      b.textContent = "";
      b.classList.remove("active");
    }
  }

  function guncelleBadge(n) {
    // ESKI imza - bos bos durmasin diye
    guncelleBadgeAtandi(n);
  }

  // ============== GIRIS SEKMESI - YAKINDA ==============
  function girisSekmesiBilgilendir() {
    // GIRIS sekmesinin formuna submit edilirse mesaj goster
    var btn = $("girisKaydetBtn");
    if (btn) {
      btn.addEventListener("click", function () {
        showError("girisError", "Bu ozellik daha sonra aktif edilecek.");
      });
    }
    var iptalBtn = $("girisIptalBtn");
    if (iptalBtn) {
      iptalBtn.addEventListener("click", function () {
        var f = $("girisForm");
        if (f) f.reset();
      });
    }
  }

  // ============== STARTUP ==============
  function init() {
    setupTabs();

    // Yenile butonlari
    var islerYn = $("islerYenileBtn");
    if (islerYn) islerYn.addEventListener("click", function () {
      _aciKisleriYuklendi = false;
      acikIsleriYukle();
    });
    var onayYn = $("onayYenileBtn");
    if (onayYn) onayYn.addEventListener("click", function () {
      _onaylariYuklendi = false;
      tamamlananlariYukle();
    });

    girisSekmesiBilgilendir();

    // Ilk yukleme - sadece ISLER (tab default active)
    acikIsleriYukle();
  }

  // Public interface (button onclick'lerinden cagirilir)
  window.UstaPanel = {
    okudu: okudu,
    basladi: basladi,
    bitti: bitti,
    yenile: function () {
      _aciKisleriYuklendi = false;
      _onaylariYuklendi = false;
      acikIsleriYukle();
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
