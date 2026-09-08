(function () {
    'use strict';

    var CAN_EDIT = !!window.UP_CAN_EDIT;
    var state = {
        donem: 'bu_hafta',
        satirlar: [],
        onizleme: [],
        seciliCreate: null,
        detayPlanId: null,
        detaySatir: null,
        detayProsesKod: null,
        detayKatFilter: 'TUMU',
        editPlanId: null,
        enj: {
            makineler: [],
            kaliplar: [],
            kapasiteSnapshot: null,
            makineId: null,
            makineKod: null,
            istasyonSayisi: 8,
            istasyonlar: [],
            slot: null,
            kalipId: null,
            kalipKod: null,
            kalipBasiCift: null,
            kalipAdedi: null,
            gozPerKalip: 1,
            kalipMode: 'liste',
            turCift: null,
            baslangic: null,
            baslangicOneri: null,
            baslangicManuel: false,
            bitis: null,
            planCift: null,
            calismaModu: 'GUNDUZ_GECE',
            haftaSonu: 'HAYIR',
            hsVardiya: null,
            motorResult: null,
            hesapOk: false,
            gridData: null,
            referenceMode: 'MANUAL',
            manualRefGunduz: null,
            manualRefGece: null,
            autoRefGunduz: null,
            autoRefGece: null,
            // Ref kaynak takibi: 'HISTORICAL_CONFIRMED' | 'MANUAL' | null
            refSourceGunduz: null,
            refSourceGece: null,
            // Onaylı referans değerleri (kullanıcı "Kullan" butonuna bastıktan sonra)
            refConfirmedGunduz: false,
            refConfirmedGece: false,
            planOzetMap: {},
            istasyonPlanDurum: {},
            reservation: null,
            pendingConflict: null,
        },
        createStep: 1,
        requiresEnj: false,
        step3: {
            basMode: null,
            secenekler: [],
            saveBlocked: false,
            bitisUyari: null,
        },
    };

    function $(id) { return document.getElementById(id); }

    function fmtN(n) {
        if (n === null || n === undefined || n === '') return '-';
        return Number(n).toLocaleString('tr-TR');
    }

    function fmtTarih(iso) {
        if (!iso) return '—';
        var p = String(iso).slice(0, 10).split('-');
        if (p.length !== 3) return iso;
        return p[2] + '.' + p[1] + '.' + p[0];
    }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function gorselUrl(skod) {
        return skod ? '/planlama/uretim-plan/gorsel/' + encodeURIComponent(skod) : '';
    }

    function thumbHtml(r, cls) {
        cls = cls || 'up-thumb';
        var sk = r.model_gorsel_skod || r.model_kod || r.mamul_skod;
        if (r.sresim && sk) {
            return '<img class="' + cls + '" src="' + esc(gorselUrl(sk)) + '" alt="" onerror="this.outerHTML=\'<span class=up-thumb-ph>👟</span>\'">';
        }
        return '<span class="up-thumb-ph">👟</span>';
    }

    function fmtPct(pct) {
        if (pct === null || pct === undefined || pct === '') return '0%';
        var n = Number(pct);
        if (!isFinite(n)) return '0%';
        if (Math.abs(n - Math.round(n)) < 0.05) return Math.round(n) + '%';
        return n.toFixed(1) + '%';
    }

    function shortProsesLabel(name) {
        if (!name) return '';
        var n = String(name).trim();
        var norm = n.toLowerCase().replace(/ı/g, 'i').replace(/ş/g, 's').replace(/ğ/g, 'g').replace(/ü/g, 'u').replace(/ö/g, 'o').replace(/ç/g, 'c');
        if (norm.indexOf('monta basla') === 0) return 'MONTA BAŞL.';
        if (norm.indexOf('eva hazir') === 0) return 'EVA HAZIR';
        if (norm.indexOf('enjeksiyon') === 0) return 'ENJEKSİYON';
        if (norm.indexOf('temizleme') === 0) return 'TEMİZLEME';
        if (norm.indexOf('kesim') === 0) return 'KESİM';
        if (norm.indexOf('saya') === 0) return 'SAYA';
        if (norm.indexOf('monta') === 0 && norm.indexOf('basla') < 0) return 'MONTA';
        try {
            return n.toLocaleUpperCase('tr-TR');
        } catch (e) {
            return n.toUpperCase();
        }
    }

    function prosesStepHtml(p, planId) {
        if (!p) return '';
        var cls = p.renk || 'gri';
        var pct = p.yuzde != null ? p.yuzde : 0;
        var pctW = Math.min(100, Math.max(0, pct));
        var fullName = p.proses_adi || p.proses_kod || '';
        var lbl = shortProsesLabel(fullName);
        var emirTxt = '';
        if (p.emir_sayisi != null && p.emir_sayisi > 0) {
            var bEm = p.biten_emir_sayisi != null ? p.biten_emir_sayisi : 0;
            emirTxt = bEm + '/' + p.emir_sayisi + ' emir';
        }
        var check = (cls === 'yesil' || pct >= 100) ? '<span class="up-step-check" aria-hidden="true">✓</span>' : '';
        var kod = esc(p.proses_kod || '');
        var pid = planId != null ? esc(String(planId)) : '';
        return '<button type="button" class="up-proses-step" data-plan-id="' + pid +
            '" data-proses-kod="' + kod + '" title="' + esc(fullName) + '">' +
            '<div class="up-step-name">' + esc(lbl) + '</div>' +
            '<div class="up-step-pct-wrap">' +
            '<div class="up-step-pct ' + cls + '">' + fmtPct(pct) + '</div>' + check +
            '</div>' +
            '<div class="up-step-bar"><i class="' + cls + '" style="width:' + pctW + '%"></i></div>' +
            '<div class="up-step-emir">' + esc(emirTxt) + '</div>' +
            '</button>';
    }

    function renderProsesInline(prosesler, maxSlots, planId) {
        maxSlots = maxSlots == null ? 6 : maxSlots;
        var list = prosesler || [];
        if (!list.length) return '<span class="up-proses-empty">—</span>';

        var visible = list;
        var hiddenMiddle = 0;
        if (list.length > maxSlots) {
            var first = list[0];
            var last = list[list.length - 1];
            var middle = list.slice(1, list.length - 1);
            var slotsMid = Math.max(0, maxSlots - 2);
            if (middle.length <= slotsMid) {
                visible = list;
            } else {
                visible = [first].concat(middle.slice(0, slotsMid)).concat([last]);
                hiddenMiddle = middle.length - slotsMid;
            }
        }

        var html = '<div class="up-proses-flow" data-count="' + visible.length + '">';
        visible.forEach(function (p, idx) {
            if (idx > 0) html += '<span class="up-proses-sep" aria-hidden="true">&gt;</span>';
            html += prosesStepHtml(p, planId);
        });
        if (hiddenMiddle > 0) {
            html += '<span class="up-proses-sep" aria-hidden="true">&gt;</span>';
            html += '<span class="up-proses-more" title="' + hiddenMiddle + ' ara proses — popup\'ta tam liste">+' +
                hiddenMiddle + ' ara proses</span>';
        }
        html += '</div>';
        return html;
    }

    function prosesByKod(prosesler, kod) {
        kod = String(kod || '');
        for (var i = 0; i < (prosesler || []).length; i++) {
            if (String(prosesler[i].proses_kod) === kod) return prosesler[i];
        }
        return null;
    }

    function emirUrunTipi(e) {
        if (e.urun_tipi) return e.urun_tipi;
        return '—';
    }

    function emirRowClass(e) {
        var renk = e.renk || 'gri';
        if (renk === 'yesil' || e.durum === 'BİTTİ') return 'up-emir-row-bitmis';
        if (renk === 'kirmizi' || e.durum === 'GERİDE') return 'up-emir-row-kirmizi';
        if (renk === 'sari' || e.durum === 'DEVAM') return 'up-emir-row-devam';
        return 'up-emir-row-gri';
    }

    function renderDetayProsesStep(p, active) {
        var cls = p.renk || 'gri';
        var emirTxt = '';
        if (p.emir_sayisi != null && p.emir_sayisi > 0) {
            var bEm = p.biten_emir_sayisi != null ? p.biten_emir_sayisi : 0;
            emirTxt = bEm + '/' + p.emir_sayisi + ' emir';
        }
        var check = (cls === 'yesil' || (p.yuzde || 0) >= 100) ? '<span class="up-dstep-check">✓</span>' : '';
        var pctW = Math.min(100, Math.max(0, p.yuzde || 0));
        var kod = esc(p.proses_kod || '');
        return '<button type="button" class="up-detay-proses-step' + (active ? ' active' : '') +
            '" data-proses-kod="' + kod + '">' +
            '<div class="up-dstep-name">' + esc(shortProsesLabel(p.proses_adi || p.proses_kod)) + '</div>' +
            '<div class="up-dstep-pct-wrap"><span class="up-dstep-pct ' + cls + '">' + fmtPct(p.yuzde) + '</span>' + check + '</div>' +
            '<div class="up-dstep-durum ' + cls + '">' + esc(p.durum || '') + '</div>' +
            '<div class="up-dstep-bar"><i class="' + cls + '" style="width:' + pctW + '%"></i></div>' +
            '<div class="up-dstep-emir">' + esc(emirTxt) + '</div></button>';
    }

    function renderDetayProsesFlow(prosesler, activeKod) {
        var list = prosesler || [];
        if (!list.length) return '<span class="up-proses-empty">—</span>';
        var html = '<div class="up-detay-proses-flow" data-count="' + list.length + '">';
        list.forEach(function (p, idx) {
            if (idx > 0) html += '<span class="up-detay-proses-sep">&gt;</span>';
            html += renderDetayProsesStep(p, String(p.proses_kod) === String(activeKod));
        });
        html += '</div>';
        return html;
    }

    function prosesHasGovdeAtki(proses) {
        var hasG = false, hasA = false;
        (proses.emir_detay || []).forEach(function (e) {
            var k = (e.kategori || '').toUpperCase();
            if (k === 'GOVDE') hasG = true;
            if (k === 'ATKI') hasA = true;
        });
        return hasG && hasA;
    }

    function filterEmirDetay(proses, katFilter) {
        var rows = (proses && proses.emir_detay) ? proses.emir_detay.slice() : [];
        if (katFilter === 'GOVDE') {
            return rows.filter(function (e) { return (e.kategori || '').toUpperCase() === 'GOVDE'; });
        }
        if (katFilter === 'ATKI') {
            return rows.filter(function (e) { return (e.kategori || '').toUpperCase() === 'ATKI'; });
        }
        return rows;
    }

    function renderDetayKatFilters(proses) {
        if (!proses || !prosesHasGovdeAtki(proses)) return '';
        var f = state.detayKatFilter || 'TUMU';
        return '<div class="up-detay-kat-filters">' +
            ['TUMU', 'GOVDE', 'ATKI'].map(function (k) {
                var lbl = k === 'TUMU' ? 'TÜMÜ' : (k === 'GOVDE' ? 'GÖVDE' : 'ATKI');
                return '<button type="button" class="up-detay-kat-btn' + (f === k ? ' active' : '') +
                    '" data-kat="' + k + '">' + lbl + '</button>';
            }).join('') + '</div>';
    }

    function renderDetayEmirOzet(rows) {
        var biten = 0, devam = 0, verilen = 0, btop = 0, kalan = 0;
        (rows || []).forEach(function (e) {
            if (e.durum === 'BİTTİ') biten++;
            if (e.durum === 'DEVAM') devam++;
            verilen += e.verilen || 0;
            btop += e.biten || 0;
            kalan += e.kalan || 0;
        });
        return '<div class="up-detay-emir-ozet">' +
            '<span>Toplam emir: <strong>' + rows.length + '</strong></span>' +
            '<span>Biten emir: <strong>' + biten + '</strong></span>' +
            '<span>Devam: <strong>' + devam + '</strong></span>' +
            '<span>Verilen: <strong>' + fmtN(verilen) + '</strong></span>' +
            '<span>Biten: <strong>' + fmtN(btop) + '</strong></span>' +
            '<span>Kalan: <strong>' + fmtN(kalan) + '</strong></span></div>';
    }

    function renderDetayEmirTable(proses) {
        if (!proses) return '<p class="up-hint">Proses seçin</p>';
        var rows = filterEmirDetay(proses, state.detayKatFilter);
        var prosesAdi = esc(proses.proses_adi || proses.proses_kod);
        var head = '<div class="up-detay-detail-head"><h4>' + prosesAdi + ' — Alt Emir Detayları</h4></div>';
        var filters = renderDetayKatFilters(proses);
        if (!rows.length) {
            return head + filters + '<p class="up-hint">Emir detayı yok</p>' + renderDetayEmirOzet(rows);
        }
        var tbl = '<div class="up-detay-emir-scroll"><table class="up-detay-emir-tbl"><thead><tr>' +
            '<th>Emir No</th><th>M/Y</th><th>Ürün Tipi</th><th>Model</th>' +
            '<th class="num">Verilen</th><th class="num">Biten</th><th class="num">Kalan</th>' +
            '<th class="num">%</th><th>Durum</th></tr></thead><tbody>';
        rows.forEach(function (e) {
            tbl += '<tr class="' + emirRowClass(e) + '">' +
                '<td><strong>' + e.emir_no + '</strong></td>' +
                '<td>' + esc(e.tip || '—') + '</td>' +
                '<td>' + esc(emirUrunTipi(e)) + '</td>' +
                '<td title="' + esc(e.model_adi || e.model_kod) + '">' + esc(e.model_kod) + '</td>' +
                '<td class="num">' + fmtN(e.verilen) + '</td>' +
                '<td class="num">' + fmtN(e.biten) + '</td>' +
                '<td class="num">' + fmtN(e.kalan) + '</td>' +
                '<td class="num">' + (e.yuzde || 0) + '%</td>' +
                '<td><span class="up-emir-durum-badge ' + (e.renk || 'gri') + '">' + esc(e.durum) + '</span></td>' +
                '</tr>';
        });
        tbl += '</tbody></table></div>';
        return head + filters + tbl + renderDetayEmirOzet(rows);
    }

    function bindDetayKatFilterEvents() {
        document.querySelectorAll('.up-detay-kat-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                state.detayKatFilter = btn.getAttribute('data-kat');
                refreshDetayDetailPanel();
            });
        });
    }

    function bindDetayProsesEvents() {
        document.querySelectorAll('.up-detay-proses-step').forEach(function (btn) {
            btn.addEventListener('click', function () {
                selectDetayProses(btn.getAttribute('data-proses-kod'));
            });
        });
    }

    function refreshDetayDetailPanel() {
        var panel = $('upDetayDetailPanel');
        if (!panel || !state.detaySatir) return;
        var proses = prosesByKod(state.detaySatir.prosesler, state.detayProsesKod);
        panel.innerHTML = renderDetayEmirTable(proses);
        bindDetayKatFilterEvents();
    }

    function selectDetayProses(prosesKod) {
        if (!prosesKod || !state.detaySatir) return;
        state.detayProsesKod = prosesKod;
        state.detayKatFilter = 'TUMU';
        document.querySelectorAll('.up-detay-proses-step').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-proses-kod') === String(prosesKod));
        });
        refreshDetayDetailPanel();
    }

    function renderProsesEmirBreakdown(prosesler) {
        var html = '';
        (prosesler || []).forEach(function (p) {
            html += '<div class="up-proses-emir-block" data-proses-kod="' + esc(p.proses_kod || '') +
                '" id="up-proses-block-' + esc(p.proses_kod || '') + '"><h5>' +
                esc(p.proses_adi || p.proses_kod) + ' — ' + fmtPct(p.yuzde) + ' ' + esc(p.durum) + '</h5>';
            if (!p.emir_detay || !p.emir_detay.length) {
                html += '<p class="up-hint">Emir detayı yok</p></div>';
                return;
            }
            html += '<table class="up-subtbl"><thead><tr>' +
                '<th>Emir</th><th>M/Y</th><th>Model</th><th>Verilen</th><th>Biten</th><th>Kalan</th><th>%</th><th>Durum</th>' +
                '</tr></thead><tbody>';
            p.emir_detay.forEach(function (e) {
                html += '<tr><td>' + e.emir_no + '</td><td>' + esc(e.tip) + '</td><td>' + esc(e.model_kod) +
                    '</td><td class="num">' + fmtN(e.verilen) + '</td><td class="num">' + fmtN(e.biten) +
                    '</td><td class="num">' + fmtN(e.kalan) + '</td><td class="num">' + (e.yuzde || 0) +
                    '%</td><td>' + esc(e.durum) + '</td></tr>';
            });
            html += '</tbody></table></div>';
        });
        return html;
    }

    function durumBadge(d, renk, yuzde) {
        var pct = (yuzde != null && yuzde !== '') ? fmtPct(yuzde) : '';
        return '<span class="up-durum-badge ' + (renk || 'gri') + '">' +
            '<span class="up-durum-lbl">' + esc(d || '-') + '</span>' +
            (pct ? '<span class="up-durum-pct">' + pct + '</span>' : '') +
            '</span>';
    }

    function showError(msg) {
        var el = $('upError');
        if (!el) return;
        if (!msg) { el.style.display = 'none'; el.textContent = ''; return; }
        el.style.display = 'block';
        el.textContent = msg;
    }

    var DONEM_LABELS = {
        bu_hafta: 'Bu Hafta',
        gelecek_hafta: 'Gelecek Hafta',
        bu_ay: 'Bu Ay',
        '3_ay': '3 Ay',
    };

    function donemLabel(v) {
        return DONEM_LABELS[v] || v || 'seçili dönem';
    }

    function clearPlanErrors() {
        var el = $('upPlanErrorSummary');
        if (el) {
            el.hidden = true;
            el.innerHTML = '';
        }
        document.querySelectorAll('.up-field-error').forEach(function (n) {
            n.classList.remove('up-field-error');
        });
        document.querySelectorAll('.up-step3-radio.error').forEach(function (n) {
            n.classList.remove('error');
        });
    }

    function showPlanErrors(errors, fieldHints) {
        clearPlanErrors();
        var el = $('upPlanErrorSummary');
        if (!el || !errors || !errors.length) return;
        el.hidden = false;
        el.innerHTML =
            '<strong>PLAN KAYDEDİLEMEDİ</strong><ul>' +
            errors.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join('') +
            '</ul>';
        (fieldHints || []).forEach(function (h) {
            if (!h) return;
            var node = typeof h === 'string' ? $(h) : h;
            if (!node) return;
            var wrap = node.closest('label') || node.closest('.up-step3-radio') || node;
            wrap.classList.add(wrap.classList.contains('up-step3-radio') ? 'error' : 'up-field-error');
        });
    }

    function normalizeServerErrors(d, status) {
        var msgs = [];
        if (d && d.errors && d.errors.length) msgs = d.errors.slice();
        else if (d && d.mesaj) msgs = [d.mesaj];
        else if (d && d.error) msgs = [d.error];
        else msgs = ['Kayıt hatası (HTTP ' + (status || '?') + ')'];
        return msgs.map(function (m) {
            if (/zaten planl/i.test(m)) {
                var donem = $('upFormDonem') ? donemLabel($('upFormDonem').value) : 'seçili dönem';
                return 'Bu model + renk "' + donem + '" döneminde zaten planlı.';
            }
            if (m.indexOf('enjeksiyon tahmini bitiş') >= 0 || m.indexOf('genel plan bitiş') >= 0) {
                return 'Plan bitiş tarihi enjeksiyon tamamlanmadan önce olamaz.';
            }
            if (m.indexOf('Plan bitiş, plan başlangıçtan önce') >= 0) {
                return 'Plan bitiş, plan başlangıçtan önce olamaz.';
            }
            return m;
        });
    }

    function collectPreSaveValidation() {
        var errors = [];
        var fields = [];
        var o = state.seciliCreateData;
        if (!o) {
            errors.push('Model seçin.');
            return { errors: errors, fields: fields };
        }
        if (state.requiresEnj && !state.enj.hesapOk) {
            errors.push('Önce enjeksiyon hesabını tamamlayın.');
            return { errors: errors, fields: fields };
        }
        validateStep3Tarihleri();
        var bas = ($('upFormBas') && $('upFormBas').value) || '';
        var bit = ($('upFormBit') && $('upFormBit').value) || '';
        var donem = ($('upFormDonem') && $('upFormDonem').value) || '';
        if (!bas) {
            errors.push('Plan başlangıç seçimi gerekli.');
            fields.push('#upStep3BasSecenekleri');
        }
        if (!donem) {
            errors.push('Plan dönemi seçin.');
            fields.push('upFormDonem');
        }
        if (state.step3.saveBlocked && state.step3.bitisUyari) {
            errors.push(state.step3.bitisUyari);
            if (state.step3.bitisUyari.indexOf('Plan bitiş') >= 0) fields.push('upFormBit');
            if (state.step3.bitisUyari.indexOf('başlangıç') >= 0) fields.push('#upStep3BasSecenekleri');
        }
        if (bas && bit && bit < bas) {
            errors.push('Plan bitiş, plan başlangıçtan önce olamaz.');
            fields.push('upFormBit');
        }
        if (state.requiresEnj && bit && state.enj.motorResult) {
            var eb = dateOnlyFromApi(state.enj.motorResult.tahmini_bitis || state.enj.bitis);
            if (eb && bit < eb) {
                errors.push('Plan bitiş tarihi enjeksiyon tamamlanmadan önce olamaz.');
                fields.push('upFormBit');
            }
        }
        var sec = state.step3.secenekler || [];
        if (bas && sec.length) {
            var hit = sec.find(function (s) { return s.tarih === bas; });
            if (hit && hit.dolu) {
                errors.push(hit.mesaj || 'Seçilen başlangıç tarihi bu dönemde kullanılamaz.');
                fields.push('#upStep3BasSecenekleri');
            }
        }
        return { errors: errors, fields: fields };
    }

    function closeModals() {
        ['upCreateModal', 'upDetayModal', 'upEditModal'].forEach(function (id) {
            var m = $(id);
            if (m) m.hidden = true;
        });
        document.querySelectorAll('.up-aksiyon-menu.open').forEach(function (m) {
            m.classList.remove('open');
        });
    }

    function renderTable(rows) {
        var body = $('upBody');
        if (!body) return;
        if (!rows || !rows.length) {
            body.innerHTML = '<tr><td colspan="15" class="up-loading">Bu dönemde plan kaydı yok. + PLAN OLUŞTUR ile ekleyin.</td></tr>';
            if ($('upToplam')) $('upToplam').textContent = 'Toplam 0 kayıt';
            return;
        }
        body.innerHTML = '';
        rows.forEach(function (r) {
            var tr = document.createElement('tr');
            tr.className = 'up-row-main';
            tr.dataset.planId = r.plan_id || '';
            var lotTxt = r.emir_lot_sayisi ? '<span class="up-emir-lot">(' + r.emir_lot_sayisi + ' lot)</span>' : '';
            var aksiyon = CAN_EDIT ?
                '<div class="up-aksiyon-wrap"><button type="button" class="up-aksiyon-btn" data-act="menu">⋮</button>' +
                '<div class="up-aksiyon-menu"><button type="button" data-act="edit">Düzenle</button>' +
                '<button type="button" data-act="remove">Kaldır</button></div></div>' : '';
            var enjMakineTxt = r.enj_makine_id
                ? esc((r.enj_makine_kod || 'M' + r.enj_makine_id) +
                  (r.enj_istasyon_no ? '/' + r.enj_istasyon_no : '') +
                  (r.enj_slot ? r.enj_slot : ''))
                : '—';
            var cariTxt = (r.musteri || r.cari || '—').trim() || '—';
            tr.innerHTML =
                '<td class="up-col-chk"><input type="checkbox" disabled></td>' +
                '<td>' + thumbHtml(r) + '</td>' +
                '<td class="up-col-cari"><span class="up-cari-text">' + esc(cariTxt) + '</span></td>' +
                '<td class="up-col-sip-emir"><div class="up-sip-no">' + esc(r.sip_no) + '</div>' +
                '<div class="up-emir-kompakt" title="' + esc((r.emir_nos || []).join(', ')) + '">' +
                esc(r.emir_no) + '</div>' + lotTxt + '</td>' +
                '<td class="up-col-model">' + esc(r.model_kod) + '</td>' +
                '<td class="up-col-renk"><span class="up-renk-dot"></span>' + esc(r.renk) + '</td>' +
                '<td class="num">' + fmtN(r.miktar) + '</td>' +
                '<td>' + fmtTarih(r.termin) + '</td>' +
                '<td class="up-proses-dinamik up-col-proses">' + renderProsesInline(r.prosesler, 6, r.plan_id) + '</td>' +
                '<td class="up-enj-makine-col">' + enjMakineTxt + '</td>' +
                '<td>' + fmtTarih(r.plan_baslangic) + '</td>' +
                '<td>' + fmtTarih(r.plan_bitis) + '</td>' +
                '<td class="num">' + esc(r.oncelik || '—') + '</td>' +
                '<td>' + durumBadge(r.durum, r.durum_renk, r.yuzde) + '</td>' +
                '<td class="up-col-aksiyon">' + aksiyon + '</td>';

            tr.addEventListener('click', function (ev) {
                if (ev.target.closest('.up-aksiyon-wrap')) return;
                if (ev.target.closest('.up-proses-step')) return;
                if (r.plan_id) openDetay(r.plan_id);
            });
            tr.querySelectorAll('.up-proses-step').forEach(function (btn) {
                btn.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    var kod = btn.getAttribute('data-proses-kod');
                    if (r.plan_id) openDetay(r.plan_id, kod);
                });
            });
            var wrap = tr.querySelector('.up-aksiyon-wrap');
            if (wrap) {
                wrap.querySelector('[data-act=menu]').addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    document.querySelectorAll('.up-aksiyon-menu.open').forEach(function (m) { m.classList.remove('open'); });
                    wrap.querySelector('.up-aksiyon-menu').classList.toggle('open');
                });
                wrap.querySelector('[data-act=edit]').addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    openEdit(r.plan_id);
                });
                wrap.querySelector('[data-act=remove]').addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    if (confirm('Plan listeden kaldırılsın mı?')) deactivatePlan(r.plan_id);
                });
            }
            body.appendChild(tr);
        });
        if ($('upToplam')) $('upToplam').textContent = 'Toplam ' + rows.length + ' kayıt';
    }

    function fetchPlanlar() {
        showError('');
        $('upBody').innerHTML = '<tr><td colspan="15" class="up-loading">Yükleniyor…</td></tr>';
        fetch('/planlama/uretim-plan/api/planlar?donem=' + encodeURIComponent(state.donem), { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj || 'Hata');
                state.satirlar = d.satirlar || [];
                renderTable(state.satirlar);
                if ($('upKaynak')) $('upKaynak').textContent = d.kaynak || 'Korgun';
            })
            .catch(function (e) {
                showError(e.message);
                $('upBody').innerHTML = '<tr><td colspan="15" class="up-loading">Yüklenemedi</td></tr>';
            });
    }

    function renderCreateListe(list) {
        var el = $('upCreateListe');
        if (!el) return;
        el.innerHTML = '';
        list.forEach(function (o) {
            var div = document.createElement('div');
            div.className = 'up-create-item' + (state.seciliCreate === o.canonical_key ? ' selected' : '');
            div.innerHTML =
                '<input type="radio" name="upCreateSel" ' + (state.seciliCreate === o.canonical_key ? 'checked' : '') + '>' +
                thumbHtml(o, 'up-create-thumb') +
                '<div class="up-create-item-info">' +
                '<strong>' + esc(o.model_kod) + '</strong>' +
                '<div>' + esc(o.renk) + '</div>' +
                '<div class="up-create-item-meta">' + fmtN(o.miktar) + ' ' + esc(o.birim || 'CIFT') +
                ' · Termin: ' + fmtTarih(o.termin) + '<br>' +
                esc(o.m_emir_sayisi || 0) + ' M emir / ' + esc(o.y_emir_sayisi || 0) + ' Y emir</div></div>';
            div.addEventListener('click', function () {
                state.seciliCreate = o.canonical_key;
                state.seciliCreateData = o;
                renderCreateListe(list);
                showCreateForm(o);
            });
            el.appendChild(div);
        });
    }

    function showCreateForm(o) {
        if (!o) return;
        // has_enjeksiyon guard: alan hiç gelmemişse sessiz false kabul etme
        if (!Object.prototype.hasOwnProperty.call(o, 'has_enjeksiyon')) {
            showError('Ürünün proses bilgisi alınamadı. Lütfen tekrar getir.');
            return;
        }
        state.requiresEnj = o.has_enjeksiyon === true;
        state.createStep = 1;
        // Modal yeniden açıldığında step3 form alanlarını temizle (stale tarih engeli)
        if ($('upFormBas')) $('upFormBas').value = '';
        if ($('upFormBit')) $('upFormBit').value = '';
        if ($('upFormNot')) $('upFormNot').value = '';
        state.step3.basMode = null;
        state.step3.saveBlocked = false;
        state.step3.bitisUyari = null;
        wizardShowStep(1);
        if ($('upStep1Readonly')) {
            $('upStep1Readonly').style.display = 'block';
            $('upStep1Readonly').innerHTML =
                '<strong>' + esc(o.model_kod) + '</strong> · ' + esc(o.renk) +
                '<br>Sipariş: ' + esc(o.sip_no) + ' · Cari: ' + esc(o.musteri || '—') +
                '<br>Miktar: ' + fmtN(o.miktar) + ' · Termin: ' + fmtTarih(o.termin) +
                (o.asorti ? '<br>Asorti: ' + esc(o.asorti) : '') +
                (state.requiresEnj ? '<br><em>Proses 26 Enjeksiyon — ADIM 2 gerekli</em>' : '');
        }
        if ($('upEnjPlanCift')) $('upEnjPlanCift').value = o.miktar || '';
        if ($('upWizardStep2')) {
            $('upWizardStep2').style.display = state.requiresEnj ? '' : 'none';
        }
        enjReset();
        if (state.requiresEnj) {
            enjYukleKapasite();
            enjYukleKaliplar();
            enjYukleSonHaftaHiz(null);
        }
        wizardUpdateNav();
    }

    function wizardShowStep(n) {
        state.createStep = n;
        clearPlanErrors();
        [1, 2, 3].forEach(function (s) {
            var p = $('upStep' + s);
            if (p) p.style.display = (s === n) ? 'block' : 'none';
            var st = document.querySelector('.up-wizard-step[data-step="' + s + '"]');
            if (st) st.classList.toggle('active', s === n);
        });
        if (n === 3) initStep3();
        wizardUpdateNav();
    }

    function fmtDateTr(iso) {
        if (!iso) return '—';
        var p = String(iso).slice(0, 10).split('-');
        if (p.length !== 3) return iso;
        return p[2] + '.' + p[1] + '.' + p[0];
    }

    function dateOnlyFromApi(v) {
        if (!v) return null;
        return String(v).replace('T', ' ').slice(0, 10);
    }

    // ---- Dönem → [başlangıç, bitiş] hesabı (Python donem_aralik'ın JS karşılığı) ----
    function donemAralikJs(donem) {
        // Türkiye yerel tarihini ISO string olarak döner (UTC kayma yok)
        var now = new Date();
        var todayIso = now.getFullYear() + '-' +
            String(now.getMonth() + 1).padStart(2, '0') + '-' +
            String(now.getDate()).padStart(2, '0');
        function addDays(iso, n) {
            var p = iso.split('-');
            var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
            d.setDate(d.getDate() + n);
            return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
        }
        function weekStart(iso) {
            var p = iso.split('-');
            var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
            var dow = d.getDay(); // 0=Sun,1=Mon
            var diff = (dow === 0) ? -6 : 1 - dow; // Pazartesi başlangıç
            d.setDate(d.getDate() + diff);
            return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
        }
        if (donem === 'bu_hafta') {
            var ws = weekStart(todayIso);
            return { bas: ws, bit: addDays(ws, 6) };
        }
        if (donem === 'gelecek_hafta') {
            var ws2 = weekStart(todayIso);
            var nw = addDays(ws2, 7);
            return { bas: nw, bit: addDays(nw, 6) };
        }
        if (donem === 'bu_ay') {
            var p2 = todayIso.split('-');
            var yr = parseInt(p2[0], 10), mo = parseInt(p2[1], 10);
            var ayBas = yr + '-' + String(mo).padStart(2, '0') + '-01';
            var nextMo = mo === 12 ? new Date(yr + 1, 0, 1) : new Date(yr, mo, 1);
            nextMo.setDate(nextMo.getDate() - 1);
            var ayBit = nextMo.getFullYear() + '-' + String(nextMo.getMonth() + 1).padStart(2, '0') + '-' + String(nextMo.getDate()).padStart(2, '0');
            return { bas: ayBas, bit: ayBit };
        }
        if (donem === '3_ay') {
            return { bas: todayIso, bit: addDays(todayIso, 92) };
        }
        // 'gecmis' veya bilinmeyen
        return { bas: todayIso, bit: todayIso };
    }

    function initStep3() {
        enjRenderStep3Reservation();

        var rez = state.enj.reservation || {};
        var enjBas = dateOnlyFromApi(rez.baslangic || state.enj.baslangic);
        var enjBit = dateOnlyFromApi(rez.bitis || (state.enj.motorResult && state.enj.motorResult.tahmini_bitis));
        var afterEnj = enjBit;
        if (enjBas && enjBit) {
            var dp = enjBit.split('-');
            var d = new Date(parseInt(dp[0], 10), parseInt(dp[1], 10) - 1, parseInt(dp[2], 10));
            d.setDate(d.getDate() + 1);
            afterEnj = d.getFullYear() + '-' +
                String(d.getMonth() + 1).padStart(2, '0') + '-' +
                String(d.getDate()).padStart(2, '0');
        }

        state.step3.basMode = null;

        // Enjeksiyon yoksa donem_aralik'tan üretilen tarihleri kullan
        if (!enjBas && !afterEnj) {
            var donem = ($('upFormDonem') && $('upFormDonem').value) || 'bu_hafta';
            var aralik = donemAralikJs(donem);
            // upFormBit'i dönem bitiş tarihiyle doldur
            if ($('upFormBit') && !$('upFormBit').value) {
                $('upFormBit').value = aralik.bit;
            }
            // Başlangıç seçeneğini dönem başı olarak sun
            var fakeSecenekler = [{ tarih: aralik.bas, dolu: false, oneri_donem: donem }];
            renderStep3BasSecenekleri(fakeSecenekler, aralik.bas, null);
            return;
        }

        fetchStep3OnCheck([enjBas, afterEnj].filter(Boolean), function (secenekler) {
            renderStep3BasSecenekleri(secenekler, enjBas, afterEnj);
        });
    }

    function renderStep3BasSecenekleri(secenekler, enjBas, afterEnj) {
        var el = $('upStep3BasSecenekleri');
        if (!el) return;
        state.step3.secenekler = secenekler;
        el.innerHTML = '';
        var opts = [
            { mode: 'enj_bas', key: enjBas, label: enjBas ? 'Enjeksiyon başlangıç günü' : 'Dönem başlangıcı' },
            { mode: 'after_enj', key: afterEnj, label: 'Enjeksiyon tamamlandıktan sonraki uygun gün' },
        ];
        var firstSelectable = null;
        opts.forEach(function (opt) {
            if (!opt.key) return;
            var sec = secenekler.find(function (s) { return s.tarih === opt.key; }) || {};
            var dolu = !!sec.dolu;
            var lbl = document.createElement('label');
            lbl.className = 'up-step3-radio' + (dolu ? ' disabled' : '');
            lbl.innerHTML =
                '<input type="radio" name="upStep3Bas" value="' + esc(opt.mode) + '"' +
                (dolu ? ' disabled' : '') + '>' +
                '<span><strong>' + esc(opt.label) + '</strong><br>' +
                '<span class="up-step3-radio-meta">' + esc(fmtDateTr(opt.key)) + '</span>' +
                (dolu ? '<br><span class="up-step3-radio-tag">KULLANILAMAZ — bu dönemde plan mevcut</span>' : '') +
                '</span>';
            if (!dolu) {
                lbl.querySelector('input').addEventListener('change', function () {
                    state.step3.basMode = opt.mode;
                    applyStep3Baslangic(opt.key, sec.oneri_donem);
                    el.querySelectorAll('.up-step3-radio').forEach(function (r) {
                        r.classList.toggle('selected', r === lbl);
                    });
                });
                if (!firstSelectable) {
                    firstSelectable = { mode: opt.mode, key: opt.key, donem: sec.oneri_donem, lbl: lbl };
                }
            }
            el.appendChild(lbl);
        });

        var customInp = $('upFormBasCustom');
        if (customInp && !customInp._bound) {
            customInp._bound = true;
            customInp.addEventListener('change', function () {
                state.step3.basMode = 'custom';
                el.querySelectorAll('.up-step3-radio').forEach(function (r) {
                    r.classList.remove('selected');
                });
                fetchStep3OnCheck([customInp.value], function (secs) {
                    var s0 = secs[0] || {};
                    if (s0.dolu) {
                        showStep3Uyari(s0.mesaj || 'KULLANILAMAZ — bu dönemde plan mevcut');
                        state.step3.saveBlocked = true;
                        wizardUpdateNav();
                        return;
                    }
                    showStep3Uyari('');
                    applyStep3Baslangic(customInp.value, s0.oneri_donem);
                });
            });
        }

        if (firstSelectable) {
            firstSelectable.lbl.querySelector('input').checked = true;
            firstSelectable.lbl.classList.add('selected');
            state.step3.basMode = firstSelectable.mode;
            applyStep3Baslangic(firstSelectable.key, firstSelectable.donem);
        }
    }

    function showStep3Uyari(msg) {
        var el = $('upStep3BasUyari');
        if (!el) return;
        if (msg) { el.textContent = msg; el.style.display = 'block'; }
        else { el.style.display = 'none'; }
    }

    function applyStep3Baslangic(isoDate, oneriDonem) {
        if ($('upFormBas')) $('upFormBas').value = isoDate || '';
        if (oneriDonem && $('upFormDonem')) $('upFormDonem').value = oneriDonem;
        if ($('upFormBit')) {
            $('upFormBit').min = isoDate || '';
            if ($('upFormBit').value && isoDate && $('upFormBit').value < isoDate) {
                $('upFormBit').value = isoDate;
            }
        }
        state.step3.saveBlocked = false;
        validateStep3Tarihleri();
    }

    function fetchStep3OnCheck(tarihler, cb) {
        var o = state.seciliCreateData;
        if (!o || !tarihler.length) { cb([]); return; }
        fetch('/planlama/uretim-plan/api/plan/on-check', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sip_no: o.sip_no,
                sip_harinx: o.sip_harinx,
                mamul_skod: o.model_kod || o.mamul_skod,
                rkod: o.rkod,
                tarihler: tarihler,
            }),
        }).then(function (r) { return r.json(); })
          .then(function (d) { cb((d.ok && d.secenekler) ? d.secenekler : []); })
          .catch(function () { cb([]); });
    }

    function validateStep3Tarihleri() {
        var bas = ($('upFormBas') && $('upFormBas').value) || '';
        var bit = ($('upFormBit') && $('upFormBit').value) || '';
        var uyari = '';
        if (bas && bit && bit < bas) {
            uyari = 'Plan bitiş, plan başlangıçtan önce olamaz';
            state.step3.saveBlocked = true;
        } else if (state.requiresEnj && bit && state.enj.bitis) {
            var eb = dateOnlyFromApi(state.enj.motorResult && state.enj.motorResult.tahmini_bitis
                ? state.enj.motorResult.tahmini_bitis : state.enj.bitis);
            if (eb && bit < eb) {
                uyari = 'Plan bitiş enjeksiyon tahmini bitişinden (' + fmtDateTr(eb) + ') önce';
                state.step3.saveBlocked = true;
            }
        } else {
            state.step3.saveBlocked = false;
        }
        state.step3.bitisUyari = uyari || null;
        showStep3Uyari(uyari);
        wizardUpdateNav();
    }

    function step3CanSave() {
        if (state.step3.saveBlocked) return false;
        if (!$('upFormBas') || !$('upFormBas').value) return false;
        return true;
    }

    function enjUpdateManualRefVisibility() {
        var cm = state.enj.calismaModu || 'GUNDUZ_GECE';
        var gW = $('upEnjManualGunduzWrap');
        var eW = $('upEnjManualGeceWrap');
        var wrap = $('upEnjManualRefWrap');
        if (wrap) wrap.style.display = '';
        // Vardiya saatlerini bant olarak göster
        var bantEl = $('upEnjVardiyaSaatBant');
        if (bantEl) {
            var bant = [];
            if (cm !== 'GECE')   bant.push('<span class="up-enj-vd-pill up-vd-gunduz">Gündüz</span> 07:00–17:00 <span style="color:#94a3b8">· 10 saat/vardiya</span>');
            if (cm !== 'GUNDUZ') bant.push('<span class="up-enj-vd-pill up-vd-gece">Gece</span> 17:00–07:00 <span style="color:#94a3b8">· 14 saat/vardiya</span>');
            bantEl.innerHTML = bant.join('<span style="color:#cbd5e1;margin:0 4px">|</span>');
        }
        // Doluluk bandı makine modunu güncelle
        var dolEl = $('upEnjDolulukBant');
        var dolMode = $('upEnjDolulukModeLabel');
        if (dolEl && dolMode) {
            dolMode.textContent = enjCalismaLabel(cm);
            dolEl.style.display = state.enj.gridData && state.enj.gridData.length ? '' : 'none';
        }
        if (gW) gW.style.display = cm !== 'GECE' ? '' : 'none';
        if (eW) eW.style.display = cm !== 'GUNDUZ' ? '' : 'none';
        // Auto-ref hint ve autofill güncelle
        enjUpdateAutoRefHints();
    }

    function enjSyncReferenceModeFromDom() {
        // referenceMode: kullanıcı "Kullan" butonuna basıp onaylayana kadar MANUAL.
        // refConfirmedGunduz / refConfirmedGece onay durumunu takip eder.
        state.enj.manualRefGunduz = $('upEnjManualGunduz') && $('upEnjManualGunduz').value
            ? parseFloat($('upEnjManualGunduz').value) : null;
        state.enj.manualRefGece = $('upEnjManualGece') && $('upEnjManualGece').value
            ? parseFloat($('upEnjManualGece').value) : null;
        // Kullanıcı manuel değiştirirse kaynak MANUAL olur
        // (kaynak, "Kullan" click handler'ında HISTORICAL_CONFIRMED olarak set edilir)
        state.enj.referenceMode = 'MANUAL';
    }

    function enjUpdateLowConfHint(d) {
        // HESAPLA sonrasında auto_gunduz_reference / auto_gece_reference'ı state'e al
        // ve hint panelini güncelle. AUTO moda geçme — kullanıcı onayı gerekiyor.
        if (d && (d.auto_gunduz_reference || d.auto_gece_reference)) {
            // Zaten yüklenmiş autoRef'i override etme; sadece boşsa güncelle
            if (!state.enj.autoRefGunduz || !state.enj.autoRefGunduz.reference_value) {
                state.enj.autoRefGunduz = d.auto_gunduz_reference || d.gunduz_reference || {};
            }
            if (!state.enj.autoRefGece || !state.enj.autoRefGece.reference_value) {
                state.enj.autoRefGece = d.auto_gece_reference || d.gece_reference || {};
            }
        }
        enjUpdateAutoRefHints();
    }

    function enjRefConfidenceLabel(conf) {
        return { YUKSEK: 'Yüksek güven', ORTA: 'Orta güven', DUSUK: 'Düşük güven', YETERSIZ: 'Yetersiz veri' }[conf] || conf;
    }

    function enjUpdateAutoRefHints() {
        // Her aktif vardiya için geçmiş veri durumunu göster.
        // YETERSIZ confidence'ta da değer + örnek bilgisi gösterilir.
        // Otomatik doldurma YOK — kullanıcı "Kullan" / "Manuel doğrulayarak kullan" butonuna basmalı.
        var cm = state.enj.calismaModu || 'GUNDUZ_GECE';
        var autoG = state.enj.autoRefGunduz || {};
        var autoE = state.enj.autoRefGece || {};
        var mkod = state.enj.makineKod;
        var DAYS_LABEL = 'son ' + (state.enj._sonHaftaDays || 7) + ' gün';

        // ── Gündüz ──────────────────────────────────────────────────────
        var hintGEl = $('upEnjAutoRefGunduzHint');
        var fillGEl = $('upEnjAutoFillGunduz');
        if (hintGEl && cm !== 'GECE') {
            var gHasData = autoG.reference_value > 0 && (autoG.sample_count || 0) > 0;
            if (gHasData) {
                var confG    = enjRefConfidenceLabel(autoG.confidence);
                var sampleG  = autoG.sample_count || 0;
                var medG     = Math.round(autoG.reference_value);
                var minG     = autoG.min != null ? Math.round(autoG.min) : null;
                var maxG     = autoG.max != null ? Math.round(autoG.max) : null;
                var rangeG   = (minG != null && maxG != null) ? ' · aralık ' + minG + '–' + maxG : '';
                hintGEl.innerHTML = '<strong>' + medG + ' tur/vd</strong> — ' + confG +
                    ' · ' + sampleG + ' örnek (' + DAYS_LABEL + ')' + rangeG;
                hintGEl.className = 'up-enj-ref-hint ' + (autoG.confidence === 'YUKSEK' ? 'ok' : 'warn');
                hintGEl.style.display = '';
                if (fillGEl) {
                    // YETERSIZ: uyarılı buton; diğerleri: normal buton
                    fillGEl.style.display = '';
                    if (autoG.confidence === 'YETERSIZ' || sampleG < 3) {
                        fillGEl.textContent = 'Manuel doğrulayarak kullan';
                        fillGEl.dataset.confirm = '1';
                    } else {
                        fillGEl.textContent = 'Kullan';
                        fillGEl.dataset.confirm = '0';
                    }
                }
            } else {
                // Geçmiş veri yok — manuel değer girilmiş mi kontrol et
                var manG = state.enj.manualRefGunduz;
                var manGValid = manG && isFinite(manG) && manG > 0;
                if (manGValid) {
                    hintGEl.textContent = 'Manuel hız kullanılacak: ' + Math.round(manG) + ' tur/vardiya';
                    hintGEl.className = 'up-enj-ref-hint warn';
                } else {
                    var msgG = mkod
                        ? ('Gündüz vardiyası için geçmiş hız verisi yok. Manuel giriş gerekli.')
                        : 'Makine seçilmedi';
                    hintGEl.textContent = msgG;
                    hintGEl.className = 'up-enj-ref-hint err';
                }
                hintGEl.style.display = '';
                if (fillGEl) fillGEl.style.display = 'none';
            }
        } else if (hintGEl) {
            hintGEl.style.display = 'none';
            if (fillGEl) fillGEl.style.display = 'none';
        }

        // ── Gece ────────────────────────────────────────────────────────
        var hintEEl = $('upEnjAutoRefGeceHint');
        var fillEEl = $('upEnjAutoFillGece');
        if (hintEEl && cm !== 'GUNDUZ') {
            var eHasData = autoE.reference_value > 0 && (autoE.sample_count || 0) > 0;
            if (eHasData) {
                var confE    = enjRefConfidenceLabel(autoE.confidence);
                var sampleE  = autoE.sample_count || 0;
                var medE     = Math.round(autoE.reference_value);
                var minE     = autoE.min != null ? Math.round(autoE.min) : null;
                var maxE     = autoE.max != null ? Math.round(autoE.max) : null;
                var rangeE   = (minE != null && maxE != null) ? ' · aralık ' + minE + '–' + maxE : '';
                hintEEl.innerHTML = '<strong>' + medE + ' tur/vd</strong> — ' + confE +
                    ' · ' + sampleE + ' örnek (' + DAYS_LABEL + ')' + rangeE;
                hintEEl.className = 'up-enj-ref-hint ' + (autoE.confidence === 'YUKSEK' ? 'ok' : 'warn');
                hintEEl.style.display = '';
                if (fillEEl) {
                    fillEEl.style.display = '';
                    if (autoE.confidence === 'YETERSIZ' || sampleE < 3) {
                        fillEEl.textContent = 'Manuel doğrulayarak kullan';
                        fillEEl.dataset.confirm = '1';
                    } else {
                        fillEEl.textContent = 'Kullan';
                        fillEEl.dataset.confirm = '0';
                    }
                }
            } else {
                // Geçmiş veri yok — manuel değer girilmiş mi kontrol et
                var manE = state.enj.manualRefGece;
                var manEValid = manE && isFinite(manE) && manE > 0;
                if (manEValid) {
                    hintEEl.textContent = 'Manuel hız kullanılacak: ' + Math.round(manE) + ' tur/vardiya';
                    hintEEl.className = 'up-enj-ref-hint warn';
                } else {
                    hintEEl.textContent = 'Gece vardiyası için geçmiş hız verisi yok. Manuel giriş gerekli.';
                    hintEEl.className = 'up-enj-ref-hint err';
                }
                hintEEl.style.display = '';
                if (fillEEl) fillEEl.style.display = 'none';
            }
        } else if (hintEEl) {
            hintEEl.style.display = 'none';
            if (fillEEl) fillEEl.style.display = 'none';
        }

        // ── Kaynak durum bandı ───────────────────────────────────────────
        var srcEl = $('upEnjRefKaynakDurum');
        if (srcEl) {
            var cm2 = state.enj.calismaModu || 'GUNDUZ_GECE';
            var needG2 = cm2 !== 'GECE';
            var needE2 = cm2 !== 'GUNDUZ';
            var gConf = needG2 ? (state.enj.refConfirmedGunduz ? '✓ Gündüz onaylı' : null) : null;
            var eConf = needE2 ? (state.enj.refConfirmedGece   ? '✓ Gece onaylı'   : null) : null;
            var parts = [];
            if (gConf) parts.push(gConf);
            if (eConf) parts.push(eConf);
            if (parts.length) {
                srcEl.className = 'up-enj-ref-kaynak-durum auto';
                srcEl.textContent = parts.join(' · ');
            } else {
                srcEl.className = 'up-enj-ref-kaynak-durum manual';
                srcEl.textContent = '⚠ Hız referansı doğrulanmadı — "Kullan" veya manuel giriş';
            }
            srcEl.style.display = '';
        }
    }

    function wizardUpdateNav() {
        var back = $('upWizardBackBtn');
        var next = $('upWizardNextBtn');
        var save = $('upPlanaEkleBtn');
        if (!back || !next || !save) return;
        back.style.display = state.createStep > 1 ? '' : 'none';
        next.style.display = state.createStep < 3 ? '' : 'none';
        save.style.display = state.createStep === 3 ? '' : 'none';
        if (state.createStep === 1) {
            next.disabled = !state.seciliCreate;
        } else if (state.createStep === 2) {
            next.disabled = state.requiresEnj && !state.enj.hesapOk;
        } else {
            save.disabled = state.requiresEnj && !state.enj.hesapOk;
        }
    }

    // ─── ENJEKSİYON PLAN HESABI (Faz 2C.2) ─────────────────────────────────

    function enjReset() {
        var e = state.enj;
        e.makineId = null; e.makineKod = null; e.istasyonlar = []; e.slot = null;
        e.kalipId = null; e.kalipKod = null; e.kalipAdedi = null; e.gozPerKalip = 1;
        e.kalipMode = 'liste'; e.kalipBasiCift = null;
        e.turCift = null; e.baslangic = null; e.baslangicOneri = null; e.baslangicManuel = false;
        e.bitis = null; e.planCift = null;
        e.motorResult = null; e.hesapOk = false; e.gridData = null;
        e.calismaModu = 'GUNDUZ_GECE'; e.haftaSonu = 'HAYIR'; e.hsVardiya = null;
        e.ilkUygunMap = {};
        e.planOzetMap = {};
        e.istasyonPlanDurum = {};
        e.reservation = null;
        e.pendingConflict = null;
        e.referenceMode = 'MANUAL'; e.manualRefGunduz = null; e.manualRefGece = null;
        e.autoRefGunduz = null; e.autoRefGece = null;
        e._sonHaftaVeri = null;
        enjHesapGizle();
        if ($('upEnjMakineCards')) $('upEnjMakineCards').innerHTML = '';
        if ($('upEnjIstasyonGrid')) $('upEnjIstasyonGrid').innerHTML = '';
        if ($('upEnjKalip')) { $('upEnjKalip').value = ''; $('upEnjKalip').disabled = true; }
        if ($('upEnjKalipManuelKod')) $('upEnjKalipManuelKod').value = '';
        if ($('upEnjKalipManuelKbc')) $('upEnjKalipManuelKbc').value = '';
        if ($('upEnjKalipAdedi')) $('upEnjKalipAdedi').value = '';
        if ($('upEnjGozPerKalip')) $('upEnjGozPerKalip').value = '1';
        enjSetKalipMode('liste');
        if ($('upEnjSlotA')) $('upEnjSlotA').classList.remove('selected');
        if ($('upEnjSlotB')) $('upEnjSlotB').classList.remove('selected');
        if ($('upEnjHesapBtn')) $('upEnjHesapBtn').disabled = true;
        if ($('upEnjUyari')) { $('upEnjUyari').style.display = 'none'; $('upEnjUyari').textContent = ''; }
        if ($('upEnjIstasyonUyari')) { $('upEnjIstasyonUyari').style.display = 'none'; $('upEnjIstasyonUyari').textContent = ''; }
        if ($('upEnjCakismaUyari')) $('upEnjCakismaUyari').style.display = 'none';
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        var _ew = $('upEnjBasEarlyWarn');
        if (_ew) _ew.style.display = 'none';
        if ($('upEnjManualGece')) $('upEnjManualGece').value = '';
        // Reset auto-ref state
        state.enj.autoRefGunduz     = {};
        state.enj.autoRefGece       = {};
        state.enj.refSourceGunduz   = null;
        state.enj.refSourceGece     = null;
        state.enj.refConfirmedGunduz = false;
        state.enj.refConfirmedGece   = false;
        // Hint ve disabled sebep temizle
        if ($('upEnjHesapBtnHint')) $('upEnjHesapBtnHint').style.display = 'none';
        if ($('upEnjRefKaynakDurum')) $('upEnjRefKaynakDurum').style.display = 'none';
        enjUpdateManualRefVisibility();
        enjUpdateGozField();
    }

    function enjHesapGizle() {
        if ($('upEnjHesapOzet')) $('upEnjHesapOzet').style.display = 'none';
        state.enj.hesapOk = false;
        state.enj.reservation = null;
        wizardUpdateNav();
    }

    function enjUpdateToplamGozHint() {
        var hint = $('upEnjToplamGozHint');
        if (!hint) return;
        var ka = parseInt(($('upEnjKalipAdedi') && $('upEnjKalipAdedi').value) || '0', 10) || 0;
        var gp = parseInt(($('upEnjGozPerKalip') && $('upEnjGozPerKalip').value) || '1', 10) || 1;
        hint.textContent = ka > 0
            ? ('Toplam aktif göz: ' + (ka * gp) + ' (' + ka + ' kalıp × ' + gp + ' göz/kalıp)')
            : 'Toplam aktif göz = kalıp adedi × göz/kalıp';
    }

    function enjSideTimelineHtml(sideData, sideClass) {
        if (!sideData) return '';
        var rows = (sideData.timeline || []).slice(0, 3).map(function (seg) {
            var bas = enjFmtDtApi(seg.bas);
            var bit = enjFmtDtApi(seg.bit);
            var cls = seg.tip === 'DOLU' ? 'dolu' : 'bos';
            var lbl = seg.tip === 'DOLU'
                ? ('DOLU — ' + (seg.label || seg.sip_no || ''))
                : 'BOŞ / PLANLANABİLİR';
            return '<div class="up-enj-timeline-row ' + cls + '">' +
                esc(bas) + ' → ' + esc(bit) + '<br>' + esc(lbl) + '</div>';
        }).join('');
        var ilk = sideData.ilk_uygun_gosterim || sideData.ilk_uygun_tam || '—';
        return '<div class="up-enj-card-side ' + sideClass + '">' +
            '<div class="up-enj-card-side-title">' + (sideClass === 'side-a' ? 'A TARAFI' : 'B TARAFI') + '</div>' +
            '<div>İlk uygun: <strong>' + esc(ilk) + '</strong></div>' +
            rows +
            '</div>';
    }

    function enjShowConflictModal(detail) {
        if (!detail) return;
        state.enj.pendingConflict = detail;
        var modal = $('upEnjConflictModal');
        var body = $('upEnjConflictBody');
        if (!modal || !body) return;
        body.innerHTML =
            '<dl class="up-conflict-body-dl">' +
            '<dt>Makine</dt><dd>' + esc(detail.makine_kod || '—') + '</dd>' +
            '<dt>Taraf</dt><dd>' + esc(detail.slot || '—') + '</dd>' +
            '<dt>Çakışan istasyon</dt><dd>İST' + esc(detail.istasyon_no || '—') + '</dd>' +
            '<dt>Çakışan plan</dt><dd>' + esc(detail.cakisan_plan || '—') + '</dd>' +
            '<dt>Dolu</dt><dd>' + esc(detail.plan_bas_gosterim || detail.plan_baslangic || '—') +
            ' → ' + esc(detail.plan_bit_gosterim || detail.plan_bitis || '—') + '</dd>' +
            '<dt>İlk uygun başlangıç</dt><dd>' + esc(detail.ilk_uygun_gosterim || detail.ilk_uygun || '—') + '</dd>' +
            '</dl>';
        if ($('upEnjConflictApply')) {
            $('upEnjConflictApply').style.display = detail.ilk_uygun ? '' : 'none';
        }
        modal.hidden = false;
    }

    function enjHideConflictModal() {
        var modal = $('upEnjConflictModal');
        if (modal) modal.hidden = true;
        state.enj.pendingConflict = null;
    }

    function enjApplyConflictIlkUygun() {
        var d = state.enj.pendingConflict;
        if (!d || !d.ilk_uygun) return;
        enjHideConflictModal();
        state.enj.baslangic = d.ilk_uygun;
        state.enj.baslangicManuel = true;
        if ($('upEnjBas')) $('upEnjBas').value = enjApiDtToLocal(d.ilk_uygun);
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        enjHesapGizle();
        enjFetchIstasyonPlanDurum(function () {
            var m = (state.enj.gridData || []).find(function (x) {
                return (x.makine_id || x.id) === state.enj.makineId;
            });
            if (m) enjRenderIstasyonGrid(m);
        });
        enjUpdateHesapBtn();
    }

    function enjOpenConflictCalendar() {
        var d = state.enj.pendingConflict || {};
        var kod = d.makine_kod || state.enj.makineKod || 'M1';
        var anchor = (d.plan_baslangic || state.enj.baslangic || '').slice(0, 10);
        var url = '/planlama/enjeksiyon-plan?makine=' + encodeURIComponent(kod);
        if (anchor) url += '&view=bu_hafta&anchor=' + anchor;
        window.open(url, '_blank');
    }

    function enjFreezeReservation(d) {
        var e = state.enj;
        var mr = d || e.motorResult || {};
        var istStr = e.istasyonlar.map(function (x) { return 'İST' + x; }).join('–');
        // B PHASE CLEANUP: daima MANUEL mod, kaynak takibi ile
        var refLbl = '—';
        var rv = mr.manual_reference_gunduz || e.manualRefGunduz;
        if (e.calismaModu === 'GECE') rv = mr.manual_reference_gece || e.manualRefGece;
        var srcG = e.refSourceGunduz || 'MANUAL';
        var srcE = e.refSourceGece   || 'MANUAL';
        var activeSrc = (e.calismaModu === 'GECE') ? srcE : srcG;
        var modeLbl = (activeSrc === 'HISTORICAL_CONFIRMED') ? 'GEÇMİŞ(onaylı)' : 'MANUEL';
        refLbl = rv != null ? (modeLbl + ' ' + Math.round(rv) + ' tur/vardiya') : modeLbl;
        e.reservation = {
            makineKod: e.makineKod,
            slot: e.slot,
            istasyonlar: e.istasyonlar.slice(),
            istStr: istStr,
            kalipKod: e.kalipKod,
            kalipAdedi: e.kalipAdedi,
            gozPerKalip: e.gozPerKalip,
            kalipBasiCift: e.kalipBasiCift,
            planCift: e.planCift,
            gerekliTur: mr.gerekli_tam_tur || mr.tahmini_gerekli_tur,
            refLabel: refLbl,
            baslangic: e.baslangic,
            bitis: mr.tahmini_bitis || e.bitis,
            calismaModu: e.calismaModu,
            motorResult: JSON.parse(JSON.stringify(mr)),
        };
    }

    function enjRenderStep3Reservation() {
        var wrap = $('upStep3EnjRezerv');
        var body = $('upStep3EnjRezervBody');
        var legacy = $('upStep3EnjOzet');
        var rez = state.enj.reservation;
        if (!wrap || !body || !state.requiresEnj || !state.enj.hesapOk || !rez) {
            if (wrap) wrap.style.display = 'none';
            if (legacy) legacy.style.display = 'none';
            return;
        }
        wrap.style.display = 'block';
        if (legacy) legacy.style.display = 'none';
        body.innerHTML =
            '<div class="up-step3-rezerv-line"><strong>' + esc(rez.makineKod) + ' / ' + esc(rez.slot) +
            '</strong> · ' + esc(rez.istStr) + ' · ' + esc(rez.kalipAdedi) + ' kalıp</div>' +
            '<div class="up-step3-rezerv-line">' + esc(rez.kalipKod || '—') + '</div>' +
            '<div class="up-step3-rezerv-line">' + fmtN(rez.planCift) + ' çift · ' +
            esc(rez.gerekliTur) + ' tur · Referans: ' + esc(rez.refLabel) + '</div>' +
            '<div class="up-step3-rezerv-line">' + esc(enjFmtDtApi(rez.baslangic)) + ' → ' +
            esc(enjFmtDtApi(rez.bitis)) + '</div>';
    }

    function enjFetchIstasyonPlanDurum(cb) {
        var e = state.enj;
        if (!e.makineId || !e.slot || !e.baslangic) {
            e.istasyonPlanDurum = {};
            if (cb) cb();
            return;
        }
        fetch('/planlama/uretim-plan/api/enj/istasyon-plan-durum', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                makine_id: e.makineId,
                slot: e.slot,
                istasyonlar: Array.from({ length: e.istasyonSayisi || 8 }, function (_, i) { return i + 1; }),
                plan_baslangic: e.baslangic,
            }),
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              e.istasyonPlanDurum = {};
              if (d.ok && d.istasyonlar) {
                  d.istasyonlar.forEach(function (row) {
                      e.istasyonPlanDurum[row.istasyon_no] = row;
                  });
              }
              if (cb) cb();
          })
          .catch(function () { if (cb) cb(); });
    }

    function enjYuklePlanOzet(cb) {
        var e = state.enj;
        var q = 'days=7&calisma_modu=' + encodeURIComponent(e.calismaModu || 'GUNDUZ_GECE') +
            '&hafta_sonu_calisma=' + encodeURIComponent(e.haftaSonu || 'HAYIR');
        if (e.baslangic) q += '&anchor=' + encodeURIComponent(e.baslangic.slice(0, 10));
        fetch('/planlama/uretim-plan/api/enj/makine-plan-ozet?' + q, { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                e.planOzetMap = {};
                if (d.ok && d.makineler) {
                    d.makineler.forEach(function (m) {
                        e.planOzetMap[m.makine_id] = m;
                    });
                }
                if (cb) cb();
            })
            .catch(function () { if (cb) cb(); });
    }

    function enjDtLocalToApi(v) {
        if (!v) return null;
        return v.replace('T', ' ') + ':00';
    }

    function enjFmtDtApi(v) {
        if (!v) return '—';
        var p = String(v).replace('T', ' ').slice(0, 16);
        var d = p.split(' ');
        if (d.length !== 2) return v;
        var dp = d[0].split('-');
        return dp[2] + '.' + dp[1] + '.' + dp[0] + ' ' + d[1].slice(0, 5);
    }

    function enjCalismaLabel(v) {
        return { GUNDUZ: 'Gündüz', GECE: 'Gece', GUNDUZ_GECE: 'Gündüz + Gece' }[v] || v;
    }

    function enjApiDtToLocal(v) {
        if (!v) return '';
        var p = String(v).replace('T', ' ').slice(0, 19);
        var parts = p.split(' ');
        if (parts.length !== 2) return '';
        return parts[0] + 'T' + parts[1].slice(0, 5);
    }

    function enjSetKalipMode(mode) {
        state.enj.kalipMode = mode;
        var liste = mode === 'liste';
        if ($('upEnjKalipModeListe')) $('upEnjKalipModeListe').classList.toggle('selected', liste);
        if ($('upEnjKalipModeManuel')) $('upEnjKalipModeManuel').classList.toggle('selected', !liste);
        if ($('upEnjKalipListeWrap')) $('upEnjKalipListeWrap').style.display = liste ? '' : 'none';
        if ($('upEnjKalipManuelWrap')) $('upEnjKalipManuelWrap').style.display = liste ? 'none' : '';
        if (liste) {
            state.enj.kalipKod = null;
            if ($('upEnjKalipManuelKod')) $('upEnjKalipManuelKod').value = '';
            if ($('upEnjKalipManuelKbc')) $('upEnjKalipManuelKbc').value = '';
        } else {
            state.enj.kalipId = null;
            if ($('upEnjKalip')) $('upEnjKalip').value = '';
        }
        enjHesapGizle();
        enjUpdateGozField();
        enjUpdateHesapBtn();
    }

    function enjUpdateGozField() {
        var goz = $('upEnjGozPerKalip');
        if (!goz) return;
        var liste = state.enj.kalipMode === 'liste';
        goz.readOnly = liste;
        goz.classList.toggle('up-readonly', liste);
    }

    function enjYukleKalipGoz() {
        var e = state.enj;
        if (e.kalipMode !== 'liste' || !e.kalipId) return;
        var q = 'kalip_id=' + encodeURIComponent(e.kalipId);
        if (e.makineId) q += '&makine_id=' + encodeURIComponent(e.makineId);
        if (e.slot) q += '&slot=' + encodeURIComponent(e.slot);
        fetch('/planlama/uretim-plan/api/enj/kalip-kapasite?' + q, { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok || !d.kapasite) return;
                var kap = d.kapasite;
                var ag = parseInt(kap.aktif_goz_sayisi, 10);
                if (ag > 0) {
                    e.gozPerKalip = ag;
                    if ($('upEnjGozPerKalip')) $('upEnjGozPerKalip').value = String(ag);
                }
                if (kap.kalip_basi_cift) {
                    e.kalipBasiCift = parseFloat(kap.kalip_basi_cift);
                }
                enjHesapGizle();
                enjUpdateHesapBtn();
            });
    }

    function enjIstasyonUyariMesaji() {
        var e = state.enj;
        var ka = e.kalipAdedi;
        var n = e.istasyonlar.length;
        if (!ka || !n) return '';
        if (ka > n) return ka + ' kalıp için yalnızca ' + n + ' istasyon seçildi — kalıp adedi aşılamaz.';
        if (ka < n) return ka + ' kalıp için ' + n + ' istasyon seçildi. Hangi ' + ka + ' istasyon kullanılacak?';
        return '';
    }

    function enjSyncInputsFromDom() {
        var e = state.enj;
        if ($('upEnjPlanCift')) {
            e.planCift = parseFloat($('upEnjPlanCift').value) || null;
        }
        if ($('upEnjKalipAdedi')) {
            e.kalipAdedi = parseInt($('upEnjKalipAdedi').value, 10) || null;
        }
        if ($('upEnjGozPerKalip')) {
            e.gozPerKalip = parseInt($('upEnjGozPerKalip').value, 10) || 1;
        }
        if ($('upEnjBas')) {
            e.baslangic = enjDtLocalToApi($('upEnjBas').value);
        }
        if ($('upEnjCalismaModu')) {
            e.calismaModu = $('upEnjCalismaModu').value;
        }
        if ($('upEnjHaftaSonu')) {
            e.haftaSonu = $('upEnjHaftaSonu').value;
            e.hsVardiya = e.haftaSonu === 'EVET' && $('upEnjHsVardiya')
                ? $('upEnjHsVardiya').value : null;
        }
        if (e.kalipMode === 'manuel') {
            e.kalipKod = ($('upEnjKalipManuelKod') && $('upEnjKalipManuelKod').value.trim()) || null;
            e.kalipBasiCift = $('upEnjKalipManuelKbc')
                ? parseFloat($('upEnjKalipManuelKbc').value) || null : null;
            e.kalipId = null;
        } else {
            // Liste modunda DOM'dan kalipId ve kalipBasiCift senkronize et
            // (programmatic select change event'i listener'ı tetiklemeyebilir)
            var kalipSel = $('upEnjKalip');
            if (kalipSel && kalipSel.value) {
                var selOpt = kalipSel.options[kalipSel.selectedIndex];
                var domKalipId = parseInt(kalipSel.value, 10) || null;
                if (domKalipId) {
                    e.kalipId = domKalipId;
                    // Her zaman DOM'dan kalipBasiCift oku (change event garantisi yok)
                    if (selOpt && selOpt.dataset && selOpt.dataset.kbc) {
                        var kbc = parseFloat(selOpt.dataset.kbc);
                        if (kbc > 0) e.kalipBasiCift = kbc;
                    }
                }
            }
        }
        // İstasyon grid'inden checked istasyonları state ile senkronize et
        var istGrid = $('upEnjIstasyonGrid');
        if (istGrid) {
            var cbs = istGrid.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)');
            if (cbs.length > 0) {
                var domIstasyonlar = [];
                cbs.forEach(function (cb) {
                    var n = parseInt(cb.value, 10);
                    if (n > 0) domIstasyonlar.push(n);
                });
                // DOM'da seçim varsa state'i override et
                e.istasyonlar = domIstasyonlar;
            }
        }
    }

    function enjKalipSecili() {
        var e = state.enj;
        if (e.kalipMode === 'manuel') {
            return !!(e.kalipKod && e.kalipBasiCift > 0);
        }
        return !!e.kalipId;
    }

    function enjCanHesapla() {
        var e = state.enj;
        enjSyncReferenceModeFromDom();
        var istOk = e.istasyonlar.length > 0 &&
            e.kalipAdedi > 0 &&
            e.kalipAdedi === e.istasyonlar.length &&
            e.kalipAdedi <= e.istasyonlar.length;
        var refOk = true;
        if (e.referenceMode === 'MANUAL') {
            if (e.calismaModu !== 'GECE') refOk = (e.manualRefGunduz || 0) > 0;
            if (refOk && e.calismaModu !== 'GUNDUZ') refOk = (e.manualRefGece || 0) > 0;
        }
        return !!(e.makineId && e.slot && istOk && enjKalipSecili() &&
            e.planCift > 0 && e.baslangic && e.kalipBasiCift > 0 && e.gozPerKalip > 0 && refOk);
    }

    function enjHesaplaDisabledNeden() {
        var e = state.enj;
        var reasons = [];
        if (!e.makineId) reasons.push('Makine seçilmedi');
        if (!e.slot)     reasons.push('A/B tarafı seçilmedi');
        if (!(e.istasyonlar.length > 0)) reasons.push('İstasyon seçilmedi');
        if (e.kalipAdedi !== e.istasyonlar.length) reasons.push('Kalıp adedi (' + (e.kalipAdedi||0) + ') ≠ seçili istasyon (' + e.istasyonlar.length + ')');
        if (!enjKalipSecili())   reasons.push('Kalıp seçilmedi');
        if (!(e.planCift > 0))   reasons.push('Planlanacak çift girilmedi');
        if (!e.baslangic)        reasons.push('Başlangıç tarihi girilmedi');
        if (!(e.kalipBasiCift > 0)) reasons.push('Kalıp başı çift sıfır/boş');
        if (e.referenceMode === 'MANUAL') {
            if (e.calismaModu !== 'GECE' && !((e.manualRefGunduz || 0) > 0))
                reasons.push('Gündüz tur/vardiya değeri girilmedi');
            if (e.calismaModu !== 'GUNDUZ' && !((e.manualRefGece || 0) > 0))
                reasons.push('Gece tur/vardiya değeri girilmedi');
        }
        return reasons;
    }

    function enjUpdateHesapBtn() {
        enjSyncInputsFromDom();
        enjSyncReferenceModeFromDom();
        var uyari = enjIstasyonUyariMesaji();
        var uyEl = $('upEnjIstasyonUyari');
        if (uyEl) {
            if (uyari) {
                uyEl.textContent = uyari;
                uyEl.style.display = 'block';
            } else {
                uyEl.style.display = 'none';
            }
        }
        var canCalc = enjCanHesapla();
        if ($('upEnjHesapBtn')) $('upEnjHesapBtn').disabled = !canCalc;
        // Disabled sebebini göster
        var hintEl = $('upEnjHesapBtnHint');
        if (hintEl) {
            if (!canCalc) {
                var reasons = enjHesaplaDisabledNeden();
                hintEl.textContent = reasons.length ? 'Hesapla için eksik: ' + reasons.join(' · ') : '';
                hintEl.style.display = reasons.length ? '' : 'none';
            } else {
                hintEl.style.display = 'none';
            }
        }
    }

    function enjHesaplaMotor() {
        var e = state.enj;
        if (!enjCanHesapla()) return;
        enjSyncInputsFromDom();
        enjSyncReferenceModeFromDom();

        var payload = {
            makine_id: e.makineId,
            taraf: e.slot,
            slot: e.slot,
            istasyonlar: e.istasyonlar.slice(),
            kalip_adedi: e.kalipAdedi,
            goz_per_kalip: e.gozPerKalip || 1,
            aktif_goz_sayisi: (e.kalipAdedi || 0) * (e.gozPerKalip || 1),
            kalip_id: e.kalipMode === 'liste' ? e.kalipId : null,
            kalip_basi_cift: e.kalipBasiCift,
            uretilecek_cift: e.planCift,
            plan_baslangic: e.baslangic,
            calisma_modu: e.calismaModu,
            hafta_sonu_calisma: e.haftaSonu,
            hafta_sonu_vardiya: e.hsVardiya,
            reference_mode: e.referenceMode || 'AUTO',
        };
        if (e.referenceMode === 'MANUAL') {
            if (e.calismaModu !== 'GECE') payload.manual_reference_gunduz = e.manualRefGunduz;
            if (e.calismaModu !== 'GUNDUZ') payload.manual_reference_gece = e.manualRefGece;
        }
        fetch('/planlama/uretim-plan/api/enj/hesapla', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              if (!d.ok) {
                  enjHesapGizle();
                  if ($('upEnjUyari')) {
                      var msg = d.hata || 'Hesap başarısız';
                      if (d.baslangic_gecersiz && d.onerilen_baslangic_gosterim) {
                          msg += ' Önerilen başlangıç: ' + d.onerilen_baslangic_gosterim;
                      }
                      $('upEnjUyari').textContent = msg;
                      $('upEnjUyari').style.display = 'block';
                  }
                  if (d.baslangic_gecersiz && d.onerilen_baslangic && $('upEnjBas') && !state.enj.baslangicManuel) {
                      $('upEnjBas').value = enjApiDtToLocal(d.onerilen_baslangic);
                      state.enj.baslangic = d.onerilen_baslangic;
                      if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = '';
                  }
                  return;
              }
              if (d.conflict_var) {
                  enjHesapGizle();
                  if ($('upEnjCakismaUyari')) $('upEnjCakismaUyari').style.display = 'none';
                  enjShowConflictModal(d.conflict_detail || {
                      makine_kod: e.makineKod,
                      slot: e.slot,
                      istasyon_no: (d.conflicts || [])[0] && (d.conflicts[0].istasyon_no),
                      cakisan_plan: (d.conflicts || [])[0] &&
                          ((d.conflicts[0].sip_no) + ' / ' + (d.conflicts[0].mamul_skod)),
                      plan_baslangic: (d.conflicts || [])[0] && d.conflicts[0].plan_baslangic,
                      plan_bitis: (d.conflicts || [])[0] && d.conflicts[0].plan_bitis,
                      plan_bas_gosterim: (d.conflicts || [])[0] && enjFmtDtApi(d.conflicts[0].plan_baslangic),
                      plan_bit_gosterim: (d.conflicts || [])[0] && enjFmtDtApi(d.conflicts[0].plan_bitis),
                  });
                  return;
              }
              e.motorResult = d;
              e.hesapOk = true;
              e.bitis = d.tahmini_bitis;
              e.turCift = d.tur_basi_cift;
              e.autoRefGunduz = (d.auto_gunduz_reference || d.gunduz_reference || {});
              e.autoRefGece = (d.auto_gece_reference || d.gece_reference || {});
              enjFreezeReservation(d);
              enjRenderHesapOzet(d);
              enjUpdateLowConfHint(d);  // auto-ref güncelle + sync
              wizardUpdateNav();
          })
          .catch(function (err) {
              enjHesapGizle();
              if ($('upEnjUyari')) {
                  $('upEnjUyari').textContent = err.message;
                  $('upEnjUyari').style.display = 'block';
              }
          });
    }

    function enjRenderVardiyaBreakdown(bd, gerekliTur, teorikCikan) {
        var wrap = $('upEnjVardiyaBreakdown');
        var list = $('upEnjVardiyaListe');
        var tot = $('upEnjVardiyaToplam');
        if (!wrap || !list) return;
        bd = bd || [];
        if (!bd.length) {
            wrap.style.display = 'none';
            return;
        }
        var sumTur = 0;
        var sumCift = 0;
        var allInt = true;
        list.innerHTML = bd.map(function (row) {
            var tur = Number(row.tur) || 0;
            if (Math.abs(tur - Math.round(tur)) > 0.001) allInt = false;
            sumTur += tur;
            sumCift += Number(row.cift) || 0;
            var dp = (row.tarih || '').split('-');
            var vardiyaLbl = row.vardiya || '';
            var saatBilgisi = vardiyaLbl === 'gunduz' ? ' (07:00–17:00)' : vardiyaLbl === 'gece' ? ' (17:00–07:00)' : '';
            var lbl = dp.length === 3 ? dp[2] + '.' + dp[1] + ' ' + vardiyaLbl + saatBilgisi : (vardiyaLbl + saatBilgisi);
            return '<div class="up-enj-vardiya-satir"><span>' + esc(lbl) + '</span><span>' +
                Math.round(tur) + ' tur · ' + fmtN(row.cift) + ' çift</span></div>';
        }).join('');
        if (tot) {
            tot.textContent = 'TOPLAM: ' + Math.round(sumTur) + ' tur · ' +
                fmtN(teorikCikan || sumCift) + ' çift (teorik brüt)';
        }
        wrap.style.display = 'block';
    }

    function enjRenderWarningsShort(warns) {
        var warnEl = $('upEnjWarnings');
        if (!warnEl) return;
        warns = warns || [];
        if (!warns.length) {
            warnEl.style.display = 'none';
            return;
        }
        var low = warns.filter(function (w) {
            return (w.kod || '').indexOf('DUSUK') >= 0 || (w.mesaj || '').toLowerCase().indexOf('düşük') >= 0;
        });
        if (low.length) {
            warnEl.textContent = 'DÜŞÜK GÜVEN — ' + (low[0].mesaj || low[0].kod || 'Referans yaklaşık');
            warnEl.title = warns.map(function (w) { return w.mesaj || w.kod; }).join('\n');
        } else {
            warnEl.textContent = warns[0].mesaj || warns[0].kod || '';
            warnEl.title = warns.map(function (w) { return w.mesaj || w.kod; }).join('\n');
        }
        warnEl.style.display = 'block';
    }

    function enjRenderHesapOzet(d) {
        var e = state.enj;
        var istStr = e.istasyonlar.map(function (x) { return 'İST' + x; }).join('–');
        if ($('upEnjHesapOzet')) $('upEnjHesapOzet').style.display = 'block';
        if ($('upEnjOzetMakine')) $('upEnjOzetMakine').textContent = (e.makineKod || 'M?') + ' / ' + e.slot;
        if ($('upEnjOzetIstasyon')) $('upEnjOzetIstasyon').textContent = istStr;
        if ($('upEnjOzetKalip')) $('upEnjOzetKalip').textContent = e.kalipKod || '—';
        if ($('upEnjOzetKalipAdedi')) $('upEnjOzetKalipAdedi').textContent = String(e.kalipAdedi || '—');
        if ($('upEnjOzetGoz')) $('upEnjOzetGoz').textContent = String(e.gozPerKalip || '—');
        if ($('upEnjOzetKbc')) $('upEnjOzetKbc').textContent = String(e.kalipBasiCift || '—');
        if ($('upEnjOzetCift')) $('upEnjOzetCift').textContent = fmtN(d.siparis_ihtiyaci || e.planCift) + ' çift';
        if ($('upEnjTurCift')) $('upEnjTurCift').textContent = (d.tur_basi_cift || '—') + ' çift';
        if ($('upEnjGerekliTur')) $('upEnjGerekliTur').textContent = (d.gerekli_tam_tur || d.tahmini_gerekli_tur || '—') + ' tur';
        if ($('upEnjTeorikTur')) $('upEnjTeorikTur').textContent = d.teorik_tur != null ? String(d.teorik_tur) : '—';
        if ($('upEnjTeorikCikan')) $('upEnjTeorikCikan').textContent = fmtN(d.teorik_cikan) + ' çift';
        if ($('upEnjFazlaCift')) {
            var fz = d.fazla_cift || 0;
            $('upEnjFazlaCift').textContent = fz > 0 ? fmtN(fz) + ' çift' : '0';
        }
        if ($('upEnjOzetCalisma')) $('upEnjOzetCalisma').textContent = enjCalismaLabel(e.calismaModu);
        if ($('upEnjOzetBas')) $('upEnjOzetBas').textContent = enjFmtDtApi(e.baslangic);
        if ($('upEnjBitis')) $('upEnjBitis').textContent = enjFmtDtApi(d.tahmini_bitis);
        if ($('upEnjOzetRefMode')) {
            $('upEnjOzetRefMode').textContent = 'MANUEL';
        }
        var showManG = e.calismaModu !== 'GECE';
        var showManE = e.calismaModu !== 'GUNDUZ';
        if ($('upEnjOzetManuelGWrap')) $('upEnjOzetManuelGWrap').style.display = showManG ? '' : 'none';
        if ($('upEnjOzetManuelGWrap2')) $('upEnjOzetManuelGWrap2').style.display = showManE ? '' : 'none';
        if ($('upEnjOzetManuelG') && showManG) {
            $('upEnjOzetManuelG').textContent = (d.manual_reference_gunduz || e.manualRefGunduz || '—') + ' tur/vardiya';
        }
        if ($('upEnjOzetManuelE') && showManE) {
            $('upEnjOzetManuelE').textContent = (d.manual_reference_gece || e.manualRefGece || '—') + ' tur/vardiya';
        }
        if ($('upEnjOzetRefKaynak')) {
            var kaynak = state.enj.referenceMode === 'AUTO'
                ? ('Geçmiş üretim — ' + enjRefConfidenceLabel((d.gunduz_reference || {}).confidence || 'YETERSIZ'))
                : 'Manuel operasyon tahmini';
            $('upEnjOzetRefKaynak').textContent = kaynak;
        }
        // Güven gösterimi
        var guvenEl = $('upEnjOzetGuven');
        var guvenWrap = $('upEnjOzetGuvenWrap');
        if (guvenEl && guvenWrap && d.overall_confidence) {
            guvenEl.textContent = enjRefConfidenceLabel(d.overall_confidence);
            guvenWrap.style.display = '';
        }
        if ($('upEnjOzetHs')) {
            $('upEnjOzetHs').textContent = e.haftaSonu === 'EVET'
                ? enjCalismaLabel(e.hsVardiya) : 'Çalışma yok';
        }
        enjRenderVardiyaBreakdown(d.vardiya_breakdown, d.gerekli_tam_tur, d.teorik_cikan);
        enjRenderWarningsShort(d.warnings);
        if ($('upEnjCakismaUyari')) $('upEnjCakismaUyari').style.display = 'none';
    }

    function enjApplyIlkUygunInput() {
        var e = state.enj;
        if (e.baslangicManuel || !e.makineId) return;
        var iu = e.ilkUygunMap[e.makineId];
        if (!iu || !iu.ilk_uygun) return;
        // Stale map guard: ilkUygun fetch edildiği slotla seçili slot aynı olmalı
        if (iu._fetched_slot && iu._fetched_slot !== e.slot) {
            if ($('upEnjBas')) $('upEnjBas').value = '';
            if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
            return;
        }
        e.baslangicOneri = iu.ilk_uygun;
        e.baslangic = iu.ilk_uygun;
        if ($('upEnjBas')) {
            $('upEnjBas').value = enjApiDtToLocal(iu.ilk_uygun);
        }
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = '';
        enjFetchIstasyonPlanDurum(function () {
            var m = (state.enj.gridData || []).find(function (x) {
                return (x.makine_id || x.id) === state.enj.makineId;
            });
            if (m) enjRenderIstasyonGrid(m);
            enjUpdateHesapBtn();  // Tarih set olduktan sonra HESAPLA durumunu güncelle
        });
    }

    function enjFetchIlkUygun() {
        var e = state.enj;
        if (!e.slot || !e.makineId) return;
        // Gerçek seçili istasyonları kullan (checkbox).
        // Sayı kalıp adedine eşit değilse yeterli uygun istasyon yoktur;
        // ilk uygun tarih hesaplanamaz → input ve ÖNERİLEN gizli kalır.
        var kalipAdedi = parseInt($('upEnjKalipAdedi') && $('upEnjKalipAdedi').value, 10) || 0;
        var seciliIst  = e.istasyonlar.slice();
        // Stale öneriyi her durumda gizle
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        if ($('upEnjBas') && !e.baslangicManuel) $('upEnjBas').value = '';
        e.ilkUygunMap = {};
        if (kalipAdedi < 1 || seciliIst.length === 0) return;
        if (seciliIst.length < kalipAdedi) {
            // Yeterli istasyon yok — tarih hesaplanamaz
            enjUpdateHesapBtn();
            return;
        }
        var ids = (e.gridData || []).map(function (m) { return m.makine_id || m.id; }).filter(Boolean);
        if (!ids.length) return;
        fetch('/planlama/uretim-plan/api/enj/ilk-uygun', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                makine_ids: ids,
                selected_makine_id: e.makineId,
                slot: e.slot,
                istasyonlar: seciliIst,
                calisma_modu: e.calismaModu,
                hafta_sonu_calisma: e.haftaSonu,
                hafta_sonu_vardiya: e.hsVardiya,
            }),
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              if (!d.ok) return;
              e.ilkUygunMap = {};
              (d.makineler || []).forEach(function (m) {
                  m._fetched_slot     = e.slot;
                  m._fetched_ist      = seciliIst.slice();
                  e.ilkUygunMap[m.makine_id] = m;
              });
              enjRenderMakineCards(e.gridData || []);
              enjApplyIlkUygunInput();
              enjUpdateHesapBtn();
          });
    }

    function enjRenderMakineCards(machines) {
        var el = $('upEnjMakineCards');
        if (!el) return;
        el.innerHTML = '';
        machines.forEach(function (m) {
            var mid = m.makine_id || m.id;
            var kod = m.makine_kod || m.kod || m.code;
            var oz = state.enj.planOzetMap[mid] || {};
            var card = document.createElement('button');
            card.type = 'button';
            var aSnap = m.A || (m.slots && m.slots.A) || {};
            var bSnap = m.B || (m.slots && m.slots.B) || {};
            var aPlan = oz.A || {};
            var bPlan = oz.B || {};
            card.className = 'up-enj-makine-card' + (state.enj.makineId === mid ? ' selected' : '');
            card.innerHTML =
                '<strong>' + esc(kod) + '</strong>' +
                '<span class="up-enj-card-ist-label">' + m.istasyon_sayisi + ' İSTASYON</span>' +
                enjSideTimelineHtml(Object.assign({ dolu: aSnap.dolu }, aPlan), 'side-a') +
                enjSideTimelineHtml(Object.assign({ dolu: bSnap.dolu }, bPlan), 'side-b') +
                '<div class="up-enj-card-slots">' +
                '<span class="up-slot-a">A &nbsp;<b class="up-enj-dolu-sayi">' + (aSnap.dolu || 0) + '</b> / ' + m.istasyon_sayisi + ' <span class="up-enj-dolu-lbl">DOLU</span></span>' +
                '<span class="up-slot-b">B &nbsp;<b class="up-enj-dolu-sayi">' + (bSnap.dolu || 0) + '</b> / ' + m.istasyon_sayisi + ' <span class="up-enj-dolu-lbl">DOLU</span></span>' +
                '</div>';
            card.addEventListener('click', function () {
                state.enj.makineId = mid;
                state.enj.makineKod = kod;
                state.enj.istasyonSayisi = m.istasyon_sayisi;
                state.enj.istasyonlar = [];
                state.enj.slot = null;
                state.enj.baslangicManuel = false;
                state.enj.baslangic = null;
                state.enj.baslangicOneri = null;
                // Makine değişince stale ilkUygunMap temizle
                state.enj.ilkUygunMap = {};
                state.enj.istasyonPlanDurum = {};
                if ($('upEnjBas')) $('upEnjBas').value = '';
                if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
                enjHesapGizle();
                enjRenderMakineCards(machines);
                enjRenderIstasyonGrid(m);
                if ($('upEnjSlotA')) $('upEnjSlotA').classList.remove('selected');
                if ($('upEnjSlotB')) $('upEnjSlotB').classList.remove('selected');
                if ($('upEnjKalip')) $('upEnjKalip').disabled = false;
                enjUpdateHesapBtn();
                // B2: SON 1 HAFTA kutusunda seçili makineyi vurgula + autoRef yükle
                if (state.enj._sonHaftaVeri) {
                    enjSonHaftaHizRender(state.enj._sonHaftaVeri, kod);
                    enjLoadAutoRefFromSonHafta(kod, e.slot);
                }
                enjUpdateAutoRefHints();
            });
            el.appendChild(card);
        });
    }

    function enjCellDurum(cell) {
        // ENJ_IST_PARITY_FIX: aktif=1 OR durum=AKTIF → DOLU (fiziksel occupancy)
        if (!cell) return 'BOS';
        if (parseInt(cell.aktif, 10) === 1) return 'DOLU';
        if (cell.slot_label === 'DOLU') return 'DOLU';
        var d = (cell.durum || '').toUpperCase();
        if (d === 'AKTIF') return 'DOLU';
        if (d === 'DOLU' || d === 'SETUP' || d === 'ARIZA' || d === 'KAPALI') return d;
        return 'BOS';
    }

    function enjRenderIstasyonGrid(m) {
        var el = $('upEnjIstasyonGrid');
        if (!el || !state.enj.makineId) return;
        el.innerHTML = '';
        var slot = state.enj.slot;
        var grid = (m.grid || []);
        var planDurum = state.enj.istasyonPlanDurum || {};
        for (var i = 1; i <= state.enj.istasyonSayisi; i++) {
            var row = grid[i - 1] || {};
            var cell = slot ? (row[slot] || {}) : null;
            var snapDurum = slot ? enjCellDurum(cell) : '—';
            var pd = planDurum[i];
            var durum = snapDurum;
            var detail = '';
            if (pd && pd.durum === 'PLANLI') {
                durum = 'PLANLI';
                detail = (pd.sip_no || '') + ' ' + (pd.bas_gosterim || '') + '→' + (pd.bit_gosterim || '');
            } else if (snapDurum !== 'BOS') {
                durum = snapDurum;
            }
            // ENJ_IST_PARITY_FIX: KAPALI = fiziksel execution durdurulmuş, planlama açısından BOŞ/uygun
            var disabled = !slot || durum === 'PLANLI' || durum === 'DOLU' || durum === 'SETUP' ||
                durum === 'ARIZA';
            var lbl = document.createElement('label');
            lbl.className = 'up-enj-ist-cell' +
                (state.enj.istasyonlar.indexOf(i) >= 0 ? ' selected' : '') +
                (disabled ? ' disabled' : '') +
                (slot === 'A' ? ' slot-a' : slot === 'B' ? ' slot-b' : '');
            lbl.innerHTML = '<input type="checkbox" value="' + i + '"' +
                (disabled ? ' disabled' : '') +
                (state.enj.istasyonlar.indexOf(i) >= 0 ? ' checked' : '') + '> İST' + i +
                '<small class="' + (durum === 'PLANLI' ? 'planli' : durum === 'DOLU' ? 'dolu' : '') + '">' +
                (durum === 'KAPALI' ? 'BOŞ' : durum) + (detail ? '<br>' + esc(detail) : '') + '</small>';
            if (!disabled) {
                lbl.querySelector('input').addEventListener('change', function (ev) {
                    var n = parseInt(ev.target.value, 10);
                    var arr = state.enj.istasyonlar;
                    if (ev.target.checked) {
                        if (arr.indexOf(n) < 0) arr.push(n);
                    } else {
                        state.enj.istasyonlar = arr.filter(function (x) { return x !== n; });
                    }
                    state.enj.istasyonlar.sort(function (a, b) { return a - b; });
                    state.enj.baslangicManuel = false;
                    enjHesapGizle();
                    enjRenderIstasyonGrid(m);
                    if ($('upEnjKalipAdedi')) {
                        $('upEnjKalipAdedi').value = state.enj.istasyonlar.length || '';
                    }
                    enjUpdateToplamGozHint();
                    enjFetchIlkUygun();
                    enjUpdateHesapBtn();
                });
            }
            el.appendChild(lbl);
        }
    }

    function enjSelectSlot(slot) {
        state.enj.slot = slot;
        state.enj.istasyonlar = [];
        state.enj.baslangicManuel = false;
        state.enj.baslangic = null;
        state.enj.baslangicOneri = null;
        // Slot değişince stale ilkUygunMap temizle — yeni slot için yeniden hesaplanacak
        state.enj.ilkUygunMap = {};
        state.enj.istasyonPlanDurum = {};
        if ($('upEnjBas')) $('upEnjBas').value = '';
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        enjHesapGizle();
        if ($('upEnjSlotA')) $('upEnjSlotA').classList.toggle('selected', slot === 'A');
        if ($('upEnjSlotB')) $('upEnjSlotB').classList.toggle('selected', slot === 'B');
        var m = (state.enj.gridData || []).find(function (x) {
            return (x.makine_id || x.id) === state.enj.makineId;
        });
        if (m) enjRenderIstasyonGrid(m);
        enjFetchIlkUygun();
        enjSyncInputsFromDom();
        enjFetchIstasyonPlanDurum(function () {
            if (m) enjRenderIstasyonGrid(m);
        });
        // Slot değişince autoRef yeniden yükle (A/B farklı hız olabilir)
        if (state.enj.makineKod && state.enj._sonHaftaVeri) {
            enjLoadAutoRefFromSonHafta(state.enj.makineKod, slot);
        }
        enjUpdateHesapBtn();
    }

    function enjYukleKapasite() {
        enjYuklePlanOzet(function () {
            fetch('/planlama/uretim-plan/api/enj-kapasite?days=90', { credentials: 'include' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d.ok) return;
                    state.enj.gridData = d.machines || [];
                    enjRenderMakineCards(state.enj.gridData);
                });
        });
    }

    // ─── SON 1 HAFTA MAKİNE VERİSİ — görsel referans kutusu ─────────────────
    function enjLoadAutoRefFromSonHafta(mkod, slot) {
        // Son hafta verisi varsa ilgili makine/slot için autoRef state'i doldur.
        // NOT: Otomatik input doldurma YOKTUR. Kullanıcı "Kullan" butonuna basmalı.
        var veri = state.enj._sonHaftaVeri;
        if (!veri || !mkod) return;
        var mkVeri = veri[mkod];
        if (!mkVeri) return;
        var slotKey = (slot || state.enj.slot || 'A').toUpperCase();
        var gData = ((mkVeri.gunduz || {})[slotKey]) || {};
        var eData = ((mkVeri.gece   || {})[slotKey]) || {};
        // autoRefGunduz — min/max/avg da sakla
        if (!gData.calismadi && gData.median != null) {
            state.enj.autoRefGunduz = {
                reference_value: gData.median,
                confidence: gData.sample >= 6 ? 'YUKSEK' : gData.sample >= 3 ? 'ORTA' : 'DUSUK',
                sample_count: gData.sample || 0,
                min: gData.min,
                max: gData.max,
                avg: gData.avg,
                reference_type: 'SonHaftaHiz',
            };
        } else {
            state.enj.autoRefGunduz = { reference_value: 0, confidence: 'YETERSIZ', sample_count: 0 };
        }
        // autoRefGece
        if (!eData.calismadi && eData.median != null) {
            state.enj.autoRefGece = {
                reference_value: eData.median,
                confidence: eData.sample >= 6 ? 'YUKSEK' : eData.sample >= 3 ? 'ORTA' : 'DUSUK',
                sample_count: eData.sample || 0,
                min: eData.min,
                max: eData.max,
                avg: eData.avg,
                reference_type: 'SonHaftaHiz',
            };
        } else {
            state.enj.autoRefGece = { reference_value: 0, confidence: 'YETERSIZ', sample_count: 0 };
        }
        // Otomatik doldurma YAPILMAZ — kullanıcı onayı zorunlu
        enjUpdateAutoRefHints();
        enjUpdateHesapBtn();
    }

    function enjSonHaftaHizRender(veri, secilenMakine) {
        var kutu = $('upEnjSonHaftaHiz');
        var icerik = $('upEnjSonHaftaIcerik');
        if (!kutu || !icerik) return;

        var mkodlar = Object.keys(veri || {}).sort();
        if (!mkodlar.length) {
            kutu.style.display = 'none';
            return;
        }

        var html = '';
        mkodlar.forEach(function (mkod) {
            var isSelected = secilenMakine && mkod === secilenMakine;
            var rowClass = 'up-shh-makine' + (isSelected ? ' up-shh-secili' : '');
            html += '<div class="' + rowClass + '">';
            html += '<div class="up-shh-mkod">' + esc(mkod) + '</div>';

            var mkVeri = veri[mkod] || {};
            var gunduzA = (mkVeri.gunduz || {}).A || {};
            var gunduzB = (mkVeri.gunduz || {}).B || {};
            var geceA   = (mkVeri.gece   || {}).A || {};
            var geceB   = (mkVeri.gece   || {}).B || {};

            // Slot A + B birleştir: en az birinde veri varsa göster
            function slotSatir(label, slotA, slotB) {
                var aOk = !slotA.calismadi && slotA.median != null;
                var bOk = !slotB.calismadi && slotB.median != null;
                if (!aOk && !bOk) {
                    return '<div class="up-shh-satir"><span class="up-shh-vd">' + label + '</span>'
                         + '<span class="up-shh-deger up-shh-yok">ÇALIŞMADI</span></div>';
                }
                var parts = [];
                if (aOk) parts.push('A: ' + slotA.median + ' tur/vd (' + slotA.sample + ' vd)');
                if (bOk) parts.push('B: ' + slotB.median + ' tur/vd (' + slotB.sample + ' vd)');
                return '<div class="up-shh-satir"><span class="up-shh-vd">' + label + '</span>'
                     + '<span class="up-shh-deger">' + parts.join(' &nbsp;|&nbsp; ') + '</span></div>';
            }

            html += slotSatir('Gündüz', gunduzA, gunduzB);
            html += slotSatir('Gece',   geceA,   geceB);
            html += '</div>';
        });

        icerik.innerHTML = html;
        kutu.style.display = '';
    }

    function enjYukleSonHaftaHiz(secilenMakine) {
        // Kademeli referans aralığı: 7 → 30 → 90 gün
        // Bir makine/slot için herhangi bir veri varsa o adımda dur.
        var kutu = $('upEnjSonHaftaHiz');
        var icerik = $('upEnjSonHaftaIcerik');
        if (!kutu || !icerik) return;
        kutu.style.display = '';
        icerik.innerHTML = '<span class="up-enj-son-hafta-yukleniyor">Yükleniyor…</span>';

        function _hasAnyData(makineler) {
            for (var k in makineler) {
                var mk = makineler[k];
                for (var vd in mk) {
                    for (var s in mk[vd]) {
                        if (mk[vd][s] && !mk[vd][s].calismadi) return true;
                    }
                }
            }
            return false;
        }

        function _fetch(days, remaining) {
            fetch('/planlama/uretim-plan/api/enj/son-hafta-hiz?days=' + days, { credentials: 'include' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d.ok && d.makineler) {
                        if (_hasAnyData(d.makineler) || remaining.length === 0) {
                            // Veri bulundu veya son deneme
                            state.enj._sonHaftaVeri = d.makineler;
                            state.enj._sonHaftaDays = days;
                            // Başlık güncelle
                            if ($('upEnjSonHaftaAralik')) $('upEnjSonHaftaAralik').textContent = 'son ' + days + ' gün';
                            enjSonHaftaHizRender(d.makineler, secilenMakine);
                            if (state.enj.makineKod) {
                                enjLoadAutoRefFromSonHafta(state.enj.makineKod, state.enj.slot);
                            }
                        } else {
                            // Veri yok, bir üst aralığı dene
                            _fetch(remaining[0], remaining.slice(1));
                        }
                    } else {
                        state.enj._sonHaftaVeri = null;
                        state.enj._sonHaftaDays = days;
                        icerik.innerHTML = '<span class="up-shh-yok">Veri alınamadı</span>';
                        enjUpdateAutoRefHints();
                    }
                })
                .catch(function () {
                    state.enj._sonHaftaVeri = null;
                    icerik.innerHTML = '<span class="up-shh-yok">Veri alınamadı</span>';
                });
        }

        _fetch(7, [30, 90]);
    }

    function enjBuildKalipSelect() {
        var sel = $('upEnjKalip');
        if (!sel) return;
        sel.innerHTML = '<option value="">— Kalıp Seçin —</option>';
        state.enj.kaliplar.forEach(function (k) {
            var o = document.createElement('option');
            o.value = k.id;
            o.textContent = k.kalip_kod + (k.model_kod ? ' (' + k.model_kod + ')' : '');
            o.dataset.kod = k.kalip_kod;
            o.dataset.kbc = k.kalip_basi_cift || '';
            sel.appendChild(o);
        });
    }

    function enjYukleKaliplar() {
        if (state.enj.kaliplar.length) { enjBuildKalipSelect(); return; }
        fetch('/planlama/uretim-plan/api/enj/kaliplar', { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.ok) {
                    state.enj.kaliplar = d.kaliplar || [];
                    enjBuildKalipSelect();
                }
            });
    }

    function enjBindEvents() {
        if ($('upEnjSlotA')) $('upEnjSlotA').addEventListener('click', function () { enjSelectSlot('A'); });
        if ($('upEnjSlotB')) $('upEnjSlotB').addEventListener('click', function () { enjSelectSlot('B'); });
        if ($('upEnjKalipModeListe')) $('upEnjKalipModeListe').addEventListener('click', function () { enjSetKalipMode('liste'); });
        if ($('upEnjKalipModeManuel')) $('upEnjKalipModeManuel').addEventListener('click', function () { enjSetKalipMode('manuel'); });
        if ($('upEnjKalip')) $('upEnjKalip').addEventListener('change', function () {
            var e = state.enj;
            var opt = $('upEnjKalip').options[$('upEnjKalip').selectedIndex];
            e.kalipId = $('upEnjKalip').value ? parseInt($('upEnjKalip').value, 10) : null;
            e.kalipKod = opt ? (opt.dataset.kod || opt.textContent.split(' ')[0]) : null;
            e.kalipBasiCift = opt && opt.dataset.kbc ? parseFloat(opt.dataset.kbc) : null;
            enjHesapGizle();
            enjYukleKalipGoz();
            enjUpdateHesapBtn();
        });
        ['upEnjPlanCift', 'upEnjKalipAdedi', 'upEnjGozPerKalip', 'upEnjBas', 'upEnjCalismaModu',
         'upEnjKalipManuelKod', 'upEnjKalipManuelKbc'].forEach(function (id) {
            if ($(id)) {
                $(id).addEventListener('change', function () {
                    if (id === 'upEnjBas') {
                        state.enj.baslangicManuel = true;
                        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
                        enjSyncInputsFromDom();
                        enjHesapGizle();
                        // Erken tarih kontrolü: girilen tarih ilk uygun tarihten erken olamaz
                        var iu = state.enj.ilkUygunMap[state.enj.makineId];
                        if (iu && iu.ilk_uygun && $('upEnjBas').value) {
                            var girildi = $('upEnjBas').value.replace('T', ' ');
                            var ilkStr = iu.ilk_uygun.substring(0, 16).replace('T', ' ');
                            if (girildi < ilkStr) {
                                var uyariEl = $('upEnjBasEarlyWarn');
                                if (!uyariEl) {
                                    uyariEl = document.createElement('div');
                                    uyariEl.id = 'upEnjBasEarlyWarn';
                                    uyariEl.className = 'up-enj-warn-msg';
                                    $('upEnjBas').parentNode.appendChild(uyariEl);
                                }
                                uyariEl.textContent = '⚠ Seçilen tarih, ' + iu.ilk_uygun_gosterim + ' ilk uygun tarihinden erken. Çakışma olabilir.';
                                uyariEl.style.display = '';
                            } else {
                                var w = $('upEnjBasEarlyWarn');
                                if (w) w.style.display = 'none';
                            }
                        }
                        enjFetchIstasyonPlanDurum(function () {
                            var m = (state.enj.gridData || []).find(function (x) {
                                return (x.makine_id || x.id) === state.enj.makineId;
                            });
                            if (m) enjRenderIstasyonGrid(m);
                        });
                    } else if (id === 'upEnjKalipAdedi' || id === 'upEnjCalismaModu') {
                        state.enj.baslangicManuel = false;
                        if (id === 'upEnjCalismaModu') {
                            // Mod değişiminde: stale değerleri ve eski hesabı temizle
                            state.enj.autoRefGunduz      = {};
                            state.enj.autoRefGece        = {};
                            state.enj.refSourceGunduz    = null;
                            state.enj.refSourceGece      = null;
                            state.enj.refConfirmedGunduz = false;
                            state.enj.refConfirmedGece   = false;
                            // Stale öneri tarihini de temizle
                            state.enj.ilkUygunMap    = {};
                            state.enj.baslangic      = null;
                            state.enj.baslangicOneri = null;
                            if ($('upEnjBas')) $('upEnjBas').value = '';
                            if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
                            if ($('upEnjManualGunduz')) $('upEnjManualGunduz').value = '';
                            if ($('upEnjManualGece'))   $('upEnjManualGece').value   = '';
                            state.enj.manualRefGunduz = null;
                            state.enj.manualRefGece   = null;
                            enjUpdateManualRefVisibility();
                            // Seçili makine için yeni modda autoRef yükle
                            if (state.enj.makineKod && state.enj._sonHaftaVeri) {
                                enjLoadAutoRefFromSonHafta(state.enj.makineKod, state.enj.slot);
                            }
                        }
                        enjFetchIlkUygun();
                        enjYuklePlanOzet(function () {
                            enjRenderMakineCards(state.enj.gridData || []);
                            // Doluluk bandı modunu güncelle
                            var dolMode = $('upEnjDolulukModeLabel');
                            var dolEl   = $('upEnjDolulukBant');
                            var cm = state.enj.calismaModu || 'GUNDUZ_GECE';
                            if (dolMode) dolMode.textContent = enjCalismaLabel(cm);
                            if (dolEl && state.enj.gridData && state.enj.gridData.length) dolEl.style.display = '';
                        });
                        if (id === 'upEnjKalipAdedi') enjUpdateToplamGozHint();
                    } else if (id === 'upEnjGozPerKalip') {
                        enjUpdateToplamGozHint();
                    }
                    enjHesapGizle();
                    enjUpdateHesapBtn();
                });
                $(id).addEventListener('input', function () {
                    if (id === 'upEnjBas') {
                        state.enj.baslangicManuel = true;
                        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
                        enjSyncInputsFromDom();
                        enjFetchIstasyonPlanDurum(function () {
                            var m = (state.enj.gridData || []).find(function (x) {
                                return (x.makine_id || x.id) === state.enj.makineId;
                            });
                            if (m) enjRenderIstasyonGrid(m);
                        });
                    }
                    if (id === 'upEnjKalipAdedi' || id === 'upEnjGozPerKalip') enjUpdateToplamGozHint();
                    enjHesapGizle();
                    enjUpdateHesapBtn();
                });
            }
        });
        if ($('upEnjHaftaSonu')) $('upEnjHaftaSonu').addEventListener('change', function () {
            var evet = $('upEnjHaftaSonu').value === 'EVET';
            if ($('upEnjHsVardiyaWrap')) $('upEnjHsVardiyaWrap').style.display = evet ? '' : 'none';
            state.enj.baslangicManuel = false;
            enjHesapGizle();
            enjFetchIlkUygun();
            enjUpdateHesapBtn();
        });
        if ($('upEnjHsVardiya')) $('upEnjHsVardiya').addEventListener('change', function () {
            state.enj.baslangicManuel = false;
            enjHesapGizle();
            enjFetchIlkUygun();
            enjUpdateHesapBtn();
        });
        if ($('upEnjHesapBtn')) $('upEnjHesapBtn').addEventListener('click', enjHesaplaMotor);
        document.querySelectorAll('input[name="upEnjRefMode"]').forEach(function (r) {
            r.addEventListener('change', function () {
                enjSyncReferenceModeFromDom();
                enjHesapGizle();
                enjUpdateHesapBtn();
            });
        });
        ['upEnjManualGunduz', 'upEnjManualGece'].forEach(function (id) {
            if ($(id)) {
                $(id).addEventListener('input', function () {
                    // Kullanıcı değeri değiştirirse kaynak MANUAL olur
                    if (id === 'upEnjManualGunduz') {
                        state.enj.refSourceGunduz    = 'MANUAL';
                        state.enj.refConfirmedGunduz = false;
                    } else {
                        state.enj.refSourceGece    = 'MANUAL';
                        state.enj.refConfirmedGece = false;
                    }
                    enjSyncReferenceModeFromDom();
                    enjHesapGizle();
                    enjUpdateHesapBtn();
                    enjUpdateAutoRefHints();
                });
            }
        });
        // Auto-fill butonları — kullanıcı onayı + kaynak takibi
        if ($('upEnjAutoFillGunduz')) {
            $('upEnjAutoFillGunduz').addEventListener('click', function () {
                var autoG = state.enj.autoRefGunduz || {};
                if (!autoG.reference_value) return;
                var val = Math.round(autoG.reference_value);
                var needConfirm = this.dataset.confirm === '1';
                var proceed = true;
                if (needConfirm) {
                    var confLabel = enjRefConfidenceLabel(autoG.confidence);
                    proceed = window.confirm(
                        'Gündüz verisi güven seviyesi: ' + confLabel +
                        ' (' + (autoG.sample_count || 0) + ' örnek).\n\n' +
                        'Bu referans değerini (' + val + ' tur/vardiya) gündüz alanına aktarmak istiyor musunuz?\n\n' +
                        'Değeri üretime özgün verilerle doğrulamanız önerilir.'
                    );
                }
                if (proceed) {
                    var inp = $('upEnjManualGunduz');
                    if (inp) {
                        inp.value = val;
                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    // Kaynak takibi
                    state.enj.refSourceGunduz    = 'HISTORICAL_CONFIRMED';
                    state.enj.refConfirmedGunduz = true;
                    enjUpdateAutoRefHints();
                }
            });
        }
        if ($('upEnjAutoFillGece')) {
            $('upEnjAutoFillGece').addEventListener('click', function () {
                var autoE = state.enj.autoRefGece || {};
                if (!autoE.reference_value) return;
                var val = Math.round(autoE.reference_value);
                var needConfirm = this.dataset.confirm === '1';
                var proceed = true;
                if (needConfirm) {
                    var confLabelE = enjRefConfidenceLabel(autoE.confidence);
                    proceed = window.confirm(
                        'Gece verisi güven seviyesi: ' + confLabelE +
                        ' (' + (autoE.sample_count || 0) + ' örnek).\n\n' +
                        'Bu referans değerini (' + val + ' tur/vardiya) gece alanına aktarmak istiyor musunuz?\n\n' +
                        'Değeri üretime özgün verilerle doğrulamanız önerilir.'
                    );
                }
                if (proceed) {
                    var inpE = $('upEnjManualGece');
                    if (inpE) {
                        inpE.value = val;
                        inpE.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    state.enj.refSourceGece    = 'HISTORICAL_CONFIRMED';
                    state.enj.refConfirmedGece = true;
                    enjUpdateAutoRefHints();
                }
            });
        }
        if ($('upEnjConflictApply')) $('upEnjConflictApply').addEventListener('click', enjApplyConflictIlkUygun);
        if ($('upEnjConflictCalendar')) $('upEnjConflictCalendar').addEventListener('click', enjOpenConflictCalendar);
        if ($('upEnjConflictKapat')) $('upEnjConflictKapat').addEventListener('click', enjHideConflictModal);
        if ($('upEnjConflictClose')) $('upEnjConflictClose').addEventListener('click', enjHideConflictModal);
        if ($('upEnjConflictBackdrop')) $('upEnjConflictBackdrop').addEventListener('click', enjHideConflictModal);
        if ($('upStep3EnjDegistir')) {
            $('upStep3EnjDegistir').addEventListener('click', function () { wizardShowStep(2); });
        }
        if ($('upFormBit')) $('upFormBit').addEventListener('change', validateStep3Tarihleri);
        enjUpdateManualRefVisibility();
    }

    function fetchCreateOnizleme(sip) {
        $('upCreateHint').textContent = 'Sorgulanıyor…';
        state.seciliCreate = null;
        state.seciliCreateData = null;
        state.createStep = 1;
        wizardShowStep(1);
        if ($('upStep1Readonly')) $('upStep1Readonly').style.display = 'none';
        fetch('/planlama/uretim-plan/api/siparis-onizle?sipno=' + encodeURIComponent(sip), { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj || 'Hata');
                state.onizleme = d.onizleme || [];
                renderCreateListe(state.onizleme);
                $('upCreateHint').textContent = state.onizleme.length + ' model+renk kalemi';
            })
            .catch(function (e) {
                $('upCreateHint').textContent = '';
                showError(e.message);
            });
    }

    function savePlan() {
        clearPlanErrors();
        var pre = collectPreSaveValidation();
        if (pre.errors.length) {
            showPlanErrors(pre.errors, pre.fields);
            return;
        }
        var o = state.seciliCreateData;
        var enj = state.enj;
        var rez = enj.reservation;
        var mr = (rez && rez.motorResult) || enj.motorResult || {};

        function postPlan() {
            var payload = {
                sip_no: o.sip_no,
                sip_harinx: o.sip_harinx,
                mamul_skod: o.model_kod || o.mamul_skod,
                rkod: o.rkod,
                model_adi: o.model_tanim,
                renk_adi: o.renk,
                miktar: o.miktar,
                termin: o.termin,
                plan_donemi: $('upFormDonem').value,
                plan_baslangic: $('upFormBas').value || null,
                plan_bitis: $('upFormBit').value || null,
                oncelik: parseInt($('upFormOncelik').value, 10),
                plan_gerekce: $('upFormGerekce').value || null,
                plan_notu: $('upFormNot').value || null,
                has_enjeksiyon: state.requiresEnj === true,
            };
            if (state.requiresEnj && enj.hesapOk && rez) {
                payload.enj_makine_id = enj.makineId;
                payload.enj_istasyonlar = rez.istasyonlar.slice();
                payload.enj_slot = rez.slot;
                payload.enj_kalip_id = enj.kalipMode === 'liste' ? enj.kalipId : null;
                payload.enj_kalip_kod = rez.kalipKod;
                payload.enj_aktif_goz = (rez.kalipAdedi || 0) * (rez.gozPerKalip || 1);
                payload.enj_kalip_adedi = rez.kalipAdedi || 0;
                payload.enj_goz_per_kalip = rez.gozPerKalip;
                payload.enj_kalip_basi_cift = rez.kalipBasiCift;
                payload.enj_tur_cift = mr.tur_basi_cift || enj.turCift;
                payload.enj_plan_baslangic = rez.baslangic;
                payload.enj_plan_bitis = mr.tahmini_bitis || rez.bitis;
                payload.enj_planlanacak_cift = rez.planCift;
                payload.enj_calisma_modu = rez.calismaModu || enj.calismaModu;
                payload.enj_hafta_sonu_calisma = enj.haftaSonu;
                payload.enj_hafta_sonu_vardiya = enj.haftaSonu === 'EVET' ? enj.hsVardiya : null;
                payload.enj_kapasite_snapshot = JSON.stringify({
                    kalip_adedi: rez.kalipAdedi,
                    kalip_basi_cift: rez.kalipBasiCift,
                    aktif_goz: rez.gozPerKalip,
                    tur_basi_cift: mr.tur_basi_cift,
                    teorik_tur: mr.teorik_tur,
                    gerekli_tam_tur: mr.gerekli_tam_tur || mr.tahmini_gerekli_tur,
                    planlanacak_cift: rez.planCift,
                    siparis_ihtiyaci: mr.siparis_ihtiyaci || rez.planCift,
                    teorik_cikan: mr.teorik_cikan,
                    fazla_cift: mr.fazla_cift,
                    gerekli_tur: mr.gerekli_tam_tur || mr.tahmini_gerekli_tur,
                    warnings: mr.warnings || [],
                    tahmini_bitis: mr.tahmini_bitis,
                    calendar_rule: mr.hafta_sonu_kural,
                    calisma_modu: rez.calismaModu || enj.calismaModu,
                    hafta_sonu_calisma: enj.haftaSonu,
                    hafta_sonu_vardiya: enj.hsVardiya,
                    calendar_breakdown: mr.vardiya_breakdown || [],
                    kalip_kod: rez.kalipKod,
                    manuel_kalip: enj.kalipMode === 'manuel',
                    reference_mode: enj.referenceMode || 'MANUAL',
                    manual_reference_gunduz: enj.referenceMode === 'MANUAL' ? enj.manualRefGunduz : null,
                    manual_reference_gece: enj.referenceMode === 'MANUAL' ? enj.manualRefGece : null,
                    auto_ref_gunduz: enj.autoRefGunduz || null,
                    auto_ref_gece: enj.autoRefGece || null,
                    // Audit: kaynak ve onay durumu
                    ref_source_gunduz: enj.refSourceGunduz || 'MANUAL',
                    ref_source_gece:   enj.refSourceGece   || 'MANUAL',
                    ref_confirmed_gunduz: !!enj.refConfirmedGunduz,
                    ref_confirmed_gece:   !!enj.refConfirmedGece,
                    ref_audit_ts: new Date().toISOString(),
                });
            }
            fetch('/planlama/uretim-plan/api/plan', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); })
                .then(function (res) {
                    if (!res.d.ok) {
                        if (res.status === 409 && res.d.conflict_detail) {
                            enjShowConflictModal(res.d.conflict_detail);
                        }
                        var msgs = normalizeServerErrors(res.d, res.status);
                        var flds = [];
                        if (msgs.some(function (m) { return m.indexOf('zaten planlı') >= 0; })) flds.push('upFormDonem');
                        if (msgs.some(function (m) { return m.indexOf('Plan bitiş') >= 0; })) flds.push('upFormBit');
                        showPlanErrors(msgs, flds);
                        return;
                    }
                    clearPlanErrors();
                    closeModals();
                    fetchPlanlar();
                })
                .catch(function (e) {
                    showPlanErrors([e.message || 'Bağlantı hatası'], []);
                });
        }

        if (state.requiresEnj && enj.hesapOk && rez) {
            fetch('/planlama/uretim-plan/api/enj/cakisma-kontrol', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    makine_id: enj.makineId,
                    slot: rez.slot,
                    istasyonlar: rez.istasyonlar,
                    enj_plan_baslangic: rez.baslangic,
                    enj_plan_bitis: mr.tahmini_bitis || rez.bitis,
                    calisma_modu: rez.calismaModu || enj.calismaModu,
                    hafta_sonu_calisma: enj.haftaSonu,
                    hafta_sonu_vardiya: enj.hsVardiya,
                }),
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d.ok && d.cakisma && d.conflict_detail) {
                      enjShowConflictModal(d.conflict_detail);
                      showPlanErrors([d.conflict_detail.mesaj || 'Kayıt anında çakışma'], []);
                      return;
                  }
                  postPlan();
              })
              .catch(function () { postPlan(); });
            return;
        }
        postPlan();
    }

    function deactivatePlan(planId) {
        fetch('/planlama/uretim-plan/api/plan/' + planId, {
            method: 'DELETE', credentials: 'include',
        }).then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj);
                fetchPlanlar();
            })
            .catch(function (e) { showError(e.message); });
    }

    function focusDetayProses(prosesKod) {
        selectDetayProses(prosesKod);
    }

    function openDetay(planId, focusProsesKod) {
        state.detayPlanId = planId;
        var modal = $('upDetayModal');
        var body = $('upDetayBody');
        if (!modal || !body) return;
        modal.hidden = false;
        body.innerHTML = '<div class="up-loading">Yükleniyor…</div>';
        fetch('/planlama/uretim-plan/api/detay/' + planId, { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj);
                renderDetayOzet(d.satir, body, focusProsesKod);
            })
            .catch(function (e) { body.innerHTML = '<div class="up-error">' + esc(e.message) + '</div>'; });
    }

    function renderEnjOzetHtml(r) {
        if (!r.enj_makine_id) return '';
        var makKod = r.enj_makine_kod || ('M' + r.enj_makine_id);
        var slotStr = (r.enj_istasyon_no ? r.enj_istasyon_no : '—') + (r.enj_slot || '');
        var turCift = r.enj_tur_cift != null ? r.enj_tur_cift + ' çift/tur' : '—';
        var gunlukKap = r.enj_gunluk_kapasite != null ? fmtN(r.enj_gunluk_kapasite) + ' çift/gün' : '—';
        var tahminiGun = r.enj_tahmini_gun != null ? parseFloat(r.enj_tahmini_gun).toFixed(2) + ' gün' : '—';
        return '<div class="up-enj-detay-ozet">' +
            '<h4>Planlanan Enjeksiyon</h4>' +
            '<dl class="up-detay-meta up-enj-ozet-dl">' +
            '<dt>Makine</dt><dd>' + esc(makKod) + '</dd>' +
            '<dt>İstasyon / Slot</dt><dd>' + esc(slotStr) + '</dd>' +
            '<dt>Kalıp</dt><dd>' + esc(r.enj_kalip_kod || '—') + '</dd>' +
            '<dt>Tur başı çift</dt><dd>' + esc(turCift) + '</dd>' +
            '<dt>Plan Tur/Gün</dt><dd>' + esc(r.enj_gunluk_tur_plan != null ? r.enj_gunluk_tur_plan : '—') + '</dd>' +
            '<dt>Günlük Kapasite</dt><dd>' + esc(gunlukKap) + '</dd>' +
            '<dt>Plan Başlangıç</dt><dd>' + fmtTarih(r.enj_plan_baslangic) + '</dd>' +
            '<dt>Plan Bitiş</dt><dd>' + fmtTarih(r.enj_plan_bitis) + '</dd>' +
            '<dt>Tahmini Süre</dt><dd>' + esc(tahminiGun) + '</dd>' +
            '</dl></div>';
    }

    function detayMetaRow(label, valueHtml, valueClass) {
        return '<div class="up-detay-meta-row">' +
            '<span class="up-detay-meta-lbl">' + esc(label) + '</span>' +
            '<span class="up-detay-meta-val' + (valueClass ? ' ' + valueClass : '') + '">' + valueHtml + '</span>' +
            '</div>';
    }

    function renderDetayOzet(r, body, focusProsesKod) {
        state.detaySatir = r;
        state.detayKatFilter = 'TUMU';
        var prosesler = r.prosesler || [];
        state.detayProsesKod = focusProsesKod || (prosesler[0] && prosesler[0].proses_kod) || '';
        var activeProses = prosesByKod(prosesler, state.detayProsesKod);
        $('upDetayBaslik').textContent = (r.model_kod || '') + ' — ' + (r.renk || '');
        body.innerHTML =
            '<div class="up-detay-layout">' +
            '<div class="up-detay-top">' +
            '<div class="up-detay-top-media">' + thumbHtml(r, 'up-detay-thumb') + '</div>' +
            '<div class="up-detay-top-sip">' +
            detayMetaRow('Sipariş No', esc(r.sip_no), 'up-detay-meta-val-key') +
            detayMetaRow('Cari', esc(r.musteri || r.cari || '—')) +
            detayMetaRow('Model', esc(r.model_kod), 'up-detay-meta-val-key') +
            detayMetaRow('Renk', '<span class="up-renk-dot"></span>' + esc(r.renk)) +
            detayMetaRow('Asorti', esc(r.asorti || '—')) +
            detayMetaRow('Miktar', fmtN(r.miktar), 'up-detay-meta-val-key') +
            detayMetaRow('Termin', fmtTarih(r.termin)) +
            '</div>' +
            '<div class="up-detay-top-plan">' +
            detayMetaRow('Plan Dönemi', esc(r.plan_donemi || '—')) +
            detayMetaRow('Plan Başlangıç', fmtTarih(r.plan_baslangic)) +
            detayMetaRow('Plan Bitiş', fmtTarih(r.plan_bitis)) +
            detayMetaRow('Öncelik', esc(r.oncelik != null && r.oncelik !== '' ? r.oncelik : '—')) +
            detayMetaRow('Durum', durumBadge(r.durum, r.durum_renk, r.yuzde)) +
            '</div></div>' +
            renderEnjOzetHtml(r) +
            '<div class="up-detay-proses-section">' +
            '<div class="up-detay-proses-head">' +
            '<span class="up-detay-proses-title">PROSES DURUMLARI</span>' +
            '<span class="up-detay-legend-inline">' +
            '<i class="dot yesil"></i> BİTTİ <i class="dot sari"></i> DEVAM ' +
            '<i class="dot gri"></i> BAŞLANMADI <i class="dot kirmizi"></i> GERİDE</span></div>' +
            renderDetayProsesFlow(prosesler, state.detayProsesKod) +
            '</div>' +
            '<div id="upDetayDetailPanel" class="up-detay-detail-panel">' +
            renderDetayEmirTable(activeProses) +
            '</div></div>';
        if (r.plan_notu) {
            body.insertAdjacentHTML('beforeend', '<p class="up-detay-not"><strong>Plan Notu:</strong> ' + esc(r.plan_notu) + '</p>');
        }
        bindDetayProsesEvents();
        bindDetayKatFilterEvents();
    }

    function openEdit(planId) {
        var row = state.satirlar.find(function (r) { return r.plan_id === planId; });
        if (!row) return;
        state.editPlanId = planId;
        var donemSel = $('upEditDonem');
        donemSel.innerHTML = '';
        ['bu_hafta', 'gelecek_hafta', 'bu_ay', '3_ay'].forEach(function (d) {
            var o = document.createElement('option');
            o.value = d; o.textContent = d.replace('_', ' ');
            if (d === row.plan_donemi) o.selected = true;
            donemSel.appendChild(o);
        });
        $('upEditBas').value = (row.plan_baslangic || '').slice(0, 10);
        $('upEditBit').value = (row.plan_bitis || '').slice(0, 10);
        var onc = $('upEditOncelik');
        onc.innerHTML = '';
        for (var i = 1; i <= 5; i++) {
            var o = document.createElement('option');
            o.value = i; o.textContent = i;
            if (i === row.oncelik) o.selected = true;
            onc.appendChild(o);
        }
        var gerek = $('upEditGerekce');
        gerek.innerHTML = '<option value="">—</option>';
        (window.UP_GEREKCE || []).forEach(function (g) {
            var o = document.createElement('option');
            o.value = g; o.textContent = g;
            if (g === row.plan_gerekce) o.selected = true;
            gerek.appendChild(o);
        });
        $('upEditNot').value = row.plan_notu || '';
        $('upEditModal').hidden = false;
    }

    function saveEdit() {
        fetch('/planlama/uretim-plan/api/plan/' + state.editPlanId, {
            method: 'PUT',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plan_donemi: $('upEditDonem').value,
                plan_baslangic: $('upEditBas').value,
                plan_bitis: $('upEditBit').value,
                oncelik: parseInt($('upEditOncelik').value, 10),
                plan_gerekce: $('upEditGerekce').value,
                plan_notu: $('upEditNot').value,
            }),
        }).then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj);
                closeModals();
                fetchPlanlar();
            })
            .catch(function (e) { showError(e.message); });
    }

    function init() {
        enjBindEvents();
        document.querySelectorAll('.up-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                document.querySelectorAll('.up-tab').forEach(function (t) { t.classList.remove('active'); });
                tab.classList.add('active');
                state.donem = tab.getAttribute('data-donem');
                fetchPlanlar();
            });
        });

        if ($('upYenileBtn')) $('upYenileBtn').addEventListener('click', fetchPlanlar);

        if ($('upPlanOlusturBtn')) {
            $('upPlanOlusturBtn').addEventListener('click', function () {
                state.seciliCreate = null;
                state.seciliCreateData = null;
                state.createStep = 1;
                state.requiresEnj = false;
                $('upCreateListe').innerHTML = '';
                if ($('upStep1Readonly')) $('upStep1Readonly').style.display = 'none';
                wizardShowStep(1);
                $('upCreateSipNo').value = '';
                $('upCreateHint').textContent = '';
                enjReset();
                clearPlanErrors();
                $('upCreateModal').hidden = false;
            });
        }

        if ($('upWizardNextBtn')) {
            $('upWizardNextBtn').addEventListener('click', function () {
                if (state.createStep === 1) {
                    if (!state.seciliCreate) return;
                    if (state.requiresEnj) wizardShowStep(2);
                    else wizardShowStep(3);
                } else if (state.createStep === 2) {
                    if (state.requiresEnj && !state.enj.hesapOk) return;
                    wizardShowStep(3);
                }
            });
        }
        if ($('upWizardBackBtn')) {
            $('upWizardBackBtn').addEventListener('click', function () {
                if (state.createStep === 3) {
                    wizardShowStep(state.requiresEnj ? 2 : 1);
                } else if (state.createStep === 2) {
                    wizardShowStep(1);
                }
            });
        }

        document.querySelectorAll('[data-close]').forEach(function (el) {
            el.addEventListener('click', closeModals);
        });

        if ($('upCreateGetirBtn')) {
            $('upCreateGetirBtn').addEventListener('click', function () {
                var sip = ($('upCreateSipNo').value || '').trim();
                if (!sip) { showError('Sipariş no girin'); return; }
                fetchCreateOnizleme(sip);
            });
        }

        if ($('upPlanaEkleBtn')) $('upPlanaEkleBtn').addEventListener('click', savePlan);
        if ($('upFormBit')) $('upFormBit').addEventListener('change', function () {
            validateStep3Tarihleri();
            clearPlanErrors();
        });
        if ($('upFormDonem')) $('upFormDonem').addEventListener('change', function () {
            clearPlanErrors();
            var donem = $('upFormDonem').value;
            var bas = $('upFormBas') && $('upFormBas').value;
            // Dönem değişince bitiş tarihini yeniden hesapla (enjeksiyon yoksa)
            var rez = state.enj.reservation || {};
            var hasEnj = !!(rez.baslangic || state.enj.baslangic);
            if (!hasEnj) {
                var aralik = donemAralikJs(donem);
                if ($('upFormBit')) $('upFormBit').value = aralik.bit;
                // Başlangıç seçeneğini de güncelle
                var fakeSecenekler = [{ tarih: aralik.bas, dolu: false, oneri_donem: donem }];
                renderStep3BasSecenekleri(fakeSecenekler, aralik.bas, null);
                return;
            }
            if (bas) {
                fetchStep3OnCheck([bas], function (secs) {
                    var s0 = secs[0] || {};
                    if (s0.dolu) {
                        showStep3Uyari(s0.mesaj || 'KULLANILAMAZ — bu dönemde plan mevcut');
                        state.step3.saveBlocked = true;
                    } else {
                        state.step3.saveBlocked = false;
                        showStep3Uyari('');
                    }
                    wizardUpdateNav();
                });
            }
        });
        if ($('upEditKaydetBtn')) $('upEditKaydetBtn').addEventListener('click', saveEdit);

        if ($('upDetayDuzenleBtn')) {
            $('upDetayDuzenleBtn').addEventListener('click', function () {
                if (state.detayPlanId) openEdit(state.detayPlanId);
            });
        }

        fetchPlanlar();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
