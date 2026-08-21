# -*- coding: utf-8 -*-
"""
tedarikci_ayar_service.py
=========================
FAZ 6C — Tedarikçi çalışma ayarı service (schema temeli).

Ayar kaydı yoksa DB INSERT YOK — default yalnız DTO/in-memory.
finans_odeme_tedarikci_takip (aktif_takip) AYRI tablo — birleştirilmez.
Korgün OdemeVade bu tabloya KOPYALANMAZ.
N+1 YASAK: fetch_settings_map tek sorgu.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from config import Config

    def get_db_path() -> str:
        return Config.MOCK_DB_PATH
except ImportError:
    try:
        from db import get_db_path  # type: ignore
    except ImportError:
        def get_db_path() -> str:
            return os.path.normpath(
                os.path.join(os.path.dirname(__file__), '..', '..', '..', 'mock_data.db')
            )

try:
    from modules.finans.services.korgun_finance_adapter import CANONICAL_LOCATION_CODES
except ImportError:
    from app.modules.finans.services.korgun_finance_adapter import CANONICAL_LOCATION_CODES

KATEGORI_TABLO = 'finans_tedarikci_kategori'
AYAR_TABLO = 'finans_odeme_tedarikci_ayar'

PAYMENT_MODES = (
    'FATURA_BAZLI', 'SIPARIS_BAZLI', 'DUZENLI',
    'DONEMSEL', 'MANUEL', 'SOZLESME_BAZLI',
)
PAYMENT_PERIODS = (
    'HAFTALIK', 'ON_BES_GUNLUK', 'AYLIK',
    'BELIRLI_GUN', 'FATURA_VADESINDE', 'MANUEL',
)
PRIORITIES = ('DUSUK', 'NORMAL', 'YUKSEK', 'KRITIK')
CURRENCIES = ('TRY', 'USD', 'EUR')
WORKING_TERM_BASES = (
    'FATURA_TARIHI', 'MAL_KABUL_TARIHI', 'SEVK_TARIHI', 'AY_SONU', 'MANUEL',
)
WORKING_TERM_DAY_PRESETS = (0, 7, 15, 30, 45, 60, 75, 90, 120, 150, 180)
WORKING_TERM_DAYS_MAX = 730
BOOLEAN_FIELDS = (
    'critical_supplier', 'must_not_stop', 'recurring_payment',
    'partial_payment_allowed', 'settings_active',
)
DEPARTMENTS = ('Finans', 'Muhasebe', 'Satın Alma', 'İdari İşler', 'Yönetim')

PAYMENT_MODE_LABELS = {
    'FATURA_BAZLI': 'Fatura Bazlı',
    'SIPARIS_BAZLI': 'Sipariş Bazlı',
    'DUZENLI': 'Düzenli',
    'DONEMSEL': 'Dönemsel',
    'MANUEL': 'Manuel',
    'SOZLESME_BAZLI': 'Sözleşme Bazlı',
}
PAYMENT_PERIOD_LABELS = {
    'HAFTALIK': 'Haftalık',
    'ON_BES_GUNLUK': '15 Günlük',
    'AYLIK': 'Aylık',
    'BELIRLI_GUN': 'Belirli Gün',
    'FATURA_VADESINDE': 'Fatura Vadesinde',
    'MANUEL': 'Manuel',
}
PRIORITY_LABELS = {
    'DUSUK': 'Düşük',
    'NORMAL': 'Normal',
    'YUKSEK': 'Yüksek',
    'KRITIK': 'Kritik',
}
WORKING_TERM_BASIS_LABELS = {
    'FATURA_TARIHI': 'Fatura Tarihi',
    'MAL_KABUL_TARIHI': 'Mal Kabul Tarihi',
    'SEVK_TARIHI': 'Sevk Tarihi',
    'AY_SONU': 'Ay Sonu',
    'MANUEL': 'Manuel',
}

_AUDIT_MODUL = 'finans'
_AUDIT_ALT = 'tedarikci_ayar'


class TedarikciAyarError(Exception):
    def __init__(self, message: str, code: str = 'VALIDATION'):
        super().__init__(message)
        self.code = code


def _canonical_key(location: str, cari_kod: str) -> str:
    return f'{location}|{cari_kod}'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _tables_ready(con: sqlite3.Connection) -> bool:
    return _table_exists(con, KATEGORI_TABLO) and _table_exists(con, AYAR_TABLO)


def build_default_setting_dto(location: str, cari_kod: str) -> Dict[str, Any]:
    """Kayıt yoksa in-memory default — DB INSERT yok."""
    return {
        'location': location,
        'cari_kod': cari_kod,
        'has_settings': False,
        'category_code': 'TANIMSIZ',
        'category_label': 'Tanımsız',
        'payment_mode': 'MANUEL',
        'payment_period': None,
        'payment_day': None,
        'priority': 'NORMAL',
        'critical_supplier': False,
        'must_not_stop': False,
        'recurring_payment': False,
        'recurring_amount': None,
        'recurring_currency': None,
        'partial_payment_allowed': False,
        'minimum_payment_amount': None,
        'responsible_user_id': None,
        'responsible_department': None,
        'payment_working_note': None,
        'settings_active': True,
        'cari_adi_snapshot': '',
        'working_term_days': None,
        'working_term_basis': None,
    }


def _row_val(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def format_period_display(setting: Dict[str, Any]) -> str:
    """Periyot hücresi — ritim + ödeme günü + çalışma vadesi (kompakt)."""
    lines: List[str] = []
    period = setting.get('payment_period')
    if period:
        lines.append(PAYMENT_PERIOD_LABELS.get(period, period))
    payment_day = setting.get('payment_day')
    if payment_day and period in ('HAFTALIK', 'AYLIK', 'BELIRLI_GUN', 'ON_BES_GUNLUK'):
        lines.append(str(payment_day))
    wtd = setting.get('working_term_days')
    if wtd is not None and wtd != '':
        try:
            days = int(wtd)
            term_line = 'Peşin' if days == 0 else f'{days} gün'
            basis = setting.get('working_term_basis')
            if basis:
                term_line += f' · {WORKING_TERM_BASIS_LABELS.get(basis, basis)}'
            lines.append(term_line)
        except (TypeError, ValueError):
            pass
    return '\n'.join(lines) if lines else '—'


def _row_to_dto(row: sqlite3.Row, category_labels: Dict[str, str]) -> Dict[str, Any]:
    return {
        'id': row['id'],
        'location': row['location'],
        'cari_kod': row['cari_kod'],
        'has_settings': True,
        'category_code': row['category_code'],
        'category_label': category_labels.get(row['category_code'], row['category_code']),
        'payment_mode': row['payment_mode'],
        'payment_period': row['payment_period'],
        'payment_day': row['payment_day'],
        'priority': row['priority'],
        'critical_supplier': bool(row['critical_supplier']),
        'must_not_stop': bool(row['must_not_stop']),
        'recurring_payment': bool(row['recurring_payment']),
        'recurring_amount': row['recurring_amount'],
        'recurring_currency': row['recurring_currency'],
        'partial_payment_allowed': bool(row['partial_payment_allowed']),
        'minimum_payment_amount': row['minimum_payment_amount'],
        'responsible_user_id': row['responsible_user_id'],
        'responsible_department': row['responsible_department'],
        'payment_working_note': row['payment_working_note'],
        'settings_active': bool(row['settings_active']),
        'cari_adi_snapshot': row['cari_adi_snapshot'] or '',
        'created_by': row['created_by'],
        'created_at': row['created_at'],
        'updated_by': row['updated_by'],
        'updated_at': row['updated_at'],
        'working_term_days': _row_val(row, 'working_term_days'),
        'working_term_basis': _row_val(row, 'working_term_basis'),
        'working_term_display': format_period_display({
            'payment_period': row['payment_period'],
            'payment_day': row['payment_day'],
            'working_term_days': _row_val(row, 'working_term_days'),
            'working_term_basis': _row_val(row, 'working_term_basis'),
        }),
    }


def validate_location(location: Optional[str]) -> str:
    loc = (location or '').strip().upper()
    if loc not in CANONICAL_LOCATION_CODES:
        raise TedarikciAyarError('Geçersiz şirket (location).', 'INVALID_LOCATION')
    return loc


def validate_cari_kod(cari_kod: Optional[str]) -> str:
    ck = (cari_kod or '').strip()
    if not ck:
        raise TedarikciAyarError('Cari kod zorunlu.', 'REQUIRED')
    return ck


def validate_payment_mode(value: Optional[str]) -> str:
    mode = (value or 'MANUEL').strip().upper()
    if mode not in PAYMENT_MODES:
        raise TedarikciAyarError('Geçersiz ödeme modu.', 'INVALID_PAYMENT_MODE')
    return mode


def validate_payment_period(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == '':
        return None
    period = str(value).strip().upper()
    if period not in PAYMENT_PERIODS:
        raise TedarikciAyarError('Geçersiz ödeme periyodu.', 'INVALID_PAYMENT_PERIOD')
    return period


def validate_priority(value: Optional[str]) -> str:
    pri = (value or 'NORMAL').strip().upper()
    if pri not in PRIORITIES:
        raise TedarikciAyarError('Geçersiz öncelik.', 'INVALID_PRIORITY')
    return pri


def validate_boolean_field(name: str, value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in (0, 1):
        return value
    raise TedarikciAyarError(f'Geçersiz boolean alan: {name}.', 'INVALID_BOOLEAN')


def validate_currency(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == '':
        return None
    cur = str(value).strip().upper()
    if cur not in CURRENCIES:
        raise TedarikciAyarError('Geçersiz para birimi.', 'INVALID_CURRENCY')
    return cur


def validate_amount_non_negative(value: Any, field_name: str) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise TedarikciAyarError(f'{field_name} geçersiz.', 'INVALID_AMOUNT') from exc
    if num < 0:
        raise TedarikciAyarError(f'{field_name} negatif olamaz.', 'INVALID_AMOUNT')
    return num


def validate_responsible_user(con: sqlite3.Connection, user_id: Any) -> Optional[int]:
    if user_id is None or user_id == '':
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError) as exc:
        raise TedarikciAyarError('Geçersiz sorumlu kullanıcı.', 'INVALID_USER') from exc
    row = con.execute(
        'SELECT Id FROM sistem_kullanici WHERE Id=? AND Aktif=1', (uid,),
    ).fetchone()
    if not row:
        raise TedarikciAyarError('Sorumlu kullanıcı bulunamadı.', 'INVALID_USER')
    return uid


def validate_supplier_canonical(location: str, cari_kod: str) -> None:
    try:
        from modules.finans.services.korgun_finance_adapter import KorgunFinanceAdapter
    except ImportError:
        from app.modules.finans.services.korgun_finance_adapter import KorgunFinanceAdapter
    adapter = KorgunFinanceAdapter()
    if not adapter.supplier_canonical_exists(location, cari_kod):
        raise TedarikciAyarError(
            f'Tedarikçi bulunamadı: {location}|{cari_kod}',
            'INVALID_CARI',
        )


def validate_department(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == '':
        return None
    dep = str(value).strip()
    if dep not in DEPARTMENTS:
        raise TedarikciAyarError('Geçersiz departman.', 'INVALID_DEPARTMENT')
    return dep


def validate_working_term_days(value: Any) -> Optional[int]:
    if value is None or value == '':
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise TedarikciAyarError('Çalışma vadesi gün sayısı geçersiz.', 'INVALID_TERM_DAYS') from exc
    if days < 0 or days > WORKING_TERM_DAYS_MAX:
        raise TedarikciAyarError(
            f'Çalışma vadesi 0–{WORKING_TERM_DAYS_MAX} arasında olmalı.',
            'INVALID_TERM_DAYS',
        )
    return days


def validate_working_term_basis(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == '':
        return None
    basis = str(value).strip().upper()
    if basis not in WORKING_TERM_BASES:
        raise TedarikciAyarError('Geçersiz vade başlangıç noktası.', 'INVALID_TERM_BASIS')
    return basis


def _audit_create(kullanici: str, setting_id: int, loc: str, ck: str, con: Optional[sqlite3.Connection] = None) -> None:
    try:
        from modules import audit
    except ImportError:
        from app.modules import audit
    audit.log_olay(
        kullanici, 'TEDARIKCI_AYAR_CREATE', AYAR_TABLO, setting_id,
        aciklama=f'{loc}|{ck}',
        modul=_AUDIT_MODUL, alt_modul=_AUDIT_ALT, conn=con,
    )


def _audit_update(kullanici: str, setting_id: int, loc: str, ck: str, fields: Sequence[str],
                  con: Optional[sqlite3.Connection] = None) -> None:
    try:
        from modules import audit
    except ImportError:
        from app.modules import audit
    audit.log_olay(
        kullanici, 'TEDARIKCI_AYAR_UPDATE', AYAR_TABLO, setting_id,
        aciklama=f'{loc}|{ck} · {",".join(fields)}',
        modul=_AUDIT_MODUL, alt_modul=_AUDIT_ALT, conn=con,
    )


def _audit_deactivate(kullanici: str, setting_id: int, loc: str, ck: str,
                      con: Optional[sqlite3.Connection] = None) -> None:
    try:
        from modules import audit
    except ImportError:
        from app.modules import audit
    audit.log_olay(
        kullanici, 'TEDARIKCI_AYAR_DEACTIVATE', AYAR_TABLO, setting_id,
        aciklama=f'{loc}|{ck}',
        modul=_AUDIT_MODUL, alt_modul=_AUDIT_ALT, conn=con,
    )


def validate_category_code(con: sqlite3.Connection, code: Optional[str]) -> str:
    cat = (code or 'TANIMSIZ').strip().upper()
    row = con.execute(
        f"SELECT code FROM {KATEGORI_TABLO} WHERE code=? AND active=1",
        (cat,),
    ).fetchone()
    if not row:
        raise TedarikciAyarError('Geçersiz kategori.', 'INVALID_CATEGORY')
    return cat


def validate_create_payload(
    payload: Dict[str, Any],
    con: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Create için normalize edilmiş payload — DB yazmaz."""
    own_con = con is None
    if own_con:
        con = _connect()
    try:
        if not _tables_ready(con):
            raise TedarikciAyarError('Ayar tabloları hazır değil.', 'SCHEMA_MISSING')
        loc = validate_location(payload.get('location'))
        ck = validate_cari_kod(payload.get('cari_kod'))
        kullanici = (payload.get('created_by') or payload.get('kullanici') or '').strip()
        if not kullanici:
            raise TedarikciAyarError('Oluşturan kullanıcı zorunlu.', 'REQUIRED')
        normalized = {
            'location': loc,
            'cari_kod': ck,
            'cari_adi_snapshot': (payload.get('cari_adi_snapshot') or '').strip(),
            'category_code': validate_category_code(con, payload.get('category_code')),
            'payment_mode': validate_payment_mode(payload.get('payment_mode')),
            'payment_period': validate_payment_period(payload.get('payment_period')),
            'payment_day': (payload.get('payment_day') or None),
            'priority': validate_priority(payload.get('priority')),
            'critical_supplier': validate_boolean_field(
                'critical_supplier', payload.get('critical_supplier', 0)),
            'must_not_stop': validate_boolean_field(
                'must_not_stop', payload.get('must_not_stop', 0)),
            'recurring_payment': validate_boolean_field(
                'recurring_payment', payload.get('recurring_payment', 0)),
            'recurring_amount': validate_amount_non_negative(
                payload.get('recurring_amount'), 'Düzenli tutar'),
            'recurring_currency': validate_currency(payload.get('recurring_currency')),
            'partial_payment_allowed': validate_boolean_field(
                'partial_payment_allowed', payload.get('partial_payment_allowed', 0)),
            'minimum_payment_amount': validate_amount_non_negative(
                payload.get('minimum_payment_amount'), 'Minimum ödeme tutarı'),
            'responsible_user_id': validate_responsible_user(
                con, payload.get('responsible_user_id')),
            'responsible_department': validate_department(payload.get('responsible_department')),
            'payment_working_note': (payload.get('payment_working_note') or None),
            'settings_active': validate_boolean_field(
                'settings_active', payload.get('settings_active', 1)),
            'working_term_days': validate_working_term_days(payload.get('working_term_days')),
            'working_term_basis': validate_working_term_basis(payload.get('working_term_basis')),
            'created_by': kullanici,
            'created_at': payload.get('created_at') or _now(),
        }
        return normalized
    finally:
        if own_con and con is not None:
            con.close()


def validate_update_payload(
    payload: Dict[str, Any],
    con: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Update için normalize edilmiş alanlar — DB yazmaz."""
    own_con = con is None
    if own_con:
        con = _connect()
    try:
        if not _tables_ready(con):
            raise TedarikciAyarError('Ayar tabloları hazır değil.', 'SCHEMA_MISSING')
        kullanici = (payload.get('updated_by') or payload.get('kullanici') or '').strip()
        if not kullanici:
            raise TedarikciAyarError('Güncelleyen kullanıcı zorunlu.', 'REQUIRED')
        normalized: Dict[str, Any] = {
            'updated_by': kullanici,
            'updated_at': payload.get('updated_at') or _now(),
        }
        if 'category_code' in payload:
            normalized['category_code'] = validate_category_code(con, payload['category_code'])
        if 'payment_mode' in payload:
            normalized['payment_mode'] = validate_payment_mode(payload['payment_mode'])
        if 'payment_period' in payload:
            normalized['payment_period'] = validate_payment_period(payload['payment_period'])
        if 'payment_day' in payload:
            normalized['payment_day'] = payload.get('payment_day')
        if 'priority' in payload:
            normalized['priority'] = validate_priority(payload['priority'])
        for field in BOOLEAN_FIELDS:
            if field in payload:
                normalized[field] = validate_boolean_field(field, payload[field])
        if 'recurring_currency' in payload:
            normalized['recurring_currency'] = validate_currency(payload['recurring_currency'])
        if 'recurring_amount' in payload:
            normalized['recurring_amount'] = validate_amount_non_negative(
                payload['recurring_amount'], 'Düzenli tutar')
        if 'minimum_payment_amount' in payload:
            normalized['minimum_payment_amount'] = validate_amount_non_negative(
                payload['minimum_payment_amount'], 'Minimum ödeme tutarı')
        if 'responsible_user_id' in payload:
            normalized['responsible_user_id'] = validate_responsible_user(
                con, payload['responsible_user_id'])
        if 'responsible_department' in payload:
            normalized['responsible_department'] = validate_department(
                payload.get('responsible_department'))
        if 'payment_working_note' in payload:
            normalized['payment_working_note'] = payload.get('payment_working_note')
        if 'cari_adi_snapshot' in payload:
            normalized['cari_adi_snapshot'] = (payload.get('cari_adi_snapshot') or '').strip()
        if 'working_term_days' in payload:
            normalized['working_term_days'] = validate_working_term_days(payload['working_term_days'])
        if 'working_term_basis' in payload:
            normalized['working_term_basis'] = validate_working_term_basis(payload['working_term_basis'])
        return normalized
    finally:
        if own_con and con is not None:
            con.close()


def list_categories(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        if not _table_exists(con, KATEGORI_TABLO):
            return []
        rows = con.execute(
            f"""
            SELECT code, label_tr, sort_order, active
            FROM {KATEGORI_TABLO}
            WHERE active=1
            ORDER BY sort_order, code
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _load_category_labels(con: sqlite3.Connection) -> Dict[str, str]:
    if not _table_exists(con, KATEGORI_TABLO):
        return {'TANIMSIZ': 'Tanımsız'}
    rows = con.execute(
        f"SELECT code, label_tr FROM {KATEGORI_TABLO} WHERE active=1"
    ).fetchall()
    return {r['code']: r['label_tr'] for r in rows}


def get_setting(
    location: str,
    cari_kod: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    loc = validate_location(location)
    ck = validate_cari_kod(cari_kod)
    con = _connect(db_path)
    try:
        if not _tables_ready(con):
            dto = build_default_setting_dto(loc, ck)
            return dto
        labels = _load_category_labels(con)
        row = con.execute(
            f"SELECT * FROM {AYAR_TABLO} WHERE location=? AND cari_kod=?",
            (loc, ck),
        ).fetchone()
        if not row:
            return build_default_setting_dto(loc, ck)
        return _row_to_dto(row, labels)
    finally:
        con.close()


def fetch_settings_map(
    locations: Optional[Sequence[str]] = None,
    cari_kods: Optional[Sequence[str]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Tek sorgu — canonical_key → ayar DTO map.
    Kayıt yoksa map'te yer almaz; caller get_setting veya default builder kullanır.
    """
    con = _connect(db_path)
    try:
        if not _tables_ready(con):
            return {}
        labels = _load_category_labels(con)
        params: List[Any] = []
        where_parts: List[str] = []
        if locations:
            locs = [validate_location(x) for x in locations]
            ph = ','.join('?' * len(locs))
            where_parts.append(f'location IN ({ph})')
            params.extend(locs)
        if cari_kods:
            cks = [validate_cari_kod(x) for x in cari_kods]
            ph = ','.join('?' * len(cks))
            where_parts.append(f'cari_kod IN ({ph})')
            params.extend(cks)
        where = f" WHERE {' AND '.join(where_parts)}" if where_parts else ''
        rows = con.execute(
            f"SELECT * FROM {AYAR_TABLO}{where}",
            tuple(params),
        ).fetchall()
        return {
            _canonical_key(r['location'], r['cari_kod']): _row_to_dto(r, labels)
            for r in rows
        }
    finally:
        con.close()


def create_setting(
    payload: Dict[str, Any],
    db_path: Optional[str] = None,
    validate_supplier: bool = True,
) -> Dict[str, Any]:
    loc = validate_location(payload.get('location'))
    ck = validate_cari_kod(payload.get('cari_kod'))
    if validate_supplier:
        validate_supplier_canonical(loc, ck)
    con = _connect(db_path)
    try:
        data = validate_create_payload(payload, con)
        dup = con.execute(
            f'SELECT id FROM {AYAR_TABLO} WHERE location=? AND cari_kod=?',
            (data['location'], data['cari_kod']),
        ).fetchone()
        if dup:
            raise TedarikciAyarError(
                'Bu location+cari_kod için ayar zaten var.',
                'DUPLICATE',
            )
        cur = con.execute(
            f"""
            INSERT INTO {AYAR_TABLO} (
                location, cari_kod, cari_adi_snapshot, category_code,
                payment_mode, payment_period, payment_day, priority,
                critical_supplier, must_not_stop, recurring_payment,
                recurring_amount, recurring_currency, partial_payment_allowed,
                minimum_payment_amount, responsible_user_id, responsible_department,
                payment_working_note, settings_active, created_by, created_at,
                working_term_days, working_term_basis
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data['location'], data['cari_kod'], data['cari_adi_snapshot'],
                data['category_code'], data['payment_mode'], data['payment_period'],
                data['payment_day'], data['priority'], data['critical_supplier'],
                data['must_not_stop'], data['recurring_payment'], data['recurring_amount'],
                data['recurring_currency'], data['partial_payment_allowed'],
                data['minimum_payment_amount'], data['responsible_user_id'],
                data['responsible_department'], data['payment_working_note'],
                data['settings_active'], data['created_by'], data['created_at'],
                data['working_term_days'], data['working_term_basis'],
            ),
        )
        setting_id = cur.lastrowid
        _audit_create(data['created_by'], int(setting_id), data['location'], data['cari_kod'], con=con)
        con.commit()
        return get_setting(data['location'], data['cari_kod'], db_path=db_path)
    finally:
        con.close()


def save_setting(
    payload: Dict[str, Any],
    db_path: Optional[str] = None,
    validate_supplier: bool = True,
) -> Dict[str, Any]:
    """Create veya update — location+cari_kod identity."""
    loc = validate_location(payload.get('location'))
    ck = validate_cari_kod(payload.get('cari_kod'))
    if validate_supplier:
        validate_supplier_canonical(loc, ck)
    con = _connect(db_path)
    try:
        existing = con.execute(
            f'SELECT id FROM {AYAR_TABLO} WHERE location=? AND cari_kod=?',
            (loc, ck),
        ).fetchone()
    finally:
        con.close()
    if existing:
        upd_payload = dict(payload)
        upd_payload['updated_by'] = payload.get('updated_by') or payload.get('created_by')
        return update_setting(loc, ck, upd_payload, db_path=db_path)
    return create_setting(payload, db_path=db_path)


def deactivate_setting(
    location: str,
    cari_kod: str,
    kullanici: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    loc = validate_location(location)
    ck = validate_cari_kod(cari_kod)
    con = _connect(db_path)
    try:
        row = con.execute(
            f'SELECT id FROM {AYAR_TABLO} WHERE location=? AND cari_kod=?',
            (loc, ck),
        ).fetchone()
        if not row:
            raise TedarikciAyarError('Ayar kaydı bulunamadı.', 'NOT_FOUND')
        now = _now()
        con.execute(
            f"""
            UPDATE {AYAR_TABLO}
            SET settings_active=0, updated_by=?, updated_at=?
            WHERE location=? AND cari_kod=?
            """,
            (kullanici, now, loc, ck),
        )
        _audit_deactivate(kullanici, int(row['id']), loc, ck, con=con)
        con.commit()
        return get_setting(loc, ck, db_path=db_path)
    finally:
        con.close()


def list_responsible_users(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT Id, AdSoyad, KullaniciAdi
            FROM sistem_kullanici
            WHERE Aktif=1
            ORDER BY AdSoyad, KullaniciAdi
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def update_setting(
    location: str,
    cari_kod: str,
    payload: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    loc = validate_location(location)
    ck = validate_cari_kod(cari_kod)
    con = _connect(db_path)
    try:
        existing = con.execute(
            f'SELECT id FROM {AYAR_TABLO} WHERE location=? AND cari_kod=?',
            (loc, ck),
        ).fetchone()
        if not existing:
            raise TedarikciAyarError('Ayar kaydı bulunamadı.', 'NOT_FOUND')
        data = validate_update_payload(payload, con)
        fields = [k for k in data if k not in ('updated_by', 'updated_at')]
        if not fields:
            raise TedarikciAyarError('Güncellenecek alan yok.', 'REQUIRED')
        set_clause = ', '.join(f'{k}=?' for k in fields)
        values = [data[k] for k in fields]
        values.extend([data['updated_by'], data['updated_at'], loc, ck])
        con.execute(
            f"""
            UPDATE {AYAR_TABLO}
            SET {set_clause}, updated_by=?, updated_at=?
            WHERE location=? AND cari_kod=?
            """,
            tuple(values),
        )
        _audit_update(data['updated_by'], int(existing['id']), loc, ck, fields, con=con)
        con.commit()
        return get_setting(loc, ck, db_path=db_path)
    finally:
        con.close()
