# -*- coding: utf-8 -*-
"""apply_enjeksiyon_sidebar.py - FAZ 4

base.html sidebar'a Enjeksiyon Takip linkini ekler.

Iki patch noktasi (mevcut Jinja conditional'larina DOKUNMAZ):
  1. LINK: Mevcut URETIM grubunun ICINE Hedef Paneli'nin altina
     (Yonetim + admin icin)
  2. PLAN: Mevcut URETIM bloga DIS, Planlama-only mini URETIM grubu
     (Planlama icin sadece bu link)

Markerlar:
  ENJ_F4_LINK_START/END        - link bloga
  ENJ_F4_PLANLAMA_START/END    - planlama grubuna

Yedek    : base.html.YEDEK_FAZ_ENJ_F4_<ts>
Atomic   : .tmp + line-ending check + os.replace
Idempotent: marker bazli skip
Rollback : --rollback ile en son yedekten geri yukle

Kullanim:
  py apply_enjeksiyon_sidebar.py             # apply
  py apply_enjeksiyon_sidebar.py --dry-run   # dry-run
  py apply_enjeksiyon_sidebar.py --rollback  # rollback
"""
import os
import sys
import shutil
import glob
from datetime import datetime

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_HTML = os.path.join(BASE_DIR, 'templates', 'base.html')

LINK_START = '<!-- ENJ_F4_LINK_START -->'
LINK_END   = '<!-- ENJ_F4_LINK_END -->'
PLAN_START = '<!-- ENJ_F4_PLANLAMA_START -->'
PLAN_END   = '<!-- ENJ_F4_PLANLAMA_END -->'

LINK_ANCHOR = '<span class="sl">Hedef Paneli</span>'
CLOSE_A     = '</a>'
PLAN_ANCHOR = '<!-- ============ PLANLAMA ============ -->'

NL = '\r\n'

LINK_LINES = [
    '',
    '        ' + LINK_START,
    "        <a href=\"/enjeksiyon/\" class=\"si {% if '/enjeksiyon' in rp %}active{% endif %}\" title=\"Enjeksiyon Takip\">",
    '          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v4"/><path d="M11 10v4"/><path d="M15 10v4"/></svg></span>',
    '          <span class="sl">Enjeksiyon Takip</span>',
    '        </a>',
    '        ' + LINK_END,
    '',
]
LINK_BLOCK = NL.join(LINK_LINES)

PLAN_LINES = [
    '',
    '      ' + PLAN_START,
    "      {% if g_user.RolAd == 'Planlama' %}",
    "      <div class=\"sn-sec sn-toggle{% if aktif_grup == 'uretim' %} acik{% endif %}\" data-grup=\"uretim\">",
    "        <span class=\"sn-arrow\">{% if aktif_grup == 'uretim' %}\u25BC{% else %}\u25BA{% endif %}</span>",
    '        <svg class="sn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v4"/><path d="M11 10v4"/><path d="M15 10v4"/></svg>',
    '        <span class="sn-baslik">\u00DCretim</span>',
    '        <span class="sn-count">1</span>',
    '      </div>',
    "      <div class=\"sn-grup{% if aktif_grup != 'uretim' %} kapali{% endif %}\" data-grup=\"uretim\">",
    "        <a href=\"/enjeksiyon/\" class=\"si {% if '/enjeksiyon' in rp %}active{% endif %}\" title=\"Enjeksiyon Takip\">",
    '          <span class="si-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10v4"/><path d="M11 10v4"/><path d="M15 10v4"/></svg></span>',
    '          <span class="sl">Enjeksiyon Takip</span>',
    '        </a>',
    '      </div>',
    '      {% endif %}',
    '      ' + PLAN_END,
    '',
]
PLAN_BLOCK = NL.join(PLAN_LINES)


def le_detect(s):
    crlf = s.count('\r\n')
    lf = s.count('\n') - crlf
    return 'CRLF' if crlf > lf else 'LF'


def yedek_al():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    y = BASE_HTML + '.YEDEK_FAZ_ENJ_F4_' + ts
    shutil.copy2(BASE_HTML, y)
    return y


def en_son_yedek():
    ys = sorted(glob.glob(BASE_HTML + '.YEDEK_FAZ_ENJ_F4_*'))
    return ys[-1] if ys else None


def patch_uygula(dry_run=False):
    print('=' * 60)
    print('apply_enjeksiyon_sidebar.py - F4')
    print('=' * 60)
    print('Mod      : ' + ('DRY-RUN' if dry_run else 'APPLY'))

    with open(BASE_HTML, 'r', encoding='utf-8', newline='') as f:
        content = f.read()

    print('\n[1/7] base.html okunuyor...')
    print('       Line ending : ' + le_detect(content))
    print('       Boyut       : ' + str(len(content.encode('utf-8'))) + ' byte')

    print('\n[2/7] Idempotency kontrol...')
    has_l = LINK_START in content
    has_p = PLAN_START in content
    if has_l and has_p:
        print('  [SKIP] Patch zaten uygulanmis (her iki marker da var)')
        return
    if has_l or has_p:
        print('  [HATA] Kismi patch tespit edildi:')
        print('         LINK marker : ' + ('VAR' if has_l else 'YOK'))
        print('         PLAN marker : ' + ('VAR' if has_p else 'YOK'))
        print('         Once --rollback yapip yeniden deneyin.')
        sys.exit(1)
    print('  [OK] Temiz dosya - patch uygulanabilir')

    print('\n[3/7] Anchor satirlari araniyor...')

    if LINK_ANCHOR not in content:
        print('  [HATA] LINK anchor yok: ' + LINK_ANCHOR)
        sys.exit(1)
    n_link = content.count(LINK_ANCHOR)
    if n_link > 1:
        print('  [HATA] LINK anchor coklu: ' + str(n_link) + ' match')
        sys.exit(1)
    link_anchor_pos = content.index(LINK_ANCHOR)
    close_a_pos = content.index(CLOSE_A, link_anchor_pos)
    link_insert = close_a_pos + len(CLOSE_A)
    print('  [OK] LINK anchor (Hedef Paneli sl)  @ ' + str(link_anchor_pos))
    print('       Sonraki </a>                   @ ' + str(close_a_pos))
    print('       LINK insert pos                @ ' + str(link_insert))

    if PLAN_ANCHOR not in content:
        print('  [HATA] PLAN anchor yok: ' + PLAN_ANCHOR)
        sys.exit(1)
    n_plan = content.count(PLAN_ANCHOR)
    if n_plan > 1:
        print('  [HATA] PLAN anchor coklu: ' + str(n_plan) + ' match')
        sys.exit(1)
    plan_insert = content.index(PLAN_ANCHOR)
    print('  [OK] PLAN anchor (PLANLAMA basligi) @ ' + str(plan_insert))

    if dry_run:
        print('\n[DRY-RUN] Patch hesaplandi ama uygulanmadi. Cikiliyor.')
        print('  Eklenecek LINK satir : ' + str(len(LINK_LINES)))
        print('  Eklenecek PLAN satir : ' + str(len(PLAN_LINES)))
        print('  Tahmini boyut farki  : +' + str(len(LINK_BLOCK.encode('utf-8')) + len(PLAN_BLOCK.encode('utf-8'))) + ' byte')
        return

    print('\n[4/7] Yedek aliniyor...')
    yedek = yedek_al()
    print('       ' + os.path.basename(yedek))

    print('\n[5/7] Patch hesaplaniyor (PLAN once, sonra LINK)...')
    yeni = content[:plan_insert] + PLAN_BLOCK + content[plan_insert:]
    yeni = yeni[:link_insert] + LINK_BLOCK + yeni[link_insert:]

    tmp = BASE_HTML + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(yeni)
    yeni_b = os.path.getsize(tmp)
    eski_b = os.path.getsize(BASE_HTML)
    print('       .tmp yazildi: ' + str(yeni_b) + ' byte (+' + str(yeni_b - eski_b) + ')')

    with open(tmp, 'r', encoding='utf-8', newline='') as f:
        tc = f.read()

    if not (LINK_START in tc and LINK_END in tc and PLAN_START in tc and PLAN_END in tc):
        os.remove(tmp)
        print('  [HATA] Marker dogrulama (tmp) basarisiz.')
        sys.exit(1)

    if le_detect(tc) != le_detect(content):
        os.remove(tmp)
        print('  [HATA] Line ending degisti: ' + le_detect(content) + ' -> ' + le_detect(tc))
        sys.exit(1)
    print('       [OK] 4 marker dogrulandi, line ending korundu (' + le_detect(tc) + ')')

    os.replace(tmp, BASE_HTML)
    print('       [OK] os.replace tamamlandi')

    print('\n[6/7] Son dogrulama...')
    with open(BASE_HTML, 'r', encoding='utf-8', newline='') as f:
        son = f.read()
    ok = (LINK_START in son and LINK_END in son and PLAN_START in son and PLAN_END in son)
    if ok:
        print('  [OK] Tum 4 marker mevcut, patch tamamlandi.')
        print('       Yedek dosyasi: ' + os.path.basename(yedek))
    else:
        print('  [HATA] Marker dogrulama (son) basarisiz!')
        sys.exit(1)

    print('\n[7/7] Ozet:')
    print('  LINK eklenen satir  : ' + str(len(LINK_LINES)))
    print('  PLAN eklenen satir  : ' + str(len(PLAN_LINES)))
    print('  Toplam boyut farki  : +' + str(yeni_b - eski_b) + ' byte')

    print('\n' + '=' * 60)
    print('[TAMAM] F4 patch basarili.')
    print('  Sonraki adim: Task Scheduler restart + sidebar gorsel kontrol')
    print('=' * 60)


def rollback():
    print('=' * 60)
    print('apply_enjeksiyon_sidebar.py - F4 ROLLBACK')
    print('=' * 60)
    y = en_son_yedek()
    if not y:
        print('[HATA] FAZ_ENJ_F4 yedegi yok.')
        sys.exit(1)
    print('[ROLLBACK] Geri yukleniyor: ' + os.path.basename(y))
    shutil.copy2(y, BASE_HTML)
    with open(BASE_HTML, 'r', encoding='utf-8', newline='') as f:
        c = f.read()
    if LINK_START in c or PLAN_START in c:
        print('[HATA] Marker hala var - rollback basarisiz!')
        sys.exit(1)
    print('[OK] Rollback tamamlandi. base.html eski haline donduruldu.')


def main():
    if '--rollback' in sys.argv:
        rollback()
    elif '--dry-run' in sys.argv:
        patch_uygula(dry_run=True)
    else:
        patch_uygula(dry_run=False)


if __name__ == '__main__':
    main()
