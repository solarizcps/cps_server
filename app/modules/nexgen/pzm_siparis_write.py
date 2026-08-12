# -*- coding: utf-8 -*-
"""
Pazarlama Merkezi BE-2 — Çok kalemli taslak kaydetme (V2 payload)
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from modules.nexgen.cekirdek_gorunum import cekirdek_formul_mu
from modules.nexgen.mo_gorusme_config import VADE_GUN_MAX

PZM_V2_JSON_PREFIX = '__PZM_V2__'
PZM_AILELER = frozenset({'TERLIK', 'TABAN', 'DOKME'})
# Cari kart / Pazarlama / Finans ortak whitelist (CNY satınalmada var — bu fazda eklenmez)
PZM_PARA_BIRIMLERI = frozenset({'TRY', 'USD', 'EUR', 'GBP'})
PZM_ODEME_TIPLERI = frozenset({'NAKIT', 'VADELI', 'CEK'})
PZM_TESLIM_SEKILLERI = frozenset({'FABRIKA_TESLIM', 'MUSTERIYE_SEVK'})
PZM_SIPARIS_ONCELIKLERI = frozenset({'NORMAL', 'ACIL', 'YUKSEK'})
PZM_KDV_DURUMLARI = frozenset({'RESMI', 'GAYRI_RESMI', 'GAYRI'})
PZM_ODEME_NOTU_MAX = 500
PZM_BIRIM_FIYAT_MAX = Decimal('999999.9999')
PZM_KUR_MAX = Decimal('999999.9999')
PZM_KUR_KAYNAKLARI = frozenset({'SISTEM', 'MANUEL'})

def pzm_finans_kolonlari_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return (
        'anlasma_para_birimi' in cols
        and 'vade_gun' in cols
        and 'anlasma_birim_fiyat' in cols
    )


def pzm_odeme_tipi_kolonu_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return 'odeme_tipi' in cols


def pzm_odeme_notu_kolonu_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return 'odeme_notu' in cols


def pzm_cek_vadesi_kolonu_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return 'cek_vadesi' in cols


def pzm_teslim_sekli_kolonu_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return 'teslim_sekli' in cols


def pzm_teslim_sekli_normalize(raw: Any) -> str | None:
    v = (raw or '').strip().upper() if raw not in (None, '') else ''
    if v in PZM_TESLIM_SEKILLERI:
        return v
    return None


def pzm_siparis_onceligi_normalize(raw: Any) -> str | None:
    v = (raw or '').strip().upper() if raw not in (None, '') else ''
    if v in PZM_SIPARIS_ONCELIKLERI:
        return v
    return None


def pzm_kdv_durumu_normalize(raw: Any) -> str | None:
    v = (raw or '').strip().upper() if raw not in (None, '') else ''
    if v == 'GAYRI':
        v = 'GAYRI_RESMI'
    if v in PZM_KDV_DURUMLARI:
        return 'GAYRI_RESMI' if v == 'GAYRI' else v
    return None


def pzm_baslik_operasyon_alanlari_dogrula(
    data: dict,
    *,
    zorunlu: bool = False,
) -> dict[str, Any]:
    """Başlık teslim / öncelik / KDV / istenen termin — operasyon kaydında zorunlu olabilir."""
    teslim = pzm_teslim_sekli_normalize(data.get('teslim_sekli'))
    if zorunlu and not teslim:
        raise PzmWriteError('Teslim şekli zorunludur.')
    oncelik = pzm_siparis_onceligi_normalize(
        data.get('siparis_onceligi') or data.get('oncelik'),
    )
    if zorunlu and not oncelik:
        raise PzmWriteError('Sipariş önceliği zorunludur.')
    kdv = pzm_kdv_durumu_normalize(data.get('kdv_durumu'))
    if zorunlu and not kdv:
        raise PzmWriteError('KDV durumu zorunludur.')
    istenen = (data.get('istenen_termin') or data.get('genel_termin_tarihi') or '')
    istenen = str(istenen).strip()[:10] or None
    if zorunlu and not istenen:
        raise PzmWriteError('Talep edilen termin zorunludur.')
    return {
        'teslim_sekli': teslim,
        'siparis_onceligi': oncelik,
        'kdv_durumu': kdv,
        'istenen_termin': istenen,
    }


def pzm_kalem_fiyat_kolonlari_var(con) -> bool:
    cols = {c[1] for c in con.execute(
        "PRAGMA table_info(nexgen_planlama_siparis_kalem)"
    ).fetchall()}
    return (
        'birim_fiyat' in cols
        and 'iskonto_orani' in cols
        and 'net_birim_fiyat' in cols
        and 'satir_tutari' in cols
    )


def pzm_kur_kolonlari_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return 'kur' in cols and 'kur_tarihi' in cols and 'kur_kaynagi' in cols


def pzm_kalem_try_kolonlari_var(con) -> bool:
    cols = {c[1] for c in con.execute(
        "PRAGMA table_info(nexgen_planlama_siparis_kalem)"
    ).fetchall()}
    return 'net_birim_fiyat_try' in cols and 'satir_tutari_try' in cols


def pzm_mtt_kalem_id_kolonu_var(con) -> bool:
    cols = {c[1] for c in con.execute(
        "PRAGMA table_info(nexgen_planlama_siparis_kalem)"
    ).fetchall()}
    return 'mtt_kalem_id' in cols


def pzm_mtt_kalem_pointer_dogrula(
    con,
    kalemler: list[dict],
    kaynak_mtt_talep_id: Any,
    *,
    guncelleme_siparis_id: int | None = None,
) -> None:
    """MTT dönüşümünde kalem pointer kuralları (migration 149)."""
    mtt_id = None
    if kaynak_mtt_talep_id not in (None, '', 0, '0'):
        try:
            mtt_id = int(kaynak_mtt_talep_id)
        except (TypeError, ValueError):
            mtt_id = None
    is_mtt = mtt_id is not None and mtt_id > 0

    if not is_mtt:
        for i, k in enumerate(kalemler, start=1):
            if k.get('mtt_kalem_id') not in (None, '', 0, '0'):
                raise PzmWriteError(
                    f'Kalem {i}: MTT olmayan siparişte mtt_kalem_id kullanılamaz.',
                )
        return

    if not pzm_mtt_kalem_id_kolonu_var(con):
        raise PzmWriteError(
            'MTT kalem pointer kolonu yok — migration 149 gerekli.', 500,
        )

    seen: set[int] = set()
    for i, k in enumerate(kalemler, start=1):
        raw = k.get('mtt_kalem_id')
        if raw in (None, '', 0, '0'):
            raise PzmWriteError(f'Kalem {i}: MTT dönüşümünde mtt_kalem_id zorunlu.')
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            raise PzmWriteError(f'Kalem {i}: mtt_kalem_id geçersiz.')
        if mid <= 0:
            raise PzmWriteError(f'Kalem {i}: mtt_kalem_id geçersiz.')
        if mid in seen:
            raise PzmWriteError(f'Kalem {i}: aynı mtt_kalem_id tekrar kullanılamaz.')
        seen.add(mid)

        row = con.execute(
            'SELECT id, talep_id FROM nexgen_musteri_temsilcisi_talep_kalem WHERE id=?',
            (mid,),
        ).fetchone()
        if not row:
            raise PzmWriteError(f'Kalem {i}: MTT kalem bulunamadı.')
        if int(row['talep_id']) != int(mtt_id):
            raise PzmWriteError(
                f'Kalem {i}: mtt_kalem_id bu MTT talebine ait değil.', 403,
            )

        dup_sql = (
            'SELECT id, planlama_siparis_id FROM nexgen_planlama_siparis_kalem '
            "WHERE mtt_kalem_id=? AND COALESCE(durum,'AKTIF')='AKTIF'"
        )
        dup_params: list[Any] = [mid]
        if guncelleme_siparis_id:
            dup_sql += ' AND planlama_siparis_id != ?'
            dup_params.append(int(guncelleme_siparis_id))
        existing = con.execute(dup_sql, tuple(dup_params)).fetchone()
        if existing:
            raise PzmWriteError(
                f'Kalem {i}: MTT kalem zaten siparişe dönüştürülmüş.', 409,
            )


def pzm_ticari_miktar_kg(miktar_l, miktar_s, miktar_m) -> Decimal:
    """Kesin ticari miktar: L+S+M kg toplamı (üretim/MRP ile aynı)."""
    total = (
        Decimal(str(miktar_l or 0))
        + Decimal(str(miktar_s or 0))
        + Decimal(str(miktar_m or 0))
    )
    return total.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


def _dec_para(d: Decimal) -> str:
    return format(d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP), 'f')


def pzm_kur_deger_dogrula(raw) -> Decimal:
    """Kur > 0 Decimal. Boş/geçersiz → PzmWriteError."""
    if raw in (None, ''):
        raise PzmWriteError('Dövizli siparişte kur zorunludur.')
    s = str(raw).strip().replace(' ', '').replace(',', '.')
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        raise PzmWriteError('Kur geçerli bir sayı olmalıdır.')
    if not d.is_finite() or d <= 0:
        raise PzmWriteError('Kur sıfırdan büyük olmalıdır.')
    if d > PZM_KUR_MAX:
        raise PzmWriteError('Kur geçerli bir sayı olmalıdır.')
    return d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


def pzm_sistem_kur_oku(con, para_birimi: str, tarih: str | None) -> tuple[Decimal | None, str | None]:
    """
    Mevcut sistem standardı: sistem_kur.MerkezKur
    Harici internet servisi yok.
    Dönüş: (kur, kur_tarihi) veya (None, None)
    """
    pb = (para_birimi or '').upper()
    if pb == 'TRY':
        return Decimal('1'), (tarih or '')[:10] or None
    tab = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sistem_kur'"
    ).fetchone()
    if not tab:
        return None, None
    t = (tarih or '')[:10] or None
    if t:
        row = con.execute(
            """
            SELECT MerkezKur, Tarih FROM sistem_kur
            WHERE ParaBirimi=? AND Tarih=?
            ORDER BY Id DESC LIMIT 1
            """,
            (pb, t),
        ).fetchone()
        if row and row['MerkezKur'] not in (None, ''):
            try:
                return Decimal(str(row['MerkezKur'])), row['Tarih']
            except (InvalidOperation, ValueError):
                pass
        row = con.execute(
            """
            SELECT MerkezKur, Tarih FROM sistem_kur
            WHERE ParaBirimi=? AND Tarih<?
            ORDER BY Tarih DESC, Id DESC LIMIT 1
            """,
            (pb, t),
        ).fetchone()
        if row and row['MerkezKur'] not in (None, ''):
            try:
                return Decimal(str(row['MerkezKur'])), row['Tarih']
            except (InvalidOperation, ValueError):
                pass
    row = con.execute(
        """
        SELECT MerkezKur, Tarih FROM sistem_kur
        WHERE ParaBirimi=?
        ORDER BY Tarih DESC, Id DESC LIMIT 1
        """,
        (pb,),
    ).fetchone()
    if row and row['MerkezKur'] not in (None, ''):
        try:
            return Decimal(str(row['MerkezKur'])), row['Tarih']
        except (InvalidOperation, ValueError):
            return None, None
    return None, None


def pzm_kur_snapshot_hazirla(
    con,
    data: dict,
    para_birimi: str | None,
    *,
    kur_zorunlu: bool = False,
) -> dict[str, Any]:
    """
    TRY → kur=1, kaynak=SISTEM.
    USD/EUR/GBP → kullanıcı kuru veya sistem_kur; gönderde zorunlu.
    Frontend TRY karşılıklarına güvenilmez.
    """
    from datetime import datetime

    pb = pzm_para_birimi_normalize(para_birimi)
    snap_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sip_tarih = (data.get('siparis_tarihi') or '')[:10] or snap_ts[:10]

    if not pb:
        return {'kur': None, 'kur_tarihi': None, 'kur_kaynagi': None}

    if pb == 'TRY':
        return {
            'kur': '1.0000',
            'kur_tarihi': snap_ts,
            'kur_kaynagi': 'SISTEM',
        }

    raw_kur = data.get('kur')
    if raw_kur not in (None, ''):
        kd = pzm_kur_deger_dogrula(raw_kur)
        kt = (data.get('kur_tarihi') or '').strip() or snap_ts
        kaynak = (data.get('kur_kaynagi') or 'MANUEL').strip().upper()
        if kaynak not in PZM_KUR_KAYNAKLARI:
            kaynak = 'MANUEL'
        return {
            'kur': _dec_para(kd),
            'kur_tarihi': kt,
            'kur_kaynagi': kaynak,
        }

    sist, sist_tarih = pzm_sistem_kur_oku(con, pb, sip_tarih)
    if sist is not None and sist > 0:
        return {
            'kur': _dec_para(sist.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
            'kur_tarihi': sist_tarih or snap_ts,
            'kur_kaynagi': 'SISTEM',
        }

    if kur_zorunlu:
        raise PzmWriteError('Dövizli siparişte kur zorunludur.')
    return {'kur': None, 'kur_tarihi': None, 'kur_kaynagi': None}


def pzm_kalem_try_uygula(kalem: dict, kur_raw) -> dict:
    """net/satır × kur → TRY alanları. Frontend değerleri yok sayılır."""
    if kur_raw in (None, '') or kalem.get('net_birim_fiyat') in (None, ''):
        kalem['net_birim_fiyat_try'] = None
        kalem['satir_tutari_try'] = None
        return kalem
    try:
        kur = Decimal(str(kur_raw))
        net = Decimal(str(kalem['net_birim_fiyat']))
        satir = Decimal(str(kalem['satir_tutari'])) if kalem.get('satir_tutari') not in (None, '') else None
    except (InvalidOperation, ValueError, TypeError):
        kalem['net_birim_fiyat_try'] = None
        kalem['satir_tutari_try'] = None
        return kalem
    if kur <= 0:
        kalem['net_birim_fiyat_try'] = None
        kalem['satir_tutari_try'] = None
        return kalem
    kalem['net_birim_fiyat_try'] = _dec_para(net * kur)
    kalem['satir_tutari_try'] = _dec_para(satir * kur) if satir is not None else None
    return kalem


def pzm_kalem_ticari_hesapla(
    birim_fiyat_raw,
    iskonto_orani_raw,
    miktar_l,
    miktar_s,
    miktar_m,
    *,
    sira: int = 1,
    fiyat_zorunlu: bool = False,
) -> dict[str, Any]:
    """
    Backend yeniden hesaplar — frontend net/satır tutarına güvenilmez.
    Taslakta fiyat boş → snapshot alanları None.
    """
    etiket = f'{sira}. kalem'

    if birim_fiyat_raw in (None, ''):
        if fiyat_zorunlu:
            raise PzmWriteError(f'{etiket} için birim fiyat zorunludur.')
        # iskonto tek başına gelirse yine kontrol
        if iskonto_orani_raw not in (None, ''):
            try:
                io = Decimal(str(iskonto_orani_raw).strip().replace(',', '.'))
            except (InvalidOperation, ValueError):
                raise PzmWriteError('İskonto oranı 0 ile 100 arasında olmalıdır.')
            if io < 0 or io > 100:
                raise PzmWriteError('İskonto oranı 0 ile 100 arasında olmalıdır.')
        return {
            'birim_fiyat': None,
            'iskonto_orani': None,
            'iskonto_tutari': None,
            'net_birim_fiyat': None,
            'satir_tutari': None,
            'ticari_miktar_kg': float(pzm_ticari_miktar_kg(miktar_l, miktar_s, miktar_m)),
        }

    try:
        bf = Decimal(str(birim_fiyat_raw).strip().replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError, AttributeError):
        raise PzmWriteError(f'{etiket} birim fiyatı geçerli bir sayı olmalıdır.')
    if not bf.is_finite() or bf <= 0:
        raise PzmWriteError(f'{etiket} birim fiyatı sıfırdan büyük olmalıdır.')
    if bf > PZM_BIRIM_FIYAT_MAX:
        raise PzmWriteError(f'{etiket} birim fiyatı geçerli bir sayı olmalıdır.')

    if iskonto_orani_raw in (None, ''):
        io = Decimal('0')
    else:
        try:
            io = Decimal(str(iskonto_orani_raw).strip().replace(',', '.'))
        except (InvalidOperation, ValueError):
            raise PzmWriteError('İskonto oranı 0 ile 100 arasında olmalıdır.')
    if not io.is_finite() or io < 0 or io > 100:
        raise PzmWriteError('İskonto oranı 0 ile 100 arasında olmalıdır.')

    iskonto_tutari = (bf * io / Decimal('100')).quantize(
        Decimal('0.0001'), rounding=ROUND_HALF_UP,
    )
    net = (bf - iskonto_tutari).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    miktar = pzm_ticari_miktar_kg(miktar_l, miktar_s, miktar_m)
    if miktar <= 0:
        raise PzmWriteError(
            f'Satır tutarı hesaplanamadı; sipariş miktarını kontrol edin. ({etiket})'
        )
    satir = (miktar * net).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

    return {
        'birim_fiyat': _dec_para(bf),
        'iskonto_orani': format(io.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f'),
        'iskonto_tutari': _dec_para(iskonto_tutari),
        'net_birim_fiyat': _dec_para(net),
        'satir_tutari': _dec_para(satir),
        'ticari_miktar_kg': float(miktar),
    }


def pzm_para_birimi_normalize(raw) -> str:
    s = (raw or '').strip().upper()
    if s == 'TL':
        s = 'TRY'
    return s


def pzm_odeme_tipi_normalize(raw) -> str | None:
    if raw in (None, ''):
        return None
    s = str(raw).strip().upper()
    # Türkçe İ/ı normalize
    s = s.replace('\u0130', 'I').replace('\u0131', 'I')
    if s == 'NAKIT':
        return 'NAKIT'
    if s == 'VADELI':
        return 'VADELI'
    if s in ('CEK', 'ÇEK'):
        return 'CEK'
    return s or None


def pzm_odeme_notu_normalize(raw) -> str | None:
    if raw in (None, ''):
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) > PZM_ODEME_NOTU_MAX:
        raise PzmWriteError(f'Ödeme notu en fazla {PZM_ODEME_NOTU_MAX} karakter olabilir.')
    return s


def pzm_vade_gun_dogrula(raw, *, odeme_tipi: str | None = None, zorunlu: bool = True) -> int | None:
    """
    Ödeme vadesi (teslim termininden ayrı).
    NAKIT → her zaman 0 (pozitif gelirse 0'a normalize).
    VADELI → >= 1 zorunlu.
    """
    tip = pzm_odeme_tipi_normalize(odeme_tipi) if odeme_tipi is not None else None

    if tip == 'NAKIT':
        if raw in (None, ''):
            return 0
        try:
            v = int(str(raw).strip())
        except (TypeError, ValueError):
            raise PzmWriteError('Nakit siparişlerde vade günü 0 olmalıdır.')
        if v < 0:
            raise PzmWriteError('Nakit siparişlerde vade günü 0 olmalıdır.')
        # Manipülasyon: pozitif vade sessizce 0'a çekilir (kaydetme yok)
        return 0

    if tip == 'VADELI':
        if raw in (None, ''):
            raise PzmWriteError('Vadeli siparişlerde vade günü en az 1 olmalıdır.')
        if isinstance(raw, str):
            s = raw.strip()
            if not s.isdigit():
                raise PzmWriteError('Vadeli siparişlerde vade günü en az 1 olmalıdır.')
            raw = s
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise PzmWriteError('Vadeli siparişlerde vade günü en az 1 olmalıdır.')
        if v < 1:
            raise PzmWriteError('Vadeli siparişlerde vade günü en az 1 olmalıdır.')
        return v

    if tip == 'CEK':
        # CEK: canonical vade_gun = cek_vade_gun alanından normalize edilir.
        # Bu fonksiyon ham vade_gun alanını işler; CEK'te vade_gun payload'da
        # boş gelir (kullanıcı cek_vade_gun girer). pzm_ticari_sartlar_dogrula
        # CEK için vade_gun'u cek_vade_gun'dan besleyerek çağırır.
        # Burada raw doğrudan cek_vade_gun değeri olarak geçer.
        if raw in (None, ''):
            return None  # zorunlu kontrolü pzm_cek_vade_gun_dogrula'da
        if isinstance(raw, str):
            s = raw.strip()
            if not s.isdigit():
                return None
            raw = s
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return None
        return v if v >= 1 else None

    # odeme_tipi yok (eski / taslak yumuşak)
    if raw in (None, ''):
        if zorunlu:
            raise PzmWriteError('Vade günü zorunludur.')
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s.isdigit():
            raise PzmWriteError('Vade günü 0 veya daha büyük tam sayı olmalıdır.')
        raw = s
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise PzmWriteError('Vade günü 0 veya daha büyük tam sayı olmalıdır.')
    if v < 0:
        raise PzmWriteError('Vade günü 0 veya daha büyük tam sayı olmalıdır.')
    return v


def pzm_cek_vade_gun_dogrula(
    raw, *, odeme_tipi: str | None = None, zorunlu: bool = True,
) -> int | None:
    """Çek vade gününü başlık snapshot'ı için pozitif tam sayı olarak doğrula."""
    tip = pzm_odeme_tipi_normalize(odeme_tipi) if odeme_tipi is not None else None
    if tip != 'CEK':
        return None
    if raw in (None, ''):
        if zorunlu:
            raise PzmWriteError('Çek ödeme tipinde çek vadesi gün sayısı zorunludur.')
        return None
    if isinstance(raw, bool):
        raise PzmWriteError('Çek vadesi gün sayısı pozitif tam sayı olmalıdır.')
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw.isdigit():
            raise PzmWriteError('Çek vadesi gün sayısı pozitif tam sayı olmalıdır.')
    elif not isinstance(raw, int):
        raise PzmWriteError('Çek vadesi gün sayısı pozitif tam sayı olmalıdır.')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise PzmWriteError('Çek vadesi gün sayısı pozitif tam sayı olmalıdır.')
    if value < 1 or value > VADE_GUN_MAX:
        raise PzmWriteError(
            f'Çek vadesi gün sayısı 1-{VADE_GUN_MAX} arasında olmalıdır.'
        )
    return value


def pzm_ticari_sartlar_dogrula(
    data: dict,
    *,
    zorunlu: bool = True,
) -> dict[str, Any]:
    """Başlık ticari şartları — odeme_tipi / vade / PB / odeme_notu."""
    tip = pzm_odeme_tipi_normalize(data.get('odeme_tipi'))
    if zorunlu and not tip:
        raise PzmWriteError('Ödeme tipi seçimi zorunludur.')
    if tip and tip not in PZM_ODEME_TIPLERI:
        raise PzmWriteError('Ödeme tipi NAKIT, VADELI veya CEK olmalıdır.')

    pb = pzm_para_birimi_normalize(data.get('anlasma_para_birimi') or data.get('para_birimi'))
    if zorunlu or pb:
        if pb not in PZM_PARA_BIRIMLERI:
            raise PzmWriteError('Anlaşma para birimi zorunludur.')
    else:
        pb = None

    vade_zorunlu = zorunlu or bool(tip)
    odeme_notu = pzm_odeme_notu_normalize(data.get('odeme_notu'))
    cek_vadesi = None
    cek_vade_gun = None
    if tip == 'CEK':
        cek_vade_gun = pzm_cek_vade_gun_dogrula(
            data.get('cek_vade_gun'), odeme_tipi=tip, zorunlu=zorunlu,
        )
        raw_cv = (data.get('cek_vadesi') or '').strip()[:10] if data.get('cek_vadesi') not in (None, '') else ''
        if zorunlu and not raw_cv:
            raise PzmWriteError('Çek vadesi zorunludur.')
        cek_vadesi = raw_cv or None
        # CEK: canonical vade_gun = cek_vade_gun (tahsilat motoru tek kaynaktan okur)
        vade_gun = pzm_vade_gun_dogrula(
            cek_vade_gun, odeme_tipi=tip, zorunlu=False,
        )
    else:
        vade_gun = pzm_vade_gun_dogrula(
            data.get('vade_gun'), odeme_tipi=tip, zorunlu=vade_zorunlu,
        )
    return {
        'odeme_tipi': tip,
        'vade_gun': vade_gun,
        'anlasma_para_birimi': pb,
        'odeme_notu': odeme_notu,
        'cek_vadesi': cek_vadesi,
        'cek_vade_gun': cek_vade_gun,
    }


def pzm_cari_dogrula(con, cari_id_raw, uid: int | None = None) -> dict[str, Any]:
    """nexgen_cari.id — varlık + aktif + (gerekirse) kapsam yetkisi."""
    try:
        cari_id = int(cari_id_raw)
    except (TypeError, ValueError):
        raise PzmWriteError('Cari seçimi zorunludur.', 400)
    if cari_id <= 0:
        raise PzmWriteError('Cari seçimi zorunludur.', 400)

    cari = con.execute(
        "SELECT id, unvan, aktif FROM nexgen_cari WHERE id=?",
        (cari_id,),
    ).fetchone()
    if not cari:
        raise PzmWriteError('Seçilen cari bulunamadı.', 404)
    if not cari['aktif']:
        raise PzmWriteError('Seçilen cari bulunamadı.', 404)

    if uid:
        try:
            from modules.nexgen.cari_sorumlu_service import (
                load_kullanici_yetkileri,
                _kullanici_cari_atanmis,
            )
            from modules.nexgen.cari360_yetki import (
                can_cari360_view_all,
                can_cari360_crm_write,
                can_siparis_onaya_gonder,
                _yk_has,
            )
            yk = load_kullanici_yetkileri(con, int(uid))
            if can_cari360_view_all(yk) or '*' in (yk or set()):
                # Yönetim / view_all — tüm carilere erişim
                pass
            elif can_siparis_onaya_gonder(yk):
                # Planlama / sipariş operasyonu capability.
                # nexgen.plan.manage:can_manage yetkisi aktif cari üzerinde
                # sipariş oluşturmak için yeterlidir; cari_sorumlu ataması şart değil.
                pass
            elif (
                _yk_has(yk, 'cari360.view_own', 'can_view')
                or can_cari360_crm_write(yk)
            ):
                # Müşteri temsilcisi / pazarlamacı: yalnız atanmış carilerde işlem.
                if not _kullanici_cari_atanmis(con, int(uid), cari_id):
                    raise PzmWriteError('Bu cari için işlem yetkiniz yok.', 403)
        except PzmWriteError:
            raise
        except Exception:
            pass
    return dict(cari)


def pzm_mtt_donusum_cari_dogrula(
    con, cari_id: int, uid: int | None, data: dict,
) -> dict[str, Any]:
    """
    Onaylı MTT dönüşüm yolunda cari scope bypass — dar koşullar.
    Normal Yeni Sipariş cari kuralları etkilenmez.
    """
    from modules.nexgen.mtt_donusum_service import talep_detay_getir

    mtt_raw = data.get('kaynak_mtt_talep_id')
    try:
        mtt_id = int(mtt_raw)
    except (TypeError, ValueError):
        raise PzmWriteError('MTT dönüşüm kaynağı geçersiz.', 400)
    if mtt_id <= 0:
        raise PzmWriteError('MTT dönüşüm kaynağı geçersiz.', 400)

    talep = talep_detay_getir(con, mtt_id, kullanici_id=uid)
    if not talep:
        raise PzmWriteError('MTT talep bulunamadı.', 404)

    onay = con.execute(
        "SELECT id, durum FROM nexgen_onay "
        "WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=?",
        (mtt_id,),
    ).fetchone()
    if not onay or (onay['durum'] or '').upper() != 'ONAYLANDI':
        raise PzmWriteError(
            'Yalnız yönetim onaylı MTT siparişe dönüştürülebilir.', 403,
        )

    try:
        mtt_cari_id = int(talep.get('cari_id') or 0)
    except (TypeError, ValueError):
        mtt_cari_id = 0
    if mtt_cari_id <= 0:
        raise PzmWriteError('MTT cari_id geçersiz.', 400)
    if int(cari_id) != mtt_cari_id:
        raise PzmWriteError(
            'Sipariş cari_id onaylı MTT cari ile eşleşmeli.', 403,
        )

    mtt_durum = (talep.get('durum') or '').upper()
    donus_sip = talep.get('donusturulen_siparis_id')
    raw_ps = data.get('talep_id')
    if mtt_durum == 'SIPARISE_DONUSTU' and donus_sip:
        if raw_ps not in (None, '', 0, '0'):
            try:
                if int(raw_ps) != int(donus_sip):
                    raise PzmWriteError('Talep zaten başka siparişe dönüştürülmüş.', 409)
            except PzmWriteError:
                raise
            except (TypeError, ValueError):
                raise PzmWriteError('Talep zaten siparişe dönüştürülmüş.', 409)
        else:
            raise PzmWriteError('Talep zaten siparişe dönüştürülmüş.', 409)
    elif mtt_durum != 'ISLEME_ALINDI':
        raise PzmWriteError(
            f'Yalnız ISLEME_ALINDI talepler siparişe dönüştürülebilir (şu an: {mtt_durum}).',
            409,
        )

    cari = con.execute(
        "SELECT id, unvan, aktif FROM nexgen_cari WHERE id=?",
        (cari_id,),
    ).fetchone()
    if not cari:
        raise PzmWriteError('Seçilen cari bulunamadı.', 404)
    if not cari['aktif']:
        raise PzmWriteError('Seçilen cari bulunamadı.', 404)
    return dict(cari)


def pzm_ticari_kilitli_mi(con, siparis_id: int) -> tuple[bool, str | None]:
    """
    Minimum ticari kilit:
    - durum üretim/sevk sonrası
    - veya gerçek plan/batch/sevkiyat kaydı varsa
    TASLAK/REVIZYON/REDDEDILDI ve henüz üretim yoksa kilit yok.
    """
    row = con.execute(
        'SELECT id, durum FROM nexgen_planlama_siparis WHERE id=?',
        (siparis_id,),
    ).fetchone()
    if not row:
        return True, 'Sipariş bulunamadı.'
    durum = (row['durum'] or '').upper()
    if durum in ('URETIMDE', 'SEVK_BEKLIYOR', 'KISMI_SEVK', 'SEVK_EDILDI', 'TAMAMLANDI'):
        return True, f'Sipariş ticari olarak kilitli ({durum}).'

    plan_var = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_uretim_plan'"
    ).fetchone()
    if plan_var:
        if con.execute(
            'SELECT 1 FROM nexgen_uretim_plan WHERE planlama_siparis_id=? LIMIT 1',
            (siparis_id,),
        ).fetchone():
            # plan var ama batch yoksa hâlâ kilit: üretim başlamış sayılır
            batch_tab = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_uretim_batch'"
            ).fetchone()
            if batch_tab:
                if con.execute(
                    """
                    SELECT 1 FROM nexgen_uretim_batch b
                    JOIN nexgen_uretim_plan p ON p.id = b.plan_id
                    WHERE p.planlama_siparis_id=? LIMIT 1
                    """,
                    (siparis_id,),
                ).fetchone():
                    return True, 'Üretim batch oluşmuş siparişte ticari şartlar değiştirilemez.'

    sevk_tab = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mo_musteri_sevkiyat'"
    ).fetchone()
    if sevk_tab:
        if con.execute(
            'SELECT 1 FROM mo_musteri_sevkiyat WHERE siparis_id=? AND aktif=1 LIMIT 1',
            (siparis_id,),
        ).fetchone():
            return True, 'Sevkiyat başlamış siparişte ticari şartlar değiştirilemez.'

    if durum not in ('TASLAK', 'REVIZYON', 'REDDEDILDI', 'ONAY_BEKLIYOR', 'ONAYLANDI', 'MPR_BEKLIYOR'):
        # bilinmeyen ileri durum — güvenli tarafta kilitle
        if durum and durum not in ('IPTAL',):
            pass
    return False, None


def pzm_operasyon_eksikleri(con, siparis_id: int) -> list[str]:
    """
    MRP / Üretime Gönder / kesin işlem öncesi eksik alan listesi.
    Kullanıcıya genel hata yerine açık mesajlar döner.
    """
    eksik: list[str] = []
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    select_cols = ['id', 'cari_id', 'anlasma_para_birimi', 'vade_gun']
    if 'odeme_tipi' in cols:
        select_cols.append('odeme_tipi')
    if 'cek_vadesi' in cols:
        select_cols.append('cek_vadesi')
    if 'kur' in cols:
        select_cols.append('kur')
    if 'teslim_sekli' in cols:
        select_cols.append('teslim_sekli')
    row = con.execute(
        f"SELECT {', '.join(select_cols)} FROM nexgen_planlama_siparis WHERE id=?",
        (siparis_id,),
    ).fetchone()
    if not row:
        return ['Sipariş bulunamadı.']
    if row['cari_id'] in (None, ''):
        eksik.append('Cari seçimi zorunludur.')

    tip = None
    if 'odeme_tipi' in row.keys():
        tip = pzm_odeme_tipi_normalize(row['odeme_tipi'])
    if not tip:
        eksik.append('Ödeme tipi seçilmemiş.')
    else:
        pb = pzm_para_birimi_normalize(row['anlasma_para_birimi'])
        if pb not in PZM_PARA_BIRIMLERI:
            eksik.append('Para birimi seçilmemiş.')
        if tip == 'VADELI':
            try:
                vg = int(row['vade_gun']) if row['vade_gun'] not in (None, '') else None
            except (TypeError, ValueError):
                vg = None
            if vg is None or vg < 1:
                eksik.append('Vadeli siparişte vade günü zorunludur.')
        elif tip == 'CEK':
            cv = row['cek_vadesi'] if 'cek_vadesi' in row.keys() else None
            if not cv:
                eksik.append('Çek ödeme tipinde çek vadesi zorunludur.')

    if 'teslim_sekli' in row.keys():
        ts = pzm_teslim_sekli_normalize(row['teslim_sekli'])
        if not ts:
            eksik.append('Teslim şekli zorunludur.')

    fiyat_var = pzm_kalem_fiyat_kolonlari_var(con)
    fiyat_sel = 'birim_fiyat' if fiyat_var else 'NULL AS birim_fiyat'
    kalemler = con.execute(
        f"""
        SELECT sira_no, {fiyat_sel}, termin_tarihi, formul_id, rf_renk_id,
               miktar_l, miktar_s, miktar_m
        FROM nexgen_planlama_siparis_kalem
        WHERE planlama_siparis_id=? AND IFNULL(durum,'AKTIF')='AKTIF'
        ORDER BY sira_no
        """,
        (siparis_id,),
    ).fetchall()
    if not kalemler:
        eksik.append('En az bir sipariş kalemi zorunlu.')
        return eksik

    for k in kalemler:
        sira = k['sira_no']
        if k['formul_id'] in (None, ''):
            eksik.append(f'{sira}. kalemin formülü eksik.')
        if k['rf_renk_id'] in (None, ''):
            eksik.append(f'{sira}. kalemin teknik rengi eksik.')
        ml = float(k['miktar_l'] or 0)
        ms = float(k['miktar_s'] or 0)
        mm = float(k['miktar_m'] or 0)
        if (ml + ms + mm) <= 0:
            eksik.append(f'{sira}. kalemin miktarı eksik.')
        if not k['termin_tarihi']:
            eksik.append(f'{sira}. kalemin termini eksik.')
        if fiyat_var and k['birim_fiyat'] in (None, ''):
            eksik.append(f'{sira}. kalemin birim fiyatı eksik.')
    return eksik


def pzm_gonder_ticari_hazir_mi(con, siparis_id: int) -> None:
    """Gönder / onaya-gonder / MRP öncesi zorunlu ticari + fiyat + termin."""
    eksikler = pzm_operasyon_eksikleri(con, siparis_id)
    if eksikler:
        raise PzmWriteError(eksikler[0], 400)
    # TRY kur snapshot tutarlılığı (operasyon listesinde ayrıntı yok)
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    if 'kur' not in cols:
        return
    row = con.execute(
        'SELECT anlasma_para_birimi, kur FROM nexgen_planlama_siparis WHERE id=?',
        (siparis_id,),
    ).fetchone()
    if not row:
        return
    pb = pzm_para_birimi_normalize(row['anlasma_para_birimi'])
    if pb == 'TRY':
        if row['kur'] in (None, ''):
            raise PzmWriteError('TRY siparişte kur snapshot eksik (1 olmalı).', 400)
        try:
            if Decimal(str(row['kur'])) != Decimal('1'):
                raise PzmWriteError('TRY siparişte kur 1 olmalıdır.', 400)
        except (InvalidOperation, ValueError):
            raise PzmWriteError('TRY siparişte kur 1 olmalıdır.', 400)


def pzm_birim_fiyat_dogrula(raw) -> str:
    """Decimal string döner — en fazla 4 ondalık, örn. 2.3500."""
    if raw in (None, ''):
        raise PzmWriteError('Anlaşma birim fiyatı zorunludur.')
    s = str(raw).strip().replace(' ', '')
    if not s:
        raise PzmWriteError('Anlaşma birim fiyatı zorunludur.')
    if s.count(',') > 1 or s.count('.') > 1:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    if ',' in s and '.' in s:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    s = s.replace(',', '.')
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    if not d.is_finite():
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    if d <= 0:
        raise PzmWriteError('Anlaşma birim fiyatı sıfırdan büyük olmalıdır.')
    if d > PZM_BIRIM_FIYAT_MAX:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    return format(d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP), 'f')


class PzmWriteError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def pzm_is_v2_payload(data: dict) -> bool:
    return isinstance(data.get('kalemler'), list)


def pzm_v2_header_pack(meta: dict) -> str:
    return PZM_V2_JSON_PREFIX + json.dumps(meta, ensure_ascii=False, separators=(',', ':'))


def _float_miktar(val, alan: str) -> float:
    if val in (None, ''):
        return 0.0
    try:
        v = round(float(val), 3)
    except (TypeError, ValueError):
        raise PzmWriteError(f'{alan} geçersiz.')
    if v < 0:
        raise PzmWriteError('Miktar negatif olamaz.')
    return v


def _kalem_anahtar(k: dict) -> tuple:
    rf = k.get('rf_renk_id') or k.get('renk_varyant_id')
    return (
        int(k['formul_id']),
        int(rf),
        float(k.get('miktar_l') or 0),
        float(k.get('miktar_s') or 0),
        float(k.get('miktar_m') or 0),
    )


def pzm_v2_kalem_dogrula(
    con,
    kalem_raw: dict,
    sira: int,
    cari_id: int | None = None,
    *,
    fiyat_zorunlu: bool = False,
    termin_zorunlu: bool = True,
) -> dict[str, Any]:
    """Tek kalem doğrulama — taslak: renk kartı yeterli, RF uygunluk MRP'de."""
    from modules.nexgen.routes import (
        _pzm_termin_dogrula,
        _renk_varyant_uv_haritasi,
        _pzm_kalem_renk_coz,
        _pzm_formul_boyutlari,
        _pzm_renk_etiketi,
        _pzm_rf_cari_uygun,
    )
    from modules.nexgen.cekirdek_gorunum import yeni_secimde_renk_gosterilebilir_mi

    urun_ailesi = (kalem_raw.get('urun_ailesi') or '').strip().upper()
    if urun_ailesi not in PZM_AILELER:
        raise PzmWriteError(f'Kalem {sira}: geçersiz ürün ailesi.')

    try:
        formul_id = int(kalem_raw.get('formul_id'))
    except (TypeError, ValueError):
        raise PzmWriteError(f'Kalem {sira}: formül zorunlu.')

    rf_renk_id = kalem_raw.get('rf_renk_id')
    if rf_renk_id in (None, ''):
        rf_renk_id = kalem_raw.get('renk_varyant_id')
    try:
        rf_renk_id = int(rf_renk_id)
    except (TypeError, ValueError):
        raise PzmWriteError(f'Kalem {sira}: renk seçimi zorunlu.')

    f = con.execute(
        "SELECT id, ad, kod, urun_ailesi FROM nexgen_formul "
        "WHERE id=? AND aktif=1 AND durum IN ('AKTIF','URETIME_ACIK')",
        (formul_id,),
    ).fetchone()
    if not f or not cekirdek_formul_mu(f['kod']):
        raise PzmWriteError(f'Kalem {sira}: formül geçersiz veya legacy.')

    rf_row = con.execute("""
        SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id, kaynak_arge_test_id
        FROM nexgen_rf_renk WHERE id=? AND aktif=1
    """, (rf_renk_id,)).fetchone()
    if not rf_row or not yeni_secimde_renk_gosterilebilir_mi(dict(rf_row)):
        raise PzmWriteError(f'Kalem {sira}: renk kartı geçersiz veya pasif.')
    if not _pzm_rf_cari_uygun(dict(rf_row), cari_id):
        raise PzmWriteError(f'Kalem {sira}: renk bu cari için uygun değil.')

    renk_satir, _ = _pzm_kalem_renk_coz(
        con, formul_id, rf_renk_id, cari_id, rf_renk_id=rf_renk_id,
    )
    if not renk_satir:
        raise PzmWriteError(f'Kalem {sira}: renk seçimi formül ile uyumlu değil.')

    ml = _float_miktar(kalem_raw.get('miktar_l'), 'LARGE')
    ms = _float_miktar(kalem_raw.get('miktar_s'), 'SMALL')
    mm = _float_miktar(kalem_raw.get('miktar_m'), 'MEDIUM')

    if urun_ailesi == 'DOKME':
        if ml > 0 or ms > 0:
            raise PzmWriteError(f'Kalem {sira}: DÖKME yalnız MEDIUM kabul eder.')
        if mm <= 0:
            raise PzmWriteError(f'Kalem {sira}: DÖKME için MEDIUM miktar zorunlu.')
    else:
        if mm > 0:
            raise PzmWriteError(f'Kalem {sira}: TERLİK/TABAN için MEDIUM kullanılamaz.')
        if ml <= 0 and ms <= 0:
            raise PzmWriteError(f'Kalem {sira}: en az bir LARGE veya SMALL miktar girin.')

    raw_termin = kalem_raw.get('termin_tarihi')
    if raw_termin in (None, ''):
        if termin_zorunlu:
            raise PzmWriteError(f'{sira}. kalemin termini eksik.')
        termin = None
    else:
        ok, t_hata, termin = _pzm_termin_dogrula(raw_termin)
        if not ok:
            raise PzmWriteError(f'Kalem {sira}: {t_hata}')

    boyutlar = _pzm_formul_boyutlari(con, formul_id)
    boyut_rv = {b['boyut']: int(b['rv_id']) for b in boyutlar}
    if ml > 0:
        rv_l = boyut_rv.get('LARGE')
        if not rv_l or not _renk_varyant_uv_haritasi(con, rv_l).get('LARGE'):
            raise PzmWriteError(f'Kalem {sira}: LARGE boyutu üretime açık değil.')
    if ms > 0:
        rv_s = boyut_rv.get('SMALL')
        if not rv_s or not _renk_varyant_uv_haritasi(con, rv_s).get('SMALL'):
            raise PzmWriteError(f'Kalem {sira}: SMALL boyutu üretime açık değil.')
    if mm > 0:
        rv_m = boyut_rv.get('MEDIUM')
        if not rv_m or not _renk_varyant_uv_haritasi(con, rv_m).get('STANDART'):
            raise PzmWriteError(f'Kalem {sira}: MEDIUM boyutu üretime açık değil.')

    if ml > 0 and boyut_rv.get('LARGE'):
        renk_varyant_id = boyut_rv['LARGE']
    elif ms > 0 and boyut_rv.get('SMALL'):
        renk_varyant_id = boyut_rv['SMALL']
    elif mm > 0 and boyut_rv.get('MEDIUM'):
        renk_varyant_id = boyut_rv['MEDIUM']
    else:
        renk_varyant_id = next(iter(boyut_rv.values()), None)

    notlar = (kalem_raw.get('notlar') or '').strip() or None
    renk_ad = _pzm_renk_etiketi(rf_row['rf_kod'], rf_row['ad'])

    # Opsiyonel kaynak numune — gerçek FK; tahmini eşleştirme yok
    numune_talep_id = None
    raw_nt = kalem_raw.get('numune_talep_id')
    if raw_nt not in (None, '', 0, '0'):
        try:
            numune_talep_id = int(raw_nt)
        except (TypeError, ValueError):
            raise PzmWriteError(f'Kalem {sira}: numune_talep_id geçersiz.')
        nt = con.execute(
            'SELECT id, cari_id, aktif, durum FROM nexgen_numune_talep WHERE id=?',
            (numune_talep_id,),
        ).fetchone()
        if not nt or not int(nt['aktif'] or 0):
            raise PzmWriteError(f'Kalem {sira}: numune talebi bulunamadı.')
        if nt['cari_id'] is None or int(nt['cari_id']) != int(cari_id or 0):
            raise PzmWriteError(f'Kalem {sira}: numune bu cariye ait değil.', 403)

    mtt_kalem_id = None
    raw_mtt = kalem_raw.get('mtt_kalem_id')
    if raw_mtt not in (None, '', 0, '0'):
        try:
            mtt_kalem_id = int(raw_mtt)
        except (TypeError, ValueError):
            raise PzmWriteError(f'Kalem {sira}: mtt_kalem_id geçersiz.')
        if mtt_kalem_id <= 0:
            raise PzmWriteError(f'Kalem {sira}: mtt_kalem_id geçersiz.')

    ticari = pzm_kalem_ticari_hesapla(
        kalem_raw.get('birim_fiyat'),
        kalem_raw.get('iskonto_orani'),
        ml, ms, mm,
        sira=sira,
        fiyat_zorunlu=fiyat_zorunlu,
    )

    return {
        'sira_no': int(kalem_raw.get('sira_no') or sira),
        'urun_ailesi': urun_ailesi,
        'formul_id': formul_id,
        'formul_ad': (f['ad'] or f['kod'] or '').strip(),
        'renk_varyant_id': renk_varyant_id,
        'renk_ad': renk_ad,
        'rf_renk_id': rf_renk_id,
        'miktar_l': ml,
        'miktar_s': ms,
        'miktar_m': mm,
        'termin_tarihi': termin,
        'notlar': notlar,
        'numune_talep_id': numune_talep_id,
        'mtt_kalem_id': mtt_kalem_id,
        'birim_fiyat': ticari['birim_fiyat'],
        'iskonto_orani': ticari['iskonto_orani'],
        'iskonto_tutari': ticari['iskonto_tutari'],
        'net_birim_fiyat': ticari['net_birim_fiyat'],
        'satir_tutari': ticari['satir_tutari'],
        'ticari_miktar_kg': ticari['ticari_miktar_kg'],
    }


def _pzm_tek_kalem_header_fiyat_sync(kalemler_raw: list, data: dict) -> None:
    """Tek kalem: header anlasma_birim_fiyat → kalem birim_fiyat (çok kalemde kör kopya yok)."""
    if len(kalemler_raw) != 1:
        return
    kr = kalemler_raw[0]
    if not isinstance(kr, dict):
        return
    if kr.get('birim_fiyat') not in (None, ''):
        return
    hdr_bf = data.get('anlasma_birim_fiyat') or data.get('birim_fiyat')
    if hdr_bf in (None, ''):
        return
    kr['birim_fiyat'] = hdr_bf


def pzm_v2_payload_dogrula(
    con,
    data: dict,
    cari_id: int,
    *,
    uid: int | None = None,
    ticari_zorunlu: bool = True,
) -> dict[str, Any]:
    """V2 payload tam doğrulama."""
    from modules.nexgen.routes import _pzm_termin_dogrula

    mtt_raw = data.get('kaynak_mtt_talep_id')
    if mtt_raw not in (None, '', 0, '0'):
        cari = pzm_mtt_donusum_cari_dogrula(con, cari_id, uid, data)
    else:
        cari = pzm_cari_dogrula(con, cari_id, uid=uid)

    kalemler_raw = data.get('kalemler')
    if not isinstance(kalemler_raw, list) or len(kalemler_raw) < 1:
        raise PzmWriteError('En az bir sipariş kalemi zorunlu.')

    siparis_tarihi = (data.get('siparis_tarihi') or '').strip()[:10] or None
    genel_not = (data.get('genel_not') or data.get('notlar') or '').strip() or None

    # Genel termin UI yok — dolu kalem terminlerinden türetilir (taslakta boş olabilir)
    termler = []
    for kr0 in kalemler_raw:
        if not isinstance(kr0, dict):
            continue
        tt = (kr0.get('termin_tarihi') or '')
        tt = str(tt).strip()[:10]
        if tt:
            termler.append(tt)
    genel_termin = None
    if termler:
        genel_termin = min(termler)
        ok, t_hata, genel_termin = _pzm_termin_dogrula(genel_termin)
        if not ok:
            raise PzmWriteError(t_hata or 'Kalem termini geçersiz.')
    elif ticari_zorunlu:
        raise PzmWriteError('En az bir kalem termini zorunludur.')

    # Taslak: ticari alanlar boş kalabilir. Gönder: ticari_zorunlu=True.
    tip_raw = pzm_odeme_tipi_normalize(data.get('odeme_tipi'))
    if ticari_zorunlu or tip_raw:
        ticari = pzm_ticari_sartlar_dogrula(
            data,
            zorunlu=bool(ticari_zorunlu or tip_raw),
        )
    else:
        # UX V2: ilk oluşturmada ticari şartlar sonra tamamlanır
        pb_raw = pzm_para_birimi_normalize(
            data.get('anlasma_para_birimi') or data.get('para_birimi')
        )
        ticari = {
            'odeme_tipi': None,
            'vade_gun': None,
            'anlasma_para_birimi': pb_raw if pb_raw in PZM_PARA_BIRIMLERI else None,
            'odeme_notu': pzm_odeme_notu_normalize(data.get('odeme_notu')),
            'cek_vadesi': None,
            'cek_vade_gun': None,
        }

    op_alan = pzm_baslik_operasyon_alanlari_dogrula(
        data,
        zorunlu=bool(ticari_zorunlu),
    )

    kalem_fiyat_var = pzm_kalem_fiyat_kolonlari_var(con)
    # Gönder: kalem fiyat zorunlu. Taslak: boş olabilir.
    fiyat_zorunlu = bool(ticari_zorunlu and kalem_fiyat_var)
    termin_zorunlu = bool(ticari_zorunlu)

    _pzm_tek_kalem_header_fiyat_sync(kalemler_raw, data)

    kalemler = []
    seen = set()
    for i, kr in enumerate(kalemler_raw, start=1):
        k = pzm_v2_kalem_dogrula(
            con, kr, i, cari_id,
            fiyat_zorunlu=fiyat_zorunlu,
            termin_zorunlu=termin_zorunlu,
        )
        anahtar = (
            k['formul_id'],
            k['rf_renk_id'],
            k['miktar_l'],
            k['miktar_s'],
            k['miktar_m'],
        )
        if anahtar in seen:
            raise PzmWriteError(f'Kalem {i}: aynı ürün/renk/miktar zaten listede.')
        seen.add(anahtar)
        k['sira_no'] = i
        kalemler.append(k)

    guncelleme_id = None
    raw_ps = data.get('talep_id')
    if raw_ps not in (None, '', 0, '0'):
        try:
            guncelleme_id = int(raw_ps)
        except (TypeError, ValueError):
            guncelleme_id = None
    pzm_mtt_kalem_pointer_dogrula(
        con,
        kalemler,
        data.get('kaynak_mtt_talep_id'),
        guncelleme_siparis_id=guncelleme_id,
    )

    # Başlık anlasma_birim_fiyat yalnız tek kalem senkron kolonu (kaynak = kalem)
    if kalem_fiyat_var:
        if len(kalemler) == 1 and kalemler[0].get('birim_fiyat'):
            birim_fiyat = kalemler[0]['birim_fiyat']
        else:
            birim_fiyat = None
        if ticari_zorunlu and any(not k.get('birim_fiyat') for k in kalemler):
            raise PzmWriteError('Tüm aktif kalemlerde birim fiyat zorunludur.')
    else:
        # Legacy şema (kalem fiyat kolonu yok) — tek istisna
        birim_fiyat = pzm_birim_fiyat_dogrula(
            data.get('anlasma_birim_fiyat') or data.get('birim_fiyat')
        )

    # T3 kur snapshot + kalem TRY karşılıkları (backend yeniden hesaplar)
    kur_snap = {'kur': None, 'kur_tarihi': None, 'kur_kaynagi': None}
    if pzm_kur_kolonlari_var(con):
        kur_snap = pzm_kur_snapshot_hazirla(
            con, data, ticari['anlasma_para_birimi'],
            kur_zorunlu=False,
        )
        if pzm_kalem_try_kolonlari_var(con):
            for k in kalemler:
                pzm_kalem_try_uygula(k, kur_snap.get('kur'))

    header_termin = genel_termin

    return {
        'cari': cari,
        'siparis_tarihi': siparis_tarihi,
        'genel_termin': header_termin,
        'genel_not': genel_not,
        'anlasma_para_birimi': ticari['anlasma_para_birimi'],
        'vade_gun': ticari['vade_gun'],
        'anlasma_birim_fiyat': birim_fiyat,
        'odeme_tipi': ticari['odeme_tipi'],
        'odeme_notu': ticari['odeme_notu'],
        'cek_vadesi': ticari.get('cek_vadesi'),
        'cek_vade_gun': ticari.get('cek_vade_gun'),
        'teslim_sekli': op_alan.get('teslim_sekli'),
        'siparis_onceligi': op_alan.get('siparis_onceligi'),
        'kdv_durumu': op_alan.get('kdv_durumu'),
        'istenen_termin': op_alan.get('istenen_termin'),
        'kur': kur_snap.get('kur'),
        'kur_tarihi': kur_snap.get('kur_tarihi'),
        'kur_kaynagi': kur_snap.get('kur_kaynagi'),
        'kalemler': kalemler,
    }


def pzm_v2_taslak_kaydet(
    con, data: dict, uid: int | None, *, commit: bool = True,
) -> dict[str, Any]:
    """Header + kalemler tek transaction. commit=False → dış TX (MTT dönüşüm)."""
    from modules.nexgen.pzm_siparis_read import pzm_kalem_tablosu_var
    from modules.nexgen.routes import _pzm_siparis_no_uret

    if not pzm_kalem_tablosu_var(con):
        raise PzmWriteError('Sipariş kalem tablosu yok.', 400)

    try:
        cari_id = int(data.get('cari_id'))
    except (TypeError, ValueError):
        raise PzmWriteError('Cari seçimi zorunludur.', 400)

    # Taslak: odeme_tipi zorunlu değil; operasyon/MRP yolunda ticari zorunlu
    operasyon = bool(data.get('operasyon'))
    hazir = pzm_v2_payload_dogrula(
        con, data, cari_id, uid=uid, ticari_zorunlu=operasyon,
    )
    cari = hazir['cari']
    kalemler = hazir['kalemler']
    toplam_kg = round(sum(k['miktar_l'] + k['miktar_s'] + k['miktar_m'] for k in kalemler), 3)

    meta = {
        'v': 2,
        'siparis_tarihi': hazir['siparis_tarihi'],
        'genel_termin_tarihi': hazir['genel_termin'],
        'anlasma_para_birimi': hazir['anlasma_para_birimi'],
        'vade_gun': hazir['vade_gun'],
        'anlasma_birim_fiyat': hazir['anlasma_birim_fiyat'],
        'odeme_tipi': hazir.get('odeme_tipi'),
        'odeme_notu': hazir.get('odeme_notu'),
        'cek_vadesi': hazir.get('cek_vadesi'),
        'cek_vade_gun': hazir.get('cek_vade_gun'),
        'teslim_sekli': hazir.get('teslim_sekli'),
        'siparis_onceligi': hazir.get('siparis_onceligi'),
        'kdv_durumu': hazir.get('kdv_durumu'),
        'istenen_termin': hazir.get('istenen_termin'),
        'kalem_sayisi': len(kalemler),
    }
    mtt_id = data.get('kaynak_mtt_talep_id')
    if mtt_id not in (None, '', 0, '0'):
        try:
            meta['kaynak_mtt_talep_id'] = int(mtt_id)
        except (TypeError, ValueError):
            pass
    talep_ref = pzm_v2_header_pack(meta)
    finans_kolon = pzm_finans_kolonlari_var(con)
    odeme_tipi_kolon = pzm_odeme_tipi_kolonu_var(con)
    odeme_notu_kolon = pzm_odeme_notu_kolonu_var(con)
    cek_kolon = pzm_cek_vadesi_kolonu_var(con)

    ps_id = data.get('talep_id')
    guncellendi = False
    own_tx = False

    try:
        if commit:
            try:
                con.execute('BEGIN IMMEDIATE')
                own_tx = True
            except Exception:
                pass

        if ps_id:
            try:
                ps_id = int(ps_id)
            except (TypeError, ValueError):
                raise PzmWriteError('talep_id geçersiz.')
            row = con.execute(
                "SELECT id, durum, talep_referansi, cari_id, anlasma_para_birimi, "
                "vade_gun FROM nexgen_planlama_siparis WHERE id=?",
                (ps_id,),
            ).fetchone()
            if not row:
                raise PzmWriteError('Talep bulunamadı.', 404)
            if row['durum'] not in ('TASLAK',):
                raise PzmWriteError('Yalnız taslak siparişler güncellenebilir.')
            kilitli, kilit_msg = pzm_ticari_kilitli_mi(con, ps_id)
            if kilitli:
                raise PzmWriteError(kilit_msg or 'Ticari şartlar kilitli.', 400)
            ref = str(row['talep_referansi'] or '')
            if not ref.startswith(PZM_V2_JSON_PREFIX) and not ref.startswith('__PZM_V1__'):
                raise PzmWriteError('Bu sipariş çok kalemli güncelleme için uygun değil.')

            set_parts = [
                "cari_id=?", "cari_unvan=?", "termin_tarihi=?", "notlar=?",
                "talep_referansi=?", "durum='TASLAK'",
                "guncelleme_tarihi=datetime('now','localtime')",
            ]
            params: list[Any] = [
                cari['id'], cari['unvan'], hazir['genel_termin'], hazir['genel_not'], talep_ref,
            ]
            if finans_kolon:
                set_parts.extend([
                    'anlasma_para_birimi=?', 'vade_gun=?', 'anlasma_birim_fiyat=?',
                ])
                params.extend([
                    hazir['anlasma_para_birimi'], hazir['vade_gun'], hazir['anlasma_birim_fiyat'],
                ])
            if odeme_tipi_kolon:
                set_parts.append('odeme_tipi=?')
                params.append(hazir.get('odeme_tipi'))
            if odeme_notu_kolon:
                set_parts.append('odeme_notu=?')
                params.append(hazir.get('odeme_notu'))
            if cek_kolon:
                set_parts.append('cek_vadesi=?')
                params.append(hazir.get('cek_vadesi'))
            if pzm_teslim_sekli_kolonu_var(con):
                set_parts.append('teslim_sekli=?')
                params.append(hazir.get('teslim_sekli'))
            if pzm_kur_kolonlari_var(con):
                set_parts.extend(['kur=?', 'kur_tarihi=?', 'kur_kaynagi=?'])
                params.extend([hazir.get('kur'), hazir.get('kur_tarihi'), hazir.get('kur_kaynagi')])
            params.append(ps_id)
            con.execute(
                f"UPDATE nexgen_planlama_siparis SET {', '.join(set_parts)} WHERE id=?",
                tuple(params),
            )
            con.execute(
                'DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?',
                (ps_id,),
            )
            guncellendi = True
            siparis_no = con.execute(
                'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?', (ps_id,)
            ).fetchone()['siparis_no']
        else:
            siparis_no = _pzm_siparis_no_uret(con)
            cols = [
                'siparis_no', 'cari_id', 'cari_unvan', 'termin_tarihi', 'talep_referansi',
                'durum', 'notlar', 'olusturan_id',
            ]
            vals: list[Any] = [
                siparis_no, cari['id'], cari['unvan'], hazir['genel_termin'],
                talep_ref, 'TASLAK', hazir['genel_not'], uid,
            ]
            if finans_kolon:
                cols.extend(['anlasma_para_birimi', 'vade_gun', 'anlasma_birim_fiyat'])
                vals.extend([
                    hazir['anlasma_para_birimi'], hazir['vade_gun'], hazir['anlasma_birim_fiyat'],
                ])
            if odeme_tipi_kolon:
                cols.append('odeme_tipi')
                vals.append(hazir.get('odeme_tipi'))
            if odeme_notu_kolon:
                cols.append('odeme_notu')
                vals.append(hazir.get('odeme_notu'))
            if cek_kolon:
                cols.append('cek_vadesi')
                vals.append(hazir.get('cek_vadesi'))
            if pzm_teslim_sekli_kolonu_var(con):
                cols.append('teslim_sekli')
                vals.append(hazir.get('teslim_sekli'))
            if pzm_kur_kolonlari_var(con):
                cols.extend(['kur', 'kur_tarihi', 'kur_kaynagi'])
                vals.extend([hazir.get('kur'), hazir.get('kur_tarihi'), hazir.get('kur_kaynagi')])
            ph = ', '.join(['?'] * len(vals))
            cur = con.execute(
                f"INSERT INTO nexgen_planlama_siparis ({', '.join(cols)}) VALUES ({ph})",
                tuple(vals),
            )
            ps_id = cur.lastrowid

        kalem_cols = {c[1] for c in con.execute(
            "PRAGMA table_info(nexgen_planlama_siparis_kalem)"
        ).fetchall()}
        has_numune_col = 'numune_talep_id' in kalem_cols
        has_mtt_col = 'mtt_kalem_id' in kalem_cols
        has_fiyat_col = (
            'birim_fiyat' in kalem_cols and 'iskonto_orani' in kalem_cols
            and 'net_birim_fiyat' in kalem_cols and 'satir_tutari' in kalem_cols
        )
        has_try_col = (
            'net_birim_fiyat_try' in kalem_cols and 'satir_tutari_try' in kalem_cols
        )
        for k in kalemler:
            cols_k = [
                'planlama_siparis_id', 'sira_no', 'urun_ailesi', 'formul_id', 'formul_ad',
                'renk_varyant_id', 'renk_ad', 'rf_renk_id',
                'miktar_l', 'miktar_s', 'miktar_m', 'termin_tarihi', 'notlar',
            ]
            vals_k: list[Any] = [
                ps_id, k['sira_no'], k['urun_ailesi'], k['formul_id'], k['formul_ad'],
                k['renk_varyant_id'], k['renk_ad'], k['rf_renk_id'],
                k['miktar_l'], k['miktar_s'], k['miktar_m'],
                k['termin_tarihi'], k['notlar'],
            ]
            if has_numune_col:
                cols_k.append('numune_talep_id')
                vals_k.append(k.get('numune_talep_id'))
            if has_mtt_col:
                cols_k.append('mtt_kalem_id')
                vals_k.append(k.get('mtt_kalem_id'))
            if has_fiyat_col:
                cols_k.extend([
                    'birim_fiyat', 'iskonto_orani', 'iskonto_tutari',
                    'net_birim_fiyat', 'satir_tutari',
                ])
                vals_k.extend([
                    k.get('birim_fiyat'),
                    k.get('iskonto_orani') if k.get('birim_fiyat') is not None else None,
                    k.get('iskonto_tutari'),
                    k.get('net_birim_fiyat'),
                    k.get('satir_tutari'),
                ])
            if has_try_col:
                cols_k.extend(['net_birim_fiyat_try', 'satir_tutari_try'])
                vals_k.extend([k.get('net_birim_fiyat_try'), k.get('satir_tutari_try')])
            cols_k.extend(['durum', 'legacy_kaynak'])
            vals_k.extend(['AKTIF', 0])
            ph = ', '.join(['?'] * len(vals_k))
            con.execute(
                f"INSERT INTO nexgen_planlama_siparis_kalem ({', '.join(cols_k)}) "
                f"VALUES ({ph})",
                tuple(vals_k),
            )

        # MTT / görüşme kaynak bağları (kolon varsa)
        ps_cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
        if 'mo_gorusme_id' in ps_cols and data.get('mo_gorusme_id'):
            try:
                con.execute(
                    'UPDATE nexgen_planlama_siparis SET mo_gorusme_id=? WHERE id=?',
                    (int(data['mo_gorusme_id']), ps_id),
                )
            except Exception:
                pass
        if 'kaynak_modul' in ps_cols and data.get('kaynak_modul'):
            try:
                con.execute(
                    'UPDATE nexgen_planlama_siparis SET kaynak_modul=? WHERE id=?',
                    (str(data['kaynak_modul'])[:80], ps_id),
                )
            except Exception:
                pass

        if own_tx:
            con.commit()
    except PzmWriteError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception as e:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise PzmWriteError(str(e), 500) from e

    return {
        'ok': True,
        'talep_id': ps_id,
        'siparis_no': siparis_no,
        'durum': 'TASLAK',
        'kalem_sayisi': len(kalemler),
        'toplam_kg': toplam_kg,
        'guncellendi': guncellendi,
        'anlasma_para_birimi': hazir['anlasma_para_birimi'],
        'vade_gun': hazir['vade_gun'],
        'anlasma_birim_fiyat': hazir['anlasma_birim_fiyat'],
        'odeme_tipi': hazir.get('odeme_tipi'),
        'odeme_notu': hazir.get('odeme_notu'),
        'kur': hazir.get('kur'),
        'kur_tarihi': hazir.get('kur_tarihi'),
        'kur_kaynagi': hazir.get('kur_kaynagi'),
        'genel_termin_tarihi': hazir['genel_termin'],
    }
