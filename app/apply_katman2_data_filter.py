# -*- coding: utf-8 -*-
"""
apply_katman2_data_filter.py
KATMAN 2 - /hedef/ DATA YETKI FILTRESI (v2 - CRLF-aware)
========================================================
Hedef       : modules/hedef/routes.py
Mudahaleler : 4 (helper + 3 endpoint guard/filter)
Idempotent  : Evet (BEGIN/END marker kontrolu)
Backup      : routes.py.YEDEK_KATMAN2_DATA_FILTER_<timestamp>
Rollback    : Otomatik (hata durumunda)

CRLF stratejisi:
  - read: ham bytes oku, line ending'i tespit et, LF'e normalize
  - replace: hep LF uzerinde calis
  - write: orijinal line ending'i geri uygula (CRLF kalsin)
"""
import os
import sys
import shutil
import datetime
import py_compile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROUTES_PATH = os.path.join(SCRIPT_DIR, 'modules', 'hedef', 'routes.py')
MASTER_MARKER = '[KATMAN_2_DATA_FILTER:BEGIN]'

# ---------------- PATCH ICERIKLERI (LF ile) ----------------

HELPER_KODU = """\
# === [KATMAN_2_DATA_FILTER:BEGIN] ===
def _katman2_izinli_emirler():
    \"\"\"
    Session sahibi 'usta' ise:
      - proses_usta_atama'dan kullanicinin atandigi proses_kod'lari cek
      - uretim_kayit'tan o proseslerde kaydi olan emir_no'lari don
    Diger roller icin None doner (filtre uygulanmaz).
    \"\"\"
    import sqlite3 as _sq_k2
    u = session.get('kullanici') or {}
    tip = session.get('kullanici_tip')

    if tip != 'usta':
        return None

    kullanici_adi = u.get('KullaniciAdi')
    if not kullanici_adi:
        return set()

    try:
        db_path = _hedef_db_path()
        conn = _sq_k2.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                \"SELECT proses_kod FROM proses_usta_atama \"
                \"WHERE usta_kullanici=? AND aktif=1\",
                (kullanici_adi,)
            )
            proses_kodlar = [r[0] for r in cur.fetchall()]
            if not proses_kodlar:
                return set()

            placeholders = ','.join(['?'] * len(proses_kodlar))
            cur.execute(
                f\"SELECT DISTINCT emir_no FROM uretim_kayit \"
                f\"WHERE proses_kod IN ({placeholders})\",
                proses_kodlar
            )
            return set(int(r[0]) for r in cur.fetchall() if r[0] is not None)
        finally:
            conn.close()
    except Exception as _e_k2:
        try:
            print(f'[KATMAN_2_FILTER] hata, guvenli mod (bos liste): {_e_k2}')
        except Exception:
            pass
        return set()


def _katman2_emir_yetkili(emir_no):
    \"\"\"Tek emir icin yetki kontrol. Filtre yoksa True doner.\"\"\"
    izin_set = _katman2_izinli_emirler()
    if izin_set is None:
        return True
    try:
        return int(emir_no) in izin_set
    except Exception:
        return False
# === [KATMAN_2_DATA_FILTER:END] ===


"""

PLAN_FILTRE = """\
    # === [KATMAN_2_FILTER:hedef_plan:BEGIN] ===
    _izin_set_k2 = _katman2_izinli_emirler()
    if _izin_set_k2 is not None:
        sonuc = [_x for _x in sonuc if int(_x.get('emir_no', 0)) in _izin_set_k2]
    # === [KATMAN_2_FILTER:hedef_plan:END] ===

"""

PLAN_DETAY_GUARD = """\
    # === [KATMAN_2_GUARD:plan_detay:BEGIN] ===
    if not _katman2_emir_yetkili(emir_no):
        from flask import jsonify as _jsf_k2
        return _jsf_k2({'ok': False, 'mesaj': 'Bu emir icin yetkiniz yok.', 'kod': 'YETKI_YOK'}), 403
    # === [KATMAN_2_GUARD:plan_detay:END] ===
"""

PLAN_DARBOGAZ_FILTRE = """\
    # === [KATMAN_2_FILTER:plan_darbogaz:BEGIN] ===
    _izin_set_k2 = _katman2_izinli_emirler()
    if _izin_set_k2 is not None:
        emirler = [_e for _e in emirler if _e in _izin_set_k2]
        if not emirler:
            return jsonify({'ok': True, 'emirler': [], 'mesaj': 'yetkili_emir_yok'})
    # === [KATMAN_2_FILTER:plan_darbogaz:END] ===
"""

# ---------------- ANCHOR PATTERN'LERI (LF) ----------------

ANCHOR_HELPER = 'def hedef_yetkili(f):'

# Dosyadan dogrulanmis tam metin (LF)
# Satir 394-399 (CRLF kaldirildi):
#   return jsonify({
#       'success': True, 'ok': True,
#       'emirler': sonuc,
ANCHOR_PLAN_AFTER = (
    "    return jsonify({\n"
    "        'success': True, 'ok': True,\n"
    "        'emirler': sonuc,"
)

# Satir 392 (sort) + bosluk + return - LF formatinda
ANCHOR_PLAN_BEFORE = "    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)"

# Satir 1300-1301 (def + docstring) - LF formatinda
ANCHOR_DETAY_BEFORE = (
    "def hedef_plan_detay(emir_no):\n"
    "    \"\"\"Hiyerarsik detay - Atki/Govde/Ana, Korgun+CPS birlesik.\"\"\"\n"
)

# Satir 1844-1845 (if + return 400) - LF formatinda
ANCHOR_DARBOGAZ_BEFORE = (
    "    if not emirler:\n"
    "        return jsonify({'ok': False, 'mesaj': 'gecerli emir yok'}), 400\n"
)

# ---------------- UTIL ----------------

def log(msg, level='INFO'):
    pfx = {'INFO': '[INFO]', 'OK': '[OK]', 'ERR': '[HATA]', 'WARN': '[UYARI]'}.get(level, '[INFO]')
    print(f'{pfx} {msg}')


def read_normalize(path):
    """Dosyayi oku, line ending'i tespit et, LF'e normalize ederek don."""
    with open(path, 'rb') as f:
        raw = f.read()
    # BOM strip
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    text = raw.decode('utf-8')
    # Line ending tespit
    if '\r\n' in text:
        line_ending = '\r\n'
    elif '\r' in text:
        line_ending = '\r'
    else:
        line_ending = '\n'
    # LF'e normalize
    norm = text.replace('\r\n', '\n').replace('\r', '\n')
    return norm, line_ending


def write_with_ending(path, content_lf, line_ending):
    """LF icerigi orijinal line ending ile yaz (BOM yok)."""
    if line_ending != '\n':
        content = content_lf.replace('\n', line_ending)
    else:
        content = content_lf
    with open(path, 'wb') as f:
        f.write(content.encode('utf-8'))


def auto_rollback(backup_path, target_path):
    try:
        shutil.copy2(backup_path, target_path)
        log(f'ROLLBACK BASARILI: {os.path.basename(backup_path)} -> routes.py', 'OK')
    except Exception as e:
        log(f'ROLLBACK BASARISIZ: {e}', 'ERR')


# ---------------- ANA AKIS ----------------

def main():
    log('=' * 70)
    log('KATMAN 2 - /hedef/ DATA FILTER PATCH (v2 CRLF-aware)')
    log('=' * 70)
    log(f'Hedef: {ROUTES_PATH}')

    if not os.path.exists(ROUTES_PATH):
        log(f'routes.py bulunamadi: {ROUTES_PATH}', 'ERR')
        return 1

    # 1) Oku + normalize
    orig_lf, line_ending = read_normalize(ROUTES_PATH)
    le_name = {'\r\n': 'CRLF', '\r': 'CR', '\n': 'LF'}.get(line_ending, '?')
    log(f'Boyut (LF norm): {len(orig_lf)} karakter, line ending: {le_name}')

    # 2) Idempotency
    if MASTER_MARKER in orig_lf:
        log('Master marker zaten var. Patch daha once uygulanmis.', 'WARN')
        return 0

    # 3) Anchor varlik kontrolu (LF uzerinde)
    log('')
    log('--- Anchor varlik kontrolu (LF normalized) ---')
    anchors = {
        'A_HELPER': ANCHOR_HELPER,
        'B_PLAN_BEFORE': ANCHOR_PLAN_BEFORE,
        'B_PLAN_AFTER': ANCHOR_PLAN_AFTER,
        'C_DETAY': ANCHOR_DETAY_BEFORE,
        'D_DARBOGAZ': ANCHOR_DARBOGAZ_BEFORE,
    }
    eksik = []
    for name, anchor in anchors.items():
        say = orig_lf.count(anchor)
        durum = 'OK' if say == 1 else ('COKLU' if say > 1 else 'YOK')
        log(f'  [{durum}] {name}: {say} eslesme')
        if say != 1:
            eksik.append(name)

    if eksik:
        log(f'Anchor problemi var: {eksik}. Patch IPTAL.', 'ERR')
        return 2

    # 4) Backup (ORIJINAL DOSYAYI - line ending koru)
    log('')
    log('--- Backup ---')
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f'{ROUTES_PATH}.YEDEK_KATMAN2_DATA_FILTER_{ts}'
    shutil.copy2(ROUTES_PATH, backup_path)
    log(f'Backup: {os.path.basename(backup_path)}', 'OK')

    # 5) Replace (LF uzerinde)
    log('')
    log('--- Replace uygulamalari ---')
    new_lf = orig_lf

    # A) Helper
    new_lf = new_lf.replace(ANCHOR_HELPER, HELPER_KODU + ANCHOR_HELPER, 1)
    log('  A) Helper enjekte edildi', 'OK')

    # B) /hedef/plan: sort + 2 blank line + return arasi
    eski_b = ANCHOR_PLAN_BEFORE + '\n\n' + ANCHOR_PLAN_AFTER
    yeni_b = ANCHOR_PLAN_BEFORE + '\n\n' + PLAN_FILTRE + ANCHOR_PLAN_AFTER
    if eski_b in new_lf:
        new_lf = new_lf.replace(eski_b, yeni_b, 1)
        log('  B) /hedef/plan filtresi eklendi', 'OK')
    else:
        log('  B) sort..return arasi format eslemedi', 'ERR')
        log(f'     Ariyor: {repr(eski_b[:80])}...', 'INFO')
        auto_rollback(backup_path, ROUTES_PATH)
        return 3

    # C) /hedef/plan-detay docstring sonrasi
    new_lf = new_lf.replace(
        ANCHOR_DETAY_BEFORE,
        ANCHOR_DETAY_BEFORE + PLAN_DETAY_GUARD,
        1
    )
    log('  C) /hedef/plan-detay guard eklendi', 'OK')

    # D) /hedef/plan-darbogaz 400 return sonrasi
    new_lf = new_lf.replace(
        ANCHOR_DARBOGAZ_BEFORE,
        ANCHOR_DARBOGAZ_BEFORE + '\n' + PLAN_DARBOGAZ_FILTRE,
        1
    )
    log('  D) /hedef/plan-darbogaz filtresi eklendi', 'OK')

    # 6) Marker dogrulama
    begin_say = new_lf.count(':BEGIN]')
    end_say = new_lf.count(':END]')
    log('')
    log(f'Marker sayim: {begin_say} BEGIN / {end_say} END')
    if begin_say != 4 or end_say != 4:
        log('Marker sayisi yanlis. Rollback.', 'ERR')
        auto_rollback(backup_path, ROUTES_PATH)
        return 4

    # 7) Yaz (orijinal line ending'i geri uygula)
    write_with_ending(ROUTES_PATH, new_lf, line_ending)
    log(f'Yazma tamam. Yeni boyut (LF): {len(new_lf)} karakter (+{len(new_lf)-len(orig_lf)})')

    # 8) Syntax check
    log('')
    log('--- py_compile syntax check ---')
    try:
        py_compile.compile(ROUTES_PATH, doraise=True)
        log('Syntax OK', 'OK')
    except py_compile.PyCompileError as e:
        log(f'SYNTAX HATASI: {e}', 'ERR')
        auto_rollback(backup_path, ROUTES_PATH)
        return 5

    # 9) Sonuc
    log('')
    log('=' * 70)
    log('PATCH BASARILI', 'OK')
    log(f'Backup       : {os.path.basename(backup_path)}')
    log(f'Marker BEGIN : {begin_say}')
    log(f'Marker END   : {end_say}')
    log(f'Boyut farki  : +{len(new_lf)-len(orig_lf)} karakter')
    log(f'Line ending  : {le_name} (korundu)')
    log('=' * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())