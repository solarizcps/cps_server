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


def kategori(model_kod, model_adi):
    mk = (model_kod or '').upper()
    ma = (model_adi or '').upper().replace('Ğ', 'G').replace('Ö', 'O').replace('İ', 'I')
    if 'ATKI' in mk or 'ATKI' in ma:
        return 'ATKI'
    if 'GOVDE' in mk or 'GOVDE' in ma or 'EVA CRX-001' in mk:
        return 'GOVDE'
    if 'TABAN' in mk or 'TABAN' in ma:
        return 'TABAN'
    return 'MAMUL'


try:
    cur = con.cursor()

    # 1) 33638 emirleri (DISTINCT FisNo bazli)
    cur.execute("""
        SELECT DISTINCT EmirNo
        FROM Urt_Em_gch
        WHERE FisNo = 33638
        ORDER BY EmirNo
    """)
    emirler = [r[0] for r in cur.fetchall()]
    print('=== 33638 Tum Emirler (' + str(len(emirler)) + ') ===')
    print(emirler)

    # 2) Her emirin model bilgisi
    if not emirler:
        print('33638 emir yok')
        sys.exit(0)

    ph = ','.join(['%s'] * len(emirler))
    cur.execute(f"""
        SELECT e.EmirNo, e.ModelKod, e.Tip,
               ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
               e.YazSay
        FROM Urt_Emir e WITH (NOLOCK)
        LEFT JOIN Model_M m WITH (NOLOCK) ON m.ModelKod = e.ModelKod
        WHERE e.EmirNo IN ({ph})
        ORDER BY e.EmirNo
    """, tuple(emirler))
    emir_meta = {}
    for r in cur.fetchall():
        emir_meta[int(r[0])] = {
            'model_kod': r[1] or '',
            'tip': (r[2] or '').strip().upper(),
            'model_adi': r[3] or '',
            'yaz_say': r[4],
            'kategori': kategori(r[1], r[3]),
        }

    print()
    print('=== Emir bazli kategori ===')
    print('EmirNo  | Tip | Kategori | ModelKod      | ModelAdi (kisaltilmis)')
    for e in emirler:
        m = emir_meta.get(e)
        if m:
            print(f"{e}  | {m['tip']}   | {m['kategori']:<7} | {m['model_kod']:<14} | {m['model_adi'][:50]}")

    # 3) Kategori dagilim sayisi
    print()
    print('=== Kategori dagilim ===')
    kat_say = {'ATKI': 0, 'GOVDE': 0, 'TABAN': 0, 'MAMUL': 0}
    for e in emirler:
        m = emir_meta.get(e)
        if m:
            kat_say[m['kategori']] = kat_say.get(m['kategori'], 0) + 1
    for k, v in kat_say.items():
        print(f"  {k}: {v} emir")

    # 4) Her emir icin Korgun proses miktarlari
    print()
    print('=== Her emir icin Urt_con_gch SUM(Cikan) per Proses ===')
    cur.execute(f"""
        SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS yapilan
        FROM Urt_con_gch g WITH (NOLOCK)
        WHERE g.EmirNo IN ({ph}) AND g.Cikan > 0
        GROUP BY g.EmirNo, g.Proses
        ORDER BY g.EmirNo, g.Proses
    """, tuple(emirler))
    proses_map = {}
    for r in cur.fetchall():
        en = int(r[0])
        if en not in proses_map:
            proses_map[en] = []
        proses_map[en].append({
            'proses': r[1],
            'yapilan': int(float(r[2] or 0)),
        })

    for e in emirler:
        m = emir_meta.get(e, {})
        ps = proses_map.get(e, [])
        if ps:
            ps_str = ', '.join([f"{p['proses']}={p['yapilan']}" for p in ps])
            print(f"  {e} ({m.get('kategori','?'):<5}): {ps_str}")
        else:
            print(f"  {e} ({m.get('kategori','?'):<5}): YOK")

    # 5) Her emir icin "son proses" (numerik MAX) ve miktar
    print()
    print('=== Her emir son proses (proses_kod numerik MAX) ===')
    emir_son = {}
    for e in emirler:
        ps = proses_map.get(e, [])
        if not ps:
            emir_son[e] = {'son_proses': None, 'yapilan': 0}
            continue
        max_kod = -1
        son_yp = 0
        son_pr = None
        for p in ps:
            try:
                kod = int(p['proses'])
            except Exception:
                continue
            if kod > max_kod:
                max_kod = kod
                son_yp = p['yapilan']
                son_pr = p['proses']
        emir_son[e] = {'son_proses': son_pr, 'yapilan': son_yp}

    # 6) Kategori bazli toplam
    print()
    print('=== Kategori bazli toplam (son proses miktari toplami) ===')
    kat_toplam = {'ATKI': 0, 'GOVDE': 0, 'TABAN': 0, 'MAMUL': 0}
    kat_emirler = {'ATKI': [], 'GOVDE': [], 'TABAN': [], 'MAMUL': []}
    for e in emirler:
        m = emir_meta.get(e)
        s = emir_son.get(e)
        if m and s:
            k = m['kategori']
            kat_toplam[k] = kat_toplam.get(k, 0) + (s['yapilan'] or 0)
            kat_emirler[k].append((e, s['son_proses'], s['yapilan']))

    for k in ['MAMUL', 'ATKI', 'GOVDE', 'TABAN']:
        print(f"  {k}: TOPLAM = {kat_toplam[k]}")
        for em, pr, yp in kat_emirler[k]:
            print(f"    {em}: proses={pr}, yapilan={yp}")

    # 7) Hedef
    print()
    print('=== Siparis 33638 hedef ===')
    cur.execute("""
        SELECT SUM(Miktar)
        FROM Siparis_Har WITH (NOLOCK)
        WHERE SipNo = 33638
          AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
    """)
    hedef = int(float(cur.fetchone()[0] or 0))
    print(f"  Hedef: {hedef} cift")

    # 8) Darbogaz hesabi
    print()
    print('=== Darbogaz hesabi ===')
    print(f"  ATKI tamamlanan: {kat_toplam['ATKI']}")
    print(f"  GOVDE tamamlanan: {kat_toplam['GOVDE']}")
    print(f"  MAMUL tamamlanan: {kat_toplam['MAMUL']}")
    yapilan = min(kat_toplam['ATKI'], kat_toplam['GOVDE'], kat_toplam['MAMUL'])
    print(f"  YAPILAN_DARBOGAZ = min(...) = {yapilan}")
    if hedef > 0:
        print(f"  KALAN = {hedef - yapilan}")
        print(f"  YUZDE = {round(yapilan / hedef * 100, 1)}%")

    cur.close()
finally:
    con.close()
print('TAMAM')