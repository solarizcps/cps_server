# -*- coding: utf-8 -*-
"""
Migration 050 — NexGen FAZ-2 Yetki Revizyonu
=============================================

Mimari karar (Rev.1):
  nexgen.tedarikci.manage -> Sadece Yönetim rolüne verilir.
  Satın Alma rolü tedarikçi listesini görebilir (view),
  ancak tedarikçi ekleyemez/düzenleyemez.

Tedarikçi + stok kart yönetimi -> NexGen Yönetim (FAZ-2.5)

Yapılanlar:
  1) Satın Alma rolünden nexgen.tedarikci.manage kaldırılır (varsa)
  2) Yönetim rolünde nexgen.tedarikci.manage korunur (değişmez)
  3) Doğrulama raporu

Idempotent: tekrar çalıştırma güvenli.
Versiyon: 050
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
SATINALMA_ROL_ADI = 'Satın Alma'
SILINCEK_YETKI    = 'nexgen.tedarikci.manage'


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 050 — NexGen FAZ-2 Yetki Revizyonu")
    print("=" * 65)

    # ── Satın Alma rolü ───────────────────────────────────────────
    sa_rol = cur.execute(
        "SELECT Id FROM sistem_rol WHERE Ad=?", (SATINALMA_ROL_ADI,)
    ).fetchone()
    if not sa_rol:
        print(f"\nUYARI: '{SATINALMA_ROL_ADI}' rolü DB'de yok — atlandı.")
        print("(Rol oluşturulduktan sonra bu migration tekrar çalıştırılabilir.)")
        con.close()
        return
    sa_rol_id = sa_rol["Id"]
    print(f"\nSatın Alma RolId: {sa_rol_id}")

    # ── nexgen.tedarikci.manage yetki ID ─────────────────────────
    yetki = cur.execute(
        "SELECT Id FROM sistem_yetki WHERE Kod=?", (SILINCEK_YETKI,)
    ).fetchone()
    if not yetki:
        print(f"INFO: '{SILINCEK_YETKI}' sistem_yetki'de yok — zaten temiz.")
        con.close()
        return
    yetki_id = yetki["Id"]
    print(f"nexgen.tedarikci.manage YetkiId: {yetki_id}")

    # ── Satın Alma rolünden sil ───────────────────────────────────
    kayit = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
        (sa_rol_id, yetki_id)
    ).fetchone()

    if kayit:
        cur.execute(
            "DELETE FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (sa_rol_id, yetki_id)
        )
        con.commit()
        print(f"SILINDI: Satın Alma (RolId={sa_rol_id}) → nexgen.tedarikci.manage kaldırıldı.")
    else:
        print(f"SKIP: Satın Alma rolünde '{SILINCEK_YETKI}' zaten yoktu — temiz.")

    # ── schema_migrations ─────────────────────────────────────────
    sm_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'description' in sm_kolonlar and 'applied_at' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
            VALUES (50, 'nexgen satinalma yetki revizyonu FAZ-2', datetime('now'))
        """)
    elif 'aciklama' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, aciklama)
            VALUES (50, 'nexgen satinalma yetki revizyonu FAZ-2')
        """)
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (50)")
    con.commit()

    # ── Doğrulama ─────────────────────────────────────────────────
    print("\n[DOGRULAMA] Satın Alma rolü nexgen.* yetkileri:")
    rows = cur.execute("""
        SELECT sy.Kod, srk.can_view, srk.can_create, srk.can_update
        FROM sistem_rol_yetki srk
        JOIN sistem_yetki sy ON sy.Id = srk.YetkiId
        WHERE srk.RolId = ? AND sy.Modul = 'nexgen'
        ORDER BY sy.Kod
    """, (sa_rol_id,)).fetchall()
    for r in rows:
        print(f"  {r['Kod']:<35} view={r['can_view']} create={r['can_create']} update={r['can_update']}")

    yonetim_check = cur.execute("""
        SELECT srk.Id FROM sistem_rol_yetki srk
        JOIN sistem_rol sr ON sr.Id = srk.RolId
        JOIN sistem_yetki sy ON sy.Id = srk.YetkiId
        WHERE sy.Kod = ? AND (sr.Ad LIKE '%netim%' OR sr.Ad LIKE '%Admin%')
        LIMIT 1
    """, (SILINCEK_YETKI,)).fetchone()
    print(f"\nYönetim rolünde nexgen.tedarikci.manage: {'VAR ✓' if yonetim_check else 'YOK — kontrol et!'}")

    con.close()
    print("\nMigration 050 tamamlandı.")


if __name__ == '__main__':
    run()
