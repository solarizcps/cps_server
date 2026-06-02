# -*- coding: utf-8 -*-
"""CPS DEV - Enjeksiyon DB CRUD katmani (FAZ 2 iskelet)

F2'de sadece okuma fonksiyonlari. F6'da rapor CRUD eklenecek.
Tum sorgular enj_ prefix'li tablolara erisir.
"""
from db import q, qexec


# ============== OKUMA (F2) ==============

def makine_listele():
    """Aktif makineler, sira'ya gore."""
    return q("""
        SELECT id, kod, ad, istasyon_sayisi, sira
        FROM enj_makine
        WHERE aktif = 1
        ORDER BY sira
    """)


def makine_getir(makine_id):
    """Tek makine."""
    sonuc = q("SELECT * FROM enj_makine WHERE id = ? AND aktif = 1", (makine_id,))
    return sonuc[0] if sonuc else None


def aksama_sebep_listele():
    """Aktif aksama sebepleri, sira'ya gore."""
    return q("""
        SELECT id, kod, ad, kategori
        FROM enj_aksama_sebep
        WHERE aktif = 1
        ORDER BY sira
    """)


def kalip_listele():
    """Aktif kaliplar (Excel import sonrasi dolacak, simdilik bos olabilir)."""
    return q("""
        SELECT id, kalip_kodu, model, kalip_tipi, kalip_basi_cift,
               bagli_kalip_varsayilan, gorsel_yolu
        FROM enj_kalip
        WHERE aktif = 1
        ORDER BY kalip_kodu
    """)


# ============== F6'DA EKLENECEK ==============
# rapor_olustur(tarih, makine_id, vardiya, kullanici_id) -> rapor_id
# rapor_getir(rapor_id) -> dict (rapor + saatlik kayitlar + istasyon durumu)
# rapor_listele(tarih=None, makine_id=None, durum=None) -> list
# saatlik_kayit_yaz(rapor_id, saat_baslangic, tur_adet, durum, ...)
# istasyon_durumu_yaz(rapor_id, istasyon_no, aktif)
# gun_sonu_kaydet(rapor_id, toplam_fire_cift, fire_kg, fire_gr, notu)
# foto_ekle(rapor_id, tip, dosya_yolu)
# rapor_kapat(rapor_id) -> net_cikan + fark hesapla

# === BEGIN: ENJ_F8_1A_RAPOR ===
# F8.1-A - Rapor state yukleme
# Anahtar: (tarih, vardiya, makine_id)
# Atomik: tek connection, rapor + saatlik + istasyon birlikte
import sqlite3 as _sq_f81a
from db import get_conn as _gc_f81a

_VAR_SAAT_F81A = {
    "gunduz": [("07:00", "08:00"), ("08:00", "09:00"), ("09:00", "10:00"),
               ("10:00", "11:00"), ("11:00", "12:00"), ("12:00", "13:00"),
               ("13:00", "14:00"), ("14:00", "15:00"), ("15:00", "16:00"),
               ("16:00", "17:00")],
    "gece":   [("17:00", "18:00"), ("18:00", "19:00"), ("19:00", "20:00"),
               ("20:00", "21:00"), ("21:00", "22:00"), ("22:00", "23:00"),
               ("23:00", "00:00"), ("00:00", "01:00"), ("01:00", "02:00"),
               ("02:00", "03:00"), ("03:00", "04:00"), ("04:00", "05:00"),
               ("05:00", "06:00"), ("06:00", "07:00")],
    "mesai":  [],
}


def _saat_sirala_f81a(items, vardiya):
    if vardiya != "gece":
        return sorted(items, key=lambda r: r.get("saat_baslangic", ""))
    def k(r):
        s = r.get("saat_baslangic", "")
        h = int(s.split(":")[0]) if s else 0
        return (0 if h >= 17 else 1, s)
    return sorted(items, key=k)


def rapor_bul_veya_olustur(tarih, vardiya, makine_id, kullanici_id=None, kullanici_adi="bilinmeyen"):
    """(tarih, vardiya, makine_id) ile rapor bul; yoksa olustur."""
    if vardiya not in ("gunduz", "gece", "mesai"):
        return None
    try:
        makine_id = int(makine_id)
    except (TypeError, ValueError):
        return None

    con = _gc_f81a()
    try:
        cur = con.cursor()

        cur.execute("SELECT id, istasyon_sayisi FROM enj_makine WHERE id = ? AND aktif = 1", (makine_id,))
        mk = cur.fetchone()
        if not mk:
            return None
        ist_sayisi = mk["istasyon_sayisi"] if isinstance(mk, _sq_f81a.Row) else mk[1]

        cur.execute(
            "SELECT id FROM enj_gunluk_rapor WHERE tarih = ? AND vardiya = ? AND makine_id = ?",
            (tarih, vardiya, makine_id)
        )
        row = cur.fetchone()
        olusturuldu = False

        if row:
            rapor_id = row["id"] if isinstance(row, _sq_f81a.Row) else row[0]
        else:
            try:
                cur.execute(
                    "INSERT INTO enj_gunluk_rapor "
                    "(tarih, vardiya, makine_id, kullanici_id, kullanici_adi, durum, olusturma_tarih, son_guncelleme) "
                    "VALUES (?, ?, ?, ?, ?, 'taslak', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (tarih, vardiya, makine_id, kullanici_id, kullanici_adi)
                )
                rapor_id = cur.lastrowid

                for bas, bit in _VAR_SAAT_F81A.get(vardiya, []):
                    cur.execute(
                        "INSERT INTO enj_saatlik_kayit "
                        "(rapor_id, saat_baslangic, saat_bitis, tur_adet, durum, olusturma_tarih, son_guncelleme) "
                        "VALUES (?, ?, ?, 0, 'calisiyor', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                        (rapor_id, bas, bit)
                    )
                for no in range(1, ist_sayisi + 1):
                    for slot in ("A", "B"):
                        cur.execute(
                            "INSERT INTO enj_istasyon_durumu "
                            "(rapor_id, istasyon_no, slot, aktif) VALUES (?, ?, ?, 0)",
                            (rapor_id, no, slot)
                        )
                con.commit()
                olusturuldu = True
            except _sq_f81a.IntegrityError:
                con.rollback()
                cur.execute(
                    "SELECT id FROM enj_gunluk_rapor WHERE tarih = ? AND vardiya = ? AND makine_id = ?",
                    (tarih, vardiya, makine_id)
                )
                row = cur.fetchone()
                if not row:
                    return None
                rapor_id = row["id"] if isinstance(row, _sq_f81a.Row) else row[0]

        # Payload
        cur.execute("SELECT * FROM enj_gunluk_rapor WHERE id = ?", (rapor_id,))
        r = cur.fetchone()
        rapor = dict(r) if isinstance(r, _sq_f81a.Row) else dict(zip([d[0] for d in cur.description], r))

        cur.execute("SELECT * FROM enj_saatlik_kayit WHERE rapor_id = ?", (rapor_id,))
        rows = cur.fetchall()
        saatlik = [dict(x) if isinstance(x, _sq_f81a.Row) else dict(zip([d[0] for d in cur.description], x)) for x in rows]
        saatlik = _saat_sirala_f81a(saatlik, vardiya)

        cur.execute(
            "SELECT * FROM enj_istasyon_durumu WHERE rapor_id = ? ORDER BY istasyon_no, slot",
            (rapor_id,)
        )
        rows = cur.fetchall()
        istasyonlar = [dict(x) if isinstance(x, _sq_f81a.Row) else dict(zip([d[0] for d in cur.description], x)) for x in rows]

        return {
            "rapor": rapor,
            "saatlik": saatlik,
            "istasyonlar": istasyonlar,
            "olusturuldu": olusturuldu,
        }
    finally:
        try: con.close()
        except Exception: pass
# === END: ENJ_F8_1A_RAPOR ===
