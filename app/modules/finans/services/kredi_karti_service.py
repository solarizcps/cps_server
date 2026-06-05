# -*- coding: utf-8 -*-
"""
Kredi Karti Service V2 - FAZ 4B-1
Tablo: finans_kredi_karti
Yetki: admin + altan (helper kontrol routes'ta)
admin + altan tum entity'leri gorur (Karar 1)
Fiziksel DELETE YOK - iptal icin Aktif=0
"""
import sqlite3
import os
import re
from datetime import datetime, date


# ===== SABITLER =====
ENTITY_SET = ("solariz", "nexgen", "pera", "sahsi")
PARA_BIRIMI_SET = ("TRY", "USD", "EUR")
KART_TIPI_SET = ("kredi", "bankamatik", "ticari", "diger")


def _db_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))), "mock_data.db")


def _conn(db_path=None):
    c = sqlite3.connect(db_path or _db_path())
    c.row_factory = sqlite3.Row
    return c


def _kullanici_adi(g_user):
    if not g_user:
        return None
    return (g_user.get("KullaniciAdi") or "").strip().lower()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ===== VALIDATION =====
class ValidationError(ValueError):
    pass


def _validate(data):
    """Form validasyon. Hata varsa ValidationError raise."""
    entity = (data.get("entity") or "").strip().lower()
    if entity not in ENTITY_SET:
        raise ValidationError(f"Entity gecersiz: {entity!r}. Set: {ENTITY_SET}")

    kart_ad = (data.get("kart_adi") or data.get("KartAd") or "").strip()
    if not kart_ad:
        raise ValidationError("Kart Adi bos olamaz")
    if len(kart_ad) > 100:
        raise ValidationError("Kart Adi en fazla 100 karakter")

    banka = (data.get("banka") or data.get("Banka") or "").strip()
    if len(banka) > 80:
        raise ValidationError("Banka en fazla 80 karakter")

    son4 = (data.get("son4") or data.get("Son4") or "").strip()
    if son4:
        if not re.match(r"^\d{1,4}$", son4):
            raise ValidationError(f"Son 4 hane sadece rakam (1-4 karakter): {son4!r}")

    # Limit
    try:
        limit = float(data.get("limit") or data.get("Limit_") or 0)
    except (ValueError, TypeError):
        raise ValidationError("Limit sayisal olmali")
    if limit < 0:
        raise ValidationError(f"Limit negatif olamaz: {limit}")
    if limit > 100_000_000:
        raise ValidationError(f"Limit 100M ustune cikamaz: {limit}")

    para_birimi = (data.get("para_birimi") or data.get("ParaBirimi") or "TRY").strip().upper()
    if para_birimi not in PARA_BIRIMI_SET:
        raise ValidationError(f"Para birimi gecersiz: {para_birimi!r}. Set: {PARA_BIRIMI_SET}")

    # DonemKesim (1-31, opsiyonel) - 0 falsy oldugu icin "or" kullanmiyoruz
    dk = data.get("donem_kesim")
    if dk is None or dk == "":
        dk = data.get("DonemKesim")
    if dk is None or str(dk).strip() == "":
        donem_kesim = None
    else:
        try:
            donem_kesim = int(dk)
        except (ValueError, TypeError):
            raise ValidationError("Donem Kesim Gunu sayisal olmali")
        if not (1 <= donem_kesim <= 31):
            raise ValidationError(f"Donem Kesim Gunu 1-31 arasi olmali: {donem_kesim}")

    # SonOdemeGun (1-31, opsiyonel)
    sg = data.get("son_odeme_gun")
    if sg is None or sg == "":
        sg = data.get("SonOdemeGun")
    if sg is None or str(sg).strip() == "":
        son_odeme_gun = None
    else:
        try:
            son_odeme_gun = int(sg)
        except (ValueError, TypeError):
            raise ValidationError("Son Odeme Gunu sayisal olmali")
        if not (1 <= son_odeme_gun <= 31):
            raise ValidationError(f"Son Odeme Gunu 1-31 arasi olmali: {son_odeme_gun}")

    kart_tipi = (data.get("kart_tipi") or data.get("KartTipi") or "kredi").strip().lower()
    if kart_tipi not in KART_TIPI_SET:
        kart_tipi = "kredi"

    try:
        kull_limit = float(data.get("kullanilabilir_limit") or data.get("KullanilabilirLimit") or 0)
    except (ValueError, TypeError):
        kull_limit = 0
    if kull_limit < 0:
        kull_limit = 0
    if kull_limit > limit:
        kull_limit = limit

    kart_sahibi = (data.get("kart_sahibi") or data.get("KartSahibi") or "").strip()[:120]
    notu = (data.get("aciklama") or data.get("notu") or data.get("Notu") or "").strip()[:500]

    return {
        "entity": entity,
        "KartAd": kart_ad,
        "Banka": banka,
        "KartTipi": kart_tipi,
        "KartSahibi": kart_sahibi,
        "Limit_": limit,
        "KullanilabilirLimit": kull_limit,
        "DonemKesim": donem_kesim,
        "SonOdemeGun": son_odeme_gun,
        "ParaBirimi": para_birimi,
        "Son4": son4 if son4 else None,
        "Notu": notu,
    }



# ===== LISTELE =====
def kredi_kartlari_listele(g_user=None, filtre=None, db_path=None):
    """
    Kart liste + filtre + KPI.
    admin + altan tum entity gorur.
    """
    f = filtre or {}
    c = _conn(db_path)

    where = ["1=1"]
    params = []

    if f.get("entity"):
        where.append("entity = ?")
        params.append(f["entity"].lower())

    if f.get("banka"):
        where.append("Banka LIKE ?")
        params.append("%" + f["banka"] + "%")

    if f.get("search"):
        where.append("(KartAd LIKE ? OR Banka LIKE ? OR Son4 LIKE ?)")
        s = "%" + f["search"] + "%"
        params.extend([s, s, s])

    # Pasif kartlar default gizli
    if not f.get("pasif_dahil"):
        where.append("Aktif = 1")

    sql = f"""
        SELECT * FROM finans_kredi_karti
         WHERE {' AND '.join(where)}
         ORDER BY entity, Banka, KartAd
    """
    rows = c.execute(sql, params).fetchall()
    items = [dict(r) for r in rows]

    # KPI hesap
    kpi = {
        "toplam_kart": 0, "aktif_kart": 0, "pasif_kart": 0,
        "toplam_limit": 0, "toplam_kullanim": 0, "kullanim_yuzde": 0,
        "yaklasan_odeme": 0,
    }
    bugun = date.today()
    for it in items:
        kpi["toplam_kart"] += 1
        if it.get("Aktif") == 1:
            kpi["aktif_kart"] += 1
            limit = it.get("Limit_") or 0
            kull = it.get("KullanilabilirLimit") or 0
            kpi["toplam_limit"] += limit
            kpi["toplam_kullanim"] += (limit - kull)
            son_g = it.get("SonOdemeGun")
            if son_g:
                # Bu ayin son odeme tarihi
                try:
                    son_t = date(bugun.year, bugun.month, min(son_g, 28))
                    if 0 <= (son_t - bugun).days <= 10:
                        kpi["yaklasan_odeme"] += 1
                except Exception:
                    pass
        else:
            kpi["pasif_kart"] += 1

    if kpi["toplam_limit"] > 0:
        kpi["kullanim_yuzde"] = round(100 * kpi["toplam_kullanim"] / kpi["toplam_limit"], 1)

    c.close()
    return {
        "items": items,
        "kpi": kpi,
        "filtre": f,
        "entity_set": list(ENTITY_SET),
        "para_birimi_set": list(PARA_BIRIMI_SET),
        "kart_tipi_set": list(KART_TIPI_SET),
    }


# ===== TEK KAYIT =====
def tek_kayit(kart_id, db_path=None):
    c = _conn(db_path)
    r = c.execute("SELECT * FROM finans_kredi_karti WHERE Id = ?", (kart_id,)).fetchone()
    c.close()
    return dict(r) if r else None


# ===== YENI KAYIT =====
def yeni(data, g_user, db_path=None):
    clean = _validate(data)
    kullanici = _kullanici_adi(g_user) or "system"

    c = _conn(db_path)
    cur = c.execute("""
        INSERT INTO finans_kredi_karti
            (entity, KartAd, Banka, KartTipi, KartSahibi, Limit_, KullanilabilirLimit,
             DonemKesim, SonOdemeGun, ParaBirimi, Son4, Aktif, Notu, KaynakModul,
             OlusturmaTarih, OlusturanKullanici)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'MANUEL', ?, ?)
    """, (clean["entity"], clean["KartAd"], clean["Banka"], clean["KartTipi"],
          clean["KartSahibi"], clean["Limit_"], clean["KullanilabilirLimit"],
          clean["DonemKesim"], clean["SonOdemeGun"], clean["ParaBirimi"],
          clean["Son4"], clean["Notu"], _now(), kullanici))
    yeni_id = cur.lastrowid
    c.commit()
    c.close()
    return yeni_id


# ===== GUNCELLE =====
def guncelle(kart_id, data, g_user, db_path=None):
    mevcut = tek_kayit(kart_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Kart bulunamadi: Id={kart_id}")
    if mevcut.get("Aktif") == 0:
        raise ValidationError("Pasif kart guncellenemez (once aktif et)")

    clean = _validate(data)
    kullanici = _kullanici_adi(g_user) or "system"

    c = _conn(db_path)
    c.execute("""
        UPDATE finans_kredi_karti
           SET entity = ?, KartAd = ?, Banka = ?, KartTipi = ?, KartSahibi = ?,
               Limit_ = ?, KullanilabilirLimit = ?, DonemKesim = ?, SonOdemeGun = ?,
               ParaBirimi = ?, Son4 = ?, Notu = ?,
               GuncellemeTarih = ?, Guncelleyen = ?
         WHERE Id = ?
    """, (clean["entity"], clean["KartAd"], clean["Banka"], clean["KartTipi"],
          clean["KartSahibi"], clean["Limit_"], clean["KullanilabilirLimit"],
          clean["DonemKesim"], clean["SonOdemeGun"], clean["ParaBirimi"],
          clean["Son4"], clean["Notu"], _now(), kullanici, kart_id))
    c.commit()
    c.close()
    return True


# ===== IPTAL / PASIF (DELETE yerine) =====
def iptal(kart_id, g_user, db_path=None):
    """Aktif=0 set eder. Fiziksel DELETE YOK."""
    mevcut = tek_kayit(kart_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Kart bulunamadi: Id={kart_id}")
    if mevcut.get("Aktif") == 0:
        return False  # zaten pasif

    kullanici = _kullanici_adi(g_user) or "system"
    c = _conn(db_path)
    c.execute("""
        UPDATE finans_kredi_karti
           SET Aktif = 0, GuncellemeTarih = ?, Guncelleyen = ?
         WHERE Id = ?
    """, (_now(), kullanici, kart_id))
    c.commit()
    c.close()
    return True

# ============================================================
# FAZ 4B-2: EKSTRE + HAREKET CRUD
# Sema degisikligi YOK
# Hareket iptal: KaynakModul = 'MANUEL_IPTAL'
# ============================================================

EKSTRE_DURUM_SET = ("ODENMEDI", "KISMEN_ODENDI", "ODENDI", "IPTAL")

# ===== EKSTRE VALIDATION =====
def _validate_ekstre(data):
    try:
        kart_id = int(data.get("kart_id") or data.get("KartId") or 0)
    except (ValueError, TypeError):
        raise ValidationError("KartId sayisal olmali")
    if kart_id <= 0:
        raise ValidationError("KartId zorunlu")

    db = (data.get("donem_baslangic") or data.get("DonemBaslangic") or "").strip()
    de = (data.get("donem_bitis") or data.get("DonemBitis") or "").strip()
    if not db or not de:
        raise ValidationError("DonemBaslangic ve DonemBitis zorunlu (YYYY-MM-DD)")
    try:
        d_bas = datetime.strptime(db, "%Y-%m-%d")
        d_bit = datetime.strptime(de, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("Donem format YYYY-MM-DD olmali")
    if d_bas > d_bit:
        raise ValidationError(f"DonemBaslangic ({db}) <= DonemBitis ({de}) olmali")

    son_odeme = (data.get("son_odeme_tarihi") or data.get("SonOdemeTarihi") or "").strip()
    if not son_odeme:
        raise ValidationError("SonOdemeTarihi zorunlu")
    try:
        datetime.strptime(son_odeme, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("SonOdemeTarihi format YYYY-MM-DD olmali")

    try:
        toplam_borc = float(data.get("toplam_borc") or data.get("ToplamBorc") or 0)
    except (ValueError, TypeError):
        raise ValidationError("ToplamBorc sayisal olmali")
    if toplam_borc < 0:
        raise ValidationError("ToplamBorc negatif olamaz")

    try:
        asgari = float(data.get("asgari_odeme") or data.get("AsgariOdeme") or 0)
    except (ValueError, TypeError):
        asgari = 0
    if asgari < 0:
        raise ValidationError("AsgariOdeme negatif olamaz")
    if asgari > toplam_borc:
        asgari = toplam_borc

    try:
        odenen = float(data.get("odenen_tutar") or data.get("OdenenTutar") or 0)
    except (ValueError, TypeError):
        odenen = 0
    if odenen < 0:
        raise ValidationError("OdenenTutar negatif olamaz")

    durum = (data.get("durum") or data.get("Durum") or "ODENMEDI").strip().upper()
    if durum not in EKSTRE_DURUM_SET:
        raise ValidationError(f"Durum gecersiz: {durum!r}. Set: {EKSTRE_DURUM_SET}")

    notu = (data.get("notu") or data.get("Notu") or "").strip()[:500]

    return {
        "KartId": kart_id,
        "DonemBaslangic": db,
        "DonemBitis": de,
        "SonOdemeTarihi": son_odeme,
        "ToplamBorc": toplam_borc,
        "AsgariOdeme": asgari,
        "OdenenTutar": odenen,
        "Durum": durum,
        "Notu": notu,
    }


# ===== EKSTRE CRUD =====
def ekstre_listele(kart_id=None, filtre=None, db_path=None):
    """
    Ekstre liste. kart_id verilirse o karta ait ekstreler.
    """
    f = filtre or {}
    c = _conn(db_path)
    where = ["1=1"]
    params = []

    if kart_id is not None:
        where.append("e.KartId = ?")
        params.append(int(kart_id))

    if f.get("durum"):
        where.append("e.Durum = ?")
        params.append(f["durum"].upper())

    if f.get("entity"):
        where.append("k.entity = ?")
        params.append(f["entity"].lower())

    sql = f"""
        SELECT e.*, k.entity as Kart_Entity, k.KartAd, k.Banka, k.Son4
          FROM finans_kredi_karti_ekstre e
          LEFT JOIN finans_kredi_karti k ON k.Id = e.KartId
         WHERE {' AND '.join(where)}
         ORDER BY e.DonemBaslangic DESC, e.Id DESC
    """
    rows = c.execute(sql, params).fetchall()
    items = [dict(r) for r in rows]

    kpi = {
        "toplam_ekstre": len(items),
        "odenmedi_sayi": sum(1 for it in items if it.get("Durum") == "ODENMEDI"),
        "kismen_sayi": sum(1 for it in items if it.get("Durum") == "KISMEN_ODENDI"),
        "odendi_sayi": sum(1 for it in items if it.get("Durum") == "ODENDI"),
        "iptal_sayi": sum(1 for it in items if it.get("Durum") == "IPTAL"),
        "toplam_borc": sum((it.get("ToplamBorc") or 0) for it in items if it.get("Durum") != "IPTAL"),
        "toplam_odenen": sum((it.get("OdenenTutar") or 0) for it in items),
    }
    kpi["kalan"] = kpi["toplam_borc"] - kpi["toplam_odenen"]

    c.close()
    return {
        "items": items,
        "kpi": kpi,
        "kart_id": kart_id,
        "durum_set": list(EKSTRE_DURUM_SET),
    }


def ekstre_tek(ekstre_id, db_path=None):
    c = _conn(db_path)
    r = c.execute("""
        SELECT e.*, k.entity as Kart_Entity, k.KartAd, k.Banka, k.Son4
          FROM finans_kredi_karti_ekstre e
          LEFT JOIN finans_kredi_karti k ON k.Id = e.KartId
         WHERE e.Id = ?
    """, (ekstre_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def ekstre_yeni(data, g_user, db_path=None):
    clean = _validate_ekstre(data)
    # Kart var mi kontrolu
    c = _conn(db_path)
    kart = c.execute("SELECT Id, Aktif FROM finans_kredi_karti WHERE Id = ?", (clean["KartId"],)).fetchone()
    if not kart:
        c.close()
        raise ValidationError(f"Kart bulunamadi: KartId={clean['KartId']}")
    if kart["Aktif"] == 0:
        c.close()
        raise ValidationError("Pasif kart icin ekstre olusturulamaz")

    cur = c.execute("""
        INSERT INTO finans_kredi_karti_ekstre
            (KartId, DonemBaslangic, DonemBitis, SonOdemeTarihi,
             ToplamBorc, AsgariOdeme, OdenenTutar, Durum, Notu, OlusturmaTarih)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (clean["KartId"], clean["DonemBaslangic"], clean["DonemBitis"],
          clean["SonOdemeTarihi"], clean["ToplamBorc"], clean["AsgariOdeme"],
          clean["OdenenTutar"], clean["Durum"], clean["Notu"], _now()))
    yeni_id = cur.lastrowid
    c.commit()
    c.close()
    return yeni_id


def ekstre_guncelle(ekstre_id, data, g_user, db_path=None):
    mevcut = ekstre_tek(ekstre_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Ekstre bulunamadi: Id={ekstre_id}")
    if mevcut.get("Durum") == "IPTAL":
        raise ValidationError("IPTAL ekstre guncellenemez")

    clean = _validate_ekstre(data)
    c = _conn(db_path)
    c.execute("""
        UPDATE finans_kredi_karti_ekstre
           SET KartId = ?, DonemBaslangic = ?, DonemBitis = ?, SonOdemeTarihi = ?,
               ToplamBorc = ?, AsgariOdeme = ?, OdenenTutar = ?, Durum = ?, Notu = ?
         WHERE Id = ?
    """, (clean["KartId"], clean["DonemBaslangic"], clean["DonemBitis"],
          clean["SonOdemeTarihi"], clean["ToplamBorc"], clean["AsgariOdeme"],
          clean["OdenenTutar"], clean["Durum"], clean["Notu"], ekstre_id))
    c.commit()
    c.close()
    return True


def ekstre_kapat(ekstre_id, odenen_tutar, g_user, db_path=None):
    """
    Ekstre kapatma. odenen_tutar = ToplamBorc ise Durum='ODENDI'
    odenen_tutar > 0 ama < ToplamBorc ise Durum='KISMEN_ODENDI'
    """
    mevcut = ekstre_tek(ekstre_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Ekstre bulunamadi: Id={ekstre_id}")
    if mevcut.get("Durum") == "IPTAL":
        raise ValidationError("IPTAL ekstre kapatilamaz")

    try:
        ot = float(odenen_tutar)
    except (ValueError, TypeError):
        raise ValidationError("Odenen tutar sayisal olmali")
    if ot < 0:
        raise ValidationError("Odenen tutar negatif olamaz")

    toplam = mevcut.get("ToplamBorc") or 0
    if ot >= toplam:
        yeni_durum = "ODENDI"
    elif ot > 0:
        yeni_durum = "KISMEN_ODENDI"
    else:
        yeni_durum = "ODENMEDI"

    c = _conn(db_path)
    c.execute("""
        UPDATE finans_kredi_karti_ekstre
           SET OdenenTutar = ?, Durum = ?
         WHERE Id = ?
    """, (ot, yeni_durum, ekstre_id))
    c.commit()
    c.close()
    return yeni_durum


# ===== HAREKET VALIDATION =====
def _validate_hareket(data):
    try:
        kart_id = int(data.get("kart_id") or data.get("KartId") or 0)
    except (ValueError, TypeError):
        raise ValidationError("KartId sayisal olmali")
    if kart_id <= 0:
        raise ValidationError("KartId zorunlu")

    ekstre_id = data.get("ekstre_id") or data.get("EkstreId")
    if ekstre_id is None or str(ekstre_id).strip() == "":
        ekstre_id = None
    else:
        try:
            ekstre_id = int(ekstre_id)
        except (ValueError, TypeError):
            raise ValidationError("EkstreId sayisal olmali")
        if ekstre_id <= 0:
            ekstre_id = None

    tarih = (data.get("hareket_tarih") or data.get("HareketTarih") or "").strip()
    if not tarih:
        raise ValidationError("HareketTarih zorunlu")
    try:
        datetime.strptime(tarih, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("HareketTarih format YYYY-MM-DD olmali")

    try:
        tutar = float(data.get("tutar") or data.get("IslemTutari") or 0)
    except (ValueError, TypeError):
        raise ValidationError("IslemTutari sayisal olmali")
    if tutar < 0:
        raise ValidationError("IslemTutari negatif olamaz")

    islem_adi = (data.get("islem_adi") or data.get("IslemAdi") or "").strip()[:120]
    kategori = (data.get("kategori") or data.get("Kategori") or "").strip()[:50]
    aciklama = (data.get("aciklama") or data.get("Aciklama") or "").strip()[:500]
    para_birimi = (data.get("para_birimi") or data.get("ParaBirimi") or "TRY").strip().upper()
    if para_birimi not in PARA_BIRIMI_SET:
        para_birimi = "TRY"

    # Taksit mantigi
    taksit_mi_raw = data.get("taksit_mi") or data.get("TaksitMi") or 0
    taksit_mi = 1 if str(taksit_mi_raw).strip() in ("1", "true", "True", "on") else 0

    try:
        taksit_sayisi = int(data.get("taksit_sayisi") or data.get("TaksitSayisi") or 0)
    except (ValueError, TypeError):
        taksit_sayisi = 0
    try:
        taksit_no = int(data.get("taksit_no") or data.get("TaksitNo") or 0)
    except (ValueError, TypeError):
        taksit_no = 0

    if taksit_mi == 1:
        if taksit_sayisi <= 0:
            raise ValidationError("TaksitMi=1 ise TaksitSayisi > 0 olmali")
    else:
        # Taksitsiz ise normalize
        taksit_sayisi = 0
        taksit_no = 0

    if not (0 <= taksit_sayisi <= 24):
        raise ValidationError("TaksitSayisi 0-24 arasi olmali")
    if not (0 <= taksit_no <= 24):
        raise ValidationError("TaksitNo 0-24 arasi olmali")
    if taksit_no > taksit_sayisi:
        raise ValidationError(f"TaksitNo ({taksit_no}) <= TaksitSayisi ({taksit_sayisi}) olmali")

    return {
        "KartId": kart_id,
        "EkstreId": ekstre_id,
        "HareketTarih": tarih,
        "IslemTutari": tutar,
        "IslemAdi": islem_adi,
        "Kategori": kategori,
        "TaksitMi": taksit_mi,
        "TaksitSayisi": taksit_sayisi,
        "TaksitNo": taksit_no,
        "ParaBirimi": para_birimi,
        "Aciklama": aciklama,
    }


# ===== HAREKET CRUD =====
def hareket_listele(ekstre_id=None, kart_id=None, filtre=None, db_path=None):
    f = filtre or {}
    c = _conn(db_path)
    where = ["1=1"]
    params = []

    if ekstre_id is not None:
        where.append("h.EkstreId = ?")
        params.append(int(ekstre_id))
    elif kart_id is not None:
        where.append("h.KartId = ?")
        params.append(int(kart_id))

    if f.get("kategori"):
        where.append("h.Kategori = ?")
        params.append(f["kategori"])

    # Iptal hariç
    if not f.get("iptal_dahil"):
        where.append("(h.KaynakModul IS NULL OR h.KaynakModul NOT LIKE '%_IPTAL')")

    sql = f"""
        SELECT h.*, k.entity as Kart_Entity, k.KartAd, k.Son4
          FROM finans_kredi_karti_hareket h
          LEFT JOIN finans_kredi_karti k ON k.Id = h.KartId
         WHERE {' AND '.join(where)}
         ORDER BY h.HareketTarih DESC, h.Id DESC
    """
    rows = c.execute(sql, params).fetchall()
    items = [dict(r) for r in rows]

    # Aktif/Iptal flag
    for it in items:
        it["_aktif"] = not (it.get("KaynakModul") or "").endswith("_IPTAL")

    kpi = {
        "toplam_hareket": len(items),
        "aktif_sayi": sum(1 for it in items if it["_aktif"]),
        "iptal_sayi": sum(1 for it in items if not it["_aktif"]),
        "toplam_tutar": sum((it.get("IslemTutari") or 0) for it in items if it["_aktif"]),
        "taksitli_sayi": sum(1 for it in items if it.get("TaksitMi") == 1 and it["_aktif"]),
    }

    c.close()
    return {
        "items": items,
        "kpi": kpi,
        "ekstre_id": ekstre_id,
        "kart_id": kart_id,
    }


def hareket_tek(hareket_id, db_path=None):
    c = _conn(db_path)
    r = c.execute("""
        SELECT h.*, k.entity as Kart_Entity, k.KartAd, k.Son4
          FROM finans_kredi_karti_hareket h
          LEFT JOIN finans_kredi_karti k ON k.Id = h.KartId
         WHERE h.Id = ?
    """, (hareket_id,)).fetchone()
    c.close()
    if r:
        d = dict(r)
        d["_aktif"] = not (d.get("KaynakModul") or "").endswith("_IPTAL")
        return d
    return None


def hareket_yeni(data, g_user, db_path=None):
    clean = _validate_hareket(data)
    # Kart var mi
    c = _conn(db_path)
    kart = c.execute("SELECT Id, Aktif FROM finans_kredi_karti WHERE Id = ?", (clean["KartId"],)).fetchone()
    if not kart:
        c.close()
        raise ValidationError(f"Kart bulunamadi: KartId={clean['KartId']}")
    if kart["Aktif"] == 0:
        c.close()
        raise ValidationError("Pasif karta hareket eklenemez")

    # Ekstre var mi (opsiyonel)
    if clean["EkstreId"] is not None:
        ekstre = c.execute("SELECT Id, KartId, Durum FROM finans_kredi_karti_ekstre WHERE Id = ?", (clean["EkstreId"],)).fetchone()
        if not ekstre:
            c.close()
            raise ValidationError(f"Ekstre bulunamadi: EkstreId={clean['EkstreId']}")
        if ekstre["KartId"] != clean["KartId"]:
            c.close()
            raise ValidationError("EkstreId baska bir karta ait")
        if ekstre["Durum"] == "IPTAL":
            c.close()
            raise ValidationError("IPTAL ekstreye hareket eklenemez")

    cur = c.execute("""
        INSERT INTO finans_kredi_karti_hareket
            (KartId, EkstreId, HareketTarih, IslemTutari, IslemAdi, Kategori,
             TaksitMi, TaksitSayisi, TaksitNo, ParaBirimi, Aciklama, KaynakModul, OlusturmaTarih)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUEL', ?)
    """, (clean["KartId"], clean["EkstreId"], clean["HareketTarih"], clean["IslemTutari"],
          clean["IslemAdi"], clean["Kategori"], clean["TaksitMi"], clean["TaksitSayisi"],
          clean["TaksitNo"], clean["ParaBirimi"], clean["Aciklama"], _now()))
    yeni_id = cur.lastrowid
    c.commit()
    c.close()
    return yeni_id


def hareket_guncelle(hareket_id, data, g_user, db_path=None):
    mevcut = hareket_tek(hareket_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Hareket bulunamadi: Id={hareket_id}")
    if not mevcut.get("_aktif"):
        raise ValidationError("IPTAL hareket guncellenemez")

    clean = _validate_hareket(data)
    c = _conn(db_path)
    c.execute("""
        UPDATE finans_kredi_karti_hareket
           SET KartId = ?, EkstreId = ?, HareketTarih = ?, IslemTutari = ?,
               IslemAdi = ?, Kategori = ?, TaksitMi = ?, TaksitSayisi = ?,
               TaksitNo = ?, ParaBirimi = ?, Aciklama = ?
         WHERE Id = ?
    """, (clean["KartId"], clean["EkstreId"], clean["HareketTarih"], clean["IslemTutari"],
          clean["IslemAdi"], clean["Kategori"], clean["TaksitMi"], clean["TaksitSayisi"],
          clean["TaksitNo"], clean["ParaBirimi"], clean["Aciklama"], hareket_id))
    c.commit()
    c.close()
    return True


def hareket_iptal(hareket_id, g_user, db_path=None):
    """
    Fiziksel DELETE YOK. KaynakModul -> '*_IPTAL' suffix ile isaretlenir.
    """
    mevcut = hareket_tek(hareket_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Hareket bulunamadi: Id={hareket_id}")
    if not mevcut.get("_aktif"):
        return False  # zaten iptal

    eski_km = mevcut.get("KaynakModul") or "MANUEL"
    yeni_km = eski_km if eski_km.endswith("_IPTAL") else (eski_km + "_IPTAL")

    c = _conn(db_path)
    c.execute("UPDATE finans_kredi_karti_hareket SET KaynakModul = ? WHERE Id = ?",
              (yeni_km, hareket_id))
    c.commit()
    c.close()
    return True