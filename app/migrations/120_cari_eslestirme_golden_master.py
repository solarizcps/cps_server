# -*- coding: utf-8 -*-
"""
120_cari_eslestirme_golden_master.py
=====================================
FAZ-CARI-GOLDEN-MASTER-ESLESTIRME-F1B

1) cari_eslestirme tablosu (Golden Master eşleştirme katmanı)
2) Cari 360 / Finans / Onay yetki kodları (sistem_yetki)
3) Rol atamaları: Yönetim, Muhasebe
4) Mehmet (pazarlamacı) user override'ları

Idempotent: tablo/yetki/rol kayıtları tekrar çalıştırmada güvenli.
Otomatik eşleştirme / backfill YOK — tablo boş kalabilir.
"""
from __future__ import annotations

import datetime
import os
import sqlite3

from migrations.nexgen_manifest import MEHMET_KADI, MEHMET_CARI360_OVERRIDE_SPECS

MIGRATION_VERSION = 120

YONETIM_ROL_ID = 1
MUHASEBE_ROL_ID = 2

# (Kod, Modul, Ad, Aciklama, Sira)
CARI360_YETKILER = [
    ('cari360.view', 'cari360', 'Cari 360 Görüntüleme',
     'Tüm cariler için Cari 360 okuma', 200),
    ('cari360.view_own', 'cari360', 'Cari 360 Kendi Carileri',
     'Pazarlamacının kendi carilerini görüntülemesi', 201),
    ('cari360.finans.view', 'cari360', 'Cari 360 Finans Özet',
     'Cari finans özet alanlarını görüntüleme', 202),
    ('cari360.finans.write', 'cari360', 'Cari 360 Finans Yazma',
     'Finans kaydı ekleme/güncelleme (fiziksel silme yok)', 203),
    ('cari360.crm.write', 'cari360', 'Cari 360 CRM Yazma',
     'Görüşme/not/ziyaret girişi', 204),
    ('cari360.makina.write', 'cari360', 'Cari 360 Makina Yazma',
     'Makina/kimlik bilgisi girişi', 205),
    ('cari360.mapping.manage', 'cari360', 'Cari Eşleştirme Yönetimi',
     'Golden Master eşleştirme yönetimi', 206),
    ('finans.tahsilat.write', 'finans', 'Finans Tahsilat Yazma',
     'Tahsilat kaydı ekleme/güncelleme', 210),
    ('finans.cek.write', 'finans', 'Finans Çek Yazma',
     'Çek kaydı ekleme/güncelleme', 211),
    ('finans.odeme_plani.write', 'finans', 'Finans Ödeme Planı Yazma',
     'Ödeme planı ekleme/güncelleme', 212),
    ('onay.merkez.view', 'onay', 'Onay Merkezi Görüntüleme',
     'Merkezi onay ekranını görüntüleme', 220),
    ('onay.merkez.karar', 'onay', 'Onay Merkezi Karar',
     'Onay/red kararı verme', 221),
]

# yetki_kod -> izin haritası (can_delete her zaman 0 — fiziksel silme yasağı)
YONETIM_YETKI = {
    'cari360.view': dict(can_view=1),
    'cari360.view_own': dict(can_view=1),
    'cari360.finans.view': dict(can_view=1),
    'cari360.finans.write': dict(can_view=1, can_create=1, can_update=1),
    'cari360.crm.write': dict(can_view=1, can_create=1, can_update=1),
    'cari360.makina.write': dict(can_view=1, can_create=1, can_update=1),
    'cari360.mapping.manage': dict(can_view=1, can_manage=1),
    'finans.tahsilat.write': dict(can_view=1, can_create=1, can_update=1),
    'finans.cek.write': dict(can_view=1, can_create=1, can_update=1),
    'finans.odeme_plani.write': dict(can_view=1, can_create=1, can_update=1),
    'onay.merkez.view': dict(can_view=1),
    'onay.merkez.karar': dict(can_view=1, can_approve=1, can_manage=1),
}

MUHASEBE_YETKI = {
    'cari360.view': dict(can_view=1),
    'cari360.finans.view': dict(can_view=1),
    'cari360.finans.write': dict(can_view=1, can_create=1, can_update=1),
    'cari360.crm.write': dict(can_view=1, can_create=1, can_update=1),
    'finans.tahsilat.write': dict(can_view=1, can_create=1, can_update=1),
    'finans.cek.write': dict(can_view=1, can_create=1, can_update=1),
    'finans.odeme_plani.write': dict(can_view=1, can_create=1, can_update=1),
    'onay.merkez.view': dict(can_view=1),
    'onay.merkez.karar': dict(can_view=1, can_approve=1),
    # mapping.manage VERİLMEZ
    # can_delete VERİLMEZ
}


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _ensure_cari_eslestirme(con: sqlite3.Connection) -> None:
    if _table_exists(con, 'cari_eslestirme'):
        log('[120] SKIP cari_eslestirme — tablo zaten var')
        return
    con.executescript("""
        PRAGMA foreign_keys = ON;

        CREATE TABLE cari_eslestirme (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            nexgen_cari_id      INTEGER NOT NULL UNIQUE,
            cari_kart_ckod      TEXT,
            crm_firma_id        INTEGER,
            eslestirme_durumu   TEXT NOT NULL DEFAULT 'BEKLIYOR'
                                CHECK(eslestirme_durumu IN (
                                    'BEKLIYOR','DOGRULANDI','MANUEL','IPTAL'
                                )),
            eslestirme_yontemi  TEXT
                                CHECK(eslestirme_yontemi IS NULL OR eslestirme_yontemi IN (
                                    'CARI_KODU','ERP_KODU','VERGI_NO','MANUEL'
                                )),
            guven_puani         INTEGER,
            eslestiren_id       INTEGER,
            eslestirme_tarihi   TEXT,
            aktif               INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (nexgen_cari_id) REFERENCES nexgen_cari(id) ON DELETE RESTRICT,
            FOREIGN KEY (cari_kart_ckod) REFERENCES Cari_Kart(CKod) ON DELETE SET NULL,
            FOREIGN KEY (crm_firma_id) REFERENCES crm_firma(id) ON DELETE SET NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_cari_eslestirme_ckod
            ON cari_eslestirme(cari_kart_ckod)
            WHERE cari_kart_ckod IS NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_cari_eslestirme_crm
            ON cari_eslestirme(crm_firma_id)
            WHERE crm_firma_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_cari_eslestirme_durum
            ON cari_eslestirme(eslestirme_durumu);

        CREATE INDEX IF NOT EXISTS idx_cari_eslestirme_aktif
            ON cari_eslestirme(aktif);
    """)
    log('[120] OK cari_eslestirme tablosu oluşturuldu')


def _yetki_id(con: sqlite3.Connection, kod: str) -> int:
    row = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
    if row:
        return int(row['Id'])
    spec = next(y for y in CARI360_YETKILER if y[0] == kod)
    con.execute(
        'INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira) VALUES (?,?,?,?,?)',
        spec,
    )
    log(f'[120] EKLENDI yetki {kod}')
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])


def _ensure_yetkiler(con: sqlite3.Connection) -> dict[str, int]:
    ids: dict[str, int] = {}
    for kod, *_ in CARI360_YETKILER:
        ids[kod] = _yetki_id(con, kod)
    return ids


def _rol_yetki_upsert(con: sqlite3.Connection, rol_id: int, yetki_id: int,
                       izinler: dict, etiket: str) -> None:
    mevcut = con.execute(
        'SELECT Id, can_view, can_create, can_update, can_delete, '
        'can_approve, can_report, can_manage FROM sistem_rol_yetki '
        'WHERE RolId=? AND YetkiId=?',
        (rol_id, yetki_id),
    ).fetchone()
    flags = {
        'can_view': izinler.get('can_view', 0),
        'can_create': izinler.get('can_create', 0),
        'can_update': izinler.get('can_update', 0),
        'can_delete': 0,
        'can_approve': izinler.get('can_approve', 0),
        'can_report': izinler.get('can_report', 0),
        'can_manage': izinler.get('can_manage', 0),
    }
    if mevcut:
        need = any(int(mevcut[k] or 0) != v for k, v in flags.items())
        if need:
            con.execute(
                """
                UPDATE sistem_rol_yetki
                SET can_view=?, can_create=?, can_update=?, can_delete=?,
                    can_approve=?, can_report=?, can_manage=?
                WHERE Id=?
                """,
                (*flags.values(), mevcut['Id']),
            )
            log(f'[120] UPDATE rol_yetki {etiket}')
        else:
            log(f'[120] SKIP rol_yetki {etiket}')
        return
    con.execute(
        """
        INSERT INTO sistem_rol_yetki
            (RolId, YetkiId, Gorebilir, Duzenleyebilir,
             can_view, can_create, can_update, can_delete,
             can_approve, can_report, can_manage)
        VALUES (?, ?, 1, 0, ?, ?, ?, 0, ?, ?, ?)
        """,
        (rol_id, yetki_id, flags['can_view'], flags['can_create'], flags['can_update'],
         flags['can_approve'], flags['can_report'], flags['can_manage']),
    )
    log(f'[120] EKLENDI rol_yetki {etiket}')


def _assign_role_matrix(con: sqlite3.Connection, yetki_ids: dict[str, int]) -> None:
    for kod, izin in YONETIM_YETKI.items():
        _rol_yetki_upsert(con, YONETIM_ROL_ID, yetki_ids[kod], izin,
                          f'Yönetim/{kod}')
    for kod, izin in MUHASEBE_YETKI.items():
        _rol_yetki_upsert(con, MUHASEBE_ROL_ID, yetki_ids[kod], izin,
                          f'Muhasebe/{kod}')


def _upsert_mehmet_override(con: sqlite3.Connection, yetki_ids: dict[str, int]) -> None:
    row = con.execute(
        "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1",
        (MEHMET_KADI,),
    ).fetchone()
    if not row:
        log(f'[120] WARN Mehmet kullanıcısı bulunamadı — override atlanıyor')
        return
    kid = int(row['Id'])
    for spec in MEHMET_CARI360_OVERRIDE_SPECS:
        kod, cv, cc, cu, cd, ca, cr, cm = spec
        yid = yetki_ids.get(kod) or _yetki_id(con, kod)
        mevcut = con.execute(
            """
            SELECT Id, can_view, can_create, can_update, can_delete,
                   can_approve, can_report, can_manage
            FROM user_permission_override
            WHERE KullaniciId=? AND YetkiId=?
            """,
            (kid, yid),
        ).fetchone()
        if mevcut:
            need = any(
                int(mevcut[k] or 0) != v
                for k, v in (
                    ('can_view', cv), ('can_create', cc), ('can_update', cu),
                    ('can_delete', cd), ('can_approve', ca),
                    ('can_report', cr), ('can_manage', cm),
                )
            )
            if need:
                con.execute(
                    """
                    UPDATE user_permission_override
                    SET can_view=?, can_create=?, can_update=?, can_delete=?,
                        can_approve=?, can_report=?, can_manage=?
                    WHERE Id=?
                    """,
                    (cv, cc, cu, cd, ca, cr, cm, mevcut['Id']),
                )
                log(f'[120] UPDATE mehmet override {kod}')
            else:
                log(f'[120] SKIP mehmet override {kod}')
        else:
            con.execute(
                """
                INSERT INTO user_permission_override
                    (KullaniciId, YetkiId, can_view, can_create, can_update,
                     can_delete, can_approve, can_report, can_manage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (kid, yid, cv, cc, cu, cd, ca, cr, cm),
            )
            log(f'[120] EKLENDI mehmet override {kod}')


def run(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] cari_eslestirme_golden_master starting')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys = ON')
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        already = False
        if _table_exists(con, 'schema_migrations'):
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,),
            ).fetchone()
            if applied and _table_exists(con, 'cari_eslestirme'):
                yrow = con.execute(
                    "SELECT 1 FROM sistem_yetki WHERE Kod='cari360.view'"
                ).fetchone()
                if yrow:
                    log(f'[{MIGRATION_VERSION}] SKIP — already applied (idempotent)')
                    return

        con.execute('BEGIN IMMEDIATE')
        _ensure_cari_eslestirme(con)
        yetki_ids = _ensure_yetkiler(con)
        _assign_role_matrix(con, yetki_ids)
        _upsert_mehmet_override(con, yetki_ids)

        cnt = con.execute('SELECT COUNT(*) FROM cari_eslestirme').fetchone()[0]
        log(f'[{MIGRATION_VERSION}] cari_eslestirme satır sayısı: {cnt} (backfill yok)')

        if _table_exists(con, 'schema_migrations'):
            cols = [c[1] for c in con.execute('PRAGMA table_info(schema_migrations)').fetchall()]
            if 'aciklama' in cols:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version, aciklama) VALUES (?, ?)',
                    (MIGRATION_VERSION, 'cari_eslestirme + cari360 yetki'),
                )
            else:
                con.execute(
                    'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                    (MIGRATION_VERSION,),
                )
        con.commit()
        log(f'[{MIGRATION_VERSION}] OK — committed @ {ts}')
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
