# -*- coding: utf-8 -*-
"""
NX-AR tek çalışma kartı — service katmanı (FAZ-ARGE-2D2)

CREATE / GET / LIST
Kod/UI dışı: yalnız veri sözleşmesi + guard + transaction.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from modules.nexgen.cekirdek_gorunum import cekirdek_formul_mu

CALISMA_TIPLERI = frozenset({'MUSTERI_RENK', 'YENI_RF', 'YENI_FORMUL'})
ONCELIKLER = frozenset({'NORMAL', 'ACIL', 'KRITIK'})
BOYUTLAR = frozenset({'LARGE', 'SMALL', 'MEDIUM'})
SAHA_NEDENLERI = frozenset({
    'BILINEN_RECETE', 'BILINEN_RENK', 'YENI_RENK', 'YENI_FORMUL',
    'SHORE_RISKI', 'PISME_RISKI', 'YOGUNLUK_RISKI', 'KALIP_RISKI',
    'YONETICI_KARARI', 'DIGER',
})
ANA_GRUP = frozenset({'1BA', '2BA', '3BA'})

# AT çalışma tipi harfi — R=Renk/RF, F=Formül, M=Müşteri renk talebi
_AT_TIP_HARF = {
    'MUSTERI_RENK': 'M',
    'YENI_RF': 'R',
    'YENI_FORMUL': 'F',
}
_CALISMA_TIP_ETIKET = {
    'MUSTERI_RENK': 'Müşteri Renk Talebi',
    'YENI_RF': 'Renk Denemesi',
    'YENI_FORMUL': 'Formül Denemesi',
}


class NxArError(Exception):
    def __init__(self, message: str, status: int = 400, kod: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kod = kod or 'NXAR_HATA'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _nx_ar_kod_uret(con) -> str:
    row = con.execute(
        "SELECT MAX(CAST(SUBSTR(arge_kodu, 7) AS INTEGER)) AS son "
        "FROM nexgen_arge_test WHERE arge_kodu LIKE 'NX-AR-%'"
    ).fetchone()
    son = int(row['son'] or 0) if row else 0
    return f'NX-AR-{son + 1:04d}'


def at_tip_harf(calisma_tipi: str | None) -> str | None:
    """calisma_tipi → AT harfi (R/F/M). Bilinmeyen tipte None."""
    return _AT_TIP_HARF.get((calisma_tipi or '').strip().upper())


def calisma_tipi_etiket(calisma_tipi: str | None) -> str:
    return _CALISMA_TIP_ETIKET.get((calisma_tipi or '').strip().upper(), calisma_tipi or '—')


def _test_no_uret(con, calisma_tipi: str) -> str:
    """AT-{R|F|M}-YYYY-NNNN — tip bazlı sıra (MAX). Eski AT-YYYY-NNNN üretilmez."""
    harf = at_tip_harf(calisma_tipi)
    if not harf:
        raise NxArError(
            f'Geçersiz calisma_tipi için AT kodu üretilemez: {calisma_tipi}',
            400,
            'AT_TIP',
        )
    yil = datetime.now().year
    prefix = f'AT-{harf}-{yil}-'
    row = con.execute(
        "SELECT MAX(CAST(SUBSTR(test_no, -4) AS INTEGER)) AS son "
        "FROM nexgen_arge_test WHERE test_no LIKE ?",
        (prefix + '%',),
    ).fetchone()
    son = int(row['son'] or 0) if row else 0
    return f'{prefix}{son + 1:04d}'


def _uv_cekirdek_bilgi(con, uv_id: int) -> dict:
    row = con.execute(
        """
        SELECT uv.id, uv.boyut, uv.aktif AS uv_aktif,
               rv.id AS rv_id, f.id AS formul_id, f.kod AS formul_kod, f.aktif AS f_aktif
        FROM nexgen_uretim_varyant uv
        JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
        JOIN nexgen_formul f ON f.id = rv.formul_id
        WHERE uv.id = ?
        """,
        (uv_id,),
    ).fetchone()
    if not row:
        raise NxArError(f'Üretim varyantı bulunamadı: {uv_id}', 404, 'UV_YOK')
    d = dict(row)
    if not d['uv_aktif']:
        raise NxArError(f'Üretim varyantı pasif: {uv_id}', 409, 'UV_PASIF')
    if not d['f_aktif']:
        raise NxArError(f'Formül pasif: {d["formul_kod"]}', 409, 'FORMUL_PASIF')
    if not cekirdek_formul_mu(d['formul_kod']):
        raise NxArError(
            f'Legacy formül ile NX-AR açılamaz: {d["formul_kod"]}',
            409,
            'LEGACY_FORMUL',
        )
    return d


def _validate_kaynak_set(con, kaynak_uvler: list, ana_grup: str) -> list[dict]:
    if not kaynak_uvler:
        raise NxArError('kaynak_uvler zorunludur.', 400, 'KAYNAK_BOS')

    normalized = []
    boyutlar = []
    for i, item in enumerate(kaynak_uvler):
        if not isinstance(item, dict):
            raise NxArError(f'kaynak_uvler[{i}] geçersiz.', 400)
        boyut = (item.get('boyut') or '').strip().upper()
        uv_id = item.get('kaynak_uretim_varyant_id')
        if boyut not in BOYUTLAR:
            raise NxArError(f'Geçersiz boyut: {boyut}', 400, 'BOYUT')
        if not uv_id:
            raise NxArError('kaynak_uretim_varyant_id zorunludur.', 400)
        try:
            uv_id = int(uv_id)
        except (TypeError, ValueError):
            raise NxArError('kaynak_uretim_varyant_id geçersiz.', 400)
        info = _uv_cekirdek_bilgi(con, uv_id)
        if (info['boyut'] or '').upper() != boyut:
            raise NxArError(
                f'UV {uv_id} boyutu {info["boyut"]}, istek {boyut}.',
                409,
                'BOYUT_UYUSMAZ',
            )
        kod = (info['formul_kod'] or '').upper()
        if not kod.startswith(ana_grup + '-'):
            raise NxArError(
                f'UV {uv_id} formül {kod} ana grup {ana_grup} ile uyumsuz.',
                409,
                'GRUP_UYUSMAZ',
            )
        if boyut in boyutlar:
            raise NxArError(f'Boyut tekrar: {boyut}', 400, 'BOYUT_TEKRAR')
        boyutlar.append(boyut)
        normalized.append({
            'boyut': boyut,
            'kaynak_uretim_varyant_id': uv_id,
            'formul_id': info['formul_id'],
            'formul_kod': info['formul_kod'],
            'rv_id': info['rv_id'],
            'sira_no': int(item.get('sira_no') or (i + 1)),
        })

    set_b = set(boyutlar)
    if set_b == {'LARGE', 'SMALL'}:
        tip = 'LS'
    elif set_b == {'MEDIUM'}:
        tip = 'M'
    else:
        raise NxArError(
            'Kaynak set yalnız LARGE+SMALL veya yalnız MEDIUM olabilir.',
            409,
            'KAYNAK_SET',
        )
    for n in normalized:
        n['set_tipi'] = tip
    return normalized


def _kalemler_uv_snapshot(
    con, kaynaklar: list[dict], numune_orani: float,
) -> list[dict]:
    """Seçilen her kaynak UV reçetesini ilgili boyuta snapshot/copy eder.

    test_miktar_kg = orijinal * (numune_orani/100). L/S kalemleri karışmaz.
    """
    oran = float(numune_orani or 10.0)
    if oran <= 0:
        raise NxArError('numune_orani > 0 olmalı.', 400)
    carpan = oran / 100.0
    out: list[dict] = []
    for kay in kaynaklar:
        uv_id = kay['kaynak_uretim_varyant_id']
        boyut = kay['boyut']
        rows = con.execute(
            """
            SELECT rk.stok_kart_id, rk.sira, rk.miktar_kg, rk.aciklama, sk.aktif
            FROM nexgen_recete_kalem rk
            JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
            WHERE rk.uretim_varyant_id=? AND rk.aktif=1
            ORDER BY rk.sira, rk.id
            """,
            (uv_id,),
        ).fetchall()
        if not rows:
            raise NxArError(
                f'Kaynak UV {uv_id} ({boyut}) reçete kalemi yok.',
                400,
                'RECETE_BOS',
            )
        for r in rows:
            if not r['aktif']:
                raise NxArError(
                    f'Pasif stok kartı reçetede: {r["stok_kart_id"]}',
                    409,
                    'STOK_PASIF',
                )
            orj = float(r['miktar_kg'] or 0)
            if orj <= 0:
                continue
            test_kg = round(orj * carpan, 6)
            if test_kg <= 0:
                continue
            out.append({
                'boyut': boyut,
                'stok_kart_id': int(r['stok_kart_id']),
                'test_miktar_kg': test_kg,
                'orjinal_miktar_kg': orj,
                'sira': int(r['sira'] or 1),
                'kaynak_uv_id': uv_id,
                'aciklama': (r['aciklama'] or None),
            })
    if not out:
        raise NxArError('UV snapshot kalemi üretilemedi.', 400, 'KALEM_BOS')
    return out


def _validate_kalemler(con, kalemler: list, kaynaklar: list[dict]) -> list[dict]:
    if not kalemler:
        raise NxArError('deneme.kalemler zorunludur.', 400, 'KALEM_BOS')
    izinli = {k['boyut'] for k in kaynaklar}
    uv_by_boyut = {k['boyut']: k['kaynak_uretim_varyant_id'] for k in kaynaklar}
    out = []
    for i, k in enumerate(kalemler):
        if not isinstance(k, dict):
            raise NxArError(f'kalemler[{i}] geçersiz.', 400)
        boyut = (k.get('boyut') or '').strip().upper()
        if boyut not in izinli:
            raise NxArError(
                f'Kalem boyutu kaynak sette yok: {boyut}',
                409,
                'KALEM_BOYUT',
            )
        try:
            stok_id = int(k.get('stok_kart_id'))
        except (TypeError, ValueError):
            raise NxArError('stok_kart_id geçersiz.', 400)
        sk = con.execute(
            'SELECT id, aktif FROM nexgen_stok_kart WHERE id=?', (stok_id,)
        ).fetchone()
        if not sk or not sk['aktif']:
            raise NxArError(f'Stok kartı yok/pasif: {stok_id}', 404, 'STOK')
        try:
            miktar = float(k.get('test_miktar_kg'))
        except (TypeError, ValueError):
            raise NxArError('test_miktar_kg geçersiz.', 400)
        if miktar <= 0:
            raise NxArError('test_miktar_kg > 0 olmalı.', 400)
        sira = int(k.get('sira') or (i + 1))
        out.append({
            'boyut': boyut,
            'stok_kart_id': stok_id,
            'test_miktar_kg': miktar,
            'orjinal_miktar_kg': float(k.get('orjinal_miktar_kg') or miktar),
            'sira': sira,
            'kaynak_uv_id': int(k.get('kaynak_uv_id') or uv_by_boyut[boyut]),
            'aciklama': (k.get('aciklama') or '').strip() or None,
        })
    return out


def create_nx_ar(con, payload: dict, kullanici_id: int | None = None) -> dict:
    """NX-AR kartı + kaynak UV + deneme#1 + kalemler. Tek transaction."""
    if not isinstance(payload, dict):
        raise NxArError('JSON gövde gerekli.', 400)

    calisma_tipi = (payload.get('calisma_tipi') or 'YENI_RF').strip().upper()
    if calisma_tipi not in CALISMA_TIPLERI:
        raise NxArError('calisma_tipi geçersiz.', 400)

    oncelik = (payload.get('oncelik') or 'NORMAL').strip().upper()
    if oncelik not in ONCELIKLER:
        raise NxArError('oncelik geçersiz.', 400)

    ana_grup = (payload.get('ana_formul_grup_kodu') or '').strip().upper()
    if ana_grup not in ANA_GRUP:
        raise NxArError('ana_formul_grup_kodu 1BA/2BA/3BA olmalı.', 400)

    try:
        cari_id = int(payload['cari_id']) if payload.get('cari_id') not in (None, '') else None
    except (TypeError, ValueError):
        raise NxArError('cari_id geçersiz.', 400)
    if cari_id is not None:
        c = con.execute(
            'SELECT id FROM nexgen_cari WHERE id=? AND aktif=1', (cari_id,)
        ).fetchone()
        if not c:
            raise NxArError('Cari bulunamadı.', 404, 'CARI')

    hedef = (
        (payload.get('hedef_renk_adi') or payload.get('yeni_renk_adi') or '')
        .strip()
    )
    if not hedef:
        raise NxArError('hedef_renk_adi veya yeni_renk_adi zorunlu.', 400)

    saha = payload.get('saha_testi_gerekli_mi')
    try:
        saha_mi = int(saha) if saha not in (None, '') else 0
    except (TypeError, ValueError):
        raise NxArError('saha_testi_gerekli_mi 0/1 olmalı.', 400)
    if saha_mi not in (0, 1):
        raise NxArError('saha_testi_gerekli_mi 0/1 olmalı.', 400)

    saha_neden = (payload.get('saha_testi_nedeni') or '').strip().upper() or None
    if saha_mi == 1:
        if not saha_neden or saha_neden not in SAHA_NEDENLERI:
            raise NxArError(
                'saha_testi_gerekli_mi=1 iken geçerli saha_testi_nedeni zorunlu.',
                400,
                'SAHA_NEDEN',
            )
    elif saha_neden and saha_neden not in SAHA_NEDENLERI:
        raise NxArError('saha_testi_nedeni geçersiz.', 400)

    kaynaklar = _validate_kaynak_set(con, payload.get('kaynak_uvler') or [], ana_grup)

    deneme_in = payload.get('deneme') or {}
    if not isinstance(deneme_in, dict):
        raise NxArError('deneme nesnesi gerekli.', 400)

    try:
        numune_orani = float(deneme_in['numune_orani']) if deneme_in.get('numune_orani') not in (None, '') else 10.0
    except (TypeError, ValueError):
        raise NxArError('numune_orani geçersiz.', 400)

    ham_kalem = deneme_in.get('kalemler')
    if ham_kalem:
        kalemler = _validate_kalemler(con, ham_kalem, kaynaklar)
    else:
        # Müşteri renk / tablet: kalem yoksa kaynak UV reçetesinden boyutlu snapshot
        kalemler = _kalemler_uv_snapshot(con, kaynaklar, numune_orani)

    shore_hedef = None
    if payload.get('shore_hedef') not in (None, ''):
        try:
            shore_hedef = float(payload['shore_hedef'])
        except (TypeError, ValueError):
            raise NxArError('shore_hedef geçersiz.', 400)

    yogunluk_hedef = None
    if payload.get('yogunluk_hedef') not in (None, ''):
        try:
            yogunluk_hedef = float(payload['yogunluk_hedef'])
        except (TypeError, ValueError):
            raise NxArError('yogunluk_hedef geçersiz.', 400)

    primary_uv = next(
        (k for k in kaynaklar if k['boyut'] in ('LARGE', 'MEDIUM')),
        kaynaklar[0],
    )
    test_batch_kg = round(sum(k['test_miktar_kg'] for k in kalemler), 4)
    simdi = _now()
    arge_kodu = _nx_ar_kod_uret(con)
    test_no = _test_no_uret(con, calisma_tipi)
    test_tipi = 'FORMUL_TEST' if calisma_tipi == 'YENI_FORMUL' else 'RENK_TEST'
    talep = (payload.get('talep_referansi') or '').strip() or None
    urun_ailesi = (payload.get('urun_ailesi') or '').strip() or None
    formul_grup_adi = (payload.get('formul_grup_adi') or '').strip() or None
    renk_kodu = (payload.get('renk_kodu') or '').strip() or None
    lot_no = (deneme_in.get('lot_no') or '').strip() or None
    genel_not = (deneme_in.get('genel_not') or '').strip() or None
    renk_bilesenleri = payload.get('renk_bilesenleri')
    renk_bilesenleri_json = None
    if renk_bilesenleri is not None:
        import json
        if not isinstance(renk_bilesenleri, list):
            raise NxArError('renk_bilesenleri liste olmalı.', 400)
        renk_bilesenleri_json = json.dumps(renk_bilesenleri, ensure_ascii=False)

    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute(
            """
            INSERT INTO nexgen_arge_test (
                kaynak_uretim_varyant_id, test_no, test_tipi, makina,
                test_batch_kg, kaynak_batch_kg, yeni_renk_adi, notlar, durum,
                cari_id, shore_hedef, lot_no, talep_referansi,
                olusturan_id, olusturma_tarihi, aktif, arge_kodu, numune_orani,
                aktif_rev_no, basarili_mi, aktarildi_mi,
                calisma_tipi, guncelleme_tarihi, sorumlu_kullanici_id, oncelik,
                urun_ailesi, formul_grup_adi, ana_formul_grup_kodu, renk_kodu,
                yogunluk_hedef, saha_testi_gerekli_mi, saha_testi_nedeni,
                saha_testi_karar_veren_id, saha_testi_karar_tarihi,
                renk_bilesenleri_json
            ) VALUES (
                ?, ?, ?, '—',
                ?, 0, ?, ?, 'ARGE_HAZIR',
                ?, ?, ?, ?,
                ?, ?, 1, ?, ?,
                0, 0, 0,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?
            )
            """,
            (
                primary_uv['kaynak_uretim_varyant_id'],
                test_no,
                test_tipi,
                test_batch_kg,
                hedef,
                genel_not or talep,
                cari_id,
                shore_hedef,
                lot_no,
                talep,
                kullanici_id,
                simdi,
                arge_kodu,
                numune_orani,
                calisma_tipi,
                simdi,
                kullanici_id,
                oncelik,
                urun_ailesi,
                formul_grup_adi,
                ana_grup,
                renk_kodu,
                yogunluk_hedef,
                saha_mi,
                saha_neden,
                kullanici_id if saha_neden else None,
                simdi if saha_neden else None,
                renk_bilesenleri_json,
            ),
        )
        test_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])

        for k in kaynaklar:
            con.execute(
                """
                INSERT INTO nexgen_arge_kaynak_uv (
                    arge_test_id, boyut, kaynak_uretim_varyant_id, sira_no, aktif_mi, created_at
                ) VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    test_id,
                    k['boyut'],
                    k['kaynak_uretim_varyant_id'],
                    k['sira_no'],
                    simdi,
                ),
            )

        con.execute(
            """
            INSERT INTO nexgen_arge_deneme (
                arge_test_id, deneme_no, durum, aktif_mi, deneme_tarihi,
                hazirlayan_kullanici_id, numune_orani, lot_no, genel_not,
                created_at, updated_at
            ) VALUES (?, 1, 'HAZIR', 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                test_id, simdi, kullanici_id, numune_orani, lot_no, genel_not,
                simdi, simdi,
            ),
        )
        deneme_id = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])

        for k in kalemler:
            con.execute(
                """
                INSERT INTO nexgen_arge_deneme_kalem (
                    deneme_id, boyut, kaynak_uv_id, stok_kart_id, sira,
                    orjinal_miktar_kg, test_miktar_kg, aciklama, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deneme_id, k['boyut'], k['kaynak_uv_id'], k['stok_kart_id'],
                    k['sira'], k['orjinal_miktar_kg'], k['test_miktar_kg'],
                    k['aciklama'], simdi,
                ),
            )

        # REV-0 audit satırı (mevcut revizyon tablosu)
        con.execute(
            """
            INSERT INTO nexgen_arge_revizyon (
                test_id, rev_no, onceki_rev_no, neden, ne_degisti, revizyon_notu,
                snapshot_json, degisiklik_json, olusturan_id, olusturma_tarihi,
                basarili_mi, kilitli_mi, deneme_id
            ) VALUES (?, 0, NULL, 'NX-AR create', '[]', NULL, '{}', '[]', ?, ?, 0, 0, ?)
            """,
            (test_id, kullanici_id, simdi, deneme_id),
        )

        con.execute('COMMIT')
    except NxArError:
        try:
            con.execute('ROLLBACK')
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            con.execute('ROLLBACK')
        except Exception:
            pass
        raise NxArError(f'Kayıt hatası: {e}', 500, 'DB') from e

    return get_nx_ar(con, test_id)


_BOYUT_HARF = {'LARGE': 'L', 'SMALL': 'S', 'MEDIUM': 'M'}
_BOYUT_SIRA = {'LARGE': 0, 'SMALL': 1, 'MEDIUM': 2}


def _boyut_etiket(boyutlar: list[str]) -> str:
    harf = []
    for b in sorted(boyutlar, key=lambda x: _BOYUT_SIRA.get(x, 9)):
        h = _BOYUT_HARF.get(b)
        if h and h not in harf:
            harf.append(h)
    return '+'.join(harf) if harf else '—'


def get_nx_ar(con, arge_test_id: int) -> dict:
    """NX-AR detay — tek kart payload (batch join, N+1 yok)."""
    row = con.execute(
        'SELECT * FROM nexgen_arge_test WHERE id=? AND aktif=1',
        (arge_test_id,),
    ).fetchone()
    if not row:
        raise NxArError('NX-AR kartı bulunamadı.', 404, 'YOK')
    t = dict(row)
    if not (t.get('arge_kodu') or '').startswith('NX-AR-'):
        raise NxArError('Kayıt NX-AR kartı değil.', 404, 'YOK')

    kaynaklar = [
        dict(r) for r in con.execute(
            """
            SELECT id, boyut, kaynak_uretim_varyant_id, sira_no, aktif_mi, created_at
            FROM nexgen_arge_kaynak_uv
            WHERE arge_test_id=? AND aktif_mi=1
            ORDER BY sira_no, id
            """,
            (arge_test_id,),
        ).fetchall()
    ]

    # Kaynak UV → RV → formül (tek IN sorgusu)
    uv_ids = [k['kaynak_uretim_varyant_id'] for k in kaynaklar if k.get('kaynak_uretim_varyant_id')]
    uv_map: dict[int, dict] = {}
    if uv_ids:
        ph = ','.join('?' * len(uv_ids))
        for r in con.execute(
            f"""
            SELECT uv.id AS uv_id, uv.ad AS uv_ad, uv.boyut AS uv_boyut,
                   rv.id AS rv_id, rv.ad AS rv_ad,
                   f.id AS formul_id, f.kod AS formul_kod, f.ad AS formul_ad
            FROM nexgen_uretim_varyant uv
            LEFT JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
            LEFT JOIN nexgen_formul f ON f.id = rv.formul_id
            WHERE uv.id IN ({ph})
            """,
            uv_ids,
        ).fetchall():
            uv_map[int(r['uv_id'])] = dict(r)
    for k in kaynaklar:
        meta = uv_map.get(int(k['kaynak_uretim_varyant_id'] or 0)) or {}
        k['uv_ad'] = meta.get('uv_ad')
        k['uv_kod'] = meta.get('uv_ad')  # UV ad/kod gösterim
        k['rv_id'] = meta.get('rv_id')
        k['rv_ad'] = meta.get('rv_ad')
        k['formul_id'] = meta.get('formul_id')
        k['formul_kod'] = meta.get('formul_kod')
        k['formul_ad'] = meta.get('formul_ad')

    deneme = con.execute(
        """
        SELECT * FROM nexgen_arge_deneme
        WHERE arge_test_id=? AND aktif_mi=1
        ORDER BY deneme_no DESC LIMIT 1
        """,
        (arge_test_id,),
    ).fetchone()
    deneme_d = dict(deneme) if deneme else None
    kalemler = []
    if deneme_d:
        kalemler = [
            dict(r) for r in con.execute(
                """
                SELECT id, deneme_id, boyut, kaynak_uv_id, stok_kart_id, sira,
                       orjinal_miktar_kg, test_miktar_kg, aciklama, created_at
                FROM nexgen_arge_deneme_kalem
                WHERE deneme_id=?
                ORDER BY boyut, sira, id
                """,
                (deneme_d['id'],),
            ).fetchall()
        ]
        stok_ids = sorted({int(k['stok_kart_id']) for k in kalemler if k.get('stok_kart_id')})
        stok_map: dict[int, dict] = {}
        if stok_ids:
            ph = ','.join('?' * len(stok_ids))
            for r in con.execute(
                f"""
                SELECT id, kod, ad, kategori
                FROM nexgen_stok_kart WHERE id IN ({ph})
                """,
                stok_ids,
            ).fetchall():
                stok_map[int(r['id'])] = dict(r)
        for k in kalemler:
            sk = stok_map.get(int(k['stok_kart_id'] or 0)) or {}
            k['stok_kod'] = sk.get('kod')
            k['stok_ad'] = sk.get('ad')
            k['kategori'] = sk.get('kategori')

    # Cari + kullanıcılar (batch)
    cari = None
    if t.get('cari_id'):
        cr = con.execute(
            'SELECT id, cari_kod, unvan FROM nexgen_cari WHERE id=?',
            (t['cari_id'],),
        ).fetchone()
        cari = dict(cr) if cr else None

    uid_set = []
    for key in ('olusturan_id', 'sorumlu_kullanici_id'):
        if t.get(key):
            uid_set.append(int(t[key]))
    user_map: dict[int, str] = {}
    if uid_set:
        ph = ','.join('?' * len(uid_set))
        for r in con.execute(
            f'SELECT Id, KullaniciAdi FROM sistem_kullanici WHERE Id IN ({ph})',
            uid_set,
        ).fetchall():
            user_map[int(r['Id'])] = r['KullaniciAdi']

    boyutlar = sorted(
        {str(k['boyut']).upper() for k in kaynaklar if k.get('boyut')},
        key=lambda x: _BOYUT_SIRA.get(x, 9),
    )

    # Boyut sonuçları — boş olsa bile boyut iskeleti
    boyut_sonuc_map: dict[str, dict] = {}
    if deneme_d:
        for r in con.execute(
            """
            SELECT * FROM nexgen_arge_boyut_sonuc
            WHERE deneme_id=? ORDER BY boyut
            """,
            (deneme_d['id'],),
        ).fetchall():
            boyut_sonuc_map[str(r['boyut']).upper()] = dict(r)
    boyut_sonuclar = []
    for b in boyutlar or ['LARGE']:
        mevcut = boyut_sonuc_map.get(b) or {
            'boyut': b,
            'shore_sonuc': None,
            'yogunluk': None,
            'pisme_suresi_dk': None,
            'renk_sonucu': None,
            'kalip_sonucu': None,
        }
        boyut_sonuclar.append(mevcut)

    # Kalemleri boyuta göre grupla (şablon kolaylığı)
    kalemler_by_boyut: dict[str, list] = {b: [] for b in boyutlar}
    for k in kalemler:
        b = str(k.get('boyut') or '').upper()
        if b not in kalemler_by_boyut:
            kalemler_by_boyut[b] = []
        kalemler_by_boyut[b].append(k)

    revizyonlar = [
        dict(r) for r in con.execute(
            """
            SELECT id, rev_no, onceki_rev_no, neden, revizyon_notu,
                   olusturan_id, olusturan_adi, olusturma_tarihi
            FROM nexgen_arge_revizyon
            WHERE test_id=?
            ORDER BY rev_no DESC
            """,
            (arge_test_id,),
        ).fetchall()
    ]

    rf = None
    if t.get('rf_renk_id'):
        rf_row = con.execute(
            """
            SELECT id, rf_kod, ad, durum, aktif
            FROM nexgen_rf_renk WHERE id=?
            """,
            (t['rf_renk_id'],),
        ).fetchone()
        rf = dict(rf_row) if rf_row else None

    uretim_kodlari = [
        dict(r) for r in con.execute(
            """
            SELECT id, boyut, olusan_uv_id, olusan_rv_id, formul_id,
                   uretim_kodu, created_at
            FROM nexgen_arge_olusan_uv
            WHERE arge_test_id=?
            ORDER BY boyut
            """,
            (arge_test_id,),
        ).fetchall()
    ]

    olusturan_ad = user_map.get(int(t['olusturan_id'])) if t.get('olusturan_id') else None
    sorumlu_ad = user_map.get(int(t['sorumlu_kullanici_id'])) if t.get('sorumlu_kullanici_id') else None

    gecmis = [{
        'olay': 'olusturuldu',
        'kullanici': olusturan_ad or '—',
        'tarih': t.get('olusturma_tarihi'),
    }]

    return {
        'ok': True,
        'arge_test_id': t['id'],
        'arge_kodu': t.get('arge_kodu'),
        'test_no': t.get('test_no'),
        'durum': t.get('durum'),
        'calisma_tipi': t.get('calisma_tipi'),
        'cari_id': t.get('cari_id'),
        'cari_kod': (cari or {}).get('cari_kod'),
        'cari_unvan': (cari or {}).get('unvan'),
        'oncelik': t.get('oncelik'),
        'urun_ailesi': t.get('urun_ailesi'),
        'formul_grup_adi': t.get('formul_grup_adi'),
        'ana_formul_grup_kodu': t.get('ana_formul_grup_kodu'),
        'renk_kodu': t.get('renk_kodu'),
        'hedef_renk_adi': t.get('yeni_renk_adi'),
        'shore_hedef': t.get('shore_hedef'),
        'yogunluk_hedef': t.get('yogunluk_hedef'),
        'talep_referansi': t.get('talep_referansi'),
        'saha_testi_gerekli_mi': t.get('saha_testi_gerekli_mi'),
        'saha_testi_nedeni': t.get('saha_testi_nedeni'),
        'boyutlar': boyutlar,
        'boyut_etiket': _boyut_etiket(boyutlar),
        'kaynak_uvler': kaynaklar,
        'deneme': deneme_d,
        'kalemler': kalemler,
        'kalemler_by_boyut': kalemler_by_boyut,
        'boyut_sonuclar': boyut_sonuclar,
        'revizyonlar': revizyonlar,
        'rf': rf,
        'uretim_kodlari': uretim_kodlari,
        'olusturan_id': t.get('olusturan_id'),
        'olusturan_ad': olusturan_ad,
        'sorumlu_kullanici_id': t.get('sorumlu_kullanici_id'),
        'sorumlu_ad': sorumlu_ad,
        'olusturma_tarihi': t.get('olusturma_tarihi'),
        'guncelleme_tarihi': t.get('guncelleme_tarihi'),
        'gecmis': gecmis,
    }


def list_nx_ar(con, *, limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    rows = [
        dict(r) for r in con.execute(
            """
            SELECT id, arge_kodu, test_no, durum, calisma_tipi, cari_id,
                   oncelik, urun_ailesi, formul_grup_adi, ana_formul_grup_kodu,
                   renk_kodu, yeni_renk_adi AS hedef_renk_adi,
                   saha_testi_gerekli_mi, olusturma_tarihi, guncelleme_tarihi
            FROM nexgen_arge_test
            WHERE aktif=1 AND arge_kodu LIKE 'NX-AR-%'
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    ]
    total = con.execute(
        "SELECT COUNT(*) FROM nexgen_arge_test WHERE aktif=1 AND arge_kodu LIKE 'NX-AR-%'"
    ).fetchone()[0]
    return {'ok': True, 'total': total, 'items': rows}


# Kanonik CREATE örneği (dokümantasyon / test) — legacy UV YOK
CANONICAL_CREATE_PAYLOAD_DOC = {
    'calisma_tipi': 'MUSTERI_RENK',
    'cari_id': 1,
    'oncelik': 'NORMAL',
    'urun_ailesi': 'TERLIK',
    'formul_grup_adi': 'TERLIK 18-28',
    'ana_formul_grup_kodu': '1BA',
    'renk_kodu': '0030',
    'hedef_renk_adi': 'GRI',
    'shore_hedef': 42,
    'yogunluk_hedef': 0.25,
    'talep_referansi': 'Müşteri renk talebi',
    'saha_testi_gerekli_mi': 0,
    'saha_testi_nedeni': None,
    'kaynak_uvler': [
        {'boyut': 'LARGE', 'kaynak_uretim_varyant_id': 10100, 'sira_no': 1},
        {'boyut': 'SMALL', 'kaynak_uretim_varyant_id': 10101, 'sira_no': 2},
    ],
    'deneme': {
        'numune_orani': 10,
        'lot_no': None,
        'genel_not': None,
        'kalemler': [
            {
                'boyut': 'LARGE',
                'stok_kart_id': 14,
                'test_miktar_kg': 0.01,
                'sira': 1,
            },
            {
                'boyut': 'SMALL',
                'stok_kart_id': 14,
                'test_miktar_kg': 0.008,
                'sira': 1,
            },
        ],
    },
}
