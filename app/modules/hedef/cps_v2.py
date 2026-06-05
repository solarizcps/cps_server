"""CPS PLAN v2 - CPS operasyon/personel veri katmani.

KURAL: Bu modul SADECE CPS verisini saglar.
Korgun ile birlestirme YASAK.
"""
import sqlite3
import os

CPS_DB = r'C:\cps_dev\mock_data.db'


def _baglan():
    if not os.path.exists(CPS_DB):
        return None
    con = sqlite3.connect(CPS_DB)
    con.row_factory = sqlite3.Row
    return con


def get_cps_siparis(sip_no, emir_listesi=None):
    """Bir siparis (ve onun emirleri) icin CPS operasyon verisi.

    sip_no: int (referans)
    emir_listesi: list of int — bu sipariste bulunan emirler (Korgun'dan)

    Donus:
    {
        'sablon_prosesleri': [{proses_adi, yapilan, hedef_adet, kaynak}],
        'personel_uretim': [{personel_id, personel_ad, toplam_miktar}],
        'prim_performans': null
    }
    """
    if emir_listesi is None:
        emir_listesi = []

    con = _baglan()
    if con is None:
        return {
            'sablon_prosesleri': [],
            'personel_uretim': [],
            'prim_performans': None,
        }

    try:
        sablon_prosesleri = []
        personel_uretim = []

        if emir_listesi:
            emirler_str = [str(e) for e in emir_listesi]
            ph = ','.join(['?'] * len(emirler_str))

            # Sablon prosesleri (emir_alt_proses + uretim_kayit JOIN)
            try:
                rows = con.execute(f"""
                    SELECT
                        ap.proses_adi AS proses_adi,
                        SUM(COALESCE(ap.hedef_adet, 0)) AS hedef_adet,
                        COALESCE(SUM(uk_yp.miktar), 0) AS yapilan
                    FROM emir_alt_proses ap
                    LEFT JOIN (
                        SELECT
                            CAST(emir_no AS TEXT) AS en,
                            LOWER(TRIM(proses_adi)) AS pa,
                            SUM(miktar) AS miktar
                        FROM uretim_kayit
                        WHERE onay_durum IN ('onaylandi', 'bekliyor')
                        GROUP BY CAST(emir_no AS TEXT), LOWER(TRIM(proses_adi))
                    ) uk_yp
                      ON uk_yp.en = ap.emir_no
                     AND uk_yp.pa = LOWER(TRIM(ap.proses_adi))
                    WHERE ap.emir_no IN ({ph})
                      AND ap.aktif = 1
                    GROUP BY LOWER(TRIM(ap.proses_adi)), ap.proses_adi
                    ORDER BY ap.proses_adi
                """, tuple(emirler_str)).fetchall()
                for r in rows:
                    sablon_prosesleri.append({
                        'proses_adi': r['proses_adi'] or '',
                        'yapilan': int(r['yapilan'] or 0),
                        'hedef_adet': int(r['hedef_adet'] or 0),
                        'kaynak': 'sablon',
                    })
            except Exception as e:
                try:
                    print(f'[cps_v2 sablon hata]: {e}')
                except Exception:
                    pass

            # Personel uretim (uretim_kayit'tan personel bazli toplam)
            try:
                rows2 = con.execute(f"""
                    SELECT
                        personel_id,
                        MAX(personel_ad) AS personel_ad,
                        SUM(miktar) AS toplam_miktar,
                        COUNT(*) AS kayit_sayisi
                    FROM uretim_kayit
                    WHERE CAST(emir_no AS TEXT) IN ({ph})
                      AND onay_durum IN ('onaylandi', 'bekliyor')
                      AND personel_id IS NOT NULL
                    GROUP BY personel_id
                    ORDER BY toplam_miktar DESC
                """, tuple(emirler_str)).fetchall()
                for r in rows2:
                    personel_uretim.append({
                        'personel_id': r['personel_id'],
                        'personel_ad': r['personel_ad'] or '?',
                        'toplam_miktar': int(r['toplam_miktar'] or 0),
                        'kayit_sayisi': int(r['kayit_sayisi'] or 0),
                    })
            except Exception as e:
                try:
                    print(f'[cps_v2 personel hata]: {e}')
                except Exception:
                    pass

        return {
            'sablon_prosesleri': sablon_prosesleri,
            'personel_uretim': personel_uretim,
            'prim_performans': None,
        }
    finally:
        con.close()