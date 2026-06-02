// ============================================================
// F9_5_2_OPERASYON_GECMIS_JS
// Patch: OP_RAPOR_V2_GECMIS
// Snapshot: STABLE_OP_RAPOR_V2_GECMIS_PRE_PATCH_20260515_153601
// Operasyon Raporu - GECMIS / EXCEL DETAY sekmesi davranisi
// Mevcut planlama_operasyon.js dokunulmaz, bu dosya bagimsiz.
// ============================================================

(function() {
  'use strict';

  // ----- DURUM MAPPING (backend -> saha dili gosterim) -----
  const DURUM_GOSTER = {
    'CLS': 'CLS',
    'KLP': 'KLP',
    'ARZ': 'ARZ',
    'KPL': 'KPL',
    'DRS': 'DRS'
  };

  const VARDIYA_GOSTER = {
    'gunduz': 'Gunduz',
    'mesai':  'Mesai',
    'gece':   'Gece'
  };

  // ----- STATE -----
  const state = {
    ilkYukleme: true,
    sayfa: 1,
    boyut: 50,
    tarihPreset: 'bugun',
    yukleniyor: false
  };

  // ----- HELPERS -----
  function el(id) { return document.getElementById(id); }

  function tarihYYYYMMDD(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const g = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + g;
  }

  function bugunTarih() { return tarihYYYYMMDD(new Date()); }

  function gunOnceTarih(gun) {
    const d = new Date();
    d.setDate(d.getDate() - gun);
    return tarihYYYYMMDD(d);
  }

  function ayBaslangic() {
    const d = new Date();
    d.setDate(1);
    return tarihYYYYMMDD(d);
  }

  function yilBaslangic() {
    const d = new Date();
    return d.getFullYear() + '-01-01';
  }

  function sayiFmt(n) {
    if (n === null || n === undefined) return '-';
    return Number(n).toLocaleString('tr-TR');
  }

  function htmlEscape(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>\"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;','\\u0027':'&#39;'}[c];
    });
  }

  // ----- TARIH PRESET'LERINI UYGULA -----
  function tarihAraligiUygula(preset) {
    state.tarihPreset = preset;
    const bugun = bugunTarih();
    let bas, bit;
    if (preset === 'bugun') { bas = bugun; bit = bugun; }
    else if (preset === 'son15') { bas = gunOnceTarih(14); bit = bugun; }
    else if (preset === 'buay') { bas = ayBaslangic(); bit = bugun; }
    else if (preset === 'son6ay') { bas = gunOnceTarih(180); bit = bugun; }
    else if (preset === 'buyil') { bas = yilBaslangic(); bit = bugun; }
    else { return; }
    el('orgec-tarih-bas').value = bas;
    el('orgec-tarih-bit').value = bit;
    document.querySelectorAll('.or-gec-tarih-btn').forEach(function(b) {
      b.classList.toggle('aktif', b.dataset.preset === preset);
    });
  }

  // ----- FETCH -----
  function veriCek() {
    if (state.yukleniyor) return;
    state.yukleniyor = true;

    const params = new URLSearchParams();
    params.set('tarih_bas', el('orgec-tarih-bas').value);
    params.set('tarih_bit', el('orgec-tarih-bit').value);
    const makineId = el('orgec-makine').value;
    const operator = el('orgec-operator').value;
    const kalipTipi = el('orgec-kalip-tipi').value;
    const vardiya  = el('orgec-vardiya').value;
    const durum    = el('orgec-durum').value;
    const arama    = el('orgec-arama').value.trim();
    if (makineId)  params.set('makine_id', makineId);
    if (operator)  params.set('operator', operator);
    if (kalipTipi) params.set('kalip_tipi', kalipTipi);
    if (vardiya)   params.set('vardiya', vardiya);
    if (durum)     params.set('durum', durum);
    if (arama)     params.set('arama', arama);
    params.set('sayfa', state.sayfa);
    params.set('boyut', state.boyut);

    el('orgec-icerik').innerHTML = '<div class=\"or-gec-yukleniyor\">Yukleniyor...</div>';

    fetch('/planlama/api/operasyon/gecmis?' + params.toString(), {
      credentials: 'same-origin'
    })
    .then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(d) {
      state.yukleniyor = false;
      if (!d.ok) {
        el('orgec-icerik').innerHTML = '<div class=\"or-gec-hata\">Hata: ' + htmlEscape(d.hata || 'bilinmeyen') + '</div>';
        return;
      }
      tabloRender(d);
    })
    .catch(function(e) {
      state.yukleniyor = false;
      el('orgec-icerik').innerHTML = '<div class=\"or-gec-hata\">Baglanti hatasi: ' + htmlEscape(e.message) + '</div>';
    });
  }

  // ----- TABLO RENDER -----
  function tabloRender(d) {
    const sayfalama   = d.sayfalama   || {};
    const tipDagilim  = d.tip_dagilimi || {};
    const kpi         = d.kpi || {};
    const satirlar    = d.satirlar || [];

    let html = '';
    html += '<div class=\"or-gec-tablo-kabi\">';
    html += '<div class=\"or-gec-tablo-scroll\">';
    html += '<table class=\"or-gec-tablo\"><thead><tr>';
    html += '<th>Tarih</th><th>Saat</th><th>Makine</th><th>Istasyon</th>';
    html += '<th>Operator</th><th>Vardiya</th><th>Kalip</th><th>Tip</th>';
    html += '<th class=\"sag\">Tur</th><th class=\"sag\">Teorik</th>';
    html += '<th class=\"sag\">Net</th><th class=\"sag\">Fire</th>';
    html += '<th class=\"sag\">Verim %</th>';
    html += '<th class=\"sag\">Ariza</th><th class=\"sag\">Kalip Dgs</th>';
    html += '<th class=\"ort\">Durum</th><th>Sebep / Not</th><th class=\"ort\">Foto</th>';
    html += '</tr></thead><tbody>';

    if (satirlar.length === 0) {
      html += '<tr><td colspan=\"18\" class=\"or-gec-bos\">Bu tarih araliginda kayit bulunamadi</td></tr>';
    } else {
      satirlar.forEach(function(s) {
        html += satirHtml(s);
      });
    }
    html += '</tbody></table></div>';

    // Pagination + footer
    const tk = sayfalama.toplam_kayit || 0;
    const ts = sayfalama.toplam_sayfa || 0;
    const sf = sayfalama.sayfa || 1;
    html += '<div class=\"or-gec-tablo-alt\">';
    html += '<span>Toplam <strong>' + sayiFmt(tk) + '</strong> kayit';
    html += '<span class=\"or-gec-dagilim\">(';
    html += (tipDagilim.tur||0) + ' tur . ' + (tipDagilim.ariza||0) + ' ariza . ' + (tipDagilim.setup||0) + ' kalip dgs';
    html += ')</span></span>';
    html += pageHtml(sf, ts);
    html += '</div></div>';

    // KPI serit
    html += '<div class=\"or-gec-kpi-serit\">';
    html += kpiHtml('Toplam tur',   sayiFmt(kpi.toplam_tur),  '');
    html += kpiHtml('Teorik cift',  sayiFmt(kpi.teorik_cift), '');
    html += kpiHtml('Net cift',     sayiFmt(kpi.net_cift),    'success');
    html += kpiHtml('Fire',         sayiFmt(kpi.fire),        'danger');
    html += kpiHtml('Ort. verim',   (kpi.ortalama_verim_yuzde||0) + '%', '');
    html += kpiHtml('Ariza',        kpi.toplam_ariza_hhmmss || '00:00:00', '');
    html += kpiHtml('Kalip dgs',    kpi.toplam_kalip_degisim_hhmmss || '00:00:00', '');
    html += '</div>';

    // Export placeholder
    html += '<div class=\"or-gec-export\">';
    html += '<button disabled title=\"Yakinda\">Excel indir</button>';
    html += '<button disabled title=\"Yakinda\">PDF indir</button>';
    html += '<button disabled title=\"Yakinda\">Yazdir</button>';
    html += '</div>';

    el('orgec-icerik').innerHTML = html;
    pageEventBaglan();
  }

  // ----- SATIR HTML -----
  function satirHtml(s) {
    const durum   = s.durum_label || s.durum || '-';
    const pillCls = 'or-gec-pill or-gec-pill-' + durum.toLowerCase();
    const kalip   = s.kalip || {};
    const tipi    = kalip.tipi || '';
    const tipPill = tipi ? '<span class=\"or-gec-pill ' + (tipi==='GOVDE'?'or-gec-tip-govde':'or-gec-tip-atki') + '\">' + htmlEscape(tipi) + '</span>' : '<span class=\"bos\">-</span>';

    let kalipKolon;
    if (kalip.kod_eski) {
      kalipKolon = '<span class=\"or-gec-kalip-eski\">' + htmlEscape(kalip.kod_eski) + '</span><span class=\"or-gec-kalip-yon\">&rarr;</span><strong>' + htmlEscape(kalip.kod || '-') + '</strong>';
    } else if (kalip.kod) {
      kalipKolon = htmlEscape(kalip.kod);
    } else {
      kalipKolon = '<span class=\"bos\">-</span>';
    }

    const vrd = VARDIYA_GOSTER[s.vardiya] || s.vardiya || '-';
    const ist = s.istasyon || '<span class=\"bos\">-</span>';
    const op  = s.operator || '-';
    const not = s.gosterim_not || '-';
    const anomaliCls = s.anomali_seviye ? 'or-gec-anomali-' + s.anomali_seviye : '';

    function num(v) { return (v === null || v === undefined) ? '<span class=\"bos\">-</span>' : sayiFmt(v); }
    function sure(v) { return v ? v : '<span class=\"bos\">-</span>'; }

    const fotoIko = s.foto_var ? '<span title=\"Foto var\">[F]</span>' : '<span class=\"bos\" title=\"Foto yok\">-</span>';

    let html = '<tr>';
    html += '<td>' + htmlEscape(s.tarih || '-') + '</td>';
    html += '<td>' + htmlEscape(s.saat_araligi || '-') + '</td>';
    html += '<td class=\"makine\">' + htmlEscape(s.makine || '-') + '</td>';
    html += '<td>' + (s.istasyon ? htmlEscape(s.istasyon) : '<span class=\"bos\">-</span>') + '</td>';
    html += '<td>' + htmlEscape(op) + '</td>';
    html += '<td>' + htmlEscape(vrd) + '</td>';
    html += '<td>' + kalipKolon + '</td>';
    html += '<td>' + tipPill + '</td>';
    html += '<td class=\"sag\">' + num(s.tur) + '</td>';
    html += '<td class=\"sag\">' + num(s.teorik_cift) + '</td>';
    html += '<td class=\"sag\">' + num(s.net_cift) + '</td>';
    html += '<td class=\"sag fire\">' + num(s.fire) + '</td>';
    html += '<td class=\"sag verim\">' + (s.verim_yuzde !== null && s.verim_yuzde !== undefined ? s.verim_yuzde : '<span class=\"bos\">-</span>') + '</td>';
    html += '<td class=\"sag ' + anomaliCls + '\">' + sure(s.ariza_hhmmss) + '</td>';
    html += '<td class=\"sag ' + anomaliCls + '\">' + sure(s.kalip_degisim_hhmmss) + '</td>';
    html += '<td class=\"ort\"><span class=\"' + pillCls + '\">' + htmlEscape(durum) + '</span></td>';
    html += '<td>' + htmlEscape(not) + '</td>';
    html += '<td class=\"ort\">' + fotoIko + '</td>';
    html += '</tr>';
    return html;
  }

  // ----- KPI / PAGINATION HTML -----
  function kpiHtml(lbl, val, tone) {
    return '<div class=\"or-gec-kpi\"><div class=\"or-gec-kpi-lbl\">' + lbl + '</div><div class=\"or-gec-kpi-val ' + (tone||'') + '\">' + val + '</div></div>';
  }

  function pageHtml(sayfa, toplam) {
    if (toplam <= 1) return '<div class=\"or-gec-pgn\"></div>';
    let h = '<div class=\"or-gec-pgn\">';
    h += '<button data-pgn=\"prev\"' + (sayfa<=1?' disabled':'') + '>&lt;</button>';
    const maxBtn = 5;
    let bas = Math.max(1, sayfa - 2);
    let bit = Math.min(toplam, bas + maxBtn - 1);
    if (bit - bas < maxBtn - 1) bas = Math.max(1, bit - maxBtn + 1);
    for (let i = bas; i <= bit; i++) {
      h += '<button data-pgn=\"' + i + '\"' + (i===sayfa?' class=\"aktif\"':'') + '>' + i + '</button>';
    }
    if (bit < toplam) {
      h += '<span style=\"color:#9ca3af;padding:0 4px;\">...</span>';
      h += '<button data-pgn=\"' + toplam + '\">' + toplam + '</button>';
    }
    h += '<button data-pgn=\"next\"' + (sayfa>=toplam?' disabled':'') + '>&gt;</button>';
    h += '<select id=\"orgec-boyut-sec\">';
    [50, 100, 250].forEach(function(b) {
      h += '<option value=\"' + b + '\"' + (b===state.boyut?' selected':'') + '>' + b + '/sayfa</option>';
    });
    h += '</select>';
    h += '</div>';
    return h;
  }

  function pageEventBaglan() {
    document.querySelectorAll('.or-gec-pgn button[data-pgn]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        const v = btn.dataset.pgn;
        if (v === 'prev') state.sayfa = Math.max(1, state.sayfa - 1);
        else if (v === 'next') state.sayfa = state.sayfa + 1;
        else state.sayfa = parseInt(v, 10);
        veriCek();
      });
    });
    const ss = el('orgec-boyut-sec');
    if (ss) ss.addEventListener('change', function() {
      state.boyut = parseInt(ss.value, 10);
      state.sayfa = 1;
      veriCek();
    });
  }

  // ----- SEKME SWITCH -----
  function sekmeAktifEt(hangi) {
    document.querySelectorAll('.or-sekme').forEach(function(s) {
      s.classList.toggle('aktif', s.dataset.sekme === hangi);
    });
    const canli  = document.querySelector('.or-sayfa');
    const gecmis = document.querySelector('.or-gec-sayfa');
    if (hangi === 'canli') {
      if (canli)  canli.style.display = '';
      if (gecmis) gecmis.classList.remove('aktif');
    } else if (hangi === 'gecmis') {
      if (canli)  canli.style.display = 'none';
      if (gecmis) gecmis.classList.add('aktif');
      if (state.ilkYukleme) {
        state.ilkYukleme = false;
        tarihAraligiUygula('bugun');
        veriCek();
      }
    }
  }

  // ----- INIT -----
  function init() {
    document.querySelectorAll('.or-sekme').forEach(function(s) {
      s.addEventListener('click', function() { sekmeAktifEt(s.dataset.sekme); });
    });
    document.querySelectorAll('.or-gec-tarih-btn').forEach(function(b) {
      b.addEventListener('click', function() { tarihAraligiUygula(b.dataset.preset); });
    });
    const btnFiltrele = el('orgec-btn-filtrele');
    if (btnFiltrele) btnFiltrele.addEventListener('click', function() {
      state.sayfa = 1; veriCek();
    });
    const btnTemizle = el('orgec-btn-temizle');
    if (btnTemizle) btnTemizle.addEventListener('click', function() {
      el('orgec-makine').value = '';
      el('orgec-operator').value = '';
      el('orgec-kalip-tipi').value = '';
      el('orgec-vardiya').value = '';
      el('orgec-durum').value = '';
      el('orgec-arama').value = '';
      tarihAraligiUygula('bugun');
      state.sayfa = 1;
      veriCek();
    });
    tarihAraligiUygula('bugun');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
