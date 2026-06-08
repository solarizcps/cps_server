# -*- coding: utf-8 -*-
"""
CPS DEV - Config
"""

import os


class Config:
    # ===================== DB MODE =====================
    # 🔥 PROD YAPILDI
    DB_MODE = 'mock'

    # ===================== MOCK =====================
    MOCK_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mock_data.db')

    # ===================== PROD (MSSQL) =====================
    # LAN IP — Korgun SQL Server
    MSSQL_HOST     = os.environ.get('CPS_MSSQL_HOST', '192.168.1.35')
    MSSQL_DATABASE = os.environ.get('CPS_MSSQL_DB', 'Solariz22')
    MSSQL_USER     = os.environ.get('CPS_MSSQL_USER', 'claude')
    MSSQL_PASSWORD = os.environ.get('CPS_MSSQL_PASS', '104099')
    MSSQL_PORT     = int(os.environ.get('CPS_MSSQL_PORT', '1433'))

    # ===================== REMOTE MES API =====================
    MES_API_URL = os.environ.get('CPS_MES_API_URL', 'http://192.168.1.35:5056')
    USE_REMOTE_API = False

    # ===================== SERVER =====================
    HOST  = '0.0.0.0'
    PORT  = 8080
    MAX_UPLOAD_MB = 50
    ALLOWED_EXT   = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf', 'docx', 'xlsx', 'doc', 'xls'}
    UPLOAD_ROOT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    # Korgun SQL Server — LAN IP
    KORGUN_HOST = os.environ.get('CPS_KORGUN_HOST', '192.168.1.35')
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