# -*- coding: utf-8 -*-
"""
FAZ-DEPLOY-MIGRATION-KALICI-DUZELTME-1
Tek kaynak NexGen migration manifesti (095+).

Version 100 çakışması çözümü:
  - 100 = nexgen_formul.urun_ailesi (100_nexgen_formul_urun_ailesi.py)
  - 110 = import log tabloları (eski dosya 100_nexgen_import_log.py → 110_*)
  Eski DB'de version=100 kaydı varken:
    - urun_ailesi kolonu varsa → 100 uygulanmış sayılır
    - nexgen_import_batch varsa ve 110 kaydı yoksa → 110 reconcile adayı
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class MigEntry:
    version: int
    module: str          # app.migrations.<stem> — stem without .py
    filename: str
    description: str
    dependencies: tuple[int, ...] = ()
    required_tables: tuple[str, ...] = ()
    required_columns: tuple[tuple[str, str], ...] = ()  # (table, column)
    risk: str = "normal"  # normal | high | permission
    legacy_aliases: tuple[int, ...] = ()  # eski yanlış version kayıtları


# Sıra = apply sırası (dependency topolojisi ile uyumlu)
MANIFEST: tuple[MigEntry, ...] = (
    MigEntry(
        95, "095_nexgen_rf_kalem_sema_uyum", "095_nexgen_rf_kalem_sema_uyum.py",
        "nexgen_rf_kalem.pigment_ad",
        required_columns=(("nexgen_rf_kalem", "pigment_ad"),),
    ),
    MigEntry(
        96, "096_nexgen_fiyat_gecerlilik_idx", "096_nexgen_fiyat_gecerlilik_idx.py",
        "fiyat gecerlilik index",
    ),
    MigEntry(
        97, "097_nexgen_fiyat_batch_hash", "097_nexgen_fiyat_batch_hash.py",
        "nexgen_fiyat_batch hash kolonlari",
        required_columns=(("nexgen_fiyat_batch", "dosya_hash"),),
    ),
    MigEntry(
        98, "098_nexgen_rf_revizyon", "098_nexgen_rf_revizyon.py",
        "RF revizyon + aktif_rev_no",
        required_columns=(("nexgen_rf_renk", "aktif_rev_no"),),
    ),
    MigEntry(
        99, "099_nexgen_planlama_uygunluk", "099_nexgen_planlama_uygunluk.py",
        "planlama uygunluk / uretim tipi",
        required_tables=("nexgen_planlama_uygunluk", "nexgen_uretim_tipi"),
    ),
    MigEntry(
        100, "100_nexgen_formul_urun_ailesi", "100_nexgen_formul_urun_ailesi.py",
        "nexgen_formul.urun_ailesi",
        required_columns=(("nexgen_formul", "urun_ailesi"),),
    ),
    MigEntry(
        101, "101_nexgen_planlama_identity", "101_nexgen_planlama_identity.py",
        "planlama identity kolonlari",
        dependencies=(99,),
        required_tables=("nexgen_planlama_uygunluk",),
        required_columns=(("nexgen_planlama_uygunluk", "musteri_renk_kodu"),),
    ),
    MigEntry(
        102, "102_nexgen_uv_rev_no", "102_nexgen_uv_rev_no.py",
        "uretim_varyant.rev_no rebuild",
        required_columns=(("nexgen_uretim_varyant", "rev_no"),),
        risk="high",
    ),
    MigEntry(
        103, "103_nexgen_renk_merkezi_ferhat_alanlari",
        "103_nexgen_renk_merkezi_ferhat_alanlari.py",
        "arge_test ferhat alanlari",
        required_columns=(("nexgen_arge_test", "ferhat_adi"),),
    ),
    MigEntry(
        104, "104_nexgen_uretim_kodu", "104_nexgen_uretim_kodu.py",
        "uretim_kodu alanlari",
        required_columns=(("nexgen_uretim_plan", "uretim_kodu"),),
    ),
    MigEntry(
        105, "105_nexgen_siparis_kontrol_view_repair",
        "105_nexgen_siparis_kontrol_view_repair.py",
        "v_nexgen_siparis_uretim_kontrol view",
    ),
    MigEntry(
        106, "106_nexgen_arge_nx_ar_model", "106_nexgen_arge_nx_ar_model.py",
        "NX-AR model + arge_test kolonlari",
        required_tables=("nexgen_arge_boyut_sonuc", "nexgen_arge_kaynak_uv"),
        required_columns=(("nexgen_arge_test", "calisma_tipi"),),
    ),
    MigEntry(
        107, "107_nexgen_planlama_siparis_kalem",
        "107_nexgen_planlama_siparis_kalem.py",
        "pazarlama cok kalem tablosu",
        required_tables=("nexgen_planlama_siparis_kalem",),
    ),
    MigEntry(
        108, "108_ferhat_enjeksiyon_tablet_view",
        "108_ferhat_enjeksiyon_tablet_view.py",
        "Ferhat nexgen.tablet.view yetkisi",
        risk="permission",
    ),
    MigEntry(
        109, "109_nx_ar_onay_enjeksiyon_alanlari",
        "109_nx_ar_onay_enjeksiyon_alanlari.py",
        "NX-AR boyut sonuc alanlari",
        dependencies=(106,),
        required_tables=("nexgen_arge_boyut_sonuc",),
        required_columns=(("nexgen_arge_boyut_sonuc", "enjeksiyon_saniye"),),
    ),
    MigEntry(
        110, "110_nexgen_import_log", "110_nexgen_import_log.py",
        "import batch/item log (eski cakisan 100)",
        required_tables=("nexgen_import_batch", "nexgen_import_item_log"),
        legacy_aliases=(),  # eski 100 kaydi formul icin kullanilir; import ayri tespit
    ),
    MigEntry(
        111, "111_nexgen_planlama_siparis_finans", "111_nexgen_planlama_siparis_finans.py",
        "planlama siparis finans kolonlari",
        required_columns=(
            ("nexgen_planlama_siparis", "anlasma_para_birimi"),
            ("nexgen_planlama_siparis", "vade_gun"),
            ("nexgen_planlama_siparis", "anlasma_birim_fiyat"),
        ),
    ),
    MigEntry(
        112, "112_nexgen_planlama_mehmet_yetki", "112_nexgen_planlama_mehmet_yetki.py",
        "Mehmet NexGen permission overrides",
        risk="permission",
    ),
    MigEntry(
        113, "113_nexgen_numune_talep", "113_nexgen_numune_talep.py",
        "nexgen_numune_talep tablosu",
        required_tables=("nexgen_numune_talep",),
    ),
    MigEntry(
        114, "114_nexgen_numune_talep_arge_birlestirme",
        "114_nexgen_numune_talep_arge_birlestirme.py",
        "numune talep arge birlestirme",
        dependencies=(113,),
        required_tables=("nexgen_numune_talep_gelisme",),
        required_columns=(("nexgen_numune_talep", "isleme_alan_kullanici_id"),),
    ),
    MigEntry(
        115, "115_nexgen_numune_talep_mehmet_musteri_alanlari",
        "115_nexgen_numune_talep_mehmet_musteri_alanlari.py",
        "numune talep mehmet musteri alanlari",
        dependencies=(113, 114),
        required_columns=(
            ("nexgen_numune_talep", "karsilama_yolu"),
            ("nexgen_numune_talep", "numune_adedi"),
        ),
    ),
    MigEntry(
        116, "116_nexgen_ferhat_deneme_kalip_gramaj",
        "116_nexgen_ferhat_deneme_kalip_gramaj.py",
        "Ferhat deneme kalip snapshot + gramaj_gr + saha.ferhat_islem",
        dependencies=(106, 109),
        required_columns=(
            ("nexgen_arge_deneme", "kalip_id"),
            ("nexgen_arge_boyut_sonuc", "gramaj_gr"),
        ),
        risk="permission",
    ),
    MigEntry(
        126, "126_mo_tahsilat_plani",
        "126_mo_tahsilat_plani.py",
        "MO sipariş tahsilat planı + mo_tahsilat_kayit",
        dependencies=(116,),
        required_tables=("mo_tahsilat_kayit",),
        required_columns=(
            ("nexgen_planlama_siparis", "tahsilat_kurali"),
            ("nexgen_planlama_siparis", "tahsilat_durumu"),
        ),
    ),
    MigEntry(
        127, "127_mo_musteri_sevkiyat",
        "127_mo_musteri_sevkiyat.py",
        "Gerçek outbound müşteri sevkiyat entity",
        dependencies=(126,),
        required_tables=("mo_musteri_sevkiyat", "mo_musteri_sevkiyat_kalem"),
    ),
)

BY_VERSION = {m.version: m for m in MANIFEST}
EXPECTED_VERSIONS = tuple(m.version for m in MANIFEST)

MEHMET_KADI = 'mehmet'
# (Kod, can_view, can_create, can_update, can_delete, can_approve, can_report, can_manage)
MEHMET_OVERRIDE_SPECS: tuple[tuple[str, int, int, int, int, int, int, int], ...] = (
    ('nexgen.view', 1, 0, 0, 0, 0, 1, 0),
    ('nexgen.plan.view', 1, 0, 0, 0, 0, 1, 0),
    ('nexgen.plan.manage', 0, 0, 0, 0, 0, 0, 1),
)

def tablo_var(cur, tablo: str) -> bool:
    return bool(
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
        ).fetchone()
    )


def kolon_var(cur, tablo: str, kolon: str) -> bool:
    if not tablo_var(cur, tablo):
        return False
    return kolon in [c[1] for c in cur.execute(f"PRAGMA table_info({tablo})").fetchall()]


def _override_flags_ok(row, spec: tuple[str, int, int, int, int, int, int, int]) -> bool:
    _, cv, cc, cu, cd, ca, cr, cm = spec
    return (
        int(row['can_view'] or 0) == cv
        and int(row['can_create'] or 0) == cc
        and int(row['can_update'] or 0) == cu
        and int(row['can_delete'] or 0) == cd
        and int(row['can_approve'] or 0) == ca
        and int(row['can_report'] or 0) == cr
        and int(row['can_manage'] or 0) == cm
    )


def mehmet_nexgen_overrides_ok(cur) -> bool:
    """Migration 112 tamamlandı mı — KullaniciAdi/Kod üzerinden."""
    if not tablo_var(cur, 'user_permission_override'):
        return False
    mehmet = cur.execute(
        "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi=? AND Aktif=1",
        (MEHMET_KADI,),
    ).fetchone()
    if not mehmet:
        return False
    mid = int(mehmet['Id'])
    for spec in MEHMET_OVERRIDE_SPECS:
        kod = spec[0]
        row = cur.execute(
            """
            SELECT upo.can_view, upo.can_create, upo.can_update, upo.can_delete,
                   upo.can_approve, upo.can_report, upo.can_manage
            FROM user_permission_override upo
            JOIN sistem_yetki y ON y.Id = upo.YetkiId
            WHERE upo.KullaniciId=? AND y.Kod=?
            """,
            (mid, kod),
        ).fetchone()
        if not row or not _override_flags_ok(row, spec):
            return False
    return True


def schema_satisfies(cur, entry: MigEntry) -> bool:
    for t in entry.required_tables:
        if not tablo_var(cur, t):
            return False
    for t, c in entry.required_columns:
        if not kolon_var(cur, t, c):
            return False
    if entry.version == 112:
        return mehmet_nexgen_overrides_ok(cur)
    # 108 permission: schema marker yok — version kaydı veya yetki satırı
    if entry.version == 108:
        row = cur.execute(
            """
            SELECT 1 FROM sistem_rol_yetki ry
            JOIN sistem_yetki y ON y.Id = ry.YetkiId
            WHERE ry.RolId=35 AND y.Kod='nexgen.tablet.view' AND ry.can_view=1
            """
        ).fetchone()
        return bool(row)
    # 96, 105: soft yoksa version kaydı ile yetin (aşağıda)
    if not entry.required_tables and not entry.required_columns and entry.version not in (108,):
        return True  # index/view — version kaydı yeterli; verify ayrı
    return True


def detect_applied_by_schema(cur, entry: MigEntry) -> bool:
    """Migration kaydı olmasa bile şemadan uygulanmış mı?"""
    if entry.version in (108, 112):
        return schema_satisfies(cur, entry)
    if entry.required_tables or entry.required_columns:
        for t in entry.required_tables:
            if not tablo_var(cur, t):
                return False
        for t, c in entry.required_columns:
            if not kolon_var(cur, t, c):
                return False
        return bool(entry.required_tables or entry.required_columns)
    return False


def read_migration_versions(cur) -> set[int]:
    if not tablo_var(cur, "schema_migrations"):
        return set()
    out = set()
    for row in cur.execute("SELECT version FROM schema_migrations").fetchall():
        v = row[0]
        try:
            out.add(int(str(v).strip()))
        except (TypeError, ValueError):
            continue
    return out
