# -*- coding: utf-8 -*-
"""
Migration 119 — nexgen_arge_test.kaynak_uretim_varyant_id NULLABLE

FAZ-1D4-A: Yalnız şema. NULL kayıt üretmez. 0/hardcode UV yok.

Idempotent: kolon zaten nullable ise rebuild yok, already-nullable PASS.
Rollback: NULL satır > 0 ise REDDET; aksi halde ters rebuild → NOT NULL.

CLI:
  python app/migrations/119_nexgen_arge_kaynak_uv_nullable.py --db <path> dry-run
  python app/migrations/119_nexgen_arge_kaynak_uv_nullable.py --db <path> apply
  python app/migrations/119_nexgen_arge_kaynak_uv_nullable.py --db <path> rollback
  python app/migrations/119_nexgen_arge_kaynak_uv_nullable.py --db <path> selftest
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
from typing import Any

VERSION = "119"
TABLE = "nexgen_arge_test"
TABLE_NEW = "nexgen_arge_test__new"
COL = "kaynak_uretim_varyant_id"

DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock_data.db")
)

# Bilinen indexler (runtime'da eksik olanlar da PRAGMA ile eklenir)
KNOWN_INDEX_SQL = {
    "idx_arge_test_calisma_tipi":
        "CREATE INDEX IF NOT EXISTS idx_arge_test_calisma_tipi ON nexgen_arge_test(calisma_tipi)",
    "idx_arge_test_oncelik":
        "CREATE INDEX IF NOT EXISTS idx_arge_test_oncelik ON nexgen_arge_test(oncelik)",
    "idx_arge_test_saha_gerekli":
        "CREATE INDEX IF NOT EXISTS idx_arge_test_saha_gerekli ON nexgen_arge_test(saha_testi_gerekli_mi)",
    "idx_arge_test_renk_kodu":
        "CREATE INDEX IF NOT EXISTS idx_arge_test_renk_kodu ON nexgen_arge_test(renk_kodu)",
    "idx_arge_rf_renk":
        "CREATE INDEX IF NOT EXISTS idx_arge_rf_renk ON nexgen_arge_test(rf_renk_id)",
}


def _log(stats: dict, msg: str) -> None:
    stats.setdefault("log", []).append(msg)
    print(msg)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _tablo_var(cur: sqlite3.Cursor, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _table_info(cur: sqlite3.Cursor, table: str = TABLE) -> list[dict[str, Any]]:
    return [
        {
            "cid": r[0],
            "name": r[1],
            "type": r[2],
            "notnull": r[3],
            "dflt_value": r[4],
            "pk": r[5],
        }
        for r in cur.execute(f"PRAGMA table_info({table})")
    ]


def _kolon_notnull(cur: sqlite3.Cursor, col: str = COL) -> int | None:
    for c in _table_info(cur):
        if c["name"] == col:
            return int(c["notnull"])
    return None


def _already_nullable(cur: sqlite3.Cursor) -> bool:
    nn = _kolon_notnull(cur)
    return nn == 0


def _index_names(cur: sqlite3.Cursor, table: str = TABLE) -> list[str]:
    names = []
    for r in cur.execute(f"PRAGMA index_list('{table}')"):
        # r: seq, name, unique, origin, partial
        name = r[1]
        origin = r[3] if len(r) > 3 else "c"
        if origin == "u":  # auto unique from constraints — skip recreate by name if auto
            continue
        names.append(name)
    return names


def _index_create_sqls(cur: sqlite3.Cursor, table: str = TABLE) -> list[tuple[str, str]]:
    """(index_name, CREATE SQL) — sqlite_master.sql varsa onu kullan."""
    out: list[tuple[str, str]] = []
    for name in _index_names(cur, table):
        row = cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
        ).fetchone()
        if row and row[0]:
            out.append((name, row[0]))
        elif name in KNOWN_INDEX_SQL:
            out.append((name, KNOWN_INDEX_SQL[name]))
        else:
            # kolonlardan yeniden kur
            cols = [
                c[2]
                for c in cur.execute(f"PRAGMA index_info('{name}')")
            ]
            if cols:
                colsql = ", ".join(cols)
                out.append(
                    (name, f"CREATE INDEX IF NOT EXISTS {name} ON {table}({colsql})")
                )
    # bilinen eksikler
    have = {n for n, _ in out}
    for n, sql in KNOWN_INDEX_SQL.items():
        if n not in have:
            out.append((n, sql))
    return out


def _triggers(cur: sqlite3.Cursor) -> list[tuple[str, str]]:
    return [
        (r[0], r[1])
        for r in cur.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (TABLE,),
        ).fetchall()
        if r[1]
    ]


def _id_fingerprint(cur: sqlite3.Cursor) -> tuple[int, int | None, str]:
    n = cur.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    mx = cur.execute(f"SELECT MAX(id) FROM {TABLE}").fetchone()[0]
    ids = [str(r[0]) for r in cur.execute(f"SELECT id FROM {TABLE} ORDER BY id")]
    fp = hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()
    return int(n), (int(mx) if mx is not None else None), fp


def _kaynak_fingerprint(cur: sqlite3.Cursor) -> str:
    rows = cur.execute(
        f"SELECT id, {COL} FROM {TABLE} ORDER BY id"
    ).fetchall()
    raw = "|".join(f"{a}:{b}" for a, b in rows)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _col_def(c: dict[str, Any], *, force_nullable_kaynak: bool, force_notnull_kaynak: bool) -> str:
    name = c["name"]
    typ = c["type"] or "TEXT"
    parts = [name, typ]
    if c["pk"]:
        parts.append("PRIMARY KEY AUTOINCREMENT" if name == "id" else "PRIMARY KEY")
    else:
        if name == COL:
            if force_notnull_kaynak:
                parts.append("NOT NULL")
            # force_nullable: NOT NULL ekleme
        elif c["notnull"]:
            parts.append("NOT NULL")
        if c["dflt_value"] is not None:
            dflt = str(c["dflt_value"])
            # SQLite: fonksiyon ifadeleri DEFAULT (expr) olmalı
            if "(" in dflt and not dflt.strip().startswith("("):
                dflt = f"({dflt})"
            parts.append(f"DEFAULT {dflt}")
    return " ".join(parts)


def _create_table_sql(
    cols: list[dict[str, Any]],
    new_name: str,
    *,
    kaynak_nullable: bool,
) -> str:
    defs = []
    for c in cols:
        if c["name"] == "id":
            defs.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
            continue
        defs.append(
            _col_def(
                c,
                force_nullable_kaynak=kaynak_nullable,
                force_notnull_kaynak=not kaynak_nullable,
            )
        )
    body = ",\n                ".join(defs)
    return f"CREATE TABLE {new_name} (\n                {body}\n            )"


def _copy_columns_sql(cols: list[dict[str, Any]], src: str, dst: str) -> str:
    names = ", ".join(_quote_ident(c["name"]) for c in cols)
    return f"INSERT INTO {dst} ({names}) SELECT {names} FROM {src}"


def _ensure_sequence(cur: sqlite3.Cursor) -> None:
    mx = cur.execute(f"SELECT MAX(id) FROM {TABLE}").fetchone()[0]
    if mx is None:
        return
    has = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone()
    if not has:
        return
    row = cur.execute(
        "SELECT seq FROM sqlite_sequence WHERE name=?", (TABLE,)
    ).fetchone()
    if row:
        cur.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name=?", (int(mx), TABLE)
        )
    else:
        cur.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (TABLE, int(mx))
        )


def _record_migration(cur: sqlite3.Cursor, stats: dict) -> None:
    if not _tablo_var(cur, "schema_migrations"):
        _log(stats, "[119] WARN schema_migrations yok — kayıt atlandı")
        return
    # şema varyantları
    try:
        cur.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", (VERSION,)
        )
    except sqlite3.Error:
        try:
            cur.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, aciklama) VALUES(?, ?)",
                (VERSION, "kaynak_uretim_varyant_id nullable"),
            )
        except sqlite3.Error as e:
            _log(stats, f"[119] WARN schema_migrations: {e}")
            return
    _log(stats, f"[119] schema_migrations version={VERSION}")


def _unrecord_migration(cur: sqlite3.Cursor, stats: dict) -> None:
    if not _tablo_var(cur, "schema_migrations"):
        return
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=?", (VERSION,))
        _log(stats, "[119-RB] schema_migrations 119 silindi")
    except sqlite3.Error as e:
        _log(stats, f"[119-RB] schema_migrations: {e}")


def dry_run(db_path: str) -> dict:
    stats: dict[str, Any] = {"ok": True, "mode": "dry-run", "db": db_path}
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        if not _tablo_var(cur, TABLE):
            _log(stats, f"[119] HATA: tablo yok {TABLE}")
            stats["ok"] = False
            return stats
        if _tablo_var(cur, TABLE_NEW):
            _log(stats, f"[119] HATA: geçici tablo mevcut: {TABLE_NEW} — DUR")
            stats["ok"] = False
            return stats
        nn = _kolon_notnull(cur)
        _log(stats, f"[119] DRY-RUN {COL} notnull={nn}")
        if nn == 0:
            _log(stats, "[119] DRY-RUN already nullable — rebuild YOK")
            return stats
        n, mx, fp = _id_fingerprint(cur)
        kfp = _kaynak_fingerprint(cur)
        idxs = _index_create_sqls(cur)
        trigs = _triggers(cur)
        _log(stats, f"[119] DRY-RUN rows={n} max_id={mx} id_fp={fp[:16]}… kaynak_fp={kfp[:16]}…")
        _log(stats, f"[119] DRY-RUN indexes={ [i[0] for i in idxs] }")
        _log(stats, f"[119] DRY-RUN triggers={ [t[0] for t in trigs] }")
        _log(stats, "[119] DRY-RUN plan: rebuild → kaynak INTEGER NULL; veri birebir; NULL üretme yok")
        return stats
    finally:
        con.close()


def apply(db_path: str) -> dict:
    stats: dict[str, Any] = {"ok": False, "mode": "apply", "db": db_path}
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        if not _tablo_var(cur, TABLE):
            _log(stats, f"[119] HATA: tablo yok {TABLE}")
            return stats
        if _tablo_var(cur, TABLE_NEW):
            _log(stats, f"[119] HATA: geçici tablo mevcut: {TABLE_NEW} — rebuild yok, DUR")
            return stats

        if _already_nullable(cur):
            _log(stats, "[119] already nullable — PASS (rebuild yok, veri yazılmadı)")
            _record_migration(cur, stats)
            con.commit()
            stats["ok"] = True
            stats["idempotent"] = True
            return stats

        cols = _table_info(cur)
        before_n, before_mx, before_fp = _id_fingerprint(cur)
        before_kfp = _kaynak_fingerprint(cur)
        idx_sqls = _index_create_sqls(cur)
        trig_sqls = _triggers(cur)
        integ = cur.execute("PRAGMA integrity_check").fetchone()[0]
        if integ != "ok":
            _log(stats, f"[119] HATA integrity before={integ}")
            return stats

        id110 = cur.execute(
            f"SELECT {COL} FROM {TABLE} WHERE id=110"
        ).fetchone()
        before_110 = id110[0] if id110 else None

        create_sql = _create_table_sql(cols, TABLE_NEW, kaynak_nullable=True)
        copy_sql = _copy_columns_sql(cols, TABLE, TABLE_NEW)

        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute(create_sql)
            cur.execute(copy_sql)
            after_n = cur.execute(f"SELECT COUNT(*) FROM {TABLE_NEW}").fetchone()[0]
            after_mx = cur.execute(f"SELECT MAX(id) FROM {TABLE_NEW}").fetchone()[0]
            after_ids = [
                str(r[0])
                for r in cur.execute(f"SELECT id FROM {TABLE_NEW} ORDER BY id")
            ]
            after_fp = hashlib.sha256(",".join(after_ids).encode()).hexdigest()
            after_kfp = hashlib.sha256(
                "|".join(
                    f"{a}:{b}"
                    for a, b in cur.execute(
                        f"SELECT id, {COL} FROM {TABLE_NEW} ORDER BY id"
                    )
                ).encode()
            ).hexdigest()

            if after_n != before_n or after_mx != before_mx or after_fp != before_fp:
                raise RuntimeError(
                    f"satır/ID uyuşmazlığı before=({before_n},{before_mx},{before_fp[:12]}) "
                    f"after=({after_n},{after_mx},{after_fp[:12]})"
                )
            if after_kfp != before_kfp:
                raise RuntimeError("kaynak_uretim_varyant_id değerleri değişti")

            # 0 kontrolü — migration üretmemeli; mevcutta da olmamalı
            z = cur.execute(
                f"SELECT COUNT(*) FROM {TABLE_NEW} WHERE {COL}=0"
            ).fetchone()[0]
            if z:
                raise RuntimeError(f"yasak: {COL}=0 satır sayısı={z}")

            cur.execute(f"DROP TABLE {TABLE}")
            cur.execute(f"ALTER TABLE {TABLE_NEW} RENAME TO {TABLE}")

            for name, sql in idx_sqls:
                cur.execute(sql)

            for tname, tsql in trig_sqls:
                cur.execute(tsql)

            _ensure_sequence(cur)

            # verify
            if not _already_nullable(cur):
                raise RuntimeError("nullable verify failed")
            missing = []
            have = set(_index_names(cur))
            for name, _ in idx_sqls:
                if name not in have and name not in KNOWN_INDEX_SQL:
                    missing.append(name)
            # bilinenler zorunlu
            for name in KNOWN_INDEX_SQL:
                if name not in set(_index_names(cur)):
                    # IF NOT EXISTS sonrası tekrar kontrol
                    cur.execute(KNOWN_INDEX_SQL[name])
            have2 = set(_index_names(cur))
            for name in KNOWN_INDEX_SQL:
                if name not in have2:
                    missing.append(name)
            if missing:
                raise RuntimeError(f"index eksik: {missing}")

            integ2 = cur.execute("PRAGMA integrity_check").fetchone()[0]
            if integ2 != "ok":
                raise RuntimeError(f"integrity after={integ2}")

            after_110 = cur.execute(
                f"SELECT {COL} FROM {TABLE} WHERE id=110"
            ).fetchone()
            if before_110 is not None and (not after_110 or after_110[0] != before_110):
                raise RuntimeError(f"id=110 kaynak değişti {before_110}→{after_110}")

            null_cnt = cur.execute(
                f"SELECT COUNT(*) FROM {TABLE} WHERE {COL} IS NULL"
            ).fetchone()[0]
            if null_cnt != 0:
                raise RuntimeError(
                    f"migration NULL üretmemeli; null_cnt={null_cnt}"
                )

            _record_migration(cur, stats)
            con.commit()
            stats["ok"] = True
            _log(stats, f"[119] APPLY OK rows={after_n} max_id={after_mx} id110={before_110}")
            _log(stats, f"[119] indexes={sorted(have2)}")
            return stats
        except Exception as e:
            con.rollback()
            # orphan __new temizliği sadece biz oluşturduysak ve rename olmadıysa
            if _tablo_var(cur, TABLE_NEW) and _tablo_var(cur, TABLE):
                try:
                    cur.execute(f"DROP TABLE {TABLE_NEW}")
                    con.commit()
                    _log(stats, f"[119] geçici tablo temizlendi: {TABLE_NEW}")
                except sqlite3.Error:
                    pass
            _log(stats, f"[119] HATA rollback: {e}")
            stats["ok"] = False
            return stats
    finally:
        con.close()


def rollback(db_path: str) -> dict:
    """NULL kayıt yoksa NOT NULL'a ters rebuild. NULL>0 → REDDET."""
    stats: dict[str, Any] = {"ok": False, "mode": "rollback", "db": db_path}
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        if not _tablo_var(cur, TABLE):
            _log(stats, f"[119-RB] HATA: tablo yok")
            return stats
        if _tablo_var(cur, TABLE_NEW):
            _log(stats, f"[119-RB] HATA: geçici tablo mevcut {TABLE_NEW} — DUR")
            return stats
        if not _already_nullable(cur):
            _log(stats, "[119-RB] zaten NOT NULL — PASS")
            _unrecord_migration(cur, stats)
            con.commit()
            stats["ok"] = True
            return stats

        null_cnt = cur.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE {COL} IS NULL"
        ).fetchone()[0]
        if null_cnt > 0:
            _log(
                stats,
                f"[119-RB] REDDET: {null_cnt} NULL kayıt var — "
                "0/UV doldurma veya silme YASAK; backup restore kullanın",
            )
            stats["rejected"] = True
            stats["null_count"] = null_cnt
            return stats

        # 0 yasak
        z = cur.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE {COL}=0"
        ).fetchone()[0]
        if z:
            _log(stats, f"[119-RB] REDDET: {COL}=0 satır={z}")
            stats["rejected"] = True
            return stats

        cols = _table_info(cur)
        before_n, before_mx, before_fp = _id_fingerprint(cur)
        before_kfp = _kaynak_fingerprint(cur)
        idx_sqls = _index_create_sqls(cur)
        trig_sqls = _triggers(cur)

        create_sql = _create_table_sql(cols, TABLE_NEW, kaynak_nullable=False)
        copy_sql = _copy_columns_sql(cols, TABLE, TABLE_NEW)

        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute(create_sql)
            cur.execute(copy_sql)
            after_n = cur.execute(f"SELECT COUNT(*) FROM {TABLE_NEW}").fetchone()[0]
            after_mx = cur.execute(f"SELECT MAX(id) FROM {TABLE_NEW}").fetchone()[0]
            after_fp = hashlib.sha256(
                ",".join(
                    str(r[0])
                    for r in cur.execute(f"SELECT id FROM {TABLE_NEW} ORDER BY id")
                ).encode()
            ).hexdigest()
            if after_n != before_n or after_mx != before_mx or after_fp != before_fp:
                raise RuntimeError("rollback satır/ID uyuşmazlığı")
            after_kfp = hashlib.sha256(
                "|".join(
                    f"{a}:{b}"
                    for a, b in cur.execute(
                        f"SELECT id, {COL} FROM {TABLE_NEW} ORDER BY id"
                    )
                ).encode()
            ).hexdigest()
            if after_kfp != before_kfp:
                raise RuntimeError("rollback kaynak değerleri değişti")

            cur.execute(f"DROP TABLE {TABLE}")
            cur.execute(f"ALTER TABLE {TABLE_NEW} RENAME TO {TABLE}")
            for _, sql in idx_sqls:
                cur.execute(sql)
            for _, tsql in trig_sqls:
                cur.execute(tsql)
            _ensure_sequence(cur)

            nn = _kolon_notnull(cur)
            if nn != 1:
                raise RuntimeError(f"rollback NOT NULL verify failed notnull={nn}")
            integ = cur.execute("PRAGMA integrity_check").fetchone()[0]
            if integ != "ok":
                raise RuntimeError(f"integrity={integ}")

            _unrecord_migration(cur, stats)
            con.commit()
            stats["ok"] = True
            _log(stats, "[119-RB] OK — kolon tekrar NOT NULL")
            return stats
        except Exception as e:
            con.rollback()
            if _tablo_var(cur, TABLE_NEW) and _tablo_var(cur, TABLE):
                try:
                    cur.execute(f"DROP TABLE {TABLE_NEW}")
                    con.commit()
                except sqlite3.Error:
                    pass
            _log(stats, f"[119-RB] HATA: {e}")
            return stats
    finally:
        con.close()


def selftest(source_db: str, work_dir: str) -> dict:
    """Kopya DB üzerinde tam FAZ-1D4-A test paketi."""
    stats: dict[str, Any] = {"ok": False, "mode": "selftest"}
    os.makedirs(work_dir, exist_ok=True)
    copy_path = os.path.join(work_dir, "mock_data_119_test.db")
    shutil.copy2(source_db, copy_path)
    sha0 = _sha256(copy_path)
    _log(stats, f"[selftest] copy={copy_path} sha0={sha0}")

    # 1 dry-run
    d = dry_run(copy_path)
    if not d.get("ok", True) and d.get("ok") is False:
        stats["fail"] = "dry-run"
        return stats

    # before snapshot
    con = sqlite3.connect(copy_path)
    cur = con.cursor()
    before_nn = _kolon_notnull(cur)
    before_n, before_mx, before_fp = _id_fingerprint(cur)
    before_kfp = _kaynak_fingerprint(cur)
    before_110 = cur.execute(
        f"SELECT {COL} FROM {TABLE} WHERE id=110"
    ).fetchone()
    before_110 = before_110[0] if before_110 else None
    con.close()
    _log(stats, f"[selftest] before notnull={before_nn} rows={before_n} id110={before_110}")

    # 2 apply
    a1 = apply(copy_path)
    if not a1.get("ok"):
        stats["fail"] = "apply1"
        stats["detail"] = a1
        return stats

    con = sqlite3.connect(copy_path)
    cur = con.cursor()
    after_nn = _kolon_notnull(cur)
    after_n, after_mx, after_fp = _id_fingerprint(cur)
    after_kfp = _kaynak_fingerprint(cur)
    after_110 = cur.execute(
        f"SELECT {COL} FROM {TABLE} WHERE id=110"
    ).fetchone()[0]
    null_cnt = cur.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE {COL} IS NULL"
    ).fetchone()[0]
    zero_cnt = cur.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE {COL}=0"
    ).fetchone()[0]
    integ = cur.execute("PRAGMA integrity_check").fetchone()[0]
    idxs = sorted(_index_names(cur))
    con.close()

    checks = {
        "notnull_0": after_nn == 0,
        "rows_same": after_n == before_n and after_mx == before_mx and after_fp == before_fp,
        "kaynak_same": after_kfp == before_kfp,
        "id110_same": after_110 == before_110,
        "null_produced_0": null_cnt == 0,
        "zero_0": zero_cnt == 0,
        "integrity": integ == "ok",
        "indexes": all(k in idxs for k in KNOWN_INDEX_SQL),
    }
    _log(stats, f"[selftest] after checks={checks} indexes={idxs}")
    if not all(checks.values()):
        stats["fail"] = "verify"
        stats["checks"] = checks
        return stats

    sha1 = _sha256(copy_path)

    # 3 second apply idempotent
    a2 = apply(copy_path)
    if not a2.get("ok"):
        stats["fail"] = "apply2"
        return stats
    sha2 = _sha256(copy_path)
    _log(stats, f"[selftest] idempotent sha1={sha1} sha2={sha2} same={sha1==sha2}")
    # schema_migrations may already exist — sha should be identical on second apply
    if sha1 != sha2:
        _log(stats, "[selftest] WARN ikinci apply SHA değişti — log incelensin")
        # still ok if only no-op; if already nullable second apply may only touch migrations once
        # first apply already wrote migration; second should be no-op → same sha
        stats["fail"] = "idempotent_sha"
        return stats

    # 4 rollback (NULL yok)
    rb = rollback(copy_path)
    if not rb.get("ok"):
        stats["fail"] = "rollback"
        stats["detail"] = rb
        return stats
    con = sqlite3.connect(copy_path)
    cur = con.cursor()
    rb_nn = _kolon_notnull(cur)
    rb_kfp = _kaynak_fingerprint(cur)
    con.close()
    if rb_nn != 1 or rb_kfp != before_kfp:
        stats["fail"] = "rollback_verify"
        return stats
    _log(stats, "[selftest] rollback → NOT NULL OK")

    # 5 re-apply nullable
    a3 = apply(copy_path)
    con = sqlite3.connect(copy_path)
    ok_nn = _already_nullable(con.cursor())
    con.close()
    if not a3.get("ok") or not ok_nn:
        stats["fail"] = "reapply"
        return stats
    _log(stats, "[selftest] re-apply nullable OK")

    # 6 NULL rollback guard
    con = sqlite3.connect(copy_path)
    cur = con.cursor()
    # pick any id
    tid = cur.execute(f"SELECT id FROM {TABLE} ORDER BY id LIMIT 1").fetchone()[0]
    old_val = cur.execute(
        f"SELECT {COL} FROM {TABLE} WHERE id=?", (tid,)
    ).fetchone()[0]
    cur.execute(f"UPDATE {TABLE} SET {COL}=NULL WHERE id=?", (tid,))
    con.commit()
    con.close()

    rb2 = rollback(copy_path)
    if rb2.get("ok") or not rb2.get("rejected"):
        stats["fail"] = "null_rollback_should_reject"
        stats["detail"] = rb2
        return stats

    con = sqlite3.connect(copy_path)
    cur = con.cursor()
    cur_val = cur.execute(
        f"SELECT {COL} FROM {TABLE} WHERE id=?", (tid,)
    ).fetchone()[0]
    zero_after = cur.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE {COL}=0"
    ).fetchone()[0]
    still_nullable = _already_nullable(cur)
    con.close()
    if cur_val is not None:
        stats["fail"] = "null_was_filled"
        return stats
    if zero_after != 0:
        stats["fail"] = "zero_written"
        return stats
    if not still_nullable:
        stats["fail"] = "schema_changed_on_reject"
        return stats
    _log(
        stats,
        f"[selftest] NULL rollback REDDET OK id={tid} still_null=True "
        f"old_val_was={old_val} zero_cnt={zero_after}",
    )

    # restore test row for cleanliness (optional)
    con = sqlite3.connect(copy_path)
    con.execute(f"UPDATE {TABLE} SET {COL}=? WHERE id=?", (old_val, tid))
    con.commit()
    con.close()

    stats["ok"] = True
    stats["copy_db"] = copy_path
    stats["sha0"] = sha0
    stats["checks"] = checks
    _log(stats, "[selftest] ALL PASS")
    return stats


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Migration 119 kaynak UV nullable")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument(
        "command",
        choices=["dry-run", "apply", "rollback", "selftest"],
    )
    ap.add_argument(
        "--work-dir",
        default=None,
        help="selftest çalışma klasörü",
    )
    args = ap.parse_args(argv)
    db = os.path.abspath(args.db)

    if args.command == "dry-run":
        r = dry_run(db)
        return 0 if r.get("ok", True) else 1
    if args.command == "apply":
        # güvenlik: gerçek mock_data.db için env onayı
        real = os.path.abspath(DEFAULT_DB)
        if os.path.normcase(db) == os.path.normcase(real):
            if os.environ.get("FAZ1D4A_LOCAL_APPLY_ONAY") != "1":
                print(
                    "[119] REDDET: gerçek mock_data.db apply için "
                    "FAZ1D4A_LOCAL_APPLY_ONAY=1 gerekli",
                    file=sys.stderr,
                )
                return 2
        r = apply(db)
        return 0 if r.get("ok") else 1
    if args.command == "rollback":
        r = rollback(db)
        return 0 if r.get("ok") else 1
    # selftest
    work = args.work_dir or os.path.join(
        os.path.dirname(db),
        "..",
        "backup",
        "faz1d4a_nullable_selftest",
    )
    work = os.path.abspath(work)
    r = selftest(db, work)
    return 0 if r.get("ok") else 1


# NexGen runner uyumu
def run(db_path: str | None = None) -> None:
    path = os.path.abspath(db_path or DEFAULT_DB)
    if os.path.normcase(path) == os.path.normcase(os.path.abspath(DEFAULT_DB)):
        if os.environ.get("FAZ1D4A_LOCAL_APPLY_ONAY") != "1":
            raise RuntimeError(
                "119: gerçek DB apply engelli — FAZ1D4A_LOCAL_APPLY_ONAY=1 veya kopya DB kullanın"
            )
    r = apply(path)
    if not r.get("ok"):
        raise RuntimeError("migration 119 failed: " + "; ".join(r.get("log") or []))


if __name__ == "__main__":
    raise SystemExit(main())
