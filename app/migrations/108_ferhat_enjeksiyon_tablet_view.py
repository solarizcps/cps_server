# -*- coding: utf-8 -*-
"""
Migration 108 — Ferhat / Enjeksiyon (RolId=35) nexgen.tablet.view

Amaç:
  RolId=35 (Enjeksiyon) operatörünün /nexgen/tablet/ferhat erişimi için
  minimum yetkiyi verir. Yalnız can_view.

Kapsam DIŞI:
  - Diğer roller
  - nexgen.tablet.uretim
  - Yetki bypass / dekoratör gevşetme
  - Kullanıcı kaydı değişikliği

Çalıştırma:
  # tmp kopya üzerinde:
  python app/migrations/108_ferhat_enjeksiyon_tablet_view.py --db path/to/tmp.db
  # canlı (mock_data.db) — ayrı onay gerekir:
  python app/migrations/108_ferhat_enjeksiyon_tablet_view.py

İdempotent. Rollback: yalnız bu migration'ın eklediği RolId=35 satırını siler.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

VERSION = "108"
ROL_ID = 35
YETKI_KOD = "nexgen.tablet.view"
DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock_data.db")
)


def rollback(db_path: str) -> int:
    """Yalnız RolId=35 + nexgen.tablet.view satırını ve schema 108 kaydını kaldırır."""
    if not os.path.exists(db_path):
        print(f"[108] HATA: DB yok: {db_path}")
        return 1
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    yetki = cur.execute(
        "SELECT Id FROM sistem_yetki WHERE Kod=?", (YETKI_KOD,)
    ).fetchone()
    if not yetki:
        print(f"[108] rollback: yetki yok — SKIP")
        con.close()
        return 0
    yetki_id = yetki["Id"]
    # Başka rollere dokunma — yalnız ROL_ID
    cur.execute(
        "DELETE FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (ROL_ID, yetki_id),
    )
    deleted = cur.rowcount
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=?", (VERSION,))
    except Exception as e:
        print(f"[108] rollback WARN schema_migrations: {e}")
    con.commit()
    con.close()
    print(f"[108] rollback OK deleted_rol_yetki={deleted} rol={ROL_ID} yetki={YETKI_KOD}")
    return 0


def run(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"[108] HATA: DB yok: {db_path}")
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    log = []

    rol = cur.execute(
        "SELECT Id, Ad, Aktif FROM sistem_rol WHERE Id=?", (ROL_ID,)
    ).fetchone()
    if not rol:
        print(f"[108] HATA: RolId={ROL_ID} bulunamadı")
        con.close()
        return 1
    log.append(f"[108] Rol {ROL_ID} = {rol['Ad']} Aktif={rol['Aktif']}")

    yetki = cur.execute(
        "SELECT Id, Kod FROM sistem_yetki WHERE Kod=?", (YETKI_KOD,)
    ).fetchone()
    if not yetki:
        print(f"[108] HATA: yetki kodu yok: {YETKI_KOD}")
        con.close()
        return 1
    yetki_id = yetki["Id"]
    log.append(f"[108] Yetki {YETKI_KOD} Id={yetki_id}")

    mevcut = cur.execute(
        "SELECT Id, can_view, Gorebilir FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (ROL_ID, yetki_id),
    ).fetchone()

    if mevcut:
        # Minimum: can_view + Gorebilir açık olsun; başka flag'e dokunma
        if int(mevcut["can_view"] or 0) == 1 and int(mevcut["Gorebilir"] or 0) == 1:
            log.append("[108] Atama zaten mevcut — SKIP")
        else:
            cur.execute(
                """
                UPDATE sistem_rol_yetki
                   SET can_view=1, Gorebilir=1
                 WHERE Id=?
                """,
                (mevcut["Id"],),
            )
            log.append(f"[108] Mevcut satır güncellendi Id={mevcut['Id']} (can_view/Gorebilir=1)")
    else:
        cur.execute(
            """
            INSERT INTO sistem_rol_yetki
                (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                 can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 0, 1, 0, 0, 0, 0, 0, 0)
            """,
            (ROL_ID, yetki_id),
        )
        log.append(f"[108] RolId={ROL_ID} ← {YETKI_KOD} (yalnız can_view) eklendi")

    # Başka rollere dokunulmadığını doğrula (sayaç log)
    diger = cur.execute(
        """
        SELECT COUNT(*) AS c FROM sistem_rol_yetki
         WHERE YetkiId=? AND RolId<>?
        """,
        (yetki_id, ROL_ID),
    ).fetchone()["c"]
    log.append(f"[108] Diğer roller tablet.view satır sayısı (dokunulmadı): {diger}")

    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", (VERSION,)
        )
        log.append(f"[108] schema_migrations version={VERSION}")
    except Exception as e:
        log.append(f"[108] WARN schema_migrations: {e}")

    con.commit()
    con.close()
    for line in log:
        print(line)
    print("[108] OK")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Migration 108 Ferhat tablet.view")
    p.add_argument(
        "--db",
        default=DEFAULT_DB,
        help="Hedef DB yolu (varsayılan: app/mock_data.db)",
    )
    p.add_argument(
        "--rollback",
        action="store_true",
        help="Yalnız RolId=35 tablet.view atamasını geri al",
    )
    args = p.parse_args(argv)
    print(f"[108] db={os.path.abspath(args.db)}")
    if args.rollback:
        return rollback(args.db)
    return run(args.db)


if __name__ == "__main__":
    sys.exit(main())
