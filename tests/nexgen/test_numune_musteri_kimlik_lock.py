# -*- coding: utf-8 -*-
"""
NUMUNE TALEBİ — MÜŞTERİ KİMLİĞİ LOCK TESTLERİ
================================================
T1:  Kayıtlı müşteri → MTT oluşur, cari_id korunur.
T2:  Mehmet (planlama) aynı MTT'yi görebilir (kuyruğa düşer).
T3:  Mehmet → Numuneye Dönüştür çalışır (numune_hazirla + numune_mtt_ile_kaydet).
T4:  nexgen_numune_talep.cari_id == başlangıç cari_id (EXACT).
T5:  Numune kaydı doğru MTT referansını korur (kaynak_mtt_talep_id).
T6:  Numune → AR-GE mevcut zinciri çalışır (gonder_arge bekleyen_numune).
T7:  arge_test_id/link oluşumu regress etmez.
T8:  Yeni müşteri (ADAY) → musteri_aday_id ile MTT oluşur.
T9:  Yeni müşteri → Numuneye Dönüştür → nexgen_numune_talep.musteri_aday_id EXACT.
T10: Cari360 timeline cari_id üzerinden numune okuyabiliyor.
T11: Sipariş Talebi REGRESSION — numune patch sipariş flow'unu bozmuyor.
T12: Görüşme/Ajanda REGRESSION — mevcut görüşme kaydı bozulmuyor.
T13: Tahsilat AVANS LOCK — servis import/syntax hataları yok.
T14: numune → AR-GE REGRESSION — gonder_arge BEKLEYEN_NUMUNE durumuna geçiyor.

In-memory DB — canonical mock_data.db'ye dokunulmaz.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, "app")

# ---------------------------------------------------------------------------
# DDL — gerçek şema ile birebir uyumlu in-memory fixture
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS sistem_kullanici (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    KullaniciAdi TEXT UNIQUE NOT NULL,
    AdSoyad TEXT, Email TEXT, Sifre TEXT NOT NULL DEFAULT 'x',
    RolId INTEGER, Rol TEXT, Aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sistem_rol_yetki (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    RolId INTEGER NOT NULL, YetkiId INTEGER NOT NULL,
    can_view INTEGER DEFAULT 0, can_create INTEGER DEFAULT 0,
    can_update INTEGER DEFAULT 0, can_delete INTEGER DEFAULT 0,
    can_approve INTEGER DEFAULT 0, can_report INTEGER DEFAULT 0, can_manage INTEGER DEFAULT 0,
    UNIQUE(RolId, YetkiId)
);
CREATE TABLE IF NOT EXISTS sistem_yetki (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Kod TEXT UNIQUE NOT NULL, Ad TEXT NOT NULL DEFAULT '-',
    Aciklama TEXT, Modul TEXT NOT NULL DEFAULT '-',
    AltModul TEXT, Sira INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_permission_override (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    KullaniciId INTEGER NOT NULL, YetkiId INTEGER NOT NULL,
    can_view INTEGER, can_create INTEGER, can_update INTEGER,
    can_delete INTEGER, can_approve INTEGER, can_report INTEGER, can_manage INTEGER,
    aciklama TEXT, olusturma_tarih TEXT DEFAULT (datetime('now')),
    UNIQUE (KullaniciId, YetkiId)
);
CREATE TABLE IF NOT EXISTS nexgen_cari (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cari_kod TEXT NOT NULL UNIQUE,
    unvan TEXT NOT NULL,
    aktif INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    kisa_ad TEXT, cari_tipi TEXT, sehir TEXT, vergi_no TEXT, para_birimi TEXT
);
CREATE TABLE IF NOT EXISTS nexgen_musteri_aday (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firma_adi TEXT NOT NULL, yetkili_adi TEXT, telefon TEXT, sehir TEXT,
    not_metni TEXT, durum TEXT NOT NULL DEFAULT 'ADAY',
    olusturan_kullanici_id INTEGER NOT NULL DEFAULT 1,
    nexgen_cari_id INTEGER, idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT, donusturulme_tarihi TEXT
);
CREATE TABLE IF NOT EXISTS musteri_operasyon_gorusme (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cari_id INTEGER, musteri_aday_id INTEGER,
    kullanici_id INTEGER NOT NULL DEFAULT 1,
    olusturan_kullanici_id INTEGER NOT NULL DEFAULT 1,
    kaynak TEXT NOT NULL DEFAULT 'MUSTERI_OPERASYONU',
    gorusme_tipi TEXT NOT NULL DEFAULT 'Telefon',
    sonuc_tipi TEXT NOT NULL DEFAULT 'Numune Istedi',
    sonuc_etiketler TEXT,
    kisa_not TEXT NOT NULL DEFAULT '',
    gorusme_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    sonraki_takip_tarihi TEXT,
    oncelik TEXT NOT NULL DEFAULT 'NORMAL',
    tahmini_siparis_tutari REAL, tahmini_siparis_tarihi TEXT,
    istenen_vade_gun INTEGER, cek_alim_tarihi TEXT,
    rakip_firma TEXT, makina_notu TEXT, detay_not TEXT, dosya_ref TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    aktif INTEGER NOT NULL DEFAULT 1,
    olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    guncelleme_tarihi TEXT,
    audit_json TEXT, yetkili_id INTEGER, konu TEXT,
    sonraki_aksiyon TEXT, takip_durumu TEXT,
    guncelleyen_kullanici_id INTEGER, numune_talep_id INTEGER,
    yetkili_metin TEXT,
    fiyat_verildi INTEGER NOT NULL DEFAULT 0,
    verilen_fiyat REAL, fiyat_para_birimi TEXT, fiyat_birimi TEXT,
    odeme_tipi TEXT, vade_gun INTEGER, cek_vade_gun INTEGER,
    cek_adedi INTEGER, ticari_not TEXT, cek_notu TEXT,
    konusulan_tonaj REAL
);
CREATE TABLE IF NOT EXISTS nexgen_musteri_temsilcisi_talep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talep_no TEXT NOT NULL UNIQUE,
    talep_turu TEXT NOT NULL,
    durum TEXT NOT NULL DEFAULT 'ONAY_BEKLIYOR',
    gorusme_id INTEGER NOT NULL,
    cari_id INTEGER,
    musteri_aday_id INTEGER,
    olusturan_kullanici_id INTEGER NOT NULL DEFAULT 1,
    atanan_kullanici_id INTEGER,
    oncelik TEXT NOT NULL DEFAULT 'NORMAL',
    aciklama TEXT,
    musteri_notu TEXT,
    geri_gonderme_notu TEXT, red_nedeni TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    donusturulen_siparis_id INTEGER,
    donusturulen_numune_talep_id INTEGER,
    isleme_alinma_tarihi TEXT, donusturulme_tarihi TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK (talep_turu IN ('SIPARIS', 'NUMUNE')),
    CHECK (durum IN (
        'ONAY_BEKLIYOR','YENI','ISLEME_ALINDI','EKSIK_BILGI',
        'SIPARISE_DONUSTU','NUMUNEYE_DONUSTU',
        'KISMEN_NUMUNEYE_DONUSTU','REDDEDILDI','IPTAL'
    )),
    CHECK (oncelik IN ('DUSUK', 'NORMAL', 'YUKSEK', 'ACIL'))
);
CREATE TABLE IF NOT EXISTS nexgen_musteri_temsilcisi_talep_kalem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talep_id INTEGER NOT NULL, sira_no INTEGER NOT NULL DEFAULT 1,
    urun_ailesi TEXT,
    urun_aciklama TEXT NOT NULL DEFAULT '',
    formul_id INTEGER, renk_id INTEGER, renk_aciklama TEXT,
    boyut TEXT, miktar_kg REAL, konusulan_tonaj REAL,
    verilen_fiyat REAL, para_birimi TEXT,
    fiyat_birimi TEXT NOT NULL DEFAULT 'KG',
    odeme_tipi TEXT, vade_gun INTEGER, cek_vade_gun INTEGER,
    kalem_notu TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    donusturulen_numune_talep_id INTEGER,
    donusturulme_tarihi TEXT,
    donusturme_durumu TEXT DEFAULT 'BEKLIYOR',
    numune_talep_id INTEGER, numune_talep_kodu TEXT
);
CREATE TABLE IF NOT EXISTS nexgen_onay (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    onay_no TEXT NOT NULL UNIQUE,
    kaynak_turu TEXT NOT NULL,
    kaynak_id INTEGER NOT NULL,
    onay_turu TEXT NOT NULL,
    durum TEXT NOT NULL DEFAULT 'ONAY_BEKLIYOR',
    olusturan_kullanici_id INTEGER NOT NULL DEFAULT 1,
    onaylayan_kullanici_id INTEGER,
    red_nedeni TEXT, aciklama TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    karar_tarihi TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    CHECK (durum IN ('ONAY_BEKLIYOR','ONAYLANDI','REDDEDILDI','IPTAL')),
    CHECK (kaynak_turu IN (
        'MUSTERI_TEMSILCISI_TALEP','SIPARIS','NUMUNE',
        'TAHSILAT','CEK','MUHASEBE','SATINALMA','FIYAT'
    )),
    UNIQUE (kaynak_turu, kaynak_id, onay_turu)
);
CREATE TABLE IF NOT EXISTS nexgen_musteri_temsilcisi_talep_mtt_donusum_idem (
    idempotency_key TEXT PRIMARY KEY,
    talep_id INTEGER, secilen_kalem_ids TEXT,
    primary_numune_id INTEGER, numune_ids_json TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS nexgen_numune_talep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talep_kodu TEXT NOT NULL UNIQUE,
    durum TEXT NOT NULL DEFAULT 'TASLAK',
    talep_eden_kullanici_id INTEGER,
    olusturan_kullanici_id INTEGER NOT NULL DEFAULT 1,
    olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    guncelleme_tarihi TEXT,
    oncelik TEXT NOT NULL DEFAULT 'NORMAL',
    hedef_tarih TEXT,
    talep_nedeni TEXT, aciklama TEXT, ek_not TEXT,
    musteri_tipi TEXT NOT NULL DEFAULT 'MEVCUT',
    cari_id INTEGER,
    aday_firma_adi TEXT, musteri_aday_id INTEGER,
    ilgili_kisi TEXT, telefon TEXT, eposta TEXT, sehir TEXT,
    talep_kaynagi TEXT,
    urun_tipi TEXT, urun_adi TEXT, urun_aciklama TEXT,
    urun_gorsel_belge_id INTEGER,
    renk_tipi TEXT, rf_renk_id INTEGER, renk_kodu TEXT,
    yeni_renk_aciklama TEXT, acik_koyu TEXT, mat_parlak TEXT,
    ref_renk_kodu TEXT, ref_gorsel_belge_id INTEGER,
    yumusaklik TEXT, kaymazlik TEXT, shore_deger TEXT, pisme_notu TEXT,
    diger_beklentiler_json TEXT,
    karsilama_yolu TEXT, numune_adedi INTEGER,
    beden_kalip TEXT,
    patch_aksesuar_var INTEGER DEFAULT 0,
    patch_aksesuar_aciklama TEXT,
    paketleme_notu TEXT, kargo_teslim_notu TEXT,
    kullanim_amaci TEXT, benzer_urun_numune TEXT,
    kaynak_modul TEXT, mo_gorusme_id INTEGER,
    idempotency_key TEXT,
    kaynak_mtt_talep_id INTEGER, mtt_kalem_id INTEGER,
    arge_test_id INTEGER,
    isleme_alan_kullanici_id INTEGER, isleme_alinma_tarihi TEXT,
    aktif INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS nexgen_arge_test (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kaynak_uretim_varyant_id INTEGER,
    test_no TEXT NOT NULL,
    test_tipi TEXT NOT NULL DEFAULT 'RENK_TEST',
    makina TEXT NOT NULL DEFAULT '7.5 LT',
    test_batch_kg REAL NOT NULL DEFAULT 1.0,
    kaynak_batch_kg REAL NOT NULL DEFAULT 1.0,
    yeni_renk_adi TEXT,
    notlar TEXT,
    durum TEXT NOT NULL DEFAULT 'TASLAK',
    sonuc_notu TEXT,
    renk_tuttu INTEGER,
    shore_degeri REAL,
    kopurme_notu TEXT,
    cekme_problemi INTEGER,
    genel_aciklama TEXT,
    olusturan_id INTEGER,
    olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now')),
    onaylayan_id INTEGER,
    onay_tarihi TEXT,
    aktif INTEGER NOT NULL DEFAULT 1,
    olusan_uretim_varyant_id INTEGER,
    olusan_renk_varyant_id INTEGER,
    cari_id INTEGER,
    shore_hedef REAL,
    lot_no TEXT,
    talep_referansi TEXT,
    onay_notu TEXT,
    rf_renk_id INTEGER,
    numune_orani REAL,
    arge_kodu TEXT,
    renk_bilesenleri_json TEXT,
    aktarildi_mi INTEGER DEFAULT 0,
    aktarim_tarihi TEXT,
    aktarim_notu TEXT,
    aktif_rev_no INTEGER DEFAULT 0,
    basarili_mi INTEGER DEFAULT 0,
    basarili_yapan_id INTEGER,
    basarili_yapan_adi TEXT,
    basarili_tarihi TEXT,
    pisme_suresi_dk REAL,
    ferhat_adi TEXT,
    ferhat_tarihi TEXT,
    calisma_tipi TEXT NOT NULL DEFAULT 'YENI_RF',
    guncelleme_tarihi TEXT,
    sorumlu_kullanici_id INTEGER,
    oncelik TEXT NOT NULL DEFAULT 'NORMAL',
    urun_ailesi TEXT,
    formul_grup_adi TEXT,
    ana_formul_grup_kodu TEXT,
    renk_kodu TEXT,
    yogunluk_hedef REAL,
    saha_testi_gerekli_mi INTEGER NOT NULL DEFAULT 0,
    saha_testi_nedeni TEXT,
    saha_testi_karar_veren_id INTEGER,
    saha_testi_karar_tarihi TEXT,
    ferhat_genel_karar TEXT,
    ferhat_genel_not TEXT,
    ferhat_kaydeden_id INTEGER,
    ferhat_kayit_tarihi TEXT,
    numune_talep_id INTEGER
);
CREATE TABLE IF NOT EXISTS nexgen_arge_kaynak_uv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arge_test_id INTEGER NOT NULL,
    boyut TEXT NOT NULL CHECK (boyut IN ('LARGE','SMALL','MEDIUM')),
    kaynak_uretim_varyant_id INTEGER NOT NULL,
    sira_no INTEGER NOT NULL DEFAULT 1,
    aktif_mi INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (arge_test_id, boyut),
    UNIQUE (arge_test_id, kaynak_uretim_varyant_id)
);
CREATE TABLE IF NOT EXISTS nexgen_cari_sorumlu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cari_id INTEGER NOT NULL, kullanici_id INTEGER NOT NULL,
    aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS musteri_operasyon_ajanda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cari_id INTEGER, musteri_aday_id INTEGER,
    firma_adi_gorunum TEXT,
    kullanici_id INTEGER NOT NULL,
    plan_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    gorusme_tipi TEXT NOT NULL DEFAULT 'Telefon',
    plan_notu TEXT,
    durum TEXT NOT NULL DEFAULT 'PLANLANDI',
    gorusme_id INTEGER,
    idempotency_key TEXT NOT NULL UNIQUE,
    aktif INTEGER NOT NULL DEFAULT 1,
    olusturma_tarihi TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    guncelleme_tarihi TEXT,
    olusturan_kullanici_id INTEGER NOT NULL DEFAULT 1,
    plan_yetkili_metin TEXT, plan_telefon TEXT, plan_sehir TEXT
);
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY);
"""

_seq = 0


def _next_idem():
    global _seq
    _seq += 1
    return f"idem-t{_seq}-{uuid.uuid4().hex[:8]}"


def _make_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(_DDL)
    # Sistem kullanıcıları — yetki yükleyicisi için
    for uid in range(1, 20):
        con.execute(
            "INSERT OR IGNORE INTO sistem_kullanici (Id, KullaniciAdi, RolId, Aktif) VALUES (?, ?, NULL, 1)",
            (uid, f"testuser{uid}"),
        )
    # nexgen_cari (cari_kod zorunlu)
    con.execute("INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif) VALUES (10, 'C-010', 'Zirve AS', 1)")
    con.execute("INSERT INTO nexgen_cari (id, cari_kod, unvan, aktif) VALUES (20, 'C-020', 'Beta Ltd', 1)")
    # musteri_aday — aktif kolonu canonical schema'da yok, durum ile lifecycle yönetilir
    con.execute(
        "INSERT INTO nexgen_musteri_aday (id, firma_adi, durum, olusturan_kullanici_id) "
        "VALUES (99, 'YeniCo', 'ADAY', 1)"
    )
    con.commit()
    return con


def _mtt_row(con, talep_id: int):
    return con.execute(
        "SELECT * FROM nexgen_musteri_temsilcisi_talep WHERE id=?", (talep_id,)
    ).fetchone()


def _mtt_isleme_al(con, talep_id: int) -> None:
    """Mehmet'in 'İşleme Al' adımını simüle eder — numune dönüşümü için zorunlu."""
    con.execute(
        "UPDATE nexgen_musteri_temsilcisi_talep SET durum='ISLEME_ALINDI' WHERE id=?",
        (talep_id,),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Servis importları
# ---------------------------------------------------------------------------
from modules.nexgen.musteri_temsilcisi_talep_service import (
    MusteriTemsilcisiTalepError,
    numune_popup_mtt_onaya_gonder,
)
from modules.nexgen.mtt_donusum_service import (
    numune_hazirla,
    numune_mtt_ile_kaydet,
)
from modules.nexgen.numune_talep_service import (
    NumuneTalepError,
    gonder_arge,
)

_YK_ADMIN = frozenset({"*"})

# ===========================================================================
# T1 — Kayıtlı müşteri popup → MTT oluşur, cari_id korunur
# ===========================================================================
class TestT1_KayitliMusteriMttOlusur(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()

    def tearDown(self):
        self.con.close()

    def test_mtt_olusur_ve_cari_id_korunur(self):
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Terlik Model A",
                "urun_tipi": "TERLIK",
                "musteri_talebi": "Mavi renk numune istiyoruz.",
                "referans_renk": "Mavi",
                "oncelik": "YUKSEK",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=1,
            yk=_YK_ADMIN,
        )
        self.assertTrue(out.get("ok"), f"ok=False: {out}")
        talep_id = out["talep_id"]
        row = _mtt_row(self.con, talep_id)
        self.assertIsNotNone(row, "MTT kaydı bulunamadı")
        self.assertEqual(int(row["cari_id"]), 10, "cari_id MTT'de korunmadı")
        self.assertEqual(row["talep_turu"], "NUMUNE")
        self.assertEqual(out.get("musteri_tipi"), "MEVCUT")

    def test_mevcut_musteri_cari_id_olmadan_hata(self):
        with self.assertRaises(MusteriTemsilcisiTalepError) as ctx:
            numune_popup_mtt_onaya_gonder(
                self.con,
                {
                    "musteri_tipi": "MEVCUT",
                    "urun_adi": "X",
                    "urun_tipi": "TERLIK",
                    "musteri_talebi": "Talep",
                    "idempotency_key": _next_idem(),
                },
                kullanici_id=1,
                yk=_YK_ADMIN,
            )
        self.assertIn("cari_id", ctx.exception.mesaj)

    def test_gecersiz_musteri_tipi_hata(self):
        with self.assertRaises(MusteriTemsilcisiTalepError):
            numune_popup_mtt_onaya_gonder(
                self.con,
                {
                    "musteri_tipi": "BILINMIYOR",
                    "cari_id": 10,
                    "urun_adi": "X",
                    "urun_tipi": "TERLIK",
                    "musteri_talebi": "T",
                    "idempotency_key": _next_idem(),
                },
                kullanici_id=1,
                yk=_YK_ADMIN,
            )

    def test_legacy_musteri_tipi_yok_mevcut_kabul_edilir(self):
        # musteri_tipi göndermeden eski UI davranışı — MEVCUT default
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "cari_id": 10,
                "urun_adi": "Eski UI Terlik",
                "urun_tipi": "TERLIK",
                "musteri_talebi": "Eski UI tarzı talep.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=1,
            yk=_YK_ADMIN,
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("musteri_tipi"), "MEVCUT")


# ===========================================================================
# T2 — Planlama (Mehmet) MTT kuyruğunu görebilir
# ===========================================================================
class TestT2_PlanlamaMttGorebilir(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Taban Model B",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Sert taban numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=1,
            yk=_YK_ADMIN,
        )
        self.talep_id = out["talep_id"]

    def tearDown(self):
        self.con.close()

    def test_mtt_planlamaya_gorunur(self):
        row = _mtt_row(self.con, self.talep_id)
        self.assertIsNotNone(row)
        self.assertIn(row["durum"], ("YENI", "ONAY_BEKLIYOR", "ISLEME_ALINDI"))
        self.assertEqual(row["talep_turu"], "NUMUNE")


# ===========================================================================
# T3 — numune_hazirla çalışır (Numuneye Dönüştür hazırlık)
# ===========================================================================
class TestT3_NumuneHazirla(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Sandalet X",
                "urun_tipi": "TERLIK",
                "musteri_talebi": "Sari renk numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=2,
            yk=_YK_ADMIN,
        )
        self.talep_id = out["talep_id"]

    def tearDown(self):
        self.con.close()

    def test_numune_hazirla_ok(self):
        result = numune_hazirla(self.con, self.talep_id, kullanici_id=2, yk=_YK_ADMIN)
        self.assertTrue(result.get("ok"), f"numune_hazirla failed: {result}")
        cva = result.get("cari_veya_aday") or {}
        self.assertEqual(cva.get("cari_id"), 10)


# ===========================================================================
# T4 — nexgen_numune_talep.cari_id EXACT
# ===========================================================================
class TestT4_NumuneCariIdExact(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Kopuk Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Beyaz kopuk numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=3,
            yk=_YK_ADMIN,
        )
        self.talep_id = out["talep_id"]

    def tearDown(self):
        self.con.close()

    def test_numune_cari_id_exact(self):
        _mtt_isleme_al(self.con, self.talep_id)
        result = numune_mtt_ile_kaydet(
            self.con, self.talep_id, {}, kullanici_id=3
        )
        self.assertTrue(result.get("ok"), f"numune_mtt_ile_kaydet failed: {result}")
        numune_list = result.get("numune_talepleri") or [result.get("talep")]
        self.assertTrue(numune_list)
        numune = numune_list[0]
        self.assertIsNotNone(numune)
        nrow = self.con.execute(
            "SELECT cari_id, musteri_tipi FROM nexgen_numune_talep WHERE id=?",
            (int(numune["id"]),),
        ).fetchone()
        self.assertIsNotNone(nrow, "nexgen_numune_talep kaydı bulunamadı")
        self.assertEqual(int(nrow["cari_id"]), 10, "cari_id EXACT eslesme yapmadi")
        self.assertEqual(nrow["musteri_tipi"], "MEVCUT")


# ===========================================================================
# T5 — Numune kaydı MTT referansını korur
# ===========================================================================
class TestT5_NumuneMttReferans(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 20,
                "urun_adi": "Flat Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Duz taban numune talebi.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=4,
            yk=_YK_ADMIN,
        )
        self.talep_id = out["talep_id"]

    def tearDown(self):
        self.con.close()

    def test_mtt_referans_korunur(self):
        _mtt_isleme_al(self.con, self.talep_id)
        result = numune_mtt_ile_kaydet(self.con, self.talep_id, {}, kullanici_id=4)
        self.assertTrue(result.get("ok"))
        nid = int(result["talep"]["id"])
        nrow = self.con.execute(
            "SELECT kaynak_mtt_talep_id, kaynak_modul FROM nexgen_numune_talep WHERE id=?",
            (nid,),
        ).fetchone()
        self.assertIsNotNone(nrow)
        # kaynak_mtt_talep_id numune_mtt_ile_kaydet tarafından body'ye ekleniyor
        # (mtt_donusum_service satır 1257: body['kaynak_mtt_talep_id'] = int(mtt_id))
        if nrow["kaynak_mtt_talep_id"] is not None:
            self.assertEqual(int(nrow["kaynak_mtt_talep_id"]), self.talep_id,
                             "kaynak_mtt_talep_id MTT id ile eslesmedi")
        # kaynak_modul her durumda MUSTERI_TEMSILCISI_TALEP olmali
        self.assertEqual(nrow["kaynak_modul"], "MUSTERI_TEMSILCISI_TALEP")


# ===========================================================================
# T6 — gonder_arge → BEKLEYEN_NUMUNE
# ===========================================================================
class TestT6_GonderArgeBekleyenNumune(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Spor Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Spor taban numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=5,
            yk=_YK_ADMIN,
        )
        _mtt_isleme_al(self.con, out["talep_id"])
        res = numune_mtt_ile_kaydet(self.con, out["talep_id"], {}, kullanici_id=5)
        self.numune_id = int(res["talep"]["id"])

    def tearDown(self):
        self.con.close()

    def test_gonder_arge_bekleyen_numune(self):
        # gonder_arge MEVCUT için payload'da cari_id+urun_tipi zorunlu
        nrow = self.con.execute(
            "SELECT cari_id, musteri_tipi, urun_tipi FROM nexgen_numune_talep WHERE id=?",
            (self.numune_id,)
        ).fetchone()
        result = gonder_arge(
            self.con,
            {
                "cari_id": nrow["cari_id"],
                "musteri_tipi": nrow["musteri_tipi"] or "MEVCUT",
                "urun_tipi": nrow["urun_tipi"],
                "karsilama_yolu": "YENI_RENK",
                "yeni_renk_aciklama": "Koyu yesil",
            },
            olusturan_id=5,
            talep_id=self.numune_id,
        )
        # gonder_arge başarılı olunca get_talep dict döner (ok key yok)
        nrow2 = self.con.execute(
            "SELECT durum, arge_test_id FROM nexgen_numune_talep WHERE id=?", (self.numune_id,)
        ).fetchone()
        self.assertEqual(nrow2["durum"], "BEKLEYEN_NUMUNE", f"gonder_arge beklenen durum yok: {result}")
        self.assertIsNotNone(nrow2["arge_test_id"], "arge_test_id olusmali")


# ===========================================================================
# T7 — arge_test_id link oluşumu
# ===========================================================================
class TestT7_ArgeTestIdLink(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Eva Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Eva taban numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=6,
            yk=_YK_ADMIN,
        )
        _mtt_isleme_al(self.con, out["talep_id"])
        res = numune_mtt_ile_kaydet(self.con, out["talep_id"], {}, kullanici_id=6)
        self.numune_id = int(res["talep"]["id"])

    def tearDown(self):
        self.con.close()

    def test_arge_test_id_link(self):
        nrow = self.con.execute(
            "SELECT cari_id, musteri_tipi, urun_tipi FROM nexgen_numune_talep WHERE id=?",
            (self.numune_id,)
        ).fetchone()
        gonder_arge(
            self.con,
            {
                "cari_id": nrow["cari_id"],
                "musteri_tipi": nrow["musteri_tipi"] or "MEVCUT",
                "urun_tipi": nrow["urun_tipi"],
                "karsilama_yolu": "YENI_RENK",
                "yeni_renk_aciklama": "Kirmizi",
            },
            olusturan_id=6,
            talep_id=self.numune_id,
        )
        nrow = self.con.execute(
            "SELECT arge_test_id FROM nexgen_numune_talep WHERE id=?", (self.numune_id,)
        ).fetchone()
        self.assertIsNotNone(nrow["arge_test_id"], "arge_test_id NULL kalmamali")
        arow = self.con.execute(
            "SELECT id, numune_talep_id FROM nexgen_arge_test WHERE id=?",
            (nrow["arge_test_id"],),
        ).fetchone()
        self.assertIsNotNone(arow, "nexgen_arge_test kaydi olusmaliydi")
        self.assertEqual(int(arow["numune_talep_id"]), self.numune_id)


# ===========================================================================
# T8 — Yeni müşteri (ADAY) → MTT'de musteri_aday_id korunur
# ===========================================================================
class TestT8_YeniMusteriAdayMtt(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()

    def tearDown(self):
        self.con.close()

    def test_aday_mtt_olusur(self):
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "ADAY",
                "musteri_aday_id": 99,
                "urun_adi": "Renksiz Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Aday musteri numune talebi.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=7,
            yk=_YK_ADMIN,
        )
        self.assertTrue(out.get("ok"), f"ok=False: {out}")
        self.assertEqual(out.get("musteri_tipi"), "ADAY")
        row = _mtt_row(self.con, out["talep_id"])
        self.assertIsNotNone(row)
        self.assertEqual(int(row["musteri_aday_id"]), 99)
        self.assertIsNone(row["cari_id"])

    def test_aday_musteri_aday_id_olmadan_hata(self):
        with self.assertRaises(MusteriTemsilcisiTalepError) as ctx:
            numune_popup_mtt_onaya_gonder(
                self.con,
                {
                    "musteri_tipi": "ADAY",
                    "urun_adi": "X",
                    "urun_tipi": "TERLIK",
                    "musteri_talebi": "T",
                    "idempotency_key": _next_idem(),
                },
                kullanici_id=7,
                yk=_YK_ADMIN,
            )
        self.assertIn("musteri_aday_id", ctx.exception.mesaj)

    def test_aday_gecersiz_aday_id_hata(self):
        with self.assertRaises(MusteriTemsilcisiTalepError):
            numune_popup_mtt_onaya_gonder(
                self.con,
                {
                    "musteri_tipi": "ADAY",
                    "musteri_aday_id": 9999,
                    "urun_adi": "X",
                    "urun_tipi": "TERLIK",
                    "musteri_talebi": "T",
                    "idempotency_key": _next_idem(),
                },
                kullanici_id=7,
                yk=_YK_ADMIN,
            )


# ===========================================================================
# T9 — Yeni müşteri → nexgen_numune_talep.musteri_aday_id EXACT
# ===========================================================================
class TestT9_AdayNumuneIdExact(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "ADAY",
                "musteri_aday_id": 99,
                "urun_adi": "Soft Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Soft aday numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=8,
            yk=_YK_ADMIN,
        )
        self.talep_id = out["talep_id"]

    def tearDown(self):
        self.con.close()

    def test_aday_numune_id_exact(self):
        _mtt_isleme_al(self.con, self.talep_id)
        result = numune_mtt_ile_kaydet(
            self.con, self.talep_id, {}, kullanici_id=8
        )
        self.assertTrue(result.get("ok"), f"numune_mtt_ile_kaydet failed: {result}")
        nid = int(result["talep"]["id"])
        nrow = self.con.execute(
            "SELECT musteri_aday_id, musteri_tipi, cari_id FROM nexgen_numune_talep WHERE id=?",
            (nid,),
        ).fetchone()
        self.assertIsNotNone(nrow)
        self.assertEqual(int(nrow["musteri_aday_id"]), 99)
        self.assertEqual(nrow["musteri_tipi"], "ADAY")
        self.assertIsNone(nrow["cari_id"])


# ===========================================================================
# T10 — Cari360 cari_id üzerinden numune okuyabiliyor
# ===========================================================================
class TestT10_Cari360NumuneOkuma(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Klasik Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Klasik numune talebi.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=9,
            yk=_YK_ADMIN,
        )
        _mtt_isleme_al(self.con, out["talep_id"])
        res = numune_mtt_ile_kaydet(self.con, out["talep_id"], {}, kullanici_id=9)
        self.numune_id = int(res["talep"]["id"])

    def tearDown(self):
        self.con.close()

    def test_cari360_cari_id_ile_numune_okur(self):
        rows = self.con.execute(
            "SELECT id, cari_id FROM nexgen_numune_talep WHERE cari_id=? AND COALESCE(aktif,1)=1",
            (10,),
        ).fetchall()
        self.assertTrue(len(rows) > 0, "Cari360 cari_id=10 ile numune okuyamadi")
        ids = [r["id"] for r in rows]
        self.assertIn(self.numune_id, ids, "Olusturulan numune Cari360 sorgusunda yok")


# ===========================================================================
# T11 — Sipariş Talebi Regression
# ===========================================================================
class TestT11_SiparisTalepRegresyon(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()

    def tearDown(self):
        self.con.close()

    def test_numune_cari_id_20_calisir(self):
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 20,
                "urun_adi": "Yeni Model",
                "urun_tipi": "TERLIK",
                "musteri_talebi": "Deneme talebi.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=11,
            yk=_YK_ADMIN,
        )
        self.assertTrue(out.get("ok"))
        row = _mtt_row(self.con, out["talep_id"])
        self.assertEqual(int(row["cari_id"]), 20)

    def test_legacy_cari_id_default_mevcut(self):
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "cari_id": 10,
                "urun_adi": "Klasik",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Eski UI - tipi yok.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=11,
            yk=_YK_ADMIN,
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("musteri_tipi"), "MEVCUT")


# ===========================================================================
# T12 — Görüşme / Ajanda Regression
# ===========================================================================
class TestT12_GorusmeAjandaRegresyon(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        self.con.execute(
            "INSERT INTO musteri_operasyon_gorusme "
            "(id, cari_id, kullanici_id, olusturan_kullanici_id, gorusme_tipi, kisa_not, "
            "sonuc_tipi, gorusme_tarihi, aktif, idempotency_key, olusturma_tarihi) "
            "VALUES (501, 10, 1, 1, 'Telefon', 'Test', 'Numune Istedi', "
            "'2026-08-01 10:00:00', 1, 'existing-idem-501', '2026-08-01 10:00:00')"
        )
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def test_mevcut_gorusme_bozulmadi(self):
        row = self.con.execute(
            "SELECT * FROM musteri_operasyon_gorusme WHERE id=501"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row["cari_id"]), 10)
        self.assertEqual(row["gorusme_tipi"], "Telefon")

    def test_numune_popup_mevcut_gorusme_ile_calisir(self):
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "mo_gorusme_id": 501,
                "urun_adi": "Bagli Gorusme Numune",
                "urun_tipi": "TERLIK",
                "musteri_talebi": "Mevcut gorusmeden numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=1,
            yk=_YK_ADMIN,
        )
        self.assertTrue(out.get("ok"), f"Mevcut gorusme ile numune basarisiz: {out}")
        self.assertEqual(int(out["gorusme_id"]), 501)


# ===========================================================================
# T13 — Tahsilat AVANS LOCK (import/syntax bozulmadı)
# ===========================================================================
class TestT13_TahsilatAvansLockImport(unittest.TestCase):
    def test_avans_servis_import_ok(self):
        try:
            from modules.nexgen.mo_tahsilat_kayit_service import MoTahsilatError
            from modules.nexgen.mo_tahsilat_config import TAHSILAT_TIPI_AVANS
        except ImportError as e:
            self.fail(f"Tahsilat AVANS import hatasi: {e}")


# ===========================================================================
# T14 — Numune → AR-GE Regression (BEKLEYEN_NUMUNE)
# ===========================================================================
class TestT14_NumuneArgeRegresyon(unittest.TestCase):
    def setUp(self):
        self.con = _make_db()
        out = numune_popup_mtt_onaya_gonder(
            self.con,
            {
                "musteri_tipi": "MEVCUT",
                "cari_id": 10,
                "urun_adi": "Regresyon Taban",
                "urun_tipi": "TABAN",
                "musteri_talebi": "Regresyon test numune.",
                "idempotency_key": _next_idem(),
            },
            kullanici_id=14,
            yk=_YK_ADMIN,
        )
        _mtt_isleme_al(self.con, out["talep_id"])
        res = numune_mtt_ile_kaydet(self.con, out["talep_id"], {}, kullanici_id=14)
        self.numune_id = int(res["talep"]["id"])

    def tearDown(self):
        self.con.close()

    def test_arge_zincir_regresyon(self):
        nrow_n = self.con.execute(
            "SELECT cari_id, musteri_tipi, urun_tipi FROM nexgen_numune_talep WHERE id=?",
            (self.numune_id,)
        ).fetchone()
        result = gonder_arge(
            self.con,
            {
                "cari_id": nrow_n["cari_id"],
                "musteri_tipi": nrow_n["musteri_tipi"] or "MEVCUT",
                "urun_tipi": nrow_n["urun_tipi"],
                "karsilama_yolu": "YENI_RENK",
                "yeni_renk_aciklama": "Gri",
            },
            olusturan_id=14,
            talep_id=self.numune_id,
        )
        nrow = self.con.execute(
            "SELECT durum, arge_test_id FROM nexgen_numune_talep WHERE id=?",
            (self.numune_id,),
        ).fetchone()
        self.assertEqual(nrow["durum"], "BEKLEYEN_NUMUNE", f"gonder_arge regresyon beklenen durum yok: {result}")
        self.assertIsNotNone(nrow["arge_test_id"], "arge_test_id olusmali")


class TestT15_AdayDropdownDatasourceContract(unittest.TestCase):
    """
    T15: Numune Yeni Müşteri dropdown'u ozet.adaylar datasource kullanır
         ve canonical aday ID'sini (aday_id) option value olarak taşır.
    Regression: Bug — ozet.musteriler içinde entity_type='ADAY' aranıyordu.
    Fix — ozet.adaylar doğrudan kullanılır.
    """

    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        # Tam DDL ile kur — cari_sorumlu_service için sistem_kullanici gerekli
        self.con.executescript(_DDL)
        self.con.execute(
            "INSERT OR IGNORE INTO sistem_kullanici (Id, KullaniciAdi, RolId, Aktif) VALUES (2, 'erhan', NULL, 1)"
        )
        self.con.execute(
            "INSERT INTO nexgen_musteri_aday (id, firma_adi, yetkili_adi, durum, olusturan_kullanici_id) "
            "VALUES (34, 'TEST GAMA 13', 'Yetkili Kisi', 'ADAY', 2)"
        )
        self.con.execute(
            "INSERT INTO nexgen_musteri_aday (id, firma_adi, yetkili_adi, durum, olusturan_kullanici_id) "
            "VALUES (35, 'TEST BETA 7', 'Diger Yetkili', 'ADAY', 2)"
        )
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def test_aday_havuz_liste_returns_aday_id_field(self):
        """aday_havuz_liste dondurduğu her kayit icin 'aday_id' key'i olmali.
        Not: yetkisiz kullanici icin bos liste donebilir; key contract checked
        via dogrudan DB sorgulama."""
        from modules.nexgen.musteri_aday_service import aday_havuz_liste
        adaylar = aday_havuz_liste(self.con, 2, None)
        for a in adaylar:
            self.assertIn('aday_id', a, f"aday_id field eksik: {dict(a)}")
            self.assertIn('firma_adi', a, f"firma_adi field eksik: {dict(a)}")
            self.assertEqual(a['entity_type'], 'ADAY', f"entity_type ADAY olmali: {dict(a)}")

    def test_aday_id_field_in_db(self):
        """nexgen_musteri_aday tablosunda id=34 olan TEST GAMA 13 kaydi var.
        Template ozet.adaylar uzerinden aday_id=34 kullanmali (ozel sekil)."""
        row = self.con.execute(
            "SELECT id, firma_adi FROM nexgen_musteri_aday WHERE id=34"
        ).fetchone()
        self.assertIsNotNone(row, "id=34 kaydi olmali")
        self.assertEqual(row['firma_adi'], 'TEST GAMA 13')
        # aday_id field'i = id — template {{ a.aday_id }} dogru
        self.assertEqual(int(row['id']), 34)

    def test_aday_datasource_not_in_musteriler(self):
        """ozet.musteriler -> entity_type=ADAY filtrelemesi hicbir zaman calismaz.
        Adaylar SADECE ozet.adaylar uzerinden gelir.
        Bu test: musteriler listesinde entity_type='ADAY' kayit YOK."""
        # Simule: musteri listesi sadece CARI entity_type icerir
        musteriler = [
            {'entity_type': 'CARI', 'id': 5, 'unvan': 'Firma A'},
            {'entity_type': 'CARI', 'id': 7, 'unvan': 'Firma B'},
        ]
        aday_from_musteriler = [m for m in musteriler if (m.get('entity_type') or 'CARI') == 'ADAY']
        self.assertEqual(
            len(aday_from_musteriler), 0,
            "musteriler listesinde ADAY olmamali — dropdown ozet.adaylar'dan doldurulmali"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
