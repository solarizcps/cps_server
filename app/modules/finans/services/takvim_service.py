# -*- coding: utf-8 -*-
"""
Takvim Service V2 - FAZ 3D V2 (Altan mockup)
Calendar grid + sag panel "En Yakin Odemeler"
Toggle filtre destegi (5 kaynak: CEK/CARI/KART/KREDI/MANUEL)
Ay navigasyon (prev/next/bugun)
"""
import sqlite3
import os
import calendar
from datetime import datetime, timedelta, date


def _db_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))), "mock_data.db")


def _entity_yetki_filtre(g_user):
    kullanici_adi = (g_user.get("KullaniciAdi") or "").lower() if g_user else ""
    if kullanici_adi == "admin":
        return ["solariz", "nexgen", "pera", "sahsi"]
    return ["solariz", "nexgen", "pera"]


def _durum_class(durum, tarih_str):
    d = (durum or "").upper()
    if d == "ODENDI": return "odendi"
    if d == "PLANLANDI": return "planlandi"
    try:
        t = datetime.strptime(tarih_str, "%Y-%m-%d").date()
    except Exception:
        return "bekliyor"
    bugun = date.today()
    if t < bugun: return "gecikti"
    if t == bugun: return "bugun"
    if (t - bugun).days <= 7: return "yaklasan"
    return "bekliyor"


def _gun_class(tarih_str, durum):
    if (durum or "").upper() == "ODENDI":
        return "odendi"
    try:
        t = datetime.strptime(tarih_str, "%Y-%m-%d").date()
    except Exception:
        return "normal"
    bugun = date.today()
    if t < bugun: return "gecikti"
    if t == bugun: return "bugun"
    if (t - bugun).days <= 7: return "yaklasan"
    return "normal"


def _gun_tag(tarih_str):
    try:
        t = datetime.strptime(tarih_str, "%Y-%m-%d").date()
    except Exception:
        return (None, None)
    bugun = date.today()
    if t < bugun:
        return ("GECIKTI", "gecikti")
    if t == bugun:
        return ("BUGUN", "bugun")
    if (t - bugun).days <= 7:
        return ("YAKLASAN", "yaklasan")
    return (None, None)


def _gun_adi(tarih_str):
    try:
        t = datetime.strptime(tarih_str, "%Y-%m-%d").date()
    except Exception:
        return ""
    isim = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
    return isim[t.weekday()]


AY_ADLARI = ["Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
             "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik"]
AY_KISA = ["Oca", "Sub", "Mar", "Nis", "May", "Haz",
           "Tem", "Agu", "Eyl", "Eki", "Kas", "Ara"]


def _demo_kayitlar():
    bugun = date.today()
    items = []
    items.append({"tarih": (bugun - timedelta(days=3)).strftime("%Y-%m-%d"), "kaynak": "CARI", "entity": "solariz", "baslik": "Kaplan Tekstil", "alt_baslik": "Fatura T-0145", "tutar": 87500.00, "para_birimi": "TRY", "durum": "GECIKTI"})
    items.append({"tarih": bugun.strftime("%Y-%m-%d"), "kaynak": "CARI", "entity": "solariz", "baslik": "LC Waikiki", "alt_baslik": "Fatura LC-58923", "tutar": 154300.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=5)).strftime("%Y-%m-%d"), "kaynak": "CARI", "entity": "nexgen", "baslik": "Esem Ayakkabi", "alt_baslik": "ES-12005", "tutar": 42800.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=3)).strftime("%Y-%m-%d"), "kaynak": "KART", "entity": "nexgen", "baslik": "Akbank Kart 2197", "alt_baslik": "NexGen Wings", "tutar": 96500.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=12)).strftime("%Y-%m-%d"), "kaynak": "KART", "entity": "solariz", "baslik": "Is Bankasi 8834", "alt_baslik": "Solariz Max Ekstre", "tutar": 45000.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun - timedelta(days=2)).strftime("%Y-%m-%d"), "kaynak": "KART", "entity": "solariz", "baslik": "Denizbank 7715", "alt_baslik": "Solariz Bonus Plus", "tutar": 134500.00, "para_birimi": "TRY", "durum": "GECIKTI"})
    items.append({"tarih": (bugun + timedelta(days=1)).strftime("%Y-%m-%d"), "kaynak": "MANUEL", "entity": "solariz", "baslik": "Personel maas", "alt_baslik": "Mayis 2026", "tutar": 580000.00, "para_birimi": "TRY", "durum": "PLANLANDI"})
    items.append({"tarih": (bugun + timedelta(days=15)).strftime("%Y-%m-%d"), "kaynak": "MANUEL", "entity": "solariz", "baslik": "Kira odemesi", "alt_baslik": "Atolye Gedikpasa", "tutar": 35000.00, "para_birimi": "TRY", "durum": "PLANLANDI"})
    items.append({"tarih": (bugun + timedelta(days=8)).strftime("%Y-%m-%d"), "kaynak": "MANUEL", "entity": "pera", "baslik": "Vergi odemesi", "alt_baslik": "KDV Mayis", "tutar": 28500.00, "para_birimi": "TRY", "durum": "PLANLANDI"})
    items.append({"tarih": (bugun - timedelta(days=10)).strftime("%Y-%m-%d"), "kaynak": "MANUEL", "entity": "sahsi", "baslik": "Saglik fatura", "alt_baslik": "", "tutar": 4500.00, "para_birimi": "TRY", "durum": "ODENDI"})
    items.append({"tarih": (bugun + timedelta(days=2)).strftime("%Y-%m-%d"), "kaynak": "MANUEL", "entity": "sahsi", "baslik": "Cep telefonu", "alt_baslik": "Turkcell", "tutar": 850.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=7)).strftime("%Y-%m-%d"), "kaynak": "CEK", "entity": "solariz", "baslik": "Cek No 12453", "alt_baslik": "Garanti BBVA", "tutar": 175000.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=20)).strftime("%Y-%m-%d"), "kaynak": "CEK", "entity": "solariz", "baslik": "Cek No 12458", "alt_baslik": "Is Bankasi", "tutar": 95000.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=10)).strftime("%Y-%m-%d"), "kaynak": "KREDI", "entity": "solariz", "baslik": "KOBI Kredi Taksit 5/24", "alt_baslik": "Garanti BBVA", "tutar": 62500.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    items.append({"tarih": (bugun + timedelta(days=18)).strftime("%Y-%m-%d"), "kaynak": "KREDI", "entity": "nexgen", "baslik": "Arac Kredi Taksit 8/36", "alt_baslik": "Akbank", "tutar": 18500.00, "para_birimi": "TRY", "durum": "BEKLIYOR"})
    return items


def _db_kayitlar(c, izinli):
    items = []
    placeholders = ",".join(["?"] * len(izinli))
    try:
        rows = c.execute("SELECT VadeTarih AS tarih, entity, 'CARI' AS kaynak, COALESCE(ck.CName, ch.CKod) AS baslik, ch.BelgeNo AS alt_baslik, (COALESCE(ch.Borc,0) - COALESCE(ch.Alacak,0)) AS tutar, 'TRY' AS para_birimi, COALESCE(cod.Durum, 'BEKLIYOR') AS durum FROM finans_cari_odeme_durum cod LEFT JOIN Cari_Har ch ON ch.Id = cod.CariHarId LEFT JOIN Cari_Kart ck ON ck.CKod = ch.CKod WHERE cod.entity IN (" + placeholders + ")", izinli).fetchall()
        for r in rows:
            items.append(dict(r))
    except Exception:
        pass
    try:
        rows = c.execute("SELECT e.SonOdemeTarihi AS tarih, k.entity, 'KART' AS kaynak, k.KartAd AS baslik, k.Banka AS alt_baslik, e.ToplamBorc AS tutar, 'TRY' AS para_birimi, e.Durum AS durum FROM finans_kredi_karti_ekstre e LEFT JOIN finans_kredi_karti k ON k.Id = e.KartId WHERE k.entity IN (" + placeholders + ")", izinli).fetchall()
        for r in rows:
            items.append(dict(r))
    except Exception:
        pass
    try:
        rows = c.execute("SELECT VadeTarih AS tarih, entity, 'MANUEL' AS kaynak, Aciklama AS baslik, Tip AS alt_baslik, Tutar AS tutar, ParaBirimi AS para_birimi, Durum AS durum FROM finans_manuel_odeme WHERE entity IN (" + placeholders + ")", izinli).fetchall()
        for r in rows:
            items.append(dict(r))
    except Exception:
        pass
    return items


def _calendar_hucreler(yil, ay, items):
    """Aylik takvim grid - 6 hafta x 7 gun (42 hucre)"""
    bugun = date.today()
    cal = calendar.Calendar(firstweekday=0)
    monthdays = cal.itermonthdates(yil, ay)
    hucreler = []
    for d in monthdays:
        items_for_day = [it for it in items if it.get("tarih") == d.strftime("%Y-%m-%d")]
        hucreler.append({
            "tarih": d.strftime("%Y-%m-%d"),
            "gun_num": d.day,
            "diger_ay": (d.month != ay),
            "bugun": (d == bugun),
            "hafta_sonu": (d.weekday() >= 5),
            "kayitlar": items_for_day,
        })
    return hucreler


def takvim_listele(g_user=None, ay_param=None):
    """
    ay_param: 'YYYY-MM' formatinda. None ise bu ay.
    """
    izinli = _entity_yetki_filtre(g_user)

    bugun = date.today()
    if ay_param:
        try:
            yil, ay = map(int, ay_param.split("-"))
        except Exception:
            yil, ay = bugun.year, bugun.month
    else:
        yil, ay = bugun.year, bugun.month

    # Onceki/sonraki ay navigasyon
    if ay == 1:
        prev_yil, prev_ay_num = yil - 1, 12
    else:
        prev_yil, prev_ay_num = yil, ay - 1
    if ay == 12:
        next_yil, next_ay_num = yil + 1, 1
    else:
        next_yil, next_ay_num = yil, ay + 1
    prev_ay = "{:04d}-{:02d}".format(prev_yil, prev_ay_num)
    next_ay = "{:04d}-{:02d}".format(next_yil, next_ay_num)
    ay_baslik = AY_ADLARI[ay - 1] + " " + str(yil)

    # Veri yukle
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    db_items = _db_kayitlar(c, izinli)
    c.close()

    if db_items:
        items_raw = db_items
        veri_kaynak = "DB"
    else:
        items_raw = [k for k in _demo_kayitlar() if k["entity"] in izinli]
        veri_kaynak = "DEMO"

    # Metadata ekle
    items = []
    for it in items_raw:
        it["durum_class"] = _durum_class(it.get("durum"), it.get("tarih") or "")
        items.append(it)

    # Calendar hucreler
    cal_hucreler = _calendar_hucreler(yil, ay, items)

    # ===== Liste view: Gunlere grupla (eski takvim formati korunuyor) =====
    gun_dict = {}
    for it in items:
        t = it.get("tarih")
        if not t:
            continue
        if t not in gun_dict:
            try:
                td = datetime.strptime(t, "%Y-%m-%d").date()
            except Exception:
                continue
            tag, tag_class = _gun_tag(t)
            gun_dict[t] = {"tarih": t, "gun_num": td.day, "gun_adi": _gun_adi(t),
                           "day_class": _gun_class(t, None), "tag": tag, "tag_class": tag_class,
                           "toplam_tutar": 0, "kayit_sayi": 0, "kayitlar": []}
        gun_dict[t]["kayitlar"].append(it)
        gun_dict[t]["toplam_tutar"] += it.get("tutar") or 0
        gun_dict[t]["kayit_sayi"] += 1
    gunler = sorted(gun_dict.values(), key=lambda g: g["tarih"])

    # KPI hesap
    bu_hafta_son = bugun + timedelta(days=7)
    kpi = {"bugun_sayi": 0, "bugun_tutar": 0, "hafta_sayi": 0, "hafta_tutar": 0,
           "gecikti_sayi": 0, "gecikti_tutar": 0, "bekleyen_sayi": 0, "bekleyen_tutar": 0}
    for it in items:
        tut = it.get("tutar") or 0
        durum = (it.get("durum") or "").upper()
        try:
            t = datetime.strptime(it.get("tarih") or "", "%Y-%m-%d").date()
        except Exception:
            continue
        if durum != "ODENDI":
            kpi["bekleyen_sayi"] += 1
            kpi["bekleyen_tutar"] += tut
        if t == bugun and durum != "ODENDI":
            kpi["bugun_sayi"] += 1
            kpi["bugun_tutar"] += tut
        if bugun <= t <= bu_hafta_son and durum != "ODENDI":
            kpi["hafta_sayi"] += 1
            kpi["hafta_tutar"] += tut
        if t < bugun and durum != "ODENDI":
            kpi["gecikti_sayi"] += 1
            kpi["gecikti_tutar"] += tut

    # ===== Sag panel: En Yakin Odemeler (>=bugun, <=30 gun) =====
    en_yakin = []
    for it in items:
        if (it.get("durum") or "").upper() == "ODENDI":
            continue
        try:
            t = datetime.strptime(it.get("tarih") or "", "%Y-%m-%d").date()
        except Exception:
            continue
        delta = (t - bugun).days
        if -7 <= delta <= 30:
            it_c = dict(it)
            it_c["gun_num"] = t.day
            it_c["ay_kisa"] = AY_KISA[t.month - 1]
            it_c["gun_kala"] = delta
            en_yakin.append(it_c)
    en_yakin.sort(key=lambda x: x.get("gun_kala", 0))
    en_yakin = en_yakin[:10]

    return {
        "cal_hucreler": cal_hucreler,
        "ay_baslik": ay_baslik,
        "prev_ay": prev_ay,
        "next_ay": next_ay,
        "yil": yil,
        "ay": ay,
        "en_yakin": en_yakin,
        "gunler": gunler,
        "kpi": kpi,
        "izinli_entity": izinli,
        "can_view_sahsi": "sahsi" in izinli,
        "veri_kaynak": veri_kaynak,
        "kayit_sayi": len(items),
    }