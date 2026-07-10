# -*- coding: utf-8 -*-
"""
MIG 094 — nexgen_print_job.print_token
Android Print Bridge için job-bazlı erişim token'ı.

Kurallar:
- Idempotent: tablo veya kolon zaten varsa sıfır değişiklik.
- print_token: secrets.token_urlsafe(24) ile doldurulur (tablet endpoint'i tarafından).
- Boş token ile job hiçbir zaman Android API'ye erişilemez.
"""


def mig094(cur, con, log):
    tag = "[094]"

    # nexgen_print_job tablosu var mı?
    tablo_var = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone() is not None

    if not tablo_var:
        log.append(f"{tag} ATLA — nexgen_print_job tablosu yok (önce mig093 çalıştır).")
        return

    # print_token kolonu var mı?
    kolonlar = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_print_job)").fetchall()]
    if "print_token" not in kolonlar:
        cur.execute("ALTER TABLE nexgen_print_job ADD COLUMN print_token TEXT")
        con.commit()
        log.append(f"{tag} nexgen_print_job.print_token kolonu eklendi.")
    else:
        log.append(f"{tag} print_token zaten mevcut — değişiklik yok.")

    # schema_migrations kaydı
    cur.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, aciklama) "
        "VALUES('094', 'nexgen_print_job.print_token — Android Print Bridge token')"
    )
    con.commit()
