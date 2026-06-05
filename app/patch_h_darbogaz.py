# ADIM H: Darbogaz hesabi - yeni yapilan/kalan/yuzde alanlari
# - ATKI/GOVDE tamamlanan = son siralanan proses miktari (emir_alt_proses.siralama MAX)
# - MAMUL tamamlanan = emir_alt_proses varsa siralama MAX, yoksa Korgun proses_kod numerik MAX
# - YAPILAN_DARBOGAZ = min(ATKI, GOVDE, MAMUL)
# - Eski alanlar (yapilan, kalan, yuzde) korunacak
import io, sys, shutil, time

PATH = r'C:\cps_dev\modules\hedef\routes.py'
MARKER = '# === FAZ 4.7 DARBOGAZ ==='

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM H zaten uygulanmis')
    sys.exit(0)

# Anchor: FAZ 4.7 MINI bloku bittikten sonra, return jsonify oncesi
# `# === /FAZ 4.7 MINI ===` satirini ariyoruz
ANCHOR = '# === /FAZ 4.7 MINI ==='
anchor_idx = src.find(ANCHOR)
if anchor_idx < 0:
    print('HATA: FAZ 4.7 MINI bitis marker bulunamadi')
    sys.exit(1)

# Anchor satirinin sonuna git (newline'a kadar)
anchor_end = src.find('\n', anchor_idx) + 1

# Indent: anchor satirinin basinda kac space?
line_start = src.rfind('\n', 0, anchor_idx) + 1
indent = ''
i = line_start
while i < len(src) and src[i] == ' ':
    indent += ' '
    i += 1

print('Anchor: # === /FAZ 4.7 MINI === sonrasina ekleniyor')
print('Indent: ' + str(len(indent)) + ' bosluk')

# Yeni hesap blok
HESAP_TEMPLATE = '''
# === FAZ 4.7 DARBOGAZ ===
# YAPILAN_DARBOGAZ = min(ATKI tamamlanan, GOVDE tamamlanan, MAMUL tamamlanan)
# - ATKI/GOVDE: emir_alt_proses son siralanan proses (siralama MAX) - uretim_kayit toplam
# - MAMUL: emir_alt_proses varsa siralama MAX, yoksa Korgun ana_prosesleri proses_kod MAX
# - Sablon yoksa = 0 (sipariş ilerleyemez)
try:
    import sqlite3 as _sqlite_h47
    from config import Config as _Config_h47

    def _h47_son_proses_miktari(emir_no_str):
        """emir_alt_proses siralama MAX olan prosesin uretim_kayit toplam miktari.
        Donen: (yapilan_int, son_proses_adi) veya (None, None) sablon yoksa.
        """
        _con_h47_l = _sqlite_h47.connect(_Config_h47.MOCK_DB_PATH)
        try:
            _row_h47 = _con_h47_l.execute("""
                SELECT proses_adi, siralama, id
                FROM emir_alt_proses
                WHERE emir_no = ? AND aktif = 1
                ORDER BY siralama DESC, id DESC
                LIMIT 1
            """, (emir_no_str,)).fetchone()
            if not _row_h47:
                return (None, None)
            _son_adi_h47 = _row_h47[0]
            _yp_h47 = _con_h47_l.execute("""
                SELECT COALESCE(SUM(miktar), 0)
                FROM uretim_kayit
                WHERE CAST(emir_no AS TEXT) = ?
                  AND LOWER(TRIM(proses_adi)) = LOWER(TRIM(?))
                  AND onay_durum IN ('onaylandi','bekliyor')
            """, (emir_no_str, _son_adi_h47)).fetchone()
            return (int(_yp_h47[0] or 0), _son_adi_h47)
        finally:
            _con_h47_l.close()

    # ATKI/GOVDE: alt_parcalar uzerinden tara
    _atki_tamamlanan_h47 = 0
    _govde_tamamlanan_h47 = 0
    _atki_var_h47 = False
    _govde_var_h47 = False
    for _ap_h47 in alt_parcalar:
        _kat_h47 = (_ap_h47.get('kategori') or '').strip().lower()
        _emir_h47 = str(_ap_h47.get('emir_no') or '')
        if not _emir_h47:
            continue
        _yp_h47, _adi_h47 = _h47_son_proses_miktari(_emir_h47)
        if _kat_h47 in ('atki', 'atk\u0131'):
            _atki_var_h47 = True
            _atki_tamamlanan_h47 = _yp_h47 or 0
            _ap_h47['son_proses_adi'] = _adi_h47
            _ap_h47['tamamlanan'] = _atki_tamamlanan_h47
        elif _kat_h47 in ('govde', 'g\u00f6vde'):
            _govde_var_h47 = True
            _govde_tamamlanan_h47 = _yp_h47 or 0
            _ap_h47['son_proses_adi'] = _adi_h47
            _ap_h47['tamamlanan'] = _govde_tamamlanan_h47

    # MAMUL: emir_alt_proses ana emir icin var mi?
    _mamul_yp_h47, _mamul_adi_h47 = _h47_son_proses_miktari(str(emir_no))
    _mamul_kaynak_h47 = 'sablon'
    if _mamul_yp_h47 is None:
        # Fallback: Korgun ana_prosesleri proses_kod numerik MAX
        _mamul_kaynak_h47 = 'korgun_max'
        if ana_prosesleri:
            def _kod_int(p):
                k = str(p.get('proses_kod') or '')
                try:
                    return int(k) if k.isdigit() else -1
                except Exception:
                    return -1
            _en_son_h47 = max(ana_prosesleri, key=_kod_int)
            if _kod_int(_en_son_h47) >= 0:
                _mamul_yp_h47 = int(_en_son_h47.get('yapilan') or 0)
                _mamul_adi_h47 = _en_son_h47.get('proses_adi')
            else:
                _mamul_yp_h47 = 0
                _mamul_adi_h47 = None
        else:
            _mamul_yp_h47 = 0
            _mamul_adi_h47 = None
    _mamul_tamamlanan_h47 = _mamul_yp_h47 or 0

    # YAPILAN_DARBOGAZ = min(ATKI, GOVDE, MAMUL)
    # Eger ATKI/GOVDE alt parcasi yok ise -> sadece MAMUL
    _adaylar_h47 = []
    _adaylar_h47.append(('MAMUL', _mamul_tamamlanan_h47))
    if _atki_var_h47:
        _adaylar_h47.append(('ATKI', _atki_tamamlanan_h47))
    if _govde_var_h47:
        _adaylar_h47.append(('GOVDE', _govde_tamamlanan_h47))

    _en_dusuk_h47 = min(_adaylar_h47, key=lambda x: x[1])
    _yapilan_darbogaz_h47 = int(_en_dusuk_h47[1])
    _darbogaz_kategori_h47 = _en_dusuk_h47[0]
    _kalan_darbogaz_h47 = max(0, hedef_toplam - _yapilan_darbogaz_h47)
    _yuzde_darbogaz_h47 = round((_yapilan_darbogaz_h47 / hedef_toplam) * 100, 1) if hedef_toplam > 0 else 0.0

    _darbogaz_data_h47 = {
        'yapilan_darbogaz': _yapilan_darbogaz_h47,
        'kalan_darbogaz': _kalan_darbogaz_h47,
        'yuzde_darbogaz': _yuzde_darbogaz_h47,
        'darbogaz_kategori': _darbogaz_kategori_h47,
        'darbogaz_detay': {
            'atki_tamamlanan': _atki_tamamlanan_h47 if _atki_var_h47 else None,
            'govde_tamamlanan': _govde_tamamlanan_h47 if _govde_var_h47 else None,
            'mamul_tamamlanan': _mamul_tamamlanan_h47,
            'mamul_son_proses': _mamul_adi_h47,
            'mamul_kaynak': _mamul_kaynak_h47,
        }
    }
except Exception as _e_h47:
    try:
        from flask import current_app as _ca_h47
        _ca_h47.logger.warning(
            'FAZ 4.7 DARBOGAZ hesap hatasi: ' + str(_e_h47)[:200]
        )
    except Exception:
        pass
    _darbogaz_data_h47 = {
        'yapilan_darbogaz': None,
        'kalan_darbogaz': None,
        'yuzde_darbogaz': None,
        'darbogaz_kategori': None,
        'darbogaz_detay': None,
    }
# === /FAZ 4.7 DARBOGAZ ===
'''

# Indent uygula
hesap_lines = HESAP_TEMPLATE.split('\n')
indented_h = []
for ln in hesap_lines:
    if ln == '':
        indented_h.append('')
    else:
        indented_h.append(indent + ln)
HESAP = '\n'.join(indented_h) + '\n'

# Anchor sonrasina ekle
new_src = src[:anchor_end] + HESAP + src[anchor_end:]

if new_src == src:
    print('HATA: hesap blok eklenemedi')
    sys.exit(1)

# Simdi return jsonify icine yeni alanlari ekle
RETURN_OLD = """        'siparisler': ozet.get('siparisler', []),
        'ana_prosesleri': ana_prosesleri,
        'alt_parcalar': alt_parcalar,
        'takildi': takildi,
    })"""

RETURN_NEW = """        'siparisler': ozet.get('siparisler', []),
        'ana_prosesleri': ana_prosesleri,
        'alt_parcalar': alt_parcalar,
        'takildi': takildi,
        'yapilan_darbogaz': _darbogaz_data_h47.get('yapilan_darbogaz'),
        'kalan_darbogaz': _darbogaz_data_h47.get('kalan_darbogaz'),
        'yuzde_darbogaz': _darbogaz_data_h47.get('yuzde_darbogaz'),
        'darbogaz_kategori': _darbogaz_data_h47.get('darbogaz_kategori'),
        'darbogaz_detay': _darbogaz_data_h47.get('darbogaz_detay'),
    })"""

if RETURN_OLD not in new_src:
    print('HATA: return jsonify alanlari bulunamadi')
    sys.exit(1)

new_src2 = new_src.replace(RETURN_OLD, RETURN_NEW, 1)

# Yedek
bak = PATH + '.bak_pre_h_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(new_src2)

artis = len(new_src2) - len(src)
print('OK: ADIM H darbogaz hesabi eklendi (' + str(artis) + ' byte)')