(function (global) {
  'use strict';

  var backdrop = document.getElementById('atpLocModalBackdrop');
  var baseModal = document.getElementById('atpBaseModal');
  var konumModal = document.getElementById('atpKonumModal');
  var parseErrEl = document.getElementById('atpKonumParseErr');
  var masterChoiceEl = document.getElementById('atpKonumMasterChoice');
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

  function parseCoordsFromForm(mapsEl, latEl, lngEl) {
    var maps = (mapsEl.value || '').trim();
    var lat = latEl.value.trim();
    var lng = lngEl.value.trim();
    if (lat && lng) {
      return { lat: parseFloat(lat), lng: parseFloat(lng), err: null };
    }
    if (!maps) return { lat: null, lng: null, err: 'Koordinat veya Google Maps linki gerekli.' };
    var patterns = [
      /@(-?\d+\.\d+),(-?\d+\.\d+)/,
      /[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)/,
      /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/
    ];
    for (var i = 0; i < patterns.length; i++) {
      var m = maps.match(patterns[i]);
      if (m) return { lat: parseFloat(m[1]), lng: parseFloat(m[2]), err: null };
    }
    return { lat: null, lng: null, err: 'Bu bağlantıdan koordinat okunamadı.' };
  }

  function openBaseModal(existing) {
    existing = existing || {};
    document.getElementById('atpBaseName').value = existing.base_name || '';
    document.getElementById('atpBaseAddress').value = existing.base_address || '';
    document.getElementById('atpBaseMaps').value = existing.base_maps_url || '';
    document.getElementById('atpBaseLat').value = existing.latitude != null ? String(existing.latitude) : '';
    document.getElementById('atpBaseLng').value = existing.longitude != null ? String(existing.longitude) : '';
    document.getElementById('atpBaseParseErr').textContent = '';
    if (baseModal) baseModal.hidden = false;
    openBackdrop();
  }

  function openKonumModal(task, cb) {
    onSavedCallback = cb || null;
    document.getElementById('atpKonumFirma').textContent = task.company_name || '—';
    document.getElementById('atpKonumAdres').value = task.address_text || '';
    document.getElementById('atpKonumMaps').value = task.location_url || '';
    document.getElementById('atpKonumLat').value = '';
    document.getElementById('atpKonumLng').value = '';
    document.getElementById('atpKonumTalepId').value = task.is_talebi_id || '';
    document.getElementById('atpKonumMasterId').value = task.kayitli_yer_id || '';
    if (parseErrEl) parseErrEl.textContent = '';
    if (masterChoiceEl) {
      masterChoiceEl.hidden = !task.kayitli_yer_id;
      document.querySelectorAll('input[name="atpKonumScope"]').forEach(function (r) {
        r.checked = r.value === 'request_only';
      });
    }
    if (konumModal) konumModal.hidden = false;
    openBackdrop();
  }

  var baseBtn = document.getElementById('atpBtnBaseLocation');
  if (baseBtn) {
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
      var parsed = parseCoordsFromForm(
        document.getElementById('atpBaseMaps'),
        document.getElementById('atpBaseLat'),
        document.getElementById('atpBaseLng')
      );
      if (parsed.err) {
        if (errEl) errEl.textContent = parsed.err;
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
          base_maps_url: document.getElementById('atpBaseMaps').value.trim(),
          base_latitude: parsed.lat,
          base_longitude: parsed.lng
        })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (!j.ok) {
          if (errEl) errEl.textContent = j.error || 'Kaydedilemedi';
          return;
        }
        closeBackdrop();
        toast('Başlangıç noktası kaydedildi');
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
      var parsed = parseCoordsFromForm(
        document.getElementById('atpKonumMaps'),
        document.getElementById('atpKonumLat'),
        document.getElementById('atpKonumLng')
      );
      if (parsed.err) {
        if (parseErrEl) parseErrEl.textContent = parsed.err;
        return;
      }
      if (parseErrEl) parseErrEl.textContent = '';
      var scopeEl = document.querySelector('input[name="atpKonumScope"]:checked');
      var scope = scopeEl ? scopeEl.value : 'request_only';
    var root = document.getElementById('atpRoot');
    var planDate = root ? root.getAttribute('data-date') : '';
    var vid = document.getElementById('atpSelVehicle');
    var vehicleId = (vid && vid.value) ? vid.value : (new URLSearchParams(window.location.search).get('vehicle_id') || null);
      fetch('/planlama/arac-takip/api/plan-items/konum', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          is_talebi_id: document.getElementById('atpKonumTalepId').value,
          kayitli_yer_id: document.getElementById('atpKonumMasterId').value || null,
          scope: scope,
          maps_url: document.getElementById('atpKonumMaps').value.trim(),
          latitude: parsed.lat,
          longitude: parsed.lng,
        date: planDate,
        vehicle_id: vehicleId
        })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (!j.ok) {
          if (parseErrEl) parseErrEl.textContent = j.error || 'Kaydedilemedi';
          return;
        }
        closeBackdrop();
        toast('Konum kaydedildi');
        if (onSavedCallback) onSavedCallback(j);
      }).catch(function () { toast('Konum kaydedilemedi'); });
    });
  }

  global.AtpLocationModals = {
    openBaseModal: openBaseModal,
    openKonumModal: openKonumModal,
    close: closeBackdrop
  };
})(window);
