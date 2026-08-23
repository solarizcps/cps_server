(function () {
  'use strict';

  var dashEl = document.getElementById('atpDashboardJson');
  var dashboard = dashEl ? JSON.parse(dashEl.textContent) : {};
  var activeTalep = null;

  function toast(msg) {
    var el = document.getElementById('atpToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 3200);
  }

  function fmtDist(km) {
    if (km == null || km === '' || km === '—') return '—';
    return km + ' km';
  }

  window.AtpFmtDist = fmtDist;

  var poolToggle = document.getElementById('atpPoolToggle');
  if (poolToggle) {
    poolToggle.addEventListener('click', function () {
      var body = document.getElementById('atpPoolBody');
      var lbl = document.getElementById('atpPoolCollapseLbl');
      var open = body && !body.classList.contains('atp-pool-collapsed');
      if (body) body.classList.toggle('atp-pool-collapsed', open);
      poolToggle.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (lbl) lbl.textContent = open ? 'Genişlet' : 'Daralt';
    });
  }

  function renderPoolRows(rows) {
    var tbody = document.getElementById('atpPoolBodyRows');
    var badge = document.getElementById('atpPoolBadge');
    if (badge) badge.textContent = String(rows.length);
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr class="atp-pool-empty"><td colspan="8">Bekleyen talep yok.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(function (t) {
      var pri = t.oncelik === 'YUKSEK' ? 'yuksek' : (t.oncelik === 'ACIL' ? 'acil' : (t.oncelik === 'DUSUK' ? 'dusuk' : 'normal'));
      var no = t.talep_no || ('#' + t.id);
      return '<tr data-talep-id="' + t.id + '"' + (t.urun_ozet ? ' title="' + t.urun_ozet + '"' : '') + '>' +
        '<td class="atp-pool-no">' + no + '</td><td>' + (t.firma || '—') + '</td><td>' + (t.is || '—') + '</td>' +
        '<td>' + (t.sofor || t.sofor_adi_snapshot || '—') + '</td>' +
        '<td>' + (t.is_turu_label || '—') + '</td>' +
        '<td>' + (t.istenen_saat || '—') + '</td>' +
        '<td><span class="atp-badge atp-pri-' + pri + '">' + (t.oncelik_label || t.oncelik) + '</span></td>' +
        '<td><button type="button" class="atp-btn atp-btn-sm atp-btn-plana-al" data-talep-id="' + t.id + '">Plana Al</button></td></tr>';
    }).join('');
    bindPlanaAl();
  }

  function refreshPool() {
    fetch('/planlama/arac-takip/api/talepler/bekleyen', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j.ok) renderPoolRows(j.talepler || []); });
  }

  function bindPlanaAl() {
    document.querySelectorAll('.atp-btn-plana-al').forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute('data-talep-id');
        fetch('/planlama/arac-takip/api/talepler/bekleyen', { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            var t = (j.talepler || []).find(function (x) { return String(x.id) === String(id); });
            if (t) openPlanModal(t);
          });
      };
    });
  }
  bindPlanaAl();

  var planModal = document.getElementById('atpPlanModal');
  var planBackdrop = document.getElementById('atpPlanModalBackdrop');

  function openPlanModal(talep) {
    activeTalep = talep;
    document.getElementById('atpPlanTalepId').value = talep.id;
    document.getElementById('atpPlanTarih').value = talep.tarih || dashboard.date;
    document.getElementById('atpPlanSummary').innerHTML =
      '<strong>' + (talep.firma || '') + '</strong><br>' +
      (talep.is || '') + '<br>Adres: ' + (talep.adres || '—') + '<br>' +
      'Talep Eden: ' + (talep.talep_eden_adi || '—') + '<br>Öncelik: ' + (talep.oncelik_label || talep.oncelik);
    var saatEl = document.getElementById('atpPlanSaat');
    var saatDisp = document.getElementById('atpPlanTimeDisplay');
    if (saatEl) saatEl.value = talep.istenen_saat || '';
    if (saatDisp) {
      saatDisp.textContent = talep.istenen_saat || 'Saat seç';
      saatDisp.classList.toggle('is-placeholder', !talep.istenen_saat);
    }
    fillPlanArac();
    fillPlanSofor();
    planModal.classList.add('open');
    planBackdrop.classList.add('open');
  }

  function closePlanModal() {
    planModal.classList.remove('open');
    planBackdrop.classList.remove('open');
    activeTalep = null;
  }

  document.getElementById('atpPlanModalClose').addEventListener('click', closePlanModal);
  document.getElementById('atpPlanCancel').addEventListener('click', closePlanModal);
  planBackdrop.addEventListener('click', function (e) {
    if (e.target === planBackdrop) closePlanModal();
  });

  function fillPlanArac() {
    var sel = document.getElementById('atpPlanArac');
    if (!sel) return;
    sel.innerHTML = '<option value="">Yükleniyor…</option>';
    fetch('/planlama/arac-takip/api/araclar', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var veh = (j && j.vehicles) || [];
        sel.innerHTML = '<option value="">— Araç seç —</option>' + veh.map(function (v) {
          return '<option value="' + v.id + '" data-plate="' + (v.plate_display || v.plate || '') + '">' +
            (v.plate_display || v.plate || v.id) + '</option>';
        }).join('');
      });
  }

  function fillPlanSofor() {
    var sel = document.getElementById('atpPlanSofor');
    if (!sel) return;
    var drivers = dashboard.drivers || [];
    sel.innerHTML = '<option value="">—</option>' + drivers.map(function (d) {
      return '<option value="' + d.id + '">' + d.ad + '</option>';
    }).join('');
  }

  document.getElementById('atpPlanForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var aracSel = document.getElementById('atpPlanArac');
    var soforSel = document.getElementById('atpPlanSofor');
    if (!aracSel.value) { toast('Araç seçin'); return; }
    var opt = aracSel.options[aracSel.selectedIndex];
    var payload = {
      talep_id: document.getElementById('atpPlanTalepId').value,
      plan_tarihi: document.getElementById('atpPlanTarih').value,
      arac_external_id: aracSel.value,
      arac_plaka: opt.getAttribute('data-plate') || opt.textContent,
      sofor_id: soforSel.value || null,
      sofor_adi: soforSel.value ? soforSel.options[soforSel.selectedIndex].textContent : null,
      planlanan_saat: document.getElementById('atpPlanSaat').value || null,
      sira: document.getElementById('atpPlanSira').value || null,
    };
    fetch('/planlama/arac-takip/api/talepler/plana-al', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        if (res.body.ok) {
          toast('İş plana alındı');
          closePlanModal();
          refreshPool();
          var vid = aracSel.value;
          var d = document.getElementById('atpPlanTarih').value;
          window.location.href = '/planlama/arac-takip/?tab=gunluk&date=' + encodeURIComponent(d) +
            '&vehicle_id=' + encodeURIComponent(vid);
        } else {
          toast(res.body.error || 'Plana alınamadı');
        }
      }).catch(function () { toast('Plana alınamadı'); });
  });

  window.AtpPool = { refresh: refreshPool };
})();
