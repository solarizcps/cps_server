/* =====================================================
   DARBOGAZ UYARI SISTEMI (06.05.2026)
   - Global uyari bandi (ust)
   - PLAN tablosuna darbogaz kolonu (F22'ye dokunmaz)
   - Hedef sayfasi planTable + planBody yapisina ozel
   ===================================================== */

(function () {
    'use strict';
    
    window._darbogazCache = window._darbogazCache || {};
    
    // =====================================================
    // 1. API'den darbogaz ozetini cek
    // =====================================================
    function darbogazVeriCek() {
        return fetch('/hedef/darbogaz-ozet')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var yeniCache = {};
                if (Array.isArray(data)) {
                    data.forEach(function (d) {
                        yeniCache[String(d.siparis_no)] = d;
                    });
                }
                window._darbogazCache = yeniCache;
                return data;
            })
            .catch(function () { return []; });
    }
    
    // =====================================================
    // 2. Global uyari bandini guncelle
    // =====================================================
    function bandGuncelle(data) {
        var band = document.getElementById('darbogaz-band');
        var mesaj = document.getElementById('dband-mesaj');
        if (!band || !mesaj) return;
        
        if (!Array.isArray(data) || data.length === 0) {
            band.classList.add('gizli');
            return;
        }
        
        var kritikler = data.filter(function (d) { return d.seviye === 'KRITIK'; });
        
        if (kritikler.length === 0) {
            band.classList.add('gizli');
            return;
        }
        
        var ozet;
        if (kritikler.length === 1) {
            var k = kritikler[0];
            ozet = '1 KRİTİK DARBOĞAZ — Sipariş ' + k.siparis_no +
                   ' • ' + (k.ana || '') + ' → Proses ' + (k.proses || '') +
                   ' (Sapma %' + k.yuzde + ')';
        } else {
            var kategoriler = {};
            kritikler.forEach(function (k) {
                var anahtar = (k.ana || '?') + '/' + (k.proses || '');
                kategoriler[anahtar] = (kategoriler[anahtar] || 0) + 1;
            });
            ozet = kritikler.length + ' KRİTİK DARBOĞAZ — ' + Object.keys(kategoriler).join(', ');
        }
        
        mesaj.textContent = ozet;
        band.classList.remove('gizli');
    }
    
    // =====================================================
    // 3. PLAN tablosuna darbogaz kolonu ekle
    // hedef.html'deki #planTable + #planBody yapisina ozel
    // =====================================================
    function planTablosunaKolonEkle() {
        var tablo = document.getElementById('planTable');
        if (!tablo) return;
        
        // Header'a "DARBOĞAZ" ekle (yoksa)
        var thead = tablo.querySelector('thead tr');
        if (thead && !thead.querySelector('.th-darbogaz')) {
            var th = document.createElement('th');
            th.className = 'th-darbogaz text';
            th.textContent = 'DARBOĞAZ';
            thead.appendChild(th);
        }
        
        var satirlar = tablo.querySelectorAll('tbody tr');
        if (satirlar.length === 0) return;
        
        // Her satira td ekle
        satirlar.forEach(function (tr) {
            // Loading/empty row'lari atla
            if (tr.classList.contains('h-row-loading') || tr.classList.contains('h-row-empty')) {
                return;
            }
            
            // Onceki TD'yi sil (refresh)
            var eskiTd = tr.querySelector('.td-darbogaz');
            if (eskiTd) eskiTd.remove();
            
            var sipNo = bulSiparisNo(tr);
            var td = document.createElement('td');
            td.className = 'td-darbogaz';
            
            if (sipNo && window._darbogazCache[sipNo]) {
                var d = window._darbogazCache[sipNo];
                if (d.seviye === 'KRITIK') {
                    td.innerHTML = '<span class="darbogaz-rozet kritik">🔴 ' +
                                   (d.ana || '') + ' → ' + (d.proses || '') +
                                   ' (%' + d.yuzde + ')</span>';
                } else {
                    td.innerHTML = '<span class="darbogaz-rozet normal">🟢 —</span>';
                }
            } else {
                td.innerHTML = '<span class="darbogaz-rozet bos">—</span>';
            }
            
            tr.appendChild(td);
        });
    }
    
    // Siparis no satirdan cikar (esnek arama)
    function bulSiparisNo(tr) {
        if (tr.dataset && tr.dataset.siparisNo) return String(tr.dataset.siparisNo);
        if (tr.dataset && tr.dataset.sipno) return String(tr.dataset.sipno);
        if (tr.dataset && tr.dataset.sipNo) return String(tr.dataset.sipNo);
        
        // hedef.html SİPARİŞ kolonu = 3. td (Görsel, Emir, SİPARİŞ, ...)
        var tdler = tr.querySelectorAll('td');
        // Index 2 = SİPARİŞ kolonu
        if (tdler.length >= 3) {
            var metin = (tdler[2].textContent || '').trim();
            if (/^\d{4,7}$/.test(metin)) return metin;
        }
        // Yedek: ilk 6 td icinde 4-7 haneli rakam
        for (var i = 0; i < Math.min(tdler.length, 6); i++) {
            var m = (tdler[i].textContent || '').trim();
            if (/^\d{4,7}$/.test(m)) return m;
        }
        return null;
    }
    
    // =====================================================
    // 4. Tam refresh
    // =====================================================
    function tamRefresh() {
        darbogazVeriCek().then(function (data) {
            bandGuncelle(data);
            // F22 + planlariYukle bitsin diye gecikmeli dene
            setTimeout(planTablosunaKolonEkle, 500);
            setTimeout(planTablosunaKolonEkle, 1500);
            setTimeout(planTablosunaKolonEkle, 3000);
        });
    }
    
    // =====================================================
    // 5. Tikla → PLAN tab'ina scroll
    // =====================================================
    window.darbogazBandTikla = function () {
        var planTab = document.querySelector('.h-tab[data-tab="plan"]');
        if (planTab) planTab.click();
        var tablo = document.getElementById('planTable');
        if (tablo) tablo.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    
    // =====================================================
    // 6. Baslat
    // =====================================================
    document.addEventListener('DOMContentLoaded', function () {
        tamRefresh();
        setInterval(tamRefresh, 30000);
    });
    
    // Periyodik kolon kontrol (F22 sonrasi tabloyu yeniden cizebilir)
    setInterval(planTablosunaKolonEkle, 5000);
    
})();