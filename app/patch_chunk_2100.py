"""PATCH: 2100 parametre limit fix.
SQL Server max 2100 parametre. Batch'i 500'erli chunk'lara bol.
Ayrica DUPLICATE siparisleri ele.
"""
import io, shutil, time, sys

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = '/* CHUNK 2100 FIX */'

with io.open(KP, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: zaten uygulanmis')
    sys.exit(0)

# 1) _sql_get_siparis_listesi - DISTINCT ekle (duplicate sil)
OLD1 = """        # 1) Aktif siparisler
        cur.execute(\"\"\"
            SELECT
                sk.SipNo,
                ISNULL(ck.CName, '-') AS CariAdi,
                sh.SKOD AS ModelKod,
                ISNULL(sm.Tanim, sh.SKOD) AS ModelAdi,
                sh.Miktar AS Hedef,
                CONVERT(VARCHAR(10), sh.TerminTarihi, 120) AS Termin,
                sk.BelgeNo,
                sk.CariKod
            FROM Siparis_Kay sk WITH (NOLOCK)
            INNER JOIN Siparis_Har sh WITH (NOLOCK) ON sh.SipNo = sk.SipNo
            LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = sk.CariKod
            LEFT JOIN StokKart sm WITH (NOLOCK) ON sm.SKod = sh.SKOD
            WHERE LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
              AND EXISTS (
                  SELECT 1 FROM Urt_Em_gch g WITH (NOLOCK)
                  WHERE g.FisNo = sk.SipNo
              )
            ORDER BY sk.SipNo DESC
        \"\"\")"""

NEW1 = """        # 1) Aktif siparisler /* CHUNK 2100 FIX */ DISTINCT eklendi
        cur.execute(\"\"\"
            SELECT DISTINCT
                sk.SipNo,
                ISNULL(ck.CName, '-') AS CariAdi,
                sh.SKOD AS ModelKod,
                ISNULL(sm.Tanim, sh.SKOD) AS ModelAdi,
                sh.Miktar AS Hedef,
                CONVERT(VARCHAR(10), sh.TerminTarihi, 120) AS Termin,
                sk.BelgeNo,
                sk.CariKod
            FROM Siparis_Kay sk WITH (NOLOCK)
            INNER JOIN Siparis_Har sh WITH (NOLOCK) ON sh.SipNo = sk.SipNo
            LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = sk.CariKod
            LEFT JOIN StokKart sm WITH (NOLOCK) ON sm.SKod = sh.SKOD
            WHERE LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
              AND EXISTS (
                  SELECT 1 FROM Urt_Em_gch g WITH (NOLOCK)
                  WHERE g.FisNo = sk.SipNo
              )
            ORDER BY sk.SipNo DESC
        \"\"\")"""

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    print('OK: DISTINCT eklendi')

# 2) _sql_siparis_listesi_full - chunk'lara bol
# Mevcut SQL: 2 batch sorgu, her biri tum emir listesini parametre olarak gonderiyor
# Cozum: emir listesi 500'erli chunk'lara bol, sonuclari topla
OLD2 = """        if not tum_emirler:
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
        cur.execute(f\"\"\"
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
        \"\"\", tuple(emir_listesi) + tuple(emir_listesi))

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
        cur.execute(f\"\"\"
            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urt_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses

            UNION ALL

            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urtx_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses
        \"\"\", tuple(emir_listesi) + tuple(emir_listesi))

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
                emir_meta[en]['son_proses_biten'] = bt"""

NEW2 = """        if not tum_emirler:
            cur.close()
            sonuc_bos = []
            for sip in siparisler:
                sip_kopya = dict(sip)
                sip_kopya['emir_sayisi'] = {'mamul': 0, 'atki': 0, 'govde': 0}
                sip_kopya['korgun'] = {'atki_tamamlanan': 0, 'govde_tamamlanan': 0, 'mamul_tamamlanan': 0}
                sonuc_bos.append(sip_kopya)
            return sonuc_bos

        emir_listesi = list(tum_emirler)
        emir_meta = {}

        # /* CHUNK 2100 FIX */ - 500'erli chunk
        CHUNK = 500
        for i in range(0, len(emir_listesi), CHUNK):
            chunk = emir_listesi[i:i+CHUNK]
            ph_em = ','.join(['%s'] * len(chunk))

            # 2) Emir bilgisi (Urt + Urtx) - 2x parametre = 1000 max
            cur.execute(f\"\"\"
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
            \"\"\", tuple(chunk) + tuple(chunk))

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

            # 3) Her emirin SON prosesi - chunk
            cur.execute(f\"\"\"
                SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
                FROM Urt_con_gch g WITH (NOLOCK)
                WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
                GROUP BY g.EmirNo, g.Proses

                UNION ALL

                SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
                FROM Urtx_con_gch g WITH (NOLOCK)
                WHERE g.EmirNo IN ({ph_em}) AND g.Cikan > 0
                GROUP BY g.EmirNo, g.Proses
            \"\"\", tuple(chunk) + tuple(chunk))

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
                    emir_meta[en]['son_proses_biten'] = bt"""

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    print('OK: chunk 500 eklendi')
else:
    print('HATA: anchor bulunamadi')
    sys.exit(1)

bak = KP + '.bak_pre_chunk_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(src)

print('TAMAM: 2100 parametre limit fix')