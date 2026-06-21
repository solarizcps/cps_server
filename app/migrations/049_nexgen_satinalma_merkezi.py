# -*- coding: utf-8 -*-
"""
Migration 049 — NexGen FAZ-2: Satın Alma Merkezi
=================================================

Yapılanlar:
  1) nexgen_tedarikci        — Tedarikçi master tablosu
  2) nexgen_satin_siparis    — Satın alma sipariş tablosu
  3) sistem_yetki            — 6 yeni yetki kodu (nexgen.satinalma.* + nexgen.tedarikci.*)
  4) Yönetim rolü (RolId=1)  — tam yetki (tedarikçi yönetimi dahil)
  5) Satın Alma rolü         — view + manage + fiyat + tedarikci.view
                               NOT: tedarikci.manage VERİLMEZ — sadece Yönetim
  6) Örnek tedarikçi seed    — ABC Kimya, Efe Petkim
  7) schema_migrations kayıt

YETKİ MİMARİSİ (Rev.1 — FAZ-2 Kapanış):
  nexgen.tedarikci.manage → Sadece Yönetim (Adem/Alpay)
  Satın Alma rolü tedarikçi listesini görebilir (view) ama ekleyemez/düzenleyemez.
  Tedarikçi + stok kart yönetimi → NexGen Yönetim (FAZ-2.5)

KURALLAR:
  - nexgen_stok_hareket tablosuna DOKUNULMAZ.
  - FAZ-2 hiçbir şekilde stok INSERT yapmaz.
  - nexgen_satin_siparis_kalem tablosu FAZ-3'te eklenecek.
  - referans_tip: 'SATINALMA_SIPARIS' (SATINALMA_FIS değil)
  - Idempotent: tekrar çalıştırma güvenli.

Versiyon: 049
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

YONETIM_ROL_ID = 1

# ── Satın Alma rolünü bul (eğer yoksa ID None döner, atlanır) ──────────────
SATINALMA_ROL_ADI = 'Satın Alma'

YENI_YETKILER = [
    # (Kod,                          Modul,   Ad,                         Sira)
    ('nexgen.satinalma.view',   'nexgen', 'NexGen Satın Alma Görüntüleme', 120),
    ('nexgen.satinalma.manage', 'nexgen', 'NexGen Satın Alma Yönetim',     121),
    ('nexgen.satinalma.approve','nexgen', 'NexGen Satın Alma Onay',         122),
    ('nexgen.satinalma.fiyat',  'nexgen', 'NexGen Fiyat/Maliyet Görme',    123),
    ('nexgen.tedarikci.view',   'nexgen', 'NexGen Tedarikçi Görüntüleme',  124),
    ('nexgen.tedarikci.manage', 'nexgen', 'NexGen Tedarikçi Yönetim',      125),
]

ORNEK_TEDARIKCILER = [
    # (kod,         ad,                      ulke, para_birimi, vade)
    ('ABCKIMYA',  'ABC Kimya A.Ş.',          'TR', 'USD',       60),
    ('EFEPETKIM', 'Efe Petrokimya San. Ltd.', 'TR', 'TRY',       30),
]


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 65)
    print("Migration 049 — NexGen FAZ-2: Satın Alma Merkezi")
    print("=" * 65)

    # ── Güvenlik: nexgen_stok_hareket tablosuna dokunulmadığını doğrula ─
    print("\n[KONTROL] nexgen_stok_hareket tablosu korunuyor:")
    hrt_say = cur.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket"
    ).fetchone()[0]
    print(f"  Mevcut hareket sayısı: {hrt_say} — bu değer değişmeyecek.")

    # ── 1) nexgen_tedarikci tablosu ────────────────────────────────────
    print("\n[1] nexgen_tedarikci tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_tedarikci (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            kod               TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            ad                TEXT    NOT NULL,
            ulke              TEXT    NOT NULL DEFAULT 'TR',
            para_birimi       TEXT    NOT NULL DEFAULT 'TRY',
            varsayilan_vade   INTEGER NOT NULL DEFAULT 30,
            iletisim_ad       TEXT,
            iletisim_tel      TEXT,
            iletisim_email    TEXT,
            notlar            TEXT,
            aktif             INTEGER NOT NULL DEFAULT 1,
            olusturan_id      INTEGER,
            olusturma_tarihi  TEXT    DEFAULT (datetime('now')),
            guncelleyen_id    INTEGER,
            guncelleme_tarihi TEXT
        )
    """)
    print("  OK nexgen_tedarikci oluşturuldu veya zaten mevcut.")

    # ── 2) nexgen_satin_siparis tablosu ───────────────────────────────
    print("\n[2] nexgen_satin_siparis tablosu:")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nexgen_satin_siparis (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            siparis_no          TEXT    NOT NULL UNIQUE,
            tedarikci_id        INTEGER NOT NULL
                                    REFERENCES nexgen_tedarikci(id),
            stok_kart_id        INTEGER NOT NULL
                                    REFERENCES nexgen_stok_kart(id),
            siparis_tarihi      TEXT    NOT NULL DEFAULT (date('now')),
            beklenen_teslim     TEXT,
            siparis_miktari_kg  REAL    NOT NULL,
            birim_fiyat         REAL,
            para_birimi         TEXT    NOT NULL DEFAULT 'TRY',
            kur                 REAL,
            birim_fiyat_try     REAL,
            toplam_tutar_try    REAL,
            vade_gun            INTEGER,
            vade_tarihi         TEXT,
            durum               TEXT    NOT NULL DEFAULT 'BEKLIYOR',
            aciklama            TEXT,
            onay_durumu         TEXT    NOT NULL DEFAULT 'TASLAK',
            olusturan_id        INTEGER,
            olusturma_tarihi    TEXT    DEFAULT (datetime('now')),
            onaylayan_id        INTEGER,
            onay_tarihi         TEXT,
            guncelleyen_id      INTEGER,
            guncelleme_tarihi   TEXT,
            -- durum: BEKLIYOR | KISMI_TESLIM | TAMAMLANDI | IPTAL
            -- onay_durumu: TASLAK | ONAY_BEKLIYOR | ONAYLANDI | REDDEDILDI
            CHECK (durum IN ('BEKLIYOR','KISMI_TESLIM','TAMAMLANDI','IPTAL')),
            CHECK (onay_durumu IN ('TASLAK','ONAY_BEKLIYOR','ONAYLANDI','REDDEDILDI'))
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nss_tedarikci
        ON nexgen_satin_siparis(tedarikci_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nss_stok_kart
        ON nexgen_satin_siparis(stok_kart_id)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nss_durum
        ON nexgen_satin_siparis(durum, onay_durumu)
    """)
    print("  OK nexgen_satin_siparis oluşturuldu veya zaten mevcut.")

    con.commit()

    # ── 3) nexgen_stok_hareket dokunulmadığını tekrar doğrula ─────────
    print("\n[KONTROL] Stok hareket sayısı değişmedi mi?")
    hrt_say2 = cur.execute(
        "SELECT COUNT(*) FROM nexgen_stok_hareket"
    ).fetchone()[0]
    assert hrt_say2 == hrt_say, "HATA: nexgen_stok_hareket sayısı değişti!"
    print(f"  OK — hâlâ {hrt_say2} hareket, stok motoru korundu.")

    # ── 4) sistem_yetki ───────────────────────────────────────────────
    print("\n[3] sistem_yetki — nexgen.satinalma.* + nexgen.tedarikci.*:")
    for kod, modul, ad, sira in YENI_YETKILER:
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

    # ── 5) Yönetim rolü — tam yetki ──────────────────────────────────
    print(f"\n[4] Yönetim (RolId={YONETIM_ROL_ID}) → tüm satın alma yetkileri:")
    for kod, _, _, _ in YENI_YETKILER:
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
            print(f"  SKIP  Kod='{kod}' Yönetim zaten mevcut")
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

    # ── 6) Satın Alma rolü — fiyat görür, stok yönetemez ─────────────
    print(f"\n[5] '{SATINALMA_ROL_ADI}' rolü → satın alma yetkileri (stok yok):")
    sa_rol = cur.execute(
        "SELECT Id FROM sistem_rol WHERE Ad=?", (SATINALMA_ROL_ADI,)
    ).fetchone()
    if not sa_rol:
        print(f"  UYARI: '{SATINALMA_ROL_ADI}' rolü DB'de yok — atlandı.")
        print("  (Rol oluşturulduktan sonra bu migration tekrar çalıştırılabilir.)")
    else:
        sa_rol_id = sa_rol["Id"]
        # view + view_tedarikci: sadece görüntüleme
        # manage: sipariş oluşturma/güncelleme
        # fiyat: fiyat/maliyet alanlarını görme
        # tedarikci.view: listeden seçebilir
        # tedarikci.manage: VERİLMEZ — sadece Yönetim rolüne verilir
        SATINALMA_YETKİ_MAP = {
            'nexgen.satinalma.view':    dict(can_view=1),
            'nexgen.satinalma.manage':  dict(can_view=1, can_create=1, can_update=1),
            'nexgen.satinalma.fiyat':   dict(can_view=1),
            'nexgen.tedarikci.view':    dict(can_view=1),
            # nexgen.tedarikci.manage — NexGen Yönetim (FAZ-2.5) yetkisidir, buraya eklenmez
        }
        for kod, izinler in SATINALMA_YETKİ_MAP.items():
            yid_row = cur.execute(
                "SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)
            ).fetchone()
            if not yid_row:
                print(f"  HATA: Kod='{kod}' bulunamadı!")
                continue
            yid = yid_row["Id"]
            mev = cur.execute(
                "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?",
                (sa_rol_id, yid)
            ).fetchone()
            if mev:
                print(f"  SKIP  Kod='{kod}' Satın Alma zaten mevcut")
            else:
                cur.execute("""
                    INSERT INTO sistem_rol_yetki
                      (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                       can_view, can_create, can_update, can_delete,
                       can_approve, can_report, can_manage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0)
                """, (
                    sa_rol_id, yid,
                    izinler.get('can_view', 0),
                    izinler.get('can_update', 0),
                    izinler.get('can_view', 0),
                    izinler.get('can_create', 0),
                    izinler.get('can_update', 0),
                    izinler.get('can_view', 0),
                ))
                print(f"  EKLENDI Kod='{kod}' → Satın Alma: {izinler}")

    con.commit()

    # ── 7) Örnek tedarikçiler ─────────────────────────────────────────
    print("\n[6] Örnek tedarikçiler:")
    for kod, ad, ulke, pb, vade in ORNEK_TEDARIKCILER:
        mev = cur.execute(
            "SELECT id FROM nexgen_tedarikci WHERE kod=?", (kod,)
        ).fetchone()
        if mev:
            print(f"  SKIP  kod='{kod}' zaten mevcut (id={mev['id']})")
        else:
            cur.execute("""
                INSERT INTO nexgen_tedarikci
                  (kod, ad, ulke, para_birimi, varsayilan_vade,
                   aktif, olusturan_id, olusturma_tarihi)
                VALUES (?, ?, ?, ?, ?, 1, 1, datetime('now'))
            """, (kod, ad, ulke, pb, vade))
            print(f"  EKLENDI kod='{kod}' ad='{ad}'")

    con.commit()

    # ── 8) schema_migrations ─────────────────────────────────────────
    sm_kolonlar = [r[1] for r in cur.execute("PRAGMA table_info(schema_migrations)").fetchall()]
    if 'description' in sm_kolonlar and 'applied_at' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
            VALUES (49, 'nexgen satin alma merkezi FAZ-2', datetime('now'))
        """)
    elif 'aciklama' in sm_kolonlar:
        cur.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, aciklama)
            VALUES (49, 'nexgen satin alma merkezi FAZ-2')
        """)
    else:
        cur.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (49)")
    con.commit()

    # ── 9) Doğrulama ─────────────────────────────────────────────────
    print("\n[7] Doğrulama:")
    n_ted  = cur.execute("SELECT COUNT(*) FROM nexgen_tedarikci").fetchone()[0]
    n_sip  = cur.execute("SELECT COUNT(*) FROM nexgen_satin_siparis").fetchone()[0]
    hrt_son = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"  nexgen_tedarikci       : {n_ted} kayıt")
    print(f"  nexgen_satin_siparis   : {n_sip} kayıt")
    print(f"  nexgen_stok_hareket    : {hrt_son} kayıt (değişmedi ✓)" if hrt_son == hrt_say else
          f"  nexgen_stok_hareket    : UYARI — {hrt_son} kayıt (başlangıç: {hrt_say})")

    tedarikciler = cur.execute("SELECT id, kod, ad, para_birimi FROM nexgen_tedarikci").fetchall()
    for t in tedarikciler:
        print(f"  Tedarikçi id={t['id']}  {t['kod']:15s}  {t['ad']}  ({t['para_birimi']})")

    con.close()
    print("\nMigration 049 tamamlandı.")


if __name__ == '__main__':
    run()
