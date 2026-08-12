"""
CARI360-FINANS-VISUAL-CLOSURE-04 regression testi
10 case — in-memory DB, canonical DB'ye yazma yok.
"""
import sys, os, sqlite3, types, importlib, datetime, uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
os.environ.setdefault('DB_MODE', 'mock')

# ── In-memory DB kur ──────────────────────────────────────────────────────────
con = sqlite3.connect(':memory:')
con.row_factory = sqlite3.Row
con.execute('PRAGMA foreign_keys=OFF')

con.executescript("""
CREATE TABLE nexgen_cari (id INTEGER PRIMARY KEY, cari_kod TEXT, unvan TEXT, aktif INTEGER DEFAULT 1);
INSERT INTO nexgen_cari VALUES (10,'A-001','Cari A',1);
INSERT INTO nexgen_cari VALUES (20,'B-001','Cari B',1);

CREATE TABLE nexgen_planlama_siparis (
  id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, durum TEXT, aktif INTEGER DEFAULT 1
);
INSERT INTO nexgen_planlama_siparis VALUES (101,'PZM-A-0001',10,'TAMAMLANDI',1);
INSERT INTO nexgen_planlama_siparis VALUES (102,'PZM-A-0002',10,'DEVAM',1);
INSERT INTO nexgen_planlama_siparis VALUES (201,'PZM-B-0001',20,'TAMAMLANDI',1);

CREATE TABLE mo_musteri_sevkiyat (
  id INTEGER PRIMARY KEY, sevkiyat_no TEXT, cari_id INTEGER, siparis_id INTEGER,
  durum TEXT, aktif INTEGER DEFAULT 1,
  olusturma_tarihi TEXT, guncelleme_tarihi TEXT
);
INSERT INTO mo_musteri_sevkiyat VALUES (301,'MSV-A-0001',10,101,'SEVK_EDILDI',1,NULL,NULL);
INSERT INTO mo_musteri_sevkiyat VALUES (401,'MSV-B-0001',20,201,'SEVK_EDILDI',1,NULL,NULL);

CREATE TABLE mo_tahsilat_kayit (
  id INTEGER PRIMARY KEY, kayit_kodu TEXT, cari_id INTEGER, siparis_id INTEGER,
  sevkiyat_id INTEGER, kaynak_modul TEXT, beklenen_tutar REAL, beklenen_tahmini INTEGER DEFAULT 0,
  alinan_tutar REAL, kalan_tutar REAL, planlanan_tahsilat_tarihi TEXT,
  alinan_tarih TEXT, odeme_tipi TEXT, odeme_referansi TEXT, kismi_mi INTEGER,
  aciklama TEXT, durum TEXT, cari_entegrasyon_durumu TEXT, idempotency_key TEXT,
  olusturan_id INTEGER, onaylayan_id INTEGER, aktif INTEGER DEFAULT 1,
  olusturma_tarihi TEXT, guncelleme_tarihi TEXT, audit_json TEXT,
  para_birimi TEXT DEFAULT 'TRY'
);
-- MO kaydı cari A
INSERT INTO mo_tahsilat_kayit
  (id,kayit_kodu,cari_id,siparis_id,kaynak_modul,alinan_tutar,alinan_tarih,odeme_tipi,durum,aktif,idempotency_key,olusturan_id,olusturma_tarihi,guncelleme_tarihi,beklenen_tahmini,para_birimi)
VALUES
  (1,'MO-T-A-001',10,101,'MUSTERI_OPERASYONU',5000,'2026-08-01','NAKIT','ONAYLANDI',1,'u1',1,'2026-08-01','2026-08-01',0,'TRY');

CREATE TABLE mo_tahsilat_cek (
  id INTEGER PRIMARY KEY, tahsilat_kayit_id INTEGER, sira_no INTEGER,
  tutar REAL, para_birimi TEXT, gercek_cek_vade_tarihi TEXT, odeme_referansi TEXT,
  durum TEXT, aktif INTEGER DEFAULT 1, idempotency_key TEXT,
  olusturan_id INTEGER, olusturma_tarihi TEXT, guncelleme_tarihi TEXT
);
""")
con.commit()

from modules.nexgen.cari360_finans_service import (
    manuel_tahsilat_olustur, FinansManuelTahsilatError,
)
from modules.nexgen.mo_tahsilat_config import KAYNAK_MANUEL_FINANS, KAYNAK_MUSTERI_OPERASYONU

_ok = 0
_fail = 0

def chk(label, cond):
    global _ok, _fail
    if cond:
        print(f'  PASS  {label}')
        _ok += 1
    else:
        print(f'  FAIL  {label}')
        _fail += 1

def _write(cari_id, siparis_id=None, sevkiyat_id=None, odeme_tipi='NAKIT',
           tutar=100.0, pb='TRY', cek_vade=None):
    return manuel_tahsilat_olustur(
        con, cari_id, 1,
        alinan_tarih='2026-08-12',
        odeme_tipi=odeme_tipi,
        alinan_tutar=tutar,
        para_birimi=pb,
        siparis_id=siparis_id,
        sevkiyat_id=sevkiyat_id,
        cek_vade_tarihi=cek_vade,
    )

# ── CASE 1: Cari A siparişi Cari A'ya bağlanabilir ───────────────────────────
print('CASE 1 — Cari A siparis_id=101 Cari A:')
try:
    r = _write(cari_id=10, siparis_id=101)
    chk('yazılır', r.get('ok'))
except Exception as e:
    chk('yazılır', False); print('   ', e)

# ── CASE 2: Cari B siparişi Cari A'ya → REJECT ───────────────────────────────
print('CASE 2 — Cari B siparis_id=201 Cari A (cross-cari):')
try:
    _write(cari_id=10, siparis_id=201)
    chk('REJECT', False)
except FinansManuelTahsilatError as e:
    chk('REJECT', '400' in str(e.kod) or e.kod == 400)
except Exception as e:
    chk('REJECT', False); print('   ', e)

# ── CASE 3: Cari A sevkiyatı Cari A'ya bağlanabilir ─────────────────────────
print('CASE 3 — Cari A sevkiyat_id=301 Cari A:')
try:
    r = _write(cari_id=10, sevkiyat_id=301)
    chk('yazılır', r.get('ok'))
except Exception as e:
    chk('yazılır', False); print('   ', e)

# ── CASE 4: Cari B sevkiyatı Cari A'ya → REJECT ─────────────────────────────
print('CASE 4 — Cari B sevkiyat_id=401 Cari A (cross-cari):')
try:
    _write(cari_id=10, sevkiyat_id=401)
    chk('REJECT', False)
except FinansManuelTahsilatError as e:
    chk('REJECT', e.kod == 400)
except Exception as e:
    chk('REJECT', False); print('   ', e)

# ── CASE 5: Pointer seçilmeden PASS ─────────────────────────────────────────
print('CASE 5 — siparis_id=None, sevkiyat_id=None:')
try:
    r = _write(cari_id=10)
    chk('PASS (opsiyonel)', r.get('ok'))
except Exception as e:
    chk('PASS (opsiyonel)', False); print('   ', e)

# ── CASE 6: NAKIT → mo_tahsilat_cek oluşturmaz ──────────────────────────────
print('CASE 6 — NAKIT → mo_tahsilat_cek oluşturmaz:')
cek_before = con.execute('SELECT COUNT(*) FROM mo_tahsilat_cek').fetchone()[0]
_write(cari_id=10, odeme_tipi='NAKIT')
cek_after = con.execute('SELECT COUNT(*) FROM mo_tahsilat_cek').fetchone()[0]
chk('cek oluşmadı', cek_before == cek_after)

# ── CASE 7: kaynak_modul = MANUEL_FINANS ────────────────────────────────────
print('CASE 7 — kaynak_modul=MANUEL_FINANS:')
rows = con.execute(
    "SELECT kaynak_modul FROM mo_tahsilat_kayit WHERE kaynak_modul=?",
    (KAYNAK_MANUEL_FINANS,)
).fetchall()
chk('MANUEL_FINANS var', len(rows) > 0)

# ── CASE 8: MO kayıtları MUSTERI_OPERASYONU kalır ───────────────────────────
print('CASE 8 — MO kayıtları MUSTERI_OPERASYONU:')
mo_rows = con.execute(
    "SELECT kaynak_modul FROM mo_tahsilat_kayit WHERE kaynak_modul=?",
    (KAYNAK_MUSTERI_OPERASYONU,)
).fetchall()
chk('MUSTERI_OPERASYONU korundu', len(mo_rows) > 0)

# ── CASE 9: Finans panelinde sahipsiz 'Aktif' badge — JS 'Kart Snap.' veya 'Canlı Veri' ─
print("CASE 9 — badge metni 'Aktif' artık YOK (template değişti):")
import re
with open('app/templates/nexgen/cari360_kart.html', encoding='utf-8') as f:
    tmpl = f.read()
# 'Aktif' literal badge olarak sadece JS'de vardı; şimdi olmamalı
badge_aktif = re.search(r"badge\.textContent\s*=\s*'Aktif'", tmpl)
chk("badge 'Aktif' literal kaldırıldı", badge_aktif is None)

# ── CASE 10: Cari header badge 'Aktif' hâlâ var ────────────────────────────
print("CASE 10 — header badge 'Aktif' hâlâ template'de:")
header_aktif = re.search(r'ckart-badge-aktif-v2.*?Aktif|Aktif.*?ckart-badge-aktif-v2', tmpl, re.DOTALL)
chk("header 'Aktif' badge var", bool(header_aktif))

con.close()

print()
print(f'TOPLAM: {_ok + _fail}  PASS: {_ok}  FAIL: {_fail}')
sys.exit(0 if _fail == 0 else 1)
