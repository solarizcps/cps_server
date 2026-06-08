import pyodbc
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    from config import Config
    _KORGUN_HOST = getattr(Config, 'KORGUN_HOST', '') or ''
    _KORGUN_DB   = getattr(Config, 'KORGUN_DB', 'Solariz22')
    _KORGUN_USER = getattr(Config, 'KORGUN_USER', 'claude')
    _KORGUN_PASS = getattr(Config, 'KORGUN_PASS', '104099')
except Exception:
    _KORGUN_HOST = os.environ.get('CPS_KORGUN_HOST', '')
    _KORGUN_DB   = os.environ.get('CPS_KORGUN_DB', 'Solariz22')
    _KORGUN_USER = os.environ.get('CPS_KORGUN_USER', 'claude')
    _KORGUN_PASS = os.environ.get('CPS_KORGUN_PASS', '104099')


def get_conn():
    if not _KORGUN_HOST:
        raise RuntimeError(
            "Korgun SQL Server IP tanimli degil. "
            "config.py icinde KORGUN_HOST veya CPS_KORGUN_HOST env var set edilmeli."
        )
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={_KORGUN_HOST};"
        f"DATABASE={_KORGUN_DB};"
        f"UID={_KORGUN_USER};"
        f"PWD={_KORGUN_PASS};"
        "TrustServerCertificate=yes;"
    )


def emir_getir(emir_no):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT TOP 1 
            emir_no,
            model,
            hedef_adet
        FROM emirler
        WHERE emir_no = ?
    """, emir_no)

    row = cur.fetchone()

    if not row:
        return None

    return {
        "emir_no": row.emir_no,
        "model": row.model,
        "hedef": row.hedef_adet
    }


def toplam_yapilan(emir_no):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT ISNULL(SUM(miktar),0)
        FROM uretim_kayit
        WHERE emir_no = ?
          AND onay_durum IN ('onaylandi','bekliyor')
    """, emir_no)

    toplam = cur.fetchone()[0]

    return toplam