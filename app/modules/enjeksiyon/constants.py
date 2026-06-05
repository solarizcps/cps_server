# -*- coding: utf-8 -*-
"""F9.2 — Enjeksiyon Operasyon Davranis Modeli Constants

UYARI:
  enj_event_log = OLAY KAYDI (ne oldu?)
  enj_gunluk_rapor = SNAPSHOT (mevcut durum)
  enj_istasyon_durumu = CANLI DURUM (gercek)

  enj_event_log ASLA hesap kaynagi olarak kullanilmayacak.
  enj_event_log silinmez (archive disiplini, F11+).

LEGACY UYARI (enj_istasyon_durumu):
  aktif kolonu LEGACY COMPATIBILITY icin korunmustur.
  SOURCE OF TRUTH = durum kolonudur.
  aktif=1 <-> durum='AKTIF'
  aktif=0 <-> durum IN ('KAPALI','SETUP','ARIZA')
  Yeni kod 'durum' kolonunu okumali.

KRITIK KURAL:
  Ayni kalip_id birden fazla slotta olabilir.
  Hesap motoru AKTIF SLOT bazli, UNIQUE KALIP bazli DEGIL.
"""

EVENT_GROUP = [
    'SLOT',
    'SETUP',
    'ARIZA',
    'RAPOR',
    'FIRE',
    'SYNC',
    'MANUEL',
    'VALIDATION'
]

EVENT_TYPE_MAP = {
    'SLOT': [
        'A_B_TOGGLE',
        'TOPLU_A',
        'TOPLU_B',
        'TOPLU_X',
        'DURUM_DEGISIM'
    ],
    'SETUP': [
        'SETUP_START',
        'SETUP_END',
        'SETUP_UZUN_UYARI',
        'SETUP_CREATED',
        'SETUP_APPROVED',
        'SETUP_CLOSED',
    ],
    'ARIZA': [
        'ARIZA_START',
        'ARIZA_END',
        'ARIZA_UZUN'
    ],
    'RAPOR': [
        'VARDIYA_KAPANIS',
        'VARDIYA_ACILIS'
    ],
    'FIRE': [
        'FIRE_GIRISI',
        'FIRE_DUZELTME'
    ],
    'SYNC': [
        'SSR_SYNC',
        'AUTO_SYNC'
    ],
    'MANUEL': [
        'MANUEL_DUZELTME',
        'MISMATCH_FIX'
    ],
    'VALIDATION': [
        'SLOT_MISMATCH_WARNING',
        'ATKI_GOVDE_KARISIK_UYARI'
    ]
}

SLOT_DURUM = ['AKTIF', 'KAPALI', 'SETUP', 'ARIZA']

# TODO F9.6+: 'BEKLEME' eklenebilir (planli durus, mavi #3b82f6)

ARIZA_SEBEPLER = [
    'KALIP',
    'HIDROLIK',
    'ELEKTRIK',
    'MALZEME',
    'OPERATOR',
    'BILINMIYOR'
]

SETUP_SEBEPLER = [
    'PLANLI_DEGISIM',
    'ARIZA_SONRASI',
    'ACIL'
]

# ENJ_SETUP_V1 — slot setup kayit durumlari
SETUP_DURUM = ['TASLAK', 'AKTIF', 'KAPANDI', 'IPTAL']

SPAM_WINDOWS = {
    ('SLOT', 'A_B_TOGGLE'): 2,
    ('SLOT', 'TOPLU_A'): 2,
    ('SLOT', 'TOPLU_B'): 2,
    ('SLOT', 'TOPLU_X'): 2,
    ('SLOT', 'DURUM_DEGISIM'): 1,
    ('SETUP', 'SETUP_START'): 0,
    ('SETUP', 'SETUP_END'): 0,
    ('SETUP', 'SETUP_UZUN_UYARI'): 600,
    ('SETUP', 'SETUP_CREATED'): 0,
    ('SETUP', 'SETUP_APPROVED'): 0,
    ('SETUP', 'SETUP_CLOSED'): 0,
    ('ARIZA', 'ARIZA_START'): 0,
    ('ARIZA', 'ARIZA_END'): 0,
    ('ARIZA', 'ARIZA_UZUN'): 600,
    ('RAPOR', 'VARDIYA_KAPANIS'): 0,
    ('RAPOR', 'VARDIYA_ACILIS'): 0,
    ('FIRE', 'FIRE_GIRISI'): 5,
    ('FIRE', 'FIRE_DUZELTME'): 5,
    ('SYNC', 'SSR_SYNC'): 10,
    ('SYNC', 'AUTO_SYNC'): 5,
    ('MANUEL', 'MANUEL_DUZELTME'): 0,
    ('MANUEL', 'MISMATCH_FIX'): 0,
    ('VALIDATION', 'SLOT_MISMATCH_WARNING'): 30,
    ('VALIDATION', 'ATKI_GOVDE_KARISIK_UYARI'): 60,
}

EVENT_VERSION = 'F9.2'

F9_2_ACTIVE = [
    ('SLOT', 'A_B_TOGGLE'),
    ('SLOT', 'TOPLU_A'),
    ('SLOT', 'TOPLU_B'),
    ('SLOT', 'TOPLU_X'),
    ('SLOT', 'DURUM_DEGISIM'),
    ('SETUP', 'SETUP_START'),
    ('SETUP', 'SETUP_END'),
    ('SETUP', 'SETUP_UZUN_UYARI'),
    ('SETUP', 'SETUP_CREATED'),
    ('SETUP', 'SETUP_APPROVED'),
    ('SETUP', 'SETUP_CLOSED'),
    ('ARIZA', 'ARIZA_START'),
    ('ARIZA', 'ARIZA_END'),
    ('ARIZA', 'ARIZA_UZUN'),
    ('VALIDATION', 'SLOT_MISMATCH_WARNING'),
    ('VALIDATION', 'ATKI_GOVDE_KARISIK_UYARI'),
    ('SYNC', 'SSR_SYNC'),
]

F9_0_5_ACTIVE = [
    ('SLOT', 'A_B_TOGGLE'),
    ('SLOT', 'TOPLU_A'),
    ('SLOT', 'TOPLU_B'),
    ('SLOT', 'TOPLU_X'),
    ('SYNC', 'SSR_SYNC')
]
