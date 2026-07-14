# -*- coding: utf-8 -*-
"""
Migration 100 — NexGen: nexgen_formul.urun_ailesi kolonu
=========================================================
[1] Zaman damgali tam DB yedeği alinir (boyut + SHA-256 dogrulamasi).
[2] nexgen_formul tablosuna urun_ailesi TEXT NULL kolonu eklenir.
    V1 izin verilen degerler: TERLIK, TABAN
    (DB-level CHECK constraint YOK — uygulama katmaninda dogrulanir,
     SQLite mevcut tablo yeniden olusturulmasini gerektiren CONSTRAINT
     eklemeyi desteklemez.)

Backfill:
  - Mevcut formullerin urun_ailesi alani NULL birakilir.
  - Otomatik tahmin yapilmaz; elle veya sonraki migration ile doldurulabilir.
  - id=3 AYM, id=5 TERLIK, id=6 TABAN, id=7 DOKME gibi kayitlar
    NULL kalir; admin tarafindan tamamlanmasi gerekir.

Guvenlik:
  - Yedek alinmadan devam edilmez (boyut sifirsa HATA verir).
  - nexgen_stok_hareket, nexgen_recete_kalem, nexgen_rf_renk dokunulmaz.
  - Eski formul kayitlari (durum, onay_durumu) degistirilmez.
  - Idempotent: tekrar calistirilabilir.

Rollback:
  SQLite ALTER ADD COLUMN geri alinamaz.
  Tam geri donus icin: shutil.copy2(yedek_dosyasi, DB_PATH)

ENTEGRASYON FAZ ZORUNLU KABUL KRİTERİ — bkz. Migration 099 docstring.
  nexgen_formul.kod → otomatik, salt okunur, transaction-safe
  nexgen_formul.ad  → manuel, zorunlu, strip() uygulanir
  nexgen_formul.urun_ailesi → V1: TERLIK | TABAN (uygulama katmaninda dogrulama)
"""

import sqlite3
import os
import shutil
import hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]
    return kolon in cols


def _sha256(dosya):
    h = hashlib.sha256()
    with open(dosya, 'rb') as f:
        for blok in iter(lambda: f.read(65536), b''):
            h.update(blok)
    return h.hexdigest()


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    # ── [0] Yedek al — Migration 100 kucuk olsa da yedeksiz calistirilmaz ──
    print("\n[0] Zaman damgali DB yedegi aliniyor...")
    ts  = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB_PATH.replace('.db', f'_backup_pre100_{ts}.db')
    try:
        shutil.copy2(DB_PATH, bak)
        bak_boyut  = os.path.getsize(bak)
        kaynak_boyut = os.path.getsize(DB_PATH)
        if bak_boyut == 0:
            raise RuntimeError("Yedek dosyasi bos — iptal edildi")
        bak_hash = _sha256(bak)
        src_hash = _sha256(DB_PATH)
        if bak_hash != src_hash:
            raise RuntimeError(f"Hash uyusmazligi: kaynak={src_hash[:16]} yedek={bak_hash[:16]}")
        print(f"  OK    Yedek: {os.path.basename(bak)}")
        print(f"  OK    Boyut: {bak_boyut:,} byte")
        print(f"  OK    SHA-256: {bak_hash}")
        print(f"  INFO  Geri yukleme: shutil.copy2(r'{bak}', r'{DB_PATH}')")
    except Exception as e:
        print(f"  HATA  Yedek alinamadi: {e}")
        raise SystemExit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n" + "=" * 65)
    print("Migration 100 - nexgen_formul.urun_ailesi kolonu")
    print("=" * 65)

    # Guvenlik sayimi — dokunulmaz tablolar
    sh_once  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    rk_once  = cur.execute("SELECT COUNT(*) FROM nexgen_recete_kalem").fetchone()[0]
    rf_once  = cur.execute("SELECT COUNT(*) FROM nexgen_rf_renk").fetchone()[0]
    frm_once = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    print(f"\n[ONCESI] stok_hareket={sh_once}  recete_kalem={rk_once}  "
          f"rf_renk={rf_once}  formul={frm_once}")

    # ── [1] urun_ailesi kolonu ──────────────────────────────────────
    print("\n[1] nexgen_formul.urun_ailesi kolonu:")
    if not _kolon_var(cur, 'nexgen_formul', 'urun_ailesi'):
        cur.execute("ALTER TABLE nexgen_formul ADD COLUMN urun_ailesi TEXT")
        con.commit()
        print("  OK    urun_ailesi TEXT NULL eklendi")
        print("  INFO  Izin verilen V1 degerleri: TERLIK, TABAN")
        print("  INFO  Mevcut kayitlar NULL — otomatik backfill yapilmadi")
    else:
        print("  SKIP  urun_ailesi zaten var")

    # Dogrulama
    cols = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_formul)").fetchall()]
    assert 'urun_ailesi' in cols, "HATA: urun_ailesi kolonu eklenemedi!"
    print(f"  OK    nexgen_formul kolonlari: {cols}")

    # Mevcut formul kayitlarini raporla (backfill icin)
    formul_rows = cur.execute(
        "SELECT id, kod, ad, durum, urun_ailesi FROM nexgen_formul WHERE aktif=1 ORDER BY id"
    ).fetchall()
    print("\n[2] Mevcut formul kayitlari (urun_ailesi = NULL bekleniyor):")
    for r in formul_rows:
        ua = r['urun_ailesi'] or 'NULL'
        print(f"  id={r['id']:3}  kod={r['kod']:8}  ad={r['ad']:20}  durum={r['durum']:8}  urun_ailesi={ua}")

    # Guvenlik sayimi — degismemeli
    sh_son  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    rk_son  = cur.execute("SELECT COUNT(*) FROM nexgen_recete_kalem").fetchone()[0]
    rf_son  = cur.execute("SELECT COUNT(*) FROM nexgen_rf_renk").fetchone()[0]
    frm_son = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    print(f"\n[SONRASI] stok_hareket={sh_son}  recete_kalem={rk_son}  "
          f"rf_renk={rf_son}  formul={frm_son}")
    assert sh_son == sh_once,   "HATA: stok_hareket sayisi degisti!"
    assert rk_son == rk_once,   "HATA: recete_kalem sayisi degisti!"
    assert rf_son == rf_once,   "HATA: rf_renk sayisi degisti!"
    assert frm_son == frm_once, "HATA: formul sayisi degisti!"

    # schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version, aciklama) "
                    "VALUES(100, 'nexgen_formul.urun_ailesi TEXT NULL')")
        con.commit()
        print("\n  OK    schema_migrations version=100")
    except Exception as e:
        print(f"\n  WARN  schema_migrations: {e}")

    print("\n" + "=" * 65)
    print("OZET: nexgen_formul.urun_ailesi kolonu hazir")
    print("  Izin verilen V1 degerleri: TERLIK, TABAN")
    print("  Backfill gerekiyor — admin tarafindan tamamlanmali")
    print("=" * 65)
    print("Migration 100 tamamlandi.\n")

    con.close()


if __name__ == '__main__':
    run()
