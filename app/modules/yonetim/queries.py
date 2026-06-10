# -*- coding: utf-8 -*-
"""CPS DEV - Yönetim Queries (routes.py ile uyumlu)"""
from datetime import date, datetime
from db import q, qone, qscalar, qexec, get_conn
from modules import audit


# ============================================================
# KPI
# ============================================================

def yonetim_kpi():
    """Panel üstü 5 KPI kartı."""
    return {
        'kullanici_toplam':  qscalar("SELECT COUNT(*) FROM sistem_kullanici") or 0,
        'kullanici_aktif':   qscalar("SELECT COUNT(*) FROM sistem_kullanici WHERE Aktif=1") or 0,
        'rol_toplam':        qscalar("SELECT COUNT(*) FROM sistem_rol WHERE Aktif=1") or 0,
        'kur_bugun':         qscalar("SELECT COUNT(*) FROM sistem_kur WHERE Tarih = ?",
                                     (date.today().strftime('%Y-%m-%d'),)) or 0,
        'log_bugun':         qscalar("SELECT COUNT(*) FROM sistem_audit WHERE Tarih LIKE ?",
                                     (date.today().strftime('%Y-%m-%d') + '%',)) or 0,
    }


# ============================================================
# KULLANICI
# ============================================================

def kullanici_liste():
    return q("""
        SELECT u.*, r.Ad AS RolAd, r.Renk AS RolRenk
        FROM sistem_kullanici u
        LEFT JOIN sistem_rol r ON r.Id = u.RolId
        ORDER BY u.Aktif DESC, u.KullaniciAdi
    """)


def kullanici_tek(kullanici_id):
    return qone("""
        SELECT u.*, r.Ad AS RolAd
        FROM sistem_kullanici u
        LEFT JOIN sistem_rol r ON r.Id = u.RolId
        WHERE u.Id = ?
    """, (kullanici_id,))


def kullanici_ekle(veri, kullanici):
    kadi = veri['KullaniciAdi'].strip().lower()
    if not kadi:
        raise ValueError('Kullanıcı adı zorunlu.')
    if qone("SELECT Id FROM sistem_kullanici WHERE KullaniciAdi = ?", (kadi,)):
        raise ValueError(f"Kullanıcı adı zaten var: {kadi}")

    rol_id = int(veri.get('RolId') or 0) or None
    rol_ad = None
    if rol_id:
        rol_ad = qscalar("SELECT Ad FROM sistem_rol WHERE Id = ?", (rol_id,))

    uid = qexec("""
        INSERT INTO sistem_kullanici
          (KullaniciAdi, AdSoyad, Email, Sifre, RolId, Rol,
           Aktif, ZorunluSifreDegistir, OlusturmaTarih, OlusturanKullanici)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (kadi, veri.get('AdSoyad'), veri.get('Email'), veri.get('Sifre') or '1234',
          rol_id, rol_ad,
          1 if veri.get('Aktif', 1) else 0,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          kullanici))

    # P1A: Atomik kullanici_profil oluştur (Personel 360 merkezi)
    # sistem_kullanici → kullanici_profil köprüsü: kaynak='sistem_kullanici', kaynak_id=uid
    # Mevcut profil varsa INSERT OR IGNORE ile dokunma.
    try:
        qexec("""
            INSERT OR IGNORE INTO kullanici_profil
              (gercek_ad, kullanici_adi, profil_tipi, aktif, kaynak, kaynak_id)
            VALUES (?, ?, 'sistem', ?, 'sistem_kullanici', ?)
        """, (
            veri.get('AdSoyad') or kadi,
            kadi,
            1 if veri.get('Aktif', 1) else 0,
            uid,
        ))
    except Exception:
        pass  # Profil oluşturulamazsa kullanici_ekle yine de basarili sayilir

    audit.log_ekle(kullanici, 'sistem_kullanici', uid,
                   aciklama=f"Kullanıcı eklendi: {kadi} ({veri.get('AdSoyad') or '-'})",
                   modul='yonetim', alt_modul='kullanici')
    return uid


def kullanici_guncelle(kullanici_id, veri, kullanici):
    eski = kullanici_tek(kullanici_id)
    if not eski:
        raise ValueError('Kullanıcı bulunamadı.')

    rol_id = int(veri.get('RolId') or 0) or None
    rol_ad = qscalar("SELECT Ad FROM sistem_rol WHERE Id = ?", (rol_id,)) if rol_id else None
    yeni = {
        'AdSoyad': veri.get('AdSoyad'),
        'Email':   veri.get('Email'),
        'RolId':   rol_id,
        'Rol':     rol_ad,
        'Aktif':   1 if veri.get('Aktif') else 0,
    }
    qexec("""
        UPDATE sistem_kullanici
           SET AdSoyad=?, Email=?, RolId=?, Rol=?, Aktif=?
         WHERE Id=?
    """, (yeni['AdSoyad'], yeni['Email'], yeni['RolId'], yeni['Rol'], yeni['Aktif'],
          kullanici_id))

    audit.log_duzenle_coklu(kullanici, 'sistem_kullanici', kullanici_id,
                            dict(eski), yeni,
                            modul='yonetim', alt_modul='kullanici')


def kullanici_sifre_sifirla(kullanici_id, yeni_sifre, kullanici, zorunlu_degistir=True):
    qexec("""
        UPDATE sistem_kullanici SET Sifre=?, ZorunluSifreDegistir=? WHERE Id=?
    """, (yeni_sifre, 1 if zorunlu_degistir else 0, kullanici_id))
    audit.log_olay(kullanici, 'SIFRE_SIFIRLA', 'sistem_kullanici', kullanici_id,
                   aciklama="Şifre sıfırlandı",
                   modul='yonetim', alt_modul='kullanici')


def kullanici_pasif(kullanici_id, kullanici, aktif=False):
    qexec("UPDATE sistem_kullanici SET Aktif=? WHERE Id=?",
          (1 if aktif else 0, kullanici_id))
    audit.log_olay(kullanici,
                   'AKTIF' if aktif else 'PASIF',
                   'sistem_kullanici', kullanici_id,
                   aciklama=f"Kullanıcı {'aktif' if aktif else 'pasif'} edildi",
                   modul='yonetim', alt_modul='kullanici')


# ============================================================
# ROL
# ============================================================

def rol_liste():
    return q("""
        SELECT r.*,
               (SELECT COUNT(*) FROM sistem_kullanici u WHERE u.RolId = r.Id AND u.Aktif=1) AS KullaniciSayi
        FROM sistem_rol r
        WHERE r.Aktif = 1
        ORDER BY r.SuperAdmin DESC, r.Ad
    """)


def rol_tek(rol_id):
    return qone("SELECT * FROM sistem_rol WHERE Id = ?", (rol_id,))


def rol_ekle(ad, aciklama, kullanici):
    ad = (ad or '').strip()
    if not ad:
        raise ValueError('Rol adı zorunlu.')
    if qone("SELECT Id FROM sistem_rol WHERE Ad = ?", (ad,)):
        raise ValueError(f"Rol zaten var: {ad}")
    rid = qexec("""
        INSERT INTO sistem_rol (Ad, Aciklama, Renk, Aktif, SuperAdmin, OlusturmaTarih, OlusturanKullanici)
        VALUES (?, ?, ?, 1, 0, ?, ?)
    """, (ad, aciklama, '#64748b',
          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          kullanici))
    audit.log_ekle(kullanici, 'sistem_rol', rid,
                   aciklama=f"Rol eklendi: {ad}",
                   modul='yonetim', alt_modul='rol')
    return rid


def rol_guncelle(rol_id, ad, aciklama, kullanici):
    eski = rol_tek(rol_id)
    if not eski:
        raise ValueError('Rol bulunamadı.')
    if eski['SuperAdmin']:
        ad = eski['Ad']  # koru
    yeni = {'Ad': ad, 'Aciklama': aciklama}
    qexec("UPDATE sistem_rol SET Ad=?, Aciklama=? WHERE Id=?",
          (ad, aciklama, rol_id))
    audit.log_duzenle_coklu(kullanici, 'sistem_rol', rol_id, dict(eski), yeni,
                            modul='yonetim', alt_modul='rol')


def rol_sil(rol_id, kullanici):
    r = rol_tek(rol_id)
    if not r:
        return False
    if r['SuperAdmin']:
        raise ValueError("SuperAdmin rolü silinemez.")
    kul_sayi = qscalar("SELECT COUNT(*) FROM sistem_kullanici WHERE RolId=? AND Aktif=1", (rol_id,)) or 0
    if kul_sayi > 0:
        raise ValueError(f"Bu role bağlı {kul_sayi} aktif kullanıcı var. Önce onları taşıyın.")
    qexec("UPDATE sistem_rol SET Aktif=0 WHERE Id=?", (rol_id,))
    audit.log_sil(kullanici, 'sistem_rol', rol_id,
                  aciklama=f"Rol silindi: {r['Ad']}",
                  modul='yonetim', alt_modul='rol')
    return True


def rol_yetkileri(rol_id):
    """V2: Dict: {yetki_id: {'Gorebilir', 'Duzenleyebilir', 'can_view', ...}}"""
    rows = q("""
        SELECT YetkiId, Gorebilir, Duzenleyebilir,
               can_view, can_create, can_update, can_delete,
               can_approve, can_report, can_manage
        FROM sistem_rol_yetki
        WHERE RolId = ?
    """, (rol_id,))
    return {r['YetkiId']: {'Gorebilir': r['Gorebilir'],
                          'Duzenleyebilir': r['Duzenleyebilir'],
                          'can_view': r['can_view'],
                          'can_create': r['can_create'],
                          'can_update': r['can_update'],
                          'can_delete': r['can_delete'],
                          'can_approve': r['can_approve'],
                          'can_report': r['can_report'],
                          'can_manage': r['can_manage']}
            for r in rows}


def rol_yetki_kaydet(rol_id, yetki_map, kullanici):
    """
    F2X: V2 boyutlu yetki kaydet (11 kolon — Migration 006 uyumlu).

    yetki_map: {yetki_id: {
        'gor': bool,           # eski (geriye uyum — Gorebilir)
        'duz': bool,           # eski (geriye uyum — Duzenleyebilir)
        'can_view': bool,      # V2 (Migration 006)
        'can_create': bool,
        'can_update': bool,
        'can_delete': bool,
        'can_approve': bool,
        'can_report': bool,
        'can_manage': bool,
    }, ...}
    """
    r = rol_tek(rol_id)
    if not r:
        raise ValueError('Rol bulunamadı.')

    eski = rol_yetkileri(rol_id)

    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("BEGIN")
            cur.execute("DELETE FROM sistem_rol_yetki WHERE RolId = ?", (rol_id,))
            degisen = 0
            for yid, sec in yetki_map.items():
                # Eski boyutlar (geriye uyum)
                g  = 1 if sec.get('gor')        else 0
                d  = 1 if sec.get('duz')        else 0
                # V2 boyutlar (Migration 006)
                v  = 1 if sec.get('can_view')    else 0
                c  = 1 if sec.get('can_create')  else 0
                u  = 1 if sec.get('can_update')  else 0
                de = 1 if sec.get('can_delete')  else 0
                ap = 1 if sec.get('can_approve') else 0
                rp = 1 if sec.get('can_report')  else 0
                mg = 1 if sec.get('can_manage')  else 0

                # Herhangi bir izin verilmis mi? (11 boyut hepsi)
                if g or d or v or c or u or de or ap or rp or mg:
                    cur.execute("""
                        INSERT INTO sistem_rol_yetki (
                            RolId, YetkiId, Gorebilir, Duzenleyebilir,
                            can_view, can_create, can_update, can_delete,
                            can_approve, can_report, can_manage
                        )
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """, (rol_id, yid, g, d, v, c, u, de, ap, rp, mg))

                # Degisiklik sayaci (audit log icin) — 9 boyut karsilastir
                ek = eski.get(yid, {})
                if (ek.get('Gorebilir', 0)      != g  or
                    ek.get('Duzenleyebilir', 0) != d  or
                    ek.get('can_view', 0)       != v  or
                    ek.get('can_create', 0)     != c  or
                    ek.get('can_update', 0)     != u  or
                    ek.get('can_delete', 0)     != de or
                    ek.get('can_approve', 0)    != ap or
                    ek.get('can_report', 0)     != rp or
                    ek.get('can_manage', 0)     != mg):
                    degisen += 1
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    audit.log_olay(kullanici, 'YETKI_GUNCELLE', 'sistem_rol_yetki', rol_id,
                   aciklama=f"'{r['Ad']}' rolünün yetkileri güncellendi ({degisen} değişiklik)",
                   modul='yonetim', alt_modul='rol')


# ============================================================
# YETKİ (sabit liste)
# ============================================================

def yetki_liste():
    return q("SELECT * FROM sistem_yetki ORDER BY Sira, Modul, AltModul")


def yetki_secimlik_liste():
    """Kullanıcı formu için rol seçim listesi."""
    return q("""
        SELECT Id, Ad, Renk FROM sistem_rol
        WHERE Aktif = 1
        ORDER BY SuperAdmin DESC, Ad
    """)


# ============================================================
# KUR
# ============================================================

def kur_liste(limit=120):
    return q("SELECT * FROM sistem_kur ORDER BY Tarih DESC, ParaBirimi LIMIT ?", (limit,))


def kur_guncel(para_birimi='USD'):
    """En son girilen kur — dashboard için."""
    return qone("""
        SELECT * FROM sistem_kur WHERE ParaBirimi = ?
        ORDER BY Tarih DESC, Id DESC LIMIT 1
    """, (para_birimi,))


def kur_tarihli(tarih, para_birimi):
    return qone("SELECT * FROM sistem_kur WHERE Tarih = ? AND ParaBirimi = ?",
                (tarih, para_birimi))


def get_kur_by_date(para_birimi, tarih):
    """
    Parça 8a: İşlem tarihine göre kur döndürür, fallback zinciri ile.

    Returns: (kur_deger, kaynak_tipi, kur_tarih) veya (None, 'BULUNAMADI', None)
      kaynak_tipi: 'TRY_NATIVE' | 'TAM_ESLESIR' | 'ONCEKI_YAKIN' | 'BULUNAMADI'
    """
    if para_birimi == 'TRY':
        return (1.0, 'TRY_NATIVE', tarih)

    # 1. Tam eşleşme
    row = qone("""SELECT MerkezKur, Tarih FROM sistem_kur
                  WHERE ParaBirimi = ? AND Tarih = ? ORDER BY Id DESC LIMIT 1""",
               (para_birimi, tarih))
    if row:
        return (row['MerkezKur'], 'TAM_ESLESIR', row['Tarih'])

    # 2. En yakın önceki tarih
    row = qone("""SELECT MerkezKur, Tarih FROM sistem_kur
                  WHERE ParaBirimi = ? AND Tarih < ?
                  ORDER BY Tarih DESC, Id DESC LIMIT 1""",
               (para_birimi, tarih))
    if row:
        return (row['MerkezKur'], 'ONCEKI_YAKIN', row['Tarih'])

    return (None, 'BULUNAMADI', None)


def kur_ekle(tarih, para_birimi, alis, satis, kullanici, kaynak='MANUEL'):
    """Basit ekle — aynı gün+PB varsa güncelle."""
    merkez = round((alis + satis) / 2, 4)
    eski = kur_tarihli(tarih, para_birimi)
    if eski:
        qexec("""
            UPDATE sistem_kur SET Alis=?, Satis=?, MerkezKur=?, Kaynak=? WHERE Id=?
        """, (alis, satis, merkez, kaynak, eski['Id']))
        audit.log_duzenle_coklu(kullanici, 'sistem_kur', eski['Id'],
                                dict(eski),
                                {'Alis': alis, 'Satis': satis, 'MerkezKur': merkez},
                                modul='yonetim', alt_modul='kur')
        return eski['Id']
    else:
        kid = qexec("""
            INSERT INTO sistem_kur
              (Tarih, ParaBirimi, Alis, Satis, MerkezKur, Kaynak, OlusturmaTarih, OlusturanKullanici)
            VALUES (?,?,?,?,?,?,?,?)
        """, (tarih, para_birimi, alis, satis, merkez, kaynak,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              kullanici))
        audit.log_ekle(kullanici, 'sistem_kur', kid,
                       aciklama=f"Kur: {para_birimi} {tarih} → {merkez:.4f}",
                       modul='yonetim', alt_modul='kur')
        return kid


def kur_sil(kur_id, kullanici):
    k = qone("SELECT * FROM sistem_kur WHERE Id=?", (kur_id,))
    if not k:
        return False
    qexec("DELETE FROM sistem_kur WHERE Id=?", (kur_id,))
    audit.log_sil(kullanici, 'sistem_kur', kur_id,
                  aciklama=f"Kur silindi: {k['ParaBirimi']} {k['Tarih']}",
                  modul='yonetim', alt_modul='kur')
    return True


def kur_bugun():
    bugun = date.today().strftime('%Y-%m-%d')
    return q("SELECT * FROM sistem_kur WHERE Tarih = ? ORDER BY ParaBirimi", (bugun,))


def rol_metrik(rol_id):
    """V2: Rol icin ozet metrik (D4.6.1 - 16.05.2026)

    Donus:
        {
            'kullanici_sayi': int  (aktif kullanici sayisi),
            'aktif_yetki':    int  (en az 1 action acik yetki sayisi),
            'riskli_yetki':   int  (can_delete veya can_manage acik),
            'modul_erisim':   int  (DISTINCT modul sayisi),
        }
    """
    r = qone("SELECT COUNT(*) c FROM sistem_kullanici WHERE RolId = ? AND Aktif = 1", (rol_id,))
    kullanici_sayi = r['c'] if r else 0

    r = qone("""
        SELECT COUNT(*) c FROM sistem_rol_yetki
        WHERE RolId = ?
          AND (can_view OR can_create OR can_update
            OR can_delete OR can_approve OR can_report OR can_manage)
    """, (rol_id,))
    aktif_yetki = r['c'] if r else 0

    r = qone("""
        SELECT COUNT(*) c FROM sistem_rol_yetki
        WHERE RolId = ? AND (can_delete OR can_manage)
    """, (rol_id,))
    riskli_yetki = r['c'] if r else 0

    r = qone("""
        SELECT COUNT(DISTINCT y.Modul) c
        FROM sistem_rol_yetki ry
        JOIN sistem_yetki y ON y.Id = ry.YetkiId
        WHERE ry.RolId = ?
    """, (rol_id,))
    modul_erisim = r['c'] if r else 0

    return {
        'kullanici_sayi': kullanici_sayi,
        'aktif_yetki':    aktif_yetki,
        'riskli_yetki':   riskli_yetki,
        'modul_erisim':   modul_erisim,
    }
