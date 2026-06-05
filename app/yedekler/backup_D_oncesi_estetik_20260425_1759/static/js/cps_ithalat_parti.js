/**
 * CPS DEV - Ithalat Parti Listesi JS
 * -----------------------------------
 * Sayfa:     templates/ithalat_parti_liste.html
 * Endpoint:  /api/ithalat/parti/liste
 *            /api/ithalat/parti/liste/kpi
 *            /api/lookup/tedarikciler
 *
 * Prensipler:
 *   - Vanilla JS, fetch API
 *   - IIFE scope (global cakisma yok)
 *   - Fail-safe: tum fetch'ler try/catch
 *   - Debounce 300ms
 */
(function () {
  'use strict';

  // =====================================================================
  // SABITLER
  // =====================================================================
  var API = {
    liste:     '/api/ithalat/parti/liste',
    kpi:       '/api/ithalat/parti/liste/kpi',
    tedarikci: '/api/lookup/tedarikciler',
  };

  var DETAY_URL = '/ithalat/parti/';
  var DEBOUNCE_MS = 300;
  var FETCH_TIMEOUT = 15000;

  var DURUM_MAP = {
    'TASLAK':  { etiket: 'Taslak', sinif: 'cps-ith-d-taslak' },
    'AKTIF':   { etiket: 'Yolda',  sinif: 'cps-ith-d-aktif'  },
    'TESLIM':  { etiket: 'Geldi',  sinif: 'cps-ith-d-teslim' },
    'KAPALI':  { etiket: 'Kapali', sinif: 'cps-ith-d-kapali' },
    'IPTAL':   { etiket: 'Iptal',  sinif: 'cps-ith-d-iptal'  },
  };

  var RISK_UYARI_ESIK  = 5.0;
  var RISK_KRITIK_ESIK = 10.0;


  // =====================================================================
  // DOM REFERANSLARI
  // =====================================================================
  var dom = {
    sayfa: null,
    kpiToplam: null, kpiAktif: null, kpiAktifTutar: null,
    kpiOdemeAdet: null, kpiOdemeTutar: null, kpiRiskli: null,
    fDurum: null, fTedarikci: null, fTarih: null, fAra: null,
    btnSifirla: null, btnBosSifirla: null,
    btnYenile: null, btnYeniParti: null,
    tablo: null, tbody: null, sablon: null, ozetSayi: null,
    yukleniyor: null, bos: null, hata: null, hataTekrar: null,
  };


  // =====================================================================
  // STATE
  // =====================================================================
  var state = {
    aktifIstek: null,
    debounceTimer: null,
    sonFiltre: null,
  };


  // =====================================================================
  // YARDIMCILAR
  // =====================================================================
  function $(id) { return document.getElementById(id); }

  function gosterGizle(el, goster) {
    if (!el) return;
    if (goster) el.classList.remove('cps-ith-gizle');
    else        el.classList.add('cps-ith-gizle');
  }

  function metinAyarla(el, metin) {
    if (!el) return;
    el.textContent = (metin == null || metin === '') ? '—' : String(metin);
  }

  function paraFormatla(tutar, paraBirimi) {
    if (tutar == null || isNaN(tutar)) return '—';
    var num = Number(tutar);
    var abs = Math.abs(num);
    var gosterilen;
    if (abs >= 1000000) {
      gosterilen = (num / 1000000).toFixed(2) + 'M';
    } else if (abs >= 10000) {
      gosterilen = (num / 1000).toFixed(1) + 'K';
    } else {
      gosterilen = num.toLocaleString('tr-TR', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      });
    }
    return paraBirimi ? gosterilen + ' ' + paraBirimi : gosterilen;
  }

  function sayiFormatla(sayi) {
    if (sayi == null || isNaN(sayi)) return '—';
    return Number(sayi).toLocaleString('tr-TR');
  }

  function yuzdeFormatla(yuzde) {
    if (yuzde == null || isNaN(yuzde)) return '';
    var num = Number(yuzde);
    var isaret = num > 0 ? '+' : '';
    return isaret + num.toFixed(1) + '%';
  }

  function tarihFormatla(isoStr) {
    if (!isoStr) return '';
    try {
      var parts = String(isoStr).substring(0, 10).split('-');
      if (parts.length !== 3) return isoStr;
      return parts[2] + '.' + parts[1] + '.' + parts[0].substring(2);
    } catch (e) {
      return isoStr;
    }
  }

  function gunFarki(isoStr) {
    if (!isoStr) return null;
    try {
      var t = new Date(isoStr);
      var bugun = new Date();
      t.setHours(0, 0, 0, 0);
      bugun.setHours(0, 0, 0, 0);
      return Math.round((t - bugun) / (1000 * 60 * 60 * 24));
    } catch (e) {
      return null;
    }
  }


  // =====================================================================
  // FETCH
  // =====================================================================
  function fetchJson(url) {
    var ctrl = new AbortController();
    var timeoutId = setTimeout(function () { ctrl.abort(); }, FETCH_TIMEOUT);

    var istek = fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' },
      signal: ctrl.signal,
    }).then(function (resp) {
      clearTimeout(timeoutId);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    }).catch(function (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') return null;
      console.warn('[cps-ith] fetch hata:', url, err);
      throw err;
    });

    istek.ctrl = ctrl;
    return istek;
  }


  // =====================================================================
  // KPI
  // =====================================================================
  function kpiYukle() {
    fetchJson(API.kpi).then(function (veri) {
      if (!veri) return;
      kpiDoldur(veri);
    }).catch(function () {
      console.warn('[cps-ith] KPI yuklenemedi');
    });
  }

  function kpiDoldur(veri) {
    var d = veri || {};
    metinAyarla(dom.kpiToplam,    sayiFormatla(d.toplam_parti));
    metinAyarla(dom.kpiAktif,     sayiFormatla(d.aktif_parti));
    metinAyarla(dom.kpiAktifTutar,
      d.aktif_tutar != null
        ? paraFormatla(d.aktif_tutar, d.aktif_para || 'USD')
        : '—'
    );
    metinAyarla(dom.kpiOdemeAdet, sayiFormatla(d.bu_hafta_odeme_adet));
    metinAyarla(dom.kpiOdemeTutar,
      d.bu_hafta_odeme_tutar != null
        ? paraFormatla(d.bu_hafta_odeme_tutar, d.bu_hafta_odeme_para || 'USD')
        : '—'
    );
    metinAyarla(dom.kpiRiskli,    sayiFormatla(d.riskli_parti));
  }


  // =====================================================================
  // FILTRE
  // =====================================================================
  function tedarikciYukle() {
    fetchJson(API.tedarikci).then(function (veri) {
      if (!veri || !Array.isArray(veri)) return;
      tedarikciDoldur(veri);
    }).catch(function () {});
  }

  function tedarikciDoldur(liste) {
    if (!dom.fTedarikci) return;
    liste.forEach(function (t) {
      if (!t || !t.kod) return;
      var opt = document.createElement('option');
      opt.value = t.kod;
      opt.textContent = t.ad ? (t.kod + ' — ' + t.ad) : t.kod;
      dom.fTedarikci.appendChild(opt);
    });
  }

  function filtreleriTopla() {
    return {
      durum:         (dom.fDurum     && dom.fDurum.value)     || '',
      tedarikci_kod: (dom.fTedarikci && dom.fTedarikci.value) || '',
      tarih:         (dom.fTarih     && dom.fTarih.value)     || '',
      ara:           (dom.fAra       && dom.fAra.value.trim()) || '',
    };
  }

  function filtreleriSifirla() {
    if (dom.fDurum)     dom.fDurum.value     = '';
    if (dom.fTedarikci) dom.fTedarikci.value = '';
    if (dom.fTarih)     dom.fTarih.value     = 'son-12-ay';
    if (dom.fAra)       dom.fAra.value       = '';
    listeYenileDebounce();
  }

  function filtreDegistiginde() {
    listeYenileDebounce();
  }

  function listeYenileDebounce() {
    if (state.debounceTimer) clearTimeout(state.debounceTimer);
    state.debounceTimer = setTimeout(listeYukle, DEBOUNCE_MS);
  }


  // =====================================================================
  // LISTE
  // =====================================================================
  function listeYukle() {
    var filtre = filtreleriTopla();
    state.sonFiltre = filtre;

    if (state.aktifIstek && state.aktifIstek.ctrl) {
      state.aktifIstek.ctrl.abort();
    }

    durumGoster('yukleniyor');

    var qs = new URLSearchParams();
    Object.keys(filtre).forEach(function (k) {
      if (filtre[k]) qs.append(k, filtre[k]);
    });

    state.aktifIstek = fetchJson(API.liste + '?' + qs.toString());

    state.aktifIstek.then(function (veri) {
      if (!veri) return;
      if (!Array.isArray(veri)) {
        durumGoster('hata');
        return;
      }
      listeBas(veri);
    }).catch(function () {
      durumGoster('hata');
    });
  }

  function listeBas(liste) {
    dom.tbody.innerHTML = '';

    if (!liste.length) {
      durumGoster('bos');
      metinAyarla(dom.ozetSayi, '0');
      return;
    }

    var frag = document.createDocumentFragment();
    liste.forEach(function (parti) {
      var satir = satirUret(parti);
      if (satir) frag.appendChild(satir);
    });
    dom.tbody.appendChild(frag);

    metinAyarla(dom.ozetSayi, String(liste.length));
    durumGoster('tablo');
  }

  function satirUret(p) {
    if (!dom.sablon || !p || !p.id) return null;

    var klon = dom.sablon.content.cloneNode(true);
    var tr = klon.querySelector('tr');
    if (!tr) return null;

    tr.dataset.partiId = p.id;

    // Risk
    var risk = riskHesapla(p);
    tr.classList.add('cps-ith-risk-' + risk.seviye);
    var riskNokta = tr.querySelector('.cps-ith-risk-nokta');
    if (riskNokta) riskNokta.title = risk.aciklama;

    // Kod
    var kodEl = tr.querySelector('[data-alan="kod"]');
    if (kodEl) kodEl.textContent = p.kod || '—';

    // Baslik
    var baslikEl = tr.querySelector('[data-alan="baslik"]');
    if (baslikEl) baslikEl.textContent = p.baslik || '—';

    // Tedarikci
    var tedEl = tr.querySelector('[data-alan="tedarikci"]');
    if (tedEl) {
      var ted = p.tedarikci_ad || p.tedarikci_kod || '—';
      tedEl.textContent = ted;
      if (p.tedarikci_ad && p.tedarikci_kod) {
        tedEl.title = p.tedarikci_kod + ' — ' + p.tedarikci_ad;
      }
    }

    // Toplam Maliyet
    var tutarEl = tr.querySelector('[data-alan="etkin-toplam"]');
    var paraEl  = tr.querySelector('[data-alan="para"]');
    if (tutarEl) {
      tutarEl.textContent = p.etkin_toplam != null
        ? paraFormatla(p.etkin_toplam)
        : '—';
    }
    if (paraEl) {
      paraEl.textContent = p.etkin_toplam != null && p.para_birimi
        ? ' ' + p.para_birimi
        : '';
    }

    // Cift Maliyet
    var ciftEl    = tr.querySelector('[data-alan="cift-maliyet"]');
    var ciftBirEl = tr.querySelector('[data-alan="cift-birim"]');
    if (ciftEl) {
      if (p.cift_maliyet != null) {
        ciftEl.textContent = Number(p.cift_maliyet).toFixed(2);
        if (ciftBirEl) ciftBirEl.textContent = ' ' + (p.para_birimi || '') + '/cift';
      } else {
        ciftEl.textContent = '—';
        if (ciftBirEl) ciftBirEl.textContent = '';
      }
    }

    // Durum
    var durumEl = tr.querySelector('[data-alan="durum"]');
    if (durumEl) {
      var dMap = DURUM_MAP[p.durum] || { etiket: p.durum || '—', sinif: '' };
      durumEl.textContent = dMap.etiket;
      if (dMap.sinif) durumEl.classList.add(dMap.sinif);
    }

    // Ilk Odeme
    var odEl   = tr.querySelector('[data-alan="ilk-odeme-tarih"]');
    var odEkEl = tr.querySelector('[data-alan="ilk-odeme-ek"]');
    if (odEl) {
      if (p.ilk_odeme_tarih) {
        odEl.textContent = tarihFormatla(p.ilk_odeme_tarih);
        if (odEkEl) {
          var fark = gunFarki(p.ilk_odeme_tarih);
          if (fark != null) {
            if (fark < 0)       odEkEl.textContent = ' (' + Math.abs(fark) + 'g gecikti)';
            else if (fark === 0) odEkEl.textContent = ' (bugun)';
            else if (fark <= 7) odEkEl.textContent = ' (' + fark + 'g sonra)';
            else                odEkEl.textContent = '';
          }
        }
      } else {
        odEl.textContent = '—';
        if (odEkEl) odEkEl.textContent = '';
      }
    }

    // Sapma
    var sapmaEl = tr.querySelector('[data-alan="sapma-yuzde"]');
    if (sapmaEl) {
      if (p.sapma_yuzde != null) {
        sapmaEl.textContent = yuzdeFormatla(p.sapma_yuzde);
        if (Math.abs(p.sapma_yuzde) > RISK_KRITIK_ESIK) {
          sapmaEl.classList.add('cps-ith-sapma-kritik');
        } else if (Math.abs(p.sapma_yuzde) > RISK_UYARI_ESIK) {
          sapmaEl.classList.add('cps-ith-sapma-uyari');
        }
      } else {
        sapmaEl.textContent = '—';
      }
    }

    // Satir tiklama
    tr.addEventListener('click', function () {
      window.location.href = DETAY_URL + p.id;
    });

    return tr;
  }


  // =====================================================================
  // RISK
  // =====================================================================
  function riskHesapla(p) {
    var sebep = [];
    var seviye = 'normal';

    if (p.geciken_odeme) {
      seviye = 'kritik';
      sebep.push('Geciken odeme var');
    }

    if (p.sapma_yuzde != null) {
      var abs = Math.abs(p.sapma_yuzde);
      if (abs > RISK_KRITIK_ESIK) {
        seviye = 'kritik';
        sebep.push('Sapma ' + yuzdeFormatla(p.sapma_yuzde));
      } else if (abs > RISK_UYARI_ESIK && seviye !== 'kritik') {
        seviye = 'uyari';
        sebep.push('Sapma ' + yuzdeFormatla(p.sapma_yuzde));
      }
    }

    if (seviye === 'normal' && p.ilk_odeme_tarih) {
      var fark = gunFarki(p.ilk_odeme_tarih);
      if (fark != null && fark >= 0 && fark <= 7) {
        seviye = 'uyari';
        sebep.push(fark + ' gun icinde odeme');
      }
    }

    if (p.tahmini_varis_tarih && p.durum === 'AKTIF') {
      var vf = gunFarki(p.tahmini_varis_tarih);
      if (vf != null && vf < 0) {
        seviye = 'kritik';
        sebep.push('Varis ' + Math.abs(vf) + ' gun gecikti');
      }
    }

    return {
      seviye: seviye,
      aciklama: sebep.length ? sebep.join(', ') : 'Risk yok',
    };
  }


  // =====================================================================
  // DURUM
  // =====================================================================
  function durumGoster(hangi) {
    gosterGizle(dom.yukleniyor, hangi === 'yukleniyor');
    gosterGizle(dom.bos,        hangi === 'bos');
    gosterGizle(dom.hata,       hangi === 'hata');
    gosterGizle(dom.tablo,      hangi === 'tablo');
  }


  // =====================================================================
  // OLAY BAGLAMA
  // =====================================================================
  function olaylariBagla() {
    if (dom.fDurum)     dom.fDurum.addEventListener('change', filtreDegistiginde);
    if (dom.fTedarikci) dom.fTedarikci.addEventListener('change', filtreDegistiginde);
    if (dom.fTarih)     dom.fTarih.addEventListener('change', filtreDegistiginde);
    if (dom.fAra)       dom.fAra.addEventListener('input', filtreDegistiginde);

    if (dom.btnSifirla)    dom.btnSifirla.addEventListener('click', filtreleriSifirla);
    if (dom.btnBosSifirla) dom.btnBosSifirla.addEventListener('click', filtreleriSifirla);

    if (dom.btnYenile) {
      dom.btnYenile.addEventListener('click', function () {
        kpiYukle();
        listeYukle();
      });
    }

    if (dom.hataTekrar) {
      dom.hataTekrar.addEventListener('click', function (e) {
        e.preventDefault();
        listeYukle();
      });
    }

    if (dom.btnYeniParti) {
      dom.btnYeniParti.addEventListener('click', function () {
        yeniPartiModul.ac();
      });
    }
  }


  // =====================================================================
  // YENI PARTI MODULI (modal) - TAM VERSIYON
  // =====================================================================
  var yeniPartiModul = {
    _autocomplete_zamani: null,

    ac: function () {
      var m = $('cps-ith-yeni-parti-modal');
      if (!m) {
        console.error('[yeni-parti] modal bulunamadi - HTML eksik!');
        alert('Yeni parti formu yüklenemedi. Sayfayı yenileyin (Ctrl+F5).');
        return;
      }
      yeniPartiModul._temizle();
      m.classList.remove('cps-ith-gizle');
      document.body.style.overflow = 'hidden';

      // Default yukleme tarihi = bugun
      var bugun = new Date().toISOString().substring(0, 10);
      var yukEl = $('yp-yukleme');
      if (yukEl && !yukEl.value) yukEl.value = bugun;

      // Default tahmini varis = +30 gun
      var varis = new Date();
      varis.setDate(varis.getDate() + 30);
      var varisEl = $('yp-varis');
      if (varisEl && !varisEl.value) {
        varisEl.value = varis.toISOString().substring(0, 10);
      }

      // Odak
      setTimeout(function () {
        var blk = $('yp-baslik');
        if (blk) blk.focus();
      }, 100);
    },

    kapat: function () {
      var m = $('cps-ith-yeni-parti-modal');
      if (m) m.classList.add('cps-ith-gizle');
      document.body.style.overflow = '';
      yeniPartiModul._onerileriGizle();
    },

    _temizle: function () {
      ['yp-baslik', 'yp-tedarikci-ad', 'yp-tedarikci-kod',
       'yp-yukleme', 'yp-varis', 'yp-cift', 'yp-kg',
       'yp-aciklama'].forEach(function (id) {
        var el = $(id);
        if (el) el.value = '';
      });
      var paraEl = $('yp-para');
      if (paraEl) paraEl.value = 'USD';
      yeniPartiModul._durumTemizle();
      yeniPartiModul._onerileriGizle();
      // Field hata classlari temizle
      ['yp-baslik', 'yp-tedarikci-ad', 'yp-para', 'yp-cift'].forEach(function (id) {
        var el = $(id);
        if (el) el.classList.remove('cps-ith-input-hata');
      });
    },

    _durumTemizle: function () {
      var durumEl = $('cps-ith-yeni-parti-durum');
      if (durumEl) {
        durumEl.textContent = '';
        durumEl.className = 'cps-ith-kayit-durum';
      }
    },

    _durumHata: function (msg) {
      var durumEl = $('cps-ith-yeni-parti-durum');
      if (durumEl) {
        durumEl.className = 'cps-ith-kayit-durum hata';
        durumEl.textContent = '✗ ' + msg;
      }
    },

    _durumOk: function (msg) {
      var durumEl = $('cps-ith-yeni-parti-durum');
      if (durumEl) {
        durumEl.className = 'cps-ith-kayit-durum ok';
        durumEl.textContent = '✓ ' + msg;
      }
    },

    _alanHata: function (id, odak) {
      var el = $(id);
      if (el) {
        el.classList.add('cps-ith-input-hata');
        if (odak) el.focus();
      }
    },

    _alanHatayiTemizle: function (id) {
      var el = $(id);
      if (el) el.classList.remove('cps-ith-input-hata');
    },

    _loadingBasla: function () {
      var btn = $('cps-ith-yeni-parti-kaydet');
      if (!btn) return;
      btn.disabled = true;
      var metin = btn.querySelector('.cps-ith-btn-metin');
      var spinner = btn.querySelector('.cps-ith-btn-spinner');
      if (metin) metin.textContent = 'Kaydediliyor...';
      if (spinner) spinner.classList.remove('cps-ith-gizle');
    },

    _loadingBitir: function () {
      var btn = $('cps-ith-yeni-parti-kaydet');
      if (!btn) return;
      btn.disabled = false;
      var metin = btn.querySelector('.cps-ith-btn-metin');
      var spinner = btn.querySelector('.cps-ith-btn-spinner');
      if (metin) metin.textContent = 'Oluştur';
      if (spinner) spinner.classList.add('cps-ith-gizle');
    },

    /**
     * Tedarikci autocomplete.
     * Kullanici yazdikca /api/ithalat/tedarikci/arama sorgusu.
     * Debounce 300ms.
     */
    _tedarikciAutocomplete: function (e) {
      var q_str = (e.target.value || '').trim();
      if (yeniPartiModul._autocomplete_zamani) {
        clearTimeout(yeniPartiModul._autocomplete_zamani);
      }
      if (q_str.length < 2) {
        yeniPartiModul._onerileriGizle();
        return;
      }
      yeniPartiModul._autocomplete_zamani = setTimeout(function () {
        fetch('/api/ithalat/tedarikci/arama?q=' + encodeURIComponent(q_str) + '&limit=8',
              { credentials: 'same-origin', headers: {'Accept': 'application/json'} })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok && d.sonuclar && d.sonuclar.length) {
              yeniPartiModul._onerileriGoster(d.sonuclar);
            } else {
              yeniPartiModul._onerileriGizle();
            }
          })
          .catch(function (err) {
            console.warn('[yeni-parti] autocomplete fetch hata:', err);
            yeniPartiModul._onerileriGizle();
          });
      }, 300);
    },

    _onerileriGoster: function (sonuclar) {
      var kutu = $('yp-tedarikci-oneriler');
      if (!kutu) return;
      kutu.innerHTML = '';
      sonuclar.forEach(function (s) {
        var item = document.createElement('div');
        item.className = 'cps-ith-autocomplete-item';
        var ad = document.createElement('div');
        ad.className = 'cps-ith-autocomplete-ad';
        ad.textContent = s.ad || '—';
        item.appendChild(ad);
        if (s.kod && s.kod !== s.ad) {
          var kod = document.createElement('div');
          kod.className = 'cps-ith-autocomplete-kod';
          kod.textContent = s.kod;
          item.appendChild(kod);
        }
        item.addEventListener('mousedown', function (e) {
          e.preventDefault();  // input blur'u engelle
          yeniPartiModul._oneriSec(s);
        });
        kutu.appendChild(item);
      });
      kutu.classList.remove('cps-ith-gizle');
    },

    _onerileriGizle: function () {
      var kutu = $('yp-tedarikci-oneriler');
      if (kutu) kutu.classList.add('cps-ith-gizle');
    },

    _oneriSec: function (s) {
      var adEl = $('yp-tedarikci-ad');
      var kodEl = $('yp-tedarikci-kod');
      if (adEl) adEl.value = s.ad || '';
      if (kodEl && s.kod && s.kod !== s.ad) kodEl.value = s.kod;
      yeniPartiModul._onerileriGizle();
      yeniPartiModul._alanHatayiTemizle('yp-tedarikci-ad');
    },

    /**
     * VALIDASYON + KAYDET
     */
    kaydet: function () {
      yeniPartiModul._durumTemizle();

      // 1. Baslik
      var baslik = ($('yp-baslik').value || '').trim();
      if (!baslik) {
        yeniPartiModul._durumHata('Başlık zorunludur');
        yeniPartiModul._alanHata('yp-baslik', true);
        return;
      }
      if (baslik.length < 3) {
        yeniPartiModul._durumHata('Başlık en az 3 karakter olmalı');
        yeniPartiModul._alanHata('yp-baslik', true);
        return;
      }
      yeniPartiModul._alanHatayiTemizle('yp-baslik');

      // 2. Tedarikci adi
      var tedAd = ($('yp-tedarikci-ad').value || '').trim();
      if (!tedAd) {
        yeniPartiModul._durumHata('Tedarikçi adı zorunludur');
        yeniPartiModul._alanHata('yp-tedarikci-ad', true);
        return;
      }
      yeniPartiModul._alanHatayiTemizle('yp-tedarikci-ad');

      // 3. Para birimi
      var para = ($('yp-para').value || '').trim();
      if (!para) {
        yeniPartiModul._durumHata('Para birimi seçilmeli');
        yeniPartiModul._alanHata('yp-para', true);
        return;
      }
      yeniPartiModul._alanHatayiTemizle('yp-para');

      // 4. Toplam cift
      var ciftStr = $('yp-cift').value;
      if (ciftStr === '' || ciftStr == null) {
        yeniPartiModul._durumHata('Toplam çift zorunludur');
        yeniPartiModul._alanHata('yp-cift', true);
        return;
      }
      var cift = parseInt(ciftStr, 10);
      if (isNaN(cift) || cift <= 0) {
        yeniPartiModul._durumHata('Toplam çift 0\'dan büyük olmalı');
        yeniPartiModul._alanHata('yp-cift', true);
        return;
      }
      yeniPartiModul._alanHatayiTemizle('yp-cift');

      // 5. Opsiyonel alanlar
      var yukleme = $('yp-yukleme').value || null;
      var varis = $('yp-varis').value || null;

      // Tarih format kontrolu (YYYY-MM-DD)
      var tarihRegex = /^\d{4}-\d{2}-\d{2}$/;
      if (yukleme && !tarihRegex.test(yukleme)) {
        yeniPartiModul._durumHata('Yükleme tarihi formatı hatalı (YYYY-MM-DD)');
        return;
      }
      if (varis && !tarihRegex.test(varis)) {
        yeniPartiModul._durumHata('Tahmini varış tarihi formatı hatalı (YYYY-MM-DD)');
        return;
      }

      var kgStr = $('yp-kg').value;
      var kg = null;
      if (kgStr !== '' && kgStr != null) {
        kg = parseFloat(kgStr);
        if (isNaN(kg) || kg < 0) {
          yeniPartiModul._durumHata('Toplam kg sayısal olmalı (0 veya pozitif)');
          return;
        }
      }

      // Veri paketi
      var veri = {
        baslik:              baslik,
        tedarikci_ad:        tedAd,
        tedarikci_kod:       ($('yp-tedarikci-kod').value || '').trim() || null,
        para_birimi:         para,
        yukleme_tarih:       yukleme,
        tahmini_varis_tarih: varis,
        toplam_cift:         cift,
        toplam_kg:           kg,
        aciklama:            ($('yp-aciklama').value || '').trim() || null,
      };

      // Loading state
      yeniPartiModul._loadingBasla();
      yeniPartiModul._durumTemizle();

      fetch('/api/ithalat/parti/olustur', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(veri),
      })
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, status: r.status, data: j }; });
      })
      .then(function (r) {
        yeniPartiModul._loadingBitir();
        if (r.ok && r.data && r.data.ok) {
          yeniPartiModul._durumOk(
            (r.data.mesaj || 'İthalat partisi başarıyla oluşturuldu.') +
            ' (' + (r.data.parti_kod || '') + ')'
          );
          setTimeout(function () {
            yeniPartiModul.kapat();
            listeYukle();
            // Yeni parti detayina git teklifi
            if (r.data.parti_id) {
              if (confirm('Parti oluşturuldu: ' + (r.data.parti_kod || '') +
                         '\n\nDetayına gitmek ister misiniz?')) {
                window.location.href = '/ithalat/parti/' + r.data.parti_id;
              }
            }
          }, 1000);
        } else {
          var hata = (r.data && (r.data.hata || r.data.mesaj)) || 'Bir hata oluştu';
          yeniPartiModul._durumHata(hata);
        }
      })
      .catch(function (e) {
        yeniPartiModul._loadingBitir();
        yeniPartiModul._durumHata('Bağlantı hatası: ' + (e.message || ''));
        console.error('[yeni-parti] fetch hata:', e);
      });
    },

    bagla: function () {
      var kapat1 = $('cps-ith-yeni-parti-kapat');
      if (kapat1) kapat1.addEventListener('click', yeniPartiModul.kapat);

      var back = $('cps-ith-yeni-parti-backdrop');
      if (back) back.addEventListener('click', yeniPartiModul.kapat);

      var iptal = $('cps-ith-yeni-parti-iptal');
      if (iptal) iptal.addEventListener('click', yeniPartiModul.kapat);

      var kaydet = $('cps-ith-yeni-parti-kaydet');
      if (kaydet) kaydet.addEventListener('click', yeniPartiModul.kaydet);

      // Autocomplete
      var tedAdEl = $('yp-tedarikci-ad');
      if (tedAdEl) {
        tedAdEl.addEventListener('input', yeniPartiModul._tedarikciAutocomplete);
        tedAdEl.addEventListener('blur', function () {
          // Tiklama bitmeden gizlememeli - gecikme
          setTimeout(yeniPartiModul._onerileriGizle, 150);
        });
      }

      // ESC ile kapat
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
          var m = $('cps-ith-yeni-parti-modal');
          if (m && !m.classList.contains('cps-ith-gizle')) {
            yeniPartiModul.kapat();
          }
        }
      });

      // Enter ile formu kaydet (textarea haric)
      var f = $('cps-ith-yeni-parti-form');
      if (f) {
        f.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') {
            e.preventDefault();
            yeniPartiModul.kaydet();
          }
        });
      }
    },
  };


  // =====================================================================
  // BASLATMA
  // =====================================================================
  function domReferansVer() {
    dom.sayfa = document.querySelector('[data-sayfa="parti-liste"]');
    if (!dom.sayfa) return false;

    var kpiRoot = $('cps-ith-kpi');
    if (kpiRoot) {
      dom.kpiToplam      = kpiRoot.querySelector('[data-deger="toplam"]');
      dom.kpiAktif       = kpiRoot.querySelector('[data-deger="aktif"]');
      dom.kpiAktifTutar  = kpiRoot.querySelector('[data-deger="aktif-tutar"]');
      dom.kpiOdemeAdet   = kpiRoot.querySelector('[data-deger="odeme-adet"]');
      dom.kpiOdemeTutar  = kpiRoot.querySelector('[data-deger="odeme-tutar"]');
      dom.kpiRiskli      = kpiRoot.querySelector('[data-deger="riskli"]');
    }

    dom.fDurum        = $('cps-ith-f-durum');
    dom.fTedarikci    = $('cps-ith-f-tedarikci');
    dom.fTarih        = $('cps-ith-f-tarih');
    dom.fAra          = $('cps-ith-f-ara');
    dom.btnSifirla    = $('cps-ith-btn-filtre-sifirla');
    dom.btnBosSifirla = $('cps-ith-bos-sifirla');
    dom.btnYenile     = $('cps-ith-btn-yenile');
    dom.btnYeniParti  = $('cps-ith-btn-yeni-parti');

    dom.tablo    = $('cps-ith-tablo');
    dom.tbody    = $('cps-ith-tbody');
    dom.sablon   = $('cps-ith-satir-sablon');
    dom.ozetSayi = $('cps-ith-ozet-sayi');

    dom.yukleniyor = $('cps-ith-yukleniyor');
    dom.bos        = $('cps-ith-bos');
    dom.hata       = $('cps-ith-hata');
    dom.hataTekrar = $('cps-ith-hata-tekrar');

    return true;
  }

  function baslat() {
    if (!domReferansVer()) {
      console.warn('[cps-ith] Parti listesi sayfasi bulunamadi, JS pasif.');
      return;
    }

    olaylariBagla();
    yeniPartiModul.bagla();
    tedarikciYukle();
    kpiYukle();
    listeYukle();

    console.info('[cps-ith] Parti listesi aktif.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', baslat);
  } else {
    baslat();
  }

})();
