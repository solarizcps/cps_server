# FIX: hedef_plan_detay alt emir sorgusu Urt_Emir + Urtx_Emir UNION ALL
import io, sys, shutil, time

PATH = r'C:\cps_dev\modules\hedef\routes.py'
MARKER = '/* FAZ 4.10 ALT EMIR UNION ALL */'

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: alt emir union all zaten uygulanmis')
    sys.exit(0)

OLD_SQL = '''            cur.execute("""
                SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location,
                       sk.Tanim AS ModelAdi
                  FROM Urt_Em2Em em WITH(NOLOCK)
                  INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
                  LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
                 WHERE em.EmirNo = %s
            """, (emir_no,))'''

NEW_SQL = '''            # /* FAZ 4.10 ALT EMIR UNION ALL */
            # Alt emirler hem Urt_Emir hem Urtx_Emir tablosunda olabilir
            cur.execute("""
                SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location,
                       sk.Tanim AS ModelAdi
                  FROM Urt_Em2Em em WITH(NOLOCK)
                  INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
                  LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
                 WHERE em.EmirNo = %s
                UNION ALL
                SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location,
                       sk.Tanim AS ModelAdi
                  FROM Urt_Em2Em em WITH(NOLOCK)
                  INNER JOIN Urtx_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
                  LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
                 WHERE em.EmirNo = %s
            """, (emir_no, emir_no))'''

if OLD_SQL not in src:
    print('HATA: anchor bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD_SQL, NEW_SQL, 1)

bak = PATH + '.bak_pre_unionall_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: alt emir UNION ALL eklendi (' + str(artis) + ' byte)')