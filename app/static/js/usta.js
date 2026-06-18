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

  // ============== GİRİŞ SEKMESİ — FAZ 2 ÜRETİM KAYIT ==============
  // State
  var _girisState = {
    hatlar:        [],
    seciliHat:     null,   // {kod, ad, proses}
    isler:         [],
    seciliIs:      null,   // {emir_no, skod, proses_kodu, proses_adi, bekleyen_miktar, ...}
    personeller:   [],
    ekipSayac:     0,
    kapalanAd:     '',
  };

  function girisAdimGoster(adimId) {
    var adimlar = ['adim-hat', 'adim-isler', 'adim-form'];
    adimlar.forEach(function (a) {
      var el = $(a);
      if (el) el.style.display = (a === adimId) ? '' : 'none';
    });
  }

  // ---- ADIM 1: Hat yükleme ----
  async function hatlarYukle() {
    try {
      var r = await apiFetch('/usta/api/hat-listesi');
      if (r.status >= 400 || !r.data.ok) { return; }
      _girisState.hatlar = r.data.hatlar || [];
      renderHatListe();
    } catch (e) {
      console.warn('[GIRIS] hat listesi hatasi:', e.message);
    }
  }

  function renderHatListe() {
    var wrap = $('hatListeWrap');
    if (!wrap) return;
    wrap.innerHTML = '';
    _girisState.hatlar.forEach(function (h) {
      var btn = document.createElement('button');
      btn.className = 'u-hat-btn';
      btn.textContent = h.ad;
      btn.addEventListener('click', function () {
        _girisState.seciliHat = h;
        hatSecilenGuncelle(h);
      });
      wrap.appendChild(btn);
    });
  }

  async function hatSecilenGuncelle(hat) {
    var baslik = $('seciliHatBaslik');
    if (baslik) baslik.textContent = hat.ad;
    girisAdimGoster('adim-isler');

    var liste = $('onumdekiList');
    if (liste) liste.innerHTML = '<div class="u-empty">Yükleniyor...</div>';

    try {
      var url = '/usta/api/onumdeki-isler?hat_kodu=' + encodeURIComponent(hat.kod);
      var r = await apiFetch(url);
      if (r.status >= 400 || !r.data.ok) {
        showError('onumdekiError',
          (r.data && r.data.hata) ? r.data.hata : ('HTTP ' + r.status));
        if (liste) liste.innerHTML = '<div class="u-empty">Yuklenemedi.</div>';
        return;
      }
      _girisState.isler = r.data.isler || [];
      renderOnumdekiIsler(_girisState.isler);
    } catch (e) {
      console.warn('[GIRIS] onumdeki isler hatasi:', e.message);
      var ll = $('onumdekiList');
      if (ll) ll.innerHTML = '<div class="u-empty">Bağlantı hatası.</div>';
    }
  }

  function renderOnumdekiIsler(isler) {
    var liste = $('onumdekiList');
    if (!liste) return;
    liste.innerHTML = '';

    if (!isler || isler.length === 0) {
      liste.innerHTML = '<div class="u-empty">Bu bölümde bekleyen iş yok.</div>';
      return;
    }

    isler.forEach(function (is) {
      var card = document.createElement('div');
      card.className = 'u-card u-card-is';

      var miktar = is.bekleyen_miktar || 0;
      card.innerHTML =
        '<div class="u-card-header">' +
          '<div class="u-card-emir">Sip ' + escapeHtml(String(is.sip_no || '-')) + ' / Emir ' + escapeHtml(String(is.emir_no)) + '</div>' +
          '<div class="u-card-durum bekliyor">' + escapeHtml(is.proses_adi || is.proses_kodu || '-') + '</div>' +
        '</div>' +
        '<div class="u-card-model">' + escapeHtml(is.skod || '-') + '</div>' +
        '<div class="u-card-info">' +
          '<span><span class="lbl">Müşteri:</span> ' + escapeHtml(is.musteri_adi || '-') + '</span>' +
          '<span><span class="lbl">Bekleyen:</span> <strong>' + miktar + ' ' + escapeHtml(is.birim || 'ÇIFT') + '</strong></span>' +
        '</div>' +
        '<div class="u-card-actions">' +
          '<button class="u-btn u-btn-primary">Kayıt Gir</button>' +
        '</div>';

      card.querySelector('.u-btn-primary').addEventListener('click', function () {
        isSecildi(is);
      });
      liste.appendChild(card);
    });
  }

  // ---- ADIM 3: Form (kayıt girişi) ----
  async function isSecildi(is) {
    _girisState.seciliIs = is;

    // Özet bandı
    var ozet = $('formEmirozet');
    if (ozet) {
      ozet.innerHTML =
        '<div class="u-emir-ozet-satir">' +
          '<span class="u-emir-ozet-emir">Sip ' + escapeHtml(String(is.sip_no || '-')) +
          ' / Emir <strong>' + escapeHtml(String(is.emir_no)) + '</strong>' +
          ' — ' + escapeHtml(is.proses_adi || is.proses_kodu) + '</span>' +
        '</div>' +
        '<div class="u-emir-ozet-satir">' +
          '<span>' + escapeHtml(is.skod) + '</span>' +
          '<span class="u-emir-ozet-musteri">' + escapeHtml(is.musteri_adi || '') + '</span>' +
        '</div>' +
        '<div class="u-emir-ozet-satir">' +
          '<span class="u-emir-ozet-lbl">Bekleyen:</span>' +
          '<strong>' + (is.bekleyen_miktar || 0) + ' ' + escapeHtml(is.birim || 'ÇIFT') + '</strong>' +
          ((_girisState.seciliHat) ? ' <span class="u-hat-badge">' + escapeHtml(_girisState.seciliHat.ad) + '</span>' : '') +
        '</div>';
    }

    // Şimdiki saati bitiş saat alanına doldur
    var now = new Date();
    var hh = String(now.getHours()).padStart(2, '0');
    var mm = String(now.getMinutes()).padStart(2, '0');
    var fBitis = $('fBitisSaat');
    if (fBitis && !fBitis.value) fBitis.value = hh + ':' + mm;

    // Miktar alanına bekleyen miktarı doldur
    var fMiktar = $('fToplamMiktar');
    if (fMiktar && !fMiktar.value && is.bekleyen_miktar > 0) {
      fMiktar.value = is.bekleyen_miktar;
    }

    // Kapatan adı
    var kapatanEl = $('fKapatan');
    if (kapatanEl) kapatanEl.textContent = _girisState.kapalanAd || '—';

    // Personel listesini yükle (ekip seçimi için)
    await personelListesiYukle();

    // İlk ekip satırı
    ekipSifirlaDoldur();

    girisAdimGoster('adim-form');

    // Hata/başarı mesajlarını temizle
    var fe = $('formError');
    var fs = $('formSuccess');
    if (fe) fe.style.display = 'none';
    if (fs) fs.style.display = 'none';
  }

  async function personelListesiYukle() {
    if (_girisState.personeller.length > 0) return; // cached
    try {
      var r = await apiFetch('/usta/api/personel-listesi');
      if (r.data && r.data.ok && r.data.personeller) {
        _girisState.personeller = r.data.personeller;
      }
    } catch (e) {
      console.warn('[GIRIS] personel listesi hatasi:', e.message);
    }
  }

  function ekipSifirla() {
    var wrap = $('ekipSatirlar');
    if (wrap) wrap.innerHTML = '';
    _girisState.ekipSayac = 0;
  }

  function ekipSifirlaDoldur() {
    ekipSifirla();
    // Bir boş satır ekle
    ekipSatirEkle();
  }

  function ekipSatirEkle() {
    var wrap = $('ekipSatirlar');
    if (!wrap) return;
    var idx = _girisState.ekipSayac++;
    var div = document.createElement('div');
    div.className = 'u-ekip-satir';
    div.id = 'ekip-satir-' + idx;

    // Personel seçimi (select veya text)
    var personelHtml = '';
    if (_girisState.personeller.length > 0) {
      personelHtml = '<select class="u-ekip-ad" data-idx="' + idx + '">' +
        '<option value="">— Kişi Seç —</option>';
      _girisState.personeller.forEach(function (p) {
        personelHtml += '<option value="' + p.id + '" data-ad="' + escapeHtml(p.ad) + '">' +
          escapeHtml(p.ad) + '</option>';
      });
      personelHtml += '</select>';
    } else {
      personelHtml = '<input type="text" class="u-ekip-ad" placeholder="İsim" data-idx="' + idx + '">';
    }

    div.innerHTML =
      personelHtml +
      '<input type="number" class="u-ekip-miktar" placeholder="Miktar" min="0" inputmode="numeric" data-idx="' + idx + '">' +
      '<button type="button" class="u-ekip-sil" data-idx="' + idx + '">✕</button>';

    div.querySelector('.u-ekip-sil').addEventListener('click', function () {
      var el = $('ekip-satir-' + idx);
      if (el) el.remove();
    });
    wrap.appendChild(div);
  }

  function ekipOku() {
    var ekip = [];
    var satirlar = document.querySelectorAll('.u-ekip-satir');
    satirlar.forEach(function (satir) {
      var adEl = satir.querySelector('.u-ekip-ad');
      var miktarEl = satir.querySelector('.u-ekip-miktar');
      if (!adEl || !miktarEl) return;

      var adVal = adEl.value ? adEl.value.trim() : '';
      var miktar = parseInt(miktarEl.value, 10) || 0;
      if (!adVal) return;

      var pId = null;
      var pAd = adVal;

      // select ise value = id, data-ad = ad
      if (adEl.tagName === 'SELECT') {
        var sel = adEl.options[adEl.selectedIndex];
        if (!sel || !sel.value) return;
        pId = parseInt(sel.value, 10);
        pAd = sel.getAttribute('data-ad') || sel.text;
      }

      ekip.push({ personel_id: pId, personel_ad: pAd, miktar: miktar });
    });
    return ekip;
  }

  async function formKaydet() {
    var btn = $('formKaydetBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Kaydediliyor...'; }

    try {
      var is = _girisState.seciliIs;
      if (!is) {
        showError('formError', 'İş seçilmemiş.');
        return;
      }

      var miktarEl = $('fToplamMiktar');
      var toplam = parseInt((miktarEl && miktarEl.value) || '0', 10);
      if (toplam <= 0) {
        showError('formError', 'Miktar girilmedi veya geçersiz.');
        if (btn) { btn.disabled = false; btn.textContent = '✓ KAYDET'; }
        return;
      }

      var ekip = ekipOku();

      var payload = {
        emir_no:         is.emir_no,
        skod:            is.skod,
        proses_kodu:     is.proses_kodu,
        proses_adi:      is.proses_adi,
        hat_adi:         _girisState.seciliHat ? _girisState.seciliHat.ad : '',
        toplam_miktar:   toplam,
        baslangic_saat:  ($('fBaslangicSaat') && $('fBaslangicSaat').value) || null,
        bitis_saat:      ($('fBitisSaat') && $('fBitisSaat').value) || null,
        sip_no:          is.sip_no || null,
        ekip:            ekip,
        not_metin:       ($('fNot') && $('fNot').value.trim()) || null,
      };

      var r = await apiFetch('/usta/api/uretim-kayit', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      if (r.status >= 400 || !r.data.ok) {
        var msg = (r.data && (r.data.mesaj || r.data.hata)) || ('HTTP ' + r.status);
        showError('formError', msg);
        return;
      }

      // Başarı
      var kayitId = r.data.kayit_id || '?';
      showSuccess('formSuccess',
        'Kayıt oluşturuldu! #' + kayitId + '  (' + toplam + ' çift)');

      // Formu sıfırla, işler listesine geri dön
      setTimeout(function () {
        formTemizle();
        girisAdimGoster('adim-isler');
        // İşler listesini yenile
        if (_girisState.seciliHat) {
          hatSecilenGuncelle(_girisState.seciliHat);
        }
      }, 1500);

    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✓ KAYDET'; }
    }
  }

  function formTemizle() {
    var miktarEl = $('fToplamMiktar');
    var notEl = $('fNot');
    var basEl = $('fBaslangicSaat');
    var bitEl = $('fBitisSaat');
    if (miktarEl) miktarEl.value = '';
    if (notEl) notEl.value = '';
    if (basEl) basEl.value = '';
    if (bitEl) bitEl.value = '';
    ekipSifirlaDoldur();
    _girisState.seciliIs = null;
  }

  function setupGirisAkis() {
    // Geri butonları
    var islerGeri = $('islerGeriBtn');
    if (islerGeri) islerGeri.addEventListener('click', function () {
      girisAdimGoster('adim-hat');
    });
    var formGeri = $('formGeriBtn');
    if (formGeri) formGeri.addEventListener('click', function () {
      girisAdimGoster('adim-isler');
    });

    // Yenile
    var onumdekiYenile = $('onumdekiYenileBtn');
    if (onumdekiYenile) onumdekiYenile.addEventListener('click', function () {
      if (_girisState.seciliHat) {
        hatSecilenGuncelle(_girisState.seciliHat);
      }
    });

    // Ekip ekle
    var ekipEkle = $('ekipEkleBtn');
    if (ekipEkle) ekipEkle.addEventListener('click', ekipSatirEkle);

    // Kaydet
    var formKaydetBtn = $('formKaydetBtn');
    if (formKaydetBtn) formKaydetBtn.addEventListener('click', formKaydet);

    // Temizle
    var formIptal = $('formIptalBtn');
    if (formIptal) formIptal.addEventListener('click', function () {
      formTemizle();
    });

    // Kullanıcı adını oku (kapatan)
    var ustaAdEl = $('ustaAd');
    if (ustaAdEl) {
      _girisState.kapalanAd = ustaAdEl.textContent.trim();
    }

    // Hat listesini yükle
    hatlarYukle();
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

    setupGirisAkis();

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
