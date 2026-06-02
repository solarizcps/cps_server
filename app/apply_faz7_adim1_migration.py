# -*- coding: utf-8 -*-
"""
CPS DEV - FAZ 7 ADIM 1: STANDART SURE DB MIGRATION
====================================================

YAPILACAK:
  ALTER TABLE proses_kategori ADD COLUMN standart_saniye REAL DEFAULT NULL
  
  Mevcut 10 satir DOKUNULMUYOR — sadece NULL kolon eklenir.
  Yeni proses ekleme/standart sure guncellenmesi ADIM 2-3'te olacak.

DOKUNULMAYAN:
  - emir_alt_proses, uretim_kayit, sablon_proses
  - sistem_kullanici, pers_kullanici, usta_kullanici
  - Hicbir veri silinmiyor, hicbir mevcut kolon degismiyor

Idempotent: Kolon zaten varsa SKIP.
Yedek: mock_data.db.YEDEK_FAZ7_<ts>
"""
import sys
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_DB = PROJECT_ROOT / "mock_data.db"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 7 ADIM 1: STANDART SURE DB MIGRATION")
    print("=" * 60)

    if not TARGET_DB.exists():
        print(f"  [HATA] DB dosyasi yok: {TARGET_DB}")
        return 1

    print(f"  DB: {TARGET_DB}")
    print(f"  Mevcut boyut: {TARGET_DB.stat().st_size} byte")

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")
    
    conn = sqlite3.connect(str(TARGET_DB))
    cur = conn.cursor()
    
    # 1. proses_kategori tablosu var mi
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='proses_kategori'")
    if not cur.fetchone():
        print("  [HATA] proses_kategori tablosu yok!")
        conn.close()
        return 1
    print("  [OK] proses_kategori tablosu mevcut")
    
    # 2. Mevcut satir sayisi
    cur.execute("SELECT COUNT(*) FROM proses_kategori")
    mevcut_satir = cur.fetchone()[0]
    print(f"  [OK] Mevcut satir sayisi: {mevcut_satir}")
    
    # 3. Mevcut kolonlar
    cur.execute("PRAGMA table_info(proses_kategori)")
    cols = [c[1] for c in cur.fetchall()]
    print(f"  [OK] Mevcut kolonlar: {', '.join(cols)}")
    
    # 4. IDEMPOTENT: standart_saniye zaten var mi
    if 'standart_saniye' in cols:
        conn.close()
        print()
        print("  [SKIP] standart_saniye kolonu zaten var, migration atland.")
        print("=" * 60)
        return 0
    
    # 5. Mevcut veri ornekleri (yedek niyetine)
    cur.execute("SELECT proses_kod, proses_adi, kategori, sira FROM proses_kategori ORDER BY kategori, sira LIMIT 12")
    mevcut_veri = cur.fetchall()
    print()
    print("  Mevcut veri ornegi:")
    for r in mevcut_veri:
        print(f"    {r[0]} | {r[1]:<15} | {r[2]:<8} | sira={r[3]}")
    
    conn.close()

    # ============================================================
    # YEDEK
    # ============================================================
    print()
    print("=== YEDEK ===")
    backup_path = TARGET_DB.with_suffix(f".db.YEDEK_FAZ7_{ts}")
    shutil.copy2(str(TARGET_DB), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # MIGRATION
    # ============================================================
    print()
    print("=== MIGRATION ===")
    conn = sqlite3.connect(str(TARGET_DB))
    cur = conn.cursor()
    
    try:
        cur.execute("ALTER TABLE proses_kategori ADD COLUMN standart_saniye REAL DEFAULT NULL")
        conn.commit()
        print("  [OK] standart_saniye REAL DEFAULT NULL kolonu eklendi")
    except Exception as e:
        print(f"  [HATA] ALTER TABLE: {e}")
        conn.close()
        return 1

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    
    # 1. Yeni kolon var mi
    cur.execute("PRAGMA table_info(proses_kategori)")
    yeni_cols = [c[1] for c in cur.fetchall()]
    print(f"  Yeni kolon listesi: {', '.join(yeni_cols)}")
    
    if 'standart_saniye' in yeni_cols:
        print("  [OK] standart_saniye kolonu mevcut")
    else:
        print("  [HATA] standart_saniye kolonu eklenmedi!")
        conn.close()
        return 1
    
    # 2. Mevcut satir sayisi BOZULMADI mi
    cur.execute("SELECT COUNT(*) FROM proses_kategori")
    yeni_satir = cur.fetchone()[0]
    print(f"  [OK] Yeni satir sayisi: {yeni_satir} (eski: {mevcut_satir})")
    if yeni_satir != mevcut_satir:
        print("  [HATA] Satir sayisi degismis!")
        conn.close()
        return 1
    
    # 3. Mevcut veriler hala var mi (1 satir kontrol)
    cur.execute("SELECT proses_kod, proses_adi, kategori, sira, standart_saniye FROM proses_kategori ORDER BY kategori, sira LIMIT 12")
    yeni_veri = cur.fetchall()
    print()
    print("  Yeni veri durumu:")
    for r in yeni_veri:
        print(f"    {r[0]} | {r[1]:<15} | {r[2]:<8} | sira={r[3]} | std_sn={r[4]}")
    
    # 4. Tum standart_saniye degerleri NULL mi (default kontrol)
    cur.execute("SELECT COUNT(*) FROM proses_kategori WHERE standart_saniye IS NULL")
    null_say = cur.fetchone()[0]
    if null_say == yeni_satir:
        print(f"  [OK] Tum {null_say} satirin standart_saniye degeri NULL (Adem dolduracak)")
    else:
        print(f"  [UYARI] {yeni_satir - null_say} satirin degeri NULL degil")
    
    # 5. Diger tablolar BOZULMADI mi (5 random)
    diger_tablolar = ['emir_alt_proses', 'uretim_kayit', 'sablon', 'sistem_kullanici', 'siparis_darbogaz']
    print()
    print("  Diger tablolar (regression):")
    for t in diger_tablolar:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            cnt = cur.fetchone()[0]
            print(f"    [OK] {t}: {cnt} satir")
        except Exception as e:
            print(f"    [HATA] {t}: {e}")
            conn.close()
            return 1
    
    conn.close()

    # ============================================================
    # TAMAMLANDI
    # ============================================================
    new_size = TARGET_DB.stat().st_size
    print()
    print("=" * 60)
    print("[OK] FAZ 7 ADIM 1 DB MIGRATION TAMAM")
    print("=" * 60)
    print()
    print(f"  DB boyut: {new_size} byte")
    print(f"  Yedek:    {backup_path.name}")
    print()
    print("Sonraki:")
    print("  ADIM 2: Backend endpoint (modules/yonetim/routes.py)")
    print("    - GET  /yonetim/proses-kategori/liste")
    print("    - PUT  /yonetim/proses-kategori/<kod>/sure")
    print("    - POST /yonetim/proses-kategori/yeni")
    print()
    print(f"Rollback (manuel):")
    print(f"  Stop-Process Flask")
    print(f"  Copy-Item {backup_path.name} mock_data.db -Force")
    print(f"  Start Flask")
    return 0


if __name__ == "__main__":
    sys.exit(main())
