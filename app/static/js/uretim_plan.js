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
            libraryPlanEnabled: false,
            libraryKalipList: [],
            libraryUuid: null,
            libraryKalipMeta: null,
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
            shiftStartOverrideRequired: false,
            shiftStartOverrideConfirmed: false,
            shiftStartOverrideTime: null,
            shiftStartSuggestedBoundary: null,
            shiftStartApprovalContext: null,
            bitis: null,
            planCift: null,
            calismaModu: 'GUNDUZ_GECE',
            haftaSonu: 'HAYIR',
            hsVardiya: null,
            motorResult: null,
            hesapOk: false,
            hesapDetayAcik: false,
            _fizikselKalipLimitAttempt: false,
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
            slotOzetMap: {},
            baseFirstAvailableMap: {},
            slotOzetSeq: 0,
            istasyonAvailabilitySeq: 0,
            ilkUygunMap: {},
            makineDetayCache: {},
            makineDetayLoadingKey: null,
            makineDetayTriggerBtn: null,
            takvimMakineId: null,
            takvimMakineKod: null,
            takvimAnchor: null,
            takvimNumDays: 4,
            takvimPlanDetay: null,
            takvimData: null,
            takvimLoadingKey: null,
            takvimSecim: null,
            takvimActiveSlot: null,
            takvimFormSnapshot: null,
            takvimApplied: false,
            takvimTriggerBtn: null,
            istasyonPlanDurum: {},
            reservation: null,
            pendingConflict: null,
            quantitySummary: null,
            capacityOneri: null,
            capacitySourceGunduz: 'NONE',
            capacitySourceGece: 'NONE',
            capacityConfirmedTurGunduz: null,
            capacityConfirmedTurGece: null,
            capacityAuditGunduz: null,
            capacityAuditGece: null,
            capacityManualOpenGunduz: false,
            capacityManualOpenGece: false,
            setupMinutes: null,
            setupConfirmed: false,
            draftPreview: null,
            takvimAccOpen: true,
            makinePanelCollapsed: false,
            _timelineRecalcMsg: null,
        },
        createStep: 1,
        requiresEnj: false,
        step3: {
            basMode: null,
            secenekler: [],
            saveBlocked: false,
            bitisUyari: null,
            onerilenBit: null,
            manuelDegisti: false,
            oncekiPlanlar: [],
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
            // PHASE_7E: Library modunda UUID seçimi yapılmadıysa daha net hata göster.
            if (state.enj.libraryPlanEnabled && state.enj.kalipMode === 'liste' && !state.enj.libraryUuid) {
                errors.push('Kütüphaneden kalıp seçiniz: "Seç" butonuna tıklayarak seçim yapın.');
                fields.push('upEnjKalipLibraryList');
            } else {
                errors.push('Önce enjeksiyon hesabını tamamlayın.');
            }
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
        ['upDetayModal', 'upEditModal'].forEach(function (id) {
            var m = $(id);
            if (m) m.hidden = true;
        });
        document.querySelectorAll('.up-aksiyon-menu.open').forEach(function (m) {
            m.classList.remove('open');
        });
    }

    function createModalIsDirty() {
        if (state.seciliCreate) return true;
        var e = state.enj;
        return !!(e.makineId || e.slot || (e.istasyonlar && e.istasyonlar.length) ||
            e.baslangic || e.kalipId || e.kalipKod || e.hesapOk ||
            (e.planCift && e.planCift > 0));
    }

    function closeCreateModalConfirmed() {
        closeModals();
        var m = $('upCreateModal');
        if (m) m.hidden = true;
        state.seciliCreate = null;
        state.seciliCreateData = null;
        enjReset();
    }

    function requestCloseCreateModal() {
        if (!createModalIsDirty()) {
            closeCreateModalConfirmed();
            return;
        }
        if (window.confirm('Kaydedilmemiş seçimler silinecek. Çıkmak istiyor musunuz?')) {
            closeCreateModalConfirmed();
        }
    }

    function fetchQuantitySummary(cb) {
        var o = state.seciliCreateData;
        if (!o) {
            state.enj.quantitySummary = null;
            if (cb) cb();
            return;
        }
        var q = 'sip_no=' + encodeURIComponent(o.sip_no) +
            '&sip_harinx=' + encodeURIComponent(o.sip_harinx || 0) +
            '&mamul_skod=' + encodeURIComponent(o.model_kod || o.mamul_skod) +
            '&rkod=' + encodeURIComponent(o.rkod || 0);
        fetch('/planlama/uretim-plan/api/plan/kalem-miktar-ozet?' + q, { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                // ok=true (normal) veya quantity_calculable=false (legacy partial) kabul edilir
                state.enj.quantitySummary = (d.ok || (d && d.quantity_calculable === false)) ? d : null;
                if (state.enj.quantitySummary && state.enj.quantitySummary.remaining_quantity === 0 &&
                    state.enj.quantitySummary.quantity_calculable !== false) {
                    enjFetchMevcutPlanLink(function () {
                        enjUpdateMiktarOzet();
                        enjUpdateKurulumOzet();
                        if (cb) cb();
                    });
                } else {
                    state.enj._mevcutPlanLink = null;
                    enjUpdateMiktarOzet();
                    enjUpdateKurulumOzet();
                    if (cb) cb();
                }
            })
            .catch(function () {
                state.enj.quantitySummary = null;
                if (cb) cb();
            });
    }

    function enjSummaryVal(val, pendingLabel) {
        if (val === null || val === undefined || val === '') {
            return '<span class="pending">' + esc(pendingLabel || 'Seçilmedi') + '</span>';
        }
        return esc(String(val));
    }

    function enjUpdateKurulumOzet() {
        var body = $('upStep2KurulumBody');
        var footKurulum = $('upStep2FootKurulum');
        var e = state.enj;
        var parts = [];
        if (e.makineKod) parts.push(e.makineKod);
        if (e.slot)      parts.push(e.slot + ' Tarafı');
        if (e.istasyonlar && e.istasyonlar.length) parts.push(e.istasyonlar.length + ' istasyon');
        if (e.kalipKod)  parts.push(e.kalipKod);
        var txt = parts.length ? parts.join(' · ') : 'Henüz makine ve taraf seçilmedi.';
        if (body) body.textContent = txt;
        if (footKurulum) footKurulum.style.display = 'none';
        enjUpdateDurumStrip();
        enjUpdateHeadCompactSummary();
    }

    /** PHASE_7O3E: Üst başlık kompakt özet + tek yönlendirme */
    function enjUpdateHeadCompactSummary(statusMsg, nextOverride) {
        var wrap = $('upStep2HeadSummary');
        var compact = $('upStep2HeadCompact');
        var next = $('upStep2HeadNext');
        if (!wrap) return;
        if (state.createStep !== 2) {
            wrap.style.display = 'none';
            return;
        }
        wrap.style.display = '';
        var e = state.enj;
        var parts = [];
        if (e.makineKod && e.slot) parts.push(e.makineKod + '/' + e.slot);
        else if (e.makineKod) parts.push(e.makineKod);
        if (e.istasyonlar && e.istasyonlar.length) {
            parts.push(e.istasyonlar.length + ' istasyon');
        }
        var kalipLbl = e.kalipKod ||
            (e.libraryKalipMeta && e.libraryKalipMeta.visible_mold_code) || '';
        if (kalipLbl) parts.push(kalipLbl);
        if (typeof enjCapacityConfirmedOk === 'function') {
            parts.push(enjCapacityConfirmedOk() ? 'Kapasite onaylı' : 'Kapasite eksik');
        }
        var basIso = (e.draftPreview && (e.draftPreview.plan_baslangic || e.draftPreview.uretim_baslangic)) ||
            e.baslangic;
        if (basIso) parts.push(enjFmtDtCompact(basIso));
        if (compact) compact.textContent = parts.length ? parts.join(' · ') : 'Kurulum devam ediyor';

        var nextTxt = nextOverride || '';
        if (!nextTxt) {
            if (enjKalanSifirBlocked()) {
                nextTxt = 'Sıradaki: Mevcut planı inceleyin';
            } else if (!e.makineId || !e.slot) {
                nextTxt = 'Sıradaki: Makine ve taraf seçin';
            } else if (!enjHasBaslangic()) {
                nextTxt = 'Sıradaki: Başlangıç tercihini belirleyin';
            } else if (!enjKalipSecili()) {
                nextTxt = 'Sıradaki: Kalıp seçin';
            } else if (!e.istasyonlar || !e.istasyonlar.length) {
                nextTxt = 'Sıradaki: İstasyon seçin';
            } else if (typeof enjCapacityConfirmedOk === 'function' && !enjCapacityConfirmedOk()) {
                nextTxt = 'Sıradaki: Kapasiteyi onaylayın';
            } else if (!e.hesapOk && !e.draftPreview) {
                nextTxt = 'Sıradaki: Takvimde hesaplayın';
            } else {
                nextTxt = 'Sıradaki: İleri ile devam edin';
            }
        }
        if (statusMsg && compact) {
            compact.textContent = statusMsg;
        }
        if (next) next.textContent = nextTxt;
    }

    function enjUpdateFizikselKalipDisplay() {
        var valEl = $('upEnjFizikselKalipVal');
        var hintEl = $('upEnjFizikselKalipHint');
        if (!valEl) return;
        var lim = enjGetFizikselKalipLimit();
        if (!enjKalipSecili() || lim == null) {
            valEl.textContent = '—';
            if (hintEl) hintEl.textContent = 'Seçilen kalıptan gelir; istasyon seçim üst sınırıdır.';
            return;
        }
        valEl.textContent = String(lim) + ' adet';
        if (hintEl) {
            hintEl.textContent = 'En fazla ' + lim + ' istasyon seçilebilir.';
        }
    }

    function enjUpdateKalipSeciliCards() {
        var manBox = $('upEnjManuelKalipSummary');
        var e = state.enj;
        if (e.kalipMode === 'manuel') {
            enjRenderLibrarySummary(null);
            if (!manBox) return;
            if (!enjKalipSecili()) {
                manBox.style.display = 'none';
                manBox.innerHTML = '';
                return;
            }
            manBox.innerHTML = '<div class="up-ws-sum-card"><div class="up-ws-sum-head"><span class="up-ws-sum-title">' +
                esc(e.kalipKod || 'Manuel kalıp') + '</span></div><div class="up-ws-sum-row">Kalıp İçi <b>' +
                esc(String(e.kalipBasiCift || '—')) + '</b> Çift · Manuel giriş</div></div>';
            manBox.style.display = '';
            return;
        }
        if (manBox) { manBox.style.display = 'none'; manBox.innerHTML = ''; }
        enjRenderLibrarySummary(e.libraryKalipMeta || null);
    }

    function enjMountTakvimAccordionPanels() {
        var host = $('upTakvimAccHost');
        var body = $('upTakvimAccBody');
        if (!body || body.dataset.mounted === '1') return;
        if (host) {
            while (host.firstChild) body.appendChild(host.firstChild);
            host.parentNode.removeChild(host);
        }
        body.dataset.mounted = '1';
    }

    function enjCalismaShortLabel(v) {
        if (v === 'GUNDUZ') return 'Gündüz';
        if (v === 'GECE') return 'Gece';
        return 'Gündüz + Gece';
    }

    function enjHsShortLabel(v) {
        return v === 'EVET' ? 'Hafta sonu açık' : 'Hafta sonu kapalı';
    }

    function enjUpdateTakvimAccSummary() {
        var sum = $('upTakvimAccSummary');
        var acc = $('upTakvimAcc');
        if (!sum || !acc) return;
        var e = state.enj;
        var capOk = typeof enjCapacityConfirmedOk === 'function' && enjCapacityConfirmedOk();
        var parts = [
            enjCalismaShortLabel(e.calismaModu || 'GUNDUZ_GECE'),
            enjHsShortLabel(e.haftaSonu || 'HAYIR'),
            capOk ? 'Kapasite onaylı' : 'Kapasite eksik',
        ];
        sum.innerHTML = '▶ ' + esc(parts.join(' · ')) + ' · <span class="up-takvim-acc-edit">Düzenle</span>';
    }

    function enjSetTakvimAccOpen(open) {
        var acc = $('upTakvimAcc');
        var toggle = $('upTakvimAccToggle');
        if (!acc) return;
        state.enj.takvimAccOpen = open !== false;
        acc.classList.toggle('is-collapsed', !state.enj.takvimAccOpen);
        if (toggle) toggle.setAttribute('aria-expanded', state.enj.takvimAccOpen ? 'true' : 'false');
        var openLbl = acc.querySelector('.up-takvim-acc-open-lbl');
        var closedLbl = $('upTakvimAccSummary');
        if (openLbl) openLbl.hidden = !state.enj.takvimAccOpen;
        if (closedLbl) closedLbl.hidden = state.enj.takvimAccOpen;
        enjUpdateTakvimAccSummary();
    }

    function enjToggleTakvimAcc(forceOpen) {
        var open = forceOpen;
        if (open === undefined) open = !state.enj.takvimAccOpen;
        enjSetTakvimAccOpen(open);
    }

    function enjUpdateTakvimDraftBar() {
        var bar = $('upTakvimDraftBar');
        var txt = $('upTakvimDraftMetin');
        var e = state.enj;
        if (!bar) return;
        if (!e.draftPreview) {
            bar.style.display = 'none';
            return;
        }
        var dp = e.draftPreview;
        var bas = dp.plan_baslangic || dp.uretim_baslangic;
        var bit = dp.tahmini_bitis;
        if (txt) {
            txt.textContent = (e.makineKod || 'M') + '/' + (dp.slot || e.slot || '—') +
                ' · ' + enjFmtDtCompact(bas) + ' → ' + enjFmtDtCompact(bit) + ' · Taslak (kaydedilmedi)';
        }
        bar.style.display = '';
    }

    function enjApplyTakvimHesap() {
        if (!enjCanHesapla()) {
            enjUpdateHeadCompactSummary();
            enjToggleTakvimAcc(true);
            return;
        }
        state.enj._takvimHesapPending = true;
        enjHesaplaMotor();
    }

    function enjApplyDraftPlanToSetup() {
        var e = state.enj;
        var dp = e.draftPreview;
        if (!dp) return;
        var bas = dp.plan_baslangic || dp.uretim_baslangic;
        if (bas) {
            e.baslangic = bas;
            e.baslangicManuel = true;
            if ($('upEnjBas')) $('upEnjBas').value = enjApiDtToLocal(bas);
            if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        }
        if (dp.tahmini_bitis) e.bitis = dp.tahmini_bitis;
        if (dp.slot) e.slot = dp.slot;
        e.takvimApplied = true;
        enjCloseTakvimWorkspace();
        enjUpdateStep2Ui();
        enjUpdateHesapBtn();
        wizardUpdateNav();
    }

    function enjUpdateDurumStrip() {
        var e = state.enj;
        function setKutu(id, valTxt, ok) {
            var el = $(id);
            if (!el) return;
            /* Hem yeni (.up-durum-kutu) hem eski (.up-enj-durum-kutu) class adını destekle */
            var baseClass = el.className.indexOf('up-durum-kutu') >= 0 ? 'up-durum-kutu' : 'up-enj-durum-kutu';
            el.className = baseClass + (ok ? ' ok' : ' pending');
            /* Yeni HTML: .up-durum-check / .up-durum-val  |  Eski: .up-enj-durum-icon / .up-enj-durum-val */
            var icon = el.querySelector('.up-durum-check') || el.querySelector('.up-enj-durum-icon');
            if (icon) icon.textContent = ok ? '✓' : '';
            var valEl = el.querySelector('.up-durum-val') || el.querySelector('.up-enj-durum-val');
            if (valEl && valTxt !== undefined) valEl.textContent = valTxt;
        }
        /* Makine */
        setKutu('upEnjDurumMakine', e.makineKod || 'Seçilmedi', !!e.makineKod);
        /* İstasyon */
        var istSayisi = e.istasyonlar ? e.istasyonlar.length : 0;
        setKutu('upEnjDurumIstasyon', istSayisi > 0 ? istSayisi + ' seçili' : 'Seçilmedi', istSayisi > 0);
        /* Kalıp */
        var kalipGoster = e.kalipMode === 'manuel' ? (e.kalipKod || null) : (e.kalipKod || null);
        setKutu('upEnjDurumKalip', kalipGoster || 'Tanımlı değil', !!kalipGoster);
        /* Hız */
        var hizOk = e.calismaModu === 'GECE'
            ? (e.manualRefGece != null)
            : e.calismaModu === 'GUNDUZ'
                ? (e.manualRefGunduz != null)
                : (e.manualRefGunduz != null && e.manualRefGece != null);
        setKutu('upEnjDurumHiz', hizOk ? 'Hazır' : 'Eksik', hizOk);
        /* Başlangıç */
        var basGoster = e.baslangic ? enjFmtDtApi(e.baslangic) : 'Belirlenmedi';
        setKutu('upEnjDurumBas', basGoster, !!e.baslangic);
        /* Başlangıç mirror */
        var mirror = $('upEnjBas2Mirror');
        if (mirror) mirror.textContent = e.baslangic ? enjFmtDtApi(e.baslangic) : '—';
        /* Kompakt hesap bandı güncelle */
        enjUpdateHesapBandi();
        enjUpdateTarihDurumEtiketi();
    }

    function enjUpdateHesapBandi() {
        var bant = $('upEnjHesapBandi');
        if (!bant) return;
        var e = state.enj;
        var parts = [];
        var planCift = parseInt(($('upEnjPlanCift') && $('upEnjPlanCift').value) || e.planCift || 0, 10);
        if (planCift > 0) parts.push(fmtN(planCift) + ' çift');
        if (e.kalipAdedi > 0 && e.gozPerKalip > 0) {
            parts.push((e.kalipAdedi * (e.gozPerKalip || 1)) + ' aktif göz');
        } else if (e.istasyonlar && e.istasyonlar.length > 0) {
            parts.push(e.istasyonlar.length + ' istasyon');
        }
        if (e.makineKod && e.slot) parts.push(e.makineKod + '/' + e.slot);
        if (e.calismaModu) parts.push(enjCalismaLabel(e.calismaModu));
        bant.textContent = parts.length ? parts.join(' · ') : '—';
    }

    function enjKalanSifirBlocked() {
        var qs = state.enj.quantitySummary;
        return !!(qs && qs.quantity_calculable !== false && qs.remaining_quantity === 0);
    }

    function enjUpdateMiktarOzet() {
        var el = $('upEnjMiktarOzet');
        var warn = $('upEnjMiktarUyari');
        if (!el) return;
        var qs = state.enj.quantitySummary;
        var req = parseInt(($('upEnjPlanCift') && $('upEnjPlanCift').value) || state.enj.planCift || 0, 10) || 0;
        if (!qs || qs.order_total_quantity == null) {
            el.innerHTML = '<span class="up-hint">Miktar özeti yüklenemedi.</span>';
            if (warn) warn.style.display = 'none';
            state.enj._kalanSifir = false;
            return;
        }
        var rem = qs.remaining_quantity;  // null ise hesaplanamıyor
        var legacyBlock = (qs.quantity_calculable === false);
        var after = (rem != null) ? Math.max(0, rem - req) : null;
        state.enj._kalanSifir = !legacyBlock && rem === 0;
        var planInput = $('upEnjPlanCift');
        if (planInput && state.enj._kalanSifir) {
            planInput.value = '';
            planInput.disabled = true;
            state.enj.planCift = null;
        } else if (planInput) {
            planInput.disabled = false;
        }
        var alreadyLbl = qs.already_planned_quantity != null
            ? (legacyBlock ? 'En az ' + fmtN(qs.already_planned_quantity) + ' çift' : fmtN(qs.already_planned_quantity) + ' çift')
            : '—';
        var remLbl = legacyBlock ? 'Hesaplanamıyor' : (rem != null ? fmtN(rem) + ' çift' : '—');
        var afterLbl = legacyBlock ? 'Hesaplanamıyor' : (after != null ? fmtN(after) + ' çift' : '—');
        function mikRow(lbl, val) {
            return '<div class="up-miktar-row"><span class="up-miktar-lbl">' + lbl + '</span>' +
                '<span class="up-miktar-val">' + val + '</span></div>';
        }
        el.innerHTML =
            mikRow('Toplam Sipariş', fmtN(qs.order_total_quantity) + ' çift') +
            mikRow('Önceden Planlanan', alreadyLbl) +
            mikRow('Kalan', remLbl) +
            mikRow('Bu Plan', (req > 0 ? fmtN(req) : '—') + ' çift') +
            mikRow('Planlama Sonrası', afterLbl);
        if (warn) {
            if (state.enj._kalanSifir) {
                warn.style.display = 'none';
            } else if (legacyBlock) {
                warn.className = 'up-enj-miktar-uyari';
                warn.textContent = qs.warning || 'Legacy plan miktarı düzeltilmeden kayıt yapılamaz.';
                warn.style.display = 'block';
            } else if (req > 0 && rem != null && req > rem) {
                warn.className = 'up-enj-miktar-uyari';
                warn.textContent = 'Bu plan miktarı kalan miktarı (' + fmtN(rem) + ' çift) aşıyor. Kayıt sunucuda reddedilir.';
                warn.style.display = 'block';
            } else if (req > 0 && after === 0) {
                warn.className = 'up-enj-miktar-uyari';
                warn.textContent = 'Sipariş miktarının tamamı planlanacak.';
                warn.style.display = 'block';
            } else if (req > 0 && after > 0) {
                warn.className = 'up-enj-miktar-uyari';
                warn.textContent = 'Bu işlemden sonra ' + fmtN(after) + ' çift planlanmayı bekleyecek.';
                warn.style.display = 'block';
            } else {
                warn.style.display = 'none';
            }
        }
        enjUpdateKurulumOzet();
        enjUpdateCentralStatus();
        wizardUpdateNav();
    }

    function enjFetchMevcutPlanLink(cb) {
        var o = state.seciliCreateData;
        if (!o) { if (cb) cb(); return; }
        fetch('/planlama/uretim-plan/api/plan/onceki?' + new URLSearchParams({
            sip_no: o.sip_no || '',
            sip_harinx: o.sip_harinx || 0,
            mamul_skod: o.model_kod || o.mamul_skod || '',
            rkod: o.rkod || 0,
        }), { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                state.enj._mevcutPlanLink = null;
                if (d.ok && d.planlar && d.planlar.length) {
                    var aktif = d.planlar.find(function (p) { return p.aktif == 1 || p.aktif === true; });
                    var pid = (aktif || d.planlar[0]).plan_id;
                    if (pid) state.enj._mevcutPlanLink = '/planlama/uretim-plan/?plan_id=' + pid;
                }
                if (cb) cb();
            })
            .catch(function () { if (cb) cb(); });
    }

    // Faz 2B'de fiziksel kalıp envanteri / istasyon-kalıp dağılımı ile ayrıştırılacak.
    function enjSyncKalipAdediFromStations() {
        var n = (state.enj.istasyonlar || []).length;
        state.enj.kalipAdedi = n > 0 ? n : null;
        if ($('upEnjKalipAdedi')) $('upEnjKalipAdedi').value = n > 0 ? String(n) : '';
        var hint = $('upEnjKalipAdediHint');
        if (hint) {
            hint.textContent = n > 0
                ? (n + ' istasyon seçildi = ' + n + ' kalıp')
                : 'Seçilen istasyon sayısından otomatik hesaplanır.';
        }
        // PHASE_7E: Fiziksel kalıp adedi >= istasyon sayısı kontrolü
        enjCheckFizikselKalipLimit(n);
        enjUpdateToplamGozHint();
        // PHASE_7N3: İstasyon değişince özet kartı güncelle (tur başı çift dinamik)
        if (state.enj.libraryKalipMeta) {
            enjRenderLibrarySummary(state.enj.libraryKalipMeta);
        }
    }

    /** PHASE_7O3A_R1: DOGRULANMALI — kesin dolu/boş değil; son bilinen kalıp gösterilir. */
    function enjUnknownStatusUiLabel() {
        return 'GÜNCEL DURUM BİLİNMİYOR';
    }

    function enjUnknownStatusCardShort(n) {
        return '⚠ ' + n + ' istasyon · güncel durum bilinmiyor';
    }

    function enjUnknownStatusCentralMsg(stationNums, adv) {
        var stations = (adv && adv.stations) || [];
        if (stations.length === 1 && stations[0].kalip_kod) {
            var st = stations[0];
            var dt = st.last_known_date || (st.last_record ? String(st.last_record).split(' ')[0] : '—');
            return '⚠ İST' + st.istasyon_no + ' için güncel durum bilinmiyor · Son bilinen kalıp: ' +
                st.kalip_kod + ' · ' + dt;
        }
        var n = stationNums.length || stations.length;
        if (n <= 0) return '';
        return '⚠ ' + n + ' istasyonun güncel durumu bilinmiyor — bağlamadan önce kontrol edin.';
    }

    function enjVardiyaFromCell(cell) {
        if (!cell) return null;
        if (cell.vardiya) return String(cell.vardiya).toLowerCase();
        if (!cell.win_bas) return null;
        var h = parseInt(String(cell.win_bas).substring(11, 13), 10);
        if (isNaN(h)) return null;
        return (h >= 7 && h < 17) ? 'gunduz' : 'gece';
    }

    function enjSyncCalismaModuForCellVardiya(vd) {
        if (!vd) return;
        var e = state.enj;
        var want = vd === 'gunduz' ? 'GUNDUZ' : 'GECE';
        if (e.calismaModu === 'GUNDUZ_GECE') return;
        if (e.calismaModu === want) return;
        e.calismaModu = want;
        document.querySelectorAll('.up-enj-calisma-tab').forEach(function (b) {
            b.classList.toggle('selected', b.dataset.val === want);
            b.setAttribute('aria-selected', b.dataset.val === want ? 'true' : 'false');
        });
        if ($('upEnjCalismaModu')) $('upEnjCalismaModu').value = want;
        if (typeof enjRenderKapasitePanel === 'function') enjRenderKapasitePanel();
    }

    function enjRecalcPlanningTimeline(reason) {
        var e = state.enj;
        if (!e.baslangicManuel) {
            e.baslangic = null;
            e.takvimSecim = null;
            if ($('upEnjBas')) $('upEnjBas').value = '';
            if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        }
        e.hesapOk = false;
        e.draftPreview = null;
        enjHesapGizle();
        enjFetchIlkUygun(false);
        if (e.takvimMakineId) enjLoadTakvimData();
        enjEvaluateShiftStartBoundary();
        enjUpdateHesapBtn();
        var hsOpen = e.haftaSonu === 'EVET';
        var msgs = {
            hafta_sonu: hsOpen ? 'Hafta sonu mesaisi açık — takvim güncellendi.' : 'Hafta sonu kapalı — süre hafta sonunu atlar.',
            hafta_sonu_tab: hsOpen ? 'Hafta sonu mesaisi açık — takvim güncellendi.' : 'Hafta sonu kapalı — süre hafta sonunu atlar.',
            calisma_modu: 'Vardiya seçimi değişti — kapasite ve takvim güncellendi.',
            calisma_tab: 'Vardiya seçimi değişti — kapasite ve takvim güncellendi.',
            shift: 'Vardiya seçimi değişti — kapasite ve takvim güncellendi.',
        };
        e._timelineRecalcMsg = msgs[reason] || msgs.shift;
        enjUpdateCentralStatus();
    }

    function enjCaptureFormSnapshot() {
        var e = state.enj;
        return {
            makineId: e.makineId,
            makineKod: e.makineKod,
            slot: e.slot,
            baslangic: e.baslangic,
            istasyonlar: (e.istasyonlar || []).slice(),
            kalipId: e.kalipId,
            kalipKod: e.kalipKod,
            kalipAdedi: e.kalipAdedi,
            libraryUuid: e.libraryUuid,
        };
    }

    function enjRestoreFormSnapshot(snap) {
        if (!snap) return;
        var e = state.enj;
        var machines = e.gridData || [];
        e.makineId = snap.makineId;
        e.makineKod = snap.makineKod;
        e.slot = snap.slot;
        e.baslangic = snap.baslangic;
        e.istasyonlar = (snap.istasyonlar || []).slice();
        e.kalipId = snap.kalipId;
        e.kalipKod = snap.kalipKod;
        e.kalipAdedi = snap.kalipAdedi;
        e.libraryUuid = snap.libraryUuid;
        if ($('upEnjSlotA')) $('upEnjSlotA').classList.toggle('selected', snap.slot === 'A');
        if ($('upEnjSlotB')) $('upEnjSlotB').classList.toggle('selected', snap.slot === 'B');
        if ($('upEnjBas')) {
            $('upEnjBas').value = snap.baslangic ? enjApiDtToLocal(snap.baslangic) : '';
            $('upEnjBas').disabled = !snap.makineId;
        }
        var m = machines.find(function (x) { return (x.makine_id || x.id) === snap.makineId; });
        enjRenderMakineCards(machines);
        if (m) enjRenderIstasyonGrid(m);
        enjSyncKalipAdediFromStations();
        enjUpdateStep2Ui();
    }

    /** PHASE_7E/7N4: Fiziksel kalıp limiti — yalnız merkezi durum alanında gösterilir. */
    function enjCheckFizikselKalipLimit(istasyonSayisi) {
        var meta = state.enj.libraryKalipMeta;
        var physTotal = meta && meta.physical_mold_total != null ? meta.physical_mold_total : null;
        state.enj._fizikselKalipAsimi = false;
        if (physTotal !== null && istasyonSayisi > 0 && istasyonSayisi > physTotal) {
            state.enj._fizikselKalipAsimi = true;
        }
    }

    function enjFmtIstasyonList(nums) {
        var arr = (nums || []).slice().sort(function (a, b) { return a - b; });
        if (!arr.length) return '';
        if (arr.length === 1) return 'İST' + arr[0];
        if (arr.length === 2) return 'İST' + arr[0] + ' ve İST' + arr[1];
        return 'İST' + arr.slice(0, -1).join(', İST') + ' ve İST' + arr[arr.length - 1];
    }

    /** PHASE_7O1E / 7O3E: Durum üst başlıkta; alt alan minimize */
    function enjUpdateCentralStatus() {
        var wrap = $('upStep2CentralStatus');
        if (wrap) wrap.style.display = 'none';
        var e = state.enj;
        enjSyncInputsFromDom();
        var statusMsg = '';
        var nextOverride = '';

        if (e._timelineRecalcMsg) {
            statusMsg = e._timelineRecalcMsg;
            e._timelineRecalcMsg = null;
        }

        if (enjKalanSifirBlocked()) {
            enjUpdateHeadCompactSummary(
                'Bu siparişin planlanacak kalan miktarı yok.',
                'Sıradaki: Mevcut planı inceleyin');
            return;
        }

        if (typeof enjCapacityBlockingMessage === 'function') {
            var capBlock = enjCapacityBlockingMessage();
            if (capBlock && !e.draftPreview) {
                enjUpdateHeadCompactSummary(capBlock, 'Sıradaki: Kapasiteyi onaylayın');
                return;
            }
        }

        if (e._istasyonCleanupMsg) {
            statusMsg = e._istasyonCleanupMsg;
            e._istasyonCleanupMsg = null;
        }

        if (e._fizikselKalipAsimi || e._fizikselKalipLimitAttempt) {
            var pt = enjGetFizikselKalipLimit();
            if (pt == null && e.libraryKalipMeta) {
                pt = e.libraryKalipMeta.physical_mold_total;
            }
            enjUpdateHeadCompactSummary(
                pt + ' kalıp için en fazla ' + pt + ' istasyon kullanılabilir.',
                'Sıradaki: İstasyon sayısını düşürün');
            return;
        }

        var adv = e.physicalAdvisory || {};
        var advN = adv.needs_confirmation_count || e.dogrulanmaliCount || 0;
        if (advN > 0) {
            var nums = adv.needs_confirmation_stations || [];
            if (!nums.length) {
                Object.keys(e.istasyonPlanDurum || {}).forEach(function (k) {
                    var row = e.istasyonPlanDurum[k];
                    if (row && row.durum === 'DOGRULANMALI') nums.push(parseInt(k, 10));
                });
            }
            var advMsg = enjUnknownStatusCentralMsg(nums, adv);
            if (advMsg) statusMsg = statusMsg ? (statusMsg + ' ' + advMsg) : advMsg;
        }

        enjUpdateHeadCompactSummary(statusMsg || null, nextOverride || null);
        enjUpdateTakvimAccSummary();
    }

    function enjUpdateTakvimHesapBtn() {
        var btn = $('upTakvimHesapUygula');
        if (!btn) return;
        btn.disabled = !enjCanHesapla();
    }

    function enjHasBaslangic() {
        var e = state.enj;
        if (e.baslangic) return true;
        var inp = $('upEnjBas');
        return !!(inp && inp.value);
    }

    function enjAvailabilityCapture(seq) {
        return {
            seq: seq,
            sipNo: state.seciliCreateData && state.seciliCreateData.sip_no,
            makineId: state.enj.makineId,
            slot: state.enj.slot,
            baslangic: state.enj.baslangic,
        };
    }

    function enjAvailabilityStillValid(capture) {
        var e = state.enj;
        return capture.seq === e.istasyonAvailabilitySeq &&
            capture.sipNo === (state.seciliCreateData && state.seciliCreateData.sip_no) &&
            capture.makineId === e.makineId &&
            capture.slot === e.slot &&
            capture.baslangic === e.baslangic;
    }

    function enjUpdateStep2SectionStates() {
        var e = state.enj;
        var hasBas = enjHasBaslangic();
        var kalipOk = enjKalipSecili();
        var fizOk = enjFizikselKalipAdediGecerli();
        var basEl = $('upEnjBas');
        if (basEl) basEl.disabled = !(e.makineId && e.slot);
        var gateHint = $('upEnjIstasyonGateHint');
        if (gateHint) {
            gateHint.style.display = (e.makineId && e.slot && hasBas && !kalipOk) ? '' : 'none';
        }
        var istasyonOpen = !!(e.makineId && e.slot && hasBas && kalipOk && fizOk);
        var sections = {
            upStep2SecSlot: !!e.makineId,
            upStep2SecTarih: !!(e.makineId && e.slot),
            upStep2SecKalip: !!(e.makineId && e.slot && hasBas),
            upStep2SecKalipSecili: kalipOk,
            upStep2SecFizikselKalip: kalipOk && fizOk,
            upStep2SecIstasyon: istasyonOpen,
            upStep2SecTakvimPlanla: !!(e.makineId && e.slot && hasBas && kalipOk && e.istasyonlar.length),
            upStep2SecMiktar: !!(e.makineId && e.istasyonlar.length && kalipOk),
            upStep2SecHesap: !!e.makineId,
        };
        Object.keys(sections).forEach(function (id) {
            var sec = $(id);
            if (sec) sec.classList.toggle('up-step2-locked', !sections[id]);
        });
        var planlaBtn = $('upEnjTakvimPlanlaBtn');
        if (planlaBtn) {
            planlaBtn.disabled = !sections.upStep2SecTakvimPlanla;
        }
        enjUpdateFizikselKalipDisplay();
        enjUpdateKalipSeciliCards();
    }

    function enjUpdateIlkUygunDisplay() {
        var e = state.enj;
        var lbl = $('upEnjIlkUygunVal');
        var btn = $('upEnjBasIlkUygunBtn');
        var iu = e.makineId ? e.ilkUygunMap[e.makineId] : null;
        var disp = (iu && iu.ilk_uygun_gosterim) || (iu && iu.ilk_uygun && enjFmtDtApi(iu.ilk_uygun)) || '—';
        if (lbl) lbl.textContent = disp;
        if (btn) {
            btn.disabled = !(iu && iu.ilk_uygun && e.makineId && e.slot);
        }
    }

    function enjUpdateWizardSiparisStrip() {
        var strip = $('upWizardSiparisStrip');
        if (!strip) return;
        var o = state.seciliCreateData;
        if (!o || state.createStep === 1) {
            strip.style.display = 'none';
            return;
        }
        strip.style.display = 'block';
        strip.innerHTML = '<strong>' + esc(o.model_kod) + '</strong> · ' + esc(o.renk) +
            ' · Sipariş ' + esc(o.sip_no) + ' · ' + fmtN(o.miktar) + ' ' + esc(o.birim || 'CIFT');
        // V31: sol kolon SEÇİLEN ÜRÜN kartı
        var card = $('upSelectedProductCard');
        var empty = $('upSelectedProductEmpty');
        var row = $('upSelectedModelRow');
        if (!card && !row) return;
        if (!o || state.createStep === 1) {
            if (card) card.style.display = 'none';
            if (empty) empty.style.display = '';
            if (row) row.innerHTML = '';
            return;
        }
        if (card) card.style.display = '';
        if (empty) empty.style.display = 'none';
        if (!row) return;
        var modelLine = esc(o.model_kod || '');
        if (o.renk) modelLine += ' · ' + esc(o.renk);
        var birimLbl = (o.birim || 'çift').toLowerCase();
        var sipLine = 'Sipariş ' + esc(o.sip_no);
        if (o.miktar != null && !isNaN(o.miktar)) {
            sipLine += ' · ' + fmtN(o.miktar) + ' ' + esc(birimLbl);
        }
        var html = '<div class="up-selected-product-model">' + modelLine + '</div>' +
            '<div class="up-selected-product-meta">' + sipLine + '</div>';
        var emirTxt = '';
        if (o.emir_no && o.emir_no !== '-' && String(o.emir_no).trim()) {
            emirTxt = String(o.emir_no).trim();
        } else if (o.emir_nos && o.emir_nos.length === 1) {
            emirTxt = String(o.emir_nos[0]);
        }
        if (emirTxt) {
            html += '<div class="up-selected-product-emir">Emir ' + esc(emirTxt) + '</div>';
        }
        row.innerHTML = html;
        if (card) card.title = (o.model_kod || '') + ' · Sipariş ' + (o.sip_no || '');
    }

    function enjUpdateStep2Ui() {
        enjUpdateStep2SectionStates();
        enjUpdateIlkUygunDisplay();
        enjUpdateMiktarOzet();
        enjUpdateKurulumOzet();
        enjUpdateWizardSiparisStrip();
        enjRenderHesapRequirements();
        enjUpdateTarihDurumEtiketi();
        enjUpdateCentralStatus();
        enjUpdateTakvimHesapBtn();
        enjUpdateTakvimDraftBar();
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
        state.step3.onerilenBit = null;
        state.step3.manuelDegisti = false;
        state.step3.oncekiPlanlar = [];
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
            fetchQuantitySummary(function () { enjUpdateStep2Ui(); });
        }
        wizardUpdateNav();
    }

    function wizardShowStep(n) {
        state.createStep = n;
        clearPlanErrors();
        [1, 2, 3].forEach(function (s) {
            var p = $('upStep' + s);
            if (p) p.style.display = (s === n) ? '' : 'none';
            var st = document.querySelector('.up-wizard-step[data-step="' + s + '"]');
            if (st) st.classList.toggle('active', s === n);
        });
        var scroll = document.querySelector('.up-create-scroll');
        if (scroll) {
            if (n === 2) scroll.classList.add('step2-active');
            else scroll.classList.remove('step2-active');
            if (n === 3) scroll.classList.add('step3-active');
            else scroll.classList.remove('step3-active');
        }
        if (n === 2) {
            fetchQuantitySummary(function () { enjUpdateStep2Ui(); });
            /* Makine seçilmemişse placeholder göster */
            if (!state.enj.makineId) enjRenderIstasyonPlaceholder();
        }
        enjUpdateWizardSiparisStrip();
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
        step3RenderOneriKural(null);
        step3RenderManuelBadge(false);
        step3RenderOncekiPlanlar([]);
        step3FetchMiktarOzet();

        var rez = state.enj.reservation || {};
        var enjBas = dateOnlyFromApi(rez.baslangic || state.enj.baslangic);
        var enjBit = dateOnlyFromApi(rez.bitis || (state.enj.motorResult && state.enj.motorResult.tahmini_bitis));

        state.step3.basMode = null;
        state.step3.manuelDegisti = false;
        // Bitiş için güvenilir üretim süresi kaynağı yok; alan manuel kalır.
        state.step3.onerilenBit = null;

        // Enjeksiyon yoksa donem_aralik'tan üretilen tarihleri kullan
        if (!enjBas && !enjBit) {
            var donem = ($('upFormDonem') && $('upFormDonem').value) || 'bu_hafta';
            var aralik = donemAralikJs(donem);
            if ($('upFormBit') && !$('upFormBit').value) {
                $('upFormBit').value = aralik.bit;
                $('upFormBit').min = aralik.bas;
            }
            step3ShowBitHint(aralik.bas);
            var fakeSecenekler = [{ tarih: aralik.bas, dolu: false, oneri_donem: donem }];
            renderStep3BasSecenekleri(fakeSecenekler, aralik.bas);
            step3FetchOncekiPlanlar(aralik.bas, aralik.bit);
            return;
        }

        // Başlangıç önerisi: enjeksiyon bitiş tarihi (backend kuralıyla uyumlu: >=)
        // Bitiş: güvenilir kaynak yok; alan min=enjBit ile manuel kalır
        if (enjBit) {
            if ($('upFormBit')) {
                $('upFormBit').min = enjBit;
                // Daha önce doldurulmuşsa ve min'den küçükse temizle
                if ($('upFormBit').value && $('upFormBit').value < enjBit) {
                    $('upFormBit').value = '';
                }
            }
            step3ShowBitHint(enjBit);
        }

        // Öneri kuralını göster
        step3RenderOneriKural('Başlangıç en erken enjeksiyon bitiş tarihi: ' + fmtDateTr(enjBit));

        fetchStep3OnCheck([enjBit].filter(Boolean), function (secenekler) {
            renderStep3BasSecenekleri(secenekler, enjBit);
            var tarihBit = $('upFormBit') ? $('upFormBit').value : '';
            step3FetchOncekiPlanlar(enjBit, tarihBit);
        });
    }

    function renderStep3BasSecenekleri(secenekler, enjBit) {
        var el = $('upStep3BasSecenekleri');
        if (!el) return;
        state.step3.secenekler = secenekler;
        el.innerHTML = '';
        // Tek seçenek: enjeksiyon bitiş tarihi (backend >= kuralıyla uyumlu)
        var opts = [
            { mode: 'enj_bit', key: enjBit, label: enjBit ? 'Enjeksiyon bitiş tarihi (en erken başlangıç)' : 'Dönem başlangıcı' },
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
        if (customInp) {
            // Min tarih her seferinde güncelle (enjBit değişebilir)
            if (enjBit) customInp.min = enjBit;
        }
        if (customInp && !customInp._bound) {
            customInp._bound = true;
            customInp.addEventListener('change', function () {
                state.step3.basMode = 'custom';
                el.querySelectorAll('.up-step3-radio').forEach(function (r) {
                    r.classList.remove('selected');
                });
                // Manuel tarih enjBit'ten önce olamaz
                var enjBitMin = customInp.min || '';
                if (enjBitMin && customInp.value < enjBitMin) {
                    showStep3Uyari('Başlangıç tarihi enjeksiyon bitişinden (' + fmtDateTr(enjBitMin) + ') önce olamaz');
                    state.step3.saveBlocked = true;
                    wizardUpdateNav();
                    return;
                }
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

    function step3RenderOneriKural(msg) {
        var el = $('upStep3OneriKural');
        if (!el) return;
        if (msg) { el.textContent = msg; el.style.display = 'block'; }
        else { el.style.display = 'none'; }
    }

    function step3ShowBitHint(minIsoDate) {
        var el = $('upStep3BitOneri');
        if (!el) return;
        if (minIsoDate) {
            el.textContent = 'En erken bitiş: ' + fmtDateTr(minIsoDate) + ' (başlangıç tarihinden önce olamaz)';
            el.style.display = '';
        } else {
            el.style.display = 'none';
        }
        // upFormBit min değerini güncelle
        var bitEl = $('upFormBit');
        if (bitEl && minIsoDate) bitEl.min = minIsoDate;
    }

    function step3RenderManuelBadge(show) {
        var el = $('upStep3ManuelBadge');
        if (!el) return;
        el.style.display = show ? '' : 'none';
        var btn = $('upStep3OneriDon');
        if (btn) btn.style.display = show ? '' : 'none';
    }

    function step3FetchOncekiPlanlar(tarihBas, tarihBit) {
        var wrap = $('upStep3OncekiPlanWrap');
        if (!wrap) return;
        var o = state.seciliCreateData;
        if (!o) { step3RenderOncekiPlanlar([]); return; }
        var loading = $('upStep3OncekiLoading');
        if (loading) loading.style.display = '';
        var list = $('upStep3OncekiPlanList');
        if (list) list.innerHTML = '';
        fetch('/planlama/uretim-plan/api/plan/onceki?' + new URLSearchParams({
            sip_no: o.sip_no || '',
            sip_harinx: o.sip_harinx || 0,
            mamul_skod: o.model_kod || o.mamul_skod || '',
            rkod: o.rkod || 0,
            tarih_bas: tarihBas || '',
            tarih_bit: tarihBit || '',
        }), { credentials: 'include' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (loading) loading.style.display = 'none';
            state.step3.oncekiPlanlar = (d.ok && d.planlar) ? d.planlar : [];
            step3RenderOncekiPlanlar(state.step3.oncekiPlanlar, tarihBas, tarihBit);
        })
        .catch(function () {
            if (loading) loading.style.display = 'none';
            state.step3.oncekiPlanlar = [];
            step3RenderOncekiPlanlar([]);
        });
    }

    function step3RenderOncekiPlanlar(planlar, tarihBas, tarihBit) {
        var listEl = $('upStep3OncekiPlanList');
        var cakismaEl = $('upStep3CakismaUyari');
        if (!listEl) return;
        listEl.innerHTML = '';
        if (!planlar || !planlar.length) {
            listEl.innerHTML = '<div class="up-step3-onceki-none">Bu dönemde önceki aktif plan yok.</div>';
            if (cakismaEl) cakismaEl.style.display = 'none';
            return;
        }
        var cakismaVar = false;
        planlar.forEach(function (p) {
            var pb = (p.plan_baslangic || '').slice(0, 10);
            var pe = (p.plan_bitis || '').slice(0, 10);
            var overlaps = tarihBas && tarihBit && pb && pe &&
                !(pe < tarihBas || pb > tarihBit);
            if (overlaps) cakismaVar = true;
            var item = document.createElement('div');
            item.className = 'up-step3-onceki-item' + (overlaps ? ' conflict' : '');
            var durumClass = (p.aktif == 1 || p.aktif === true) ? ' aktif' : '';
            var durumLabel = (p.aktif == 1 || p.aktif === true) ? 'AKTİF' : 'PASİF';
            item.innerHTML =
                '<div class="up-step3-onceki-donem">' + esc(p.plan_donemi || '—') + '</div>' +
                '<div class="up-step3-onceki-tarih">' + esc(pb || '—') + ' → ' + esc(pe || '—') + '</div>' +
                '<div class="up-step3-onceki-durum' + durumClass + '">' + esc(durumLabel) + '</div>';
            listEl.appendChild(item);
        });
        if (cakismaEl) {
            if (cakismaVar) {
                cakismaEl.textContent = 'Bu dönemde mevcut aktif planla çakışma var! Tarihleri kontrol edin.';
                cakismaEl.style.display = '';
            } else {
                cakismaEl.style.display = 'none';
            }
        }
    }

    function step3FetchMiktarOzet() {
        var wrap = $('upStep3MiktarOzet');
        if (!wrap) return;
        var o = state.seciliCreateData;
        if (!o) return;
        fetch('/planlama/uretim-plan/api/plan/kalem-miktar-ozet?' + new URLSearchParams({
            sip_no: o.sip_no || '',
            sip_harinx: o.sip_harinx || 0,
            mamul_skod: o.model_kod || o.mamul_skod || '',
            rkod: o.rkod || 0,
        }), { credentials: 'include' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (!d.ok) return;
            var rez = state.enj.reservation;
            var buPlan = rez ? (rez.planCift || 0) : 0;
            var kalan = (d.kalan_miktar || 0) - buPlan;
            var ozetEl = function (id, val) {
                var el = $(id);
                if (el) el.textContent = fmtN(val) + ' çift';
            };
            ozetEl('upStep3OzetSipToplam', d.siparis_toplam);
            ozetEl('upStep3OzetOnceden', d.planlanan_miktar);
            ozetEl('upStep3OzetBuPlan', buPlan);
            ozetEl('upStep3OzetKalan', kalan >= 0 ? kalan : 0);
            wrap.style.display = '';
        })
        .catch(function () {});
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
        var tarihBit = $('upFormBit') ? $('upFormBit').value : '';
        step3FetchOncekiPlanlar(isoDate, tarihBit);
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
        // Bitiş uyarısını da göster
        var bitUyariEl = $('upStep3BitUyari');
        if (bitUyariEl) {
            if (uyari) { bitUyariEl.textContent = uyari; bitUyariEl.style.display = ''; }
            else { bitUyariEl.style.display = 'none'; }
        }
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
        if (wrap) wrap.style.display = 'none';
        // Vardiya saatlerini bant olarak göster
        var bantEl = $('upEnjVardiyaSaatBant');
        if (bantEl) {
            if (cm === 'GUNDUZ') {
                bantEl.textContent = 'Gündüz 07:00–17:00 · 10 saat/vardiya';
            } else if (cm === 'GECE') {
                bantEl.textContent = 'Gece 17:00–07:00 · 14 saat/vardiya';
            } else {
                bantEl.innerHTML = 'Gündüz 07:00–17:00 · 10 saat/vardiya<br>Gece 17:00–07:00 · 14 saat/vardiya';
            }
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
        var e = state.enj;
        if (typeof enjCapacityConfirmedOk === 'function' && enjCapacityConfirmedOk()) {
            if (e.calismaModu !== 'GECE' && e.capacityConfirmedTurGunduz > 0) {
                e.manualRefGunduz = e.capacityConfirmedTurGunduz;
                if ($('upEnjManualGunduz')) $('upEnjManualGunduz').value = String(e.capacityConfirmedTurGunduz);
            }
            if (e.calismaModu !== 'GUNDUZ' && e.capacityConfirmedTurGece > 0) {
                e.manualRefGece = e.capacityConfirmedTurGece;
                if ($('upEnjManualGece')) $('upEnjManualGece').value = String(e.capacityConfirmedTurGece);
            }
        } else {
            e.manualRefGunduz = $('upEnjManualGunduz') && $('upEnjManualGunduz').value
                ? parseFloat($('upEnjManualGunduz').value) : null;
            e.manualRefGece = $('upEnjManualGece') && $('upEnjManualGece').value
                ? parseFloat($('upEnjManualGece').value) : null;
        }
        e.referenceMode = 'MANUAL';
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

        var srcEl = $('upEnjRefKaynakDurum');
        if (srcEl) srcEl.style.display = 'none';
    }

    function enjSyncHsVardiyaFromCalisma(force) {
        var e = state.enj;
        if (e.haftaSonu !== 'EVET') return;
        var cm = e.calismaModu || 'GUNDUZ_GECE';
        if (force || !e.hsVardiya) e.hsVardiya = cm;
        document.querySelectorAll('.up-enj-hs-vardiya-tab').forEach(function (b) {
            b.classList.toggle('selected', b.dataset.val === e.hsVardiya);
        });
        if ($('upEnjHsVardiya')) $('upEnjHsVardiya').value = e.hsVardiya;
    }

    function wizardUpdateNav() {
        var back = $('upWizardBackBtn');
        var next = $('upWizardNextBtn');
        var save = $('upPlanaEkleBtn');
        if (!back || !next || !save) return;
        back.style.display = state.createStep > 1 ? '' : 'none';
        next.style.display = state.createStep < 3 ? '' : 'none';
        save.style.display = state.createStep === 3 ? '' : 'none';
        var qs = state.enj.quantitySummary;
        var legacyBlockNav = (qs && qs.quantity_calculable === false);
        var kalanBlockNav = enjKalanSifirBlocked();
        if (state.createStep === 1) {
            next.disabled = !state.seciliCreate;
        } else if (state.createStep === 2) {
            next.disabled = legacyBlockNav || kalanBlockNav || (state.requiresEnj && !state.enj.hesapOk);
        } else {
            save.disabled = legacyBlockNav || (state.requiresEnj && !state.enj.hesapOk);
        }
    }

    // ─── ENJEKSİYON PLAN HESABI (Faz 2C.2) ─────────────────────────────────

    function enjWeekdayFromLocalParts(y, mo, d) {
        var jsDay = new Date(y, mo - 1, d).getDay();
        return jsDay === 0 ? 6 : jsDay - 1;
    }

    function enjParseLocalDatetimeLocal(val) {
        if (!val) return null;
        var m = String(val).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
        if (!m) return null;
        return {
            y: parseInt(m[1], 10),
            mo: parseInt(m[2], 10),
            d: parseInt(m[3], 10),
            h: parseInt(m[4], 10),
            mi: parseInt(m[5], 10),
        };
    }

    function enjTarihDurumEtiketiMetni(local, haftaSonu) {
        if (!local) return '';
        var wd = enjWeekdayFromLocalParts(local.y, local.mo, local.d);
        var mins = local.h * 60 + local.mi;
        haftaSonu = (haftaSonu || 'HAYIR').toUpperCase();

        if (haftaSonu === 'EVET') {
            if (wd >= 5) return 'Hafta sonu çalışma açık';
            return 'Standart üretim günü';
        }

        if (wd === 6) return 'Hafta sonu kapalı; yeni vardiya başlatılamaz';
        if (wd === 5) {
            if (mins < 7 * 60) {
                return 'Cuma gece vardiyasının devam aralığıdır; yeni vardiya başlangıcı değildir';
            }
            return 'Hafta sonu kapalı; yeni vardiya başlatılamaz';
        }
        if (wd === 4 && local.h === 17 && local.mi === 0) {
            return 'Gece vardiyası Cumartesi 07:00\u2019a kadar devam edebilir';
        }
        if (wd >= 0 && wd <= 4) return 'Standart üretim günü';
        return 'Standart üretim günü';
    }

    function enjUpdateTarihDurumEtiketi() {
        var el = $('upEnjBasDurumEtiketi');
        if (!el) return;
        var inp = $('upEnjBas');
        var val = inp && inp.value;
        if (!val) {
            el.textContent = '';
            el.style.display = 'none';
            el.setAttribute('aria-hidden', 'true');
            return;
        }
        var local = enjParseLocalDatetimeLocal(val);
        if (!local) {
            el.textContent = '';
            el.style.display = 'none';
            el.setAttribute('aria-hidden', 'true');
            return;
        }
        var metin = enjTarihDurumEtiketiMetni(local, state.enj.haftaSonu);
        el.textContent = metin;
        el.style.display = metin ? '' : 'none';
        el.setAttribute('aria-hidden', metin ? 'false' : 'true');
    }

    function enjShiftStartOverrideRequiredLocal(basStr) {
        if (!basStr) return false;
        var m = String(basStr).match(/(\d{2}):(\d{2})/);
        if (!m) return false;
        var hm = m[1] + ':' + m[2];
        return hm !== '07:00' && hm !== '17:00';
    }

    function enjFormatSuggestedShiftBoundary(basStr) {
        if (!basStr) return '—';
        var dateM = String(basStr).match(/(\d{4}-\d{2}-\d{2})/);
        var date = dateM ? dateM[1] : '';
        var hmM = String(basStr).match(/(\d{2}):(\d{2})/);
        if (!hmM) return date + ' 07:00';
        var mins = parseInt(hmM[1], 10) * 60 + parseInt(hmM[2], 10);
        if (mins < 7 * 60) return date + ' 07:00';
        if (mins < 17 * 60) return date + ' 17:00';
        return date + ' 17:00';
    }

    function enjShiftStartApprovalContext() {
        var e = state.enj;
        return [
            e.makineId, e.slot,
            (e.istasyonlar || []).join(','),
            e.calismaModu, e.haftaSonu, e.hsVardiya || '',
            e.baslangic || '',
        ].join('|');
    }

    function enjClearShiftStartApproval() {
        var e = state.enj;
        e.shiftStartOverrideConfirmed = false;
        e.shiftStartOverrideTime = null;
        e.shiftStartApprovalContext = null;
        var cb = $('upEnjShiftStartApprove');
        if (cb) cb.checked = false;
    }

    function enjRenderShiftStartOverrideUi() {
        var wrap = $('upEnjShiftStartWarn');
        if (!wrap) return;
        var e = state.enj;
        if (!e.shiftStartOverrideRequired || !e.baslangic) {
            wrap.style.display = 'none';
            wrap.innerHTML = '';
            return;
        }
        wrap.style.display = '';
        var secilen = enjFmtDtApi(e.baslangic);
        var oneri = e.shiftStartSuggestedBoundary || enjFormatSuggestedShiftBoundary(e.baslangic);
        wrap.innerHTML =
            '⚠ Seçilen başlangıç <strong>' + esc(secilen) + '</strong> standart vardiya saati (07:00 / 17:00) değil. ' +
            'Önerilen vardiya başlangıcı: <strong>' + esc(oneri) + '</strong>.' +
            '<label style="display:block;margin-top:8px;font-weight:600;">' +
            '<input type="checkbox" id="upEnjShiftStartApprove"' +
            (e.shiftStartOverrideConfirmed ? ' checked' : '') +
            '> Bu saatle devam etmeyi onaylıyorum</label>';
        var cb = $('upEnjShiftStartApprove');
        if (cb) {
            cb.onchange = function () {
                if (cb.checked) {
                    e.shiftStartOverrideConfirmed = true;
                    e.shiftStartOverrideTime = e.baslangic;
                    e.shiftStartApprovalContext = enjShiftStartApprovalContext();
                } else {
                    enjClearShiftStartApproval();
                }
                enjHesapGizle();
                enjUpdateHesapBtn();
            };
        }
    }

    function enjEvaluateShiftStartBoundary() {
        var e = state.enj;
        enjSyncInputsFromDom();
        var required = enjShiftStartOverrideRequiredLocal(e.baslangic);
        var ctx = enjShiftStartApprovalContext();
        if (e.shiftStartApprovalContext && e.shiftStartApprovalContext !== ctx) {
            enjClearShiftStartApproval();
        }
        e.shiftStartOverrideRequired = required;
        if (!required) {
            enjClearShiftStartApproval();
        } else {
            e.shiftStartSuggestedBoundary = enjFormatSuggestedShiftBoundary(e.baslangic);
        }
        enjRenderShiftStartOverrideUi();
        enjUpdateTarihDurumEtiketi();
    }

    function enjReset() {
        var e = state.enj;
        e.makineId = null; e.makineKod = null; e.istasyonlar = []; e.slot = null;
        e.kalipId = null; e.kalipKod = null; e.kalipAdedi = null; e.gozPerKalip = 1;
        e.kalipMode = 'liste'; e.kalipBasiCift = null;
        e.turCift = null; e.baslangic = null; e.baslangicOneri = null; e.baslangicManuel = false;
        e.shiftStartOverrideRequired = false;
        e.shiftStartOverrideConfirmed = false;
        e.shiftStartOverrideTime = null;
        e.shiftStartSuggestedBoundary = null;
        e.shiftStartApprovalContext = null;
        e.bitis = null; e.planCift = null;
        e.motorResult = null; e.hesapOk = false; e.gridData = null;
        e.calismaModu = 'GUNDUZ_GECE'; e.haftaSonu = 'HAYIR'; e.hsVardiya = null;
        e.ilkUygunMap = {};
        e.planOzetMap = {};
        e.slotOzetMap = {};
        e.baseFirstAvailableMap = {};
        e.slotOzetSeq = 0;
        e.istasyonAvailabilitySeq = 0;
        e.makineDetayCache = {};
        e.quantitySummary = null;
        e.istasyonPlanDurum = {};
        e.reservation = null;
        e.pendingConflict = null;
        e.referenceMode = 'MANUAL'; e.manualRefGunduz = null; e.manualRefGece = null;
        e.autoRefGunduz = null; e.autoRefGece = null;
        e._sonHaftaVeri = null;
        enjHesapGizle();
        if ($('upEnjMakineCards')) $('upEnjMakineCards').innerHTML = '';
        enjRenderIstasyonPlaceholder();
        _enjKalipListeTemizle();   /* sipariş bağlamı değişince eski model kalıplarını temizle */
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
        if ($('upEnjShiftStartWarn')) { $('upEnjShiftStartWarn').style.display = 'none'; $('upEnjShiftStartWarn').innerHTML = ''; }
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
        enjUpdateTarihDurumEtiketi();
    }

    function enjSetHesapDetayAcik(acik) {
        var e = state.enj;
        e.hesapDetayAcik = !!acik;
        var panel = $('upEnjHesapDetayPanel');
        var toggle = $('upEnjHesapDetayToggle');
        if (!panel || !toggle) return;
        if (acik) {
            panel.removeAttribute('hidden');
        } else {
            panel.setAttribute('hidden', '');
        }
        toggle.setAttribute('aria-expanded', acik ? 'true' : 'false');
        toggle.textContent = acik ? 'Hesap detayını gizle' : 'Hesap detayını göster';
    }

    function enjHesapGizle() {
        if ($('upEnjHesapOzet')) $('upEnjHesapOzet').style.display = 'none';
        enjSetHesapDetayAcik(false);
        if ($('upEnjHesapDetayToggle')) $('upEnjHesapDetayToggle').style.display = 'none';
        if ($('upEnjVardiyaListe')) $('upEnjVardiyaListe').innerHTML = '';
        if ($('upEnjVardiyaBreakdown')) $('upEnjVardiyaBreakdown').style.display = 'none';
        if ($('upEnjWarnings')) {
            $('upEnjWarnings').textContent = '';
            $('upEnjWarnings').style.display = 'none';
        }
        state.enj.hesapOk = false;
        state.enj.motorResult = null;
        state.enj.reservation = null;
        wizardUpdateNav();
        enjUpdateKurulumOzet();
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

    function enjSlotOzetParams() {
        var e = state.enj;
        var q = 'calisma_modu=' + encodeURIComponent(e.calismaModu || 'GUNDUZ_GECE') +
            '&hafta_sonu_calisma=' + encodeURIComponent(e.haftaSonu || 'HAYIR');
        if (e.haftaSonu === 'EVET' && e.hsVardiya) {
            q += '&hafta_sonu_vardiya=' + encodeURIComponent(e.hsVardiya);
        }
        if (e.baslangic) {
            q += '&plan_baslangic=' + encodeURIComponent(e.baslangic);
            q += '&secim_baslangic=' + encodeURIComponent(e.baslangic);
        }
        var bit = (e.motorResult && e.motorResult.tahmini_bitis) || e.bitis;
        if (bit) {
            q += '&secim_bitis=' + encodeURIComponent(bit);
        }
        return q;
    }

    function enjMakineDetayCacheKey(makineId) {
        return String(makineId) + '|' + (state.enj.baslangic || '') + '|' +
            ((state.enj.motorResult && state.enj.motorResult.tahmini_bitis) || state.enj.bitis || '');
    }

    function enjSideDurum(side) {
        /* PHASE_7O1: CPS plan doluluğu — kart footer */
        if (!side) side = {};
        var cps = side.cps || {};
        if (cps.cps_hata) return { cls: 'hata', lbl: 'HATA' };
        var total = cps.cps_toplam_istasyon || 8;
        var occupied = cps.cps_dolu_istasyon || 0;
        if (occupied >= total) return { cls: 'dolu', lbl: 'TAM DOLU' };
        if (occupied > 0) return { cls: 'planli', lbl: 'KISMI DOLU' };
        return { cls: 'bos', lbl: 'BOŞ' };
    }

    function enjMachineFooterStatus(dA, dB) {
        if (dA.cls === 'hata' || dB.cls === 'hata') return { cls: 'hata', lbl: 'VERİ HATASI' };
        if (dA.cls === 'dolu' && dB.cls === 'dolu') return { cls: 'dolu', lbl: 'TAM DOLU' };
        if (dA.cls === 'bos' && dB.cls === 'bos') return { cls: 'bos', lbl: 'BOŞ' };
        return { cls: 'planli', lbl: 'KISMI DOLU' };
    }

    function enjCpsBarClass(occ, total, hata, confN) {
        if (hata) return 'kirmizi';
        if ((confN || 0) > 0 && (occ || 0) <= 0) return 'sari';
        if (occ >= total) return 'turuncu';
        if (occ > 0) return 'turuncu';
        return 'yesil';
    }

    function enjNearestGapLabel(sideA, sideB) {
        var a = (sideA && sideA.cps) || {};
        var b = (sideB && sideB.cps) || {};
        var candidates = [];
        if (a.cps_ilk_bos_kisa && a.cps_ilk_bos_kisa !== '—') {
            candidates.push({ slot: 'A', kisa: a.cps_ilk_bos_kisa, iso: a.cps_ilk_bos });
        }
        if (b.cps_ilk_bos_kisa && b.cps_ilk_bos_kisa !== '—') {
            candidates.push({ slot: 'B', kisa: b.cps_ilk_bos_kisa, iso: b.cps_ilk_bos });
        }
        if (!candidates.length) return '';
        candidates.sort(function (x, y) {
            return String(x.iso || '').localeCompare(String(y.iso || ''));
        });
        var best = candidates[0];
        return 'En yakın: ' + best.slot + ' · ' + best.kisa;
    }

    function enjMergeBaseFromSlotOzet(makineler) {
        var e = state.enj;
        if (!e.baseFirstAvailableMap) e.baseFirstAvailableMap = {};
        (makineler || []).forEach(function (m) {
            var mid = m.makine_id;
            if (!e.baseFirstAvailableMap[mid]) e.baseFirstAvailableMap[mid] = {};
            ['A', 'B'].forEach(function (sk) {
                var side = m[sk] || {};
                var gos = side.base_first_available_gosterim;
                if (gos) {
                    e.baseFirstAvailableMap[mid][sk] = {
                        iso: side.base_first_available || null,
                        gosterim: gos,
                        tam: side.base_first_available_tam || gos,
                    };
                }
            });
        });
    }

    function enjSideBaseDate(machineId, slotKey, side) {
        var base = (state.enj.baseFirstAvailableMap[machineId] || {})[slotKey];
        if (base && base.gosterim) {
            return { kisa: base.gosterim, tam: base.tam || base.gosterim };
        }
        if (side && side.base_first_available_gosterim) {
            return {
                kisa: side.base_first_available_gosterim,
                tam: side.base_first_available_tam || side.base_first_available_gosterim,
            };
        }
        return { kisa: '—', tam: '—' };
    }

    function enjSideCardBlock(side, slotKey, machineId) {
        /* PHASE_7O1: CPS-only kısa A/B doluluk */
        if (!side) side = {};
        var cps = side.cps || {};
        var total = cps.cps_toplam_istasyon || 8;
        var planli = cps.cps_planli_istasyon || 0;
        var confN = cps.cps_dogrulanmali_istasyon || 0;
        var sideClass = slotKey === 'A' ? 'side-a' : 'side-b';
        var barCls = enjCpsBarClass(planli, total, cps.cps_hata, 0);
        var barPct = total > 0 ? Math.min(100, Math.round((planli / total) * 100)) : 0;
        var planRow = '';
        var e = state.enj;
        if (e.makineId === machineId && e.slot === slotKey && e.baslangic) {
            var planTam = enjFmtDtApi(e.baslangic);
            var planKisa = enjFmtDtKisa(e.baslangic);
            planRow = '<div class="up-mcard-side-plan">' +
                '<span class="up-mcard-side-plan-lbl">Taslak:</span> ' +
                '<strong title="' + esc(planTam) + '">' + esc(planKisa) + '</strong></div>';
        }
        var hataRow = cps.cps_hata
            ? '<div class="up-mcard-cps-line" style="color:#b91c1c;">⛔ Bitiş doğrulanamıyor</div>'
            : '';
        var confRow = confN > 0
            ? '<div class="up-mcard-cps-line up-mcard-cps-warn-short">' + esc(enjUnknownStatusCardShort(confN)) + '</div>'
            : '';
        var doluTxt = cps.cps_dolu_label || (planli + '/' + total + ' planlı dolu');
        return '<div class="up-mcard-side ' + sideClass + '">' +
            '<div class="up-mcard-cps-line"><strong>' + slotKey + ':</strong> ' + esc(doluTxt) + '</div>' +
            hataRow + confRow +
            planRow +
            '<div class="up-mcard-cps-bar" aria-hidden="true">' +
            '<div class="up-mcard-cps-bar-fill ' + barCls + '" style="width:' + barPct + '%"></div></div>' +
            '</div>';
    }

    function enjMdBadge(durum) {
        var d = String(durum || 'BOS').toUpperCase();
        var lbl = d === 'CAKISAN' ? 'ÇAKIŞAN' : d === 'DOGRULANMALI' ? enjUnknownStatusUiLabel() : d;
        var cls = d === 'PLANLI' ? 'planli' : d === 'CAKISAN' ? 'cakisan' :
            d === 'DOGRULANMALI' ? 'dogrulanmali' : d === 'DOLU' ? 'dolu' : 'bos';
        return '<span class="up-enj-md-badge ' + cls + '">' + esc(lbl) + '</span>';
    }

    function enjMdStationRows(stations, mode) {
        if (!stations || !stations.length) {
            return '<p class="up-enj-md-hint">Kayıt yok</p>';
        }
        var headPhys = ['İstasyon', 'Taraf', 'Durum', 'Kalıp', 'Snapshot'];
        var headPlan = ['İstasyon', 'Taraf', 'Durum', 'Sipariş', 'Model', 'Renk', 'Kalıp', 'Asorti', 'Çift', 'Başlangıç', 'Bitiş', 'Mod'];
        var head = mode === 'phys' ? headPhys : headPlan;
        var tbl = '<div class="up-enj-md-table-wrap"><table class="up-enj-md-table"><thead><tr>' +
            head.map(function (h) { return '<th>' + h + '</th>'; }).join('') + '</tr></thead><tbody>';
        var cards = '<div class="up-enj-md-station-cards">';
        stations.forEach(function (st) {
            var no = st.istasyon_no;
            var slot = st.slot || '—';
            var durum = st.durum || 'BOS';
            if (mode === 'phys') {
                var snap = st.snapshot_at || '';
                tbl += '<tr><td>İST' + no + '</td><td>' + esc(slot) + '</td><td>' + enjMdBadge(durum) +
                    '</td><td>' + esc(st.kalip_kod || '—') + '</td><td>' + esc(snap || '—') + '</td></tr>';
                cards += '<div class="up-enj-md-station-card"><dl>' +
                    '<dt>İstasyon</dt><dd>İST' + no + ' · ' + esc(slot) + '</dd>' +
                    '<dt>Durum</dt><dd>' + enjMdBadge(durum) + '</dd>' +
                    '<dt>Kalıp</dt><dd>' + esc(st.kalip_kod || '—') + '</dd>' +
                    '<dt>Snapshot</dt><dd>' + esc(snap || '—') + '</dd></dl></div>';
            } else {
                var asorti = st.asorti ? ('Asorti: ' + st.asorti) : '—';
                tbl += '<tr><td>İST' + no + '</td><td>' + esc(slot) + '</td><td>' + enjMdBadge(durum) +
                    '</td><td>' + esc(st.sip_no || '—') + '</td><td>' + esc(st.model || '—') + '</td>' +
                    '<td>' + esc(st.renk || '—') + '</td><td>' + esc(st.kalip_kod || '—') + '</td>' +
                    '<td>' + esc(asorti) + '</td><td>' + esc(st.planlanacak_cift != null ? fmtN(st.planlanacak_cift) : '—') +
                    '</td><td>' + esc(st.plan_bas_gosterim || enjFmtDtApi(st.plan_baslangic)) +
                    '</td><td>' + esc(st.plan_bit_gosterim || enjFmtDtApi(st.plan_bitis)) +
                    '</td><td>' + esc(st.calisma_modu || '—') + '</td></tr>';
                cards += '<div class="up-enj-md-station-card"><dl>' +
                    '<dt>İstasyon</dt><dd>İST' + no + ' · ' + esc(slot) + '</dd>' +
                    '<dt>Durum</dt><dd>' + enjMdBadge(durum) + '</dd>' +
                    '<dt>Sipariş</dt><dd>' + esc(st.sip_no || '—') + '</dd>' +
                    '<dt>Model</dt><dd>' + esc(st.model || '—') + '</dd>' +
                    '<dt>Renk</dt><dd>' + esc(st.renk || '—') + '</dd>' +
                    '<dt>Kalıp</dt><dd>' + esc(st.kalip_kod || '—') + '</dd>' +
                    '<dt>Asorti</dt><dd>' + esc(asorti) + '</dd>' +
                    '<dt>Çift</dt><dd>' + esc(st.planlanacak_cift != null ? fmtN(st.planlanacak_cift) : '—') + '</dd>' +
                    '<dt>Başlangıç</dt><dd>' + esc(st.plan_bas_gosterim || enjFmtDtApi(st.plan_baslangic)) + '</dd>' +
                    '<dt>Bitiş</dt><dd>' + esc(st.plan_bit_gosterim || enjFmtDtApi(st.plan_bitis)) + '</dd>' +
                    '<dt>Mod</dt><dd>' + esc(st.calisma_modu || '—') + '</dd></dl></div>';
            }
        });
        tbl += '</tbody></table></div>';
        cards += '</div>';
        return tbl + cards;
    }

    function enjRenderMakineDetayBody(data) {
        var body = $('upEnjMakineDetayBody');
        var title = $('upEnjMakineDetayTitle');
        if (!body || !data || !data.makine) return;
        var mk = data.makine;
        var anchor = data.anchor || {};
        var basLbl = anchor.baslangic
            ? enjFmtDtApi(anchor.baslangic)
            : 'Plan tarihi seçilmedi';
        if (title) {
            title.textContent = (mk.kod || 'Makine') + ' — ' + (mk.istasyon_sayisi || 8) + ' istasyon';
        }
        var meta = '<div class="up-enj-md-meta">' +
            '<span>Makine: <strong>' + esc(mk.kod) + '</strong></span>' +
            '<span>Kapasite: <strong>' + (mk.istasyon_sayisi || 8) + ' istasyon</strong></span>' +
            '<span>Başlangıç: <strong>' + esc(basLbl) + '</strong></span></div>';
        var sides = data.sides || {};
        var html = meta;
        ['A', 'B'].forEach(function (slotKey) {
            var side = sides[slotKey] || {};
            var phys = side.physical || {};
            var plan = side.planned || {};
            var snap = phys.snapshot_at || phys.snapshot_tarih || '';
            if (phys.snapshot_vardiya && phys.snapshot_tarih) {
                snap = phys.snapshot_tarih + ' ' + phys.snapshot_vardiya;
            }
            html += '<div class="up-enj-md-section">' +
                '<h3 class="up-enj-md-section-title phys">' + slotKey + ' — ŞU ANKİ FİZİKSEL DURUM</h3>';
            if (snap) {
                html += '<p class="up-hint" style="margin:0 0 6px;font-size:11px;">Snapshot: ' + esc(snap) + '</p>';
            }
            var physSt = (phys.stations || []).map(function (st) {
                var row = Object.assign({}, st);
                if (snap) row.snapshot_at = snap;
                return row;
            });
            html += enjMdStationRows(physSt, 'phys') + '</div>';
            html += '<div class="up-enj-md-section">' +
                '<h3 class="up-enj-md-section-title plan">' + slotKey + ' — SEÇİLEN TARİHTEKİ PLAN DURUMU</h3>';
            if (plan.plan_tarih_secilmedi) {
                html += '<p class="up-enj-md-hint">Plan durumunu görmek için başlangıç tarihi seçin.</p>';
            } else {
                html += enjMdStationRows(plan.stations || [], 'plan');
            }
            html += '</div>';
        });
        body.innerHTML = html;
    }

    function enjCloseMakineDetay() {
        var modal = $('upEnjMakineDetayModal');
        if (modal) modal.hidden = true;
        var btn = state.enj.makineDetayTriggerBtn;
        state.enj.makineDetayLoadingKey = null;
        if (btn && typeof btn.focus === 'function') btn.focus();
        state.enj.makineDetayTriggerBtn = null;
    }

    function enjOpenMakineDetay(makineId, makineKod, triggerBtn) {
        var modal = $('upEnjMakineDetayModal');
        var body = $('upEnjMakineDetayBody');
        if (!modal || !body) return;
        state.enj.makineDetayTriggerBtn = triggerBtn || null;
        modal.hidden = false;
        var panel = modal.querySelector('.up-enj-makine-detay-panel');
        if (panel) panel.focus();
        var cacheKey = enjMakineDetayCacheKey(makineId);
        var cached = state.enj.makineDetayCache[cacheKey];
        if (cached) {
            enjRenderMakineDetayBody(cached);
            return;
        }
        if (state.enj.makineDetayLoadingKey === cacheKey) return;
        state.enj.makineDetayLoadingKey = cacheKey;
        body.innerHTML = '<div class="up-loading">Yükleniyor…</div>';
        fetch('/planlama/uretim-plan/api/enj/makine-detay?' +
            'makine_id=' + encodeURIComponent(makineId) + '&' + enjSlotOzetParams(),
            { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (state.enj.makineDetayLoadingKey !== cacheKey) return;
                state.enj.makineDetayLoadingKey = null;
                if (!d.ok) {
                    body.innerHTML = '<p class="up-enj-md-hint">' + esc(d.mesaj || 'Detay yüklenemedi') + '</p>';
                    return;
                }
                state.enj.makineDetayCache[cacheKey] = d;
                enjRenderMakineDetayBody(d);
            })
            .catch(function () {
                state.enj.makineDetayLoadingKey = null;
                body.innerHTML = '<p class="up-enj-md-hint">Detay yüklenemedi</p>';
            });
    }

    function enjBindMakineDetayModal() {
        var modal = $('upEnjMakineDetayModal');
        if (!modal) return;
        ['upEnjMakineDetayClose', 'upEnjMakineDetayKapat'].forEach(function (id) {
            if ($(id)) $(id).addEventListener('click', enjCloseMakineDetay);
        });
        if ($('upEnjMakineDetayBackdrop')) {
            $('upEnjMakineDetayBackdrop').addEventListener('click', enjCloseMakineDetay);
        }
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && modal && !modal.hidden) {
                ev.stopPropagation();
                enjCloseMakineDetay();
            }
        });
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
        wrap.style.display = '';
        if (legacy) legacy.style.display = 'none';
        var modLabel = rez.calismaModu === 'GUNDUZ' ? 'Gündüz'
            : rez.calismaModu === 'GECE' ? 'Gece' : 'Gündüz+Gece';
        body.innerHTML =
            '<div class="up-step3-rezerv-grid">' +
              '<div class="up-step3-rg-item"><span>Makine</span><strong>' + esc(rez.makineKod || '—') + '</strong></div>' +
              '<div class="up-step3-rg-item"><span>Taraf</span><strong>' + esc(rez.slot || '—') + '</strong></div>' +
              '<div class="up-step3-rg-item"><span>İstasyonlar</span><strong>' + esc(rez.istStr || '—') + '</strong></div>' +
              '<div class="up-step3-rg-item"><span>Kalıp</span><strong>' + esc(rez.kalipKod || '—') + ' (' + esc(rez.kalipAdedi) + ')</strong></div>' +
              '<div class="up-step3-rg-item"><span>Planlanacak çift</span><strong>' + fmtN(rez.planCift) + '</strong></div>' +
              '<div class="up-step3-rg-item"><span>Çalışma modu</span><strong>' + esc(modLabel) + '</strong></div>' +
              '<div class="up-step3-rg-item up-step3-rg-span2"><span>Enjeksiyon başlangıcı</span><strong>' + esc(enjFmtDtApi(rez.baslangic)) + '</strong></div>' +
              '<div class="up-step3-rg-item up-step3-rg-span2"><span>Hesaplanan bitiş</span><strong>' + esc(enjFmtDtApi(rez.bitis)) + '</strong></div>' +
            '</div>';
    }

    function enjFetchIstasyonPlanDurum(cb, captureSeq) {
        var e = state.enj;
        if (!e.makineId || !e.slot || !e.baslangic) {
            e.istasyonPlanDurum = {};
            if (cb) cb();
            return;
        }
        var seq = captureSeq != null ? captureSeq : ++e.istasyonAvailabilitySeq;
        var capture = enjAvailabilityCapture(seq);
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
              if (!enjAvailabilityStillValid(capture)) return;
              e.istasyonPlanDurum = {};
              e.unifiedBusyCount = d.unified_busy_count != null ? d.unified_busy_count : null;
              e.dogrulanmaliCount = d.dogrulanmali_count != null ? d.dogrulanmali_count : 0;
              e.physicalAdvisory = d.physical_advisory || null;
              if (d.ok && d.istasyonlar) {
                  d.istasyonlar.forEach(function (row) {
                      if (row && row.istasyon_no != null) {
                          e.istasyonPlanDurum[row.istasyon_no] = row;
                      }
                  });
              }
              if (cb) cb(capture);
          })
          .catch(function () { if (cb && enjAvailabilityStillValid(capture)) cb(capture); });
    }

    function enjValidateSelectedStationsAtDate(cb, pruneReason) {
        var e = state.enj;
        if (!e.makineId || !e.slot || !e.baslangic) {
            if (cb) cb(false);
            return;
        }
        var seq = ++e.istasyonAvailabilitySeq;
        enjFetchIstasyonPlanDurum(function () {
            var m = (e.gridData || []).find(function (x) {
                return (x.makine_id || x.id) === e.makineId;
            });
            if (m) {
                enjPruneInvalidStations(m, pruneReason || 'validate');
                enjRenderIstasyonGrid(m);
            }
            enjSyncKalipAdediFromStations();
            enjUpdateStep2Ui();
            if (cb) cb(true);
        }, seq);
    }

    function enjYukleSlotOzet(cb) {
        var e = state.enj;
        var seq = ++e.slotOzetSeq;
        var captureSip = state.seciliCreateData && state.seciliCreateData.sip_no;
        fetch('/planlama/uretim-plan/api/enj/makine-slot-ozet?' + enjSlotOzetParams(),
            { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (seq !== e.slotOzetSeq) return;
                if (captureSip !== (state.seciliCreateData && state.seciliCreateData.sip_no)) return;
                if (d.ok && d.makineler) {
                    enjMergeBaseFromSlotOzet(d.makineler);
                    var newMap = {};
                    d.makineler.forEach(function (m) {
                        newMap[m.makine_id] = m;
                    });
                    e.slotOzetMap = newMap;
                    e.makineDetayCache = {};
                }
                if (cb) cb();
            })
            .catch(function () { if (cb) cb(); });
    }

    function enjIstasyonUnifiedDurum(n, m) {
        var e = state.enj;
        var pd = (e.istasyonPlanDurum || {})[n];
        if (pd && pd.durum) return pd.durum;
        var slot = e.slot;
        var grid = (m && m.grid) || [];
        var row = grid[n - 1] || {};
        var cell = slot ? (row[slot] || {}) : null;
        return slot ? enjCellDurum(cell) : 'BOS';
    }

    function enjIstasyonDisabledAtDate(n, m) {
        var e = state.enj;
        var durum = enjIstasyonUnifiedDurum(n, m);
        return !e.slot || durum === 'PLANLI' || durum === 'DOLU' ||
            durum === 'SETUP' || durum === 'ARIZA';
    }

    function enjPruneInvalidStations(m, pruneReason) {
        if (!m || !state.enj.istasyonlar.length) return false;
        var removed = [];
        state.enj.istasyonlar = state.enj.istasyonlar.filter(function (n) {
            var disabled = !enjIstasyonSelectionGateOpen() || enjIstasyonDisabledAtDate(n, m);
            if (disabled) { removed.push(n); return false; }
            return true;
        });
        if (enjTrimIstasyonlarToPhysLimit(m)) return true;
        if (removed.length) {
            state.enj._istasyonCleanupMsg =
                'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.';
            enjHesapGizle();
            enjUpdateCentralStatus();
            return true;
        }
        return false;
    }

    function enjYuklePlanOzet(cb) {
        enjYukleSlotOzet(cb);
    }

    function enjDtLocalToApi(v) {
        if (!v) return null;
        return v.replace('T', ' ') + ':00';
    }

    function enjFmtDtKisa(v) {
        if (!v) return '—';
        var p = String(v).replace('T', ' ').slice(0, 16);
        var sp = p.indexOf(' ');
        if (sp < 0) return p;
        var dp = p.slice(0, sp).split('-');
        var tp = p.slice(sp + 1, sp + 6);
        if (dp.length === 3) return dp[2] + '.' + dp[1] + ' ' + tp;
        return p;
    }

    function enjFmtDtApi(v) {
        if (!v) return '—';
        var p = String(v).replace('T', ' ').slice(0, 16);
        var d = p.split(' ');
        if (d.length !== 2) return v;
        var dp = d[0].split('-');
        return dp[2] + '.' + dp[1] + '.' + dp[0] + ' ' + d[1].slice(0, 5);
    }

    function enjFmtDtCompact(v) {
        if (!v) return '';
        var p = String(v).replace('T', ' ').slice(0, 16);
        var d = p.split(' ');
        if (d.length !== 2) return enjFmtDtApi(v);
        var dp = d[0].split('-');
        return dp[2] + '.' + dp[1] + ' ' + d[1].slice(0, 5);
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
        // PHASE_7N3: library modunda Aktif Göz / İstasyon Sayısı gizlenir
        var layout = document.querySelector('.up-step2-layout');
        if (layout) layout.classList.toggle('library-mode', liste);
        if (liste) {
            state.enj.kalipKod = null;
            state.enj.libraryUuid = null;
            state.enj.libraryKalipMeta = null;
            if ($('upEnjKalipManuelKod')) $('upEnjKalipManuelKod').value = '';
            if ($('upEnjKalipManuelKbc')) $('upEnjKalipManuelKbc').value = '';
        } else {
            state.enj.kalipId = null;
            state.enj.kalipKod = null;
            state.enj.kalipBasiCift = null;
            state.enj.libraryUuid = null;
            state.enj.libraryKalipMeta = null;
            if ($('upEnjKalip')) $('upEnjKalip').value = '';
        }
        enjRenderLibrarySummary(null);
        enjUpdateKalipSeciliCards();
        enjUpdateFizikselKalipDisplay();
        if (state.enj.istasyonlar.length) {
            enjClearIstasyonSecimleri(
                'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.');
        }
        var mMode = (state.enj.gridData || []).find(function (x) {
            return (x.makine_id || x.id) === state.enj.makineId;
        });
        if (mMode) enjRenderIstasyonGrid(mMode);
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
        // PHASE_7O3B: Kapı kapalıyken DOM checkbox senkronu state'i bozmasın
        var istGrid = $('upEnjIstasyonGrid');
        if (istGrid && enjIstasyonSelectionGateOpen()) {
            var cbs = istGrid.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)');
            if (cbs.length > 0) {
                var domIstasyonlar = [];
                cbs.forEach(function (cb) {
                    var n = parseInt(cb.value, 10);
                    if (n > 0) domIstasyonlar.push(n);
                });
                e.istasyonlar = domIstasyonlar;
            }
        }
        enjUpdateTarihDurumEtiketi();
    }

    function enjKalipSecili() {
        var e = state.enj;
        if (e.kalipMode === 'manuel') {
            return !!(e.kalipKod && e.kalipBasiCift > 0);
        }
        if (e.libraryPlanEnabled) {
            return !!e.libraryUuid;
        }
        return !!e.kalipId;
    }

    /** PHASE_7O3B: Kullanılacak fiziksel kalıp adedi — istasyon üst limiti. */
    function enjGetFizikselKalipLimit() {
        var e = state.enj;
        if (!enjKalipSecili()) return null;
        if (e.kalipMode === 'manuel') {
            return e.istasyonSayisi || 8;
        }
        if (e.libraryPlanEnabled && e.libraryKalipMeta) {
            var pt = parseInt(e.libraryKalipMeta.physical_mold_total, 10);
            return pt > 0 ? pt : null;
        }
        if (e.kalipId) {
            return e.istasyonSayisi || 8;
        }
        return null;
    }

    function enjFizikselKalipAdediGecerli() {
        var lim = enjGetFizikselKalipLimit();
        return lim != null && lim > 0;
    }

    function enjIstasyonlarYuklendi() {
        var e = state.enj;
        return !!(e.makineId && e.slot && enjHasBaslangic());
    }

    /** PHASE_7O3B: Kalıp seçilmeden istasyon seçimi kapalı. */
    function enjIstasyonSelectionGateOpen() {
        var e = state.enj;
        return !!(e.makineId && e.slot && enjHasBaslangic() &&
            enjKalipSecili() && enjFizikselKalipAdediGecerli() && enjIstasyonlarYuklendi());
    }

    function enjIstasyonGateBlockReason() {
        if (!state.enj.makineId) return 'makine';
        if (!state.enj.slot) return 'slot';
        if (!enjHasBaslangic()) return 'tarih';
        if (!enjKalipSecili()) return 'kalip';
        if (!enjFizikselKalipAdediGecerli()) return 'fiziksel';
        return null;
    }

    function enjClearIstasyonSecimleri(centralMsg) {
        var had = (state.enj.istasyonlar || []).length > 0;
        state.enj.istasyonlar = [];
        state.enj._fizikselKalipLimitAttempt = false;
        state.enj._fizikselKalipAsimi = false;
        if (centralMsg) state.enj._istasyonCleanupMsg = centralMsg;
        enjSyncKalipAdediFromStations();
        enjHesapGizle();
        return had;
    }

    function enjTrimIstasyonlarToPhysLimit(m) {
        var lim = enjGetFizikselKalipLimit();
        var arr = state.enj.istasyonlar || [];
        if (!lim || arr.length <= lim) return false;
        state.enj.istasyonlar = arr.slice(0, lim);
        state.enj._istasyonCleanupMsg =
            'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.';
        enjSyncKalipAdediFromStations();
        enjHesapGizle();
        if (m) enjRenderIstasyonGrid(m);
        return true;
    }

    /** PHASE_7O3B: UI + programmatic bypass guard. */
    function enjTryToggleIstasyon(n, checked, m, inputEl) {
        if (!enjIstasyonSelectionGateOpen()) {
            if (inputEl) inputEl.checked = false;
            return false;
        }
        if (checked && enjIstasyonDisabledAtDate(n, m)) {
            if (inputEl) inputEl.checked = false;
            return false;
        }
        var arr = state.enj.istasyonlar;
        if (checked) {
            var physTotal = enjGetFizikselKalipLimit();
            if (physTotal !== null && arr.length >= physTotal) {
                if (inputEl) inputEl.checked = false;
                state.enj._fizikselKalipLimitAttempt = true;
                enjUpdateCentralStatus();
                return false;
            }
            if (arr.indexOf(n) < 0) arr.push(n);
        } else {
            state.enj.istasyonlar = arr.filter(function (x) { return x !== n; });
        }
        state.enj.istasyonlar.sort(function (a, b) { return a - b; });
        state.enj._fizikselKalipLimitAttempt = false;
        enjCheckFizikselKalipLimit(state.enj.istasyonlar.length);
        enjEvaluateShiftStartBoundary();
        enjHesapGizle();
        enjSyncKalipAdediFromStations();
        enjValidateSelectedStationsAtDate(function () {
            enjUpdateHesapBtn();
        }, 'validate');
        return true;
    }

    function enjHesaplaRequirements() {
        var e = state.enj;
        enjSyncInputsFromDom();
        enjSyncReferenceModeFromDom();
        enjSyncKalipAdediFromStations();
        var istOk = e.istasyonlar.length > 0 &&
            e.kalipAdedi > 0 &&
            e.kalipAdedi === e.istasyonlar.length;
        var refOk = true;
        if (typeof enjCapacityConfirmedOk === 'function') {
            refOk = enjCapacityConfirmedOk();
        } else if (e.referenceMode === 'MANUAL') {
            if (e.calismaModu !== 'GECE') refOk = (e.manualRefGunduz || 0) > 0;
            if (refOk && e.calismaModu !== 'GUNDUZ') refOk = (e.manualRefGece || 0) > 0;
        }
        return [
            { key: 'makine', label: 'Makine seçin', ok: !!e.makineId, focus: 'upEnjMakineCards' },
            { key: 'slot', label: 'Slot seçin', ok: !!e.slot, focus: 'upEnjSlotA' },
            { key: 'tarih', label: 'Başlangıç seçilmedi', ok: !!e.baslangic, focus: 'upEnjBas' },
            { key: 'kalip', label: 'Kalıp seçilmedi', ok: enjKalipSecili() && (e.kalipBasiCift || 0) > 0, focus: 'upEnjKalip' },
            { key: 'istasyon', label: 'İstasyon seçilmedi', ok: istOk, focus: 'upEnjIstasyonGrid' },
            // PHASE_7N4: fiziksel kalıp aşımı Hesapla/İleri'yi engeller
            { key: 'fizikselLimit', label: 'İstasyon sayısı fiziksel kalıp adedini aşıyor', ok: !e._fizikselKalipAsimi && !e._fizikselKalipLimitAttempt, focus: 'upEnjIstasyonGrid' },
            { key: 'kalan', label: 'Planlanacak kalan miktar yok', ok: !enjKalanSifirBlocked(), focus: 'upEnjMiktarOzet' },
            { key: 'miktar', label: 'Planlanacak miktarı girin', ok: (e.planCift || 0) > 0, focus: 'upEnjPlanCift' },
            { key: 'kapasite', label: 'Kapasite onaylanmadı', ok: refOk && (e.gozPerKalip || 0) > 0, focus: 'upTakvimAcc' },
            { key: 'shiftApprove', label: 'Vardiya dışı başlangıç onaylayın', ok: !e.shiftStartOverrideRequired || e.shiftStartOverrideConfirmed, focus: 'upEnjShiftStartWarn' },
        ];
    }

    function enjCanHesapla() {
        return enjHesaplaRequirements().every(function (r) { return r.ok; });
    }

    function enjHesaplaDisabledNeden() {
        return enjHesaplaRequirements().filter(function (r) { return !r.ok; }).map(function (r) { return r.label; });
    }

    function enjRenderHesapRequirements() {
        var wrap = $('upEnjHesapReqList');
        if (!wrap) return;
        var reqs = enjHesaplaRequirements();
        var missing = reqs.filter(function (r) { return !r.ok; });
        var allOk = missing.length === 0;

        /* Tek satır özet */
        var ozet = wrap.querySelector('.up-req-ozet');
        if (!ozet) {
            ozet = document.createElement('div');
            ozet.className = 'up-req-ozet';
            wrap.appendChild(ozet);
        }
        if (allOk) {
            ozet.innerHTML = '<span class="up-req-hazir">✓ Hesaplama için hazır</span>';
        } else {
            var eksikler = missing.map(function (r) {
                if (!r.focus) return esc(r.label);
                return '<button type="button" class="up-req-link" data-focus="' + r.focus + '">' + esc(r.label) + '</button>';
            }).join(', ');
            ozet.innerHTML = '<span class="up-req-eksik-lbl">Eksikler:</span> ' + eksikler +
                ' &nbsp;<button type="button" class="up-req-toggle" aria-expanded="false">▸ Detay</button>';
        }

        /* Tam liste — varsayılan kapalı */
        var liste = wrap.querySelector('.up-req-liste');
        if (!liste) {
            liste = document.createElement('ul');
            liste.className = 'up-req-liste';
            liste.setAttribute('hidden', '');
            wrap.appendChild(liste);
        }
        liste.innerHTML = reqs.map(function (r) {
            var cls = r.ok ? 'ok' : 'missing';
            var mark = r.ok ? '✓' : '○';
            var link = (!r.ok && r.focus)
                ? ' <button type="button" class="up-req-link" data-focus="' + r.focus + '">Git</button>'
                : '';
            return '<li class="' + cls + '"><span>' + mark + '</span> ' + esc(r.label) + link + '</li>';
        }).join('');

        /* Event: toggle */
        wrap.querySelectorAll('.up-req-toggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var open = btn.getAttribute('aria-expanded') === 'true';
                btn.setAttribute('aria-expanded', open ? 'false' : 'true');
                btn.textContent = open ? '▸ Detay' : '▾ Gizle';
                if (open) liste.setAttribute('hidden', ''); else liste.removeAttribute('hidden');
            });
        });
        /* Event: git */
        wrap.querySelectorAll('.up-req-link').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-focus');
                var t = $(id);
                if (t) { t.scrollIntoView({ behavior: 'smooth', block: 'center' }); if (typeof t.focus === 'function') t.focus(); }
            });
        });
        if (missing.length) wrap.dataset.firstMissing = missing[0].focus;
    }

    function enjUpdateHesapBtn() {
        enjSyncInputsFromDom();
        enjSyncReferenceModeFromDom();
        enjSyncKalipAdediFromStations();
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
        enjRenderHesapRequirements();
        enjUpdateStep2Ui();
        var hintEl = $('upEnjHesapBtnHint');
        if (hintEl) hintEl.style.display = 'none';
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
        if (typeof enjCapacityConfirmedOk === 'function' && enjCapacityConfirmedOk()) {
            payload.reference_mode = 'MANUAL';
            if (e.calismaModu !== 'GECE') payload.manual_reference_gunduz = e.capacityConfirmedTurGunduz;
            if (e.calismaModu !== 'GUNDUZ') payload.manual_reference_gece = e.capacityConfirmedTurGece;
        } else if (e.referenceMode === 'MANUAL') {
            if (e.calismaModu !== 'GECE') payload.manual_reference_gunduz = e.manualRefGunduz;
            if (e.calismaModu !== 'GUNDUZ') payload.manual_reference_gece = e.manualRefGece;
        }
        if (e.shiftStartOverrideRequired && e.shiftStartOverrideConfirmed) {
            payload.shift_start_override_confirmed = true;
            payload.shift_start_override_time = e.shiftStartOverrideTime || e.baslangic;
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
                  if (d.shift_start_override_required) {
                      state.enj.shiftStartOverrideRequired = true;
                      state.enj.shiftStartSuggestedBoundary = d.onerilen_baslangic_gosterim || d.onerilen_baslangic;
                      enjRenderShiftStartOverrideUi();
                  }
                  if (d.baslangic_gecersiz && d.onerilen_baslangic && $('upEnjBas') &&
                      !state.enj.baslangicManuel && !d.shift_start_override_required) {
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
              e.draftPreview = {
                  plan_baslangic: d.plan_baslangic,
                  uretim_baslangic: d.uretim_baslangic || d.plan_baslangic,
                  tahmini_bitis: d.tahmini_bitis,
                  setup_dakika: d.setup_dakika || 0,
                  slot: e.slot,
              };
              if (typeof enjRefreshDraftBars === 'function') enjRefreshDraftBars();
              enjUpdateTakvimDraftBar();
              if (e._takvimHesapPending) {
                  e._takvimHesapPending = false;
                  enjSetTakvimAccOpen(false);
                  var gBody = $('upTakvimWsBody');
                  if (gBody && typeof gBody.scrollIntoView === 'function') {
                      gBody.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                  }
              }
              if (d.shift_start_override_confirmed) {
                  e.shiftStartOverrideConfirmed = true;
                  e.shiftStartOverrideTime = d.shift_start_override_time || e.baslangic;
                  e.shiftStartApprovalContext = enjShiftStartApprovalContext();
              }
              e.bitis = d.tahmini_bitis;
              e.turCift = d.tur_basi_cift;
              e.autoRefGunduz = (d.auto_gunduz_reference || d.gunduz_reference || {});
              e.autoRefGece = (d.auto_gece_reference || d.gece_reference || {});
              enjFreezeReservation(d);
              enjRenderHesapOzet(d);
              enjUpdateLowConfHint(d);
              enjUpdateKurulumOzet();
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
        /* Hesaplama sonrası bitiş placeholder'ı gizle */
        if ($('upEnjBitisPlaceholder')) $('upEnjBitisPlaceholder').style.display = 'none';
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
        enjSetHesapDetayAcik(false);
        if ($('upEnjHesapDetayToggle')) $('upEnjHesapDetayToggle').style.display = '';
    }

    function enjApplyIlkUygunInput() {
        enjUpdateIlkUygunDisplay();
    }

    function enjUseIlkUygunDate() {
        var e = state.enj;
        var iu = e.ilkUygunMap[e.makineId];
        if (!iu || !iu.ilk_uygun) return;
        e.baslangicOneri = iu.ilk_uygun;
        e.baslangic = iu.ilk_uygun;
        e.baslangicManuel = true;
        if ($('upEnjBas')) $('upEnjBas').value = enjApiDtToLocal(iu.ilk_uygun);
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = '';
        enjHesapGizle();
        enjValidateSelectedStationsAtDate(function () {
            enjYukleSlotOzet(function () { enjRenderMakineCards(e.gridData || []); });
            enjUpdateHesapBtn();
        }, 'date');
    }

    function enjFetchIlkUygun(forPreview) {
        var e = state.enj;
        if (!e.slot || !e.makineId) return;
        var kalipAdedi = parseInt($('upEnjKalipAdedi') && $('upEnjKalipAdedi').value, 10) || 0;
        var seciliIst = forPreview ? [1] : e.istasyonlar.slice();
        if (!forPreview) {
            if (kalipAdedi < 1 || seciliIst.length === 0) {
                enjUpdateHesapBtn();
                return;
            }
            if (seciliIst.length < kalipAdedi) {
                enjUpdateHesapBtn();
                return;
            }
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
              if (!forPreview) e.ilkUygunMap = {};
              (d.makineler || []).forEach(function (m) {
                  m._fetched_slot = e.slot;
                  m._fetched_ist = seciliIst.slice();
                  e.ilkUygunMap[m.makine_id] = m;
              });
              if (!forPreview) {
                  enjRenderMakineCards(e.gridData || []);
              }
              enjUpdateIlkUygunDisplay();
              enjUpdateHesapBtn();
          });
    }

    function enjClearMakineDependencies() {
        var e = state.enj;
        e.istasyonAvailabilitySeq++;
        e.slot = null;
        e.istasyonlar = [];
        e.baslangicManuel = false;
        e.baslangic = null;
        e.baslangicOneri = null;
        e.ilkUygunMap = {};
        e.istasyonPlanDurum = {};
        if ($('upEnjBas')) $('upEnjBas').value = '';
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        if ($('upEnjBasConflict')) $('upEnjBasConflict').style.display = 'none';
        if ($('upEnjSlotA')) $('upEnjSlotA').classList.remove('selected');
        if ($('upEnjSlotB')) $('upEnjSlotB').classList.remove('selected');
        enjHesapGizle();
        enjSyncKalipAdediFromStations();
        enjUpdateTarihDurumEtiketi();
    }

    function enjSelectMakine(m, machines) {
        var mid = m.makine_id || m.id;
        var kod = m.makine_kod || m.kod || m.code;
        state.enj.makineId = mid;
        state.enj.makineKod = kod;
        state.enj.istasyonSayisi = m.istasyon_sayisi;
        enjClearMakineDependencies();
        enjRenderMakineCards(machines);
        enjRenderIstasyonGrid(m);
        if ($('upEnjKalip')) $('upEnjKalip').disabled = false;
        enjUpdateHesapBtn();
        if (state.enj._hizGosterimVeri) {
            enjSonHaftaHizRender(state.enj._hizGosterimVeri, kod);
        }
        if (state.enj._sonHaftaVeri) {
            enjLoadAutoRefFromSonHafta(kod, state.enj.slot);
        }
        enjUpdateAutoRefHints();
    }

    function enjRequestMakineChange(m, machines) {
        var mid = m.makine_id || m.id;
        if (state.enj.makineId === mid) return;
        var hasDeps = !!(state.enj.slot || state.enj.baslangic ||
            (state.enj.istasyonlar && state.enj.istasyonlar.length) || state.enj.hesapOk);
        if (state.enj.makineId && hasDeps) {
            if (!window.confirm(
                'Makine değiştirildiğinde slot, tarih ve istasyon seçimleri temizlenecek. Devam edilsin mi?'
            )) {
                enjRenderMakineCards(machines);
                return;
            }
        }
        enjSelectMakine(m, machines);
    }

    function enjRenderMakineCards(machines) {
        var el = $('upEnjMakineCards');
        if (!el) return;
        el.innerHTML = '';
        machines.forEach(function (m) {
            var mid = m.makine_id || m.id;
            var kod = m.makine_kod || m.kod || m.code;
            var oz = state.enj.slotOzetMap[mid] || {};
            var sideA = oz.A || {};
            var sideB = oz.B || {};
            /* Durum satırı — A ve B'yi karşılaştır */
            var dA = enjSideDurum(sideA);
            var dB = enjSideDurum(sideB);
            var foot = enjMachineFooterStatus(dA, dB);
            var footerCls = foot.cls;
            var footerLbl = foot.lbl;
            var nearestHtml = enjNearestGapLabel(sideA, sideB);
            var isSelected = (state.enj.makineId === mid);
            /* Radio göstergesi - sağ üstte */
            var radioHtml = '<span class="up-mcard-radio' + (isSelected ? ' selected' : '') + '" aria-hidden="true"></span>';
            /* Kart wrapper */
            var wrap = document.createElement('div');
            wrap.className = 'up-mcard-wrap' + (isSelected ? ' selected' : '');
            /* Tıklanabilir makine başlık + içerik alanı */
            var card = document.createElement('button');
            card.type = 'button';
            card.className = 'up-mcard-btn';
            card.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
            card.innerHTML =
                '<div class="up-mcard-head">' +
                  '<div class="up-mcard-head-left">' +
                    '<strong class="up-mcard-kod">' + esc(kod) + '</strong>' +
                    '<span class="up-mcard-ist">' + m.istasyon_sayisi + ' İSTASYON</span>' +
                  '</div>' +
                  radioHtml +
                '</div>' +
                '<div class="up-mcard-sides">' +
                  enjSideCardBlock(sideA, 'A', mid) +
                  enjSideCardBlock(sideB, 'B', mid) +
                '</div>' +
                (nearestHtml ? '<div class="up-mcard-nearest">' + esc(nearestHtml) + '</div>' : '');
            card.addEventListener('click', function () {
                enjRequestMakineChange(m, machines);
            });
            /* Alt satır: durum noktası + durum metni + Detay butonu */
            var footer = document.createElement('div');
            footer.className = 'up-mcard-foot';
            var durumDot = document.createElement('span');
            durumDot.className = 'up-mcard-dot ' + footerCls;
            var durumSpan = document.createElement('span');
            durumSpan.className = 'up-mcard-durum-lbl';
            durumSpan.textContent = footerLbl;
            var detBtn = document.createElement('button');
            detBtn.type = 'button';
            detBtn.className = 'up-mcard-detay-btn';
            detBtn.textContent = 'Detay ›';
            detBtn.setAttribute('aria-label', kod + ' makine detayını aç');
            detBtn.addEventListener('click', function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                enjOpenTakvimWorkspace(mid, kod, detBtn);
            });
            footer.appendChild(durumDot);
            footer.appendChild(durumSpan);
            footer.appendChild(detBtn);
            wrap.appendChild(card);
            wrap.appendChild(footer);
            el.appendChild(wrap);
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

    function enjRenderIstasyonPlaceholder() {
        /* Makine/taraf seçilmeden önce IST1–IST8 disabled placeholder */
        var el = $('upEnjIstasyonGrid');
        if (!el) return;
        el.innerHTML = '';
        for (var i = 1; i <= 8; i++) {
            var lbl = document.createElement('label');
            lbl.className = 'up-ist-card disabled';
            lbl.innerHTML =
                '<input type="checkbox" disabled>' +
                '<span class="up-ist-dot neutral"></span>' +
                '<span class="up-ist-kod">İST' + i + '</span>' +
                '<span class="up-ist-durum">—</span>';
            el.appendChild(lbl);
        }
        enjUpdateIstasyonOzetSatir(null, null);
    }

    function enjUpdateIstasyonOzetSatir(m, uygunSayisi) {
        /* "X uygun istasyon · Y seçili · Y kalıp" veya açıklama metni */
        var hint = $('upEnjToplamGozHint');
        if (!hint) return;
        var e = state.enj;
        if (!e.makineId || !e.slot || !e.baslangic) {
            hint.textContent = 'İstasyon seçimi için makine, taraf ve tarih seçin.';
            return;
        }
        if (!enjIstasyonSelectionGateOpen()) {
            if (enjIstasyonGateBlockReason() === 'kalip') {
                hint.textContent = 'Önce kalıp seçin; ardından istasyonları seçebilirsiniz.';
            } else {
                hint.textContent = 'İstasyon seçimi için gerekli planlama adımlarını tamamlayın.';
            }
            return;
        }
        var secilenSayisi = e.istasyonlar ? e.istasyonlar.length : 0;
        var kalipAdedi = e.kalipAdedi || secilenSayisi;
        var goz = parseInt(($('upEnjGozPerKalip') && $('upEnjGozPerKalip').value) || '1', 10) || 1;
        var uygunTxt = uygunSayisi != null ? (uygunSayisi + ' uygun istasyon · ') : '';
        hint.textContent = uygunTxt + secilenSayisi + ' seçili · ' + kalipAdedi + ' kalıp' +
            (kalipAdedi > 0 ? ' · Toplam ' + (kalipAdedi * goz) + ' aktif göz' : '');
    }

    function enjRenderIstasyonGrid(m) {
        var el = $('upEnjIstasyonGrid');
        if (!el) return;
        /* Makine seçilmemişse placeholder göster */
        if (!state.enj.makineId) {
            enjRenderIstasyonPlaceholder();
            return;
        }
        if (!enjIstasyonSelectionGateOpen() && state.enj.istasyonlar.length) {
            state.enj.istasyonlar = [];
            enjSyncKalipAdediFromStations();
        }
        el.innerHTML = '';
        var slot = state.enj.slot;
        var planDurum = state.enj.istasyonPlanDurum || {};
        var uygunSayisi = 0;
        for (var i = 1; i <= state.enj.istasyonSayisi; i++) {
            var pd = planDurum[i];
            var durum = enjIstasyonUnifiedDurum(i, m);
            var detail = '';
            if (pd && pd.durum === 'PLANLI') {
                detail = (pd.sip_no || '') + ' ' + (pd.bas_gosterim || '') + '→' + (pd.bit_gosterim || '');
            } else if (pd && pd.durum === 'DOLU' && pd.katman === 'FIZIKSEL') {
                detail = pd.kalip_kod || (pd.physical_snapshot_stale ? 'Fiziksel (eski snapshot)' : 'Fiziksel kurulum');
            } else if (pd && pd.durum === 'DOGRULANMALI') {
                var lr2 = pd.last_physical_record || pd.physical_snapshot || '';
                var lrDate = lr2 ? String(lr2).split(' ')[0] : '';
                if (pd.kalip_kod || lrDate) {
                    detail = '__STACK__';
                }
            }
            // ENJ_IST_PARITY_FIX: KAPALI = fiziksel execution durdurulmuş, planlama açısından BOŞ/uygun
            var gateOpen = enjIstasyonSelectionGateOpen();
            var gateKalipBlock = !gateOpen && enjIstasyonGateBlockReason() === 'kalip';
            var disabled = !gateOpen || !slot || durum === 'PLANLI' || durum === 'DOLU' ||
                durum === 'SETUP' || durum === 'ARIZA';
            if (gateOpen && !disabled) uygunSayisi++;
            var isChecked = gateOpen && state.enj.istasyonlar.indexOf(i) >= 0;
            /* durum sınıfı: bos / planli / dolu / dogrulanmali */
            var durumCls = durum === 'PLANLI' ? 'planli' :
                durum === 'DOGRULANMALI' ? 'dogrulanmali' :
                (durum === 'DOLU' || durum === 'SETUP' || durum === 'ARIZA') ? 'dolu' : 'bos';
            var durumLbl = durum === 'KAPALI' ? 'BOŞ' : durum === 'DOGRULANMALI' ? enjUnknownStatusUiLabel() :
                (durum === 'BOS' ? 'BOŞ' : durum);
            var lbl = document.createElement('label');
            lbl.className = 'up-ist-card ' + durumCls +
                (isChecked ? ' selected' : '') +
                (disabled ? ' disabled' : '');
            var detailHtml = '';
            if (detail === '__STACK__' && pd && pd.durum === 'DOGRULANMALI') {
                var lr3 = pd.last_physical_record || pd.physical_snapshot || '';
                var lrD = lr3 ? String(lr3).split(' ')[0] : '—';
                detailHtml = '<span class="up-ist-detail-stack">' +
                    (pd.kalip_kod ? '<span class="up-ist-sub">Son bilinen: ' + esc(pd.kalip_kod) + '</span>' : '') +
                    '<span class="up-ist-sub">' + esc(lrD) + '</span></span>';
            } else if (detail) {
                detailHtml = '<span class="up-ist-detail">' + esc(detail) + '</span>';
            }
            if (gateKalipBlock) {
                detailHtml = '<span class="up-ist-sub up-ist-gate-hint">Önce kalıp seçin</span>' + detailHtml;
            }
            lbl.innerHTML =
                '<input type="checkbox" value="' + i + '"' +
                  (disabled ? ' disabled' : '') +
                  (isChecked ? ' checked' : '') + '>' +
                '<span class="up-ist-dot ' + durumCls + '"></span>' +
                '<span class="up-ist-kod">İST' + i + '</span>' +
                '<span class="up-ist-durum">' + durumLbl + '</span>' +
                detailHtml;
            var cb = lbl.querySelector('input');
            cb.addEventListener('change', function (ev) {
                var n = parseInt(ev.target.value, 10);
                if (!enjTryToggleIstasyon(n, ev.target.checked, m, ev.target)) {
                    ev.target.checked = state.enj.istasyonlar.indexOf(n) >= 0;
                }
            });
            lbl.addEventListener('click', function (ev) {
                if (!enjIstasyonSelectionGateOpen() || enjIstasyonDisabledAtDate(i, m)) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    cb.checked = state.enj.istasyonlar.indexOf(i) >= 0;
                }
            }, true);
            el.appendChild(lbl);
        }
        enjUpdateIstasyonOzetSatir(m, uygunSayisi);
        enjUpdateCentralStatus();
    }

    function enjSelectSlot(slot) {
        state.enj.istasyonAvailabilitySeq++;
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
        enjSyncKalipAdediFromStations();
        enjFetchIlkUygun(true);
        enjSyncInputsFromDom();
        enjFetchIstasyonPlanDurum(function () {
            if (m) enjRenderIstasyonGrid(m);
        });
        if (state.enj._hizGosterimVeri) {
            enjSonHaftaHizRender(state.enj._hizGosterimVeri, state.enj.makineKod);
        }
        if (state.enj.makineKod && state.enj._sonHaftaVeri) {
            enjLoadAutoRefFromSonHafta(state.enj.makineKod, slot);
        }
        enjEvaluateShiftStartBoundary();
        enjUpdateHesapBtn();
    }

    function enjYukleKapasite() {
        enjYukleSlotOzet(function () {
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

    /* ACCORDION TOGGLE — Makine Hız Geçmişi */
    function enjInitSonHaftaToggle() {
        var btn = $('upEnjSonHaftaToggle');
        var icerik = $('upEnjSonHaftaIcerik');
        if (!btn || !icerik) return;
        // Yalnızca bir kez bağla
        if (btn._toggleBound) return;
        btn._toggleBound = true;
        btn.addEventListener('click', function () {
            var expanded = btn.getAttribute('aria-expanded') === 'true';
            btn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            if (expanded) {
                icerik.hidden = true;
            } else {
                icerik.hidden = false;
            }
            // chevron güncelle
            var chev = btn.querySelector('.up-enj-son-hafta-chevron');
            if (chev) chev.textContent = expanded ? '▸' : '▾';
        });
    }

    function enjSonHaftaSlotDisplay(slotInfo) {
        if (!slotInfo) return { kind: 'no_data', text: 'Veri yok', cls: 'up-shh-yok', tip: 'Veri yok' };
        if (slotInfo.status === 'draft_zero') {
            var tipDraft = slotInfo.label || 'Üretim verisi girilmemiş';
            if (slotInfo.tooltip) tipDraft = tipDraft + ' · ' + slotInfo.tooltip;
            return { kind: 'status', text: 'Veri girilmemiş', cls: 'up-shh-draft', tip: tipDraft };
        }
        if (slotInfo.status === 'calismadi') {
            var tipCal = slotInfo.label || 'Çalışmadı';
            if (slotInfo.tooltip) tipCal = tipCal + ' · ' + slotInfo.tooltip;
            return { kind: 'status', text: 'Çalışmadı', cls: 'up-shh-calismadi', tip: tipCal };
        }
        if (slotInfo.status === 'no_data') {
            var tipNo = 'Veri yok';
            if (slotInfo.tooltip) tipNo = tipNo + ' · ' + slotInfo.tooltip;
            return { kind: 'status', text: 'Veri yok', cls: 'up-shh-yok', tip: tipNo };
        }
        if (slotInfo.status === 'ok') {
            var med = Math.round(slotInfo.median || 0);
            var n = slotInfo.sample || 0;
            var wd = slotInfo.window_days || 7;
            var tipOk = slotInfo.label || '';
            if (slotInfo.tooltip) tipOk = tipOk ? (tipOk + ' · ' + slotInfo.tooltip) : slotInfo.tooltip;
            return {
                kind: 'ok',
                speed: med + ' tur/vd',
                sample: n + ' vardiya',
                window: wd + ' gün',
                tip: tipOk,
                lowConf: !!slotInfo.low_confidence
            };
        }
        return { kind: 'status', text: 'Veri yok', cls: 'up-shh-yok', tip: 'Veri yok' };
    }

    function enjSonHaftaSlotRow(slotInfo, slotLbl, isSlotSelected) {
        var disp = enjSonHaftaSlotDisplay(slotInfo);
        var badgeCls = 'up-shh-slot-badge' + (isSlotSelected ? ' up-shh-slot-badge-on' : '');
        var html = '<div class="up-shh-slot-row">';
        html += '<span class="' + badgeCls + '">' + esc(slotLbl) + '</span>';
        if (disp.kind === 'ok') {
            var lc = disp.lowConf
                ? ('<span class="up-shh-lc" title="' + esc(slotInfo.label || disp.tip) + '" aria-label="Düşük güven">!</span>')
                : '';
            html += '<span class="up-shh-speed">' + lc + esc(disp.speed) + '</span>';
            html += '<span class="up-shh-pill up-shh-pill-n">' + esc(disp.sample) + '</span>';
            html += '<span class="up-shh-pill up-shh-pill-w">' + esc(disp.window) + '</span>';
        } else {
            html += '<span class="up-shh-status ' + (disp.cls || '') + '">' + esc(disp.text) + '</span>';
        }
        html += '</div>';
        return html;
    }

    function enjSonHaftaVardiyaBlock(vdKey, vdLabel, vdIconCls, mkVeri, isSelectedMachine, secilenSlot) {
        var vd = mkVeri || {};
        var html = '<div class="up-shh-vd-block up-shh-' + vdKey + '">';
        html += '<div class="up-shh-vd-head"><span class="up-shh-vd-ico ' + vdIconCls + '" aria-hidden="true"></span>';
        html += '<span class="up-shh-vd-lbl">' + esc(vdLabel) + '</span></div>';
        html += '<div class="up-shh-slot-rows">';
        html += enjSonHaftaSlotRow(vd.A, 'A', isSelectedMachine && secilenSlot === 'A');
        html += enjSonHaftaSlotRow(vd.B, 'B', isSelectedMachine && secilenSlot === 'B');
        html += '</div></div>';
        return html;
    }

    function enjSonHaftaHizRender(payload, secilenMakine) {
        var kutu = $('upEnjSonHaftaHiz');
        var icerik = $('upEnjSonHaftaIcerik');
        if (!kutu || !icerik) return;

        var liste = (payload && payload.makineler) ? payload.makineler : [];
        if (!liste.length) {
            kutu.style.display = 'none';
            return;
        }

        var secilenSlot = (state.enj.slot || 'A').toUpperCase();
        var html = '<div class="up-shh-panel">';

        liste.forEach(function (mk) {
            var mkod = mk.makine_kod;
            var isSelected = secilenMakine && mkod === secilenMakine;
            var rowClass = 'up-shh-mk-row' + (isSelected ? ' up-shh-secili' : '');
            html += '<div class="' + rowClass + '">';
            html += '<div class="up-shh-mkod">' + esc(mkod) + '</div>';
            html += enjSonHaftaVardiyaBlock('gunduz', 'Gündüz', 'up-shh-ico-sun', mk.gunduz, isSelected, secilenSlot);
            html += enjSonHaftaVardiyaBlock('gece', 'Gece', 'up-shh-ico-moon', mk.gece, isSelected, secilenSlot);
            html += '</div>';
        });
        html += '</div>';

        icerik.innerHTML = html;
        kutu.style.display = '';
        var btn = $('upEnjSonHaftaToggle');
        if (btn) {
            btn.setAttribute('aria-expanded', 'false');
            var chev = btn.querySelector('.up-enj-son-hafta-chevron');
            if (chev) chev.textContent = '▸';
        }
        icerik.hidden = true;
        enjInitSonHaftaToggle();
    }

    function enjYukleSonHaftaHints() {
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
                            state.enj._sonHaftaVeri = d.makineler;
                            state.enj._sonHaftaDays = days;
                            if (state.enj.makineKod) {
                                enjLoadAutoRefFromSonHafta(state.enj.makineKod, state.enj.slot);
                            } else {
                                enjUpdateAutoRefHints();
                            }
                        } else {
                            _fetch(remaining[0], remaining.slice(1));
                        }
                    } else {
                        state.enj._sonHaftaVeri = null;
                        enjUpdateAutoRefHints();
                    }
                })
                .catch(function () {
                    state.enj._sonHaftaVeri = null;
                });
        }
        _fetch(7, [30, 90]);
    }

    function enjYukleSonHaftaHiz(secilenMakine) {
        var kutu = $('upEnjSonHaftaHiz');
        var icerik = $('upEnjSonHaftaIcerik');
        if (!kutu || !icerik) return;
        kutu.style.display = '';
        icerik.hidden = true;
        icerik.innerHTML = '<span class="up-enj-son-hafta-yukleniyor">Yükleniyor…</span>';
        enjInitSonHaftaToggle();

        fetch('/planlama/uretim-plan/api/enj/makine-hiz-gosterim', { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.ok) {
                    state.enj._hizGosterimVeri = d;
                    enjSonHaftaHizRender(d, secilenMakine || state.enj.makineKod);
                } else {
                    state.enj._hizGosterimVeri = null;
                    icerik.innerHTML = '<span class="up-shh-yok">Veri alınamadı</span>';
                }
            })
            .catch(function () {
                state.enj._hizGosterimVeri = null;
                icerik.innerHTML = '<span class="up-shh-yok">Veri alınamadı</span>';
            });

        enjYukleSonHaftaHints();
    }

    function enjBuildKalipSelect() {
        var sel = $('upEnjKalip');
        if (!sel) return;
        sel.innerHTML = '<option value="">— Kalıp Seçin —</option>';
        var kodCount = {};
        state.enj.kaliplar.forEach(function (k) {
            var key = k.kalip_kod || '';
            kodCount[key] = (kodCount[key] || 0) + 1;
        });
        var kodIndex = {};
        state.enj.kaliplar.forEach(function (k) {
            var o = document.createElement('option');
            o.value = k.id;
            var label = k.kalip_kod || ('ID ' + k.id);
            if (k.model_kod) label += ' · ' + k.model_kod;
            var key = k.kalip_kod || '';
            if (kodCount[key] > 1) {
                kodIndex[key] = (kodIndex[key] || 0) + 1;
                label += ' · Kayıt ' + kodIndex[key];
            }
            o.textContent = label;
            o.dataset.kod = k.kalip_kod;
            o.dataset.kbc = k.kalip_basi_cift || '';
            sel.appendChild(o);
        });
    }

    function _enjKalipListeTemizle() {
        /* Sipariş değiştiğinde önceki kalıp listesini ve seçimi sıfırla */
        state.enj.kaliplar = [];
        state.enj.libraryKalipList = [];
        state.enj.kalipId = null;
        state.enj.kalipKod = null;
        state.enj.kalipBasiCift = null;
        state.enj.libraryUuid = null;
        state.enj.libraryKalipMeta = null;
        var sel = $('upEnjKalip');
        if (sel) { sel.innerHTML = '<option value="">— Kalıp Seçin —</option>'; sel.disabled = true; }
        var libList = $('upEnjKalipLibraryList');
        if (libList) libList.innerHTML = '';
        enjRenderLibrarySummary(null);
    }

    function enjToggleLibraryKalipUi(useLibrary) {
        var src = $('upEnjKalipLibrarySource');
        var list = $('upEnjKalipLibraryList');
        var legacyLabel = $('upEnjKalipLegacyLabel');
        var sel = $('upEnjKalip');
        if (src) src.style.display = useLibrary ? '' : 'none';
        if (list) list.style.display = useLibrary ? '' : 'none';
        if (legacyLabel) legacyLabel.style.display = useLibrary ? 'none' : '';
        if (sel) sel.style.display = useLibrary ? 'none' : '';
    }

    function enjLibraryFamilyVariantLabel(item) {
        var fam = (item && item.product_family) || '';
        var varnt = (item && item.product_variant) || '';
        if (fam && varnt && fam !== varnt) return fam + ' · ' + varnt;
        return varnt || fam || '—';
    }

    /** PHASE_7O3C: visible_mold_code tek başına kimlik değil — kod + varyant + asorti. */
    function enjLibraryMoldIdentityLabel(item) {
        if (!item) return '—';
        var parts = [];
        if (item.visible_mold_code) parts.push(item.visible_mold_code);
        if (item.product_variant) parts.push(item.product_variant);
        if (item.assortment) parts.push(item.assortment);
        return parts.length ? parts.join(' · ') : '—';
    }

    function enjLibraryDetailLine(item) {
        if (!item) return '';
        return [
            item.assortment || '',
            item.pairs_per_cycle != null ? ('Kalıp İçi ' + item.pairs_per_cycle + ' Çift') : '',
            item.physical_mold_total != null ? ('Fiziksel ' + item.physical_mold_total + ' adet') : '',
        ].filter(Boolean).join(' · ');
    }

    function enjLibraryThumbEl(item) {
        if (item && item.image_url) {
            var img = document.createElement('img');
            img.className = 'up-lib-kalip-thumb';
            img.alt = '';
            img.src = item.image_url;
            img.onerror = function () {
                var ph = document.createElement('div');
                ph.className = 'up-lib-kalip-thumb-ph';
                ph.textContent = 'Görsel yok';
                if (this.parentNode) this.replaceWith(ph);
            };
            return img;
        }
        var ph = document.createElement('div');
        ph.className = 'up-lib-kalip-thumb-ph';
        ph.textContent = 'Görsel yok';
        return ph;
    }

    // PHASE_7M: Compact decision card for selected mold summary
    // PHASE_7N3: Library özet kartı — "X Kalıp · Kalıp İçi Y Çift · Z İstasyon · Tur Başı T Çift · SSS sn"
    function enjRenderLibrarySummary(item) {
        var box = $('upEnjLibraryKalipSummary');
        if (!box) return;
        if (!item) {
            box.style.display = 'none';
            box.innerHTML = '';
            return;
        }
        var phys = item.physical_mold_total;
        var physNum = (typeof phys === 'number') ? phys : null;
        var istSay = (state.enj.istasyonlar || []).length;
        var kalipIciCift = (item.pairs_per_cycle != null) ? parseFloat(item.pairs_per_cycle) : null;
        // Tur başı = seçili istasyon × pairs_per_cycle (sadece istasyon seçilmişse)
        var turBasiCift = (istSay > 0 && kalipIciCift != null) ? istSay * kalipIciCift : null;

        box.innerHTML = '';
        var card = document.createElement('div');
        card.className = 'up-ws-sum-card';

        // Başlık satırı
        var head = document.createElement('div');
        head.className = 'up-ws-sum-head';
        var titleEl = document.createElement('span');
        titleEl.className = 'up-ws-sum-title';
        titleEl.textContent = enjLibraryMoldIdentityLabel(item);
        var badge = document.createElement('span');
        badge.className = 'up-ws-sum-badge';
        badge.textContent = item.selectable ? '✓ Seçilebilir' : 'Seçilemez';
        head.appendChild(titleEl);
        head.appendChild(badge);
        card.appendChild(head);

        // Asorti + varyant satırı
        var famRow = document.createElement('div');
        famRow.className = 'up-ws-sum-row';
        var famParts = [];
        if (item.product_variant) famParts.push(esc(item.product_variant));
        if (item.assortment) famParts.push('Asorti ' + esc(item.assortment));
        if (item.model_code) famParts.push(esc(item.model_code));
        famRow.innerHTML = famParts.join(' · ') || '&nbsp;';
        card.appendChild(famRow);

        // PHASE_7N4: Ana sayısal özet — "[ist] Kalıp · Kalıp İçi [ppc] Çift · Tur Başı [tot] Çift · [sn]"
        var numRow = document.createElement('div');
        numRow.className = 'up-ws-sum-row';
        var numParts = [];
        // X Kalıp — istasyon seçilmişse seçili adet, yoksa fiziksel toplam
        var displayKalip = istSay > 0 ? istSay : physNum;
        if (displayKalip != null) {
            numParts.push('<b>' + esc(String(displayKalip)) + '</b> Kalıp');
        }
        // Kalıp İçi Çift
        if (kalipIciCift != null) {
            numParts.push('Kalıp İçi <b>' + esc(String(kalipIciCift)) + '</b> Çift');
        }
        // Tur Başı Çift — sadece istasyon seçilmişse göster
        if (turBasiCift != null) {
            numParts.push('Tur Başı <b>' + esc(String(turBasiCift)) + '</b> Çift');
        }
        // Pişme süresi
        if (item.cooking_time_label) {
            numParts.push('<b>' + esc(item.cooking_time_label) + '</b>');
        } else {
            numParts.push('<span class="up-ws-info-warn">Pişme süresi doğrulanmalı</span>');
        }
        numRow.innerHTML = numParts.join(' &nbsp;·&nbsp; ');
        card.appendChild(numRow);

        // Seri blokları
        var seriesDisplay = item.series_display || {};
        var seriesLines = seriesDisplay.lines || [];
        if (seriesLines.length) {
            var serDiv = document.createElement('div');
            serDiv.className = 'up-ws-sum-series';
            enjBuildSeriesBlocks(serDiv, seriesDisplay);
            card.appendChild(serDiv);
        }

        // PHASE_7N4: Kullanım özeti — istasyon seçilmişse daima göster
        if (physNum !== null && istSay > 0) {
            var useDiv = document.createElement('div');
            useDiv.className = 'up-ws-sum-usage';
            if (istSay >= physNum) {
                // Tüm kalıplar kullanılıyor: "3/3 kalıp"
                useDiv.innerHTML = 'Mevcut kullanım: <b>' + esc(istSay + '/' + physNum + ' kalıp') + '</b>';
            } else {
                var unusedNum = physNum - istSay;
                useDiv.innerHTML = 'Mevcut kullanım: <b>' + esc(istSay + '/' + physNum + ' kalıp') + '</b>'
                    + ' &nbsp;·&nbsp; <span>' + unusedNum + ' kalıp kullanılmıyor</span>';
            }
            card.appendChild(useDiv);
        }

        box.appendChild(card);
        box.style.display = '';
    }

    // PHASE_7N: enjWsRequestMapping kaldırıldı (mapping UI yok)

    // PHASE_7M: Compact horizontal grid for series blocks
    function enjWsAppendSeriesStack(parent, item) {
        var sd = item.series_display || {};
        var lines = sd.lines || [];
        if (!lines.length) return;
        var stack = document.createElement('div');
        stack.className = 'up-ws-series-stack';
        lines.forEach(function (ln) {
            var block = document.createElement('div');
            block.className = 'up-ws-series-row' +
                (ln.coverage === 'covered' ? ' covered' : '') +
                (ln.coverage === 'outside_order' ? ' outside_order' : '') +
                (ln.missing_qty ? ' missing_qty' : '');
            var lbl = document.createElement('div');
            lbl.className = 'up-ws-series-label';
            // PHASE_7N: duplikat numara normalize ("23/24-23/24" → "23/24")
            lbl.textContent = enjNormSeriesLabel(ln.numara_asorti) || '—';
            var qty = document.createElement('div');
            qty.className = 'up-ws-series-qty' + (ln.missing_qty ? ' missing' : '');
            qty.textContent = ln.missing_qty ? 'Doğrulanmalı' : (ln.kalip_adedi != null ? ln.kalip_adedi + ' adet' : '—');
            block.appendChild(lbl);
            block.appendChild(qty);
            stack.appendChild(block);
        });
        if (sd.coverage_note) {
            var note = document.createElement('div');
            note.className = 'up-ws-series-note';
            note.textContent = sd.coverage_note;
            stack.appendChild(note);
        }
        parent.appendChild(stack);
    }

    // PHASE_7M: Single-line placement hint, correct terminology
    function enjWsAppendPlacement(parent, item) {
        var pl = item.placement_recommendation;
        if (!pl || !pl.available) return;
        var primaryLabels = (pl.primary || []).map(function (p) { return p.label; });
        var altLabels = (pl.alternatives || []).slice(0, 1); // en fazla 1 alternatif
        if (!primaryLabels.length && !altLabels.length) return;
        var box = document.createElement('div');
        box.className = 'up-ws-placement';
        if (primaryLabels.length) {
            var pLine = document.createElement('div');
            pLine.className = 'up-ws-placement-inline';
            pLine.textContent = primaryLabels.join(' + ');
            box.appendChild(pLine);
        }
        altLabels.forEach(function (a) {
            var aLine = document.createElement('div');
            aLine.className = 'up-ws-alt-inline';
            aLine.textContent = a;
            box.appendChild(aLine);
        });
        parent.appendChild(box);
    }

    // PHASE_7M/7N: series blocks reused in summary card, with label normalize
    function enjBuildSeriesBlocks(container, seriesDisplay) {
        var lines = (seriesDisplay || {}).lines || [];
        lines.forEach(function (ln) {
            var block = document.createElement('div');
            block.className = 'up-ws-series-row' + (ln.missing_qty ? ' missing_qty' : '');
            var lbl = document.createElement('div');
            lbl.className = 'up-ws-series-label';
            lbl.textContent = enjNormSeriesLabel(ln.numara_asorti) || '—';
            var qty = document.createElement('div');
            qty.className = 'up-ws-series-qty' + (ln.missing_qty ? ' missing' : '');
            qty.textContent = ln.missing_qty ? 'Doğrulanmalı' : (ln.kalip_adedi != null ? ln.kalip_adedi + ' adet' : '—');
            block.appendChild(lbl);
            block.appendChild(qty);
            container.appendChild(block);
        });
    }

    function enjSelectLibraryKalip(item) {
        // PHASE_7E: Explicit selection only — user must click "Seç" button.
        // selected_library_uuid is only set here; never auto-assigned.
        var e = state.enj;
        if (!item || !item.selectable) return;
        var prevUuid = e.libraryUuid;
        if (e.istasyonlar.length && prevUuid !== item.library_uuid) {
            enjClearIstasyonSecimleri(
                'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.');
        }
        // UUID-only identity: identify mold solely by library_uuid (not legacy_enj_kalip_id or visible_mold_code).
        e.libraryUuid = item.library_uuid;
        e.libraryKalipMeta = item;
        e.kalipId = item.legacy_enj_kalip_id || null;
        e.kalipKod = item.visible_mold_code || null;
        e.kalipBasiCift = item.pairs_per_cycle != null ? parseFloat(item.pairs_per_cycle) : null;
        enjBuildLibraryKalipList();
        enjRenderLibrarySummary(item);
        enjUpdateKalipSeciliCards();
        enjUpdateFizikselKalipDisplay();
        enjHesapGizle();
        enjYukleKalipGoz();
        enjTrimIstasyonlarToPhysLimit((e.gridData || []).find(function (x) {
            return (x.makine_id || x.id) === e.makineId;
        }));
        enjCheckFizikselKalipLimit((e.istasyonlar || []).length);
        var mSel = (e.gridData || []).find(function (x) {
            return (x.makine_id || x.id) === e.makineId;
        });
        if (mSel) enjRenderIstasyonGrid(mSel);
        enjUpdateHesapBtn();
        enjUpdateCentralStatus();
    }

    function enjBuildLibraryKalipList() {
        // PHASE_7E: Explicit selection — no auto-select, user must click "Seç" button.
        // selected_library_uuid starts null; only set by explicit user action.
        // PHASE_7J: Also refresh workspace if open.
        var host = $('upEnjKalipLibraryList');
        if (host) {
            host.style.display = 'none'; // inline list hidden; selection via workspace
        }
        // Refresh workspace content if open
        var layout = document.querySelector('.up-step2-layout');
        if (layout && layout.classList.contains('kalip-secim-aktif')) {
            enjWsRender();
        }
        var e = state.enj;
        (e.libraryKalipList || []).forEach(function (item) {
            var isSelected = e.libraryUuid !== null && e.libraryUuid === item.library_uuid;
            var row = document.createElement('div');
            row.className = 'up-lib-kalip-item' +
                (item.selectable ? '' : ' blocked') +
                (isSelected ? ' selected' : '');
            row.setAttribute('data-library-uuid', item.library_uuid || '');
            row.setAttribute('aria-label', [
                enjLibraryMoldIdentityLabel(item), item.model_code, enjLibraryDetailLine(item),
            ].filter(Boolean).join(' '));
            var meta = document.createElement('div');
            meta.className = 'up-lib-kalip-meta';
            var code = document.createElement('div');
            code.className = 'up-lib-kalip-code';
            code.textContent = enjLibraryMoldIdentityLabel(item);
            var fam = document.createElement('div');
            fam.className = 'up-lib-kalip-family';
            fam.textContent = item.model_code || '—';
            var sub = document.createElement('div');
            sub.className = 'up-lib-kalip-sub';
            sub.textContent = enjLibraryDetailLine(item);
            meta.appendChild(code);
            meta.appendChild(fam);
            meta.appendChild(sub);
            if (!item.selectable && item.block_reasons && item.block_reasons.length) {
                var blk = document.createElement('div');
                blk.className = 'up-lib-kalip-block';
                blk.textContent = '⚠ ' + item.block_reasons.join(' · ');
                meta.appendChild(blk);
            }
            row.appendChild(enjLibraryThumbEl(item));
            row.appendChild(meta);
            if (item.selectable) {
                // PHASE_7E: Explicit "Seç" button — user must click to select.
                // Tüm satır click kaldırıldı; yalnızca buton explicit seçim yapar.
                var secBtn = document.createElement('button');
                secBtn.type = 'button';
                secBtn.className = 'up-lib-kalip-sec-btn' + (isSelected ? ' active' : '');
                secBtn.textContent = isSelected ? '✓ Seçildi' : 'Seç';
                secBtn.setAttribute('aria-label', 'Kalıbı seç: ' + enjLibraryMoldIdentityLabel(item));
                (function(capturedItem, capturedBtn) {
                    capturedBtn.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        enjSelectLibraryKalip(capturedItem);
                    });
                })(item, secBtn);
                row.appendChild(secBtn);
            }
            host.appendChild(row);
        });
    }

    // ── PHASE_7O1: Makine A/B Doluluk Takvimi (inline workspace) ─────────────

    function enjTakvimAnchorDefault() {
        var e = state.enj;
        var src = e.baslangic || e.baslangicOneri;
        if (!src && $('upFormBas') && $('upFormBas').value) src = $('upFormBas').value;
        if (src) return String(src).slice(0, 10);
        var now = new Date();
        return now.getFullYear() + '-' +
            String(now.getMonth() + 1).padStart(2, '0') + '-' +
            String(now.getDate()).padStart(2, '0');
    }

    function enjShiftAnchorDate(isoDate, deltaDays) {
        var parts = String(isoDate || '').slice(0, 10).split('-');
        if (parts.length !== 3) return enjTakvimAnchorDefault();
        var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        d.setDate(d.getDate() + deltaDays);
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
    }

    function enjTakvimParams(makineId, anchor) {
        var e = state.enj;
        var q = 'makine_id=' + encodeURIComponent(makineId) +
            '&anchor=' + encodeURIComponent(anchor || enjTakvimAnchorDefault()) +
            '&num_days=' + encodeURIComponent(e.takvimNumDays || 4) +
            '&calisma_modu=' + encodeURIComponent(e.calismaModu || 'GUNDUZ_GECE') +
            '&hafta_sonu_calisma=' + encodeURIComponent(e.haftaSonu || 'HAYIR');
        if (e.haftaSonu === 'EVET' && e.hsVardiya) {
            q += '&hafta_sonu_vardiya=' + encodeURIComponent(e.hsVardiya);
        }
        if (e.baslangic) q += '&secim_baslangic=' + encodeURIComponent(e.baslangic);
        if (e.slot) q += '&secim_slot=' + encodeURIComponent(e.slot);
        return q;
    }

    function enjFmtTakvimGun(isoDate) {
        if (!isoDate) return '—';
        var p = String(isoDate).slice(0, 10).split('-');
        if (p.length !== 3) return isoDate;
        return p[2] + '.' + p[1];
    }

    function enjGanttParseMs(iso) {
        if (!iso) return NaN;
        return new Date(String(iso).trim().replace(' ', 'T')).getTime();
    }

    function enjGanttWindowMeta(data) {
        var cells = [];
        ['A', 'B'].forEach(function (slot) {
            cells = cells.concat((data.sides[slot] && data.sides[slot].hucreler) || []);
        });
        if (!cells.length) return null;
        var winStart = enjGanttParseMs(cells[0].win_bas);
        var winEnd = enjGanttParseMs(cells[cells.length - 1].win_bit);
        var dayMap = {};
        cells.forEach(function (c) {
            if (!dayMap[c.tarih]) dayMap[c.tarih] = { gunduz: null, gece: null };
            dayMap[c.tarih][c.vardiya] = c;
        });
        var days = Object.keys(dayMap).sort();
        return { winStart: winStart, winEnd: winEnd, winMs: winEnd - winStart, days: days, dayMap: dayMap, cells: cells };
    }

    function enjGanttCollectPlans(hucreler) {
        var byId = {};
        (hucreler || []).forEach(function (cell) {
            (cell.planlar || []).forEach(function (p) {
                if (!byId[p.plan_id]) {
                    byId[p.plan_id] = {
                        plan_id: p.plan_id,
                        sip_no: p.sip_no,
                        model: p.model,
                        istasyon_sayisi: p.istasyon_sayisi,
                        istasyonlar: p.istasyonlar,
                        baslangic: p.baslangic,
                        bitis: p.bitis,
                        bas_gosterim: p.bas_gosterim,
                        bit_gosterim: p.bit_gosterim,
                        bitis_dogrulanamadi: p.bitis_dogrulanamadi,
                        toplam_istasyon: cell.toplam_istasyon || 8,
                    };
                }
            });
        });
        return Object.keys(byId).map(function (k) { return byId[k]; });
    }

    function enjGanttBarGeom(plan, meta) {
        var pStart = enjGanttParseMs(plan.baslangic);
        var pEnd = plan.bitis_dogrulanamadi ? meta.winEnd : enjGanttParseMs(plan.bitis);
        if (isNaN(pStart)) return null;
        if (plan.bitis_dogrulanamadi) pEnd = meta.winEnd;
        if (isNaN(pEnd) || pEnd <= meta.winStart || pStart >= meta.winEnd) return null;
        var visStart = Math.max(pStart, meta.winStart);
        var visEnd = Math.min(pEnd, meta.winEnd);
        var left = ((visStart - meta.winStart) / meta.winMs) * 100;
        var width = ((visEnd - visStart) / meta.winMs) * 100;
        return {
            left: left,
            width: Math.max(width, 0.35),
            clipLeft: pStart < meta.winStart,
            clipRight: !plan.bitis_dogrulanamadi && pEnd > meta.winEnd,
        };
    }

    function enjGanttSlotGeom(cell, meta) {
        var s = enjGanttParseMs(cell.win_bas);
        var e = enjGanttParseMs(cell.win_bit);
        if (isNaN(s) || isNaN(e)) return null;
        return {
            left: ((s - meta.winStart) / meta.winMs) * 100,
            width: ((e - s) / meta.winMs) * 100,
        };
    }

    function enjGanttBarLabel(plan) {
        var total = plan.toplam_istasyon || 8;
        var occ = plan.istasyon_sayisi || 0;
        return esc(String(plan.sip_no || '—')) + ' · ' + esc(String(plan.model || '—')) + ' · ' + occ + '/' + total;
    }

    function enjRenderGanttDetail(plan, slot, makineKod) {
        var det = $('upTakvimWsDetail');
        if (!det || !plan) return;
        var total = plan.toplam_istasyon || 8;
        var occ = plan.istasyon_sayisi || 0;
        var free = Math.max(0, total - occ);
        var freeLine = (occ > 0 && occ < total)
            ? '<div class="up-gantt-detail-free">' + free + ' istasyon kullanılabilir</div>'
            : '';
        det.innerHTML =
            '<div class="up-gantt-detail-grid">' +
            '<div><span class="up-gantt-detail-lbl">CPS Plan</span> #' + esc(String(plan.plan_id)) + '</div>' +
            '<div><span class="up-gantt-detail-lbl">Sipariş</span> ' + esc(String(plan.sip_no || '—')) + '</div>' +
            '<div><span class="up-gantt-detail-lbl">Model</span> ' + esc(String(plan.model || '—')) + '</div>' +
            '<div><span class="up-gantt-detail-lbl">Makine</span> ' + esc(makineKod || '—') + ' / ' + esc(slot) + ' Tarafı</div>' +
            '<div><span class="up-gantt-detail-lbl">İstasyon</span> ' + occ + '/' + total + '</div>' +
            '<div><span class="up-gantt-detail-lbl">Başlangıç</span> ' + esc(plan.bas_gosterim || '—') + '</div>' +
            '<div><span class="up-gantt-detail-lbl">Bitiş</span> ' + esc(plan.bit_gosterim || '—') + '</div>' +
            '</div>' + freeLine;
        det.style.display = '';
    }

    function enjSelectTakvimPlan(plan, slot) {
        var e = state.enj;
        e.takvimPlanDetay = { plan: plan, slot: slot };
        e.takvimSecim = null;
        var secBar = $('upTakvimWsSecim');
        if (secBar) secBar.style.display = 'none';
        enjRenderGanttDetail(plan, slot, e.takvimMakineKod);
        if (e.takvimData) enjRenderTakvimBody(e.takvimData);
    }

    function enjInitTakvimSideSelection(data) {
        if (!data || !data.sides) return;
        var e = state.enj;
        var slot = e.takvimActiveSlot;
        if (!slot || !data.sides[slot]) return;
        var side = data.sides[slot];
        var fs = side.first_selectable;
        var hucreler = side.hucreler || [];
        var match = null;
        if (fs && fs.iso) {
            match = hucreler.find(function (c) { return c.oneri_baslangic === fs.iso; });
        }
        if (!match) {
            match = hucreler.find(function (c) {
                var d = String(c.durum || '').toUpperCase();
                return (d === 'BOS' || d === 'SECIM') && c.selectable !== false && c.oneri_baslangic;
            });
        }
        if (match && match.oneri_baslangic) {
            enjSelectTakvimCell(slot, match.oneri_baslangic, match.durum || 'BOS', match);
        }
    }

    function enjSelectTakvimCell(slot, oneriIso, durum, cell) {
        if (!slot || !oneriIso) return;
        if (durum === 'HATA' || durum === 'TAM' || durum === 'KAPALI' || durum === 'KISMI') return;
        if (cell && cell.selectable === false) return;
        var e = state.enj;
        e.takvimActiveSlot = slot;
        e.takvimPlanDetay = null;
        var det = $('upTakvimWsDetail');
        if (det) { det.style.display = 'none'; det.innerHTML = ''; }
        e.takvimSecim = {
            slot: slot,
            oneri_baslangic: oneriIso,
            makine_id: e.takvimMakineId,
            makine_kod: e.takvimMakineKod,
            win_bas: cell && cell.win_bas,
            win_bit: cell && cell.win_bit,
            vardiya: enjVardiyaFromCell(cell),
        };
        var secBar = $('upTakvimWsSecim');
        var secMetin = $('upTakvimSecimMetin');
        if (secBar) secBar.style.display = '';
        if (secMetin) {
            secMetin.textContent = (e.takvimMakineKod || 'M') + ' / ' + slot + ' Tarafı · Önerilen başlangıç: ' +
                enjFmtDtApi(oneriIso);
        }
        if (e.takvimData) enjRenderTakvimBody(e.takvimData);
    }

    function enjShowGanttAdvisoryDetail(adv, anchorBtn) {
        var panel = $('upGanttAdvisoryDetail');
        if (!panel) return;
        if (!adv || !adv.stations || !adv.stations.length) {
            panel.hidden = true;
            panel.innerHTML = '';
            return;
        }
        var rows = adv.stations.map(function (st) {
            return '<li><strong>İST' + st.istasyon_no + '</strong> · Kalıp: ' + esc(st.kalip_kod || '—') +
                ' · Son kayıt: ' + esc(st.last_record || '—') +
                (st.guncel_rapor_yok ? ' · Güncel rapor yok' : '') + '</li>';
        }).join('');
        panel.innerHTML = '<div class="up-gantt-advisory-detail-head">' + esc(adv.short_label || '') + '</div><ul>' + rows + '</ul>';
        panel.hidden = false;
        if (anchorBtn && anchorBtn.scrollIntoView) {
            anchorBtn.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }

    function enjRenderTakvimBody(data) {
        var body = $('upTakvimWsBody');
        if (!body || !data || !data.sides) return;
        var meta = enjGanttWindowMeta(data);
        if (!meta) {
            body.innerHTML = '<p class="up-enj-md-hint">Takvim verisi yok</p>';
            return;
        }
        var nowMs = Date.now();
        var mk = data.makine.kod || 'M';
        var e = state.enj;

        var html = '<div class="up-gantt">';
        html += '<div class="up-gantt-axis"><div class="up-gantt-axis-label"></div><div class="up-gantt-axis-track">';
        meta.days.forEach(function (d) {
            html += '<div class="up-gantt-day-col">' +
                '<div class="up-gantt-day-head">' + esc(enjFmtTakvimGun(d)) + '</div>' +
                '<div class="up-gantt-shifts">' +
                '<span class="up-gantt-shift-head">Gündüz</span>' +
                '<span class="up-gantt-shift-head">Gece</span>' +
                '</div></div>';
        });
        html += '</div></div>';

        ['A', 'B'].forEach(function (slot) {
            var hucreler = (data.sides[slot] && data.sides[slot].hucreler) || [];
            var plans = enjGanttCollectPlans(hucreler);
            var advisory = (data.sides[slot] && data.sides[slot].physical_advisory) || {};
            var rowH = Math.max(34, plans.length * 20 + 12);
            var advHtml = '';
            if (advisory.needs_confirmation_count > 0) {
                advHtml = '<button type="button" class="up-gantt-advisory-chip" data-slot="' + esc(slot) +
                    '" title="Detay için tıklayın">' + esc(advisory.short_label || '') + '</button>';
            }
            var rowActive = e.takvimActiveSlot === slot;
            html += '<div class="up-gantt-row' + (rowActive ? ' active-side' : '') + '" style="min-height:' + rowH + 'px">' +
                '<div class="up-gantt-row-label">' + esc(mk) + ' / ' + slot + advHtml + '</div>' +
                '<div class="up-gantt-track" style="height:' + rowH + 'px">';

            hucreler.forEach(function (cell) {
                var geom = enjGanttSlotGeom(cell, meta);
                if (!geom) return;
                var endMs = enjGanttParseMs(cell.win_bit);
                var past = endMs <= nowMs;
                var durum = String(cell.durum || 'BOS').toUpperCase();
                if (durum === 'KAPALI') {
                    html += '<div class="up-gantt-slot kapali" style="left:' +
                        geom.left.toFixed(3) + '%;width:' + geom.width.toFixed(3) + '%;" ' +
                        'data-durum="KAPALI" title="Hafta sonu kapalı"></div>';
                    return;
                }
                var clickable = (durum === 'BOS' || durum === 'SECIM') && cell.selectable !== false;
                if (!clickable) return;
                html += '<div class="up-gantt-slot' + (past ? ' past' : '') + '" style="left:' +
                    geom.left.toFixed(3) + '%;width:' + geom.width.toFixed(3) + '%;" ' +
                    'data-slot="' + esc(slot) + '" data-oneri="' + esc(cell.oneri_baslangic || '') + '" ' +
                    'data-durum="' + esc(durum) + '" title="Boş alan — tıkla"></div>';
            });

            if (e.takvimSecim && e.takvimSecim.slot === slot && e.takvimSecim.win_bas) {
                var selCell = { win_bas: e.takvimSecim.win_bas, win_bit: e.takvimSecim.win_bit };
                var selGeom = enjGanttSlotGeom(selCell, meta);
                if (selGeom) {
                    html += '<div class="up-gantt-sel" style="left:' + selGeom.left.toFixed(3) +
                        '%;width:' + selGeom.width.toFixed(3) + '%;"></div>';
                }
            }

            plans.forEach(function (plan, idx) {
                var geom = enjGanttBarGeom(plan, meta);
                if (!geom) return;
                var cls = plan.bitis_dogrulanamadi ? 'kirmizi' : 'turuncu';
                var selPlan = e.takvimPlanDetay && e.takvimPlanDetay.plan &&
                    e.takvimPlanDetay.plan.plan_id === plan.plan_id;
                var top = 4 + idx * 20;
                html += '<div class="up-gantt-bar ' + cls + (selPlan ? ' selected' : '') +
                    (geom.clipLeft ? ' clip-left' : '') + (geom.clipRight ? ' clip-right' : '') +
                    '" style="left:' + geom.left.toFixed(3) + '%;width:' + geom.width.toFixed(3) +
                    '%;top:' + top + 'px;" data-plan-id="' + esc(String(plan.plan_id)) +
                    '" data-slot="' + esc(slot) + '" title="' + enjGanttBarLabel(plan) + '">' +
                    (geom.clipLeft ? '<span class="up-gantt-cont left" aria-hidden="true">◀</span>' : '') +
                    enjGanttBarLabel(plan) +
                    (geom.clipRight ? '<span class="up-gantt-cont right" aria-hidden="true">▶</span>' : '') +
                    '</div>';
            });

            html += '</div></div>';
        });
        html += '</div>';
        html += '<div class="up-gantt-legend" aria-label="Gantt renk açıklaması">' +
            '<span class="up-gantt-legend-item"><i class="up-gantt-legend-swatch draft"></i>Taslak üretim</span>' +
            '<span class="up-gantt-legend-item"><i class="up-gantt-legend-swatch plan"></i>Kayıtlı CPS planı</span>' +
            '<span class="up-gantt-legend-item"><i class="up-gantt-legend-swatch free"></i>Uygun zaman</span>' +
            '<span class="up-gantt-legend-item"><i class="up-gantt-legend-swatch unknown"></i>Güncel durum bilinmiyor</span>' +
            '<span class="up-gantt-legend-item"><i class="up-gantt-legend-swatch conflict"></i>Kesin çakışma</span>' +
            '</div>';
        html += '<div id="upGanttAdvisoryDetail" class="up-gantt-advisory-detail" hidden></div>';
        body.innerHTML = html;

        body.querySelectorAll('.up-gantt-advisory-chip').forEach(function (btn) {
            btn.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var slotKey = btn.getAttribute('data-slot');
                var adv = (data.sides[slotKey] && data.sides[slotKey].physical_advisory) || {};
                enjShowGanttAdvisoryDetail(adv, btn);
            });
        });
        body.querySelectorAll('.up-gantt-slot').forEach(function (el) {
            el.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var slotKey = el.getAttribute('data-slot');
                var hucreler = (data.sides[slotKey] && data.sides[slotKey].hucreler) || [];
                var match = hucreler.find(function (c) {
                    return c.oneri_baslangic === el.getAttribute('data-oneri');
                });
                enjSelectTakvimCell(slotKey, el.getAttribute('data-oneri'), el.getAttribute('data-durum'), match);
            });
        });
        body.querySelectorAll('.up-gantt-bar').forEach(function (el) {
            el.addEventListener('click', function (ev) {
                ev.stopPropagation();
                var pid = parseInt(el.getAttribute('data-plan-id'), 10);
                var slotKey = el.getAttribute('data-slot');
                var plans = enjGanttCollectPlans((data.sides[slotKey] || {}).hucreler || []);
                var plan = plans.find(function (p) { return p.plan_id === pid; });
                if (plan) enjSelectTakvimPlan(plan, slotKey);
            });
        });
    }

    function enjLoadTakvimData(cb) {
        var e = state.enj;
        if (!e.takvimMakineId) return;
        var anchor = e.takvimAnchor || enjTakvimAnchorDefault();
        var cacheKey = e.takvimMakineId + '|' + anchor + '|' + (e.baslangic || '') + '|' + (e.slot || '');
        e.takvimLoadingKey = cacheKey;
        var body = $('upTakvimWsBody');
        if (body) body.innerHTML = '<div class="up-loading">Yükleniyor…</div>';
        fetch('/planlama/uretim-plan/api/enj/makine-doluluk-takvim?' + enjTakvimParams(e.takvimMakineId, anchor),
            { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (e.takvimLoadingKey !== cacheKey) return;
                e.takvimLoadingKey = null;
                if (!d.ok) {
                    if (body) body.innerHTML = '<p class="up-enj-md-hint">' + esc(d.mesaj || 'Takvim yüklenemedi') + '</p>';
                    return;
                }
                e.takvimData = d;
                enjRenderTakvimBody(d);
                if (cb) cb(d);
            })
            .catch(function () {
                e.takvimLoadingKey = null;
                if (body) body.innerHTML = '<p class="up-enj-md-hint">Takvim yüklenemedi</p>';
            });
    }

    function enjOpenTakvimWorkspace(makineId, makineKod, triggerBtn) {
        enjCloseKalipWorkspace();
        enjMountTakvimAccordionPanels();
        var layout = document.querySelector('.up-step2-layout');
        var ws = $('upTakvimWorkspace');
        if (!layout || !ws) return;
        var e = state.enj;
        e.takvimMakineId = makineId;
        e.takvimMakineKod = makineKod;
        e.takvimAnchor = enjTakvimAnchorDefault();
        e.takvimSecim = null;
        e.takvimPlanDetay = null;
        e.takvimActiveSlot = (e.makineId === makineId && e.slot) ? e.slot : null;
        e.takvimTriggerBtn = triggerBtn || null;
        var title = $('upTakvimWsTitle');
        if (title) title.textContent = (makineKod || 'M') + ' · A/B DOLULUK TAKVİMİ';
        var secBar = $('upTakvimWsSecim');
        var detBar = $('upTakvimWsDetail');
        if (secBar) secBar.style.display = 'none';
        if (detBar) { detBar.style.display = 'none'; detBar.innerHTML = ''; }
        ws.style.display = 'flex';
        layout.classList.add('takvim-aktif');
        if (typeof enjShowMakinePanelToggle === 'function') enjShowMakinePanelToggle(true);
        if (e.draftPreview) {
            enjSetTakvimAccOpen(false);
        } else if (typeof enjCapacityConfirmedOk === 'function' && !enjCapacityConfirmedOk()) {
            enjSetTakvimAccOpen(true);
        } else {
            enjSetTakvimAccOpen(e.takvimAccOpen !== false);
        }
        if (typeof enjLoadKapasiteOneri === 'function') enjLoadKapasiteOneri();
        if (typeof enjRenderKapasitePanel === 'function') enjRenderKapasitePanel();
        enjUpdateTakvimAccSummary();
        enjUpdateTakvimHesapBtn();
        enjUpdateTakvimDraftBar();
        enjLoadTakvimData(function () {
            if (e.takvimActiveSlot) enjInitTakvimSideSelection(e.takvimData);
            if (typeof enjRefreshDraftBars === 'function') enjRefreshDraftBars();
        });
        var geriBtn = $('upTakvimWsGeri');
        if (geriBtn) setTimeout(function () { geriBtn.focus(); }, 50);
    }

    function enjCloseTakvimWorkspace() {
        var layout = document.querySelector('.up-step2-layout');
        var ws = $('upTakvimWorkspace');
        if (!layout) return;
        var e = state.enj;
        layout.classList.remove('takvim-aktif');
        layout.classList.remove('mak-panel-hidden');
        if (typeof enjShowMakinePanelToggle === 'function') enjShowMakinePanelToggle(false);
        if (ws) ws.style.display = '';
        var btn = e.takvimTriggerBtn;
        e.takvimSecim = null;
        e.takvimPlanDetay = null;
        e.takvimActiveSlot = null;
        e.takvimLoadingKey = null;
        var secBar = $('upTakvimWsSecim');
        if (secBar) secBar.style.display = 'none';
        var detBar = $('upTakvimWsDetail');
        if (detBar) { detBar.style.display = 'none'; detBar.innerHTML = ''; }
        if (btn && typeof btn.focus === 'function') btn.focus();
        e.takvimTriggerBtn = null;
        enjUpdateStep2Ui();
    }

    function enjApplyTakvimSecim() {
        var sel = state.enj.takvimSecim;
        if (!sel || !sel.oneri_baslangic) return;
        var machines = state.enj.gridData || [];
        var m = machines.find(function (x) {
            return (x.makine_id || x.id) === sel.makine_id;
        });
        if (!m) return;
        var mid = sel.makine_id;
        var kod = sel.makine_kod || m.makine_kod || m.kod;
        var slot = sel.slot;
        var bas = sel.oneri_baslangic;
        var e = state.enj;
        enjSyncCalismaModuForCellVardiya(sel.vardiya || enjVardiyaFromCell(sel));
        if (e.makineId !== mid) {
            e.makineId = mid;
            e.makineKod = kod;
            e.istasyonSayisi = m.istasyon_sayisi;
            enjClearMakineDependencies();
            enjRenderMakineCards(machines);
            if ($('upEnjKalip')) $('upEnjKalip').disabled = false;
        }
        e.slot = slot;
        e.baslangicManuel = true;
        e.baslangic = bas;
        if ($('upEnjSlotA')) $('upEnjSlotA').classList.toggle('selected', slot === 'A');
        if ($('upEnjSlotB')) $('upEnjSlotB').classList.toggle('selected', slot === 'B');
        if ($('upEnjBas')) $('upEnjBas').value = enjApiDtToLocal(bas);
        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
        enjHesapGizle();
        enjRenderIstasyonGrid(m);
        enjSyncKalipAdediFromStations();
        enjFetchIlkUygun(false);
        enjFetchIstasyonPlanDurum(function () {
            enjRenderIstasyonGrid(m);
            enjUpdateStep2Ui();
            enjUpdateHesapBtn();
            enjEvaluateShiftStartBoundary();
        });
        e.takvimApplied = true;
        enjCloseTakvimWorkspace();
        enjYukleSlotOzet(function () {
            enjRenderMakineCards(machines);
        });
    }

    function enjBindTakvimWorkspace() {
        enjMountTakvimAccordionPanels();
        if ($('upTakvimWsGeri')) {
            $('upTakvimWsGeri').addEventListener('click', enjCloseTakvimWorkspace);
        }
        if ($('upTakvimAccToggle')) {
            $('upTakvimAccToggle').addEventListener('click', function (ev) {
                if (ev.target.closest('.up-takvim-acc-edit')) {
                    enjToggleTakvimAcc(true);
                    return;
                }
                var acc = $('upTakvimAcc');
                if (acc && acc.classList.contains('is-collapsed')) {
                    enjToggleTakvimAcc(true);
                } else {
                    enjToggleTakvimAcc(false);
                }
            });
        }
        if ($('upTakvimHesapUygula')) {
            $('upTakvimHesapUygula').addEventListener('click', enjApplyTakvimHesap);
        }
        if ($('upTakvimDraftKullan')) {
            $('upTakvimDraftKullan').addEventListener('click', enjApplyDraftPlanToSetup);
        }
        if ($('upEnjTakvimPlanlaBtn')) {
            $('upEnjTakvimPlanlaBtn').addEventListener('click', function () {
                var e = state.enj;
                if (!e.makineId) return;
                enjOpenTakvimWorkspace(e.makineId, e.makineKod, $('upEnjTakvimPlanlaBtn'));
            });
        }
        if ($('upTakvimPrev')) {
            $('upTakvimPrev').addEventListener('click', function () {
                state.enj.takvimAnchor = enjShiftAnchorDate(state.enj.takvimAnchor, -(state.enj.takvimNumDays || 4));
                enjLoadTakvimData();
            });
        }
        if ($('upTakvimToday')) {
            $('upTakvimToday').addEventListener('click', function () {
                state.enj.takvimAnchor = enjTakvimAnchorDefault();
                enjLoadTakvimData();
            });
        }
        if ($('upTakvimNext')) {
            $('upTakvimNext').addEventListener('click', function () {
                state.enj.takvimAnchor = enjShiftAnchorDate(state.enj.takvimAnchor, state.enj.takvimNumDays || 4);
                enjLoadTakvimData();
            });
        }
        if ($('upTakvimSecimKullan')) {
            $('upTakvimSecimKullan').addEventListener('click', enjApplyTakvimSecim);
        }
    }

    // ── PHASE_7J: Kalıp Seçim Çalışma Alanı (modal içi) ─────────────────────
    // PHASE_7N: Tab sistemi kaldırıldı; tek liste (tüm aktif kalıplar)

    var _wsSearch = '';

    function enjOpenKalipWorkspace() {
        enjCloseTakvimWorkspace();
        var layout = document.querySelector('.up-step2-layout');
        var ws = $('upKalipWorkspace');
        if (!layout || !ws) return;
        _wsSearch = '';
        var si = $('upKalipWsSearch');
        if (si) si.value = '';
        ws.style.display = 'flex';
        enjWsRender();
        layout.classList.add('kalip-secim-aktif');
        var geriBtn = $('upKalipWsGeri');
        if (geriBtn) setTimeout(function () { geriBtn.focus(); }, 50);
    }

    function enjCloseKalipWorkspace() {
        var layout = document.querySelector('.up-step2-layout');
        var ws = $('upKalipWorkspace');
        if (!layout) return;
        layout.classList.remove('kalip-secim-aktif');
        if (ws) ws.style.display = '';
        var listeBtn = $('upEnjKalipModeListe');
        if (listeBtn) listeBtn.focus();
    }

    function enjWsBuildMeta() {
        var metaEl = $('upKalipWsMeta');
        if (!metaEl) return;
        var o = state.seciliCreateData || {};
        var model = o.mamul_skod || '';
        var sipNo = o.sip_no || '';
        var miktar = o.miktar_cift || o.cift_miktar || '';
        var e = state.enj;
        var makine = e.secilenMakine ? ('M' + e.secilenMakine) : '';
        var taraf = e.secilenSlot || '';
        var ist = (e.istasyonlar || []).length;
        var parts = [];
        if (model) parts.push('Model: <b>' + esc(model) + '</b>');
        if (sipNo) parts.push('Sipariş: <b>' + esc(String(sipNo)) + '</b>');
        if (miktar) parts.push('Planlanan: <b>' + esc(String(miktar)) + ' çift</b>');
        if (makine && taraf) parts.push('Makine: <b>' + esc(makine + '-' + taraf) + '</b>');
        if (ist > 0) parts.push('İstasyon: <b>' + ist + '</b>');
        metaEl.innerHTML = parts.join(' &nbsp;·&nbsp; ');
    }

    // PHASE_7N/7N2: seri asorti label normalize
    // Kural: yalnız kanıtlı tam tekrar veya bağlamsal tekrar normalize edilir; kaynak veri değişmez
    function enjNormSeriesLabel(raw) {
        if (!raw) return raw;
        var s = String(raw).trim();

        // "A-A" token bazlı tam tekrar (örn. "38-38" → "38")
        var parts = s.split('-');
        if (parts.length === 2 && parts[0].trim() === parts[1].trim()) return parts[0].trim();

        // "X/Y-X/Y" veya "X/Y- X/Y" (boşluklu) (örn. "25/26-25/26" → "25/26")
        // Tire konumunu bul
        var dashIdx = s.indexOf('-');
        if (dashIdx > 0) {
            var left = s.slice(0, dashIdx).trim();
            var right = s.slice(dashIdx + 1).trim();
            if (left === right && left.length > 0) return left;
            // PHASE_7N2 bağlamsal: "29/30-29-30" — sol "29/30", sağ "29-30" (aynı numara aralığı)
            // Kanıt: aynı kalıbın komşu satırları X/Y-X/Y formatında → normalize güvenli
            // "X/Y-X-Y" formunu "X/Y" ile karşılaştır
            var slashInLeft = left.indexOf('/');
            if (slashInLeft > 0) {
                var la = left.slice(0, slashInLeft);
                var lb = left.slice(slashInLeft + 1);
                // right = "la-lb" ise eşdeğer
                if (right === la + '-' + lb) return left;
            }
        }
        return s;
    }

    function enjWsRender() {
        enjWsBuildMeta();
        var list = state.enj.libraryKalipList || [];
        var search = _wsSearch.toLowerCase().trim();

        // PHASE_7N: Tek liste — tüm aktif kalıplar, tab filtresi yok
        var filtered = list.slice();

        // Arama
        if (search) {
            filtered = filtered.filter(function (it) {
                return [it.model_code, it.visible_mold_code, it.product_family, it.product_variant, it.assortment]
                    .filter(Boolean).some(function (s) { return s.toLowerCase().indexOf(search) !== -1; });
            });
        }

        // Sayaç
        var countEl = $('upKalipWsCount');
        if (countEl) {
            var selCnt = filtered.filter(function (it) { return it.selectable; }).length;
            countEl.textContent = filtered.length + ' kayıt · ' + selCnt + ' seçilebilir';
        }

        var body = $('upKalipWsBody');
        if (!body) return;
        body.innerHTML = '';

        if (!filtered.length) {
            var empty = document.createElement('div');
            empty.className = 'up-kalip-ws-empty';
            empty.textContent = 'Listelenecek aktif kalıp kaydı yok.';
            body.appendChild(empty);
            return;
        }

        // PHASE_7N2: Asorti bilgi bannerı — yalnız asorti uyarısı olan kalıp varsa, bir kez göster
        var hasAsortiWarn = filtered.some(function (it) {
            return (it.info_warnings || []).some(function (w) {
                return w.indexOf('asorti') !== -1 || w.indexOf('Numara') !== -1;
            });
        });
        if (hasAsortiWarn) {
            var banner = document.createElement('div');
            banner.className = 'up-ws-asorti-banner';
            banner.textContent = 'ℹ Korgün\'den numara bazlı sipariş dağılımı gelmiyor. Kalıp numaralarını ve adetlerini kontrol ederek seçim yapın.';
            body.appendChild(banner);
        }

        // Sıralama: seçilebilir önce, bloke sonra
        var sorted = filtered.slice().sort(function (a, b) {
            var aScore = a.selectable ? 0 : 1;
            var bScore = b.selectable ? 0 : 1;
            return aScore - bScore;
        });

        sorted.forEach(function (item) {
            var isSelected = state.enj.libraryUuid !== null && state.enj.libraryUuid === item.library_uuid;
            // PHASE_7N1: model_mismatch ve asorti_mismatch artık hard block değil
            var isIncompat = false;

            var row = document.createElement('div');
            var cls = 'up-ws-kalip-item';
            if (item.selectable) cls += ' ws-selectable';
            else if (isIncompat) cls += ' ws-incompatible';
            else cls += ' ws-blocked';
            if (isSelected) cls += ' ws-selected';
            row.className = cls;
            row.setAttribute('data-library-uuid', item.library_uuid || '');

            // Görsel
            var thumb;
            if (item.image_url) {
                thumb = document.createElement('img');
                thumb.className = 'up-ws-kalip-thumb';
                thumb.alt = '';
                thumb.src = item.image_url;
                thumb.onerror = function () {
                    var ph = document.createElement('div');
                    ph.className = 'up-ws-kalip-thumb-ph';
                    ph.textContent = 'Görsel yok';
                    if (this.parentNode) this.replaceWith(ph);
                };
            } else {
                thumb = document.createElement('div');
                thumb.className = 'up-ws-kalip-thumb-ph';
                thumb.textContent = 'Görsel yok';
            }

            var bodyWrap = document.createElement('div');
            bodyWrap.className = 'up-ws-kalip-body';
            var topRow = document.createElement('div');
            topRow.className = 'up-ws-kalip-top-row';
            topRow.appendChild(thumb);

            var meta = document.createElement('div');
            meta.className = 'up-ws-kalip-meta';

            var codeEl = document.createElement('div');
            codeEl.className = 'up-ws-kalip-code';
            codeEl.textContent = enjLibraryMoldIdentityLabel(item);

            var famEl = document.createElement('div');
            famEl.className = 'up-ws-kalip-family';
            famEl.textContent = item.model_code || '—';

            meta.appendChild(codeEl);
            meta.appendChild(famEl);

            // PHASE_7N: is_recommended rozeti kaldırıldı

            // PHASE_7N3: kompakt stat satırı — "Kalıp İçi X Çift" terminolojisi
            var stats = document.createElement('div');
            stats.className = 'up-ws-kalip-stats';
            var statParts = [];
            if (item.pairs_per_cycle != null) statParts.push('Kalıp İçi <b>' + esc(String(item.pairs_per_cycle)) + '</b> Çift');
            if (item.weight_label) statParts.push(esc(item.weight_label));
            if (item.weight_reference_size) statParts.push('Ref. ' + esc(item.weight_reference_size));
            if (item.cooking_time_label) statParts.push('<b>' + esc(item.cooking_time_label) + '</b>');
            if (item.physical_mold_label) statParts.push(esc(item.physical_mold_label));
            if (item.max_station_hint != null) statParts.push('En fazla ' + esc(String(item.max_station_hint)) + ' ist.');
            stats.innerHTML = statParts.join(' · ');
            meta.appendChild(stats);
            // PHASE_7N2: asorti uyarısı kartlarda gösterilmiyor — tek banner listeye ekleniyor
            (item.info_warnings || []).filter(function (w) {
                return w.indexOf('asorti') === -1 && w.indexOf('Numara') === -1;
            }).forEach(function (w) {
                var wEl = document.createElement('div');
                wEl.className = 'up-ws-info-warn';
                wEl.textContent = '⚠ ' + w;
                meta.appendChild(wEl);
            });

            topRow.appendChild(meta);
            bodyWrap.appendChild(topRow);
            enjWsAppendSeriesStack(bodyWrap, item);
            enjWsAppendPlacement(bodyWrap, item);

            // Bloke gerekçeleri — PHASE_7N: model uyumsuzluk mesajı kaldırıldı
            if (!item.selectable) {
                var blockDiv = document.createElement('div');
                blockDiv.className = 'up-ws-kalip-block-msg';
                // activation_block_detail (kalıp kütüphanesi gate'leri) varsa önce onu göster
                var blockMsgs = (item.activation_block_detail && item.activation_block_detail.length)
                    ? item.activation_block_detail
                    : (item.block_reasons || []);
                blockMsgs.forEach(function (msg) {
                    var tag = document.createElement('span');
                    tag.className = 'up-ws-block-tag' + (isIncompat ? ' ws-block-incompatible' : '');
                    tag.textContent = '⚠ ' + msg;
                    blockDiv.appendChild(tag);
                });
                var detLink = document.createElement('a');
                detLink.className = 'up-ws-detail-link';
                detLink.textContent = 'Aktif Kalıplarda İncele →';
                detLink.href = '/planlama/aktif-kaliplar';
                detLink.target = '_blank';
                detLink.rel = 'noopener';
                blockDiv.appendChild(detLink);
                bodyWrap.appendChild(blockDiv);
            }

            var actDiv = document.createElement('div');
            actDiv.className = 'up-ws-kalip-actions';
            if (item.selectable) {
                var secBtn = document.createElement('button');
                secBtn.type = 'button';
                secBtn.className = 'up-ws-sec-btn' + (isSelected ? ' active' : '');
                secBtn.textContent = isSelected ? '✓ Seçildi' : 'Seç';
                secBtn.setAttribute('aria-label', 'Kalıbı seç: ' + enjLibraryMoldIdentityLabel(item));
                (function (capturedItem) {
                    secBtn.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        enjSelectLibraryKalip(capturedItem);
                        enjCloseKalipWorkspace();
                    });
                })(item);
                actDiv.appendChild(secBtn);
            } else {
                var disBtn = document.createElement('button');
                disBtn.type = 'button';
                disBtn.className = 'up-ws-sec-btn';
                disBtn.textContent = 'Seçilemez';
                disBtn.disabled = true;
                actDiv.appendChild(disBtn);
            }
            // PHASE_7N: "Bu ürünle ilişkilendir" butonu kaldırıldı

            row.appendChild(bodyWrap);
            row.appendChild(actDiv);
            body.appendChild(row);
        });
    }

    function enjBindWorkspaceEvents() {
        // Geri butonu
        var geriBtn = $('upKalipWsGeri');
        if (geriBtn) geriBtn.addEventListener('click', enjCloseKalipWorkspace);
        // PHASE_7N: Tab eventleri kaldırıldı — tek liste
        // Arama
        var searchInput = $('upKalipWsSearch');
        if (searchInput) searchInput.addEventListener('input', function () {
            _wsSearch = searchInput.value;
            enjWsRender();
        });
        // Escape ile kapat
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') {
                var layout = document.querySelector('.up-step2-layout');
                if (layout && layout.classList.contains('takvim-aktif')) {
                    enjCloseTakvimWorkspace();
                } else if (layout && layout.classList.contains('kalip-secim-aktif')) {
                    enjCloseKalipWorkspace();
                }
            }
        });
    }

    // ── END PHASE_7J Workspace ────────────────────────────────────────────────

    function enjYukleKaliplar() {
        var o = state.seciliCreateData;
        if (!o || !o.mamul_skod) return;

        var sel = $('upEnjKalip');
        state.enj.kaliplar = [];
        state.enj.libraryKalipList = [];
        if (sel) { sel.disabled = true; sel.innerHTML = '<option value="">Kalıplar yükleniyor…</option>'; }
        var libList = $('upEnjKalipLibraryList');
        if (libList) libList.innerHTML = '<div style="padding:8px;font-size:12px;color:#64748b;">Yükleniyor…</div>';

        var params = new URLSearchParams({
            sip_no: o.sip_no,
            sip_harinx: o.sip_harinx || o.sip_harinx_id || 0,
            mamul_skod: o.mamul_skod,
            rkod: o.rkod || 0,
        });

        fetch('/planlama/uretim-plan/api/enj/plan-config', { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (cfg) {
                state.enj.libraryPlanEnabled = !!(cfg && cfg.library_plan_selection_enabled);
                enjToggleLibraryKalipUi(state.enj.libraryPlanEnabled);
                var url = state.enj.libraryPlanEnabled
                    ? '/planlama/uretim-plan/api/enj/library-kaliplar?'
                    : '/planlama/uretim-plan/api/enj/kaliplar?';
                return fetch(url + params.toString(), { credentials: 'include' }).then(function (r) { return r.json(); });
            })
            .then(function (d) {
                if (!d.ok) {
                    if (sel) sel.innerHTML = '<option value="">— ' + (d.mesaj || 'Hata') + ' —</option>';
                    if (libList) libList.innerHTML = '<div class="up-lib-kalip-block">' + esc(d.mesaj || 'Hata') + '</div>';
                    return;
                }
                if (state.enj.libraryPlanEnabled) {
                    state.enj.libraryKalipList = d.kaliplar || [];
                    state.enj.kaliplar = (d.selectable || []).map(function (k) {
                        return {
                            id: k.legacy_enj_kalip_id,
                            kalip_kod: k.visible_mold_code,
                            kalip_basi_cift: k.pairs_per_cycle,
                            library_uuid: k.library_uuid,
                        };
                    });
                    enjBuildLibraryKalipList();
                    if (!state.enj.libraryKalipList.length) {
                        if (libList) libList.innerHTML = '<div class="up-lib-kalip-block">Bu model için kütüphane kaydı bulunamadı.</div>';
                    }
                } else {
                    if (sel) sel.disabled = false;
                    state.enj.kaliplar = d.kaliplar || [];
                    enjBuildKalipSelect();
                    if (!state.enj.kaliplar.length && d.mesaj && sel) {
                        sel.innerHTML = '<option value="">— ' + d.mesaj + ' —</option>';
                        sel.disabled = true;
                    }
                }
            })
            .catch(function () {
                if (sel) sel.innerHTML = '<option value="">— Kalıplar yüklenemedi —</option>';
                if (libList) libList.innerHTML = '<div class="up-lib-kalip-block">Kalıplar yüklenemedi</div>';
            });
    }

    function enjBindEvents() {
        if ($('upEnjSlotA')) $('upEnjSlotA').addEventListener('click', function () { enjSelectSlot('A'); });
        if ($('upEnjSlotB')) $('upEnjSlotB').addEventListener('click', function () { enjSelectSlot('B'); });
        if ($('upEnjKalipModeListe')) $('upEnjKalipModeListe').addEventListener('click', function () {
            enjSetKalipMode('liste');
            // PHASE_7I: Open real selection drawer when list mode is activated
            if (state.enj.libraryPlanEnabled) {
                setTimeout(function () { enjOpenKalipWorkspace(); }, 50);
            }
        });
        if ($('upEnjKalipModeManuel')) $('upEnjKalipModeManuel').addEventListener('click', function () { enjSetKalipMode('manuel'); });
        if ($('upEnjKalip')) $('upEnjKalip').addEventListener('change', function () {
            var e = state.enj;
            if (e.istasyonlar.length) {
                enjClearIstasyonSecimleri(
                    'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.');
            }
            var opt = $('upEnjKalip').options[$('upEnjKalip').selectedIndex];
            e.kalipId = $('upEnjKalip').value ? parseInt($('upEnjKalip').value, 10) : null;
            e.kalipKod = opt ? (opt.dataset.kod || opt.textContent.split(' ')[0]) : null;
            e.kalipBasiCift = opt && opt.dataset.kbc ? parseFloat(opt.dataset.kbc) : null;
            enjHesapGizle();
            enjYukleKalipGoz();
            var mLeg = (e.gridData || []).find(function (x) {
                return (x.makine_id || x.id) === e.makineId;
            });
            if (mLeg) enjRenderIstasyonGrid(mLeg);
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
                        enjEvaluateShiftStartBoundary();
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
                        enjValidateSelectedStationsAtDate(function () {
                            var mBas = (state.enj.gridData || []).find(function (x) {
                                return (x.makine_id || x.id) === state.enj.makineId;
                            });
                            if (mBas) enjRenderIstasyonGrid(mBas);
                            enjYukleSlotOzet(function () {
                                enjRenderMakineCards(state.enj.gridData || []);
                            });
                        }, 'date');
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
                    } else if (id === 'upEnjKalipManuelKod' || id === 'upEnjKalipManuelKbc') {
                        if (state.enj.istasyonlar.length) {
                            enjClearIstasyonSecimleri(
                                'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.');
                        }
                        enjSyncInputsFromDom();
                        enjUpdateKalipSeciliCards();
                        enjUpdateFizikselKalipDisplay();
                        var mMan = (state.enj.gridData || []).find(function (x) {
                            return (x.makine_id || x.id) === state.enj.makineId;
                        });
                        if (mMan) enjRenderIstasyonGrid(mMan);
                    } else if (id === 'upEnjGozPerKalip') {
                        enjUpdateToplamGozHint();
                    } else if (id === 'upEnjPlanCift') {
                        enjUpdateMiktarOzet();
                    }
                    enjHesapGizle();
                    enjUpdateHesapBtn();
                });
                $(id).addEventListener('input', function () {
                    if (id === 'upEnjKalipManuelKod' || id === 'upEnjKalipManuelKbc') {
                        if (state.enj.istasyonlar.length) {
                            enjClearIstasyonSecimleri(
                                'Kalıp veya planlama koşulları değiştiği için istasyonları yeniden seçin.');
                        }
                        enjSyncInputsFromDom();
                        // KAPI_42A8_FIX: update summary cards + fiziksel display on every keystroke
                        // so the station gate and right summary reflect the current value immediately.
                        enjUpdateKalipSeciliCards();
                        enjUpdateFizikselKalipDisplay();
                        var mManIn = (state.enj.gridData || []).find(function (x) {
                            return (x.makine_id || x.id) === state.enj.makineId;
                        });
                        if (mManIn) enjRenderIstasyonGrid(mManIn);
                        enjUpdateHesapBtn();
                    } else if (id === 'upEnjBas') {
                        state.enj.baslangicManuel = true;
                        if ($('upEnjBasOneri')) $('upEnjBasOneri').style.display = 'none';
                        enjSyncInputsFromDom();
                        enjEvaluateShiftStartBoundary();
                        enjHesapGizle();
                        enjValidateSelectedStationsAtDate(function () {
                            var mBas = (state.enj.gridData || []).find(function (x) {
                                return (x.makine_id || x.id) === state.enj.makineId;
                            });
                            if (mBas) enjRenderIstasyonGrid(mBas);
                            enjYukleSlotOzet(function () {
                                enjRenderMakineCards(state.enj.gridData || []);
                            });
                        }, 'date');
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
            state.enj.haftaSonu = $('upEnjHaftaSonu').value;
            if (evet) enjSyncHsVardiyaFromCalisma(true);
            else state.enj.hsVardiya = null;
            state.enj.baslangicManuel = false;
            state.enj.takvimSecim = null;
            enjRecalcPlanningTimeline('hafta_sonu');
            enjYukleSlotOzet(function () {
                enjRenderMakineCards(state.enj.gridData || []);
            });
        });
        document.querySelectorAll('.up-enj-hs-vardiya-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var val = btn.dataset.val;
                document.querySelectorAll('.up-enj-hs-vardiya-tab').forEach(function (b) {
                    b.classList.toggle('selected', b.dataset.val === val);
                });
                if ($('upEnjHsVardiya')) {
                    $('upEnjHsVardiya').value = val;
                    $('upEnjHsVardiya').dispatchEvent(new Event('change'));
                }
            });
        });
        document.querySelectorAll('.up-enj-hs-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var val = btn.dataset.val;
                document.querySelectorAll('.up-enj-hs-tab').forEach(function (b) {
                    b.classList.toggle('selected', b.dataset.val === val);
                });
                var sel = $('upEnjHaftaSonu');
                if (sel && sel.value !== val) {
                    sel.value = val;
                    sel.dispatchEvent(new Event('change'));
                }
            });
        });
        if ($('upEnjHsVardiya')) $('upEnjHsVardiya').addEventListener('change', function () {
            state.enj.baslangicManuel = false;
            state.enj.takvimSecim = null;
            enjEvaluateShiftStartBoundary();
            enjHesapGizle();
            enjFetchIlkUygun();
            if (state.enj.takvimMakineId) enjLoadTakvimData();
            enjUpdateHesapBtn();
        });
        // Tab-stili çalışma modu
        document.querySelectorAll('.up-enj-calisma-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var val = btn.dataset.val;
                document.querySelectorAll('.up-enj-calisma-tab').forEach(function (b) {
                    b.classList.toggle('selected', b.dataset.val === val);
                    b.setAttribute('aria-selected', b.dataset.val === val ? 'true' : 'false');
                });
                var sel = $('upEnjCalismaModu');
                if (sel) {
                    sel.value = val;
                    sel.dispatchEvent(new Event('change'));
                }
                enjUpdateManualRefVisibility();
                if (state.enj.haftaSonu === 'EVET') enjSyncHsVardiyaFromCalisma(true);
            });
        });
        if ($('upEnjHesapBtn')) $('upEnjHesapBtn').addEventListener('click', enjHesaplaMotor);
        if ($('upEnjHesapDetayToggle')) {
            $('upEnjHesapDetayToggle').addEventListener('click', function () {
                enjSetHesapDetayAcik(!state.enj.hesapDetayAcik);
            });
        }
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
        if ($('upEnjBasIlkUygunBtn')) {
            $('upEnjBasIlkUygunBtn').addEventListener('click', enjUseIlkUygunDate);
        }
        if ($('upEnjConflictApply')) $('upEnjConflictApply').addEventListener('click', enjApplyConflictIlkUygun);
        if ($('upEnjConflictCalendar')) $('upEnjConflictCalendar').addEventListener('click', enjOpenConflictCalendar);
        if ($('upEnjConflictKapat')) $('upEnjConflictKapat').addEventListener('click', enjHideConflictModal);
        if ($('upEnjConflictClose')) $('upEnjConflictClose').addEventListener('click', enjHideConflictModal);
        if ($('upEnjConflictBackdrop')) $('upEnjConflictBackdrop').addEventListener('click', enjHideConflictModal);
        if ($('upStep3EnjDegistir')) {
            $('upStep3EnjDegistir').addEventListener('click', function () { wizardShowStep(2); });
        }
        if ($('upFormBit')) {
            $('upFormBit').addEventListener('change', function () {
                validateStep3Tarihleri();
                // Manuel değişiklik takibi
                if (state.step3.onerilenBit && $('upFormBit').value !== state.step3.onerilenBit) {
                    state.step3.manuelDegisti = true;
                } else {
                    state.step3.manuelDegisti = false;
                }
                step3RenderManuelBadge(state.step3.manuelDegisti);
                // Önceki plan güncelle
                var bas = $('upFormBas') ? $('upFormBas').value : '';
                step3FetchOncekiPlanlar(bas, $('upFormBit').value);
            });
        }
        if ($('upStep3OneriDon')) {
            $('upStep3OneriDon').addEventListener('click', function () {
                if (state.step3.onerilenBit && $('upFormBit')) {
                    $('upFormBit').value = state.step3.onerilenBit;
                    state.step3.manuelDegisti = false;
                    step3RenderManuelBadge(false);
                    validateStep3Tarihleri();
                    var bas = $('upFormBas') ? $('upFormBas').value : '';
                    step3FetchOncekiPlanlar(bas, state.step3.onerilenBit);
                }
            });
        }
        enjBindMakineDetayModal();
        enjBindTakvimWorkspace();
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
                payload.kalip_mode = enj.kalipMode || 'liste';
                if (enj.kalipMode === 'liste' && enj.libraryPlanEnabled && enj.libraryUuid) {
                    payload.mold_source = 'LIBRARY';
                    payload.mold_library_uuid = enj.libraryUuid;
                    payload.order_asorti = (state.seciliCreateData && state.seciliCreateData.asorti) || null;
                    if (enj.libraryKalipMeta) {
                        payload.mold_library_snapshot_json = JSON.stringify({
                            library_uuid: enj.libraryKalipMeta.library_uuid,
                            model_code: enj.libraryKalipMeta.model_code,
                            visible_mold_code: enj.libraryKalipMeta.visible_mold_code,
                            material_group: 'EVA',
                            product_family: enj.libraryKalipMeta.product_family,
                            product_variant: enj.libraryKalipMeta.product_variant,
                            assortment: enj.libraryKalipMeta.assortment,
                            pairs_per_cycle: enj.libraryKalipMeta.pairs_per_cycle,
                            series_summary: enj.libraryKalipMeta.series,
                            readiness_status: enj.libraryKalipMeta.review_status,
                            legacy_enj_kalip_id: enj.libraryKalipMeta.legacy_enj_kalip_id,
                            snapshot_at: new Date().toISOString(),
                        });
                    }
                }
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
                    capacity_source_gunduz: enj.capacitySourceGunduz || 'NONE',
                    capacity_source_gece: enj.capacitySourceGece || 'NONE',
                    capacity_audit_gunduz: enj.capacityAuditGunduz || null,
                    capacity_audit_gece: enj.capacityAuditGece || null,
                    setup_dakika: enj.setupMinutes || 0,
                    setup_time_rule: enj.setupMinutes > 0 ? 'WORKING_MINUTES_ONLY' : null,
                    ref_audit_ts: new Date().toISOString(),
                    shift_start_override_confirmed: !!enj.shiftStartOverrideConfirmed,
                    shift_start_override_time: enj.shiftStartOverrideConfirmed
                        ? (enj.shiftStartOverrideTime || rez.baslangic) : null,
                });
                if (enj.shiftStartOverrideConfirmed) {
                    payload.shift_start_override_confirmed = true;
                    payload.shift_start_override_time = enj.shiftStartOverrideTime || rez.baslangic;
                }
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
                    closeCreateModalConfirmed();
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
        enjBindWorkspaceEvents(); // PHASE_7J: Workspace event listeners
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
        if ($('upCreateClose')) $('upCreateClose').addEventListener('click', requestCloseCreateModal);
        if ($('upCreateCancel')) $('upCreateCancel').addEventListener('click', requestCloseCreateModal);
        document.addEventListener('keydown', function (ev) {
            var cm = $('upCreateModal');
            if (ev.key === 'Escape' && cm && !cm.hidden) {
                ev.stopPropagation();
                requestCloseCreateModal();
            }
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
            // Manuel değişiklik takibi (eğer ilk listener'dan kaçtıysa)
            if (state.step3.onerilenBit && $('upFormBit').value !== state.step3.onerilenBit) {
                state.step3.manuelDegisti = true;
            } else {
                state.step3.manuelDegisti = false;
            }
            step3RenderManuelBadge(state.step3.manuelDegisti);
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

    window.__UP7O3 = {
        getState: function () { return state; },
        $: $,
        esc: esc,
        fmtN: fmtN,
        enjHesapGizle: enjHesapGizle,
        enjUpdateHesapBtn: enjUpdateHesapBtn,
        enjUpdateCentralStatus: enjUpdateCentralStatus,
        enjUpdateStep2Ui: enjUpdateStep2Ui,
        enjLoadTakvimData: enjLoadTakvimData,
        enjGanttWindowMeta: enjGanttWindowMeta,
        enjGanttParseMs: enjGanttParseMs,
        enjRenderTakvimBody: enjRenderTakvimBody,
        enjRecalcPlanningTimeline: enjRecalcPlanningTimeline,
        enjFetchIlkUygun: enjFetchIlkUygun,
        enjEvaluateShiftStartBoundary: enjEvaluateShiftStartBoundary,
        enjKalipSecili: enjKalipSecili,
        enjIstasyonSelectionGateOpen: enjIstasyonSelectionGateOpen,
        enjGetFizikselKalipLimit: enjGetFizikselKalipLimit,
        enjTryToggleIstasyon: enjTryToggleIstasyon,
        enjIstasyonDisabledAtDate: enjIstasyonDisabledAtDate,
        enjIstasyonGateBlockReason: enjIstasyonGateBlockReason,
        enjRenderIstasyonGrid: enjRenderIstasyonGrid,
        enjLibraryMoldIdentityLabel: enjLibraryMoldIdentityLabel,
        enjMountTakvimAccordionPanels: enjMountTakvimAccordionPanels,
        enjSetTakvimAccOpen: enjSetTakvimAccOpen,
        enjOpenTakvimWorkspace: enjOpenTakvimWorkspace,
        enjCanHesapla: enjCanHesapla,
        enjApplyTakvimHesap: enjApplyTakvimHesap,
        enjApplyDraftPlanToSetup: enjApplyDraftPlanToSetup,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
