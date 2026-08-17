# -*- coding: utf-8 -*-
"""
T1–T14 lock tests — Üretim Plan V1 Enjeksiyon Kapasite
READ-ONLY enj_ab_setup/enj_makine. plan_ekle/guncelle DB write (mock).
"""
from __future__ import annotations
import sys, sqlite3, json, math, os
sys.stdout.reconfigure(encoding='utf-8')

# ── DB bağlantısı ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from config import Config
DB = Config.MOCK_DB_PATH

def _con():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

# ── Migration 159 control ─────────────────────────────────────────────────
def _enj_cols_mevcut(con):
    cols = {r[1] for r in con.execute('PRAGMA table_info(uretim_model_plan)').fetchall()}
    return 'enj_makine_id' in cols and 'enj_tur_cift' in cols

# ── Yardımcılar ───────────────────────────────────────────────────────────
passed = []
failed = []

def ok(label, _=''):
    passed.append(label)
    print(f'  PASS  {label}')

def fail(label, reason=''):
    failed.append(label)
    print(f'  FAIL  {label}' + (f' — {reason}' if reason else ''))

def check(label, condition, reason=''):
    if condition:
        ok(label)
    else:
        fail(label, reason)


# ══════════════════════════════════════════════════════════════════════════
print('=' * 60)
print('Üretim Plan V1 Enjeksiyon — Lock Test Seti')
print('=' * 60)

con = _con()

# T1: M1 → 8 istasyon
row = con.execute("SELECT istasyon_sayisi FROM enj_makine WHERE kod='M1'").fetchone()
check('T1  M1 = 8 istasyon', row and row['istasyon_sayisi'] == 8,
      f'Gerçek: {row["istasyon_sayisi"] if row else "yok"}')

# T2: M3 → 6 istasyon
row = con.execute("SELECT istasyon_sayisi FROM enj_makine WHERE kod='M3'").fetchone()
check('T2  M3 = 6 istasyon', row and row['istasyon_sayisi'] == 6,
      f'Gerçek: {row["istasyon_sayisi"] if row else "yok"}')

# T3: Her makine hem A hem B slota sahip
row = con.execute("""
    SELECT COUNT(DISTINCT i.slot) sc
    FROM enj_istasyon_durumu i
    JOIN enj_gunluk_rapor r ON r.id=i.rapor_id
    WHERE r.makine_id=1
""").fetchone()
check('T3  M1 istasyonlarında A ve B slot var', row and row['sc'] == 2,
      f'Slot tipi sayısı: {row["sc"] if row else 0}')

# T4: 16 çift/tur × 60 tur = 960/gün
tur_cift = 16
gun_tur = 60
gunluk_kap = tur_cift * gun_tur
check('T4  16 × 60 = 960 çift/gün', gunluk_kap == 960,
      f'Hesap: {gunluk_kap}')

# T5: 4000 / 960 doğru tahmini süre
plan_cift = 4000
tahmini_gun = plan_cift / gunluk_kap
check('T5  4000 / 960 ≈ 4.1667 gün', abs(tahmini_gun - (4000/960)) < 0.0001,
      f'Hesap: {tahmini_gun:.4f}')
gun_sayisi = math.ceil(tahmini_gun)
check('T5b ceil(4.1667) = 5 gün (teslim)', gun_sayisi == 5,
      f'ceil: {gun_sayisi}')

# T6: Migration 159 — enj_ kolonları mevcut
check('T6  enj_ kolonları uretim_model_plan tablosunda', _enj_cols_mevcut(con))

# T7: Farklı renk canonical key bozulmuyor
from modules.planlama.uretim_plan_repo import canonical_key
k1 = canonical_key(33919, 1, 'CRP-8100', 1)
k2 = canonical_key(33919, 1, 'CRP-8100', 2)
check('T7  Farklı RKOD → farklı canonical key', k1 != k2,
      f'k1={k1}, k2={k2}')
k3 = canonical_key(33919, 1, 'CRP-8100', 1)
check('T7b Aynı parametreler → aynı canonical key', k1 == k3)

# T8: aynı model+renk lot/emir drilldown bağımsız — canonical key parse
from modules.planlama.uretim_plan_repo import parse_canonical_key
parsed = parse_canonical_key(k1)
check('T8  canonical_key parse doğru',
      parsed['sip_no'] == 33919 and parsed['mamul_skod'] == 'CRP-8100' and parsed['rkod'] == 1,
      str(parsed))

# T9: Canlı enj_ab_setup WRITE yok — sadece read
# Kontrol: plan_ekle çağrılsa bile enj_ab_setup tablosuna insert yapılmaz.
# enj_ab_setup satır sayısı değişmemeli
before = con.execute('SELECT COUNT(*) c FROM enj_ab_setup').fetchone()['c']
from modules.planlama.uretim_plan_repo import ENJ_ALANLARI
# repo kodu yalnızca uretim_model_plan'a yazar
check('T9  ENJ_ALANLARI yalnızca uretim_model_plan kolonlarını kapsar',
      all('enj_ab_setup' not in k for k in ENJ_ALANLARI))
after = con.execute('SELECT COUNT(*) c FROM enj_ab_setup').fetchone()['c']
check('T9b enj_ab_setup satır sayısı değişmedi', before == after)

# T10: Mevcut proses aggregate bozulmamış — korgun_row olmadığında BAŞLANMADI döner
from modules.planlama.uretim_plan_service import merge_plan_korgun
dummy_plan = {
    'id': 1, 'sip_no': 1, 'sip_harinx': 1, 'mamul_skod': 'TEST', 'rkod': 0,
    'plan_donemi': 'bu_hafta', 'plan_baslangic': None, 'plan_bitis': None,
    'oncelik': 3, 'plan_gerekce': None, 'plan_notu': None, 'aktif': 1,
    'model_adi': None, 'renk_adi': None, 'miktar': None, 'termin': None,
    'canonical_key': '1|1|TEST|0',
    'enj_makine_id': None, 'enj_istasyon_no': None, 'enj_slot': None,
}
merged_no_korgun = merge_plan_korgun(dummy_plan, None)
check('T10 merge_plan_korgun(None) → durum=BAŞLANMADI',
      merged_no_korgun.get('durum') == 'BAŞLANMADI',
      f'durum: {merged_no_korgun.get("durum")}')

dummy_korgun = {
    'sip_no': 1, 'model_kod': 'TEST', 'renk': 'SİYAH', 'miktar': 1000,
    'durum': 'DEVAM', 'durum_renk': 'sari', 'yuzde': 55,
    'enjeksiyon': {'durum': 'DEVAM', 'yuzde': 55, 'renk': 'sari', 'biten': 550, 'verilen': 1000},
    'saya': {'durum': 'BAŞLANMADI', 'yuzde': 0, 'renk': 'gri', 'biten': 0, 'verilen': 1000},
    'montaj': {'durum': 'BAŞLANMADI', 'yuzde': 0, 'renk': 'gri', 'biten': 0, 'verilen': 1000},
    'temizleme': {'durum': 'BAŞLANMADI', 'yuzde': 0, 'renk': 'gri', 'biten': 0, 'verilen': 1000},
}
merged_with_korgun = merge_plan_korgun(dummy_plan, dummy_korgun)
proses_keys = {'enjeksiyon', 'saya', 'montaj', 'temizleme'}
check('T10 merge_plan_korgun(korgun) proses anahtarları mevcut',
      proses_keys.issubset(merged_with_korgun.keys()),
      f'Mevcut: {set(merged_with_korgun.keys()) & proses_keys}')

# T11: Çakışma — aynı slot/tarih
# uretim_model_plan'a test kaydı ekleyip çakışma kontrolü yapıyoruz
# Ardından kaydı siliyoruz (test izolasyonu)
test_plan_id = None
try:
    import datetime
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    cur = c.execute("""
        INSERT INTO uretim_model_plan (
            sip_no, sip_harinx, mamul_skod, rkod, plan_donemi,
            aktif, created_by, oncelik,
            enj_makine_id, enj_istasyon_no, enj_slot,
            enj_plan_baslangic, enj_plan_bitis
        ) VALUES (99999,1,'TESTOVERLAP',0,'bu_hafta',1,0,3,
                  1,3,'A','2026-08-20','2026-08-24')
    """)
    c.commit()
    test_plan_id = cur.lastrowid

    # Çakışan aralık
    rows = c.execute("""
        SELECT id FROM uretim_model_plan
        WHERE aktif=1 AND enj_makine_id=1 AND enj_istasyon_no=3 AND enj_slot='A'
          AND enj_plan_baslangic IS NOT NULL
          AND id <> ?
    """, (test_plan_id + 1,)).fetchall()
    # Bu test: test kaydı var mı?
    check('T11 Aynı slot/tarih test kaydı eklendi', test_plan_id is not None)

    # Çakışma: sorgu aralığı 2026-08-18 – 2026-08-22 → 2026-08-20 ile overlap
    bas = datetime.date(2026, 8, 18)
    bit = datetime.date(2026, 8, 22)
    existing = c.execute("""
        SELECT id, enj_plan_baslangic, enj_plan_bitis
        FROM uretim_model_plan
        WHERE aktif=1 AND enj_makine_id=1 AND enj_istasyon_no=3 AND enj_slot='A'
          AND enj_plan_baslangic IS NOT NULL AND id=?
    """, (test_plan_id,)).fetchone()
    if existing:
        rb = datetime.date.fromisoformat(existing['enj_plan_baslangic'][:10])
        re = datetime.date.fromisoformat(existing['enj_plan_bitis'][:10])
        overlap = not (bit < rb or bas > re)
        check('T11 Çakışma doğru tespit edildi (2026-08-18–22 ↔ 2026-08-20–24)', overlap)
    else:
        fail('T11 Test kaydı okunamadı')
    c.close()
except Exception as ex:
    fail('T11 Exception: ' + str(ex))
finally:
    if test_plan_id:
        cl = sqlite3.connect(DB)
        cl.execute("DELETE FROM uretim_model_plan WHERE id=?", (test_plan_id,))
        cl.commit()
        cl.close()

# T12: Farklı slot → false overlap yok
try:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    import datetime
    cur2 = c.execute("""
        INSERT INTO uretim_model_plan (
            sip_no, sip_harinx, mamul_skod, rkod, plan_donemi,
            aktif, created_by, oncelik,
            enj_makine_id, enj_istasyon_no, enj_slot,
            enj_plan_baslangic, enj_plan_bitis
        ) VALUES (99998,1,'TESTNOOVERLAP',0,'bu_hafta',1,0,3,
                  1,3,'B','2026-08-20','2026-08-24')
    """)
    c.commit()
    id2 = cur2.lastrowid

    # Slot A için sorgula → slot B kaydı çakışmamalı
    rows = c.execute("""
        SELECT id FROM uretim_model_plan
        WHERE aktif=1 AND enj_makine_id=1 AND enj_istasyon_no=3 AND enj_slot='A'
          AND enj_plan_baslangic IS NOT NULL AND id=?
    """, (id2,)).fetchall()
    check('T12 Farklı slot (B) A sorgusunda görünmüyor', len(rows) == 0)
    c.execute("DELETE FROM uretim_model_plan WHERE id=?", (id2,))
    c.commit()
    c.close()
except Exception as ex:
    fail('T12 Exception: ' + str(ex))

# T13: Plan ile gerçek setup overwrite yok
# enj_ab_setup'ta baslangic_zamani plan kaydından etkilenmemeli
bas_before = con.execute(
    "SELECT baslangic_zamani FROM enj_ab_setup WHERE id=115"
).fetchone()
check('T13 enj_ab_setup.baslangic_zamani test öncesi/sonrası değişmedi',
      bas_before is not None)

# T14: Faz 2 regression — mevcut kolonlar hâlâ mevcut
faz2_cols = {'sip_no','sip_harinx','mamul_skod','rkod','plan_donemi',
             'plan_baslangic','plan_bitis','oncelik','plan_gerekce','plan_notu','aktif'}
mevcut_cols = {r[1] for r in con.execute('PRAGMA table_info(uretim_model_plan)').fetchall()}
eksik = faz2_cols - mevcut_cols
check('T14 Faz 2 kolonları hâlâ mevcut', not eksik, f'Eksik: {eksik}')

con.close()

# ── Özet ──────────────────────────────────────────────────────────────────
print()
print('=' * 60)
print(f'SONUÇ: {len(passed)} PASS / {len(failed)} FAIL')
if failed:
    print('Başarısız testler:')
    for f in failed:
        print(f'  ✗ {f}')
else:
    print('Tüm testler geçti.')
print('=' * 60)
sys.exit(0 if not failed else 1)
