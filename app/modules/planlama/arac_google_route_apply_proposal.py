# -*- coding: utf-8 -*-
"""Google route apply proposal — source of truth for user-approved suggested order."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from modules.planlama.arac_route_constraints import (
    RouteApplyConflictError,
    active_tasks_sorted,
    classify_route_tasks,
    load_visit_states_for_tasks,
    normalize_priority,
    validate_apply_task_ids,
)
from modules.planlama.arac_emergency_route_order import acil_before_normal_violation

_TZ = ZoneInfo('Europe/Istanbul')
_PROPOSAL_TTL_MINUTES = 20
_SOURCE = 'google-routes-v1'


def _now() -> datetime:
    return datetime.now(_TZ)


def coordinate_fingerprint(tasks: list[dict]) -> str:
    parts: list[str] = []
    for t in sorted(active_tasks_sorted(tasks), key=lambda x: str(x.get('id'))):
        tid = str(t.get('id'))
        lat = t.get('latitude')
        lng = t.get('longitude')
        pri = normalize_priority(t.get('priority'))
        parts.append(f'{tid}:{lat}:{lng}:{pri}')
    raw = '|'.join(parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _canonical_proposal_body(
    *,
    plan_date: str,
    vehicle_id: str,
    departure_time: str,
    google_profile: str,
    suggested_order: list[str],
    tasks: list[dict],
) -> dict[str, Any]:
    active_ids = sorted(str(t['id']) for t in active_tasks_sorted(tasks))
    return {
        'source': _SOURCE,
        'plan_date': str(plan_date),
        'vehicle_id': str(vehicle_id),
        'departure_time': str(departure_time)[:5],
        'google_profile': str(google_profile).strip().lower(),
        'suggested_order': [str(x) for x in suggested_order],
        'task_ids_sorted': active_ids,
        'coordinate_fingerprint': coordinate_fingerprint(tasks),
    }


def proposal_hash_from_body(body: dict[str, Any]) -> str:
    payload = {k: body[k] for k in sorted(body) if k != 'proposal_hash'}
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def build_google_apply_proposal(
    *,
    plan_date: str,
    vehicle_id: str,
    departure_time: str,
    google_profile: str,
    suggested_order: list[str],
    tasks: list[dict],
    ttl_minutes: int = _PROPOSAL_TTL_MINUTES,
) -> dict[str, Any]:
    body = _canonical_proposal_body(
        plan_date=plan_date,
        vehicle_id=vehicle_id,
        departure_time=departure_time,
        google_profile=google_profile,
        suggested_order=suggested_order,
        tasks=tasks,
    )
    computed_at = _now()
    expires_at = computed_at + timedelta(minutes=int(ttl_minutes))
    critical = [
        str(t['id'])
        for t in active_tasks_sorted(tasks)
        if normalize_priority(t.get('priority')) == 'ACIL'
    ]
    body['proposal_hash'] = proposal_hash_from_body(body)
    body['computed_at'] = computed_at.isoformat()
    body['expires_at'] = expires_at.isoformat()
    body['ttl_minutes'] = int(ttl_minutes)
    body['emergency_task_ids'] = critical
    body['emergency_before_normal'] = not acil_before_normal_violation(
        body['suggested_order'],
        active_tasks_sorted(tasks),
        critical_ids=set(critical),
    )
    return body


def validate_google_apply_proposal(
    *,
    proposal: dict[str, Any] | None,
    plan_date: str,
    vehicle_id: str,
    departure_time: str,
    google_profile: str,
    task_ids: list[str],
    tasks: list[dict],
) -> None:
    """Raise RouteApplyConflictError (409) or RouteApplyValidationError on mismatch."""
    if not proposal or not isinstance(proposal, dict):
        raise RouteApplyConflictError(
            'GOOGLE_PROPOSAL_REQUIRED',
            'Google rota teklifi eksik; önce rota seçeneklerini yeniden hesaplayın.',
        )

    dep = str(departure_time or '')[:5]
    prof = str(google_profile or '').strip().lower()
    norm_ids = [str(t) for t in task_ids]
    sug = [str(x) for x in (proposal.get('suggested_order') or [])]

    if str(proposal.get('source') or '') != _SOURCE:
        raise RouteApplyConflictError('GOOGLE_PROPOSAL_SOURCE', 'Geçersiz proposal kaynağı.')

    if str(proposal.get('plan_date') or '') != str(plan_date):
        raise RouteApplyConflictError('GOOGLE_PROPOSAL_SCOPE', 'Proposal tarih uyuşmazlığı.')
    if str(proposal.get('vehicle_id') or '') != str(vehicle_id):
        raise RouteApplyConflictError('GOOGLE_PROPOSAL_SCOPE', 'Proposal araç uyuşmazlığı.')
    if str(proposal.get('departure_time') or '')[:5] != dep:
        raise RouteApplyConflictError('GOOGLE_PROPOSAL_STALE', 'Çıkış saati proposal ile uyuşmuyor.')
    if str(proposal.get('google_profile') or '').strip().lower() != prof:
        raise RouteApplyConflictError('GOOGLE_PROPOSAL_STALE', 'Google profil proposal ile uyuşmuyor.')

    exp_raw = (proposal.get('expires_at') or '').strip()
    if exp_raw:
        try:
            exp = datetime.fromisoformat(exp_raw)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_TZ)
            if _now() > exp:
                raise RouteApplyConflictError(
                    'STALE_PROPOSAL',
                    'Google rota teklifinin süresi doldu; yeniden hesaplayın.',
                )
        except RouteApplyConflictError:
            raise
        except Exception:
            raise RouteApplyConflictError('STALE_PROPOSAL', 'Proposal süresi geçersiz.')

    ph = (proposal.get('proposal_hash') or '').strip()
    body = _canonical_proposal_body(
        plan_date=plan_date,
        vehicle_id=vehicle_id,
        departure_time=dep,
        google_profile=prof,
        suggested_order=sug,
        tasks=tasks,
    )
    if ph != proposal_hash_from_body(body):
        raise RouteApplyConflictError(
            'STALE_PROPOSAL',
            'Plan durumu değişti; Google teklifi güncel değil.',
        )

    active_sorted = sorted(str(t['id']) for t in active_tasks_sorted(tasks))
    if sorted(norm_ids) != active_sorted:
        raise RouteApplyConflictError(
            'TASK_SET_MISMATCH',
            'Görev kümesi proposal ile uyuşmuyor.',
        )
    if norm_ids != sug:
        raise RouteApplyConflictError(
            'GOOGLE_PROPOSAL_ORDER_MISMATCH',
            'Gönderilen sıra onaylanan Google önerisi ile eşleşmiyor.',
        )
    if coordinate_fingerprint(tasks) != str(proposal.get('coordinate_fingerprint') or ''):
        raise RouteApplyConflictError(
            'STALE_PROPOSAL',
            'Durak koordinatları değişti; teklif geçersiz.',
        )

    visit_states = load_visit_states_for_tasks(tasks)
    constraints = classify_route_tasks(tasks, visit_states)
    validate_apply_task_ids(tasks, norm_ids, constraints)
