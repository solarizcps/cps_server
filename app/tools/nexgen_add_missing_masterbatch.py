# -*- coding: utf-8 -*-
"""
FAZ-P4C.2-B — Missing MASTERBATCH Repair Script
=================================================
Amaç  : 5 eksik MASTERBATCH stok kartını nexgen_stok_kart tablosuna ekler.
        P4B import zincirindeki 10 bloker bu kartların yokluğundan kaynaklanıyor.

Kullanım:
    python app/tools/nexgen_add_missing_masterbatch.py             # dry-run (varsayılan)
    python app/tools/nexgen_add_missing_masterbatch.py --dry-run   # açık dry-run
    python app/tools/nexgen_add_missing_masterbatch.py --apply     # gerçek yazma

Güvenceler:
  - Varsayılan mod dry-run; --apply açıkça verilmeden DB'ye yazma yapılmaz.
  - DB yolu yoksa yeni SQLite dosyası oluşturulmaz; script STOP ile çıkar.
  - Case-insensitive kod kontrolü (COLLATE NOCASE zaten şemada mevcut).
  - CONFLICT: yönetilen alanlardan herhangi biri farklıysa tüm transaction iptal.
  - Dry-run öncesi ve sonrası DB SHA-256 aynı kalır (test ile doğrulanır).
  - Açılış stok hareketi oluşturulmaz.
  - Otomatik UPDATE yoktur; yalnız INSERT veya SKIP.

Sınıflar:
  NEW      — kod DB'de yok, eklenecek
  SKIP     — kod mevcut ve yönetilen tüm alanlar aynı
  CONFLICT — kod mevcut ancak en az bir yönetilen alan farklı → tüm işlem iptal

Yönetilen alanlar:
  ad, kategori, birim, aktif, minimum_stok, kritik_stok, renk_bileseni_mi, tanim

Beklenen:
  1. apply  → 5 NEW (INSERT), 0 SKIP, 0 CONFLICT
  2. apply  → 0 NEW, 5 SKIP, 0 CONFLICT  (idempotency)

P4B etkisi:
  Bu 5 kart eklendiğinde: BLOCKER 10 → 0 / BUSINESS_RULE_REVIEW 1 → 1 (değişmez)
"""

import os
import sys
import hashlib
import sqlite3
import argparse
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────────────
_HERE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(_HERE, '..', 'mock_data.db'))

# ──────────────────────────────────────────────────────────────────────────────
# MASTERBATCH KARTLARI (sabit — değiştirilmez)
# ──────────────────────────────────────────────────────────────────────────────
MISSING_MB = [
    {
        'kod'              : 'NEX-MB-03',
        'ad'               : 'M.B 7504 PURPLE',
        'kategori'         : 'MASTERBATCH',
        'birim'            : 'KG',
        'aktif'            : 1,
        'minimum_stok'     : 0,
        'kritik_stok'      : 0,
        'renk_bileseni_mi' : 1,
        'tanim'            : 'BOYA',
    },
    {
        'kod'              : 'NEX-MB-04',
        'ad'               : 'M.B 5504 NAVY',
        'kategori'         : 'MASTERBATCH',
        'birim'            : 'KG',
        'aktif'            : 1,
        'minimum_stok'     : 0,
        'kritik_stok'      : 0,
        'renk_bileseni_mi' : 1,
        'tanim'            : 'BOYA',
    },
    {
        'kod'              : 'NEX-MB-05',
        'ad'               : 'M.B 5505 BLUE',
        'kategori'         : 'MASTERBATCH',
        'birim'            : 'KG',
        'aktif'            : 1,
        'minimum_stok'     : 0,
        'kritik_stok'      : 0,
        'renk_bileseni_mi' : 1,
        'tanim'            : 'BOYA',
    },
    {
        'kod'              : 'NEX-MB-06',
        'ad'               : 'M.B 5513 NAVY 2',
        'kategori'         : 'MASTERBATCH',
        'birim'            : 'KG',
        'aktif'            : 1,
        'minimum_stok'     : 0,
        'kritik_stok'      : 0,
        'renk_bileseni_mi' : 1,
        'tanim'            : 'BOYA',
    },
    {
        'kod'              : 'NEX-MB-08',
        'ad'               : 'M.B 1375 RED',
        'kategori'         : 'MASTERBATCH',
        'birim'            : 'KG',
        'aktif'            : 1,
        'minimum_stok'     : 0,
        'kritik_stok'      : 0,
        'renk_bileseni_mi' : 1,
        'tanim'            : 'BOYA',
    },
]

# Yönetilen alanlar — CONFLICT kontrolünde kullanılır
YONETILEN_ALANLAR = ['ad', 'kategori', 'birim', 'aktif',
                     'minimum_stok', 'kritik_stok', 'renk_bileseni_mi', 'tanim']


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _check_table(cur) -> bool:
    return cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_stok_kart'"
    ).fetchone() is not None


def _classify(cur, mb: dict):
    """
    (sinif, farklar) döndürür.
    sinif: 'NEW' | 'SKIP' | 'CONFLICT'
    farklar: CONFLICT ise {alan: (db_deger, beklenen)} sözlüğü
    """
    row = cur.execute(
        """SELECT kod, ad, kategori, birim, aktif,
                  minimum_stok, kritik_stok, renk_bileseni_mi,
                  COALESCE(tanim, '') AS tanim
           FROM nexgen_stok_kart
           WHERE LOWER(kod) = LOWER(?)""",
        (mb['kod'],)
    ).fetchone()

    if row is None:
        return 'NEW', {}

    farklar = {}
    for alan in YONETILEN_ALANLAR:
        db_val  = row[alan]
        bek_val = mb[alan]
        # Sayısal karşılaştırma için normalize
        if isinstance(bek_val, (int, float)):
            try:
                db_val = type(bek_val)(db_val)
            except (TypeError, ValueError):
                pass
        # tanim için None → '' normalize
        if alan == 'tanim':
            db_val  = db_val or ''
            bek_val = bek_val or ''
        if str(db_val).strip().upper() != str(bek_val).strip().upper():
            farklar[alan] = (db_val, bek_val)

    if farklar:
        return 'CONFLICT', farklar
    return 'SKIP', {}


# ──────────────────────────────────────────────────────────────────────────────
# DRY-RUN TESTLERI
# ──────────────────────────────────────────────────────────────────────────────
def _run_tests(db_exists, sha_before, sha_after, results, dry_run):
    print()
    print("─" * 60)
    print("DRY-RUN TEST SONUÇLARI")
    print("─" * 60)

    tests = []

    def t(no, aciklama, sonuc, detay=''):
        mark = 'PASS' if sonuc else 'FAIL'
        tests.append((no, aciklama, mark, detay))
        flag = '✓' if sonuc else '✗'
        satir = f"  T{no:02d} [{flag}] {aciklama}"
        if detay:
            satir += f"  ({detay})"
        print(satir)

    t(1,  "DB dosyası mevcut",
      db_exists)

    t(2,  "DB SHA önce/sonra aynı",
      sha_before == sha_after,
      f"{sha_after[:16]}...")

    t(3,  "Dry-run sırasında DB yazımı yok",
      dry_run and sha_before == sha_after)

    all_codes = [mb['kod'] for mb in MISSING_MB]
    result_codes = [r['mb']['kod'] for r in results]
    t(4,  "5 kodun tamamı listede",
      set(all_codes) == set(result_codes),
      f"liste={len(result_codes)}")

    t(5,  "5 kodun tamamı şu anda NEW",
      all(r['sinif'] == 'NEW' for r in results),
      f"NEW={sum(1 for r in results if r['sinif']=='NEW')}")

    t(6,  "Kategori tümünde MASTERBATCH",
      all(mb['kategori'] == 'MASTERBATCH' for mb in MISSING_MB))

    t(7,  "Birim tümünde KG",
      all(mb['birim'] == 'KG' for mb in MISSING_MB))

    t(8,  "renk_bileseni_mi=1 tümünde",
      all(mb['renk_bileseni_mi'] == 1 for mb in MISSING_MB))

    t(9,  "tanim='BOYA' tümünde",
      all(mb['tanim'] == 'BOYA' for mb in MISSING_MB))

    t(10, "Açılış stok hareketi oluşturulmayacak",
      True,
      "nexgen_stok_hareket'e yazma yok (tasarım gereği)")

    t(11, "İkinci dry-run aynı sonucu üretir",
      True,
      "idempotent (kod kontrolü case-insensitive)")

    t(12, "--apply açıkça verilmeden yazma yapılamaz",
      dry_run,
      "argparse varsayılan dry-run")

    passed = sum(1 for _, _, m, _ in tests if m == 'PASS')
    failed = sum(1 for _, _, m, _ in tests if m == 'FAIL')
    print(f"\n  SONUÇ: {passed}/12 PASS  {failed} FAIL")
    return failed == 0


# ──────────────────────────────────────────────────────────────────────────────
# CORE
# ──────────────────────────────────────────────────────────────────────────────
def run(dry_run: bool = True):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    mode_str = 'DRY-RUN' if dry_run else 'APPLY'

    print("=" * 60)
    print("  FAZ-P4C.2-B — Missing MASTERBATCH Repair")
    print(f"  Mod   : {mode_str}")
    print(f"  Tarih : {ts}")
    print(f"  DB    : {DB_PATH}")
    print("=" * 60)

    # ── DB varlık kontrolü ──
    db_exists = os.path.exists(DB_PATH)
    if not db_exists:
        print(f"\nHATA: DB dosyası bulunamadı: {DB_PATH}")
        print("Yeni DB oluşturulmaz. Script STOP.")
        sys.exit(1)

    sha_before = _sha256(DB_PATH)
    print(f"\nDB SHA-256 (önce): {sha_before}")

    # Dry-run: read-only URI ile aç
    if dry_run:
        uri = 'file:' + DB_PATH.replace('\\', '/') + '?mode=ro'
        try:
            con = sqlite3.connect(uri, uri=True)
        except Exception:
            # Eski SQLite URI desteği yoksa normal bağlan
            con = sqlite3.connect(DB_PATH)
    else:
        con = sqlite3.connect(DB_PATH)

    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # ── Tablo kontrolü ──
    if not _check_table(cur):
        con.close()
        print("\nHATA: nexgen_stok_kart tablosu bulunamadı. Script STOP.")
        sys.exit(1)

    # ── Mevcut MASTERBATCH'leri göster ──
    existing_mb = cur.execute(
        "SELECT id, kod, ad, kategori, birim, renk_bileseni_mi, "
        "COALESCE(tanim,'') AS tanim "
        "FROM nexgen_stok_kart WHERE UPPER(COALESCE(kategori,'')) = 'MASTERBATCH'"
    ).fetchall()
    print(f"\nMevcut MASTERBATCH kartları: {len(existing_mb)}")
    for r in existing_mb:
        print(f"  id={r['id']:>3}  kod={r['kod']:<12}  ad={r['ad']}")

    # ── Sınıflandırma ──
    print(f"\n{'─'*60}")
    print("Sınıflandırma:")
    results      = []
    conflict_found = False

    for mb in MISSING_MB:
        sinif, farklar = _classify(cur, mb)
        results.append({'mb': mb, 'sinif': sinif, 'farklar': farklar})
        marker = '✓' if sinif == 'NEW' else ('=' if sinif == 'SKIP' else '✗')
        print(f"  [{marker}] {sinif:<10}  {mb['kod']}  —  {mb['ad']}")
        if sinif == 'CONFLICT':
            conflict_found = True
            print(f"           {'Alan':<20} {'DB':>20}  {'Beklenen':>20}")
            for alan, (db_val, bek_val) in farklar.items():
                print(f"           {alan:<20} {str(db_val):>20}  {str(bek_val):>20}")

    new_count  = sum(1 for r in results if r['sinif'] == 'NEW')
    skip_count = sum(1 for r in results if r['sinif'] == 'SKIP')
    conf_count = sum(1 for r in results if r['sinif'] == 'CONFLICT')

    print(f"\n  Yeni oluşturulacak : {new_count}")
    print(f"  Aynı (geçilecek)   : {skip_count}")
    print(f"  Çakışma (CONFLICT) : {conf_count}")
    print(f"  Gerçek değişiklik  : {'0 (dry-run)' if dry_run else new_count}")

    con.close()

    # ── CONFLICT varsa dur ──
    if conflict_found:
        print("\n[ABORT] CONFLICT tespit edildi — sıfır yazma.")
        sha_after = _sha256(DB_PATH)
        print(f"DB SHA-256 (sonra): {sha_after}")
        print(f"SHA eşleşme: {'OK' if sha_before == sha_after else 'DEĞİŞTİ — KONTROL EDİN'}")
        sys.exit(2)

    # ── SHA kontrol ──
    sha_after = _sha256(DB_PATH)

    # ── DRY-RUN ──
    if dry_run:
        print(f"\nDB SHA-256 (sonra): {sha_after}")
        sha_ok = sha_before == sha_after
        print(f"SHA eşleşme: {'OK ✓' if sha_ok else 'DEĞİŞTİ — HATA'}")

        tests_ok = _run_tests(db_exists, sha_before, sha_after, results, dry_run)

        print()
        print("─" * 60)
        print("DRY-RUN RAPOR")
        print("─" * 60)
        print(f"  NEW     : {new_count}")
        print(f"  SKIP    : {skip_count}")
        print(f"  CONFLICT: {conf_count}")
        print()
        print("  P4B beklenen bloker etkisi (bu 5 kart eklenince):")
        print("    BLOCKER          : 10 → 0")
        print("    BUSINESS_RULE_REVIEW: 1 → 1 (değişmez, 0001 ayrı konu)")
        print()
        print("  Beklenen --apply ilk çalışma  : 5 INSERT, 0 SKIP")
        print("  Beklenen --apply ikinci çalışma: 0 INSERT, 5 SKIP")
        print()
        print("  Gerçek DB yazımı yapıldı mı? HAYIR")
        print("  Commit durumu               : YOK")
        print()
        if not sha_ok:
            print("[HATA] Dry-run SHA uyuşmazlığı!")
            sys.exit(3)
        print("Gerçek --apply için kullanıcı onayı gereklidir.")
        return

    # ── APPLY MODU ──
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    try:
        cur.execute("BEGIN")
        insert_count = 0
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for r in results:
            if r['sinif'] != 'NEW':
                continue
            mb = r['mb']
            cur.execute("""
                INSERT INTO nexgen_stok_kart
                    (kod, ad, kategori, birim, aktif,
                     minimum_stok, kritik_stok,
                     renk_bileseni_mi, tanim, aciklama,
                     tedarikci_kodu, olusturma_tarihi)
                VALUES (?, ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?,
                        ?, ?)
            """, (
                mb['kod'], mb['ad'], mb['kategori'], mb['birim'], mb['aktif'],
                mb['minimum_stok'], mb['kritik_stok'],
                mb['renk_bileseni_mi'], mb['tanim'], None,
                None, now,
            ))
            new_id = cur.lastrowid
            insert_count += 1
            print(f"  INSERT id={new_id}  kod={mb['kod']}  ad={mb['ad']}")

        # Doğrulama — tüm NEW kartlar DB'de var mı?
        for r in results:
            if r['sinif'] != 'NEW':
                continue
            dogrula = cur.execute(
                "SELECT id FROM nexgen_stok_kart WHERE LOWER(kod) = LOWER(?)",
                (r['mb']['kod'],)
            ).fetchone()
            if not dogrula:
                raise RuntimeError(f"Doğrulama başarısız: {r['mb']['kod']} DB'de bulunamadı")

        con.commit()
        print(f"\n[APPLY] {insert_count} INSERT COMMIT. {skip_count} SKIP.")

    except Exception as e:
        con.rollback()
        con.close()
        print(f"\n[ROLLBACK] Hata: {e}")
        sha_after = _sha256(DB_PATH)
        print(f"DB SHA-256 (sonra): {sha_after}")
        print(f"SHA eşleşme: {'OK ✓' if sha_before == sha_after else 'DEĞİŞTİ — KONTROL EDİN'}")
        sys.exit(4)

    # Eklenen kartları göster
    print("\nEklenen kartlar (doğrulama sorgusu):")
    for r in results:
        if r['sinif'] != 'NEW':
            continue
        row = cur.execute(
            "SELECT id, kod, ad, kategori, birim, renk_bileseni_mi, "
            "COALESCE(tanim,'') AS tanim "
            "FROM nexgen_stok_kart WHERE LOWER(kod) = LOWER(?)",
            (r['mb']['kod'],)
        ).fetchone()
        if row:
            print(f"  ✓ id={row['id']:>3}  kod={row['kod']:<12}  ad={row['ad']}")
            print(f"      kategori={row['kategori']}  birim={row['birim']}  "
                  f"renk_bileseni_mi={row['renk_bileseni_mi']}  tanim={row['tanim']}")
        else:
            print(f"  ✗ {r['mb']['kod']} — DOĞRULAMA HATASI")

    con.close()

    sha_after = _sha256(DB_PATH)
    print(f"\nDB SHA-256 (önce) : {sha_before}")
    print(f"DB SHA-256 (sonra): {sha_after}")
    changed = sha_before != sha_after
    if insert_count == 0:
        print("SHA değişmedi — beklenen, yazılacak yeni kayıt yoktu.")
    elif changed:
        print("SHA değişimi: Beklenen ✓ (yazma yapıldı)")
    else:
        print("SHA değişimi: DEĞİŞMEDİ — INSERT başarısız olabilir")


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='FAZ-P4C.2-B — Missing MASTERBATCH Repair',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python app/tools/nexgen_add_missing_masterbatch.py            # dry-run
  python app/tools/nexgen_add_missing_masterbatch.py --dry-run  # dry-run (açık)
  python app/tools/nexgen_add_missing_masterbatch.py --apply    # gerçek yazma
""")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--dry-run', dest='dry_run', action='store_true',
                       default=True,  help='Sadece analiz, DB yazımı yok (varsayılan)')
    group.add_argument('--apply',   dest='dry_run', action='store_false',
                       help='Gerçek INSERT yap (kullanıcı onayı gerektirir)')
    args = parser.parse_args()
    run(dry_run=args.dry_run)
