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

    print('=== Siparis_Har TOP 1 (33638) ===')
    cur.execute("""
        SELECT TOP 1 *
        FROM Siparis_Har
        WHERE SipNo = 33638
    """)
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if row:
        for k, v in zip(cols, row):
            preview = str(v)[:60] if v is not None else 'NULL'
            print(' ', k, '=', preview)
    else:
        print('Kayit yok')

    print()
    print('=== TUM KOLONLAR LISTESI ===')
    print(cols)

    print()
    print('=== 33638 icin TUM SATIRLAR (kac varyant?) ===')
    cur.execute("""
        SELECT COUNT(*)
        FROM Siparis_Har
        WHERE SipNo = 33638
    """)
    print('Toplam satir:', cur.fetchone()[0])

    cur.close()
finally:
    con.close()

print()
print('TAMAM')