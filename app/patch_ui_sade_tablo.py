"""PATCH UI SADE: PLAN detay panelinde sadece Korgun gibi duz tablo.
Slogan yok, ozet bloku yok. Emir + Proses + Baslayacak + Devam + Biten + Kalan.
Altta TOPLAM satiri.
"""
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\plan_v2.js'
CSS_PATH = r'C:\cps_dev\static\css\plan_v2.css'

JS_MARKER = '_planv2SadeTablo'
CSS_MARKER = '/* === SADE KORGUN TABLO === */'

# === JS - eski _planv2DetayHiyerarsik fonksiyonunu komple ez ===
with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

if JS_MARKER in js_src:
    print('SKIP-JS: sade tablo zaten uygulanmis')
else:
    # Mevcut _planv2DetayHiyerarsik fonksiyonunu bul ve ezilecek
    OLD_BAS = """    /* === U3 HIYERARSI === */
    function _planv2DetayHiyerarsik(d) {"""
    OLD_SON = """    /* === /U3 HIYERARSI === */"""

    if OLD_BAS not in js_src or OLD_SON not in js_src:
        print('HATA: U3 anchor bulunamadi')
        sys.exit(1)

    bas_idx = js_src.find(OLD_BAS)
    son_idx = js_src.find(OLD_SON) + len(OLD_SON)
    
    YENI_BLOK = """    /* === SADE KORGUN TABLO === */
    function _planv2SadeTablo(d) {
        var html = '';

        // Ust bilgi - tek satir
        html += '<div class="planv2-ust-bilgi">';
        html += '<strong>Sipariş:</strong> ' + _esc(d.sip_no);
        html += ' &nbsp;&nbsp; <strong>Müşteri:</strong> ' + _esc(d.musteri || '-');
        html += ' &nbsp;&nbsp; <strong>Hedef:</strong> ' + _fmt(d.hedef);
        if (d.termin) {
            html += ' &nbsp;&nbsp; <strong>Termin:</strong> ' + _esc(String(d.termin).substring(0, 10));
        }
        html += '</div>';

        // Tablo
        html += '<table class="planv2-sade-tablo">';
        html += '<thead><tr>';
        html += '<th>EMİR</th>';
        html += '<th>KATEGORİ</th>';
        html += '<th>PROSES</th>';
        html += '<th class="num">BAŞLAYACAK</th>';
        html += '<th class="num">DEVAM</th>';
        html += '<th class="num">BİTEN</th>';
        html += '<th class="num">KALAN</th>';
        html += '</tr></thead><tbody>';

        // Satirlari topla - her emir x her proses
        var satirlar = [];
        var modeller = d.modeller || [];
        for (var mi = 0; mi < modeller.length; mi++) {
            var m = modeller[mi];
            var mamulEmirler = m.mamul_emirler || [];
            for (var ei = 0; ei < mamulEmirler.length; ei++) {
                var me = mamulEmirler[ei];
                var k = me.korgun || {};

                // MAMUL emir prosesleri
                var mamulProsesler = (k.mamul && k.mamul.prosesler) || [];
                for (var pi = 0; pi < mamulProsesler.length; pi++) {
                    var p = mamulProsesler[pi];
                    satirlar.push({
                        emir_no: me.emir_no,
                        kategori: 'MAMUL',
                        proses_adi: p.proses_adi || p.proses_kod,
                        proses_kod: parseInt(p.proses_kod) || 0,
                        biten: parseInt(p.yapilan || 0),
                        baslayacak: 0,
                        devam: 0,
                        hedef_emir: parseInt(me.yaz_say || 0),
                    });
                }

                // GOVDE alt emirler
                var govdeEmirler = (k.govde && k.govde.emirler) || [];
                for (var gi = 0; gi < govdeEmirler.length; gi++) {
                    var ge = govdeEmirler[gi];
                    var gp = ge.prosesler || [];
                    if (gp.length === 0) {
                        // Hic proses yoksa baslayacak satiri olarak goster
                        satirlar.push({
                            emir_no: ge.emir_no,
                            kategori: 'GÖVDE',
                            proses_adi: '-',
                            proses_kod: 0,
                            biten: 0,
                            baslayacak: parseInt(ge.yaz_say || 0),
                            devam: 0,
                            hedef_emir: parseInt(ge.yaz_say || 0),
                        });
                    } else {
                        for (var gpi = 0; gpi < gp.length; gpi++) {
                            var p2 = gp[gpi];
                            satirlar.push({
                                emir_no: ge.emir_no,
                                kategori: 'GÖVDE',
                                proses_adi: p2.proses_adi || p2.proses_kod,
                                proses_kod: parseInt(p2.proses_kod) || 0,
                                biten: parseInt(p2.yapilan || 0),
                                baslayacak: 0,
                                devam: 0,
                                hedef_emir: parseInt(ge.yaz_say || 0),
                            });
                        }
                    }
                }

                // ATKI alt emirler
                var atkiEmirler = (k.atki && k.atki.emirler) || [];
                for (var ai = 0; ai < atkiEmirler.length; ai++) {
                    var ae = atkiEmirler[ai];
                    var ap = ae.prosesler || [];
                    if (ap.length === 0) {
                        satirlar.push({
                            emir_no: ae.emir_no,
                            kategori: 'ATKI',
                            proses_adi: '-',
                            proses_kod: 0,
                            biten: 0,
                            baslayacak: parseInt(ae.yaz_say || 0),
                            devam: 0,
                            hedef_emir: parseInt(ae.yaz_say || 0),
                        });
                    } else {
                        for (var api = 0; api < ap.length; api++) {
                            var p3 = ap[api];
                            satirlar.push({
                                emir_no: ae.emir_no,
                                kategori: 'ATKI',
                                proses_adi: p3.proses_adi || p3.proses_kod,
                                proses_kod: parseInt(p3.proses_kod) || 0,
                                biten: parseInt(p3.yapilan || 0),
                                baslayacak: 0,
                                devam: 0,
                                hedef_emir: parseInt(ae.yaz_say || 0),
                            });
                        }
                    }
                }
            }
        }

        // Sirala: kategori (MAMUL once), sonra emir_no, sonra proses_kod
        satirlar.sort(function (a, b) {
            var katSira = {'MAMUL': 1, 'GÖVDE': 2, 'ATKI': 3};
            var ks = (katSira[a.kategori] || 9) - (katSira[b.kategori] || 9);
            if (ks !== 0) return ks;
            if (a.emir_no !== b.emir_no) return a.emir_no - b.emir_no;
            return a.proses_kod - b.proses_kod;
        });

        // Render satirlari
        var toplam_baslayacak = 0;
        var toplam_devam = 0;
        var toplam_biten = 0;
        var toplam_kalan = 0;

        for (var si = 0; si < satirlar.length; si++) {
            var s = satirlar[si];
            var kalan = Math.max(0, s.hedef_emir - s.biten);
            toplam_baslayacak += s.baslayacak;
            toplam_devam += s.devam;
            toplam_biten += s.biten;
            toplam_kalan += kalan;

            var katClass = 'kat-' + s.kategori.toLowerCase().replace(/[^a-z]/g, '');
            var bitenClass = s.biten > 0 ? 'biten-yesil' : '';
            var kalanClass = kalan > 0 ? 'kalan-kirmizi' : '';
            var baslayacakClass = s.baslayacak > 0 ? 'baslayacak-gri' : '';

            html += '<tr class="' + katClass + '">';
            html += '<td>' + _esc(s.emir_no) + '</td>';
            html += '<td><span class="planv2-kat-pill ' + katClass + '">' + _esc(s.kategori) + '</span></td>';
            html += '<td>' + _esc(s.proses_adi) + '</td>';
            html += '<td class="num ' + baslayacakClass + '">' + _fmt(s.baslayacak) + '</td>';
            html += '<td class="num">' + _fmt(s.devam) + '</td>';
            html += '<td class="num ' + bitenClass + '">' + _fmt(s.biten) + '</td>';
            html += '<td class="num ' + kalanClass + '">' + _fmt(kalan) + '</td>';
            html += '</tr>';
        }

        // TOPLAM satiri
        html += '<tr class="planv2-toplam">';
        html += '<td colspan="3"><strong>TOPLAM</strong></td>';
        html += '<td class="num"><strong>' + _fmt(toplam_baslayacak) + '</strong></td>';
        html += '<td class="num"><strong>' + _fmt(toplam_devam) + '</strong></td>';
        html += '<td class="num biten-yesil"><strong>' + _fmt(toplam_biten) + '</strong></td>';
        html += '<td class="num kalan-kirmizi"><strong>' + _fmt(toplam_kalan) + '</strong></td>';
        html += '</tr>';

        html += '</tbody></table>';

        // CPS - sadece kayit varsa kucuk dipnot
        var cpsg = d.cps_genel || {};
        var personel = cpsg.personel_uretim || [];
        if (personel.length > 0) {
            html += '<div class="planv2-cps-dipnot"><strong>CPS Personel:</strong> ';
            var ps = [];
            for (var pi2 = 0; pi2 < personel.length; pi2++) {
                ps.push(_esc(personel[pi2].personel_ad) + ' ' + _fmt(personel[pi2].toplam_miktar));
            }
            html += ps.join(' &middot; ');
            html += '</div>';
        }

        return html;
    }
    /* === /SADE KORGUN TABLO === */"""

    js_src = js_src[:bas_idx] + YENI_BLOK + js_src[son_idx:]

    # _planv2DetayHiyerarsik cagrisini _planv2SadeTablo ile degistir
    js_src = js_src.replace('_planv2DetayHiyerarsik(d)', '_planv2SadeTablo(d)')

    bak_js = JS_PATH + '.bak_pre_sade_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_src)
    print('OK-JS: sade tablo eklendi')


# === CSS - sade tablo stili ===
with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: sade tablo zaten uygulanmis')
else:
    CSS_ADD = '''

/* === SADE KORGUN TABLO === */
.planv2-ust-bilgi {
    padding: 12px 16px;
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
    font-size: 13px;
    color: #1f2937;
    margin-bottom: 12px;
    border-radius: 4px;
}

.planv2-sade-tablo {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    overflow: hidden;
}
.planv2-sade-tablo thead {
    background: #f3f4f6;
}
.planv2-sade-tablo th {
    text-align: left;
    padding: 8px 10px;
    font-size: 11px;
    font-weight: 700;
    color: #374151;
    letter-spacing: 0.5px;
    border-bottom: 1px solid #e5e7eb;
}
.planv2-sade-tablo th.num,
.planv2-sade-tablo td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.planv2-sade-tablo td {
    padding: 6px 10px;
    border-bottom: 1px solid #f3f4f6;
    color: #1f2937;
}
.planv2-sade-tablo tbody tr:hover {
    background: #fef3c7;
}

.planv2-kat-pill {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 8px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}
.planv2-kat-pill.kat-mamul { background: #fee2e2; color: #991b1b; }
.planv2-kat-pill.kat-govde { background: #dbeafe; color: #1e40af; }
.planv2-kat-pill.kat-atki { background: #f3e8ff; color: #6b21a8; }

.biten-yesil { color: #065f46; font-weight: 600; }
.kalan-kirmizi { color: #991b1b; font-weight: 600; }
.baslayacak-gri { color: #6b7280; }

.planv2-toplam {
    background: #f9fafb !important;
    border-top: 2px solid #d1d5db;
}
.planv2-toplam td {
    padding: 10px;
    font-size: 13px;
}

.planv2-cps-dipnot {
    margin-top: 12px;
    padding: 8px 10px;
    background: #faf5ff;
    border-left: 3px solid #a855f7;
    font-size: 11px;
    color: #6b21a8;
    border-radius: 4px;
}
'''

    bak_css = CSS_PATH + '.bak_pre_sade_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: sade stil eklendi')

print()
print('TAMAM: Sade Korgun tablo uygulandi')
print('Test: Ctrl+Shift+R, satira tikla')