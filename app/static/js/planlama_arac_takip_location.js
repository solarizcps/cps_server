(function (global) {
  'use strict';

  var backdrop = document.getElementById('atpLocModalBackdrop');
  var baseModal = document.getElementById('atpBaseModal');
  var konumModal = document.getElementById('atpKonumModal');
  var parseErrEl = document.getElementById('atpKonumParseErr');
  var onSavedCallback = null;

  function toast(msg) {
    var el = document.getElementById('atpToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 3200);
  }

  function openBackdrop() {
    if (backdrop) {
      backdrop.classList.add('open');
      backdrop.setAttribute('aria-hidden', 'false');
    }
  }

  function closeBackdrop() {
    if (backdrop) {
      backdrop.classList.remove('open');
      backdrop.setAttribute('aria-hidden', 'true');
    }
    if (baseModal) baseModal.hidden = true;
    if (konumModal) konumModal.hidden = true;
  }

  function openBaseModal(existing) {
    existing = existing || {};
    document.getElementById('atpBaseName').value = existing.base_name || '';
    document.getElementById('atpBaseAddress').value = existing.base_address || '';
    document.getElementById('atpBaseMaps').value = existing.base_maps_url || '';
    document.getElementById('atpBaseLat').value = '';
    document.getElementById('atpBaseLng').value = '';
    document.getElementById('atpBaseParseErr').textContent = '';
    if (baseModal) baseModal.hidden = false;
    openBackdrop();
  }

  function openKonumModal(task, cb) {
    onSavedCallback = cb || null;
    document.getElementById('atpKonumFirma').textContent = task.company_name || '—';
    document.getElementById('atpKonumAdres').textContent = task.address_text || '—';
    document.getElementById('atpKonumMaps').value = task.location_url || '';
    document.getElementById('atpKonumTalepId').value = task.is_talebi_id || '';
    if (parseErrEl) parseErrEl.textContent = '';
    if (konumModal) konumModal.hidden = false;
    openBackdrop();
    var mapsInp = document.getElementById('atpKonumMaps');
    if (mapsInp) mapsInp.focus();
  }

  var baseBtn = document.getElementById('atpBtnBaseLocation');
  if (baseBtn && baseModal && document.getElementById('atpBaseName')) {
    baseBtn.addEventListener('click', function () {
      var dashEl = document.getElementById('atpDashboardJson');
      var dash = dashEl ? JSON.parse(dashEl.textContent) : {};
      openBaseModal(dash.base_location || {});
    });
  }

  var baseClose = document.getElementById('atpBaseModalClose');
  if (baseClose) baseClose.addEventListener('click', closeBackdrop);
  var baseCancel = document.getElementById('atpBaseModalCancel');
  if (baseCancel) baseCancel.addEventListener('click', closeBackdrop);
  var konumClose = document.getElementById('atpKonumModalClose');
  if (konumClose) konumClose.addEventListener('click', closeBackdrop);
  var konumCancel = document.getElementById('atpKonumModalCancel');
  if (konumCancel) konumCancel.addEventListener('click', closeBackdrop);
  if (backdrop) {
    backdrop.addEventListener('click', function (e) {
      if (e.target === backdrop) closeBackdrop();
    });
  }

  var baseForm = document.getElementById('atpBaseForm');
  if (baseForm) {
    baseForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var errEl = document.getElementById('atpBaseParseErr');
      var mapsUrl = document.getElementById('atpBaseMaps').value.trim();
      if (!mapsUrl) {
        if (errEl) errEl.textContent = 'Google Maps konum linki gerekli.';
        return;
      }
      if (errEl) errEl.textContent = '';
      fetch('/planlama/arac-takip/api/operasyon/base', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base_name: document.getElementById('atpBaseName').value.trim(),
          base_address: document.getElementById('atpBaseAddress').value.trim(),
          base_maps_url: mapsUrl
        })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (!j.ok) {
          if (errEl) errEl.textContent = j.error || 'Kaydedilemedi';
          return;
        }
        closeBackdrop();
        toast('Fabrika başlangıç noktası kaydedildi');
        if (onSavedCallback) onSavedCallback(j);
        else if (j.base && window.AtpPlanMap && typeof window.applyAtpDashboard === 'function') {
          window.applyAtpDashboard({ base_location: j.base, plan_map: { base: j.base } });
        } else window.location.reload();
      }).catch(function () { toast('Başlangıç noktası kaydedilemedi'); });
    });
  }

  var konumForm = document.getElementById('atpKonumForm');
  if (konumForm) {
    konumForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var mapsUrl = document.getElementById('atpKonumMaps').value.trim();
      if (!mapsUrl) {
        if (parseErrEl) parseErrEl.textContent = 'Google Maps bağlantısı gerekli.';
        return;
      }
      if (parseErrEl) parseErrEl.textContent = '';
      var root = document.getElementById('atpRoot');
      var planDate = root ? root.getAttribute('data-date') : '';
      var vid = document.getElementById('atpSelVehicle');
      var vehicleId = (vid && vid.value) ? vid.value : (new URLSearchParams(window.location.search).get('vehicle_id') || null);
      var saveBtn = konumForm.querySelector('button[type="submit"]');
      if (saveBtn) saveBtn.disabled = true;
      fetch('/planlama/arac-takip/api/plan-items/konum', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          is_talebi_id: document.getElementById('atpKonumTalepId').value,
          maps_url: mapsUrl,
          date: planDate,
          vehicle_id: vehicleId
        })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (saveBtn) saveBtn.disabled = false;
        if (!j.ok) {
          if (parseErrEl) parseErrEl.textContent = j.error || 'Kaydedilemedi';
          return;
        }
        closeBackdrop();
        toast('Konum kaydedildi');
        if (onSavedCallback) onSavedCallback(j);
      }).catch(function () {
        if (saveBtn) saveBtn.disabled = false;
        toast('Konum kaydedilemedi');
      });
    });
  }

  global.AtpLocationModals = {
    openBaseModal: openBaseModal,
    openKonumModal: openKonumModal,
    close: closeBackdrop
  };
})(window);
