(function () {
  'use strict';

  var modal = document.getElementById('atpRequestModal');
  var backdrop = document.getElementById('atpModalBackdrop');
  var form = document.getElementById('atpRequestForm');
  if (!modal || !backdrop || !form) return;

  var searchInput = document.getElementById('atpLocSearch');
  var dropdown = document.getElementById('atpLocDropdown');
  var locCard = document.getElementById('atpLocCard');
  var newPanel = document.getElementById('atpLocNewPanel');
  var masterIdEl = document.getElementById('atpLocMasterId');
  var newLocErr = document.getElementById('atpNewLocErr');
  var searchTimer = null;
  var userSearchTimer = null;
  var selectedLoc = null;
  var newLocSaved = false;
  var reqMode = 'own';
  var suggestionsCache = { recent: [], frequent: [] };
  var currentUser = { id: 0, display_name: '—' };
  var userEl = document.getElementById('atpCurrentUserJson');
  if (userEl) {
    try { currentUser = JSON.parse(userEl.textContent); } catch (e) { /* keep default */ }
  }
  var talepEdenInput = document.getElementById('atpReqTalepEden');
  var talepEdenUserIdEl = document.getElementById('atpReqTalepEdenUserId');
  var otherUserWrap = document.getElementById('atpOtherUserWrap');
  var otherUserSearch = document.getElementById('atpOtherUserSearch');
  var userDropdown = document.getElementById('atpUserDropdown');

  function toast(msg) {
    var el = document.getElementById('atpToast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 3200);
  }

  function setRequesterOwn() {
    reqMode = 'own';
    if (talepEdenInput) talepEdenInput.value = currentUser.display_name || '—';
    if (talepEdenUserIdEl) talepEdenUserIdEl.value = String(currentUser.id || '');
    if (otherUserWrap) otherUserWrap.hidden = true;
    if (otherUserSearch) otherUserSearch.value = '';
    hideUserDropdown();
    document.querySelectorAll('.atp-req-mode-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-mode') === 'own');
    });
  }

  function setRequesterOther() {
    reqMode = 'other';
    if (otherUserWrap) otherUserWrap.hidden = false;
    document.querySelectorAll('.atp-req-mode-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-mode') === 'other');
    });
    setTimeout(function () { if (otherUserSearch) otherUserSearch.focus(); }, 80);
    runUserSearch('');
  }

  function hideUserDropdown() {
    if (!userDropdown) return;
    userDropdown.hidden = true;
    userDropdown.innerHTML = '';
  }

  function selectRequesterUser(user) {
    if (!user) return;
    if (talepEdenInput) talepEdenInput.value = user.display_name || '—';
    if (talepEdenUserIdEl) talepEdenUserIdEl.value = String(user.id || '');
    if (otherUserSearch) otherUserSearch.value = user.display_name || '';
    hideUserDropdown();
  }

  function showUserDropdown(users) {
    if (!userDropdown) return;
    if (!users || !users.length) {
      userDropdown.innerHTML = '<div class="atp-loc-dd-section">Kullanıcı bulunamadı</div>';
      userDropdown.hidden = false;
      return;
    }
    userDropdown.innerHTML = users.map(function (u) {
      return '<button type="button" class="atp-user-dd-item" data-user-id="' + u.id + '" data-user-name="' +
        (u.display_name || '').replace(/"/g, '&quot;') + '">' + (u.display_name || '—') + '</button>';
    }).join('');
    userDropdown.hidden = false;
    userDropdown.querySelectorAll('.atp-user-dd-item').forEach(function (btn) {
      btn.addEventListener('click', function () {
        selectRequesterUser({
          id: parseInt(btn.getAttribute('data-user-id'), 10),
          display_name: btn.getAttribute('data-user-name') || btn.textContent,
        });
      });
    });
  }

  function runUserSearch(q) {
    fetch('/planlama/arac-takip/api/users/search?q=' + encodeURIComponent(q || ''), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) { showUserDropdown(j.results || []); })
      .catch(function () { hideUserDropdown(); });
  }

  document.querySelectorAll('.atp-req-mode-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (btn.getAttribute('data-mode') === 'other') setRequesterOther();
      else setRequesterOwn();
    });
  });

  if (otherUserSearch) {
    otherUserSearch.addEventListener('focus', function () { runUserSearch(otherUserSearch.value.trim()); });
    otherUserSearch.addEventListener('input', function () {
      clearTimeout(userSearchTimer);
      userSearchTimer = setTimeout(function () { runUserSearch(otherUserSearch.value.trim()); }, 200);
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.atp-user-search-wrap')) hideUserDropdown();
  });

  var timeTrigger = document.getElementById('atpTimeTrigger');
  var timeDisplay = document.getElementById('atpTimeDisplay');
  var timeHidden = document.getElementById('atpReqSaat');
  var timeDropdown = document.getElementById('atpTimeDropdown');
  var timeSlotsEl = document.getElementById('atpTimeSlots');
  var timeCustomBtn = document.getElementById('atpTimeCustomBtn');
  var timeCustomPanel = document.getElementById('atpTimeCustomPanel');
  var timeCustomInput = document.getElementById('atpTimeCustomInput');
  var timeCustomApply = document.getElementById('atpTimeCustomApply');
  var timePickerOpen = false;

  function buildTimeSlots() {
    var slots = [];
    for (var h = 8; h <= 18; h++) {
      slots.push(String(h).padStart(2, '0') + ':00');
      if (h < 18) slots.push(String(h).padStart(2, '0') + ':30');
    }
    return slots;
  }

  function renderTimeSlots() {
    if (!timeSlotsEl) return;
    timeSlotsEl.innerHTML = buildTimeSlots().map(function (t) {
      return '<button type="button" class="atp-time-opt" data-time="' + t + '" role="option">' + t + '</button>';
    }).join('');
    timeSlotsEl.querySelectorAll('.atp-time-opt').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setTimeValue(btn.getAttribute('data-time'));
        closeTimeDropdown();
      });
    });
  }

  function updateTimeDisplay(value) {
    if (!timeDisplay) return;
    if (value) {
      timeDisplay.textContent = value;
      timeDisplay.classList.remove('is-placeholder');
    } else {
      timeDisplay.textContent = 'Saat seç';
      timeDisplay.classList.add('is-placeholder');
    }
  }

  function setTimeValue(value) {
    var v = (value || '').trim();
    if (timeHidden) timeHidden.value = v;
    updateTimeDisplay(v);
    if (timeCustomPanel) timeCustomPanel.hidden = true;
    if (timeCustomInput) timeCustomInput.value = '';
  }

  function openTimeDropdown() {
    if (!timeDropdown || !timeTrigger) return;
    timeDropdown.hidden = false;
    timeTrigger.setAttribute('aria-expanded', 'true');
    timePickerOpen = true;
    if (timeCustomPanel) timeCustomPanel.hidden = true;
  }

  function closeTimeDropdown() {
    if (!timeDropdown || !timeTrigger) return;
    timeDropdown.hidden = true;
    timeTrigger.setAttribute('aria-expanded', 'false');
    timePickerOpen = false;
    if (timeCustomPanel) timeCustomPanel.hidden = true;
  }

  function resetTimePicker() {
    setTimeValue('');
    closeTimeDropdown();
  }

  function parseCustomTime(raw) {
    var s = (raw || '').trim();
    var m = s.match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    var hh = parseInt(m[1], 10);
    var mm = parseInt(m[2], 10);
    if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
    return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
  }

  renderTimeSlots();

  if (timeTrigger) {
    timeTrigger.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (timePickerOpen) closeTimeDropdown();
      else openTimeDropdown();
    });
  }

  if (timeCustomBtn) {
    timeCustomBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (timeCustomPanel) {
        timeCustomPanel.hidden = false;
        setTimeout(function () { if (timeCustomInput) timeCustomInput.focus(); }, 50);
      }
    });
  }

  if (timeCustomApply) {
    timeCustomApply.addEventListener('click', function (e) {
      e.preventDefault();
      var parsed = parseCustomTime(timeCustomInput ? timeCustomInput.value : '');
      if (!parsed) {
        toast('Geçerli saat girin (HH:MM)');
        return;
      }
      setTimeValue(parsed);
      closeTimeDropdown();
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.atp-time-picker')) closeTimeDropdown();
  });

  function todayStr() {
    return new Date().toISOString().slice(0, 10);
  }

  function locBadge(hasLoc) {
    if (hasLoc) return '<span class="atp-loc-badge saved">Kayıtlı Konum</span>';
    return '<span class="atp-loc-badge no">Konum yok</span>';
  }

  function showDropdown(html) {
    dropdown.innerHTML = html;
    dropdown.hidden = !html;
    dropdown.querySelectorAll('.atp-loc-dd-item').forEach(function (btn) {
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var payload = btn.getAttribute('data-loc-json');
        if (payload) {
          try { selectLocation(JSON.parse(decodeURIComponent(payload))); return; } catch (e) { /* fallthrough */ }
        }
      });
    });
  }

  function renderDropdownItems(items, sectionLabel) {
    if (!items || !items.length) return '';
    var html = '<div class="atp-loc-dd-section">' + sectionLabel + '</div>';
    items.forEach(function (loc) {
      var enc = encodeURIComponent(JSON.stringify(loc));
      html += '<button type="button" class="atp-loc-dd-item" data-loc-json="' + enc + '">' +
        '<strong>' + (loc.firma || '—') + '</strong>' +
        '<small>' + (loc.short_adres || loc.adres || '—') + ' ' + locBadge(loc.has_location) + '</small>' +
        '</button>';
    });
    return html;
  }

  function hideDropdown() {
    dropdown.hidden = true;
    dropdown.innerHTML = '';
  }

  function loadSuggestions() {
    return fetch('/planlama/arac-takip/api/locations/suggestions', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok) {
          suggestionsCache.recent = j.recent || [];
          suggestionsCache.frequent = j.frequent || [];
        }
        return j;
      })
      .catch(function () { return { ok: false, recent: [], frequent: [] }; });
  }

  function showSuggestionsDropdown() {
    var q = (searchInput.value || '').trim();
    if (!q) {
      fetch('/planlama/arac-takip/api/locations/search?q=', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var html = renderDropdownItems(suggestionsCache.recent, 'Son Kullanılanlar');
          html += renderDropdownItems(suggestionsCache.frequent, 'Sık Gidilenler');
          html += renderDropdownItems(j.results || [], 'Kayıtlı Yerler');
          showDropdown(html);
        });
      return;
    }
    runSearch(q);
  }

  function runSearch(q) {
    fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var html = renderDropdownItems(j.results || [], 'Arama Sonuçları');
        showDropdown(html);
      });
  }

  function renderLocCard(loc) {
    document.getElementById('atpLocCardFirma').textContent = loc.firma || '—';
    document.getElementById('atpLocCardAdres').textContent = loc.adres || '—';
    var hasLoc = loc.has_location || (loc.latitude != null && loc.longitude != null);
    document.getElementById('atpLocCardKonum').textContent = hasLoc ? '📍 Kayıtlı Konum' : '📍 Konum linki yok';
    var openBtn = document.getElementById('atpBtnOpenMap');
    openBtn.disabled = !(loc.maps_url || hasLoc);
    openBtn.onclick = function () {
      if (loc.maps_url) window.open(loc.maps_url, '_blank');
      else if (hasLoc) window.open('https://maps.google.com/?q=' + loc.latitude + ',' + loc.longitude, '_blank');
    };
    locCard.hidden = false;
    locCard.removeAttribute('hidden');
    newPanel.hidden = true;
    newLocSaved = true;
  }

  function selectLocation(loc) {
    selectedLoc = loc;
    newLocSaved = !!(loc && loc.has_location);
    masterIdEl.value = loc.id || '';
    searchInput.value = loc.firma || '';
    renderLocCard(loc);
    hideDropdown();
  }

  function openNewLocationPanel(prefill) {
    selectedLoc = null;
    newLocSaved = false;
    masterIdEl.value = '';
    locCard.hidden = true;
    newPanel.hidden = false;
    if (newLocErr) newLocErr.textContent = '';
    if (prefill) document.getElementById('atpNewFirma').value = prefill;
  }

  function resetLocationState() {
    selectedLoc = null;
    newLocSaved = false;
    searchInput.value = '';
    masterIdEl.value = '';
    locCard.hidden = true;
    newPanel.hidden = true;
    hideDropdown();
    document.getElementById('atpNewFirma').value = '';
    document.getElementById('atpNewAdres').value = '';
    document.getElementById('atpNewMaps').value = '';
    if (newLocErr) newLocErr.textContent = '';
  }

  function saveNewLocation(cb) {
    var firma = document.getElementById('atpNewFirma').value.trim();
    var adres = document.getElementById('atpNewAdres').value.trim();
    var maps = document.getElementById('atpNewMaps').value.trim();
    if (!firma) { if (newLocErr) newLocErr.textContent = 'Firma gerekli.'; return; }
    if (!adres) { if (newLocErr) newLocErr.textContent = 'Adres gerekli.'; return; }
    if (!maps) { if (newLocErr) newLocErr.textContent = 'Google Maps bağlantısı gerekli.'; return; }
    if (newLocErr) newLocErr.textContent = '';
    fetch('/planlama/arac-takip/api/locations/from-maps', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ firma: firma, adres: adres, maps_url: maps }),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok || !j.location) {
        if (newLocErr) newLocErr.textContent = j.error || 'Konum kaydedilemedi';
        return;
      }
      selectLocation(j.location);
      toast('Konum kaydedildi');
      if (cb) cb(j.location);
    }).catch(function () {
      if (newLocErr) newLocErr.textContent = 'Konum kaydedilemedi';
    });
  }

  function openModal() {
    document.getElementById('atpReqTarih').value = todayStr();
    resetTimePicker();
    setRequesterOwn();
    resetLocationState();
    loadSuggestions();
    modal.classList.add('open');
    backdrop.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    backdrop.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    setTimeout(function () { searchInput.focus(); }, 120);
  }

  function resetUxV2Fields() {
    var oktay = form.querySelector('input[name="sofor_secim"][value="OKTAY"]');
    if (oktay) oktay.checked = true;
    form.querySelectorAll('input[name="is_turu"]').forEach(function (el) { el.checked = false; });
    ['atpReqUrun', 'atpReqMiktar', 'atpReqEkNot'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
    var birim = document.getElementById('atpReqBirim');
    if (birim) birim.value = '';
    syncSoforOther();
  }

  function closeModal() {
    modal.classList.remove('open');
    backdrop.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    form.reset();
    setRequesterOwn();
    resetTimePicker();
    resetLocationState();
    resetUxV2Fields();
  }

  document.getElementById('atpBtnNewRequest').addEventListener('click', openModal);
  document.getElementById('atpModalClose').addEventListener('click', closeModal);
  document.getElementById('atpModalCancel').addEventListener('click', closeModal);
  backdrop.addEventListener('click', function (e) {
    if (e.target === backdrop) closeModal();
  });

  var newLocToggle = document.getElementById('atpBtnNewLocToggle');
  if (newLocToggle) {
    newLocToggle.addEventListener('click', function () {
      openNewLocationPanel(searchInput.value.trim());
    });
  }

  var mapsSearchBtn = document.getElementById('atpBtnMapsSearch');
  if (mapsSearchBtn) {
    mapsSearchBtn.addEventListener('click', function () {
      var firma = document.getElementById('atpNewFirma').value.trim();
      var adres = document.getElementById('atpNewAdres').value.trim();
      var q = [firma, adres].filter(Boolean).join(' ');
      if (!q) {
        toast('Önce firma ve adres girin');
        return;
      }
      window.open('https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(q), '_blank');
    });
  }

  var saveNewLocBtn = document.getElementById('atpBtnSaveNewLoc');
  if (saveNewLocBtn) {
    saveNewLocBtn.addEventListener('click', function () { saveNewLocation(); });
  }

  searchInput.addEventListener('focus', function () {
    loadSuggestions().then(function () {
      if (!searchInput.value.trim()) showSuggestionsDropdown();
    });
  });

  searchInput.addEventListener('input', function () {
    var q = searchInput.value.trim();
    clearTimeout(searchTimer);
    if (!q) {
      showSuggestionsDropdown();
      return;
    }
    searchTimer = setTimeout(function () { runSearch(q); }, 220);
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.atp-loc-search-wrap')) hideDropdown();
  });

  var soforOtherWrap = document.getElementById('atpSoforOtherWrap');
  var soforOtherName = document.getElementById('atpSoforOtherName');

  function syncSoforOther() {
    var diger = form.querySelector('input[name="sofor_secim"][value="DIGER"]');
    var show = diger && diger.checked;
    if (soforOtherWrap) soforOtherWrap.hidden = !show;
    if (!show && soforOtherName) soforOtherName.value = '';
  }

  form.querySelectorAll('input[name="sofor_secim"]').forEach(function (el) {
    el.addEventListener('change', syncSoforOther);
  });
  syncSoforOther();

  function readSoforSecim() {
    var checked = form.querySelector('input[name="sofor_secim"]:checked');
    return checked ? checked.value : 'OKTAY';
  }

  function readIsTuru() {
    var checked = form.querySelector('input[name="is_turu"]:checked');
    return checked ? checked.value : null;
  }

  function appendUxV2Fields(payload) {
    payload.sofor_secim = readSoforSecim();
    if (payload.sofor_secim === 'DIGER') {
      payload.sofor_adi = soforOtherName ? soforOtherName.value.trim() : '';
    }
    var isTuru = readIsTuru();
    if (isTuru) payload.is_turu = isTuru;
    var urunEl = document.getElementById('atpReqUrun');
    var miktarEl = document.getElementById('atpReqMiktar');
    var birimEl = document.getElementById('atpReqBirim');
    if (urunEl && urunEl.value.trim()) payload.urun_malzeme = urunEl.value.trim();
    if (miktarEl && miktarEl.value.trim()) payload.miktar = miktarEl.value.trim();
    if (birimEl && birimEl.value) payload.miktar_birim = birimEl.value;
    var ekEl = document.getElementById('atpReqEkNot');
    if (ekEl && ekEl.value.trim()) payload.ek_not = ekEl.value.trim();
    return payload;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (reqMode === 'other' && !(talepEdenUserIdEl && talepEdenUserIdEl.value)) {
      toast('Lütfen kullanıcı seçin');
      return;
    }
    var isVal = document.getElementById('atpReqIs').value.trim();
    if (!isVal) {
      toast('Yapılacak iş gerekli');
      return;
    }
    if (readSoforSecim() === 'DIGER' && !(soforOtherName && soforOtherName.value.trim())) {
      toast('Şoför adını yazın');
      return;
    }

    function submitPayload(loc) {
      var payload = {
        tarih: document.getElementById('atpReqTarih').value,
        istenen_saat: timeHidden ? (timeHidden.value || '') : '',
        is: isVal,
        oncelik: document.getElementById('atpReqOncelik').value,
        not: document.getElementById('atpReqNot').value.trim(),
        talep_eden_user_id: talepEdenUserIdEl ? talepEdenUserIdEl.value : currentUser.id,
        talep_eden_adi: talepEdenInput ? talepEdenInput.value.trim() : '',
        location_master_id: masterIdEl.value || null,
        firma: loc.firma,
        adres: loc.adres,
        kisi: loc.kisi || '',
        telefon: loc.telefon || '',
      };
      appendUxV2Fields(payload);
      if (!payload.location_master_id && loc.maps_url) {
        payload.maps_url = loc.maps_url;
      }
      fetch('/planlama/arac-takip/api/request', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.ok) {
          toast('İş talebi oluşturuldu');
          closeModal();
          if (window.AtpPool) window.AtpPool.refresh();
        } else {
          toast(j.error || 'Kayıt hatası');
        }
      }).catch(function () { toast('Kayıt hatası'); });
    }

    if (selectedLoc && masterIdEl.value) {
      submitPayload(selectedLoc);
      return;
    }
    if (!newPanel.hidden) {
      saveNewLocation(function (loc) { submitPayload(loc); });
      return;
    }
    toast('Firma / kayıtlı yer seçin veya yeni konum kaydedin');
    openNewLocationPanel(searchInput.value.trim());
  });

  window.AtpRequestModal = { open: openModal, close: closeModal };
})();
