"""PATCH PIVOT: Sade tablo yerine kategori+proses pivot, + ile expand.

Ust satir: KAT | PROSES | BASLAYACAK | DEVAM | BITEN | KALAN | EMIR_SAYISI
+ tiklayinca emir detay tablosu acilir
"""
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\plan_v2.js'
CSS_PATH = r'C:\cps_dev\static\css\plan_v2.css'

JS_MARKER = '_planv2PivotTablo'
CSS_MARKER = '/* === PIVOT TABLO === */'

# === JS ===
with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

if JS_MARKER in js_src:
    print('SKIP-JS: pivot zaten uygulanmis')
else:
    OLD_BAS = "    /* === SADE KORGUN TABLO === */"
    OLD_SON = "    /* === /SADE KORGUN TABLO === */"

    if OLD_BAS not in js_src or OLD_SON not in js_src:
        print('HATA: SADE KORGUN TABLO anchor bulunamadi')
        sys.exit(1)

    bas_idx = js_src.find(OLD_BAS)
    son_idx = js_src.find(OLD_SON) + len(OLD_SON)

    YENI_BLOK = """    /* === PIVOT TABLO === */
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
                        var pKey = 'MAMUL|' + (p.proses_adi || p.proses_kod);
                        if (!bucket[pKey]) bucket[pKey] = _bucketYeni('MAMUL', p.proses_adi || p.proses_kod, parseInt(p.proses_kod) || 0);
                        bucket[pKey].emir_listesi.push({
                            emir_no: me.emir_no,
                            baslayacak: 0,
                            biten: parseInt(p.yapilan || 0),
                            hedef: parseInt(me.yaz_say || 0),
                        });
                        bucket[pKey].toplam_biten += parseInt(p.yapilan || 0);
                        bucket[pKey].toplam_kalan += Math.max(0, parseInt(me.yaz_say || 0) - parseInt(p.yapilan || 0));
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
            grandBiten += ps.toplam_biten;
            grandKalan += ps.toplam_kalan;
            grandEmir += ps.emir_sayisi;

            var katClass = 'kat-' + ps.kategori.toLowerCase().replace(/[^a-z]/g, '');
            var bitenClass = ps.toplam_biten > 0 ? 'biten-yesil' : '';
            var kalanClass = ps.toplam_kalan > 0 ? 'kalan-kirmizi' : '';
            var baslayacakClass = ps.toplam_baslayacak > 0 ? 'baslayacak-gri' : '';

            var rowId = 'pivot-row-' + psi;

            // Ana pivot satiri
            html += '<tr class="planv2-pivot-ana ' + katClass + '" data-row-id="' + rowId + '" onclick="planv2PivotToggle(\\'' + rowId + '\\')">';
            html += '<td class="col-expand"><span class="planv2-expand-icon" id="icon-' + rowId + '">+</span></td>';
            html += '<td><span class="planv2-kat-pill ' + katClass + '">' + _esc(ps.kategori) + '</span></td>';
            html += '<td>' + _esc(ps.proses_adi) + '</td>';
            html += '<td class="num ' + baslayacakClass + '">' + _fmt(ps.toplam_baslayacak) + '</td>';
            html += '<td class="num">0</td>';
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
                var emKalan = Math.max(0, em.hedef - em.biten);
                var emBitenClass = em.biten > 0 ? 'biten-yesil' : '';
                var emKalanClass = emKalan > 0 ? 'kalan-kirmizi' : '';
                var emBaslayacakClass = em.baslayacak > 0 ? 'baslayacak-gri' : '';

                html += '<tr>';
                html += '<td>' + _esc(em.emir_no) + '</td>';
                html += '<td class="num ' + emBaslayacakClass + '">' + _fmt(em.baslayacak) + '</td>';
                html += '<td class="num">0</td>';
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
        html += '<td class="num"><strong>0</strong></td>';
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
                var key2 = kategori + '|' + (p.proses_adi || p.proses_kod);
                if (!bucket[key2]) bucket[key2] = _bucketYeni(kategori, p.proses_adi || p.proses_kod, parseInt(p.proses_kod) || 0);
                bucket[key2].emir_listesi.push({
                    emir_no: emir.emir_no,
                    baslayacak: 0,
                    biten: parseInt(p.yapilan || 0),
                    hedef: hedef,
                });
                bucket[key2].toplam_biten += parseInt(p.yapilan || 0);
                bucket[key2].toplam_kalan += Math.max(0, hedef - parseInt(p.yapilan || 0));
                bucket[key2].emir_sayisi++;
            }
        }
    }

    window.planv2PivotToggle = function (rowId) {
        var detay = document.getElementById('detay-' + rowId);
        var icon = document.getElementById('icon-' + rowId);
        if (!detay) return;
        if (detay.style.display === 'none') {
            detay.style.display = '';
            if (icon) icon.textContent = '−';
        } else {
            detay.style.display = 'none';
            if (icon) icon.textContent = '+';
        }
    };
    /* === /PIVOT TABLO === */"""

    js_src = js_src[:bas_idx] + YENI_BLOK + js_src[son_idx:]

    # _planv2SadeTablo cagrisini _planv2PivotTablo ile degistir
    js_src = js_src.replace('_planv2SadeTablo(d)', '_planv2PivotTablo(d)')

    bak_js = JS_PATH + '.bak_pre_pivot_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_src)
    print('OK-JS: pivot tablo eklendi')


# === CSS ===
with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: pivot zaten uygulanmis')
else:
    CSS_ADD = '''

/* === PIVOT TABLO === */
.planv2-pivot-tablo {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    overflow: hidden;
}
.planv2-pivot-tablo thead {
    background: #f3f4f6;
}
.planv2-pivot-tablo th {
    text-align: left;
    padding: 10px;
    font-size: 11px;
    font-weight: 700;
    color: #374151;
    letter-spacing: 0.5px;
    border-bottom: 1px solid #e5e7eb;
}
.planv2-pivot-tablo th.num,
.planv2-pivot-tablo td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.col-expand {
    width: 30px;
    text-align: center;
}

.planv2-pivot-ana {
    cursor: pointer;
    transition: background 0.1s;
}
.planv2-pivot-ana:hover {
    background: #fef3c7;
}
.planv2-pivot-ana td {
    padding: 10px;
    border-bottom: 1px solid #f3f4f6;
    color: #1f2937;
    font-weight: 500;
}

.planv2-expand-icon {
    display: inline-block;
    width: 20px;
    height: 20px;
    line-height: 18px;
    text-align: center;
    background: #f3f4f6;
    border-radius: 3px;
    font-weight: 700;
    color: #374151;
    font-size: 14px;
}
.planv2-pivot-ana:hover .planv2-expand-icon {
    background: #fef3c7;
    color: #92400e;
}

.planv2-pivot-detay td.planv2-detay-cell {
    padding: 0;
    background: #fafafa;
    border-bottom: 2px solid #e5e7eb;
}

.planv2-emir-tablo {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    margin: 0;
}
.planv2-emir-tablo thead {
    background: #fff;
}
.planv2-emir-tablo th {
    text-align: left;
    padding: 6px 12px;
    font-size: 10px;
    font-weight: 600;
    color: #6b7280;
    letter-spacing: 0.5px;
    border-bottom: 1px solid #e5e7eb;
}
.planv2-emir-tablo th.num,
.planv2-emir-tablo td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.planv2-emir-tablo td {
    padding: 4px 12px;
    border-bottom: 1px solid #f3f4f6;
    color: #374151;
}
.planv2-emir-tablo tbody tr:hover {
    background: #f9fafb;
}
.planv2-emir-tablo td:first-child {
    padding-left: 50px;
    font-weight: 600;
    color: #1f2937;
}
'''

    bak_css = CSS_PATH + '.bak_pre_pivot_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: pivot stil eklendi')

print()
print('TAMAM: Pivot tablo uygulandi')
print('Test: Ctrl+Shift+R, satira tikla, + ile detay ac')