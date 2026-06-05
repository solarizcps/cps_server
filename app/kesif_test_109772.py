import sys
sys.path.insert(0, r'C:\cps_dev')

# Once Korgun'dan alt emirleri al
import pytds
from config import Config
con_k = pytds.connect(
    server=getattr(Config, 'KORGUN_HOST', '25.7.184.221'),
    database=getattr(Config, 'KORGUN_DB', 'Solariz22'),
    user=getattr(Config, 'KORGUN_USER', 'claude'),
    password=getattr(Config, 'KORGUN_PASS', '104099'),
    port=int(getattr(Config, 'KORGUN_PORT', 1433)),
    timeout=30, login_timeout=10,
)
try:
    cur = con_k.cursor()
    print('=== Korgun: 109772 alt emirleri ===')
    cur.execute("""
        SELECT em.EmirNo_YM, e.ModelKod, ISNULL(m.Tanim, e.ModelKod), e.Tip
        FROM Urt_Em2Em em WITH(NOLOCK)
        INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
        LEFT JOIN Model_M m WITH(NOLOCK) ON m.ModelKod = e.ModelKod
        WHERE em.EmirNo = 109772
    """)
    alt_listesi = []
    for r in cur.fetchall():
        print(r)
        alt_listesi.append(str(r[0]))
    cur.close()
finally:
    con_k.close()

# Sonra CPS DB baseline
import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')
print()
print('=== CPS BASELINE: 109772 + alt emirler ===')
emirler = ['109772'] + alt_listesi
ph = ','.join(['?'] * len(emirler))
for r in c.execute(f"""
    SELECT id, emir_no, proses_adi, siralama, aktif, kaynak
    FROM emir_alt_proses
    WHERE emir_no IN ({ph})
    ORDER BY emir_no, siralama, id
""", tuple(emirler)):
    print(r)

print()
print('=== Sayim ===')
for r in c.execute(f"""
    SELECT emir_no, COUNT(1), SUM(CASE WHEN aktif=1 THEN 1 ELSE 0 END)
    FROM emir_alt_proses
    WHERE emir_no IN ({ph})
    GROUP BY emir_no
""", tuple(emirler)):
    print(r)
c.close()
print('TAMAM')

# Test sirasında bu liste lazim
print()
print('TEST EMIRLERI:', emirler)