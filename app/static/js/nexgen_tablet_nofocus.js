/**
 * FAZ-NEXGEN-TUM-TABLET-AUTOFOCUS-KAPAT-1
 * Tablet sayfa/modal açılışında input autofocus ve sanal klavye engeli.
 * Kullanıcı input'a elle dokunursa focus serbesttir.
 */
(function () {
  'use strict';

  function isField(el) {
    if (!el || el === document.body || el === document.documentElement) return false;
    var tag = (el.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function blurActive() {
    var ae = document.activeElement;
    if (isField(ae) && typeof ae.blur === 'function') {
      try { ae.blur(); } catch (e) { /* ignore */ }
    }
  }

  function onReady() {
    blurActive();
    // Bazı tarayıcılar autofocus'u DOMContentLoaded sonrası uygular
    setTimeout(blurActive, 0);
    setTimeout(blurActive, 100);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onReady);
  } else {
    onReady();
  }
  window.addEventListener('pageshow', function () { blurActive(); });
  window.addEventListener('load', function () { blurActive(); });

  // Kart / seçenek dokunuşunda açık klavyeyi kapat
  document.addEventListener('pointerdown', function (e) {
    var t = e.target;
    if (!t) return;
    if (isField(t)) return;
    if (t.closest && t.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (!t.closest) return;
    if (t.closest('a, button, label, [role="button"], .ag-card, .rm-sekme, .rm-fb, .nxt-kart, [onclick]')) {
      blurActive();
    }
  }, true);
})();
