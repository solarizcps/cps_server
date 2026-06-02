"""ADIM U3: Frontend hiyerarsik render.

1. plan_v2.js: yeni endpoint /plan-detay-v2 + hiyerarsik detay + alt yorum satiri
2. plan_v2.css: MODEL/EMIR kart stilleri
"""
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\plan_v2.js'
CSS_PATH = r'C:\cps_dev\static\css\plan_v2.css'

JS_MARKER = '_planv2DetayHiyerarsik'
CSS_MARKER = '/* === U3 HIYERARSI === */'

# ============================================================
# 1) JS - eski _planv2DetayHtml ve _planv2BarRow yerine yeni hiyerarsik
# ============================================================
with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    js_src = f.read()

if JS_MARKER in js_src:
    print('SKIP-JS: U3 zaten uygulanmis')
else:
    # 1a) Endpoint URL degis: plan-detay -> plan-detay-v2
    OLD_URL = "fetch(API_BASE + '/plan-detay/' + encodeURIComponent(sipNo))"
    NEW_URL = "fetch(API_BASE + '/plan-detay-v2/' + encodeURIComponent(sipNo))"
    if OLD_URL in js_src:
        js_src = js_src.replace(OLD_URL, NEW_URL, 1)

    # 1b) _planv2DetayHtml fonksiyonunu komple degistir
    OLD_DETAY_FUNC_BAS = """    function _planv2DetayHtml(d) {
        var html = '';"""
    
    # Eski fonksiyonun bittigi yere kadar yedekle (basit bul-degistir)
    # Yerine yeni fonksiyon koy; eski yardimcilar (_planv2BarRow, _planv2EmirListesi) kalsin
    
    # Yeni yardimci ve ana fonksiyon - eski _planv2DetayHtml'i SARMALA
    NEW_FUNCS = """    /* === U3 HIYERARSI === */
    function _planv2DetayHiyerarsik(d) {
        var html = '';
        var darb = d.darbogaz || {};

        // 1) DURUM blogu (en uste)
        html += '<div class="planv2-blok durum">';
        html += '<div class="planv2-blok-baslik">' + chr_durum() + ' DURUM</div>';
        html += '<div class="planv2-blok-icerik">';
        html += '<div class="planv2-durum-grid">';
        html += '<div class="planv2-durum-row"><span class="planv2-durum-label">CIKTI</span>: ' +
                '<strong>' + _fmt(d.bitmis_mamul) + '</strong> cift</div>';
        html += '<div class="planv2-durum-row"><span class="planv2-durum-label">URETIM</span>: ' +
                '<strong>' + _esc(d.uretim_asamasi || 'henuz baslamadi') + '</strong> asamasinda</div>';
        html += '<div class="planv2-durum-row"><span class="planv2-durum-label">DARBOGAZ</span>: ' +
                '<strong>' + _esc(darb.kategori || '-') + '</strong>\\'da tikandi</div>';
        html += '</div>';
        if (d.summary) {
            html += '<div class="planv2-summary-text">' + _esc(d.summary) + '</div>';
        }
        // Toplam darbogaz ozeti
        html += '<div class="planv2-darbogaz-ozet">' +
                'Darbogaz: ' + _fmt(darb.yapilan || 0) + ' / ' + _fmt(d.hedef) +
                ' (%' + _fmt(darb.yuzde || 0) + ')</div>';
        html += '</div></div>';

        // 2) MODEL listesi (her model ayri kart)
        var modeller = d.modeller || [];
        if (modeller.length === 0) {
            html += '<div class="planv2-empty">Model bulunamadi.</div>';
        } else {
            for (var mi = 0; mi < modeller.length; mi++) {
                var m = modeller[mi];
                html += _planv2ModelKart(m, d.hedef);
            }
        }

        // 3) CPS GENEL (siparis bazinda - opsiyonel)
        if (d.cps_genel && (
            (d.cps_genel.sablon_prosesleri && d.cps_genel.sablon_prosesleri.length > 0) ||
            (d.cps_genel.personel_uretim && d.cps_genel.personel_uretim.length > 0)
        )) {
            html += _planv2CpsGenelBlok(d.cps_genel);
        }

        return html;
    }

    function chr_durum() { return '\\u{1F3AF}'; }

    function _planv2ModelKart(m, siparisHedef) {
        var html = '';
        var ko = m.kategori_ozet || {};
        var hedef_pay = m.hedef_pay || siparisHedef || 0;

        html += '<div class="planv2-model-kart">';
        html += '<div class="planv2-model-baslik">';
        html += '<span class="planv2-model-icon">\\u{1F4E6}</span> ';
        html += '<strong>MODEL:</strong> ' + _esc(m.model_kod) + ' \\u00b7 ';
        html += '<span class="planv2-model-hedef">Hedef ' + _fmt(hedef_pay) + ' cift</span>';
        if (m.model_adi && m.model_adi !== m.model_kod) {
            html += '<div class="planv2-model-adi">' + _esc(m.model_adi) + '</div>';
        }
        html += '</div>';

        // Model bar grafigi (kategori_ozet)
        html += '<div class="planv2-model-bar">';
        html += _planv2BarMini('ATKI', ko.atki_tamamlanan || 0, hedef_pay);
        html += _planv2BarMini('GOVDE', ko.govde_tamamlanan || 0, hedef_pay);
        html += _planv2BarMini('MAMUL', ko.mamul_tamamlanan || 0, hedef_pay);
        html += '</div>';

        // Mamul emirler
        var mamulEmirler = m.mamul_emirler || [];
        if (mamulEmirler.length === 0) {
            html += '<div class="planv2-emir-empty">Mamul emir yok.</div>';
        } else {
            html += '<div class="planv2-emir-listesi-baslik">' + mamulEmirler.length + ' Mamul Emir:</div>';
            for (var ei = 0; ei < mamulEmirler.length; ei++) {
                html += _planv2EmirKart(mamulEmirler[ei]);
            }
        }

        html += '</div>';  // model-kart
        return html;
    }

    function _planv2BarMini(label, deger, hedef) {
        var yuzde = hedef > 0 ? Math.min(100, Math.round((deger / hedef) * 100 * 10) / 10) : 0;
        var renk = 'yesil';
        if (yuzde === 0) renk = 'kirmizi';
        else if (yuzde < 50) renk = 'sari';
        return '<div class="planv2-bar-mini">' +
               '<span class="planv2-bar-mini-label">' + label + '</span>' +
               '<div class="planv2-bar-mini-track"><div class="planv2-bar-mini-fill ' + renk +
               '" style="width:' + yuzde + '%"></div></div>' +
               '<span class="planv2-bar-mini-deger">' + _fmt(deger) + '/' + _fmt(hedef) + '</span>' +
               '</div>';
    }

    function _planv2EmirKart(me) {
        var html = '';
        var korgun = me.korgun || {};
        var atki = korgun.atki || {tamamlanan: 0, emirler: []};
        var govde = korgun.govde || {tamamlanan: 0, emirler: []};
        var mamul = korgun.mamul || {son_yapilan: 0, prosesler: []};

        html += '<div class="planv2-emir-kart">';
        html += '<div class="planv2-emir-baslik">';
        html += '<strong>EMIR ' + _esc(me.emir_no) + '</strong>';
        html += ' \\u00b7 ' + _fmt(me.yaz_say) + ' cift';
        html += '</div>';

        // KORGUN REAL alt blok
        html += '<div class="planv2-emir-korgun">';
        html += '<div class="planv2-emir-alt-baslik">\\u{1F4CA} KORGUN REAL</div>';

        // ATKI
        html += '<div class="planv2-emir-row">';
        html += '<span class="planv2-emir-row-label">ATKI</span>';
        if (atki.emirler.length > 0) {
            var aEmirNos = atki.emirler.map(function(a) { return 'E.' + a.emir_no; }).join(', ');
            html += '<span class="planv2-emir-row-emir">[' + aEmirNos + ']</span>';
        }
        html += '<span class="planv2-emir-row-deger">';
        if (atki.son_proses) {
            html += atki.son_proses + ' ' + _fmt(atki.tamamlanan);
        } else {
            html += '<em>uretim yok</em>';
        }
        html += '</span></div>';

        // GOVDE
        html += '<div class="planv2-emir-row">';
        html += '<span class="planv2-emir-row-label">GOVDE</span>';
        if (govde.emirler.length > 0) {
            var gEmirNos = govde.emirler.map(function(g) { return 'E.' + g.emir_no; }).join(', ');
            html += '<span class="planv2-emir-row-emir">[' + gEmirNos + ']</span>';
        }
        html += '<span class="planv2-emir-row-deger">';
        if (govde.son_proses) {
            html += govde.son_proses + ' ' + _fmt(govde.tamamlanan);
        } else {
            html += '<em>uretim yok</em>';
        }
        html += '</span></div>';

        // MAMUL
        html += '<div class="planv2-emir-row">';
        html += '<span class="planv2-emir-row-label">MAMUL</span>';
        html += '<span class="planv2-emir-row-deger">';
        if (mamul.son_proses) {
            html += mamul.son_proses + ' ' + _fmt(mamul.son_yapilan);
        } else {
            html += '<em>uretim yok</em>';
        }
        html += '</span></div>';
        html += '</div>';  // korgun

        // CPS OPERASYON alt blok
        var cps = me.cps || {};
        var sablon = cps.sablon_prosesleri || [];
        var personel = cps.personel_uretim || [];
        if (sablon.length > 0 || personel.length > 0) {
            html += '<div class="planv2-emir-cps">';
            html += '<div class="planv2-emir-alt-baslik">\\u2699\\ufe0f CPS OPERASYON</div>';

            if (sablon.length > 0) {
                var sablonStr = sablon.map(function(s) {
                    return _esc(s.proses_adi) + ' ' + _fmt(s.yapilan);
                }).join(' \\u00b7 ');
                html += '<div class="planv2-emir-cps-row">Sablon: ' + sablonStr + '</div>';
            }
            if (personel.length > 0) {
                var personelStr = personel.map(function(p) {
                    return _esc(p.personel_ad) + ' (' + _fmt(p.toplam_miktar) + ')';
                }).join(' \\u00b7 ');
                html += '<div class="planv2-emir-cps-row">Personel: ' + personelStr + '</div>';
            }
            html += '</div>';
        }

        html += '</div>';  // emir-kart
        return html;
    }

    function _planv2CpsGenelBlok(cps) {
        var html = '';
        html += '<div class="planv2-blok cps">';
        html += '<div class="planv2-blok-baslik">\\u2699\\ufe0f CPS GENEL (Siparis Bazli)</div>';
        html += '<div class="planv2-blok-icerik">';
        var sablon = cps.sablon_prosesleri || [];
        if (sablon.length > 0) {
            html += '<strong>Sablon prosesleri:</strong><div class="planv2-cps-grid">';
            for (var i = 0; i < sablon.length; i++) {
                html += '<div class="planv2-cps-item"><div class="planv2-cps-item-adi">' +
                        _esc(sablon[i].proses_adi) + '</div><div class="planv2-cps-item-deger">' +
                        _fmt(sablon[i].yapilan) + '</div></div>';
            }
            html += '</div>';
        }
        var personel = cps.personel_uretim || [];
        if (personel.length > 0) {
            html += '<div style="margin-top:14px;"><strong>Personel uretimi:</strong></div>';
            for (var j = 0; j < personel.length; j++) {
                html += '<div style="font-size:12px;padding:4px 0;">' +
                        _esc(personel[j].personel_ad) + ': ' + _fmt(personel[j].toplam_miktar) +
                        ' (' + personel[j].kayit_sayisi + ' kayit)</div>';
            }
        }
        html += '</div></div>';
        return html;
    }
    /* === /U3 HIYERARSI === */

"""

    # _planv2DetayHtml cagrisi yerine _planv2DetayHiyerarsik kullan
    OLD_CALL = "icerik.innerHTML = _planv2DetayHtml(d);"
    NEW_CALL = "icerik.innerHTML = _planv2DetayHiyerarsik(d);"
    if OLD_CALL in js_src:
        js_src = js_src.replace(OLD_CALL, NEW_CALL, 1)
    else:
        print('UYARI: _planv2DetayHtml cagrisi bulunamadi (devam)')

    # Yeni fonksiyonlari _planv2DetayHtml fonksiyonunun ONCESINE ekle
    if OLD_DETAY_FUNC_BAS in js_src:
        js_src = js_src.replace(OLD_DETAY_FUNC_BAS, NEW_FUNCS + OLD_DETAY_FUNC_BAS, 1)
    else:
        print('HATA: _planv2DetayHtml anchor bulunamadi')
        sys.exit(1)

    # PLAN listesi - alt yorum satiri ekle
    OLD_SATIR = """        return '<tr onclick="planv2DetayAc(' + s.sip_no + ')" data-sip-no="' + s.sip_no + '">' +
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
            '</tr>';"""

    NEW_SATIR = """        var summaryHtml = '';
        if (s.summary) {
            summaryHtml = '<tr class="planv2-summary-row" onclick="planv2DetayAc(' + s.sip_no + ')">' +
                '<td colspan="10" class="planv2-summary-td">\\u21B3 ' + _esc(s.summary) + '</td>' +
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
            '</tr>' + summaryHtml;"""

    if OLD_SATIR in js_src:
        js_src = js_src.replace(OLD_SATIR, NEW_SATIR, 1)
    else:
        print('UYARI: PLAN satir anchor bulunamadi (devam)')

    bak_js = JS_PATH + '.bak_pre_u3_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(JS_PATH, bak_js)
    print('JS Yedek: ' + bak_js)

    with io.open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_src)
    print('OK-JS: U3 hiyerarsi + alt yorum satiri eklendi')


# ============================================================
# 2) CSS - U3 stilleri
# ============================================================
with io.open(CSS_PATH, 'r', encoding='utf-8') as f:
    css_src = f.read()

if CSS_MARKER in css_src:
    print('SKIP-CSS: U3 zaten uygulanmis')
else:
    CSS_ADD = '''

/* === U3 HIYERARSI === */
/* PLAN listesi alt yorum satiri */
.planv2-summary-row {
    cursor: pointer;
}
.planv2-summary-row .planv2-summary-td {
    padding: 4px 12px 10px 56px;
    color: #6b7280;
    font-size: 11px;
    font-style: italic;
    background: #fafafa;
    border-bottom: 1px solid #f3f4f6;
}

/* DURUM blogu - 3 net satir */
.planv2-durum-grid {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 10px;
}
.planv2-durum-row {
    font-size: 14px;
    color: #1f2937;
}
.planv2-durum-label {
    display: inline-block;
    width: 90px;
    font-weight: 700;
    color: #991b1b;
    letter-spacing: 0.3px;
}
.planv2-durum-row strong {
    color: #111827;
}
.planv2-summary-text {
    margin-top: 8px;
    padding: 8px 10px;
    background: #fef3c7;
    border-radius: 4px;
    font-size: 13px;
    color: #92400e;
    font-weight: 500;
}
.planv2-darbogaz-ozet {
    margin-top: 6px;
    font-size: 12px;
    color: #6b7280;
}

/* MODEL kart */
.planv2-model-kart {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    margin-bottom: 14px;
    overflow: hidden;
}
.planv2-model-baslik {
    padding: 10px 14px;
    background: #f0f9ff;
    border-bottom: 1px solid #e5e7eb;
    font-size: 13px;
    color: #1e40af;
}
.planv2-model-icon { font-size: 16px; }
.planv2-model-hedef {
    color: #6b7280;
    font-size: 12px;
}
.planv2-model-adi {
    font-size: 11px;
    color: #6b7280;
    margin-top: 2px;
}

/* Model bar (kompakt) */
.planv2-model-bar {
    padding: 10px 14px;
    background: #fafafa;
    border-bottom: 1px solid #f3f4f6;
}
.planv2-bar-mini {
    display: grid;
    grid-template-columns: 60px 1fr 100px;
    gap: 10px;
    align-items: center;
    margin-bottom: 4px;
    font-size: 11px;
}
.planv2-bar-mini-label {
    font-weight: 600;
    color: #1f2937;
}
.planv2-bar-mini-track {
    background: #f3f4f6;
    border-radius: 8px;
    height: 8px;
    overflow: hidden;
}
.planv2-bar-mini-fill {
    height: 100%;
    background: #10b981;
    border-radius: 8px;
}
.planv2-bar-mini-fill.kirmizi { background: #dc2626; }
.planv2-bar-mini-fill.sari { background: #f59e0b; }
.planv2-bar-mini-deger {
    text-align: right;
    color: #6b7280;
    font-size: 10px;
}

/* Emir listesi baslik */
.planv2-emir-listesi-baslik {
    padding: 8px 14px 4px;
    font-size: 11px;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.planv2-emir-empty {
    padding: 12px 14px;
    color: #9ca3af;
    font-style: italic;
    font-size: 12px;
}

/* EMIR kart */
.planv2-emir-kart {
    margin: 4px 14px 12px;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    overflow: hidden;
}
.planv2-emir-baslik {
    padding: 8px 12px;
    background: #f9fafb;
    font-size: 12px;
    color: #1f2937;
    border-bottom: 1px solid #f3f4f6;
}
.planv2-emir-korgun, .planv2-emir-cps {
    padding: 8px 12px;
    font-size: 11px;
}
.planv2-emir-korgun {
    background: #eff6ff;
    border-bottom: 1px solid #f3f4f6;
}
.planv2-emir-cps {
    background: #faf5ff;
}
.planv2-emir-alt-baslik {
    font-weight: 700;
    color: #374151;
    font-size: 10px;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    text-transform: uppercase;
}
.planv2-emir-row {
    display: grid;
    grid-template-columns: 60px 1fr auto;
    gap: 8px;
    padding: 2px 0;
    font-size: 11px;
}
.planv2-emir-row-label {
    font-weight: 600;
    color: #1f2937;
}
.planv2-emir-row-emir {
    color: #6b7280;
    font-size: 10px;
}
.planv2-emir-row-deger {
    text-align: right;
    color: #1f2937;
    font-weight: 500;
}
.planv2-emir-row-deger em {
    color: #9ca3af;
    font-style: italic;
    font-weight: normal;
}
.planv2-emir-cps-row {
    color: #6b21a8;
    padding: 2px 0;
}
/* === /U3 HIYERARSI === */
'''

    bak_css = CSS_PATH + '.bak_pre_u3_' + time.strftime('%Y%m%d_%H%M%S')
    shutil.copy2(CSS_PATH, bak_css)
    print('CSS Yedek: ' + bak_css)

    with io.open(CSS_PATH, 'w', encoding='utf-8') as f:
        f.write(css_src + CSS_ADD)
    print('OK-CSS: U3 stiller eklendi (' + str(len(CSS_ADD)) + ' byte)')

print()
print('TAMAM: U3 uygulandi')
print('Test: Ctrl+F5 -> http://localhost:5057/hedef/v2/')
print('  PLAN listesi alt yorum satirlari + detayda hiyerarsi')