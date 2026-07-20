# -*- coding: utf-8 -*-
"""
Migration 098 — NexGen FAZ-BOYA-RECETESI-02B: RF Revizyon Altyapisi
=====================================================================
[1] nexgen_rf_revizyon    — yeni tablo: boya recetesi revizyon snapshot
[2] nexgen_rf_renk        — aktif_rev_no INTEGER DEFAULT 0
[3] nexgen_uretim_plan    — kalip_carpani REAL, rf_rev_no INTEGER
[4] nexgen_uretim_batch   — rf_renk_id INTEGER, rf_rev_no INTEGER, kalip_carpani REAL
[5] nexgen_rf_kullanim    — rf_rev_no INTEGER, kalip_carpani REAL
[6] Mevcut aktif + kalemli RF'ler icin REV-1 seed (idempotent)

Kurallar:
  - Idempotent: tekrar calistirilabilir, duplicate olusturmaz
  - Mevcut RF verileri silinmez, degistirilmez
  - Kalemsiz RF'lere REV-1 uydurulmaz; audit raporunda gosterilir
  - AR-GE tablet route/template DOKUNULMAZ
  - stok_hareket DOKUNULMAZ
  - nexgen_recete_kalem DOKUNULMAZ
"""

import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def _tablo_var(cur, tablo):
    r = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return r is not None


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 70)
    print("Migration 098 — nexgen_rf_revizyon altyapisi")
    print(f"DB: {os.path.abspath(DB_PATH)}")
    print("=" * 70)

    # ── Once guvenlik sayimi ─────────────────────────────────────────────
    rf_onceki    = cur.execute("SELECT COUNT(*) FROM nexgen_rf_renk").fetchone()[0]
    rfk_onceki   = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kalem").fetchone()[0]
    sh_onceki    = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"\n[ONCESI] rf_renk={rf_onceki}  rf_kalem={rfk_onceki}  stok_hareket={sh_onceki}")

    # ═══════════════════════════════════════════════════════════════════
    # [1] nexgen_rf_revizyon — yeni tablo
    # ═══════════════════════════════════════════════════════════════════
    print("\n[1] nexgen_rf_revizyon tablosu:")
    if not _tablo_var(cur, 'nexgen_rf_revizyon'):
        cur.execute("""
            CREATE TABLE nexgen_rf_revizyon (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                rf_renk_id       INTEGER NOT NULL,
                rev_no           INTEGER NOT NULL,
                durum            TEXT    NOT NULL DEFAULT 'TASLAK',
                pigmentler_json  TEXT    NOT NULL DEFAULT '[]',
                neden            TEXT,
                aciklama         TEXT,
                kalip_carpani    REAL,
                formul_id        INTEGER,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                onaylayan_id     INTEGER,
                onay_tarihi      TEXT,
                kilitli_mi       INTEGER NOT NULL DEFAULT 0,
                aktif            INTEGER NOT NULL DEFAULT 1,
                UNIQUE (rf_renk_id, rev_no)
            )
        """)
        con.commit()
        print("  OK    nexgen_rf_revizyon olusturuldu")
    else:
        print("  SKIP  nexgen_rf_revizyon zaten var")
        # Eksik kolon kontrolu (sonradan ekleme senaryosu)
        for kolon, tanim in [
            ('kalip_carpani',    'REAL'),
            ('formul_id',        'INTEGER'),
            ('neden',            'TEXT'),
            ('aciklama',         'TEXT'),
            ('onaylayan_id',     'INTEGER'),
            ('onay_tarihi',      'TEXT'),
            ('aktif',            'INTEGER NOT NULL DEFAULT 1'),
        ]:
            if not _kolon_var(cur, 'nexgen_rf_revizyon', kolon):
                cur.execute(f"ALTER TABLE nexgen_rf_revizyon ADD COLUMN {kolon} {tanim}")
                con.commit()
                print(f"  OK    nexgen_rf_revizyon.{kolon} eklendi")

    # ── Indexler ────────────────────────────────────────────────────────
    indexler = [
        ("idx_nrfrev_rf",      "nexgen_rf_revizyon(rf_renk_id)"),
        ("idx_nrfrev_durum",   "nexgen_rf_revizyon(durum)"),
        ("idx_nrfrev_kilitli", "nexgen_rf_revizyon(kilitli_mi)"),
    ]
    for idx_ad, idx_hedef in indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print(f"  OK    {len(indexler)} index")

    # ═══════════════════════════════════════════════════════════════════
    # [2] nexgen_rf_renk.aktif_rev_no
    # ═══════════════════════════════════════════════════════════════════
    print("\n[2] nexgen_rf_renk.aktif_rev_no:")
    if not _kolon_var(cur, 'nexgen_rf_renk', 'aktif_rev_no'):
        cur.execute("ALTER TABLE nexgen_rf_renk ADD COLUMN aktif_rev_no INTEGER NOT NULL DEFAULT 0")
        con.commit()
        print("  OK    aktif_rev_no eklendi")
    else:
        print("  SKIP  aktif_rev_no zaten var")

    # ═══════════════════════════════════════════════════════════════════
    # [3] nexgen_uretim_plan — kalip_carpani + rf_rev_no
    # ═══════════════════════════════════════════════════════════════════
    print("\n[3] nexgen_uretim_plan yeni kolonlar:")
    for kolon, tanim in [('kalip_carpani', 'REAL'), ('rf_rev_no', 'INTEGER')]:
        if not _kolon_var(cur, 'nexgen_uretim_plan', kolon):
            cur.execute(f"ALTER TABLE nexgen_uretim_plan ADD COLUMN {kolon} {tanim}")
            con.commit()
            print(f"  OK    nexgen_uretim_plan.{kolon} eklendi")
        else:
            print(f"  SKIP  {kolon} zaten var")

    # ═══════════════════════════════════════════════════════════════════
    # [4] nexgen_uretim_batch — rf_renk_id + rf_rev_no + kalip_carpani
    # ═══════════════════════════════════════════════════════════════════
    print("\n[4] nexgen_uretim_batch yeni kolonlar:")
    for kolon, tanim in [
        ('rf_renk_id',    'INTEGER'),
        ('rf_rev_no',     'INTEGER'),
        ('kalip_carpani', 'REAL'),
    ]:
        if not _kolon_var(cur, 'nexgen_uretim_batch', kolon):
            cur.execute(f"ALTER TABLE nexgen_uretim_batch ADD COLUMN {kolon} {tanim}")
            con.commit()
            print(f"  OK    nexgen_uretim_batch.{kolon} eklendi")
        else:
            print(f"  SKIP  {kolon} zaten var")

    # ═══════════════════════════════════════════════════════════════════
    # [5] nexgen_rf_kullanim — rf_rev_no + kalip_carpani
    # ═══════════════════════════════════════════════════════════════════
    print("\n[5] nexgen_rf_kullanim yeni kolonlar:")
    for kolon, tanim in [('rf_rev_no', 'INTEGER'), ('kalip_carpani', 'REAL')]:
        if not _kolon_var(cur, 'nexgen_rf_kullanim', kolon):
            cur.execute(f"ALTER TABLE nexgen_rf_kullanim ADD COLUMN {kolon} {tanim}")
            con.commit()
            print(f"  OK    nexgen_rf_kullanim.{kolon} eklendi")
        else:
            print(f"  SKIP  {kolon} zaten var")

    # ═══════════════════════════════════════════════════════════════════
    # [6] Mevcut kalemli RF'ler icin REV-1 seed
    # ═══════════════════════════════════════════════════════════════════
    print("\n[6] Mevcut RF'ler icin REV-1 seed:")

    rf_rows = cur.execute(
        "SELECT id, rf_kod, ad, olusturan_id, onaylayan_id, onay_tarihi "
        "FROM nexgen_rf_renk WHERE aktif = 1"
    ).fetchall()

    rev1_olusturulan = 0
    kalemsiz_listesi = []

    for rf in rf_rows:
        rf_id = rf['id']

        # Zaten revizyon var mi?
        mevcut_rev = cur.execute(
            "SELECT id FROM nexgen_rf_revizyon WHERE rf_renk_id = ? AND rev_no = 1",
            (rf_id,)
        ).fetchone()
        if mevcut_rev:
            continue

        # Aktif pigment kalemleri
        kalemler = cur.execute("""
            SELECT rk.stok_kart_id, sk.ad AS pigment_ad, rk.miktar_kg, rk.sira
            FROM nexgen_rf_kalem rk
            JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
            WHERE rk.rf_renk_id = ? AND rk.aktif = 1
            ORDER BY rk.sira
        """, (rf_id,)).fetchall()

        if not kalemler:
            kalemsiz_listesi.append({'id': rf_id, 'rf_kod': rf['rf_kod'], 'ad': rf['ad']})
            print(f"  SKIP  RF id={rf_id} rf_kod={rf['rf_kod']} kalemsiz — REV-1 olusturulmadi")
            continue

        pigmentler_json = json.dumps([
            {
                'stok_kart_id': k['stok_kart_id'],
                'pigment_ad':   k['pigment_ad'],
                'miktar_kg':    k['miktar_kg'],
                'sira':         k['sira'],
            }
            for k in kalemler
        ], ensure_ascii=False)

        cur.execute("""
            INSERT INTO nexgen_rf_revizyon
                (rf_renk_id, rev_no, durum, pigmentler_json, neden, aciklama,
                 olusturan_id, olusturma_tarihi, onaylayan_id, onay_tarihi, kilitli_mi, aktif)
            VALUES (?, 1, 'ONAYLANDI', ?, 'ILKREVIZYON', 'Migration 098 - Mevcut receteden otomatik REV-1',
                    ?, datetime('now'), ?, ?, 1, 1)
        """, (
            rf_id,
            pigmentler_json,
            rf['olusturan_id'],
            rf['onaylayan_id'],
            rf['onay_tarihi'],
        ))

        # aktif_rev_no = 1 yap (sadece 0 olan kayitlari)
        cur.execute(
            "UPDATE nexgen_rf_renk SET aktif_rev_no = 1 WHERE id = ? AND aktif_rev_no = 0",
            (rf_id,)
        )

        rev1_olusturulan += 1

    con.commit()
    print(f"  OK    REV-1 olusturulan: {rev1_olusturulan} RF")
    print(f"  SKIP  Kalemsiz RF:       {len(kalemsiz_listesi)} RF (REV-1 olusturulmadi)")
    if kalemsiz_listesi:
        for r in kalemsiz_listesi:
            print(f"        — id={r['id']} {r['rf_kod']} {r['ad']}")

    # ═══════════════════════════════════════════════════════════════════
    # Guvenlik: dokunulmaz sayimlari karsilastir
    # ═══════════════════════════════════════════════════════════════════
    rf_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_rf_renk").fetchone()[0]
    rfk_sonraki = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kalem").fetchone()[0]
    sh_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    rev_toplam  = cur.execute("SELECT COUNT(*) FROM nexgen_rf_revizyon").fetchone()[0]

    print(f"\n[SONRASI] rf_renk={rf_sonraki}  rf_kalem={rfk_sonraki}  stok_hareket={sh_sonraki}  revizyon={rev_toplam}")
    assert rf_sonraki  == rf_onceki,  "HATA: rf_renk sayisi degisti!"
    assert rfk_sonraki == rfk_onceki, "HATA: rf_kalem sayisi degisti!"
    assert sh_sonraki  == sh_onceki,  "HATA: stok_hareket degisti!"

    # ── schema_migrations ───────────────────────────────────────────────
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(98)")
        con.commit()
        print("\n  OK    schema_migrations version=98")
    except Exception as e:
        print(f"\n  WARN  schema_migrations: {e}")

    print("\n" + "=" * 70)
    print("OZET")
    print("=" * 70)
    print(f"  nexgen_rf_revizyon tablosu : {'olusturuldu' if rev_toplam >= 0 else 'var'}")
    print(f"  aktif_rev_no kolonu        : eklendi/mevcut")
    print(f"  plan/batch/kullanim kolonlari: eklendi/mevcut")
    print(f"  REV-1 olusturulan          : {rev1_olusturulan}")
    print(f"  Kalemsiz RF (atlandı)      : {len(kalemsiz_listesi)}")
    print(f"  stok_hareket delta         : {sh_sonraki - sh_onceki} (0 olmali)")
    print("=" * 70)
    print("Migration 098 tamamlandi\n")

    con.close()


def rollback():
    """
    SINIRLI ROLLBACK — nexgen_rf_revizyon tablosunu ve indexleri kaldirir.

    SQLite ALTER ADD COLUMN geri alinamaz. Asagidaki kolonlar kalici olarak kalir:
      nexgen_rf_renk.aktif_rev_no
      nexgen_uretim_plan.kalip_carpani, rf_rev_no
      nexgen_uretim_batch.rf_renk_id, rf_rev_no, kalip_carpani
      nexgen_rf_kullanim.rf_rev_no, kalip_carpani

    Bu kolonlar NULL varsayilan degerle eklenmistir;
    mevcut sorgulara zarar vermezler.
    Tam geri donus icin DB yedeginizden geri yuklemeniz gerekir.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 098 (SINIRLI): nexgen_rf_revizyon DROP ===")
    print("  UYARI: ALTER ADD COLUMN kolonlari geri alinamaz — tablo DROP yapiliyor.")
    cur.execute("DROP TABLE IF EXISTS nexgen_rf_revizyon")
    for idx in ('idx_nrfrev_rf', 'idx_nrfrev_durum', 'idx_nrfrev_kilitli'):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=98")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    nexgen_rf_revizyon kaldirildi")
    print("  INFO  ALTER kolonlari (aktif_rev_no vb.) kalici — tam geri donus icin DB yedegini kullanin")
    print("=== Rollback 098 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()
