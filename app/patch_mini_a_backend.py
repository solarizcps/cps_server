# ADIM A: alt_parcalar her bir alt icin prosesler[] + mesaj alani ekle
import io, sys, shutil, time

PATH = r'C:\cps_dev\modules\hedef\routes.py'
MARKER = '# === FAZ 4.7 MINI: alt parca proses listesi ==='

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM A zaten uygulanmis')
    sys.exit(0)

ANCHOR_A = "'alt_parcalar': alt_parcalar"
ANCHOR_B = "alt_parcalar=alt_parcalar"

if ANCHOR_A in src:
    anchor = ANCHOR_A
elif ANCHOR_B in src:
    anchor = ANCHOR_B
else:
    print('HATA: alt_parcalar response anchor bulunamadi')
    sys.exit(1)

ENRICH = '''        # === FAZ 4.7 MINI: alt parca proses listesi ===
        try:
            import sqlite3 as _sqlite_m47
            from config import Config as _Config_m47
            _con_m47 = _sqlite_m47.connect(_Config_m47.MOCK_DB_PATH)
            try:
                _con_m47.row_factory = _sqlite_m47.Row
                for _ap_m47 in alt_parcalar:
                    _alt_emir_m47 = str(_ap_m47.get('emir_no') or '')
                    if not _alt_emir_m47:
                        _ap_m47['prosesler'] = []
                        _ap_m47['mesaj'] = 'henuz sablon uygulanmadi'
                        continue
                    _rows_m47 = _con_m47.execute(\"\"\"
                        SELECT
                            ap.proses_adi AS proses_adi,
                            COALESCE(SUM(uk.miktar), 0) AS yapilan
                        FROM emir_alt_proses ap
                        LEFT JOIN uretim_kayit uk
                          ON CAST(uk.emir_no AS TEXT) = ap.emir_no
                         AND LOWER(TRIM(uk.proses_adi)) = LOWER(TRIM(ap.proses_adi))
                         AND uk.onay_durum IN ('onaylandi','bekliyor')
                        WHERE ap.emir_no = ?
                          AND ap.aktif = 1
                        GROUP BY ap.proses_adi, ap.siralama, ap.id
                        ORDER BY ap.siralama, ap.id
                    \"\"\", (_alt_emir_m47,)).fetchall()
                    _plist_m47 = []
                    for _r_m47 in _rows_m47:
                        _plist_m47.append({
                            'proses_adi': _r_m47['proses_adi'] or '',
                            'yapilan': int(_r_m47['yapilan'] or 0),
                        })
                    _ap_m47['prosesler'] = _plist_m47
                    if not _plist_m47:
                        _ap_m47['mesaj'] = 'henuz sablon uygulanmadi'
                    else:
                        _ap_m47['mesaj'] = None
            finally:
                _con_m47.close()
        except Exception as _e_m47:
            try:
                from flask import current_app as _ca_m47
                _ca_m47.logger.warning(
                    'FAZ 4.7 MINI alt_parca proses enrich hatasi: ' + str(_e_m47)[:200]
                )
            except Exception:
                pass
            for _ap_m47 in alt_parcalar:
                _ap_m47.setdefault('prosesler', [])
                _ap_m47.setdefault('mesaj', None)
        # === /FAZ 4.7 MINI ===
'''

idx = src.find(anchor)
line_start = src.rfind('\n', 0, idx) + 1
indent = ''
i = line_start
while i < len(src) and src[i] == ' ':
    indent += ' '
    i += 1

ENRICH_lines = ENRICH.split('\n')
if indent != '        ':
    new_lines = []
    for ln in ENRICH_lines:
        if ln.startswith('        '):
            new_lines.append(indent + ln[8:])
        else:
            new_lines.append(ln)
    ENRICH = '\n'.join(new_lines)

new_src = src[:line_start] + ENRICH + src[line_start:]

if new_src == src:
    print('HATA: insertion yapilamadi')
    sys.exit(1)

bak = PATH + '.bak_pre_mini_a_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: ADIM A enrichment eklendi (' + str(artis) + ' byte)')
print('Anchor: ' + anchor)