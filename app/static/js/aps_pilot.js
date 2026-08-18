/* APS P4A.5.2 — Ghost/proxy MOVE drag + P4A.5.1 perf layer */
(function () {
  'use strict';

  var CFG = window.APS_PILOT || {};
  var timelinePayload = null;
  var planOriginals = {};
  var stagedChanges = {};
  var ganttReady = false;
  var currentZoomKey = '1h';
  var isReverting = false;
  var isDragging = false;
  var viewAnchorDate = null;
  var workingWindows = [];
  var lastDragClientY = null;
  var dragTargetResource = null;
  var resourceRectCache = [];
  var highlightNodes = { grid: null, task: null };
  var dragRafId = null;
  var ghostRafId = null;
  var pendingDragY = null;
  var pendingGhostPointer = null;
  var ghostDrag = {
    active: false,
    cancelled: false,
    taskId: null,
    planId: null,
    origStart: null,
    origEnd: null,
    origResource: null,
    nativeBarEl: null,
    el: null,
    width: 200,
    height: 30,
    anchorOffsetX: 0,
    anchorOffsetY: 0,
    startPointerX: 0,
    startPointerY: 0,
    pointerX: 0,
    pointerY: 0,
    anchorSet: false,
    lastGhostY: null,
    dropping: false,
    dropHandled: false,
    samples: [],
  };
  var cellClassCache = {};
  var cellClassCacheZoom = '';
  var dragFlags = {
    autoscroll: true,
    highlight: true,
    snap: true,
    workingTime: true,
    tooltip: true,
  };
  var dragMetrics = {
    render: 0, refreshData: 0, refreshTask: 0, parse: 0, clearAll: 0,
    stage: 0, conflict: 0, taskDrag: 0, afterTaskUpdate: 0,
    hitTest: 0, highlightUpdates: 0, sameTargetSkips: 0,
    calendarTemplate: 0, rafCoalesced: 0, ghostUpdates: 0, ghostRafCoalesced: 0,
  };
  var dragHandlerTimes = [];
  var ghostMoveCompleted = false;

  (function initDragFlags() {
    var qs = new URLSearchParams(window.location.search);
    if (qs.get('aps_no_autoscroll') === '1') dragFlags.autoscroll = false;
    if (qs.get('aps_no_highlight') === '1') dragFlags.highlight = false;
    if (qs.get('aps_no_snap') === '1') dragFlags.snap = false;
    if (qs.get('aps_no_working') === '1') dragFlags.workingTime = false;
    if (qs.get('aps_no_tooltip') === '1') dragFlags.tooltip = false;
  })();

  var ZOOM_ORDER = ['1y', '6m', '3m', '2m', '1w', '1d', '1h', '30m', '10m'];

  var PROCESS_COLORS = {
    enj: 'aps-process-enj',
    monta: 'aps-process-monta',
    temizleme: 'aps-process-temiz',
    diger: 'aps-process-diger',
  };

  // ─── ZOOM CONTRACT ──────────────────────────────────────────────────────────
  // Each preset defines:
  //   scales        – DHTMLX scale rows (top → bottom)
  //   minColumnWidth – px per smallest time unit column
  //   timeStep      – drag snap resolution (minutes)
  //   windowDays    – total visible date range width
  //   anchorOffset  – how many days BEFORE anchor to start the window (0..1 fraction)
  //
  // Visible window = [anchor - anchorOffset*windowDays, anchor + (1-anchorOffset)*windowDays]
  // This guarantees anchor (= active plan start) is always in view.
  // ─────────────────────────────────────────────────────────────────────────────

  var ZOOM_PRESETS = {
    // ── CLOSE: minute-level columns ────────────────────────────────────────
    '10m': {
      scales: [
        { unit: 'day',    step: 1,  format: '%d %M %Y' },
        { unit: 'hour',   step: 1,  format: '%H:00' },
        { unit: 'minute', step: 10, format: '%H:%i' },
      ],
      minColumnWidth: 40,
      timeStep: 10,
      windowDays: 1,        // ~24 h visible
      anchorOffset: 0.25,
    },
    '30m': {
      scales: [
        { unit: 'day',    step: 1,  format: '%d %M %Y' },
        { unit: 'hour',   step: 2,  format: '%H:00' },
        { unit: 'minute', step: 30, format: '%H:%i' },
      ],
      minColumnWidth: 36,
      timeStep: 30,
      windowDays: 2,        // ~2 days visible
      anchorOffset: 0.25,
    },
    // ── MEDIUM: hour-level columns ─────────────────────────────────────────
    '1h': {
      scales: [
        { unit: 'day',  step: 1, format: '%d %M %Y' },
        { unit: 'hour', step: 1, format: '%H:00' },
      ],
      minColumnWidth: 56,
      timeStep: 60,
      windowDays: 5,        // ~5 days visible
      anchorOffset: 0.2,
    },
    // ── DAY VIEW: exactly 1 day (~24 hours) ───────────────────────────────
    // Top scale:    "18 Ağustos 2026 Salı"  (full day header)
    // Bottom scale: "00:00 | 02:00 | 04:00 ... 22:00"  (2-hour columns)
    // windowDays = 1 so the visible range is always a single calendar day.
    '1d': {
      scales: [
        { unit: 'day',  step: 1, template: function(d){ return dayFullScaleTemplate(d); } },
        { unit: 'hour', step: 2, format: '%H:00' },
      ],
      minColumnWidth: 60,   // ~12 columns × 60px ≈ 720px for 1366 screen
      timeStep: 60,
      windowDays: 1,
      anchorOffset: 0.0,    // anchor date IS the day → window starts at midnight
      exactWindow: true,    // no +1 buffer; show exactly 1 calendar day
    },
    // ── WEEK VIEW: exactly 7 days + hour detail ────────────────────────────
    // Top scale:    "Ağustos 2026"
    // Middle scale: "Pzt 18 Ağu | Sal 19 Ağu | ..."  (1 column per day)
    // Bottom scale: "00 | 04 | 08 | 12 | 16 | 20"    (4-hour slots per day)
    // windowDays = 7, anchor at start of week.
    '1w': {
      scales: [
        { unit: 'month', step: 1, format: '%F %Y' },
        { unit: 'day',   step: 1, template: function(d){ return weekDayScaleTemplate(d); } },
        { unit: 'hour',  step: 4, format: '%H' },
      ],
      minColumnWidth: 32,   // 6 × 32px = 192px per day; 7 days × 192 = 1344px
      timeStep: 60,
      windowDays: 7,
      anchorOffset: 0.0,    // anchor = plan start; window starts same day
      exactWindow: true,    // no +1 buffer; show exactly 7 calendar days
    },
    // ── LONG: month/quarter/year ───────────────────────────────────────────
    '2m': {
      scales: [
        { unit: 'year',  step: 1, format: '%Y' },
        { unit: 'month', step: 1, format: '%F' },
        { unit: 'week',  step: 1, template: function(d){ return weekScaleTemplate(d); } },
      ],
      minColumnWidth: 24,
      timeStep: 10080,
      windowDays: 62,
      anchorOffset: 0.15,
    },
    '3m': {
      scales: [
        { unit: 'year',  step: 1, format: '%Y' },
        { unit: 'month', step: 1, format: '%F' },
        { unit: 'week',  step: 1, template: function(d){ return weekScaleTemplate(d); } },
      ],
      minColumnWidth: 18,
      timeStep: 10080,
      windowDays: 92,
      anchorOffset: 0.15,
    },
    '6m': {
      scales: [
        { unit: 'year',  step: 1, format: '%Y' },
        { unit: 'month', step: 1, format: '%M' },
      ],
      minColumnWidth: 48,
      timeStep: 10080,
      windowDays: 184,
      anchorOffset: 0.15,
    },
    '1y': {
      scales: [
        { unit: 'year',  step: 1, format: '%Y' },
        { unit: 'month', step: 1, format: '%M' },
      ],
      minColumnWidth: 32,
      timeStep: 10080,
      windowDays: 366,
      anchorOffset: 0.1,
    },
  };

  // Build a {start, end} window so that anchorDate is always visible.
  // anchorOffset fraction of windowDays is placed BEFORE the anchor.
  function getVisibleWindow(anchorDate, key) {
    var preset  = ZOOM_PRESETS[key] || ZOOM_PRESETS['1h'];
    var days    = preset.windowDays    || 5;
    var before  = Math.ceil(days * (preset.anchorOffset || 0.2));
    var anchor  = anchorDate || new Date();
    var start   = new Date(anchor.getTime());
    start.setDate(start.getDate() - before);
    start.setHours(0, 0, 0, 0);
    var end = new Date(start.getTime());
    // exactWindow=true: no +1 buffer — used for '1d'/'1w' where the
    // contract specifies an exact 1-day / 7-day visible range.
    var buffer = preset.exactWindow ? 0 : 1;
    end.setDate(end.getDate() + days + buffer);
    end.setHours(23, 59, 59, 0);
    return { start: start, end: end };
  }

  // ─── CANONICAL TURKISH LOCALE ────────────────────────────────────────────────
  // Single source of truth for all date labels shown in the DHTMLX timeline.
  // Applied once via gantt.i18n.setLocale() before gantt.init() so that the
  // %F (full month), %M (short month), %D (short day), %l (full day) tokens
  // in scale format strings all render in Turkish automatically.
  // ─────────────────────────────────────────────────────────────────────────────
  var TR_LOCALE = {
    month_full:  ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran',
                  'Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'],
    month_short: ['Oca','Şub','Mar','Nis','May','Haz',
                  'Tem','Ağu','Eyl','Eki','Kas','Ara'],
    day_full:    ['Pazar','Pazartesi','Salı','Çarşamba',
                  'Perşembe','Cuma','Cumartesi'],
    day_short:   ['Paz','Pzt','Sal','Çar','Per','Cum','Cmt'],
    // UI strings used by DHTMLX lightbox / tooltips (not shown in our UI but
    // set for completeness so no English leaks through).
    label_time:  'Zaman',
    label_task:  'Görev Adı',
    new_filters: 'Yeni Filtre',
    confirm_closing:     'Değişiklikler kaybolacak. Emin misiniz?',
    confirm_deleting:    'Görev kalıcı silinecek. Emin misiniz?',
    section_description: 'Açıklama',
    section_time:        'Süre',
    section_type:        'Tür',
    column_wbs:          'WBS',
    link:                'Bağlantı',
    confirm_link_deleting: 'Bağlantı silinecek. Emin misiniz?',
    link_start:          ' (başlangıç)',
    link_end:            ' (bitiş)',
    message_ok:          'Tamam',
    message_cancel:      'İptal',
    next:                'İleri',
    prev:                'Geri',
    save:                'Kaydet',
    icon_save:           'Kaydet',
    icon_cancel:         'İptal',
    icon_delete:         'Sil',
  };

  // Installs the Turkish locale into DHTMLX once.
  // Safe to call before gantt.init(); DHTMLX merges locale on init.
  function installTurkishLocale() {
    if (gantt.i18n && typeof gantt.i18n.setLocale === 'function') {
      gantt.i18n.setLocale({
        date: {
          month_full:  TR_LOCALE.month_full,
          month_short: TR_LOCALE.month_short,
          day_full:    TR_LOCALE.day_full,
          day_short:   TR_LOCALE.day_short,
        },
        labels: {
          new_task: 'Yeni Görev',
          icon_save: TR_LOCALE.icon_save,
          icon_cancel: TR_LOCALE.icon_cancel,
          icon_delete: TR_LOCALE.icon_delete,
          confirm_closing: TR_LOCALE.confirm_closing,
          confirm_deleting: TR_LOCALE.confirm_deleting,
          section_description: TR_LOCALE.section_description,
          section_time: TR_LOCALE.section_time,
          section_type: TR_LOCALE.section_type,
          message_ok: TR_LOCALE.message_ok,
          message_cancel: TR_LOCALE.message_cancel,
        },
      });
    }
  }

  // ─── CUSTOM SCALE FORMATTER ───────────────────────────────────────────────────
  // DHTMLX processes scale format strings through gantt.date.date_to_str().
  // When a format contains custom tokens like "Hf %W" (Hafta + week number),
  // we override scale_row_class / date_scale via template.  But it is simpler
  // and safer to use a scale.template function for the week row only.
  // The month/day tokens (%F, %M, %d) already work via TR_LOCALE above.
  // We only need a custom formatter for the "Hafta N" week label.
  function weekScaleTemplate(date) {
    // ISO week number → "Hafta 34"
    var d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    var dayNum = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);
    var yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    var weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    return 'Hafta ' + weekNo;
  }

  // "1 gün" top scale: "18 Ağustos 2026 Salı"
  function dayFullScaleTemplate(date) {
    var dayShort = TR_LOCALE.day_full[date.getDay()];
    var dayNum   = date.getDate();
    var mon      = TR_LOCALE.month_full[date.getMonth()];
    var yr       = date.getFullYear();
    return dayNum + ' ' + mon + ' ' + yr + ' ' + dayShort;
  }

  // "1 hafta" middle scale: "Pzt 18 Ağu"
  function weekDayScaleTemplate(date) {
    var pad  = function(n){ return n < 10 ? '0' + n : '' + n; };
    var ds   = TR_LOCALE.day_short[date.getDay()];
    var mon  = TR_LOCALE.month_short[date.getMonth()];
    return ds + ' ' + pad(date.getDate()) + ' ' + mon;
  }

  function parseDt(str) {
    if (!str) return null;
    var s = String(str).trim().replace(' ', 'T');
    var d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }

  function fmtDt(d) {
    if (!d) return '—';
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() + ' ' +
      pad(d.getHours()) + ':' + pad(d.getMinutes()) +
      (d.getSeconds() ? (':' + pad(d.getSeconds())) : '');
  }

  function fmtDtCompact(d) {
    if (!d) return '—';
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + ' ' +
      pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function fmtDateShort(d) {
    if (!d) return '—';
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear();
  }

  function ganttDateStr(d) {
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    return pad(d.getDate()) + '-' + pad(d.getMonth() + 1) + '-' + d.getFullYear() + ' ' +
      pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function minutesBetween(a, b) {
    return Math.max(1, Math.round((b - a) / 60000));
  }

  function addDays(d, n) {
    var x = new Date(d.getTime());
    x.setDate(x.getDate() + n);
    return x;
  }

  function computeViewRange(payload) {
    var plans = payload.plans || [];
    var minS = parseDt((payload.view_start || CFG.viewStart) + ' 00:00:00');
    var maxE = parseDt((payload.view_end || CFG.viewEnd) + ' 23:59:59');
    plans.forEach(function (p) {
      var s = parseDt(p.start);
      var e = parseDt(p.end);
      if (s && (!minS || s < minS)) minS = s;
      if (e && (!maxE || e > maxE)) maxE = e;
    });
    if (!minS) minS = parseDt(CFG.viewStart + ' 00:00:00');
    if (!maxE) maxE = parseDt(CFG.viewEnd + ' 23:59:59');
    return { start: addDays(minS, -1), end: addDays(maxE, 2) };
  }

  function countVisibleRows() {
    var n = 0;
    gantt.eachTask(function (t) {
      if (t.aps_type !== 'enj_plan') n += 1;
    });
    return Math.max(n, 1);
  }

  function setGanttHeight() {
    fitGanttToShell();
  }

  function fitGanttToShell() {
    var el = document.getElementById('apsGanttEnj');
    var shell = document.getElementById('apsGanttShell');
    if (!el || !shell || !ganttReady) return;
    // CSS already sets #apsGanttEnj { height: 100% !important; flex: 1 }.
    // Read the real committed height via offsetHeight (forces layout flush).
    // Always write an explicit px value so DHTMLX getSizes() sees a number,
    // never an empty string or a percentage it cannot resolve.
    var h = shell.offsetHeight || shell.getBoundingClientRect().height || shell.clientHeight;
    if (h > 40) {
      el.style.height = h + 'px';
    }
    if (typeof gantt.setSizes === 'function') gantt.setSizes();
  }

  function installDragForensics() {
    ['render', 'refreshData', 'refreshTask', 'parse', 'clearAll'].forEach(function (m) {
      if (!gantt[m]) return;
      var orig = gantt[m].bind(gantt);
      gantt[m] = function () {
        if (isDragging) dragMetrics[m] = (dragMetrics[m] || 0) + 1;
        return orig.apply(gantt, arguments);
      };
    });
  }

  function resetDragMetrics() {
    dragMetrics = {
      render: 0, refreshData: 0, refreshTask: 0, parse: 0, clearAll: 0,
      stage: 0, conflict: 0, taskDrag: 0, afterTaskUpdate: 0,
      hitTest: 0, highlightUpdates: 0, sameTargetSkips: 0,
      calendarTemplate: 0, rafCoalesced: 0, ghostUpdates: 0, ghostRafCoalesced: 0,
    };
    dragHandlerTimes = [];
    try {
      performance.clearMeasures('aps-drag-visual');
      performance.clearMeasures('aps-onTaskDrag');
    } catch (e) { /* ignore */ }
  }

  function invalidateCellClassCache() {
    cellClassCache = {};
    cellClassCacheZoom = currentZoomKey;
  }

  function buildResourceRectCache() {
    resourceRectCache = [];
    gantt.eachTask(function (t) {
      if (t.aps_type !== 'slot') return;
      var gridNode = gantt.getTaskRowNode(t.id);
      if (!gridNode) return;
      var r = gridNode.getBoundingClientRect();
      var taskRow = document.querySelector('.gantt_task_row[task_id="' + t.id + '"]');
      resourceRectCache.push({
        id: t.id,
        top: r.top,
        bottom: r.bottom,
        gridNode: gridNode,
        taskRow: taskRow,
      });
    });
  }

  function resolveTargetResource(clientY) {
    if (clientY == null) return null;
    dragMetrics.hitTest += 1;
    for (var i = 0; i < resourceRectCache.length; i++) {
      var row = resourceRectCache[i];
      if (clientY >= row.top && clientY <= row.bottom) return row.id;
    }
    return null;
  }

  function setDragTargetHighlight(resourceId) {
    if (!dragFlags.highlight) return;
    if (resourceId === dragTargetResource) {
      dragMetrics.sameTargetSkips += 1;
      return;
    }
    if (highlightNodes.grid) highlightNodes.grid.classList.remove('aps-drag-target');
    if (highlightNodes.task) highlightNodes.task.classList.remove('aps-drag-target');
    highlightNodes = { grid: null, task: null };
    dragTargetResource = resourceId;
    if (!resourceId) return;
    for (var i = 0; i < resourceRectCache.length; i++) {
      if (resourceRectCache[i].id !== resourceId) continue;
      if (resourceRectCache[i].gridNode) {
        resourceRectCache[i].gridNode.classList.add('aps-drag-target');
        highlightNodes.grid = resourceRectCache[i].gridNode;
      }
      if (resourceRectCache[i].taskRow) {
        resourceRectCache[i].taskRow.classList.add('aps-drag-target');
        highlightNodes.task = resourceRectCache[i].taskRow;
      }
      break;
    }
    dragMetrics.highlightUpdates += 1;
  }

  function clearResourceHighlight() {
    setDragTargetHighlight(null);
  }

  function hideGanttTooltip() {
    var tip = document.querySelector('.gantt_tooltip');
    if (tip) tip.style.display = 'none';
  }

  function runDragVisualUpdate(clientY) {
    performance.mark('aps-drag-visual-start');
    var res = resolveTargetResource(clientY);
    setDragTargetHighlight(res);
    performance.mark('aps-drag-visual-end');
    try {
      performance.measure('aps-drag-visual', 'aps-drag-visual-start', 'aps-drag-visual-end');
    } catch (e) { /* ignore */ }
  }

  function scheduleDragVisualUpdate(clientY) {
    pendingDragY = clientY;
    if (dragRafId != null) {
      dragMetrics.rafCoalesced += 1;
      return;
    }
    dragRafId = requestAnimationFrame(function () {
      dragRafId = null;
      var y = pendingDragY;
      if (!isDragging || y == null) return;
      runDragVisualUpdate(y);
    });
  }

  function cancelDragVisualRaf() {
    if (dragRafId != null) {
      cancelAnimationFrame(dragRafId);
      dragRafId = null;
    }
    pendingDragY = null;
  }

  function cancelGhostRaf() {
    if (ghostRafId != null) {
      cancelAnimationFrame(ghostRafId);
      ghostRafId = null;
    }
    pendingGhostPointer = null;
  }

  function onGhostPointerMove(e) {
    if (!ghostDrag.active) return;
    ghostDrag.pointerX = e.clientX;
    ghostDrag.pointerY = e.clientY;
    lastDragClientY = e.clientY;
    if (!ghostDrag.anchorSet) {
      setGhostAnchorFromPointer(e.clientX, e.clientY);
    }
    scheduleGhostFrame();
  }

  function onGhostPointerUp(e) {
    if (!ghostDrag.active || ghostDrag.cancelled || ghostDrag.dropHandled) return;
    if (e && typeof e.clientX === 'number') {
      ghostDrag.pointerX = e.clientX;
      ghostDrag.pointerY = e.clientY;
      lastDragClientY = e.clientY;
      if (!ghostDrag.anchorSet) setGhostAnchorFromPointer(e.clientX, e.clientY);
    }
    finishGhostMoveDrop();
  }

  function finishGhostMoveDrop() {
    if (!ghostDrag.active || ghostDrag.dropHandled) return;
    ghostDrag.dropHandled = true;
    ghostDrag.dropping = true;
    ghostMoveCompleted = true;
    applyGhostDrop(ghostDrag.taskId);
    destroyGhostDrag();
    clearResourceHighlight();
    gantt.config.show_tooltips = dragFlags.tooltip;
    isDragging = false;
    ghostDrag.dropping = false;
  }

  function resolveNativeBarEl(id) {
    var node = gantt.getTaskNode(id);
    if (node) {
      if (node.classList && node.classList.contains('gantt_task_line')) return node;
      var line = node.querySelector('.gantt_task_line');
      if (line) return line;
      if (node.querySelector('.gantt_task_content')) return node;
    }
    return document.querySelector('.gantt_task_line.aps-enj-task');
  }

  function barScreenRect(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return r;
    var line = el.querySelector ? el.querySelector('.gantt_task_line') : null;
    if (line) return line.getBoundingClientRect();
    return r;
  }

  function setGhostAnchorFromPointer(clientX, clientY) {
    var rect = barScreenRect(ghostDrag.nativeBarEl);
    if (!rect || rect.width <= 0) return;
    ghostDrag.anchorOffsetX = clientX - rect.left;
    ghostDrag.anchorOffsetY = clientY - rect.top;
    ghostDrag.startPointerX = clientX;
    ghostDrag.startPointerY = clientY;
    ghostDrag.anchorSet = true;
  }

  function beginGhostMoveDrag(id) {
    var task = gantt.getTask(id);
    var plan = task.aps_plan;
    var node = resolveNativeBarEl(id);
    ghostDrag.active = true;
    ghostDrag.cancelled = false;
    ghostDrag.taskId = id;
    ghostDrag.planId = planIdForTask(task);
    ghostDrag.origStart = new Date(task.start_date.getTime());
    ghostDrag.origEnd = new Date((task.end_date || gantt.calculateEndDate(task)).getTime());
    ghostDrag.origResource = task.aps_type === 'slot' ? id : task.parent;
    ghostDrag.nativeBarEl = node;
    ghostDrag.anchorSet = false;
    ghostDrag.dropHandled = false;
    ghostDrag.samples = [];
    ghostDrag.lastGhostY = null;

    var rect = barScreenRect(node);
    if (node && rect) {
      ghostDrag.width = Math.max(rect.width, 40);
      ghostDrag.height = Math.max(rect.height, 28);
      node.classList.add('aps-native-dim');
      ghostDrag.anchorOffsetX = 24;
      ghostDrag.anchorOffsetY = rect.height / 2;
      ghostDrag.startPointerX = rect.left + ghostDrag.anchorOffsetX;
      ghostDrag.startPointerY = rect.top + ghostDrag.anchorOffsetY;
      ghostDrag.pointerX = ghostDrag.startPointerX;
      ghostDrag.pointerY = ghostDrag.startPointerY;
      ghostDrag.anchorSet = true;
    } else {
      ghostDrag.width = 200;
      ghostDrag.height = 30;
    }

    ghostDrag.el = document.createElement('div');
    ghostDrag.el.className = 'aps-drag-ghost aps-enj-task aps-status-planlandi';
    ghostDrag.el.textContent = adaptiveBlockText(plan);
    ghostDrag.el.style.width = ghostDrag.width + 'px';
    ghostDrag.el.style.height = ghostDrag.height + 'px';
    if (rect) {
      ghostDrag.el.style.left = Math.round(rect.left) + 'px';
      ghostDrag.el.style.top = Math.round(rect.top) + 'px';
      ghostDrag.lastGhostY = rect.top + rect.height / 2;
    }
    document.body.appendChild(ghostDrag.el);
    document.body.classList.add('aps-ghost-drag-active');

    document.addEventListener('mousemove', onGhostPointerMove, true);
    document.addEventListener('mouseup', onGhostPointerUp, true);
  }

  function maybeAutoscrollGhost(clientX, clientY) {
    if (!dragFlags.autoscroll) return;
    var sp = gantt.config.autoscroll_speed || 20;
    var margin = 48;
    var taskArea = document.querySelector('.gantt_task');
    if (taskArea) {
      var r = taskArea.getBoundingClientRect();
      if (clientX > r.right - margin) taskArea.scrollLeft += sp;
      else if (clientX < r.left + margin) taskArea.scrollLeft -= sp;
    }
    var vScroll = document.querySelector('.gantt_ver_scroll');
    if (vScroll) {
      var vr = vScroll.getBoundingClientRect();
      if (clientY > vr.bottom - margin) vScroll.scrollTop += sp;
      else if (clientY < vr.top + margin) vScroll.scrollTop -= sp;
    }
    buildResourceRectCache();
  }

  function runGhostFrame() {
    if (!ghostDrag.active || !ghostDrag.el) return;
    var left = ghostDrag.pointerX - ghostDrag.anchorOffsetX;
    var top = ghostDrag.pointerY - ghostDrag.anchorOffsetY;
    ghostDrag.el.style.left = Math.round(left) + 'px';
    ghostDrag.el.style.top = Math.round(top) + 'px';
    ghostDrag.lastGhostY = top + ghostDrag.height / 2;

    maybeAutoscrollGhost(ghostDrag.pointerX, ghostDrag.pointerY);
    if (dragFlags.highlight) runDragVisualUpdate(ghostDrag.pointerY);

    if (ghostDrag.samples.length < 40) {
      var nativeY = null;
      var nr = barScreenRect(ghostDrag.nativeBarEl);
      if (nr) nativeY = nr.top + nr.height / 2;
      ghostDrag.samples.push({
        pointerY: ghostDrag.pointerY,
        ghostY: ghostDrag.lastGhostY,
        targetResource: dragTargetResource,
        nativeBarY: nativeY,
      });
    }
    dragMetrics.ghostUpdates += 1;
  }

  function scheduleGhostFrame() {
    pendingGhostPointer = { x: ghostDrag.pointerX, y: ghostDrag.pointerY };
    if (ghostRafId != null) {
      dragMetrics.ghostRafCoalesced += 1;
      return;
    }
    ghostRafId = requestAnimationFrame(function () {
      ghostRafId = null;
      if (!ghostDrag.active) return;
      runGhostFrame();
    });
  }

  function destroyGhostDrag() {
    document.removeEventListener('mousemove', onGhostPointerMove, true);
    document.removeEventListener('mouseup', onGhostPointerUp, true);
    cancelGhostRaf();
    if (ghostDrag.nativeBarEl) ghostDrag.nativeBarEl.classList.remove('aps-native-dim');
    if (ghostDrag.el && ghostDrag.el.parentNode) ghostDrag.el.parentNode.removeChild(ghostDrag.el);
    document.body.classList.remove('aps-ghost-drag-active');
    ghostDrag.el = null;
    ghostDrag.nativeBarEl = null;
    ghostDrag.active = false;
    ghostDrag.anchorSet = false;
    ghostDrag.dropHandled = false;
  }

  function cancelGhostDrag() {
    if (!ghostDrag.active) return;
    ghostDrag.cancelled = true;
    isReverting = true;
    var task = gantt.getTask(ghostDrag.taskId);
    task.start_date = new Date(ghostDrag.origStart.getTime());
    task.end_date = new Date(ghostDrag.origEnd.getTime());
    gantt.updateTask(ghostDrag.taskId);
    isReverting = false;
    clearResourceHighlight();
    destroyGhostDrag();
    isDragging = false;
    gantt.config.show_tooltips = dragFlags.tooltip;
    resourceRectCache = [];
  }

  function applyGhostDrop(id) {
    if (!ghostDrag.anchorSet && ghostDrag.pointerX) {
      setGhostAnchorFromPointer(ghostDrag.pointerX, ghostDrag.pointerY);
    }
    if (!ghostDrag.anchorSet) return;
    var taskId = id;
    var task = gantt.getTask(taskId);
    if (!isPlanTask(task)) return;

    var deltaX = ghostDrag.pointerX - ghostDrag.startPointerX;
    var origPos = gantt.posFromDate(ghostDrag.origStart);
    var newPos = origPos + deltaX;
    if (newPos < 0) newPos = 0;
    var newStart = gantt.dateFromPos(newPos);
    if (dragFlags.snap && typeof gantt.roundDate === 'function') {
      newStart = gantt.roundDate(newStart);
    }
    var durMs = ghostDrag.origEnd.getTime() - ghostDrag.origStart.getTime();
    var newEnd = new Date(newStart.getTime() + durMs);

    buildResourceRectCache();
    var newResource = resolveTargetResource(ghostDrag.pointerY) || ghostDrag.origResource;

    isReverting = true;
    if (task.aps_type === 'slot' && task.aps_plan && newResource !== taskId) {
      var planId = planIdForTask(task);
      taskId = moveEmbeddedPlan(taskId, newResource, planId);
      task = gantt.getTask(taskId);
    } else if (task.aps_type === 'enj_plan' && newResource !== task.parent) {
      task.parent = newResource;
      gantt.updateTask(taskId);
      task = gantt.getTask(taskId);
    }

    task.start_date = newStart;
    task.end_date = newEnd;
    task.duration = minutesBetween(newStart, newEnd);
    task.$no_start = false;
    task.$no_end = false;
    syncEmbeddedPlanDates(task);
    gantt.updateTask(taskId);
    isReverting = false;

    syncEmbeddedPlanDates(task);
    stagePlanChange(task);
  }

  function fmtDateTR(d) {
    if (!d) return '—';
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    var mon = TR_LOCALE.month_short[d.getMonth()];
    return pad(d.getDate()) + ' ' + mon + ' ' + d.getFullYear();
  }

  function updateDateRangeLabel(view) {
    var el = document.getElementById('apsDateRange');
    if (!el || !view) return;
    el.textContent = fmtDateTR(view.start) + ' → ' + fmtDateTR(view.end);
  }

  function resourceRowAtClientY(clientY) {
    if (clientY == null || !ganttReady) return null;
    if (resourceRectCache.length) return resolveTargetResource(clientY);
    buildResourceRectCache();
    return resolveTargetResource(clientY);
  }

  function resourceLabel(taskOrId) {
    var task = typeof taskOrId === 'string' ? gantt.getTask(taskOrId) : taskOrId;
    if (!task) return '—';
    if (task.aps_type === 'slot') return task.text || '—';
    if (task.aps_resource_id) return String(task.aps_resource_id).replace('-', ' / ');
    return task.text || '—';
  }

  function findConflict(task) {
    if (!isPlanTask(task)) return null;
    var parent = task.aps_type === 'enj_plan' ? task.parent : task.id;
    var planId = planIdForTask(task);
    var start = task.start_date;
    var end = task.end_date || gantt.calculateEndDate(task);
    var conflict = null;
    gantt.eachTask(function (t) {
      if (!isPlanTask(t)) return;
      var tPlanId = planIdForTask(t);
      if (tPlanId === planId) return;
      var tParent = t.aps_type === 'enj_plan' ? t.parent : t.id;
      if (tParent !== parent) return;
      var te = t.end_date || gantt.calculateEndDate(t);
      if (start < te && end > t.start_date) conflict = t;
    });
    return conflict;
  }

  function findTaskIdForPlan(planId) {
    if (gantt.isTaskExists(planId)) return planId;
    var found = null;
    gantt.eachTask(function (t) {
      if (t.aps_type === 'slot' && t.aps_primary_plan_id === planId) found = t.id;
    });
    return found;
  }

  function findPlanData(planId) {
    var taskId = findTaskIdForPlan(planId);
    if (taskId && gantt.isTaskExists(taskId)) {
      var t = gantt.getTask(taskId);
      if (t.aps_plan) return t.aps_plan;
    }
    return (timelinePayload && timelinePayload.plans || []).find(function (p) {
      return p.id === planId;
    }) || {};
  }

  function openDrawer() {
    document.getElementById('apsPlanDrawer').classList.add('open');
    document.getElementById('apsPlanDrawer').setAttribute('aria-hidden', 'false');
    document.getElementById('apsDrawerBackdrop').style.display = 'block';
  }

  function closeDrawer() {
    document.getElementById('apsPlanDrawer').classList.remove('open');
    document.getElementById('apsPlanDrawer').setAttribute('aria-hidden', 'true');
    document.getElementById('apsDrawerBackdrop').style.display = 'none';
  }

  function isDrawerOpen() {
    return document.getElementById('apsPlanDrawer').classList.contains('open');
  }

  function showConflictModal(task, conflict) {
    var msg = document.getElementById('apsConflictMsg');
    var parentId = task.aps_type === 'enj_plan' ? task.parent : task.id;
    var plan = conflict.aps_plan || conflict;
    msg.innerHTML =
      resourceLabel(gantt.getTask(parentId)) + ' bu zaman aralığında dolu.<br><br>' +
      '<strong>Çakışan plan:</strong><br>Sipariş ' + (plan.sip_no || conflict.aps_sip_no || '—') + '<br>' +
      'Model ' + (plan.mamul_skod || conflict.aps_model || '—') + '<br>Bu plana burada yer verilemez.';
    document.getElementById('apsConflictModal').style.display = 'flex';
  }

  function hideConflictModal() {
    document.getElementById('apsConflictModal').style.display = 'none';
  }

  function hideApplyModal() {
    document.getElementById('apsApplyModal').style.display = 'none';
  }

  function moveEmbeddedPlan(fromSlotId, toSlotId, planId) {
    if (fromSlotId === toSlotId) return fromSlotId;
    var from = gantt.getTask(fromSlotId);
    var to = gantt.getTask(toSlotId);
    var start = new Date(from.start_date.getTime());
    var end = new Date((from.end_date || gantt.calculateEndDate(from)).getTime());
    var plan = from.aps_plan;
    var status = from.aps_status;
    var tooltip = from.aps_tooltip;

    isReverting = true;
    gantt.batchUpdate(function () {
      from.unscheduled = true;
      from.readonly = true;
      from.type = 'task';
      delete from.start_date;
      delete from.end_date;
      delete from.duration;
      delete from.aps_plan;
      delete from.aps_primary_plan_id;
      delete from.aps_status;
      delete from.aps_tooltip;
      gantt.updateTask(fromSlotId);

      to.start_date = new Date(start.getTime());
      to.end_date = new Date(end.getTime());
      to.duration = minutesBetween(start, end);
      to.unscheduled = false;
      to.$no_start = false;
      to.$no_end = false;
      to.readonly = false;
      to.type = 'task';
      to.aps_plan = plan;
      to.aps_primary_plan_id = planId;
      to.aps_status = status;
      to.aps_tooltip = tooltip;
      gantt.updateTask(toSlotId);
    });
    isReverting = false;
    return toSlotId;
  }

  function revertPlanToBaseline(planId) {
    var baseline = planOriginals[planId];
    if (!baseline) return;

    var currentTaskId = findTaskIdForPlan(planId);
    if (!currentTaskId) return;

    var targetResource = baseline.resourceId || baseline.parent;
    if (currentTaskId !== targetResource && gantt.isTaskExists(currentTaskId)) {
      var cur = gantt.getTask(currentTaskId);
      if (cur.aps_type === 'slot' && cur.aps_plan) {
        currentTaskId = moveEmbeddedPlan(currentTaskId, targetResource, planId);
      }
    }

    isReverting = true;
    var task = gantt.getTask(currentTaskId);
    task.start_date = new Date(baseline.start.getTime());
    task.end_date = new Date(baseline.end.getTime());
    task.duration = minutesBetween(baseline.start, baseline.end);
    if (task.aps_type === 'enj_plan') task.parent = baseline.parent;
    syncEmbeddedPlanDates(task);
    gantt.updateTask(currentTaskId);
    isReverting = false;
  }

  function syncEmbeddedPlanDates(task) {
    if (task.aps_type === 'slot' && task.aps_plan) {
      var end = task.end_date || gantt.calculateEndDate(task);
      task.aps_plan.start = fmtDt(task.start_date);
      task.aps_plan.end = fmtDt(end);
    }
  }

  function detectChangeTypes(baseline, task, resourceId) {
    var types = [];
    var end = task.end_date || gantt.calculateEndDate(task);
    var oldRes = baseline.resourceId || baseline.parent;
    if (oldRes !== resourceId) types.push('RESOURCE_CHANGE');
    if (baseline.start.getTime() !== task.start_date.getTime()) types.push('MOVE_TIME');
    if (baseline.end.getTime() !== end.getTime()) types.push('RESIZE');
    if (!types.length) types.push('MOVE_TIME');
    return types;
  }

  function updateStagingBar() {
    var bar = document.getElementById('apsStagingBar');
    var count = Object.keys(stagedChanges).length;
    var conflictEl = document.getElementById('apsStagingConflict');
    var hasConflict = Object.values(stagedChanges).some(function (c) { return c.conflict; });

    if (count === 0) {
      bar.style.display = 'none';
      document.body.classList.remove('aps-has-staging');
    } else {
      bar.style.display = 'flex';
      document.body.classList.add('aps-has-staging');
      document.getElementById('apsStagingCount').textContent =
        count + ' PLAN DEĞİŞİKLİĞİ BEKLİYOR';
      conflictEl.style.display = hasConflict ? 'inline' : 'none';
    }
  }

  function stagePlanChange(task) {
    var planId = planIdForTask(task);
    var baseline = planOriginals[planId];
    if (!planId || !baseline) return;

    var resourceId = task.aps_type === 'enj_plan' ? task.parent : task.id;
    var end = task.end_date || gantt.calculateEndDate(task);
    dragMetrics.conflict += 1;
    var conflict = findConflict(task);
    dragMetrics.stage += 1;

    stagedChanges[planId] = {
      plan_id: planId,
      task_id: task.id,
      old_resource: baseline.resourceId || baseline.parent,
      new_resource: resourceId,
      old_start: new Date(baseline.start.getTime()),
      old_end: new Date(baseline.end.getTime()),
      proposed_start: new Date(task.start_date.getTime()),
      proposed_end: new Date(end.getTime()),
      change_type: detectChangeTypes(baseline, task, resourceId),
      conflict: !!conflict,
      downstream_impact: [],
    };

    updateStagingBar();
  }

  function discardAllStaged() {
    Object.keys(stagedChanges).forEach(function (planId) {
      revertPlanToBaseline(planId);
    });
    stagedChanges = {};
    updateStagingBar();
  }

  function showApplyPreview() {
    var changes = Object.values(stagedChanges);
    if (!changes.length) return;

    var html = '';
    changes.forEach(function (ch) {
      var plan = findPlanData(ch.plan_id);
      html += '<div class="aps-apply-block">';
      html += '<strong>Sipariş: ' + (plan.sip_no || '—') + '</strong><br>';
      html += resourceLabel(ch.old_resource) + '<br>';
      html += fmtDtCompact(ch.old_start) + ' → ' + fmtDtCompact(ch.old_end) + '<br>';
      html += '↓<br>';
      html += resourceLabel(ch.new_resource) + '<br>';
      html += fmtDtCompact(ch.proposed_start) + ' → ' + fmtDtCompact(ch.proposed_end) + '<br>';
      html += 'Çakışma: ' + (ch.conflict
        ? '<span class="aps-conflict-yes">VAR</span>'
        : '<span class="aps-conflict-no">YOK</span>');
      html += '</div>';
    });

    document.getElementById('apsApplyBody').innerHTML = html;
    document.getElementById('apsApplyModal').style.display = 'flex';
  }

  function loadWorkingWindows(payload) {
    workingWindows = (payload.calendar_windows || []).map(function (w) {
      return { start: parseDt(w.start), end: parseDt(w.end) };
    }).filter(function (w) { return w.start && w.end; });
  }

  function cellMinutesForZoom() {
    var preset = ZOOM_PRESETS[currentZoomKey] || ZOOM_PRESETS['1h'];
    return preset.timeStep || 60;
  }

  function overlapsWorkingWindow(date) {
    if (!workingWindows.length) {
      if (isWeekend(date)) return false;
      return true;
    }
    var mins = cellMinutesForZoom();
    var cellEnd = new Date(date.getTime() + mins * 60000);
    for (var i = 0; i < workingWindows.length; i++) {
      var w = workingWindows[i];
      if (date < w.end && cellEnd > w.start) return true;
    }
    return false;
  }

  function cellClassForDate(date) {
    if (isDragging && !dragFlags.workingTime) {
      return isWeekend(date) ? 'weekend aps-closed' : 'aps-working';
    }
    if (cellClassCacheZoom !== currentZoomKey) invalidateCellClassCache();
    var key = String(date.getTime());
    if (cellClassCache[key] !== undefined) return cellClassCache[key];
    if (isDragging) dragMetrics.calendarTemplate += 1;
    var cls;
    if (overlapsWorkingWindow(date)) cls = 'aps-working';
    else if (isWeekend(date)) cls = 'weekend aps-closed';
    else cls = 'aps-closed';
    cellClassCache[key] = cls;
    return cls;
  }

  function tooltipRow(label, value) {
    if (!value && value !== 0) return '';
    return '<tr><td class="aps-tip-lbl">' + label + '</td>' +
           '<td class="aps-tip-val">' + value + '</td></tr>';
  }

  function buildTooltip(plan) {
    if (!plan) return '';
    return '<div class="aps-plan-tip">' +
      '<div class="aps-tip-header">Sipariş ' + (plan.sip_no || '—') + '</div>' +
      '<table class="aps-tip-table">' +
      tooltipRow('Model', plan.mamul_skod) +
      tooltipRow('Renk', plan.renk) +
      tooltipRow('Müşteri', plan.musteri) +
      tooltipRow('Miktar', plan.miktar ? Math.round(plan.miktar) + ' çift' : null) +
      '<tr class="aps-tip-sep"><td colspan="2"></td></tr>' +
      '<tr><td class="aps-tip-section" colspan="2">ENJEKSİYON</td></tr>' +
      tooltipRow('Makine / Slot', (plan.makine || '—') + ' / ' + (plan.slot || '—')) +
      tooltipRow('İstasyon', plan.istasyonlar) +
      tooltipRow('Kalıp', plan.kalip) +
      tooltipRow('Kalıp adedi', plan.kalip_adedi) +
      tooltipRow('Aktif göz', plan.aktif_goz) +
      tooltipRow('Tur', plan.gerekli_tur) +
      tooltipRow('Çift / tur', plan.tur_cift) +
      '<tr class="aps-tip-sep"><td colspan="2"></td></tr>' +
      '<tr><td class="aps-tip-section" colspan="2">PLAN ZAMANI</td></tr>' +
      tooltipRow('Başlangıç', plan.start) +
      tooltipRow('Tahmini bitiş', plan.end) +
      tooltipRow('Çalışma modu', plan.calisma_modu) +
      tooltipRow('Hafta sonu', plan.hafta_sonu) +
      tooltipRow('Kapasite kaynağı', plan.kapasite_kaynak) +
      tooltipRow('Durum', plan.status || 'PLANLANDI') +
      '</table></div>';
  }

  function adaptiveBlockText(plan) {
    if (!plan) return '';
    if (currentZoomKey === '10m' || currentZoomKey === '30m' || currentZoomKey === '1h') {
      return [plan.sip_no, plan.mamul_skod,
        plan.miktar ? (Math.round(plan.miktar) + ' ÇİFT') : '', plan.kalip].filter(Boolean).join(' · ');
    }
    if (currentZoomKey === '1d') {
      return plan.sip_no + ' · ' + plan.mamul_skod;
    }
    return String(plan.sip_no || '');
  }

  function dd(label, value) {
    return '<dt>' + label + '</dt><dd>' + (value || '—') + '</dd>';
  }

  function renderDetailPanel(plan) {
    var panel = document.getElementById('apsDetailPanel');
    if (!plan) {
      panel.innerHTML = '<p class="aps-detail-empty">Plan seçilmedi.</p>';
      return;
    }
    panel.innerHTML =
      '<dl class="aps-dl aps-dl-compact">' +
      dd('Sipariş', plan.sip_no) +
      dd('Model', plan.mamul_skod) +
      dd('Renk', plan.renk) +
      dd('Müşteri', plan.musteri) +
      dd('Miktar', (plan.miktar || 0) + ' çift') +
      '</dl>' +
      '<h4 class="aps-detail-sub">ENJEKSİYON</h4>' +
      '<dl class="aps-dl aps-dl-compact">' +
      dd('Makine / Slot', (plan.makine || '—') + ' / ' + (plan.slot || '—')) +
      dd('İstasyon', plan.istasyonlar) +
      dd('Kalıp', plan.kalip) +
      dd('Kalıp adedi', plan.kalip_adedi) +
      dd('Aktif göz', plan.aktif_goz) +
      dd('Tur', plan.gerekli_tur) +
      dd('Çift / tur', plan.tur_cift) +
      '</dl>' +
      '<h4 class="aps-detail-sub">PLAN ZAMANI</h4>' +
      '<dl class="aps-dl aps-dl-compact">' +
      dd('Başlangıç', plan.start) +
      dd('Tahmini bitiş', plan.end) +
      dd('Çalışma modu', plan.calisma_modu) +
      dd('Hafta sonu', plan.hafta_sonu) +
      dd('Kapasite kaynağı', plan.kapasite_kaynak) +
      dd('Durum', plan.status || 'PLANLANDI') +
      '</dl>';
  }

  function plansByResource(payload) {
    var map = {};
    (payload.plans || []).forEach(function (plan) {
      if (!map[plan.resource_id]) map[plan.resource_id] = [];
      map[plan.resource_id].push(plan);
    });
    Object.keys(map).forEach(function (k) {
      map[k].sort(function (a, b) {
        return String(a.start || '').localeCompare(String(b.start || ''));
      });
    });
    return map;
  }

  function buildTasksFromPayload(payload) {
    var tasks = [];
    var planTasks = [];
    var byRes = plansByResource(payload);
    planOriginals = {};

    (payload.processes || []).forEach(function (proc) {
      if (!proc.enabled) return;
      var colorCls = PROCESS_COLORS[proc.color] || PROCESS_COLORS.diger;
      tasks.push({
        id: proc.id,
        text: proc.process_name,
        type: 'project',
        open: true,
        readonly: true,
        aps_type: 'process',
        aps_process_code: proc.process_code,
        aps_color: proc.color,
        aps_process_class: colorCls,
        unscheduled: true,
      });
    });

    (payload.resources || []).forEach(function (res) {
      if (!res.enabled) return;

      // Intermediate machine parent row (P5.1 hierarchy)
      if (res.kind === 'machine') {
        tasks.push({
          id: res.id,
          text: res.display_name || res.label || res.makine,
          parent: res.parent_process,
          type: 'project',
          open: true,
          readonly: true,
          aps_type: 'machine',
          aps_makine: res.makine,
          aps_process_code: res.process_code,
          unscheduled: true,
        });
        return;
      }

      if (res.kind !== 'slot') return;
      var rplans = byRes[res.id] || [];
      var task = {
        id: res.id,
        text: res.label || res.slot || res.display_name,
        parent: res.parent_machine || res.parent_process,
        readonly: rplans.length ? false : true,
        aps_type: 'slot',
        aps_resource_id: res.id,
        aps_process_code: res.process_code,
      };

      if (rplans.length === 1) {
        var only = rplans[0];
        var start = parseDt(only.start);
        var end = parseDt(only.end);
        task.type = 'task';
        if (start && end) {
          task.start_date = ganttDateStr(start);
          task.end_date = ganttDateStr(end);
          task.duration = minutesBetween(start, end);
          task.aps_plan = only;
          task.aps_primary_plan_id = only.id;
          task.aps_status = only.status || 'PLANLANDI';
          task.aps_tooltip = buildTooltip(only);
          planOriginals[only.id] = { start: start, end: end, parent: res.id, resourceId: res.id };
        }
      } else if (rplans.length > 1) {
        task.type = 'project';
        task.render = 'split';
        task.open = true;
        rplans.forEach(function (plan) {
          var start = parseDt(plan.start);
          var end = parseDt(plan.end);
          if (!start || !end) return;
          planOriginals[plan.id] = { start: start, end: end, parent: res.id, resourceId: res.id };
          planTasks.push({
            id: plan.id,
            text: plan.label_short || String(plan.sip_no || plan.id),
            parent: res.id,
            type: 'task',
            render: 'split',
            start_date: ganttDateStr(start),
            end_date: ganttDateStr(end),
            duration: minutesBetween(start, end),
            readonly: false,
            aps_type: 'enj_plan',
            aps_plan: plan,
            aps_status: plan.status || 'PLANLANDI',
            aps_sip_no: plan.sip_no,
            aps_model: plan.mamul_skod,
            aps_tooltip: buildTooltip(plan),
          });
        });
      } else {
        task.type = 'task';
        task.unscheduled = true;
      }
      tasks.push(task);
    });

    return tasks.concat(planTasks);
  }

  function planIdForTask(task) {
    if (!task) return null;
    if (task.aps_type === 'enj_plan') return task.id;
    if (task.aps_type === 'slot' && task.aps_primary_plan_id) return task.aps_primary_plan_id;
    return null;
  }

  function isPlanTask(task) {
    return task && (task.aps_type === 'enj_plan' || (task.aps_type === 'slot' && task.aps_plan));
  }

  function statusClass(status) {
    var s = (status || 'PLANLANDI').toUpperCase();
    if (s === 'DEVAM') return 'aps-status-devam';
    if (s === 'TAMAMLANDI') return 'aps-status-tamam';
    if (s === 'GECIKTI') return 'aps-status-gecikti';
    return 'aps-status-planlandi';
  }

  function isWeekend(date) {
    var day = date.getDay();
    return day === 0 || day === 6;
  }

  function handlePlanDragEnd(id, mode) {
    if (mode !== 'resize') return;
    var taskId = id;
    var task = gantt.getTask(taskId);
    if (!isPlanTask(task)) return;

    syncEmbeddedPlanDates(task);
    stagePlanChange(task);
  }

  function configureGantt(payload) {
    loadWorkingWindows(payload);
    invalidateCellClassCache();
    var view = computeViewRange(payload);
    // Anchor = first plan start so zoom always centres on the active plan.
    // Fall back to view.start if no plans loaded yet.
    var firstPlanStart = (payload.plans && payload.plans.length > 0)
      ? parseDt(payload.plans[0].start) : null;
    viewAnchorDate = firstPlanStart || view.start;

    gantt.config.date_format = '%d-%m-%Y %H:%i';
    gantt.config.xml_date = '%d-%m-%Y %H:%i';
    gantt.config.duration_unit = 'minute';
    gantt.config.readonly = false;
    gantt.config.drag_move = true;
    gantt.config.drag_resize = true;
    gantt.config.drag_progress = false;
    gantt.config.auto_types = false;
    gantt.config.details_on_dblclick = false;
    gantt.config.open_tree_initially = true;
    gantt.config.open_split_tasks = true;
    gantt.config.fit_tasks = false;
    gantt.config.row_height = 40;
    gantt.config.bar_height = 30;
    gantt.config.indent = 28;
    gantt.config.scale_height = 46;
    gantt.config.autosize = false;
    gantt.config.autoscroll = dragFlags.autoscroll;
    gantt.config.autoscroll_speed = 20;
    gantt.config.show_tooltips = dragFlags.tooltip;
    gantt.config.round_dnd_dates = dragFlags.snap;
    gantt.config.show_progress = false;
    gantt.config.show_links = false;
    gantt.config.scroll_on_click = false;
    // Always render tasks that fall outside the visible date window —
    // zoom changes the window, not the task data, so we must never drop rows.
    gantt.config.show_tasks_outside_timescale = true;
    // start/end are overridden per-zoom by applyZoom → getVisibleWindow.
    gantt.config.start_date = view.start;
    gantt.config.end_date = view.end;

    gantt.config.columns = [
      { name: 'text', label: 'PROSES / KAYNAK', width: 160, tree: true, resize: true },
    ];
    gantt.config.grid_width = 168;

    gantt.templates.grid_row_class = function (start, end, task) {
      if (task.$split_subtask || task.aps_type === 'enj_plan') return 'gantt_split_subtask';
      if (task.aps_type === 'process') {
        return 'aps-process-grid-row ' + (task.aps_process_class || '');
      }
      if (task.aps_type === 'machine') return 'aps-machine-grid-row';
      if (task.aps_type === 'slot') return 'aps-slot-grid-row';
      return '';
    };

    gantt.templates.task_class = function (start, end, task) {
      if (task.aps_type === 'process') return 'aps-process-row ' + (task.aps_process_class || '');
      if (task.aps_type === 'machine') return 'aps-machine-row';
      if (task.aps_type === 'slot') {
        if (task.render === 'split') return 'aps-slot-row aps-split-resource';
        if (task.aps_plan) return 'aps-enj-task ' + statusClass(task.aps_status);
        return 'aps-slot-row';
      }
      if (task.aps_type === 'enj_plan') return 'aps-enj-task ' + statusClass(task.aps_status);
      return '';
    };

    gantt.templates.task_text = function (start, end, task) {
      if (isDragging && task._aps_text_cache) return task._aps_text_cache;
      var text = '';
      if (task.aps_type === 'enj_plan') text = adaptiveBlockText(task.aps_plan);
      else if (task.aps_type === 'slot' && task.aps_plan) text = adaptiveBlockText(task.aps_plan);
      task._aps_text_cache = text;
      return text;
    };

    gantt.templates.tooltip_text = function (start, end, task) {
      if (isDragging || !dragFlags.tooltip) return '';
      if (task.aps_tooltip) return task.aps_tooltip;
      if (task.aps_plan) return buildTooltip(task.aps_plan);
      return task.text || '';
    };

    gantt.templates.timeline_cell_class = function (task, date) {
      return cellClassForDate(date);
    };

    gantt.templates.scale_cell_class = function (date) {
      if (isWeekend(date)) return 'weekend aps-weekend-header';
      return '';
    };

    // P5.1 UX: click no longer opens the right drawer — detail shown via hover tooltip.
    gantt.attachEvent('onTaskClick', function (id) {
      return true;
    });

    gantt.attachEvent('onBeforeTaskDrag', function (id, mode) {
      var task = gantt.getTask(id);
      if (task.aps_type === 'process') return false;
      if (task.aps_type === 'machine') return false;
      if (task.aps_type === 'slot' && !task.aps_plan) return false;
      if (!isPlanTask(task)) return false;
      isDragging = true;
      resetDragMetrics();
      dragTargetResource = null;
      highlightNodes = { grid: null, task: null };
      lastDragClientY = null;
      buildResourceRectCache();
      hideGanttTooltip();
      gantt.config.show_tooltips = false;
      if (mode === 'move') {
        beginGhostMoveDrag(id);
        return false;
      }
      return true;
    });

    gantt.attachEvent('onTaskDrag', function (id, mode, e) {
      var t0 = performance.now();
      dragMetrics.taskDrag += 1;
      if (ghostDrag.active && mode === 'move') {
        if (e && typeof e.clientX === 'number') {
          ghostDrag.pointerX = e.clientX;
          ghostDrag.pointerY = e.clientY;
          lastDragClientY = e.clientY;
          if (!ghostDrag.anchorSet) setGhostAnchorFromPointer(e.clientX, e.clientY);
          scheduleGhostFrame();
        }
        dragHandlerTimes.push(performance.now() - t0);
        return true;
      }
      if (e && typeof e.clientY === 'number') {
        lastDragClientY = e.clientY;
      }
      dragHandlerTimes.push(performance.now() - t0);
      return true;
    });

    gantt.attachEvent('onAfterTaskDrag', function (id, mode) {
      cancelDragVisualRaf();
      cancelGhostRaf();

      if (ghostDrag.cancelled) {
        ghostDrag.cancelled = false;
        isDragging = false;
        return true;
      }

      if (isReverting) {
        isDragging = false;
        return true;
      }

      if (ghostMoveCompleted) {
        ghostMoveCompleted = false;
        isDragging = false;
        return true;
      }

      if (ghostDrag.dropHandled) {
        return true;
      }

      if (ghostDrag.active && mode === 'move') {
        finishGhostMoveDrop();
        return true;
      }

      clearResourceHighlight();
      resourceRectCache = [];
      gantt.config.show_tooltips = dragFlags.tooltip;
      if (mode === 'resize') {
        handlePlanDragEnd(id, mode);
      }
      isDragging = false;
      return true;
    });

    gantt.attachEvent('onGanttScroll', function () {
      if (isDragging) buildResourceRectCache();
      return true;
    });

    gantt.attachEvent('onTaskOpened', function () { fitGanttToShell(); return true; });
    gantt.attachEvent('onTaskClosed', function () { fitGanttToShell(); return true; });

    gantt.attachEvent('onAfterTaskUpdate', function (id) {
      dragMetrics.afterTaskUpdate += 1;
      if (isReverting || isDragging) return true;
      return true;
    });

    updateDateRangeLabel(view);
  }

  function addTodayMarker() {
    gantt.attachEvent('onGanttRender', function () {
      var now = new Date();
      var pos = gantt.posFromDate(now);
      if (pos === null || pos === undefined || isNaN(pos)) return;
      var bg = document.querySelector('.gantt_task_bg');
      if (!bg) return;
      var line = document.getElementById('aps-today-line');
      if (!line) {
        line = document.createElement('div');
        line.id = 'aps-today-line';
        line.className = 'aps-today-line';
        line.innerHTML = '<span>ŞİMDİ</span>';
        bg.appendChild(line);
      }
      line.style.left = Math.round(pos) + 'px';
    });
  }

  function setActiveZoomButton(key) {
    document.querySelectorAll('#apsZoomGroup .aps-btn[data-zoom]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.zoom === key);
    });
  }

  function applyZoom(key) {
    var preset = ZOOM_PRESETS[key] || ZOOM_PRESETS['1h'];
    currentZoomKey = key;

    // Recompute visible date window for this zoom level around the anchor.
    var anchor = viewAnchorDate || gantt.config.start_date || new Date();
    var win = getVisibleWindow(anchor, key);
    gantt.config.start_date = win.start;
    gantt.config.end_date   = win.end;

    gantt.config.scales           = preset.scales;
    gantt.config.min_column_width = preset.minColumnWidth;
    gantt.config.time_step        = preset.timeStep || 10;
    gantt.config.round_dnd_dates  = dragFlags.snap;

    invalidateCellClassCache();
    gantt.eachTask(function (t) { delete t._aps_text_cache; });

    // Keep process/machine rows open; slot rows are leaves (no children to collapse).
    if (ganttReady) {
      gantt.eachTask(function (t) {
        if (t.aps_type === 'process' || t.aps_type === 'machine') t.$open = true;
      });
    }

    fitGanttToShell();
    gantt.render();
    fitGanttToShell();

    // Scroll to anchor so the active plan is always visible horizontally.
    if (gantt.showDate) gantt.showDate(anchor);

    setActiveZoomButton(key);
  }

  function zoomStep(delta) {
    var idx = ZOOM_ORDER.indexOf(currentZoomKey);
    if (idx < 0) idx = 2;
    var next = idx + delta;
    if (next < 0 || next >= ZOOM_ORDER.length) return;
    applyZoom(ZOOM_ORDER[next]);
  }

  function scrollToDate(d) {
    if (!ganttReady || !d) return;
    gantt.showDate(d);
    viewAnchorDate = d;
    var picker = document.getElementById('apsDatePicker');
    if (picker) {
      var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
      picker.value = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }
  }

  function navDays(delta) {
    // Navigation step is zoom-aware:
    //   '1d'  → move 1 day per click
    //   '1w'  → move 7 days per click
    //   other → move 1 day per click (scroll-based navigation)
    var step = 1;
    if (currentZoomKey === '1w') step = 7;
    var base = viewAnchorDate || gantt.config.start_date || new Date();
    var next = addDays(base, delta * step);
    // For day/week views re-render the full window centred on new anchor
    // so the visible date range actually moves (not just a scroll offset).
    if (currentZoomKey === '1d' || currentZoomKey === '1w') {
      viewAnchorDate = next;
      applyZoom(currentZoomKey);
    } else {
      scrollToDate(next);
    }
  }

  function focusPlan(planId) {
    if (!ganttReady || !planId) return false;
    var proc = (timelinePayload && timelinePayload.processes || [])[0];
    if (proc) gantt.open(proc.id);
    if (gantt.isTaskExists(planId)) {
      var task = gantt.getTask(planId);
      if (task.parent) {
        var parent = gantt.getTask(task.parent);
        if (!(parent && parent.render === 'split' && parent.open === false)) {
          gantt.open(task.parent);
        }
      }
      gantt.showTask(planId);
      gantt.selectTask(planId);
      return true;
    }
    var slotId = null;
    gantt.eachTask(function (t) {
      if (t.aps_type === 'slot' && t.aps_primary_plan_id === planId) slotId = t.id;
    });
    if (!slotId) return false;
    gantt.showTask(slotId);
    gantt.selectTask(slotId);
    return true;
  }

  function searchBySipNo(q) {
    if (!timelinePayload || !q) return false;
    var needle = String(q).trim();
    if (!needle) return false;
    var found = null;
    (timelinePayload.plans || []).some(function (p) {
      if (String(p.sip_no || '').indexOf(needle) >= 0) {
        found = p;
        return true;
      }
      return false;
    });
    if (!found) return false;
    var proc = (timelinePayload.processes || [])[0];
    if (proc) gantt.open(proc.id);
    return focusPlan(found.id);
  }

  function renderTimeline(payload) {
    planOriginals = {};
    stagedChanges = {};
    updateStagingBar();
    configureGantt(payload);
    if (!ganttReady) {
      installTurkishLocale();
      gantt.init('apsGanttEnj');
      ganttReady = true;
      installDragForensics();
      addTodayMarker();
    }
    gantt.clearAll();
    gantt.parse({ data: buildTasksFromPayload(payload), links: [] });
    fitGanttToShell();
    applyZoom(currentZoomKey);
    gantt.unselectTask();
  }

  function loadTimeline() {
    var url = CFG.timelineUrl || CFG.dataUrl;
    var qs = new URLSearchParams(window.location.search);
    if (qs.get('demo_multi') === '1') {
      url += (url.indexOf('?') >= 0 ? '&' : '?') + 'demo_multi=1';
    }
    return fetch(url, { method: 'GET', credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        timelinePayload = payload;
        renderTimeline(payload);
        return payload;
      });
  }

  function bindUi() {
    document.querySelectorAll('#apsZoomGroup .aps-btn[data-zoom]').forEach(function (btn) {
      btn.addEventListener('click', function () { applyZoom(btn.dataset.zoom); });
    });

    var zoomIn = document.getElementById('apsZoomIn');
    var zoomOut = document.getElementById('apsZoomOut');
    if (zoomIn) zoomIn.addEventListener('click', function () { zoomStep(1); });
    if (zoomOut) zoomOut.addEventListener('click', function () { zoomStep(-1); });

    var floatIn = document.getElementById('apsFloatZoomIn');
    var floatOut = document.getElementById('apsFloatZoomOut');
    if (floatIn) floatIn.addEventListener('click', function () { zoomStep(1); });
    if (floatOut) floatOut.addEventListener('click', function () { zoomStep(-1); });

    document.getElementById('apsStagingDiscard').addEventListener('click', discardAllStaged);
    document.getElementById('apsStagingApply').addEventListener('click', showApplyPreview);
    document.getElementById('apsApplyClose').addEventListener('click', hideApplyModal);
    document.getElementById('apsConflictOk').addEventListener('click', hideConflictModal);
    document.getElementById('apsDrawerClose').addEventListener('click', closeDrawer);
    document.getElementById('apsDrawerBackdrop').addEventListener('click', closeDrawer);

    var navPrev = document.getElementById('apsNavPrev');
    var navNext = document.getElementById('apsNavNext');
    var navStart = document.getElementById('apsNavStart');
    var navEnd = document.getElementById('apsNavEnd');
    if (navPrev) navPrev.addEventListener('click', function () { navDays(-1); });
    if (navNext) navNext.addEventListener('click', function () { navDays(1); });
    if (navStart) navStart.addEventListener('click', function () {
      scrollToDate(gantt.config.start_date);
    });
    if (navEnd) navEnd.addEventListener('click', function () {
      scrollToDate(gantt.config.end_date);
    });

    var picker = document.getElementById('apsDatePicker');
    if (picker) {
      picker.addEventListener('change', function () {
        var d = parseDt(picker.value + ' 08:00:00');
        if (d) scrollToDate(d);
      });
    }

    var search = document.getElementById('apsSearchInput');
    if (search) {
      search.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          searchBySipNo(search.value);
        }
      });
      search.addEventListener('input', function () {
        if (String(search.value).trim().length >= 4) {
          searchBySipNo(search.value);
        }
      });
    }

    window.addEventListener('resize', function () {
      fitGanttToShell();
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && ghostDrag.active) {
        e.preventDefault();
        cancelGhostDrag();
      }
    });
  }

  window.__apsDragMetrics = function () {
    return JSON.parse(JSON.stringify(dragMetrics));
  };

  window.__apsDragProfile = function () {
    var times = dragHandlerTimes.slice();
    times.sort(function (a, b) { return a - b; });
    var p95 = times.length ? times[Math.floor(times.length * 0.95)] : 0;
    var max = times.length ? times[times.length - 1] : 0;
    var visualMeasures = performance.getEntriesByName('aps-drag-visual', 'measure');
    var visualMs = visualMeasures.map(function (m) { return m.duration; });
    visualMs.sort(function (a, b) { return a - b; });
    return {
      metrics: JSON.parse(JSON.stringify(dragMetrics)),
      handlerMs: { count: times.length, p95: p95, max: max, avg: times.length ? times.reduce(function (a, b) { return a + b; }, 0) / times.length : 0 },
      visualMs: { count: visualMs.length, p95: visualMs.length ? visualMs[Math.floor(visualMs.length * 0.95)] : 0, max: visualMs.length ? visualMs[visualMs.length - 1] : 0 },
      flags: JSON.parse(JSON.stringify(dragFlags)),
      rectCacheSize: resourceRectCache.length,
    };
  };

  window.__apsDragFlags = function () {
    return JSON.parse(JSON.stringify(dragFlags));
  };

  window.__apsSetDragFlags = function (patch) {
    Object.keys(patch || {}).forEach(function (k) {
      if (dragFlags[k] !== undefined) dragFlags[k] = !!patch[k];
    });
    gantt.config.autoscroll = dragFlags.autoscroll;
    gantt.config.show_tooltips = dragFlags.tooltip;
    gantt.config.round_dnd_dates = dragFlags.snap;
  };

  window.__apsResourceRectCache = function () {
    return resourceRectCache.map(function (r) {
      return { id: r.id, top: r.top, bottom: r.bottom };
    });
  };

  window.__apsDragTargetResource = function () {
    return dragTargetResource;
  };

  window.__apsGhostVisible = function () {
    return !!(ghostDrag.active && ghostDrag.el && ghostDrag.el.parentNode);
  };

  window.__apsGhostMetrics = function () {
    var ghostY = ghostDrag.lastGhostY;
    var gap = null;
    if (ghostDrag.el && ghostDrag.anchorSet) {
      var r = ghostDrag.el.getBoundingClientRect();
      var ax = r.left + ghostDrag.anchorOffsetX;
      var ay = r.top + ghostDrag.anchorOffsetY;
      gap = Math.hypot(ghostDrag.pointerX - ax, ghostDrag.pointerY - ay);
    } else if (ghostY != null && ghostDrag.pointerY != null) {
      gap = Math.abs(ghostDrag.pointerY - ghostY);
    }
    return {
      active: ghostDrag.active,
      visible: window.__apsGhostVisible(),
      pointerY: ghostDrag.pointerY,
      ghostY: ghostY,
      gap: gap,
      anchorSet: ghostDrag.anchorSet,
      targetResource: dragTargetResource,
      samples: ghostDrag.samples.slice(-8),
    };
  };

  window.__apsGhostCoordinateTrace = function () {
    return ghostDrag.samples.slice();
  };

  window.__apsNativeBarDimmed = function () {
    if (ghostDrag.nativeBarEl && ghostDrag.nativeBarEl.classList.contains('aps-native-dim')) return true;
    var dim = document.querySelector('.gantt_task_line.aps-native-dim');
    return !!dim;
  };

  window.__apsWorkspaceMetrics = function () {
    var wrap = document.getElementById('apsWrap');
    var shell = document.getElementById('apsGanttShell');
    var ganttEl = document.getElementById('apsGanttEnj');
    var grid = document.querySelector('.gantt_grid');
    return {
      wrapHeight: wrap ? wrap.getBoundingClientRect().height : 0,
      shellHeight: shell ? shell.getBoundingClientRect().height : 0,
      ganttHeight: ganttEl ? ganttEl.getBoundingClientRect().height : 0,
      viewportHeight: window.innerHeight,
      gridWidth: grid ? grid.getBoundingClientRect().width : 0,
      emptyBelow: shell && ganttEl
        ? shell.getBoundingClientRect().bottom - ganttEl.getBoundingClientRect().bottom
        : 0,
    };
  };

  window.__apsIsDragging = function () {
    return isDragging;
  };

  window.__apsPostWriteCount = function () { return 0; };

  window.__apsStagedChanges = function () {
    return Object.values(stagedChanges).map(function (c) {
      return {
        plan_id: c.plan_id,
        old_resource: c.old_resource,
        new_resource: c.new_resource,
        old_start: c.old_start ? c.old_start.toISOString() : null,
        old_end: c.old_end ? c.old_end.toISOString() : null,
        proposed_start: c.proposed_start ? c.proposed_start.toISOString() : null,
        proposed_end: c.proposed_end ? c.proposed_end.toISOString() : null,
        change_type: c.change_type.slice(),
        conflict: c.conflict,
        downstream_impact: c.downstream_impact.slice(),
      };
    });
  };

  window.__apsStagingBarVisible = function () {
    var bar = document.getElementById('apsStagingBar');
    return bar && bar.style.display !== 'none';
  };

  window.__apsStagingCount = function () {
    return Object.keys(stagedChanges).length;
  };

  window.__apsDrawerOpen = function () {
    return isDrawerOpen();
  };

  window.__apsDiscardStaging = function () {
    discardAllStaged();
  };

  window.__apsApplyPreview = function () {
    showApplyPreview();
  };

  window.__apsChangeModalVisible = function () {
    var m = document.getElementById('apsChangeModal');
    return m && m.style.display !== 'none';
  };

  window.__apsApplyModalVisible = function () {
    var m = document.getElementById('apsApplyModal');
    return m && m.style.display !== 'none';
  };

  window.__apsZoomMetrics = function () {
    var bg = document.querySelector('.gantt_task_bg');
    var scale = document.querySelector('.gantt_scale_line');
    return {
      zoom: currentZoomKey,
      minColumnWidth: gantt.config.min_column_width,
      timelineScrollWidth: bg ? bg.scrollWidth : 0,
      timelineClientWidth: bg ? bg.clientWidth : 0,
      scaleText: scale ? scale.innerText.slice(0, 200) : '',
    };
  };

  window.__apsApplyZoom = function (key) { applyZoom(key); };

  // Expose moveEmbeddedPlan for automated drag simulation in acceptance tests.
  window.__apsMoveEmbeddedPlan = function (fromSlotId, toSlotId, planId) {
    return moveEmbeddedPlan(fromSlotId, toSlotId, planId);
  };

  // Combined helper: move + stage (mirrors what a completed ghost drag does).
  window.__apsDragAndStage = function (fromSlotId, toSlotId, planId) {
    var resolvedPlanId = planId;
    if (!resolvedPlanId) {
      var fromTask = gantt.getTask(fromSlotId);
      if (fromTask) resolvedPlanId = fromTask.aps_primary_plan_id || (fromTask.aps_plan && fromTask.aps_plan.id);
    }
    var newId = moveEmbeddedPlan(fromSlotId, toSlotId, resolvedPlanId);
    var task  = gantt.getTask(newId);
    stagePlanChange(task);
    return newId;
  };

  window.__apsProcessTree = function () {
    var rows = [];
    gantt.eachTask(function (t) {
      rows.push({ id: t.id, text: t.text, type: t.aps_type, parent: t.parent });
    });
    return rows;
  };

  window.__apsSearchPlan = function (q) {
    return searchBySipNo(q);
  };

  window.__apsRowMetrics = function () {
    var gridRows = 0;
    var opGridRows = 0;
    gantt.eachTask(function (t) {
      if (t.aps_type !== 'enj_plan') gridRows += 1;
    });
    document.querySelectorAll('.gantt_grid_data .gantt_row').forEach(function (row) {
      if (window.getComputedStyle(row).display === 'none') return;
      var tid = row.getAttribute('data-task-id') || row.getAttribute('task_id') || '';
      if (String(tid).indexOf('plan-') === 0) opGridRows += 1;
    });
    return { gridRows: gridRows, operationGridRows: opGridRows };
  };

  window.__apsPlansOnResource = function (resourceId) {
    var ids = [];
    var slot = gantt.getTask(resourceId);
    if (slot && slot.aps_primary_plan_id) ids.push(slot.aps_primary_plan_id);
    gantt.eachTask(function (t) {
      if (t.aps_type === 'enj_plan' && t.parent === resourceId) ids.push(t.id);
    });
    return ids;
  };

  window.__apsTimelineRowY = function (resourceId) {
    var y = null;
    document.querySelectorAll('.gantt_task_row').forEach(function (row) {
      var tid = row.getAttribute('task_id') || row.getAttribute('data-task-id') || '';
      if (tid === resourceId) {
        var r = row.getBoundingClientRect();
        y = r.top + r.height / 2;
      }
    });
    return y;
  };

  window.__apsBarMetrics = function (resourceId) {
    return {
      resourceY: window.__apsTimelineRowY(resourceId),
      bars: (function () {
        var bars = [];
        document.querySelectorAll('.gantt_task_line.aps-enj-task').forEach(function (el) {
          var r = el.getBoundingClientRect();
          bars.push({
            text: (el.textContent || '').trim().slice(0, 30),
            y: r.top + r.height / 2,
            cls: el.className,
          });
        });
        return bars;
      })(),
    };
  };

  window.__apsWorkingCellStats = function () {
    return {
      working: document.querySelectorAll('.gantt_task_cell.aps-working').length,
      closed: document.querySelectorAll('.gantt_task_cell.aps-closed, .gantt_task_cell.weekend').length,
      todayTint: document.querySelectorAll('.gantt_task_cell.aps-today-col').length,
    };
  };

  window.__apsToggleProcess = function (procId) {
    if (gantt.getTask(procId).$open) gantt.close(procId);
    else gantt.open(procId);
    fitGanttToShell();
    return gantt.getTask(procId).$open;
  };

  document.addEventListener('DOMContentLoaded', function () {
    bindUi();
    loadTimeline().catch(function (err) {
      console.error('APS timeline load failed', err);
    });
  });
})();
