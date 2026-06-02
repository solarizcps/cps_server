/* sablon.js - D5 FAZ C.4 (18.05.2026)
 * Sablon CRUD UI + sablon_eslesme CRUD
 * Backend: /hedef/sablon/* (mevcut) + /hedef/sablon-eslesme/* (C.4)
 * Korundu: sablonDetayKapat() global fonksiyon (HTML onclick)
 */
(function () {
  'use strict';

  var STATE = {
    sablonlar: [],
    eslesmeler: [],
    aktifTab: 'sablonlar',
    formMode: null,
    silTarget: null,
    formProsesler: []
  };

  var ESLESME_TIP_LABEL = {
    musteri: 'Musteri', model: 'Model', tip: 'Tip', ozel: 'Ozel',
    location: 'Lokasyon', cari_kod: 'Cari Kodu', stok_kodu: 'Stok Kodu',
    ozkod: 'Ozkod', varsayilan: 'Varsayilan'
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) { if (s === null || s === undefined) return ''; return String(s).replace(/[&<>"']/g, function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }

  function fetchJSON(url, opts) {
    opts = opts || {};
    opts.credentials = 'same-origin';
    return fetch(url, opts).then(function (r) {
      if (!r.ok && r.status !== 400 && r.status !== 404 && r.status !== 409) {
        throw new Error('HTTP ' + r.status);
      }
      return r.json().then(function (j) { return { status: r.status, body: j }; });
    });
  }

  /* ===== TAB ===== */
  function tabAc(tab) {
    STATE.aktifTab = tab;
    try { localStorage.setItem('cps_sablon_tab', tab); } catch(e){}
    document.querySelectorAll('.tab-btn').forEach(function(b){ b.classList.toggle('aktif', b.dataset.tab === tab); });
    document.querySelectorAll('.tab-panel').forEach(function(p){ p.classList.toggle('aktif', p.id === 'tabPanel-' + tab); });
    var btnSablon = $('btnYeniSablon');
    var btnEslesme = $('btnYeniEslesme');
    if (btnSablon) btnSablon.style.display = (tab === 'sablonlar') ? '' : 'none';
    if (btnEslesme) btnEslesme.style.display = (tab === 'eslesme') ? '' : 'none';
    if (tab === 'eslesme') eslesmeListeYukle();
  }

  /* ===== SABLON LISTE ===== */
  function sablonListeYukle() {
    var liste = $('sablonListe');
    var ozet = $('ozetBilgi');
    if (liste) liste.innerHTML = '<div class="yukleniyor">Sablonlar yukleniyor...</div>';
    fetchJSON('/hedef/sablon/liste').then(function (res) {
      if (!res.body.ok) {
        liste.innerHTML = '<div class="bos-durum">Hata: ' + esc(res.body.mesaj || '?') + '</div>';
        return;
      }
      STATE.sablonlar = res.body.kayitlar || [];
      if (ozet) ozet.innerHTML = '<b>' + STATE.sablonlar.length + '</b> aktif sablon';
      if (STATE.sablonlar.length === 0) {
        liste.innerHTML = '<div class="bos-durum">Henuz sablon yok. <br>Sag ustten "+ Yeni Sablon" ile ekleyin.</div>';
        return;
      }
      var html = STATE.sablonlar.map(function (s) {
        var pros = (s.prosesler || []).map(function(p){ return '<span class="pros-item">' + esc(p) + '</span>'; }).join('');
        return '<div class="sablon-karti" data-id="' + s.id + '">' +
          '<div class="kart-bas">' +
            '<div class="baslik">' + esc(s.sablon_adi) + ' <span class="sablon-id">#' + s.id + '</span></div>' +
            '<span class="durum-rozet durum-aktif">aktif</span>' +
          '</div>' +
          '<div class="kart-istatistik">' +
            '<span class="istk"><b>' + (s.proses_sayisi || 0) + '</b> proses</span>' +
            (s.aciklama ? '<span class="istk">' + esc(s.aciklama) + '</span>' : '') +
          '</div>' +
          (pros ? '<div class="kart-prosesler"><span class="etk">Adimlar:</span>' + pros + '</div>' : '') +
          '<div class="kart-aksiyon">' +
            '<button class="btn-detay" onclick="sablonDetayAc(' + s.id + ')">Detay</button>' +
            '<button class="btn-duzenle" onclick="window._sablonDuzenle(' + s.id + ')">Duzenle</button>' +
            '<button class="btn-sil" onclick="window._sablonSilSor(' + s.id + ')">Sil</button>' +
          '</div>' +
        '</div>';
      }).join('');
      liste.innerHTML = html;
    }).catch(function (e) {
      liste.innerHTML = '<div class="bos-durum">Hata: ' + esc(e.message) + '</div>';
    });
  }

  /* ===== SABLON DETAY (mevcut JS davranisi korundu) ===== */
  window.sablonDetayAc = function (sid) {
    var s = STATE.sablonlar.find(function(x){ return x.id === sid; });
    if (!s) return;
    $('modalBaslik').textContent = 'Sablon: ' + s.sablon_adi;
    var body = '<div class="modal-bolum"><h3>Bilgi</h3>' +
      '<div class="bilgi"><b>ID:</b> ' + s.id + '</div>' +
      '<div class="bilgi"><b>Olusturan:</b> ' + esc(s.olusturan_ad || '-') + '</div>' +
      '<div class="bilgi"><b>Olusturma:</b> ' + esc(s.olusturma || '-') + '</div>' +
      (s.aciklama ? '<div class="bilgi"><b>Aciklama:</b> ' + esc(s.aciklama) + '</div>' : '') +
      '</div>';
    if (s.prosesler && s.prosesler.length) {
      body += '<div class="modal-bolum"><h3>Prosesler</h3><ol>' +
        s.prosesler.map(function(p){ return '<li>' + esc(p) + '</li>'; }).join('') +
        '</ol></div>';
    }
    $('modalBody').innerHTML = body;
    $('detayModal').classList.add('acik');
  };
  window.sablonDetayKapat = function () { $('detayModal').classList.remove('acik'); };

  /* ===== SABLON FORM (Yeni + Duzenle) ===== */
  function prosesOnerileriYukle() {
    fetchJSON('/hedef/sablon/proses-onerileri').then(function(res){
      if (!res.body.ok) return;
      var dl = $('prosesOnerileri');
      if (!dl) return;
      dl.innerHTML = (res.body.kayitlar || []).map(function(k){ return '<option value="' + esc(k.proses_adi) + '">'; }).join('');
    });
  }

  function sablonFormAc(mode, sid) {
    STATE.formMode = mode;
    STATE.formProsesler = [];
    $('sablonFormId').value = sid || '';
    $('sablonFormHata').style.display = 'none';
    $('sablonFormHata').textContent = '';
    $('sablonFormProsesYeni').value = '';
    if (mode === 'duzenle' && sid) {
      var s = STATE.sablonlar.find(function(x){ return x.id === sid; });
      if (!s) { alert('Sablon bulunamadi'); return; }
      $('sablonFormBaslik').textContent = 'Sablonu Duzenle: ' + s.sablon_adi;
      $('sablonFormAdi').value = s.sablon_adi || '';
      $('sablonFormAciklama').value = s.aciklama || '';
      STATE.formProsesler = (s.prosesler || []).slice();
    } else {
      $('sablonFormBaslik').textContent = 'Yeni Sablon';
      $('sablonFormAdi').value = '';
      $('sablonFormAciklama').value = '';
    }
    prosesListeRender();
    prosesOnerileriYukle();
    $('sablonFormModal').classList.add('acik');
  }
  window.sablonFormKapat = function () { $('sablonFormModal').classList.remove('acik'); };

  function prosesListeRender() {
    var c = $('sablonFormProsesler');
    if (STATE.formProsesler.length === 0) {
      c.innerHTML = '<div class="proses-bos">Henuz proses eklenmedi</div>';
      return;
    }
    c.innerHTML = STATE.formProsesler.map(function(p, i){
      return '<div class="proses-sira-item">' +
        '<span class="sira-no">' + (i+1) + '.</span>' +
        '<span class="proses-adi">' + esc(p) + '</span>' +
        '<div class="sira-aksiyon">' +
          (i > 0 ? '<button type="button" onclick="window._prosesYukari(' + i + ')">&uarr;</button>' : '') +
          (i < STATE.formProsesler.length-1 ? '<button type="button" onclick="window._prosesAsagi(' + i + ')">&darr;</button>' : '') +
          '<button type="button" class="btn-prs-sil" onclick="window._prosesSil(' + i + ')">&times;</button>' +
        '</div>' +
      '</div>';
    }).join('');
  }
  window._prosesYukari = function(i) { if(i<=0) return; var t=STATE.formProsesler[i]; STATE.formProsesler[i]=STATE.formProsesler[i-1]; STATE.formProsesler[i-1]=t; prosesListeRender(); };
  window._prosesAsagi = function(i) { if(i>=STATE.formProsesler.length-1) return; var t=STATE.formProsesler[i]; STATE.formProsesler[i]=STATE.formProsesler[i+1]; STATE.formProsesler[i+1]=t; prosesListeRender(); };
  window._prosesSil = function(i) { STATE.formProsesler.splice(i, 1); prosesListeRender(); };

  function prosesEkle() {
    var inp = $('sablonFormProsesYeni');
    var v = (inp.value || '').trim();
    if (!v) return;
    if (STATE.formProsesler.indexOf(v) >= 0) { inp.value = ''; return; }
    STATE.formProsesler.push(v);
    inp.value = '';
    prosesListeRender();
  }

  function sablonKaydet() {
    var ad = ($('sablonFormAdi').value || '').trim();
    var aciklama = ($('sablonFormAciklama').value || '').trim();
    var hata = $('sablonFormHata');
    hata.style.display = 'none';

    if (!ad) { hata.textContent = 'Sablon adi zorunlu'; hata.style.display = 'block'; return; }
    if (STATE.formProsesler.length === 0) { hata.textContent = 'En az 1 proses gerekli'; hata.style.display = 'block'; return; }

    var body = { sablon_adi: ad, aciklama: aciklama, prosesler: STATE.formProsesler.slice() };
    var sid = $('sablonFormId').value;
    var url = STATE.formMode === 'duzenle' ? '/hedef/sablon/guncelle/' + sid : '/hedef/sablon/ekle';
    var btn = $('btnSablonKaydet');
    btn.disabled = true;

    fetchJSON(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function(res){
        btn.disabled = false;
        if (!res.body.ok) {
          hata.textContent = res.body.mesaj || 'Kayit basarisiz';
          hata.style.display = 'block';
          return;
        }
        window.sablonFormKapat();
        sablonListeYukle();
      })
      .catch(function(e){
        btn.disabled = false;
        hata.textContent = 'Hata: ' + e.message;
        hata.style.display = 'block';
      });
  }

  window._sablonDuzenle = function(sid) { sablonFormAc('duzenle', sid); };

  /* ===== SABLON SIL ===== */
  window._sablonSilSor = function(sid) {
    var s = STATE.sablonlar.find(function(x){ return x.id === sid; });
    if (!s) return;
    STATE.silTarget = { tip: 'sablon', id: sid, label: s.sablon_adi };
    $('silOnayBaslik').textContent = 'Sablon Silme Onayi';
    $('silOnayMesaj').innerHTML = '<b>' + esc(s.sablon_adi) + '</b> sablonu silinecek (pasife alinacak).';
    fetchJSON('/hedef/sablon-eslesme/liste/' + sid).then(function(res){
      var uyari = $('silOnayUyari');
      var n = (res.body && res.body.kayitlar) ? res.body.kayitlar.length : 0;
      if (n > 0) {
        uyari.innerHTML = 'Bu sablona bagli <b>' + n + '</b> eslesme kurali var.<br>Sablon pasiflenince kurallar AYNEN KORUNUR, sablon yeniden aktiflesirse kurallar yine calisir.';
        uyari.style.display = 'block';
      } else {
        uyari.style.display = 'none';
      }
      $('silOnayModal').classList.add('acik');
    });
  };
  window.silOnayKapat = function () { $('silOnayModal').classList.remove('acik'); STATE.silTarget = null; };

  function silOnayla() {
    if (!STATE.silTarget) return;
    var t = STATE.silTarget;
    var url = (t.tip === 'sablon') ? '/hedef/sablon/sil/' + t.id : '/hedef/sablon-eslesme/sil/' + t.id;
    var btn = $('btnSilOnay');
    btn.disabled = true;
    fetchJSON(url, { method: 'POST' }).then(function(res){
      btn.disabled = false;
      window.silOnayKapat();
      if (t.tip === 'sablon') sablonListeYukle();
      else eslesmeListeYukle();
    }).catch(function(e){ btn.disabled = false; alert('Hata: ' + e.message); });
  }

  /* ===== ESLESME LISTE ===== */
  function eslesmeListeYukle() {
    var yuk = $('eslesmeYukleniyor');
    var tbl = $('eslesmeTablo');
    var tb = $('eslesmeTbody');
    var bos = $('eslesmeBos');
    if (yuk) yuk.style.display = 'block';
    if (tbl) tbl.style.display = 'none';
    if (bos) bos.style.display = 'none';
    fetchJSON('/hedef/sablon-eslesme/liste').then(function(res){
      yuk.style.display = 'none';
      if (!res.body.ok) {
        bos.textContent = 'Hata: ' + esc(res.body.mesaj || '?');
        bos.style.display = 'block';
        return;
      }
      STATE.eslesmeler = res.body.kayitlar || [];
      if (STATE.eslesmeler.length === 0) {
        bos.style.display = 'block';
        return;
      }
      tb.innerHTML = STATE.eslesmeler.map(function(e){
        return '<tr data-id="' + e.id + '">' +
          '<td class="onc">' + (e.oncelik) + '</td>' +
          '<td><span class="tip-pill">' + esc(ESLESME_TIP_LABEL[e.eslesme_tipi] || e.eslesme_tipi) + '</span></td>' +
          '<td>' + esc(e.eslesme_degeri) + '</td>' +
          '<td class="sablon-link">' + esc(e.sablon_adi || '#' + e.sablon_id) + '</td>' +
          '<td>' + esc(e.aciklama || '') + '</td>' +
          '<td><div class="islem-grup">' +
            '<button class="btn-duzenle" onclick="window._eslesmeDuzenle(' + e.id + ')">Duzenle</button>' +
            '<button class="btn-sil" onclick="window._eslesmeSilSor(' + e.id + ')">Sil</button>' +
          '</div></td>' +
        '</tr>';
      }).join('');
      tbl.style.display = 'table';
    }).catch(function(err){
      yuk.style.display = 'none';
      bos.textContent = 'Hata: ' + esc(err.message);
      bos.style.display = 'block';
    });
  }

  /* ===== ESLESME FORM ===== */
  function eslesmeFormAc(mode, eid) {
    STATE.formMode = 'eslesme_' + mode;
    $('eslesmeFormId').value = eid || '';
    $('eslesmeFormHata').style.display = 'none';
    var sel = $('eslesmeFormSablonId');
    sel.innerHTML = STATE.sablonlar.map(function(s){ return '<option value="' + s.id + '">' + esc(s.sablon_adi) + '</option>'; }).join('');
    if (mode === 'duzenle' && eid) {
      var e = STATE.eslesmeler.find(function(x){ return x.id === eid; });
      if (!e) { alert('Kural bulunamadi'); return; }
      $('eslesmeFormBaslik').textContent = 'Eslesme Kuralini Duzenle';
      sel.value = e.sablon_id;
      $('eslesmeFormTip').value = e.eslesme_tipi;
      $('eslesmeFormDeger').value = e.eslesme_degeri;
      $('eslesmeFormOncelik').value = e.oncelik;
      $('eslesmeFormAciklama').value = e.aciklama || '';
    } else {
      $('eslesmeFormBaslik').textContent = 'Yeni Eslesme Kurali';
      $('eslesmeFormTip').value = 'musteri';
      $('eslesmeFormDeger').value = '';
      $('eslesmeFormOncelik').value = 50;
      $('eslesmeFormAciklama').value = '';
    }
    $('eslesmeFormModal').classList.add('acik');
  }
  window.eslesmeFormKapat = function () { $('eslesmeFormModal').classList.remove('acik'); };
  window._eslesmeDuzenle = function(eid) { eslesmeFormAc('duzenle', eid); };

  window._eslesmeSilSor = function(eid) {
    var e = STATE.eslesmeler.find(function(x){ return x.id === eid; });
    if (!e) return;
    STATE.silTarget = { tip: 'eslesme', id: eid };
    $('silOnayBaslik').textContent = 'Eslesme Kurali Silme Onayi';
    $('silOnayMesaj').innerHTML = 'Bu eslesme kurali silinecek (pasife alinacak):<br>' +
      '<b>' + esc(ESLESME_TIP_LABEL[e.eslesme_tipi] || e.eslesme_tipi) + '</b> = <b>' + esc(e.eslesme_degeri) + '</b> &rarr; ' +
      '<b>' + esc(e.sablon_adi) + '</b> (onc:' + e.oncelik + ')';
    $('silOnayUyari').style.display = 'none';
    $('silOnayModal').classList.add('acik');
  };

  function eslesmeKaydet() {
    var hata = $('eslesmeFormHata');
    hata.style.display = 'none';
    var body = {
      sablon_id: parseInt($('eslesmeFormSablonId').value),
      eslesme_tipi: $('eslesmeFormTip').value,
      eslesme_degeri: ($('eslesmeFormDeger').value || '').trim(),
      oncelik: parseInt($('eslesmeFormOncelik').value),
      aciklama: ($('eslesmeFormAciklama').value || '').trim()
    };
    if (!body.eslesme_degeri) { hata.textContent = 'Deger zorunlu'; hata.style.display = 'block'; return; }
    if (!(body.oncelik >= 1 && body.oncelik <= 999)) { hata.textContent = 'Oncelik 1-999 arasi olmali'; hata.style.display = 'block'; return; }
    var eid = $('eslesmeFormId').value;
    var url = eid ? '/hedef/sablon-eslesme/guncelle/' + eid : '/hedef/sablon-eslesme/ekle';
    var btn = $('btnEslesmeKaydet');
    btn.disabled = true;
    fetchJSON(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function(res){
        btn.disabled = false;
        if (!res.body.ok) {
          hata.textContent = res.body.mesaj || 'Kayit basarisiz';
          hata.style.display = 'block';
          return;
        }
        window.eslesmeFormKapat();
        eslesmeListeYukle();
      })
      .catch(function(e){
        btn.disabled = false;
        hata.textContent = 'Hata: ' + e.message;
        hata.style.display = 'block';
      });
  }

  /* ===== INIT ===== */
  function init() {
    document.querySelectorAll('.tab-btn').forEach(function(b){
      b.addEventListener('click', function(){ tabAc(this.dataset.tab); });
    });
    var btnYS = $('btnYeniSablon');
    if (btnYS) btnYS.addEventListener('click', function(){ sablonFormAc('yeni'); });
    var btnYE = $('btnYeniEslesme');
    if (btnYE) btnYE.addEventListener('click', function(){ eslesmeFormAc('yeni'); });
    var btnPE = $('btnProsesEkle');
    if (btnPE) btnPE.addEventListener('click', prosesEkle);
    var inpPY = $('sablonFormProsesYeni');
    if (inpPY) inpPY.addEventListener('keydown', function(ev){ if (ev.key === 'Enter') { ev.preventDefault(); prosesEkle(); } });
    var btnSK = $('btnSablonKaydet');
    if (btnSK) btnSK.addEventListener('click', sablonKaydet);
    var btnEK = $('btnEslesmeKaydet');
    if (btnEK) btnEK.addEventListener('click', eslesmeKaydet);
    var btnSO = $('btnSilOnay');
    if (btnSO) btnSO.addEventListener('click', silOnayla);

    var savedTab = 'sablonlar';
    try { savedTab = localStorage.getItem('cps_sablon_tab') || 'sablonlar'; } catch(e){}
    tabAc(savedTab);

    sablonListeYukle();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();