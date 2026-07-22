# -*- coding: utf-8 -*-
"""Numune Talep (AT-M) — Pazarlama → Bekleyen Numuneler → Vedat çalışma kartı."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlite3

DURUMLAR = frozenset({
    'YENI_TALEP',
    'TASLAK',
    'BEKLEYEN_NUMUNE',
    'CALISILIYOR',
    'REVIZYONDA',
    'FERHAT_TESTINDE',
    'ONAY_BEKLIYOR',
    'ONAYLANDI',
    'RECETE_MERKEZINE_AKTARILDI',
})

MUSTERI_TIPLERI = frozenset({'MEVCUT', 'ADAY'})
ONCELIKLER = frozenset({'NORMAL', 'ACIL', 'KRITIK'})
RENK_TIPLERI = frozenset({'MEVCUT', 'YENI'})
URUN_TIPLERI = frozenset({'TERLIK', 'TABAN', 'DOKME'})
TALEP_KAYNAKLARI = frozenset({
    'Fuar', 'WhatsApp', 'Telefon', 'E-posta', 'Referans', 'Ziyaret', 'Bayi', 'Diğer',
})
VEDAT_SONUCLAR = frozenset({'Basarili', 'Revizyon', 'Red', 'Calisiliyor'})
KARSILAMA_YOLLARI = frozenset({'HAZIR_RENK', 'YENI_RENK', 'YENI_FORMUL'})
KARSILAMA_YOLLARI_JS = frozenset({'HAZIR_RF', 'HAZIR_RENK', 'YENI_RENK', 'YENI_FORMUL'})
DUZENLENEBILIR_DURUMLAR = frozenset({'YENI_TALEP', 'TASLAK'})

FILTRE_DURUMLAR = {
    'bekleyen': ('BEKLEYEN_NUMUNE',),
    'calisiliyor': ('CALISILIYOR', 'REVIZYONDA'),
    'tamamlanan': ('ONAY_BEKLIYOR', 'FERHAT_TESTINDE', 'ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI'),
}


class NumuneTalepError(Exception):
    def __init__(self, message: str, status: int = 400, kod: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kod = kod or 'NT_HATA'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def uret_talep_kodu(con) -> str:
    """AT-M-YYYY-NNNN — nexgen_arge_test ile çakışmayacak şekilde max sıra."""
    yil = datetime.now().year
    prefix = f'AT-M-{yil}-'
    row_a = con.execute(
        "SELECT MAX(CAST(SUBSTR(test_no, -4) AS INTEGER)) AS son "
        "FROM nexgen_arge_test WHERE test_no LIKE ?",
        (prefix + '%',),
    ).fetchone()
    row_n = con.execute(
        "SELECT MAX(CAST(SUBSTR(talep_kodu, -4) AS INTEGER)) AS son "
        "FROM nexgen_numune_talep WHERE talep_kodu LIKE ?",
        (prefix + '%',),
    ).fetchone()
    son = max(int(row_a['son'] or 0) if row_a else 0, int(row_n['son'] or 0) if row_n else 0)
    return f'{prefix}{son + 1:04d}'


def _norm_oncelik(v: str | None) -> str:
    m = {
        'Normal': 'NORMAL', 'Acil': 'ACIL', 'Kritik': 'KRITIK',
        'NORMAL': 'NORMAL', 'ACIL': 'ACIL', 'KRITIK': 'KRITIK',
    }
    out = m.get((v or '').strip(), 'NORMAL')
    if out not in ONCELIKLER:
        raise NumuneTalepError('Geçersiz öncelik.', 400)
    return out


def _norm_karsilama_yolu(v: str | None) -> str | None:
    if not v:
        return None
    t = (v or '').strip().upper()
    if t == 'HAZIR_RF':
        t = 'HAZIR_RENK'
    if t not in KARSILAMA_YOLLARI:
        raise NumuneTalepError('Geçersiz karsilama_yolu.', 400)
    return t


def _norm_int(v, *, default: int | None = None) -> int | None:
    if v is None or v == '':
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _norm_flag(v, *, default: int = 0) -> int:
    if v is None or v == '':
        return default
    if isinstance(v, bool):
        return 1 if v else 0
    return 1 if str(v).strip().lower() in ('1', 'true', 'evet', 'yes', 'on') else 0


def _norm_urun_tipi(v: str | None) -> str | None:
    if not v:
        return None
    t = (v or '').strip().upper().replace('İ', 'I')
    m = {'TERLIK': 'TERLIK', 'TERLİK': 'TERLIK', 'TABAN': 'TABAN', 'DOKME': 'DOKME', 'DÖKME': 'DOKME'}
    return m.get(t) or m.get((v or '').strip().upper())


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    if d.get('diger_beklentiler_json'):
        try:
            d['diger_beklentiler'] = json.loads(d['diger_beklentiler_json'])
        except (TypeError, ValueError, json.JSONDecodeError):
            d['diger_beklentiler'] = []
    else:
        d['diger_beklentiler'] = []
    return d


def _validate_payload(payload: dict, *, zorunlu_gonder: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise NumuneTalepError('JSON gövde gerekli.', 400)

    musteri_tipi = (payload.get('musteri_tipi') or 'MEVCUT').strip().upper()
    if musteri_tipi not in MUSTERI_TIPLERI:
        raise NumuneTalepError('musteri_tipi MEVCUT veya ADAY olmalı.', 400)

    cari_id = None
    if musteri_tipi == 'MEVCUT':
        try:
            cari_id = int(payload.get('cari_id') or 0)
        except (TypeError, ValueError):
            cari_id = 0
        if zorunlu_gonder and not cari_id:
            raise NumuneTalepError('Mevcut müşteri için cari seçimi zorunlu.', 400)
    else:
        firma = (payload.get('aday_firma_adi') or payload.get('firma_adi') or '').strip()
        kaynak = (payload.get('talep_kaynagi') or '').strip()
        if zorunlu_gonder and not firma:
            raise NumuneTalepError('Aday müşteri için firma adı zorunlu.', 400)
        if zorunlu_gonder and not kaynak:
            raise NumuneTalepError('Aday müşteri için talep kaynağı zorunlu.', 400)
        if kaynak and kaynak not in TALEP_KAYNAKLARI:
            raise NumuneTalepError('Geçersiz talep kaynağı.', 400)

    talep_eden = payload.get('talep_eden_kullanici_id') or payload.get('talep_eden_id')
    if zorunlu_gonder and not talep_eden:
        raise NumuneTalepError('Talep eden kişi zorunlu.', 400)

    renk_tipi = (payload.get('renk_tipi') or '').strip().upper() or None
    if renk_tipi and renk_tipi not in RENK_TIPLERI:
        raise NumuneTalepError('renk_tipi MEVCUT veya YENI olmalı.', 400)

    karsilama_yolu = _norm_karsilama_yolu(payload.get('karsilama_yolu'))
    if karsilama_yolu == 'YENI_FORMUL':
        renk_tipi = None
    elif karsilama_yolu == 'HAZIR_RENK':
        renk_tipi = 'MEVCUT' if payload.get('rf_renk_id') else None
    elif karsilama_yolu == 'YENI_RENK':
        if not renk_tipi:
            renk_tipi = 'YENI' if not payload.get('rf_renk_id') else 'MEVCUT'

    if renk_tipi == 'YENI' and zorunlu_gonder:
        if not (payload.get('yeni_renk_aciklama') or '').strip():
            raise NumuneTalepError('Yeni renk için açıklama zorunlu.', 400)

    if zorunlu_gonder:
        if not (payload.get('talep_nedeni') or '').strip():
            raise NumuneTalepError('Talep nedeni zorunlu.', 400)
        if not (payload.get('aciklama') or '').strip():
            raise NumuneTalepError('Açıklama zorunlu.', 400)

    diger = payload.get('diger_beklentiler') or []
    if not isinstance(diger, list):
        diger = []

    numune_adedi = _norm_int(payload.get('numune_adedi'))
    if numune_adedi is not None and numune_adedi < 1:
        raise NumuneTalepError('Numune adedi 1 veya daha büyük olmalı.', 400)

    patch_var = _norm_flag(payload.get('patch_aksesuar_var'))
    patch_aciklama = (payload.get('patch_aksesuar_aciklama') or '').strip() or None
    if not patch_var:
        patch_aciklama = None

    data = {
        'musteri_tipi': musteri_tipi,
        'cari_id': cari_id or None,
        'aday_firma_adi': (payload.get('aday_firma_adi') or payload.get('firma_adi') or '').strip() or None,
        'ilgili_kisi': (payload.get('ilgili_kisi') or '').strip() or None,
        'telefon': (payload.get('telefon') or '').strip() or None,
        'eposta': (payload.get('eposta') or '').strip() or None,
        'sehir': (payload.get('sehir') or '').strip() or None,
        'talep_kaynagi': (payload.get('talep_kaynagi') or '').strip() or None,
        'talep_eden_kullanici_id': int(talep_eden) if talep_eden else None,
        'oncelik': _norm_oncelik(payload.get('oncelik')),
        'hedef_tarih': (payload.get('hedef_tarih') or '').strip() or None,
        'talep_nedeni': (payload.get('talep_nedeni') or '').strip() or None,
        'aciklama': (payload.get('aciklama') or '').strip() or None,
        'ek_not': (payload.get('ek_not') or '').strip() or None,
        'urun_tipi': _norm_urun_tipi(payload.get('urun_tipi')),
        'urun_adi': (payload.get('urun_adi') or '').strip() or None,
        'urun_aciklama': (payload.get('urun_aciklama') or '').strip() or None,
        'renk_tipi': renk_tipi,
        'rf_renk_id': int(payload['rf_renk_id']) if payload.get('rf_renk_id') else None,
        'renk_kodu': (payload.get('renk_kodu') or '').strip() or None,
        'yeni_renk_aciklama': (payload.get('yeni_renk_aciklama') or '').strip() or None,
        'acik_koyu': (payload.get('acik_koyu') or '').strip() or None,
        'mat_parlak': (payload.get('mat_parlak') or '').strip() or None,
        'ref_renk_kodu': (payload.get('ref_renk_kodu') or '').strip() or None,
        'yumusaklik': (payload.get('yumusaklik') or '').strip() or None,
        'kaymazlik': (payload.get('kaymazlik') or '').strip() or None,
        'shore_deger': (payload.get('shore_deger') or '').strip() or None,
        'pisme_notu': (payload.get('pisme_notu') or '').strip() or None,
        'diger_beklentiler_json': json.dumps(diger, ensure_ascii=False),
        'karsilama_yolu': karsilama_yolu,
        'numune_adedi': numune_adedi,
        'beden_kalip': (payload.get('beden_kalip') or '').strip() or None,
        'patch_aksesuar_var': patch_var,
        'patch_aksesuar_aciklama': patch_aciklama,
        'paketleme_notu': (payload.get('paketleme_notu') or '').strip() or None,
        'kargo_teslim_notu': (payload.get('kargo_teslim_notu') or '').strip() or None,
        'kullanim_amaci': (payload.get('kullanim_amaci') or '').strip() or None,
        'benzer_urun_numune': (payload.get('benzer_urun_numune') or '').strip() or None,
    }
    return _apply_karsilama_isolation(data)


def _apply_karsilama_isolation(data: dict) -> dict:
    """Talep türüne göre ilgisiz alanları NULL/temiz değere çeker."""
    ky = data.get('karsilama_yolu')
    bos_json = json.dumps([], ensure_ascii=False)
    if ky == 'HAZIR_RENK':
        data.update({
            'yeni_renk_aciklama': None,
            'acik_koyu': None,
            'mat_parlak': None,
            'ref_renk_kodu': None,
            'shore_deger': None,
            'yumusaklik': None,
            'kaymazlik': None,
            'diger_beklentiler_json': bos_json,
            'kullanim_amaci': None,
            'benzer_urun_numune': None,
        })
    elif ky == 'YENI_RENK':
        data.update({
            'rf_renk_id': None,
            'renk_kodu': None,
            'shore_deger': None,
            'yumusaklik': None,
            'kaymazlik': None,
            'diger_beklentiler_json': bos_json,
            'kullanim_amaci': None,
            'benzer_urun_numune': None,
            'renk_tipi': 'YENI',
        })
    elif ky == 'YENI_FORMUL':
        data.update({
            'rf_renk_id': None,
            'renk_kodu': None,
            'acik_koyu': None,
            'mat_parlak': None,
            'ref_renk_kodu': None,
            'renk_tipi': None,
        })
    return data


def gelisme_ekle(
    con,
    talep_id: int,
    olay_metni: str,
    *,
    olay_tipi: str | None = None,
    kullanici_id: int | None = None,
    olay_tarihi: str | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO nexgen_numune_talep_gelisme
            (talep_id, olay_tarihi, olay_tipi, olay_metni, kullanici_id, aktif)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (talep_id, olay_tarihi or _now(), olay_tipi, olay_metni, kullanici_id),
    )


def gelisme_liste(con, talep_id: int, limit: int = 100) -> list[dict]:
    rows = con.execute(
        """
        SELECT g.*, k.KullaniciAdi AS kullanici_kadi, k.AdSoyad AS kullanici_ad
        FROM nexgen_numune_talep_gelisme g
        LEFT JOIN sistem_kullanici k ON k.Id = g.kullanici_id
        WHERE g.talep_id=? AND g.aktif=1
        ORDER BY g.olay_tarihi ASC, g.id ASC
        LIMIT ?
        """,
        (talep_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _olusturan_gelisme_metni(con, kullanici_id: int) -> str:
    row = con.execute(
        'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
        (kullanici_id,),
    ).fetchone()
    if not row:
        return 'Kullanıcı talebi oluşturdu'
    ad = (row['AdSoyad'] or row['KullaniciAdi'] or 'Kullanıcı').strip()
    return f'{ad} talebi oluşturdu'


def _isleme_alan_gelisme_metni(con, kullanici_id: int) -> str:
    row = con.execute(
        'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
        (kullanici_id,),
    ).fetchone()
    ad = (row['AdSoyad'] or row['KullaniciAdi'] or 'Vedat').strip() if row else 'Vedat'
    return f'{ad} işleme aldı'


def _renk_goster(row: dict) -> str:
    if (row.get('renk_tipi') or '').upper() == 'YENI':
        yr = (row.get('yeni_renk_aciklama') or '').strip()
        return f'Yeni renk isteği' + (f' — {yr}' if yr else '')
    return (row.get('renk_kodu') or row.get('yeni_renk_aciklama') or '—').strip() or '—'


def _firma_goster(row: dict) -> str:
    if (row.get('musteri_tipi') or '').upper() == 'ADAY':
        return (row.get('aday_firma_adi') or '—').strip() or '—'
    return (row.get('cari_unvan') or '—').strip() or '—'


def _liste_satir_zengin(row: dict) -> dict:
    d = _row_to_dict(row)
    d['firma_goster'] = _firma_goster(d)
    d['renk_goster'] = _renk_goster(d)
    d['durum_etiket'] = durum_etiket(d.get('durum'))
    return d


def _insert_fields(data: dict) -> tuple[str, list]:
    cols = list(data.keys())
    return ','.join(cols), [data[c] for c in cols]


def kaydet_taslak(con, payload: dict, olusturan_id: int, talep_id: int | None = None) -> dict:
    norm = _validate_payload(payload, zorunlu_gonder=False)
    now = _now()
    if talep_id:
        row = con.execute(
            'SELECT id, talep_kodu, durum, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
            (talep_id,),
        ).fetchone()
        if not row:
            raise NumuneTalepError('Talep bulunamadı.', 404)
        if row['durum'] not in DUZENLENEBILIR_DURUMLAR:
            raise NumuneTalepError('Yalnız taslak talepler düzenlenebilir.', 409)
        if row['arge_test_id']:
            raise NumuneTalepError('Bağlı AR-GE kartı var — duplicate oluşturulamaz.', 409)
        kod = row['talep_kodu']
        norm['guncelleme_tarihi'] = now
        norm['durum'] = 'TASLAK'
        sets = ','.join(f'{k}=?' for k in norm)
        con.execute(
            f'UPDATE nexgen_numune_talep SET {sets} WHERE id=?',
            [*norm.values(), talep_id],
        )
        tid = talep_id
    else:
        kod = uret_talep_kodu(con)
        norm.update({
            'talep_kodu': kod,
            'durum': 'TASLAK',
            'olusturan_kullanici_id': olusturan_id,
            'olusturma_tarihi': now,
            'guncelleme_tarihi': now,
            'aktif': 1,
        })
        if not norm.get('talep_eden_kullanici_id'):
            norm['talep_eden_kullanici_id'] = olusturan_id
        cols, vals = _insert_fields(norm)
        cur = con.execute(f'INSERT INTO nexgen_numune_talep ({cols}) VALUES ({",".join(["?"]*len(vals))})', vals)
        tid = int(cur.lastrowid)
    con.commit()
    return get_talep(con, tid)


def gonder_arge(con, payload: dict, olusturan_id: int, talep_id: int | None = None) -> dict:
    norm = _validate_payload(payload, zorunlu_gonder=True)
    now = _now()
    if talep_id:
        row = con.execute(
            'SELECT id, talep_kodu, durum, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
            (talep_id,),
        ).fetchone()
        if not row:
            raise NumuneTalepError('Talep bulunamadı.', 404)
        if row['durum'] not in DUZENLENEBILIR_DURUMLAR:
            raise NumuneTalepError('Yalnız taslak talepler gönderilebilir.', 409)
        if row['arge_test_id']:
            raise NumuneTalepError('Duplicate AR-GE kartı oluşturulamaz.', 409)
        kod = row['talep_kodu']
        norm['guncelleme_tarihi'] = now
        norm['durum'] = 'BEKLEYEN_NUMUNE'
        sets = ','.join(f'{k}=?' for k in norm)
        con.execute(f'UPDATE nexgen_numune_talep SET {sets} WHERE id=?', [*norm.values(), talep_id])
        tid = talep_id
    else:
        kod = uret_talep_kodu(con)
        norm.update({
            'talep_kodu': kod,
            'durum': 'BEKLEYEN_NUMUNE',
            'olusturan_kullanici_id': olusturan_id,
            'olusturma_tarihi': now,
            'guncelleme_tarihi': now,
            'aktif': 1,
        })
        if not norm.get('talep_eden_kullanici_id'):
            norm['talep_eden_kullanici_id'] = olusturan_id
        cols, vals = _insert_fields(norm)
        cur = con.execute(f'INSERT INTO nexgen_numune_talep ({cols}) VALUES ({",".join(["?"]*len(vals))})', vals)
        tid = int(cur.lastrowid)
    try:
        gelisme_ekle(
            con, tid, _olusturan_gelisme_metni(con, olusturan_id),
            olay_tipi='TALEP_OLUSTURULDU', kullanici_id=olusturan_id,
        )
    except sqlite3.OperationalError:
        pass
    con.commit()
    return get_talep(con, tid)


def get_talep(con, talep_id: int) -> dict:
    row = con.execute(
        """
        SELECT nt.*,
               c.unvan AS cari_unvan, c.cari_kod,
               te.KullaniciAdi AS talep_eden_kadi, te.AdSoyad AS talep_eden_ad,
               ok.KullaniciAdi AS olusturan_kadi, ok.AdSoyad AS olusturan_ad,
               ia.KullaniciAdi AS isleme_alan_kadi, ia.AdSoyad AS isleme_alan_ad
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN sistem_kullanici te ON te.Id = nt.talep_eden_kullanici_id
        LEFT JOIN sistem_kullanici ok ON ok.Id = nt.olusturan_kullanici_id
        LEFT JOIN sistem_kullanici ia ON ia.Id = nt.isleme_alan_kullanici_id
        WHERE nt.id=? AND nt.aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    d = _row_to_dict(row)
    d['firma_goster'] = _firma_goster(d)
    d['renk_goster'] = _renk_goster(d)
    d['durum_etiket'] = durum_etiket(d.get('durum'))
    return d


def say_bekleyen_numune(con) -> int:
    row = con.execute(
        "SELECT COUNT(*) AS c FROM nexgen_numune_talep "
        "WHERE aktif=1 AND durum='BEKLEYEN_NUMUNE'"
    ).fetchone()
    return int(row['c'] or 0) if row else 0


def liste_bekleyen(con, limit: int = 50, filtre: str | None = None, q: str | None = None) -> list[dict]:
    if filtre:
        durumlar = FILTRE_DURUMLAR.get(filtre, FILTRE_DURUMLAR['bekleyen'])
    else:
        durumlar = ('BEKLEYEN_NUMUNE', 'CALISILIYOR', 'REVIZYONDA')
    ph = ','.join(['?'] * len(durumlar))
    sql = f"""
        SELECT nt.id, nt.talep_kodu, nt.durum, nt.oncelik, nt.hedef_tarih,
               nt.urun_tipi, nt.urun_adi, nt.renk_kodu, nt.yeni_renk_aciklama,
               nt.rf_renk_id, nt.renk_tipi,
               nt.musteri_tipi, nt.aday_firma_adi,
               c.unvan AS cari_unvan,
               te.AdSoyad AS talep_eden_ad
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN sistem_kullanici te ON te.Id = nt.talep_eden_kullanici_id
        WHERE nt.aktif=1 AND nt.durum IN ({ph})
    """
    params: list[Any] = list(durumlar)
    qn = (q or '').strip()
    if qn:
        like = f'%{qn}%'
        sql += """
          AND (
            nt.talep_kodu LIKE ? OR c.unvan LIKE ? OR nt.aday_firma_adi LIKE ?
            OR te.AdSoyad LIKE ? OR nt.urun_adi LIKE ? OR nt.renk_kodu LIKE ?
            OR nt.yeni_renk_aciklama LIKE ? OR nt.durum LIKE ?
          )
        """
        params.extend([like] * 8)
    sql += """
        ORDER BY
          CASE nt.oncelik WHEN 'KRITIK' THEN 0 WHEN 'ACIL' THEN 1 ELSE 2 END,
          nt.guncelleme_tarihi DESC, nt.id DESC
        LIMIT ?
    """
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    return [_liste_satir_zengin(r) for r in rows]


def liste_pazarlama(con, kullanici_id: int | None, limit: int = 100) -> list[dict]:
    rows = con.execute(
        """
        SELECT id, talep_kodu, durum, oncelik, olusturma_tarihi, hedef_tarih,
               musteri_tipi, aday_firma_adi, cari_id
        FROM nexgen_numune_talep
        WHERE aktif=1
          AND (olusturan_kullanici_id=? OR talep_eden_kullanici_id=? OR ? IS NULL)
        ORDER BY id DESC
        LIMIT ?
        """,
        (kullanici_id, kullanici_id, kullanici_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def isleme_al(con, talep_id: int, kullanici_id: int) -> dict:
    row = con.execute(
        'SELECT id, durum, arge_test_id, talep_kodu FROM nexgen_numune_talep WHERE id=? AND aktif=1',
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    if row['arge_test_id']:
        raise NumuneTalepError('Duplicate AR-GE kartı — mevcut kayıt kullanılmalı.', 409)
    if row['durum'] in ('CALISILIYOR', 'REVIZYONDA'):
        return get_talep(con, talep_id)
    if row['durum'] != 'BEKLEYEN_NUMUNE':
        raise NumuneTalepError('Yalnız bekleyen numune işleme alınabilir.', 409)
    now = _now()
    con.execute(
        """
        UPDATE nexgen_numune_talep SET
            durum='CALISILIYOR',
            isleme_alan_kullanici_id=?,
            isleme_alinma_tarihi=?,
            guncelleme_tarihi=?
        WHERE id=?
        """,
        (kullanici_id, now, now, talep_id),
    )
    try:
        gelisme_ekle(
            con, talep_id, _isleme_alan_gelisme_metni(con, kullanici_id),
            olay_tipi='ISLEME_ALINDI', kullanici_id=kullanici_id,
        )
    except sqlite3.OperationalError:
        pass
    con.commit()
    return get_talep(con, talep_id)


def vedat_calisma_baslat(con, talep_id: int, kullanici_id: int | None = None) -> dict:
    if kullanici_id:
        return isleme_al(con, talep_id, kullanici_id)
    row = con.execute(
        'SELECT id, durum, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    if row['arge_test_id']:
        raise NumuneTalepError('Duplicate AR-GE kartı — mevcut kayıt kullanılmalı.', 409)
    if row['durum'] not in ('BEKLEYEN_NUMUNE', 'CALISILIYOR', 'REVIZYONDA'):
        raise NumuneTalepError('Bu durumda çalışma başlatılamaz.', 409)
    if row['durum'] == 'BEKLEYEN_NUMUNE':
        con.execute(
            "UPDATE nexgen_numune_talep SET durum='CALISILIYOR', guncelleme_tarihi=? WHERE id=?",
            (_now(), talep_id),
        )
        con.commit()
    return get_talep(con, talep_id)


def vedat_kaydet(con, talep_id: int, payload: dict) -> dict:
    row = con.execute(
        'SELECT id, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    if row['arge_test_id']:
        raise NumuneTalepError('Duplicate AR-GE kartı oluşturulamaz.', 409)

    ferhat = payload.get('vedat_ferhat_testi')
    try:
        ferhat_i = 1 if str(ferhat).lower() in ('1', 'true', 'evet', 'yes') else 0
    except Exception:
        ferhat_i = 0

    sonuc = (payload.get('vedat_sonuc') or '').strip()
    if sonuc and sonuc not in VEDAT_SONUCLAR:
        raise NumuneTalepError('Geçersiz Vedat sonucu.', 400)

    durum = 'CALISILIYOR'
    if sonuc == 'Revizyon':
        durum = 'REVIZYONDA'
    elif sonuc == 'Basarili':
        durum = 'CALISILIYOR'
    elif sonuc == 'Red':
        durum = 'CALISILIYOR'

    pigment = (payload.get('vedat_pigment') or '').strip() or None
    rev_not = (payload.get('vedat_revizyon_notu') or '').strip() or None
    degisiklik = (payload.get('vedat_yapilan_degisiklik') or '').strip() or None
    deneme_t = (payload.get('vedat_deneme_tarihi') or '').strip() or None

    con.execute(
        """
        UPDATE nexgen_numune_talep SET
            vedat_pigment=?,
            vedat_numune_miktari=?,
            vedat_numune_sonucu=?,
            vedat_revizyon_notu=?,
            vedat_yapilan_degisiklik=?,
            vedat_deneme_tarihi=?,
            vedat_ferhat_testi=?,
            vedat_sonuc=?,
            durum=?,
            guncelleme_tarihi=?
        WHERE id=?
        """,
        (
            pigment,
            (payload.get('vedat_numune_miktari') or '').strip() or None,
            (payload.get('vedat_numune_sonucu') or '').strip() or None,
            rev_not,
            degisiklik,
            deneme_t,
            ferhat_i,
            sonuc or None,
            durum,
            _now(),
            talep_id,
        ),
    )
    try:
        if pigment:
            gelisme_ekle(con, talep_id, 'Pigment denemesi yapıldı', olay_tipi='DENEME')
        if rev_not:
            gelisme_ekle(con, talep_id, rev_not, olay_tipi='REVIZYON')
        elif sonuc == 'Revizyon':
            gelisme_ekle(con, talep_id, 'Revizyon gerekli', olay_tipi='REVIZYON')
        if degisiklik:
            gelisme_ekle(con, talep_id, degisiklik, olay_tipi='DEGISIKLIK')
    except sqlite3.OperationalError:
        pass
    con.commit()
    return get_talep(con, talep_id)


def belge_id_guncelle(con, talep_id: int, alan: str, belge_id: int) -> None:
    izin = {'urun_gorsel_belge_id', 'ref_gorsel_belge_id', 'vedat_sonuc_gorsel_belge_id'}
    if alan not in izin:
        raise NumuneTalepError('Geçersiz belge alanı.', 400)
    con.execute(
        f'UPDATE nexgen_numune_talep SET {alan}=?, guncelleme_tarihi=? WHERE id=? AND aktif=1',
        (belge_id, _now(), talep_id),
    )
    con.commit()


def durum_etiket(durum: str | None) -> str:
    m = {
        'YENI_TALEP': 'Yeni Talep',
        'TASLAK': 'Taslak',
        'BEKLEYEN_NUMUNE': 'Bekleyen Numune',
        'CALISILIYOR': 'Çalışılıyor',
        'REVIZYONDA': 'Revizyonda',
        'FERHAT_TESTINDE': 'Ferhat Testinde',
        'ONAY_BEKLIYOR': 'Onay Bekliyor',
        'ONAYLANDI': 'Onaylandı',
        'RECETE_MERKEZINE_AKTARILDI': 'Reçete Merkezine Aktarıldı',
    }
    return m.get((durum or '').upper(), durum or '—')
