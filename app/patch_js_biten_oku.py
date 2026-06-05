"""PATCH: plan_v2.js'de p.yapilan -> p.biten (fallback yapilan).
Ayrica baslayacak ve devam alanlarini da JSON'dan oku.
Kalan mantigi: baslayacak + devam (henuz bitmemis).
"""
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\plan_v2.js'
MARKER = '/* BITEN BASLAYACAK FIX */'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: zaten uygulanmis')
    sys.exit(0)

# 1) MAMUL prosesleri okuma (line ~210)
OLD1 = """                    for (var pi = 0; pi < mamulProsesler.length; pi++) {
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
                    }"""

NEW1 = """                    for (var pi = 0; pi < mamulProsesler.length; pi++) {
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
                    }"""

if OLD1 not in src:
    print('HATA: MAMUL anchor bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD1, NEW1, 1)

# 2) _bucketEmirEkle - GOVDE/ATKI proses okuma
OLD2 = """            for (var pi = 0; pi < prosesler.length; pi++) {
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
            }"""

NEW2 = """            for (var pi = 0; pi < prosesler.length; pi++) {
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
            }"""

if OLD2 not in new_src:
    print('HATA: _bucketEmirEkle anchor bulunamadi')
    sys.exit(1)

new_src = new_src.replace(OLD2, NEW2, 1)

# 3) _bucketYeni'yi guncelle - toplam_devam alanı zaten var ama kontrol
# Mevcut: toplam_baslayacak, toplam_devam, toplam_biten, toplam_kalan, emir_sayisi var
# Sorun yok

# 4) Detay tablosunda emir kalanı duzelt: hedef - biten yerine baslayacak + devam
OLD3 = """            for (var ei2 = 0; ei2 < ps.emir_listesi.length; ei2++) {
                var em = ps.emir_listesi[ei2];
                var emKalan = Math.max(0, em.hedef - em.biten);"""

NEW3 = """            for (var ei2 = 0; ei2 < ps.emir_listesi.length; ei2++) {
                var em = ps.emir_listesi[ei2];
                /* BITEN BASLAYACAK FIX - kalan = baslayacak + devam */
                var emBaslayacak = parseInt(em.baslayacak || 0);
                var emDevam = parseInt(em.devam || 0);
                var emKalan = emBaslayacak + emDevam;"""

if OLD3 in new_src:
    new_src = new_src.replace(OLD3, NEW3, 1)
else:
    print('UYARI: detay kalan anchor bulunamadi (devam)')

# 5) Detay tablosu emir satiri - devam ve baslayacak ayri sutun
OLD4 = """                html += '<td>' + _esc(em.emir_no) + '</td>';
                html += '<td class="num ' + emBaslayacakClass + '">' + _fmt(em.baslayacak) + '</td>';
                html += '<td class="num">0</td>';
                html += '<td class="num ' + emBitenClass + '">' + _fmt(em.biten) + '</td>';
                html += '<td class="num ' + emKalanClass + '">' + _fmt(emKalan) + '</td>';"""

NEW4 = """                html += '<td>' + _esc(em.emir_no) + '</td>';
                html += '<td class="num ' + emBaslayacakClass + '">' + _fmt(emBaslayacak) + '</td>';
                html += '<td class="num">' + _fmt(emDevam) + '</td>';
                html += '<td class="num ' + emBitenClass + '">' + _fmt(em.biten) + '</td>';
                html += '<td class="num ' + emKalanClass + '">' + _fmt(emKalan) + '</td>';"""

if OLD4 in new_src:
    new_src = new_src.replace(OLD4, NEW4, 1)

# 6) Pivot ana satir - DEVAM kolonunu doldur
OLD5 = """            html += '<td class="num ' + baslayacakClass + '">' + _fmt(ps.toplam_baslayacak) + '</td>';
            html += '<td class="num">0</td>';
            html += '<td class="num ' + bitenClass + '">' + _fmt(ps.toplam_biten) + '</td>';"""

NEW5 = """            html += '<td class="num ' + baslayacakClass + '">' + _fmt(ps.toplam_baslayacak) + '</td>';
            html += '<td class="num">' + _fmt(ps.toplam_devam || 0) + '</td>';
            html += '<td class="num ' + bitenClass + '">' + _fmt(ps.toplam_biten) + '</td>';"""

if OLD5 in new_src:
    new_src = new_src.replace(OLD5, NEW5, 1)

# 7) GRAND TOPLAM satiri - DEVAM kolonu
OLD6 = """        html += '<td class="num"><strong>' + _fmt(grandBaslayacak) + '</strong></td>';
        html += '<td class="num"><strong>0</strong></td>';
        html += '<td class="num biten-yesil"><strong>' + _fmt(grandBiten) + '</strong></td>';"""

NEW6 = """        html += '<td class="num"><strong>' + _fmt(grandBaslayacak) + '</strong></td>';
        html += '<td class="num"><strong>' + _fmt(grandDevam || 0) + '</strong></td>';
        html += '<td class="num biten-yesil"><strong>' + _fmt(grandBiten) + '</strong></td>';"""

if OLD6 in new_src:
    new_src = new_src.replace(OLD6, NEW6, 1)

# 8) Grand toplam degiskenler - grandDevam ekle
OLD7 = """        var grandBaslayacak = 0;
        var grandDevam = 0;
        var grandBiten = 0;
        var grandKalan = 0;
        var grandEmir = 0;"""

# Bu zaten var, sorun yok. Ama emin olmak icin kontrol
if OLD7 not in new_src:
    # Belki tek satir
    OLD7b = "        var grandBaslayacak = 0;"
    if OLD7b in new_src and 'grandDevam' not in new_src:
        new_src = new_src.replace(OLD7b, "        var grandBaslayacak = 0;\n        var grandDevam = 0;", 1)

# 9) Grand toplam loop'unda devam topla
OLD8 = """            grandBaslayacak += ps.toplam_baslayacak;
            grandBiten += ps.toplam_biten;"""

NEW8 = """            grandBaslayacak += ps.toplam_baslayacak;
            grandDevam += (ps.toplam_devam || 0);
            grandBiten += ps.toplam_biten;"""

if OLD8 in new_src and 'grandDevam +=' not in new_src:
    new_src = new_src.replace(OLD8, NEW8, 1)

bak = JS_PATH + '.bak_pre_biten_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: biten/baslayacak/devam okuma duzeltildi (' + str(artis) + ' byte)')
print('  - p.biten oku (yapilan fallback)')
print('  - kalan = baslayacak + devam')
print('  - DEVAM kolonu dolu')