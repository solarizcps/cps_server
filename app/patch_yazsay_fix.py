"""yaz_say (lot sayısı) yerine Urt_Em_gch SUM(Giren) - gerçek çift hedef."""
import io, shutil, time, sys

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'

with io.open(KP, 'r', encoding='utf-8') as f:
    src = f.read()

if 'YAZSAY_FIX_GIREN' in src:
    print('SKIP: zaten var')
    sys.exit(0)

# _sql_get_siparis_emirler icine YazSay yerine SUM(Giren) ekle
# Mevcut kod: yaz=int(float(r[3] or 0))  (YazSay)
# Yeni: emir bazlı SUM(Giren) sözlüğünden al

OLD = """        emir_meta = {}
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                continue
            mk = r[1] or ''
            tip = r[2] or 'M'
            yaz = int(float(r[3] or 0))
            ma = r[4] or mk"""

NEW = """        emir_meta = {}
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                continue
            mk = r[1] or ''
            tip = r[2] or 'M'
            yaz = int(float(r[3] or 0))  # YAZSAY_FIX_GIREN: lot sayisi, gercek cift asagidaki sorgudan
            ma = r[4] or mk"""

if OLD not in src:
    print('HATA: anchor yok')
    sys.exit(1)

new_src = src.replace(OLD, NEW, 1)

# Em2Em sonrasi yeni sorgu ekle - emir bazli SUM(Giren)
ANCHOR_BAS = """        # 4) BITEN: Urt_con_gch + Urtx_con_gch UNION"""

if ANCHOR_BAS not in new_src:
    print('HATA: BITEN anchor yok')
    sys.exit(1)

YENI_BLOK = """        # YAZSAY_FIX_GIREN - gercek cift hedef (Urt_Em_gch SUM Giren)
        cur.execute(f\"\"\"
            SELECT EmirNo, SUM(ISNULL(Giren, 0)) AS Hedef
            FROM Urt_Em_gch WITH (NOLOCK)
            WHERE EmirNo IN ({ph})
            GROUP BY EmirNo
        \"\"\", tuple(gch_emirler))
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                gercek = int(float(r[1] or 0))
                if gercek > 0:
                    emir_meta[en]['yaz_say'] = gercek

        # 4) BITEN: Urt_con_gch + Urtx_con_gch UNION"""

new_src = new_src.replace(ANCHOR_BAS, YENI_BLOK, 1)

shutil.copy2(KP, KP + '.bak_yazsay_' + time.strftime('%Y%m%d_%H%M%S'))
with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(new_src)
print('OK: yaz_say -> Urt_Em_gch SUM(Giren) eklendi')