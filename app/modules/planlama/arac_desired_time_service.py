# -*- coding: utf-8 -*-
"""
arac_desired_time_service.py
Araç Takip — iş bazlı istenen varış saatini kaydet (atomic + audit).

POST /planlama/arac-takip/api/plan-job/desired-time

SEMANTİK TANIMLAR:
  istenen_varis_saati  = kullanıcı/kaynak tarafından istenen saat (bu servis yazar)
  tahmini_varis_saati  = ETA, sistem hesaplar (bu servis ASLA yazmaz)
  planlanan_saat       = legacy kolon, DOKUNULMAZ

İş kuralları:
- istenen_varis_saati iş seviyesinde tutulur (arac_gunluk_plan_is)
- Kayıt + audit yazımı tek transaction'da
- Inactive işlere saat yazılamaz
- Başka araç/tarihe dokunulmaz
- Migration 188 gerektirir; kolon yoksa 'MIGRATION_REQUIRED' hatası döner
- time_free=true gönderilirse saat null, kaynak='SERBEST'
- Kaynak sistem değeri varsa ve kullanıcı değiştirirse kaynak='MANUEL', manuel=1
"""
from __future__ import annotations

import re
from typing import Any

from db import get_conn
from modules.planlama.arac_takip_repo import (
    INACTIVE_PLAN_STATUSES,
    get_active_plan_row,
    list_plan_tasks,
    tables_ready,
    update_plan_item_desired_time_conn,
)

_HHMM_RE = re.compile(r'^(\d{1,2}):(\d{2})$')

ACTION_ISTENEN_SAAT_DEGISTI = 'ISTENEN_SAAT_DEGISTI'


class DesiredTimeValidationError(ValueError):
    pass


def _validate_hhmm(raw: str) -> str:
    text = (raw or '').strip()
    m = _HHMM_RE.match(text)
    if not m:
        raise DesiredTimeValidationError(f'Geçersiz saat formatı: {raw!r} — HH:mm bekleniyor')
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        raise DesiredTimeValidationError(f'Geçersiz saat değeri: {raw!r}')
    return f'{hour:02d}:{minute:02d}'


def _migration_188_ready(con) -> bool:
    cols = [r[1] for r in con.execute('PRAGMA table_info(arac_gunluk_plan_is)').fetchall()]
    return 'istenen_varis_saati' in cols


def _write_audit(
    con,
    plan_is_id: int,
    prev_saat: str | None,
    new_saat: str | None,
    kaynak: str,
    session_user_id: int,
    time_free: bool,
) -> None:
    """arac_plan_is_degisim'e ISTENEN_SAAT_DEGISTI kaydı yaz (caller'ın transaction'ı içinde)."""
    import json
    from datetime import datetime
    metadata = {
        'action': ACTION_ISTENEN_SAAT_DEGISTI,
        'plan_is_id': plan_is_id,
        'prev_istenen_varis_saati': prev_saat,
        'new_istenen_varis_saati': new_saat,
        'kaynak': kaynak,
        'time_free': time_free,
    }
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        con.execute(
            """
            INSERT INTO arac_plan_is_degisim
                (plan_is_id, action, metadata_json, created_at, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plan_is_id, ACTION_ISTENEN_SAAT_DEGISTI, json.dumps(metadata, ensure_ascii=False), now, session_user_id),
        )
    except Exception:
        pass  # audit yazma hatası ana transaction'ı durdurmasın


def save_desired_time(
    plan_date: str,
    arac_external_id: str,
    plan_item_id: int,
    desired_time: str | None,
    time_free: bool,
    session_user_id: int,
) -> dict[str, Any]:
    """
    Atomic:
    1. Validate
    2. Plan + iş varlık kontrolü
    3. Inactive kontrolü
    4. Migration 188 kolon kontrolü
    5. BEGIN IMMEDIATE
    6. UPDATE istenen_varis_saati (planlanan_saat DOKUNULMAZ, tahmini_varis_saati DOKUNULMAZ)
    7. INSERT audit
    8. COMMIT
    Hata: rollback, hata dict döner.
    """
    if not tables_ready():
        return {'ok': False, 'error': 'Araç takip tabloları hazır değil', 'code': 'TABLES_NOT_READY'}

    if time_free:
        canonical_saat: str | None = None
        kaynak = 'SERBEST'
    else:
        try:
            canonical_saat = _validate_hhmm(desired_time)
        except DesiredTimeValidationError as exc:
            return {'ok': False, 'error': str(exc), 'code': 'INVALID_TIME'}
        kaynak = 'MANUEL'

    plan_row = get_active_plan_row(plan_date, arac_external_id)
    if not plan_row:
        return {'ok': False, 'error': 'Aktif plan bulunamadı', 'code': 'PLAN_NOT_FOUND'}

    plan_id = int(plan_row['id'])

    tasks = list_plan_tasks(plan_date, arac_external_id)
    target = next((t for t in tasks if t.get('plan_item_id') == int(plan_item_id)), None)
    if not target:
        return {'ok': False, 'error': 'Plan işi bulunamadı', 'code': 'PLAN_ITEM_NOT_FOUND'}

    st = (target.get('status') or '').upper()
    if st in INACTIVE_PLAN_STATUSES:
        return {'ok': False, 'error': f'İnaktif işe saat yazılamaz: {st}', 'code': 'INACTIVE_ITEM'}

    # Kaynak belirleme
    prev_saat = target.get('istenen_varis_saati') or target.get('desired_time')
    prev_kaynak = target.get('istenen_saat_kaynak') or target.get('desired_time_source') or 'YOK'
    if not time_free:
        if prev_kaynak in ('SISTEM', 'LEGACY', 'KULLANICI') and canonical_saat != prev_saat:
            kaynak = 'MANUEL'

    con = get_conn()
    try:
        if not _migration_188_ready(con):
            return {
                'ok': False,
                'error': 'Migration 188 uygulanmamış — istenen_varis_saati kolonu yok',
                'code': 'MIGRATION_REQUIRED',
            }

        con.execute('BEGIN IMMEDIATE')
        update_plan_item_desired_time_conn(
            con,
            plan_is_id=int(plan_item_id),
            istenen_varis_saati=canonical_saat,
            kaynak=kaynak,
            manuel=(kaynak == 'MANUEL'),
            session_user_id=session_user_id,
        )
        _write_audit(
            con,
            plan_is_id=int(plan_item_id),
            prev_saat=prev_saat,
            new_saat=canonical_saat,
            kaynak=kaynak,
            session_user_id=session_user_id,
            time_free=time_free,
        )
        con.commit()
    except Exception as exc:
        con.rollback()
        return {'ok': False, 'error': f'Kayıt hatası: {exc}', 'code': 'DB_ERROR'}
    finally:
        con.close()

    updated_tasks = list_plan_tasks(plan_date, arac_external_id)

    return {
        'ok': True,
        'plan_id': plan_id,
        'plan_item_id': int(plan_item_id),
        'istenen_varis_saati': canonical_saat,
        'time_free': time_free,
        'kaynak': kaynak,
        'prev_saat': prev_saat,
        'tasks': updated_tasks,
    }
