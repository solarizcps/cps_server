# -*- coding: utf-8 -*-
"""
CPS DEV - Config
"""

import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_MOCK_DB = os.path.join(_APP_DIR, 'mock_data.db')


class Config:
    # ===================== DB MODE =====================
    # 🔥 PROD YAPILDI
    DB_MODE = 'mock'

    # ===================== MOCK =====================
    # CPS_MOCK_DB_PATH: browser regression / test server izolasyonu (opsiyonel)
    MOCK_DB_PATH = os.environ.get('CPS_MOCK_DB_PATH') or _DEFAULT_MOCK_DB

    # ===================== PROD (MSSQL) =====================
    # LAN IP — Korgun SQL Server
    MSSQL_HOST     = os.environ.get('CPS_MSSQL_HOST', '192.168.1.16')
    MSSQL_DATABASE = os.environ.get('CPS_MSSQL_DB', 'Solariz22')
    MSSQL_USER     = os.environ.get('CPS_MSSQL_USER', 'claude')
    MSSQL_PASSWORD = os.environ.get('CPS_MSSQL_PASS', '104099')
    MSSQL_PORT     = int(os.environ.get('CPS_MSSQL_PORT', '1433'))

    # ===================== REMOTE MES API =====================
    MES_API_URL = os.environ.get('CPS_MES_API_URL', 'http://192.168.1.16:5056')
    USE_REMOTE_API = False

    # ===================== SERVER =====================
    HOST  = '0.0.0.0'
    # CPS_PORT: ayrı test Flask sunucusu (opsiyonel; yoksa 8080)
    PORT  = int(os.environ.get('CPS_PORT', '8080'))
    MAX_UPLOAD_MB = 100
    ALLOWED_EXT   = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf', 'docx', 'xlsx', 'doc', 'xls'}
    UPLOAD_ROOT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    # Korgun SQL Server — LAN IP
    KORGUN_HOST = os.environ.get('CPS_KORGUN_HOST', '192.168.1.16')
    KORGUN_DB   = os.environ.get('CPS_KORGUN_DB', 'Solariz22')
    KORGUN_USER = os.environ.get('CPS_KORGUN_USER', 'claude')
    KORGUN_PASS = os.environ.get('CPS_KORGUN_PASS', '104099')
    KORGUN_PORT = int(os.environ.get('CPS_KORGUN_PORT', '1433'))
    DEBUG = True

    # ===================== SESSION =====================
    SECRET_KEY = os.environ.get('CPS_SECRET_KEY', 'cps-dev-secret-key-change-in-production')
    SESSION_DAYS = 30
    # ===================== D5 FAZ C.5 P6 (18.05.2026) =====================
    # CPS_NATIVE proses sistemi flag'i.
    # False: trigger sistemi aktif degil, sadece manuel + dry-run calisir.
    # True: lazy hook ve scheduler trigger calisabilir (P4 + C.8 sonrasi).
    # C.8 FLAG flip oncesi True YAPILMAZ.
    USE_CPS_NATIVE_PROSES = True

    # ===================== NEXGEN MPR =====================
    # Test modunu yalnızca geliştirme ortamında aktif et.
    # Production'da False olmalı — DB adı kontrolü KALDIRILDI (BR-G-06).
    MPR_TEST_MODE_ALLOWED = os.environ.get('MPR_TEST_MODE', 'false').lower() == 'true'

    # ===================== NEXGEN DEPO HAZIRLIK =====================
    # Pilot: False — Depo Hazırlık modülü geçici pasif; Bitir guard bypass, uretime-gonder kaydı yok.
    # Tam workflow: True — FAZ-5B (BEKLIYOR kaydı + HAZIR zorunlu Bitir kapısı).
    NEXGEN_DEPO_HAZIRLIK_ZORUNLU = os.environ.get(
        'NEXGEN_DEPO_HAZIRLIK_ZORUNLU', 'false'
    ).lower() == 'true'

    # ===================== NEXGEN UEM TABLET =====================
    # Pilot: False — Üretime Gönder sonrası batch tablet listelerinde görünür (marker zorunlu değil).
    # Legacy: True — yalnız __UEM_TABLET__ marker'lı batch'ler uretim-isleri / ferhat / is-listesi'nde.
    NEXGEN_UEM_TABLET_ZORUNLU = os.environ.get(
        'NEXGEN_UEM_TABLET_ZORUNLU', 'false'
    ).lower() == 'true'