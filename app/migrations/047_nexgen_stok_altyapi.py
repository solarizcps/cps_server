# -*- coding: utf-8 -*-
"""
Migration 047 — NexGen FAZ-1B: Stok Kart Master + Hareket Motoru Altyapısı
===========================================================================

Yapılanlar:
  1) nexgen_stok_kart   — Hammadde/mamul/recycle kart tanımları
  2) nexgen_stok_hareket — Her türlü stok değişimi kayıt (ASLA elle güncelleme yok)
  3) sistem_yetki       — nexgen.stok.view + nexgen.stok.manage
  4) sistem_rol_yetki   — Yönetim rolü (RolId=1) her iki yetkiye tam erişim
  5) Örnek seed kartlar — EVA18, POE, KALSİT, SİYAH BOYA, RECYCLE
  6) Örnek hareketler   — Başlangıç stoğu SAYIM_DUZELTME tipiyle

Kurallar:
  - Stok miktarı ASLA doğrudan güncellenmez; sadece hareket eklenir.
  - Mevcut ENJ_CORE / Finans / Planlama / Hedef / Personel tablolarına dokunulmaz.
  - Idempotent: tekrar çalıştırma güvenli.
  - schema_migrations INSERT OR IGNORE.

Versiyon: 047
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1

STOK_YETKILER = [
    # (Kod,                  Modul,   Ad,                        Sira)
    ('nexgen.stok.view',   'nexgen', 'NexGen Stok Görüntüleme', 110),
    ('nexgen.stok.manage', 'nexgen', 'NexGen Stok Yönetim',     111),
]

ORNEK_KARTLAR = [
    # (kod,          ad,            kategori,           birim, min_stok, kritik_stok)
    ('EVA18',       'EVA 18',       'HAMMADDE',         'KG',  5000.0,   2000.0),
    ('POE',         'POE',          'HAMMADDE',         'KG',  3000.0,   1000.0),
    ('KALSIT',      'KALSİT',       'KATKI',            'KG',  2000.0,   500.0),
    ('SIYAH_BOYA',  'SİYAH BOYA',   'BOYA',             'KG',  500.0,    100.0),
    ('RECYCLE_EVA', 'RECYCLE EVA',  'RECYCLE',          'KG',  1000.0,   200.0),
]

# Başlangıç stok miktarları — SAYIM_DUZELTME hareketi olarak girilir
BASLANGIC_STOK = {
    'EVA18':       12500.0,
    'POE':          4800.0,
    'KALSIT':       3200.0,
    'SIYAH_BOYA':    320.0,
    'RECYCLE_EVA':  1600.0,
}


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 047 — NexGen Stok Kart Master + Hareket Motoru")
    print("=" * 65)

    # ── 1) nexgen_stok_kart tablosu ────────────────────────────
    print("\n[1] nexgen_stok_kart tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_stok_kart (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            kod             TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            ad              TEXT    NOT NULL,
            kategori        TEXT    NOT NULL DEFAULT 'HAMMADDE',
            -- HAMMADDE | MAMUL_COMPOUND | RECYCLE | KATKI | BOYA | DIGER
            birim           TEXT    NOT NULL DEFAULT 'KG',
            minimum_stok    REAL    NOT NULL DEFAULT 0,
            kritik_stok     REAL    NOT NULL DEFAULT 0,
            aciklama        TEXT,
            aktif           INTEGER NOT NULL DEFAULT 1,
            olusturan_id    INTEGER,
            olusturma_tarihi TEXT   DEFAULT (datetime('now')),
            guncelleyen_id  INTEGER,
            guncelleme_tarihi TEXT
        )
    """)
    print("  OK nexgen_stok_kart oluşturuldu veya zaten mevcut.")

    # ── 2) nexgen_stok_hareket tablosu ────────────────────────
    print("\n[2] nexgen_stok_hareket tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_stok_hareket (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stok_kart_id    INTEGER NOT NULL
                                REFERENCES nexgen_stok_kart(id),
            hareket_tipi    TEXT    NOT NULL,
            -- GIRIS | CIKIS | URETIM_TUKETIM | URETIM_CIKTI
            -- SAYIM_DUZELTME | SEVK
            miktar_kg       REAL    NOT NULL,
            -- pozitif = giriş, negatif = çıkış
            onceki_stok     REAL    NOT NULL DEFAULT 0,
            sonraki_stok    REAL    NOT NULL DEFAULT 0,
            aciklama        TEXT,
            referans_tip    TEXT,
            -- SATINALMA_FIS | URETIM | SEVK | RECYCLE | SAYIM
            referans_id     INTEGER,
            olusturan_id    INTEGER,
            olusturma_tarihi TEXT   DEFAULT (datetime('now'))
        )
    """)
    # Sorgularda sık kullanılacak index'ler
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nsh_kart_id
        ON nexgen_stok_hareket(stok_kart_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nsh_tarih
        ON nexgen_stok_hareket(olusturma_tarihi)
    """)
    print("  OK nexgen_stok_hareket oluşturuldu veya zaten mevcut.")

    con.commit()

    # ── 3) sistem_yetki INSERT OR IGNORE ──────────────────────
    print("\n[3] sistem_yetki — nexgen.stok.* kodları:")
    for kod, modul, ad, sira in STOK_YETKILER:
        mevcut = cur.execute(
            "SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)
        ).fetchone()
        if mevcut:
            print(f"  SKIP  Id={mevcut['Id']} Kod='{kod}' zaten mevcut")
        else:
            cur.execute("""
                INSERT INTO sistem_yetki (Kod, Modul, Ad, Aciklama, Sira)
                VALUES (?, ?, ?, ?, ?)
            """, (kod, modul, ad, ad, sira))
            print(f"  EKLENDI Id={cur.lastrowid} Kod='{kod}'")

    con.commit()

    # ── 4) Yönetim rolüne stok yetkileri ─────────────────────
    print(f"\n[4] Yönetim (RolId={YONETIM_ROL_ID}) → stok yetkileri:")
    for kod, _, _, _ in STOK_YETKILER:
        yid_row = cur.execute(
            "SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)
        ).fetchone()
        if not yid_row:
            print(f"  HATA: Kod='{kod}' bulunamadı!")
            continue
        yid = yid_row["Id"]
        mev = cur.execute(
            "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
            (YONETIM_ROL_ID, yid)
        ).fetchone()
        if mev:
            print(f"  SKIP  Id={mev['Id']} Kod='{kod}' zaten mevcut")
        else:
            cur.execute("""
                INSERT INTO sistem_rol_yetki
                  (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                   can_view, can_create, can_update, can_delete,
                   can_approve, can_report, can_manage)
                VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 1, 1)
            """, (YONETIM_ROL_ID, yid))
            print(f"  EKLENDI Kod='{kod}' → Yönetim tam yetki")

    con.commit()

    # ── 5) altan kullanıcısı — nexgen.stok.view override ──────
    print("\n[5] altan → nexgen.stok.view override:")
    tablo_var = cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='user_permission_override'
    """).fetchone()

    if not tablo_var:
        print("  UYARI: user_permission_override tablosu yok — atlandı.")
    else:
        altan = cur.execute(
            "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi='altan'"
        ).fetchone()
        yid_view = cur.execute(
            "SELECT Id FROM sistem_yetki WHERE Kod='nexgen.stok.view'"
        ).fetchone()

        if not altan:
            print("  UYARI: 'altan' kullanıcısı bulunamadı — atlandı.")
        elif not yid_view:
            print("  HATA: nexgen.stok.view yetki kodu yok!")
        else:
            mev = cur.execute("""
                SELECT Id FROM user_permission_override
                WHERE KullaniciId=? AND YetkiId=?
            """, (altan["Id"], yid_view["Id"])).fetchone()
            if mev:
                print(f"  SKIP  altan nexgen.stok.view override zaten mevcut.")
            else:
                cur.execute("""
                    INSERT INTO user_permission_override
                      (KullaniciId, YetkiId, can_view, can_create, can_update,
                       can_delete, can_approve, can_report, can_manage)
                    VALUES (?, ?, 1, 0, 0, 0, 0, 0, 0)
                """, (altan["Id"], yid_view["Id"]))
                print(f"  EKLENDI altan → nexgen.stok.view can_view=1")
        con.commit()

    # ── 6) Örnek stok kartları ─────────────────────────────────
    print("\n[6] Örnek stok kartları:")
    sistem_id = 1  # olusturan_id için simge ID
    for kod, ad, kategori, birim, min_stok, kritik_stok in ORNEK_KARTLAR:
        mevcut = cur.execute(
            "SELECT id FROM nexgen_stok_kart WHERE kod=?", (kod,)
        ).fetchone()
        if mevcut:
            print(f"  SKIP  kod='{kod}' zaten mevcut (id={mevcut['id']})")
        else:
            cur.execute("""
                INSERT INTO nexgen_stok_kart
                  (kod, ad, kategori, birim, minimum_stok, kritik_stok,
                   aktif, olusturan_id, olusturma_tarihi)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
            """, (kod, ad, kategori, birim, min_stok, kritik_stok, sistem_id))
            print(f"  EKLENDI kod='{kod}' ad='{ad}'")

    con.commit()

    # ── 7) Başlangıç stok hareketleri (SAYIM_DUZELTME) ────────
    print("\n[7] Başlangıç stok hareketleri:")
    for kod, miktar in BASLANGIC_STOK.items():
        kart = cur.execute(
            "SELECT id FROM nexgen_stok_kart WHERE kod=?", (kod,)
        ).fetchone()
        if not kart:
            print(f"  HATA: kart bulunamadı kod='{kod}'")
            continue
        kart_id = kart["id"]
        # Zaten hareket var mı?
        mev_hrt = cur.execute(
            "SELECT id FROM nexgen_stok_hareket WHERE stok_kart_id=? AND hareket_tipi='SAYIM_DUZELTME'",
            (kart_id,)
        ).fetchone()
        if mev_hrt:
            print(f"  SKIP  kod='{kod}' başlangıç hareketi zaten mevcut")
            continue
        cur.execute("""
            INSERT INTO nexgen_stok_hareket
              (stok_kart_id, hareket_tipi, miktar_kg,
               onceki_stok, sonraki_stok,
               aciklama, referans_tip, olusturan_id, olusturma_tarihi)
            VALUES (?, 'SAYIM_DUZELTME', ?, 0, ?,
                    'FAZ-1B başlangıç stok girişi', 'SAYIM', ?, datetime('now'))
        """, (kart_id, miktar, miktar, sistem_id))
        print(f"  EKLENDI kod='{kod}' başlangıç stok={miktar} KG")

    con.commit()

    # ── 8) schema_migrations ────────────────────────────
    cur.execute("""
        INSERT OR IGNORE INTO schema_migrations (version, aciklama, uygulama_zamani)
        VALUES ('047', 'nexgen stok kart + hareket motoru (FAZ-1B)', datetime('now'))
    """)
    con.commit()

    # ── 9) Doğrulama ──────────────────────────────────────────
    print("\n[8] Doğrulama:")
    n_kart = cur.execute("SELECT COUNT(*) FROM nexgen_stok_kart").fetchone()[0]
    n_hrt  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"  nexgen_stok_kart   : {n_kart} kayıt")
    print(f"  nexgen_stok_hareket: {n_hrt} kayıt")

    rows = cur.execute("""
        SELECT k.kod, k.kategori,
               COALESCE(SUM(h.miktar_kg), 0) AS mevcut_stok
        FROM nexgen_stok_kart k
        LEFT JOIN nexgen_stok_hareket h ON h.stok_kart_id = k.id
        GROUP BY k.id
    """).fetchall()
    for r in rows:
        print(f"  {r['kod']:15s}  {r['kategori']:15s}  {r['mevcut_stok']:>10.1f} KG")

    con.close()
    print("\nMigration 047 tamamlandı.")


if __name__ == '__main__':
    run()

