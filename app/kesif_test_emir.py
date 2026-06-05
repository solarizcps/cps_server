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

    print('=== Atki/Govde alt emiri olan ana emirler (son 30) ===')
    cur.execute("""
        SELECT TOP 30
            em.EmirNo AS AnaEmir,
            COUNT(em.EmirNo_YM) AS AltSayisi,
            MAX(CASE WHEN UPPER(ISNULL(m.Tanim,'')) LIKE '%ATKI%' THEN 1 ELSE 0 END) AS Atki_Var,
            MAX(CASE WHEN UPPER(ISNULL(m.Tanim,'')) LIKE '%GOVDE%' OR UPPER(ISNULL(m.Tanim,'')) LIKE '%GÖVDE%' THEN 1 ELSE 0 END) AS Govde_Var
        FROM Urt_Em2Em em WITH(NOLOCK)
        INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
        LEFT JOIN Model_M m WITH(NOLOCK) ON m.ModelKod = e.ModelKod
        WHERE em.EmirNo != 110626
        GROUP BY em.EmirNo
        HAVING COUNT(em.EmirNo_YM) >= 2
        ORDER BY em.EmirNo DESC
    """)
    print('AnaEmir | AltSay | Atki | Govde')
    rows = cur.fetchall()
    for r in rows:
        print(r)

    print()
    print('=== Ilk 5 emirin alt detayi ===')
    if rows:
        ilk5 = [str(r[0]) for r in rows[:5]]
        ph = ','.join(['%s'] * len(ilk5))
        cur.execute(f"""
            SELECT em.EmirNo AS Ana, em.EmirNo_YM AS Alt,
                   e.ModelKod, ISNULL(m.Tanim, e.ModelKod) AS Tanim
            FROM Urt_Em2Em em WITH(NOLOCK)
            INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
            LEFT JOIN Model_M m WITH(NOLOCK) ON m.ModelKod = e.ModelKod
            WHERE em.EmirNo IN ({ph})
            ORDER BY em.EmirNo DESC, em.EmirNo_YM
        """, tuple([int(x) for x in ilk5]))
        for r in cur.fetchall():
            print(r)

    cur.close()
finally:
    con.close()

print('TAMAM')