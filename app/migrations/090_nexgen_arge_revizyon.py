# -*- coding: utf-8 -*-
"""
Migration 090 — nexgen_arge_revizyon tablosu ve aktif_rev_no kolonu

Yapılanlar:
  1. nexgen_arge_test.aktif_rev_no kolonu eklenir (idempotent ALTER)
  2. nexgen_arge_revizyon tablosu oluşturulur
     - Her revizyon kendi tam snapshot'ını taşır (JSON)
     - UNIQUE(test_id, rev_no) — çift kayıt engeli
  3. Mevcut her nexgen_arge_test kaydı için REV-0 (ilk kayıt) oluşturulur
     - Idempotent: aynı test_id için ikinci REV-0 oluşmaz

Çalıştırma:
  python app/migrations/090_nexgen_arge_revizyon.py
"""
import os, sys, sqlite3, json
from datetime import datetime

_HERE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.normpath(os.path.join(_HERE, '..', 'mock_data.db'))
VERSION  = '090'

# ── Snapshot alanları: nexgen_arge_test'ten alınacak kolon listesi
SNAPSHOT_ALANLAR = [
    'kaynak_uretim_varyant_id', 'test_no', 'test_tipi', 'makina',
    'test_batch_kg', 'kaynak_batch_kg', 'yeni_renk_adi', 'notlar',
    'durum', 'sonuc_notu', 'renk_tuttu', 'shore_degeri',
    'kopurme_notu', 'cekme_problemi', 'genel_aciklama',
    'olusturan_id', 'olusturma_tarihi',
    'onaylayan_id', 'onay_tarihi', 'onay_notu',
    'cari_id', 'shore_hedef', 'lot_no', 'talep_referansi',
    'rf_renk_id', 'arge_kodu', 'numune_orani', 'renk_bilesenleri_json',
    'olusan_uretim_varyant_id', 'olusan_renk_varyant_id',
    'aktif',
]


def _kolon_var(cur, tablo, kolon):
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info({tablo})').fetchall()]
    return kolon in cols


def _tablo_var(cur, tablo):
    r = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return r is not None


def _mig_yapildi_mi(cur):
    try:
        r = cur.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (VERSION,)
        ).fetchone()
        return r is not None
    except Exception:
        return False


def run():
    if not os.path.exists(DB_PATH):
        print(f'[090] HATA: DB bulunamadı: {DB_PATH}')
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute('PRAGMA journal_mode=WAL')
    cur.execute('PRAGMA foreign_keys=ON')

    log = []
    degisim = {'kolon_eklendi': 0, 'tablo_olusturuldu': False, 'rev0_eklendi': 0}

    # ── 1. aktif_rev_no kolonu ──────────────────────────────────────────────
    if not _kolon_var(cur, 'nexgen_arge_test', 'aktif_rev_no'):
        cur.execute('ALTER TABLE nexgen_arge_test ADD COLUMN aktif_rev_no INTEGER DEFAULT 0')
        con.commit()
        degisim['kolon_eklendi'] += 1
        log.append('[090] nexgen_arge_test.aktif_rev_no eklendi.')
    else:
        log.append('[090] aktif_rev_no zaten mevcut — atlandı.')

    # ── 2. basarili_mi kolonu (başarılı durumu için) ────────────────────────
    if not _kolon_var(cur, 'nexgen_arge_test', 'basarili_mi'):
        cur.execute('ALTER TABLE nexgen_arge_test ADD COLUMN basarili_mi INTEGER DEFAULT 0')
        cur.execute('ALTER TABLE nexgen_arge_test ADD COLUMN basarili_yapan_id INTEGER')
        cur.execute('ALTER TABLE nexgen_arge_test ADD COLUMN basarili_yapan_adi TEXT')
        cur.execute('ALTER TABLE nexgen_arge_test ADD COLUMN basarili_tarihi TEXT')
        con.commit()
        degisim['kolon_eklendi'] += 4
        log.append('[090] nexgen_arge_test başarılı alanları eklendi.')

    # ── 3. nexgen_arge_revizyon tablosu ────────────────────────────────────
    if not _tablo_var(cur, 'nexgen_arge_revizyon'):
        cur.execute("""
            CREATE TABLE nexgen_arge_revizyon (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id             INTEGER NOT NULL,
                rev_no              INTEGER NOT NULL,
                onceki_rev_no       INTEGER,

                -- Revizyon sebebi ve notlar
                neden               TEXT,
                ne_degisti          TEXT,       -- JSON list: ['renk_bilesenler','kod', ...]
                revizyon_notu       TEXT,

                -- Tam durum snapshot (JSON) — her revizyon kendi tam durumunu taşır
                snapshot_json       TEXT NOT NULL DEFAULT '{}',

                -- Değişiklik farkları (JSON list of {alan, onceki, yeni, fark})
                degisiklik_json     TEXT NOT NULL DEFAULT '[]',

                -- Revize eden
                olusturan_id        INTEGER,
                olusturan_adi       TEXT,
                olusturma_tarihi    TEXT NOT NULL DEFAULT (datetime('now','localtime')),

                -- Başarılı bilgileri (DENEME BASARILI işlemi bu revizyonu günceller)
                basarili_mi         INTEGER NOT NULL DEFAULT 0,
                basarili_yapan_id   INTEGER,
                basarili_yapan_adi  TEXT,
                basarili_tarihi     TEXT,

                -- Kilitli mi? (basarili=1 ise otomatik kilitlenir)
                kilitli_mi          INTEGER NOT NULL DEFAULT 0,

                UNIQUE(test_id, rev_no),
                FOREIGN KEY(test_id) REFERENCES nexgen_arge_test(id)
            )
        """)
        cur.execute(
            'CREATE INDEX IF NOT EXISTS idx_arge_rev_test_id ON nexgen_arge_revizyon(test_id)'
        )
        con.commit()
        degisim['tablo_olusturuldu'] = True
        log.append('[090] nexgen_arge_revizyon tablosu oluşturuldu.')
    else:
        log.append('[090] nexgen_arge_revizyon zaten mevcut — atlandı.')

    # ── 4. Mevcut testler için REV-0 seed ───────────────────────────────────
    # Mevcut nexgen_arge_test kolonlarını dinamik al (bazı kolonlar DB'de olmayabilir)
    mevcut_kolonlar = [
        r[1] for r in cur.execute('PRAGMA table_info(nexgen_arge_test)').fetchall()
    ]
    snap_alanlar = [a for a in SNAPSHOT_ALANLAR if a in mevcut_kolonlar]

    testler = cur.execute('SELECT id FROM nexgen_arge_test').fetchall()
    rev0_eklendi = 0

    for (test_id,) in testler:
        # Idempotent: bu test için zaten REV-0 varsa atla
        var = cur.execute(
            'SELECT 1 FROM nexgen_arge_revizyon WHERE test_id=? AND rev_no=0', (test_id,)
        ).fetchone()
        if var:
            continue

        # Test verisini al
        row = cur.execute(
            f'SELECT {", ".join(snap_alanlar)} FROM nexgen_arge_test WHERE id=?', (test_id,)
        ).fetchone()
        if not row:
            continue

        snapshot = dict(zip(snap_alanlar, row))

        # olusturma_tarihi snapshot'tan al, yoksa şimdi
        olusturma = snapshot.get('olusturma_tarihi') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cur.execute("""
            INSERT INTO nexgen_arge_revizyon
                (test_id, rev_no, onceki_rev_no, neden, ne_degisti, revizyon_notu,
                 snapshot_json, degisiklik_json,
                 olusturan_id, olusturan_adi, olusturma_tarihi,
                 basarili_mi, kilitli_mi)
            VALUES (?, 0, NULL, 'ilk_kayit', '[]', 'İlk kayıt',
                    ?, '[]',
                    ?, NULL, ?,
                    0, 0)
        """, (
            test_id,
            json.dumps(snapshot, ensure_ascii=False),
            snapshot.get('olusturan_id'),
            olusturma,
        ))
        rev0_eklendi += 1

    if rev0_eklendi:
        con.commit()
        degisim['rev0_eklendi'] = rev0_eklendi
        log.append(f'[090] {rev0_eklendi} test için REV-0 oluşturuldu.')
    else:
        log.append('[090] REV-0 seed: zaten tüm testler için mevcut — atlandı.')

    # ── 5. schema_migrations kaydı ─────────────────────────────────────────
    cur.execute(
        'INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)', (VERSION,)
    )
    con.commit()

    con.close()

    print(f'[090] Migration tamamlandı.')
    for l in log:
        print(l)
    print(f'[090] Özet: {degisim}')
    return degisim


if __name__ == '__main__':
    run()
