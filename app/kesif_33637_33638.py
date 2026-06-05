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

    print('=== Siparis 33637 (KAUCUK) tum emirler ===')
    cur.execute("""
        SELECT DISTINCT EmirNo
        FROM Urt_Em_gch
        WHERE FisNo = 33637
        ORDER BY EmirNo
    """)
    em37 = [r[0] for r in cur.fetchall()]
    print('33637 emirler:', em37, 'Toplam:', len(em37))

    print()
    print('=== Siparis 33638 (ISIKSIZ) tum emirler ===')
    cur.execute("""
        SELECT DISTINCT EmirNo
        FROM Urt_Em_gch
        WHERE FisNo = 33638
        ORDER BY EmirNo
    """)
    em38 = [r[0] for r in cur.fetchall()]
    print('33638 emirler:', em38, 'Toplam:', len(em38))

    print()
    print('=== 33638 modeli ===')
    cur.execute("""
        SELECT TOP 1 SKOD, Tanim, Miktar
        FROM Siparis_Har
        WHERE SipNo = 33638
    """)
    print(cur.fetchone())

    print()
    print('=== 110626 hangi siparisten? ===')
    cur.execute("""
        SELECT DISTINCT FisNo
        FROM Urt_Em_gch
        WHERE EmirNo = 110626
    """)
    for r in cur.fetchall():
        print('110626 FisNo:', r[0])

    cur.close()
finally:
    con.close()
print('TAMAM')