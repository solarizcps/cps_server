/* ===========================================================
 * usta.js — Faz 4.2 Usta Paneli JS
 * MES v2 API (port 5070) ile iletisim
 *
 * NOT: Bu ilk versiyon DEV_TOKEN kullanir (mevcut hedef.js gibi).
 *      Production'da CPS oturum -> MES v2 token koprusu yapilacak.
 * =========================================================== */

var MES_BASE = "http://127.0.0.1:5070";

// DEV_TOKEN: MES v2 her restart sonrasi yenilenmeli. Hedef.js ile ayni mantik.
// CPS oturum acmis kullanici icin gecerli token alma yontemi sonra eklenecek.
var DEV_TOKEN = "G2m56VXKRJXzUlW_UP3crxQwyDtGRiOm4Sy-NyESkNc";

var _ustaTabAktif = "isler";
var _aciKisleriYuklendi = false;
var _onaylariYuklendi = false;

// ============== HELPERS ==============

function $(id) {
    return document.getElementById(id);
}

function showError(elemId, msg) {
    var el = $(elemId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    setTimeout(function () { el.style.display = "none"; }, 5000);
}

function showSuccess(elemId, msg) {
    var el = $(elemId);
    if (!el) return;
    el.textContent = msg;
    el.style.display = "block";
    setTimeout(function () { el.style.display = "none"; }, 4000);
}

async function apiFetch(path, options) {
    options = options || {};
    options.headers = options.headers || {};
    options.headers["Authorization"] = "Bearer " + DEV_TOKEN;
    options.headers["Content-Type"] = "application/json";
    var url = MES_BASE + path;
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

function fmtDateSaat(tarih, saat) {
    if (!tarih && !saat) return "-";
    return (tarih || "") + (saat ? " " + saat : "");
}


// ============== TAB DEGISTIRME ==============

function setupTabs() {
    var tabs = document.querySelectorAll(".u-tab");
    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            var hedef = tab.dataset.tab;
            _ustaTabAktif = hedef;
            tabs.forEach(function (t) { t.classList.remove("active"); });
            tab.classList.add("active");
            document.querySelectorAll(".u-pane").forEach(function (p) {
                p.classList.remove("active");
            });
            var pane = $("pane-" + hedef);
            if (pane) pane.classList.add("active");

            // Lazy load
            if (hedef === "isler" && !_aciKisleriYuklendi) acikIsleriYukle();
            if (hedef === "onay" && !_onaylariYuklendi) onaylariYukle();
        });
    });
}


// ============== 1) ACIK ISLER ==============

async function acikIsleriYukle() {
    var liste = $("islerList");
    if (liste) liste.innerHTML = '<div class="u-empty">Yukleniyor...</div>';
    try {
        var r = await apiFetch("/api/v2/usta/acik-isler", { method: "GET" });
        if (r.status === 401) {
            showError("islerError", "Oturum gecersiz. Sayfayi yenile.");
            return;
        }
        if (r.status >= 400 || (r.data && r.data.ok === false)) {
            showError("islerError", r.data.mesaj || ("HTTP " + r.status));
            return;
        }
        var isler = r.data.isler || [];
        renderIsler(isler);
        _aciKisleriYuklendi = true;
        console.log("USTA/acik-isler", r.status, "kayit:", isler.length);
    } catch (e) {
        console.error("acik-isler fetch:", e);
        showError("islerError", "Sunucuya ulasilamadi: " + e.message);
    }
}

function renderIsler(isler) {
    var liste = $("islerList");
    if (!liste) return;
    liste.innerHTML = "";
    if (!isler || isler.length === 0) {
        liste.innerHTML = '<div class="u-empty">Aktif is yok. Yeni hedef plan eklenmesini bekleyin.</div>';
        return;
    }
    isler.forEach(function (is) {
        var hedef = is.hedef_adet || 0;
        var gercek = is.gerceklesen_adet || 0;
        var kalan = is.kalan_adet || 0;
        var yuzde = hedef > 0 ? Math.min(100, Math.round((gercek / hedef) * 100)) : 0;
        var card = document.createElement("div");
        card.className = "u-card";

        var durum = (is.durum || "ACIK").toLowerCase();
        var durumClass = durum === "tamamlandi" ? "onaylandi" : (durum === "iptal" ? "reddedildi" : "bekliyor");

        card.innerHTML =
            '<div class="u-card-header">' +
                '<div class="u-card-emir">' + escapeHtml(String(is.emir_no || "?")) + '</div>' +
                '<div class="u-card-durum ' + durumClass + '">' + escapeHtml(is.durum || "ACIK") + '</div>' +
            '</div>' +
            (is.model_adi ? '<div class="u-card-model">' + escapeHtml(is.model_adi) + '</div>' : '') +
            '<div class="u-card-info">' +
                '<span><span class="lbl">Proses:</span> ' + escapeHtml(is.proses_adi || is.proses_kodu || "-") + '</span>' +
                (is.renk_adi ? '<span><span class="lbl">Renk:</span> ' + escapeHtml(is.renk_adi) + '</span>' : '') +
                (is.beden_adi ? '<span><span class="lbl">Beden:</span> ' + escapeHtml(is.beden_adi) + '</span>' : '') +
            '</div>' +
            '<div class="u-card-info">' +
                '<span><span class="lbl">Hedef:</span> ' + hedef + '</span>' +
                '<span><span class="lbl">Yapilan:</span> ' + gercek + '</span>' +
                '<span><span class="lbl">Kalan:</span> <strong>' + kalan + '</strong></span>' +
            '</div>' +
            '<div class="u-card-progress">' +
                '<div class="u-card-progress-fill' + (yuzde >= 100 ? ' tam' : '') + '" style="width:' + yuzde + '%"></div>' +
            '</div>' +
            '<div class="u-card-actions">' +
                '<button class="u-btn u-btn-primary" onclick="formuDoldur(' + (is.emir_no || 0) + ',\'' + encodeURIComponent(is.proses_kodu || '') + '\',\'' + encodeURIComponent(is.proses_adi || '') + '\',\'' + encodeURIComponent(is.model_adi || '') + '\')">Veri Gir</button>' +
            '</div>';
        liste.appendChild(card);
    });
}

function formuDoldur(emirNo, prosesKodu, prosesAdi, modelAdi) {
    var pk = decodeURIComponent(prosesKodu);
    var pa = decodeURIComponent(prosesAdi);
    var ma = decodeURIComponent(modelAdi);
    if ($("emirNo")) $("emirNo").value = emirNo;
    if ($("prosesKodu")) {
        var sel = $("prosesKodu");
        var found = false;
        for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === pk) { sel.selectedIndex = i; found = true; break; }
        }
        if (!found && pk) {
            // Custom proses ekle
            var opt = document.createElement("option");
            opt.value = pk;
            opt.textContent = pa || pk;
            opt.selected = true;
            sel.appendChild(opt);
        }
    }
    if ($("prosesAdi")) $("prosesAdi").value = pa || pk;
    if ($("modelAdi")) $("modelAdi").value = ma;
    if ($("miktar")) $("miktar").focus();

    // GIRIS sekmesine gec
    var girisTab = document.querySelector('.u-tab[data-tab="giris"]');
    if (girisTab) girisTab.click();
}


// ============== 2) URETIM KAYDET ==============

async function uretimKaydet() {
    var emirNo = $("emirNo").value.trim();
    var prosesKodu = $("prosesKodu").value.trim();
    var prosesAdi = $("prosesAdi").value.trim();
    var miktar = $("miktar").value.trim();

    if (!emirNo) { showError("girisError", "Emir No zorunlu"); $("emirNo").focus(); return; }
    if (!prosesKodu) { showError("girisError", "Proses kodu zorunlu"); $("prosesKodu").focus(); return; }
    if (!prosesAdi) { showError("girisError", "Proses adi zorunlu"); $("prosesAdi").focus(); return; }
    if (!miktar || parseInt(miktar, 10) <= 0) { showError("girisError", "Miktar 0'dan buyuk olmali"); $("miktar").focus(); return; }

    var payload = {
        emir_no: parseInt(emirNo, 10),
        proses_kodu: prosesKodu,
        proses_adi: prosesAdi,
        miktar: parseInt(miktar, 10),
        model_adi: $("modelAdi").value.trim() || null,
        not: $("girisNot").value.trim() || null
    };

    var btn = $("girisKaydetBtn");
    if (btn) { btn.disabled = true; btn.textContent = "Kaydediliyor..."; }

    try {
        var r = await apiFetch("/api/v2/usta/uretim", {
            method: "POST",
            body: JSON.stringify(payload)
        });
        if (r.status >= 400 || (r.data && r.data.ok === false)) {
            showError("girisError", r.data.mesaj || ("HTTP " + r.status));
            return;
        }
        showSuccess("girisSuccess", "Kayit eklendi (id=" + r.data.uretim_kayit_id + "). Onay bekliyor.");
        formuTemizle();
        // Acik isleri ve onay listesini yenile
        _aciKisleriYuklendi = false;
        _onaylariYuklendi = false;
        guncelleOnayBadge();
        console.log("USTA/uretim", r.status, r.data);
    } catch (e) {
        console.error("uretim fetch:", e);
        showError("girisError", "Sunucuya ulasilamadi: " + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "KAYDET"; }
    }
}

function formuTemizle() {
    if ($("girisForm")) $("girisForm").reset();
}


// ============== 3) ONAY LISTESI ==============

async function onaylariYukle() {
    var liste = $("onayList");
    if (liste) liste.innerHTML = '<div class="u-empty">Yukleniyor...</div>';
    try {
        var r = await apiFetch("/api/v2/usta/bekleyen-onaylar", { method: "GET" });
        if (r.status >= 400 || (r.data && r.data.ok === false)) {
            showError("onayError", r.data.mesaj || ("HTTP " + r.status));
            return;
        }
        var kayitlar = r.data.kayitlar || [];
        renderOnaylar(kayitlar);
        _onaylariYuklendi = true;
        guncelleBadge(kayitlar.length);
        console.log("USTA/bekleyen-onaylar", r.status, "kayit:", kayitlar.length);
    } catch (e) {
        console.error("onaylar fetch:", e);
        showError("onayError", "Sunucuya ulasilamadi: " + e.message);
    }
}

function renderOnaylar(kayitlar) {
    var liste = $("onayList");
    if (!liste) return;
    liste.innerHTML = "";
    if (!kayitlar || kayitlar.length === 0) {
        liste.innerHTML = '<div class="u-empty">Bekleyen onay yok.</div>';
        return;
    }
    kayitlar.forEach(function (k) {
        var card = document.createElement("div");
        card.className = "u-card";
        card.innerHTML =
            '<div class="u-card-header">' +
                '<div class="u-card-emir">' + escapeHtml(String(k.emir_no || "?")) + '</div>' +
                '<div class="u-card-durum bekliyor">BEKLIYOR</div>' +
            '</div>' +
            (k.model_adi ? '<div class="u-card-model">' + escapeHtml(k.model_adi) + '</div>' : '') +
            '<div class="u-card-info">' +
                '<span><span class="lbl">Personel:</span> ' + escapeHtml(k.personel_ad || "-") + '</span>' +
                '<span><span class="lbl">Proses:</span> ' + escapeHtml(k.proses_adi || k.proses_kodu || "-") + '</span>' +
                '<span><span class="lbl">Miktar:</span> <strong>' + (k.miktar || 0) + '</strong></span>' +
            '</div>' +
            '<div class="u-card-info">' +
                '<span><span class="lbl">Tarih:</span> ' + escapeHtml(fmtDateSaat(k.tarih, k.saat)) + '</span>' +
            '</div>' +
            '<div class="u-card-actions">' +
                '<button class="u-btn u-btn-success" onclick="onayVer(' + k.id + ',\'onayla\')">✓ ONAYLA</button>' +
                '<button class="u-btn u-btn-danger" onclick="onayVer(' + k.id + ',\'reddet\')">✗ REDDET</button>' +
            '</div>';
        liste.appendChild(card);
    });
}


// ============== 4) ONAY VER ==============

async function onayVer(uretimId, karar) {
    if (!confirm(karar === "onayla" ? "Bu kaydi onaylamak istiyor musun?" : "Bu kaydi reddetmek istiyor musun?")) return;

    try {
        var r = await apiFetch("/api/v2/usta/onay", {
            method: "POST",
            body: JSON.stringify({
                uretim_kayit_id: uretimId,
                karar: karar,
                not: ""
            })
        });
        if (r.status >= 400 || (r.data && r.data.ok === false)) {
            showError("onayError", r.data.mesaj || ("HTTP " + r.status));
            return;
        }
        // Listeyi yenile
        _onaylariYuklendi = false;
        _aciKisleriYuklendi = false;
        await onaylariYukle();
        console.log("USTA/onay", r.status, r.data);
    } catch (e) {
        console.error("onay fetch:", e);
        showError("onayError", "Sunucuya ulasilamadi: " + e.message);
    }
}


// ============== BADGE ==============

function guncelleBadge(n) {
    var b = $("onayBadge");
    if (!b) return;
    if (n > 0) {
        b.textContent = String(n);
        b.classList.add("active");
    } else {
        b.classList.remove("active");
    }
}

async function guncelleOnayBadge() {
    try {
        var r = await apiFetch("/api/v2/usta/bekleyen-onaylar", { method: "GET" });
        if (r.data && r.data.kayit_sayisi !== undefined) {
            guncelleBadge(r.data.kayit_sayisi);
        }
    } catch (e) {
        // sessizce gec
    }
}


// ============== HTML ESCAPE ==============

function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}


// ============== STARTUP ==============

document.addEventListener("DOMContentLoaded", function () {
    setupTabs();

    // Buton event'leri
    if ($("islerYenileBtn")) $("islerYenileBtn").addEventListener("click", function () {
        _aciKisleriYuklendi = false;
        acikIsleriYukle();
    });
    if ($("onayYenileBtn")) $("onayYenileBtn").addEventListener("click", function () {
        _onaylariYuklendi = false;
        onaylariYukle();
    });
    if ($("girisKaydetBtn")) $("girisKaydetBtn").addEventListener("click", uretimKaydet);
    if ($("girisIptalBtn")) $("girisIptalBtn").addEventListener("click", formuTemizle);

    // Ilk yukleme
    acikIsleriYukle();
    guncelleOnayBadge();
});
