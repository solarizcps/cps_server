# -*- coding: utf-8 -*-
# _recon_korgun.py - SALT OKUMA analiz betigi
# Degistirme YOK. Sadece SELECT sorgulari.
# Calistir: python _recon_korgun.py
import sys, os, sqlite3
sys.path.insert(0, r'C:\Solariz_CPS_SERVER\app')
sys.stdout.reconfigure(encoding='utf-8')

EMIR = 111191
SEP = "-" * 60

# ============================================================
# BOLUM A: mock_data.db (local, baglanti gerekmez)
# ============================================================
print(SEP)
print("BOLUM A: mock_data.db (local)")
print(SEP)

DB_PATH = r'C:\Solariz_CPS_SERVER\app\mock_data.db'
con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

print(f"\n[A1] emir_alt_proses WHERE emir_no='{EMIR}'")
ea = con.execute("""
    SELECT id, proses_adi, hedef_adet, aktif, kaynak
    FROM emir_alt_proses WHERE emir_no=? ORDER BY aktif DESC, id
""", (str(EMIR),)).fetchall()
if ea:
    for r in ea:
        print(f"  id={r['id']}  aktif={r['aktif']}  hedef_adet={r['hedef_adet']}"
              f"  proses={str(r['proses_adi'])[:35]}"
              f"  kaynak={str(r['kaynak'] or '')[:45]}")
else:
    print("  KAYIT YOK")

print(f"\n[A2] emir_proses WHERE emir_no='{EMIR}' (5055 tablosu)")
try:
    ep = con.execute("""
        SELECT emir_no, proses_adi, limit_miktar
        FROM emir_proses WHERE emir_no=? ORDER BY id
    """, (str(EMIR),)).fetchall()
    if ep:
        for r in ep:
            print(f"  proses={r['proses_adi']}  limit_miktar={r['limit_miktar']}")
    else:
        print("  KAYIT YOK")
except Exception as ex:
    print(f"  TABLO YOK veya HATA: {ex}")

print(f"\n[A3] emir_alt_proses icinde 480 degeri gecen kayitlar")
ea480 = con.execute("""
    SELECT id, emir_no, proses_adi, hedef_adet, kaynak
    FROM emir_alt_proses WHERE hedef_adet = 480
    ORDER BY id DESC LIMIT 10
""").fetchall()
if ea480:
    for r in ea480:
        print(f"  id={r['id']}  emir={r['emir_no']}  hedef={r['hedef_adet']}"
              f"  proses={str(r['proses_adi'])[:35]}")
else:
    print("  480 hedef_adet bulunamadi")

con.close()

# 5055 snapshot
print(f"\n[A4] 5055 snapshot emir_proses WHERE emir_no='{EMIR}'")
DB_5055_PATHS = [
    r"D:\Ortak\Solariz-ARGE\solariz.db",
    r"D:\Firma_Ozel\adem\Solariz_CPS_SERVER\app\5055_snapshot\solariz.db",
]
db5055 = None
for p in DB_5055_PATHS:
    if os.path.exists(p):
        db5055 = p
        break
if db5055:
    con5 = sqlite3.connect(db5055)
    con5.row_factory = sqlite3.Row
    try:
        ep5 = con5.execute("""
            SELECT emir_no, proses_adi, limit_miktar
            FROM emir_proses WHERE emir_no=? ORDER BY id
        """, (str(EMIR),)).fetchall()
        print(f"  DB: {db5055}")
        if ep5:
            for r in ep5:
                print(f"  proses={r['proses_adi']}  limit_miktar={r['limit_miktar']}")
        else:
            print("  KAYIT YOK")
    except Exception as ex5:
        print(f"  HATA: {ex5}")
    con5.close()
else:
    print("  5055 snapshot bu makinede bulunamadi")

# ============================================================
# BOLUM B: Korgun MSSQL
# ============================================================
print(f"\n{SEP}")
print("BOLUM B: Korgun MSSQL")
print(SEP)

try:
    import pytds
    from config import Config
    host = getattr(Config, 'KORGUN_HOST', '127.0.0.1')
    port = int(getattr(Config, 'KORGUN_PORT', 1433))
    db   = getattr(Config, 'KORGUN_DB',   'Solariz22')
    user = getattr(Config, 'KORGUN_USER', 'claude')
    pw   = getattr(Config, 'KORGUN_PASS', '')
    print(f"\n[B0] Baglanti: {host}:{port}  DB={db}  User={user}")

    con2 = pytds.connect(server=host, database=db, user=user, password=pw,
                         port=port, timeout=8, login_timeout=8)
    cur = con2.cursor()
    print("  BAGLANTI BASARILI")

    # B1 - Urt_Emir
    print(f"\n[B1] Urt_Emir WHERE EmirNo={EMIR}")
    cur.execute("""
        SELECT EmirNo, ModelKod, LTRIM(RTRIM(ISNULL(Tip,''))) AS Tip,
               YazSay, LTRIM(RTRIM(ISNULL(Location,''))) AS Location,
               LTRIM(RTRIM(ISNULL(Durum,''))) AS Durum
        FROM Urt_Emir WHERE EmirNo = %s
    """, (EMIR,))
    row = cur.fetchone()
    if row:
        print(f"  EmirNo   = {row[0]}")
        print(f"  ModelKod = {row[1]}")
        print(f"  Tip      = {row[2]}")
        print(f"  YazSay   = {row[3]}")
        print(f"  Location = {row[4]}")
        print(f"  Durum    = {row[5]}")
        model_kod = row[1]
        tip       = str(row[2]).strip().upper()
        yaz_say   = row[3]
    else:
        print("  KAYIT YOK")
        model_kod = None
        tip       = None
        yaz_say   = None

    # B2 - Urt_Em_gch
    print(f"\n[B2] Urt_Em_gch WHERE EmirNo={EMIR}")
    cur.execute("""
        SELECT SUM(Giren) AS ToplamGiren, SUM(Cikan) AS ToplamCikan, COUNT(*) AS N
        FROM Urt_Em_gch WHERE EmirNo = %s
    """, (EMIR,))
    r2 = cur.fetchone()
    print(f"  SUM(Giren) = {r2[0]}   SUM(Cikan) = {r2[1]}   KayitSayisi = {r2[2]}")
    sum_giren = float(r2[0] or 0)

    cur.execute("""
        SELECT DISTINCT FisNo FROM Urt_Em_gch
        WHERE EmirNo = %s AND FisNo IS NOT NULL AND FisNo > 0
    """, (EMIR,))
    fis_list = [r[0] for r in cur.fetchall() if r and r[0]]
    print(f"  FisNo listesi = {fis_list}")

    # B3 - Urt_Em2Em
    print(f"\n[B3] Urt_Em2Em - {EMIR} parent (alt emirler)")
    cur.execute("""
        SELECT em.EmirNo_YM, e.ModelKod, LTRIM(RTRIM(ISNULL(e.Tip,''))) AS Tip,
               e.YazSay,
               COALESCE(g.toplam_giren, e.YazSay) AS EmirMiktari
        FROM Urt_Em2Em em
        INNER JOIN Urt_Emir e ON e.EmirNo = em.EmirNo_YM
        LEFT JOIN (
            SELECT EmirNo, SUM(Giren) AS toplam_giren
            FROM Urt_Em_gch GROUP BY EmirNo
        ) g ON g.EmirNo = e.EmirNo
        WHERE em.EmirNo = %s
    """, (EMIR,))
    children = cur.fetchall()
    print(f"  Alt emir sayisi: {len(children)}")
    for c in children:
        print(f"  child_EmirNo={c[0]}  ModelKod={c[1]}  Tip={c[2]}"
              f"  YazSay={c[3]}  EmirMiktari={c[4]}")

    print(f"\n[B3b] Urt_Em2Em - {EMIR} child (parent emirler)")
    cur.execute("""
        SELECT em.EmirNo, e.ModelKod, LTRIM(RTRIM(ISNULL(e.Tip,''))) AS Tip, e.YazSay
        FROM Urt_Em2Em em
        INNER JOIN Urt_Emir e ON e.EmirNo = em.EmirNo
        WHERE em.EmirNo_YM = %s
    """, (EMIR,))
    parents = cur.fetchall()
    print(f"  Parent emir sayisi: {len(parents)}")
    for p in parents:
        print(f"  parent_EmirNo={p[0]}  ModelKod={p[1]}  Tip={p[2]}  YazSay={p[3]}")

    # B4 - Siparis_Har
    if model_kod:
        print(f"\n[B4] Siparis_Har WHERE SKOD='{model_kod}'")
        if fis_list:
            ph = ','.join(['%s'] * len(fis_list))
            cur.execute(f"""
                SELECT sh.SipNo, sh.Miktar,
                       LTRIM(RTRIM(ISNULL(sh.Durum,''))) AS Durum,
                       ISNULL(ck.CName, '-') AS CariAdi
                FROM Siparis_Har sh
                LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                WHERE sh.SKOD = %s AND sh.SipNo IN ({ph})
            """, tuple([model_kod] + fis_list))
        else:
            cur.execute("""
                SELECT sh.SipNo, sh.Miktar,
                       LTRIM(RTRIM(ISNULL(sh.Durum,''))) AS Durum,
                       ISNULL(ck.CName, '-') AS CariAdi
                FROM Siparis_Har sh
                LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                WHERE sh.SKOD = %s
                ORDER BY sh.SipNo
            """, (model_kod,))
        sip_rows = cur.fetchall()
        print(f"  Siparis_Har satir sayisi: {len(sip_rows)}")
        for sr in sip_rows:
            print(f"  SipNo={sr[0]}  Miktar={sr[1]}  Durum='{sr[2]}'  Cari={sr[3]}")
        acik = sum(float(sr[1] or 0) for sr in sip_rows if not str(sr[2]).strip())
        print(f"  Acik Miktar toplami (Durum='') = {acik}")

    # B5 - Ozet: hangi kaynak ne veriyor
    print(f"\n{SEP}")
    print("OZET: Hangi kaynak ne veriyor?")
    print(SEP)
    print(f"  Urt_Emir.YazSay         = {yaz_say}")
    print(f"  Urt_Em_gch SUM(Giren)   = {sum_giren if sum_giren else 'N/A (hareket yok)'}")
    alt_miktarlar = [(c[0], c[4]) for c in children] if children else []
    for child_no, child_miktar in alt_miktarlar:
        print(f"  Alt Emir {child_no} EmirMiktari = {child_miktar}")
    print(f"  Siparis_Har toplami     = {acik if model_kod else 'N/A'}")
    print()
    print("  CPS_TRIGGER_C5 su an kullaniyor: get_emir_ozet().yaz_say")
    print("  Bu YazSay degeri: " + str(yaz_say))
    print()
    if yaz_say and int(yaz_say) == 480:
        print("  => YazSay = 480 DOGRU, fix calisacak")
    elif alt_miktarlar and any(m == 480 for _, m in alt_miktarlar):
        print("  => 480 degeri: alt emirin EmirMiktari - _resolve_target_emir dogrudan bulur")
    else:
        print("  => 480 BU KAYNAKLAR ARASINDA BULUNUMADI")
        print("     Olasi: Siparis_Har tek satir miktari veya baska bir alan")

    con2.close()

except Exception as e:
    print(f"\nKORGUN HATA: {type(e).__name__}: {str(e)[:300]}")

print(f"\n{'=' * 60}")
print("DONE")
print('=' * 60)
