# -*- coding: utf-8 -*-
"""CPS - Korgun MSSQL Servisi (Faz 4.3)"""
import pytds
from config import Config


def _baglan():
    host = getattr(Config, 'KORGUN_HOST', '') or ''
    if not host:
        raise RuntimeError(
            "Korgun SQL Server IP tanimli degil. "
            "config.py icinde KORGUN_HOST veya CPS_KORGUN_HOST env var set edilmeli."
        )
    return pytds.connect(
        server=host,
        database=getattr(Config, 'KORGUN_DB', 'Solariz22'),
        user=getattr(Config, 'KORGUN_USER', 'claude'),
        password=getattr(Config, 'KORGUN_PASS', '104099'),
        port=int(getattr(Config, 'KORGUN_PORT', 1433)),
        timeout=10, login_timeout=10,
    )


_PROSES_TANIM = {
    '02': 'Kesim', '15': 'Saya', '18': 'Saya Kontrol',
    '26': 'Enjeksiyon', '28': 'Monta Baslayacak', '30': 'Monta',
    '32': 'Mekval', '35': 'Temizleme', '42': 'Saya Hazir', '50': 'Eva Hazir',
}


def get_emir_ozet(emir_no):
    """Emir genel bilgi: tip, hedef, yapilan, kalan, cari, siparis."""
    try:
        emir_no_int = int(emir_no)
        if emir_no_int <= 0:
            return {'ok': False, 'hata': 'gecersiz_emir'}
    except Exception:
        return {'ok': False, 'hata': 'gecersiz_emir'}

    try:
        con = _baglan()
        try:
            cur = con.cursor()

            # 1) Emir + model
            cur.execute("""
                SELECT TOP 1
                    e.EmirNo, e.ModelKod, e.Tip, e.Location,
                    LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                    ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                    CONVERT(VARCHAR(10), e.TerTarih, 120) AS TerTarih,
                    e.YazSay
                FROM Urt_Emir e
                LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                WHERE e.EmirNo = %s
            """, (emir_no_int,))
            row = cur.fetchone()
            if not row:
                return {'ok': False, 'hata': 'emir_bulunamadi',
                        'mesaj': f'Emir {emir_no_int} bulunamadi'}

            emir_no_db, model_kod, tip, location, durum, model_adi, ter_tarih, yaz_say = row
            tip = (tip or '').strip().upper()
            location = (location or '').strip()

            # 2) Yapilan (her tip icin)
            cur.execute("""
                SELECT COALESCE(SUM(Cikan), 0), COALESCE(SUM(Giren), 0), COUNT(*)
                FROM Urt_Em_gch
                WHERE EmirNo = %s
            """, (emir_no_int,))
            yapilan, giren, kayit_sayisi = cur.fetchone()
            yapilan = float(yapilan or 0)

            # 3) Hedef + Cari/SipNo
            #    Mamul (M): Siparis_Har'dan toplam
            #    Yari mamul (Y): parent emirden bul (Urt_Em2Em)
            hedef = 0.0
            siparisler = []
            cari_adi = None

            if tip == 'M':
                # === FAZ 4.7 HEDEF: FisNo bazli hedef ===
                # Once emirin gercek FisNo'larini bul (Urt_Em_gch.FisNo = Siparis_Kay.SipNo)
                cur.execute("""
                    SELECT DISTINCT FisNo
                    FROM Urt_Em_gch
                    WHERE EmirNo = %s
                      AND FisNo IS NOT NULL
                      AND FisNo > 0
                """, (emir_no_int,))
                _fis_listesi_47 = [r[0] for r in cur.fetchall() if r and r[0]]
                
                if _fis_listesi_47:
                    # FisNo bulundu - sadece bu siparis(ler)den hedef
                    _ph = ','.join(['%s'] * len(_fis_listesi_47))
                    cur.execute("""
                        SELECT sh.SipNo, sh.Miktar, sh.Tanim,
                               ISNULL(ck.CName, '-') AS CariAdi
                        FROM Siparis_Har sh
                        LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                        LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                        WHERE sh.SKOD = %s
                          AND sh.SipNo IN (""" + _ph + """)
                          AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                    """, tuple([model_kod] + _fis_listesi_47))
                else:
                    # Fallback: hareket yok (yeni emir), eski SKOD bazli (geriye uyumlu)
                    cur.execute("""
                        SELECT sh.SipNo, sh.Miktar, sh.Tanim,
                               ISNULL(ck.CName, '-') AS CariAdi
                        FROM Siparis_Har sh
                        LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                        LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                        WHERE sh.SKOD = %s
                          AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                    """, (model_kod,))
                
                for r in cur.fetchall():
                    sip_no, miktar, tanim, ca = r
                    miktar_f = float(miktar or 0)
                    hedef += miktar_f
                    siparisler.append({
                        'sip_no': sip_no,
                        'miktar': int(miktar_f) if miktar_f == int(miktar_f) else miktar_f,
                        'tanim': tanim,
                        'cari_adi': ca,
                    })
                    if not cari_adi and ca and ca != '-':
                        cari_adi = ca
                # === /FAZ 4.7 HEDEF (M tipi) ===

            elif tip == 'Y':
                # === FAZ 4.7 HEDEF: Y tipi parent hedefi miras alir ===
                # Parent emiri bul
                cur.execute("""
                    SELECT TOP 5 EmirNo, Proses, SKod
                    FROM Urt_Em2Em
                    WHERE EmirNo_YM = %s
                """, (emir_no_int,))
                parent_list = cur.fetchall()
                if parent_list:
                    parent_no = parent_list[0][0]
                    # Parent emirin modelini al
                    cur.execute("""
                        SELECT TOP 1 e.ModelKod
                        FROM Urt_Emir e
                        WHERE e.EmirNo = %s
                    """, (parent_no,))
                    p_row = cur.fetchone()
                    if p_row:
                        p_model = p_row[0]
                        # Parent'in FisNo'larini bul
                        cur.execute("""
                            SELECT DISTINCT FisNo
                            FROM Urt_Em_gch
                            WHERE EmirNo = %s
                              AND FisNo IS NOT NULL
                              AND FisNo > 0
                        """, (parent_no,))
                        _pfis_47 = [r[0] for r in cur.fetchall() if r and r[0]]
                        
                        if _pfis_47:
                            # Parent'in gercek siparisleri uzerinden hedef
                            _ph_y = ','.join(['%s'] * len(_pfis_47))
                            cur.execute("""
                                SELECT COALESCE(SUM(Miktar), 0)
                                FROM Siparis_Har
                                WHERE SKOD = %s
                                  AND SipNo IN (""" + _ph_y + """)
                                  AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                            """, tuple([p_model] + _pfis_47))
                        else:
                            # Fallback: parent'in de hareketi yoksa eski mantik
                            cur.execute("""
                                SELECT COALESCE(SUM(Miktar), 0)
                                FROM Siparis_Har
                                WHERE SKOD = %s
                                  AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                            """, (p_model,))
                        hedef = float(cur.fetchone()[0] or 0)
                # === /FAZ 4.7 HEDEF (Y tipi) ===

            kalan = max(0, hedef - yapilan)

            cur.close()

            return {
                'ok': True,
                'emir_no': emir_no_int,
                'model_kod': model_kod,
                'model_adi': model_adi,
                'tip': tip,
                'tip_aciklama': 'Mamul' if tip == 'M' else ('Yari Mamul' if tip == 'Y' else tip),
                'durum': durum,
                'location': location,
                'termin_tarihi': ter_tarih,
                'yaz_say': yaz_say,
                'cari_adi': cari_adi,
                'siparisler': siparisler,
                'siparis_sayisi': len(siparisler),
                'hedef_adet': int(hedef) if hedef == int(hedef) else hedef,
                'yapilan_adet': int(yapilan) if yapilan == int(yapilan) else yapilan,
                'gerceklesen_adet': int(yapilan) if yapilan == int(yapilan) else yapilan,  # JS uyumlulugu
                'plan_var_mi': hedef > 0,  # JS bunu bekliyor
                'kalan_adet': int(kalan) if kalan == int(kalan) else kalan,
                'uretim_kayit_sayisi': int(kayit_sayisi),
            }
        finally:
            con.close()
    except Exception as e:
        return {'ok': False, 'hata': 'sistem_hatasi',
                'mesaj': f'{type(e).__name__}: {str(e)[:200]}'}


def saglik_kontrol():
    try:
        con = _baglan()
        cur = con.cursor()
        cur.execute('SELECT 1')
        cur.fetchone()
        cur.close()
        con.close()
        return True
    except Exception:
        return False



# === FAZ 4.6 B1: get_siparis_emirleri ===
def get_siparis_emirleri(sip_no):
    """Bir siparise ait tum emirler: ana (Tip='M') + alt/yari (Tip='Y').

    Akis:
      1. Siparis_Har -> SKOD listesi -> Urt_Emir (Tip='M') -> ana emirler
      2. Her ana emir icin Urt_Em2Em -> Urt_Emir (Tip='Y') -> yari mamul emirler
    """
    try:
        sip_no_int = int(sip_no)
        if sip_no_int <= 0:
            return {'ok': False, 'hata': 'gecersiz_sipno', 'emirler': []}
    except Exception:
        return {'ok': False, 'hata': 'gecersiz_sipno', 'emirler': []}

    try:
        con = _baglan()
        try:
            cur = con.cursor()

            # 1) Ana emirler (Tip='M') -- FAZ 4.6 B3: Cari_Kart JOIN ile CariAdi
            cur.execute("""
                SELECT DISTINCT
                    e.EmirNo, e.ModelKod, e.Tip,
                    ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                    e.Location,
                    LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                    e.YazSay,
                    sh.SipNo,
                    sh.Miktar AS HedefMiktar,
                    ISNULL(ck.CName, '-') AS CariAdi
                FROM Siparis_Har sh
                INNER JOIN Urt_Emir e ON e.ModelKod = sh.SKOD
                LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                WHERE sh.SipNo = %s
                  AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                  AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'M'
                ORDER BY e.EmirNo
            """, (sip_no_int,))
            ana_rows = cur.fetchall()
            ana_cols = [d[0] for d in cur.description]
            ana_dicts = [dict(zip(ana_cols, r)) for r in ana_rows]
            ana_emir_nos = [int(d['EmirNo']) for d in ana_dicts]

            # 2) Yari mamul emirler (Tip='Y') - Urt_Em2Em ile parent eslestirme
            yari_dicts = []
            if ana_emir_nos:
                placeholders = ','.join(['%s'] * len(ana_emir_nos))
                cur.execute(f"""
                    SELECT
                        e.EmirNo, e.ModelKod, e.Tip,
                        ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                        e.Location,
                        LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                        e.YazSay,
                        em2em.EmirNo AS ParentEmirNo
                    FROM Urt_Em2Em em2em
                    INNER JOIN Urt_Emir e ON e.EmirNo = em2em.EmirNo_YM
                    LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                    WHERE em2em.EmirNo IN ({placeholders})
                      AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'Y'
                    ORDER BY e.EmirNo
                """, tuple(ana_emir_nos))
                yari_rows = cur.fetchall()
                yari_cols = [d[0] for d in cur.description]
                yari_dicts = [dict(zip(yari_cols, r)) for r in yari_rows]

            # Sonuc liste
            emirler = []
            # === FAZ 4.6 B3 polish ===
            # Ana emir EmirMiktari = SUM(Giren) (alt ile tutarli, gercek lot miktari)
            # Fallback: Siparis_Har.Miktar (Urt_Em_gch'de hareket yoksa)
            # Bu blokun sonunda emir_giren_map ile guncellenecek
            parent_cari_map = {}
            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                hm_f = float(hm) if hm is not None else None
                ca = d.get('CariAdi')
                if ca == '-' or not ca:
                    ca = None
                emir_no_int = int(d['EmirNo'])
                parent_cari_map[emir_no_int] = ca
                # Ilk olarak Siparis_Har'i koy, asagida giren_map ile override edilecek
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': hm_f,                     # Siparis_Har bilgisi (fallback)
                    'SiparisMiktari': hm_f,                  # ham siparis miktari (fallback'i ayri tut)
                    'EmirMiktari': hm_f,                     # asagida update
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                    'CariAdi': ca,
                    'RKOD': None,
                })
            # === FAZ 4.6 B3 LAZY: batch kaldirildi ===
            # Urt_Em_gch toplam SUM/MAX sorgusu yavas. Ayri endpoint /hedef/siparis/emir-detay
            # cagrilarak frontend'den lazy load yapilir.
            # Burada sadece Siparis_Har bilgisi var, hizli.
            emir_giren_map = {}
            emir_rkod_map = {}

            # Yari mamul (alt) emirler - miktar/RKOD lazy load icin null
            for d in yari_dicts:
                emir_no_int = int(d['EmirNo'])
                parent_no = int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None
                ca_alt = parent_cari_map.get(parent_no) if parent_no else None
                emirler.append({
                    'EmirNo': emir_no_int,
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': None,
                    'EmirMiktari': None,         # lazy: /hedef/siparis/emir-detay
                    'SipNo': sip_no_int,
                    'ParentEmirNo': parent_no,
                    'CariAdi': ca_alt,
                    'RKOD': None,                # lazy
                })

            # === FAZ 4.6 toplam siparis fix ===
            # Distinct siparis Miktar toplami (asil siparis adedi)
            siparis_kalemleri = []
            siparis_toplam = 0.0
            try:
                cur.execute("""
                    SELECT sh.SipNo, sh.SKOD, sh.Miktar
                      FROM Siparis_Har sh
                     WHERE sh.SipNo = %s
                       AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                """, (sip_no_int,))
                for r in cur.fetchall():
                    miktar = float(r[2] or 0)
                    siparis_toplam += miktar
                    siparis_kalemleri.append({
                        'SipNo': int(r[0]) if r[0] is not None else None,
                        'SKOD': r[1],
                        'Miktar': miktar
                    })
            except Exception:
                pass

            cur.close()
            return {
                'ok': True,
                'siparis_no': str(sip_no_int),
                'emir_sayisi': len(emirler),
                'ana_sayisi': len(ana_dicts),
                'alt_sayisi': len(yari_dicts),
                'siparis_toplam': siparis_toplam,
                'siparis_kalemleri': siparis_kalemleri,
                'emirler': emirler,
            }
        finally:
            con.close()
    except Exception as e:
        return {'ok': False, 'hata': 'sistem_hatasi',
                'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
                'emirler': []}

# === FAZ 4.7 ALT EMIR HELPER (sablon routing icin) ===
def get_alt_emirler(ana_emir_no):
    """Bir ana emirin alt (Tip='Y') yari mamul emirlerini dondurur."""
    try:
        ana_int = int(ana_emir_no)
        if ana_int <= 0:
            return {'ok': False, 'hata': 'gecersiz_emir', 'alt_emirler': []}
    except Exception:
        return {'ok': False, 'hata': 'gecersiz_emir', 'alt_emirler': []}

    try:
        con = _baglan()
        try:
            cur = con.cursor()
            cur.execute("""
                SELECT
                    e.EmirNo,
                    e.ModelKod,
                    ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                    UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                    LTRIM(RTRIM(ISNULL(e.Location,''))) AS Location
                FROM Urt_Em2Em em2em
                INNER JOIN Urt_Emir e ON e.EmirNo = em2em.EmirNo_YM
                LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                WHERE em2em.EmirNo = %s
                  AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'Y'
                ORDER BY e.EmirNo
            """, (ana_int,))
            rows = cur.fetchall()
            alt = []
            for r in rows:
                alt.append({
                    'emir_no': int(r[0]),
                    'model_kod': r[1] or '',
                    'model_adi': r[2] or '',
                    'tip': r[3] or 'Y',
                    'location': r[4] or '',
                })
            return {'ok': True, 'alt_emirler': alt}
        finally:
            con.close()
    except Exception as e:
        return {'ok': False, 'hata': 'sistem',
                'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
                'alt_emirler': []}
