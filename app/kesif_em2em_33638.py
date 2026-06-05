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

    # 33638'in tum 26 emirinin Em2Em bagi
    emirler = [110615, 110616, 110618, 110619, 110620, 110621, 110622, 110623,
               110624, 110625, 110626, 110627, 110628, 110629, 110630, 110631,
               110652, 110653, 110654, 110655, 110656, 110657, 110658, 110659,
               110660, 110661]
    ph = ','.join(['%s'] * len(emirler))

    print('=== Em2Em: Mamul -> Alt baglantilari (33638 emirleri) ===')
    cur.execute(f"""
        SELECT em.EmirNo AS Mamul, em.EmirNo_YM AS Alt, em.Proses
        FROM Urt_Em2Em em WITH (NOLOCK)
        WHERE em.EmirNo IN ({ph})
        ORDER BY em.EmirNo, em.EmirNo_YM
    """, tuple(emirler))
    bag_say = 0
    for r in cur.fetchall():
        print(f'  Mamul {r[0]} -> Alt {r[1]} (proses {r[2]})')
        bag_say += 1
    print(f'  Toplam Em2Em bagi: {bag_say}')

    print()
    print('=== Em2Em: ALT olarak gecen emirler (EmirNo_YM ile bagli olanlar) ===')
    cur.execute(f"""
        SELECT em.EmirNo AS Mamul, em.EmirNo_YM AS Alt, em.Proses
        FROM Urt_Em2Em em WITH (NOLOCK)
        WHERE em.EmirNo_YM IN ({ph})
        ORDER BY em.EmirNo_YM
    """, tuple(emirler))
    for r in cur.fetchall():
        print(f'  Alt {r[1]} <- Mamul {r[0]} (proses {r[2]})')

    cur.close()
finally:
    con.close()
print('TAMAM')