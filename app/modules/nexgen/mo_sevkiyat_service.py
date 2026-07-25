# -*- coding: utf-8 -*-
"""Gerçek outbound müşteri sevkiyat servisi."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.cari_sorumlu_service import can_view_cari, load_kullanici_yetkileri
from modules.nexgen.mo_sevkiyat_config import (
    DURUM_ETIKET,
    DURUM_GECIS,
    DURUMLAR,
    KAYNAK_MODUL,
    OLAY_SEVK_CIKTI,
    OLAY_SEVK_HAZIR,
    OLAY_SEVK_TAMAMLANDI,
    OLAY_SEVK_TESLIM,
    YETKI_SEVKIYAT_VIEW,
    YETKI_SEVKIYAT_WRITE,
)
from modules.nexgen.mo_tahsilat_config import PLAN_DURUM_PLANLANDI
from modules.nexgen.mo_tahsilat_plan_service import hesapla_tahsilat_plani
from modules.nexgen.pzm_siparis_read import pzm_siparis_kalemleri_getir


class MoSevkiyatError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return date.today().isoformat()


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _yk_has(yk: set[str] | None, kod: str, action: str = 'can_view') -> bool:
    if not yk:
        return False
    if '*' in yk:
        return True
    return f'{kod}:{action}' in yk or kod in yk


def can_sevkiyat_yaz(yk: set[str] | None) -> bool:
    if not yk:
        return False
    if '*' in yk:
        return True
    return (
        _yk_has(yk, YETKI_SEVKIYAT_WRITE, 'can_create')
        or _yk_has(yk, YETKI_SEVKIYAT_WRITE, 'can_update')
        or _yk_has(yk, YETKI_SEVKIYAT_WRITE, 'can_manage')
        or _yk_has(yk, 'nexgen.plan.manage', 'can_manage')
    )


def can_sevkiyat_oku(
    con: sqlite3.Connection,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if can_sevkiyat_yaz(yk):
        return True
    if _yk_has(yk, YETKI_SEVKIYAT_VIEW, 'can_view'):
        return True
    return can_view_cari(con, kullanici_id, cari_id, yk)


def cari360_olay_sozlesmesi(olay_tipi: str, kayit: dict[str, Any]) -> dict[str, Any]:
    """Cari360 tüketimi için olay sözleşmesi — UI bu fazda yok."""
    return {
        'olay_tipi': olay_tipi,
        'kaynak_modul': KAYNAK_MODUL,
        'kaynak_id': kayit.get('id'),
        'cari_id': kayit.get('cari_id'),
        'siparis_id': kayit.get('siparis_id'),
        'sevkiyat_no': kayit.get('sevkiyat_no'),
        'sevk_tarihi': kayit.get('sevk_tarihi'),
        'teslim_tarihi': kayit.get('teslim_tarihi'),
        'durum': kayit.get('durum'),
        'olay_motoru_aktif': False,
    }


def _sevkiyat_no_uret(con) -> str:
    yil = datetime.now().year
    prefix = f'MSV-{yil}-'
    row = con.execute(
        "SELECT sevkiyat_no FROM mo_musteri_sevkiyat WHERE sevkiyat_no LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',),
    ).fetchone()
    son = 0
    if row and row['sevkiyat_no']:
        try:
            son = int(str(row['sevkiyat_no']).split('-')[-1])
        except ValueError:
            son = 0
    return f'{prefix}{son + 1:04d}'


def _siparis_guard(con, siparis_id: int) -> dict:
    row = con.execute(
        """
        SELECT id, cari_id, siparis_no, durum, kaynak_modul,
               musteri_termin, onerilen_termin, termin_tarihi
        FROM nexgen_planlama_siparis WHERE id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        raise MoSevkiyatError('Sipariş bulunamadı.', 404)
    d = dict(row)
    if (d.get('durum') or '').upper() in (
        'IPTAL', 'REDDEDILDI', 'TASLAK', 'ONAY_BEKLIYOR', 'REVIZYON',
    ):
        raise MoSevkiyatError('Bu sipariş durumunda sevkiyat açılamaz.', 409)
    return d


def _kalem_satir(con, sevkiyat_id: int) -> list[dict]:
    rows = con.execute(
        """
        SELECT id, sevkiyat_id, siparis_kalem_id, urun_adi, renk_ad, formul_ad,
               miktar_kg, miktar_adet, notlar
        FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?
        ORDER BY id
        """,
        (sevkiyat_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _detay(con, sevkiyat_id: int) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT s.*, ps.siparis_no, c.unvan AS cari_unvan, c.cari_kod
        FROM mo_musteri_sevkiyat s
        LEFT JOIN nexgen_planlama_siparis ps ON ps.id = s.siparis_id
        LEFT JOIN nexgen_cari c ON c.id = s.cari_id
        WHERE s.id=? AND s.aktif=1
        """,
        (sevkiyat_id,),
    ).fetchone()
    if not row:
        raise MoSevkiyatError('Sevkiyat bulunamadı.', 404)
    d = dict(row)
    d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
    d['kalemler'] = _kalem_satir(con, sevkiyat_id)
    d['toplam_kg'] = round(sum(float(k.get('miktar_kg') or 0) for k in d['kalemler']), 3)
    return d


def sevk_edilmis_kg(con, siparis_id: int, siparis_kalem_id: int | None = None) -> float:
    """Kısmi sevkiyat — daha önce sevk edilen toplam kg."""
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return 0.0
    if siparis_kalem_id:
        row = con.execute(
            """
            SELECT COALESCE(SUM(k.miktar_kg), 0) AS t
            FROM mo_musteri_sevkiyat_kalem k
            JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
            WHERE s.siparis_id=? AND s.aktif=1
              AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
              AND k.siparis_kalem_id=?
            """,
            (siparis_id, siparis_kalem_id),
        ).fetchone()
    else:
        row = con.execute(
            """
            SELECT COALESCE(SUM(k.miktar_kg), 0) AS t
            FROM mo_musteri_sevkiyat_kalem k
            JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
            WHERE s.siparis_id=? AND s.aktif=1
              AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
            """,
            (siparis_id,),
        ).fetchone()
    return float(row['t'] or 0) if row else 0.0


def kalan_miktarlar(con, siparis_id: int) -> list[dict[str, Any]]:
    """Sipariş kalemleri — kalan sevk edilebilir miktar."""
    kalemler = pzm_siparis_kalemleri_getir(con, siparis_id)
    out: list[dict] = []
    for k in kalemler:
        kid = k.get('id')
        siparis_kg = float(k.get('toplam_kg') or 0)
        sevk_kg = sevk_edilmis_kg(con, siparis_id, kid) if kid else sevk_edilmis_kg(con, siparis_id)
        kalan = round(max(siparis_kg - sevk_kg, 0), 3)
        out.append({
            'siparis_kalem_id': kid,
            'urun_ailesi': k.get('urun_ailesi'),
            'formul_ad': k.get('formul_ad'),
            'renk_ad': k.get('renk_ad'),
            'siparis_kg': siparis_kg,
            'sevk_edilen_kg': sevk_kg,
            'kalan_kg': kalan,
        })
    return out


def gercek_sevk_tarihi(con, siparis_id: int) -> str | None:
    """İlk gerçek sevk tarihi — tahsilat tek kaynak (MIN sevk_tarihi)."""
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return None
    row = con.execute(
        """
        SELECT sevk_tarihi FROM mo_musteri_sevkiyat
        WHERE siparis_id=? AND aktif=1 AND sevk_tarihi IS NOT NULL AND sevk_tarihi != ''
          AND durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        ORDER BY sevk_tarihi ASC, id ASC LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()
    return (row['sevk_tarihi'] or '')[:10] or None if row else None


def _uretilen_kg_siparis(con: sqlite3.Connection, planlama_siparis_id: int) -> float:
    """planlama_siparis_id için rf_kullanim toplamı (geçici sevk edilebilir üst sınır)."""
    if not _tablo_var(con, 'nexgen_rf_kullanim'):
        return 0.0
    cols = []
    if _tablo_var(con, 'nexgen_uretim_plan'):
        cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_uretim_plan)').fetchall()]
    if 'planlama_siparis_id' in cols:
        row = con.execute(
            """
            SELECT ROUND(COALESCE(SUM(k.miktar_kg), 0), 3) AS kg
            FROM nexgen_rf_kullanim k
            JOIN nexgen_uretim_plan np ON np.id = k.siparis_id
            WHERE k.aktif = 1 AND np.planlama_siparis_id = ?
            """,
            (planlama_siparis_id,),
        ).fetchone()
        if row and float(row['kg'] or 0) > 0:
            return float(row['kg'])
    row = con.execute(
        """
        SELECT ROUND(COALESCE(SUM(miktar_kg), 0), 3) AS kg
        FROM nexgen_rf_kullanim
        WHERE aktif = 1 AND siparis_id = ?
        """,
        (planlama_siparis_id,),
    ).fetchone()
    return float(row['kg'] or 0) if row else 0.0


def _kalem_tablosu_var(con) -> bool:
    return _tablo_var(con, 'nexgen_planlama_siparis_kalem')


def son_sevkiyat_ozet(con, cari_id: int) -> dict[str, Any] | None:
    """MO/Cari360 read-only tüketimi için son sevkiyat."""
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return None
    row = con.execute(
        """
        SELECT s.id, s.sevkiyat_no, s.sevk_tarihi, s.teslim_tarihi, s.durum,
               s.teslim_durumu, s.siparis_id, ps.siparis_no
        FROM mo_musteri_sevkiyat s
        LEFT JOIN nexgen_planlama_siparis ps ON ps.id = s.siparis_id
        WHERE s.cari_id=? AND s.aktif=1
          AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        ORDER BY COALESCE(s.sevk_tarihi, s.olusturma_tarihi) DESC, s.id DESC
        LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    kalemler = _kalem_satir(con, int(d['id']))
    d['toplam_kg'] = round(sum(float(k.get('miktar_kg') or 0) for k in kalemler), 3)
    d['kalem_ozet'] = [
        {
            'urun': k.get('urun_adi') or '—',
            'renk': k.get('renk_ad') or '—',
            'kg': k.get('miktar_kg'),
        }
        for k in kalemler[:5]
    ]
    d['teslim_edildi'] = (d.get('durum') or '') in ('TESLIM_EDILDI', 'TAMAMLANDI')
    d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
    return d


def termin_karsilastirma(con, siparis_id: int) -> dict[str, Any]:
    sip = _siparis_guard(con, siparis_id)
    sevk = gercek_sevk_tarihi(con, siparis_id)
    teslim_row = con.execute(
        """
        SELECT teslim_tarihi FROM mo_musteri_sevkiyat
        WHERE siparis_id=? AND aktif=1 AND teslim_tarihi IS NOT NULL AND teslim_tarihi != ''
        ORDER BY teslim_tarihi DESC LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()
    teslim = (teslim_row['teslim_tarihi'] or '')[:10] if teslim_row else None
    return {
        'siparis_id': siparis_id,
        'musteri_termin': (sip.get('musteri_termin') or '')[:10] or None,
        'verilen_termin': (sip.get('onerilen_termin') or sip.get('termin_tarihi') or '')[:10] or None,
        'gercek_sevk_tarihi': sevk,
        'gercek_teslim_tarihi': teslim,
    }


def _validate_kalemler(
    con,
    siparis_id: int,
    kalemler: list[dict],
    *,
    mevcut_sevkiyat_id: int | None = None,
) -> list[dict]:
    if not kalemler:
        raise MoSevkiyatError('En az bir sevk kalemi gerekli.', 400)
    kalan_list = kalan_miktarlar(con, siparis_id)
    kalan_map = {k['siparis_kalem_id']: k['kalan_kg'] for k in kalan_list}
    norm: list[dict] = []
    toplam_kg = 0.0
    for i, raw in enumerate(kalemler):
        try:
            kg = round(float(raw.get('miktar_kg') or 0), 3)
        except (TypeError, ValueError):
            raise MoSevkiyatError(f'Kalem {i + 1}: geçersiz kg.', 400)
        if kg <= 0:
            raise MoSevkiyatError(f'Kalem {i + 1}: miktar sıfırdan büyük olmalı.', 400)
        sk_raw = raw.get('siparis_kalem_id')
        if sk_raw in (None, ''):
            raise MoSevkiyatError(f'Kalem {i + 1}: siparis_kalem_id zorunlu.', 400)
        try:
            sk_id = int(sk_raw)
        except (TypeError, ValueError):
            raise MoSevkiyatError(f'Kalem {i + 1}: geçersiz sipariş kalemi ID.', 400)
        if sk_id not in kalan_map:
            if _kalem_tablosu_var(con):
                row = con.execute(
                    """
                    SELECT id FROM nexgen_planlama_siparis_kalem
                    WHERE id=? AND planlama_siparis_id=?
                    """,
                    (sk_id, siparis_id),
                ).fetchone()
                if not row:
                    raise MoSevkiyatError(
                        f'Kalem {i + 1}: sipariş kalemi bu siparişe ait değil veya bulunamadı.',
                        400,
                    )
            raise MoSevkiyatError(
                f'Kalem {i + 1}: sipariş kalemi kalan miktar hesaplanamadı.',
                400,
            )
        ek = 0.0
        if mevcut_sevkiyat_id:
            r = con.execute(
                """
                SELECT miktar_kg FROM mo_musteri_sevkiyat_kalem
                WHERE sevkiyat_id=? AND siparis_kalem_id=?
                """,
                (mevcut_sevkiyat_id, sk_id),
            ).fetchone()
            if r:
                ek = float(r['miktar_kg'] or 0)
        limit = float(kalan_map.get(sk_id, 0)) + ek
        if kg > limit + 0.001:
            raise MoSevkiyatError(
                f'Kalem {i + 1}: kalan {limit} kg — {kg} kg sevk edilemez.',
                409,
            )
        pk = next((k for k in kalan_list if k.get('siparis_kalem_id') == sk_id), {})
        norm.append({
            'siparis_kalem_id': sk_id,
            'urun_adi': (raw.get('urun_adi') or pk.get('urun_ailesi') or '').strip() or None,
            'renk_ad': (raw.get('renk_ad') or pk.get('renk_ad') or '').strip() or None,
            'formul_ad': (raw.get('formul_ad') or pk.get('formul_ad') or '').strip() or None,
            'miktar_kg': kg,
            'miktar_adet': raw.get('miktar_adet'),
            'notlar': (raw.get('notlar') or '').strip() or None,
        })
        toplam_kg += kg
    sevk_edilen = sevk_edilmis_kg(con, siparis_id)
    uretilen = _uretilen_kg_siparis(con, siparis_id)
    sevk_edilebilir = round(max(0.0, uretilen - sevk_edilen), 3)
    if uretilen > 0.001 and toplam_kg > sevk_edilebilir + 0.001:
        raise MoSevkiyatError(
            f'Toplam sevk {toplam_kg} kg — üretilen stok üst sınırı {sevk_edilebilir} kg.',
            409,
        )
    return norm


def _tahsilat_sevk_sonrasi_guncelle(con, siparis_id: int, sevkiyat_id: int) -> None:
    """Sipariş bazlı tek tahsilat planı — her zaman MIN(gercek sevk) ile idempotent."""
    cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()]
    if 'tahsilat_kurali' not in cols:
        return
    row = con.execute(
        """
        SELECT id, tahsilat_kurali, tahsilat_gun_sayisi, tahsilat_sabit_tarih,
               tahsilat_durumu, planlanan_tahsilat_tarihi
        FROM nexgen_planlama_siparis WHERE id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return
    kural = (row['tahsilat_kurali'] or '').upper()
    if kural not in ('SEVKTE', 'SEVKTEN_SONRA'):
        return
    ilk_sevk = gercek_sevk_tarihi(con, siparis_id)
    if not ilk_sevk:
        return
    gun = int(row['tahsilat_gun_sayisi'] or 0) if row['tahsilat_gun_sayisi'] else None
    hp = hesapla_tahsilat_plani(
        kural, gun_sayisi=gun, gercek_sevk_tarihi=ilk_sevk,
    )
    plan_tarih = hp.get('planlanan_tahsilat_tarihi')
    kaynak = hp.get('tahsilat_tarih_kaynagi') or 'GERCEK_SEVK'
    if not plan_tarih:
        return
    ref = f'msv:{sevkiyat_id}'
    con.execute(
        """
        UPDATE nexgen_planlama_siparis SET
            planlanan_tahsilat_tarihi=?,
            tahsilat_tarih_kaynagi=?,
            tahsilat_durumu=?,
            tahsilat_hesaplanan_sevk_ref=?,
            guncelleme_tarihi=?
        WHERE id=?
        """,
        (plan_tarih, kaynak, PLAN_DURUM_PLANLANDI, ref, _now(), siparis_id),
    )


def sevkiyat_olustur(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        raise MoSevkiyatError('Migration 127 uygulanmamış.', 503)
    if not can_sevkiyat_yaz(yk):
        raise MoSevkiyatError('Sevkiyat oluşturma yetkiniz yok.', 403)

    idem = (payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MoSevkiyatError('idempotency_key zorunlu.', 400)
    dup = con.execute(
        'SELECT id FROM mo_musteri_sevkiyat WHERE idempotency_key=?', (idem,)
    ).fetchone()
    if dup:
        return _detay(con, int(dup['id']))

    try:
        siparis_id = int(payload.get('siparis_id') or 0)
    except (TypeError, ValueError):
        siparis_id = 0
    if not siparis_id:
        raise MoSevkiyatError('siparis_id zorunlu.', 400)

    sip = _siparis_guard(con, siparis_id)
    cari_id = int(sip['cari_id'])
    kalemler = _validate_kalemler(con, siparis_id, payload.get('kalemler') or [])

    now = _now()
    cur = con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat (
            sevkiyat_no, siparis_id, cari_id, durum, hazirlik_tarihi,
            arac_plaka, sofor, irsaliye_no, kargo_firmasi, kargo_takip_no,
            teslim_alan, teslim_durumu, notlar, idempotency_key,
            olusturan_id, olusturma_tarihi, guncelleme_tarihi, audit_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _sevkiyat_no_uret(con), siparis_id, cari_id, 'HAZIRLANIYOR',
            (payload.get('hazirlik_tarihi') or _today())[:10],
            (payload.get('arac_plaka') or payload.get('arac') or '').strip() or None,
            (payload.get('sofor') or '').strip() or None,
            (payload.get('irsaliye_no') or '').strip() or None,
            (payload.get('kargo_firmasi') or payload.get('kargo') or '').strip() or None,
            (payload.get('kargo_takip_no') or '').strip() or None,
            (payload.get('teslim_alan') or '').strip() or None,
            (payload.get('teslim_durumu') or '').strip() or None,
            (payload.get('notlar') or '').strip() or None,
            idem, kullanici_id, now, now,
            json.dumps({'islem': 'OLUSTUR', 'kullanici_id': kullanici_id}, ensure_ascii=False),
        ),
    )
    sid = int(cur.lastrowid)
    for k in kalemler:
        adet = k.get('miktar_adet')
        if adet not in (None, ''):
            try:
                adet = float(adet)
            except (TypeError, ValueError):
                adet = None
        con.execute(
            """
            INSERT INTO mo_musteri_sevkiyat_kalem
                (sevkiyat_id, siparis_kalem_id, urun_adi, renk_ad, formul_ad,
                 miktar_kg, miktar_adet, notlar)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                sid, k['siparis_kalem_id'], k['urun_adi'], k['renk_ad'], k['formul_ad'],
                k['miktar_kg'], adet, k['notlar'],
            ),
        )
    con.commit()
    det = _detay(con, sid)
    det['cari360_olay'] = cari360_olay_sozlesmesi(OLAY_SEVK_HAZIR, det)
    return det


def durum_guncelle(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    yeni_durum: str,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    sevk_tarihi: str | None = None,
    teslim_tarihi: str | None = None,
    teslim_alan: str | None = None,
    teslim_durumu: str | None = None,
) -> dict[str, Any]:
    if not can_sevkiyat_yaz(yk):
        raise MoSevkiyatError('Sevkiyat durumu güncelleme yetkiniz yok.', 403)
    yeni = (yeni_durum or '').upper()
    if yeni not in DURUMLAR:
        raise MoSevkiyatError('Geçersiz durum.', 400)

    row = con.execute(
        'SELECT id, durum, siparis_id, cari_id FROM mo_musteri_sevkiyat WHERE id=? AND aktif=1',
        (sevkiyat_id,),
    ).fetchone()
    if not row:
        raise MoSevkiyatError('Sevkiyat bulunamadı.', 404)
    mevcut = (row['durum'] or '').upper()
    if yeni not in DURUM_GECIS.get(mevcut, frozenset()):
        raise MoSevkiyatError(f'{mevcut} → {yeni} geçişi yapılamaz.', 409)

    now = _now()
    updates: dict[str, Any] = {'durum': yeni, 'guncelleme_tarihi': now}
    olay = OLAY_SEVK_HAZIR

    if yeni == 'SEVK_EDILDI':
        st = (sevk_tarihi or _today())[:10]
        updates['sevk_tarihi'] = st
        olay = OLAY_SEVK_CIKTI
    elif yeni == 'TESLIM_EDILDI':
        updates['teslim_tarihi'] = (teslim_tarihi or _today())[:10]
        if teslim_alan:
            updates['teslim_alan'] = teslim_alan.strip()
        if teslim_durumu:
            updates['teslim_durumu'] = teslim_durumu.strip()
        olay = OLAY_SEVK_TESLIM
    elif yeni == 'TAMAMLANDI':
        updates['tamamlanma_tarihi'] = now[:10]
        olay = OLAY_SEVK_TAMAMLANDI

    set_sql = ', '.join(f'{k}=?' for k in updates)
    con.execute(
        f'UPDATE mo_musteri_sevkiyat SET {set_sql} WHERE id=?',
        [*updates.values(), sevkiyat_id],
    )
    if yeni == 'SEVK_EDILDI':
        _tahsilat_sevk_sonrasi_guncelle(con, int(row['siparis_id']), sevkiyat_id)
    con.commit()
    det = _detay(con, sevkiyat_id)
    det['cari360_olay'] = cari360_olay_sozlesmesi(olay, det)
    return det


def liste_siparis(con, siparis_id: int, kullanici_id: int, yk: set[str] | None = None) -> list[dict]:
    sip = _siparis_guard(con, siparis_id)
    if not can_sevkiyat_oku(con, kullanici_id, int(sip['cari_id']), yk):
        raise MoSevkiyatError('Görüntüleme yetkiniz yok.', 403)
    rows = con.execute(
        """
        SELECT id, sevkiyat_no, durum, sevk_tarihi, teslim_tarihi, hazirlik_tarihi
        FROM mo_musteri_sevkiyat WHERE siparis_id=? AND aktif=1
        ORDER BY id DESC
        """,
        (siparis_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
        kalemler = _kalem_satir(con, int(d['id']))
        d['toplam_kg'] = round(sum(float(k.get('miktar_kg') or 0) for k in kalemler), 3)
        out.append(d)
    return out


def sevkiyat_getir(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    det = _detay(con, sevkiyat_id)
    if not can_sevkiyat_oku(con, kullanici_id, int(det['cari_id']), yk):
        raise MoSevkiyatError('Görüntüleme yetkiniz yok.', 403)
    det['termin'] = termin_karsilastirma(con, int(det['siparis_id']))
    det['kalan_miktarlar'] = kalan_miktarlar(con, int(det['siparis_id']))
    return det
