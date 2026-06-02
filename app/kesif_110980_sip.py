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

    print('=== 110980 hangi sipariste? ===')
    cur.execute("""
        SELECT DISTINCT FisNo
        FROM Urt_Em_gch
        WHERE EmirNo = 110980
    """)
    for r in cur.fetchall():
        print('FisNo:', r[0])

    print()
    print('=== 110980 modeli ile aynı SKOD siparisleri ===')
    cur.execute("""
        SELECT TOP 5 sh.SipNo, sh.SKOD, sh.Miktar
        FROM Siparis_Har sh
        WHERE sh.SKOD = (SELECT TOP 1 ModelKod FROM Urt_Emir WHERE EmirNo = 110980)
          AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
    """)
    for r in cur.fetchall():
        print(r)

    cur.close()
finally:
    con.close()
print('TAMAM')