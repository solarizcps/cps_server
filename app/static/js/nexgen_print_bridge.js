/**
 * nexgen_print_bridge.js
 * ======================
 * NexGen MODÜL-05 ortak baskı yardımcısı.
 *
 * Tüm etiket basan ekranlar (MODÜL-01, MODÜL-04, tablet_etiket_arge)
 * bu tek dosyayı kullanır. Tekrarlanan _m5DogrudanYazdir / _m5JobPoll
 * kodu artık burada.
 *
 * Kullanım:
 *   NexGenPrint.yazdir(etiketId, kopya, mesajFn, {onBasari, onHata})
 *
 * mesajFn(txt, tip) — sayfaya özel mesaj kutusu fonksiyonu
 *   tip: 'bilgi' | 'ok' | 'hata'
 *
 * Callbacks (opsiyonel):
 *   onBasari() — PRINTED sonrası çağrılır
 *   onHata(msg) — FAILED veya timeout sonrası
 *
 * Android vs Windows kararı bu dosyada verilir:
 *   Android  → nexgenprint:// URL scheme → NexGen Print Bridge APK
 *   Windows  → Print Agent polling (mevcut davranış korunur)
 */

(function(global) {
  'use strict';

  /* ── Android tespiti ──────────────────────────────────────────────── */
  function _isAndroid() {
    return /android/i.test(navigator.userAgent);
  }

  /* ── Android overlay yönetimi ────────────────────────────────────── */
  /* tablet_etiket_arge.html'de overlay var; diğer sayfalarda yoktur.
     Yoksa inline mesaj (mesajFn) kullanılır.                          */
  function _overlayVar() {
    return !!document.getElementById('print-overlay');
  }

  function _overlayGoster(mesaj, spinner) {
    if (!_overlayVar()) return;
    document.getElementById('print-overlay-mesaj').textContent = mesaj;
    document.getElementById('print-overlay-spinner').style.display = spinner ? 'block' : 'none';
    var ikon = document.getElementById('print-overlay-ikon');
    ikon.style.display = spinner ? 'none' : 'block';
    document.getElementById('print-overlay').style.display = 'flex';
  }

  function _overlayGizle() {
    if (!_overlayVar()) return;
    document.getElementById('print-overlay').style.display = 'none';
  }

  function _overlayBasari() {
    if (!_overlayVar()) return;
    document.getElementById('print-overlay-spinner').style.display = 'none';
    var ikon = document.getElementById('print-overlay-ikon');
    ikon.textContent  = '✓';
    ikon.className    = 'poi-ikon poi-ok';
    ikon.style.display = 'block';
    document.getElementById('print-overlay-mesaj').textContent = 'Etiket basıldı';
    var kapat = document.getElementById('print-overlay-kapat');
    if (kapat) kapat.style.display = 'inline-block';
  }

  function _overlayHata(mesaj) {
    if (!_overlayVar()) return;
    document.getElementById('print-overlay-spinner').style.display = 'none';
    var ikon = document.getElementById('print-overlay-ikon');
    ikon.textContent  = '✗';
    ikon.className    = 'poi-ikon poi-hata';
    ikon.style.display = 'block';
    document.getElementById('print-overlay-mesaj').textContent = mesaj;
    var kapat = document.getElementById('print-overlay-kapat');
    if (kapat) kapat.style.display = 'inline-block';
  }

  /* ── Mesaj gönderici (overlay yoksa inline kutu) ─────────────────── */
  function _mesaj(mesajFn, txt, tip) {
    if (_overlayVar()) {
      if (tip === 'ok')   { _overlayBasari(); }
      else if (tip === 'hata') { _overlayHata(txt); }
      else                { _overlayGoster(txt, true); }
    } else if (typeof mesajFn === 'function') {
      mesajFn(txt, tip);
    }
  }

  /* ── Windows/Agent polling ───────────────────────────────────────── */
  function _jobPoll(jobId, deneme, mesajFn, opts) {
    var MAKS = 30;  /* 30 × 2 sn = 60 sn */
    if (deneme >= MAKS) {
      var zMsg = 'Zaman aşımı — yazıcı kapalı veya bağlantı kesildi';
      _mesaj(mesajFn, zMsg, 'hata');
      if (opts.onHata) opts.onHata(zMsg);
      return;
    }
    setTimeout(function() {
      fetch('/nexgen/api/tablet/arge/print-job/' + jobId + '/durum')
        .then(function(r) { return r.json(); })
        .then(function(d) {
          if (!d.ok) {
            var e = 'Durum sorgulanamadı';
            _mesaj(mesajFn, e, 'hata');
            if (opts.onHata) opts.onHata(e);
            return;
          }
          if (d.status === 'PRINTED') {
            _mesaj(mesajFn, 'Etiket basıldı ✓', 'ok');
            if (opts.onBasari) opts.onBasari();
          } else if (d.status === 'FAILED') {
            var h = d.hata || '';
            var msg;
            if (h.indexOf('COM') !== -1 || h.indexOf('Serial') !== -1 || h.indexOf('port') !== -1) {
              msg = 'Yazıcıya bağlanılamadı. Kablo veya Bluetooth bağlantısını kontrol edin.';
            } else if (h.indexOf('Bluetooth') !== -1 || h.indexOf('bluetooth') !== -1) {
              msg = 'Bluetooth bağlantısı kurulamadı';
            } else if (h.indexOf('Agent') !== -1 || h.indexOf('agent') !== -1) {
              msg = 'Print Agent çalışmıyor. Lütfen yetkiliyle iletişime geçin.';
            } else {
              msg = 'Baskı başarısız. Lütfen tekrar deneyin.';
            }
            _mesaj(mesajFn, msg, 'hata');
            if (opts.onHata) opts.onHata(msg);
          } else {
            _jobPoll(jobId, deneme + 1, mesajFn, opts);
          }
        })
        .catch(function() {
          _jobPoll(jobId, deneme + 1, mesajFn, opts);
        });
    }, 2000);
  }

  /* ── Android akışı: nexgenprint:// + polling ─────────────────────── */
  function _androidYazdir(jobId, token, mesajFn, opts) {
    var scheme = 'nexgenprint://print?job_id=' + jobId +
                 '&token=' + encodeURIComponent(token);

    /* iframe ile URL scheme'i tetikle (sayfa navigasyonu olmadan) */
    var iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    iframe.src = scheme;
    document.body.appendChild(iframe);

    /* 2 saniye bekle — sayfa background'a geçtiyse APK açıldı demektir */
    setTimeout(function() {
      if (document.hidden) {
        /* APK açıldı — polling başlat */
        _mesaj(mesajFn, 'Baskı devam ediyor...', 'bilgi');
        _jobPoll(jobId, 0, mesajFn, opts);
      } else {
        /* APK kurulu değil — kuyrukta bırak, Windows Agent dener veya uyar */
        _mesaj(
          mesajFn,
          'NexGen Print Bridge uygulaması bulunamadı.\n' +
          'Ana ekrandan kurulum talimatlarını alın.\n' +
          'Baskı kuyruğa alındı (İş #' + jobId + ').',
          'hata'
        );
        if (opts.onHata) opts.onHata('APK bulunamadı');
      }
    }, 2000);
  }

  /* ══ ANA PUBLIC API ══════════════════════════════════════════════════
   *
   * NexGenPrint.yazdir(etiketId, kopya, mesajFn, opts)
   *
   * @param {number}   etiketId  nexgen_arge_etiket.id
   * @param {number}   kopya     1–5 arası kopya sayısı
   * @param {function} mesajFn   m5Mesaj(txt, tip) benzeri sayfa fonksiyonu
   * @param {object}   opts      { onBasari, onHata }  — opsiyonel
   * ═════════════════════════════════════════════════════════════════ */
  function yazdir(etiketId, kopya, mesajFn, opts) {
    opts = opts || {};
    kopya = kopya || 1;

    _mesaj(mesajFn, 'Baskı hazırlanıyor...', 'bilgi');

    fetch('/nexgen/api/tablet/arge/etiket/' + etiketId + '/dogrudan-yazdir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ copies: kopya })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.ok) {
        var e = d.hata || 'Baskı başlatılamadı';
        _mesaj(mesajFn, 'Hata: ' + e, 'hata');
        if (opts.onHata) opts.onHata(e);
        return;
      }

      var jobId = d.job_id;
      var token = d.print_token;

      if (_isAndroid() && token) {
        /* Android: nexgenprint:// URL scheme ile APK'ya gönder */
        _mesaj(mesajFn, 'Yazıcıya bağlanıyor...', 'bilgi');
        _androidYazdir(jobId, token, mesajFn, opts);
      } else {
        /* Windows / masaüstü: Print Agent polling */
        _mesaj(mesajFn, 'Baskı gönderildi, bekleniyor...', 'bilgi');
        _jobPoll(jobId, 0, mesajFn, opts);
      }
    })
    .catch(function() {
      var e = 'Sunucuya bağlanılamadı';
      _mesaj(mesajFn, e, 'hata');
      if (opts.onHata) opts.onHata(e);
    });
  }

  /* Global nesne */
  global.NexGenPrint = { yazdir: yazdir };

}(window));
