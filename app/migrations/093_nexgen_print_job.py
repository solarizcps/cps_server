# -*- coding: utf-8 -*-
"""
MIG 093 — nexgen_print_job
NexGen Print Agent — Doğrudan Yazıcı Baskı Kuyruğu

Kurallar:
- Idempotent: ikinci çalıştırmada sıfır değişiklik.
- Startup migration DEĞİL — sadece nexgen_db_repair.py üzerinden çalışır.
- Tek yazıcı, tek agent varsayımı — bu fazda printer_code / priority yok.
- Durumlar: PENDING → CLAIMED → PRINTED | FAILED

Tablo:
  nexgen_print_job
    id, etiket_id, payload_base64, status,
    requested_by_user_id, requested_at,
    claimed_at, printed_at,
    last_error, created_at, updated_at
"""


def mig093(cur, con, log):
    tag = "[093]"

    # ── 1. nexgen_print_job tablosu ───────────────────────────────────────────
    tablovar = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone() is not None

    if not tablovar:
        cur.execute("""
            CREATE TABLE nexgen_print_job (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                etiket_id            INTEGER NOT NULL,
                payload_base64       TEXT    NOT NULL,
                status               TEXT    NOT NULL DEFAULT 'PENDING',
                requested_by_user_id INTEGER,
                requested_at         TEXT,
                claimed_at           TEXT,
                printed_at           TEXT,
                last_error           TEXT,
                created_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (etiket_id) REFERENCES nexgen_arge_etiket(id)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_print_job_status
            ON nexgen_print_job(status)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_print_job_etiket
            ON nexgen_print_job(etiket_id)
        """)
        con.commit()
        log.append(f"{tag} nexgen_print_job tablosu oluşturuldu.")
    else:
        # Idempotent: kolon var mı kontrol et, eksikse ekle
        kolonlar = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_print_job)").fetchall()]
        eklendi = 0

        eklenecekler = [
            ("etiket_id",            "INTEGER NOT NULL DEFAULT 0"),
            ("payload_base64",       "TEXT NOT NULL DEFAULT ''"),
            ("status",               "TEXT NOT NULL DEFAULT 'PENDING'"),
            ("requested_by_user_id", "INTEGER"),
            ("requested_at",         "TEXT"),
            ("claimed_at",           "TEXT"),
            ("printed_at",           "TEXT"),
            ("last_error",           "TEXT"),
            ("created_at",           "TEXT NOT NULL DEFAULT (datetime('now','localtime'))"),
            ("updated_at",           "TEXT NOT NULL DEFAULT (datetime('now','localtime'))"),
        ]

        for kolon_adi, tanim in eklenecekler:
            if kolon_adi not in kolonlar:
                try:
                    cur.execute(f"ALTER TABLE nexgen_print_job ADD COLUMN {kolon_adi} {tanim}")
                    log.append(f"{tag}   + kolon eklendi: {kolon_adi}")
                    eklendi += 1
                except Exception as e:
                    log.append(f"{tag}   UYARI {kolon_adi}: {e}")

        # Index kontrolü
        for idx_name, idx_sql in [
            ("idx_print_job_status",
             "CREATE INDEX IF NOT EXISTS idx_print_job_status ON nexgen_print_job(status)"),
            ("idx_print_job_etiket",
             "CREATE INDEX IF NOT EXISTS idx_print_job_etiket ON nexgen_print_job(etiket_id)"),
        ]:
            idx_var = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx_name,)
            ).fetchone() is not None
            if not idx_var:
                cur.execute(idx_sql)
                log.append(f"{tag}   + index oluşturuldu: {idx_name}")
                eklendi += 1

        if eklendi == 0:
            log.append(f"{tag} nexgen_print_job zaten güncel — değişiklik yok.")
        else:
            con.commit()

    # ── 2. schema_migrations kaydı ────────────────────────────────────────────
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, aciklama) "
        "VALUES('093', 'nexgen_print_job — dogrudan yazici baskı kuyruğu')"
    )
    con.commit()
