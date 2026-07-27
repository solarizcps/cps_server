# -*- coding: utf-8 -*-
"""
122_onay_merkezi_mvp.py
========================
FAZ-MERKEZI-ONAY-MVP — onay_talep + adim + adapter_log + planlama snapshot kolonu.
"""
from __future__ import annotations

import os
import sqlite3

MIGRATION_VERSION = 122
YONETIM_ROL_ID = 1
MUHASEBE_ROL_ID = 2

YENI_YETKILER = [
    ('onay.satis.karar', 'onay', 'Satış Onay Kararı', 'Satış siparişi onay adımı', 221),
    ('onay.satinalma.karar', 'onay', 'Satın Alma Onay Kararı', 'Satın alma siparişi onay', 222),
    ('onay.finans.karar', 'onay', 'Finans Onay Kararı', 'Finans K2 onay adımı', 223),
    ('onay.yonetim.karar', 'onay', 'Yönetim Onay Kararı', 'K3/K4 yönetim onayı', 224),
]

YONETIM_YETKI = (
    'onay.merkez.view', 'onay.merkez.karar',
    'onay.satis.karar', 'onay.satinalma.karar',
    'onay.finans.karar', 'onay.yonetim.karar',
)
MUHASEBE_YETKI = ('onay.merkez.view', 'onay.finans.karar', 'onay.merkez.karar')


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _kolon_var(con, tablo: str, kolon: str) -> bool:
    return kolon in [c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()]


def _ensure_tables(con: sqlite3.Connection) -> None:
    if not _table_exists(con, 'onay_talep'):
        con.execute("""
            CREATE TABLE onay_talep (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                talep_kod           TEXT NOT NULL UNIQUE,
                talep_tipi          TEXT NOT NULL,
                kaynak_modul        TEXT NOT NULL,
                kaynak_id           INTEGER NOT NULL,
                kaynak_kod          TEXT,
                cari_id             INTEGER,
                cari_unvan_snapshot TEXT,
                talep_eden_id       INTEGER,
                talep_tarihi        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                durum               TEXT NOT NULL DEFAULT 'BEKLIYOR'
                    CHECK(durum IN (
                        'TASLAK','BEKLIYOR','ONAYLANDI','REDDEDILDI',
                        'REVIZYON','BEKLETILDI','IPTAL'
                    )),
                aktif_kademe        TEXT,
                oncelik             TEXT NOT NULL DEFAULT 'NORMAL',
                tutar               REAL,
                para_birimi         TEXT,
                vade_gun            INTEGER,
                payload_json        TEXT,
                snapshot_json       TEXT,
                etki_onizleme_json  TEXT,
                idempotency_key     TEXT NOT NULL UNIQUE,
                revizyon_no         INTEGER NOT NULL DEFAULT 1,
                aktif               INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        log('[122] OK onay_talep olusturuldu')
    else:
        log('[122] SKIP onay_talep mevcut')

    if not _table_exists(con, 'onay_talep_adim'):
        con.execute("""
            CREATE TABLE onay_talep_adim (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                talep_id                INTEGER NOT NULL,
                sira                    INTEGER NOT NULL,
                adim_tipi               TEXT NOT NULL,
                kademe                  TEXT NOT NULL,
                rol_adi                 TEXT,
                kullanici_id            INTEGER,
                kullanici_ad_snapshot   TEXT,
                durum                   TEXT NOT NULL DEFAULT 'BEKLIYOR'
                    CHECK(durum IN (
                        'BEKLIYOR','TAMAMLANDI','ATLANDI','REDDEDILDI',
                        'REVIZYON','BEKLETILDI'
                    )),
                karar_notu              TEXT,
                tarih                   TEXT,
                created_at              TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (talep_id) REFERENCES onay_talep(id) ON DELETE RESTRICT
            )
        """)
        log('[122] OK onay_talep_adim olusturuldu')
    else:
        log('[122] SKIP onay_talep_adim mevcut')

    if not _table_exists(con, 'onay_adapter_log'):
        con.execute("""
            CREATE TABLE onay_adapter_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                talep_id        INTEGER,
                adapter_kodu    TEXT NOT NULL,
                kaynak_modul    TEXT,
                islem           TEXT NOT NULL,
                sonuc           TEXT NOT NULL,
                hata_mesaji     TEXT,
                payload_json    TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (talep_id) REFERENCES onay_talep(id) ON DELETE SET NULL
            )
        """)
        log('[122] OK onay_adapter_log olusturuldu')
    else:
        log('[122] SKIP onay_adapter_log mevcut')

    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_onay_talep_aktif_kaynak
            ON onay_talep(kaynak_modul, kaynak_id, talep_tipi)
            WHERE aktif=1 AND durum IN ('BEKLIYOR','BEKLETILDI')
    """)
    con.execute('CREATE INDEX IF NOT EXISTS idx_onay_talep_durum ON onay_talep(durum, talep_tipi)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_onay_talep_eden ON onay_talep(talep_eden_id)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_onay_adim_talep ON onay_talep_adim(talep_id, sira)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_onay_adapter_talep ON onay_adapter_log(talep_id)')

    if _table_exists(con, 'nexgen_planlama_siparis') and not _kolon_var(con, 'nexgen_planlama_siparis', 'onay_snapshot_json'):
        con.execute('ALTER TABLE nexgen_planlama_siparis ADD COLUMN onay_snapshot_json TEXT')
        log('[122] OK nexgen_planlama_siparis.onay_snapshot_json eklendi')


def _yetki_id(con, kod: str) -> int:
    row = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
    if row:
        return int(row['Id'])
    spec = next(y for y in YENI_YETKILER if y[0] == kod)
    con.execute(
        'INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)',
        spec,
    )
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])


def _rol_yetki(con, rol_id: int, kod: str, *, manage: bool = False, approve: bool = False) -> None:
    yid = _yetki_id(con, kod)
    mevcut = con.execute(
        'SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?', (rol_id, yid)
    ).fetchone()
    cv, ca, cm = 1, 1 if approve else 0, 1 if manage else 0
    if mevcut:
        con.execute(
            'UPDATE sistem_rol_yetki SET can_view=?, can_approve=?, can_manage=? WHERE Id=?',
            (cv, ca, cm, mevcut['Id']),
        )
    else:
        con.execute(
            """
            INSERT INTO sistem_rol_yetki
                (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                 can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 0, ?, 0, 0, 0, ?, 0, ?)
            """,
            (rol_id, yid, cv, ca, cm),
        )


def _ensure_yetkiler(con: sqlite3.Connection) -> None:
    for spec in YENI_YETKILER:
        _yetki_id(con, spec[0])
    for kod in YONETIM_YETKI:
        _rol_yetki(con, YONETIM_ROL_ID, kod, manage='karar' in kod, approve='karar' in kod)
    for kod in MUHASEBE_YETKI:
        _rol_yetki(con, MUHASEBE_ROL_ID, kod, approve='karar' in kod)


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )
    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] onay_merkezi_mvp')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'onay_talep') and _table_exists(con, 'onay_talep_adim'):
                log(f'[{MIGRATION_VERSION}] SKIP — idempotent')
                return

        con.execute('BEGIN IMMEDIATE')
        _ensure_tables(con)
        _ensure_yetkiler(con)
        if _table_exists(con, 'schema_migrations'):
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,),
            )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
