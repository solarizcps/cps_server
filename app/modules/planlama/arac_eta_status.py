# -*- coding: utf-8 -*-
"""
arac_eta_status.py
Araç Takip — ETA durum hesabı (ortak, katmandan bağımsız).

KULLANIM:
    from modules.planlama.arac_eta_status import eta_status, ETA_TOLERANCE_MINUTES

Bu modül saf (pure) fonksiyonlar içerir; DB veya Flask bağımlılığı yoktur.
Tüm katmanlar (repo DTO, optimizer DTO, frontend API) aynı sabit ve fonksiyonu kullanır.

İSTENEN_SAAT DURUM KURALLARI:
  ETA - İstenen ≤ -ETA_TOLERANCE_MINUTES  →  'ERKEN'
  |ETA - İstenen| ≤ ETA_TOLERANCE_MINUTES  →  'ZAMANINDA'
  ETA - İstenen > ETA_TOLERANCE_MINUTES    →  'GECIKIYOR'
  İstenen saat yoksa                        →  'SERBEST'
  ETA hesaplanmadıysa                       →  'ETA_YOK'

TOLERANS:
  İstenen saatten 0–10 dakika önce/sonra → Zamanında
  Bu sabit bilinçli olarak tek yerde tanımlanmıştır.
"""
from __future__ import annotations

from typing import Literal

# ─── Tek canonical tolerans sabiti ──────────────────────────────────────────
ETA_TOLERANCE_MINUTES: int = 10

EtaStatusCode = Literal['ZAMANINDA', 'ERKEN', 'GECIKIYOR', 'SERBEST', 'ETA_YOK']


def _parse_hhmm(val: str | None) -> int | None:
    """HH:mm → dakika (gece yarısından itibaren). Geçersiz veya eksik → None."""
    if not val:
        return None
    val = val.strip()
    if len(val) >= 5 and val[2] == ':':
        try:
            h, m = int(val[:2]), int(val[3:5])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h * 60 + m
        except ValueError:
            pass
    return None


def eta_status(
    eta_saati: str | None,
    istenen_varis_saati: str | None,
    *,
    tolerance: int = ETA_TOLERANCE_MINUTES,
) -> dict:
    """
    ETA durum bilgisi üret.

    Dönen dict alanları:
      code          — EtaStatusCode
      label         — kullanıcıya gösterilecek metin
      delay_minutes — gecikme dakikası (pozitif: geç, negatif: erken), None ise hesaplanamadı
    """
    if not eta_saati:
        return {'code': 'ETA_YOK', 'label': '—', 'delay_minutes': None}

    if not istenen_varis_saati:
        return {'code': 'SERBEST', 'label': 'Saat serbest', 'delay_minutes': None}

    eta_min = _parse_hhmm(eta_saati)
    ist_min = _parse_hhmm(istenen_varis_saati)

    if eta_min is None or ist_min is None:
        return {'code': 'ETA_YOK', 'label': '—', 'delay_minutes': None}

    diff = eta_min - ist_min  # pozitif: geç, negatif: erken

    if diff > tolerance:
        return {
            'code': 'GECIKIYOR',
            'label': f'{diff} dk gecikiyor',
            'delay_minutes': diff,
        }
    if diff < -tolerance:
        return {
            'code': 'ERKEN',
            'label': f'{abs(diff)} dk erken',
            'delay_minutes': diff,
        }
    return {
        'code': 'ZAMANINDA',
        'label': 'Zamanında',
        'delay_minutes': diff,
    }


def enrich_task_eta_status(task: dict) -> dict:
    """
    task dict'ini in-place mutate et: eta_durum, eta_durum_label, eta_delay_minutes ekle.

    Semantik ayrım:
      eta_time / tahmini_varis_saati  = sistem ETA (rota motoru hesaplar)
      desired_time / istenen_varis_saati = kullanıcı/kaynak istenen saat

    Migration 188 öncesi: eta_time NULL gelir (ETA hesaplanmamış), durum ETA_YOK.
    planlanan_saat ← legacy istenen saat, ETA için KULLANILMAZ.
    """
    eta = task.get('eta_time') or task.get('tahmini_varis_saati') or None
    desired = task.get('desired_time') or task.get('istenen_varis_saati') or None
    result = eta_status(eta, desired)
    task['eta_durum'] = result['code']
    task['eta_durum_label'] = result['label']
    task['eta_delay_minutes'] = result['delay_minutes']
    return task
