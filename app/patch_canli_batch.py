"""PATCH: PLAN listesi tek batch SQL ile cek (yavaslık fix).

Eski: her siparis icin ayri _sql_get_siparis_emirler() = 250+ sorgu
Yeni: 1 batch sorgu tum siparisler+emirler+prosesler

PLAN listesi sadece OZET bilgisi (siparis basligi).
Detay tek sipariş icin tıklayinca _sql_get_siparis_emirler() cagrilir.
"""
import io, sys, shutil, time

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = '/* CANLI BATCH FIX */'

with io.open(KP, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: batch fix zaten uygulanmis')
    sys.exit(0)

# _sql_siparis_listesi_full'u ezilen versiyon ile degistir
OLD = '''def _sql_siparis_listesi_full():
    """Tum aktif siparisleri ozet bilgi ile dondurur (PLAN listesi icin)."""
    siparisler = _sql_get_siparis_listesi()
    sonuc = []
    for sip in siparisler:
        try:
            emirler = _sql_get_siparis_emirler(sip['sip_no'])
        except Exception as e:
            try:
                print(f'[korgun_v2 SQL hata sip {sip["sip_no"]}]: {e}')
            except Exception:
                pass
            emirler = []

        # Kategorize
        atki_emirler = [e for e in emirler if e.get('kategori') == 'ATKI']
        govde_emirler = [e for e in emirler if e.get('kategori') == 'GOVDE']
        mamul_emirler = [e for e in emirler if e.get('kategori') == 'MAMUL']

        atki_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in atki_emirler)
        govde_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in govde_emirler)
        mamul_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in mamul_emirler)

        sip_kopya = dict(sip)
        sip_kopya['emir_sayisi'] = {
            'mamul': len(mamul_emirler),
            'atki': len(atki_emirler),
            'govde': len(govde_emirler),
        }
        sip_kopya['korgun'] = {
            'atki_tamamlanan': atki_t,
            'govde_tamamlanan': govde_t,
            'mamul_tamamlanan': mamul_t,
        }
        # Detay icin emir listesini sakla
        sip_kopya['_emirler_cache'] = emirler
        sonuc.append(sip_kopya)
    return sonuc'''

NEW = '''def _sql_siparis_listesi_full():
    """Tum aktif siparisleri ozet bilgi ile dondurur.
    /* CANLI BATCH FIX */ - tek sorguda tum siparis+emir+proses bilgisi.
    PLAN listesi icin hizli, detay tıklayinca ayri sorgu.
    """
    siparisler = _sql_get_siparis_listesi()
    if not siparisler:
        return []

    sip_no_listesi = [s['sip_no'] for s in siparisler]

    # Tek batch: tum siparislerin tum emirlerini cek
    con = _korgun_baglan()
    try:
        cur = con.cursor()
        ph_sip = ','.join(['%s'] * len(sip_no_listesi))

        # 1) Tum sip -> emir map
        cur.execute(f"""
            SELECT DISTINCT g.FisNo, g.EmirNo
            FROM Urt_Em_gch g WITH (NOLOCK)
            WHERE g.FisNo IN ({ph_sip})
        """, tuple(sip_no_listesi))

        sip_emir_map = {}  # sip_no -> [emir_no_list]
        tum_emirler = set()
        for r in cur.fetchall():
            sn = int(r[0])
            en = int(r[1])
            if sn not in sip_emir_map:
                sip_emir_map[sn] = []
            sip_emir_map[sn].append(en)
            tum_emirler.add(en)

        if not tum_emirler:
            cur.close()
            sonuc_bos = []
            for sip in siparisler:
                sip_kopya = dict(sip)
                sip_kopya['emir_sayisi'] = {'mamul': 0, 'atki': 0, 'govde': 0}
                sip_kopya['korgun'] = {'atki_tamamlanan': 0, 'govde_tamamlanan': 0, 'mamul_tamamlanan': 0}
                sonuc_bos.append(sip_kopya)
            return sonuc_bos

        emir_listesi = list(tum_emirler)
        ph_em = ','.join(['%s'] * len(emir_listesi))

        # 2) Emir bilgisi (Urt + Urtx)
        cur.execute(f"""
            SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                   ISNULL(e.YazSay, 0) AS YazSay,
                   ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
            FROM Urt_Emir e WITH (NOLOCK)
            LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
            WHERE e.EmirNo IN ({ph_em})

            UNION ALL

            SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                   ISNULL(e.YazSay, 0) AS YazSay,
                   ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
            FROM Urtx_Emir e WITH (NOLOCK)
            LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
            WHERE e.EmirNo IN ({ph_em})
        """, tuple(emir_listesi) + tuple(emir_listesi))

        emir_meta = {}
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                continue
            mk = r[1] or ''
            ma = r[4] or mk
            emir_meta[en] = {
                'emir_no': en,
                'model_kod': mk,
                'tip': r[2] or 'M',
                'yaz_say': int(float(r[3] or 0)),
                'kategori': _kategori_belirle(mk, ma),
                'son_proses_kod': -1,
                'son_proses_biten': 0,
            }

        # 3) Her emirin SON prosesi (numerik MAX) ve biten miktari
        cur.execute(f"""
            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urt_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses

            UNION ALL

            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urtx_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses
        """, tuple(emir_listesi) + tuple(emir_listesi))

        # Her emir icin en yuksek proses_kod numerik MAX'in biten'i
        for r in cur.fetchall():
            en = int(r[0])
            pr = str(r[1]).strip()
            try:
                pr_int = int(pr)
            except Exception:
                continue
            bt = int(float(r[2] or 0))
            if en not in emir_meta:
                continue
            if pr_int > emir_meta[en]['son_proses_kod']:
                emir_meta[en]['son_proses_kod'] = pr_int
                emir_meta[en]['son_proses_biten'] = bt

        cur.close()
    finally:
        con.close()

    # 4) Her siparis icin ozet hesapla
    sonuc = []
    for sip in siparisler:
        sn = sip['sip_no']
        emir_nos = sip_emir_map.get(sn, [])

        atki_t = 0
        govde_t = 0
        mamul_t = 0
        atki_count = 0
        govde_count = 0
        mamul_count = 0

        for en in emir_nos:
            meta = emir_meta.get(en)
            if not meta:
                continue
            kat = meta['kategori']
            if kat == 'ATKI':
                atki_count += 1
                atki_t += meta['son_proses_biten']
            elif kat == 'GOVDE':
                govde_count += 1
                govde_t += meta['son_proses_biten']
            elif kat == 'MAMUL':
                mamul_count += 1
                mamul_t += meta['son_proses_biten']

        sip_kopya = dict(sip)
        sip_kopya['emir_sayisi'] = {
            'mamul': mamul_count,
            'atki': atki_count,
            'govde': govde_count,
        }
        sip_kopya['korgun'] = {
            'atki_tamamlanan': atki_t,
            'govde_tamamlanan': govde_t,
            'mamul_tamamlanan': mamul_t,
        }
        sonuc.append(sip_kopya)

    return sonuc'''

if OLD not in src:
    print('HATA: _sql_siparis_listesi_full anchor bulunamadi')
    sys.exit(1)

new_src = src.replace(OLD, NEW, 1)

bak = KP + '.bak_pre_batch_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: batch fix uygulandi (' + str(artis) + ' byte degisim)')
print('  - PLAN listesi: 1 batch sorgu (eski: N siparis x 5 sorgu)')
print('  - Detay: ayrı sorgu (tikla zamani)')