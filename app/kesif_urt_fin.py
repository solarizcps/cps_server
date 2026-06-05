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

    print('=== Urt_Fin_gch: 110626, 110648, 110649 ===')
    cur.execute("""
        SELECT EmirNo, Proses, SUM(Cikan) AS Miktar
        FROM Urt_Fin_gch
        WHERE EmirNo IN (110626, 110648, 110649)
        GROUP BY EmirNo, Proses
        ORDER BY EmirNo, Proses
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Urt_con_gch: 110626, 110648, 110649 ===')
    cur.execute("""
        SELECT EmirNo, Proses, SUM(Cikan) AS Miktar
        FROM Urt_con_gch
        WHERE EmirNo IN (110626, 110648, 110649)
        GROUP BY EmirNo, Proses
        ORDER BY EmirNo, Proses
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Urtx_Fin_gch (paralel) ===')
    cur.execute("""
        SELECT EmirNo, Proses, SUM(Cikan) AS Miktar
        FROM Urtx_Fin_gch
        WHERE EmirNo IN (110626, 110648, 110649)
        GROUP BY EmirNo, Proses
        ORDER BY EmirNo, Proses
    """)
    for r in cur.fetchall():
        print(r)

    print()
    print('=== Urtx_con_gch (paralel) ===')
    cur.execute("""
        SELECT EmirNo, Proses, SUM(Cikan) AS Miktar
        FROM Urtx_con_gch
        WHERE EmirNo IN (110626, 110648, 110649)
        GROUP BY EmirNo, Proses
        ORDER BY EmirNo, Proses
    """)
    for r in cur.fetchall():
        print(r)

    cur.close()
finally:
    con.close()
print('TAMAM')