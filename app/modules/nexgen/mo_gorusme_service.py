# -*- coding: utf-8 -*-
"""Müşteri Operasyonu görüşme kaydı — MVP servis."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from modules.nexgen.cari_sorumlu_service import can_view_cari, load_kullanici_yetkileri
from modules.nexgen.cari360_yetki import can_cari360_view_all, can_cari360_view_own
from modules.nexgen.mo_gorusme_config import (
    GORUSME_GUN_ESIK,
    GORUSME_TIPLERI,
    KAYNAK_MUSTERI_OPERASYONU,
    ONCELIKLER,
    SIPARIS_ZIYARET_ESIK_GUN,
    SONUC_TIPLERI,
    TABLO,
)


class MoGorusmeError(Exception):
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


def _kullanici_cari_atanmis(con, kullanici_id: int, cari_id: int) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM cari_sorumlu
        WHERE kullanici_id=? AND cari_id=? AND sorumluluk_rolu IN ('ANA','YEDEK','DESTEK')
          AND aktif=1 AND (bitis_tarihi IS NULL OR bitis_tarihi=''
               OR bitis_tarihi > datetime('now','localtime'))
        """,
        (kullanici_id, cari_id),
    ).fetchone()
    return bool(row)


def can_mo_gorusme_yaz(
    con: sqlite3.Connection,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_view_cari(con, kullanici_id, cari_id, yk):
        return False
    if can_cari360_view_all(yk):
        return True
    if can_cari360_view_own(yk):
        return _kullanici_cari_atanmis(con, kullanici_id, cari_id)
    return False


def timeline_olay_sozlesmesi(kayit: dict[str, Any]) -> dict[str, Any]:
    """Cari 360 timeline — olay motoru henüz aktif değil; sözleşme hazır."""
    return {
        'olay_tipi': 'MUSTERI_OPERASYONU_GORUSME',
        'kaynak_modul': KAYNAK_MUSTERI_OPERASYONU,
        'kaynak_id': kayit.get('id'),
        'cari_id': kayit.get('cari_id'),
        'baslik': f"Görüşme — {kayit.get('gorusme_tipi', '')}",
        'ozet': (kayit.get('kisa_not') or '')[:200],
        'tarih': kayit.get('gorusme_tarihi'),
        'olay_motoru_aktif': False,
    }


def _row_dict(r) -> dict[str, Any]:
    d = dict(r)
    d['kullanici_adi'] = d.get('kullanici_adi') or ''
    return d


def _validate_payload(payload: dict) -> dict[str, Any]:
    tip = (payload.get('gorusme_tipi') or '').strip()
    if tip not in GORUSME_TIPLERI:
        raise MoGorusmeError('Geçerli görüşme tipi seçin.', 400)

    sonuc = (payload.get('sonuc_tipi') or '').strip()
    if sonuc not in SONUC_TIPLERI:
        raise MoGorusmeError('Geçerli görüşme sonucu seçin.', 400)

    kisa = (payload.get('kisa_not') or '').strip()
    if len(kisa) < 3:
        raise MoGorusmeError('Kısa görüşme notu zorunlu (en az 3 karakter).', 400)

    gt = (payload.get('gorusme_tarihi') or '').strip()
    if not gt:
        gt = _now()
    elif len(gt) == 10:
        gt = gt + ' 12:00:00'

    oncelik = (payload.get('oncelik') or 'NORMAL').strip().upper()
    if oncelik not in ONCELIKLER:
        oncelik = 'NORMAL'

    idem = (payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MoGorusmeError('idempotency_key zorunlu.', 400)

    cari_id = payload.get('cari_id')
    if not cari_id:
        raise MoGorusmeError('cari_id zorunlu.', 400)

    def _opt_float(v):
        if v in (None, ''):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _opt_int(v):
        if v in (None, ''):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {
        'cari_id': int(cari_id),
        'gorusme_tipi': tip,
        'sonuc_tipi': sonuc,
        'sonuc_etiketler': json.dumps(payload.get('sonuc_etiketler') or [], ensure_ascii=False),
        'kisa_not': kisa,
        'gorusme_tarihi': gt,
        'sonraki_takip_tarihi': (payload.get('sonraki_takip_tarihi') or '').strip() or None,
        'oncelik': oncelik,
        'tahmini_siparis_tutari': _opt_float(payload.get('tahmini_siparis_tutari')),
        'tahmini_siparis_tarihi': (payload.get('tahmini_siparis_tarihi') or '').strip() or None,
        'istenen_vade_gun': _opt_int(payload.get('istenen_vade_gun')),
        'cek_alim_tarihi': (payload.get('cek_alim_tarihi') or '').strip() or None,
        'rakip_firma': (payload.get('rakip_firma') or '').strip() or None,
        'makina_notu': (payload.get('makina_notu') or '').strip() or None,
        'detay_not': (payload.get('detay_not') or '').strip() or None,
        'dosya_ref': (payload.get('dosya_ref') or '').strip() or None,
        'idempotency_key': idem,
    }


def gorusme_kaydet(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    if not _tablo_var(con, TABLO):
        raise MoGorusmeError('Görüşme tablosu hazır değil.', 503)

    norm = _validate_payload(payload)
    if not can_mo_gorusme_yaz(con, kullanici_id, norm['cari_id'], yk):
        raise MoGorusmeError('Bu cari için görüşme yazma yetkiniz yok.', 403)

    mevcut = con.execute(
        f'SELECT id FROM {TABLO} WHERE idempotency_key=? AND aktif=1',
        (norm['idempotency_key'],),
    ).fetchone()
    if mevcut:
        return gorusme_detay(con, int(mevcut['id']), kullanici_id, yk)

    cari = con.execute(
        'SELECT id, cari_kod, unvan FROM nexgen_cari WHERE id=? AND aktif=1',
        (norm['cari_id'],),
    ).fetchone()
    if not cari:
        raise MoGorusmeError('Cari bulunamadı.', 404)

    audit = json.dumps({
        'islem': 'OLUSTUR',
        'kullanici_id': kullanici_id,
        'tarih': _now(),
    }, ensure_ascii=False)

    cur = con.execute(
        f"""
        INSERT INTO {TABLO} (
            cari_id, kullanici_id, kaynak, gorusme_tipi, sonuc_tipi, sonuc_etiketler,
            kisa_not, gorusme_tarihi, sonraki_takip_tarihi, oncelik,
            tahmini_siparis_tutari, tahmini_siparis_tarihi, istenen_vade_gun,
            cek_alim_tarihi, rakip_firma, makina_notu, detay_not, dosya_ref,
            idempotency_key, olusturan_kullanici_id, audit_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            norm['cari_id'], kullanici_id, KAYNAK_MUSTERI_OPERASYONU,
            norm['gorusme_tipi'], norm['sonuc_tipi'], norm['sonuc_etiketler'],
            norm['kisa_not'], norm['gorusme_tarihi'], norm['sonraki_takip_tarihi'],
            norm['oncelik'], norm['tahmini_siparis_tutari'], norm['tahmini_siparis_tarihi'],
            norm['istenen_vade_gun'], norm['cek_alim_tarihi'], norm['rakip_firma'],
            norm['makina_notu'], norm['detay_not'], norm['dosya_ref'],
            norm['idempotency_key'], kullanici_id, audit,
        ),
    )
    con.commit()
    gid = int(cur.lastrowid)
    detay = gorusme_detay(con, gid, kullanici_id, yk)
    detay['timeline_sozlesme'] = timeline_olay_sozlesmesi(detay)
    return detay


def gorusme_detay(
    con: sqlite3.Connection,
    gorusme_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    row = con.execute(
        f"""
        SELECT g.*, sk.KullaniciAdi AS kullanici_adi
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.id=? AND g.aktif=1
        """,
        (gorusme_id,),
    ).fetchone()
    if not row:
        raise MoGorusmeError('Görüşme kaydı bulunamadı.', 404)
    if not can_view_cari(con, kullanici_id, int(row['cari_id']), yk):
        raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
    return _row_dict(row)


def list_gorusmeler(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not can_view_cari(con, kullanici_id, cari_id, yk):
        raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
    if not _tablo_var(con, TABLO):
        return []
    rows = con.execute(
        f"""
        SELECT g.*, sk.KullaniciAdi AS kullanici_adi
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.cari_id=? AND g.aktif=1
        ORDER BY g.gorusme_tarihi DESC, g.id DESC
        LIMIT ?
        """,
        (cari_id, limit),
    ).fetchall()
    return [_row_dict(r) for r in rows]


def son_gorusme_ozet_map(
    con: sqlite3.Connection,
    cari_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not cari_ids or not _tablo_var(con, TABLO):
        return {}
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT g.*, sk.KullaniciAdi AS kullanici_adi
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.cari_id IN ({ph}) AND g.aktif=1
        ORDER BY g.gorusme_tarihi DESC, g.id DESC
        """,
        cari_ids,
    ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        cid = int(r['cari_id'])
        if cid not in out:
            out[cid] = _row_dict(r)
    return out


def son_gorusmeler_grup(
    con: sqlite3.Connection,
    cari_ids: list[int],
    limit_per_cari: int = 3,
) -> dict[int, list[dict[str, Any]]]:
    if not cari_ids or not _tablo_var(con, TABLO):
        return {}
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT g.*, sk.KullaniciAdi AS kullanici_adi
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.cari_id IN ({ph}) AND g.aktif=1
        ORDER BY g.gorusme_tarihi DESC, g.id DESC
        """,
        cari_ids,
    ).fetchall()
    out: dict[int, list] = {cid: [] for cid in cari_ids}
    for r in rows:
        cid = int(r['cari_id'])
        if len(out.get(cid, [])) < limit_per_cari:
            out.setdefault(cid, []).append(_row_dict(r))
    return out


def sorumlu_pazarlamaci_adi(con, cari_id: int) -> str | None:
    row = con.execute(
        """
        SELECT sk.KullaniciAdi
        FROM cari_sorumlu cs
        JOIN sistem_kullanici sk ON sk.Id = cs.kullanici_id
        WHERE cs.cari_id=? AND cs.sorumluluk_rolu='ANA' AND cs.aktif=1
          AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi=''
               OR cs.bitis_tarihi > datetime('now','localtime'))
        LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    return row['KullaniciAdi'] if row else None


def bugunun_gorusme_sayaclari(
    con: sqlite3.Connection,
    cari_ids: list[int],
) -> dict[str, int]:
    today = _today()
    week_end = (date.today() + timedelta(days=7 - date.today().weekday())).isoformat()
    out = {'bugun_cek': 0, 'bugun_ziyaret': 0, 'bugun_aranacak': 0, 'takip_bugun': 0, 'takip_hafta': 0}
    if not cari_ids or not _tablo_var(con, TABLO):
        return out
    ph = ','.join(['?'] * len(cari_ids))

    out['bugun_ziyaret'] = int(con.execute(
        f"""
        SELECT COUNT(*) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND substr(gorusme_tarihi,1,10)=?
          AND gorusme_tipi='Ziyaret'
        """,
        [*cari_ids, today],
    ).fetchone()[0] or 0)

    out['bugun_aranacak'] = int(con.execute(
        f"""
        SELECT COUNT(*) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND sonraki_takip_tarihi=?
          AND gorusme_tipi IN ('Telefon','WhatsApp')
        """,
        [*cari_ids, today],
    ).fetchone()[0] or 0)

    out['bugun_cek'] = int(con.execute(
        f"""
        SELECT COUNT(*) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND (cek_alim_tarihi=? OR (sonraki_takip_tarihi=? AND sonuc_tipi='Çek / Tahsilat Görüşüldü'))
        """,
        [*cari_ids, today, today],
    ).fetchone()[0] or 0)

    out['takip_bugun'] = int(con.execute(
        f"""
        SELECT COUNT(DISTINCT cari_id) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1 AND sonraki_takip_tarihi=?
        """,
        [*cari_ids, today],
    ).fetchone()[0] or 0)

    out['takip_hafta'] = int(con.execute(
        f"""
        SELECT COUNT(DISTINCT cari_id) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND sonraki_takip_tarihi > ? AND sonraki_takip_tarihi <= ?
        """,
        [*cari_ids, today, week_end],
    ).fetchone()[0] or 0)

    return out


def _gun_farki(tarih_str: str | None) -> int:
    if not tarih_str:
        return 9999
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(str(tarih_str)[:19], fmt)
            return max(0, (datetime.now() - dt).days)
        except ValueError:
            continue
    return 9999


def gorusme_oneri_kaynaklari(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict[str, Any]]:
    """Akıllı öneriler için görüşme tabanlı kaynaklar."""
    if not cari_ids or not _tablo_var(con, TABLO):
        return []
    today = _today()
    week_end = (date.today() + timedelta(days=7 - date.today().weekday())).isoformat()
    son_map = son_gorusme_ozet_map(con, cari_ids)
    oneriler: list[dict] = []

    for cid in cari_ids:
        info = cari_map.get(cid) or {}
        unvan = info.get('unvan') or '—'
        son = son_map.get(cid)
        if son:
            gun = _gun_farki(son.get('gorusme_tarihi'))
            if gun >= GORUSME_GUN_ESIK:
                oneriler.append({
                    'cari_id': cid, 'musteri': unvan, 'tip': 'gorusme_esik',
                    'surec_tipi': 'Ziyaret',
                    'surec_asama': 'Ziyaret gerekli',
                    'neden': f'Müşteri {gun} gündür ziyaret edilmedi',
                    'aksiyon': 'Görüşme Kaydet',
                })
            takip = (son.get('sonraki_takip_tarihi') or '')[:10]
            if takip == today:
                oneriler.append({
                    'cari_id': cid, 'musteri': unvan, 'tip': 'takip_bugun',
                    'surec_tipi': 'Ziyaret',
                    'surec_asama': 'Takip tarihi bugün',
                    'neden': 'Takip tarihi bugün',
                    'aksiyon': 'Görüşme Kaydet',
                })
            elif takip and today < takip <= week_end:
                oneriler.append({
                    'cari_id': cid, 'musteri': unvan, 'tip': 'takip_hafta',
                    'surec_tipi': 'Ziyaret',
                    'surec_asama': 'Takip bu hafta',
                    'neden': 'Takip tarihi bu hafta',
                    'aksiyon': 'Görüşme Kaydet',
                })

    return oneriler
