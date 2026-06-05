/* ===== CANLI SAHA (5055) READ-ONLY BRIDGE ===== */
/* Vanilla JS - jQuery yok, izole - LEGACY_5055 verisini gosterir */

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const elGun       = $('cs-gun');
  const elPersonel  = $('cs-personel');
  const elEmir      = $('cs-emir');
  const elYenile    = $('cs-yenile');
  const elStatus    = $('cs-status');
  const elHata      = $('cs-hata');
  const elOzet      = $('cs-ozet');
  const elTbody     = $('cs-tbody');

  function escHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function onayRozet(d) {
    const safe = escHtml(d || '');
    if (d === 'onaylandi')  return '<span class="cs-onay-onayli">Onayli</span>';
    if (d === 'bekliyor')   return '<span class="cs-onay-bekliyor">Bekliyor</span>';
    if (d === 'reddedildi') return '<span class="cs-onay-reddedildi">Reddedildi</span>';
    return safe;
  }

  function setStatus(txt, renk) {
    elStatus.textContent = txt || '';
    elStatus.style.color = renk || '#718096';
  }

  function hataGoster(mesaj) {
    elHata.textContent = '⚠ ' + mesaj;
    elHata.style.display = 'block';
  }

  function hataGizle() {
    elHata.style.display = 'none';
  }

  function ozetGoster(o, kayitSayisi) {
    if (!o) {
      elOzet.style.display = 'none';
      return;
    }
    $('cs-ozet-kayit').textContent       = kayitSayisi;
    $('cs-ozet-miktar').textContent      = (o.toplam_miktar || 0).toLocaleString('tr-TR');
    $('cs-ozet-onayli').textContent      = o.onayli || 0;
    $('cs-ozet-bekleyen').textContent    = o.bekleyen || 0;
    $('cs-ozet-reddedilen').textContent  = o.reddedilen || 0;
    elOzet.style.display = 'grid';
  }

  function tabloGoster(kayitlar) {
    if (!kayitlar || kayitlar.length === 0) {
      elTbody.innerHTML = '<tr><td colspan="10" class="cs-yukleniyor">Kayit yok.</td></tr>';
      return;
    }

    const rows = kayitlar.map(k => {
      const model = k.model_adi || k.model_kod || '';
      return `<tr>
        <td>${escHtml(k.tarih)}</td>
        <td>${escHtml(k.saat)}</td>
        <td><strong>${escHtml(k.emir_no)}</strong></td>
        <td>${escHtml(model)}</td>
        <td>${escHtml(k.proses_adi)}</td>
        <td>${escHtml(k.personel_ad)}</td>
        <td class="cs-r">${escHtml((k.miktar || 0).toLocaleString('tr-TR'))}</td>
        <td>${onayRozet(k.onay_durum)}</td>
        <td>${escHtml(k.usta_ad)}</td>
        <td><span class="cs-kaynak-rozet">${escHtml(k.kaynak)}</span></td>
      </tr>`;
    });

    elTbody.innerHTML = rows.join('');
  }

  async function veriYukle() {
    hataGizle();
    elYenile.disabled = true;
    setStatus('Yukleniyor...', '#3182ce');
    elTbody.innerHTML = '<tr><td colspan="10" class="cs-yukleniyor">Yukleniyor...</td></tr>';

    const params = new URLSearchParams();
    params.set('gun', elGun.value || '30');
    if (elPersonel.value.trim()) params.set('personel', elPersonel.value.trim());
    if (elEmir.value.trim())     params.set('emir_no', elEmir.value.trim());

    try {
      const r = await fetch('/canli-saha/data?' + params.toString(), {
        method: 'GET',
        credentials: 'same-origin'
      });

      if (!r.ok) {
        throw new Error('HTTP ' + r.status);
      }

      const data = await r.json();

      if (!data.ok) {
        hataGoster(data.hata || '5055 erisilemiyor');
        ozetGoster(null, 0);
        elTbody.innerHTML = '<tr><td colspan="10" class="cs-yukleniyor">Veri alinamadi (yukaridaki uyariya bakiniz).</td></tr>';
        setStatus('Hata', '#c53030');
        return;
      }

      ozetGoster(data.ozet, data.kayit_sayisi);
      tabloGoster(data.kayitlar);

      const ts = new Date().toLocaleTimeString('tr-TR');
      const limitNote = (data.kayit_sayisi >= (data.max_limit || 2000))
        ? ` (LIMIT: ${data.max_limit})`
        : '';
      setStatus(`✓ ${data.kayit_sayisi} kayit · ${ts}${limitNote}`, '#38a169');

    } catch (err) {
      hataGoster('Baglanti hatasi: ' + err.message);
      setStatus('Hata', '#c53030');
      elTbody.innerHTML = '<tr><td colspan="10" class="cs-yukleniyor">Hata olustu.</td></tr>';
    } finally {
      elYenile.disabled = false;
    }
  }

  // Event listeners
  elYenile.addEventListener('click', veriYukle);
  elGun.addEventListener('change', veriYukle);

  // Enter ile arama
  [elPersonel, elEmir].forEach(el => {
    el.addEventListener('keypress', e => {
      if (e.key === 'Enter') veriYukle();
    });
  });

  // Ilk yukleme
  veriYukle();

})();