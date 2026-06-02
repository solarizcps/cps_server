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

    print('=== Test 1: Backend SQL aynen ===')
    cur.execute("""
        SELECT TOP 10
            sk.SipNo, ck.CName, sh.SKOD, sh.Miktar
        FROM Siparis_Kay sk WITH (NOLOCK)
        INNER JOIN Siparis_Har sh WITH (NOLOCK) ON sh.SipNo = sk.SipNo
        LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = sk.CariKod
        WHERE LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
          AND EXISTS (SELECT 1 FROM Urt_Em_gch g WITH (NOLOCK) WHERE g.FisNo = sk.SipNo)
        ORDER BY sk.SipNo DESC
    """)
    rows = cur.fetchall()
    print(f'Sonuc: {len(rows)} satir')
    for r in rows:
        print(r)

    print()
    print('=== Test 2: 33637/33638/33558 ===')
    cur.execute("""
        SELECT sk.SipNo, sh.Durum, sh.SKOD, sh.Miktar
        FROM Siparis_Kay sk WITH (NOLOCK)
        INNER JOIN Siparis_Har sh WITH (NOLOCK) ON sh.SipNo = sk.SipNo
        WHERE sk.SipNo IN (33637, 33638, 33558)
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Test 3: Urt_Em_gch FisNo bu siparişler? ===')
    cur.execute("""
        SELECT DISTINCT FisNo
        FROM Urt_Em_gch WITH (NOLOCK)
        WHERE FisNo IN (33637, 33638, 33558)
    """)
    for r in cur.fetchall():
        print(r)

    cur.close()
finally:
    con.close()
print('TAMAM')