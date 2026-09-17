/* AKTİF KALIPLAR — PHASE_4  (scoped, no global pollution) */
'use strict';
(function () {

var FX = window.AK_FIXTURE;
var filtered = [], curPage = 1, PAGE_SIZE = 10, selSeq = null;

/* ── HELPERS ── */
function esc(v) { return String(v == null ? '—' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function akFmtSn(v) {
  if (v == null || v === '') return '—';
  var n = Number(v);
  if (isNaN(n)) return esc(v);
  var s = String(n);
  if (s.indexOf('.') >= 0) s = s.replace('.', ',');
  return s + ' sn';
}
function akFmtGram(v) {
  if (v == null || v === '') return '—';
  return esc(v) + ' g';
}

/* ── TÜRKÇE NORMALİZASYON (merkezi) ── */
function akTrLower(s) {
  if (!s) return '';
  return s.trim().split('').map(function (ch) {
    if (ch === 'İ') return 'i';
    if (ch === 'I') return 'ı';
    if (ch === 'Ş') return 'ş';
    if (ch === 'Ğ') return 'ğ';
    if (ch === 'Ü') return 'ü';
    if (ch === 'Ö') return 'ö';
    if (ch === 'Ç') return 'ç';
    return ch.toLowerCase();
  }).join('');
}
function akTrUpperFirst(s) {
  if (!s) return '';
  var low = akTrLower(s);
  var c = low.charAt(0);
  if (c === 'i') return 'İ' + low.slice(1);
  if (c === 'ı') return 'I' + low.slice(1);
  return c.toUpperCase() + low.slice(1);
}
function akTrTitleWord(w) {
  if (!w) return '';
  return akTrUpperFirst(w.trim());
}
function akNormalizeProductType(raw) {
  if (!raw) return '';
  var s = raw.trim().replace(/\s*-\s*/g, ' - ').replace(/\s+/g, ' ');
  if (s.indexOf(' - ') >= 0) {
    return s.split(' - ').map(function (p) { return akTrTitleWord(p.trim()); }).filter(Boolean).join(' - ');
  }
  if (s.indexOf(' ') >= 0) {
    return s.split(/\s+/).map(function (p) { return akTrTitleWord(p); }).filter(Boolean).join(' ');
  }
  return akTrTitleWord(s);
}
function akNormKey(raw) {
  return akTrLower(akNormalizeProductType(raw));
}
function akDisplayProductType(r) {
  return r.product_variant || r.product_type_normalized || akNormalizeProductType(r.product_category || '');
}
function akProductFamily(r) {
  if (r.product_family) return r.product_family;
  var norm = akDisplayProductType(r);
  var low = akTrLower(norm);
  if (low.indexOf('patik') === 0) return 'Patik';
  if (low.indexOf('filet zenne') === 0 || low.indexOf('filet') === 0) return 'Filet';
  if (low.indexOf('eva taban') >= 0) return 'EVA Taban';
  if (low.indexOf('bebe') === 0) return 'Bebe';
  if (low.indexOf('fuspet') === 0 || low.indexOf('füspet') === 0 || low.indexOf('fuşpet') === 0) return 'Fuspet';
  if (low.indexOf('merdane') === 0) return 'Merdane';
  if (low === 'zenne') return 'Zenne';
  if (norm.indexOf(' - ') > 0) return norm.split(' - ')[0];
  return norm;
}
function akFamilyKey(fam) {
  return akTrLower(fam || '');
}
function akComposeProductType(family, variant) {
  var fam = (family || '').trim();
  var vari = (variant || '').trim();
  if (!fam) return '';
  if (!vari || akTrLower(vari) === akTrLower(fam)) return akNormalizeProductType(fam);
  if (akTrLower(vari).indexOf(akTrLower(fam)) === 0) return akNormalizeProductType(vari);
  return akNormalizeProductType(fam + ' - ' + vari);
}
function akKnownFamilies() {
  return ['Patik', 'Filet', 'Bebe', 'EVA Taban', 'Fuspet', 'Merdane', 'Zenne'];
}
function akPopulateFamilySelect(el, selected) {
  if (!el) return;
  el.innerHTML = '';
  akKnownFamilies().forEach(function (f) {
    var o = document.createElement('option');
    o.value = f; o.textContent = f;
    el.appendChild(o);
  });
  if (selected) el.value = selected;
}
function akSplitFamilyVariant(r) {
  var fam = akProductFamily(r);
  var vari = akDisplayProductType(r);
  if (vari === fam) return { family: fam, variant: '' };
  return { family: fam, variant: vari };
}
function akParseAsorti(asorti) {
  if (!asorti) return { bas: '', bit: '' };
  var m = String(asorti).match(/^(\d+)\s*-\s*(\d+)$/);
  return m ? { bas: m[1], bit: m[2] } : { bas: '', bit: '' };
}
function akSeriNumara(s) {
  return s.numara_asorti_display || s.numara_asorti || s.seri_label || '—';
}
function akKalipAdedi(s) {
  if (s.kalip_adedi != null) return s.kalip_adedi + ' adet';
  if (s.kalip_adedi_source === 'UNRESOLVED' || s.goz_adet == null) return 'Adet doğrulanmalı';
  return '—';
}
function akSeriCikis(s, r) {
  var c = s.kalip_cikisi != null ? s.kalip_cikisi : (r && r.cift_miktari != null ? r.cift_miktari : null);
  return c != null ? c + ' çift' : '—';
}
function akRecordPhysicalTotal(r) {
  if (!r.seri_dagilimi || !r.seri_dagilimi.length) return { total: null, complete: false };
  var sum = 0;
  for (var i = 0; i < r.seri_dagilimi.length; i++) {
    var q = r.seri_dagilimi[i].kalip_adedi;
    if (q == null) return { total: null, complete: false };
    sum += q;
  }
  return { total: sum, complete: true };
}

function pillCls(r) {
  if (!r.durum) return 'ak-review';
  return { AKTIF: 'ak-ok', NUMUNE: 'ak-sample', PASIF: 'ak-passive', TASLAK: 'ak-draft' }[r.durum] || 'ak-review';
}
function pillLbl(r) {
  if (!r.durum) return 'İnceleme Gerekli';
  return { AKTIF: 'Aktif', NUMUNE: 'Numune', PASIF: 'Pasif', TASLAK: 'Taslak' }[r.durum] || r.durum;
}
function akProductionRecords() {
  return (FX.records || []).filter(function (r) { return r.record_origin === 'IMPORTED' && !r.is_test_record; });
}
function akImportedEvaCount() {
  return (FX.records || []).filter(function (r) {
    return r.material_group === 'EVA' && r.record_origin === 'IMPORTED' && !r.is_test_record;
  }).length;
}
function fReview(r) {
  if (r.review_status === 'READY_FOR_PLANNING') return 'Planlamada kullanılabilir';
  if (r.review_status === 'READY_FOR_LIBRARY')  return 'Kütüphaneye hazır';
  return 'Planlamada kullanılmadan önce inceleme gerekli';
}
function fBlock(r) {
  var raw = r.activation_block_reason || '', seen = {}, parts = [];
  raw.split(';').forEach(function (s) {
    s = s.trim(); if (!s) return;
    var m;
    if      (s.indexOf('component_role') >= 0)  m = 'Fiziksel rol doğrulanmalı';
    else if (s.indexOf('legacy_mapping') >= 0)  m = 'Mevcut Kalıp Master eşleşmesi bekliyor';
    else if (s.indexOf('product_category') >= 0) m = 'Ürün kategorisi eksik';
    else if (s.indexOf('passive') >= 0 || s.indexOf('not_active') >= 0) m = 'Pasif kalıp planlamada seçilemez';
    else m = s;
    if (!seen[m]) { seen[m] = 1; parts.push(m); }
  });
  return parts.join(' · ');
}
function fRole(r) {
  var cr = r.component_role || '';
  if (cr === 'UNRESOLVED') return 'Doğrulanmadı';
  return { GOVDE: 'Gövde', ATKI: 'Atkı', GOVDE_ATKI: 'Gövde + Atkı' }[cr] || cr || '—';
}

/* ── INIT ── */
function akDoInit() {
  FX = window.AK_FIXTURE;
  if (!FX || !FX.records) {
    var el = document.getElementById('akRoot');
    if (el) el.innerHTML = '<div style="color:red;padding:20px">Fixture yüklenemedi</div>';
    return;
  }
  initSegments();
  renderKpis();
  initFilters();
  applyFilters();
  if (FX.records.length) selectRecord(FX.records[0].source_seq);
}

// Fixture fetch'ten sonra çağrılır (template'den)
window.akInit = akDoInit;

// Eğer fixture zaten hazırsa (sayfa tekrar yüklenirse) hemen başlat
document.addEventListener('DOMContentLoaded', function () {
  if (window.AK_FIXTURE) akDoInit();
});

/* ── KOMPAKT EVA/POLİ ── */
function initSegments() {
  var cnt = akImportedEvaCount();
  var ec = document.getElementById('akSegEvaCount');
  if (ec) ec.textContent = cnt;
  var se = document.getElementById('akSegEva');
  var sp = document.getElementById('akSegPoli');
  if (se) se.onclick = function () {
    se.classList.add('active'); if (sp) sp.classList.remove('active');
    document.getElementById('akEvaPanel').style.display = '';
    document.getElementById('akPoliPanel').style.display = 'none';
  };
  if (sp) sp.onclick = function () {
    sp.classList.add('active'); if (se) se.classList.remove('active');
    document.getElementById('akEvaPanel').style.display = 'none';
    document.getElementById('akPoliPanel').style.display = 'block';
  };
  akPopulateFamilySelect(document.getElementById('akFFamily'), 'Patik');
  akPopulateFamilySelect(document.getElementById('akEditFamily'), 'Patik');
}

/* ── KPI ── */
function renderKpis() {
  var rs = akProductionRecords();
  var data = [
    { ico: '📦', val: rs.length, lbl: 'Kalıp Kaydı', note: 'Kalıp kaydı ≠ fiziksel kalıp adedi. Fiziksel toplam seri detayında.' },
    { ico: '✅', val: rs.filter(function (r) { return r.durum === 'AKTIF'; }).length, lbl: 'Aktif' },
    { ico: '🧪', val: rs.filter(function (r) { return r.durum === 'NUMUNE'; }).length, lbl: 'Numune' },
    { ico: '⏸',  val: rs.filter(function (r) { return r.durum === 'PASIF'; }).length, lbl: 'Pasif' },
    { ico: '📝', val: rs.filter(function (r) { return r.durum === 'TASLAK'; }).length, lbl: 'Taslak' },
    { ico: '🖼',  val: rs.filter(function (r) { return !!r.image_url; }).length, lbl: 'Görselli' },
  ];
  var el = document.getElementById('akKpiRow');
  if (!el) return;
  el.innerHTML = data.map(function (d) {
    return '<div class="ak-kpi"><span class="ak-kpi-icon">' + d.ico + '</span>'
      + '<div><div class="ak-kpi-val">' + d.val + '</div>'
      + '<div class="ak-kpi-lbl">' + d.lbl + '</div>'
      + (d.note ? '<div class="ak-kpi-note">' + esc(d.note) + '</div>' : '')
      + '</div></div>';
  }).join('');
}

/* ── FILTERS ── */
function initFilters() {
  var fd = document.getElementById('akFDurum');
  if (fd) {
    var o = document.createElement('option'); o.value = 'EKSIK'; o.textContent = 'İnceleme Gerekli'; fd.appendChild(o);
    ['AKTIF', 'NUMUNE', 'PASIF', 'TASLAK'].forEach(function (d) {
      var o = document.createElement('option'); o.value = d;
      o.textContent = { AKTIF: 'Aktif', NUMUNE: 'Numune', PASIF: 'Pasif', TASLAK: 'Taslak' }[d]; fd.appendChild(o);
    });
  }
  var ft = document.getElementById('akFTip');
  if (ft) {
    var families = {};
    FX.records.forEach(function (r) {
      var fam = akProductFamily(r);
      if (!fam) fam = 'Belirsiz';
      var key = akFamilyKey(fam);
      if (!families[key]) families[key] = fam;
    });
    Object.keys(families).sort(function (a, b) { return families[a].localeCompare(families[b], 'tr'); }).forEach(function (k) {
      var o = document.createElement('option'); o.value = k; o.textContent = families[k]; ft.appendChild(o);
    });
  }
  ['akFSearch', 'akFDurum', 'akFTip', 'akFNumara', 'akFGorsel'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener('input',  function () { curPage = 1; applyFilters(); });
      el.addEventListener('change', function () { curPage = 1; applyFilters(); });
    }
  });
  var clr = document.getElementById('akFClear');
  if (clr) clr.onclick = function () {
    ['akFSearch', 'akFNumara'].forEach(function (id) { var el = document.getElementById(id); if (el) el.value = ''; });
    ['akFDurum', 'akFTip'].forEach(function (id) { var el = document.getElementById(id); if (el) el.value = ''; });
    var g = document.getElementById('akFGorsel'); if (g) g.checked = false;
    curPage = 1; applyFilters();
  };
  var dc = document.getElementById('akDetailClose');
  if (dc) dc.onclick = closeDetailPanel;
  var bd = document.getElementById('akBackdrop');
  if (bd) bd.onclick = closeDetailPanel;
}

function applyFilters() {
  var q = (document.getElementById('akFSearch') || {}).value || '';
  var d = (document.getElementById('akFDurum')  || {}).value || '';
  var t = (document.getElementById('akFTip')    || {}).value || '';
  var n = (document.getElementById('akFNumara') || {}).value || '';
  var g = ((document.getElementById('akFGorsel') || {}).checked);
  q = q.trim().toLowerCase(); n = n.trim().toLowerCase();
  filtered = akProductionRecords().filter(function (r) {
    if (q && !(r.model_kod || '').toLowerCase().includes(q) && !(r.visible_mold_code || '').toLowerCase().includes(q)) return false;
    if (d) {
      if (d === 'EKSIK' && r.durum) return false;
      if (d !== 'EKSIK' && r.durum !== d) return false;
    }
    if (t && akFamilyKey(akProductFamily(r)) !== t) return false;
    if (n && !(r.asorti || '').toLowerCase().includes(n)) return false;
    if (g && !r.image_url) return false;
    return true;
  });
  if (selSeq && !filtered.some(function (r) { return r.source_seq === selSeq; })) {
    selSeq = filtered.length ? filtered[0].source_seq : null;
  }
  renderTable();
  if (selSeq) selectRecord(selSeq);
  else {
    var body = document.getElementById('akDetailBody');
    if (body) body.innerHTML = '<div style="color:var(--ak-muted);font-size:12px;padding:24px 0;text-align:center;">Listeden bir kalıp seçin</div>';
  }
}

/* ── TABLE ── */
function renderTable() {
  var start = (curPage - 1) * PAGE_SIZE;
  var rows = filtered.slice(start, start + PAGE_SIZE);
  var tbody = document.getElementById('akTblBody');
  if (!tbody) return;
  tbody.innerHTML = rows.map(function (r) {
    var img = r.image_url
      ? '<img class="ak-thumb" src="' + esc(r.image_url) + '" alt="">'
      : '<div class="ak-thumb-ph"><span class="ak-thumb-ph-ico">📷</span>Görsel<br>yok</div>';
    var vb = r.variant_count > 1 ? '<div class="ak-var-badge">' + r.variant_count + ' varyant</div>' : '';
    var pc = pillCls(r), pl = pillLbl(r);
    return '<tr data-seq="' + r.source_seq + '"' + (selSeq === r.source_seq ? ' class="ak-sel"' : '') + '>'
      + '<td>' + img + '</td>'
      + '<td><span class="ak-model">' + esc(r.model_kod) + '</span></td>'
      + '<td><div class="ak-code">' + esc(r.visible_mold_code) + '</div>' + vb + '</td>'
      + '<td>' + esc(akDisplayProductType(r) || '—') + '</td>'
      + '<td>' + esc(r.asorti || '—') + '</td>'
      + '<td>' + (r.cift_miktari != null ? esc(r.cift_miktari) + ' çift' : '—') + '</td>'
      + '<td>' + (r.gramaj_gr != null ? esc(r.gramaj_gr) + ' g' : '—') + '</td>'
      + '<td><span class="ak-mat">' + esc(r.material_group || 'EVA') + '</span></td>'
      + '<td><span class="ak-pill ' + pc + '">' + pl + '</span></td>'
      + '<td><button class="ak-btn ak-btn-ghost ak-btn-sm ak-det-btn" data-seq="' + r.source_seq + '">Detay</button></td>'
      + '</tr>';
  }).join('');
  tbody.querySelectorAll('tr').forEach(function (tr) {
    tr.onclick = function (e) {
      if (e.target.classList.contains('ak-det-btn') || e.target.closest('.ak-det-btn')) return;
      selectRecord(+tr.dataset.seq);
    };
  });
  tbody.querySelectorAll('.ak-det-btn').forEach(function (b) {
    b.onclick = function (e) { e.stopPropagation(); selectRecord(+b.dataset.seq); };
  });
  var sm = document.getElementById('akTblSummary');
  if (sm) sm.textContent = 'Toplam ' + filtered.length + ' kalıp listeleniyor (evren: ' + akProductionRecords().length + ')';
  renderPagination();
}

function renderPagination() {
  var pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  var pg = document.getElementById('akPagination');
  if (!pg) return;
  var h = '<button class="ak-pg-arr" id="akPgPrev"' + (curPage <= 1 ? ' disabled' : '') + '>&#8249;</button>';
  for (var i = 1; i <= Math.min(pages, 7); i++)
    h += '<button class="ak-pg' + (i === curPage ? ' active' : '') + '" data-p="' + i + '">' + i + '</button>';
  h += '<button class="ak-pg-arr" id="akPgNext"' + (curPage >= pages ? ' disabled' : '') + '>&#8250;</button>';
  pg.innerHTML = h;
  pg.querySelectorAll('.ak-pg').forEach(function (b) { b.onclick = function () { curPage = +b.dataset.p; renderTable(); }; });
  var prev = document.getElementById('akPgPrev'); if (prev) prev.onclick = function () { if (curPage > 1) { curPage--; renderTable(); } };
  var next = document.getElementById('akPgNext'); if (next) next.onclick = function () { if (curPage < pages) { curPage++; renderTable(); } };
}

/* ── SELECT ── */
function selectRecord(seq) {
  selSeq = seq;
  document.querySelectorAll('#akTblBody tr').forEach(function (tr) {
    tr.classList.toggle('ak-sel', +tr.dataset.seq === seq);
  });
  var r = FX.records.find(function (x) { return x.source_seq === seq; });
  if (!r) return;
  renderDetail(r);
  if (window.innerWidth <= 1050) {
    var dp = document.getElementById('akDetailPanel');
    var bd = document.getElementById('akBackdrop');
    if (dp) dp.classList.add('open');
    if (bd) bd.classList.add('show');
  }
}
function closeDetailPanel() {
  var dp = document.getElementById('akDetailPanel');
  var bd = document.getElementById('akBackdrop');
  if (dp) dp.classList.remove('open');
  if (bd) bd.classList.remove('show');
}

/* ── DETAIL ── */
function renderDetail(r) {
  var notPlan = r.review_status !== 'READY_FOR_PLANNING';
  var heroImg = r.image_url
    ? '<img class="ak-hero-img" src="' + esc(r.image_url) + '" alt="">'
    : '<div class="ak-hero-ph"><span style="font-size:28px;opacity:.3">📷</span><span style="font-size:10px">Görsel yok</span></div>';
  var sysId = r.library_uuid
    ? r.library_uuid.split('-')[0].toUpperCase()
    : (r.legacy_enj_kalip_id ? 'MOLD-' + String(r.legacy_enj_kalip_id).padStart(6, '0') : '—');
  var alertHtml = '';
  if (r.durum === 'TASLAK') {
    var miss = [];
    if (!r.product_category && !r.product_family) miss.push('Ana ürün ailesi');
    if (!r.asorti) miss.push('Asorti');
    if (r.cift_miktari == null) miss.push('Çevrim Başına Çıkış (çift)');
    if (!r.seri_dagilimi || !r.seri_dagilimi.length) miss.push('Seri satırları');
    if (r.gramaj_gr == null) miss.push('Bir Çift Ürün Gramajı (g) — Gramaj doğrulanmalı');
    if (r.pisirme_suresi_sn == null) miss.push('Pişme Süresi (sn) — Pişme süresi doğrulanmalı');
    alertHtml += '<div class="ak-alert ak-draft-alert"><span class="ak-alert-ico">📝</span><span>Taslak kayıt'
      + (miss.length ? ' — eksik: ' + esc(miss.join(', ')) : '') + '. Planlamada seçilemez.</span></div>';
  }
  if (notPlan && r.durum !== 'TASLAK')
    alertHtml += '<div class="ak-alert"><span class="ak-alert-ico">⚠️</span><span>' + esc(fBlock(r)) + '</span></div>';
  var dh = document.querySelector('#akDetailPanel .ak-detail-head');
  if (dh) {
    dh.innerHTML = '<span class="ak-detail-title">Kalıp Detayı</span>'
      + '<div class="ak-detail-head-actions">'
      + '<button class="ak-btn ak-btn-primary ak-btn-sm" id="akEditBtn">Düzenle</button>'
      + '<button class="ak-close" id="akDetailClose" aria-label="Kapat">×</button>'
      + '</div>';
    document.getElementById('akEditBtn').onclick = function () { openEditDrawer(r); };
    document.getElementById('akDetailClose').onclick = closeDetailPanel;
  }
  var body = document.getElementById('akDetailBody');
  if (!body) return;
  body.innerHTML =
    '<div class="ak-hero">' + heroImg
    + '<div><div class="ak-hero-model">' + esc(r.model_kod) + '</div>'
    + '<div class="ak-hero-code">' + esc(r.visible_mold_code) + '</div>'
    + '<div class="ak-hero-badges">'
    + '<span class="ak-pill ' + pillCls(r) + '">' + pillLbl(r) + '</span>'
    + '<span class="ak-eva-badge">EVA</span>'
    + '</div></div></div>'
    + alertHtml
    + '<div class="ak-tabs" id="akDTabs">'
    + '<button class="ak-tab active" data-tab="genel">Genel</button>'
    + '<button class="ak-tab" data-tab="seri">Seri &amp; Kalıp Adedi</button>'
    + '<button class="ak-tab" data-tab="teknik">Teknik</button>'
    + '<button class="ak-tab" data-tab="bag">Bağlantılar</button>'
    + '<button class="ak-tab" data-tab="audit">Audit</button>'
    + '</div>'
    + '<div id="akTabContent"></div>'
    + '<div class="ak-plan-box">'
    + '<div class="ak-plan-title">🔗 Planlama Bağlantısı</div>'
    + '<div class="ak-plan-sub">Planlama &gt; Enjeksiyon &gt; Kalıp Seç</div>'
    + '<div id="akPlanList"></div>'
    + '</div>';
  document.querySelectorAll('#akDTabs .ak-tab').forEach(function (t) {
    t.onclick = function () { renderTab(r, t.dataset.tab); };
  });
  renderTab(r, 'genel');
  renderPlanList(r);
}

function renderTab(r, tab) {
  document.querySelectorAll('#akDTabs .ak-tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === tab); });
  var el = document.getElementById('akTabContent');
  if (!el) return;
  var sysId = r.library_uuid ? r.library_uuid.split('-')[0].toUpperCase() : (r.legacy_enj_kalip_id ? 'MOLD-' + String(r.legacy_enj_kalip_id).padStart(6, '0') : '—');
  if (tab === 'genel') {
    el.innerHTML = fg([
      ['Tip', akDisplayProductType(r)],
      ['Asorti / Numara', r.asorti],
      ['Kalıp (Sistem) ID', sysId],
      ['Atkı Ayrı Kalıbı', r.separate_upper_mold === null ? '—' : (r.separate_upper_mold ? 'Evet' : 'Hayır')],
      ['Çevrim Başına Çıkış', r.cift_miktari != null ? r.cift_miktari + ' çift' : '—'],
      ['Bir Çift Ürün Gramajı (g)', akFmtGram(r.gramaj_gr)],
      ['Gramaj Referans Numarası', r.gramaj_ref_numara || '—'],
      ['Pişme Süresi (sn)', akFmtSn(r.pisirme_suresi_sn)],
      ['Kalıp Grubu', r.material_group || 'EVA'],
    ]) + (r.not ? '<div class="ak-note"><span class="ak-note-ico">📄</span><span>' + esc(r.not) + '</span></div>' : '');
  } else if (tab === 'seri') {
    el.innerHTML = seriesTbl(r);
  } else if (tab === 'teknik') {
    el.innerHTML = fg([
      ['Çevrim Başına Çıkış', r.cift_miktari != null ? r.cift_miktari + ' çift' : '—'],
      ['Bir Çift Ürün Gramajı (g)', akFmtGram(r.gramaj_gr)],
      ['Gramaj Referans Numarası', r.gramaj_ref_numara || '—'],
      ['Pişme Süresi (sn)', akFmtSn(r.pisirme_suresi_sn)],
      ['Bileşen Rolü', fRole(r)],
      ['Varyant Sayısı', r.variant_count || 1],
    ]) + (r.not ? '<div class="ak-note"><span class="ak-note-ico">📄</span><span>' + esc(r.not) + '</span></div>' : '');
  } else if (tab === 'audit') {
    el.innerHTML = '<div style="font-size:12px;color:var(--ak-muted);padding:8px 0">Audit yükleniyor…</div>';
    if (r.library_uuid) {
      fetch('/planlama/aktif-kaliplar/audit/' + encodeURIComponent(r.library_uuid))
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var rows = (data.audit || []);
          if (!rows.length) {
            el.innerHTML = '<div style="font-size:12px;color:var(--ak-muted);padding:8px 0">Audit kaydı yok</div>';
            return;
          }
          el.innerHTML = '<div class="ak-audit-list">' + rows.map(function (a) {
            return '<div class="ak-audit-item"><strong>' + esc(a.action) + '</strong> · '
              + esc(a.changed_at || '') + '<br><span style="color:var(--ak-muted)">'
              + esc(a.changed_by || '') + ' — ' + esc(a.change_reason || '') + '</span></div>';
          }).join('') + '</div>';
        });
    }
  } else {
    var leg = r.legacy_enj_kalip_id ? 'Kalıp Master kaydı: #' + esc(r.legacy_enj_kalip_id) : 'Mevcut Kalıp Master eşleşmesi bekliyor';
    el.innerHTML = fg([
      ['Kalıp Master Durumu', leg],
      ['Planlama Uygunluğu', fReview(r)],
    ]) + (r.variant_count > 1
      ? '<div class="ak-note"><span class="ak-note-ico">🔢</span><span>Bu kalıp kodunda <strong>' + r.variant_count + ' varyant</strong> bulunuyor.</span></div>'
      : '');
  }
}

function fg(pairs) {
  return '<div class="ak-field-grid">'
    + pairs.map(function (p) {
      return '<div class="ak-field"><label>' + esc(p[0]) + '</label><span>' + esc(p[1] != null ? p[1] : '—') + '</span></div>';
    }).join('')
    + '</div>';
}

function seriesTbl(r) {
  if (!r.seri_dagilimi || !r.seri_dagilimi.length)
    return '<div style="font-size:12px;color:var(--ak-muted);padding:8px 0">Seri verisi yok</div>';
  var rows = r.seri_dagilimi.map(function (s) {
    return '<tr><td>' + esc(String(akSeriNumara(s))) + '</td>'
      + '<td>' + esc(String(akKalipAdedi(s))) + '</td>'
      + '<td>' + esc(String(akSeriCikis(s, r))) + '</td></tr>';
  }).join('');
  var phys = akRecordPhysicalTotal(r);
  var summary;
  if (phys.complete) {
    summary = '<div class="ak-seri-summary"><strong>Toplam Fiziksel Kalıp:</strong> ' + phys.total + ' adet</div>';
  } else {
    summary = '<div class="ak-seri-summary ak-seri-summary-warn">Toplam fiziksel kalıp kesinleştirilemedi — eksik adet bilgisi var</div>';
  }
  return '<div class="ak-series-wrap"><table class="ak-series-tbl ak-series-vtbl"><thead><tr>'
    + '<th>Numara / Asorti</th><th>Kalıp Adedi</th><th>Çevrim Başına Çıkış</th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div>' + summary;
}

function renderPlanList(r) {
  var el = document.getElementById('akPlanList');
  if (!el) return;
  var planEnabled = FX.meta && FX.meta.plan_selection_enabled === true;
  if (!planEnabled) {
    el.innerHTML = '<div class="ak-plan-disabled-note">Planlama bağlantısı kapalı.</div>';
    return;
  }
  // Seçilebilir mi?
  if (r.review_status === 'READY_FOR_PLANNING' && r.durum === 'AKTIF') {
    var variantList = akProductionRecords().filter(function (p) {
      return p.model_kod === r.model_kod && p.material_group === 'EVA'
        && p.durum === 'AKTIF' && p.review_status === 'READY_FOR_PLANNING';
    });
    var listHtml = variantList.map(function (p) {
      return '<div class="ak-plan-item"><div class="ak-plan-code">' + esc(p.visible_mold_code) + '</div>'
        + '<button class="ak-btn-plan" disabled>Seç</button></div>';
    }).join('');
    el.innerHTML = '<div class="ak-plan-ok-note">Bu kalıp Plan Oluştur ekranında seçilebilir.</div>' + listHtml;
    return;
  }
  // Bloke
  var blockMsg = fBlock(r);
  if (!blockMsg) {
    if (r.durum === 'TASLAK') blockMsg = 'Taslak kayıt planlamada seçilemez.';
    else if (r.durum === 'PASIF') blockMsg = 'Pasif kalıp planlamada seçilemez.';
    else blockMsg = 'Bu kalıp planlamada kullanılmadan önce inceleme gerekli.';
  }
  el.innerHTML = '<div class="ak-plan-block-note">⚠️ ' + esc(blockMsg) + '</div>';
}

function reloadFixture(cb) {
  fetch('/planlama/aktif-kaliplar/fixture.json')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      FX = data;
      initSegments();
      renderKpis();
      applyFilters();
      if (typeof cb === 'function') cb();
    })
    .catch(function (e) { console.error('Fixture reload error:', e); });
}

/* ══════════════════════════════════════════════════════════════════════════
   YENİ KALIP DRAWER
   ══════════════════════════════════════════════════════════════════════════ */

// ── helpers ──────────────────────────────────────────────────────────────────
function showToast(msg, type) {
  var el = document.createElement('div');
  el.className = 'ak-toast ' + (type || '');
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(function () { el.classList.add('show'); });
  setTimeout(function () {
    el.classList.remove('show');
    setTimeout(function () { el.parentNode && el.parentNode.removeChild(el); }, 300);
  }, 3200);
}

function getVal(id) {
  var el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

function setErr(id, msg) {
  var el = document.getElementById(id);
  if (el) el.textContent = msg;
}

function clearErrs() {
  ['akErrModel','akErrMoldCode','akErrFamily','akErrAsBas','akErrAsBit',
   'akErrCift','akErrGramaj','akErrImage'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.textContent = '';
  });
  document.querySelectorAll('#akNewMoldForm .ak-invalid').forEach(function (el) {
    el.classList.remove('ak-invalid');
  });
}

function markInvalid(inputId, errId, msg) {
  var el = document.getElementById(inputId);
  if (el) el.classList.add('ak-invalid');
  setErr(errId, msg);
}

// ── Yeni Kalıp drawer open/close ─────────────────────────────────────────────
var _formDrawerOpen = false;

function openFormDrawer() {
  document.getElementById('akDrawer').classList.add('open');
  document.getElementById('akDrawerBackdrop').classList.add('show');
  document.body.style.overflow = 'hidden';
  _formDrawerOpen = true;
  clearErrs();
  resetForm();
  addSeriesRow();
  updateFormReadiness();
}

function closeFormDrawer() {
  document.getElementById('akDrawer').classList.remove('open');
  document.getElementById('akDrawerBackdrop').classList.remove('show');
  document.body.style.overflow = '';
  _formDrawerOpen = false;
}

function resetForm() {
  var frm = document.getElementById('akNewMoldForm');
  if (frm) frm.reset();
  // Malzeme grubu varsayılan
  var evaRadio = frm && frm.querySelector('[name=material_group][value=EVA]');
  if (evaRadio) evaRadio.checked = true;
  // Poli uyarı gizle
  var pw = document.getElementById('akPoliWarn');
  if (pw) pw.classList.add('ak-hidden');
  // Görsel önizleme gizle
  var prev = document.getElementById('akImagePreview');
  if (prev) { prev.classList.add('ak-hidden'); prev.innerHTML = ''; }
  // Seri satırlarını sıfırla
  var rows = document.getElementById('akSeriesRows');
  if (rows) rows.innerHTML = '';
  // Hint sıfırla
  var hint = document.getElementById('akMoldCodeHint');
  if (hint) hint.textContent = '';
  // Save butonunu etkinleştir
  var sv = document.getElementById('akMoldSave');
  if (sv) { sv.disabled = false; sv.textContent = 'Kalıbı Kaydet'; }
}

// ── Seri satırı yönetimi ────────────────────────────────────────────────────
var _seriesCount = 0;

function addSeriesRow(label, qty, cikis) {
  _seriesCount++;
  var cont = document.getElementById('akSeriesRows');
  if (!cont) return;

  // İlk satırda header ekle
  if (_seriesCount === 1) {
    var hdr = document.createElement('div');
    hdr.className = 'ak-series-row-header';
    hdr.id = 'akSeriesHeader';
    hdr.innerHTML = [
      '<span class="ak-series-col-label">Numara / Asorti</span>',
      '<span class="ak-series-col-label">Kalıp Adedi</span>',
      '<span class="ak-series-col-label">Çevrim Başına Çıkış</span>',
      '<span></span>'
    ].join('');
    cont.appendChild(hdr);
  }

  var row = document.createElement('div');
  row.className = 'ak-series-row';
  row.dataset.idx = _seriesCount;
  row.innerHTML = [
    '<input type="text" class="ak-input ak-s-label" placeholder="örn: 23/24" value="' + esc(label || '') + '" maxlength="30">',
    '<input type="number" class="ak-input ak-s-qty" placeholder="1" value="' + (qty != null ? qty : '') + '" min="1" max="32">',
    '<input type="number" class="ak-input ak-s-cikis" placeholder="2" value="' + (cikis != null ? cikis : '') + '" min="1" max="8">',
    '<button type="button" class="ak-remove-row" title="Satırı kaldır">×</button>'
  ].join('');
  cont.appendChild(row);
  row.querySelector('.ak-remove-row').addEventListener('click', function () {
    cont.removeChild(row);
    if (!cont.querySelectorAll('.ak-series-row').length) {
      var h = document.getElementById('akSeriesHeader');
      if (h) cont.removeChild(h);
      _seriesCount = 0;
    }
    updateFormReadiness();
  });
  row.querySelectorAll('input').forEach(function (inp) {
    inp.addEventListener('input', updateFormReadiness);
    inp.addEventListener('change', updateFormReadiness);
  });
  updateFormReadiness();
}

function bindSeriesSectionInvalid(invalid) {
  var sec = document.getElementById('akSeriesSection');
  if (sec) sec.classList.toggle('ak-section-invalid', !!invalid);
}

function collectSeriesRows() {
  var rows = document.querySelectorAll('#akSeriesRows .ak-series-row');
  var result = [];
  rows.forEach(function (r) {
    var lbl = r.querySelector('.ak-s-label');
    var qty = r.querySelector('.ak-s-qty');
    var cik = r.querySelector('.ak-s-cikis');
    if (lbl && lbl.value.trim()) {
      result.push({
        size_label: lbl.value.trim(),
        mold_quantity: qty && qty.value ? parseInt(qty.value, 10) : null,
        output_pair: cik && cik.value ? parseInt(cik.value, 10) : null,
      });
    }
  });
  return result;
}

// ── Duplicate check (client-side, fixture verisine karşı) ───────────────────
function checkDuplicateFx(form) {
  if (!FX || !FX.records) return null;
  var mat   = (form.querySelector('[name=material_group]:checked') || {}).value || '';
  var model = (form.querySelector('[name=model_kod]') || {}).value.trim();
  var mold  = (form.querySelector('[name=visible_mold_code]') || {}).value.trim();
  var fam   = (document.getElementById('akFFamily') || {}).value || '';
  var vari  = (document.getElementById('akFVariant') || {}).value.trim();
  var cat   = akComposeProductType(fam, vari);
  var bas   = (form.querySelector('[name=asorti_bas]') || {}).value.trim();
  var bit   = (form.querySelector('[name=asorti_bit]') || {}).value.trim();
  if (!model || !mold) return null;
  var asorti = bas && bit ? bas + '-' + bit : '';
  var normCat = akNormalizeProductType(cat);
  var match = FX.records.find(function (r) {
    return r.material_group === mat
      && r.model_kod === model
      && r.visible_mold_code === mold
      && akNormKey(akDisplayProductType(r)) === akNormKey(normCat)
      && (r.asorti || '') === asorti;
  });
  return match || null;
}

// ── Canlı form hazırlık / eksik alan takibi ─────────────────────────────────
var _formFieldMap = [
  { id: 'akFModel', err: 'akErrModel', label: 'Model kodu' },
  { id: 'akFMoldCode', err: 'akErrMoldCode', label: 'Enjeksiyon kalıp kodu' },
  { id: 'akFFamily', err: 'akErrFamily', label: 'Ana ürün ailesi', isSelect: true },
  { id: 'akFAsBas', err: 'akErrAsBas', label: 'Asorti başlangıç' },
  { id: 'akFAsBit', err: 'akErrAsBit', label: 'Asorti bitiş' },
  { id: 'akFCift', err: 'akErrCift', label: 'Kalıp çıkış adedi', isSelect: true },
];

function computeDraftMissing() {
  var model = getVal('akFModel');
  var mold = getVal('akFMoldCode');
  var missing = [];
  if (!model && !mold) missing.push('Model kodu veya enjeksiyon kalıp kodu');
  return missing;
}

function computeFullMissing(markFields) {
  var missing = [];
  var firstFocus = null;
  _formFieldMap.forEach(function (f) {
    var el = document.getElementById(f.id);
    var val = el ? (f.isSelect ? el.value : el.value.trim()) : '';
    if (!val) {
      missing.push(f.label);
      if (markFields) markInvalid(f.id, f.err, f.label + ' zorunlu');
      if (!firstFocus) firstFocus = el;
    } else if (markFields) {
      if (el) el.classList.remove('ak-invalid');
      setErr(f.err, '');
    }
  });
  var bas = parseInt(getVal('akFAsBas'), 10);
  var bit = parseInt(getVal('akFAsBit'), 10);
  if (bas && bit && bit < bas) {
    missing.push('Asorti aralığı geçersiz');
    if (markFields) markInvalid('akFAsBit', 'akErrAsBit', 'Bitiş başlangıçtan küçük olamaz');
  }
  var seriIssues = [];
  var rows = document.querySelectorAll('#akSeriesRows .ak-series-row');
  if (!rows.length) {
    missing.push('Seri & Kalıp Adedi bölümünü tamamlayın');
    seriIssues.push('section');
  } else {
    rows.forEach(function (row, idx) {
      var lbl = row.querySelector('.ak-s-label');
      var qty = row.querySelector('.ak-s-qty');
      var cik = row.querySelector('.ak-s-cikis');
      var n = idx + 1;
      if (!lbl || !lbl.value.trim()) seriIssues.push('Numara/Asorti (satır ' + n + ')');
      if (!qty || !qty.value || parseInt(qty.value, 10) < 1) seriIssues.push('Kalıp adedi (satır ' + n + ')');
      if (!cik || !cik.value || parseInt(cik.value, 10) < 1) seriIssues.push('Çevrim başına çıkış (satır ' + n + ')');
    });
    if (seriIssues.length) {
      missing.push('Seri & Kalıp Adedi bölümünü tamamlayın');
      if (markFields) {
        rows.forEach(function (row) {
          var lbl = row.querySelector('.ak-s-label');
          var qty = row.querySelector('.ak-s-qty');
          var cik = row.querySelector('.ak-s-cikis');
          if (lbl && !lbl.value.trim()) lbl.classList.add('ak-invalid');
          if (qty && (!qty.value || parseInt(qty.value, 10) < 1)) qty.classList.add('ak-invalid');
          if (cik && (!cik.value || parseInt(cik.value, 10) < 1)) cik.classList.add('ak-invalid');
        });
      }
    }
  }
  bindSeriesSectionInvalid(seriIssues.length > 0);
  var gramaj = getVal('akFGramaj');
  if (!gramaj) missing.push('Bir Çift Ürün Gramajı (g) — eksik teknik bilgi, kaydı engellemez');
  var pisirme = getVal('akFPisirme');
  if (pisirme && (parseFloat(pisirme) <= 0 || parseFloat(pisirme) > 9999)) {
    markInvalid('akFPisirme', 'akErrPisirme', 'Pişme süresi saniye birimiyle pozitif olmalı (max 9999 sn)');
    missing.push('Pişme Süresi (sn) geçersiz');
  }
  if (gramaj && (parseFloat(gramaj) < 50 || parseFloat(gramaj) > 2000)) {
    markInvalid('akFGramaj', 'akErrGramaj', 'Gramaj 50–2000 g aralığında olmalı');
    missing.push('Bir Çift Ürün Gramajı (g) geçersiz');
  }
  return { missing: missing, firstFocus: firstFocus, seriIssues: seriIssues };
}

function updateFormReadiness() {
  if (!_formDrawerOpen) return;
  var full = computeFullMissing(false);
  var draftMissing = computeDraftMissing();
  var blocking = full.missing.filter(function (m) { return m.indexOf('eksik teknik') < 0; });
  var saveBtn = document.getElementById('akMoldSave');
  var draftBtn = document.getElementById('akDraftSave');
  if (saveBtn && !_saving) saveBtn.disabled = blocking.length > 0;
  if (draftBtn && !_saving) draftBtn.disabled = draftMissing.length > 0;
  var sum = document.getElementById('akFormMissingSummary');
  if (sum) {
    if (!blocking.length) {
      sum.innerHTML = '<span class="ak-missing-ok">✓ Tam kayıt için gerekli alanlar dolu</span>'
        + (full.missing.some(function (m) { return m.indexOf('Gramajı') >= 0; })
          ? '<div class="ak-missing-warn">Bir Çift Ürün Gramajı girilmedi — eksik teknik bilgi olarak işaretlenecek</div>' : '');
    } else {
      sum.innerHTML = '<div class="ak-missing-title">Eksik alanlar:</div><ul>'
        + blocking.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join('')
        + '</ul>';
    }
  }
}

function validateForm(form, markFields) {
  clearErrs();
  var full = computeFullMissing(!!markFields);
  var blocking = full.missing.filter(function (m) { return m.indexOf('eksik teknik') < 0; });
  var img = document.getElementById('akFImage');
  if (img && img.files && img.files[0] && img.files[0].size > 5 * 1024 * 1024) {
    setErr('akErrImage', 'Dosya 5 MB sınırını aşıyor');
    blocking.push('Görsel boyutu');
  }
  if (markFields && blocking.length && full.firstFocus) {
    full.firstFocus.focus();
    full.firstFocus.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } else if (markFields && full.seriIssues.length) {
    var sec = document.getElementById('akSeriesSection');
    if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  return blocking.length === 0;
}

function validateDraftForm(form) {
  clearErrs();
  var missing = computeDraftMissing();
  if (missing.length) {
    if (!getVal('akFModel')) markInvalid('akFModel', 'akErrModel', 'Model veya kalıp kodu gerekli');
    if (!getVal('akFMoldCode')) markInvalid('akFMoldCode', 'akErrMoldCode', 'Model veya kalıp kodu gerekli');
    return false;
  }
  return true;
}

// ── Collect form data ────────────────────────────────────────────────────────
function collectFormData(form) {
  var mat = (form.querySelector('[name=material_group]:checked') || {}).value || 'EVA';
  var bas = form.querySelector('[name=asorti_bas]').value.trim();
  var bit = form.querySelector('[name=asorti_bit]').value.trim();
  var atk = form.querySelector('[name=separate_upper_mold]').value;
  return {
    material_group:        mat,
    model_kod:             form.querySelector('[name=model_kod]').value.trim(),
    visible_mold_code:     form.querySelector('[name=visible_mold_code]').value.trim(),
    product_category:      akComposeProductType(
      (document.getElementById('akFFamily') || {}).value,
      (document.getElementById('akFVariant') || {}).value.trim()
    ),
    product_family:        (document.getElementById('akFFamily') || {}).value,
    product_variant:       (document.getElementById('akFVariant') || {}).value.trim(),
    durum:                 form.querySelector('[name=durum]').value,
    asorti:                (bas && bit) ? bas + '-' + bit : '',
    asorti_bas:            bas ? parseInt(bas, 10) : null,
    asorti_bit:            bit ? parseInt(bit, 10) : null,
    cift_miktari:          parseFloat(form.querySelector('[name=cift_miktari]').value) || null,
    gramaj_gr:             parseFloat(form.querySelector('[name=gramaj_gr]').value) || null,
    pisirme_suresi_sn:     parseFloat(form.querySelector('[name=pisirme_suresi_sn]').value) || null,
    gramaj_ref_numara:     form.querySelector('[name=gramaj_ref_numara]').value.trim() || null,
    separate_upper_mold:   atk !== '' ? parseInt(atk, 10) : null,
    not:                   form.querySelector('[name=not]').value.trim() || null,
    is_draft:              false,
    seri_rows:             collectSeriesRows(),
  };
}

// ── Submit ────────────────────────────────────────────────────────────────────
var _saving = false;

function submitNewMold(isDraft) {
  if (_saving) return;
  var form = document.getElementById('akNewMoldForm');
  if (!form) return;

  if (isDraft && !validateDraftForm(form)) {
    showToast('Taslak için model kodu veya kalıp kodu girin', 'error');
    updateFormReadiness();
    return;
  }
  if (!isDraft && !validateForm(form, true)) {
    showToast('Eksik alanları tamamlayın', 'error');
    updateFormReadiness();
    return;
  }

  // Composite duplicate kontrolü (sadece fixture verisi üzerinde, client-side)
  if (!isDraft) {
    var dup = checkDuplicateFx(form);
    if (dup) {
      document.getElementById('akMoldCodeHint').textContent =
        'Uyarı: Mevcut kütüphanede aynı bileşik anahtara sahip kayıt var: ' + dup.visible_mold_code + ' / ' + (dup.asorti || '—');
      showToast('Aynı bileşik anahtarla kayıt zaten mevcut', 'error');
      return;
    }
  }

  var data = collectFormData(form);
  data.is_draft = isDraft;

  // Görsel
  var img = document.getElementById('akFImage');
  var hasImage = img && img.files && img.files[0];

  _saving = true;
  var saveBtn = document.getElementById('akMoldSave');
  var draftBtn = document.getElementById('akDraftSave');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Kaydediliyor…'; }
  if (draftBtn) draftBtn.disabled = true;

  var fd = new FormData();
  fd.append('payload', JSON.stringify(data));
  if (hasImage) fd.append('gorsel', img.files[0]);

  fetch('/planlama/aktif-kaliplar/yeni-kalip', {
    method: 'POST',
    body: fd,
  })
  .then(function (r) { return r.json(); })
  .then(function (res) {
    _saving = false;
    if (saveBtn) { saveBtn.textContent = 'Kalıbı Kaydet'; }
    if (draftBtn) draftBtn.disabled = false;
    updateFormReadiness();

    if (res.ok) {
      var msg = isDraft ? 'Taslak başarıyla kaydedildi' : 'Kalıp başarıyla kaydedildi';
      if (res.poli_library_only) msg += ' (Poli yalnız kütüphanede — planlamaya düşmez)';
      showToast(msg, 'success');
      var newCode = res.visible_mold_code || data.visible_mold_code;
      var newSeq = res.source_seq;
      closeFormDrawer();
      reloadFixture(function () {
        var rec = null;
        if (newSeq) rec = FX.records.find(function (r) { return r.source_seq === newSeq; });
        if (!rec && newCode) rec = FX.records.find(function (r) { return r.visible_mold_code === newCode; });
        if (rec) {
          var search = document.getElementById('akFSearch');
          if (search) search.value = rec.visible_mold_code || '';
          curPage = 1;
          applyFilters();
          selectRecord(rec.source_seq);
        }
      });
    } else {
      var msg = res.error || 'Kayıt başarısız';
      if (res.duplicate) {
        document.getElementById('akMoldCodeHint').textContent = 'Sunucu: Aynı bileşik anahtar mevcut.';
      }
      showToast(msg, 'error');
    }
  })
  .catch(function (err) {
    _saving = false;
    if (saveBtn) saveBtn.textContent = 'Kalıbı Kaydet';
    if (draftBtn) draftBtn.disabled = false;
    updateFormReadiness();
    showToast('Sunucu hatası: ' + err.message, 'error');
  });
}

// ── Drawer event bindings ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  var yeniBtn = document.getElementById('akYeniKalipBtn');
  if (yeniBtn) {
    yeniBtn.addEventListener('click', function () { openFormDrawer(); });
  }

  var closeBtn = document.getElementById('akDrawerClose');
  if (closeBtn) closeBtn.addEventListener('click', closeFormDrawer);

  var cancelBtn = document.getElementById('akDrawerCancel');
  if (cancelBtn) cancelBtn.addEventListener('click', closeFormDrawer);

  var backdrop = document.getElementById('akDrawerBackdrop');
  if (backdrop) backdrop.addEventListener('click', closeFormDrawer);

  var addRowBtn = document.getElementById('akAddSeriesRow');
  if (addRowBtn) addRowBtn.addEventListener('click', function () { addSeriesRow(); });

  var newForm = document.getElementById('akNewMoldForm');
  if (newForm) {
    newForm.querySelectorAll('input, select, textarea').forEach(function (el) {
      el.addEventListener('input', updateFormReadiness);
      el.addEventListener('change', updateFormReadiness);
    });
  }

  var saveBtn = document.getElementById('akMoldSave');
  if (saveBtn) saveBtn.addEventListener('click', function () { submitNewMold(false); });

  var draftBtn = document.getElementById('akDraftSave');
  if (draftBtn) draftBtn.addEventListener('click', function () { submitNewMold(true); });

  // Poli uyarısı
  document.querySelectorAll('[name=material_group]').forEach(function (r) {
    r.addEventListener('change', function () {
      var warn = document.getElementById('akPoliWarn');
      if (warn) {
        warn.classList.toggle('ak-hidden', r.value !== 'POLI');
      }
    });
  });

  // Görsel önizleme
  var imgInput = document.getElementById('akFImage');
  if (imgInput) {
    imgInput.addEventListener('change', function () {
      var prev = document.getElementById('akImagePreview');
      if (!prev) return;
      if (imgInput.files && imgInput.files[0]) {
        var url = URL.createObjectURL(imgInput.files[0]);
        prev.innerHTML = '<img src="' + url + '" alt="Görsel önizleme">';
        prev.classList.remove('ak-hidden');
      } else {
        prev.innerHTML = '';
        prev.classList.add('ak-hidden');
      }
    });
  }

  // Escape key
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && _formDrawerOpen) closeFormDrawer();
    if (e.key === 'Escape' && _editDrawerOpen) closeEditDrawer();
  });

  // Edit drawer bindings
  var editClose = document.getElementById('akEditDrawerClose');
  if (editClose) editClose.addEventListener('click', closeEditDrawer);
  var editCancel = document.getElementById('akEditCancel');
  if (editCancel) editCancel.addEventListener('click', closeEditDrawer);
  var editBackdrop = document.getElementById('akEditBackdrop');
  if (editBackdrop) editBackdrop.addEventListener('click', closeEditDrawer);
  var editAddRow = document.getElementById('akEditAddSeriesRow');
  if (editAddRow) editAddRow.addEventListener('click', function () { addEditSeriesRow(); });
  var editSave = document.getElementById('akEditSave');
  if (editSave) editSave.addEventListener('click', submitEdit);
  var editArchive = document.getElementById('akEditArchive');
  if (editArchive) editArchive.addEventListener('click', function () {
    if (!_editRecord || _editSaving) return;
    var reason = window.prompt('Arşiv gerekçesi (zorunlu):');
    if (!reason || !reason.trim()) return;
    var fd = new FormData();
    fd.append('payload', JSON.stringify({ source_seq: _editRecord.source_seq, change_reason: reason.trim() }));
    fetch('/planlama/aktif-kaliplar/arsivle', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.ok) {
          showToast('Kayıt arşivlendi', 'success');
          closeEditDrawer();
          reloadFixture(function () { if (selSeq) selectRecord(selSeq); });
        } else showToast(res.error || 'Arşivleme başarısız', 'error');
      });
  });
  var editRemoveImg = document.getElementById('akEditRemoveImage');
  if (editRemoveImg) editRemoveImg.addEventListener('click', function () {
    _editRemoveImage = true;
    var cur = document.getElementById('akEditCurrentImage');
    var prev = document.getElementById('akEditImagePreview');
    if (cur) { cur.classList.add('ak-hidden'); cur.innerHTML = ''; }
    if (prev) { prev.classList.add('ak-hidden'); prev.innerHTML = ''; }
    var img = document.getElementById('akEditImage');
    if (img) img.value = '';
    showToast('Görsel kaldırma işaretlendi — kaydet ile uygulanır', 'info');
  });
  var editImgInput = document.getElementById('akEditImage');
  if (editImgInput) {
    editImgInput.addEventListener('change', function () {
      var prev = document.getElementById('akEditImagePreview');
      if (!prev) return;
      _editRemoveImage = false;
      if (editImgInput.files && editImgInput.files[0]) {
        if (editImgInput.files[0].size > 5 * 1024 * 1024) {
          setErr('akEditErrImage', 'Dosya 5 MB sınırını aşıyor');
          return;
        }
        prev.innerHTML = '<img src="' + URL.createObjectURL(editImgInput.files[0]) + '" alt="Önizleme">';
        prev.classList.remove('ak-hidden');
      }
    });
  }
  document.querySelectorAll('[name=edit_material_group]').forEach(function (r) {
    r.addEventListener('change', function () {
      var w = document.getElementById('akEditPoliWarn');
      if (w) w.classList.toggle('ak-hidden', r.value !== 'POLI');
    });
  });
});

/* ══════════════════════════════════════════════════════════════════════════
   DÜZENLE DRAWER
   ══════════════════════════════════════════════════════════════════════════ */
var _editDrawerOpen = false;
var _editRecord = null;
var _editRemoveImage = false;
var _editSeriesCount = 0;
var _editSaving = false;

function openEditDrawer(r) {
  _editRecord = r;
  _editRemoveImage = false;
  document.getElementById('akEditSourceSeq').value = r.source_seq;
  document.getElementById('akEditModel').value = r.model_kod || '';
  document.getElementById('akEditMoldCode').value = r.visible_mold_code || '';
  var fv = akSplitFamilyVariant(r);
  akPopulateFamilySelect(document.getElementById('akEditFamily'), fv.family);
  document.getElementById('akEditVariant').value = fv.variant === fv.family ? '' : fv.variant;
  document.getElementById('akEditDurum').value = r.durum || 'AKTIF';
  document.getElementById('akEditCift').value = r.cift_miktari != null ? String(r.cift_miktari) : '2';
  document.getElementById('akEditGramaj').value = r.gramaj_gr != null ? r.gramaj_gr : '';
  document.getElementById('akEditPisirme').value = r.pisirme_suresi_sn != null ? r.pisirme_suresi_sn : '';
  document.getElementById('akEditRefNo').value = r.gramaj_ref_numara || '';
  document.getElementById('akEditNot').value = r.not || '';
  document.getElementById('akEditReason').value = '';
  var as = akParseAsorti(r.asorti);
  document.getElementById('akEditAsBas').value = as.bas;
  document.getElementById('akEditAsBit').value = as.bit;
  var mat = (r.material_group || 'EVA').toUpperCase();
  document.querySelector('[name=edit_material_group][value="' + mat + '"]').checked = true;
  var atki = document.getElementById('akEditAtki');
  if (atki) atki.value = r.separate_upper_mold === null ? '' : (r.separate_upper_mold ? '1' : '0');
  var pw = document.getElementById('akEditPoliWarn');
  if (pw) pw.classList.toggle('ak-hidden', mat !== 'POLI');

  var curImg = document.getElementById('akEditCurrentImage');
  if (curImg) {
    if (r.image_url) {
      curImg.innerHTML = '<img src="' + esc(r.image_url) + '" alt="Mevcut görsel">';
      curImg.classList.remove('ak-hidden');
    } else {
      curImg.innerHTML = '<div style="padding:12px;color:var(--ak-muted);font-size:12px">Mevcut görsel yok</div>';
      curImg.classList.remove('ak-hidden');
    }
  }
  var prev = document.getElementById('akEditImagePreview');
  if (prev) { prev.classList.add('ak-hidden'); prev.innerHTML = ''; }
  var imgIn = document.getElementById('akEditImage');
  if (imgIn) imgIn.value = '';

  var rows = document.getElementById('akEditSeriesRows');
  if (rows) rows.innerHTML = '';
  _editSeriesCount = 0;
  (r.seri_dagilimi || []).forEach(function (s) {
    addEditSeriesRow(akSeriNumara(s), s.kalip_adedi,
      s.kalip_cikisi != null ? s.kalip_cikisi : r.cift_miktari);
  });
  if (!_editSeriesCount) addEditSeriesRow();

  document.getElementById('akEditDrawer').classList.add('open');
  document.getElementById('akEditBackdrop').classList.add('show');
  document.body.style.overflow = 'hidden';
  _editDrawerOpen = true;
}

function closeEditDrawer() {
  document.getElementById('akEditDrawer').classList.remove('open');
  document.getElementById('akEditBackdrop').classList.remove('show');
  document.body.style.overflow = '';
  _editDrawerOpen = false;
  _editRecord = null;
  _editRemoveImage = false;
  var prev = document.getElementById('akEditImagePreview');
  if (prev) { prev.innerHTML = ''; prev.classList.add('ak-hidden'); }
}

function addEditSeriesRow(label, qty, cikis) {
  _editSeriesCount++;
  var cont = document.getElementById('akEditSeriesRows');
  if (!cont) return;
  if (_editSeriesCount === 1) {
    var hdr = document.createElement('div');
    hdr.className = 'ak-series-row-header';
    hdr.id = 'akEditSeriesHeader';
    hdr.innerHTML = [
      '<span class="ak-series-col-label">Numara / Asorti</span>',
      '<span class="ak-series-col-label">Kalıp Adedi</span>',
      '<span class="ak-series-col-label">Çevrim Başına Çıkış</span>',
      '<span></span>'
    ].join('');
    cont.appendChild(hdr);
  }
  var row = document.createElement('div');
  row.className = 'ak-series-row';
  row.innerHTML = [
    '<input type="text" class="ak-input ak-es-label" placeholder="örn: 23/24" value="' + esc(label || '') + '" maxlength="30">',
    '<input type="number" class="ak-input ak-es-qty" placeholder="1" value="' + (qty != null ? qty : '') + '" min="1" max="32">',
    '<input type="number" class="ak-input ak-es-cikis" placeholder="2" value="' + (cikis != null ? cikis : '') + '" min="1" max="8">',
    '<button type="button" class="ak-remove-row" title="Satırı kaldır">×</button>'
  ].join('');
  cont.appendChild(row);
  row.querySelector('.ak-remove-row').addEventListener('click', function () {
    cont.removeChild(row);
    if (!cont.querySelectorAll('.ak-series-row').length) {
      var h = document.getElementById('akEditSeriesHeader');
      if (h) cont.removeChild(h);
      _editSeriesCount = 0;
    }
  });
}

function collectEditSeriesRows() {
  var rows = document.querySelectorAll('#akEditSeriesRows .ak-series-row');
  var result = [];
  rows.forEach(function (r) {
    var lbl = r.querySelector('.ak-es-label');
    if (lbl && lbl.value.trim()) {
      result.push({
        size_label: lbl.value.trim(),
        numara: lbl.value.trim(),
        mold_quantity: r.querySelector('.ak-es-qty') && r.querySelector('.ak-es-qty').value ? parseInt(r.querySelector('.ak-es-qty').value, 10) : null,
        output_pair: r.querySelector('.ak-es-cikis') && r.querySelector('.ak-es-cikis').value ? parseInt(r.querySelector('.ak-es-cikis').value, 10) : null,
      });
    }
  });
  return result;
}

function submitEdit() {
  if (_editSaving || !_editRecord) return;
  var bas = document.getElementById('akEditAsBas').value.trim();
  var bit = document.getElementById('akEditAsBit').value.trim();
  if (!document.getElementById('akEditModel').value.trim() || !document.getElementById('akEditMoldCode').value.trim()) {
    showToast('Model kodu ve kalıp kodu zorunlu', 'error');
    return;
  }
  if (bas && bit && parseInt(bit, 10) < parseInt(bas, 10)) {
    showToast('Asorti bitiş başlangıçtan küçük olamaz', 'error');
    return;
  }
  var data = {
    source_seq: _editRecord.source_seq,
    material_group: (document.querySelector('[name=edit_material_group]:checked') || {}).value || 'EVA',
    model_kod: document.getElementById('akEditModel').value.trim(),
    visible_mold_code: document.getElementById('akEditMoldCode').value.trim(),
    product_category: akComposeProductType(
      document.getElementById('akEditFamily').value,
      document.getElementById('akEditVariant').value.trim()
    ),
    product_family: document.getElementById('akEditFamily').value,
    product_variant: document.getElementById('akEditVariant').value.trim(),
    durum: document.getElementById('akEditDurum').value,
    asorti_bas: bas, asorti_bit: bit,
    cift_miktari: parseFloat(document.getElementById('akEditCift').value) || null,
    gramaj_gr: parseFloat(document.getElementById('akEditGramaj').value) || null,
    pisirme_suresi_sn: parseFloat(document.getElementById('akEditPisirme').value) || null,
    gramaj_ref_numara: document.getElementById('akEditRefNo').value.trim() || null,
    separate_upper_mold: document.getElementById('akEditAtki').value,
    not: document.getElementById('akEditNot').value.trim() || null,
    change_reason: document.getElementById('akEditReason').value.trim() || 'Kullanıcı düzenlemesi',
    seri_rows: collectEditSeriesRows(),
    remove_image: _editRemoveImage,
    row_version: _editRecord.row_version,
  };
  _editSaving = true;
  var btn = document.getElementById('akEditSave');
  if (btn) { btn.disabled = true; btn.textContent = 'Kaydediliyor…'; }
  var fd = new FormData();
  fd.append('payload', JSON.stringify(data));
  var img = document.getElementById('akEditImage');
  if (img && img.files && img.files[0]) fd.append('gorsel', img.files[0]);
  fetch('/planlama/aktif-kaliplar/duzenle', { method: 'POST', body: fd })
    .then(function (r) { return r.json(); })
    .then(function (res) {
      _editSaving = false;
      if (btn) { btn.disabled = false; btn.textContent = 'Değişiklikleri Kaydet'; }
      if (res.ok) {
        showToast('Değişiklikler preview DB\'ye kaydedildi', 'success');
        closeEditDrawer();
        return fetch('/planlama/aktif-kaliplar/fixture.json').then(function (r) { return r.json(); });
      }
      if (res.conflict) showToast('Kayıt güncellendi — sayfayı yenileyin', 'error');
      showToast(res.error || 'Düzenleme başarısız', 'error');
      return null;
    })
    .then(function (fresh) {
      if (!fresh) return;
      window.AK_FIXTURE = fresh;
      FX = fresh;
      initFiltersRepopulate();
      applyFilters();
      if (selSeq) selectRecord(selSeq);
    })
    .catch(function (err) {
      _editSaving = false;
      if (btn) { btn.disabled = false; btn.textContent = 'Değişiklikleri Kaydet'; }
      showToast('Sunucu hatası: ' + err.message, 'error');
    });
}

function initFiltersRepopulate() {
  var ft = document.getElementById('akFTip');
  if (!ft) return;
  var cur = ft.value;
  while (ft.options.length > 1) ft.remove(1);
  var families = {};
  FX.records.forEach(function (r) {
    var fam = akProductFamily(r) || 'Belirsiz';
    var key = akFamilyKey(fam);
    if (!families[key]) families[key] = fam;
  });
  Object.keys(families).sort(function (a, b) { return families[a].localeCompare(families[b], 'tr'); }).forEach(function (k) {
    var o = document.createElement('option'); o.value = k; o.textContent = families[k]; ft.appendChild(o);
  });
  ft.value = cur;
}

})(); /* end IIFE */
