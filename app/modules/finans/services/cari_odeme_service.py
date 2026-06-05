# -*- coding: utf-8 -*-
"""
Cari Odeme Service - FAZ 3B
Sadece READ. Korgun canli sync YOK (FAZ 3B sonrasi).
Veri kaynaklari:
  - Cari_Kart + Cari_Har (CPS mock_data.db'de mock veri)
  - finans_cari_odeme_durum (FAZ 3A tablosu, su an bos)
Entity filtre + yetki seviyesi madde 10, 11 (sahsi admin only).
"""
import sqlite3
import os
from datetime import datetime, timedelta


def _db_path():
    """app/mock_data.db full path"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))), "mock_data.db")


def _durum_class(durum):
    """Durum string -> CSS class mapping"""
    d = (durum or "BEKLIYOR").upper()
    if d in ("ODENDI", "ODENMIS"): return "odendi"
    if d in ("GECIKTI", "GECIKMIS"): return "gecikti"
    if d in ("ACIK", "KISMI"): return "acik"
    return "bekliyor"


def _entity_yetki_filtre(g_user):
    """
    Madde 10, 11: Sahsi sadece admin gorur.
    Donus: izinli entity listesi
    """
    kullanici_adi = (g_user.get("KullaniciAdi") or "").lower() if g_user else ""
    rol_ad = g_user.get("RolAd") or g_user.get("Rol") or ""

    if kullanici_adi == "admin":
        return ["solariz", "nexgen", "pera", "sahsi"]
    else:
        # Yonetim, Muhasebe vb. - sahsi GORMEZ
        return ["solariz", "nexgen", "pera"]


def cari_odemeler_listele(g_user=None, entity=None, durum=None, baslangic=None,
                          bitis=None, cari_arama=None, limit=500):
    """
    Cari hareket + overlay durum okuyup birlestir.
    Mock entity ataması: CTip=1 ise solariz, CTip=2 nexgen vb. (gercek hayatta entity FK)
    """
    izinli = _entity_yetki_filtre(g_user)

    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row

    # Cari_Har + Cari_Kart join + overlay
    sql = """
        SELECT
            ch.Id              AS Id,
            ch.CKod            AS CKod,
            ck.CName           AS CName,
            ch.BelgeNo         AS BelgeNo,
            ch.Tarih           AS Tarih,
            ch.Borc            AS Borc,
            ch.Alacak          AS Alacak,
            COALESCE(cod.Durum, 'BEKLIYOR')      AS Durum,
            COALESCE(cod.VadeTarih, ch.Tarih)    AS VadeTarih,
            COALESCE(cod.entity,
                CASE
                    WHEN ck.CTip = 1 THEN 'solariz'
                    WHEN ck.CTip = 2 THEN 'nexgen'
                    ELSE 'solariz'
                END
            ) AS entity,
            COALESCE(cod.KaynakModul, 'MOCK')    AS KaynakModul,
            'TRY' AS ParaBirimi,
            cod.Notu AS Notu
        FROM Cari_Har ch
        LEFT JOIN Cari_Kart ck ON ck.CKod = ch.CKod
        LEFT JOIN finans_cari_odeme_durum cod ON cod.CariHarId = ch.Id
        WHERE 1=1
    """
    params = []

    # Entity filtre - yetki + secim
    if entity and entity in izinli:
        sql += " AND (COALESCE(cod.entity, CASE WHEN ck.CTip=1 THEN 'solariz' WHEN ck.CTip=2 THEN 'nexgen' ELSE 'solariz' END) = ?)"
        params.append(entity)
    else:
        # Tum izinli entity'ler
        placeholders = ",".join(["?"] * len(izinli))
        sql += f" AND (COALESCE(cod.entity, CASE WHEN ck.CTip=1 THEN 'solariz' WHEN ck.CTip=2 THEN 'nexgen' ELSE 'solariz' END) IN ({placeholders}))"
        params.extend(izinli)

    if durum:
        sql += " AND COALESCE(cod.Durum, 'BEKLIYOR') = ?"
        params.append(durum)

    if baslangic:
        sql += " AND ch.Tarih >= ?"
        params.append(baslangic)

    if bitis:
        sql += " AND ch.Tarih <= ?"
        params.append(bitis)

    if cari_arama:
        sql += " AND (ch.CKod LIKE ? OR ck.CName LIKE ?)"
        like = f"%{cari_arama}%"
        params.extend([like, like])

    sql += " ORDER BY ch.Tarih DESC, ch.Id DESC LIMIT ?"
    params.append(limit)

    rows = c.execute(sql, params).fetchall()

    kayitlar = []
    toplam_borc = 0.0
    toplam_alacak = 0.0
    for r in rows:
        d = dict(r)
        d["durum_class"] = _durum_class(d.get("Durum"))
        kayitlar.append(d)
        toplam_borc += d.get("Borc") or 0
        toplam_alacak += d.get("Alacak") or 0

    c.close()

    return {
        "kayitlar": kayitlar,
        "toplam_borc": toplam_borc,
        "toplam_alacak": toplam_alacak,
        "izinli_entity": izinli,
        "can_view_sahsi": "sahsi" in izinli,
    }


def cari_hareket_detay(hareket_id, g_user=None):
    """Tek hareket detayi (modal icin)"""
    izinli = _entity_yetki_filtre(g_user)
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    r = c.execute("""
        SELECT ch.*, ck.CName, ck.CTip, ck.VergiNo, ck.Telefon, ck.Sehir
          FROM Cari_Har ch
          LEFT JOIN Cari_Kart ck ON ck.CKod = ch.CKod
         WHERE ch.Id = ?
    """, (hareket_id,)).fetchone()
    c.close()
    return dict(r) if r else None


# ============================================================
# KORGUN SYNC STUB - madde 23 (canli calistirma YOK)
# ============================================================

def korgun_cari_har_query_stub():
    """
    FAZ 3B sonrasi (FAZ 6) Korgun sync icin query taslagi.
    Bu fonksiyon su an SADECE SQL stringi doner, calistirilmaz.
    """
    return {
        "dsn": {
            "server": "25.7.184.221",
            "port": 1433,
            "database": "Solariz22",
            "user": "claude",
            "password": "<gizli>",
        },
        "queries": {
            "cari_kart": """
                SELECT CKod, CName, CTip, VergiNo, VergiDairesi,
                       Telefon, Sehir, Ulke, Email, Adres, Bakiye, Aktif
                  FROM Cari_Kart
                 WHERE Aktif = 1
            """,
            "cari_har_son30g": """
                SELECT Id, CKod, Tarih, BelgeNo, BelgeTip,
                       Aciklama, Borc, Alacak
                  FROM Cari_Har
                 WHERE Tarih >= DATEADD(day, -30, GETDATE())
                 ORDER BY Tarih DESC
            """,
        },
        "target": {
            "Cari_Kart": "UPSERT (CKod PK)",
            "Cari_Har":  "UPSERT (Id PK, KaynakModul='KORGUN')",
        },
        "sync_freq": "Manuel tetik veya Task Scheduler 5 dk",
        "status": "STUB - canli kullanim FAZ 3B sonrasi onayli atomic move'da aktif olur",
    }