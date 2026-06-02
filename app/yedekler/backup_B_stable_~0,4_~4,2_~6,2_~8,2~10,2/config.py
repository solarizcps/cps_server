# -*- coding: utf-8 -*-
"""
CPS DEV - Config
DB_MODE ile mock (SQLite) veya prod (MSSQL) arasında geçiş yapılır.
"""
import os


class Config:
    # ===================== DB MODE =====================
    # 'mock' -> SQLite (notebook geliştirme)
    # 'prod' -> MSSQL Solariz22 (server)
    DB_MODE = os.environ.get('CPS_DB_MODE', 'mock')

    # ===================== MOCK (SQLite) =====================
    MOCK_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mock_data.db')

    # ===================== PROD (MSSQL) =====================
    MSSQL_HOST     = '192.168.1.16'
    MSSQL_DATABASE = 'Solariz22'
    MSSQL_USER     = 'claude'
    MSSQL_PASSWORD = '104099'
    MSSQL_PORT     = 1433

    # ===================== SERVER =====================
    HOST  = '0.0.0.0'
    PORT  = 5057
    DEBUG = True

    # ===================== UPLOADS =====================
    UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_UPLOAD_MB = 20

    # Izinli uzantilar (kucuk harfle).
    # Excel (.xlsx, .xls), PDF, yaygin gorsel formatlari, eski Office (.doc/.docx)
    ALLOWED_EXT = {
        # Dokuman
        'pdf',
        # Excel
        'xlsx', 'xls', 'xlsm',
        # Word (bazi anlasmalar Word olarak gelir)
        'docx', 'doc',
        # Gorsel
        'jpg', 'jpeg', 'png', 'webp', 'gif',
        # CSV
        'csv',
    }

    # MIME type beyaz liste - upload seviyesinde ikinci kontrol
    ALLOWED_MIME = {
        # PDF
        'application/pdf',
        # Excel
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # xlsx
        'application/vnd.ms-excel',                                           # xls
        'application/vnd.ms-excel.sheet.macroenabled.12',                     # xlsm
        # Word
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # docx
        'application/msword',                                                       # doc
        # Gorsel
        'image/jpeg', 'image/png', 'image/webp', 'image/gif',
        # CSV + duz metin (CSV bazen 'text/plain' gelir)
        'text/csv', 'application/csv', 'text/plain',
        # Bazen tarayicilar Excel'i bu tip olarak gonderir
        'application/octet-stream',  # fallback - uzantidan kontrol zaten var
    }

    # Belge tipi -> Onerilen uzanti eslesmesi (ipucu, zorlayici degil)
    BELGE_TIPI_UZANTI_IPUCU = {
        'ANLASMA_EXCEL':      {'xlsx', 'xls', 'xlsm'},
        'COMMERCIAL_INVOICE': {'pdf', 'xlsx', 'xls'},
        'PROFORMA':           {'pdf', 'xlsx', 'xls'},
        'BEYANNAME':          {'pdf'},
        'FATURA':             {'pdf'},
        'TEKNIK_CIZIM':       {'pdf', 'jpg', 'jpeg', 'png'},
        'GORSEL':             {'jpg', 'jpeg', 'png', 'webp', 'gif'},
        'SERTIFIKA':          {'pdf'},
        'DIGER':              None,  # hepsi serbest
    }

    # ===================== SESSION =====================
    SECRET_KEY = os.environ.get('CPS_SECRET_KEY', 'cps-dev-secret-key-change-in-production')
    SESSION_DAYS = 30
