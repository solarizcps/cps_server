/* enjeksiyon.js - PATCH C (F8 FIX FINAL)
   - SSR yapiyor: makine kart <a href>, form value Jinja'dan
   - F6.6 makineDegistir KALDIRILDI (artik <a href> tam reload)
   - F8_JS_STATE init/formDoldur/saatlikDoldur/istasyonDoldur KALDIRILDI
   - chr(34) bug otomatik silindi (istasyonDoldur silinince)
   - Auto-save KORUNDU - raporId DOM'dan okunuyor
   - F25.2 + F25.3 dokunulmadi
   - bfcache restore icin pageshow listener eklendi
*/

/* === BEGIN: ENJ_CPS_DEBUG === */
/* F9.1: Production console temizligi.
   cpsLog  -> sadece localStorage.cps_debug='1' iken cikar
   cpsWarn -> her zaman cikar (uyarilar onemli)
   cpsError-> her zaman cikar (hatalar kritik)
   Acmak:  localStorage.setItem('cps_debug','1')
   Kapatmak: localStorage.removeItem('cps_debug')
*/
(function () {
    'use strict';
    var DEBUG = (function () {
        try { return localStorage.getItem('cps_debug') === '1'; }
        catch (e) { return false; }
    })();
    window.CPS_DEBUG = DEBUG;
    window.cpsLog = function () {
        if (DEBUG && console && console.log) {
            console.log.apply(console, arguments);
        }
    };
    window.cpsWarn = function () {
        if (console && console.warn) {
            console.warn.apply(console, arguments);
        }
    };
    window.cpsError = function () {
        if (console && console.error) {
            console.error.apply(console, arguments);
        }
    };
})();
/* === END: ENJ_CPS_DEBUG === */


/* === BEGIN: ENJ_UI_DELEGATE === */
/* F9.1: Sorumluluk = optimistic UI feedback + toplu buton delegated handler.
   Backend authoritative state ENJ_F8_AUTOSAVE bloğunda yapılır.
   Bu blok sadece: click anında anlık görsel tepki + toplu butonu bridge. */
(function () {
    'use strict';

    // Optimistic UI helper — backend response beklemeden anlik visual feedback
    function abToggle(btn) {
        btn.classList.toggle('on');
        // F9_2_P3A_DURUM_SYNC
        try {
          var _aktif = btn.classList.contains('on');
          btn.classList.remove('durum-aktif', 'durum-kapali');
          btn.classList.add(_aktif ? 'durum-aktif' : 'durum-kapali');
          btn.dataset.durum = _aktif ? 'AKTIF' : 'KAPALI';
        } catch(e) {}
    }

    document.addEventListener('click', function (e) {
        // Slot click — anlik gorsel tepki (backend ENJ_F8_AUTOSAVE PATCH gonderir)
        var slot = e.target.closest('.enj-ist-cell .s');
        if (slot) {
          e.preventDefault();
          // F9_2_P3B_ROUTER
          if (window.EnjSlotPopup && window.EnjSlotPopup.handleSlotClick) {
            window.EnjSlotPopup.handleSlotClick(slot);
          } else {
            abToggle(slot);
          }
          return;
        }

        // Toplu buton bridge — F9.0.5 TOPLU bloguna delegate
        var toplu = e.target.closest('[data-toplu]');
        if (toplu) {
            e.preventDefault();
            var panel = toplu.closest('.enj-mak-panel');
            if (panel && window._enjTopluUygulaG) {
                window._enjTopluUygulaG(panel, toplu.dataset.toplu);
            }
        }
    });

    cpsLog('[CPS LOCAL] enjeksiyon.js Patch C yuklendi');
})();
/* === END: ENJ_UI_DELEGATE === */


/* === BEGIN: ENJ_F25_2_KALIP_SECICI === */
(function () {
    'use strict';
    var kayitlar = [], goruntulenenler = [], aktifIdx = -1;
    var input = document.getElementById('enj-kalip-input');
    var liste = document.getElementById('enj-kalip-liste');
    var hiddenId = document.getElementById('enj-kalip-id');
    if (!input || !liste || !hiddenId) return;

    fetch('/enjeksiyon/api/kalip-listesi')
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d && d.ok) { kayitlar = d.kayitlar || []; cpsLog('[CPS LOCAL] F25.2 kalip listesi: ' + kayitlar.length + ' kayit'); } })
        .catch(function () {});

    function escHTML(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

    input.addEventListener('input', function () {
        var q = (input.value || '').trim().toLocaleLowerCase('tr');
        if (q.length < 1) { liste.hidden = true; hiddenId.value = ''; return; }
        goruntulenenler = kayitlar.filter(function (k) {
            return (k.kalip_kod || '').toLocaleLowerCase('tr').indexOf(q) >= 0 ||
                   (k.model_kod || '').toLocaleLowerCase('tr').indexOf(q) >= 0 ||
                   (k.model_ad  || '').toLocaleLowerCase('tr').indexOf(q) >= 0 ||
                   (k.asorti    || '').toLocaleLowerCase('tr').indexOf(q) >= 0;
        }).slice(0, 30);
        if (goruntulenenler.length === 0) {
            liste.innerHTML = '<div class="enj-kalip-bos">Eslesme yok</div>';
        } else {
            var html = '';
            for (var i = 0; i < goruntulenenler.length; i++) {
                html += '<div class="enj-kalip-item" data-id="' + goruntulenenler[i].id + '">' + escHTML(goruntulenenler[i].display || '') + '</div>';
            }
            liste.innerHTML = html;
        }
        liste.hidden = false;
        aktifIdx = -1;
    });

    liste.addEventListener('click', function (e) {
        var item = e.target.closest('.enj-kalip-item');
        if (item && item.dataset.id) selectById(parseInt(item.dataset.id, 10));
    });

    input.addEventListener('keydown', function (e) {
        if (liste.hidden) return;
        if (e.key === 'ArrowDown') { aktifIdx = Math.min(aktifIdx + 1, goruntulenenler.length - 1); updateAktif(); e.preventDefault(); }
        else if (e.key === 'ArrowUp') { aktifIdx = Math.max(aktifIdx - 1, 0); updateAktif(); e.preventDefault(); }
        else if (e.key === 'Enter' && aktifIdx >= 0) { selectById(goruntulenenler[aktifIdx].id); e.preventDefault(); }
        else if (e.key === 'Escape') { liste.hidden = true; }
    });

    function updateAktif() {
        var items = liste.querySelectorAll('.enj-kalip-item');
        for (var i = 0; i < items.length; i++) {
            if (i === aktifIdx) { items[i].classList.add('aktif'); items[i].scrollIntoView({ block: 'nearest' }); }
            else items[i].classList.remove('aktif');
        }
    }

    document.addEventListener('click', function (e) { if (!e.target.closest('.enj-kalip-secici')) liste.hidden = true; });

    function selectById(id) {
        fetch('/enjeksiyon/api/kalip/' + id)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) return;
                var sec = d.secilen;
                var disp = sec.kalip_kod + ' / ' + (sec.model_ad || sec.model_kod) + (sec.asorti ? ' (' + sec.asorti + ')' : '');
                input.value = disp;
                hiddenId.value = sec.id;
                liste.hidden = true;
                formDoldur(d);
                urunPaneliGuncelle(d);
                document.dispatchEvent(new CustomEvent('enj-kalip-secildi', { detail: d }));
            })
            .catch(function () {});
    }

    function formDoldur(d) {
        var sec = d.secilen;
        var renkInp = document.getElementById('enj-renk');
        var kbcInp  = document.getElementById('enj-kalip-basi-cift');
        // PATCH F: bkInp (bagli_kalip) ARTIK SET EDILMEYECEK.
        // Bagli kalip backend authoritative + aktif slot sayisindan turetilir.
        // Kalip secimi bagli kalip alanini DEGISTIRMEZ.
        if (renkInp && !String(renkInp.value || '').trim()) {
            renkInp.value = sec.renk || '';
        }
        if (kbcInp) {
            // F_KBC_MASTER_DATA_BLOCK: master data sayfasi referans
            kbcInp.value = (sec.kalip_basi_cift != null) ? sec.kalip_basi_cift : '';
            kbcInp.readOnly = true;
            kbcInp.title = 'KBC degeri Kalip Yonetim sayfasindan duzeltilir';
            kbcInp.dataset.masterValue = (sec.kalip_basi_cift != null) ? String(sec.kalip_basi_cift) : '';
        }
    }

    function urunPaneliGuncelle(d) {
        var panel = document.querySelector('.enj-urun');
        if (!panel) return;
        panel.dataset.state = d.state || 'empty';

        var govdeBlok = panel.querySelector('[data-tip="govde"]');
        if (govdeBlok && d.govde) {
            var gkk = govdeBlok.querySelector('[data-field="kalip-kod"]');
            var gmk = govdeBlok.querySelector('[data-field="model-kod"]');
            var gimg = govdeBlok.querySelector('[data-field="gorsel"]');
            if (gkk) gkk.textContent = d.govde.kalip_kod || '';
            if (gmk) gmk.textContent = d.govde.model_ad || d.govde.model_kod || '';
            if (gimg) {
                if (d.govde.gorsel_dosya) {
                    gimg.src = '/static/img/kaliplar/' + d.govde.gorsel_dosya;
                    gimg.hidden = false;
                    gimg.onerror = function () { gimg.hidden = true; gimg.onerror = null; };
                } else { gimg.hidden = true; gimg.removeAttribute('src'); }
            }
        }

        var atkiBlok = panel.querySelector('[data-tip="atki"]');
        if (atkiBlok) {
            var akk = atkiBlok.querySelector('[data-field="kalip-kod"]');
            var amk = atkiBlok.querySelector('[data-field="model-kod"]');
            var aimg = atkiBlok.querySelector('[data-field="gorsel"]');
            if (d.atki) {
                if (akk) akk.textContent = d.atki.kalip_kod || '';
                if (amk) amk.textContent = d.atki.model_ad || d.atki.model_kod || '';
                if (aimg) {
                    if (d.atki.gorsel_dosya) {
                        aimg.src = '/static/img/kaliplar/' + d.atki.gorsel_dosya;
                        aimg.hidden = false;
                        aimg.onerror = function () { aimg.hidden = true; aimg.onerror = null; };
                    } else { aimg.hidden = true; aimg.removeAttribute('src'); }
                }
            } else {
                if (akk) akk.textContent = '';
                if (amk) amk.textContent = '';
                if (aimg) { aimg.hidden = true; aimg.removeAttribute('src'); }
            }
        }
    }

    cpsLog('[CPS LOCAL] F25.2 kalip secici yuklendi');
})();
/* === END: ENJ_F25_2_KALIP_SECICI === */


/* === BEGIN: ENJ_F25_3_SOFT_WARNING === */
(function () {
    'use strict';
    var kbc = document.getElementById('enj-kalip-basi-cift');
    if (!kbc) return;

    function kontrolEt() {
        var mv = kbc.dataset.masterValue;
        if (mv === undefined || mv === '' || mv === null) {
            kbc.classList.remove('enj-master-fark');
            return;
        }
        var current = (kbc.value || '').toString().trim();
        if (current === '' || current === mv) {
            kbc.classList.remove('enj-master-fark');
        } else {
            kbc.classList.add('enj-master-fark');
        }
    }

    kbc.addEventListener('input', kontrolEt);
    kbc.addEventListener('change', kontrolEt);

    var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
            if (muts[i].type === 'attributes' && muts[i].attributeName === 'data-master-value') {
                kbc.classList.remove('enj-master-fark');
            }
        }
    });
    mo.observe(kbc, { attributes: true });

    cpsLog('[CPS LOCAL] F25.3 soft warning yuklendi');
})();
/* === END: ENJ_F25_3_SOFT_WARNING === */


/* === BEGIN: ENJ_F8_AUTOSAVE === */
(function () {
    'use strict';

    // raporId DOM'dan oku (SSR'da .enj-wrap data-rapor-id'de bulunur)
    var wrap = document.querySelector('.enj-wrap');
    if (!wrap) {
        cpsWarn('[F8] .enj-wrap bulunamadi, auto-save pasif');
        return;
    }
    var raporId = parseInt(wrap.dataset.raporId || '', 10);
    if (!raporId || isNaN(raporId)) {
        cpsWarn('[F8] data-rapor-id bos veya gecersiz, auto-save pasif');
        return;
    }

    // === API helper ===
    function api(url, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        if (opts.body && typeof opts.body !== 'string') {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(opts.body);
        }
        opts.keepalive = true;
        return fetch(url, opts).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    // === Debounce ===
    var DEBOUNCE = 800;
    var timers = {};
    var pending = {};

    function setError(el, msg) {
        if (!el) return;
        el.classList.add('enj-save-err');
        el.title = msg || 'Kayit hatasi';
        setTimeout(function () {
            el.classList.remove('enj-save-err');
            el.removeAttribute('title');
        }, 3000);
    }

    function patch(url, body, target) {
        return api(url, { method: 'PATCH', body: body }).then(function (d) {
            if (!d || !d.ok) throw new Error((d && d.hata) || 'API hatasi');
        }).catch(function (err) {
            cpsError('[F8] PATCH:', url, err.message);
            setError(target, 'Kayit: ' + err.message);
        });
    }

    function schedule(key, fn) {
        if (timers[key]) clearTimeout(timers[key]);
        pending[key] = fn;
        timers[key] = setTimeout(function () {
            delete timers[key]; delete pending[key]; fn();
        }, DEBOUNCE);
    }

    function flushKey(key) {
        if (!timers[key]) return;
        clearTimeout(timers[key]);
        delete timers[key];
        var fn = pending[key]; delete pending[key];
        if (fn) fn();
    }

    function flushAll() {
        Object.keys(timers).forEach(flushKey);
    }

    function getNum(el) {
        var v = (el.value || '').trim();
        if (v === '') return null;
        var n = parseInt(v, 10);
        return isNaN(n) ? null : n;
    }

    function getTxt(el) {
        var v = (el.value || '').trim();
        return v === '' ? null : v;
    }

    function getFloat(el) {
        var v = (el.value || '').trim().replace(',', '.');
        if (v === '') return null;
        var n = parseFloat(v);
        return isNaN(n) ? null : n;
    }

    // === Form alanlari auto-save ===
    // PATCH D: enj-bagli-kalip artik readonly + backend authoritative, listeden cikti
    [
        ['enj-emir-no',         'emir_no',          'text'],
        ['enj-renk',            'renk',             'text'],
        ['enj-kalip-basi-cift', 'kalip_basi_cift',  'int'],
        ['enj-personel-sayisi', 'personel_sayisi',  'int'],
        // ENJ-FIRE: gun sonu fire breakdown kg
        ['enj-fire-bos',        'bos_atis_kg',      'float'],
        ['enj-fire-teknik',     'teknik_fire_kg',   'float'],
        ['enj-fire-yolluk',     'yolluk_fire_kg',   'float']
    ].forEach(function (spec) {
        var inp = document.getElementById(spec[0]);
        if (!inp) return;
        var key = 'f_' + spec[0];
        function save() {
            var v;
            if (spec[2] === 'int') v = getNum(inp);
            else if (spec[2] === 'float') v = getFloat(inp);
            else v = getTxt(inp);
            var body = {}; body[spec[1]] = v;
            patch('/enjeksiyon/api/rapor/' + raporId, body, inp);
        }
        inp.addEventListener('input', function () { schedule(key, save); });
        inp.addEventListener('blur', function () { flushKey(key); });
    });

    // === Saatlik tur ===
    document.querySelectorAll('tr[data-saatlik-id] .tur-inp').forEach(function (inp) {
        var tr = inp.closest('tr[data-saatlik-id]');
        var sid = tr && tr.dataset.saatlikId;
        if (!sid) return;
        var key = 's_tur_' + sid;
        function save() {
            var v = getNum(inp);
            if (v === null) v = 0;
            patch('/enjeksiyon/api/saatlik/' + sid, { tur_adet: v }, inp);
        }
        inp.addEventListener('input', function () { schedule(key, save); });
        inp.addEventListener('blur', function () { flushKey(key); });
    });

    // === Saatlik durum ===
    document.querySelectorAll('tr[data-saatlik-id] .durum-sel').forEach(function (sel) {
        var tr = sel.closest('tr[data-saatlik-id]');
        var sid = tr && tr.dataset.saatlikId;
        if (!sid) return;
        sel.addEventListener('change', function () {
            patch('/enjeksiyon/api/saatlik/' + sid, { durum: sel.value }, sel);
        });
    });

    // === Saatlik aksama ===
    document.querySelectorAll('tr[data-saatlik-id] .aks-sel').forEach(function (sel) {
        var tr = sel.closest('tr[data-saatlik-id]');
        var sid = tr && tr.dataset.saatlikId;
        if (!sid) return;
        sel.addEventListener('change', function () {
            var v = sel.value;
            patch('/enjeksiyon/api/saatlik/' + sid, {
                aksama_sebep_id: v === '' ? null : parseInt(v, 10)
            }, sel);
        });
    });

    // === A/B istasyon click - PATCH D: response.bagli_kalip_adet ile input guncelle ===
    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('button.s');
        if (!btn) return;
        var iid = btn.dataset.istasyonId;
        if (!iid) return;
        setTimeout(function () {
            var aktif = btn.classList.contains('on') ? 1 : 0;
            api('/enjeksiyon/api/istasyon/' + iid, {
                method: 'PATCH',
                body: { aktif: aktif }
            }).then(function (d) {
                if (!d || !d.ok) throw new Error((d && d.hata) || 'API hatasi');
                // Bagli kalip adetini guncelle (backend authoritative)
                if (typeof d.bagli_kalip_adet === 'number') {
                    var bk = document.getElementById('enj-bagli-kalip');
                    if (bk) bk.value = d.bagli_kalip_adet;
                    wrap.dataset.bagliKalip = String(d.bagli_kalip_adet);
                }
                document.dispatchEvent(new CustomEvent('enj-ab-ozet-refresh'));
            }).catch(function (err) {
                cpsError('[F8] istasyon PATCH:', err.message);
                setError(btn, 'Kayit: ' + err.message);
            });
        }, 0);
    }, false);

    // === Kalip secimi event (F25.2 dispatchEvent) - PATCH D: bagli_kalip_adet GONDERILMEZ ===
    document.addEventListener('enj-kalip-secildi', function (e) {
        var d = e.detail || {};
        var sec = d.secilen;
        if (!sec) return;
        var body = {
            kalip_id: sec.id,
            kalip_no: sec.kalip_kod || null,
            kalip_basi_cift: sec.kalip_basi_cift != null ? sec.kalip_basi_cift : null
        };
        if (sec.renk && String(sec.renk).trim()) {
            body.renk = String(sec.renk).trim();
        }
        var inp = document.getElementById('enj-kalip-input');
        patch('/enjeksiyon/api/rapor/' + raporId, body, inp);
    });

    // === Sayfa kapaniyor / makine kart click oncesi flush ===
    document.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('a.enj-mak-kart')) flushAll();
    }, true);
    window.addEventListener('beforeunload', flushAll);

    cpsLog('[CPS LOCAL] F8 auto-save aktif (rapor_id=' + raporId + ')');
})();
/* === END: ENJ_F8_AUTOSAVE === */


/* === BEGIN: ENJ_BFCACHE_FIX === */
(function () {
    'use strict';
    // Geri/Ileri tuslarinda veya bfcache restore'da sayfayi YENIDEN YUKLE
    // Bu Edge/Chrome'un form input cache'ini bypass eder
    window.addEventListener('pageshow', function (e) {
        if (e.persisted) {
            cpsLog('[CPS LOCAL] bfcache restore yakalandi, reload tetikleniyor');
            window.location.reload();
        }
    });
})();
/* === END: ENJ_BFCACHE_FIX === */


/* === BEGIN: ENJ_F9_0_5_TOPLU === */
(function () {
    'use strict';

    function getRaporId() {
        var wrap = document.querySelector('.enj-wrap');
        if (!wrap) return null;
        var v = parseInt(wrap.dataset.raporId || '', 10);
        return (isNaN(v) || !v) ? null : v;
    }

    function uiGuncelleSlotlar(aktifSlotlar) {
        // aktifSlotlar: ["1A", "1B", "2A", ...]
        // Aktif makinenin panelini bul, butun .s butonlarini gez
        var panel = document.querySelector('.enj-mak-panel.aktif');
        if (!panel) return;
        var aktifSet = {};
        for (var i = 0; i < aktifSlotlar.length; i++) {
            aktifSet[aktifSlotlar[i]] = true;
        }
        var cells = panel.querySelectorAll('.enj-ist-cell');
        cells.forEach(function (cell, idx) {
            var ist_no = idx + 1;
            var btns = cell.querySelectorAll('button.s');
            btns.forEach(function (btn) {
                var key = ist_no + btn.dataset.slot;
                if (aktifSet[key]) {
                    btn.classList.add('on');
                } else {
                    btn.classList.remove('on');
                }
            });
        });
    }

    function uiGuncelleBagli(bagli) {
        if (typeof bagli !== 'number') return;
        var bk = document.getElementById('enj-bagli-kalip');
        if (bk) bk.value = bagli;
    }

    window._enjTopluUygulaG = function (panel, action) {
        if (!panel || !action) return;
        if (!/^(a|b|x)$/i.test(action)) return;
        action = action.toLowerCase();

        // KAPAT icin onay
        if (action === 'x') {
            var onay = window.confirm('Bu makinedeki aktif slotlar kapatilacak. Emin misiniz?');
            if (!onay) return;
        }

        var raporId = getRaporId();
        if (!raporId) {
            alert('Rapor ID bulunamadi, sayfayi yenileyin');
            return;
        }

        var url = '/enjeksiyon/api/rapor/' + raporId + '/toplu-istasyon';
        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action }),
            keepalive: true
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (d) {
            if (!d || !d.ok) {
                cpsError('[F8] Toplu API hatasi:', d);
                alert('Toplu islem basarisiz: ' + ((d && d.hata) || 'bilinmeyen hata'));
                return;
            }
            // UI senkronizasyon
            if (d.aktif_slotlar) uiGuncelleSlotlar(d.aktif_slotlar);
            if (typeof d.bagli_kalip_adet === 'number') uiGuncelleBagli(d.bagli_kalip_adet);
            cpsLog('[CPS LOCAL] Toplu islem OK: ' + action + ' -> ' + d.aktif_slotlar.length + ' aktif slot');
        }).catch(function (err) {
            cpsError('[F8] Toplu islem hatasi:', err.message);
            alert('Toplu islem hatasi: ' + err.message);
        });
    };

    cpsLog('[CPS LOCAL] F9.0.5 toplu uygula yuklendi');
})();
/* === END: ENJ_F9_0_5_TOPLU === */

/* === BEGIN: F9_2_P3B_POPUP_CONTROLLER === */
/* F9.2 Patch 3.B - Slot Durum Yonetim Popup
   - Tek global instance (window.EnjSlotPopup)
   - 4 durum (AKTIF/KAPALI/SETUP/ARIZA) icin farkli icerik
   - AKTIF/KAPALI'da gercek aksiyon (Slotu Kapat / Aktif Yap)
   - SETUP/ARIZA butonlari placeholder (Patch 3.C)
   - 220ms debounce, ayni slot toggle, dis-tik kapanma
   - Scroll = repositionPopup, Resize = closePopup
*/
(function () {
    'use strict';
    
    var DEBOUNCE_MS = 220;
    
    var popup = null;
    var aktifSlot = null;
    var sonAcilis = 0;
    var _toastTimer = null;
    
    // Public API
    window.EnjSlotPopup = {
        handleSlotClick: handleSlotClick,
        close: closeSlotPopup
    };
    
    function init() {
        popup = document.getElementById('enj-slot-popup');
        if (!popup) {
            if (window.cpsLog) window.cpsLog('[F9.2 P3B] popup DOM yok');
            return;
        }
        
        // Popup ici butonlara delegation
        popup.addEventListener('click', function (e) {
            var btn = e.target.closest('.esp-btn');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            
            if (btn.classList.contains('placeholder')) {
                var tt = btn.getAttribute('data-tooltip') || 'Bu eylem yakinda aktiflesecek';
                showToast(tt);
                return;
            }
            
            var action = btn.getAttribute('data-action');
            executeAction(action);
        });
        
        // Dis-tik kapatma
        document.addEventListener('click', function (e) {
            if (!popup || popup.hidden) return;
            if (e.target.closest('#enj-slot-popup')) return;
            if (e.target.closest('.enj-ist-cell .s')) return; // slot click ayri ele alinir
            closeSlotPopup();
        }, true); // capture phase
        
        // ESC kapatma
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && popup && !popup.hidden) closeSlotPopup();
        });
        
        // SCROLL: pozisyon takip (kapatma DEGIL - Adem revize 2)
        var _scrollDebounce = null;
        window.addEventListener('scroll', function () {
            if (!popup || popup.hidden || !aktifSlot) return;
            clearTimeout(_scrollDebounce);
            _scrollDebounce = setTimeout(function () {
                if (aktifSlot && !popup.hidden) repositionPopup();
            }, 16);
        }, true);
        
        // RESIZE: kapat (layout shift sirasinda)
        window.addEventListener('resize', function () {
            if (popup && !popup.hidden) closeSlotPopup();
        });
        
        // visibilitychange (sekme degisti)
        document.addEventListener('visibilitychange', function () {
            if (document.hidden && popup && !popup.hidden) closeSlotPopup();
        });
        
        if (window.cpsLog) window.cpsLog('[F9.2 P3B] Popup controller hazir');
    }
    
    function handleSlotClick(slot) {
        if (!popup) return;
        
        // Ayni slot tikrar tiklandi -> kapan (toggle)
        if (aktifSlot === slot && !popup.hidden) {
            closeSlotPopup();
            return;
        }
        
        // Debounce gate (220ms)
        var simdi = Date.now();
        if (!popup.hidden && (simdi - sonAcilis < DEBOUNCE_MS)) {
            return;
        }
        
        // Eski popup acik mi? Anlik gec
        if (!popup.hidden) {
            // Kapatmadan dogrudan yeni icerik
            openSlotPopup(slot, true);
        } else {
            openSlotPopup(slot, false);
        }
    }
    
    function openSlotPopup(slot, isHotSwap) {
        var durum = slot.dataset.durum || 'KAPALI';
        var istNo = slot.dataset.istasyonNo || '?';
        var slotHarf = slot.dataset.slot || '?';
        var istId = slot.dataset.istasyonId || '';
        var kalipKod = slot.dataset.kalipKod || '';
        var setupYeni = slot.dataset.setupYeni || '';
        var arizaSebep = slot.dataset.arizaSebep || '';
        
        // Makine id panel'den
        var makineId = '?';
        var panel = slot.closest('.enj-mak-panel');
        if (panel) makineId = panel.getAttribute('data-makine-id') || '?';
        
        var data = {
            makineId: makineId,
            istNo: istNo,
            slot: slotHarf,
            istId: istId,
            kalipKod: kalipKod,
            setupYeni: setupYeni,
            arizaSebep: arizaSebep,
            durum: durum
        };
        
        renderPopup(durum, data);
        aktifSlot = slot;
        
        if (isHotSwap) {
            // Popup zaten acik, sadece pozisyon ve content guncelle
            requestAnimationFrame(function () {
                repositionPopup();
            });
        } else {
            // Yeni popup
            popup.hidden = false;
            popup.classList.remove('kapanan');
            // Pozisyon hesabi ICIN once gorunur olmali (offsetHeight icin)
            popup.style.left = '-9999px';
            popup.style.top = '-9999px';
            requestAnimationFrame(function () {
                repositionPopup();
                popup.classList.add('aktif');
            });
        }
        
        sonAcilis = Date.now();
    }
    
    function renderPopup(durum, data) {
        // Popup class
        popup.className = 'enj-slot-popup durum-' + durum.toLowerCase();
        
        // Baslik (MAK 2 • IST 3-A format)
        var baslikEl = popup.querySelector('.esp-mak-ist');
        baslikEl.textContent = 'MAK ' + data.makineId + ' • İST ' + data.istNo + '-' + data.slot;
        
        var altEl = popup.querySelector('.esp-alt');
        var detayEl = popup.querySelector('.esp-detay');
        var aksiyonEl = popup.querySelector('.esp-aksiyonlar');
        
        // 4 durum icin ayri render
        // F9_2_P3C_POPUP_BTN_AKTIF
        if (durum === 'AKTIF') {
            altEl.textContent = data.kalipKod || 'Aktif';
            detayEl.hidden = true;
            detayEl.innerHTML = '';
            aksiyonEl.innerHTML = 
                btnHTML('🔧', 'Setup Başlat', 'setup-baslat', '') +
                btnHTML('⚠', 'Arıza Bildir', 'ariza-baslat', '') +
                btnHTML('⛔', 'Slotu Kapat', 'durdur', '');
        } else if (durum === 'KAPALI') {
            altEl.textContent = 'Boş';
            detayEl.hidden = true;
            detayEl.innerHTML = '';
            aksiyonEl.innerHTML = 
                btnHTML('▶', 'Aktif Yap', 'baslat', '') +
                btnHTML('🔧', 'Setup Başlat', 'setup-baslat', '') +
                btnHTML('⚠', 'Arıza Bildir', 'ariza-baslat', '');
        } else if (durum === 'SETUP') {
            altEl.textContent = 'Setup sürmekte';
            detayEl.hidden = false;
            detayEl.innerHTML = 
                '<div class="esp-kalip-satir"><span>Eski:</span> <span class="esp-kalip-deger">' + (data.kalipKod || '—') + '</span></div>' +
                '<div class="esp-kalip-satir"><span>Yeni:</span> <span class="esp-kalip-deger">' + (data.setupYeni || '—') + '</span></div>';
            aksiyonEl.innerHTML = 
                btnHTML('✓', 'Setup Tamamla', 'setup-bitir-basari', '') +
                btnHTML('↩', 'İptal Et', 'setup-bitir-iptal', '') +
                btnHTML('⚠', 'Arıza Bildir', 'placeholder', 'Önce setup\'ı bitirin, sonra arıza bildirin');
        } else if (durum === 'ARIZA') {
            altEl.textContent = 'Arıza sürmekte';
            detayEl.hidden = false;
            var sebepTr = arizaSebepTurkce(data.arizaSebep);
            detayEl.innerHTML = '<div class="esp-ariza-sebep">⚠ ' + sebepTr + '</div>';
            aksiyonEl.innerHTML = 
                btnHTML('✓', 'Arızayı Kapat', 'ariza-bitir', '') +
                btnHTML('🔧', "Setup'a Al", 'placeholder', 'Önce arızayı kapatın, sonra setup başlatın');
        } else {
            // Bilinmeyen durum - defansif
            altEl.textContent = '—';
            detayEl.hidden = true;
            detayEl.innerHTML = '';
            aksiyonEl.innerHTML = '';
        }
    }
    
    function btnHTML(ikon, metin, action, tooltip) {
        var cls = 'esp-btn';
        if (action === 'placeholder') {
            cls += ' placeholder';
        } else {
            cls += ' esp-btn-' + action;
        }
        var tt = tooltip ? ' data-tooltip="' + escapeAttr(tooltip) + '"' : '';
        return '<button type="button" class="' + cls + '" data-action="' + action + '"' + tt + '>' +
               '<span class="esp-btn-ikon">' + ikon + '</span>' +
               '<span class="esp-btn-metin">' + metin + '</span>' +
               '</button>';
    }
    
    function escapeAttr(s) {
        return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }
    
    function arizaSebepTurkce(sebep) {
        var map = {
            'KALIP': 'Kalıp Arızası',
            'HIDROLIK': 'Hidrolik Arızası',
            'ELEKTRIK': 'Elektrik Arızası',
            'MALZEME': 'Malzeme Arızası',
            'OPERATOR': 'Operatör Hatası',
            'BILINMIYOR': 'Bilinmeyen Arıza'
        };
        return map[sebep] || sebep || 'Arıza';
    }
    
    function repositionPopup() {
        if (!aktifSlot || !popup || popup.hidden) return;
        
        var rect = aktifSlot.getBoundingClientRect();
        var popupW = popup.offsetWidth || 220;
        var popupH = popup.offsetHeight || 180;
        var margin = 8;
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        
        // Ilk tercih: sag
        var pozX = rect.right + margin;
        var pozY = rect.top;
        
        // Saga sigmiyor mu?
        if (pozX + popupW > vw - margin) {
            pozX = rect.left - popupW - margin;
        }
        // Sol da sigmiyor mu?
        if (pozX < margin) {
            pozX = Math.max(margin, (vw - popupW) / 2);
        }
        // Alta sigmiyor mu?
        if (pozY + popupH > vh - margin) {
            pozY = vh - popupH - margin;
        }
        if (pozY < margin) pozY = margin;
        
        popup.style.left = pozX + 'px';
        popup.style.top = pozY + 'px';
    }
    
    function executeAction(action) {
        if (!aktifSlot) return;
        var istId = aktifSlot.dataset.istasyonId;
        if (!istId) {
            showToast('İstasyon ID yok - sayfayı yenileyin');
            return;
        }
        
        // F9_2_P3C_POPUP_ROUTER
        if (action === 'durdur') {
            durumGec(istId, 'KAPALI');
        } else if (action === 'baslat') {
            durumGec(istId, 'AKTIF');
        } else if (action === 'setup-baslat') {
            if (window.EnjModal) window.EnjModal.open('setup-baslat', aktifSlot);
            else showToast('Modal henüz hazır değil');
        } else if (action === 'setup-bitir-basari') {
            if (window.EnjModal) window.EnjModal.open('setup-bitir', aktifSlot, {defaultSuccess: true});
            else showToast('Modal henüz hazır değil');
        } else if (action === 'setup-bitir-iptal') {
            if (window.EnjModal) window.EnjModal.open('setup-bitir', aktifSlot, {defaultSuccess: false});
            else showToast('Modal henüz hazır değil');
        } else if (action === 'ariza-baslat') {
            if (window.EnjModal) window.EnjModal.open('ariza-baslat', aktifSlot);
            else showToast('Modal henüz hazır değil');
        } else if (action === 'ariza-bitir') {
            if (window.EnjModal) window.EnjModal.open('ariza-bitir', aktifSlot);
            else showToast('Modal henüz hazır değil');
        }
    }
    
    function durumGec(istId, yeniDurum) {
        var slot = aktifSlot;
        closeSlotPopup();
        
        fetch('/enjeksiyon/api/istasyon/' + istId + '/durum', {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({durum: yeniDurum})
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, status: r.status, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                var hata = (res.data && res.data.hata) || ('HTTP ' + res.status);
                showToast('Hata: ' + hata);
                return;
            }
            // Slot DOM update
            if (slot) {
                var yeniAktif = (yeniDurum === 'AKTIF');
                if (yeniAktif) {
                    slot.classList.add('on');
                } else {
                    slot.classList.remove('on');
                }
                slot.classList.remove('durum-aktif', 'durum-kapali', 'durum-setup', 'durum-ariza');
                slot.classList.add('durum-' + yeniDurum.toLowerCase());
                slot.dataset.durum = yeniDurum;
            }
        })
        .catch(function (err) {
            showToast('Bağlantı hatası');
            if (window.cpsError) window.cpsError('[F9.2 P3B] fetch err', err);
        });
    }
    
    function closeSlotPopup() {
        if (!popup || popup.hidden) return;
        popup.classList.remove('aktif');
        popup.classList.add('kapanan');
        setTimeout(function () {
            popup.hidden = true;
            popup.classList.remove('kapanan');
            aktifSlot = null;
        }, 100);
    }
    
    function showToast(metin) {
        var toast = document.getElementById('esp-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'esp-toast';
            toast.className = 'esp-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = metin;
        // Force reflow
        void toast.offsetWidth;
        toast.classList.add('aktif');
        clearTimeout(_toastTimer);
        _toastTimer = setTimeout(function () {
            toast.classList.remove('aktif');
        }, 2500);
    }
    
    // F9_2_P3C_TOAST_GLOBAL - showToast'u modal IIFE'sine expose
    window._enjShowToast = showToast;
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
/* === END: F9_2_P3B_POPUP_CONTROLLER === */

/* ═══════════════════════════════════════════════════════════════════
   === BEGIN: F9_2_P3C_MODAL_CONTROLLER ===
   ═══════════════════════════════════════════════════════════════════
   F9.2 Patch 3.C - Modal Detay Yonetimi
   
   YAPI (Adem'in disiplin kurali uyarinca):
     EnjModalUI    - Render, DOM build, modal ac/kapat, gorsel guncelleme
     EnjModalState - State, validation, secili kalip/sebep, form kontrol
     EnjModalAPI   - Fetch, submit, backend response, hata yonetimi
   
   4 modal tip:
     setup-baslat  - sebep radio + kalip dropdown + 'sonra' checkbox + not
     setup-bitir   - 2 buyuk buton (EVET/HAYIR), durumsal metin, kalip ekrani
     ariza-baslat  - 6 chip buton (2x3) + detay text
     ariza-bitir   - 2 buyuk buton (URETIM/DURUR)
     kalip-degistir - ENJ_SETUP_V1 FAZ3A slot setup kalip degisimi
   
   Public API: window.EnjModal.open(tip, slot, options)
                window.EnjModal.close()
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    
    /* ════════════════════════════════════════════════════════════
       STATE BOLUMU - EnjModalState
       Form verileri, secili kalip/sebep, validation
       ════════════════════════════════════════════════════════════ */
    var state = {
        modalTip: null,         // 'setup-baslat' | 'setup-bitir' | 'ariza-baslat' | 'ariza-bitir' | 'kalip-degistir'
        slot: null,             // aktif slot DOM elementi (grid) veya null (A/B form)
        istId: null,            // istasyon id
        
        // ENJ_SETUP_V1 FAZ3A — slot kalip degistir
        slotLetter: null,
        setupId: null,
        raporId: null,
        pendingPayload: null,
        eskiKalipKod: null,
        yeniKalipKod: null,
        yeniKalipId: null,
        sebepKalipDegistir: 'SIPARIS_BITTI',
        kalipDegistirNot: '',
        eskiSetup: null,
        yeniDisplay: null,
        initialForm: null,
        setupMode: 'degistir',  // 'degistir' | 'ilk' | 'baslat' (FAZ-UI1)
        formKalipBasiCift: null,
        aktifGozSayisi: 0,
        sebepSetup: 'PLANLI_DEGISIM',
        kalipSonra: false,
        not: '',
        
        // Setup Bitir
        defaultSuccess: true,
        setupYeniKalipKod: null,
        setupYeniKalipId: null,  // varsa setup_kalip_id_yeni (slot data'sindan)
        modalKalipId: null,       // modal icinde secilen (varsa override)
        modalKalipKod: null,
        
        // Ariza Baslat
        sebepAriza: null,
        sebepDetay: '',
        
        // Ariza Bitir
        arizaSebepMevcut: null,
        arizaSure: null
    };
    
    function resetState() {
        state.modalTip = null;
        state.slot = null;
        state.istId = null;
        state.slotLetter = null;
        state.setupId = null;
        state.raporId = null;
        state.pendingPayload = null;
        state.eskiKalipKod = null;
        state.yeniKalipKod = null;
        state.yeniKalipId = null;
        state.sebepKalipDegistir = 'SIPARIS_BITTI';
        state.kalipDegistirNot = '';
        state.eskiSetup = null;
        state.yeniDisplay = null;
        state.initialForm = null;
        state.setupMode = 'degistir';
        state.formKalipBasiCift = null;
        state.aktifGozSayisi = 0;
        state.sebepSetup = 'PLANLI_DEGISIM';
        state.yeniKalipId = null;
        state.yeniKalipKod = null;
        state.kalipSonra = false;
        state.not = '';
        state.defaultSuccess = true;
        state.eskiKalipKod = null;
        state.setupYeniKalipKod = null;
        state.setupYeniKalipId = null;
        state.modalKalipId = null;
        state.modalKalipKod = null;
        state.sebepAriza = null;
        state.sebepDetay = '';
        state.arizaSebepMevcut = null;
        state.arizaSure = null;
    }
    
    /* Validation - Setup Baslat */
    function validateSetupBaslat() {
        if (!state.sebepSetup) return false;
        // Sebep secili + (kalip secili VEYA checkbox isaretli)
        if (state.kalipSonra) return true;
        if (state.yeniKalipId) return true;
        return false;
    }
    
    /* Validation - Setup Bitir EVET butonu */
    function validateSetupBitirBasari() {
        // success=true icin kalip lazim
        // Oncelik: modal'da secildi > slot'tan gelen setup_yeni > yok
        var kalipVar = state.modalKalipId || state.setupYeniKalipId;
        return !!kalipVar;
    }
    
    /* Validation - Ariza Baslat */
    function validateArizaBaslat() {
        return !!state.sebepAriza;
    }

    var KALIP_DEGISTIR_SEBEP_LABEL = {
        SIPARIS_BITTI: 'Sipariş bitti',
        HAMMADDE_BITTI: 'Hammadde bitti',
        KALIP_ARIZA: 'Kalıp arıza',
        RENK_DEGISIMI: 'Renk değişimi',
        YANLIS_SECIM: 'Yanlış seçim',
        DIGER: 'Diğer'
    };

    var ILK_SETUP_SEBEP_LABEL = {
        VARDIYA_BASLANGICI: 'Vardiya başlangıcı',
        YENI_URETIM: 'Yeni üretim',
        YANLIS_SECIM: 'Yanlış seçim düzeltme',
        DIGER: 'Diğer'
    };

    function isSetupBaslatMode() {
        return state.setupMode === 'ilk' || state.setupMode === 'baslat';
    }

    function setupFormVal(id) {
        var el = document.getElementById(id);
        if (!el) return '';
        return String(el.value || '').trim();
    }

    function setupFormInt(id) {
        var v = parseInt(setupFormVal(id), 10);
        return isNaN(v) ? null : v;
    }

    function clearSetupFieldErrors() {
        if (!bodyEl) return;
        bodyEl.querySelectorAll('.esu-fld-invalid').forEach(function (el) {
            el.classList.remove('esu-fld-invalid');
        });
    }

    function markSetupFieldInvalid(fieldRef) {
        var el = null;
        if (!fieldRef) return;
        if (fieldRef.charAt(0) === '.' || fieldRef.charAt(0) === '#') {
            el = bodyEl ? bodyEl.querySelector(fieldRef) : null;
        } else {
            el = document.getElementById(fieldRef);
        }
        if (el) el.classList.add('esu-fld-invalid');
    }

    function syncAktifGozFromGrid() {
        var sl = state.slotLetter;
        var cnt = window.enjCountAktifGozForSlot ? window.enjCountAktifGozForSlot(sl) : 0;
        state.aktifGozSayisi = cnt;
        var disp = document.getElementById('esu-goz-display');
        if (disp) disp.value = cnt > 0 ? String(cnt) : '0';
        return cnt;
    }

    function validateSetupForm(showErrors) {
        if (showErrors) clearSetupFieldErrors();
        var errors = [];

        if (!state.raporId || !state.slotLetter) {
            errors.push({ field: null, msg: 'Rapor veya slot bilgisi eksik' });
        }
        if (!state.yeniKalipId) {
            errors.push({ field: '.enj-modal-kalip-input', msg: 'Kalıp seçin' });
        }
        if (!setupFormVal('esu-renk')) {
            errors.push({ field: 'esu-renk', msg: 'Renk seçin' });
        }
        var pisme = setupFormInt('esu-pisme');
        if (pisme == null || isNaN(pisme) || pisme <= 0) {
            errors.push({ field: 'esu-pisme', msg: 'Pişme süresi zorunlu (pozitif sayı)' });
        }
        var pe = setupFormInt('esu-personel');
        if (pe == null || isNaN(pe) || pe <= 0) {
            errors.push({ field: 'esu-personel', msg: 'Personel sayısı zorunlu (pozitif sayı)' });
        }
        syncAktifGozFromGrid();
        var goz = state.aktifGozSayisi;
        if (goz == null || isNaN(goz) || goz <= 0) {
            errors.push({ field: 'esu-goz-display', msg: 'Aktif göz yok — üst gridde istasyon seçin' });
        }
        var kbc = setupFormInt('esu-kbc');
        if (kbc == null || isNaN(kbc) || kbc <= 0) {
            errors.push({ field: 'esu-kbc', msg: 'KBÇ / kalıp içi çift zorunlu (pozitif sayı)' });
        }
        if (!isSetupBaslatMode()) {
            if (!state.setupId) {
                errors.push({ field: null, msg: 'Aktif setup bulunamadı' });
            }
            if (!state.sebepKalipDegistir) {
                errors.push({ field: null, msg: 'Değişim sebebi seçin' });
            }
        }

        if (showErrors && errors.length) {
            errors.forEach(function (err) {
                if (err.field) markSetupFieldInvalid(err.field);
            });
            notify(errors[0].msg);
        }
        return errors.length === 0;
    }

    function collectSetupCreateBody() {
        syncAktifGozFromGrid();
        var sl = state.slotLetter;
        var sebepMap = isSetupBaslatMode() ? ILK_SETUP_SEBEP_LABEL : KALIP_DEGISTIR_SEBEP_LABEL;
        var sebepLabel = sebepMap[state.sebepKalipDegistir] || state.sebepKalipDegistir;
        var notParts = [];
        if (sebepLabel) notParts.push(sebepLabel);
        if (state.kalipDegistirNot) notParts.push(state.kalipDegistirNot);
        return {
            slot: sl,
            kalip_id: state.yeniKalipId,
            renk: setupFormVal('esu-renk'),
            pisme_suresi_sn: setupFormInt('esu-pisme'),
            personel_sayisi: setupFormInt('esu-personel'),
            aktif_goz_sayisi: state.aktifGozSayisi,
            kalip_basi_cift: setupFormInt('esu-kbc'),
            notlar: notParts.length ? notParts.join(' — ') : null
        };
    }

    function validateKalipDegistir() {
        return validateSetupForm();
    }
    /* ════════════════════════════════════════════════════════════
       UI BOLUMU - EnjModalUI
       Render, DOM build, modal ac/kapat, gorsel guncelleme
       ════════════════════════════════════════════════════════════ */
    var overlayEl, modalEl, bodyEl, footerEl, headerTipEl, headerMakIstEl;
    var miniKalipCache = null;  // F25.2 mini cache (kalip listesi)
    
    function isSetupUnifiedModal() {
        return state.modalTip === 'kalip-degistir';
    }

    function initUI() {
        overlayEl = document.getElementById('enj-modal-overlay');
        if (!overlayEl) return false;
        modalEl = document.getElementById('enj-modal');
        bodyEl = overlayEl.querySelector('.enj-modal-body');
        footerEl = overlayEl.querySelector('.enj-modal-footer');
        headerTipEl = overlayEl.querySelector('.emh-tip');
        headerMakIstEl = overlayEl.querySelector('.emh-makine-ist');
        
        // Close X — güvenli iptal (POST yok)
        var closeBtn = overlayEl.querySelector('.enj-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', closeModal);
        
        // Overlay dış-tık: setup modalında kapatma yok
        overlayEl.addEventListener('click', function (e) {
            if (e.target === overlayEl) {
                if (isSetupUnifiedModal()) return;
                closeModal();
            }
        });
        
        // ESC: setup modalında önce renk kartelasını kapat, modalı kapatma
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !overlayEl.hidden) {
                if (isSetupUnifiedModal()) {
                    e.stopPropagation();
                    e.preventDefault();
                    var renkFld = document.getElementById('esu-renk');
                    var openKrt = renkFld && renkFld.closest('.enj-fld') &&
                        renkFld.closest('.enj-fld').querySelector('.enj-ab-renk-v3-krt.open');
                    if (openKrt) {
                        openKrt.classList.remove('open');
                        return;
                    }
                    return;
                }
                e.stopPropagation();
                closeModal();
            }
        }, true);
        
        return true;
    }
    
    function openModal(tip, slot, options) {
        if (!overlayEl) {
            if (!initUI()) {
                if (window._enjShowToast) window._enjShowToast('Modal DOM yok');
                return;
            }
        }
        
        resetState();
        state.modalTip = tip;
        state.slot = slot;
        state.istId = slot ? slot.dataset.istasyonId : null;
        
        // Slot data'sini state'e kopyala
        if (slot) {
            state.eskiKalipKod = slot.dataset.kalipKod || '';
            state.setupYeniKalipKod = slot.dataset.setupYeni || '';
            // setup_yeni_kalip_id slot data'sinda yok, sadece kod var.
            // Setup bitir modal'da kalip_id setup_kalip_id_yeni'den okumak lazim.
            // Cozum: setupYeniKalipId modal acildiginda yeni endpoint ile cekilebilir,
            // ya da slot.dataset.setupYeniId ekle. Su an: setupYeniKalipKod kullaniyoruz,
            // submit aninda backend setup_kalip_id_yeni'yi otomatik kullanir (override yoksa).
            state.arizaSebepMevcut = slot.dataset.arizaSebep || '';
        }
        
        if (options) {
            if (options.defaultSuccess !== undefined) state.defaultSuccess = options.defaultSuccess;
            if (options.slotLetter) state.slotLetter = options.slotLetter;
            if (options.setupId) state.setupId = options.setupId;
            if (options.raporId) state.raporId = options.raporId;
            if (options.pendingPayload) state.pendingPayload = options.pendingPayload;
            if (options.eskiKalipKod !== undefined) state.eskiKalipKod = options.eskiKalipKod;
            if (options.yeniKalipKod) state.yeniKalipKod = options.yeniKalipKod;
            if (options.yeniKalipId) state.yeniKalipId = options.yeniKalipId;
            if (options.eskiSetup) state.eskiSetup = options.eskiSetup;
            if (options.yeniDisplay) state.yeniDisplay = options.yeniDisplay;
            if (options.initialForm) state.initialForm = options.initialForm;
            if (options.mode === 'ilk' || options.mode === 'baslat') {
                state.setupMode = 'baslat';
                state.sebepKalipDegistir = 'VARDIYA_BASLANGICI';
            } else {
                state.setupMode = 'degistir';
                state.sebepKalipDegistir = 'SIPARIS_BITTI';
            }
        }
        
        // Modal class + header
        modalEl.className = 'enj-modal tip-' + tip;
        
        if (tip === 'kalip-degistir') {
            headerMakIstEl.textContent = 'SLOT ' + (state.slotLetter || '?');
        } else {
            var makineId = slot && slot.closest('.enj-mak-panel');
            makineId = makineId ? (makineId.getAttribute('data-makine-id') || '?') : '?';
            var istNo = slot ? (slot.dataset.istasyonNo || '?') : '?';
            var slotHarf = slot ? (slot.dataset.slot || '?') : '?';
            headerMakIstEl.textContent = 'MAK ' + makineId + ' • İST ' + istNo + '-' + slotHarf;
        }
        
        // Render
        switch (tip) {
            case 'setup-baslat':
                headerTipEl.innerHTML = '🟠 SETUP BAŞLAT';
                renderSetupBaslat();
                break;
            case 'setup-bitir':
                headerTipEl.innerHTML = '🟠 SETUP BİTİR';
                renderSetupBitir();
                break;
            case 'ariza-baslat':
                headerTipEl.innerHTML = '🔴 ARIZA BİLDİR';
                renderArizaBaslat();
                break;
            case 'ariza-bitir':
                headerTipEl.innerHTML = '🔴 ARIZAYI KAPAT';
                renderArizaBitir();
                break;
            case 'kalip-degistir':
                headerTipEl.innerHTML = isSetupBaslatMode()
                    ? '🟢 Setup Başlat'
                    : '🔄 Setup Değiştir';
                renderKalipDegistir();
                break;
        }
        
        // Body scroll lock
        document.body.classList.add('modal-acik');
        
        // Goster
        overlayEl.hidden = false;
        overlayEl.classList.remove('kapanan');
        requestAnimationFrame(function () {
            overlayEl.classList.add('aktif');
        });
    }
    
    function closeModal() {
        if (!overlayEl || overlayEl.hidden) return;
        var rollbackOzet = state.modalTip === 'kalip-degistir';
        overlayEl.classList.remove('aktif');
        overlayEl.classList.add('kapanan');
        setTimeout(function () {
            overlayEl.hidden = true;
            overlayEl.classList.remove('kapanan');
            document.body.classList.remove('modal-acik');
            bodyEl.innerHTML = '';
            footerEl.innerHTML = '';
            resetState();
            if (rollbackOzet && window.enjLoadOzet) window.enjLoadOzet();
        }, 160);
    }
    
    /* Render: Setup Baslat */
    function renderSetupBaslat() {
        var eskiKalipDisplay = state.eskiKalipKod || '— (slot boş)';
        var eskiCls = state.eskiKalipKod ? '' : ' bos';
        
        bodyEl.innerHTML =
            '<div class="emb-bolum">' +
                '<label class="emb-label">Mevcut Kalıp</label>' +
                '<div class="emb-mevcut-kalip' + eskiCls + '">' + escapeHTML(eskiKalipDisplay) + '</div>' +
            '</div>' +
            
            '<div class="emb-bolum">' +
                '<label class="emb-label">Setup Sebebi<span class="gerekli">*</span></label>' +
                '<div class="emb-radio-grup">' +
                    radioHTML('PLANLI_DEGISIM', '📅', 'Planlı Değişim', true) +
                    radioHTML('ARIZA_SONRASI', '⚙', 'Arıza Sonrası', false) +
                    radioHTML('ACIL', '⚠', 'Acil', false) +
                '</div>' +
            '</div>' +
            
            '<div class="emb-bolum">' +
                '<label class="emb-label">Yeni Kalıp</label>' +
                kalipSeciciHTML() +
                '<label class="emb-checkbox-row">' +
                    '<input type="checkbox" id="esb-kalip-sonra">' +
                    '<span class="emb-checkbox-label">' +
                        '<span class="baslik">Kalıp sonra seçilecek</span>' +
                        '<span class="alt">Setup biterken belirlenecek</span>' +
                    '</span>' +
                '</label>' +
            '</div>' +
            
            '<div class="emb-bolum">' +
                '<label class="emb-label">Not (opsiyonel)</label>' +
                '<textarea class="emb-not-input" id="esb-not" placeholder="örn: kalıp temizlendi, ayar değiştirildi" maxlength="200"></textarea>' +
            '</div>';
        
        footerEl.innerHTML =
            '<button type="button" class="emf-btn iptal" data-act="iptal">İPTAL</button>' +
            '<button type="button" class="emf-btn submit" data-act="submit" disabled>SETUP BAŞLAT 🟠</button>';
        
        bindSetupBaslat();
    }
    
    /* Render: Setup Bitir */
    function renderSetupBitir() {
        var hasEski = !!state.eskiKalipKod;
        var hasYeni = !!state.setupYeniKalipKod;
        
        // 4 senaryo
        var eskiHTML, yeniHTML, kalipSeciciEk = '';
        
        eskiHTML = hasEski 
            ? '<span class="deger">' + escapeHTML(state.eskiKalipKod) + '</span>'
            : '<span class="deger bos">— (slot boştu)</span>';
        
        yeniHTML = hasYeni
            ? '<span class="deger">' + escapeHTML(state.setupYeniKalipKod) + '</span>'
            : '<span class="deger uyari">⚠ Henüz seçilmedi</span>';
        
        if (!hasYeni) {
            // Modal icinde kalip secimi gerekli
            kalipSeciciEk = 
                '<div class="emb-bolum" id="esb-modal-kalip-secim">' +
                    '<label class="emb-label">Kalıp Seç<span class="gerekli">*</span></label>' +
                    kalipSeciciHTML() +
                '</div>';
        }
        
        // Buton metinleri - durumsal
        var evetMetin, evetAlt, hayirMetin, hayirAlt;
        if (hasYeni) {
            evetMetin = 'EVET';
            evetAlt = escapeHTML(state.setupYeniKalipKod) + ' aktif olsun';
        } else {
            evetMetin = 'EVET';
            evetAlt = 'Önce kalıp seç';
        }
        if (hasEski) {
            hayirMetin = 'HAYIR';
            hayirAlt = escapeHTML(state.eskiKalipKod) + ' geri dönsün';
        } else {
            hayirMetin = 'HAYIR';
            hayirAlt = 'Slot KAPALI kalsın';
        }
        
        var evetDisabled = !hasYeni ? 'disabled' : '';
        
        bodyEl.innerHTML =
            '<div class="emb-bilgi-satir">' +
                '<div class="satir"><span class="etiket">Setup süresi:</span><span class="deger">hesaplanıyor</span></div>' +
            '</div>' +
            
            '<div class="emb-kalip-flow">' +
                '<div class="emb-kalip-row"><span class="etiket">Eski</span>' + eskiHTML + '</div>' +
                '<div class="emb-kalip-ok">↓</div>' +
                '<div class="emb-kalip-row"><span class="etiket">Yeni</span>' + yeniHTML + '</div>' +
            '</div>' +
            
            kalipSeciciEk +
            
            '<div class="emb-bolum">' +
                '<label class="emb-label">Setup BAŞARILI mı?</label>' +
                '<div class="emb-buyuk-secim">' +
                    '<button type="button" class="emb-buyuk-btn bb-basari" data-act="evet" ' + evetDisabled + '>' +
                        '<span class="bb-ikon">✓</span>' +
                        '<span class="bb-icerik">' +
                            '<span class="bb-baslik">' + evetMetin + '</span>' +
                            '<span class="bb-alt">' + evetAlt + '</span>' +
                        '</span>' +
                    '</button>' +
                    '<button type="button" class="emb-buyuk-btn bb-iptal" data-act="hayir">' +
                        '<span class="bb-ikon">✗</span>' +
                        '<span class="bb-icerik">' +
                            '<span class="bb-baslik">' + hayirMetin + '</span>' +
                            '<span class="bb-alt">' + hayirAlt + '</span>' +
                        '</span>' +
                    '</button>' +
                '</div>' +
            '</div>';
        
        footerEl.innerHTML =
            '<button type="button" class="emf-btn iptal" data-act="iptal">İPTAL</button>';
        
        // Setup yeni kalip slot data'sindan zaten var (kullanılacak)
        // Eger setupYeniKalipKod varsa, yeni kalip id'yi de "saklamak" lazim ama
        // slot data'sinda yok. Backend zaten setup_kalip_id_yeni'yi kullanir
        // (override yoksa). Bu yuzden modalKalipId opsiyonel.
        
        bindSetupBitir();
    }
    
    /* Render: Ariza Baslat */
    function renderArizaBaslat() {
        bodyEl.innerHTML =
            '<div class="emb-bolum">' +
                '<label class="emb-label">Arıza Sebebi<span class="gerekli">*</span></label>' +
                '<div class="emb-chip-grid">' +
                    chipHTML('KALIP', '🔧', 'KALIP') +
                    chipHTML('HIDROLIK', '💧', 'HİDROLİK') +
                    chipHTML('ELEKTRIK', '⚡', 'ELEKTRİK') +
                    chipHTML('MALZEME', '📦', 'MALZEME') +
                    chipHTML('OPERATOR', '👤', 'OPERATÖR') +
                    chipHTML('BILINMIYOR', '❓', 'BİLİNMİYOR') +
                '</div>' +
            '</div>' +
            
            '<div class="emb-bolum">' +
                '<label class="emb-label">Detay (opsiyonel)</label>' +
                '<textarea class="emb-not-input" id="eab-detay" placeholder="örn: ısıtıcı yanık, motor çıkardı" maxlength="200"></textarea>' +
            '</div>';
        
        footerEl.innerHTML =
            '<button type="button" class="emf-btn iptal" data-act="iptal">İPTAL</button>' +
            '<button type="button" class="emf-btn submit ariza" data-act="submit" disabled>🔴 ARIZAYI BİLDİR</button>';
        
        bindArizaBaslat();
    }
    
    /* Render: Ariza Bitir */
    function renderArizaBitir() {
        var sebepTr = arizaSebepTurkce(state.arizaSebepMevcut);
        
        bodyEl.innerHTML =
            '<div class="emb-bilgi-satir">' +
                '<div class="satir"><span class="etiket">Arıza süresi:</span><span class="deger">hesaplanıyor</span></div>' +
                '<div class="satir"><span class="etiket">Sebep:</span><span class="deger">⚠ ' + escapeHTML(sebepTr) + '</span></div>' +
            '</div>' +
            
            '<div class="emb-bolum">' +
                '<label class="emb-label">Slot artık ne yapsın?</label>' +
                '<div class="emb-buyuk-secim">' +
                    '<button type="button" class="emb-buyuk-btn bb-basari" data-act="uretim">' +
                        '<span class="bb-ikon">▶</span>' +
                        '<span class="bb-icerik">' +
                            '<span class="bb-baslik">ÜRETİME DEVAM ET</span>' +
                            '<span class="bb-alt">slot AKTİF olsun</span>' +
                        '</span>' +
                    '</button>' +
                    '<button type="button" class="emb-buyuk-btn bb-durur" data-act="durur">' +
                        '<span class="bb-ikon">⏸</span>' +
                        '<span class="bb-icerik">' +
                            '<span class="bb-baslik">DURUR KALSIN</span>' +
                            '<span class="bb-alt">slot KAPALI olsun</span>' +
                        '</span>' +
                    '</button>' +
                '</div>' +
            '</div>';
        
        footerEl.innerHTML =
            '<button type="button" class="emf-btn iptal" data-act="iptal">İPTAL</button>';
        
        bindArizaBitir();
    }

    /* Render: Unified Setup Modal (FAZ-UI1) */
    function setupReceteSnapshotHTML(baslik, data) {
        data = data || {};
        var pismeTxt = (data.pisme_suresi_sn != null && data.pisme_suresi_sn !== '')
            ? (escapeHTML(String(data.pisme_suresi_sn)) + ' sn') : '—';
        var kalipTxt = data.kalip_kod || data.kalip_kod_snapshot || '—';
        return '<div class="emb-kalip-degistir-blok">' +
            '<div class="emb-kalip-row"><span class="etiket">' + escapeHTML(baslik) + '</span>' +
            '<span class="deger">' + escapeHTML(kalipTxt) + '</span></div>' +
            '<div class="emb-kalip-row"><span class="etiket">Renk</span>' +
            '<span class="deger">' + escapeHTML(data.renk || '—') + '</span></div>' +
            '<div class="emb-kalip-row"><span class="etiket">Pişme</span>' +
            '<span class="deger">' + pismeTxt + '</span></div>' +
            '<div class="emb-kalip-row"><span class="etiket">Personel</span>' +
            '<span class="deger">' + escapeHTML(data.personel_sayisi != null ? String(data.personel_sayisi) : '—') + '</span></div>' +
            '<div class="emb-kalip-row"><span class="etiket">Aktif göz</span>' +
            '<span class="deger">' + escapeHTML(data.aktif_goz_sayisi != null ? String(data.aktif_goz_sayisi) : '—') + '</span></div>' +
            '<div class="emb-kalip-row"><span class="etiket">KBÇ</span>' +
            '<span class="deger">' + escapeHTML(data.kalip_basi_cift != null ? String(data.kalip_basi_cift) : '—') + '</span></div>' +
            '</div>';
    }

    function setupFormColHTML(label, id, type, value, step, opts) {
        opts = opts || {};
        var val = (value != null && value !== '') ? escapeHTML(String(value)) : '';
        var stepAttr = step ? (' step="' + step + '"') : '';
        var ro = opts.readonly ? ' readonly class="emb-not-input esu-readonly"' :
            ' class="emb-not-input esu-fld"';
        var idAttr = id ? (' id="' + id + '"') : '';
        return '<div class="emb-bolum">' +
            '<label class="emb-label">' + label + '<span class="gerekli">*</span></label>' +
            '<input type="' + type + '"' + idAttr + ro + ' value="' + val + '"' +
            stepAttr + ' autocomplete="off">' +
            (opts.hint ? ('<p class="esu-hint">' + opts.hint + '</p>') : '') +
            '</div>';
    }

    function renderKalipDegistir() {
        var isBaslat = isSetupBaslatMode();
        var eski = state.eskiSetup || {};
        var init = state.initialForm || {};
        var sl = String(state.slotLetter || '?');

        if (init.kalip_id) {
            state.yeniKalipId = init.kalip_id;
            state.yeniKalipKod = init.kalip_kod || '';
        }

        var gozCount = window.enjCountAktifGozForSlot ? window.enjCountAktifGozForSlot(sl) : 0;
        state.aktifGozSayisi = gozCount;

        // Gorsel kaynak (eski setup veya bos)
        var _rawGorsel = (state.eskiSetup && (state.eskiSetup.gorsel || state.eskiSetup.gorsel_dosya)) || null;
        var gorselSrc = _rawGorsel
            ? ((_rawGorsel.startsWith('/') || _rawGorsel.startsWith('http'))
                ? _rawGorsel
                : '/static/img/kaliplar/' + _rawGorsel)
            : null;

        // ---- SATIR 1: Gorsel (sol) + Mevcut Setup ozet (sag) ----
        var gorselKartHTML =
            '<div class="tsu-blok tsu-gorsel-blok">' +
                '<div class="tsu-blok-baslik">KALIP GÖRSELİ</div>' +
                '<div class="tsu-gorsel-cerceve" id="esu-kalip-gorsel-wrap">' +
                    (gorselSrc
                        ? '<img id="esu-kalip-gorsel-img" src="' + escapeHTML(gorselSrc) + '" alt="Kalıp görseli" ' +
                          'onerror="this.style.display=\'none\';var s=this.nextSibling;if(s)s.style.display=\'\';">' +
                          '<span class="tsu-gorsel-yok" style="display:none">Kalıp görseli yok</span>'
                        : '<span class="tsu-gorsel-yok">Kalıp görseli yok</span>') +
                '</div>' +
            '</div>';

        var pismeTxt = (eski.pisme_suresi_sn != null && eski.pisme_suresi_sn !== '')
            ? (escapeHTML(String(eski.pisme_suresi_sn)) + ' sn') : '—';
        var eskiKalipTxt = eski.kalip_kod_snapshot || eski.kalip_kod || '—';

        var mevSetupHTML = isBaslat
            ? '<div class="tsu-blok tsu-mev-blok tsu-baslat-bilgi">' +
                  '<div class="tsu-blok-baslik">BİLGİ</div>' +
                  '<p class="tsu-baslat-txt">Slot <strong>' + escapeHTML(sl) + '</strong> için yeni setup başlatılacak.<br>Tüm alanlar zorunludur.</p>' +
              '</div>'
            : '<div class="tsu-blok tsu-mev-blok">' +
                  '<div class="tsu-blok-baslik">MEVCUT SETUP</div>' +
                  '<div class="tsu-mev-liste">' +
                      tsuMevSatir('⚙', 'Kalıp',    eskiKalipTxt) +
                      tsuMevSatir('🎨', 'Renk',     eski.renk || '—') +
                      tsuMevSatir('⏱', 'Pişme',    pismeTxt) +
                      tsuMevSatir('👥', 'Personel', eski.personel_sayisi != null ? String(eski.personel_sayisi) : '—') +
                      tsuMevSatir('👁', 'Aktif göz', eski.aktif_goz_sayisi != null ? String(eski.aktif_goz_sayisi) : '—') +
                      tsuMevSatir('⚙', 'KBÇ',      eski.kalip_basi_cift != null ? String(eski.kalip_basi_cift) : '—') +
                  '</div>' +
              '</div>';

        var satir1HTML =
            '<div class="tsu-satir tsu-satir-1">' +
                gorselKartHTML +
                mevSetupHTML +
            '</div>';

        // ---- SATIR 2: Yeni setup formu (sol) + Uretim bilgileri (sag) ----
        var renkVal = (init.renk != null && init.renk !== '') ? escapeHTML(String(init.renk)) : '';

        var yeniSetupHTML =
            '<div class="tsu-blok tsu-form-blok">' +
                '<div class="tsu-blok-baslik">YENİ SETUP BİLGİLERİ</div>' +
                '<div class="tsu-form-alan">' +
                    '<label class="tsu-label">KALIP <span class="gerekli">*</span></label>' +
                    kalipSeciciHTML() +
                '</div>' +
                '<div class="tsu-form-alan">' +
                    '<label class="tsu-label">RENK <span class="gerekli">*</span></label>' +
                    '<div class="enj-fld esu-renk-fld">' +
                        '<input type="text" class="tsu-inp esu-fld" id="esu-renk" value="' +
                        renkVal + '" autocomplete="off" placeholder="Renk seçin…">' +
                    '</div>' +
                '</div>' +
                '<div class="tsu-form-alan">' +
                    '<label class="tsu-label">PİŞME SÜRESİ (SN) <span class="gerekli">*</span></label>' +
                    '<input type="number" id="esu-pisme" class="tsu-inp esu-fld" step="1" ' +
                    'value="' + ((init.pisme_suresi_sn != null && init.pisme_suresi_sn !== '') ? escapeHTML(String(init.pisme_suresi_sn)) : '') + '" autocomplete="off">' +
                '</div>' +
            '</div>';

        var gozVal = gozCount > 0 ? gozCount : '0';
        var peVal  = (init.personel_sayisi != null && init.personel_sayisi !== '') ? escapeHTML(String(init.personel_sayisi)) : '';
        var kbcVal = (init.kalip_basi_cift != null && init.kalip_basi_cift !== '') ? escapeHTML(String(init.kalip_basi_cift)) : '';

        var uretimHTML =
            '<div class="tsu-blok tsu-uretim-blok">' +
                '<div class="tsu-blok-baslik">ÜRETİM BİLGİLERİ</div>' +
                '<div class="tsu-uretim-grid">' +
                    '<div class="tsu-form-alan">' +
                        '<label class="tsu-label">PERSONEL SAYISI (SLOT ' + escapeHTML(sl) + ') <span class="gerekli">*</span></label>' +
                        '<div class="tsu-inp-ikonlu">' +
                            '<input type="number" id="esu-personel" class="tsu-inp esu-fld" step="1" value="' + peVal + '" autocomplete="off">' +
                            '<span class="tsu-inp-ikon">👥</span>' +
                        '</div>' +
                    '</div>' +
                    '<div class="tsu-form-alan">' +
                        '<label class="tsu-label">AKTİF GÖZ <span class="gerekli">*</span></label>' +
                        '<div class="tsu-inp-ikonlu">' +
                            '<input type="text" id="esu-goz-display" class="tsu-inp esu-readonly" readonly value="' + gozVal + '">' +
                            '<span class="tsu-inp-ikon">👁</span>' +
                        '</div>' +
                        '<p class="tsu-hint">Üst gridde Slot ' + escapeHTML(sl) + ' için seçili istasyon</p>' +
                    '</div>' +
                    '<div class="tsu-form-alan tsu-kbc-alan">' +
                        '<label class="tsu-label">KBÇ / KALIP İÇİ ÇİFT <span class="gerekli">*</span></label>' +
                        '<div class="tsu-inp-ikonlu">' +
                            '<input type="number" id="esu-kbc" class="tsu-inp esu-fld" step="1" value="' + kbcVal + '" autocomplete="off">' +
                            '<span class="tsu-inp-ikon">⚙</span>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        var satir2HTML =
            '<div class="tsu-satir tsu-satir-2">' +
                yeniSetupHTML +
                uretimHTML +
            '</div>';

        // ---- SATIR 3: Sebep (degistir modunda) + Not ----
        var sebepHTML = '';
        if (!isBaslat) {
            sebepHTML =
                '<div class="tsu-alt-blok">' +
                    '<label class="tsu-label">DEĞİŞİM SEBEBİ <span class="gerekli">*</span></label>' +
                    '<div class="tsu-sebep-grup">' +
                        tsuSebepBtnHTML('SIPARIS_BITTI', '✓', 'Sipariş bitti', true) +
                        tsuSebepBtnHTML('HAMMADDE_BITTI', '⏳', 'Hammadde bitti', false) +
                        tsuSebepBtnHTML('KALIP_ARIZA', '⚙', 'Kalıp arıza', false) +
                        tsuSebepBtnHTML('RENK_DEGISIMI', '🎨', 'Renk değişimi', false) +
                        tsuSebepBtnHTML('YANLIS_SECIM', '↩', 'Yanlış seçim', false) +
                        tsuSebepBtnHTML('DIGER', '…', 'Diğer', false) +
                    '</div>' +
                '</div>';
        }

        var notHTML =
            '<div class="tsu-alt-blok tsu-not-blok">' +
                '<label class="tsu-label">NOT (OPSİYONEL)</label>' +
                '<textarea class="tsu-textarea emb-not-input" id="ekd-not" ' +
                'placeholder="Ek açıklama (opsiyonel)" maxlength="200"></textarea>' +
            '</div>';

        var satir3HTML =
            '<div class="tsu-satir tsu-satir-3">' +
                sebepHTML +
                notHTML +
            '</div>';

        bodyEl.innerHTML = satir1HTML + satir2HTML + satir3HTML;

        footerEl.innerHTML =
            '<button type="button" class="emf-btn iptal" data-act="iptal">✕ İPTAL</button>' +
            '<button type="button" class="emf-btn submit tsu-submit-btn" data-act="submit" disabled>' +
            (isBaslat ? '✓ SETUP KAYDET' : '✓ SETUP DEĞİŞTİR') +
            '</button>';

        var kalipInp = bodyEl.querySelector('.enj-modal-kalip-input');
        if (kalipInp && init.kalip_kod) kalipInp.value = init.kalip_kod;

        bindKalipDegistir(isBaslat);
    }

    /** Mevcut setup ozet satiri */
    function tsuMevSatir(ikon, label, deger) {
        return '<div class="tsu-mev-satir">' +
            '<span class="tsu-mev-ikon">' + ikon + '</span>' +
            '<span class="tsu-mev-label">' + escapeHTML(label) + '</span>' +
            '<span class="tsu-mev-deger">' + escapeHTML(String(deger)) + '</span>' +
        '</div>';
    }

    /** Sebep kart butonu */
    function tsuSebepBtnHTML(id, ikon, metin, secili) {
        return '<button type="button" class="tsu-sebep-btn' + (secili ? ' secili' : '') + '" ' +
            'data-sebep="' + id + '">' +
            '<span class="tsu-sebep-ikon">' + ikon + '</span>' +
            '<span>' + escapeHTML(metin) + '</span>' +
        '</button>';
    }
    
    /* HTML Helpers */
    function radioHTML(id, ikon, metin, secili) {
        var cls = secili ? 'emb-radio secili' : 'emb-radio';
        var ch = secili ? 'checked' : '';
        return '<label class="' + cls + '" data-sebep="' + id + '">' +
            '<input type="radio" name="esb-sebep" value="' + id + '" ' + ch + '>' +
            '<span class="emb-radio-ikon">' + ikon + '</span>' +
            '<span class="emb-radio-metin">' + escapeHTML(metin) + '</span>' +
            '</label>';
    }

    function kalipDegistirRadioHTML(id, ikon, metin, secili) {
        var cls = secili ? 'emb-radio secili' : 'emb-radio';
        var ch = secili ? 'checked' : '';
        return '<label class="' + cls + '" data-sebep="' + id + '">' +
            '<input type="radio" name="ekd-sebep" value="' + id + '" ' + ch + '>' +
            '<span class="emb-radio-ikon">' + ikon + '</span>' +
            '<span class="emb-radio-metin">' + escapeHTML(metin) + '</span>' +
            '</label>';
    }
    
    function chipHTML(id, ikon, metin) {
        return '<button type="button" class="emb-chip" data-sebep="' + id + '">' +
            '<span class="emb-chip-ikon">' + ikon + '</span>' +
            '<span class="emb-chip-metin">' + escapeHTML(metin) + '</span>' +
            '</button>';
    }
    
    function kalipSeciciHTML() {
        return '<div class="enj-modal-kalip-secici">' +
            '<input type="text" class="enj-modal-kalip-input" placeholder="Ara: kod, model..." autocomplete="off">' +
            '<div class="enj-modal-kalip-liste" hidden></div>' +
            '</div>';
    }
    
    /* Event Binding - Setup Baslat */
    function bindSetupBaslat() {
        // Radio butonlar
        bodyEl.querySelectorAll('.emb-radio').forEach(function (r) {
            r.addEventListener('click', function () {
                bodyEl.querySelectorAll('.emb-radio').forEach(function (x) {
                    x.classList.remove('secili');
                });
                r.classList.add('secili');
                r.querySelector('input[type="radio"]').checked = true;
                state.sebepSetup = r.getAttribute('data-sebep');
                refreshSetupBaslatSubmit();
            });
        });
        
        // Kalip dropdown
        var kalipKontEl = bodyEl.querySelector('.enj-modal-kalip-secici');
        if (kalipKontEl) {
            initMiniKalipDropdown(kalipKontEl, function (id, kod) {
                state.yeniKalipId = id;
                state.yeniKalipKod = kod;
                refreshSetupBaslatSubmit();
            });
        }
        
        // Checkbox "Kalip sonra"
        var cb = document.getElementById('esb-kalip-sonra');
        if (cb) {
            cb.addEventListener('change', function () {
                state.kalipSonra = cb.checked;
                var kalipInp = bodyEl.querySelector('.enj-modal-kalip-input');
                if (kalipInp) {
                    kalipInp.disabled = cb.checked;
                    if (cb.checked) {
                        kalipInp.value = '';
                        state.yeniKalipId = null;
                        state.yeniKalipKod = null;
                        var liste = bodyEl.querySelector('.enj-modal-kalip-liste');
                        if (liste) liste.hidden = true;
                    }
                }
                refreshSetupBaslatSubmit();
            });
        }
        
        // Not
        var notEl = document.getElementById('esb-not');
        if (notEl) {
            notEl.addEventListener('input', function () {
                state.not = notEl.value || '';
            });
        }
        
        // Footer
        footerEl.querySelector('[data-act="iptal"]').addEventListener('click', closeModal);
        footerEl.querySelector('[data-act="submit"]').addEventListener('click', submitSetupBaslat);
    }
    
    function refreshSetupBaslatSubmit() {
        var btn = footerEl.querySelector('[data-act="submit"]');
        if (!btn) return;
        btn.disabled = !validateSetupBaslat();
    }

    function refreshSetupSubmitBtn() {
        var btn = footerEl && footerEl.querySelector('[data-act="submit"]');
        if (!btn) return;
        syncAktifGozFromGrid();
        btn.disabled = !validateSetupForm(false);
    }

    function applyKalipMasterToForm(kalipId) {
        fetchKalipListesi(function (list) {
            var k = null;
            for (var i = 0; i < list.length; i++) {
                if (String(list[i].id) === String(kalipId)) {
                    k = list[i];
                    break;
                }
            }
            if (!k) {
                refreshSetupSubmitBtn();
                return;
            }
            var renkEl = document.getElementById('esu-renk');
            var pismeEl = document.getElementById('esu-pisme');
            var kbcEl = document.getElementById('esu-kbc');
            if (renkEl && !String(renkEl.value || '').trim() && k.renk) {
                renkEl.value = k.renk;
            }
            if (pismeEl && !String(pismeEl.value || '').trim() && k.pisme_suresi_sn != null) {
                pismeEl.value = String(k.pisme_suresi_sn);
            }
            if (kbcEl && !String(kbcEl.value || '').trim() && k.kalip_basi_cift != null) {
                kbcEl.value = String(k.kalip_basi_cift);
            }
            state.formKalipBasiCift = k.kalip_basi_cift;

            // Kalip gorsel preview guncelle (yeni tsu tasarimi)
            var wrap = document.getElementById('esu-kalip-gorsel-wrap');
            if (wrap) {
                var gorselUrl = k.gorsel || k.image_url || null;
                if (!gorselUrl && k.gorsel_dosya) {
                    var gd = String(k.gorsel_dosya);
                    gorselUrl = (gd.startsWith('/') || gd.startsWith('http'))
                        ? gd
                        : '/static/img/kaliplar/' + gd;
                }
                if (gorselUrl) {
                    wrap.innerHTML =
                        '<img id="esu-kalip-gorsel-img" src="' + escapeHTML(gorselUrl) + '" alt="Kalıp görseli" ' +
                        'onerror="this.style.display=\'none\';this.nextSibling.style.display=\'\'">' +
                        '<span class="tsu-gorsel-yok" style="display:none">Kalıp görseli yok</span>';
                } else {
                    wrap.innerHTML = '<span class="tsu-gorsel-yok">Kalıp görseli yok</span>';
                }
            }

            refreshSetupSubmitBtn();
        });
    }

    function bindKalipDegistir(isBaslat) {
        if (!isBaslat) {
            state.sebepKalipDegistir = 'SIPARIS_BITTI';
        } else {
            state.sebepKalipDegistir = 'VARDIYA_BASLANGICI';
        }

        // Yeni tablet kart sebep butonlari
        bodyEl.querySelectorAll('.tsu-sebep-btn').forEach(function (r) {
            r.addEventListener('click', function () {
                bodyEl.querySelectorAll('.tsu-sebep-btn').forEach(function (x) {
                    x.classList.remove('secili');
                });
                r.classList.add('secili');
                state.sebepKalipDegistir = r.getAttribute('data-sebep');
                refreshSetupSubmitBtn();
            });
        });

        // Geriye donuk uyum: eski .emb-radio varsa onlara da baglan
        bodyEl.querySelectorAll('.emb-radio').forEach(function (r) {
            r.addEventListener('click', function () {
                bodyEl.querySelectorAll('.emb-radio').forEach(function (x) {
                    x.classList.remove('secili');
                });
                r.classList.add('secili');
                var radioInp = r.querySelector('input[type="radio"]');
                if (radioInp) radioInp.checked = true;
                state.sebepKalipDegistir = r.getAttribute('data-sebep');
                refreshSetupSubmitBtn();
            });
        });

        var notEl = document.getElementById('ekd-not');
        if (notEl) {
            notEl.addEventListener('input', function () {
                state.kalipDegistirNot = notEl.value || '';
            });
        }

        bodyEl.querySelectorAll('.esu-fld').forEach(function (inp) {
            inp.addEventListener('input', function () {
                inp.classList.remove('esu-fld-invalid');
                refreshSetupSubmitBtn();
            });
        });

        var renkInp = document.getElementById('esu-renk');
        if (renkInp && window.enjRenkKartelaBuild) {
            window.enjRenkKartelaBuild(renkInp);
        }

        var kalipKontEl = bodyEl.querySelector('.enj-modal-kalip-secici');
        if (kalipKontEl) {
            initMiniKalipDropdown(kalipKontEl, function (id, kod) {
                state.yeniKalipId = id;
                state.yeniKalipKod = kod;
                var kalipInpEl = bodyEl.querySelector('.enj-modal-kalip-input');
                if (kalipInpEl) kalipInpEl.classList.remove('esu-fld-invalid');
                applyKalipMasterToForm(id);
            });
        }

        footerEl.querySelector('[data-act="iptal"]').addEventListener('click', closeModal);
        footerEl.querySelector('[data-act="submit"]').addEventListener('click', submitKalipDegistir);
        refreshSetupSubmitBtn();
    }
    
    /* Event Binding - Setup Bitir */
    function bindSetupBitir() {
        // Buyuk butonlar
        bodyEl.querySelectorAll('.emb-buyuk-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                if (b.disabled) return;
                var act = b.getAttribute('data-act');
                if (act === 'evet') {
                    submitSetupBitir(true);
                } else if (act === 'hayir') {
                    submitSetupBitir(false);
                }
            });
        });
        
        // Modal icinde kalip secimi varsa (setupYeniKalipKod yoksa)
        var kalipKontEl = bodyEl.querySelector('.enj-modal-kalip-secici');
        if (kalipKontEl) {
            initMiniKalipDropdown(kalipKontEl, function (id, kod) {
                state.modalKalipId = id;
                state.modalKalipKod = kod;
                refreshSetupBitirEvet();
            });
        }
        
        // Footer
        footerEl.querySelector('[data-act="iptal"]').addEventListener('click', closeModal);
    }
    
    function refreshSetupBitirEvet() {
        var evetBtn = bodyEl.querySelector('[data-act="evet"]');
        if (!evetBtn) return;
        var ok = validateSetupBitirBasari();
        evetBtn.disabled = !ok;
        // Buton metnini guncelle (kalip secildikten sonra)
        if (ok && state.modalKalipKod) {
            var altEl = evetBtn.querySelector('.bb-alt');
            if (altEl) altEl.textContent = state.modalKalipKod + ' aktif olsun';
        }
    }
    
    /* Event Binding - Ariza Baslat */
    function bindArizaBaslat() {
        // Chip butonlar
        bodyEl.querySelectorAll('.emb-chip').forEach(function (c) {
            c.addEventListener('click', function () {
                bodyEl.querySelectorAll('.emb-chip').forEach(function (x) {
                    x.classList.remove('secili');
                });
                c.classList.add('secili');
                state.sebepAriza = c.getAttribute('data-sebep');
                refreshArizaBaslatSubmit();
            });
        });
        
        // Detay
        var detayEl = document.getElementById('eab-detay');
        if (detayEl) {
            detayEl.addEventListener('input', function () {
                state.sebepDetay = detayEl.value || '';
            });
        }
        
        // Footer
        footerEl.querySelector('[data-act="iptal"]').addEventListener('click', closeModal);
        footerEl.querySelector('[data-act="submit"]').addEventListener('click', submitArizaBaslat);
    }
    
    function refreshArizaBaslatSubmit() {
        var btn = footerEl.querySelector('[data-act="submit"]');
        if (!btn) return;
        btn.disabled = !validateArizaBaslat();
    }
    
    /* Event Binding - Ariza Bitir */
    function bindArizaBitir() {
        bodyEl.querySelectorAll('.emb-buyuk-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var act = b.getAttribute('data-act');
                if (act === 'uretim') {
                    submitArizaBitir('AKTIF');
                } else if (act === 'durur') {
                    submitArizaBitir('KAPALI');
                }
            });
        });
        footerEl.querySelector('[data-act="iptal"]').addEventListener('click', closeModal);
    }
    
    /* Mini F25.2 - Modal scope */
    function initMiniKalipDropdown(container, onSelect) {
        var input = container.querySelector('.enj-modal-kalip-input');
        var liste = container.querySelector('.enj-modal-kalip-liste');
        if (!input || !liste) return;
        
        var goruntulenenler = [];
        var aktifIdx = -1;
        
        fetchKalipListesi(function (kayitlar) {
            // Cache yuklu, listening hazir
        });
        
        input.addEventListener('input', function () {
            if (input.disabled) return;
            var q = (input.value || '').trim().toLocaleLowerCase('tr');
            if (q.length < 1) { liste.hidden = true; return; }
            
            fetchKalipListesi(function (kayitlar) {
                goruntulenenler = kayitlar.filter(function (k) {
                    return (k.kalip_kod || '').toLocaleLowerCase('tr').indexOf(q) >= 0 ||
                           (k.model_kod || '').toLocaleLowerCase('tr').indexOf(q) >= 0 ||
                           (k.model_ad || '').toLocaleLowerCase('tr').indexOf(q) >= 0 ||
                           (k.asorti || '').toLocaleLowerCase('tr').indexOf(q) >= 0;
                }).slice(0, 30);
                
                if (goruntulenenler.length === 0) {
                    liste.innerHTML = '<div class="enj-modal-kalip-bos">Eslesme yok</div>';
                } else {
                    var html = '';
                    for (var i = 0; i < goruntulenenler.length; i++) {
                        var k = goruntulenenler[i];
                        var disp = escapeHTML(k.kalip_kod + ' / ' + (k.model_ad || k.model_kod));
                        html += '<div class="enj-modal-kalip-item" data-id="' + k.id + '" data-kod="' + escapeAttr(k.kalip_kod) + '">' + disp + '</div>';
                    }
                    liste.innerHTML = html;
                }
                liste.hidden = false;
                aktifIdx = -1;
            });
        });
        
        liste.addEventListener('click', function (e) {
            var item = e.target.closest('.enj-modal-kalip-item');
            if (item && item.dataset.id) {
                var id = parseInt(item.dataset.id, 10);
                var kod = item.dataset.kod || '';
                input.value = kod;
                liste.hidden = true;
                if (onSelect) onSelect(id, kod);
            }
        });
        
        // Dis-tik kapatma
        document.addEventListener('click', function (e) {
            if (liste.hidden) return;
            if (!e.target.closest('.enj-modal-kalip-secici')) liste.hidden = true;
        });
        
        // Keyboard
        input.addEventListener('keydown', function (e) {
            if (liste.hidden) return;
            var items = liste.querySelectorAll('.enj-modal-kalip-item');
            if (e.key === 'ArrowDown') {
                aktifIdx = Math.min(aktifIdx + 1, items.length - 1);
                updateAktif(items);
                e.preventDefault();
            } else if (e.key === 'ArrowUp') {
                aktifIdx = Math.max(aktifIdx - 1, 0);
                updateAktif(items);
                e.preventDefault();
            } else if (e.key === 'Enter' && aktifIdx >= 0) {
                items[aktifIdx].click();
                e.preventDefault();
            } else if (e.key === 'Escape') {
                liste.hidden = true;
                e.stopPropagation();
            }
        });
        
        function updateAktif(items) {
            for (var i = 0; i < items.length; i++) {
                if (i === aktifIdx) {
                    items[i].classList.add('aktif');
                    items[i].scrollIntoView({block: 'nearest'});
                } else {
                    items[i].classList.remove('aktif');
                }
            }
        }
    }
    
    function fetchKalipListesi(callback) {
        if (miniKalipCache) {
            callback(miniKalipCache);
            return;
        }
        fetch('/enjeksiyon/api/kalip-listesi')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.ok) {
                    miniKalipCache = d.kayitlar || [];
                    callback(miniKalipCache);
                } else {
                    callback([]);
                }
            })
            .catch(function () { callback([]); });
    }
    
    
    /* ════════════════════════════════════════════════════════════
       API BOLUMU - EnjModalAPI
       Fetch, submit, backend response, hata yonetimi
       ════════════════════════════════════════════════════════════ */
    
    function submitSetupBaslat() {
        if (!validateSetupBaslat()) return;
        if (!state.istId) return notify('İstasyon ID yok');
        
        var body = {
            sebep: state.sebepSetup
        };
        if (!state.kalipSonra && state.yeniKalipId) {
            body.yeni_kalip_id = state.yeniKalipId;
        }
        if (state.kalipSonra) {
            body.kalip_sonra = true;
        }
        if (state.not) {
            body.not = state.not;
        }
        
        apiSubmit('/setup-start', body, function (data) {
            updateSlotAfterSetupStart();
            closeModal();
        });
    }
    
    function submitSetupBitir(success) {
        if (success && !validateSetupBitirBasari()) {
            notify('Yeni kalıp seçmeden setup tamamlanamaz.');
            return;
        }
        if (!state.istId) return notify('İstasyon ID yok');
        
        var body = {
            success: success
        };
        if (success && state.modalKalipId) {
            body.yeni_kalip_id = state.modalKalipId;
        }
        if (!success && !state.eskiKalipKod) {
            body.hedef_durum = 'KAPALI';
        }
        
        apiSubmit('/setup-end', body, function (data) {
            updateSlotAfterSetupEnd(data);
            closeModal();
        });
    }
    
    function submitArizaBaslat() {
        if (!validateArizaBaslat()) return;
        if (!state.istId) return notify('İstasyon ID yok');
        
        var body = {
            sebep: state.sebepAriza
        };
        if (state.sebepDetay) {
            body.sebep_detay = state.sebepDetay;
        }
        
        apiSubmit('/ariza-start', body, function (data) {
            updateSlotAfterArizaStart();
            closeModal();
        });
    }
    
    function submitArizaBitir(yeniDurum) {
        if (!state.istId) return notify('İstasyon ID yok');
        
        var body = {
            hedef_durum: yeniDurum
        };
        
        apiSubmit('/ariza-end', body, function (data) {
            updateSlotAfterArizaEnd(data, yeniDurum);
            closeModal();
        });
    }

    function submitIlkSetup() {
        if (!validateSetupForm(true)) {
            return;
        }

        var allBtn = overlayEl.querySelectorAll('button');
        allBtn.forEach(function (b) { b.disabled = true; });

        var rid = state.raporId;
        var sl = state.slotLetter;
        var createBody = collectSetupCreateBody();
        var base = '/enjeksiyon/api/rapor/' + rid + '/setup';

        fetch(base, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify(createBody)
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                throw new Error((res.data && res.data.hata) || 'Setup oluşturulamadı');
            }
            var newId = res.data.setup && res.data.setup.id;
            if (!newId) throw new Error('Setup id alınamadı');
            return fetch(base + '/' + newId + '/onayla', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin'
            });
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                throw new Error((res.data && res.data.hata) || 'Setup onaylanamadı');
            }
            closeModal();
            if (window.enjLoadOzet) window.enjLoadOzet();
            document.dispatchEvent(new CustomEvent('enj-ab-ozet-refresh'));
            notify('Setup onaylandı (Slot ' + sl + ')');
        })
        .catch(function (err) {
            notify('Hata: ' + (err.message || 'Bağlantı hatası'));
            allBtn.forEach(function (b) { b.disabled = false; });
            refreshSetupSubmitBtn();
        });
    }

    function submitKalipDegistir() {
        if (!validateSetupForm(true)) {
            return;
        }

        if (isSetupBaslatMode()) {
            submitIlkSetup();
            return;
        }

        if (!state.setupId) {
            notify('Aktif setup bulunamadı.');
            return;
        }

        var allBtn = overlayEl.querySelectorAll('button');
        allBtn.forEach(function (b) { b.disabled = true; });

        var rid = state.raporId;
        var oldId = state.setupId;
        var sl = state.slotLetter;
        var createBody = collectSetupCreateBody();
        var sebepLabel = KALIP_DEGISTIR_SEBEP_LABEL[state.sebepKalipDegistir] ||
            state.sebepKalipDegistir;
        var base = '/enjeksiyon/api/rapor/' + rid + '/setup';

        fetch(base + '/' + oldId + '/kapat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({
                degisim_sebebi: sebepLabel,
                notlar: state.kalipDegistirNot || null
            })
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                throw new Error((res.data && res.data.hata) || 'Setup kapatılamadı');
            }
            return fetch(base, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify(createBody)
            });
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                throw new Error((res.data && res.data.hata) || 'Yeni setup oluşturulamadı');
            }
            var newId = res.data.setup && res.data.setup.id;
            if (!newId) throw new Error('Yeni setup id alınamadı');
            return fetch(base + '/' + newId + '/onayla', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                credentials: 'same-origin'
            });
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                throw new Error((res.data && res.data.hata) || 'Setup onaylanamadı');
            }
            closeModal();
            if (window.enjLoadOzet) window.enjLoadOzet();
            document.dispatchEvent(new CustomEvent('enj-ab-ozet-refresh'));
            notify('Setup değiştirildi (Slot ' + sl + ')');
        })
        .catch(function (err) {
            notify('Hata: ' + (err.message || 'Bağlantı hatası'));
            allBtn.forEach(function (b) { b.disabled = false; });
            refreshSetupSubmitBtn();
        });
    }
    
    function apiSubmit(endpoint, body, onSuccess) {
        // Tum submit butonlari disabled (cift-tik onleme)
        var allBtn = overlayEl.querySelectorAll('button');
        allBtn.forEach(function (b) { b.disabled = true; });
        
        fetch('/enjeksiyon/api/istasyon/' + state.istId + endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify(body)
        })
        .then(function (r) {
            return r.json().then(function (d) { return {ok: r.ok, status: r.status, data: d}; });
        })
        .then(function (res) {
            if (!res.ok || !res.data.ok) {
                var hata = (res.data && res.data.hata) || ('HTTP ' + res.status);
                // Operator dostu mesajlar
                if (hata.indexOf('yeni_kalip_id zorunlu') >= 0) {
                    hata = 'Yeni kalıp seçmeden setup tamamlanamaz.';
                }
                notify('Hata: ' + hata);
                allBtn.forEach(function (b) { b.disabled = false; });
                // Submit-baslat butonu icin validation tekrar
                refreshAllSubmitButtons();
                return;
            }
            onSuccess(res.data);
        })
        .catch(function (err) {
            notify('Bağlantı hatası');
            allBtn.forEach(function (b) { b.disabled = false; });
            refreshAllSubmitButtons();
        });
    }
    
    function refreshAllSubmitButtons() {
        if (state.modalTip === 'setup-baslat') refreshSetupBaslatSubmit();
        if (state.modalTip === 'setup-bitir') refreshSetupBitirEvet();
        if (state.modalTip === 'ariza-baslat') refreshArizaBaslatSubmit();
    }
    
    
    /* Slot DOM Update - Modal sonrasi */
    function updateSlotAfterSetupStart() {
        if (!state.slot) return;
        state.slot.classList.remove('durum-aktif', 'durum-kapali', 'durum-ariza');
        state.slot.classList.add('durum-setup');
        state.slot.classList.remove('on');
        state.slot.dataset.durum = 'SETUP';
        if (state.yeniKalipKod) {
            state.slot.dataset.setupYeni = state.yeniKalipKod;
        }
    }
    
    function updateSlotAfterSetupEnd(data) {
        if (!state.slot) return;
        var yeniDurum = data.durum || 'AKTIF';
        state.slot.classList.remove('durum-aktif', 'durum-kapali', 'durum-setup', 'durum-ariza');
        state.slot.classList.add('durum-' + yeniDurum.toLowerCase());
        if (yeniDurum === 'AKTIF') {
            state.slot.classList.add('on');
        } else {
            state.slot.classList.remove('on');
        }
        state.slot.dataset.durum = yeniDurum;
        state.slot.dataset.setupYeni = '';
        // Yeni kalip kodu update et
        if (data.kalip_id && state.modalKalipKod) {
            state.slot.dataset.kalipKod = state.modalKalipKod;
        } else if (data.kalip_id && state.setupYeniKalipKod) {
            state.slot.dataset.kalipKod = state.setupYeniKalipKod;
        }
        document.dispatchEvent(new CustomEvent('enj-ab-ozet-refresh'));
    }
    
    function updateSlotAfterArizaStart() {
        if (!state.slot) return;
        state.slot.classList.remove('durum-aktif', 'durum-kapali', 'durum-setup');
        state.slot.classList.add('durum-ariza');
        state.slot.classList.remove('on');
        state.slot.dataset.durum = 'ARIZA';
        state.slot.dataset.arizaSebep = state.sebepAriza;
    }
    
    function updateSlotAfterArizaEnd(data, yeniDurum) {
        if (!state.slot) return;
        state.slot.classList.remove('durum-aktif', 'durum-kapali', 'durum-setup', 'durum-ariza');
        state.slot.classList.add('durum-' + yeniDurum.toLowerCase());
        if (yeniDurum === 'AKTIF') {
            state.slot.classList.add('on');
        } else {
            state.slot.classList.remove('on');
        }
        state.slot.dataset.durum = yeniDurum;
        state.slot.dataset.arizaSebep = '';
    }
    
    
    /* Helpers */
    function escapeHTML(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
        });
    }
    function escapeAttr(s) {
        return String(s == null ? '' : s).replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }
    function arizaSebepTurkce(sebep) {
        var map = {
            'KALIP': 'Kalıp Arızası',
            'HIDROLIK': 'Hidrolik Arızası',
            'ELEKTRIK': 'Elektrik Arızası',
            'MALZEME': 'Malzeme Arızası',
            'OPERATOR': 'Operatör Hatası',
            'BILINMIYOR': 'Bilinmeyen Arıza'
        };
        return map[sebep] || sebep || 'Arıza';
    }
    function notify(metin) {
        if (window._enjShowToast) {
            window._enjShowToast(metin);
        } else {
            console.warn('[EnjModal]', metin);
        }
    }
    
    
    /* ════════════════════════════════════════════════════════════
       PUBLIC API
       ════════════════════════════════════════════════════════════ */
    window.EnjModal = {
        open: openModal,
        close: closeModal
    };
    
    /* INIT */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initUI);
    } else {
        initUI();
    }
})();
/* === END: F9_2_P3C_MODAL_CONTROLLER === */


/* === BEGIN: ENJ_FOTO_FIX === */
/* Enjeksiyon foto upload kontrolu - tikla, kamera ac, upload, onizleme */
(function () {
    'use strict';
    var wrap = document.querySelector('.enj-wrap');
    if (!wrap) return;
    var raporId = parseInt(wrap.dataset.raporId || '', 10);
    if (!raporId || isNaN(raporId)) return;

    var MAX = 5 * 1024 * 1024;

    function fmtMB(bytes) {
        return (Math.round((bytes / 1024 / 1024) * 10) / 10).toFixed(1);
    }

    function loadExisting() {
        fetch('/enjeksiyon/api/foto?rapor_id=' + raporId)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok || !d.fotolar) return;
                d.fotolar.forEach(function (f) {
                    var cell = document.querySelector('.enj-gs-foto[data-foto-tip="' + f.tip + '"]');
                    if (!cell) return;
                    var thumb = cell.querySelector('.enj-foto-thumb');
                    var zone = cell.querySelector('.zone');
                    if (thumb && f.url) {
                        thumb.src = f.url + '?t=' + Date.now();
                        thumb.hidden = false;
                        if (zone) zone.style.display = 'none';
                    }
                });
            })
            .catch(function () { });
    }

    function bind(cell) {
        var input = cell.querySelector('input[type="file"]');
        var zone = cell.querySelector('.zone');
        var thumb = cell.querySelector('.enj-foto-thumb');
        var tip = cell.dataset.fotoTip;
        if (!input || !tip) return;

        function trigger() { input.click(); }
        if (zone) zone.addEventListener('click', trigger);
        if (thumb) thumb.addEventListener('click', trigger);

        input.addEventListener('change', function () {
            var f = input.files && input.files[0];
            if (!f) return;
            if (f.size > MAX) {
                alert('Dosya 5 MB sinirini asiyor (' + fmtMB(f.size) + ' MB)');
                input.value = '';
                return;
            }
            if (!f.type || f.type.indexOf('image/') !== 0) {
                alert('Sadece resim dosyasi kabul edilir');
                input.value = '';
                return;
            }

            var fd = new FormData();
            fd.append('rapor_id', raporId);
            fd.append('tip', tip);
            fd.append('dosya', f);

            var origText = zone ? zone.innerHTML : '';
            if (zone) zone.textContent = 'Yukleniyor...';

            fetch('/enjeksiyon/api/foto/ekle', { method: 'POST', body: fd })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) throw new Error((d && d.hata) || 'Yukleme hatasi');
                    if (thumb && d.url) {
                        thumb.src = d.url + '?t=' + Date.now();
                        thumb.hidden = false;
                        if (zone) zone.style.display = 'none';
                    }
                })
                .catch(function (err) {
                    alert('Foto yukleme hatasi: ' + err.message);
                    if (zone) {
                        zone.innerHTML = origText;
                        zone.style.display = '';
                    }
                })
                .then(function () {
                    input.value = '';
                });
        });
    }

    document.querySelectorAll('.enj-gs-foto[data-foto-tip]').forEach(bind);
    loadExisting();
    if (typeof cpsLog === 'function') cpsLog('[CPS LOCAL] ENJ_FOTO_FIX aktif');
})();
/* === END: ENJ_FOTO_FIX === */

/* === BEGIN: ENJ_FOTO_SIL === */
/* Yuklenmis fotograflara X silme butonu ekler (MutationObserver ile) */
(function () {
    'use strict';

    function silBtnEkle(thumb) {
        if (!thumb) return;
        var cell = thumb.closest('.enj-gs-foto');
        if (!cell) return;
        if (cell.querySelector('.enj-foto-sil')) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'enj-foto-sil';
        btn.title = 'Fotografi sil';
        btn.innerHTML = '\u2715';

        function syncVis() {
            btn.style.display = thumb.hidden ? 'none' : 'flex';
        }
        syncVis();

        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            e.preventDefault();

            var wrap = document.querySelector('.enj-wrap');
            var raporId = parseInt((wrap && wrap.dataset.raporId) || '', 10);
            var tip = cell.dataset.fotoTip;
            if (!raporId || !tip) return;

            if (!confirm('Bu fotografi silmek istediginizden emin misiniz?')) return;

            fetch('/enjeksiyon/api/foto?rapor_id=' + raporId)
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) throw new Error('foto listesi hatasi');
                    var foto = (d.fotolar || []).filter(function (f) { return f.tip === tip; })[0];
                    if (!foto) throw new Error('Foto bulunamadi');
                    return fetch('/enjeksiyon/api/foto/' + foto.id, { method: 'DELETE' });
                })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) throw new Error((d && d.hata) || 'Silme hatasi');
                    thumb.hidden = true;
                    thumb.src = '';
                    var zone = cell.querySelector('.zone');
                    if (zone) zone.style.display = '';
                    btn.style.display = 'none';
                })
                .catch(function (err) {
                    alert('Silme hatasi: ' + err.message);
                });
        });

        cell.appendChild(btn);

        var mo = new MutationObserver(syncVis);
        mo.observe(thumb, { attributes: true, attributeFilter: ['hidden'] });
    }

    function tara() {
        document.querySelectorAll('.enj-gs-foto[data-foto-tip] .enj-foto-thumb').forEach(silBtnEkle);
    }

    tara();
    setTimeout(tara, 500);
    setTimeout(tara, 1500);
    setTimeout(tara, 3000);
})();
/* === END: ENJ_FOTO_SIL === */

/* === BEGIN: ENJ_AB_FAZ2_FINAL === */
(function () {
  'use strict';
  var wrap = document.querySelector('.enj-wrap');
  if (!wrap) return;
  var raporId = parseInt(wrap.dataset.raporId || '', 10);
  if (!raporId || isNaN(raporId)) return;

  var DEBOUNCE = 600;
  var timers = {};
  var debPending = {};
  function deb(key, fn) {
    debPending[key] = fn;
    if (timers[key]) clearTimeout(timers[key]);
    timers[key] = setTimeout(function () {
      delete timers[key];
      delete debPending[key];
      fn();
    }, DEBOUNCE);
  }
  function debFlush(key) {
    if (timers[key]) {
      clearTimeout(timers[key]);
      delete timers[key];
    }
    var fn = debPending[key];
    if (fn) {
      delete debPending[key];
      fn();
    }
  }
  function fJSON(url, opts) {
    return fetch(url, opts || {}).then(function (r) { return r.json(); });
  }

  function enjGostergeTxt(id, v) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = (v == null || v === '') ? '—' : String(v);
  }

  function enjGostergeKbcVal(ayar) {
    if (!ayar) return null;
    if (ayar.efektif_kalip_basi_cift != null && ayar.efektif_kalip_basi_cift !== '') {
      return ayar.efektif_kalip_basi_cift;
    }
    if (ayar.kalip_basi_cift != null && ayar.kalip_basi_cift !== '') {
      return ayar.kalip_basi_cift;
    }
    return null;
  }

  /** Aktif göz: kapasite_per_cycle / efektif KBÇ; yoksa bagli_kalip_adet fallback */
  function enjGostergeAktifGoz(kapasite, ayar, fallbackBagli) {
    var kbc = enjGostergeKbcVal(ayar);
    var kap = (kapasite != null && kapasite !== '') ? Number(kapasite) : null;
    if (kap != null && kbc != null && Number(kbc) > 0) {
      return Math.round(kap / Number(kbc));
    }
    if (ayar && ayar.bagli_kalip_adet != null && ayar.bagli_kalip_adet !== '') {
      return ayar.bagli_kalip_adet;
    }
    if (ayar && fallbackBagli != null && fallbackBagli !== '') {
      return fallbackBagli;
    }
    return null;
  }

  function enjGostergeSlotSet(sl, slotData, fallbackBagli) {
    var data = slotData || {};
    var ayar = data.ayar;
    var kap = data.kapasite_per_cycle;
    enjGostergeTxt('enj-gosterge-bagli-' + sl, enjGostergeAktifGoz(kap, ayar, fallbackBagli));
    enjGostergeTxt('enj-gosterge-kbc-' + sl, enjGostergeKbcVal(ayar));
    enjGostergeTxt('enj-gosterge-kap-' + sl, kap);
  }
  window.enjGostergeSlotSet = enjGostergeSlotSet;

  /** FAZ-UI1-FIX: aktif göz = üst istasyon gridinde seçili slot sayısı */
  function enjCountAktifGozForSlot(slotLetter) {
    slotLetter = String(slotLetter || '').toUpperCase();
    var panel = document.querySelector('.enj-mak-panel.aktif') ||
      document.querySelector('.enj-mak-panel');
    if (!panel) return 0;
    return panel.querySelectorAll('button.s.on[data-slot="' + slotLetter + '"]').length;
  }
  window.enjCountAktifGozForSlot = enjCountAktifGozForSlot;

  /** KBÇ: efektif (COALESCE) > ham istasyon > mevcut span değeri koru */
  function enjGostergeKbcSet(sl, ayar) {
    var v = enjGostergeKbcVal(ayar);
    if (v == null) return;
    enjGostergeTxt('enj-gosterge-kbc-' + sl, v);
  }
  window.enjGostergeKbcSet = enjGostergeKbcSet;

  /** ENJ-RENK-KORUMA: uretim rengi oncelikli, master sadece oneri */
  function enjRenkInputDolu(sl) {
    var el = document.getElementById('enj-renk-' + sl);
    return el && String(el.value || '').trim() !== '';
  }

  function enjRenkMasterOner(sl, masterRenk) {
    if (enjRenkInputDolu(sl)) return;
    var m = (masterRenk == null) ? '' : String(masterRenk).trim();
    if (!m) return;
    var el = document.getElementById('enj-renk-' + sl);
    if (el) el.value = m;
  }

  function enjRenkSetFromServer(sl, serverRenk) {
    var el = document.getElementById('enj-renk-' + sl);
    if (!el) return;
    var srv = (serverRenk == null) ? '' : String(serverRenk).trim();
    if (srv !== '') {
      el.value = srv;
    }
    // ayar.renk bos/null + input dolu → mevcut uretim rengini koru
  }

  /** FIX-A: pişme focus/dirty iken loadOzet overwrite etmez */
  var enjPismeDirty = { a: false, b: false };

  function enjPismeSlKey(slot) {
    return String(slot || '').toLowerCase();
  }

  function enjPismeEl(sl) {
    return document.getElementById('enj-pisme-' + enjPismeSlKey(sl));
  }

  function enjPismeIsEditing(sl) {
    var key = enjPismeSlKey(sl);
    var el = enjPismeEl(key);
    if (!el) return false;
    return document.activeElement === el || enjPismeDirty[key];
  }

  function enjPismeParseRaw(raw) {
    var s = String(raw || '').trim();
    if (s === '') return null;
    var n = parseInt(s, 10);
    if (isNaN(n) || n < 0) return null;
    return n;
  }

  function enjPismeNormalizeEl(el) {
    if (!el) return null;
    var n = enjPismeParseRaw(el.value);
    el.value = (n == null) ? '' : String(n);
    return n;
  }

  function enjPismeMarkDirty(sl) {
    enjPismeDirty[enjPismeSlKey(sl)] = true;
  }

  function enjPismeClearDirty(sl) {
    enjPismeDirty[enjPismeSlKey(sl)] = false;
  }

  function enjPismeSetFromServer(sl, serverVal) {
    if (enjPismeIsEditing(sl)) return;
    var el = enjPismeEl(sl);
    if (!el) return;
    var n = enjPismeParseRaw(serverVal);
    el.value = (n == null) ? '' : String(n);
    enjPismeClearDirty(sl);
  }

  function enjGostergeParseInt(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var t = String(el.textContent || '').trim();
    if (t === '' || t === '—') return null;
    var n = parseInt(t, 10);
    return (isNaN(n) || n <= 0) ? null : n;
  }

  /** FIX-D: ilk setup POST için canlı gösterge değerleri */
  function enjSlotSetupPayloadExtras(slot) {
    var sl = enjPismeSlKey(slot);
    var out = {};
    var goz = enjGostergeParseInt('enj-gosterge-bagli-' + sl);
    if (goz != null) out.aktif_goz_sayisi = goz;
    var kbc = enjGostergeParseInt('enj-gosterge-kbc-' + sl);
    if (kbc != null) out.kalip_basi_cift = kbc;
    return out;
  }
  window.enjSlotSetupPayloadExtras = enjSlotSetupPayloadExtras;

  function enjSetupLockToastMsg(slot, guncel) {
    slot = String(slot || '?').toUpperCase();
    if (guncel.kalip_id) {
      return 'Slot ' + slot + ': Kalıp değişimi için Kalıp Değiştir modalını kullanın.';
    }
    if ('pisme_suresi_sn' in guncel) {
      return 'Slot ' + slot + ': Pişme süresi setup parametresidir — aktif setup varken doğrudan değiştirilemez.';
    }
    if ('renk' in guncel) {
      return 'Slot ' + slot + ': Renk setup parametresidir — aktif setup varken doğrudan değiştirilemez.';
    }
    return 'Slot ' + slot + ': Aktif setup kilitli — setup onay akışını kullanın.';
  }
  window.enjSetupLockToastMsg = enjSetupLockToastMsg;

  function enjSlotTopluPayload(slot, base, masterRenk) {
    var sl = String(slot || '').toLowerCase();
    var p = Object.assign({}, base || {});
    if ('renk' in p && (p.renk == null || String(p.renk).trim() === '')) {
      delete p.renk;
    }
    if (!enjRenkInputDolu(sl) && masterRenk != null && String(masterRenk).trim() !== '') {
      p.renk = String(masterRenk).trim();
    }
    return p;
  }

  function enjSlotAyarFromOzet(sl, slotData, fallbackBagli) {
    var data = slotData || {};
    var ayar = data.ayar;
    var setV = function (id, v) {
      var el = document.getElementById(id);
      if (el) el.value = (v == null || v === '') ? '' : v;
    };
    if (ayar) {
      enjRenkSetFromServer(sl, ayar.renk);
      var pismeEl = document.getElementById('enj-pisme-' + sl);
      if (pismeEl) {
        pismeEl.value = (ayar.pisme_suresi_sn == null || ayar.pisme_suresi_sn === '')
          ? '' : String(ayar.pisme_suresi_sn);
      }
      setV('enj-kalip-' + sl + '-id', ayar.kalip_id);
      setV('enj-kalip-' + sl + '-input', ayar.kalip_kod || '');
    } else {
      setV('enj-kalip-' + sl + '-input', '');
      setV('enj-kalip-' + sl + '-id', '');
    }
    enjGostergeSlotSet(sl, data, fallbackBagli);
  }
  window.enjSlotAyarFromOzet = enjSlotAyarFromOzet;

  /**
   * Gunluk rapor ust personel gostergesi: max(AKTIF A setup, AKTIF B setup).
   * Ornek: A=5, B=4 -> genel alan 5. Slot setup degerleri birbirini ezmez.
   */
  function enjApplyRaporPersonelMax(vals) {
    var gen = document.getElementById('enj-personel-sayisi');
    if (!gen || !vals || !vals.length) return;
    var mx = Math.max.apply(null, vals.filter(function (v) {
      return v != null && !isNaN(v) && v > 0;
    }));
    if (!isNaN(mx) && mx > 0) gen.value = String(mx);
  }

  function enjRefreshSlotPersonelDisplays() {
    var pending = 2;
    var peVals = [];
    ['A', 'B'].forEach(function (slot) {
      var sl = slot.toLowerCase();
      var el = document.getElementById('enj-gosterge-personel-' + sl);
      fetch(
        '/enjeksiyon/api/rapor/' + raporId + '/setup?slot=' + encodeURIComponent(slot) + '&aktif=1',
        {credentials: 'same-origin'}
      )
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var pe = d && d.setup && d.setup.personel_sayisi;
          if (el) {
            el.textContent = (pe != null && pe !== '') ? String(pe) : '—';
          }
          if (pe != null && pe !== '') {
            var n = parseInt(pe, 10);
            if (!isNaN(n) && n > 0) peVals.push(n);
          }
        })
        .catch(function () {
          if (el) el.textContent = '—';
        })
        .finally(function () {
          pending--;
          if (pending === 0) enjApplyRaporPersonelMax(peVals);
        });
    });
  }
  window.enjRefreshSlotPersonelDisplays = enjRefreshSlotPersonelDisplays;

  function loadOzet() {
    fJSON('/enjeksiyon/api/rapor/' + raporId + '/ab-ozet').then(function (d) {
      if (!d || !d.ok) return;
      var bagliMakine = wrap.dataset.bagliKalip;
      ['A','B'].forEach(function (slot) {
        var sl = slot.toLowerCase();
        var data = d[slot] || {};
        var setV = function (id, v) {
          var el = document.getElementById(id);
          if (el) el.value = (v == null) ? '' : v;
        };
        setV('enj-cev-' + sl + '-top', data.cevrim);
        setV('enj-uret-' + sl + '-top', data.uretilen);
        enjSlotAyarFromOzet(sl, data, bagliMakine);

        // Setup hazir degil ise kap display uzerine uyari goster
        var hazirEl = document.getElementById('enj-setup-hazir-' + sl);
        if (hazirEl) {
          hazirEl.style.display = data.setup_hazir ? 'none' : '';
        }
      });
      enjRefreshSlotPersonelDisplays();

      // ENJ_GUNLUK_OZET: d.toplam -> span ID'lere yaz
      var top = d.toplam || {};
      var setTxt = function (id, v, suffix) {
        var el = document.getElementById(id);
        if (!el) return;
        if (v == null || v === '') { el.textContent = '—'; el.classList.add('muted'); }
        else { el.textContent = v + (suffix || ''); el.classList.remove('muted'); }
      };
      setTxt('enj-ozet-toplam-tur',   top.cevrim   != null ? top.cevrim   : null);
      setTxt('enj-ozet-teorik-cift',  top.uretilen != null ? top.uretilen : null);
      setTxt('enj-ozet-net-cift',     top.net      != null ? top.net      : null);
      setTxt('enj-ozet-fire-cift',    top.fire     != null ? top.fire     : null);
      setTxt('enj-ozet-korgun',       null); // ab-ozet API korgun donmuyor, — kalsin
      setTxt('enj-ozet-fark',         null); // ab-ozet API fark donmuyor, — kalsin
      setTxt('enj-ozet-fire-orani',   top.fire_orani != null ? top.fire_orani : null, '%');
    }).catch(function () {});
  }

  // Sayfa ilk yuklendiginde bozuk snapshot'lari sessizce duzelt
  (function() {
    if (!raporId) return;
    fetch('/enjeksiyon/api/rapor/' + raporId + '/snapshot-duzelt', {
      method: 'POST',
      credentials: 'same-origin'
    }).catch(function() {});
  })();

  function buildInitialFormFromPanel(slot, activeSetup) {
    slot = String(slot || '').toUpperCase();
    var sl = slot.toLowerCase();
    var form = {};
    var kalipInp = document.getElementById('enj-kalip-' + sl + '-input');
    var kalipHid = document.getElementById('enj-kalip-' + sl + '-id');
    var renkEl = document.getElementById('enj-renk-' + sl);
    var pismeEl = document.getElementById('enj-pisme-' + sl);
    var personelEl = document.getElementById('enj-personel-sayisi');
    var gozEl = document.getElementById('enj-gosterge-bagli-' + sl);
    var kbcEl = document.getElementById('enj-gosterge-kbc-' + sl);

    if (activeSetup) {
      form.kalip_id = activeSetup.kalip_id;
      form.kalip_kod = activeSetup.kalip_kod_snapshot || '';
      form.renk = activeSetup.renk || '';
      form.pisme_suresi_sn = activeSetup.pisme_suresi_sn;
      if (activeSetup.personel_sayisi != null && activeSetup.personel_sayisi !== '') {
        form.personel_sayisi = activeSetup.personel_sayisi;
      }
      form.aktif_goz_sayisi = activeSetup.aktif_goz_sayisi;
      form.kalip_basi_cift = activeSetup.kalip_basi_cift;
    } else {
      if (kalipHid && kalipHid.value) form.kalip_id = parseInt(kalipHid.value, 10);
      if (kalipInp) form.kalip_kod = String(kalipInp.value || '').trim();
      if (renkEl) form.renk = String(renkEl.value || '').trim();
      if (pismeEl && pismeEl.value !== '') form.pisme_suresi_sn = pismeEl.value;
      if (form.personel_sayisi == null && personelEl && personelEl.value !== '') {
        var peDef = parseInt(personelEl.value, 10);
        if (!isNaN(peDef) && peDef > 0) form.personel_sayisi = peDef;
      }
    }
    if (window.enjCountAktifGozForSlot) {
      var gridGoz = window.enjCountAktifGozForSlot(slot);
      if (gridGoz > 0) form.aktif_goz_sayisi = gridGoz;
    }
    if (!form.aktif_goz_sayisi && gozEl && gozEl.textContent) {
      var g = parseInt(String(gozEl.textContent).trim(), 10);
      if (!isNaN(g) && g > 0) form.aktif_goz_sayisi = g;
    }
    if (!form.kalip_basi_cift && kbcEl && kbcEl.textContent) {
      var k = parseInt(String(kbcEl.textContent).trim(), 10);
      if (!isNaN(k) && k > 0) form.kalip_basi_cift = k;
    }
    return form;
  }

  function openSetupModal(slot) {
    slot = String(slot || '').toUpperCase();
    if (slot !== 'A' && slot !== 'B') return;
    if (!window.EnjModal) {
      if (window._enjShowToast) window._enjShowToast('Modal yüklenemedi');
      return;
    }
    fetch(
      '/enjeksiyon/api/rapor/' + raporId + '/setup?slot=' + encodeURIComponent(slot) + '&aktif=1',
      {credentials: 'same-origin'}
    )
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var active = d && d.setup;
        var initForm = buildInitialFormFromPanel(slot, active);
        if (active && active.id) {
          window.EnjModal.open('kalip-degistir', null, {
            mode: 'degistir',
            slotLetter: slot,
            setupId: active.id,
            raporId: raporId,
            eskiSetup: active,
            initialForm: initForm
          });
        } else {
          window.EnjModal.open('kalip-degistir', null, {
            mode: 'baslat',
            slotLetter: slot,
            raporId: raporId,
            initialForm: initForm
          });
        }
      })
      .catch(function () {
        window.EnjModal.open('kalip-degistir', null, {
          mode: 'baslat',
          slotLetter: slot,
          raporId: raporId,
          initialForm: buildInitialFormFromPanel(slot, null)
        });
      });
  }
  window.openSetupModal = openSetupModal;

  function openKalipDegistirModal(slot, setupId, pending, meta) {
    openSetupModal(slot);
  }
  window.openKalipDegistirModal = openKalipDegistirModal;

  function openIlkSetupModal(slot, pending, meta) {
    openSetupModal(slot);
  }
  window.openIlkSetupModal = openIlkSetupModal;

  function slotToplu(slot, payload, meta) {
    slot = String(slot || '').toUpperCase();
    var p = Object.assign({}, payload || {});
    if ('renk' in p && (p.renk == null || String(p.renk).trim() === '')) {
      delete p.renk;
    }
    p.slot = slot;
    return fetch('/enjeksiyon/api/rapor/' + raporId + '/slot-toplu', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify(p)
    }).then(function (r) {
      return r.json().then(function (d) {
        return {status: r.status, ok: r.ok && d && d.ok, data: d, locked409: r.status === 409};
      });
    }).then(function (res) {
      if (res.locked409 && res.data && res.data.setup_id) {
        if ('pisme_suresi_sn' in p) {
          enjPismeClearDirty(String(slot).toLowerCase());
        }
        loadOzet();
        if (p.kalip_id) {
          openSetupModal(slot);
        } else if (window._enjShowToast) {
          var lockMsg = window.enjSetupLockToastMsg
            ? window.enjSetupLockToastMsg(slot, p)
            : (res.data.hata || 'Aktif setup kilitli');
          window._enjShowToast(lockMsg);
        }
      } else if (res && res.ok && 'pisme_suresi_sn' in p) {
        enjPismeClearDirty(String(slot).toLowerCase());
      }
      return res;
    });
  }

  /** FAZ-UI1: panelden setup parametresi yazimi kapali — sadece modal */
  function kalipSecimSubmit(slot, payload, meta) {
    openSetupModal(slot);
    return Promise.resolve({
      status: 428,
      ok: false,
      needSetup: true,
      data: {hata: 'Setup modal acildi'}
    });
  }

  window.enjSlotToplu = slotToplu;
  window.enjKalipSecimSubmit = kalipSecimSubmit;

  function warnSetupForSlot(slotLetter) {
    slotLetter = String(slotLetter || '').toUpperCase();
    if (slotLetter !== 'A' && slotLetter !== 'B') return Promise.resolve();
    return fetch(
      '/enjeksiyon/api/rapor/' + raporId + '/setup?slot=' + encodeURIComponent(slotLetter) + '&aktif=1',
      {credentials: 'same-origin'}
    )
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.setup) {
          if (window._enjShowToast) {
            window._enjShowToast('Önce setup onaylayın (Slot ' + slotLetter + ')');
          }
        }
      })
      .catch(function () {});
  }

  function saatlikPatch(sid, payload) {
    return fetch('/enjeksiyon/api/saatlik/' + sid, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(function(r) {
      return r.json().then(function(d) {
        // SETUP GATE: 422 = setup eksik veya yok
        if (!d.ok && d.tip === 'SETUP_EKSIK') {
          var mesaj = d.mesaj || d.hata || 'Bu taraf üretime hazır değil. Önce kalıp/setup başlatın.';
          if (window._enjShowToast) {
            window._enjShowToast(mesaj, 'uyari');
          } else {
            alert(mesaj);
          }
        }
        // MAX_TUR GUARD: 400 = saatlik tur limiti asildi
        if (!d.ok && d.tip === 'MAX_TUR_ASILDI') {
          var mesajT = d.mesaj || d.hata || 'Girilen tur değeri bu pişme süresi için çok yüksek.';
          if (window._enjShowToast) {
            window._enjShowToast(mesajT, 'hata');
          } else {
            alert(mesajT);
          }
        }
        return d;
      });
    }).catch(function() { return {ok: false}; });
  }

  /* FAZ-UI1: panel setup alanlari readonly — slotToplu baglantisi kaldirildi */

  document.querySelectorAll('tr[data-saatlik-id]').forEach(function (tr) {
    var sid = tr.dataset.saatlikId;
    if (!sid) return;
    function bind(sel, field, slotLetter) {
      var el = tr.querySelector(sel);
      if (!el) return;
      el.addEventListener('input', function () {
        var raw = el.value;
        var val = raw === '' ? 0 : parseInt(raw, 10);
        if (isNaN(val) || val < 0) val = 0;
        var p = {}; p[field] = val;
        deb('sk_' + sid + '_' + field, function () {
          if (val > 0) warnSetupForSlot(slotLetter);
          saatlikPatch(sid, p).then(function (d) {
            if (d && d.ok) loadOzet();
          });
        });
      });
    }
    bind('.cev-a-inp', 'cevrim_a', 'A');
    bind('.cev-b-inp', 'cevrim_b', 'B');

    // PATCH 1 V2: A ve B icin AYRI durum/sebep listenerlar
    // HTML'de .durum-a-sel/.durum-b-sel/.aks-a-sel/.aks-b-sel zaten var
    // Eski .durum-sel ve .aks-sel (varsa) geriye uyum icin tutuldu
    var ds = tr.querySelector('.durum-sel');
    if (ds) ds.addEventListener('change', function () {
      saatlikPatch(sid, {durum: ds.value});
    });
    var as = tr.querySelector('.aks-sel');
    if (as) as.addEventListener('change', function () {
      var v = as.value === '' ? null : parseInt(as.value, 10);
      saatlikPatch(sid, {aksama_sebep_id: isNaN(v) ? null : v});
    });

    // V2 - A tarafi durum
    var dsa = tr.querySelector('.durum-a-sel');
    if (dsa) dsa.addEventListener('change', function () {
      saatlikPatch(sid, {durum_a: dsa.value || null});
    });
    // V2 - B tarafi durum
    var dsb = tr.querySelector('.durum-b-sel');
    if (dsb) dsb.addEventListener('change', function () {
      saatlikPatch(sid, {durum_b: dsb.value || null});
    });
    // V2 - A tarafi sebep
    var asa = tr.querySelector('.aks-a-sel');
    if (asa) asa.addEventListener('change', function () {
      var va = asa.value === '' ? null : parseInt(asa.value, 10);
      saatlikPatch(sid, {aksama_sebep_a_id: isNaN(va) ? null : va});
    });
    // V2 - B tarafi sebep
    var asb = tr.querySelector('.aks-b-sel');
    if (asb) asb.addEventListener('change', function () {
      var vb = asb.value === '' ? null : parseInt(asb.value, 10);
      saatlikPatch(sid, {aksama_sebep_b_id: isNaN(vb) ? null : vb});
    });
  });

  /* SAATLIK KAYDET BUTONU: tum satirlardaki tur/durum/sebep degerlerini toplu gonder */
  var kaydetBtn = document.querySelector('.enj-btn.kaydet');
  if (kaydetBtn) {
    kaydetBtn.addEventListener('click', function () {
      var satirlar = document.querySelectorAll('tr[data-saatlik-id]');
      if (!satirlar.length) {
        if (window._enjShowToast) window._enjShowToast('Kaydedilecek satır bulunamadı.', 'uyari');
        return;
      }
      kaydetBtn.disabled = true;
      var bekleyen = satirlar.length;
      var hatalar = [];
      satirlar.forEach(function (tr) {
        var sid = tr.dataset.saatlikId;
        var payload = {};
        var cevA = tr.querySelector('.cev-a-inp');
        var cevB = tr.querySelector('.cev-b-inp');
        var durA = tr.querySelector('.durum-a-sel');
        var durB = tr.querySelector('.durum-b-sel');
        var aksA = tr.querySelector('.aks-a-sel');
        var aksB = tr.querySelector('.aks-b-sel');
        if (cevA) payload.cevrim_a = cevA.value === '' ? 0 : (parseInt(cevA.value, 10) || 0);
        if (cevB) payload.cevrim_b = cevB.value === '' ? 0 : (parseInt(cevB.value, 10) || 0);
        if (durA) payload.durum_a = durA.value || null;
        if (durB) payload.durum_b = durB.value || null;
        if (aksA) { var va = aksA.value; payload.aksama_sebep_a_id = va === '' ? null : (parseInt(va, 10) || null); }
        if (aksB) { var vb = aksB.value; payload.aksama_sebep_b_id = vb === '' ? null : (parseInt(vb, 10) || null); }
        saatlikPatch(sid, payload).then(function (d) {
          bekleyen--;
          if (d && !d.ok && d.tip !== 'SETUP_EKSIK') hatalar.push(d.hata || 'bilinmeyen');
          if (bekleyen === 0) {
            kaydetBtn.disabled = false;
            if (hatalar.length) {
              var msg = hatalar.slice(0, 3).join(' | ');
              if (window._enjShowToast) window._enjShowToast('Bazı satırlar kaydedilemedi: ' + msg, 'hata');
            } else {
              if (window._enjShowToast) window._enjShowToast('Tüm saatlik kayıtlar kaydedildi.', 'basari');
            }
            loadOzet();
          }
        }).catch(function () {
          bekleyen--;
          if (bekleyen === 0) { kaydetBtn.disabled = false; loadOzet(); }
        });
      });
    });
  }

  /* Genel personel: rapor alani — A/B setup snapshot'larini dogrudan degistirmez */
  var personel = document.getElementById('enj-personel-sayisi');
  if (personel) {
    personel.addEventListener('input', function () {
      var v = personel.value === '' ? null : parseInt(personel.value, 10);
      deb('personel', function () {
        fJSON('/enjeksiyon/api/rapor/' + raporId, {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({personel_sayisi: isNaN(v) ? null : v})
        });
      });
    });
  }

  loadOzet();
  document.addEventListener('enj-ab-ozet-refresh', loadOzet);
  window.enjLoadOzet = loadOzet;
  window.enjSlotTopluPayload = enjSlotTopluPayload;
  window.enjRenkMasterOner = enjRenkMasterOner;
})();
/* === END: ENJ_AB_FAZ2_FINAL === */

/* === BEGIN: ENJ_AB_GORSEL_V2 === */
(function () {
  'use strict';
  var wrap = document.querySelector('.enj-wrap');
  if (!wrap) return;

  ['A','B'].forEach(function (slot) {
    var sl = slot.toLowerCase();
    var panel = document.querySelector('.enj-ab-faz2[data-slot="' + slot + '"]');
    if (!panel) return;
    if (panel.querySelector('.enj-ab-faz2-gorsel')) return;

    var box = document.createElement('div');
    box.className = 'enj-ab-faz2-gorsel';
    box.id = 'enj-gorsel-' + sl;

    var img = document.createElement('img');
    img.id = 'enj-gorsel-' + sl + '-img';
    img.hidden = true;
    img.alt = slot + ' kalip gorseli';
    box.appendChild(img);

    var yok = document.createElement('span');
    yok.className = 'g-yok';
    yok.id = 'enj-gorsel-' + sl + '-yok';
    yok.textContent = 'Kalip secilmedi';
    box.appendChild(yok);

    panel.appendChild(box);
  });

  var raporId = parseInt(wrap.dataset.raporId || '', 10);
  if (!raporId || isNaN(raporId)) return;

  function loadGorseller() {
    fetch('/enjeksiyon/api/rapor/' + raporId + '/ab-ozet')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) return;
        ['A','B'].forEach(function (slot) {
          var sl = slot.toLowerCase();
          var data = d[slot] || {};
          var ayar = data.ayar || {};
          var img = document.getElementById('enj-gorsel-' + sl + '-img');
          var yok = document.getElementById('enj-gorsel-' + sl + '-yok');
          if (!img || !yok) return;
          if (ayar && ayar.gorsel) {
            img.src = ayar.gorsel;
            img.hidden = false;
            yok.hidden = true;
            img.onerror = function () {
              img.hidden = true;
              yok.textContent = 'Gorsel yok';
              yok.hidden = false;
            };
          } else {
            img.hidden = true;
            img.src = '';
            yok.textContent = (ayar && ayar.kalip_id) ? 'Gorsel yok' : 'Kalip secilmedi';
            yok.hidden = false;
          }
        });
      })
      .catch(function () {});
  }

  loadGorseller();
  setInterval(loadGorseller, 3000);
})();
/* === END: ENJ_AB_GORSEL_V2 === */

/* === BEGIN: ENJ_AB_KALIP_FIX === */
(function () {
  'use strict';
  var wrap = document.querySelector('.enj-wrap');
  if (!wrap) return;
  var raporId = parseInt(wrap.dataset.raporId || '', 10);
  if (!raporId || isNaN(raporId)) return;

  var KALIP_CACHE = null;
  function loadKalipListesi() {
    if (KALIP_CACHE) return Promise.resolve(KALIP_CACHE);
    return fetch('/enjeksiyon/api/kalip-listesi')
      .then(function(r){ return r.json(); })
      .then(function(d) {
        if (d && d.ok && d.kayitlar) KALIP_CACHE = d.kayitlar;
        return KALIP_CACHE || [];
      })
      .catch(function() { return []; });
  }

  function bindSetupPanelOpener(slot) {
    slot = String(slot || '').toUpperCase();
    var sl = slot.toLowerCase();
    var targets = [
      document.getElementById('enj-kalip-' + sl + '-input'),
      document.getElementById('enj-renk-' + sl),
      document.getElementById('enj-pisme-' + sl)
    ];
    targets.forEach(function (el) {
      if (!el) return;
      el.readOnly = true;
      el.addEventListener('click', function (e) {
        e.preventDefault();
        openSetupModal(slot);
      });
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openSetupModal(slot);
        }
        if (e.key.length === 1 || e.key === 'Backspace' || e.key === 'Delete') {
          e.preventDefault();
        }
      });
      el.addEventListener('paste', function (e) { e.preventDefault(); });
      el.addEventListener('drop', function (e) { e.preventDefault(); });
    });
    document.querySelectorAll('.enj-setup-opener[data-slot="' + slot + '"]').forEach(function (wrap) {
      wrap.addEventListener('click', function (e) {
        if (e.target.tagName === 'INPUT') return;
        e.preventDefault();
        openSetupModal(slot);
      });
    });
  }

  bindSetupPanelOpener('A');
  bindSetupPanelOpener('B');
})();
/* === END: ENJ_AB_KALIP_FIX === */

/* ===== ENJ_AB_RENK_KARTELA_V3 START ===== */
(function () {
  'use strict';
  if (window.__ENJ_AB_RENK_V3_LOADED) return;
  window.__ENJ_AB_RENK_V3_LOADED = true;

  var ENJ_RENK_DB = [
    {k:"0001",a:"S\u0130YAH",h:"#111"},{k:"0002",a:"S\u0130YAH MAT S\u0130YAH",h:"#222"},
    {k:"0030",a:"GR\u0130",h:"#888"},{k:"0031",a:"BUZ GR\u0130",h:"#b0c4d8"},
    {k:"0041",a:"F\u00dcME",h:"#555"},{k:"0042",a:"ANTRAS\u0130T UGG",h:"#444"},
    {k:"0100",a:"OPT\u0130K BEYAZ",h:"#fff"},{k:"0102",a:"OFF WHITE",h:"#f5f0e8"},
    {k:"0103",a:"LIGHT ECURU",h:"#f0ebe0"},{k:"0105",a:"BEYAZ C\u0130HAN",h:"#fafafa"},
    {k:"0106",a:"BEYAZ POLTAP",h:"#f8f8f8"},{k:"0170",a:"PEMBE",h:"#ffb6c1"},
    {k:"0171",a:"TOZ PEMBE",h:"#f4c2c2"},{k:"0172",a:"\u015eEKER PEMBE",h:"#ffc0cb"},
    {k:"0173",a:"LIGHT PEMBE",h:"#ffd6e0"},{k:"0201",a:"BEJ",h:"#d2b48c"},
    {k:"0202",a:"KOYU BEJ",h:"#c19a6b"},{k:"0221",a:"A\u00c7IK PUDRA",h:"#e8d5c4"},
    {k:"0220",a:"KOYU PUDRA",h:"#c9a090"},{k:"0240",a:"SOMON",h:"#fa8072"},
    {k:"0241",a:"CORAL",h:"#ff7f50"},{k:"0242",a:"KOYU CORAL",h:"#e55b3c"},
    {k:"0250",a:"TURUNCU",h:"#ff8c00"},{k:"0260",a:"KREM",h:"#fffdd0"},
    {k:"0261",a:"KOYU KREM",h:"#e8d8a0"},{k:"0263",a:"KREM FRUDA",h:"#f5e6c8"},
    {k:"0268",a:"KREM PAW PETROL",h:"#c8b89a"},{k:"0301",a:"KIRMIZI",h:"#dc143c"},
    {k:"0302",a:"B.KIRMIZI",h:"#c00000"},{k:"0303",a:"KOYU KIRMIZI",h:"#8b0000"},
    {k:"0400",a:"A\u00c7IK LAC\u0130VERT",h:"#4169e1"},{k:"0401",a:"LAC\u0130VERT",h:"#000080"},
    {k:"0402",a:"LAC\u0130VERT EL\u0130S TERL\u0130K",h:"#1a237e"},{k:"0449",a:"L\u0130LA",h:"#c8a2c8"},
    {k:"0450",a:"A\u00c7IK L\u0130LA",h:"#e6d0e6"},{k:"0451",a:"KOYU L\u0130LA",h:"#9b59b6"},
    {k:"0455",a:"MOR",h:"#800080"},{k:"0500",a:"A\u00c7IK SARI",h:"#fffacd"},
    {k:"0502",a:"HARDAL",h:"#d4a017"},{k:"0560",a:"FUSYA",h:"#ff00ff"},
    {k:"0677",a:"MAV\u0130",h:"#4fc3f7"},{k:"0678",a:"BUZ MAV\u0130",h:"#b3e5fc"},
    {k:"0680",a:"CYAN",h:"#00bcd4"},{k:"0683",a:"SAX MAV\u0130",h:"#4682b4"},
    {k:"0688",a:"BEBE MAV\u0130",h:"#aed6f1"},{k:"0700",a:"TURKUAZ",h:"#40e0d0"},
    {k:"0702",a:"PETROL YE\u015e\u0130L\u0130",h:"#2e8b57"},{k:"0721",a:"A\u00c7IK SU YE\u015e\u0130L",h:"#90ee90"},
    {k:"0722",a:"YOSUN YE\u015e\u0130L\u0130",h:"#6b8e23"},{k:"0726",a:"HAK\u0130 YE\u015e\u0130L",h:"#556b2f"},
    {k:"0730",a:"DUL MINT",h:"#98ff98"},{k:"0820",a:"L\u0130ME",h:"#32cd32"},
    {k:"0850",a:"POWDER PINK",h:"#ffb7c5"},{k:"0902",a:"V\u0130ZON",h:"#b5a99a"},
    {k:"0903",a:"V\u0130ZON (UGG)",h:"#a89080"},{k:"0929",a:"KOYU CAMEL",h:"#8b6914"},
    {k:"0930",a:"CAMEL",h:"#c19a6b"},{k:"0960",a:"KAHVERENG\u0130",h:"#8b4513"},
    {k:"0961",a:"S\u00dcTL\u00dc KAHVE",h:"#c8a27a"},{k:"0990",a:"BORDO",h:"#800020"}
  ];
  var HEX = {};
  ENJ_RENK_DB.forEach(function(r){ HEX[r.k] = r.h; });

  function parseVal(v) {
    if (!v) return null;
    var m = String(v).match(/^(\d{4})\s*-\s*(.+)$/);
    return m ? { k: m[1].trim(), a: m[2].trim() } : null;
  }

  function build(inp, opts) {
    opts = opts || {};
    if (inp.__renkV3 || !inp) return;
    if (inp.readOnly && inp.id !== 'esu-renk') return;
    inp.__renkV3 = true;

    var fld = inp.closest('.enj-fld') || inp.closest('.esu-renk-fld') || inp.parentElement;
    if (!fld) return;

    /* fld = position anchor (MEVCUT INPUT TYPE DEGISMIYOR) */
    fld.style.position = 'relative';
    fld.style.overflow = 'visible';

    /* Mevcut input'a minimum style (type, class, parent AYNEN) */
    inp.style.paddingLeft = '28px';
    inp.style.textOverflow = 'ellipsis';
    inp.style.overflow = 'hidden';
    inp.style.cursor = 'pointer';

    /* Swatch dot (absolute, grid etkilemez) */
    var sw = document.createElement('span');
    sw.className = 'enj-ab-renk-v3-sw empty';
    fld.appendChild(sw);

    /* Kartela dropdown (absolute, grid etkilemez) */
    var krt = document.createElement('div');
    krt.className = 'enj-ab-renk-v3-krt';
    krt.innerHTML =
      '<div class="enj-ab-renk-v3-sh"><input type="text" placeholder="Renk ara (ad veya kod)..." autocomplete="off"></div>' +
      '<div class="enj-ab-renk-v3-ls"></div>';
    fld.appendChild(krt);

    var ls = krt.querySelector('.enj-ab-renk-v3-ls');
    var si = krt.querySelector('.enj-ab-renk-v3-sh input');

    function render(f) {
      f = (f || '').toLocaleLowerCase('tr-TR').trim();
      var rows = ENJ_RENK_DB.filter(function(r) {
        return !f || r.a.toLocaleLowerCase('tr-TR').indexOf(f) >= 0 || r.k.indexOf(f) >= 0;
      });
      if (!rows.length) {
        ls.innerHTML = '<div style="padding:16px;text-align:center;color:#999;font-size:12px">Sonu\u00e7 yok</div>';
        return;
      }
      ls.innerHTML = rows.map(function(r) {
        return '<div class="enj-ab-renk-v3-r" data-k="'+r.k+'" data-a="'+r.a+'" data-h="'+r.h+'">' +
          '<span class="c" style="background:'+r.h+'"></span>' +
          '<span class="t"><b>'+r.a+'</b><small>'+r.k+'</small></span></div>';
      }).join('');
    }

    function updateSw() {
      var p = parseVal(inp.value);
      if (p && HEX[p.k]) {
        sw.style.background = HEX[p.k];
        sw.classList.remove('empty');
      } else {
        sw.style.background = '';
        sw.classList.add('empty');
      }
    }

    function openK() {
      document.querySelectorAll('.enj-ab-renk-v3-krt.open').forEach(function(x){ x.classList.remove('open'); });
      krt.classList.add('open');
      render('');
      si.value = '';
      setTimeout(function(){ try{si.focus();}catch(e){} }, 50);
    }
    function closeK() { krt.classList.remove('open'); }

    inp.addEventListener('click', function(e) {
      e.stopPropagation();
      krt.classList.contains('open') ? closeK() : openK();
    });

    krt.addEventListener('click', function(e) { e.stopPropagation(); });

    si.addEventListener('input', function() { render(si.value); });
    si.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeK(); });
    si.addEventListener('click', function(e) { e.stopPropagation(); });

    ls.addEventListener('click', function(e) {
      e.stopPropagation();
      var row = e.target.closest('.enj-ab-renk-v3-r');
      if (!row) return;
      inp.value = row.dataset.k + ' - ' + row.dataset.a;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      updateSw();
      closeK();
    });

    /* Init: mevcut persisted deger varsa swatch'i guncelle */
    updateSw();
  }

  window.ENJ_RENK_DB = ENJ_RENK_DB;
  window.enjRenkKartelaBuild = build;

  function initAll() {
    var a = document.getElementById('enj-renk-a');
    var b = document.getElementById('enj-renk-b');
    if (a && !a.readOnly) build(a);
    if (b && !b.readOnly) build(b);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
  setTimeout(initAll, 500);
  setTimeout(initAll, 1500);

  document.addEventListener('click', function(e) {
    if (!e.target.closest('.enj-ab-renk-v3-krt') &&
        !e.target.closest('#enj-renk-a') &&
        !e.target.closest('#enj-renk-b') &&
        !e.target.closest('#esu-renk')) {
      document.querySelectorAll('.enj-ab-renk-v3-krt.open').forEach(function(x){ x.classList.remove('open'); });
    }
  });

  var oldDl = document.getElementById('enj-renk-dl');
  if (oldDl) oldDl.remove();
})();
/* ===== ENJ_AB_RENK_KARTELA_V3 END ===== */
