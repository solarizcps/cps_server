# Patch 7A: _resolve_target_emir helper'i routes.py'ye ekle (sablon_uygula fonksiyonundan ONCE)
import io, sys, os

PATH = r'C:\cps_dev\modules\hedef\routes.py'

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if 'def _resolve_target_emir' in src:
    print('SKIP: _resolve_target_emir zaten var')
    sys.exit(0)

ANCHOR = "# --- 7) Sablon uygula (emir -> emir_alt_proses) ---"
if ANCHOR not in src:
    print('HATA: anchor bulunamadi: ' + ANCHOR)
    sys.exit(1)

HELPER = '''# === FAZ 4.7 SABLON ROUTING (atki/govde alt emire dagit) ===
def _normalize_tr_local(s):
    if not s:
        return ''
    s = s.upper()
    repl = [('\\u0130','I'),('\\u0131','I'),('\\u011e','G'),('\\u011f','G'),
            ('\\u00dc','U'),('\\u00fc','U'),('\\u015e','S'),('\\u015f','S'),
            ('\\u00d6','O'),('\\u00f6','O'),('\\u00c7','C'),('\\u00e7','C')]
    for a,b in repl:
        s = s.replace(a,b)
    return s


def _kategori_sablon_adi(sablon_adi):
    """Sablon adindan kategori cikar. None = belirsiz, ana emirde kal."""
    s = _normalize_tr_local(sablon_adi or '')
    if 'ATKI' in s:  return 'ATKI'
    if 'GOVDE' in s: return 'GOVDE'
    if 'TABAN' in s: return 'TABAN'
    if 'SAYA' in s:  return 'SAYA'
    return None


def _kategori_alt_emir(model_kod, model_adi):
    """Alt emrin model bilgisinden kategori cikar."""
    mk = _normalize_tr_local(model_kod or '')
    ma = _normalize_tr_local(model_adi or '')
    text = mk + ' ' + ma
    if 'ATKI' in text:  return 'ATKI'
    if 'GOVDE' in text: return 'GOVDE'
    if 'TABAN' in text: return 'TABAN'
    if 'SAYA' in text:  return 'SAYA'
    return None


def _resolve_target_emir(ana_emir_no, sablon_adi):
    """Sablon hangi emire uygulanmali?
    Donen: (gercek_emir_no_str, sebep_str)
    """
    kategori = _kategori_sablon_adi(sablon_adi)
    if not kategori:
        return (str(ana_emir_no), 'ana:sablon_belirsiz')

    try:
        from modules.common import korgun as _kk
        sonuc = _kk.get_alt_emirler(ana_emir_no)
    except Exception as e:
        return (str(ana_emir_no), 'ana:helper_hata:' + str(e)[:60])

    if not sonuc.get('ok'):
        return (str(ana_emir_no), 'ana:korgun_hata')

    alt_list = sonuc.get('alt_emirler') or []
    if not alt_list:
        return (str(ana_emir_no), 'ana:alt_yok')

    for alt in alt_list:
        alt_kat = _kategori_alt_emir(alt.get('model_kod'), alt.get('model_adi'))
        if alt_kat == kategori:
            return (str(alt['emir_no']), 'alt:' + kategori + ':' + str(alt['emir_no']))

    return (str(ana_emir_no), 'ana:eslesme_yok')


'''

new_src = src.replace(ANCHOR, HELPER + ANCHOR, 1)

if new_src == src:
    print('HATA: replace yapilamadi')
    sys.exit(1)

# yedek
import shutil, time
bak = PATH + '.bak_pre_routing_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

print('OK: helper eklendi (' + str(len(new_src) - len(src)) + ' byte artis)')