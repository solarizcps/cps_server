# -*- coding: utf-8 -*-
"""FinancialPostingService — yalnız Cari_Har yazıcı (iş akışı yönetmez)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from modules.nexgen.finans_belgesi_config import (
    BELGE_TIP_SATIS_SEVKIYAT,
    BELGE_TIP_TAHSILAT,
    DURUM_ONAYLANDI,
    POSTING_DURUM_BEKLIYOR,
    POSTING_DURUM_HAZIR,
    POSTING_DURUM_POST_EDILDI,
    posting_idempotency_key_uret,
)
from modules.nexgen.finans_belgesi_repository import (
    FinansBelgesiError,
    get_by_id,
    posting_durumu_dogrula_post,
    posting_idempotency_dogrula,
    resolve_golden_cari_kart,
    tablo_var,
)
from modules.nexgen.finans_core_config import KAYNAK_SISTEM_LEGACY, idempotency_hareket_post
from modules.nexgen.finans_ledger_standard import validate_hareket_tutarlari
from modules.nexgen.finance_workflow_service import FinanceWorkflowService
from modules.nexgen.mo_tahsilat_config import CARI_ENTEGRASYON_AKTIF


class FinancialPostingError(Exception):
    def __init__(self, mesaj: str, kod: int = 409, hata_kodu: str = 'POSTING_HATA'):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


@dataclass
class LegacyHareketRequest:
    ckod: str
    tarih: str
    belge_no: str
    belge_tip: str
    aciklama: str
    borc: float
    alacak: float
    kaynak_sistem: str = KAYNAK_SISTEM_LEGACY
    kaynak_tur: str | None = None
    kaynak_id: int | None = None
    olay_turu: str | None = None
    idempotency_key: str | None = None
    kullanici: str | None = None
    legacy_caller: str | None = None


class FinancialPostingService:
    """Katman-2: onaylı finans belgesini Cari_Har'a post eder."""

    _TEST_FAULT_POINT: str | None = None

    @staticmethod
    def _cari_har_count(con: sqlite3.Connection) -> int:
        if not tablo_var(con, 'Cari_Har'):
            return 0
        return int(con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0])

    @classmethod
    def _live_enabled(cls, force_live: bool) -> bool:
        return bool(CARI_ENTEGRASYON_AKTIF and force_live)

    @classmethod
    def _check_fault(cls, point: str) -> None:
        if cls._TEST_FAULT_POINT == point:
            raise FinansBelgesiError(
                f'Test fault injection: {point}', 500, 'TEST_FAULT',
            )

    @staticmethod
    def _insert_cari_har_row(con: sqlite3.Connection, payload: dict[str, Any]) -> int:
        """Tek izinli Cari_Har INSERT noktası."""
        validate_hareket_tutarlari(payload['Borc'], payload['Alacak'])
        cur = con.execute(
            """
            INSERT INTO Cari_Har (CKod, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload['CKod'], payload['Tarih'], payload['BelgeNo'], payload['BelgeTip'],
                payload['Aciklama'], payload['Borc'], payload['Alacak'],
            ),
        )
        return int(cur.lastrowid)

    @classmethod
    def _legacy_idempotent_lookup(
        cls,
        con: sqlite3.Connection,
        req: LegacyHareketRequest,
    ) -> int | None:
        if req.idempotency_key and tablo_var(con, 'finans_hareket'):
            idem = idempotency_hareket_post(req.idempotency_key)
            row = con.execute(
                'SELECT cari_har_id FROM finans_hareket WHERE idempotency_key=?',
                (idem,),
            ).fetchone()
            if row:
                return int(row['cari_har_id'])
        row = con.execute(
            """
            SELECT Id FROM Cari_Har
            WHERE CKod=? AND BelgeNo=? AND BelgeTip=?
            ORDER BY Id DESC LIMIT 1
            """,
            (req.ckod, req.belge_no, req.belge_tip),
        ).fetchone()
        return int(row['Id']) if row else None

    @classmethod
    def post_legacy_hareket(
        cls,
        con: sqlite3.Connection,
        req: LegacyHareketRequest,
        *,
        legacy_compat_mode: bool = False,
    ) -> dict[str, Any]:
        """Legacy finans modülü uyum — commit yapmaz, metadata opsiyonel."""
        if not legacy_compat_mode:
            raise FinancialPostingError(
                'Legacy hareket yalnız legacy_compat_mode=True ile çağrılabilir.',
                403, 'LEGACY_MODE_GEREKLI',
            )
        mevcut = cls._legacy_idempotent_lookup(con, req)
        if mevcut:
            return {
                'ok': True,
                'idempotent': True,
                'cari_har_id': mevcut,
                'legacy_compat_mode': True,
                'metadata_written': False,
            }

        payload = {
            'CKod': req.ckod,
            'Tarih': (req.tarih or datetime.now().strftime('%Y-%m-%d'))[:10],
            'BelgeNo': req.belge_no,
            'BelgeTip': req.belge_tip,
            'Aciklama': req.aciklama,
            'Borc': round(float(req.borc or 0), 2),
            'Alacak': round(float(req.alacak or 0), 2),
        }
        cls._check_fault('before_insert')
        har_id = cls._insert_cari_har_row(con, payload)
        cls._check_fault('after_insert')

        metadata_written = False
        if req.idempotency_key and tablo_var(con, 'finans_hareket'):
            try:
                from modules.nexgen.finans_ledger_service import create_metadata
                from modules.nexgen.finans_posting_context import PostingContext

                ctx = PostingContext(
                    transaction_id=f'legacy-{req.kaynak_tur or "LEGACY"}-{req.kaynak_id or 0}',
                    idempotency_key=req.idempotency_key,
                    kaynak_sistem=req.kaynak_sistem,
                    kaynak_tur=req.kaynak_tur,
                    kaynak_id=req.kaynak_id,
                    olay_turu=req.olay_turu,
                )
                islem = 'ALACAK' if payload['Alacak'] > 0 else 'BORC'
                create_metadata(
                    con,
                    cari_har_id=har_id,
                    ckod=req.ckod,
                    ctx=ctx,
                    islem_tipi=islem,
                    kaynak_entity='LEGACY',
                    kaynak_entity_id=req.kaynak_id,
                )
                metadata_written = True
            except Exception:
                metadata_written = False

        return {
            'ok': True,
            'idempotent': False,
            'cari_har_id': har_id,
            'legacy_compat_mode': True,
            'legacy_caller': req.legacy_caller,
            'metadata_written': metadata_written,
            'metadata_skipped': not metadata_written,
        }

    @classmethod
    def delete_legacy_hareket(
        cls,
        con: sqlite3.Connection,
        cari_har_id: int,
        *,
        legacy_compat_mode: bool = False,
    ) -> bool:
        """Legacy geri-al uyumu — yalnız legacy_compat_mode. Teknik borç."""
        if not legacy_compat_mode:
            raise FinancialPostingError(
                'Legacy silme yalnız legacy_compat_mode=True ile çağrılabilir.',
                403, 'LEGACY_MODE_GEREKLI',
            )
        if not cari_har_id:
            return False
        cur = con.execute('DELETE FROM Cari_Har WHERE Id=?', (int(cari_har_id),))
        if tablo_var(con, 'finans_hareket'):
            con.execute('DELETE FROM finans_hareket WHERE cari_har_id=?', (int(cari_har_id),))
        return cur.rowcount > 0

    @classmethod
    def _existing_posted_result(
        cls, con: sqlite3.Connection, belge: dict[str, Any],
    ) -> dict[str, Any] | None:
        pd = (belge.get('posting_durumu') or '').upper()
        har_id = belge.get('cari_har_id')
        if har_id and pd == POSTING_DURUM_POST_EDILDI:
            return {
                'ok': True,
                'dry_run': False,
                'already_posted': True,
                'cari_har_id': int(har_id),
                'belge': belge,
                'cari_har_count_before': cls._cari_har_count(con),
                'cari_har_count_after': cls._cari_har_count(con),
                'belge_id': int(belge['id']),
            }
        return None

    @classmethod
    def _validate_belge_post(
        cls, con: sqlite3.Connection, belge: dict[str, Any], beklenen_tip: str,
    ) -> None:
        if (belge.get('belge_tipi') or '') != beklenen_tip:
            raise FinansBelgesiError(
                f'Belge tipi uyumsuz: {belge.get("belge_tipi")}', 409, 'BELGE_TIP_UYUMSUZ',
            )
        if (belge.get('durum') or '') != DURUM_ONAYLANDI:
            raise FinansBelgesiError(
                f'Yalnız ONAYLANDI belge post edilir ({belge.get("durum")}).', 409, 'POST_ONAY_GEREKLI',
            )
        posting_durumu_dogrula_post(con, belge)

    @classmethod
    def _validate_live_post(cls, belge: dict[str, Any]) -> None:
        pd = (belge.get('posting_durumu') or POSTING_DURUM_BEKLIYOR).upper()
        if pd != POSTING_DURUM_HAZIR:
            raise FinansBelgesiError(
                'Posting önizleme HAZIR değil — önce dry-run çalıştırın.', 409, 'POST_HAZIR_DEGIL',
            )
        if not (belge.get('para_birimi') or '').strip():
            raise FinansBelgesiError('Para birimi eksik.', 409, 'PARA_BIRIMI_EKSIK')

    @staticmethod
    def _borc_payload(belge: dict[str, Any], ckod: str) -> dict[str, Any]:
        tutar = float(belge.get('toplam_tutar') or 0)
        belge_no = belge.get('cari_har_belge_no') or belge.get('belge_kodu')
        kg = belge.get('toplam_kg')
        kg_s = f' / {kg} kg' if kg not in (None, '') else ''
        aciklama = (
            f"Sevkiyat {belge.get('kaynak_no') or ''} / Sipariş {belge.get('siparis_no') or ''} "
            f"/ İrsaliye {belge.get('irsaliye_no') or '—'}{kg_s}"
        ).strip()
        return {
            'CKod': ckod,
            'Tarih': (belge.get('islem_tarihi') or datetime.now().strftime('%Y-%m-%d'))[:10],
            'BelgeNo': belge_no,
            'BelgeTip': 'FATURA',
            'Aciklama': aciklama,
            'Borc': round(tutar, 2),
            'Alacak': 0.0,
        }

    @staticmethod
    def _alacak_payload(belge: dict[str, Any], ckod: str) -> dict[str, Any]:
        tutar = float(belge.get('toplam_tutar') or 0)
        belge_no = belge.get('cari_har_belge_no') or belge.get('belge_kodu')
        aciklama = f"Tahsilat {belge.get('kaynak_no') or ''}".strip()
        return {
            'CKod': ckod,
            'Tarih': (belge.get('islem_tarihi') or datetime.now().strftime('%Y-%m-%d'))[:10],
            'BelgeNo': belge_no,
            'BelgeTip': 'TAHSILAT',
            'Aciklama': aciklama,
            'Borc': 0.0,
            'Alacak': round(tutar, 2),
        }

    @classmethod
    def _post_core(
        cls,
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None,
        *,
        beklenen_tip: str,
        payload_fn,
        force_live: bool,
    ) -> dict[str, Any]:
        belge = get_by_id(con, belge_id)
        existing = cls._existing_posted_result(con, belge)
        if existing:
            return existing

        cls._validate_belge_post(con, belge, beklenen_tip)
        tutar = float(belge.get('toplam_tutar') or 0)
        if tutar <= 0:
            raise FinansBelgesiError('Post tutarı sıfır.', 409, 'POST_TUTAR_SIFIR')

        ckod = resolve_golden_cari_kart(con, int(belge['cari_id']))
        payload = payload_fn(belge, ckod)
        belge_no = payload['BelgeNo']
        live = cls._live_enabled(force_live)
        pre_count = cls._cari_har_count(con)
        post_key = posting_idempotency_key_uret(belge.get('idempotency_key') or '')

        if not live:
            guncel = FinanceWorkflowService.posting_sonrasi_isaretle(
                con, belge_id, None, belge_no, kullanici_id, kullanici_ad, dry_run=True,
            )
            return {
                'ok': True,
                'dry_run': True,
                'cari_entegrasyon_aktif': CARI_ENTEGRASYON_AKTIF,
                'would_post': payload,
                'posting_durumu': guncel.get('posting_durumu') or POSTING_DURUM_HAZIR,
                'cari_har_count_before': pre_count,
                'cari_har_count_after': cls._cari_har_count(con),
                'belge_id': belge_id,
            }

        cls._validate_live_post(belge)
        cls._check_fault('before_insert')
        posting_idempotency_dogrula(con, post_key, belge_id)

        har_id = cls._insert_cari_har_row(con, payload)
        cls._check_fault('after_insert')

        guncel = FinanceWorkflowService.posting_sonrasi_isaretle(
            con, belge_id, har_id, belge_no, kullanici_id, kullanici_ad,
            dry_run=False, posting_idempotency_key=post_key,
        )
        cls._check_fault('after_belge_update')

        return {
            'ok': True,
            'dry_run': False,
            'cari_har_id': har_id,
            'would_post': payload,
            'belge': guncel,
            'cari_har_count_before': pre_count,
            'cari_har_count_after': cls._cari_har_count(con),
            'belge_id': belge_id,
        }

    @classmethod
    def post_borc(
        cls,
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        *,
        force_live: bool = False,
    ) -> dict[str, Any]:
        return cls._post_core(
            con, belge_id, kullanici_id, kullanici_ad,
            beklenen_tip=BELGE_TIP_SATIS_SEVKIYAT,
            payload_fn=cls._borc_payload,
            force_live=force_live,
        )

    @classmethod
    def post_alacak(
        cls,
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        *,
        force_live: bool = False,
    ) -> dict[str, Any]:
        return cls._post_core(
            con, belge_id, kullanici_id, kullanici_ad,
            beklenen_tip=BELGE_TIP_TAHSILAT,
            payload_fn=cls._alacak_payload,
            force_live=force_live,
        )

    @classmethod
    def validate_post_borc(cls, con: sqlite3.Connection, belge_id: int) -> dict[str, Any]:
        """Flag kapalı validate-only kısayolu."""
        return cls.post_borc(con, belge_id, kullanici_id=0, force_live=False)

    @classmethod
    def validate_post_alacak(cls, con: sqlite3.Connection, belge_id: int) -> dict[str, Any]:
        return cls.post_alacak(con, belge_id, kullanici_id=0, force_live=False)
