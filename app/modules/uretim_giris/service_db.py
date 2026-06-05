import pyodbc

def get_conn():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=25.7.184.221;"
        "DATABASE=Solariz22;"
        "UID=claude;"
        "PWD=104099;"
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