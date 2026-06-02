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
    
    print('=== 33680 emirleri ve YazSay ===')
    cur.execute("""
        SELECT g.EmirNo, e.YazSay, e.ModelKod, e.Tip
        FROM Urt_Em_gch g WITH (NOLOCK)
        LEFT JOIN Urt_Emir e WITH (NOLOCK) ON e.EmirNo = g.EmirNo
        WHERE g.FisNo = 33680
        UNION
        SELECT g.EmirNo, e.YazSay, e.ModelKod, e.Tip
        FROM Urt_Em_gch g WITH (NOLOCK)
        LEFT JOIN Urtx_Emir e WITH (NOLOCK) ON e.EmirNo = g.EmirNo
        WHERE g.FisNo = 33680
    """)
    for r in cur.fetchall():
        print(f'EmirNo={r[0]}, YazSay={r[1]}, Model={r[2]}, Tip={r[3]}')

    print()
    print('=== Urt_Em_gch detayı (Miktar/RKOD/BedKod) ===')
    cur.execute("""
        SELECT TOP 20 EmirNo, FisNo, FisHarinx, RKOD, BedKod, Giren, Cikan
        FROM Urt_Em_gch WITH (NOLOCK)
        WHERE FisNo = 33680
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Siparis_Har 33680 ===')
    cur.execute("""
        SELECT SipNo, SipHarinx, SKOD, Miktar, Birim, Durum
        FROM Siparis_Har WITH (NOLOCK)
        WHERE SipNo = 33680
    """)
    for r in cur.fetchall():
        print(r)

    cur.close()
finally:
    con.close()
print('TAMAM')