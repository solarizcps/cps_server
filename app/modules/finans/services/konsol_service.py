# -*- coding: utf-8 -*-
"""
Finans Konsol Service - FAZ 4C-A
SELECT-ONLY, DB write YOK
KPI hesaplari + Kart Borc Raporu

Veri kaynaklari (READ-ONLY):
  - finans_kredi_karti (aktif kart sayisi)
  - finans_kredi_karti_ekstre (borc/kalan/son_odeme)
  - finans_kredi_karti_hareket (hareket istatistigi)
  - finans_manuel_odeme (yaklasan manuel odeme)
"""
import sqlite3
import os
from datetime import datetime, date, timedelta


# Kritik esikler (gun cinsinden)
KRITIK_GUN = 3      # 3 gun icinde son odeme = kritik
YAKLASAN_GUN = 7    # 7 gun icinde = yaklasan
GECIKMIS_GUN = 0    # bugun gecmis


def _db_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))), "mock_data.db")


def _conn(db_path=None):
    c = sqlite3.connect(db_path or _db_path())
    c.row_factory = sqlite3.Row
    return c


def _gun_farki(tarih_str):
    """tarih_str -> bugune kadar gun farki. Negatif = gecmis, pozitif = gelecek"""
    if not tarih_str:
        return None
    try:
        t = datetime.strptime(tarih_str, "%Y-%m-%d").date()
        return (t - date.today()).days
    except (ValueError, TypeError):
        return None


# ===== KONSOL KPI =====
def konsol_kpi_hesapla(db_path=None):
    """
    Finans konsolu KPI'larini hesaplar.
    SELECT-ONLY.
    """
    c = _conn(db_path)

    kpi = {
        # Kart durumu
        "aktif_kart_sayisi": 0,
        "toplam_kart_sayisi": 0,
        "toplam_limit": 0.0,

        # Ekstre durumu
        "acik_ekstre_sayisi": 0,        # ODENMEDI + KISMEN_ODENDI
        "toplam_ekstre_borc": 0.0,      # Acik ekstre borclari
        "toplam_odenen": 0.0,           # Tum ekstreler odenen
        "toplam_kalan": 0.0,            # Borc - Odenen

        # Risk
        "gecikmis_ekstre_sayisi": 0,    # son_odeme_tarihi < bugun
        "gecikmis_borc": 0.0,           # gecikmis ekstrelerin kalan toplami
        "kritik_yaklasan_sayisi": 0,    # 0-3 gun icinde
        "yaklasan_odeme_sayisi": 0,     # 0-7 gun icinde

        # Manuel odeme
        "yaklasan_manuel_odeme": 0,     # 7 gun icinde manuel
        "yaklasan_manuel_tutar": 0.0,
    }

    # Kart sayisi
    r = c.execute("SELECT COUNT(*) as toplam, SUM(CASE WHEN Aktif=1 THEN 1 ELSE 0 END) as aktif, SUM(CASE WHEN Aktif=1 THEN Limit_ ELSE 0 END) as limit_ FROM finans_kredi_karti").fetchone()
    kpi["toplam_kart_sayisi"] = r["toplam"] or 0
    kpi["aktif_kart_sayisi"] = r["aktif"] or 0
    kpi["toplam_limit"] = float(r["limit_"] or 0)

    # Ekstre KPI
    ekstreler = c.execute("""
        SELECT Id, KartId, SonOdemeTarihi, ToplamBorc, OdenenTutar, Durum
          FROM finans_kredi_karti_ekstre
         WHERE Durum != 'IPTAL'
    """).fetchall()

    for e in ekstreler:
        toplam = float(e["ToplamBorc"] or 0)
        odenen = float(e["OdenenTutar"] or 0)
        kalan = toplam - odenen

        kpi["toplam_odenen"] += odenen

        if e["Durum"] in ("ODENMEDI", "KISMEN_ODENDI"):
            kpi["acik_ekstre_sayisi"] += 1
            kpi["toplam_ekstre_borc"] += toplam
            kpi["toplam_kalan"] += kalan

            gun = _gun_farki(e["SonOdemeTarihi"])
            if gun is not None:
                if gun < 0:
                    kpi["gecikmis_ekstre_sayisi"] += 1
                    kpi["gecikmis_borc"] += kalan
                elif gun <= KRITIK_GUN:
                    kpi["kritik_yaklasan_sayisi"] += 1
                if 0 <= gun <= YAKLASAN_GUN:
                    kpi["yaklasan_odeme_sayisi"] += 1

    # Manuel odeme - yaklasan (sema kontrolu)
    try:
        manuel_yaklasan = c.execute("""
            SELECT COUNT(*) as say, SUM(Tutar) as tutar
              FROM finans_manuel_odeme
             WHERE Durum NOT IN ('IPTAL', 'ODENDI')
               AND OdemeTarihi IS NOT NULL
               AND date(OdemeTarihi) BETWEEN date('now','localtime') AND date('now','localtime','+7 days')
        """).fetchone()
        kpi["yaklasan_manuel_odeme"] = manuel_yaklasan["say"] or 0
        kpi["yaklasan_manuel_tutar"] = float(manuel_yaklasan["tutar"] or 0)
    except sqlite3.OperationalError:
        # Manuel odeme sema farkli olabilir, sessiz gec
        pass

    # Yuvarlama
    for k in list(kpi.keys()):
        if isinstance(kpi[k], float):
            kpi[k] = round(kpi[k], 2)

    c.close()
    return kpi


# ===== YAKLASAN EKSTRELERI LISTE (uyari widget icin) =====
def yaklasan_ekstreler(gun_limit=14, db_path=None):
    """
    Bugunden gun_limit gune kadar son odemesi olan acik ekstreler.
    Gecikmis olanlar da dahil (negatif gun).
    Risk siralamasinda doner.
    """
    c = _conn(db_path)
    rows = c.execute("""
        SELECT e.Id, e.KartId, e.SonOdemeTarihi, e.ToplamBorc, e.OdenenTutar, e.Durum,
               k.entity, k.KartAd, k.Banka, k.Son4, k.ParaBirimi
          FROM finans_kredi_karti_ekstre e
          LEFT JOIN finans_kredi_karti k ON k.Id = e.KartId
         WHERE e.Durum IN ('ODENMEDI', 'KISMEN_ODENDI')
         ORDER BY e.SonOdemeTarihi ASC
    """).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        gun = _gun_farki(d["SonOdemeTarihi"])
        if gun is None:
            continue
        if gun > gun_limit:
            continue
        d["_gun_farki"] = gun
        d["_kalan"] = round(float(d["ToplamBorc"] or 0) - float(d["OdenenTutar"] or 0), 2)
        if gun < 0:
            d["_risk"] = "GECIKMIS"
            d["_risk_class"] = "gecikmis"
        elif gun <= KRITIK_GUN:
            d["_risk"] = "KRITIK"
            d["_risk_class"] = "kritik"
        elif gun <= YAKLASAN_GUN:
            d["_risk"] = "YAKLASAN"
            d["_risk_class"] = "yaklasan"
        else:
            d["_risk"] = "NORMAL"
            d["_risk_class"] = "normal"
        items.append(d)

    c.close()
    return items


# ===== KART BAZLI BORC RAPORU =====
def kart_borc_raporu(filtre=None, db_path=None):
    """
    Her aktif kart icin: toplam borc, odenen, kalan, ekstre sayisi, yaklasan
    """
    f = filtre or {}
    c = _conn(db_path)

    where_k = ["k.Aktif = 1"]
    params = []
    if f.get("entity"):
        where_k.append("k.entity = ?")
        params.append(f["entity"].lower())

    kartlar = c.execute(f"""
        SELECT k.*
          FROM finans_kredi_karti k
         WHERE {' AND '.join(where_k)}
         ORDER BY k.entity, k.Banka, k.KartAd
    """, params).fetchall()

    items = []
    toplam_kpi = {
        "toplam_kart": 0,
        "toplam_limit": 0.0,
        "toplam_borc": 0.0,
        "toplam_odenen": 0.0,
        "toplam_kalan": 0.0,
        "gecikmis_ekstre": 0,
        "yaklasan_odeme": 0,
    }

    for k in kartlar:
        kart = dict(k)
        # Bu karta ait ekstreler
        ekstreler = c.execute("""
            SELECT Id, SonOdemeTarihi, ToplamBorc, OdenenTutar, Durum
              FROM finans_kredi_karti_ekstre
             WHERE KartId = ? AND Durum != 'IPTAL'
        """, (k["Id"],)).fetchall()

        kart_borc = 0.0
        kart_odenen = 0.0
        acik_say = 0
        gecikmis = 0
        yaklasan = 0
        en_yakin_gun = None
        en_yakin_tarih = None

        for e in ekstreler:
            tb = float(e["ToplamBorc"] or 0)
            od = float(e["OdenenTutar"] or 0)
            kart_borc += tb
            kart_odenen += od
            if e["Durum"] in ("ODENMEDI", "KISMEN_ODENDI"):
                acik_say += 1
                gun = _gun_farki(e["SonOdemeTarihi"])
                if gun is not None:
                    if gun < 0:
                        gecikmis += 1
                    elif gun <= YAKLASAN_GUN:
                        yaklasan += 1
                    if en_yakin_gun is None or gun < en_yakin_gun:
                        en_yakin_gun = gun
                        en_yakin_tarih = e["SonOdemeTarihi"]

        # Hareket sayisi
        h_count = c.execute("""
            SELECT COUNT(*) FROM finans_kredi_karti_hareket
             WHERE KartId = ?
               AND (KaynakModul IS NULL OR KaynakModul NOT LIKE '%_IPTAL')
        """, (k["Id"],)).fetchone()[0]

        kart["_toplam_borc"] = round(kart_borc, 2)
        kart["_toplam_odenen"] = round(kart_odenen, 2)
        kart["_kalan"] = round(kart_borc - kart_odenen, 2)
        kart["_acik_ekstre"] = acik_say
        kart["_gecikmis_ekstre"] = gecikmis
        kart["_yaklasan_ekstre"] = yaklasan
        kart["_en_yakin_gun"] = en_yakin_gun
        kart["_en_yakin_tarih"] = en_yakin_tarih
        kart["_hareket_sayisi"] = h_count
        kart["_kullanim_yuzde"] = round(100 * (kart_borc - kart_odenen) / float(k["Limit_"] or 1), 1) if (k["Limit_"] or 0) > 0 else 0

        items.append(kart)

        toplam_kpi["toplam_kart"] += 1
        toplam_kpi["toplam_limit"] += float(k["Limit_"] or 0)
        toplam_kpi["toplam_borc"] += kart_borc
        toplam_kpi["toplam_odenen"] += kart_odenen
        toplam_kpi["toplam_kalan"] += (kart_borc - kart_odenen)
        toplam_kpi["gecikmis_ekstre"] += gecikmis
        toplam_kpi["yaklasan_odeme"] += yaklasan

    for k in list(toplam_kpi.keys()):
        if isinstance(toplam_kpi[k], float):
            toplam_kpi[k] = round(toplam_kpi[k], 2)

    c.close()
    return {
        "items": items,
        "kpi": toplam_kpi,
        "entity_set": ["solariz", "nexgen", "pera", "sahsi"],
    }


# ===== TAKVIM EKSTRE DOGRULAMA (read-only utility) =====
def takvim_ekstre_kontrol(db_path=None):
    """
    Takvimde gosterilen ekstrelerin gercekten cekilebildigini dogrular.
    Sadece istatistik, bir sey yapmaz.
    """
    c = _conn(db_path)
    r = c.execute("""
        SELECT COUNT(*) as toplam,
               SUM(CASE WHEN Durum != 'IPTAL' THEN 1 ELSE 0 END) as aktif,
               SUM(CASE WHEN date(SonOdemeTarihi) >= date('now','localtime') AND Durum != 'IPTAL' THEN 1 ELSE 0 END) as gelecek
          FROM finans_kredi_karti_ekstre
    """).fetchone()
    c.close()
    return {
        "toplam_ekstre": r["toplam"] or 0,
        "aktif_ekstre": r["aktif"] or 0,
        "gelecek_ekstre": r["gelecek"] or 0,
    }


# [AB1A_AYLIK_BASKI BAS] Aylik baski KPI - finans_odeme_plan uzerinden
def aylik_baski(yil=None, ay_sayisi=12, db_path=None):  # [AB1C_PATTERN_FIX]
    """Mevcut finans_odeme_plan tablosundan aylik baski hesabi. SELECT-only."""
    try:
        from datetime import datetime, timedelta
        conn = _conn(db_path)

        params = []
        yil_filter = ""
        if yil:
            yil_filter = "AND strftime('%Y', PlanTarih) = ?"
            params.append(str(yil))

        sql = f"""
            SELECT
                strftime('%Y-%m', PlanTarih) AS ay,
                SUM(CASE WHEN OdemeTipi='HAVALE' THEN Tutar ELSE 0 END) AS havale,
                SUM(CASE WHEN OdemeTipi='CEK'    THEN Tutar ELSE 0 END) AS cek,
                SUM(Tutar) AS toplam,
                SUM(CASE WHEN Durum='GELDI'    THEN Tutar ELSE 0 END) AS gerceklesen,
                SUM(CASE WHEN Durum='BEKLIYOR' THEN Tutar ELSE 0 END) AS bekliyor,
                COUNT(*) AS kayit_sayi
            FROM finans_odeme_plan
            WHERE PlanTarih IS NOT NULL AND PlanTarih != ''
              AND (KaynakModul IS NULL OR KaynakModul != 'MOCK')
              {yil_filter}
            GROUP BY ay
            ORDER BY ay
            LIMIT ?
        """
        params.append(int(ay_sayisi))
        rows = conn.execute(sql, params).fetchall()

        aylar = []
        toplam_baski = 0.0
        toplam_havale = 0.0
        toplam_cek = 0.0
        en_yogun_ay = None
        en_yogun_tutar = 0.0

        for r in rows:
            d = dict(r) if hasattr(r, 'keys') else {
                'ay': r[0], 'havale': r[1], 'cek': r[2], 'toplam': r[3],
                'gerceklesen': r[4], 'bekliyor': r[5], 'kayit_sayi': r[6]
            }
            tot = float(d.get('toplam') or 0)
            aylar.append({
                'ay': d['ay'],
                'havale': float(d.get('havale') or 0),
                'cek': float(d.get('cek') or 0),
                'toplam': tot,
                'gerceklesen': float(d.get('gerceklesen') or 0),
                'bekliyor': float(d.get('bekliyor') or 0),
                'kayit_sayi': int(d.get('kayit_sayi') or 0),
            })
            toplam_baski += tot
            toplam_havale += float(d.get('havale') or 0)
            toplam_cek += float(d.get('cek') or 0)
            if tot > en_yogun_tutar:
                en_yogun_tutar = tot
                en_yogun_ay = d['ay']

        bugun = datetime.now()
        bu_ay_str = bugun.strftime('%Y-%m')
        bu_ay_baski = 0.0
        for a in aylar:
            if a['ay'] == bu_ay_str:
                bu_ay_baski = a['toplam']
                break

        try:
            son_tarih = (bugun + timedelta(days=30)).strftime('%Y-%m-%d')
            bugun_str = bugun.strftime('%Y-%m-%d')
            r30 = conn.execute("""
                SELECT COALESCE(SUM(Tutar), 0) AS toplam
                FROM finans_odeme_plan
                WHERE PlanTarih >= ? AND PlanTarih <= ?
                  AND (Durum IS NULL OR Durum != 'GELDI')
                  AND (KaynakModul IS NULL OR KaynakModul != 'MOCK')
            """, (bugun_str, son_tarih)).fetchone()
            gelecek_30 = float((dict(r30) if hasattr(r30, 'keys') else {'toplam': r30[0]}).get('toplam') or 0)
        except Exception:
            gelecek_30 = 0.0

        return {
            'ok': True,
            'aylar': aylar,
            'toplam_baski': toplam_baski,
            'toplam_havale': toplam_havale,
            'toplam_cek': toplam_cek,
            'en_yogun_ay': en_yogun_ay,
            'en_yogun_tutar': en_yogun_tutar,
            'bu_ay_baski': bu_ay_baski,
            'gelecek_30_gun': gelecek_30,
        }
    except Exception as e:
        return {
            'ok': False, 'hata': str(e),
            'aylar': [], 'toplam_baski': 0.0,
            'toplam_havale': 0.0, 'toplam_cek': 0.0,
            'en_yogun_ay': None, 'en_yogun_tutar': 0.0,
            'bu_ay_baski': 0.0, 'gelecek_30_gun': 0.0,
        }
# [AB1A_AYLIK_BASKI SON]

# AB3_PRE2_MOCK_FILTER applied


# [AB4_KREDI_LISTE BAS]
def kredi_anlasma_liste(db_path=None):
    """Excel'den migrate edilen kredi anlasmalarini listeler.
    Sadece KaynakModul LIKE 'EXCEL%' olanlar.
    Returns: list of dict
    """
    import re as _re
    conn = _conn(db_path)
    try:
        rows = conn.execute("""
            SELECT a.Id as anlasma_id, a.ProjeAdi as kredi_adi, a.CKod,
                   a.ToplamTutar as toplam, a.BaslangicTarih, a.Durum,
                   a.Notlar, a.KaynakModul,
                   COUNT(p.Id) as taksit_sayi,
                   SUM(CASE WHEN p.Durum='GELDI' THEN 1 ELSE 0 END) as taksit_geldi,
                   MIN(p.PlanTarih) as ilk_vade,
                   MAX(p.PlanTarih) as son_vade,
                   COALESCE(SUM(p.Tutar), 0) as plan_toplam,
                   COALESCE(SUM(p.GerceklesenTutar), 0) as gerc_toplam
            FROM finans_anlasma a
            LEFT JOIN finans_odeme_plan p ON p.AnlasmaId = a.Id
            WHERE a.KaynakModul LIKE 'EXCEL%'
            GROUP BY a.Id
            ORDER BY a.BaslangicTarih DESC, a.Id DESC
        """).fetchall()
    finally:
        pass
    
    result = []
    for r in rows:
        # Banka bilgisini Notlar'dan parse
        banka = ""
        notlar = r["Notlar"] or ""
        m = _re.search(r"Banka:\s*([^|]+)", notlar)
        if m:
            banka = m.group(1).strip()
        
        # Firma: CKod'dan turet
        ckod = r["CKod"] or ""
        firma = ckod.replace("M_EXCEL_", "").replace("_", " ").title() if ckod.startswith("M_EXCEL_") else ckod
        
        plan_toplam = float(r["plan_toplam"] or 0)
        gerc_toplam = float(r["gerc_toplam"] or 0)
        kalan = plan_toplam - gerc_toplam
        
        result.append({
            "anlasma_id": r["anlasma_id"],
            "firma": firma,
            "kredi_adi": r["kredi_adi"],
            "banka": banka,
            "toplam": float(r["toplam"] or 0),
            "odenen": gerc_toplam,
            "kalan": kalan,
            "taksit_sayi": r["taksit_sayi"] or 0,
            "taksit_geldi": r["taksit_geldi"] or 0,
            "ilk_vade": r["ilk_vade"],
            "son_vade": r["son_vade"],
            "durum": r["Durum"] or "AKTIF",
            "baslangic": r["BaslangicTarih"],
            "kaynak": r["KaynakModul"],
        })
    conn.close()
    return result
# [AB4_KREDI_LISTE SON]


# [AB4_KREDI_TAKSIT_DETAY BAS]
def kredi_taksit_detay(anlasma_id, db_path=None):
    """Bir kredi anlasmasinin taksit detaylarini doner."""
    conn = _conn(db_path)
    rows = conn.execute("""
        SELECT Id, Sira, PlanTarih, Tutar, Durum,
               GerceklesenTarih, GerceklesenTutar, Aciklama,
               OdemeTipi
        FROM finans_odeme_plan
        WHERE AnlasmaId = ? AND KaynakModul LIKE 'EXCEL%'
        ORDER BY Sira
    """, (int(anlasma_id),)).fetchall()
    
    result = []
    for r in rows:
        result.append({
            "id": r["Id"],
            "sira": r["Sira"],
            "plan_tarih": r["PlanTarih"],
            "tutar": float(r["Tutar"] or 0),
            "durum": r["Durum"] or "BEKLIYOR",
            "gerc_tarih": r["GerceklesenTarih"],
            "gerc_tutar": float(r["GerceklesenTutar"] or 0),
            "aciklama": r["Aciklama"] or "",
            "odeme_tipi": r["OdemeTipi"] or "HAVALE",
        })
    conn.close()
    return result
# [AB4_KREDI_TAKSIT_DETAY SON]
