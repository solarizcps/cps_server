# -*- coding: utf-8 -*-
"""
Cari genel bilgiler — FAZ-YONETIM-CARI360-GENEL-BILGILER-TAMAMLAMA-1

Whitelist okuma/yazma + yönetici / pazarlamacı yetki ayrımı.
Finans alanları yok. cari_kod / aktif / sorumlu bu servisten yazılmaz.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.cari360_yetki import (
    _yk_has,
    can_cari360_crm_write,
    can_cari360_view_all,
)
from modules.nexgen.cari_sorumlu_service import can_view_cari, can_write_crm, load_kullanici_yetkileri

CARI_TIPI_VALUES = ('MUSTERI', 'TEDARIKCI', 'HER_IKISI')
YURT_DURUMU_VALUES = ('YURTICI', 'YURTDISI')
PARA_BIRIMI_VALUES = ('TRY', 'USD', 'EUR', 'GBP')
DIL_VALUES = ('TR', 'EN', 'DE', 'FR', 'AR')

# Pazarlamacı + yönetici ortak güncellenebilir alanlar
GENEL_EDIT_FIELDS: tuple[str, ...] = (
    'kisa_ad', 'cari_tipi', 'kategori', 'yurt_durumu',
    'vergi_dairesi', 'vergi_no', 'tc_kimlik_no', 'ticaret_sicil_no', 'mersis_no',
    'e_fatura_mukellefi', 'e_irsaliye_mukellefi',
    'telefon', 'telefon2', 'eposta', 'web', 'kep', 'fax',
    'ulke', 'sehir', 'ilce', 'acik_adres',
    'para_birimi', 'odeme_vadesi_gun', 'fiyat_grubu', 'iskonto_orani',
    'minimum_siparis_kg', 'teslim_sekli', 'dil',
)

# Yalnız yönetici
ADMIN_ONLY_FIELDS: tuple[str, ...] = ('unvan',)

ALL_WRITABLE = GENEL_EDIT_FIELDS + ADMIN_ONLY_FIELDS

SELECT_COLS = (
    'id', 'cari_kod', 'unvan', 'aktif', 'created_at', 'updated_at',
) + GENEL_EDIT_FIELDS


class CariGenelError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def is_cari_admin(yk: set[str] | None) -> bool:
    """Yönetici: nexgen.yonetim.manage manage/create veya *."""
    if not yk:
        return False
    if '*' in yk:
        return True
    return (
        _yk_has(yk, 'nexgen.yonetim.manage', 'can_manage')
        or _yk_has(yk, 'nexgen.yonetim.manage', 'can_create')
    )


def can_access_cari_listesi(yk: set[str] | None) -> bool:
    if not yk:
        return False
    if is_cari_admin(yk) or _yk_has(yk, 'nexgen.yonetim.manage', 'can_view'):
        return True
    if can_cari360_view_all(yk):
        return True
    return (
        _yk_has(yk, 'cari360.view_own', 'can_view')
        or can_cari360_crm_write(yk)
        or _yk_has(yk, 'cari360.view', 'can_view')
    )


def can_edit_cari_genel(
    con: sqlite3.Connection,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if is_cari_admin(yk):
        return True
    return can_write_crm(con, kullanici_id, cari_id, yk)


def _norm_text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _norm_bool01(v: Any) -> int | None:
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return 1 if int(v) else 0
    s = str(v).strip().lower()
    if s in ('1', 'true', 'evet', 'yes', 'on'):
        return 1
    if s in ('0', 'false', 'hayir', 'no', 'off'):
        return 0
    raise CariGenelError('Boolean alan geçersiz.', 400)


def _norm_int(v: Any) -> int | None:
    if v is None or v == '':
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise CariGenelError('Sayısal alan geçersiz.', 400)


def _norm_real(v: Any) -> float | None:
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise CariGenelError('Sayısal alan geçersiz.', 400)


def parse_genel_payload(
    payload: dict[str, Any],
    *,
    allow_admin_fields: bool,
) -> dict[str, Any]:
    """Whitelist parse. Bilinmeyen alanlar yok sayılır."""
    out: dict[str, Any] = {}
    allowed = set(GENEL_EDIT_FIELDS)
    if allow_admin_fields:
        allowed |= set(ADMIN_ONLY_FIELDS)

    for key in allowed:
        if key not in payload:
            continue
        raw = payload[key]
        if key in ('e_fatura_mukellefi', 'e_irsaliye_mukellefi'):
            out[key] = _norm_bool01(raw)
        elif key == 'odeme_vadesi_gun':
            n = _norm_int(raw)
            if n is not None and n < 0:
                raise CariGenelError('Ödeme vadesi negatif olamaz.', 400)
            out[key] = n
        elif key in ('iskonto_orani', 'minimum_siparis_kg'):
            n = _norm_real(raw)
            if n is not None and n < 0:
                label = 'İskonto oranı' if key == 'iskonto_orani' else 'Minimum sipariş'
                raise CariGenelError(f'{label} negatif olamaz.', 400)
            out[key] = n
        elif key == 'cari_tipi':
            t = _norm_text(raw)
            if t and t.upper() not in CARI_TIPI_VALUES:
                raise CariGenelError('Cari tipi geçersiz.', 400)
            out[key] = t.upper() if t else None
        elif key == 'yurt_durumu':
            t = _norm_text(raw)
            if t and t.upper() not in YURT_DURUMU_VALUES:
                raise CariGenelError('Yurt durumu geçersiz.', 400)
            out[key] = t.upper() if t else None
        elif key == 'para_birimi':
            t = _norm_text(raw)
            if t and t.upper() not in PARA_BIRIMI_VALUES:
                raise CariGenelError('Para birimi geçersiz.', 400)
            out[key] = t.upper() if t else None
        elif key == 'dil':
            t = _norm_text(raw)
            if t and t.upper() not in DIL_VALUES:
                raise CariGenelError('Dil geçersiz.', 400)
            out[key] = t.upper() if t else None
        else:
            out[key] = _norm_text(raw)

    # cari_kod asla yazılmaz
    if 'cari_kod' in payload and payload.get('cari_kod') not in (None, ''):
        # sessizce yok say (admin de kod değiştiremez bu endpoint ile)
        pass
    return out


def _cols_available(con: sqlite3.Connection) -> set[str]:
    return {c[1] for c in con.execute('PRAGMA table_info(nexgen_cari)').fetchall()}


def load_cari_genel(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_view_cari(con, kullanici_id, cari_id, yk):
        raise CariGenelError('Bu cari için görüntüleme yetkiniz yok.', 403)

    avail = _cols_available(con)
    sel = [c for c in SELECT_COLS if c in avail]
    row = con.execute(
        f"SELECT {', '.join(sel)} FROM nexgen_cari WHERE id=?",
        (int(cari_id),),
    ).fetchone()
    if not row:
        raise CariGenelError('Cari bulunamadı.', 404)

    d = {k: row[k] if k in row.keys() else None for k in SELECT_COLS}
    d['id'] = int(row['id'])
    d['aktif'] = int(row['aktif'] or 0)
    return d


def update_cari_genel(
    con: sqlite3.Connection,
    cari_id: int,
    payload: dict[str, Any],
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)

    row = con.execute('SELECT id FROM nexgen_cari WHERE id=?', (int(cari_id),)).fetchone()
    if not row:
        raise CariGenelError('Cari bulunamadı.', 404)

    admin = is_cari_admin(yk)
    if not admin and not can_write_crm(con, kullanici_id, cari_id, yk):
        raise CariGenelError('Bu cari için düzenleme yetkiniz yok.', 403)

    # Unvan gönderilmiş ama pazarlamacı → 403
    if (not admin) and 'unvan' in payload and payload.get('unvan') not in (None,):
        # yalnızca gerçekten değiştirme denemesi
        cur_u = con.execute('SELECT unvan FROM nexgen_cari WHERE id=?', (cari_id,)).fetchone()
        if _norm_text(payload.get('unvan')) != _norm_text(cur_u['unvan'] if cur_u else None):
            raise CariGenelError('Firma ünvanını değiştirme yetkiniz yok.', 403)

    if (not admin) and 'cari_kod' in payload and payload.get('cari_kod') not in (None, ''):
        raise CariGenelError('Cari kodunu değiştirme yetkiniz yok.', 403)

    if (not admin) and 'aktif' in payload:
        raise CariGenelError('Cari durumunu değiştirme yetkiniz yok.', 403)

    fields = parse_genel_payload(payload, allow_admin_fields=admin)
    if not fields:
        raise CariGenelError('Güncellenecek alan yok.', 400)

    avail = _cols_available(con)
    sets = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in avail:
            continue
        sets.append(f'{k}=?')
        vals.append(v)
    if not sets:
        raise CariGenelError('Güncellenecek alan yok.', 400)

    sets.append("updated_at=datetime('now','localtime')")
    vals.append(int(cari_id))
    con.execute(
        f"UPDATE nexgen_cari SET {', '.join(sets)} WHERE id=?",
        vals,
    )
    return load_cari_genel(con, cari_id, kullanici_id, yk)


def insert_cari_with_genel(
    con: sqlite3.Connection,
    cari_kod: str,
    unvan: str,
    payload: dict[str, Any],
    kullanici_id: int,
    yk: set[str] | None = None,
) -> int:
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not is_cari_admin(yk):
        raise CariGenelError('Cari oluşturma yetkiniz yok.', 403)

    kod = (cari_kod or '').strip()
    unv = (unvan or '').strip()
    if not kod or not unv:
        raise CariGenelError('cari_kod ve unvan zorunlu', 400)
    if con.execute('SELECT id FROM nexgen_cari WHERE cari_kod=?', (kod,)).fetchone():
        raise CariGenelError(f"'{kod}' kodu zaten mevcut", 400)

    fields = parse_genel_payload(payload, allow_admin_fields=True)
    avail = _cols_available(con)
    cols = ['cari_kod', 'unvan', 'aktif']
    vals: list[Any] = [kod, unv, 1]
    for k, v in fields.items():
        if k in ('unvan',) or k not in avail:
            continue
        cols.append(k)
        vals.append(v)

    ph = ','.join(['?'] * len(cols))
    con.execute(
        f"INSERT INTO nexgen_cari({', '.join(cols)}) VALUES({ph})",
        vals,
    )
    return int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
