# -*- coding: utf-8 -*-
"""
Migration 099 — NexGen FAZ-PLANLAMA-MIMARI-01B: Planlama Uygunluk Altyapisi
=============================================================================
[1] nexgen_uretim_tipi          — master: ENJEKSIYON(aktif), DOKME(aktif), SOGUK_SICAK(pasif)
[2] nexgen_cari_uretim_tipi     — junction: cari <-> uretim tipi
    NOT: nexgen_formul.uretim_tipi_id EKLENMEZ — formul havuzda genel kalir.
[3] nexgen_planlama_uygunluk    — cari+tip+formul+renk kombinasyon tablosu
    rf_renk_id ve rf_rev_no NULL kabul eder (boya sonradan baglanabilir).

Mimari karar:
  - Formul tek cariye veya tek uretim tipine kitlenmez.
  - nexgen_formul uzerinde cari_id veya uretim_tipi_id OLMAZ.
  - Cari iliskisi yalnizca nexgen_cari_uretim_tipi ve
    nexgen_planlama_uygunluk uzerinden yonetilir.

Seed:
  - ENJEKSIYON: aktif=1
  - DOKME:      aktif=1
  - SOGUK_SICAK: aktif=0 (mimari korunuyor, UI'da goruntulenmez,
    Seha'ya seed edilmez — ileride kullanici karariyla aktif edilebilir)
  - Cari-uretim tipi seed: yalnizca aktif iliskiler
    Solariz->ENJEKSIYON, Poltab->ENJEKSIYON+DOKME
    (Seha->SOGUK_SICAK seed edilmez cunku SOGUK_SICAK pasif)

Kurallar:
  - Idempotent: tekrar calistirilabilir
  - Mevcut kayitlar silinmez, degistirilmez
  - Eski formuller otomatik uretim_tipi_id almaz (kolon nexgen_formul'a eklenmez)
  - Mevcut RF'lere renk_varyant_id atanmaz
  - nexgen_stok_hareket DOKUNULMAZ
  - nexgen_recete_kalem DOKUNULMAZ
  - AR-GE tablet DOKUNULMAZ

ENTEGRASYON FAZ ZORUNLU KABUL KRİTERİ — FORMÜL KODU VE ADI:
  nexgen_formul.kod:
    - Kullanici TARAFINDAN YAZILMAZ — sistem otomatik uretir
    - UI'da salt okunur gosterilir (readonly input)
    - Benzersiz ve sirali — mevcut + pasif + test formullerle catisma kontrolu yapilir
    - Ayni anda iki kayit acarsa mukerrer kod olusmasini onlemek icin
      transaction icinde uretilir ve kesinlesir
    - Kayit basarisiz olursa kod da gecersiz sayilir (geri alinir)
    - Kullanici sonradan degistiremez (update yasaklidir)
    - Kod formati entegrasyon fazinda mevcut standarda gore belirlenir;
      gecici veya rastgele kod uretilmez
  nexgen_formul.ad:
    - Kullanici tarafindan manuel yazilir — zorunlu alan
    - Bos veya yalnizca bosluk iceren ad KABUL EDILMEZ
    - Kaydetmeden once strip() uygulanir (bas/son bosluklar temizlenir)
    - Formul adi gerektiginde duzenlenebilir; otomatik kod degismez
    - Kod ile ad birbirine karistirilmaz
"""

import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def _kolon_var(cur, tablo, kolon):
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def _tablo_var(cur, tablo):
    r = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return r is not None


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadi: {DB_PATH}")
        return

    # Yedek al
    import shutil
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = DB_PATH.replace('.db', f'_backup_pre099_{ts}.db')
    try:
        shutil.copy2(DB_PATH, bak)
        print(f"[YEDEK] {os.path.basename(bak)}")
    except Exception as e:
        print(f"[UYARI] Yedek alinamadi: {e}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 70)
    print("Migration 099 - nexgen_planlama_uygunluk altyapisi")
    print(f"DB: {os.path.abspath(DB_PATH)}")
    print("=" * 70)

    # Guvenlik sayimi
    sh_onceki   = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    rf_onceki   = cur.execute("SELECT COUNT(*) FROM nexgen_rf_renk").fetchone()[0]
    rfk_onceki  = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kalem").fetchone()[0]
    frm_onceki  = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    plan_onceki = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan").fetchone()[0]
    print(f"\n[ONCESI] sh={sh_onceki}  rf_renk={rf_onceki}  rf_kalem={rfk_onceki}"
          f"  formul={frm_onceki}  plan={plan_onceki}")

    # ═══════════════════════════════════════════════════════════════════
    # [1] nexgen_uretim_tipi
    # ═══════════════════════════════════════════════════════════════════
    print("\n[1] nexgen_uretim_tipi tablosu:")
    if not _tablo_var(cur, 'nexgen_uretim_tipi'):
        cur.execute("""
            CREATE TABLE nexgen_uretim_tipi (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                kod              TEXT    NOT NULL UNIQUE,
                ad               TEXT    NOT NULL,
                aciklama         TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                guncelleme_tarihi TEXT
            )
        """)
        con.commit()
        print("  OK    nexgen_uretim_tipi olusturuldu")
    else:
        print("  SKIP  nexgen_uretim_tipi zaten var")

    # Index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nut_kod ON nexgen_uretim_tipi(kod)")
    con.commit()

    # Seed: aktif tipler yalnizca ENJEKSIYON ve DOKME
    # SOGUK_SICAK: mimari korunuyor ama aktif=0 ile ekleniyor,
    #              UI'da goruntulenmeyecek, yeni formul ekraninda secilemeyecek.
    #              Ilerde kullanici karariyla aktif=1 yapilabilir.
    seed_tipler = [
        ('ENJEKSIYON',  'Enjeksiyon',  'Enjeksiyon makine tipi',        1),
        ('DOKME',       'Dokme',       'Dokme uretim tipi',              1),
        ('SOGUK_SICAK', 'Soguk/Sicak', 'Soguk ve Sicak proses (pasif)', 0),
    ]
    for kod, ad, aciklama, aktif in seed_tipler:
        mevcut = cur.execute(
            "SELECT id FROM nexgen_uretim_tipi WHERE kod=?", (kod,)
        ).fetchone()
        if not mevcut:
            cur.execute(
                "INSERT INTO nexgen_uretim_tipi (kod, ad, aciklama, aktif) VALUES (?, ?, ?, ?)",
                (kod, ad, aciklama, aktif)
            )
            durum_label = 'AKTIF' if aktif else 'PASIF'
            print(f"  OK    SEED {kod} -> {ad} [{durum_label}]")
        else:
            print(f"  SKIP  SEED {kod} zaten var (id={mevcut['id']})")
    con.commit()

    # ═══════════════════════════════════════════════════════════════════
    # [2] nexgen_cari_uretim_tipi
    # ═══════════════════════════════════════════════════════════════════
    print("\n[2] nexgen_cari_uretim_tipi tablosu:")
    if not _tablo_var(cur, 'nexgen_cari_uretim_tipi'):
        cur.execute("""
            CREATE TABLE nexgen_cari_uretim_tipi (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                cari_id          INTEGER NOT NULL,
                uretim_tipi_id   INTEGER NOT NULL,
                aktif            INTEGER NOT NULL DEFAULT 1,
                aciklama         TEXT,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (cari_id, uretim_tipi_id)
            )
        """)
        con.commit()
        print("  OK    nexgen_cari_uretim_tipi olusturuldu")
    else:
        print("  SKIP  nexgen_cari_uretim_tipi zaten var")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_ncut_cari ON nexgen_cari_uretim_tipi(cari_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ncut_tip  ON nexgen_cari_uretim_tipi(uretim_tipi_id)")
    con.commit()

    # ═══════════════════════════════════════════════════════════════════
    # [3] nexgen_formul.uretim_tipi_id — KASITLI OLARAK UYGULANMIYOR
    # ═══════════════════════════════════════════════════════════════════
    # MİMARİ KARAR: Formul havuzda genel kalir.
    # nexgen_formul tablosuna cari_id veya uretim_tipi_id EKLENMEZ.
    # Uretim tipi iliskisi yalnizca nexgen_cari_uretim_tipi ve
    # nexgen_planlama_uygunluk uzerinden yonetilir.
    print("\n[3] nexgen_formul.uretim_tipi_id: ATLANADI (mimari karar - formul genel havuzda kalir)")

    # ═══════════════════════════════════════════════════════════════════
    # [4] nexgen_planlama_uygunluk
    # ═══════════════════════════════════════════════════════════════════
    # Mimari notlar:
    #   cari_id       NOT NULL  — eksik alanlarda kayit olusturulmaz
    #   rf_renk_id    NULL OK   — boya sonradan baglanabilir
    #   rf_rev_no     NULL OK   — boya sonradan baglanabilir
    #   CHECK(rf)               — rf_renk_id ve rf_rev_no birlikte dolu veya birlikte NULL olmali
    #   UNIQUE index            — IFNULL ile NULL degerleri -1'e donusturur, DB seviyesi tekil
    #   RF guncelleme           — RF sonradan secildiginde INSERT degil UPDATE yapilir
    print("\n[4] nexgen_planlama_uygunluk tablosu:")
    if not _tablo_var(cur, 'nexgen_planlama_uygunluk'):
        cur.execute("""
            CREATE TABLE nexgen_planlama_uygunluk (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Cari ve uretim tipi: kayit olusturulabilmesi icin her ikisi zorunlu
                cari_id          INTEGER NOT NULL,
                uretim_tipi_id   INTEGER NOT NULL,

                -- Formul iliskisi: formul havuzda genel, birden fazla cariye baglanabilir
                formul_id        INTEGER NOT NULL,
                renk_varyant_id  INTEGER NOT NULL,

                -- RF iliskisi: NULL olabilir (boya sonradan baglanir).
                -- Gecerli durumlar:
                --   rf_renk_id IS NULL AND rf_rev_no IS NULL   (henuz boya yok)
                --   rf_renk_id IS NOT NULL AND rf_rev_no IS NOT NULL  (boya bagli)
                -- Gecersiz: biri dolu digeri NULL.
                rf_renk_id       INTEGER,
                rf_rev_no        INTEGER,

                kalip_carpani    REAL,
                varsayilan_mi    INTEGER NOT NULL DEFAULT 1,
                durum            TEXT    NOT NULL DEFAULT 'AKTIF',
                aciklama         TEXT,
                olusturan_id     INTEGER,
                olusturma_tarihi TEXT    NOT NULL DEFAULT (datetime('now')),
                guncelleyen_id   INTEGER,
                guncelleme_tarihi TEXT,
                aktif            INTEGER NOT NULL DEFAULT 1,

                -- RF alanlari birlikte dolu veya birlikte NULL olmali
                CHECK (
                    (rf_renk_id IS NULL     AND rf_rev_no IS NULL)
                    OR
                    (rf_renk_id IS NOT NULL AND rf_rev_no IS NOT NULL)
                )
            )
        """)
        con.commit()
        print("  OK    nexgen_planlama_uygunluk olusturuldu")
        print("  OK    CHECK(rf_renk_id, rf_rev_no) birlikte dolu veya birlikte NULL")
    else:
        print("  SKIP  nexgen_planlama_uygunluk zaten var")
        # Eksik kolon kontrolu (idempotent)
        for kolon, tanim in [
            ('kalip_carpani',     'REAL'),
            ('varsayilan_mi',     'INTEGER NOT NULL DEFAULT 1'),
            ('guncelleyen_id',    'INTEGER'),
            ('guncelleme_tarihi', 'TEXT'),
        ]:
            if not _kolon_var(cur, 'nexgen_planlama_uygunluk', kolon):
                cur.execute(f"ALTER TABLE nexgen_planlama_uygunluk ADD COLUMN {kolon} {tanim}")
                con.commit()
                print(f"  OK    nexgen_planlama_uygunluk.{kolon} eklendi")

    # ── Indexler ──────────────────────────────────────────────────────
    # Tekil performans indexleri
    sade_indexler = [
        ("idx_npu_cari",        "nexgen_planlama_uygunluk(cari_id)"),
        ("idx_npu_tip",         "nexgen_planlama_uygunluk(uretim_tipi_id)"),
        ("idx_npu_formul",      "nexgen_planlama_uygunluk(formul_id)"),
        ("idx_npu_renk",        "nexgen_planlama_uygunluk(renk_varyant_id)"),
        ("idx_npu_rf",          "nexgen_planlama_uygunluk(rf_renk_id)"),
        ("idx_npu_aktif",       "nexgen_planlama_uygunluk(aktif, durum)"),
        ("idx_npu_cari_formul", "nexgen_planlama_uygunluk(cari_id, formul_id)"),
    ]
    for idx_ad, idx_hedef in sade_indexler:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_ad} ON {idx_hedef}")
    con.commit()
    print(f"  OK    {len(sade_indexler)} performans index")

    # ── DB seviyesi UNIQUE index: IFNULL ile NULL -> -1 donusumu ───────
    # SQLite expression index: CREATE UNIQUE INDEX ... ON tablo(expr, expr, ...)
    # SQLite 3.9.0+ destekler. IFNULL(NULL, -1) = -1 sayesinde NULL'lar
    # karsilastirilabilir hale gelir ve DB seviyesi tekil koruma saglanir.
    # -1 deger hicbir gercek rf_renk_id veya rf_rev_no ile catismaz
    # cunku auto-increment id degerleri > 0 olacaktir.
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_npu_kullanim
        ON nexgen_planlama_uygunluk (
            cari_id,
            uretim_tipi_id,
            formul_id,
            renk_varyant_id,
            IFNULL(rf_renk_id, -1),
            IFNULL(rf_rev_no,  -1)
        )
    """)
    con.commit()
    print("  OK    UNIQUE index uq_npu_kullanim (IFNULL NULL->-1 ile)")
    print("  INFO  RF sonradan baglandiginda INSERT degil UPDATE yapilmali")

    # ═══════════════════════════════════════════════════════════════════
    # [5] Cari ↔ Uretim Tipi ilk eslesmeleri (kesin cari isim eslesmesi)
    # ═══════════════════════════════════════════════════════════════════
    print("\n[5] Cari <-> Uretim Tipi ilk eslesmeleri:")

    # Uretim tipi ID'lerini al
    tip_map = {}
    for row in cur.execute("SELECT id, kod FROM nexgen_uretim_tipi WHERE aktif=1"):
        tip_map[row['kod']] = row['id']

    if not tip_map:
        print("  UYARI  uretim tipi kayitlari bulunamadi - seed kontrolu")
    else:
        # Tum aktif cariler
        cariler = cur.execute(
            "SELECT id, unvan, cari_kod FROM nexgen_cari WHERE aktif=1"
        ).fetchall()

        # Eslestirme kurallari: yalnizca AKTIF uretim tipine sahip iliskiler seed edilir.
        # SOGUK_SICAK pasif oldugu icin Seha'ya seed edilmez.
        # Seha iliskisi ileride admin tarafindan elle eklenebilir.
        #
        # SOLARIZ NOTU: nexgen_cari tablosunda "solariz" iceren unvan veya
        # cari_kod kaydı bulunamadi (14 Temmuz 2026 itibariyle). Bu nedenle
        # Solariz -> ENJEKSIYON iliskisi bu migration tarafindan otomatik
        # seed edilememektedir. Solariz cari kaydi sisteme eklendiginde
        # bu iliskinin admin tarafindan elle girilmesi gerekmektedir.
        #
        # KESIN KURAL: Belirsiz eslesmede kayit eklenmez.
        # Yalnizca asagidaki tanimlanmis anahtar kelimelerle kesin eslesen
        # cariler seed edilir. Yanlis cariye seed yapilmaz.
        eslestirme_kurallari = [
            # (anahtar_kelime_listesi, tip_kodlari_listesi, aciklama)
            # NOT: Solariz DB'de bulunmadiginda bu kural eslesmeyecek ve WARN verilecek
            (['solariz'],  ['ENJEKSIYON'], 'Solariz -> ENJEKSIYON'),
            (['poltab'],   ['ENJEKSIYON', 'DOKME'], 'Poltab -> ENJEKSIYON + DOKME'),
            # seha -> SOGUK_SICAK: pasif tip, seed edilmiyor
        ]

        # Hangi kurallarin eslesmedigini takip et
        eslesen_kurallar = set()

        eklenen = 0
        atlanmis = []
        for cari in cariler:
            unvan_lower = (cari['unvan'] or '').lower()
            kod_lower   = (cari['cari_kod'] or '').lower()
            eslesti = False
            for anahtar_list, tip_kodlari, kural_aciklama in eslestirme_kurallari:
                for anahtar in anahtar_list:
                    if anahtar in unvan_lower or anahtar in kod_lower:
                        eslesti = True
                        eslesen_kurallar.add(kural_aciklama)
                        for tip_kodu in tip_kodlari:
                            tip_id = tip_map.get(tip_kodu)
                            if not tip_id:
                                continue
                            mevcut = cur.execute(
                                "SELECT id FROM nexgen_cari_uretim_tipi "
                                "WHERE cari_id=? AND uretim_tipi_id=?",
                                (cari['id'], tip_id)
                            ).fetchone()
                            if not mevcut:
                                cur.execute("""
                                    INSERT INTO nexgen_cari_uretim_tipi
                                        (cari_id, uretim_tipi_id, aktif, aciklama)
                                    VALUES (?, ?, 1, 'Migration 099 otomatik eslestirme')
                                """, (cari['id'], tip_id))
                                eklenen += 1
                                try:
                                    print(f"  OK    Cari '{cari['unvan']}' (id={cari['id']}) -> {tip_kodu}")
                                except UnicodeEncodeError:
                                    print(f"  OK    Cari id={cari['id']} -> {tip_kodu}")
                        break  # bu cari icin ilk eslesen kural yeter
            if not eslesti:
                atlanmis.append(cari['unvan'])

        # Eslesmeyen kurallari WARN ile bildir
        for anahtar_list, tip_kodlari, kural_aciklama in eslestirme_kurallari:
            if kural_aciklama not in eslesen_kurallar:
                print(f"  WARN  Kural eslesmedi (cari bulunamadi): {kural_aciklama}")

        con.commit()
        print(f"  OZET  Eklenen eslestirme: {eklenen}")
        if atlanmis:
            print(f"  INFO  Uretim tipi atanmamis cariler ({len(atlanmis)}):")
            for a in atlanmis[:20]:
                try:
                    print(f"        - {a}")
                except UnicodeEncodeError:
                    print(f"        - (Turkce karakter iceren cari)")
            if len(atlanmis) > 20:
                print(f"        ... ve {len(atlanmis)-20} daha")

    # ═══════════════════════════════════════════════════════════════════
    # Guvenlik: dokunulmaz sayimlar
    # ═══════════════════════════════════════════════════════════════════
    sh_sonraki   = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    rf_sonraki   = cur.execute("SELECT COUNT(*) FROM nexgen_rf_renk").fetchone()[0]
    rfk_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kalem").fetchone()[0]
    frm_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_formul").fetchone()[0]
    plan_sonraki = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan").fetchone()[0]

    print(f"\n[SONRASI] sh={sh_sonraki}  rf_renk={rf_sonraki}  rf_kalem={rfk_sonraki}"
          f"  formul={frm_sonraki}  plan={plan_sonraki}")
    assert sh_sonraki   == sh_onceki,   "HATA: stok_hareket sayisi degisti!"
    assert rf_sonraki   == rf_onceki,   "HATA: rf_renk sayisi degisti!"
    assert rfk_sonraki  == rfk_onceki,  "HATA: rf_kalem sayisi degisti!"
    assert frm_sonraki  == frm_onceki,  "HATA: formul sayisi degisti!"
    assert plan_sonraki == plan_onceki, "HATA: uretim_plan sayisi degisti!"

    # schema_migrations
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(99)")
        con.commit()
        print("\n  OK    schema_migrations version=99")
    except Exception as e:
        print(f"\n  WARN  schema_migrations: {e}")

    # Ozet
    nut_say  = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_tipi").fetchone()[0]
    ncut_say = cur.execute("SELECT COUNT(*) FROM nexgen_cari_uretim_tipi").fetchone()[0]
    npu_say  = cur.execute("SELECT COUNT(*) FROM nexgen_planlama_uygunluk").fetchone()[0]

    nut_aktif = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_tipi WHERE aktif=1"
    ).fetchone()[0]
    nut_pasif = cur.execute(
        "SELECT COUNT(*) FROM nexgen_uretim_tipi WHERE aktif=0"
    ).fetchone()[0]

    print("\n" + "=" * 70)
    print("OZET")
    print("=" * 70)
    print(f"  nexgen_uretim_tipi       : {nut_say} kayit ({nut_aktif} aktif, {nut_pasif} pasif)")
    print(f"  nexgen_cari_uretim_tipi  : {ncut_say} kayit (seed: Poltab eklendi; Solariz DB'de bulunamazsa elle eklenecek)")
    print(f"  nexgen_planlama_uygunluk : {npu_say} kayit")
    print(f"  nexgen_formul.uretim_tipi_id: EKLENMEDI (mimari karar)")
    print(f"  nexgen_planlama_uygunluk.rf_renk_id: NULL kabul eder")
    print(f"  stok_hareket delta       : {sh_sonraki - sh_onceki} (0 olmali)")
    print("=" * 70)
    print("Migration 099 tamamlandi\n")

    con.close()


def rollback():
    """
    SINIRLI ROLLBACK — yeni tablolari kaldirir.

    Bu migration nexgen_formul tablosuna hicbir kolon eklemez (mimari karar).
    Tam geri donus icin DB yedeginizi kullanin.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    print("\n=== Rollback 099 (SINIRLI) ===")
    for tablo in ('nexgen_planlama_uygunluk', 'nexgen_cari_uretim_tipi', 'nexgen_uretim_tipi'):
        cur.execute(f"DROP TABLE IF EXISTS {tablo}")
    for idx in ('idx_nut_kod', 'idx_ncut_cari', 'idx_ncut_tip',
                'idx_npu_cari', 'idx_npu_tip', 'idx_npu_formul',
                'idx_npu_renk', 'idx_npu_rf', 'idx_npu_aktif',
                'idx_npu_cari_formul', 'uq_npu_kullanim'):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")
    try:
        cur.execute("DELETE FROM schema_migrations WHERE version=99")
    except Exception:
        pass
    con.commit()
    con.close()
    print("  OK    3 tablo kaldirildi")
    print("  INFO  nexgen_formul degistirilmemisti - tam rollback mumkun")
    print("=== Rollback 099 tamamlandi ===\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        run()
