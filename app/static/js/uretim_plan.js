(function () {
    'use strict';

    var CAN_EDIT = !!window.UP_CAN_EDIT;
    var state = {
        donem: 'bu_hafta',
        satirlar: [],
        onizleme: [],
        seciliCreate: null,
        detayPlanId: null,
        editPlanId: null,
        enj: {
            makineler: [],
            kaliplar: [],
            makineId: null,
            istasyonNo: null,
            slot: null,
            kalipId: null,
            kalipBasiCift: null,
            aktifGoz: null,
            turCift: null,
            gunlukTur: null,
            gunlukKap: null,
            tahminiGun: null,
            baslangic: null,
            bitis: null,
            planCift: null,
            kapasite_eksik: false,
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

    function renderProsesKartGrid(prosesler) {
        return (prosesler || []).map(function (p) {
            var emirTxt = '';
            if (p.emir_sayisi != null && p.emir_sayisi > 0) {
                var bEm = p.biten_emir_sayisi != null ? p.biten_emir_sayisi : 0;
                emirTxt = bEm + '/' + p.emir_sayisi + ' emir';
            }
            return '<div class="up-proses-kart">' +
                '<div class="pct">' + (p.yuzde || 0) + '%</div>' +
                '<div class="up-proses-durum ' + (p.renk || 'gri') + '">' + esc(p.durum) + '</div>' +
                '<div class="up-proses-kart-meta">' + esc(p.proses_adi || p.proses_kod) + '</div>' +
                '<div class="up-proses-kart-alt">' + esc(emirTxt) + '</div>' +
                '<div class="up-proses-kart-alt">' + fmtN(p.biten) + ' / ' + fmtN(p.hedef_miktar || p.verilen) + '</div></div>';
        }).join('');
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
        var form = $('upCreatePlanForm');
        var ro = $('upFormReadonly');
        if (!form || !o) return;
        form.style.display = 'block';
        if ($('upPlanaEkleBtn')) $('upPlanaEkleBtn').disabled = false;
        if (ro) {
            ro.innerHTML = '<strong>Korgun (read-only)</strong><br>SipHarinx: ' + o.sip_harinx +
                ' · RKOD: ' + o.rkod + ' · Canonical: ' + esc(o.canonical_key);
        }
        enjReset();
        enjYukleMakineler();
        enjYukleKaliplar();
    }

    // ─── ENJEKSİYON PLAN HESABI ─────────────────────────────────────────────

    function enjReset() {
        var e = state.enj;
        e.makineId = null; e.istasyonNo = null; e.slot = null;
        e.kalipId = null; e.kalipKod = null;
        e.aktifGoz = null; e.kalipBasiCift = null; e.turCift = null;
        e.gunlukTur = null; e.gunlukKap = null;
        e.tahminiGun = null; e.baslangic = null; e.bitis = null;
        e.planCift = null; e.kapasite_eksik = false;
        enjHesapGizle();
        if ($('upEnjSlotDurum')) {
            $('upEnjSlotDurum').textContent = '—';
            $('upEnjSlotDurum').className = 'up-enj-slot-durum';
        }
        if ($('upEnjUyari')) { $('upEnjUyari').style.display = 'none'; $('upEnjUyari').textContent = ''; }
        if ($('upEnjCakismaUyari')) $('upEnjCakismaUyari').style.display = 'none';
    }

    function enjHesapGizle() {
        if ($('upEnjHesapOzet')) $('upEnjHesapOzet').style.display = 'none';
        ['upEnjTurCift','upEnjGunlukKap','upEnjGunlukKapFormul','upEnjTahminiGun','upEnjTahminiFormul','upEnjBitis'].forEach(function(id) {
            if ($(id)) $(id).textContent = '—';
        });
    }

    function enjHesapla() {
        var e = state.enj;
        var turCift = e.turCift;
        var gunlukTurEl = $('upEnjGunlukTur');
        var planCiftEl = $('upEnjPlanCift');
        var basEl = $('upEnjBas');

        e.gunlukTur = gunlukTurEl ? (parseInt(gunlukTurEl.value, 10) || null) : null;
        e.planCift = planCiftEl ? (parseFloat(planCiftEl.value) || null) : null;
        e.baslangic = basEl ? (basEl.value || null) : null;

        if (!turCift || !e.gunlukTur) {
            enjHesapGizle();
            return;
        }

        var gunlukKap = turCift * e.gunlukTur;
        e.gunlukKap = gunlukKap;

        var tahminiGun = null;
        var bitisStr = null;
        if (e.planCift && gunlukKap > 0) {
            tahminiGun = e.planCift / gunlukKap;
            e.tahminiGun = tahminiGun;
            if (e.baslangic) {
                var bas = new Date(e.baslangic);
                var gunSayisi = Math.ceil(tahminiGun);
                var bit = new Date(bas.getTime() + (gunSayisi - 1) * 86400000);
                bitisStr = bit.toISOString().slice(0, 10);
                e.bitis = bitisStr;
                // plan_bitis otomatik doldur
                if ($('upFormBit') && !$('upFormBit').value) $('upFormBit').value = bitisStr;
                if ($('upFormBas') && !$('upFormBas').value) $('upFormBas').value = e.baslangic;
            }
        }

        var ozet = $('upEnjHesapOzet');
        if (ozet) ozet.style.display = 'block';
        if ($('upEnjTurCift')) $('upEnjTurCift').textContent = turCift + ' çift/tur';
        if ($('upEnjGunlukKap')) $('upEnjGunlukKap').textContent = gunlukKap + ' çift/gün';
        if ($('upEnjGunlukKapFormul')) $('upEnjGunlukKapFormul').textContent = '(' + turCift + ' × ' + e.gunlukTur + ')';
        if ($('upEnjTahminiGun')) $('upEnjTahminiGun').textContent = tahminiGun ? tahminiGun.toFixed(2) + ' gün' : '—';
        if ($('upEnjTahminiFormul') && e.planCift && gunlukKap)
            $('upEnjTahminiFormul').textContent = '(' + e.planCift + ' ÷ ' + gunlukKap + ')';
        if ($('upEnjBitis')) $('upEnjBitis').textContent = bitisStr ? fmtTarih(bitisStr) : '—';

        if (e.baslangic && e.bitis) enjCakismaKontrol();
    }

    function enjSetTurCift(goz, kbc, kaynak) {
        var e = state.enj;
        e.aktifGoz = goz;
        e.kalipBasiCift = kbc;
        if (goz != null && kbc != null) {
            e.turCift = goz * kbc;
            e.kapasite_eksik = false;
            if ($('upEnjUyari')) { $('upEnjUyari').style.display = 'none'; }
        } else {
            e.turCift = null;
            e.kapasite_eksik = true;
            if ($('upEnjUyari')) {
                $('upEnjUyari').textContent = 'Kapasite bilgisi eksik — aktif göz sayısını girin';
                $('upEnjUyari').style.display = 'block';
            }
        }
        enjHesapla();
    }

    function enjYukleKalipKapasite() {
        var e = state.enj;
        if (!e.kalipId) return;
        var url = '/planlama/uretim-plan/api/enj/kalip-kapasite?kalip_id=' + e.kalipId;
        if (e.makineId) url += '&makine_id=' + e.makineId;
        if (e.slot) url += '&slot=' + e.slot;
        fetch(url, { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (!d.ok) return;
                var kap = d.kapasite;
                if (kap && !d.kapasite_eksik) {
                    enjSetTurCift(kap.aktif_goz_sayisi, kap.kalip_basi_cift, kap.kaynak);
                } else if (kap && kap.kalip_basi_cift) {
                    if ($('upEnjUyari')) {
                        $('upEnjUyari').textContent = d.mesaj || 'Aktif setup yok — aktif göz sayısını girin';
                        $('upEnjUyari').style.display = 'block';
                    }
                    e.kalipBasiCift = kap.kalip_basi_cift;
                    e.turCift = null;
                    e.kapasite_eksik = true;
                } else {
                    if ($('upEnjUyari')) {
                        $('upEnjUyari').textContent = d.mesaj || 'Kapasite bilgisi eksik';
                        $('upEnjUyari').style.display = 'block';
                    }
                    e.turCift = null;
                    e.kapasite_eksik = true;
                }
            });
    }

    function enjSlotDurumYukle() {
        var e = state.enj;
        if (!e.makineId || !e.istasyonNo || !e.slot) return;
        var url = '/planlama/uretim-plan/api/enj/slot-durum?makine_id=' + e.makineId +
            '&istasyon_no=' + e.istasyonNo + '&slot=' + e.slot;
        fetch(url, { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var el = $('upEnjSlotDurum');
                if (!el) return;
                if (d.durum === 'DOLU' && d.veri) {
                    el.textContent = 'ŞU AN DOLU — ' + (d.veri.kalip_kod_snapshot || '');
                    el.className = 'up-enj-slot-durum up-enj-dolu';
                } else {
                    el.textContent = 'BOŞ';
                    el.className = 'up-enj-slot-durum up-enj-bos';
                }
            });
    }

    function enjCakismaKontrol() {
        var e = state.enj;
        if (!e.makineId || !e.istasyonNo || !e.slot || !e.baslangic) return;
        fetch('/planlama/uretim-plan/api/enj/cakisma-kontrol', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                makine_id: e.makineId,
                istasyon_no: e.istasyonNo,
                slot: e.slot,
                enj_plan_baslangic: e.baslangic,
                enj_plan_bitis: e.bitis,
            }),
        }).then(function(r) { return r.json(); })
          .then(function(d) {
              var el = $('upEnjCakismaUyari');
              if (!el) return;
              if (d.cakisma && d.cakisan_planlar && d.cakisan_planlar.length) {
                  var c = d.cakisan_planlar[0];
                  el.textContent = '⚠ ÇAKIŞMA: Aynı slotta ' + fmtTarih(c.enj_plan_baslangic) +
                      ' – ' + fmtTarih(c.enj_plan_bitis) + ' tarihli başka plan mevcut.';
                  el.style.display = 'block';
              } else {
                  el.style.display = 'none';
              }
          });
    }

    function enjBuildIstasyonSelect(istasyonSayisi) {
        var sel = $('upEnjIstasyon');
        if (!sel) return;
        sel.innerHTML = '<option value="">— İstasyon Seçin —</option>';
        for (var i = 1; i <= istasyonSayisi; i++) {
            var o = document.createElement('option');
            o.value = i; o.textContent = 'İstasyon ' + i;
            sel.appendChild(o);
        }
        sel.disabled = false;
    }

    function enjBuildKalipSelect() {
        var sel = $('upEnjKalip');
        if (!sel) return;
        sel.innerHTML = '<option value="">— Kalıp Seçin —</option>';
        state.enj.kaliplar.forEach(function(k) {
            var o = document.createElement('option');
            o.value = k.id;
            o.textContent = k.kalip_kod + (k.model_kod ? ' (' + k.model_kod + ')' : '');
            sel.appendChild(o);
        });
        sel.disabled = false;
    }

    function enjYukleMakineler() {
        fetch('/planlama/uretim-plan/api/enj/makineler', { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (!d.ok) return;
                state.enj.makineler = d.makineler || [];
                var sel = $('upEnjMakine');
                if (!sel) return;
                sel.innerHTML = '<option value="">— Makine Seçin —</option>';
                state.enj.makineler.forEach(function(m) {
                    var o = document.createElement('option');
                    o.value = m.id;
                    o.textContent = m.kod + ' — ' + m.ad + ' (' + m.istasyon_sayisi + ' ist.)';
                    o.dataset.istasyonSayisi = m.istasyon_sayisi;
                    sel.appendChild(o);
                });
            });
    }

    function enjYukleKaliplar() {
        if (state.enj.kaliplar.length) return;
        fetch('/planlama/uretim-plan/api/enj/kaliplar', { credentials: 'include' })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.ok) state.enj.kaliplar = d.kaliplar || [];
            });
    }

    function enjBindEvents() {
        var makSel = $('upEnjMakine');
        var istSel = $('upEnjIstasyon');
        var slotSel = $('upEnjSlot');
        var kalipSel = $('upEnjKalip');
        var turEl = $('upEnjGunlukTur');
        var ciftEl = $('upEnjPlanCift');
        var basEl = $('upEnjBas');

        if (makSel) makSel.addEventListener('change', function() {
            var opt = makSel.options[makSel.selectedIndex];
            var e = state.enj;
            e.makineId = makSel.value ? parseInt(makSel.value, 10) : null;
            e.istasyonNo = null; e.slot = null; e.kalipId = null;
            e.turCift = null; e.kapasite_eksik = false;
            enjHesapGizle();
            if ($('upEnjUyari')) { $('upEnjUyari').style.display = 'none'; }
            if (istSel) { istSel.innerHTML = '<option value="">— İstasyon Seçin —</option>'; istSel.disabled = !e.makineId; }
            if (slotSel) { slotSel.innerHTML = '<option value="">A</option><option value="B">B</option>'; slotSel.value = ''; slotSel.disabled = true; }
            if (kalipSel) { kalipSel.value = ''; kalipSel.disabled = true; }
            if ($('upEnjSlotDurum')) { $('upEnjSlotDurum').textContent = '—'; $('upEnjSlotDurum').className = 'up-enj-slot-durum'; }
            if (e.makineId && opt) {
                enjBuildIstasyonSelect(parseInt(opt.dataset.istasyonSayisi || 8, 10));
            }
        });

        if (istSel) istSel.addEventListener('change', function() {
            var e = state.enj;
            e.istasyonNo = istSel.value ? parseInt(istSel.value, 10) : null;
            e.slot = null;
            if (slotSel) {
                slotSel.innerHTML = '<option value="">— Slot Seçin —</option><option value="A">A</option><option value="B">B</option>';
                slotSel.disabled = !e.istasyonNo;
                slotSel.value = '';
            }
            if ($('upEnjSlotDurum')) { $('upEnjSlotDurum').textContent = '—'; $('upEnjSlotDurum').className = 'up-enj-slot-durum'; }
        });

        if (slotSel) slotSel.addEventListener('change', function() {
            var e = state.enj;
            e.slot = slotSel.value || null;
            if (e.slot) {
                enjSlotDurumYukle();
                if (kalipSel) kalipSel.disabled = false;
                enjBuildKalipSelect();
                enjYukleKaliplar();
            }
        });

        if (kalipSel) kalipSel.addEventListener('change', function() {
            var e = state.enj;
            var opt = kalipSel.options[kalipSel.selectedIndex];
            e.kalipId = kalipSel.value ? parseInt(kalipSel.value, 10) : null;
            e.kalipKod = opt ? opt.textContent.split(' ')[0] : null;
            e.turCift = null;
            if (e.kalipId) enjYukleKalipKapasite();
            else enjHesapGizle();
        });

        if (turEl) turEl.addEventListener('input', enjHesapla);
        if (ciftEl) ciftEl.addEventListener('input', enjHesapla);
        if (basEl) basEl.addEventListener('change', function() {
            state.enj.baslangic = basEl.value || null;
            enjHesapla();
        });
    }

    // ─── ENJEKSİYON PLAN HESABI SONU ────────────────────────────────────────

    function fetchCreateOnizleme(sip) {
        $('upCreateHint').textContent = 'Sorgulanıyor…';
        state.seciliCreate = null;
        state.seciliCreateData = null;
        if ($('upCreatePlanForm')) $('upCreatePlanForm').style.display = 'none';
        if ($('upPlanaEkleBtn')) $('upPlanaEkleBtn').disabled = true;
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
        var o = state.seciliCreateData;
        if (!o) { showError('Model seçin'); return; }
        var enj = state.enj;
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
            enj_makine_id: enj.makineId || null,
            enj_istasyon_no: enj.istasyonNo || null,
            enj_slot: enj.slot || null,
            enj_kalip_id: enj.kalipId || null,
            enj_kalip_kod: enj.kalipKod || null,
            enj_aktif_goz: enj.aktifGoz || null,
            enj_kalip_basi_cift: enj.kalipBasiCift || null,
            enj_tur_cift: enj.turCift || null,
            enj_gunluk_tur_plan: enj.gunlukTur || null,
            enj_gunluk_kapasite: enj.gunlukKap || null,
            enj_plan_baslangic: enj.baslangic || null,
            enj_plan_bitis: enj.bitis || null,
            enj_tahmini_gun: enj.tahminiGun || null,
            enj_planlanacak_cift: enj.planCift || null,
        };
        fetch('/planlama/uretim-plan/api/plan', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); })
            .then(function (res) {
                if (!res.d.ok) throw new Error(res.d.mesaj || 'Kayıt hatası');
                closeModals();
                fetchPlanlar();
            })
            .catch(function (e) { showError(e.message); });
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
        if (!prosesKod) return;
        var blocks = document.querySelectorAll('.up-proses-emir-block');
        blocks.forEach(function (b) { b.classList.remove('up-proses-focus'); });
        var target = document.getElementById('up-proses-block-' + prosesKod) ||
            document.querySelector('.up-proses-emir-block[data-proses-kod="' + prosesKod + '"]');
        if (!target) return;
        target.classList.add('up-proses-focus');
        target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
                renderDetayOzet(d.satir, body);
                loadDetayMEmirler(planId, body, d.satir);
                if (focusProsesKod) {
                    setTimeout(function () { focusDetayProses(focusProsesKod); }, 80);
                }
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

    function renderDetayOzet(r, body) {
        $('upDetayBaslik').textContent = (r.model_kod || '') + ' — ' + (r.renk || '');
        var prosesGrid = renderProsesKartGrid(r.prosesler);
        body.innerHTML =
            '<div class="up-detay-hero">' + thumbHtml(r, 'up-detay-hero-img') +
            '<dl class="up-detay-meta">' +
            '<dt>Sipariş No</dt><dd>' + esc(r.sip_no) + '</dd>' +
            '<dt>Cari</dt><dd>' + esc(r.musteri || r.cari || '—') + '</dd>' +
            '<dt>Model</dt><dd>' + esc(r.model_kod) + '</dd>' +
            '<dt>Renk</dt><dd>' + esc(r.renk) + '</dd>' +
            '<dt>Miktar</dt><dd>' + fmtN(r.miktar) + '</dd>' +
            '<dt>Termin</dt><dd>' + fmtTarih(r.termin) + '</dd>' +
            '<dt>Plan Dönemi</dt><dd>' + esc(r.plan_donemi) + '</dd>' +
            '<dt>Plan Başlangıç</dt><dd>' + fmtTarih(r.plan_baslangic) + '</dd>' +
            '<dt>Plan Bitiş</dt><dd>' + fmtTarih(r.plan_bitis) + '</dd>' +
            '<dt>Öncelik</dt><dd>' + esc(r.oncelik) + '</dd>' +
            '<dt>Durum</dt><dd>' + durumBadge(r.durum, r.durum_renk, r.yuzde) + '</dd>' +
            '</dl></div>' +
            renderEnjOzetHtml(r) +
            '<h4>Proses Durumları</h4><div class="up-proses-ozet-grid">' + prosesGrid + '</div>' +
            '<div class="up-proses-emir-breakdown">' + renderProsesEmirBreakdown(r.prosesler) + '</div>' +
            '<div class="up-detay-tabs">' +
            '<button type="button" class="up-detay-tab active" data-tab="m">M EMİRLER</button>' +
            '<button type="button" class="up-detay-tab" data-tab="y" disabled id="upTabY">Y EMİRLER</button>' +
            '<button type="button" class="up-detay-tab" data-tab="p" disabled id="upTabP">PROSES DETAYI</button>' +
            '</div><div id="upDetayTabBody"></div>';
        if (r.plan_notu) {
            body.insertAdjacentHTML('beforeend', '<p><strong>Plan Notu:</strong> ' + esc(r.plan_notu) + '</p>');
        }
    }

    function loadDetayMEmirler(planId, body, satir) {
        var tabBody = $('upDetayTabBody');
        if (!tabBody) return;
        tabBody.innerHTML = '<div class="up-loading">M emirler yükleniyor…</div>';
        fetch('/planlama/uretim-plan/api/detay/' + planId + '/m-emirler', { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj);
                var proCols = (satir && satir.prosesler) ? satir.prosesler : [];
                var headPro = proCols.map(function (p) {
                    return '<th>' + esc(p.proses_adi || p.proses_kod) + '</th>';
                }).join('');
                var html = '<table class="up-subtbl"><thead><tr><th>M Emir</th><th>Miktar</th><th>Durum</th>' +
                    headPro + '</tr></thead><tbody>';
                (d.m_lotlar || []).forEach(function (m) {
                    var byKod = {};
                    (m.prosesler || []).forEach(function (p) { byKod[String(p.proses_kod)] = p; });
                    var proCells = proCols.map(function (p) {
                        var mp = byKod[String(p.proses_kod)] || {};
                        return '<td>' + (mp.yuzde != null ? mp.yuzde : 0) + '%</td>';
                    }).join('');
                    html += '<tr class="clickable" data-m="' + m.emir_no + '"><td><strong>' + m.emir_no + '</strong></td>' +
                        '<td>' + fmtN(m.miktar) + '</td><td>' + esc(m.durum) + '</td>' + proCells + '</tr>';
                });
                html += '</tbody></table>';
                tabBody.innerHTML = html;
                tabBody.querySelectorAll('tr[data-m]').forEach(function (tr) {
                    tr.addEventListener('click', function () {
                        tabBody.querySelectorAll('tr.selected').forEach(function (x) { x.classList.remove('selected'); });
                        tr.classList.add('selected');
                        var mNo = tr.getAttribute('data-m');
                        loadYEmirler(mNo);
                        $('upTabY').disabled = false;
                        document.querySelectorAll('.up-detay-tab').forEach(function (t) { t.classList.remove('active'); });
                        $('upTabY').classList.add('active');
                    });
                });
            })
            .catch(function (e) { tabBody.innerHTML = esc(e.message); });
    }

    function loadYEmirler(mNo) {
        var tabBody = $('upDetayTabBody');
        tabBody.innerHTML = '<div class="up-loading">Y emirler…</div>';
        fetch('/planlama/uretim-plan/api/detay/m/' + mNo + '/y-emirler', { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.ok) throw new Error(d.mesaj);
                var html = '<p><strong>M Emir ' + mNo + '</strong></p><table class="up-subtbl"><thead><tr>' +
                    '<th>Y Emir</th><th>Kategori</th><th>Stok Kod</th><th>Miktar</th><th>Proses</th>' +
                    '<th>Verilen</th><th>Devam</th><th>Biten</th><th>%</th><th>Durum</th></tr></thead><tbody>';
                (d.y_emirler || []).forEach(function (y) {
                    html += '<tr class="clickable" data-y="' + y.emir_no + '"><td>' + y.emir_no + '</td>' +
                        '<td>' + esc(y.kategori) + '</td><td>' + esc(y.stok_kod) + '</td>' +
                        '<td>' + fmtN(y.miktar) + '</td><td>' + esc(y.proses) + '</td>' +
                        '<td>' + fmtN(y.verilen) + '</td><td>' + fmtN(y.devam) + '</td>' +
                        '<td>' + fmtN(y.biten) + '</td><td>' + (y.yuzde || 0) + '%</td><td>' + esc(y.durum) + '</td></tr>';
                });
                html += '</tbody></table>';
                tabBody.innerHTML = html;
                tabBody.querySelectorAll('tr[data-y]').forEach(function (tr) {
                    tr.addEventListener('click', function () {
                        loadProsesDetay(tr.getAttribute('data-y'));
                        $('upTabP').disabled = false;
                        document.querySelectorAll('.up-detay-tab').forEach(function (t) { t.classList.remove('active'); });
                        $('upTabP').classList.add('active');
                    });
                });
            });
    }

    function loadProsesDetay(emirNo) {
        var tabBody = $('upDetayTabBody');
        tabBody.innerHTML = '<div class="up-loading">Proses detay…</div>';
        fetch('/planlama/uretim-plan/api/detay/emir/' + emirNo + '/proses', { credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var html = '<p><strong>Emir ' + emirNo + ' — Proses Detayı</strong></p><table class="up-subtbl">' +
                    '<thead><tr><th>Ana Proses</th><th>Alt Proses</th><th>Tezgah</th><th>Verilen</th>' +
                    '<th>Devam</th><th>Biten</th><th>Kalan</th><th>%</th><th>Durum</th></tr></thead><tbody>';
                (d.prosesler || []).forEach(function (p) {
                    html += '<tr><td>' + esc(p.proses_adi) + '</td><td>' + esc(p.alt_proses_adi) + '</td>' +
                        '<td>' + esc(p.tezgah || '—') + '</td><td>' + fmtN(p.verilen) + '</td>' +
                        '<td>' + fmtN(p.devam) + '</td><td>' + fmtN(p.biten) + '</td>' +
                        '<td>' + fmtN(p.kalan) + '</td><td>' + (p.yuzde || 0) + '%</td>' +
                        '<td>' + esc(p.durum) + '</td></tr>';
                });
                html += '</tbody></table>';
                tabBody.innerHTML = html;
            });
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
                $('upCreateListe').innerHTML = '';
                $('upCreatePlanForm').style.display = 'none';
                $('upCreateSipNo').value = '';
                $('upCreateHint').textContent = '';
                $('upCreateModal').hidden = false;
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
