# -*- coding: utf-8 -*-
"""
Pazarlama Merkezi BE-2 — Çok kalemli taslak kaydetme (V2 payload)
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from modules.nexgen.cekirdek_gorunum import cekirdek_formul_mu

PZM_V2_JSON_PREFIX = '__PZM_V2__'
PZM_AILELER = frozenset({'TERLIK', 'TABAN', 'DOKME'})
# Cari kart / Pazarlama / Finans ortak whitelist (CNY satınalmada var — bu fazda eklenmez)
PZM_PARA_BIRIMLERI = frozenset({'TRY', 'USD', 'EUR', 'GBP'})
PZM_ODEME_TIPLERI = frozenset({'NAKIT', 'VADELI'})
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


def pzm_odeme_kolonlari_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return 'odeme_tipi' in cols and 'odeme_notu' in cols


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
        raise PzmWriteError('Ödeme tipi NAKIT veya VADELI olmalıdır.')

    pb = pzm_para_birimi_normalize(data.get('anlasma_para_birimi') or data.get('para_birimi'))
    if zorunlu or pb:
        if pb not in PZM_PARA_BIRIMLERI:
            raise PzmWriteError('Anlaşma para birimi zorunludur.')
    else:
        pb = None

    vade_zorunlu = zorunlu or bool(tip)
    vade_gun = pzm_vade_gun_dogrula(
        data.get('vade_gun'), odeme_tipi=tip, zorunlu=vade_zorunlu,
    )
    odeme_notu = pzm_odeme_notu_normalize(data.get('odeme_notu'))
    return {
        'odeme_tipi': tip,
        'vade_gun': vade_gun,
        'anlasma_para_birimi': pb,
        'odeme_notu': odeme_notu,
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
                can_create_order,
                load_kullanici_yetkileri,
                _kullanici_cari_atanmis,
            )
            from modules.nexgen.cari360_yetki import (
                can_cari360_view_all,
                can_cari360_crm_write,
                _yk_has,
            )
            yk = load_kullanici_yetkileri(con, int(uid))
            if can_cari360_view_all(yk) or '*' in (yk or set()):
                pass
            elif (
                _yk_has(yk, 'cari360.view_own', 'can_view')
                or can_cari360_crm_write(yk)
            ):
                if not can_create_order(con, int(uid), cari_id, yk) and not _kullanici_cari_atanmis(
                    con, int(uid), cari_id
                ):
                    raise PzmWriteError('Bu cari için işlem yetkiniz yok.', 403)
        except PzmWriteError:
            raise
        except Exception:
            pass
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


def pzm_gonder_ticari_hazir_mi(con, siparis_id: int) -> None:
    """Gönder / onaya-gonder öncesi zorunlu ticari + cari kontrolü."""
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    select_cols = ['id', 'cari_id', 'durum', 'anlasma_para_birimi', 'vade_gun', 'anlasma_birim_fiyat']
    if 'odeme_tipi' in cols:
        select_cols.append('odeme_tipi')
    if 'odeme_notu' in cols:
        select_cols.append('odeme_notu')
    if 'kur' in cols:
        select_cols.extend(['kur', 'kur_tarihi', 'kur_kaynagi'])
    row = con.execute(
        f"SELECT {', '.join(select_cols)} FROM nexgen_planlama_siparis WHERE id=?",
        (siparis_id,),
    ).fetchone()
    if not row:
        raise PzmWriteError('Sipariş bulunamadı.', 404)
    if row['cari_id'] in (None, ''):
        raise PzmWriteError('Cari seçimi zorunludur.', 400)
    pzm_cari_dogrula(con, row['cari_id'], uid=None)

    tip = row['odeme_tipi'] if 'odeme_tipi' in row.keys() else None
    if not tip:
        raise PzmWriteError('Ödeme tipi seçimi zorunludur.', 400)
    tip = pzm_odeme_tipi_normalize(tip)
    if tip not in PZM_ODEME_TIPLERI:
        raise PzmWriteError('Ödeme tipi seçimi zorunludur.', 400)

    pb = pzm_para_birimi_normalize(row['anlasma_para_birimi'])
    if pb not in PZM_PARA_BIRIMLERI:
        raise PzmWriteError('Anlaşma para birimi zorunludur.', 400)

    pzm_vade_gun_dogrula(row['vade_gun'], odeme_tipi=tip, zorunlu=True)

    # T3: kur snapshot — TRY=1; dövizde >0 zorunlu
    if 'kur' in cols:
        if pb == 'TRY':
            if row['kur'] in (None, ''):
                raise PzmWriteError('TRY siparişte kur snapshot eksik (1 olmalı).', 400)
            try:
                if Decimal(str(row['kur'])) != Decimal('1'):
                    raise PzmWriteError('TRY siparişte kur 1 olmalıdır.', 400)
            except (InvalidOperation, ValueError):
                raise PzmWriteError('TRY siparişte kur 1 olmalıdır.', 400)
        else:
            if row['kur'] in (None, ''):
                raise PzmWriteError('Dövizli siparişte kur zorunludur.', 400)
            pzm_kur_deger_dogrula(row['kur'])

    # T2: kalem fiyat snapshot zorunlu; yoksa başlık fallback (eski)
    if pzm_kalem_fiyat_kolonlari_var(con):
        kalemler = con.execute(
            """
            SELECT sira_no, birim_fiyat, durum
            FROM nexgen_planlama_siparis_kalem
            WHERE planlama_siparis_id=? AND IFNULL(durum,'AKTIF')='AKTIF'
            ORDER BY sira_no
            """,
            (siparis_id,),
        ).fetchall()
        if not kalemler:
            raise PzmWriteError('En az bir sipariş kalemi zorunlu.', 400)
        for k in kalemler:
            if k['birim_fiyat'] in (None, ''):
                raise PzmWriteError(
                    f"{k['sira_no']}. kalem için birim fiyat zorunludur.", 400,
                )
            try:
                bf = Decimal(str(k['birim_fiyat']))
            except (InvalidOperation, ValueError):
                raise PzmWriteError(
                    f"{k['sira_no']}. kalem birim fiyatı sıfırdan büyük olmalıdır.", 400,
                )
            if bf <= 0:
                raise PzmWriteError(
                    f"{k['sira_no']}. kalem birim fiyatı sıfırdan büyük olmalıdır.", 400,
                )
    elif row['anlasma_birim_fiyat'] in (None, ''):
        raise PzmWriteError('Anlaşma birim fiyatı zorunludur.', 400)


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

    ok, t_hata, termin = _pzm_termin_dogrula(kalem_raw.get('termin_tarihi'))
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
        'birim_fiyat': ticari['birim_fiyat'],
        'iskonto_orani': ticari['iskonto_orani'],
        'iskonto_tutari': ticari['iskonto_tutari'],
        'net_birim_fiyat': ticari['net_birim_fiyat'],
        'satir_tutari': ticari['satir_tutari'],
        'ticari_miktar_kg': ticari['ticari_miktar_kg'],
    }


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

    cari = pzm_cari_dogrula(con, cari_id, uid=uid)

    kalemler_raw = data.get('kalemler')
    if not isinstance(kalemler_raw, list) or len(kalemler_raw) < 1:
        raise PzmWriteError('En az bir sipariş kalemi zorunlu.')

    siparis_tarihi = (data.get('siparis_tarihi') or '').strip()[:10] or None
    genel_termin = data.get('genel_termin_tarihi')
    genel_not = (data.get('genel_not') or data.get('notlar') or '').strip() or None

    if not genel_termin or not str(genel_termin).strip():
        raise PzmWriteError('Genel termin tarihi zorunludur.')
    ok, t_hata, genel_termin = _pzm_termin_dogrula(genel_termin)
    if not ok:
        raise PzmWriteError(t_hata or 'Genel termin tarihi zorunludur.')

    # Taslak: odeme_tipi eksik kalabilir; seçildiyse kurallar uygulanır.
    # Gönder: ticari_zorunlu=True.
    tip_raw = pzm_odeme_tipi_normalize(data.get('odeme_tipi'))
    ticari = pzm_ticari_sartlar_dogrula(
        data,
        zorunlu=bool(ticari_zorunlu or tip_raw),
    )
    # Taslakta odeme_tipi yoksa PB+vade yine mevcut form akışı için istenir
    if not tip_raw and not ticari_zorunlu:
        pb = pzm_para_birimi_normalize(
            data.get('anlasma_para_birimi') or data.get('para_birimi')
        )
        if pb not in PZM_PARA_BIRIMLERI:
            raise PzmWriteError('Anlaşma para birimi zorunludur.')
        vade_gun = pzm_vade_gun_dogrula(data.get('vade_gun'), odeme_tipi=None, zorunlu=True)
        ticari = {
            'odeme_tipi': None,
            'vade_gun': vade_gun,
            'anlasma_para_birimi': pb,
            'odeme_notu': pzm_odeme_notu_normalize(data.get('odeme_notu')),
        }

    kalem_fiyat_var = pzm_kalem_fiyat_kolonlari_var(con)
    # Gönder: kalem fiyat zorunlu. Taslak: boş olabilir.
    fiyat_zorunlu = bool(ticari_zorunlu and kalem_fiyat_var)

    kalemler = []
    seen = set()
    for i, kr in enumerate(kalemler_raw, start=1):
        # Geçiş: tek kalemde başlık fiyatı kaleme düşürülebilir
        if kalem_fiyat_var and kr.get('birim_fiyat') in (None, '') and len(kalemler_raw) == 1:
            hdr_bf = data.get('anlasma_birim_fiyat') or data.get('birim_fiyat')
            if hdr_bf not in (None, ''):
                kr = dict(kr)
                kr['birim_fiyat'] = hdr_bf
        k = pzm_v2_kalem_dogrula(
            con, kr, i, cari_id, fiyat_zorunlu=fiyat_zorunlu,
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

    # Başlık anlasma_birim_fiyat geçiş:
    # - tek kalem: kalem fiyatına senkron
    # - çok kalem: ortalama yazılmaz; boş bırakılır (yanıltıcı olmasın)
    # - eski yol: kalem fiyat kolonu yoksa eski zorunlu başlık fiyatı
    if kalem_fiyat_var:
        if len(kalemler) == 1 and kalemler[0].get('birim_fiyat'):
            birim_fiyat = kalemler[0]['birim_fiyat']
        elif len(kalemler) > 1:
            birim_fiyat = None
        else:
            raw_bf = data.get('anlasma_birim_fiyat') or data.get('birim_fiyat')
            if raw_bf in (None, ''):
                birim_fiyat = None
            else:
                birim_fiyat = pzm_birim_fiyat_dogrula(raw_bf)
        if ticari_zorunlu and any(not k.get('birim_fiyat') for k in kalemler):
            raise PzmWriteError('Tüm aktif kalemlerde birim fiyat zorunludur.')
    else:
        birim_fiyat = pzm_birim_fiyat_dogrula(
            data.get('anlasma_birim_fiyat') or data.get('birim_fiyat')
        )

    # T3 kur snapshot + kalem TRY karşılıkları (backend yeniden hesaplar)
    kur_snap = {'kur': None, 'kur_tarihi': None, 'kur_kaynagi': None}
    if pzm_kur_kolonlari_var(con):
        kur_snap = pzm_kur_snapshot_hazirla(
            con, data, ticari['anlasma_para_birimi'],
            kur_zorunlu=bool(ticari_zorunlu),
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
        'kur': kur_snap.get('kur'),
        'kur_tarihi': kur_snap.get('kur_tarihi'),
        'kur_kaynagi': kur_snap.get('kur_kaynagi'),
        'kalemler': kalemler,
    }


def pzm_v2_taslak_kaydet(
    con, data: dict, uid: int | None, *, commit: bool = True,
) -> dict[str, Any]:
    """Header + kalemler tek transaction; commit=False uses an outer transaction."""
    from modules.nexgen.pzm_siparis_read import pzm_kalem_tablosu_var
    from modules.nexgen.routes import _pzm_siparis_no_uret

    if not pzm_kalem_tablosu_var(con):
        raise PzmWriteError('Sipariş kalem tablosu yok.', 400)

    try:
        cari_id = int(data.get('cari_id'))
    except (TypeError, ValueError):
        raise PzmWriteError('Cari seçimi zorunludur.', 400)

    # Taslak: odeme_tipi zorunlu değil; seçildiyse kurallar uygulanır
    hazir = pzm_v2_payload_dogrula(
        con, data, cari_id, uid=uid, ticari_zorunlu=False,
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
        'kalem_sayisi': len(kalemler),
    }
    talep_ref = pzm_v2_header_pack(meta)
    finans_kolon = pzm_finans_kolonlari_var(con)
    odeme_kolon = pzm_odeme_kolonlari_var(con)

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
            if odeme_kolon:
                set_parts.extend(['odeme_tipi=?', 'odeme_notu=?'])
                params.extend([hazir.get('odeme_tipi'), hazir.get('odeme_notu')])
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
            if odeme_kolon:
                cols.extend(['odeme_tipi', 'odeme_notu'])
                vals.extend([hazir.get('odeme_tipi'), hazir.get('odeme_notu')])
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
