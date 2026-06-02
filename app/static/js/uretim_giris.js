/* ===========================================================
 * uretim_giris.js - Faz 4.3.D2
 *
 * Personel uretim giris ekrani - JS islevi
 * Mevcut hedef.js paterni ile uyumlu
 *
 * Kapsam (D2):
 *   1. Sekme degisimi (URETIM GIR / GECMISIM)
 *   2. Emir sorgu - GET /api/v2/personel/emir/<no>
 *   3. Emir bilgisi karti doldur
 *   4. Proses listesi - GET /api/v2/personel/emir/<no>/prosesler
 *   5. Proses sec (radio)
 *   6. Validation (proses + miktar > 0)
 *   7. KAYDET - POST /api/v2/usta/uretim
 *   8. Toast (success/error)
 *
 * D3'e biraktigimiz:
 *   - Gecmisim veri yukleme
 *   - PWA manifest
 *   - Push
 *
 * NOT: DEV_TOKEN sabit. MES v2 restart sonrasi elle yenile.
 * =========================================================== */

var MES_BASE = "/uretim/proxy";

// DEV_TOKEN: hedef.js ile ayni olmali. MES v2 restart sonrasi yenile.
var DEV_TOKEN = "LNNdAkMMESTUPFPI-N3gr1FZ33-LpdVTCs26WrRySYU";

// State
var _aktifEmirNo = null;
var _aktifEmirBilgi = null;
var _aktifProses = null;  // { kod, ad }
var _seciliRadioId = null;


// ============== HELPERS ==============

function $(id) { return document.getElementById(id); }

function _esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function showError(elemId, msg, ms) {
    var el = $(elemId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    el.classList.remove("ug-mesaj-success");
    if (ms) setTimeout(function () { el.style.display = "none"; }, ms);
}

function showSuccess(elemId, msg, ms) {
    var el = $(elemId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    el.classList.add("ug-mesaj-success");
    if (ms) setTimeout(function () { el.style.display = "none"; }, ms);
}

async function _ugApi(path, options) {
    options = options || {};
    options.credentials = "include";
    options.headers = options.headers || {};
    options.headers["Accept"] = "application/json";
    if (options.method === "POST" || options.method === "PUT") {
        options.headers["Content-Type"] = "application/json";
    }
    // Mutlak path = CPS dogrudan endpoint. Eski /api/v2/* path'ler MES_BASE prefix ile gider.
    var url = path.startsWith("/uretim/") || path.startsWith("/hedef/") ? path : (MES_BASE + path);
    var resp = await fetch(url, options);
    var text = await resp.text();
    var data;
    try {
        data = text ? JSON.parse(text) : {};
    } catch (e) {
        data = { ok: false, hata: "parse_hatasi", mesaj: text.slice(0, 200) };
    }
    return { status: resp.status, data: data };
}


// ============== SEKME DEGISTIRME ==============

function setupTabs() {
    var tabs = document.querySelectorAll(".ug-tab");
    var panes = document.querySelectorAll(".ug-pane");

    // Default: ilk tab aktif, diger pane'leri gizle (DOM ile garanti)
    tabs.forEach(function (t) { t.classList.remove("active"); });
    panes.forEach(function (p) { p.classList.remove("active"); p.style.display = "none"; });
    var ilkTab = document.querySelector('.ug-tab[data-tab="gir"]');
    var ilkPane = $("ug-pane-gir");
    if (ilkTab) ilkTab.classList.add("active");
    if (ilkPane) {
        ilkPane.classList.add("active");
        ilkPane.style.display = "block";
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            var hedef = tab.dataset.tab;
            tabs.forEach(function (t) { t.classList.remove("active"); });
            tab.classList.add("active");
            panes.forEach(function (p) {
                p.classList.remove("active");
                p.style.display = "none";
            });
            var pane = $("ug-pane-" + hedef);
            if (pane) {
                pane.classList.add("active");
                pane.style.display = "block";
            }
        });
    });
}


// ============== EMIR SORGU ==============

async function emirSorgula() {
    var inp = $("emirNo");
    if (!inp) return;
    var emirNoStr = (inp.value || "").trim();
    if (!emirNoStr) {
        showError("ugError", "Emir No giriniz", 4000);
        inp.focus();
        return;
    }
    var emirNo = parseInt(emirNoStr, 10);
    if (isNaN(emirNo) || emirNo <= 0) {
        showError("ugError", "Gecerli bir emir no giriniz", 4000);
        inp.focus();
        return;
    }

    // Loading state
    var btn = $("emirSorgulaBtn");
    if (btn) { btn.disabled = true; btn.textContent = "..."; }
    var emptyDiv = $("ugEmptyGir");
    if (emptyDiv) emptyDiv.textContent = "Sorgulaniyor...";

    try {
        // 1) Emir bilgisi
        var r = await _ugApi("/uretim/emir/" + emirNo, { method: "GET" });
        if (r.status === 401) {
            showError("ugError", "Oturum gecersiz, sayfayi yenile.", 5000);
            return;
        }
        if (r.status >= 400 || (r.data && r.data.ok === false)) {
            showError("ugError", r.data.mesaj || ("HTTP " + r.status), 5000);
            return;
        }
        _aktifEmirBilgi = r.data;
        _aktifEmirNo = emirNo;
        renderEmirBilgi(r.data);

        // 2) Prosesler - mock_data.db'den (emir_alt_proses tablosu)
        var rp = await _ugApi("/uretim/emir/" + emirNo + "/prosesler", { method: "GET" });
        if (rp.status >= 400) {
            showError("ugError", "Proses listesi alinamadi (HTTP " + rp.status + ")", 5000);
            return;
        }
        if (rp.data && rp.data.ok === false) {
            // Alt proses tanimlanmamis - form pasif, mesaj
            showError("ugError", rp.data.message || "Bu emire alt proses yok", 8000);
            renderProsesler([]);
            // Form'u gosterme
            if ($("ugForm")) $("ugForm").style.display = "none";
            return;
        }
        renderProsesler((rp.data && rp.data.prosesler) || []);

        // 3) Form gorunur
        if ($("ugForm")) $("ugForm").style.display = "block";
        if (emptyDiv) emptyDiv.style.display = "none";

        // Miktara odakla
        var miktarInput = $("ugMiktar");
        if (miktarInput) miktarInput.focus();

        console.log("EMIR_SORGU OK", emirNo, r.data);
    } catch (e) {
        console.error("emirSorgula:", e);
        showError("ugError", "Sunucuya ulasilamadi: " + e.message, 5000);
        if (emptyDiv) emptyDiv.textContent = "Emir No yazip sorgulayin";
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = "&#128269;"; }
    }
}

function renderEmirBilgi(data) {
    var card = $("emirBilgi");
    if (!card) return;
    card.style.display = "block";

    // Emir no + plan rozeti
    if ($("emirBilgiNo")) $("emirBilgiNo").textContent = "E." + (data.emir_no || "?");
    var rozet = $("emirBilgiPlanRozet");
    if (rozet) {
        if (data.plan_var_mi) {
            rozet.textContent = "PLAN VAR";
            rozet.className = "ug-emir-rozet plan";
        } else {
            rozet.textContent = "PLAN YOK";
            rozet.className = "ug-emir-rozet yok";
        }
    }

    // Model
    if ($("emirBilgiModel")) {
        $("emirBilgiModel").textContent = data.model_adi || "(model bilinmiyor)";
    }

    // Snapshot (siparis, musteri, renk, beden)
    var snap = $("emirBilgiSnapshot");
    if (snap) {
        snap.innerHTML = "";
        var s = data.snapshot || {};
        if (s.siparis_no)  snap.appendChild(_chip("Sip: " + s.siparis_no));
        if (s.musteri_adi) snap.appendChild(_chip("Mst: " + s.musteri_adi));
        if (s.renk_adi)    snap.appendChild(_chip("Renk: " + s.renk_adi));
        if (s.beden_adi)   snap.appendChild(_chip("Beden: " + s.beden_adi));
    }

    // Stats
    var hedef = data.hedef_adet || 0;
    var gercek = data.gerceklesen_adet || 0;
    var kalan = data.kalan_adet || 0;
    if ($("emirBilgiHedef"))  $("emirBilgiHedef").textContent = hedef;
    if ($("emirBilgiGercek")) $("emirBilgiGercek").textContent = gercek;
    if ($("emirBilgiKalan"))  $("emirBilgiKalan").textContent = kalan;

    // Progress
    var yuzde = hedef > 0 ? Math.min(100, Math.round((gercek / hedef) * 100)) : 0;
    var prog = $("emirBilgiProgress");
    if (prog) {
        prog.style.width = yuzde + "%";
        if (yuzde >= 100) prog.classList.add("tam");
        else prog.classList.remove("tam");
    }

    // Faz 4.3.D2: Miktar input'a max + kalan uyari
    var miktarInp = $("ugMiktar");
    var uyari = $("kalanUyari");
    if (miktarInp) {
        if (data.plan_var_mi && hedef > 0) {
            miktarInp.max = kalan;
            if (kalan === 0) {
                miktarInp.disabled = true;
                if (uyari) {
                    uyari.textContent = "Bu emir/proses TAMAMLANDI - giris kapali";
                    uyari.className = "ug-kalan-uyari ug-kalan-tamam";
                    uyari.style.display = "block";
                }
            } else {
                miktarInp.disabled = false;
                if (uyari) {
                    uyari.textContent = "Maksimum " + kalan + " cift girebilirsin";
                    uyari.className = "ug-kalan-uyari ug-kalan-info";
                    uyari.style.display = "block";
                }
            }
        } else {
            miktarInp.disabled = false;
            miktarInp.removeAttribute("max");
            if (uyari) uyari.style.display = "none";
        }
    }
}

function _chip(text) {
    var s = document.createElement("span");
    s.textContent = text;
    return s;
}

function renderProsesler(prosesler) {
    var liste = $("prosesListe");
    var card = $("prosesSec");
    if (!liste || !card) return;
    card.style.display = "block";
    liste.innerHTML = "";

    if (!prosesler || prosesler.length === 0) {
        liste.innerHTML = '<div class="ug-empty">Proses bulunamadi</div>';
        return;
    }

    prosesler.forEach(function (p, i) {
        var radioId = "prosesRadio_" + i;
        var lbl = document.createElement("label");
        lbl.className = "ug-proses-item";
        lbl.htmlFor = radioId;
        lbl.dataset.kod = p.kod;
        lbl.dataset.ad = p.ad;

        var inp = document.createElement("input");
        inp.type = "radio";
        inp.name = "uretimProses";
        inp.id = radioId;
        inp.value = p.kod;
        inp.addEventListener("change", function () {
            // Diger label'lardan 'secili' class kaldir
            document.querySelectorAll(".ug-proses-item").forEach(function (el) {
                el.classList.remove("secili");
            });
            lbl.classList.add("secili");
            _aktifProses = { kod: p.kod, ad: p.ad };
            _seciliRadioId = radioId;
        });
        lbl.appendChild(inp);

        var ad = document.createElement("span");
        ad.className = "ug-proses-ad";
        ad.textContent = p.ad;
        lbl.appendChild(ad);

        if (p.kaynak === "plan" && p.hedef > 0) {
            var info = document.createElement("span");
            info.className = "ug-proses-info";
            info.textContent = "hedef: " + p.hedef;
            lbl.appendChild(info);
        } else if (p.kaynak === "default") {
            var info2 = document.createElement("span");
            info2.className = "ug-proses-info";
            info2.textContent = "default";
            lbl.appendChild(info2);
        }

        liste.appendChild(lbl);
    });

    _aktifProses = null;
    _seciliRadioId = null;
}


// ============== KAYDET ==============

async function uretimKaydet() {
    if (!_aktifEmirNo) {
        showError("ugError", "Once emir sorgulayin", 4000);
        return;
    }
    if (!_aktifProses) {
        showError("ugError", "Proses seciniz", 4000);
        return;
    }
    var miktarStr = ($("ugMiktar") || {}).value || "";
    miktarStr = miktarStr.trim();
    if (!miktarStr) {
        showError("ugError", "Miktar giriniz", 4000);
        if ($("ugMiktar")) $("ugMiktar").focus();
        return;
    }
    var miktar = parseInt(miktarStr, 10);
    if (isNaN(miktar) || miktar <= 0) {
        showError("ugError", "Miktar pozitif sayi olmali", 4000);
        if ($("ugMiktar")) $("ugMiktar").focus();
        return;
    }

    // Faz 4.3.D2: Frontend kalan kontrol (plan varsa)
    if (_aktifEmirBilgi && _aktifEmirBilgi.plan_var_mi) {
        var kalanFE = _aktifEmirBilgi.kalan_adet || 0;
        if (kalanFE === 0) {
            showError("ugError", "Bu emir/proses tamamlandi, giris kabul edilmiyor", 4500);
            return;
        }
        if (miktar > kalanFE) {
            showError("ugError", "Maksimum " + kalanFE + " cift girebilirsin (girilen: " + miktar + ")", 4500);
            if ($("ugMiktar")) $("ugMiktar").focus();
            return;
        }
    }

    var notu = ($("ugNot") || {}).value || "";
    notu = notu.trim();

    var payload = {
        emir_no: _aktifEmirNo,
        proses_kodu: _aktifProses.kod,
        proses_adi: _aktifProses.ad,
        miktar: miktar,
        not: notu || null,
    };

    // Model adi varsa ekle (snapshot icin)
    if (_aktifEmirBilgi && _aktifEmirBilgi.model_adi) {
        payload.model_adi = _aktifEmirBilgi.model_adi;
    }

    var btn = $("ugKaydetBtn");
    if (btn) { btn.disabled = true; btn.textContent = "Kaydediliyor..."; }

    try {
        var r = await _ugApi("/uretim/kaydet", {
            method: "POST",
            body: JSON.stringify(payload),
        });

        if (r.status >= 400 || (r.data && r.data.ok === false)) {
            showError("ugError", r.data.mesaj || ("HTTP " + r.status), 5000);
            return;
        }

        showSuccess("ugSuccess",
            "Kayit eklendi (id=" + (r.data.uretim_kayit_id || "?") + "). Onay bekliyor.",
            5000);

        // Form temizle (emir bilgisi karti kalir, miktar/not bosalir, proses secimi kalkar)
        if ($("ugMiktar")) $("ugMiktar").value = "";
        if ($("ugNot"))    $("ugNot").value = "";
        document.querySelectorAll('input[name="uretimProses"]').forEach(function (r) {
            r.checked = false;
        });
        document.querySelectorAll(".ug-proses-item").forEach(function (el) {
            el.classList.remove("secili");
        });
        _aktifProses = null;
        _seciliRadioId = null;

        console.log("URETIM_KAYIT OK", r.data);

        // Bilgi kartini yenile (gerceklesen artmis olabilir, bekleyen artar)
        if (_aktifEmirNo) {
            try {
                var rr = await _ugApi("/uretim/emir/" + _aktifEmirNo, { method: "GET" });
                if (rr.data && rr.data.ok !== false) {
                    _aktifEmirBilgi = rr.data;
                    renderEmirBilgi(rr.data);
                }
            } catch (e) { /* sessiz */ }
        }

    } catch (e) {
        console.error("uretimKaydet:", e);
        showError("ugError", "Sunucuya ulasilamadi: " + e.message, 5000);
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = "&#128190; KAYDET"; }
    }
}


// ============== FORM TEMIZLE ==============

function formuTemizle() {
    if ($("emirNo"))  $("emirNo").value = "";
    if ($("ugMiktar")) $("ugMiktar").value = "";
    if ($("ugNot"))    $("ugNot").value = "";

    if ($("emirBilgi"))  $("emirBilgi").style.display = "none";
    if ($("prosesSec"))  $("prosesSec").style.display = "none";
    if ($("ugForm"))     $("ugForm").style.display = "none";

    var emptyDiv = $("ugEmptyGir");
    if (emptyDiv) {
        emptyDiv.style.display = "block";
        emptyDiv.innerHTML = "&#9757; Emir No yazip sorgulayin";
    }

    _aktifEmirNo = null;
    _aktifEmirBilgi = null;
    _aktifProses = null;
    _seciliRadioId = null;

    if ($("emirNo")) $("emirNo").focus();
}


// ============== STARTUP ==============

document.addEventListener("DOMContentLoaded", function () {
    setupTabs();

    // Emir sorgu butonu
    if ($("emirSorgulaBtn")) {
        $("emirSorgulaBtn").addEventListener("click", emirSorgula);
    }

    // Emir input enter ile sorgula
    if ($("emirNo")) {
        $("emirNo").addEventListener("keydown", function (e) {
            if (e.key === "Enter") emirSorgula();
        });
    }

    // Kaydet
    if ($("ugKaydetBtn")) {
        $("ugKaydetBtn").addEventListener("click", uretimKaydet);
    }

    // Temizle
    if ($("ugTemizleBtn")) {
        $("ugTemizleBtn").addEventListener("click", formuTemizle);
    }

    // Hidden cards (initial state)
    if ($("emirBilgi"))  $("emirBilgi").style.display = "none";
    if ($("prosesSec"))  $("prosesSec").style.display = "none";
    if ($("ugForm"))     $("ugForm").style.display = "none";
});



/* ====================================================================
   CPS LOCAL — /uretim/ GECMISIM yukleyici
   - Tab 'gecmis' tiklaninca lazy-load
   - gecmisYenileBtn ile manuel yenileme
   - Endpoint: GET /uretim/gecmisim
   ==================================================================== */
(function () {
    'use strict';

    function _ugEsc(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function _ugTarihSaat(k) {
        var t = k.tarih || '';
        var s = k.saat || '';
        if (t && s) return t + ' ' + s;
        return t || s || (k.olusturma || '');
    }

    function _ugDurumStil(durum) {
        if (durum === 'onaylandi') return { renk: '#10b981', txt: 'ONAYLANDI' };
        if (durum === 'reddedildi') return { renk: '#dc2626', txt: 'REDDEDİLDİ' };
        return { renk: '#f59e0b', txt: 'BEKLİYOR' };
    }

    function _ugRenderGecmisim(rows) {
        var listEl = document.getElementById('gecmisListe');
        if (!listEl) return;
        if (!rows || rows.length === 0) {
            listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#888;">Henüz üretim kaydın yok.</div>';
            return;
        }
        var html = '';
        for (var i = 0; i < rows.length; i++) {
            var k = rows[i];
            var ds = _ugDurumStil(k.onay_durum);
            var ustaNotEk = k.usta_not
                ? '<div style="margin-top:8px; padding:8px 10px; background:rgba(220,38,38,0.06); border-radius:6px; font-size:13px; line-height:1.4;"><strong style="color:#dc2626;">Usta notu:</strong> ' + _ugEsc(k.usta_not) + '</div>'
                : '';
            var notEk = k.not_metin
                ? '<div style="margin-top:6px; font-size:12px; color:#666; font-style:italic;">Not: ' + _ugEsc(k.not_metin) + '</div>'
                : '';
            var onayZamanEk = (k.onay_durum !== 'bekliyor' && k.onay_tarihi)
                ? '<div style="margin-top:4px; font-size:11px; color:#888; font-family:monospace;">' + _ugEsc(k.onay_tarihi) + (k.usta_ad ? ' • ' + _ugEsc(k.usta_ad) : '') + '</div>'
                : '';
            html +=
                '<div class="ug-gecmis-card" style="background:#fff; border-radius:12px; padding:14px 16px; margin-bottom:10px; box-shadow:0 2px 6px rgba(0,0,0,0.05); border-left:4px solid ' + ds.renk + ';">' +
                    '<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; gap:12px;">' +
                        '<div style="min-width:0;">' +
                            '<div style="font-weight:700; font-size:15px;">E.' + _ugEsc(k.emir_no) + '</div>' +
                            '<div style="font-size:12px; color:#666; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + _ugEsc(k.model_kod || '') + '</div>' +
                        '</div>' +
                        '<div style="background:' + ds.renk + '; color:#fff; padding:4px 10px; border-radius:12px; font-size:11px; font-weight:700; letter-spacing:0.5px; white-space:nowrap;">' + ds.txt + '</div>' +
                    '</div>' +
                    '<div style="display:grid; grid-template-columns:1fr 1fr; gap:8px 16px; font-size:13px;">' +
                        '<div><span style="color:#888;">Proses:</span> <strong>' + _ugEsc(k.proses_adi || '-') + '</strong></div>' +
                        '<div><span style="color:#888;">Miktar:</span> <strong>' + _ugEsc(k.miktar) + '</strong> çift</div>' +
                        '<div style="grid-column:1/-1; color:#888; font-family:monospace; font-size:12px;">' + _ugEsc(_ugTarihSaat(k)) + '</div>' +
                    '</div>' +
                    notEk + ustaNotEk + onayZamanEk +
                '</div>';
        }
        listEl.innerHTML = html;
    }

    function _ugGecmisimYukle() {
        var listEl = document.getElementById('gecmisListe');
        var errEl = document.getElementById('gecmisError');
        if (errEl) errEl.style.display = 'none';
        if (listEl) {
            listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#888;">Yükleniyor...</div>';
        }
        fetch('/uretim/gecmisim?limit=100', {
            method: 'GET',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        })
            .then(function (resp) {
                return resp.text().then(function (t) {
                    var data;
                    try { data = JSON.parse(t); } catch (_) { data = null; }
                    return { status: resp.status, data: data };
                });
            })
            .then(function (r) {
                if (r.status >= 400 || !r.data || r.data.ok === false) {
                    if (listEl) {
                        listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#dc2626;">Geçmiş yüklenemedi.</div>';
                    }
                    window._gecmisimYuklendi = false;
                    return;
                }
                var kayitlar = (r.data && r.data.kayitlar) || [];
                _ugRenderGecmisim(kayitlar);
                window._gecmisimYuklendi = true;
                console.log('CPS/uretim/gecmisim', r.status, kayitlar.length);
            })
            .catch(function (e) {
                console.error('gecmisim fetch:', e);
                if (listEl) {
                    listEl.innerHTML = '<div class="ug-empty" style="padding:32px; text-align:center; color:#dc2626;">Sunucuya ulaşılamadı.</div>';
                }
                window._gecmisimYuklendi = false;
            });
    }

    // Globale ac (button onclick veya disaridan cagri icin)
    window.gecmisimYukle = _ugGecmisimYukle;
    window.renderGecmisim = _ugRenderGecmisim;

    document.addEventListener('DOMContentLoaded', function () {
        // GECMISIM tab'i tiklaninca lazy-load
        var gt = document.querySelector('.ug-tab[data-tab="gecmis"]');
        if (gt) {
            gt.addEventListener('click', function () {
                if (!window._gecmisimYuklendi) {
                    _ugGecmisimYukle();
                }
            });
        }

        // Yenile butonu
        var rb = document.getElementById('gecmisYenileBtn');
        if (rb) {
            rb.addEventListener('click', function () {
                window._gecmisimYuklendi = false;
                _ugGecmisimYukle();
            });
        }
    });

    console.log('[CPS LOCAL] /uretim/ gecmisim yukleyici hazir.');
})();
