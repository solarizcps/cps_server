/* ==========================================================
   CPS DEV - GLOBAL TASK LISTENER (FAZ 3 ADIM 4)
   ==========================================================
   Vanilla JS, sifir bagimlilik.

   Sorumluluk:
     - Polling (30s aktif / 120s hidden)
     - Queue (FIFO, ayni anda tek overlay)
     - Spam koruma (60s, localStorage)
     - 4 aksiyon: continue / goto / snooze / dismiss
     - ESC = dismiss (read DEGIL)
     - Page Visibility API
     - Hafif sound (kapanabilir, autoplay policy uyumlu)

   Endpoint:
     GET  /api/tasks/notifications/pending?since=ISO
     POST /api/tasks/notifications/<id>/read
     POST /api/tasks/notifications/<id>/dismiss
     POST /api/tasks/notifications/<id>/snooze   body: {minutes}

   CSS:
     static/css/global_overlay.css (cps-overlay-* class'lari)

   Debug:
     window.CPSOverlayDebug
   ========================================================== */
(function () {
  "use strict";

  // ============================================================
  // GUARD: Ayni script iki kez yuklenirse erken cik
  // ============================================================
  if (window.__cpsOverlayLoaded) {
    console.warn("[CPSOverlay] Zaten yuklenmis, atlandi");
    return;
  }
  window.__cpsOverlayLoaded = true;


  // ============================================================
  // STATE
  // ============================================================
  var state = {
    polling: {
      timer: null,
      intervalSec: 30,
      hiddenIntervalSec: 120,
      lastPollAt: null,
      isHidden: false,
      inflight: false,
    },
    queue: [],
    current: null,
    isOverlayOpen: false,
    isAnimating: false,
    isSnoozeMenuOpen: false,
    shownIds: {},      // {id: timestamp_ms}
    soundEnabled: true,
    audioCtx: null,
    audioUnlocked: false,
    abortController: null,
  };

  var SHOWN_TTL_MS = 60 * 1000;
  var STORAGE_KEY = "cps_overlay_shown_ids";


  // ============================================================
  // HELPERS
  // ============================================================
  function $(selector, root) {
    return (root || document).querySelector(selector);
  }
  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function escHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function nowISO() {
    var d = new Date();
    var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
         + " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function fmtDate(s, withTime) {
    if (!s) return "";
    var m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    if (!m) return s;
    var y = m[1], mo = m[2], d = m[3], hh = m[4], mm = m[5];
    var ds = d + "." + mo + "." + y;
    if (withTime && hh) return ds + " " + hh + ":" + mm;
    return ds;
  }

  function relativeDue(due_date) {
    if (!due_date) return null;
    var due = new Date(due_date);
    if (isNaN(due.getTime())) return null;
    var today = new Date(new Date().toDateString());
    var diff = Math.round((due - today) / 86400000);
    if (diff < 0)  return { text: Math.abs(diff) + " gun gecti", cls: "cps-overlay-meta-danger" };
    if (diff === 0) return { text: "Bugun", cls: "cps-overlay-meta-warn" };
    if (diff <= 3) return { text: diff + " gun", cls: "cps-overlay-meta-warn" };
    return { text: diff + " gun", cls: "" };
  }


  // ============================================================
  // SPAM KORUMA (localStorage + memory)
  // ============================================================
  function loadShownIds() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      var data = JSON.parse(raw);
      var now = Date.now();
      Object.keys(data).forEach(function (k) {
        if (now - data[k] < SHOWN_TTL_MS) state.shownIds[k] = data[k];
      });
    } catch (e) { /* localStorage disabled */ }
  }

  function saveShownIds() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.shownIds));
    } catch (e) { /* full or disabled */ }
  }

  function isRecentlyShown(id) {
    var ts = state.shownIds[id];
    if (!ts) return false;
    if (Date.now() - ts < SHOWN_TTL_MS) return true;
    delete state.shownIds[id];
    return false;
  }

  function markShown(id) {
    state.shownIds[id] = Date.now();
    saveShownIds();
  }

  function cleanupShownIds() {
    var now = Date.now();
    Object.keys(state.shownIds).forEach(function (k) {
      if (now - state.shownIds[k] >= SHOWN_TTL_MS) delete state.shownIds[k];
    });
    saveShownIds();
  }


  // ============================================================
  // API CALLS
  // ============================================================
  function api(path, opts) {
    opts = opts || {};
    var cfg = {
      method: opts.method || "GET",
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
    };
    if (opts.body) {
      cfg.headers["Content-Type"] = "application/json";
      cfg.body = JSON.stringify(opts.body);
    }
    if (opts.signal) cfg.signal = opts.signal;

    return fetch(path, cfg).then(function (r) {
      // FAZ UI BUGFIX: GTL_GUARD
      if (!r.ok || r.status === 401 || r.status === 403) {
        var __err = new Error('HTTP ' + r.status);
        __err._silent = true;
        return Promise.reject(__err);
      }
      var __ct = r.headers.get('content-type') || '';
      if (__ct.indexOf('application/json') < 0) {
        var __err2 = new Error('Non-JSON response');
        __err2._silent = true;
        return Promise.reject(__err2);
      }
      return r.json().then(function (data) {
        if (!r.ok) {
          var err = new Error((data && data.error) || ("HTTP " + r.status));
          err.status = r.status;
          throw err;
        }
        return data;
      });
    });
  }


  // ============================================================
  // POLL
  // ============================================================
  function doPoll() {
    if (state.polling.inflight) return Promise.resolve();
    state.polling.inflight = true;

    // Iptal edilebilir fetch
    if (state.abortController) state.abortController.abort();
    state.abortController = (typeof AbortController !== "undefined") ? new AbortController() : null;

    var url = "/api/tasks/notifications/pending?limit=20";
    if (state.polling.lastPollAt) {
      url += "&since=" + encodeURIComponent(state.polling.lastPollAt);
    }

    var pollAt = nowISO();

    return api(url, { signal: state.abortController ? state.abortController.signal : undefined })
      .then(function (resp) {
        state.polling.lastPollAt = pollAt;
        var notifs = (resp && resp.data && resp.data.notifications) || [];

        notifs.forEach(function (n) {
          if (isRecentlyShown(n.id)) return;
          // Queue'da zaten var mi?
          if (state.queue.some(function (q) { return q.id === n.id; })) return;
          // Su an gosterilen mi?
          if (state.current && state.current.id === n.id) return;
          state.queue.push(n);
        });

        processQueue();
      })
      .catch(function (e) {
        if (e.name === "AbortError") return;
        // sessizce gec, sayfa stabilitesini bozma
        if (e && e._silent) { /* GTL_GUARD silent */ } else if (window.CPSOverlayDebug) console.warn("[CPSOverlay] poll hatasi:", e.message);
      })
      .then(function () {
        state.polling.inflight = false;
      });
  }

  function startPolling(intervalSec) {
    stopPolling();
    state.polling.timer = setInterval(doPoll, intervalSec * 1000);
  }

  function stopPolling() {
    if (state.polling.timer) {
      clearInterval(state.polling.timer);
      state.polling.timer = null;
    }
  }


  // ============================================================
  // QUEUE
  // ============================================================
  function processQueue() {
    if (state.current) return;          // zaten acik
    if (state.isAnimating) return;      // animasyon devam
    if (state.queue.length === 0) return;

    var notif = state.queue.shift();
    state.current = notif;
    markShown(notif.id);
    openOverlay(notif);
    if (state.soundEnabled) playBeep();
  }


  // ============================================================
  // OVERLAY DOM (lazy create)
  // ============================================================
  var els = {};

  function ensureOverlayDOM() {
    if (els.root) return;

    var root = document.createElement("div");
    root.className = "cps-overlay-backdrop";
    root.id = "cps-overlay-root";
    root.setAttribute("aria-hidden", "true");
    root.innerHTML =
      '<div class="cps-overlay-card" role="dialog" aria-labelledby="cps-overlay-title">' +
        '<div class="cps-overlay-header">' +
          '<div class="cps-overlay-tag">YENI GOREV</div>' +
          '<button class="cps-overlay-close" data-action="close" aria-label="Kapat">&times;</button>' +
        '</div>' +
        '<div class="cps-overlay-body">' +
          '<h2 class="cps-overlay-title" id="cps-overlay-title"></h2>' +
          '<div class="cps-overlay-badges"></div>' +
          '<div class="cps-overlay-meta"></div>' +
          '<div class="cps-overlay-queue"></div>' +
        '</div>' +
        '<div class="cps-overlay-actions">' +
          '<button class="cps-overlay-btn cps-overlay-btn-primary"   data-action="continue">Devam Ediyorum</button>' +
          '<button class="cps-overlay-btn cps-overlay-btn-secondary" data-action="goto">Goreve Git</button>' +
          '<button class="cps-overlay-btn cps-overlay-btn-soft"      data-action="snooze">Daha Sonra <span class="cps-overlay-snooze-arrow">&#9662;</span></button>' +
          '<button class="cps-overlay-btn cps-overlay-btn-ghost"     data-action="dismiss">Kapat</button>' +
          '<div class="cps-overlay-snooze-menu">' +
            '<button data-min="15">15 dakika</button>' +
            '<button data-min="30">30 dakika</button>' +
            '<button data-min="60">1 saat</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.appendChild(root);

    els.root        = root;
    els.card        = $(".cps-overlay-card", root);
    els.title       = $(".cps-overlay-title", root);
    els.badges      = $(".cps-overlay-badges", root);
    els.meta        = $(".cps-overlay-meta", root);
    els.queueIndic  = $(".cps-overlay-queue", root);
    els.snoozeMenu  = $(".cps-overlay-snooze-menu", root);

    // Action delegasyonu
    root.addEventListener("click", onRootClick);
  }

  function onRootClick(e) {
    if (state.isAnimating) return;

    var target = e.target;

    // Snooze menu (15/30/60)
    if (target.matches(".cps-overlay-snooze-menu button")) {
      e.stopPropagation();
      var min = parseInt(target.getAttribute("data-min"), 10);
      if (min > 0) doSnooze(min);
      return;
    }

    var action = target.getAttribute("data-action");

    // Backdrop tiklamasi - dismiss
    if (target === els.root) { doDismiss(); return; }

    if (!action) return;

    if (action === "continue") doContinue();
    else if (action === "goto") doGoto();
    else if (action === "snooze") toggleSnoozeMenu();
    else if (action === "dismiss") doDismiss();
    else if (action === "close") doDismiss();
  }

  function toggleSnoozeMenu() {
    state.isSnoozeMenuOpen = !state.isSnoozeMenuOpen;
    if (state.isSnoozeMenuOpen) {
      els.snoozeMenu.classList.add("cps-overlay-show-snooze");
    } else {
      els.snoozeMenu.classList.remove("cps-overlay-show-snooze");
    }
  }

  function closeSnoozeMenu() {
    state.isSnoozeMenuOpen = false;
    if (els.snoozeMenu) els.snoozeMenu.classList.remove("cps-overlay-show-snooze");
  }


  // ============================================================
  // OVERLAY OPEN / CLOSE
  // ============================================================
  function openOverlay(notif) {
    ensureOverlayDOM();
    renderOverlay(notif);

    state.isOverlayOpen = true;
    state.isAnimating = true;

    els.root.classList.add("cps-overlay-show");
    els.root.setAttribute("aria-hidden", "false");

    setTimeout(function () { state.isAnimating = false; }, 200);
  }

  function closeOverlay() {
    if (!els.root) return;
    closeSnoozeMenu();

    state.isAnimating = true;
    els.card.classList.add("cps-overlay-leaving");

    setTimeout(function () {
      els.root.classList.remove("cps-overlay-show");
      els.card.classList.remove("cps-overlay-leaving");
      els.root.setAttribute("aria-hidden", "true");
      state.isOverlayOpen = false;
      state.current = null;
      state.isAnimating = false;
      // Sirada bekleyen varsa hemen ac
      processQueue();
    }, 160);
  }


  // ============================================================
  // RENDER
  // ============================================================
  function renderOverlay(notif) {
    // veri_json'dan ek bilgi
    var data = {};
    try { data = JSON.parse(notif.veri_json || "{}") || {}; } catch (e) {}

    // Title
    var title = data.title || notif.mesaj || "Yeni gorev";
    els.title.textContent = title;

    // Badges
    var prio = data.priority || "orta";
    var prioTr = { kritik: "Kritik", yuksek: "Yuksek", orta: "Orta", dusuk: "Dusuk" }[prio] || prio;
    var status = data.status || "bekliyor";
    var statusTr = {
      bekliyor: "Bekliyor",
      devam_ediyor: "Devam ediyor",
      onay_bekliyor: "Onay bekliyor",
      revize_istendi: "Revize istendi",
      tamamlandi: "Tamamlandi",
      gecikti: "Gecikti",
    }[status] || status;

    els.badges.innerHTML =
      '<span class="cps-overlay-badge cps-overlay-priority-' + escHtml(prio) + '">' + escHtml(prioTr) + '</span>' +
      '<span class="cps-overlay-badge cps-overlay-status-' + escHtml(status) + '">' + escHtml(statusTr) + '</span>';

    // Meta
    var rows = [];
    if (data.due_date) {
      var rel = relativeDue(data.due_date);
      var relHtml = rel ? ' <span class="' + rel.cls + '">(' + escHtml(rel.text) + ')</span>' : "";
      rows.push(
        '<div class="cps-overlay-meta-row">' +
          '<span class="cps-overlay-meta-lbl">Termin</span>' +
          '<span class="cps-overlay-meta-val">' + escHtml(fmtDate(data.due_date)) + relHtml + '</span>' +
        '</div>'
      );
    }
    if (data.department) {
      rows.push(
        '<div class="cps-overlay-meta-row">' +
          '<span class="cps-overlay-meta-lbl">Departman</span>' +
          '<span class="cps-overlay-meta-val">' + escHtml(data.department) + '</span>' +
        '</div>'
      );
    }
    if (data.created_by || data.olusturan) {
      rows.push(
        '<div class="cps-overlay-meta-row">' +
          '<span class="cps-overlay-meta-lbl">Olusturan</span>' +
          '<span class="cps-overlay-meta-val">' + escHtml(data.created_by || data.olusturan) + '</span>' +
        '</div>'
      );
    }
    if (data.related_order_no) {
      rows.push(
        '<div class="cps-overlay-meta-row">' +
          '<span class="cps-overlay-meta-lbl">Siparis</span>' +
          '<span class="cps-overlay-meta-val">' + escHtml(data.related_order_no) + '</span>' +
        '</div>'
      );
    }
    els.meta.innerHTML = rows.join("");
    els.meta.style.display = rows.length ? "" : "none";

    // Queue indicator
    var pending = state.queue.length;
    if (pending > 0) {
      els.queueIndic.textContent = "Sirada " + pending + " bildirim daha var";
      els.queueIndic.classList.add("cps-overlay-show-queue");
    } else {
      els.queueIndic.classList.remove("cps-overlay-show-queue");
    }
  }


  // ============================================================
  // ACTIONS
  // ============================================================
  function doContinue() {
    if (!state.current) { closeOverlay(); return; }
    var id = state.current.id;
    // Sahte test bildirimleri (id<0) icin API cagirma
    if (id > 0) {
      api("/api/tasks/notifications/" + id + "/read", { method: "POST", body: {} })
        .catch(function (e) { console.warn("[CPSOverlay] read err:", e.message); });
    }
    closeOverlay();
  }

  function doGoto() {
    if (!state.current) { closeOverlay(); return; }
    var id = state.current.id;
    var data = {};
    try { data = JSON.parse(state.current.veri_json || "{}") || {}; } catch (e) {}
    var taskId = data.task_id || data.gorev_id || null;

    if (id > 0) {
      api("/api/tasks/notifications/" + id + "/read", { method: "POST", body: {} })
        .catch(function (e) { console.warn("[CPSOverlay] read err:", e.message); });
    }

    closeOverlay();

    // AYNI sekme - yeni sekme YOK
    setTimeout(function () {
      if (taskId) {
        window.location.href = "/tasks?id=" + encodeURIComponent(taskId);
      } else {
        window.location.href = "/tasks";
      }
    }, 180);
  }

  function doSnooze(minutes) {
    if (!state.current) { closeOverlay(); return; }
    var id = state.current.id;
    closeSnoozeMenu();
    if (id > 0) {
      api("/api/tasks/notifications/" + id + "/snooze",
          { method: "POST", body: { minutes: minutes } })
        .catch(function (e) { console.warn("[CPSOverlay] snooze err:", e.message); });
    }
    closeOverlay();
  }

  function doDismiss() {
    if (!state.current) { closeOverlay(); return; }
    var id = state.current.id;
    if (id > 0) {
      api("/api/tasks/notifications/" + id + "/dismiss", { method: "POST", body: {} })
        .catch(function (e) { console.warn("[CPSOverlay] dismiss err:", e.message); });
    }
    closeOverlay();
  }


  // ============================================================
  // KEYBOARD - ESC = dismiss
  // ============================================================
  function onKeyDown(e) {
    if (!state.isOverlayOpen) return;
    if (e.key === "Escape") {
      e.preventDefault();
      doDismiss();
      return;
    }
    // Snooze menu acikken Escape onu kapatsin
    if (e.key === "Escape" && state.isSnoozeMenuOpen) {
      closeSnoozeMenu();
    }
  }


  // ============================================================
  // PAGE VISIBILITY
  // ============================================================
  function onVisibilityChange() {
    var hidden = (document.visibilityState === "hidden");
    state.polling.isHidden = hidden;
    if (hidden) {
      startPolling(state.polling.hiddenIntervalSec);
    } else {
      startPolling(state.polling.intervalSec);
      // Sayfa gorunur olunca hemen bir poll at
      setTimeout(doPoll, 200);
    }
  }


  // ============================================================
  // SOUND (Web Audio API, hafif beep)
  // ============================================================
  function unlockAudio() {
    if (state.audioUnlocked) return;
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      state.audioCtx = new Ctx();
      // Kisa silent buffer ile unlock
      var b = state.audioCtx.createBuffer(1, 1, 22050);
      var s = state.audioCtx.createBufferSource();
      s.buffer = b;
      s.connect(state.audioCtx.destination);
      s.start(0);
      state.audioUnlocked = true;
    } catch (e) { /* ignore */ }
  }

  function playBeep() {
    if (!state.audioUnlocked || !state.audioCtx) return;
    try {
      var ctx = state.audioCtx;
      var t = ctx.currentTime;
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, t);   // A5
      osc.frequency.linearRampToValueAtTime(660, t + 0.06);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.08, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.2);
    } catch (e) { /* ignore */ }
  }


  // ============================================================
  // CONFIG (task_settings'ten cek)
  // ============================================================
  function loadConfig() {
    // task_settings okunamasa bile default'larla devam et
    return api("/api/tasks/notifications/pending?limit=1").then(function () {
      // ping basarili - default ayarlar yeterli
    }).catch(function () { /* sessiz */ });
  }


  // ============================================================
  // CLEANUP (memory leak onleme)
  // ============================================================
  function cleanup() {
    stopPolling();
    if (state.abortController) try { state.abortController.abort(); } catch (e) {}
    document.removeEventListener("visibilitychange", onVisibilityChange);
    document.removeEventListener("keydown", onKeyDown);
    window.removeEventListener("beforeunload", cleanup);
    window.removeEventListener("pagehide", cleanup);
  }


  // ============================================================
  // INIT
  // ============================================================
  function init() {
    // /tasks sayfasinda overlay calistirmaya gerek yok? -> calistirsin, fark etmez
    // Ama /giris sayfasinda calismasin (oturum yok)
    if (location.pathname === "/giris" || location.pathname === "/login") {
      return;
    }

    loadShownIds();

    document.addEventListener("visibilitychange", onVisibilityChange);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("beforeunload", cleanup);
    window.addEventListener("pagehide", cleanup);

    // Audio unlock - ilk user interaction'da
    var unlockOnce = function () {
      unlockAudio();
      document.removeEventListener("click", unlockOnce);
      document.removeEventListener("keydown", unlockOnce);
      document.removeEventListener("touchstart", unlockOnce);
    };
    document.addEventListener("click", unlockOnce, { once: true });
    document.addEventListener("keydown", unlockOnce, { once: true });
    document.addEventListener("touchstart", unlockOnce, { once: true });

    // Spam koruma cleanup - 30 saniyede bir
    setInterval(cleanupShownIds, 30 * 1000);

    // Polling baslat
    startPolling(state.polling.intervalSec);

    // 2 saniye sonra ilk poll (sayfa yuklensin once)
    setTimeout(doPoll, 2000);
  }


  // ============================================================
  // DEBUG OBJECT
  // ============================================================
  window.CPSOverlayDebug = {
    version: "1.0.0",

    state: function () {
      return {
        polling: {
          intervalSec: state.polling.intervalSec,
          hiddenIntervalSec: state.polling.hiddenIntervalSec,
          lastPollAt: state.polling.lastPollAt,
          isHidden: state.polling.isHidden,
          inflight: state.polling.inflight,
          timerActive: !!state.polling.timer,
        },
        queueLength: state.queue.length,
        currentId: state.current ? state.current.id : null,
        isOverlayOpen: state.isOverlayOpen,
        soundEnabled: state.soundEnabled,
        audioUnlocked: state.audioUnlocked,
        shownCount: Object.keys(state.shownIds).length,
      };
    },
    queue: function () { return state.queue.slice(); },
    current: function () { return state.current; },
    lastPoll: function () { return state.polling.lastPollAt; },
    pollingSeconds: function () { return state.polling.intervalSec; },
    soundEnabled: function () { return state.soundEnabled; },

    pollNow: function () { return doPoll(); },
    toggleSound: function () { state.soundEnabled = !state.soundEnabled; return state.soundEnabled; },
    clearShown: function () { state.shownIds = {}; saveShownIds(); return true; },

    // Sahte bildirim - test icin
    testNotification: function (priority) {
      var fakeNotif = {
        id: -Math.floor(Math.random() * 100000),
        kullanici_id: 0,
        tip: "gorev_yeni",
        mesaj: "Test bildirimi",
        veri_json: JSON.stringify({
          title: "TEST GOREV - " + (priority || "orta"),
          priority: priority || "orta",
          status: "bekliyor",
          department: "uretim",
          due_date: new Date(Date.now() + 86400000).toISOString().slice(0, 10),
          created_by: "debug",
          task_id: 999,
        }),
        gonderim_zamani: nowISO(),
        okundu_mu: 0,
        snooze_until: null,
        dismiss_count: 0,
      };
      state.queue.push(fakeNotif);
      processQueue();
      return fakeNotif;
    },

    forceClose: function () { closeOverlay(); },
    forceCleanup: function () { cleanup(); },
  };


  // ============================================================
  // START
  // ============================================================
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
