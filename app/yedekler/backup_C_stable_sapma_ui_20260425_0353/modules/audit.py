# -*- coding: utf-8 -*-
"""CPS DEV - Audit log"""
from db import qexec, q
from datetime import datetime


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log(kullanici, islem, tablo, kayit_id,
        anlasma_id=None, alan=None, eski=None, yeni=None, aciklama=None,
        modul=None, alt_modul=None, conn=None):
    sql = """
        INSERT INTO sistem_audit
          (Tarih, KullaniciAdi, Islem, TabloAdi, KayitId, Alan, EskiDeger, YeniDeger,
           AnlasmaId, Aciklama, Modul, AltModul)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """
    params = (_now(), kullanici, islem, tablo, kayit_id, alan,
              str(eski) if eski is not None else None,
              str(yeni) if yeni is not None else None,
              anlasma_id, aciklama, modul, alt_modul)
    if conn is not None:
        conn.cursor().execute(sql, params)
    else:
        qexec(sql, params)


def log_ekle(kullanici, tablo, kayit_id, anlasma_id=None, aciklama=None,
             modul=None, alt_modul=None, conn=None):
    log(kullanici, 'EKLE', tablo, kayit_id,
        anlasma_id=anlasma_id, aciklama=aciklama,
        modul=modul, alt_modul=alt_modul, conn=conn)


def log_sil(kullanici, tablo, kayit_id, anlasma_id=None, aciklama=None,
            modul=None, alt_modul=None, conn=None):
    log(kullanici, 'SIL', tablo, kayit_id,
        anlasma_id=anlasma_id, aciklama=aciklama,
        modul=modul, alt_modul=alt_modul, conn=conn)


def log_duzenle_coklu(kullanici, tablo, kayit_id, eski_dict, yeni_dict,
                      anlasma_id=None, modul=None, alt_modul=None, conn=None):
    degisen = []
    for k in yeni_dict:
        e = eski_dict.get(k)
        y = yeni_dict.get(k)
        if str(e or '') != str(y or ''):
            degisen.append(k)
            log(kullanici, 'DUZENLE', tablo, kayit_id,
                anlasma_id=anlasma_id, alan=k, eski=e, yeni=y,
                aciklama=f"{k}: '{e}' → '{y}'",
                modul=modul, alt_modul=alt_modul, conn=conn)
    return degisen


def log_olay(kullanici, islem, tablo, kayit_id,
             anlasma_id=None, aciklama=None, modul=None, alt_modul=None, conn=None):
    log(kullanici, islem, tablo, kayit_id,
        anlasma_id=anlasma_id, aciklama=aciklama,
        modul=modul, alt_modul=alt_modul, conn=conn)


def anlasma_log(anlasma_id):
    return q("""
        SELECT a.*, k.AdSoyad
        FROM sistem_audit a
        LEFT JOIN sistem_kullanici k ON k.KullaniciAdi = a.KullaniciAdi
        WHERE a.AnlasmaId = ?
        ORDER BY a.Tarih DESC, a.Id DESC
    """, (anlasma_id,))


def son_loglar(limit=50, modul=None, alt_modul=None, kullanici=None,
               islem=None, bas=None, bit=None):
    ks = []
    params = []
    if modul:     ks.append("a.Modul = ?");        params.append(modul)
    if alt_modul: ks.append("a.AltModul = ?");     params.append(alt_modul)
    if kullanici: ks.append("a.KullaniciAdi = ?"); params.append(kullanici)
    if islem:     ks.append("a.Islem = ?");        params.append(islem)
    if bas:       ks.append("a.Tarih >= ?");       params.append(bas + ' 00:00:00')
    if bit:       ks.append("a.Tarih <= ?");       params.append(bit + ' 23:59:59')
    where = ("WHERE " + " AND ".join(ks)) if ks else ""
    params.append(limit)
    return q(f"""
        SELECT a.*, k.AdSoyad, an.ProjeKod, an.ProjeAdi
        FROM sistem_audit a
        LEFT JOIN sistem_kullanici k ON k.KullaniciAdi = a.KullaniciAdi
        LEFT JOIN finans_anlasma an ON an.Id = a.AnlasmaId
        {where}
        ORDER BY a.Tarih DESC, a.Id DESC
        LIMIT ?
    """, tuple(params))


def log_kayit_detay(tablo, kayit_id, limit=100):
    return q("""
        SELECT a.*, k.AdSoyad
        FROM sistem_audit a
        LEFT JOIN sistem_kullanici k ON k.KullaniciAdi = a.KullaniciAdi
        WHERE a.TabloAdi = ? AND a.KayitId = ?
        ORDER BY a.Tarih DESC, a.Id DESC
        LIMIT ?
    """, (tablo, kayit_id, limit))
