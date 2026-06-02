/* CPS PLAN v2 - Frontend logic */
(function () {
    'use strict';

    var API_BASE = '/hedef/v2';

    function _fmt(n) {
        if (n === null || n === undefined || n === '') return '0';
        var x = Number(n);
        if (!isFinite(x)) return '0';
        return Math.round(x).toLocaleString('tr-TR');
    }

    function _esc(s) {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _termin(t) {
        if (!t) return '-';
        try {
            var d = new Date(t);
            var bugun = new Date();
            var fark = Math.floor((bugun - d) / (1000 * 60 * 60 * 24));
            var s = t.substring(0, 10);
            if (fark > 0) {
                return s + ' <small style="color:#dc2626;">(' + fark + ' gün geçti)</small>';
            }
            return s;
        } catch (e) {
            return t;
        }
    }

    /* ========= PLAN ANA LISTE ========= */
    function planv2YukleListe() {
        var loading = document.getElementById('planv2Loading');
        var tablo = document.getElementById('planv2Tablo');
        var empty = document.getElementById('planv2Empty');
        var body = document.getElementById('planv2Body');
        var modeBadge = document.getElementById('planv2ModeBadge');

        if (loading) loading.style.display = '';
        if (tablo) tablo.style.display = 'none';
        if (empty) empty.style.display = 'none';

        // Saglik kontrolu (mode badge)
        fetch(API_BASE + '/saglik')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (modeBadge) {
                    if (d.mock_mode) {
                        modeBadge.textContent = 'MOCK MODE (data yarın)';
                        modeBadge.classList.remove('canli');
                    } else {
                        modeBadge.textContent = 'CANLI';
                        modeBadge.classList.add('canli');
                    }
                }
            })
            .catch(function () {});

        fetch(API_BASE + '/plan')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (loading) loading.style.display = 'none';
                if (!d || !d.ok) {
                    if (empty) {
                        empty.textContent = 'Hata: ' + (d && d.mesaj ? d.mesaj : 'bilinmeyen');
                        empty.style.display = '';
                    }
                    return;
                }
                var s = d.siparisler || [];
                if (s.length === 0) {
                    if (empty) empty.style.display = '';
                    return;
                }
                var html = '';
                for (var i = 0; i < s.length; i++) {
                    html += _planv2Satir(s[i]);
                }
                if (body) body.innerHTML = html;
                if (tablo) tablo.style.display = '';
            })
            .catch(function (err) {
                if (loading) loading.style.display = 'none';
                if (empty) {
                    empty.textContent = 'Sunucuya ulaşılamadı: ' + err.message;
                    empty.style.display = '';
                }
            });
    }

    function _planv2Satir(s) {
        var renk = s.durum_renk || 'kirmizi';
        var darbogazRenkClass = 'kirmizi';
        if (s.darbogaz_kategori === 'GOVDE') darbogazRenkClass = 'govde';
        else if (s.darbogaz_kategori === 'MAMUL') darbogazRenkClass = 'mamul';

        var yuzdeClass = 'kirmizi';
        if (s.yuzde >= 50) yuzdeClass = 'yesil';
        else if (s.yuzde > 0) yuzdeClass = 'sari';

        var summaryHtml = '';
        if (s.summary) {
            summaryHtml = '<tr class="planv2-summary-row" onclick="planv2DetayAc(' + s.sip_no + ')">' +
                '<td colspan="10" class="planv2-summary-td">\u21B3 ' + _esc(s.summary) + '</td>' +
                '</tr>';
        }
        return '<tr onclick="planv2DetayAc(' + s.sip_no + ')" data-sip-no="' + s.sip_no + '">' +
            '<td class="col-durum"><span class="planv2-durum-nokta ' + renk + '"></span></td>' +
            '<td class="col-sipno">' + _esc(s.sip_no) + '</td>' +
            '<td class="col-musteri">' + _esc(s.musteri || '-') + '</td>' +
            '<td class="col-model">' + _esc(s.model_kod || '-') + '</td>' +
            '<td class="col-hedef">' + _fmt(s.hedef) + '</td>' +
            '<td class="col-yapilan">' + _fmt(s.yapilan) + '</td>' +
            '<td class="col-kalan">' + _fmt(s.kalan) + '</td>' +
            '<td class="col-termin">' + _termin(s.termin) + '</td>' +
            '<td class="col-darbogaz"><span class="planv2-darbogaz-pill ' + darbogazRenkClass + '">' +
                _esc(s.darbogaz_kategori || '-') + '</span></td>' +
            '<td class="col-yuzde"><span class="planv2-yuzde-pill ' + yuzdeClass + '">%' +
                _fmt(s.yuzde) + '</span></td>' +
            '</tr>' + summaryHtml;
    }

    /* ========= DETAY PANEL ========= */
    window.planv2DetayAc = function (sipNo) {
        var overlay = document.getElementById('planv2DetayOverlay');
        var icerik = document.getElementById('planv2DetayIcerik');
        var baslik = document.getElementById('planv2DetayBaslik');
        if (!overlay || !icerik) return;

        if (icerik) icerik.innerHTML = '<div class="planv2-loading">Yükleniyor...</div>';
        if (baslik) baslik.textContent = 'Sipariş ' + sipNo;
        overlay.style.display = 'flex';

        fetch(API_BASE + '/plan-detay-v2/' + encodeURIComponent(sipNo))
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) {
                    icerik.innerHTML = '<div class="planv2-empty">Hata: ' +
                        _esc((d && d.mesaj) || 'bilinmeyen') + '</div>';
                    return;
                }
                if (baslik) {
                    baslik.textContent = 'Sipariş ' + d.sip_no + ' · ' +
                        (d.musteri || '-') + ' · ' + (d.model_kod || '-');
                }
                icerik.innerHTML = _planv2PivotTablo(d);
            })
            .catch(function (err) {
                icerik.innerHTML = '<div class="planv2-empty">Hata: ' + _esc(err.message) + '</div>';
            });
    };

    window.planv2DetayKapat = function () {
        var overlay = document.getElementById('planv2DetayOverlay');
        if (overlay) overlay.style.display = 'none';
    };

    /* === PIVOT TABLO === */
    function _planv2PivotTablo(d) {
        var html = '';

        // Ust bilgi
        html += '<div class="planv2-ust-bilgi">';
        html += '<strong>Sipariş:</strong> ' + _esc(d.sip_no);
        html += ' &nbsp; <strong>Müşteri:</strong> ' + _esc(d.musteri || '-');
        html += ' &nbsp; <strong>Hedef:</strong> ' + _fmt(d.hedef);
        if (d.termin) {
            html += ' &nbsp; <strong>Termin:</strong> ' + _esc(String(d.termin).substring(0, 10));
        }
        html += '</div>';

        // Pivot bucket: kategori + proses_adi -> {biten, baslayacak, emir_listesi}
        var bucket = {};

        var modeller = d.modeller || [];
        for (var mi = 0; mi < modeller.length; mi++) {
            var m = modeller[mi];
            var mamulEmirler = m.mamul_emirler || [];

            for (var ei = 0; ei < mamulEmirler.length; ei++) {
                var me = mamulEmirler[ei];
                var k = me.korgun || {};

                // MAMUL prosesleri (her emir x her proses)
                var mamulProsesler = (k.mamul && k.mamul.prosesler) || [];
                if (mamulProsesler.length === 0) {
                    var key0 = 'MAMUL|-';
                    if (!bucket[key0]) bucket[key0] = _bucketYeni('MAMUL', '-', 0);
                    bucket[key0].emir_listesi.push({
                        emir_no: me.emir_no,
                        baslayacak: parseInt(me.yaz_say || 0),
                        biten: 0,
                        hedef: parseInt(me.yaz_say || 0),
                    });
                    bucket[key0].toplam_baslayacak += parseInt(me.yaz_say || 0);
                    bucket[key0].toplam_kalan += parseInt(me.yaz_say || 0);
                    bucket[key0].emir_sayisi++;
                } else {
                    for (var pi = 0; pi < mamulProsesler.length; pi++) {
                        var p = mamulProsesler[pi];
                        /* BITEN BASLAYACAK FIX */
                        var pBiten = parseInt((p.biten !== undefined ? p.biten : p.yapilan) || 0);
                        var pBaslayacak = parseInt(p.baslayacak || 0);
                        var pDevam = parseInt(p.devam || 0);
                        var pHedefEmir = parseInt(me.yaz_say || 0);
                        var pKalan = pBaslayacak + pDevam;
                        var pKey = 'MAMUL|' + (p.proses_adi || p.proses_kod);
                        if (!bucket[pKey]) bucket[pKey] = _bucketYeni('MAMUL', p.proses_adi || p.proses_kod, parseInt(p.proses_kod) || 0);
                        bucket[pKey].emir_listesi.push({
                            emir_no: me.emir_no,
                            baslayacak: pBaslayacak,
                            devam: pDevam,
                            biten: pBiten,
                            hedef: pHedefEmir,
                        });
                        bucket[pKey].toplam_biten += pBiten;
                        bucket[pKey].toplam_baslayacak += pBaslayacak;
                        bucket[pKey].toplam_devam += pDevam;
                        bucket[pKey].toplam_kalan += pKalan;
                        bucket[pKey].emir_sayisi++;
                    }
                }

                // GOVDE alt emirler
                var govdeEmirler = (k.govde && k.govde.emirler) || [];
                for (var gi = 0; gi < govdeEmirler.length; gi++) {
                    _bucketEmirEkle(bucket, 'GÖVDE', govdeEmirler[gi]);
                }

                // ATKI alt emirler
                var atkiEmirler = (k.atki && k.atki.emirler) || [];
                for (var ai = 0; ai < atkiEmirler.length; ai++) {
                    _bucketEmirEkle(bucket, 'ATKI', atkiEmirler[ai]);
                }
            }
        }

        // Bucket -> liste, sirala
        var pivotSatirlar = [];
        for (var key in bucket) {
            if (Object.prototype.hasOwnProperty.call(bucket, key)) {
                pivotSatirlar.push(bucket[key]);
            }
        }
        pivotSatirlar.sort(function (a, b) {
            var katSira = {'MAMUL': 1, 'GÖVDE': 2, 'ATKI': 3};
            var ks = (katSira[a.kategori] || 9) - (katSira[b.kategori] || 9);
            if (ks !== 0) return ks;
            return a.proses_kod - b.proses_kod;
        });

        // Tablo render
        html += '<table class="planv2-pivot-tablo">';
        html += '<thead><tr>';
        html += '<th class="col-expand"></th>';
        html += '<th>KATEGORİ</th>';
        html += '<th>PROSES</th>';
        html += '<th class="num">BAŞLAYACAK</th>';
        html += '<th class="num">DEVAM</th>';
        html += '<th class="num">BİTEN</th>';
        html += '<th class="num">KALAN</th>';
        html += '<th class="num">EMİR</th>';
        html += '</tr></thead><tbody>';

        var grandBaslayacak = 0;
        var grandDevam = 0;
        var grandBiten = 0;
        var grandKalan = 0;
        var grandEmir = 0;

        for (var psi = 0; psi < pivotSatirlar.length; psi++) {
            var ps = pivotSatirlar[psi];
            grandBaslayacak += ps.toplam_baslayacak;
            grandDevam += (ps.toplam_devam || 0);
            grandBiten += ps.toplam_biten;
            grandKalan += ps.toplam_kalan;
            grandEmir += ps.emir_sayisi;

            var katClass = 'kat-' + ps.kategori.toLowerCase().replace(/[^a-z]/g, '');
            var bitenClass = ps.toplam_biten > 0 ? 'biten-yesil' : '';
            var kalanClass = ps.toplam_kalan > 0 ? 'kalan-kirmizi' : '';
            var baslayacakClass = ps.toplam_baslayacak > 0 ? 'baslayacak-gri' : '';

            var rowId = 'pivot-row-' + psi;

            // Ana pivot satiri
            html += '<tr class="planv2-pivot-ana ' + katClass + '" data-row-id="' + rowId + '" onclick="planv2PivotToggle(\'' + rowId + '\')">';
            html += '<td class="col-expand"><span class="planv2-expand-icon" id="icon-' + rowId + '">+</span></td>';
            html += '<td><span class="planv2-kat-pill ' + katClass + '">' + _esc(ps.kategori) + '</span></td>';
            html += '<td>' + _esc(ps.proses_adi) + '</td>';
            html += '<td class="num ' + baslayacakClass + '">' + _fmt(ps.toplam_baslayacak) + '</td>';
            html += '<td class="num">' + _fmt(ps.toplam_devam || 0) + '</td>';
            html += '<td class="num ' + bitenClass + '">' + _fmt(ps.toplam_biten) + '</td>';
            html += '<td class="num ' + kalanClass + '">' + _fmt(ps.toplam_kalan) + '</td>';
            html += '<td class="num">' + _fmt(ps.emir_sayisi) + '</td>';
            html += '</tr>';

            // Detay satiri (gizli)
            html += '<tr class="planv2-pivot-detay" id="detay-' + rowId + '" style="display:none;">';
            html += '<td colspan="8" class="planv2-detay-cell">';
            html += '<table class="planv2-emir-tablo"><thead><tr>';
            html += '<th>EMİR</th>';
            html += '<th class="num">BAŞLAYACAK</th>';
            html += '<th class="num">DEVAM</th>';
            html += '<th class="num">BİTEN</th>';
            html += '<th class="num">KALAN</th>';
            html += '</tr></thead><tbody>';

            for (var ei2 = 0; ei2 < ps.emir_listesi.length; ei2++) {
                var em = ps.emir_listesi[ei2];
                /* BITEN BASLAYACAK FIX - kalan = baslayacak + devam */
                var emBaslayacak = parseInt(em.baslayacak || 0);
                var emDevam = parseInt(em.devam || 0);
                var emKalan = emBaslayacak + emDevam;
                var emBitenClass = em.biten > 0 ? 'biten-yesil' : '';
                var emKalanClass = emKalan > 0 ? 'kalan-kirmizi' : '';
                var emBaslayacakClass = em.baslayacak > 0 ? 'baslayacak-gri' : '';

                html += '<tr>';
                html += '<td>' + _esc(em.emir_no) + '</td>';
                html += '<td class="num ' + emBaslayacakClass + '">' + _fmt(emBaslayacak) + '</td>';
                html += '<td class="num">' + _fmt(emDevam) + '</td>';
                html += '<td class="num ' + emBitenClass + '">' + _fmt(em.biten) + '</td>';
                html += '<td class="num ' + emKalanClass + '">' + _fmt(emKalan) + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table>';
            html += '</td></tr>';
        }

        // GRAND TOPLAM
        html += '<tr class="planv2-toplam">';
        html += '<td></td>';
        html += '<td colspan="2"><strong>TOPLAM</strong></td>';
        html += '<td class="num"><strong>' + _fmt(grandBaslayacak) + '</strong></td>';
        html += '<td class="num"><strong>' + _fmt(grandDevam || 0) + '</strong></td>';
        html += '<td class="num biten-yesil"><strong>' + _fmt(grandBiten) + '</strong></td>';
        html += '<td class="num kalan-kirmizi"><strong>' + _fmt(grandKalan) + '</strong></td>';
        html += '<td class="num"><strong>' + _fmt(grandEmir) + '</strong></td>';
        html += '</tr>';

        html += '</tbody></table>';

        // CPS dipnot
        var cpsg = d.cps_genel || {};
        var personel = cpsg.personel_uretim || [];
        if (personel.length > 0) {
            html += '<div class="planv2-cps-dipnot"><strong>CPS Personel:</strong> ';
            var ps2 = [];
            for (var pi2 = 0; pi2 < personel.length; pi2++) {
                ps2.push(_esc(personel[pi2].personel_ad) + ' ' + _fmt(personel[pi2].toplam_miktar));
            }
            html += ps2.join(' &middot; ');
            html += '</div>';
        }

        return html;
    }

    function _bucketYeni(kategori, proses_adi, proses_kod) {
        return {
            kategori: kategori,
            proses_adi: proses_adi,
            proses_kod: proses_kod,
            toplam_baslayacak: 0,
            toplam_devam: 0,
            toplam_biten: 0,
            toplam_kalan: 0,
            emir_sayisi: 0,
            emir_listesi: [],
        };
    }

    function _bucketEmirEkle(bucket, kategori, emir) {
        var prosesler = emir.prosesler || [];
        var hedef = parseInt(emir.yaz_say || 0);

        if (prosesler.length === 0) {
            // Hic proses yok - "henuz yok" satiri
            var key = kategori + '|-';
            if (!bucket[key]) bucket[key] = _bucketYeni(kategori, '(henüz yok)', 0);
            bucket[key].emir_listesi.push({
                emir_no: emir.emir_no,
                baslayacak: hedef,
                biten: 0,
                hedef: hedef,
            });
            bucket[key].toplam_baslayacak += hedef;
            bucket[key].toplam_kalan += hedef;
            bucket[key].emir_sayisi++;
        } else {
            for (var pi = 0; pi < prosesler.length; pi++) {
                var p = prosesler[pi];
                /* BITEN BASLAYACAK FIX */
                var pBiten = parseInt((p.biten !== undefined ? p.biten : p.yapilan) || 0);
                var pBaslayacak = parseInt(p.baslayacak || 0);
                var pDevam = parseInt(p.devam || 0);
                var pKalan = pBaslayacak + pDevam;
                var key2 = kategori + '|' + (p.proses_adi || p.proses_kod);
                if (!bucket[key2]) bucket[key2] = _bucketYeni(kategori, p.proses_adi || p.proses_kod, parseInt(p.proses_kod) || 0);
                bucket[key2].emir_listesi.push({
                    emir_no: emir.emir_no,
                    baslayacak: pBaslayacak,
                    devam: pDevam,
                    biten: pBiten,
                    hedef: hedef,
                });
                bucket[key2].toplam_biten += pBiten;
                bucket[key2].toplam_baslayacak += pBaslayacak;
                bucket[key2].toplam_devam += pDevam;
                bucket[key2].toplam_kalan += pKalan;
                bucket[key2].emir_sayisi++;
            }
        }
    }

    window.planv2PivotToggle = function (rowId) {
        /* ACCORDION MODU */
        var detay = document.getElementById('detay-' + rowId);
        var icon = document.getElementById('icon-' + rowId);
        if (!detay) return;
        var acilacak = (detay.style.display === 'none');
        var tumDetaylar = document.querySelectorAll('.planv2-pivot-detay');
        for (var i = 0; i < tumDetaylar.length; i++) {
            tumDetaylar[i].style.display = 'none';
        }
        var tumIkonlar = document.querySelectorAll('.planv2-expand-icon');
        for (var j = 0; j < tumIkonlar.length; j++) {
            tumIkonlar[j].textContent = '+';
        }
        if (acilacak) {
            detay.style.display = '';
            if (icon) icon.textContent = '−';
        }
    };
    /* === /PIVOT TABLO === */

    function _planv2DetayHtml(d) {
        var html = '';

        // KORGUN BLOK
        var k = d.korgun || {};
        var atki = k.atki || {tamamlanan:0, hedef:d.hedef||0, yuzde:0, emirler:[]};
        var govde = k.govde || {tamamlanan:0, hedef:d.hedef||0, yuzde:0, emirler:[]};
        var mamul = k.mamul || {tamamlanan:0, hedef:d.hedef||0, yuzde:0, emirler:[]};
        var darb = d.darbogaz || {};

        html += '<div class="planv2-blok korgun">';
        html += '<div class="planv2-blok-baslik">📊 KORGUN GERÇEK ÜRETİM</div>';
        html += '<div class="planv2-blok-icerik">';
        html += _planv2BarRow('ATKI', atki, darb.kategori === 'ATKI');
        html += _planv2BarRow('GÖVDE', govde, darb.kategori === 'GOVDE');
        html += _planv2BarRow('MAMUL', mamul, darb.kategori === 'MAMUL');

        // Emir listesi (gizli, gostermek istersen toggle)
        var totalEmir = (atki.emirler||[]).length + (govde.emirler||[]).length + (mamul.emirler||[]).length;
        if (totalEmir > 0) {
            html += '<div class="planv2-emir-listesi" style="margin-top:12px;">';
            html += '<strong>Emir bazlı detay (' + totalEmir + ' emir):</strong><br>';
            html += _planv2EmirListesi('ATKI', atki.emirler);
            html += _planv2EmirListesi('GÖVDE', govde.emirler);
            html += _planv2EmirListesi('MAMUL', mamul.emirler);
            html += '</div>';
        }
        html += '</div></div>';

        // CPS BLOK
        var cps = d.cps || {};
        var sablonProsesleri = cps.sablon_prosesleri || [];
        var personel = cps.personel_uretim || [];
        html += '<div class="planv2-blok cps">';
        html += '<div class="planv2-blok-baslik">⚙️ CPS OPERASYON / PERSONEL</div>';
        html += '<div class="planv2-blok-icerik">';

        if (sablonProsesleri.length > 0) {
            html += '<strong style="font-size:12px;">Şablon prosesleri:</strong>';
            html += '<div class="planv2-cps-grid">';
            for (var i = 0; i < sablonProsesleri.length; i++) {
                var p = sablonProsesleri[i];
                html += '<div class="planv2-cps-item">' +
                    '<div class="planv2-cps-item-adi">' + _esc(p.proses_adi) + '</div>' +
                    '<div class="planv2-cps-item-deger">' + _fmt(p.yapilan) + '</div>' +
                    '</div>';
            }
            html += '</div>';
        } else {
            html += '<div style="color:#9ca3af;font-style:italic;">Şablon prosesi yok.</div>';
        }

        if (personel.length > 0) {
            html += '<div style="margin-top:14px;"><strong style="font-size:12px;">Personel üretimi:</strong></div>';
            for (var j = 0; j < personel.length; j++) {
                var per = personel[j];
                html += '<div style="font-size:12px;padding:4px 0;">' +
                    _esc(per.personel_ad) + ': ' + _fmt(per.toplam_miktar) + ' (' +
                    per.kayit_sayisi + ' kayıt)</div>';
            }
        } else {
            html += '<div style="margin-top:10px;color:#9ca3af;font-style:italic;font-size:12px;">' +
                'Personel üretim verisi yok.</div>';
        }

        html += '<div style="margin-top:14px;color:#9ca3af;font-style:italic;font-size:11px;">' +
            'Prim/Performans: ileride hesaplanacak.</div>';
        html += '</div></div>';

        // DURUM/AKSIYON BLOK
        html += '<div class="planv2-blok durum">';
        html += '<div class="planv2-blok-baslik">🎯 DURUM</div>';
        html += '<div class="planv2-blok-icerik">';
        html += '<div class="planv2-durum-mesaj">DARBOĞAZ: ' + _esc(darb.kategori || '-') +
            ' (' + _fmt(darb.yapilan) + ' / ' + _fmt(d.hedef) + ', %' + _fmt(darb.yuzde) + ')</div>';

        var mesaj = '';
        if (darb.kategori === 'ATKI' && atki.tamamlanan === 0) {
            mesaj = 'ATKI üretimi henüz başlamadı (' + (atki.emir_sayisi || 0) + ' emir bekliyor).';
        } else if (darb.kategori === 'GOVDE' && govde.tamamlanan === 0) {
            mesaj = 'GÖVDE üretimi henüz başlamadı (' + (govde.emir_sayisi || 0) + ' emir bekliyor).';
        } else if (darb.kategori === 'MAMUL' && mamul.tamamlanan === 0) {
            mesaj = 'MAMUL üretimi henüz başlamadı.';
        } else if (darb.yuzde > 0 && darb.yuzde < 100) {
            mesaj = 'Üretim devam ediyor.';
        }
        if (mesaj) {
            html += '<div class="planv2-durum-detay">' + _esc(mesaj) + '</div>';
        }
        html += '</div></div>';

        return html;
    }

    function _planv2BarRow(label, blok, isDarbogaz) {
        var yuzde = Number(blok.yuzde || 0);
        var fillRenk = 'yesil';
        if (yuzde === 0) fillRenk = 'kirmizi';
        else if (yuzde < 50) fillRenk = 'sari';
        var fillW = Math.min(100, Math.max(0, yuzde));
        var darbogazClass = isDarbogaz ? ' darbogaz' : '';
        return '<div class="planv2-bar-row' + darbogazClass + '">' +
            '<div class="planv2-bar-label">' + label + '</div>' +
            '<div class="planv2-bar-track"><div class="planv2-bar-fill ' + fillRenk +
                '" style="width:' + fillW + '%;"></div></div>' +
            '<div class="planv2-bar-sayi">' + _fmt(blok.tamamlanan) + ' / ' + _fmt(blok.hedef) + '</div>' +
            '<div class="planv2-bar-yuzde">%' + _fmt(yuzde) + '</div>' +
            '</div>';
    }

    function _planv2EmirListesi(label, emirler) {
        if (!emirler || !emirler.length) return '';
        var html = '<div class="planv2-emir-satir"><strong>' + label + ':</strong> ';
        var parts = [];
        for (var i = 0; i < emirler.length; i++) {
            var e = emirler[i];
            var sp = e.son_proses ? ' (' + _esc(e.son_proses) + ' ' + _fmt(e.son_yapilan) + ')' : '';
            parts.push('E.' + e.emir_no + sp);
        }
        html += parts.join(' · ') + '</div>';
        return html;
    }

    /* Overlay disina tiklayinca kapat */
    document.addEventListener('click', function (ev) {
        var overlay = document.getElementById('planv2DetayOverlay');
        if (overlay && ev.target === overlay) {
            overlay.style.display = 'none';
        }
    });

    /* ESC ile kapat */
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape') {
            var overlay = document.getElementById('planv2DetayOverlay');
            if (overlay) overlay.style.display = 'none';
        }
    });

    /* Sayfa yuklendiginde calis */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', planv2YukleListe);
    } else {
        planv2YukleListe();
    }

    console.log('[CPS LOCAL] PLAN v2 yuklendi');
})();