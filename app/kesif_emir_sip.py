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

    print('=== Urt_Emir kolonlari (SipNo var mi?) ===')
    cur.execute("""
        SELECT TOP 1 *
        FROM Urt_Emir
        WHERE EmirNo = 110626
    """)
    cols = [d[0] for d in cur.description]
    print('Kolonlar:', cols)
    row = cur.fetchone()
    if row:
        for k, v in zip(cols, row):
            print(' ', k, '=', v)

    print()
    print('=== Urt_Em_gch FisNo (emir-sip baglantisi) ===')
    cur.execute("""
        SELECT DISTINCT FisNo
        FROM Urt_Em_gch
        WHERE EmirNo = 110626
    """)
    for r in cur.fetchall():
        print('FisNo:', r[0])

    print()
    print('=== Bu sipariste 110626 modeli var mi? ===')
    cur.execute("""
        SELECT sh.SipNo, sh.SKOD, sh.Miktar
        FROM Urt_Em_gch g
        INNER JOIN Siparis_Har sh ON sh.SipNo = g.FisNo
        WHERE g.EmirNo = 110626
          AND sh.SKOD = (SELECT TOP 1 ModelKod FROM Urt_Emir WHERE EmirNo = 110626)
    """)
    for r in cur.fetchall():
        print(r)

    cur.close()
finally:
    con.close()

print()
print('TAMAM')