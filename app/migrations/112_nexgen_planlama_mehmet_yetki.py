# -*- coding: utf-8 -*-
"""
112_nexgen_planlama_mehmet_yetki.py
=====================================
FAZ-MEHMET-KULLANICI-BAZLI-YETKI-DUZELTME  (v3 — Kod/KullaniciAdi, transaction-safe)

Yalnız KullaniciAdi='mehmet' aktif kullanıcısına NexGen Pazarlama erişimi.
Mehmet RolId değişmez. mehmetemin etkilenmez.

Override'lar (sistem_yetki.Kod):
  - nexgen.view        can_view=1, can_report=1
  - nexgen.plan.view   can_view=1, can_report=1
  - nexgen.plan.manage can_manage=1

schema_migrations=112 yalnız başarılı upsert sonrası yazılır.
Version kaydı var ama override eksikse yeniden uygular (reconcile).
"""
from __future__ import annotations

import datetime
import os
import sqlite3

from migrations.nexgen_manifest import (
    MEHMET_KADI,
    MEHMET_OVERRIDE_SPECS,
    mehmet_nexgen_overrides_ok,
)

MIGRATION_VERSION = 112


def log(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def _ensure_version_row(con: sqlite3.Connection) -> None:
    has_sm = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not has_sm:
        return
    con.execute(
        'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
        (MIGRATION_VERSION,),
    )


def _resolve_mehmet(con: sqlite3.Connection) -> sqlite3.Row:
    rows = con.execute(
        "SELECT Id, KullaniciAdi, RolId, Aktif FROM sistem_kullanici WHERE KullaniciAdi=?",
        (MEHMET_KADI,),
    ).fetchall()
    aktif = [r for r in rows if int(r['Aktif'] or 0) == 1]
    if len(aktif) != 1:
        raise RuntimeError(
            f"KullaniciAdi='{MEHMET_KADI}' için tek aktif kayıt bulunamadı (bulunan={len(aktif)})"
        )
    return aktif[0]


def _resolve_yetki_id(con: sqlite3.Connection, kod: str) -> int:
    row = con.execute(
        'SELECT Id, Kod FROM sistem_yetki WHERE Kod=?',
        (kod,),
    ).fetchone()
    if not row:
        raise RuntimeError(f'sistem_yetki.Kod="{kod}" bulunamadı')
    return int(row['Id'])


def _upsert_override(
    con: sqlite3.Connection,
    kullanici_id: int,
    yetki_id: int,
    spec: tuple[str, int, int, int, int, int, int, int],
    ts: str,
) -> str:
    kod, cv, cc, cu, cd, ca, cr, cm = spec
    mevcut = con.execute(
        """
        SELECT Id, can_view, can_create, can_update, can_delete,
               can_approve, can_report, can_manage
        FROM user_permission_override
        WHERE KullaniciId=? AND YetkiId=?
        """,
        (kullanici_id, yetki_id),
    ).fetchone()

    if mevcut:
        need_fix = any(
            int(mevcut[k] or 0) != v
            for k, v in (
                ('can_view', cv),
                ('can_create', cc),
                ('can_update', cu),
                ('can_delete', cd),
                ('can_approve', ca),
                ('can_report', cr),
                ('can_manage', cm),
            )
        )
        if need_fix:
            con.execute(
                """
                UPDATE user_permission_override
                SET can_view=?, can_create=?, can_update=?, can_delete=?,
                    can_approve=?, can_report=?, can_manage=?
                WHERE Id=?
                """,
                (cv, cc, cu, cd, ca, cr, cm, mevcut['Id']),
            )
            return f'UPDATE {kod}'
        return f'SKIP {kod}'

    con.execute(
        """
        INSERT INTO user_permission_override
            (KullaniciId, YetkiId, can_view, can_create, can_update,
             can_delete, can_approve, can_report, can_manage,
             aciklama, olusturma_tarih, olusturan)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'migration_112')
        """,
        (
            kullanici_id, yetki_id, cv, cc, cu, cd, ca, cr, cm,
            f'Mehmet NexGen override — {kod}', ts,
        ),
    )
    return f'INSERT {kod}'


def run(db_path: str | None = None) -> dict:
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] FAZ-MEHMET-OVERRIDE basliyor')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    result = {'ok': False, 'skipped': False, 'actions': []}
    try:
        upo_tablo = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_permission_override'"
        ).fetchone()
        if not upo_tablo:
            raise RuntimeError('user_permission_override tablosu bulunamadı')

        if mehmet_nexgen_overrides_ok(con):
            _ensure_version_row(con)
            con.commit()
            log(f'[{MIGRATION_VERSION}] SKIP — override semasi zaten tamam')
            result.update({'ok': True, 'skipped': True})
            return result

        con.execute('BEGIN IMMEDIATE')
        mehmet = _resolve_mehmet(con)
        mehmet_id = int(mehmet['Id'])
        rol_before = int(mehmet['RolId'])
        log(f'[{MIGRATION_VERSION}] mehmet Id={mehmet_id} RolId={rol_before} (degismeyecek)')

        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for spec in MEHMET_OVERRIDE_SPECS:
            kod = spec[0]
            yid = _resolve_yetki_id(con, kod)
            action = _upsert_override(con, mehmet_id, yid, spec, ts)
            result['actions'].append(action)
            log(f'[{MIGRATION_VERSION}] {action}')

        # mehmetemin etkilenmedi — yalnız mehmet'e yazıldığını doğrula
        mte = con.execute(
            "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='mehmetemin' AND Aktif=1"
        ).fetchone()
        if mte:
            cnt = con.execute(
                """
                SELECT COUNT(*) c FROM user_permission_override upo
                JOIN sistem_yetki y ON y.Id = upo.YetkiId
                WHERE upo.KullaniciId=? AND y.Kod IN ('nexgen.view','nexgen.plan.view','nexgen.plan.manage')
                """,
                (int(mte['Id']),),
            ).fetchone()['c']
            if int(cnt) > 0:
                raise RuntimeError('mehmetemin override kaydi tespit edildi — islem iptal')

        mehmet_after = con.execute(
            'SELECT RolId FROM sistem_kullanici WHERE Id=?', (mehmet_id,)
        ).fetchone()
        if int(mehmet_after['RolId']) != rol_before:
            raise RuntimeError('mehmet RolId degisti — rollback')

        if not mehmet_nexgen_overrides_ok(con):
            raise RuntimeError('Override dogrulamasi basarisiz')

        _ensure_version_row(con)
        con.commit()
        log(f'[{MIGRATION_VERSION}] COMMIT OK')
        log(f'[{MIGRATION_VERSION}] DOGRULAMA OK — override sayisi=3/3')
        log('=' * 70)
        log(f'[{MIGRATION_VERSION}] TAMAMLANDI')
        log('=' * 70)
        result['ok'] = True
        return result

    except Exception as exc:
        try:
            con.rollback()
            log(f'[{MIGRATION_VERSION}] ROLLBACK')
        except Exception:
            pass
        log(f'[{MIGRATION_VERSION}] HATA: {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import io
    import sys

    _app = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
    if _app not in sys.path:
        sys.path.insert(0, _app)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    print(run())
