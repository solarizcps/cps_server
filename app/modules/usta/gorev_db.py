# -*- coding: utf-8 -*-
"""
FAZ 4.3 - usta_gorevleri DB helper

Karar Masasi -> Usta Gorevi pilot icin CRUD katmani.
SQLite solariz_dev.db uzerinde calisir.

NOT: uretim_kayit tablosuyla iliskisi yoktur.
     MES v2 ile iletisimi yoktur.
     Tamamen izole sandbox.
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = r"C:\cps_dev\solariz_dev.db"

GECERLI_DURUMLAR = ("ATANDI", "OKUNDU", "BASLADI", "TAMAMLANDI", "IPTAL")
DURUM_GECISLERI = {
    "ATANDI": ("OKUNDU", "IPTAL"),
    "OKUNDU": ("BASLADI", "IPTAL"),
    "BASLADI": ("TAMAMLANDI", "IPTAL"),
    "TAMAMLANDI": (),
    "IPTAL": (),
}


def _conn():
    """Tek seferlik baglanti (kullaniciya birakilmaz)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row) -> Dict[str, Any]:
    """sqlite3.Row -> dict donusumu."""
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def gorev_ekle(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Yeni gorev ekler.

    Zorunlu alanlar:
        siparis_no, musteri, model, hedef_adet, olusturan

    Opsiyonel:
        karar_masasi_satir_id, emir_no, bant, kalan_adet,
        uretilebilirlik, darbogaz, talimat, oncelik,
        musteri_etiketi, atanan_usta, olusturan_notu,
        termin, termin_durumu

    Donus: { ok, gorev_id, mesaj }
    """
    zorunlu = ("siparis_no", "musteri", "model", "olusturan")
    eksik = [k for k in zorunlu if not payload.get(k)]
    if eksik:
        return {
            "ok": False,
            "hata": "snapshot_eksik",
            "mesaj": f"Zorunlu alanlar eksik: {', '.join(eksik)}"
        }

    sql = """
        INSERT INTO usta_gorevleri (
            karar_masasi_satir_id, siparis_no, emir_no, musteri, model,
            bant, hedef_adet, kalan_adet, uretilebilirlik, darbogaz,
            talimat, oncelik, musteri_etiketi, atanan_usta, olusturan,
            olusturan_notu, durum, termin, termin_durumu
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    parametreler = (
        payload.get("karar_masasi_satir_id"),
        payload["siparis_no"],
        payload.get("emir_no"),
        payload["musteri"],
        payload["model"],
        payload.get("bant"),
        int(payload.get("hedef_adet") or 0),
        payload.get("kalan_adet"),
        payload.get("uretilebilirlik"),
        payload.get("darbogaz"),
        payload.get("talimat"),
        int(payload.get("oncelik") or 50),
        payload.get("musteri_etiketi"),
        (payload.get("atanan_usta") or "").strip() or None,
        payload["olusturan"],
        payload.get("olusturan_notu"),
        "ATANDI",
        payload.get("termin"),
        payload.get("termin_durumu"),
    )

    conn = _conn()
    try:
        cur = conn.execute(sql, parametreler)
        conn.commit()
        gorev_id = cur.lastrowid

        olusturma = conn.execute(
            "SELECT olusturma_tarih FROM usta_gorevleri WHERE id=?",
            (gorev_id,)
        ).fetchone()
        olusturma_str = olusturma["olusturma_tarih"] if olusturma else None

        return {
            "ok": True,
            "gorev_id": gorev_id,
            "olusturma_tarih": olusturma_str,
            "mesaj": "Gorev basariyla olusturuldu"
        }
    except sqlite3.Error as e:
        return {
            "ok": False,
            "hata": "db_hata",
            "mesaj": str(e)
        }
    finally:
        conn.close()


def gorev_listele(durum_filtresi: str = "acik",
                  atanan: Optional[str] = None) -> Dict[str, Any]:
    """
    Gorev listesi.

    durum_filtresi:
        'acik'   -> ATANDI, OKUNDU, BASLADI (default)
        'tamam'  -> TAMAMLANDI
        'iptal'  -> IPTAL
        'hepsi'  -> tumu

    atanan:
        None -> tum gorevler
        'Hasan' -> sadece Hasan'a atanmis VEYA atanan_usta NULL olanlar
    """
    where = []
    params = []

    if durum_filtresi == "acik":
        where.append("durum IN ('ATANDI', 'OKUNDU', 'BASLADI')")
    elif durum_filtresi == "tamam":
        where.append("durum = 'TAMAMLANDI'")
    elif durum_filtresi == "iptal":
        where.append("durum = 'IPTAL'")

    if atanan:
        where.append("(atanan_usta = ? OR atanan_usta IS NULL)")
        params.append(atanan)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT * FROM usta_gorevleri{where_sql}
        ORDER BY 
            CASE durum
                WHEN 'ATANDI' THEN 1
                WHEN 'OKUNDU' THEN 2
                WHEN 'BASLADI' THEN 3
                WHEN 'TAMAMLANDI' THEN 4
                WHEN 'IPTAL' THEN 5
            END,
            oncelik DESC,
            olusturma_tarih DESC
    """

    conn = _conn()
    try:
        cur = conn.execute(sql, params)
        gorevler = [_row_to_dict(r) for r in cur.fetchall()]

        atandi_sayisi = sum(1 for g in gorevler if g["durum"] == "ATANDI")

        return {
            "ok": True,
            "gorev_sayisi": len(gorevler),
            "atandi_sayisi": atandi_sayisi,
            "gorevler": gorevler
        }
    except sqlite3.Error as e:
        return {"ok": False, "hata": "db_hata", "mesaj": str(e)}
    finally:
        conn.close()


def gorev_getir(gorev_id: int) -> Dict[str, Any]:
    """Tek gorev getir."""
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT * FROM usta_gorevleri WHERE id = ?",
            (gorev_id,)
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "hata": "bulunamadi", "mesaj": "Gorev bulunamadi"}
        return {"ok": True, "gorev": _row_to_dict(row)}
    finally:
        conn.close()


def gorev_durum_guncelle(gorev_id: int, yeni_durum: str,
                         ek_alanlar: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Durum gecisi.
    
    ATANDI -> OKUNDU      (okuma_tarih dolar)
    OKUNDU -> BASLADI     (baslama_tarih dolar)
    BASLADI -> TAMAMLANDI (tamamlanma_tarih dolar)
    
    ek_alanlar opsiyonel: usta_notu
    """
    if yeni_durum not in GECERLI_DURUMLAR:
        return {"ok": False, "hata": "gecersiz_durum",
                "mesaj": f"Gecersiz durum: {yeni_durum}"}

    mevcut = gorev_getir(gorev_id)
    if not mevcut.get("ok"):
        return {"ok": False, "hata": "bulunamadi",
                "mesaj": "Gorev bulunamadi"}

    eski_durum = mevcut["gorev"]["durum"]
    izinli = DURUM_GECISLERI.get(eski_durum, ())

    if yeni_durum not in izinli:
        return {
            "ok": False,
            "hata": "durum_uyumsuz",
            "mevcut_durum": eski_durum,
            "mesaj": f"'{eski_durum}' durumundan '{yeni_durum}' gecisi yapilamaz"
        }

    set_parts = ["durum = ?"]
    params = [yeni_durum]

    simdi = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if yeni_durum == "OKUNDU":
        set_parts.append("okuma_tarih = ?")
        params.append(simdi)
    elif yeni_durum == "BASLADI":
        set_parts.append("baslama_tarih = ?")
        params.append(simdi)
    elif yeni_durum == "TAMAMLANDI":
        set_parts.append("tamamlanma_tarih = ?")
        params.append(simdi)

    if ek_alanlar:
        if "usta_notu" in ek_alanlar:
            set_parts.append("usta_notu = ?")
            params.append(ek_alanlar["usta_notu"])

    params.append(gorev_id)
    sql = f"UPDATE usta_gorevleri SET {', '.join(set_parts)} WHERE id = ?"

    conn = _conn()
    try:
        conn.execute(sql, params)
        conn.commit()

        guncellenen = gorev_getir(gorev_id)
        return {
            "ok": True,
            "gorev_id": gorev_id,
            "eski_durum": eski_durum,
            "yeni_durum": yeni_durum,
            "guncel_zaman": simdi,
            "gorev": guncellenen.get("gorev"),
            "mesaj": f"Durum guncellendi: {eski_durum} -> {yeni_durum}"
        }
    except sqlite3.Error as e:
        return {"ok": False, "hata": "db_hata", "mesaj": str(e)}
    finally:
        conn.close()


def gorev_okudu(gorev_id: int) -> Dict[str, Any]:
    return gorev_durum_guncelle(gorev_id, "OKUNDU")


def gorev_basladi(gorev_id: int) -> Dict[str, Any]:
    return gorev_durum_guncelle(gorev_id, "BASLADI")


def gorev_bitti(gorev_id: int, usta_notu: Optional[str] = None) -> Dict[str, Any]:
    ek = {"usta_notu": usta_notu} if usta_notu else None
    return gorev_durum_guncelle(gorev_id, "TAMAMLANDI", ek)


def istatistik() -> Dict[str, Any]:
    """Pilot icin basit istatistik."""
    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT durum, COUNT(*) as adet 
            FROM usta_gorevleri 
            GROUP BY durum
        """)
        durumlar = {r["durum"]: r["adet"] for r in cur.fetchall()}
        toplam = sum(durumlar.values())
        return {
            "ok": True,
            "toplam": toplam,
            "durum_dagilimi": durumlar
        }
    finally:
        conn.close()