# -*- coding: utf-8 -*-
"""FinanceWorkflowService — finans belgesi iş akışı (Cari_Har yazmaz)."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_config import (
    BELGE_TIP_SATIS_SEVKIYAT,
    BELGE_TIP_TAHSILAT,
    DURUM_BEKLIYOR,
    DURUM_EKSIK_BILGI,
    DURUM_INCELEMEDE,
    DURUM_KAPANDI,
    DURUM_ONAYLANDI,
    DURUM_POST_EDILDI,
    KAYNAK_TIP_SEVKIYAT,
    KAYNAK_TIP_TAHSILAT_KAYIT,
    OLAY_DUZELTMEYE_GONDERILDI,
    OLAY_INCELEMEYE_ALINDI,
    OLAY_KAPANDI,
    OLAY_ONAYLANDI,
    OLAY_POST_DRY_RUN,
    OLAY_POST_EDILDI,
    OLAY_REDDEDILDI,
    ONAYA_HAZIR_DURUMLAR,
    idempotency_sevkiyat,
    idempotency_tahsilat,
    posting_idempotency_key_uret,
)
from modules.nexgen.finans_belgesi_repository import (
    FinansBelgesiError,
    belge_kodu_uret,
    durum_guncelle,
    get_by_id,
    get_by_idempotency,
    get_by_kaynak,
    insert_belge,
    posting_isaretle,
    tablo_var,
)
from modules.nexgen.mo_sevkiyat_config import DURUM_ETIKET as SEVK_DURUM_ETIKET
from modules.nexgen.mo_tahsilat_config import KAYIT_DURUM_MUHASEBE_BEKLIYOR, KAYIT_DURUM_ONAYLANDI
from modules.nexgen.pzm_siparis_read import pzm_payload_unpack, pzm_siparis_finans_alanlari, pzm_siparis_header_getir


class FinanceWorkflowService:
    """Katman-1: belge oluşturma, durum, onay — posting yapmaz."""

    SEVK_FINANS_DURUMLAR = frozenset({'SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI'})

    @staticmethod
    def _siparis_kalem_id_snapshot(kalemler: list) -> int | None:
        ids: set[int] = set()
        for k in kalemler:
            d = dict(k) if not isinstance(k, dict) else k
            kid = d.get('siparis_kalem_id')
            if kid not in (None, ''):
                ids.add(int(kid))
        if len(ids) == 1:
            return ids.pop()
        return None

    @staticmethod
    def _siparis_vade_snapshot(con: sqlite3.Connection, siparis_id: int) -> dict[str, Any]:
        """Sipariş planından vade snapshot — yeni hesap yazmaz."""
        row = con.execute(
            """
            SELECT planlanan_tahsilat_tarihi, vade_gun, tahsilat_kurali, tahsilat_durumu
            FROM nexgen_planlama_siparis WHERE id=?
            """,
            (siparis_id,),
        ).fetchone()
        if not row:
            return {}
        d = dict(row)
        vade_tarihi = (d.get('planlanan_tahsilat_tarihi') or '')[:10] or None
        vg = d.get('vade_gun')
        try:
            vade_gun = int(vg) if vg not in (None, '') else None
        except (TypeError, ValueError):
            vade_gun = None
        return {
            'vade_tarihi': vade_tarihi,
            'vade_gun': vade_gun,
            'tahsilat_kurali': d.get('tahsilat_kurali'),
        }

    @classmethod
    def belge_olustur_sevkiyat(
        cls,
        con: sqlite3.Connection,
        sevkiyat_id: int,
        kullanici_id: int | None = None,
        kullanici_ad: str | None = None,
    ) -> dict[str, Any]:
        if not tablo_var(con, 'finans_belgesi'):
            raise FinansBelgesiError('Migration 128 uygulanmamış.', 503, 'MIGRATION_128')

        idem = idempotency_sevkiyat(sevkiyat_id)
        mevcut = get_by_idempotency(con, idem)
        if not mevcut:
            mevcut = get_by_kaynak(con, BELGE_TIP_SATIS_SEVKIYAT, KAYNAK_TIP_SEVKIYAT, sevkiyat_id)
        if mevcut:
            return mevcut

        row = con.execute(
            """
            SELECT s.*, ps.siparis_no, c.unvan AS cari_unvan
            FROM mo_musteri_sevkiyat s
            LEFT JOIN nexgen_planlama_siparis ps ON ps.id = s.siparis_id
            LEFT JOIN nexgen_cari c ON c.id = s.cari_id
            WHERE s.id=? AND s.aktif=1
            """,
            (sevkiyat_id,),
        ).fetchone()
        if not row:
            raise FinansBelgesiError('Sevkiyat bulunamadı.', 404, 'SEVKIYAT_YOK')
        s = dict(row)
        durum = (s.get('durum') or '').upper()
        if durum not in cls.SEVK_FINANS_DURUMLAR:
            raise FinansBelgesiError(
                f'Sevkiyat finans için uygun değil ({durum}).', 409, 'SEVK_DURUM_UYGUN_DEGIL',
            )

        kalemler = con.execute(
            'SELECT id, siparis_kalem_id, miktar_kg FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?',
            (sevkiyat_id,),
        ).fetchall()
        gercek_kg = round(sum(float(k['miktar_kg'] or 0) for k in kalemler), 3)
        if gercek_kg <= 0.001:
            raise FinansBelgesiError('Sevk kg sıfır — belge oluşturulamaz.', 409, 'SEVK_KG_SIFIR')

        siparis_id = int(s['siparis_id'])
        hdr = pzm_siparis_header_getir(con, siparis_id) or {}
        fin = pzm_siparis_finans_alanlari(hdr, pzm_payload_unpack(hdr.get('talep_referansi')))
        vade_snap = cls._siparis_vade_snapshot(con, siparis_id)

        bf = fin.get('anlasma_birim_fiyat')
        pb = fin.get('anlasma_para_birimi')
        birim_fiyat = None
        if bf not in (None, ''):
            try:
                birim_fiyat = float(bf)
            except (TypeError, ValueError):
                birim_fiyat = None

        eksik = birim_fiyat is None or birim_fiyat <= 0 or not pb
        baslangic_durum = DURUM_EKSIK_BILGI if eksik else DURUM_BEKLIYOR
        toplam_tutar = round(gercek_kg * birim_fiyat, 2) if birim_fiyat and birim_fiyat > 0 else 0.0

        sevk_tarihi = (s.get('sevk_tarihi') or s.get('hazirlik_tarihi') or '')[:10]
        if not sevk_tarihi:
            raise FinansBelgesiError('Sevk tarihi yok.', 409, 'SEVK_TARIHI_YOK')

        ckod = None
        es = con.execute(
            """
            SELECT cari_kart_ckod FROM cari_eslestirme
            WHERE nexgen_cari_id=? AND aktif=1 ORDER BY id DESC LIMIT 1
            """,
            (int(s['cari_id']),),
        ).fetchone()
        if es and es['cari_kart_ckod']:
            ckod = es['cari_kart_ckod']

        data = {
            'belge_kodu': belge_kodu_uret(con),
            'belge_tipi': BELGE_TIP_SATIS_SEVKIYAT,
            'durum': baslangic_durum,
            'sevkiyat_id': sevkiyat_id,
            'tahsilat_kayit_id': None,
            'siparis_id': siparis_id,
            'cari_id': int(s['cari_id']),
            'cari_kart_ckod': ckod,
            'kaynak_no': s.get('sevkiyat_no'),
            'siparis_no': s.get('siparis_no'),
            'cari_unvan': s.get('cari_unvan') or '—',
            'irsaliye_no': s.get('irsaliye_no'),
            'islem_tarihi': sevk_tarihi,
            'toplam_kg': gercek_kg,
            'birim_fiyat': birim_fiyat,
            'para_birimi': (pb or 'TRY') if pb else 'TRY',
            'toplam_tutar': toplam_tutar,
            'vade_gun': vade_snap.get('vade_gun'),
            'vade_tarihi': vade_snap.get('vade_tarihi'),
            'idempotency_key': idem,
            'kaynak_tipi': KAYNAK_TIP_SEVKIYAT,
            'kaynak_id': sevkiyat_id,
            'siparis_kalem_id': cls._siparis_kalem_id_snapshot(kalemler),
            'olusturan_id': kullanici_id,
            'olusturma_tarihi': None,
            'guncelleme_tarihi': None,
            'audit_json': '[]',
            'aktif': 1,
            '_olay': 'BELGE_OLUSTURULDU',
            '_kullanici_ad': kullanici_ad,
            '_kaynak_tipi': KAYNAK_TIP_SEVKIYAT,
            '_kaynak_id': sevkiyat_id,
            '_audit_ek': {
                'kaynak_tipi': KAYNAK_TIP_SEVKIYAT,
                'kaynak_id': sevkiyat_id,
                'sevkiyat_durum': durum,
                'sevkiyat_durum_etiket': SEVK_DURUM_ETIKET.get(durum, durum),
                'kalem_sayisi': len(kalemler),
                'tahsilat_kurali': vade_snap.get('tahsilat_kurali'),
                'eksik_fiyat': eksik,
            },
        }
        return insert_belge(con, data)

    @classmethod
    def belge_olustur_tahsilat(
        cls,
        con: sqlite3.Connection,
        tahsilat_kayit_id: int,
        kullanici_id: int | None = None,
        kullanici_ad: str | None = None,
    ) -> dict[str, Any]:
        if not tablo_var(con, 'finans_belgesi'):
            raise FinansBelgesiError('Migration 128 uygulanmamış.', 503, 'MIGRATION_128')

        idem = idempotency_tahsilat(tahsilat_kayit_id)
        mevcut = get_by_idempotency(con, idem)
        if not mevcut:
            mevcut = get_by_kaynak(
                con, BELGE_TIP_TAHSILAT, KAYNAK_TIP_TAHSILAT_KAYIT, tahsilat_kayit_id,
            )
        if mevcut:
            return mevcut

        row = con.execute(
            """
            SELECT tk.*, c.unvan AS cari_unvan, ps.siparis_no
            FROM mo_tahsilat_kayit tk
            LEFT JOIN nexgen_cari c ON c.id = tk.cari_id
            LEFT JOIN nexgen_planlama_siparis ps ON ps.id = tk.siparis_id
            WHERE tk.id=? AND tk.aktif=1
            """,
            (tahsilat_kayit_id,),
        ).fetchone()
        if not row:
            raise FinansBelgesiError('Tahsilat kaydı bulunamadı.', 404, 'TAHSILAT_YOK')
        t = dict(row)
        td = (t.get('durum') or '').upper()
        if td not in (KAYIT_DURUM_MUHASEBE_BEKLIYOR, KAYIT_DURUM_ONAYLANDI):
            raise FinansBelgesiError(
                f'Tahsilat finans belgesi için uygun değil ({td}).', 409, 'TAHSILAT_DURUM_UYGUN_DEGIL',
            )

        tutar = t.get('alinan_tutar')
        if tutar in (None, ''):
            tutar = t.get('beklenen_tutar')
        try:
            tutar_f = float(tutar or 0)
        except (TypeError, ValueError):
            tutar_f = 0.0
        if tutar_f <= 0:
            raise FinansBelgesiError('Tahsilat tutarı geçersiz.', 409, 'TAHSILAT_TUTAR_GECERSIZ')

        islem_tarihi = (t.get('alinan_tarih') or '')[:10]
        if not islem_tarihi:
            raise FinansBelgesiError('Tahsilat tarihi yok.', 409, 'TAHSILAT_TARIHI_YOK')

        ckod = None
        es = con.execute(
            """
            SELECT cari_kart_ckod FROM cari_eslestirme
            WHERE nexgen_cari_id=? AND aktif=1 ORDER BY id DESC LIMIT 1
            """,
            (int(t['cari_id']),),
        ).fetchone()
        if es and es['cari_kart_ckod']:
            ckod = es['cari_kart_ckod']

        data = {
            'belge_kodu': belge_kodu_uret(con),
            'belge_tipi': BELGE_TIP_TAHSILAT,
            'durum': DURUM_BEKLIYOR,
            'sevkiyat_id': None,
            'tahsilat_kayit_id': tahsilat_kayit_id,
            'siparis_id': t.get('siparis_id'),
            'cari_id': int(t['cari_id']),
            'cari_kart_ckod': ckod,
            'kaynak_no': t.get('kayit_kodu'),
            'siparis_no': t.get('siparis_no'),
            'cari_unvan': t.get('cari_unvan') or '—',
            'irsaliye_no': None,
            'islem_tarihi': islem_tarihi,
            'toplam_kg': None,
            'birim_fiyat': None,
            'para_birimi': 'TRY',
            'toplam_tutar': round(tutar_f, 2),
            'vade_gun': None,
            'vade_tarihi': None,
            'idempotency_key': idem,
            'kaynak_tipi': KAYNAK_TIP_TAHSILAT_KAYIT,
            'kaynak_id': tahsilat_kayit_id,
            'siparis_kalem_id': None,
            'olusturan_id': kullanici_id,
            'olusturma_tarihi': None,
            'guncelleme_tarihi': None,
            'audit_json': '[]',
            'aktif': 1,
            '_olay': 'BELGE_OLUSTURULDU',
            '_kullanici_ad': kullanici_ad,
            '_kaynak_tipi': KAYNAK_TIP_TAHSILAT_KAYIT,
            '_kaynak_id': tahsilat_kayit_id,
            '_audit_ek': {
                'kaynak_tipi': KAYNAK_TIP_TAHSILAT_KAYIT,
                'kaynak_id': tahsilat_kayit_id,
                'odeme_tipi': t.get('odeme_tipi'),
                'odeme_referansi': t.get('odeme_referansi'),
                'aciklama': t.get('aciklama'),
            },
        }
        return insert_belge(con, data)

    @staticmethod
    def incelemeye_al(
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
    ) -> dict[str, Any]:
        belge = get_by_id(con, belge_id)
        if (belge.get('durum') or '') == DURUM_EKSIK_BILGI:
            raise FinansBelgesiError(
                'Eksik bilgi — incelemeye alınamaz.', 409, 'EKSIK_BILGI',
            )
        return durum_guncelle(
            con, belge_id, DURUM_INCELEMEDE,
            kullanici_id=kullanici_id, kullanici_ad=kullanici_ad,
            olay=OLAY_INCELEMEYE_ALINDI,
            kaynak_tipi=belge.get('belge_tipi'),
            kaynak_id=belge.get('sevkiyat_id') or belge.get('tahsilat_kayit_id'),
        )

    @staticmethod
    def onayla(
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        notu: str | None = None,
    ) -> dict[str, Any]:
        belge = get_by_id(con, belge_id)
        durum = belge.get('durum') or ''
        if durum not in ONAYA_HAZIR_DURUMLAR:
            raise FinansBelgesiError(
                f'Onay için uygun durum değil ({durum}).', 409, 'ONAY_DURUM_UYGUN_DEGIL',
            )
        if belge.get('belge_tipi') == BELGE_TIP_SATIS_SEVKIYAT:
            if not belge.get('birim_fiyat') or float(belge.get('birim_fiyat') or 0) <= 0:
                raise FinansBelgesiError('Birim fiyat eksik — onaylanamaz.', 409, 'FIYAT_EKSIK')
        return durum_guncelle(
            con, belge_id, DURUM_ONAYLANDI,
            kullanici_id=kullanici_id, kullanici_ad=kullanici_ad,
            olay=OLAY_ONAYLANDI,
            aciklama=notu,
            ek_updates={
                'onaylayan_id': kullanici_id,
                'onay_tarihi': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'muhasebe_notu': (notu or '').strip() or belge.get('muhasebe_notu'),
            },
        )

    @staticmethod
    def duzeltmeye_gonder(
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        notu: str | None = None,
    ) -> dict[str, Any]:
        from modules.nexgen.finans_belgesi_config import DURUM_DUZELTME_BEKLIYOR
        belge = get_by_id(con, belge_id)
        return durum_guncelle(
            con, belge_id, DURUM_DUZELTME_BEKLIYOR,
            kullanici_id=kullanici_id, kullanici_ad=kullanici_ad,
            olay=OLAY_DUZELTMEYE_GONDERILDI,
            aciklama=notu,
            ek_updates={'muhasebe_notu': notu or belge.get('muhasebe_notu')},
        )

    @staticmethod
    def reddet(
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        gerekce: str | None = None,
    ) -> dict[str, Any]:
        from modules.nexgen.finans_belgesi_config import DURUM_REDDEDILDI
        if not (gerekce or '').strip():
            raise FinansBelgesiError('Red gerekçesi zorunlu.', 400, 'RED_GEREKCE')
        return durum_guncelle(
            con, belge_id, DURUM_REDDEDILDI,
            kullanici_id=kullanici_id, kullanici_ad=kullanici_ad,
            olay=OLAY_REDDEDILDI,
            aciklama=gerekce,
            ek_updates={'red_gerekce': gerekce.strip()},
        )

    @staticmethod
    def kapat(
        con: sqlite3.Connection,
        belge_id: int,
        kullanici_id: int,
        kullanici_ad: str | None = None,
    ) -> dict[str, Any]:
        belge = get_by_id(con, belge_id)
        if (belge.get('durum') or '') != DURUM_POST_EDILDI:
            raise FinansBelgesiError('Yalnız post edilmiş belge kapatılabilir.', 409, 'KAPAT_DURUM')
        return durum_guncelle(
            con, belge_id, DURUM_KAPANDI,
            kullanici_id=kullanici_id, kullanici_ad=kullanici_ad,
            olay=OLAY_KAPANDI,
        )

    @staticmethod
    def posting_sonrasi_isaretle(
        con: sqlite3.Connection,
        belge_id: int,
        cari_har_id: int | None,
        belge_no: str | None,
        kullanici_id: int,
        kullanici_ad: str | None = None,
        dry_run: bool = False,
        posting_idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """FinancialPostingService tarafından çağrılır."""
        belge = get_by_id(con, belge_id)
        if (belge.get('durum') or '') != DURUM_ONAYLANDI:
            raise FinansBelgesiError('Posting için belge onaylı olmalı.', 409, 'POST_DURUM')
        if belge.get('cari_har_id'):
            raise FinansBelgesiError('Belge zaten post edilmiş.', 409, 'POST_DUPLICATE')
        olay = OLAY_POST_DRY_RUN if dry_run else OLAY_POST_EDILDI
        if not posting_idempotency_key and not dry_run:
            posting_idempotency_key = posting_idempotency_key_uret(belge.get('idempotency_key') or '')
        return posting_isaretle(
            con, belge_id,
            dry_run=dry_run,
            kullanici_id=kullanici_id,
            kullanici_ad=kullanici_ad,
            cari_har_id=cari_har_id,
            belge_no=belge_no,
            posting_idempotency_key=posting_idempotency_key if not dry_run else None,
            olay=olay,
            aciklama='CARI_ENTEGRASYON_AKTIF=False — dry-run' if dry_run else None,
        )
