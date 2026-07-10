# -*- coding: utf-8 -*-
"""
MIG 092 — nexgen_arge_etiket + nexgen_arge_etiket_yazdirma
AR-GE Numune Etiketi / Barkod FAZ-1

Kurallar:
- Idempotent: ikinci calistirmada sifir degisiklik.
- Startup migration degil — sadece nexgen_db_repair.py uzerinden calisir.
- Foreign key cascade yok (etiket gecmisi korunmali).
- UNIQUE constraint: barkod_kodu, (arge_kayit_id, rev_no, numune_no)

Tablo iliskileri:
  nexgen_arge_etiket.arge_kayit_id -> nexgen_arge_test.id
  nexgen_arge_etiket.revizyon_id   -> nexgen_arge_revizyon.id (NULL-able)
  nexgen_arge_etiket_yazdirma.etiket_id -> nexgen_arge_etiket.id

Barkod format (v2, 2026-07):
  NX-AR-0005  -> NX-ARGE-AR0005-R00-N01
  NX-RT-0005  -> NX-ARGE-RT0005-R00-N01
  NX-ARF-0003 -> NX-ARGE-ARF0003-R00-N01
  NX-RF-0003  -> NX-ARGE-RF0003-R00-N01
"""

import re as _re


def mig092(cur, con, log):
    tag = "[092]"

    # ── 1. Ana etiket tablosu ─────────────────────────────────────────────
    mevcut = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_arge_etiket'"
    ).fetchone()

    if not mevcut:
        # Tablo hiç yok — taze oluştur
        cur.executescript("""
            CREATE TABLE nexgen_arge_etiket (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                arge_kayit_id            INTEGER NOT NULL,
                revizyon_id              INTEGER,
                arge_kodu                TEXT,
                rev_no                   INTEGER NOT NULL DEFAULT 0,
                numune_no                INTEGER NOT NULL,
                barkod_kodu              TEXT    NOT NULL,
                cari_id                  INTEGER,
                cari_adi_snapshot        TEXT,
                talep_tarihi             TEXT,
                numune_tarihi            TEXT,
                olusturan_kullanici_id   INTEGER,
                olusturan_kullanici_adi  TEXT,
                yazdirma_sayisi          INTEGER NOT NULL DEFAULT 0,
                ilk_yazdirma_tarihi      TEXT,
                son_yazdirma_tarihi      TEXT,
                durum                    TEXT    NOT NULL DEFAULT 'AKTIF',
                created_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(barkod_kodu),
                UNIQUE(arge_kayit_id, rev_no, numune_no)
            );
            CREATE INDEX IF NOT EXISTS idx_arge_etiket_kayit
                ON nexgen_arge_etiket(arge_kayit_id);
            CREATE INDEX IF NOT EXISTS idx_arge_etiket_barkod
                ON nexgen_arge_etiket(barkod_kodu);
        """)
        con.commit()
        log.append(f"  {tag} nexgen_arge_etiket tablosu olusturuldu.")
    else:
        # Tablo var — şema ve veri kontrolü yap
        log.append(f"  {tag} nexgen_arge_etiket mevcut.")

        # 1a. revizyon_id NOT NULL kısıtı varsa kaldır (tek seferlik)
        _notnull = cur.execute(
            "SELECT notnull FROM pragma_table_info('nexgen_arge_etiket') WHERE name='revizyon_id'"
        ).fetchone()
        if _notnull and _notnull[0] == 1:
            cur.executescript("""
                PRAGMA foreign_keys = OFF;
                CREATE TABLE IF NOT EXISTS nexgen_arge_etiket_bak AS SELECT * FROM nexgen_arge_etiket;
                DROP TABLE nexgen_arge_etiket;
                CREATE TABLE nexgen_arge_etiket (
                    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                    arge_kayit_id            INTEGER NOT NULL,
                    revizyon_id              INTEGER,
                    arge_kodu                TEXT,
                    rev_no                   INTEGER NOT NULL DEFAULT 0,
                    numune_no                INTEGER NOT NULL,
                    barkod_kodu              TEXT    NOT NULL,
                    cari_id                  INTEGER,
                    cari_adi_snapshot        TEXT,
                    talep_tarihi             TEXT,
                    numune_tarihi            TEXT,
                    olusturan_kullanici_id   INTEGER,
                    olusturan_kullanici_adi  TEXT,
                    yazdirma_sayisi          INTEGER NOT NULL DEFAULT 0,
                    ilk_yazdirma_tarihi      TEXT,
                    son_yazdirma_tarihi      TEXT,
                    durum                    TEXT    NOT NULL DEFAULT 'AKTIF',
                    created_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    UNIQUE(barkod_kodu),
                    UNIQUE(arge_kayit_id, rev_no, numune_no)
                );
                INSERT INTO nexgen_arge_etiket SELECT * FROM nexgen_arge_etiket_bak;
                DROP TABLE nexgen_arge_etiket_bak;
                CREATE INDEX IF NOT EXISTS idx_arge_etiket_kayit
                    ON nexgen_arge_etiket(arge_kayit_id);
                CREATE INDEX IF NOT EXISTS idx_arge_etiket_barkod
                    ON nexgen_arge_etiket(barkod_kodu);
                PRAGMA foreign_keys = ON;
            """)
            con.commit()
            log.append(f"  {tag} nexgen_arge_etiket.revizyon_id NOT NULL kaldirildi.")
        else:
            log.append(f"  {tag} revizyon_id zaten NULL-able — atlandi.")

        # 1b. Barkod format düzeltme: NX-ARGE-{SAYI} → NX-ARGE-{TIP}{SAYI} (idempotent)
        #   Eski format (v1): NX-ARGE-0005-R00-N01  (prefix eksik — tip çakışır)
        #   Yeni format (v2): NX-ARGE-AR0005-R00-N01 / NX-ARGE-RT0005-R00-N01
        tum_kayitlar = cur.execute(
            "SELECT id, barkod_kodu, arge_kodu FROM nexgen_arge_etiket"
        ).fetchall()
        guncellenen = 0
        for eid, barkod, arge_kodu in tum_kayitlar:
            barkod = str(barkod or '')
            # Yeni formatta mı? — prefix (AR|RT|RF|ARF) hemen NX-ARGE- sonrasında varsa geç
            if _re.match(r'^NX-ARGE-(AR|RT|RF|ARF)[0-9A-Z]', barkod):
                continue
            # Eski format kontrol: NX-ARGE-{RAKAM}
            if not _re.match(r'^NX-ARGE-[0-9]', barkod):
                continue
            # arge_kodu'ndan prefix çıkar
            if not arge_kodu:
                log.append(f"  {tag} UYARI: id={eid} barkod={barkod} arge_kodu bos — atlanıyor.")
                continue
            m = _re.match(r'^NX-(AR|RT|RF|ARF)-(.+)$', str(arge_kodu).strip().upper())
            if not m:
                log.append(f"  {tag} UYARI: id={eid} arge_kodu={arge_kodu} format tanınamadı — atlanıyor.")
                continue
            tip = m.group(1)
            # NX-ARGE-0005-R00-N01 → NX-ARGE-AR0005-R00-N01
            yeni_barkod = _re.sub(r'^NX-ARGE-([0-9]+)', f'NX-ARGE-{tip}\\1', barkod)
            if yeni_barkod == barkod:
                continue
            try:
                cur.execute(
                    "UPDATE nexgen_arge_etiket SET barkod_kodu=?, updated_at=datetime('now','localtime') WHERE id=?",
                    (yeni_barkod, eid)
                )
                cur.execute(
                    "UPDATE nexgen_arge_etiket_yazdirma SET barkod_kodu=? WHERE barkod_kodu=?",
                    (yeni_barkod, barkod)
                )
                guncellenen += 1
                log.append(f"  {tag} Barkod guncellendi: {barkod} -> {yeni_barkod}")
            except Exception as exc:
                log.append(f"  {tag} HATA id={eid}: {exc}")

        if guncellenen > 0:
            con.commit()
            log.append(f"  {tag} Toplam {guncellenen} barkod yeni formata guncellendi.")
        else:
            log.append(f"  {tag} Barkod format kontrolu tamamlandi — guncelleme gerekmedi (0 kayit).")

    # ── 2. Yazdirma log tablosu ───────────────────────────────────────────
    mevcut2 = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_arge_etiket_yazdirma'"
    ).fetchone()

    if not mevcut2:
        cur.executescript("""
            CREATE TABLE nexgen_arge_etiket_yazdirma (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                etiket_id       INTEGER NOT NULL,
                barkod_kodu     TEXT    NOT NULL,
                kullanici_id    INTEGER,
                kullanici_adi   TEXT,
                kopya_sayisi    INTEGER NOT NULL DEFAULT 1,
                ilk_basim_mi    INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_etiket_yazd_etiket
                ON nexgen_arge_etiket_yazdirma(etiket_id);
        """)
        con.commit()
        log.append(f"  {tag} nexgen_arge_etiket_yazdirma tablosu olusturuldu.")
    else:
        log.append(f"  {tag} nexgen_arge_etiket_yazdirma mevcut — atlandi.")
