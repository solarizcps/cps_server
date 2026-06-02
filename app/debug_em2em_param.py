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
    
    print('=== Test 1: WHERE em.EmirNo = 110626 (LITERAL) ===')
    cur.execute("""
        SELECT em.EmirNo, em.EmirNo_YM
        FROM Urt_Em2Em em WITH(NOLOCK)
        WHERE em.EmirNo = 110626
    """)
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)
    
    print()
    print('=== Test 2: WHERE em.EmirNo = %s (PARAM int) ===')
    cur.execute("""
        SELECT em.EmirNo, em.EmirNo_YM
        FROM Urt_Em2Em em WITH(NOLOCK)
        WHERE em.EmirNo = %s
    """, (110626,))
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)
    
    print()
    print('=== Test 3: tam backend sorgusu (param) ===')
    cur.execute("""
        SELECT e.EmirNo, e.ModelKod, e.Tip
          FROM Urt_Em2Em em WITH(NOLOCK)
          INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
         WHERE em.EmirNo = %s
    """, (110626,))
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)
    
    print()
    print('=== Test 4: StokKart JOIN ekle ===')
    cur.execute("""
        SELECT e.EmirNo, e.ModelKod, e.Tip, sk.Tanim
          FROM Urt_Em2Em em WITH(NOLOCK)
          INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
          LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
         WHERE em.EmirNo = %s
    """, (110626,))
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)
    
    cur.close()
finally:
    con.close()

print('TAMAM')