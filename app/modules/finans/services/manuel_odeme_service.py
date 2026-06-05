# -*- coding: utf-8 -*-
"""
Manuel Odeme Service - FAZ 4A
Tablo: finans_manuel_odeme
Yetki: admin + altan (helper'dan baska kullanici gelmez)
Sahsi entity admin + altan ikisi de gorur (Karar 1 - 18.05.2026)
Fiziksel DELETE YOK - Durum='IPTAL' kullanilir
"""
import sqlite3
import os
from datetime import datetime, date


# ===== SABITLER =====
ENTITY_SET = ("solariz", "nexgen", "pera", "sahsi")
PARA_BIRIMI_SET = ("TRY", "USD", "EUR")
DURUM_SET = ("BEKLIYOR", "ODENDI", "GECIKTI", "IPTAL")
KATEGORI_SET = ("kredi", "kart", "cari", "cek", "maas", "vergi",
                "kira", "fatura", "nakliye", "diger")


def _db_path():
    """Service dosyasi 3 dirname yukari = app/ klasoru, sonra mock_data.db"""
    here = os.path.dirname(os.path.abspath(__file__))
    # services -> finans -> modules -> app
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
    """Form verisi validasyon. Hata varsa ValidationError raise."""
    entity = (data.get("entity") or "").strip().lower()
    if entity not in ENTITY_SET:
        raise ValidationError(f"Entity gecersiz: {entity!r}. Set: {ENTITY_SET}")

    baslik = (data.get("baslik") or data.get("Aciklama") or "").strip()
    if not baslik:
        raise ValidationError("Baslik/Aciklama bos olamaz")

    tip = (data.get("tip") or data.get("Tip") or "").strip().lower()
    if tip not in KATEGORI_SET:
        raise ValidationError(f"Kategori gecersiz: {tip!r}. Set: {KATEGORI_SET}")

    try:
        tutar = float(data.get("tutar") or data.get("Tutar") or 0)
    except (ValueError, TypeError):
        raise ValidationError("Tutar sayisal olmali")
    if tutar < 0:
        raise ValidationError(f"Tutar negatif olamaz: {tutar}")
    if tutar > 10_000_000:
        raise ValidationError(f"Tutar 10M TL ustune cikamaz: {tutar}")

    para_birimi = (data.get("para_birimi") or data.get("ParaBirimi") or "TRY").strip().upper()
    if para_birimi not in PARA_BIRIMI_SET:
        raise ValidationError(f"Para birimi gecersiz: {para_birimi!r}. Set: {PARA_BIRIMI_SET}")

    vade = (data.get("vade_tarihi") or data.get("VadeTarih") or "").strip()
    if not vade:
        raise ValidationError("VadeTarih bos olamaz")
    try:
        datetime.strptime(vade, "%Y-%m-%d")
    except ValueError:
        raise ValidationError(f"VadeTarih format hatasi (YYYY-MM-DD bekleniyor): {vade}")

    durum = (data.get("durum") or data.get("Durum") or "BEKLIYOR").strip().upper()
    if durum not in DURUM_SET:
        raise ValidationError(f"Durum gecersiz: {durum!r}. Set: {DURUM_SET}")

    notu = (data.get("notu") or data.get("Notu") or "").strip()

    return {
        "entity": entity,
        "Aciklama": baslik,
        "Tip": tip,
        "Tutar": tutar,
        "ParaBirimi": para_birimi,
        "VadeTarih": vade,
        "Durum": durum,
        "Notu": notu,
    }


# ===== LISTELE =====
def listele(g_user=None, filtre=None, db_path=None):
    """
    Liste + filtre. admin + altan tum entity'leri gorur.
    filtre = {"entity": "solariz", "durum": "BEKLIYOR", "tip": "kira", "search": "..."}
    """
    f = filtre or {}
    c = _conn(db_path)

    where = ["1=1"]
    params = []

    # Entity filtre - kullanici secimi (admin+altan hepsini gorebilir)
    if f.get("entity"):
        where.append("entity = ?")
        params.append(f["entity"].lower())

    if f.get("durum"):
        where.append("Durum = ?")
        params.append(f["durum"].upper())

    if f.get("tip"):
        where.append("Tip = ?")
        params.append(f["tip"].lower())

    if f.get("search"):
        where.append("(Aciklama LIKE ? OR Notu LIKE ?)")
        s = "%" + f["search"] + "%"
        params.extend([s, s])

    # Iptaller default gizli (sadece istenirse gosterilir)
    if not f.get("iptal_dahil"):
        where.append("Durum != 'IPTAL'")

    sql = f"""
        SELECT * FROM finans_manuel_odeme
         WHERE {' AND '.join(where)}
         ORDER BY VadeTarih ASC, Id DESC
    """
    rows = c.execute(sql, params).fetchall()
    items = [dict(r) for r in rows]

    # KPI hesap
    bugun = date.today()
    kpi = {"toplam_kayit": 0, "bugun_sayi": 0, "bugun_tutar": 0,
           "gecikti_sayi": 0, "gecikti_tutar": 0, "bekleyen_sayi": 0,
           "bekleyen_tutar": 0, "odendi_sayi": 0, "odendi_tutar": 0}

    for it in items:
        tut = it.get("Tutar") or 0
        durum = (it.get("Durum") or "").upper()
        kpi["toplam_kayit"] += 1
        try:
            t = datetime.strptime(it.get("VadeTarih") or "", "%Y-%m-%d").date()
        except Exception:
            t = None

        if durum == "ODENDI":
            kpi["odendi_sayi"] += 1
            kpi["odendi_tutar"] += tut
        elif durum == "BEKLIYOR":
            kpi["bekleyen_sayi"] += 1
            kpi["bekleyen_tutar"] += tut
            if t and t == bugun:
                kpi["bugun_sayi"] += 1
                kpi["bugun_tutar"] += tut
            if t and t < bugun:
                kpi["gecikti_sayi"] += 1
                kpi["gecikti_tutar"] += tut

    c.close()
    return {
        "items": items,
        "kpi": kpi,
        "filtre": f,
        "entity_set": list(ENTITY_SET),
        "para_birimi_set": list(PARA_BIRIMI_SET),
        "durum_set": list(DURUM_SET),
        "kategori_set": list(KATEGORI_SET),
    }


# ===== TEK KAYIT =====
def tek_kayit(kayit_id, db_path=None):
    c = _conn(db_path)
    r = c.execute("SELECT * FROM finans_manuel_odeme WHERE Id = ?", (kayit_id,)).fetchone()
    c.close()
    return dict(r) if r else None


# ===== YENI KAYIT =====
def yeni(data, g_user, db_path=None):
    """
    Yeni manuel odeme kaydi. Validation yapilir, audit yazilir.
    """
    clean = _validate(data)
    kullanici = _kullanici_adi(g_user) or "system"

    c = _conn(db_path)
    cur = c.execute("""
        INSERT INTO finans_manuel_odeme
            (entity, Aciklama, Tip, Tutar, ParaBirimi, VadeTarih,
             Durum, Notu, KaynakModul, OlusturmaTarih, OlusturanKullanici)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'MANUEL', ?, ?)
    """, (clean["entity"], clean["Aciklama"], clean["Tip"], clean["Tutar"],
          clean["ParaBirimi"], clean["VadeTarih"], clean["Durum"], clean["Notu"],
          _now(), kullanici))
    yeni_id = cur.lastrowid
    c.commit()
    c.close()
    return yeni_id


# ===== GUNCELLE =====
def guncelle(kayit_id, data, g_user, db_path=None):
    """
    Mevcut kaydi gunceller. IPTAL ediler guncellenmez.
    """
    mevcut = tek_kayit(kayit_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Kayit bulunamadi: Id={kayit_id}")
    if mevcut.get("Durum") == "IPTAL":
        raise ValidationError("IPTAL edilmis kayit guncellenemez")

    clean = _validate(data)
    kullanici = _kullanici_adi(g_user) or "system"

    c = _conn(db_path)
    c.execute("""
        UPDATE finans_manuel_odeme
           SET entity = ?, Aciklama = ?, Tip = ?, Tutar = ?,
               ParaBirimi = ?, VadeTarih = ?, Durum = ?, Notu = ?,
               GuncellemeTarih = ?, Guncelleyen = ?
         WHERE Id = ?
    """, (clean["entity"], clean["Aciklama"], clean["Tip"], clean["Tutar"],
          clean["ParaBirimi"], clean["VadeTarih"], clean["Durum"], clean["Notu"],
          _now(), kullanici, kayit_id))
    c.commit()
    c.close()
    return True


# ===== IPTAL (DELETE yerine) =====
def iptal(kayit_id, g_user, db_path=None):
    """
    Fiziksel DELETE yapmaz. Durum='IPTAL' set eder.
    """
    mevcut = tek_kayit(kayit_id, db_path=db_path)
    if not mevcut:
        raise ValidationError(f"Kayit bulunamadi: Id={kayit_id}")
    if mevcut.get("Durum") == "IPTAL":
        return False  # zaten iptal

    kullanici = _kullanici_adi(g_user) or "system"
    c = _conn(db_path)
    c.execute("""
        UPDATE finans_manuel_odeme
           SET Durum = 'IPTAL', GuncellemeTarih = ?, Guncelleyen = ?
         WHERE Id = ?
    """, (_now(), kullanici, kayit_id))
    c.commit()
    c.close()
    return True