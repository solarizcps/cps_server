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
  var latEl = document.getElementById('atpLocLat');
  var lngEl = document.getElementById('atpLocLng');
  var saveChk = document.getElementById('atpSaveToMaster');
  var searchTimer = null;
  var userSearchTimer = null;
  var selectedLoc = null;
  var editMode = false;
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
    timeTrigger.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        if (timePickerOpen) closeTimeDropdown();
        else openTimeDropdown();
      } else if (e.key === 'Escape') {
        closeTimeDropdown();
      }
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

  if (timeCustomInput) {
    timeCustomInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        timeCustomApply.click();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeTimeDropdown();
      }
    });
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && timePickerOpen) closeTimeDropdown();
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.atp-time-picker')) closeTimeDropdown();
  });

  function todayStr() {
    return new Date().toISOString().slice(0, 10);
  }

  function maskPhone(raw) {
    var d = (raw || '').replace(/\D/g, '');
    if (d.length === 11 && d[0] === '0') {
      return d.slice(0, 4) + ' ' + d.slice(4, 7) + ' ' + d.slice(7, 9) + ' ' + d.slice(9);
    }
    return raw || '';
  }

  function locBadge(hasLoc) {
    return hasLoc
      ? '<span class="atp-loc-badge">Konum mevcut</span>'
      : '<span class="atp-loc-badge no">Konum yok</span>';
  }

  function showDropdown(html) {
    dropdown.innerHTML = html;
    dropdown.hidden = !html;
    dropdown.querySelectorAll('.atp-loc-dd-item').forEach(function (btn) {
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var id = btn.getAttribute('data-loc-id');
        if (id === '__new__') {
          openNewLocationPanel(searchInput.value.trim());
          hideDropdown();
          return;
        }
        var payload = btn.getAttribute('data-loc-json');
        if (payload) {
          try { selectLocation(JSON.parse(decodeURIComponent(payload))); return; } catch (e) { /* fallthrough */ }
        }
        fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(searchInput.value || ''), { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            var found = (j.results || []).find(function (x) { return x.id === id; });
            if (!found) {
              var all = suggestionsCache.recent.concat(suggestionsCache.frequent);
              found = all.find(function (x) { return x.id === id; });
            }
            if (found) selectLocation(found);
          });
      });
    });
  }

  function renderDropdownItems(items, sectionLabel) {
    if (!items || !items.length) return '';
    var html = '<div class="atp-loc-dd-section">' + sectionLabel + '</div>';
    items.forEach(function (loc) {
      var enc = encodeURIComponent(JSON.stringify(loc));
      html += '<button type="button" class="atp-loc-dd-item" data-loc-id="' + loc.id + '" data-loc-json="' + enc + '">' +
        '<strong>' + (loc.firma || '—') + '</strong>' +
        '<small>' + (loc.kisi || '—') + ' · ' + (loc.short_adres || loc.adres || '—') + ' ' + locBadge(loc.has_location) + '</small>' +
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
          html += '<button type="button" class="atp-loc-dd-item atp-loc-dd-new" data-loc-id="__new__">+ Yeni Firma / Konum</button>';
          showDropdown(html);
        });
      return;
    }
    var html = renderDropdownItems(suggestionsCache.recent, 'Son Kullanılanlar');
    html += renderDropdownItems(suggestionsCache.frequent, 'Sık Gidilenler');
    html += '<button type="button" class="atp-loc-dd-item atp-loc-dd-new" data-loc-id="__new__">+ Yeni Firma / Konum</button>';
    showDropdown(html);
  }

  function runSearch(q) {
    fetch('/planlama/arac-takip/api/locations/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var html = renderDropdownItems(j.results || [], 'Arama Sonuçları');
        html += '<button type="button" class="atp-loc-dd-item atp-loc-dd-new" data-loc-id="__new__">+ Yeni Firma / Konum</button>';
        showDropdown(html);
      });
  }

  function fillNewPanel(loc) {
    document.getElementById('atpNewFirma').value = loc.firma || '';
    document.getElementById('atpNewKisi').value = loc.kisi || '';
    document.getElementById('atpNewTelefon').value = loc.telefon || '';
    document.getElementById('atpNewAdres').value = loc.adres || '';
    document.getElementById('atpNewMaps').value = loc.maps_url || '';
  }

  function readNewPanel() {
    return {
      firma: document.getElementById('atpNewFirma').value.trim(),
      kisi: document.getElementById('atpNewKisi').value.trim(),
      telefon: document.getElementById('atpNewTelefon').value.trim(),
      adres: document.getElementById('atpNewAdres').value.trim(),
      maps_url: document.getElementById('atpNewMaps').value.trim(),
      latitude: latEl.value || null,
      longitude: lngEl.value || null,
    };
  }

  function renderLocCard(loc) {
    document.getElementById('atpLocCardFirma').textContent = loc.firma || '—';
    var kt = [];
    if (loc.kisi) kt.push(loc.kisi);
    if (loc.telefon) kt.push(maskPhone(loc.telefon));
    document.getElementById('atpLocCardKisiTel').textContent = kt.join(' · ') || '—';
    document.getElementById('atpLocCardAdres').textContent = loc.adres || '—';
    var hasLoc = loc.latitude != null && loc.longitude != null;
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
    editMode = false;
  }

  function selectLocation(loc) {
    selectedLoc = loc;
    masterIdEl.value = loc.id || '';
    latEl.value = loc.latitude != null ? String(loc.latitude) : '';
    lngEl.value = loc.longitude != null ? String(loc.longitude) : '';
    searchInput.value = loc.firma || '';
    fillNewPanel(loc);
    renderLocCard(loc);
    hideDropdown();
  }

  function openNewLocationPanel(prefill) {
    selectedLoc = null;
    masterIdEl.value = '';
    latEl.value = '';
    lngEl.value = '';
    locCard.hidden = true;
    newPanel.hidden = false;
    editMode = true;
    if (prefill) {
      document.getElementById('atpNewFirma').value = prefill;
    }
    if (saveChk) saveChk.checked = true;
  }

  function resetLocationState() {
    selectedLoc = null;
    editMode = false;
    searchInput.value = '';
    masterIdEl.value = '';
    latEl.value = '';
    lngEl.value = '';
    locCard.hidden = true;
    newPanel.hidden = true;
    hideDropdown();
    fillNewPanel({});
    if (saveChk) saveChk.checked = true;
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
  }

  document.getElementById('atpBtnNewRequest').addEventListener('click', openModal);
  document.getElementById('atpModalClose').addEventListener('click', closeModal);
  document.getElementById('atpModalCancel').addEventListener('click', closeModal);
  backdrop.addEventListener('click', function (e) {
    if (e.target === backdrop) closeModal();
  });

  document.getElementById('atpBtnEditLoc').addEventListener('click', function () {
    if (!selectedLoc) return;
    newPanel.hidden = false;
    editMode = true;
    fillNewPanel(selectedLoc);
  });

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

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var locData = selectedLoc && !editMode ? selectedLoc : readNewPanel();
    if (!locData.firma) {
      toast('Firma / kayıtlı yer seçin veya yeni konum girin');
      if (newPanel.hidden) openNewLocationPanel(searchInput.value.trim());
      return;
    }
    if (editMode && !locData.adres) {
      toast('Adres zorunludur');
      return;
    }
    if (reqMode === 'other' && !(talepEdenUserIdEl && talepEdenUserIdEl.value)) {
      toast('Lütfen kullanıcı seçin');
      return;
    }
    var payload = {
      tarih: document.getElementById('atpReqTarih').value,
      istenen_saat: timeHidden ? (timeHidden.value || '') : '',
      is: document.getElementById('atpReqIs').value.trim(),
      oncelik: document.getElementById('atpReqOncelik').value,
      not: document.getElementById('atpReqNot').value.trim(),
      talep_eden_user_id: talepEdenUserIdEl ? talepEdenUserIdEl.value : currentUser.id,
      talep_eden_adi: talepEdenInput ? talepEdenInput.value.trim() : '',
      location_master_id: masterIdEl.value || null,
      save_to_master: editMode ? !!(saveChk && saveChk.checked) : false,
      firma: locData.firma,
      kisi: locData.kisi,
      telefon: locData.telefon,
      adres: locData.adres,
      maps_url: locData.maps_url,
      latitude: locData.latitude,
      longitude: locData.longitude,
    };
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
        toast('Kayıt hatası');
      }
    }).catch(function () { toast('Kayıt hatası'); });
  });

  window.AtpRequestModal = { open: openModal, close: closeModal };
})();
