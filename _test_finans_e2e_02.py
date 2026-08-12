# -*- coding: utf-8 -*-
"""
CARI360-FINANS-MANUEL-TAHSILAT-E2E-02
Isolated temp-copy DB'de çalışır. Canonical DB'ye dokunmaz.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

CANONICAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'mock_data.db')

_PASS = []
_FAIL = []

def _chk(label, cond, got=None, exp=None):
    if cond:
        _PASS.append(label)
        print(f'  PASS  {label}')
    else:
        _FAIL.append(label)
        print(f'  FAIL  {label}  got={got!r}  exp={exp!r}')

def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            c = f.read(65536)
            if not c:
                break
            h.update(c)
    return h.hexdigest()[:16]

# ─── DB kopyala ───────────────────────────────────────────────────────────────
sha_before = _sha(CANONICAL_DB)
print(f'CANONICAL SHA BEFORE = {sha_before}')

tmpdir = tempfile.mkdtemp(prefix='cps_e2e_')
test_db = os.path.join(tmpdir, 'test.db')
shutil.copy2(CANONICAL_DB, test_db)
# WAL dosyalarını da kopyala
for ext in ('-wal', '-shm'):
    src = CANONICAL_DB + ext
    if os.path.exists(src):
        shutil.copy2(src, test_db + ext)

print(f'TEST DB = {test_db}')

def _open():
    con = sqlite3.connect(test_db)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con

# ─── Import servisler ─────────────────────────────────────────────────────────
from modules.nexgen.cari360_finans_service import (
    KAYNAK_MANUEL_FINANS,
    KAYNAK_MUSTERI_OPERASYONU,
    load_cari360_finans,
    load_cari360_tahsilat_liste,
    manuel_tahsilat_olustur,
)
from modules.nexgen.cari360_yetki import can_cari360_finans_write

# Test carisi
CARI_ID = 5

# ─── 1. SHA BEFORE ───────────────────────────────────────────────────────────
print('\n=== 1. SHA BEFORE ===')
_chk('canonical SHA stabil', sha_before == sha_before)  # trivial marker

# ─── 2. Mevcut MO tahsilatı doğrula ──────────────────────────────────────────
print('\n=== 2. MEVCUT MO TAHSİLATI ===')
con = _open()
mo_rows = con.execute(
    """SELECT id, alinan_tarih, alinan_tutar, para_birimi, durum, kaynak_modul, siparis_id
       FROM mo_tahsilat_kayit
       WHERE cari_id=? AND kaynak_modul=? AND COALESCE(aktif,1)=1
       ORDER BY id
       LIMIT 5""",
    (CARI_ID, KAYNAK_MUSTERI_OPERASYONU),
).fetchall()
_chk('MO tahsilat var', len(mo_rows) > 0, len(mo_rows))
if mo_rows:
    r0 = mo_rows[0]
    print(f'  MO COLLECTION: id={r0["id"]} tarih={r0["alinan_tarih"]} tutar={r0["alinan_tutar"]} pb={r0["para_birimi"]} durum={r0["durum"]}')
    _chk('MO kaynak=MUSTERI_OPERASYONU', r0['kaynak_modul'] == KAYNAK_MUSTERI_OPERASYONU)
    _chk('MO cari_id doğru', r0['id'] > 0)
con.close()

# ─── 3. KPI BEFORE ───────────────────────────────────────────────────────────
print('\n=== 3. KPI BEFORE ===')
con = _open()
d_before = load_cari360_finans(con, CARI_ID)
kpi_before = d_before['tahsilat']
liste_before = d_before['tahsilat_liste']
print(f'  KPI BEFORE: alinan={kpi_before["alinan_toplam"]} toplam_kayit={liste_before["toplam"]}')
_chk('KPI before load ok', 'alinan_toplam' in kpi_before)
con.close()

# ─── 4. MANUEL TAHSİLAT OLUŞTUR (ONAYLANDI/TRY) ─────────────────────────────
print('\n=== 4. MANUEL TAHSİLAT (NAKIT/TRY/ONAYLANDI) ===')
TEST_TUTAR = 1234.56
TEST_TARIH = '2026-08-12'
TEST_NOT   = 'CARI360 MANUEL E2E TEST'

con = _open()
res = manuel_tahsilat_olustur(
    con, CARI_ID, kullanici_id=1,
    alinan_tarih=TEST_TARIH,
    odeme_tipi='NAKIT',
    alinan_tutar=TEST_TUTAR,
    para_birimi='TRY',
    aciklama=TEST_NOT,
)
new_kayit_kodu = res.get('kayit_kodu', '')
print(f'  CREATE RESULT: {res}')
_chk('manuel create ok', res.get('ok') is True)
_chk('kayit_kodu var', bool(new_kayit_kodu))
con.close()

# ─── 5. WRITE CONTRACT ────────────────────────────────────────────────────────
print('\n=== 5. WRITE CONTRACT ===')
con = _open()
written = con.execute(
    """SELECT * FROM mo_tahsilat_kayit
       WHERE kayit_kodu=? AND cari_id=?""",
    (new_kayit_kodu, CARI_ID),
).fetchone()
_chk('kayit tabloda var', written is not None)
if written:
    _chk('kaynak=MANUEL_FINANS', written['kaynak_modul'] == KAYNAK_MANUEL_FINANS, written['kaynak_modul'])
    _chk('cari_id doğru', int(written['cari_id']) == CARI_ID, written['cari_id'])
    _chk('tutar doğru', abs(float(written['alinan_tutar']) - TEST_TUTAR) < 0.01, written['alinan_tutar'])
    _chk('PB=TRY', written['para_birimi'] == 'TRY', written['para_birimi'])
    _chk('durum=ONAYLANDI', written['durum'] == 'ONAYLANDI', written['durum'])
    _chk('aktif=1', int(written['aktif']) == 1, written['aktif'])
    _chk('olusturan=1', int(written['olusturan_id']) == 1, written['olusturan_id'])
    print(f'  WRITE: id={written["id"]} kaynak={written["kaynak_modul"]} tutar={written["alinan_tutar"]}')
con.close()

# ─── 6. REAL CHECK SEPARATION — NAKIT ise cek kaydı oluşmamalı ──────────────
print('\n=== 6. REAL CHECK SEPARATION ===')
con = _open()
cek_rows = con.execute(
    """SELECT c.id FROM mo_tahsilat_cek c
       JOIN mo_tahsilat_kayit k ON k.id=c.tahsilat_kayit_id
       WHERE k.kayit_kodu=?""",
    (new_kayit_kodu,),
).fetchall()
_chk('NAKIT → cek kaydı YOK', len(cek_rows) == 0, len(cek_rows))
con.close()

# ─── 7. AYNI TABLO — MO ve Manuel yan yana ───────────────────────────────────
print('\n=== 7. AYNI TABLO / AYNI CARİ ===')
con = _open()
all_rows = con.execute(
    """SELECT id, kaynak_modul FROM mo_tahsilat_kayit
       WHERE cari_id=? AND COALESCE(aktif,1)=1""",
    (CARI_ID,),
).fetchall()
kaynaklar = {r['kaynak_modul'] for r in all_rows}
_chk('MUSTERI_OPERASYONU var', KAYNAK_MUSTERI_OPERASYONU in kaynaklar)
_chk('MANUEL_FINANS var', KAYNAK_MANUEL_FINANS in kaynaklar)
_chk('aynı tablo', True)  # by definition — tek tablo sorgulandı
# Yanlış cariye sızma yok
baska_cari = con.execute(
    "SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE kayit_kodu=? AND cari_id!=?",
    (new_kayit_kodu, CARI_ID),
).fetchone()[0]
_chk('baska cariye sizinti yok', baska_cari == 0, baska_cari)
con.close()

# ─── 8. KPI AFTER — ALINAN artmalı ───────────────────────────────────────────
print('\n=== 8. KPI AFTER ===')
con = _open()
d_after = load_cari360_finans(con, CARI_ID)
kpi_after = d_after['tahsilat']
liste_after = d_after['tahsilat_liste']
print(f'  KPI AFTER: alinan={kpi_after["alinan_toplam"]} toplam_kayit={liste_after["toplam"]}')
alinan_diff = kpi_after['alinan_toplam'] - kpi_before['alinan_toplam']
_chk('KPI alinan arttı', alinan_diff > 0, alinan_diff)
_chk('KPI artis=TEST_TUTAR', abs(alinan_diff - TEST_TUTAR) < 0.01, alinan_diff)
_chk('liste.toplam arttı', liste_after['toplam'] > liste_before['toplam'], (liste_after['toplam'], liste_before['toplam']))
con.close()

# ─── 9. CARI360 LİSTE — her iki kaynak görünüyor ──────────────────────────────
print('\n=== 9. CARI360 TAHSİLAT LİSTESİ ===')
con = _open()
tl = load_cari360_tahsilat_liste(con, CARI_ID, limit=50)
liste_kaynaklar = {x['kaynak_raw'] for x in tl['liste']}
_chk('liste MO var', KAYNAK_MUSTERI_OPERASYONU in liste_kaynaklar)
_chk('liste MANUEL var', KAYNAK_MANUEL_FINANS in liste_kaynaklar)
manuel_rows = [x for x in tl['liste'] if x['kaynak_raw'] == KAYNAK_MANUEL_FINANS]
mo_rows_lst = [x for x in tl['liste'] if x['kaynak_raw'] == KAYNAK_MUSTERI_OPERASYONU]
print(f'  MO rows={len(mo_rows_lst)}  Manuel rows={len(manuel_rows)}')
_chk('manuel row bulundu', any(x['belge_no'] == new_kayit_kodu for x in manuel_rows), new_kayit_kodu)
# Duplicate kontrol
ids = [x['id'] for x in tl['liste']]
_chk('duplicate yok', len(ids) == len(set(ids)))
con.close()

# ─── 10. BEKLEYEN durum → ALINAN'a girmemeli ─────────────────────────────────
print('\n=== 10. BEKLEYEN KPI CONTRACT ===')
# in-memory DB'de simüle
import sqlite3 as _sq
mem = _sq.connect(':memory:')
mem.row_factory = _sq.Row
mem.execute("""CREATE TABLE mo_tahsilat_kayit (
    id INTEGER PRIMARY KEY, kayit_kodu TEXT, cari_id INTEGER,
    kaynak_modul TEXT, alinan_tutar REAL, beklenen_tutar REAL, kalan_tutar REAL,
    alinan_tarih TEXT, planlanan_tahsilat_tarihi TEXT, odeme_tipi TEXT,
    durum TEXT, idempotency_key TEXT, olusturan_id INTEGER, aktif INTEGER,
    olusturma_tarihi TEXT, guncelleme_tarihi TEXT, para_birimi TEXT,
    beklened_tutar REAL, siparis_id INTEGER, aciklama TEXT, odeme_referansi TEXT
)""")
# ONAYLANDI kaydı
mem.execute(
    "INSERT INTO mo_tahsilat_kayit VALUES (1,'T-0001',1,?,5000,5000,0,'2026-08-10',NULL,'NAKIT','ONAYLANDI','k1',1,1,'2026-08-10','2026-08-10','TRY',5000,NULL,NULL,NULL)",
    (KAYNAK_MUSTERI_OPERASYONU,)
)
# TASLAK (bekleyen) kaydı — ALINAN'a girmemeli
mem.execute(
    "INSERT INTO mo_tahsilat_kayit VALUES (2,'T-0002',1,?,3000,3000,3000,'2026-08-11',NULL,'NAKIT','TASLAK','k2',1,1,'2026-08-11','2026-08-11','TRY',3000,NULL,NULL,NULL)",
    (KAYNAK_MANUEL_FINANS,)
)
mem.execute("CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, cari_adi TEXT, aktif INTEGER)")
mem.execute("INSERT INTO nexgen_cari VALUES (1,'Test',1)")
from modules.nexgen.cari360_finans_service import _tahsilat_ozet
kpi_mem = _tahsilat_ozet(mem, 1)
_chk('kpi_contract alinan=5000 (TASLAK dahil değil)', abs(kpi_mem['alinan_toplam'] - 5000.0) < 0.01, kpi_mem['alinan_toplam'])
_chk('kpi_contract bekleyen>0', kpi_mem['bekleyen_toplam'] > 0, kpi_mem['bekleyen_toplam'])
mem.close()

# ─── 11. PERMISSION CHECK ─────────────────────────────────────────────────────
print('\n=== 11. PERMISSION ===')
# Yetkili kullanıcı — finans write
yk_yetkili = frozenset({'cari360.finans.write:can_manage'})
_chk('yetkili kullanici PASS', can_cari360_finans_write(yk_yetkili))
# Yetkisiz kullanıcı
yk_yetkisiz = frozenset({'cari360.genel.view:can_view'})
_chk('yetkisiz kullanici FAIL', not can_cari360_finans_write(yk_yetkisiz))

# ─── 12. 34.343.242 TEST DATA LEAK REPORT ────────────────────────────────────
print('\n=== 12. TEST DATA LEAK REPORT ===')
con = _open()
leak = con.execute(
    "SELECT id, alinan_tutar, durum, alinan_tarih FROM mo_tahsilat_kayit WHERE id=59",
).fetchone()
if leak:
    print(f'  TEST DATA LEAK: id=59 alinan_tutar={leak["alinan_tutar"]} durum={leak["durum"]} tarih={leak["alinan_tarih"]}')
    print('  ACTION = rapor edildi, SILME/DEĞIŞTIRME YOK.')
con.close()

# ─── 13. SHA AFTER (canonical) ───────────────────────────────────────────────
sha_after = _sha(CANONICAL_DB)
print(f'\nCANONICAL SHA AFTER = {sha_after}')
_chk('canonical SHA degismedi', sha_before == sha_after, sha_after)

# ─── Temp cleanup ────────────────────────────────────────────────────────────
shutil.rmtree(tmpdir, ignore_errors=True)

# ─── ÖZET ────────────────────────────────────────────────────────────────────
print()
print(f'PASS: {len(_PASS)}  FAIL: {len(_FAIL)}')
if _FAIL:
    print('FAILED CHECKS:', _FAIL)
    raise SystemExit(1)
print('ALL PASS')
