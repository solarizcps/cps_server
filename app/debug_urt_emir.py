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
    
    print('=== Urt_Emir: 110648 ve 110649 ===')
    cur.execute("""
        SELECT EmirNo, ModelKod, Tip
        FROM Urt_Emir WITH(NOLOCK)
        WHERE EmirNo IN (110648, 110649)
    """)
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)
    
    print()
    print('=== Urtx_Emir: 110648 ve 110649 ===')
    cur.execute("""
        SELECT EmirNo, ModelKod, Tip
        FROM Urtx_Emir WITH(NOLOCK)
        WHERE EmirNo IN (110648, 110649)
    """)
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)
    
    cur.close()
finally:
    con.close()

print('TAMAM')