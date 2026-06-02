import sys
sys.path.insert(0, r'C:\cps_dev')

import pytds
from config import Config

con = pytds.connect(
    server=getattr(Config, 'KORGUN_HOST', '25.7.184.221'),
    database=getattr(Config, 'KORGUN_DB', 'Solariz22'),
    user=getattr(Config, 'KORGUN_USER', 'claude'),
    password=getattr(Config, 'KORGUN_PASS', '104099'),
    port=int(getattr(Config, 'KORGUN_PORT', 1433)),
    timeout=30, login_timeout=10,
)

try:
    cur = con.cursor()

    print('=== Urt_Emir: 110626, 110648, 110649 ===')
    cur.execute("""
        SELECT
            e.EmirNo,
            e.ModelKod,
            UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
            e.YazSay,
            ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
            LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum
        FROM Urt_Emir e
        LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
        WHERE e.EmirNo IN (110626, 110648, 110649)
        ORDER BY e.EmirNo
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Siparis_Har: SKOD CRX-71033-LCW ===')
    cur.execute("""
        SELECT
            sh.SipNo, sh.SKOD, sh.Miktar,
            LTRIM(RTRIM(ISNULL(sh.Durum,''))) AS Durum
        FROM Siparis_Har sh
        WHERE sh.SKOD = 'CRX-71033-LCW'
        ORDER BY sh.SipNo
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Urt_Em2Em: 110626 alt emirleri ===')
    cur.execute("""
        SELECT EmirNo, EmirNo_YM, Proses, SKod
        FROM Urt_Em2Em
        WHERE EmirNo = 110626
    """)
    for r in cur.fetchall():
        print(r)

    cur.close()
finally:
    con.close()

print()
print('TAMAM')