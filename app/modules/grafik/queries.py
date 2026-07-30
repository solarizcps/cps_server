# -*- coding: utf-8 -*-
"""CPS DEV - Grafik Queries (Faz 2a: ürün + varyant + tedarikçi)"""
from datetime import datetime
from db import q, qone, qscalar, qexec, get_conn
from modules import audit


# ============================================================
# KPI
# ============================================================

def grafik_kpi():
    return {
        'kategori_sayi':   qscalar("SELECT COUNT(*) FROM grafik_urun_kategori WHERE Aktif=1") or 0,
        'urun_sayi':       qscalar("SELECT COUNT(*) FROM grafik_urun WHERE Aktif=1") or 0,
        'varyant_sayi':    qscalar("SELECT COUNT(*) FROM grafik_urun_varyant WHERE Aktif=1") or 0,
        'tedarikci_sayi':  qscalar("SELECT COUNT(*) FROM grafik_tedarikci WHERE Aktif=1") or 0,
        'numune_acik':     qscalar("""SELECT COUNT(*) FROM grafik_numune
                                      WHERE Durum IN ('TALEP','GONDERILDI','RED')""") or 0,
        'numune_toplam':   qscalar("SELECT COUNT(*) FROM grafik_numune") or 0,
        # Faz 2b placeholder
        'siparis_acik':    0,
        'sevkiyat_yolda':  0,
    }


# ============================================================
# KATEGORİ
# ============================================================

def kategori_liste():
    return q("""
        SELECT k.*,
               (SELECT COUNT(*) FROM grafik_urun u WHERE u.KategoriId = k.Id AND u.Aktif=1) AS UrunSayi
        FROM grafik_urun_kategori k
        WHERE k.Aktif = 1
        ORDER BY k.Sira, k.Ad
    """)


def kategori_tek(kat_id):
    return qone("SELECT * FROM grafik_urun_kategori WHERE Id = ?", (kat_id,))


def kategori_ekle(ad, aciklama, sira, kullanici):
    ad = (ad or '').strip()
    if not ad:
        raise ValueError('Kategori adı zorunlu.')
    if qone("SELECT Id FROM grafik_urun_kategori WHERE Ad = ?", (ad,)):
        raise ValueError(f"Kategori zaten var: {ad}")
    kid = qexec("""INSERT INTO grafik_urun_kategori (Ad, Aciklama, Sira, Aktif, OlusturmaTarih)
                   VALUES (?, ?, ?, 1, ?)""",
                (ad, aciklama, int(sira or 0), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    audit.log_ekle(kullanici, 'grafik_urun_kategori', kid,
                   aciklama=f"Kategori eklendi: {ad}",
                   modul='grafik', alt_modul='urun')
    return kid


def kategori_guncelle(kat_id, ad, aciklama, sira, kullanici):
    eski = kategori_tek(kat_id)
    if not eski:
        raise ValueError('Kategori bulunamadı.')
    yeni = {'Ad': ad, 'Aciklama': aciklama, 'Sira': int(sira or 0)}
    qexec("UPDATE grafik_urun_kategori SET Ad=?, Aciklama=?, Sira=? WHERE Id=?",
          (yeni['Ad'], yeni['Aciklama'], yeni['Sira'], kat_id))
    audit.log_duzenle_coklu(kullanici, 'grafik_urun_kategori', kat_id,
                            dict(eski), yeni, modul='grafik', alt_modul='urun')


def kategori_sil(kat_id, kullanici):
    k = kategori_tek(kat_id)
    if not k:
        return False
    urun_sayi = qscalar("SELECT COUNT(*) FROM grafik_urun WHERE KategoriId=? AND Aktif=1", (kat_id,)) or 0
    if urun_sayi > 0:
        raise ValueError(f"Bu kategoride {urun_sayi} ürün var. Önce onları taşıyın/silin.")
    qexec("UPDATE grafik_urun_kategori SET Aktif=0 WHERE Id=?", (kat_id,))
    audit.log_sil(kullanici, 'grafik_urun_kategori', kat_id,
                  aciklama=f"Kategori silindi: {k['Ad']}",
                  modul='grafik', alt_modul='urun')
    return True


# ============================================================
# ÜRÜN
# ============================================================

def urun_liste(arama=None, kategori_id=None):
    ks = ["u.Aktif = 1"]
    params = []
    if arama:
        ks.append("(u.Kod LIKE ? OR u.Ad LIKE ?)")
        params.extend([f'%{arama}%', f'%{arama}%'])
    if kategori_id:
        ks.append("u.KategoriId = ?")
        params.append(int(kategori_id))
    where = " AND ".join(ks)
    return q(f"""
        SELECT u.*, k.Ad AS KategoriAd,
               (SELECT COUNT(*) FROM grafik_urun_varyant v WHERE v.UrunId = u.Id AND v.Aktif = 1) AS VaryantSayi
        FROM grafik_urun u
        LEFT JOIN grafik_urun_kategori k ON k.Id = u.KategoriId
        WHERE {where}
        ORDER BY k.Sira, u.Ad
    """, tuple(params))


def urun_tek(urun_id):
    return qone("""
        SELECT u.*, k.Ad AS KategoriAd
        FROM grafik_urun u
        LEFT JOIN grafik_urun_kategori k ON k.Id = u.KategoriId
        WHERE u.Id = ?
    """, (urun_id,))


def urun_ekle(kod, ad, kategori_id, aciklama, kullanici):
    kod = (kod or '').strip().upper()
    ad = (ad or '').strip()
    if not kod or not ad:
        raise ValueError('Kod ve ad zorunlu.')
    if qone("SELECT Id FROM grafik_urun WHERE Kod = ?", (kod,)):
        raise ValueError(f"Kod zaten var: {kod}")
    uid = qexec("""INSERT INTO grafik_urun
                   (Kod, Ad, KategoriId, Aciklama, Aktif, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (kod, ad, int(kategori_id) if kategori_id else None, aciklama,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S'), kullanici))
    audit.log_ekle(kullanici, 'grafik_urun', uid,
                   aciklama=f"Ürün eklendi: {kod} - {ad}",
                   modul='grafik', alt_modul='urun')
    return uid


def urun_guncelle(urun_id, kod, ad, kategori_id, aciklama, kullanici):
    eski = urun_tek(urun_id)
    if not eski:
        raise ValueError('Ürün bulunamadı.')
    kod = (kod or '').strip().upper()
    if kod != eski['Kod']:
        if qone("SELECT Id FROM grafik_urun WHERE Kod = ? AND Id != ?", (kod, urun_id)):
            raise ValueError(f"Kod zaten var: {kod}")
    yeni = {'Kod': kod, 'Ad': ad,
            'KategoriId': int(kategori_id) if kategori_id else None,
            'Aciklama': aciklama}
    qexec("UPDATE grafik_urun SET Kod=?, Ad=?, KategoriId=?, Aciklama=? WHERE Id=?",
          (yeni['Kod'], yeni['Ad'], yeni['KategoriId'], yeni['Aciklama'], urun_id))
    audit.log_duzenle_coklu(kullanici, 'grafik_urun', urun_id,
                            dict(eski), yeni, modul='grafik', alt_modul='urun')


def urun_sil(urun_id, kullanici):
    u = urun_tek(urun_id)
    if not u:
        return False
    qexec("UPDATE grafik_urun SET Aktif=0 WHERE Id=?", (urun_id,))
    qexec("UPDATE grafik_urun_varyant SET Aktif=0 WHERE UrunId=?", (urun_id,))
    audit.log_sil(kullanici, 'grafik_urun', urun_id,
                  aciklama=f"Ürün silindi (varyantlar dahil): {u['Kod']} - {u['Ad']}",
                  modul='grafik', alt_modul='urun')
    return True


# ============================================================
# VARYANT
# ============================================================

def varyant_liste(urun_id):
    return q("""
        SELECT * FROM grafik_urun_varyant
        WHERE UrunId = ? AND Aktif = 1
        ORDER BY RenkAd, Beden
    """, (urun_id,))


def varyant_tek(varyant_id):
    return qone("SELECT * FROM grafik_urun_varyant WHERE Id = ?", (varyant_id,))


def varyant_ekle(urun_id, kod, renk_ad, renk_hex, beden, stok_kod, kullanici):
    urun = urun_tek(urun_id)
    if not urun:
        raise ValueError('Ürün bulunamadı.')
    if qone("""SELECT Id FROM grafik_urun_varyant
               WHERE UrunId=? AND RenkAd=? AND (Beden=? OR (Beden IS NULL AND ? IS NULL))""",
            (urun_id, renk_ad, beden, beden)):
        raise ValueError(f"Bu varyant zaten var: {renk_ad} {beden or ''}")
    vid = qexec("""INSERT INTO grafik_urun_varyant
                   (UrunId, Kod, RenkAd, RenkHex, Beden, StokKod, Aktif, OlusturmaTarih)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (urun_id, kod, renk_ad, renk_hex, beden, stok_kod,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    audit.log_ekle(kullanici, 'grafik_urun_varyant', vid,
                   aciklama=f"Varyant eklendi: {urun['Kod']} — {renk_ad} {beden or ''}",
                   modul='grafik', alt_modul='urun')
    return vid


def varyant_sil(varyant_id, kullanici):
    v = varyant_tek(varyant_id)
    if not v:
        return False
    qexec("UPDATE grafik_urun_varyant SET Aktif=0 WHERE Id=?", (varyant_id,))
    audit.log_sil(kullanici, 'grafik_urun_varyant', varyant_id,
                  aciklama=f"Varyant silindi: {v['RenkAd']} {v['Beden'] or ''}",
                  modul='grafik', alt_modul='urun')
    return True


# ============================================================
# TEDARİKÇİ
# ============================================================

def tedarikci_liste(arama=None, ulke=None):
    ks = ["Aktif = 1"]
    params = []
    if arama:
        ks.append("(Kod LIKE ? OR Ad LIKE ? OR Sehir LIKE ?)")
        params.extend([f'%{arama}%', f'%{arama}%', f'%{arama}%'])
    if ulke:
        ks.append("Ulke = ?")
        params.append(ulke)
    where = " AND ".join(ks)
    return q(f"""
        SELECT * FROM grafik_tedarikci
        WHERE {where}
        ORDER BY Ulke, Ad
    """, tuple(params))


def tedarikci_tek(ted_id):
    return qone("SELECT * FROM grafik_tedarikci WHERE Id = ?", (ted_id,))


def tedarikci_ekle(veri, kullanici):
    kod = (veri.get('Kod') or '').strip().upper()
    ad = (veri.get('Ad') or '').strip()
    if not kod or not ad:
        raise ValueError('Kod ve ad zorunlu.')
    if qone("SELECT Id FROM grafik_tedarikci WHERE Kod = ?", (kod,)):
        raise ValueError(f"Kod zaten var: {kod}")
    tid = qexec("""INSERT INTO grafik_tedarikci
                   (Kod, Ad, Sehir, Ulke, Iletisim, Email, WhatsApp, WeChat,
                    NakliyeTipi, VadeGun, Notlar, Aktif, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (kod, ad,
                 veri.get('Sehir'), veri.get('Ulke') or 'Çin',
                 veri.get('Iletisim'), veri.get('Email'),
                 veri.get('WhatsApp'), veri.get('WeChat'),
                 veri.get('NakliyeTipi') or 'FOB',
                 int(veri.get('VadeGun') or 0),
                 veri.get('Notlar'),
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S'), kullanici))
    audit.log_ekle(kullanici, 'grafik_tedarikci', tid,
                   aciklama=f"Tedarikçi eklendi: {kod} - {ad}",
                   modul='grafik', alt_modul='tedarikci')
    return tid


def tedarikci_guncelle(ted_id, veri, kullanici):
    eski = tedarikci_tek(ted_id)
    if not eski:
        raise ValueError('Tedarikçi bulunamadı.')
    yeni = {
        'Ad': veri.get('Ad'),
        'Sehir': veri.get('Sehir'),
        'Ulke': veri.get('Ulke') or 'Çin',
        'Iletisim': veri.get('Iletisim'),
        'Email': veri.get('Email'),
        'WhatsApp': veri.get('WhatsApp'),
        'WeChat': veri.get('WeChat'),
        'NakliyeTipi': veri.get('NakliyeTipi') or 'FOB',
        'VadeGun': int(veri.get('VadeGun') or 0),
        'Notlar': veri.get('Notlar'),
    }
    qexec("""UPDATE grafik_tedarikci
             SET Ad=?, Sehir=?, Ulke=?, Iletisim=?, Email=?, WhatsApp=?,
                 WeChat=?, NakliyeTipi=?, VadeGun=?, Notlar=?
             WHERE Id=?""",
          (yeni['Ad'], yeni['Sehir'], yeni['Ulke'], yeni['Iletisim'],
           yeni['Email'], yeni['WhatsApp'], yeni['WeChat'],
           yeni['NakliyeTipi'], yeni['VadeGun'], yeni['Notlar'], ted_id))
    audit.log_duzenle_coklu(kullanici, 'grafik_tedarikci', ted_id,
                            dict(eski), yeni,
                            modul='grafik', alt_modul='tedarikci')


def tedarikci_sil(ted_id, kullanici):
    t = tedarikci_tek(ted_id)
    if not t:
        return False
    qexec("UPDATE grafik_tedarikci SET Aktif=0 WHERE Id=?", (ted_id,))
    audit.log_sil(kullanici, 'grafik_tedarikci', ted_id,
                  aciklama=f"Tedarikçi silindi: {t['Kod']} - {t['Ad']}",
                  modul='grafik', alt_modul='tedarikci')
    return True


# ============================================================
# NUMUNE (Faz 2b)
# ============================================================

def _sonraki_numune_no():
    """NUM-YYYY-NNNN formatında otomatik numara üretir."""
    from datetime import date
    yil = date.today().year
    mask = f"NUM-{yil}-%"
    son = qscalar("""
        SELECT MAX(CAST(SUBSTR(NumuneNo, 10) AS INTEGER))
        FROM grafik_numune WHERE NumuneNo LIKE ?
    """, (mask,)) or 0
    return f"NUM-{yil}-{son+1:04d}"


def numune_kpi():
    return {
        'talep':       qscalar("SELECT COUNT(*) FROM grafik_numune WHERE Durum='TALEP'") or 0,
        'gonderildi':  qscalar("SELECT COUNT(*) FROM grafik_numune WHERE Durum='GONDERILDI'") or 0,
        'onay':        qscalar("SELECT COUNT(*) FROM grafik_numune WHERE Durum='ONAY'") or 0,
        'red':         qscalar("SELECT COUNT(*) FROM grafik_numune WHERE Durum='RED'") or 0,
        'tamamlandi':  qscalar("SELECT COUNT(*) FROM grafik_numune WHERE Durum='TAMAMLANDI'") or 0,
        'toplam':      qscalar("SELECT COUNT(*) FROM grafik_numune") or 0,
    }


NUMUNE_DURUMLARI = [
    ('TALEP',        'Talep Açıldı',       '#6b7280'),
    ('GONDERILDI',   'Tedarikçiye Gitti',  '#0891b2'),
    ('ONAY',         'Onaylandı',          '#059669'),
    ('RED',          'Red — Revize',       '#dc2626'),
    ('TAMAMLANDI',   'Sipariş Açıldı',     '#F97316'),
]

ITERASYON_DURUMLARI = [
    ('GONDERIM',  'Gönderim'),
    ('ALINDI',    'Numune Alındı'),
    ('ONAY',      'Onay'),
    ('RED',       'Red'),
    ('REVIZYON',  'Revizyon İstendi'),
]


def numune_liste(arama=None, durum=None, tedarikci_id=None, musteri_ckod=None):
    ks = ["1=1"]
    params = []
    if arama:
        ks.append("(n.NumuneNo LIKE ? OR n.Baslik LIKE ?)")
        params.extend([f'%{arama}%', f'%{arama}%'])
    if durum:
        ks.append("n.Durum = ?")
        params.append(durum)
    if tedarikci_id:
        ks.append("n.TedarikciId = ?")
        params.append(int(tedarikci_id))
    if musteri_ckod:
        ks.append("n.MusteriCKod = ?")
        params.append(musteri_ckod)
    where = " AND ".join(ks)
    return q(f"""
        SELECT n.*,
               c.CName AS MusteriAd,
               t.Ad    AS TedarikciAd, t.Kod AS TedarikciKod, t.Ulke AS TedarikciUlke,
               u.Kod   AS UrunKod,     u.Ad  AS UrunAd,
               (SELECT COUNT(*) FROM grafik_numune_iterasyon i WHERE i.NumuneId = n.Id) AS IterasyonSayi
        FROM grafik_numune n
        LEFT JOIN Cari_Kart       c ON c.CKod = n.MusteriCKod
        LEFT JOIN grafik_tedarikci t ON t.Id   = n.TedarikciId
        LEFT JOIN grafik_urun      u ON u.Id   = n.UrunId
        WHERE {where}
        ORDER BY n.OlusturmaTarih DESC
    """, tuple(params))


def numune_tek(numune_id):
    return qone("""
        SELECT n.*,
               c.CName AS MusteriAd,
               t.Ad    AS TedarikciAd, t.Kod AS TedarikciKod, t.Ulke AS TedarikciUlke,
               u.Kod   AS UrunKod,     u.Ad  AS UrunAd
        FROM grafik_numune n
        LEFT JOIN Cari_Kart       c ON c.CKod = n.MusteriCKod
        LEFT JOIN grafik_tedarikci t ON t.Id   = n.TedarikciId
        LEFT JOIN grafik_urun      u ON u.Id   = n.UrunId
        WHERE n.Id = ?
    """, (numune_id,))


def numune_iterasyonlar(numune_id):
    return q("""
        SELECT * FROM grafik_numune_iterasyon
        WHERE NumuneId = ?
        ORDER BY Sira, Tarih
    """, (numune_id,))


def numune_ekle(veri, kullanici):
    baslik = (veri.get('Baslik') or '').strip()
    if not baslik:
        raise ValueError('Başlık zorunlu.')
    no = _sonraki_numune_no()
    from datetime import date
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    nid = qexec("""INSERT INTO grafik_numune
                   (NumuneNo, Baslik, MusteriCKod, TedarikciId, UrunId, Durum,
                    TalepTarihi, BeklenenTarih, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, ?, 'TALEP', ?, ?, ?, ?, ?)""",
                (no, baslik,
                 veri.get('MusteriCKod') or None,
                 int(veri['TedarikciId']) if veri.get('TedarikciId') else None,
                 int(veri['UrunId']) if veri.get('UrunId') else None,
                 veri.get('TalepTarihi') or date.today().strftime('%Y-%m-%d'),
                 veri.get('BeklenenTarih') or None,
                 veri.get('Notlar') or None,
                 now, kullanici))
    audit.log_ekle(kullanici, 'grafik_numune', nid,
                   aciklama=f"Numune açıldı: {no} - {baslik}",
                   modul='grafik', alt_modul='numune')
    return nid, no


def numune_guncelle(numune_id, veri, kullanici):
    eski = numune_tek(numune_id)
    if not eski:
        raise ValueError('Numune bulunamadı.')
    yeni = {
        'Baslik': veri.get('Baslik'),
        'MusteriCKod': veri.get('MusteriCKod') or None,
        'TedarikciId': int(veri['TedarikciId']) if veri.get('TedarikciId') else None,
        'UrunId': int(veri['UrunId']) if veri.get('UrunId') else None,
        'BeklenenTarih': veri.get('BeklenenTarih') or None,
        'Notlar': veri.get('Notlar') or None,
    }
    qexec("""UPDATE grafik_numune
             SET Baslik=?, MusteriCKod=?, TedarikciId=?, UrunId=?,
                 BeklenenTarih=?, Notlar=?
             WHERE Id=?""",
          (yeni['Baslik'], yeni['MusteriCKod'], yeni['TedarikciId'], yeni['UrunId'],
           yeni['BeklenenTarih'], yeni['Notlar'], numune_id))
    audit.log_duzenle_coklu(kullanici, 'grafik_numune', numune_id,
                            dict(eski), yeni, modul='grafik', alt_modul='numune')


def numune_durum_degistir(numune_id, yeni_durum, kullanici):
    eski = numune_tek(numune_id)
    if not eski:
        raise ValueError('Numune bulunamadı.')
    if yeni_durum not in [d[0] for d in NUMUNE_DURUMLARI]:
        raise ValueError(f"Geçersiz durum: {yeni_durum}")
    if eski['Durum'] == yeni_durum:
        return
    qexec("UPDATE grafik_numune SET Durum=? WHERE Id=?", (yeni_durum, numune_id))
    audit.log_olay(kullanici, 'DURUM_DEGIS', 'grafik_numune', numune_id,
                   aciklama=f"Durum: {eski['Durum']} → {yeni_durum} ({eski['NumuneNo']})",
                   modul='grafik', alt_modul='numune')


def numune_sil(numune_id, kullanici):
    n = numune_tek(numune_id)
    if not n:
        return False
    qexec("DELETE FROM grafik_numune WHERE Id=?", (numune_id,))
    audit.log_sil(kullanici, 'grafik_numune', numune_id,
                  aciklama=f"Numune silindi: {n['NumuneNo']} - {n['Baslik']}",
                  modul='grafik', alt_modul='numune')
    return True


def iterasyon_ekle(numune_id, tarih, durum, feedback, kullanici):
    n = numune_tek(numune_id)
    if not n:
        raise ValueError('Numune bulunamadı.')
    if durum not in [d[0] for d in ITERASYON_DURUMLARI]:
        raise ValueError(f"Geçersiz iterasyon durumu: {durum}")
    sira = (qscalar("SELECT COALESCE(MAX(Sira),0) FROM grafik_numune_iterasyon WHERE NumuneId=?",
                    (numune_id,)) or 0) + 1
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    iid = qexec("""INSERT INTO grafik_numune_iterasyon
                   (NumuneId, Sira, Tarih, Durum, FeedbackNotu, OlusturanKullanici, OlusturmaTarih)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (numune_id, sira, tarih, durum, feedback, kullanici, now))

    # İterasyon durumuna göre numune durumunu güncelle
    durum_map = {
        'GONDERIM':  'GONDERILDI',
        'ALINDI':    'GONDERILDI',
        'ONAY':      'ONAY',
        'RED':       'RED',
        'REVIZYON':  'GONDERILDI',
    }
    if durum in durum_map and n['Durum'] != durum_map[durum]:
        qexec("UPDATE grafik_numune SET Durum=? WHERE Id=?", (durum_map[durum], numune_id))

    audit.log_ekle(kullanici, 'grafik_numune_iterasyon', iid,
                   aciklama=f"İterasyon #{sira} ({durum}) — {n['NumuneNo']}",
                   modul='grafik', alt_modul='numune')
    return iid


def iterasyon_sil(iter_id, kullanici):
    it = qone("SELECT * FROM grafik_numune_iterasyon WHERE Id=?", (iter_id,))
    if not it:
        return False
    qexec("DELETE FROM grafik_numune_iterasyon WHERE Id=?", (iter_id,))
    audit.log_sil(kullanici, 'grafik_numune_iterasyon', iter_id,
                  aciklama=f"İterasyon #{it['Sira']} silindi",
                  modul='grafik', alt_modul='numune')
    return it['NumuneId']


def musteri_liste_secimlik():
    """Numune formu için müşteri (Cari_Kart CTip=1) listesi."""
    return q("SELECT CKod, CName FROM Cari_Kart WHERE CTip=1 ORDER BY CName")


# ============================================================
# ÇİN SİPARİŞ (Faz 2b)
# ============================================================

SIPARIS_DURUMLARI = [
    ('TASLAK',              'Taslak',                         '#6b7280'),
    ('CIN_IMPORT_KONTROL',  'Çin İçe Aktarma — Kontrol Bekliyor',  '#a855f7'),
    ('ONAYLANDI',           'Onaylandı',                      '#059669'),
    ('URETILIYOR',          'Üretiliyor',                     '#0891b2'),
    ('HAZIR',               'Üretim Bitti',                   '#F97316'),
    ('SEVKEDILDI',          'Sevk Edildi',                    '#7c3aed'),
    ('TAMAMLANDI',          'Tamamlandı',                     '#1f2937'),
    ('IPTAL',               'İptal',                          '#dc2626'),
]


def _sonraki_siparis_no():
    from datetime import date
    yil = date.today().year
    mask = f"CIN-{yil}-%"
    son = qscalar("""
        SELECT MAX(CAST(SUBSTR(SiparisNo, 10) AS INTEGER))
        FROM grafik_cin_siparis WHERE SiparisNo LIKE ?
    """, (mask,)) or 0
    return f"CIN-{yil}-{son+1:04d}"


def siparis_kpi():
    return {
        'taslak':      qscalar("SELECT COUNT(*) FROM grafik_cin_siparis WHERE Durum='TASLAK'") or 0,
        'onaylandi':   qscalar("SELECT COUNT(*) FROM grafik_cin_siparis WHERE Durum='ONAYLANDI'") or 0,
        'uretimde':    qscalar("SELECT COUNT(*) FROM grafik_cin_siparis WHERE Durum IN ('URETILIYOR','HAZIR')") or 0,
        'sevk':        qscalar("SELECT COUNT(*) FROM grafik_cin_siparis WHERE Durum='SEVKEDILDI'") or 0,
        'tamam':       qscalar("SELECT COUNT(*) FROM grafik_cin_siparis WHERE Durum='TAMAMLANDI'") or 0,
        'acik_toplam': qscalar("""SELECT COUNT(*) FROM grafik_cin_siparis
                                  WHERE Durum NOT IN ('TAMAMLANDI','IPTAL')""") or 0,
        'acik_tutar_usd': qscalar("""SELECT COALESCE(SUM(ToplamTutar),0) FROM grafik_cin_siparis
                                     WHERE Durum NOT IN ('TAMAMLANDI','IPTAL','TASLAK')""") or 0.0,
    }


def siparis_liste(arama=None, durum=None, tedarikci_id=None, musteri_ckod=None, show_fiyat=True):
    ks = ["1=1"]
    params = []
    if arama:
        ks.append("(s.SiparisNo LIKE ? OR s.Notlar LIKE ?)")
        params.extend([f'%{arama}%', f'%{arama}%'])
    if durum:
        ks.append("s.Durum = ?")
        params.append(durum)
    if tedarikci_id:
        ks.append("s.TedarikciId = ?")
        params.append(int(tedarikci_id))
    if musteri_ckod:
        ks.append("s.MusteriCKod = ?")
        params.append(musteri_ckod)
    where = " AND ".join(ks)
    return q(f"""
        SELECT s.*,
               t.Ad    AS TedarikciAd, t.Kod AS TedarikciKod, t.Ulke AS TedarikciUlke,
               c.CName AS MusteriAd,
               n.NumuneNo,
               fa.ProjeKod AS AnlasmaKod,
               (SELECT COUNT(*) FROM grafik_cin_siparis_kalem k WHERE k.SiparisId = s.Id) AS KalemSayi,
               (SELECT COUNT(*) FROM grafik_sevkiyat sv WHERE sv.SiparisId = s.Id) AS SevkiyatSayi,
               (SELECT Durum FROM grafik_sevkiyat sv WHERE sv.SiparisId = s.Id
                ORDER BY sv.OlusturmaTarih DESC LIMIT 1) AS SonSevkiyatDurum
        FROM grafik_cin_siparis s
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        LEFT JOIN Cari_Kart        c ON c.CKod = s.MusteriCKod
        LEFT JOIN grafik_numune    n ON n.Id = s.KaynakNumuneId
        LEFT JOIN finans_anlasma  fa ON fa.Id = s.FinansAnlasmaId
        WHERE {where}
        ORDER BY s.OlusturmaTarih DESC
    """, tuple(params))


def siparis_tek(siparis_id):
    return qone("""
        SELECT s.*,
               t.Ad    AS TedarikciAd, t.Kod AS TedarikciKod, t.Ulke AS TedarikciUlke,
                t.CariCKod AS TedarikciCariCKod,
               c.CName AS MusteriAd,
               n.NumuneNo, n.Baslik AS NumuneBaslik,
               fa.ProjeKod AS AnlasmaKod, fa.ToplamTutar AS AnlasmaToplamTL
        FROM grafik_cin_siparis s
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        LEFT JOIN Cari_Kart        c ON c.CKod = s.MusteriCKod
        LEFT JOIN grafik_numune    n ON n.Id = s.KaynakNumuneId
        LEFT JOIN finans_anlasma  fa ON fa.Id = s.FinansAnlasmaId
        WHERE s.Id = ?
    """, (siparis_id,))


def siparis_kalemler(siparis_id):
    return q("""
        SELECT k.*,
               v.Kod AS VaryantKod, v.RenkAd, v.RenkHex, v.Beden,
               u.Kod AS UrunKod, u.Ad AS UrunAd,
               (SELECT Id FROM sistem_belge
                WHERE Modul='grafik' AND AltModul='urun'
                  AND KayitId = COALESCE(k.UrunId, v.UrunId)
                  AND BelgeTipi='GORSEL' AND Aktif=1
                ORDER BY YuklemeTarih DESC LIMIT 1) AS UrunGorselId
        FROM grafik_cin_siparis_kalem k
        LEFT JOIN grafik_urun_varyant v ON v.Id = k.VaryantId
        LEFT JOIN grafik_urun u ON u.Id = COALESCE(k.UrunId, v.UrunId)
        WHERE k.SiparisId = ?
        ORDER BY k.Id
    """, (siparis_id,))


def siparis_ekle(veri, kullanici):
    ted_id = int(veri['TedarikciId']) if veri.get('TedarikciId') else None
    if not ted_id:
        raise ValueError('Tedarikçi zorunlu.')
    no = _sonraki_siparis_no()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    from datetime import date
    sid = qexec("""INSERT INTO grafik_cin_siparis
                   (SiparisNo, TedarikciId, KaynakNumuneId, MusteriCKod,
                    SiparisTarihi, BeklenenCikisTarihi, ParaBirimi,
                    ToplamTutar, Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, ?, ?, 'USD', 0, 'TASLAK', ?, ?, ?)""",
                (no, ted_id,
                 int(veri['KaynakNumuneId']) if veri.get('KaynakNumuneId') else None,
                 veri.get('MusteriCKod') or None,
                 veri.get('SiparisTarihi') or date.today().strftime('%Y-%m-%d'),
                 veri.get('BeklenenCikisTarihi') or None,
                 veri.get('Notlar') or None,
                 now, kullanici))
    audit.log_ekle(kullanici, 'grafik_cin_siparis', sid,
                   aciklama=f"Sipariş açıldı: {no}",
                   modul='grafik', alt_modul='cin_siparis')
    return sid, no


def siparis_guncelle(siparis_id, veri, kullanici):
    eski = siparis_tek(siparis_id)
    if not eski:
        raise ValueError('Sipariş bulunamadı.')
    if eski['Durum'] not in ('TASLAK', 'ONAYLANDI'):
        raise ValueError(f"{eski['Durum']} durumdaki sipariş düzenlenemez.")
    yeni = {
        'TedarikciId':         int(veri['TedarikciId']) if veri.get('TedarikciId') else eski['TedarikciId'],
        'KaynakNumuneId':      int(veri['KaynakNumuneId']) if veri.get('KaynakNumuneId') else None,
        'MusteriCKod':         veri.get('MusteriCKod') or None,
        'BeklenenCikisTarihi': veri.get('BeklenenCikisTarihi') or None,
        'Notlar':              veri.get('Notlar') or None,
    }
    qexec("""UPDATE grafik_cin_siparis
             SET TedarikciId=?, KaynakNumuneId=?, MusteriCKod=?,
                 BeklenenCikisTarihi=?, Notlar=?
             WHERE Id=?""",
          (yeni['TedarikciId'], yeni['KaynakNumuneId'], yeni['MusteriCKod'],
           yeni['BeklenenCikisTarihi'], yeni['Notlar'], siparis_id))
    audit.log_duzenle_coklu(kullanici, 'grafik_cin_siparis', siparis_id,
                            dict(eski), yeni, modul='grafik', alt_modul='cin_siparis')


def _siparis_toplam_guncelle(siparis_id):
    """Kalem toplamlarını siparişe yansıt."""
    t = qscalar("SELECT COALESCE(SUM(Tutar),0) FROM grafik_cin_siparis_kalem WHERE SiparisId=?",
                (siparis_id,)) or 0
    qexec("UPDATE grafik_cin_siparis SET ToplamTutar=? WHERE Id=?", (t, siparis_id))
    return t


def kalem_ekle(siparis_id, veri, kullanici):
    s = siparis_tek(siparis_id)
    if not s:
        raise ValueError('Sipariş bulunamadı.')
    if s['Durum'] != 'TASLAK':
        raise ValueError(f"{s['Durum']} durumdaki siparişe kalem eklenemez. Sadece TASLAK.")
    miktar = int(veri.get('Miktar') or 0)
    bf = float(veri.get('BirimFiyat') or 0)
    if miktar <= 0 or bf < 0:
        raise ValueError('Miktar > 0 ve birim fiyat ≥ 0 olmalı.')
    tutar = round(miktar * bf, 2)
    cift_sayi = int(veri.get('CiftSayi') or 0)
    agirlik_kg = float(veri.get('AgirlikKg') or 0)
    hacim_m3 = float(veri.get('HacimM3') or 0)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    kid = qexec("""INSERT INTO grafik_cin_siparis_kalem
                   (SiparisId, VaryantId, UrunId, Aciklama, Miktar, CiftSayi,
                    BirimFiyat, Tutar, AgirlikKg, HacimM3, OlusturmaTarih)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (siparis_id,
                 int(veri['VaryantId']) if veri.get('VaryantId') else None,
                 int(veri['UrunId']) if veri.get('UrunId') else None,
                 veri.get('Aciklama') or None,
                 miktar, cift_sayi, bf, tutar, agirlik_kg, hacim_m3, now))
    _siparis_toplam_guncelle(siparis_id)
    audit.log_ekle(kullanici, 'grafik_cin_siparis_kalem', kid,
                   aciklama=f"Kalem: {miktar} adet × ${bf} = ${tutar} "
                           f"({agirlik_kg}kg, {hacim_m3}m³, {cift_sayi} çift)",
                   modul='grafik', alt_modul='cin_siparis')
    return kid


def kalem_sil(kalem_id, kullanici):
    k = qone("SELECT * FROM grafik_cin_siparis_kalem WHERE Id=?", (kalem_id,))
    if not k:
        return None
    s = siparis_tek(k['SiparisId'])
    if s and s['Durum'] != 'TASLAK':
        raise ValueError(f"{s['Durum']} durumdaki siparişten kalem silinemez.")
    qexec("DELETE FROM grafik_cin_siparis_kalem WHERE Id=?", (kalem_id,))
    _siparis_toplam_guncelle(k['SiparisId'])
    audit.log_sil(kullanici, 'grafik_cin_siparis_kalem', kalem_id,
                  aciklama=f"Kalem silindi: {k['Miktar']} × {k['BirimFiyat']}",
                  modul='grafik', alt_modul='cin_siparis')
    return k['SiparisId']


def siparis_onayla(siparis_id, kullanici):
    """
    TASLAK → ONAYLANDI
    Otomatik finans_anlasma oluşturur, USD kurunu snapshot alır.
    """
    s = siparis_tek(siparis_id)
    if not s:
        raise ValueError('Sipariş bulunamadı.')
    if s['Durum'] != 'TASLAK':
        raise ValueError(f"Sadece TASLAK durumundaki sipariş onaylanabilir. Mevcut durum: {s['Durum']}.")
    if not s['ToplamTutar'] or s['ToplamTutar'] <= 0:
        raise ValueError('Onay öncesi en az bir kalem eklenmeli (sipariş tutarı sıfır).')
    # S4: Kalem miktarı 0 olan varsa reddet
    eksik_kalem = q("SELECT Id FROM grafik_cin_siparis_kalem WHERE SiparisId=? AND (Miktar IS NULL OR Miktar<=0)",
                    (siparis_id,))
    if eksik_kalem:
        raise ValueError(
            f"Onay öncesi tüm kalemlerde miktar girilmeli. "
            f"{len(eksik_kalem)} kalemde miktar sıfır veya boş."
        )
    if not s['TedarikciCariCKod']:
        raise ValueError(
            'Tedarikçinin Cari_Kart eşleşmesi bulunamadı. '
            'Önce Cari_Kart sayfasından tedarikçi için kayıt oluşturun ve tedarikçiye bağlayın.'
        )

    # USD kur snapshot — eğer sipariş zaten bir KurSnapshot taşıyorsa (teklif'ten geldi) onu kullan
    if s['KurSnapshot'] and float(s['KurSnapshot']) > 0:
        kur_deger = float(s['KurSnapshot'])
    else:
        from modules.yonetim.queries import kur_guncel
        kur_row = kur_guncel('USD')
        if not kur_row:
            raise ValueError(
                'USD kuru bulunamadı. Önce "/yonetim/kur" sayfasından USD kurunu tanımlayın, '
                'sonra siparişi onaylayın.'
            )
        kur_deger = float(kur_row['MerkezKur'])
    toplam_usd = float(s['ToplamTutar'])
    toplam_tl = round(toplam_usd * kur_deger, 2)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    from datetime import date

    # Finans anlaşması oluştur
    anlasma_id = qexec("""
        INSERT INTO finans_anlasma
        (ProjeKod, ProjeAdi, CKod, ToplamTutar, ParaBirimi, Durum,
         BaslangicTarih, KaynakModul, KaynakKayitId,
         OlusturmaTarih, OlusturanKullanici, Notlar)
        VALUES (?, ?, ?, ?, 'TRY', 'AKTIF', ?, 'grafik_cin_siparis', ?, ?, ?, ?)
    """, (s['SiparisNo'],
          f"Çin Sipariş: {s['TedarikciAd']} ({s['SiparisNo']})",
          s['TedarikciCariCKod'],
          toplam_tl,
          date.today().strftime('%Y-%m-%d'),
          siparis_id, now, kullanici,
          f"Otomatik — Çin sipariş onayı. {toplam_usd:.2f} USD × {kur_deger:.4f} = {toplam_tl:.2f} TRY"))

    # Sipariş durumu + kur snapshot + anlaşma ID
    qexec("""UPDATE grafik_cin_siparis
             SET Durum='ONAYLANDI', KurSnapshot=?, FinansAnlasmaId=?,
                 OnayTarihi=?, OnaylayanKullanici=?
             WHERE Id=?""",
          (kur_deger, anlasma_id, now, kullanici, siparis_id))

    # Eğer numune bağlıysa, numuneyi TAMAMLANDI'ya çevir
    if s['KaynakNumuneId']:
        qexec("UPDATE grafik_numune SET Durum='TAMAMLANDI' WHERE Id=?", (s['KaynakNumuneId'],))
        audit.log_olay(kullanici, 'DURUM_DEGIS', 'grafik_numune', s['KaynakNumuneId'],
                       aciklama=f"Numune siparişe döndü: {s['SiparisNo']}",
                       modul='grafik', alt_modul='numune')

    audit.log_olay(kullanici, 'ONAY', 'grafik_cin_siparis', siparis_id,
                   anlasma_id=anlasma_id,
                   aciklama=f"Sipariş onaylandı: {s['SiparisNo']} → Finans anlaşması #{anlasma_id} ({toplam_tl:.0f} TRY)",
                   modul='grafik', alt_modul='cin_siparis')
    return anlasma_id


def siparis_durum_degistir(siparis_id, yeni_durum, kullanici):
    """Onaylandıktan sonraki durum değişiklikleri (URETILIYOR/HAZIR/SEVKEDILDI/TAMAMLANDI/IPTAL)."""
    s = siparis_tek(siparis_id)
    if not s:
        raise ValueError('Sipariş bulunamadı.')
    if yeni_durum not in [d[0] for d in SIPARIS_DURUMLARI]:
        raise ValueError(f"Geçersiz durum: {yeni_durum}")
    if yeni_durum == 'ONAYLANDI':
        raise ValueError('ONAYLANDI durumuna geçiş için "Onayla" butonunu kullanın.')
    if s['Durum'] == 'TASLAK' and yeni_durum != 'IPTAL':
        raise ValueError('TASLAK sipariş sadece onaylanabilir veya iptal edilebilir.')
    qexec("UPDATE grafik_cin_siparis SET Durum=? WHERE Id=?", (yeni_durum, siparis_id))
    audit.log_olay(kullanici, 'DURUM_DEGIS', 'grafik_cin_siparis', siparis_id,
                   anlasma_id=s['FinansAnlasmaId'],
                   aciklama=f"Durum: {s['Durum']} → {yeni_durum} ({s['SiparisNo']})",
                   modul='grafik', alt_modul='cin_siparis')


def siparis_sil(siparis_id, kullanici):
    s = siparis_tek(siparis_id)
    if not s:
        return False
    if s['Durum'] != 'TASLAK':
        raise ValueError('Sadece TASLAK sipariş silinebilir. Onaylanmışı İPTAL durumuna çekin.')
    qexec("DELETE FROM grafik_cin_siparis WHERE Id=?", (siparis_id,))
    audit.log_sil(kullanici, 'grafik_cin_siparis', siparis_id,
                  aciklama=f"Sipariş silindi (taslak): {s['SiparisNo']}",
                  modul='grafik', alt_modul='cin_siparis')
    return True


def numune_onayli_secimlik():
    """Sipariş açma formunda gösterilecek: ONAY durumunda olan numuneler."""
    return q("""
        SELECT Id, NumuneNo, Baslik, MusteriCKod, TedarikciId
        FROM grafik_numune
        WHERE Durum = 'ONAY'
        ORDER BY NumuneNo
    """)


def varyant_secimlik():
    """Kalem eklerken dropdown için tüm aktif varyantlar."""
    return q("""
        SELECT v.Id, v.Kod, v.RenkAd, v.Beden,
               u.Kod AS UrunKod, u.Ad AS UrunAd
        FROM grafik_urun_varyant v
        JOIN grafik_urun u ON u.Id = v.UrunId
        WHERE v.Aktif = 1 AND u.Aktif = 1
        ORDER BY u.Kod, v.RenkAd, v.Beden
    """)


# ============================================================
# SEVKİYAT + MALİYET DAĞITIM (Faz 2b)
# ============================================================

SEVKIYAT_DURUMLARI = [
    ('HAZIRLIK', 'Hazırlık',      '#6b7280'),
    ('YOLDA',    'Yolda',         '#0891b2'),
    ('GUMRUK',   'Gümrükte',      '#F97316'),
    ('TESLIM',   'Teslim Alındı', '#059669'),
    ('IPTAL',    'İptal',         '#dc2626'),
]

NAKLIYE_TIPLERI = [
    ('UCAK',      '✈ Uçak (Air Freight)',    'Hızlı, kg bazlı'),
    ('KONTEYNER', '🚢 Konteyner (Sea)',       'Yavaş, toplu yük'),
    ('DHL',       '📦 DHL / Express',         'Numune + acil küçük kargo'),
    ('KARAYOLU',  '🚚 Karayolu',              'Bölgesel'),
]

DAGITIM_YONTEMLERI = [
    ('FOB',     'FOB Tutarına Göre',   'Kalem FOB USD oranı ile dağıt'),
    ('MIKTAR',  'Adet Bazlı',          'Kalem adet oranı ile dağıt'),
    ('AGIRLIK', 'Ağırlığa Göre (kg)',  'Kalem ağırlık oranı ile dağıt'),
    ('HACIM',   'Hacme Göre (m³)',     'Kalem hacim oranı ile dağıt'),
    ('MANUEL',  'Manuel',              'Her kaleme elle % ata'),
]

MASRAF_TIPLERI = [
    # Uçak grubu
    ('NAVLUN',       'Hava Navlunu (kg×fiyat)'),
    ('AWB_FEE',      'AWB Fee (Havayolu Bileti)'),
    ('CARRIER_FEE',  'Taşıyıcı Ücreti'),
    ('YAKIT',        'Yakıt Ek Ücreti'),
    ('EK_UCRET',     'Ek Ücret'),
    # Konteyner grubu
    ('NAVLUN_DENIZ', 'Deniz Navlunu'),
    ('YUKLEME',      'Yükleme'),
    ('LIMAN',        'Liman Masrafları'),
    ('THC',          'Terminal Handling (THC)'),
    ('ARDIYE',       'Ardiye'),
    ('MUSAVIR',      'Gümrük Müşaviri'),
    ('EVRAK',        'Evrak / Dosyalama'),
    ('IC_NAKLIYE',   'İç Nakliye'),
    # Genel
    ('SIGORTA',      'Sigorta'),
    ('GUMRUK',       'Gümrük / Vergi'),
    ('KDV',          'KDV'),
    ('DEPO',         'Depo / Antrepo'),
    ('TASIMA',       'İç Taşıma'),
    ('KOMIS',        'Komisyon / Forwarder'),
    ('DHL',          'DHL / Kurye'),
    ('DIGER',        'Diğer'),
]

# Masraf tipi → grup eşlemesi (template'de optgroup için)
MASRAF_GRUP = {
    'NAVLUN':'Uçak', 'AWB_FEE':'Uçak', 'CARRIER_FEE':'Uçak', 'YAKIT':'Uçak', 'EK_UCRET':'Uçak',
    'NAVLUN_DENIZ':'Konteyner', 'YUKLEME':'Konteyner', 'LIMAN':'Konteyner', 'THC':'Konteyner',
    'ARDIYE':'Konteyner', 'MUSAVIR':'Konteyner', 'EVRAK':'Konteyner', 'IC_NAKLIYE':'Konteyner',
    'SIGORTA':'Genel', 'GUMRUK':'Genel', 'KDV':'Genel', 'DEPO':'Genel',
    'TASIMA':'Genel', 'KOMIS':'Genel', 'DHL':'Genel', 'DIGER':'Genel',
}

GONDERIM_YONLERI = [
    ('CN_TR', 'Çin → Türkiye'),
    ('TR_CN', 'Türkiye → Çin'),
    ('EU_TR', 'Avrupa → Türkiye'),
    ('TR_EU', 'Türkiye → Avrupa'),
]


def _sonraki_sevkiyat_no():
    from datetime import date
    yil = date.today().year
    mask = f"SVK-{yil}-%"
    son = qscalar("""
        SELECT MAX(CAST(SUBSTR(SevkiyatNo, 10) AS INTEGER))
        FROM grafik_sevkiyat WHERE SevkiyatNo LIKE ?
    """, (mask,)) or 0
    return f"SVK-{yil}-{son+1:04d}"


def sevkiyat_kpi():
    return {
        'hazirlik':   qscalar("SELECT COUNT(*) FROM grafik_sevkiyat WHERE Durum='HAZIRLIK'") or 0,
        'yolda':      qscalar("SELECT COUNT(*) FROM grafik_sevkiyat WHERE Durum='YOLDA'") or 0,
        'gumruk':     qscalar("SELECT COUNT(*) FROM grafik_sevkiyat WHERE Durum='GUMRUK'") or 0,
        'teslim':     qscalar("SELECT COUNT(*) FROM grafik_sevkiyat WHERE Durum='TESLIM'") or 0,
        'tahmini_masraf_tl': qscalar("""
            SELECT COALESCE(SUM(ToplamMasrafTL),0) FROM grafik_sevkiyat
            WHERE Durum IN ('HAZIRLIK','YOLDA','GUMRUK')""") or 0,
        'gercek_masraf_tl': qscalar("""
            SELECT COALESCE(SUM(ToplamMasrafTL),0) FROM grafik_sevkiyat
            WHERE Durum = 'TESLIM'""") or 0,
        'toplam_masraf_tl_aktif': qscalar("""
            SELECT COALESCE(SUM(ToplamMasrafTL),0) FROM grafik_sevkiyat
            WHERE Durum NOT IN ('IPTAL')""") or 0,
    }


def sevkiyat_liste(arama=None, durum=None, nakliye=None):
    ks = ["1=1"]
    params = []
    if arama:
        ks.append("(sv.SevkiyatNo LIKE ? OR sv.Konsimento LIKE ? OR sv.TakipNo LIKE ? OR s.SiparisNo LIKE ?)")
        params.extend([f'%{arama}%']*4)
    if durum:
        ks.append("sv.Durum = ?")
        params.append(durum)
    if nakliye:
        ks.append("sv.NakliyeTipi = ?")
        params.append(nakliye)
    where = " AND ".join(ks)
    return q(f"""
        SELECT sv.*,
               s.SiparisNo, s.ToplamTutar AS FOBUSDToplam,
               t.Ad AS TedarikciAd, t.Ulke AS TedarikciUlke,
               c.CName AS MusteriAd,
               n.NumuneNo, n.Baslik AS NumuneBaslik
        FROM grafik_sevkiyat sv
        LEFT JOIN grafik_cin_siparis s  ON s.Id = sv.SiparisId
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        LEFT JOIN Cari_Kart c ON c.CKod = s.MusteriCKod
        LEFT JOIN grafik_numune n ON n.Id = sv.NumuneId
        WHERE {where}
        ORDER BY sv.OlusturmaTarih DESC
    """, tuple(params))


def sevkiyat_tek(sevkiyat_id):
    return qone("""
        SELECT sv.*, s.SiparisNo, s.ToplamTutar AS FOBUSDToplam, s.KurSnapshot AS SiparisKur,
               t.Ad AS TedarikciAd, t.Ulke AS TedarikciUlke,
               c.CName AS MusteriAd,
               n.NumuneNo, n.Baslik AS NumuneBaslik
        FROM grafik_sevkiyat sv
        LEFT JOIN grafik_cin_siparis s ON s.Id = sv.SiparisId
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        LEFT JOIN Cari_Kart c ON c.CKod = s.MusteriCKod
        LEFT JOIN grafik_numune n ON n.Id = sv.NumuneId
        WHERE sv.Id = ?
    """, (sevkiyat_id,))


def numune_dhl_sevkiyatlari(numune_id):
    """Bir numuneye bağlı DHL/kurye sevkiyatları."""
    return q("""
        SELECT * FROM grafik_sevkiyat
        WHERE NumuneId = ?
        ORDER BY OlusturmaTarih DESC
    """, (numune_id,))


def sevkiyat_masraflar(sevkiyat_id):
    return q("""SELECT * FROM grafik_sevkiyat_masraf
                WHERE SevkiyatId = ? ORDER BY Id""", (sevkiyat_id,))


def sevkiyat_dagitim(sevkiyat_id):
    return q("""
        SELECT d.*, k.Aciklama, k.Miktar AS KalemMiktar, k.BirimFiyat, k.Tutar AS KalemFOBUSD,
               k.AgirlikKg, k.HacimM3,
               u.Kod AS UrunKod, u.Ad AS UrunAd,
               v.RenkAd, v.Beden, v.RenkHex,
               (SELECT Id FROM sistem_belge
                WHERE Modul='grafik' AND AltModul='urun'
                  AND KayitId = COALESCE(k.UrunId, v.UrunId)
                  AND BelgeTipi='GORSEL' AND Aktif=1
                ORDER BY YuklemeTarih DESC LIMIT 1) AS UrunGorselId
        FROM grafik_sevkiyat_dagitim d
        JOIN grafik_cin_siparis_kalem k ON k.Id = d.KalemId
        LEFT JOIN grafik_urun u ON u.Id = COALESCE(k.UrunId, (SELECT UrunId FROM grafik_urun_varyant WHERE Id=k.VaryantId))
        LEFT JOIN grafik_urun_varyant v ON v.Id = k.VaryantId
        WHERE d.SevkiyatId = ?
        ORDER BY d.Id
    """, (sevkiyat_id,))


def onaylanmis_siparisler_sevkedilmemis():
    """
    Sevkiyat formu dropdown için: ONAYLANDI/URETILIYOR/HAZIR/SEVKEDILDI siparişler.
    Parça 4: Aynı siparişe birden fazla sevkiyat açılabildiği için mevcut sevkiyat sayısı
    da döndürülür (bilgi amaçlı, engellemez).
    """
    return q("""
        SELECT s.Id, s.SiparisNo, s.ToplamTutar, t.Ad AS TedarikciAd,
               (SELECT COUNT(*) FROM grafik_sevkiyat sv
                WHERE sv.SiparisId = s.Id) AS MevcutSevkiyatSayisi
        FROM grafik_cin_siparis s
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        WHERE s.Durum IN ('ONAYLANDI','URETILIYOR','HAZIR','SEVKEDILDI')
        ORDER BY s.SiparisNo DESC
    """)


def sevkiyat_ekle(veri, kullanici):
    """
    DHL: numune veya sipariş bağlı olabilir. Diğerleri: sipariş zorunlu.
    Sipariş sadece onaylanmış olabilir.
    """
    nakliye = (veri.get('NakliyeTipi') or 'KONTEYNER').upper()
    sid = int(veri['SiparisId']) if veri.get('SiparisId') else None
    nid = int(veri['NumuneId']) if veri.get('NumuneId') else None

    if nakliye == 'DHL':
        if not sid and not nid:
            raise ValueError('DHL için Sipariş veya Numune zorunlu.')
    else:
        if not sid:
            raise ValueError('Bu nakliye tipi için Sipariş zorunlu.')

    if sid:
        siparis = qone("SELECT * FROM grafik_cin_siparis WHERE Id=?", (sid,))
        if not siparis:
            raise ValueError('Sipariş bulunamadı.')
        if siparis['Durum'] == 'TASLAK':
            raise ValueError('TASLAK sipariş için sevkiyat oluşturulamaz. Önce onaylayın.')
        # Parça 4 (V2b): İPTAL siparişe yeni sevkiyat açılamaz
        if siparis['Durum'] == 'IPTAL':
            raise ValueError('İPTAL edilmiş sipariş için yeni sevkiyat açılamaz.')

    no = _sonraki_sevkiyat_no()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    from datetime import date
    svk_id = qexec("""INSERT INTO grafik_sevkiyat
                      (SevkiyatNo, SiparisId, NumuneId, NakliyeTipi, Forwarder, Konsimento,
                       TakipNo, GonderimYonu, UrunMaliyetineDahil, AgirlikKg,
                       SevkTarihi, BeklenenVarisTarihi, DagitimYontemi, Durum, Notlar,
                       OlusturmaTarih, OlusturanKullanici)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'HAZIRLIK', ?, ?, ?)""",
                   (no, sid, nid, nakliye,
                    veri.get('Forwarder') or None,
                    veri.get('Konsimento') or None,
                    veri.get('TakipNo') or None,
                    veri.get('GonderimYonu') or 'CN_TR',
                    1 if veri.get('UrunMaliyetineDahil') in (1, '1', 'on', True) else 0,
                    float(veri.get('AgirlikKg') or 0),
                    veri.get('SevkTarihi') or date.today().strftime('%Y-%m-%d'),
                    veri.get('BeklenenVarisTarihi') or None,
                    veri.get('DagitimYontemi') or 'FOB',
                    veri.get('Notlar') or None,
                    now, kullanici))
    audit.log_ekle(kullanici, 'grafik_sevkiyat', svk_id,
                   aciklama=f"Sevkiyat açıldı: {no} ({nakliye})",
                   modul='grafik', alt_modul='maliyet')
    return svk_id, no


def sevkiyat_guncelle(sevkiyat_id, veri, kullanici):
    eski = sevkiyat_tek(sevkiyat_id)
    if not eski:
        raise ValueError('Sevkiyat bulunamadı.')
    yeni = {
        'NakliyeTipi':            veri.get('NakliyeTipi') or eski['NakliyeTipi'],
        'Forwarder':              veri.get('Forwarder') or None,
        'Konsimento':             veri.get('Konsimento') or None,
        'TakipNo':                veri.get('TakipNo') or None,
        'GonderimYonu':           veri.get('GonderimYonu') or eski['GonderimYonu'] or 'CN_TR',
        'UrunMaliyetineDahil':    1 if veri.get('UrunMaliyetineDahil') in (1, '1', 'on', True) else 0,
        'AgirlikKg':              float(veri.get('AgirlikKg') or 0),
        'SevkTarihi':             veri.get('SevkTarihi') or None,
        'BeklenenVarisTarihi':    veri.get('BeklenenVarisTarihi') or None,
        'GerceklesenVarisTarihi': veri.get('GerceklesenVarisTarihi') or None,
        'DagitimYontemi':         veri.get('DagitimYontemi') or eski['DagitimYontemi'],
        'Notlar':                 veri.get('Notlar') or None,
    }
    qexec("""UPDATE grafik_sevkiyat
             SET NakliyeTipi=?, Forwarder=?, Konsimento=?, TakipNo=?, GonderimYonu=?,
                 UrunMaliyetineDahil=?, AgirlikKg=?, SevkTarihi=?,
                 BeklenenVarisTarihi=?, GerceklesenVarisTarihi=?,
                 DagitimYontemi=?, Notlar=?
             WHERE Id=?""",
          (yeni['NakliyeTipi'], yeni['Forwarder'], yeni['Konsimento'], yeni['TakipNo'],
           yeni['GonderimYonu'], yeni['UrunMaliyetineDahil'], yeni['AgirlikKg'],
           yeni['SevkTarihi'], yeni['BeklenenVarisTarihi'], yeni['GerceklesenVarisTarihi'],
           yeni['DagitimYontemi'], yeni['Notlar'], sevkiyat_id))
    if yeni['DagitimYontemi'] != eski['DagitimYontemi']:
        qexec("UPDATE grafik_sevkiyat SET DagitimHesaplandi=0 WHERE Id=?", (sevkiyat_id,))
        qexec("DELETE FROM grafik_sevkiyat_dagitim WHERE SevkiyatId=?", (sevkiyat_id,))
    audit.log_duzenle_coklu(kullanici, 'grafik_sevkiyat', sevkiyat_id,
                            dict(eski), yeni, modul='grafik', alt_modul='maliyet')


def sevkiyat_durum_degistir(sevkiyat_id, yeni_durum, kullanici):
    s = sevkiyat_tek(sevkiyat_id)
    if not s:
        raise ValueError('Sevkiyat bulunamadı.')
    if yeni_durum not in [d[0] for d in SEVKIYAT_DURUMLARI]:
        raise ValueError(f"Geçersiz durum: {yeni_durum}")

    qexec("UPDATE grafik_sevkiyat SET Durum=? WHERE Id=?", (yeni_durum, sevkiyat_id))

    # H1: TESLIM'e geçince mevcut dağıtım satırları kesinleşir
    uyarilar = []
    if yeni_durum == 'TESLIM':
        qexec("UPDATE grafik_sevkiyat_dagitim SET IsTahmini=0 WHERE SevkiyatId=?", (sevkiyat_id,))
        # V5 yumuşak uyarılar
        if not s['GerceklesenVarisTarihi']:
            uyarilar.append("Gerçek varış tarihi boş — detaydan girin.")
        if (s['ToplamMasrafTL'] or 0) <= 0:
            uyarilar.append("Masraf toplamı 0 — eksik masraf olabilir.")
        dag = qscalar("SELECT COUNT(*) FROM grafik_sevkiyat_dagitim WHERE SevkiyatId=?",
                      (sevkiyat_id,)) or 0
        if dag == 0:
            uyarilar.append("Dağıtım hesaplanmadı — 'Dağıtımı Hesapla' butonunu kullanın.")
    # TESLIM'den çıkınca (nadir): kesinleşmiş veriye dokunulmaz (K1)

    audit.log_olay(kullanici, 'DURUM_DEGIS', 'grafik_sevkiyat', sevkiyat_id,
                   aciklama=f"Durum: {s['Durum']} → {yeni_durum} ({s['SevkiyatNo']})",
                   modul='grafik', alt_modul='maliyet')
    return uyarilar


def sevkiyat_sil(sevkiyat_id, kullanici):
    s = sevkiyat_tek(sevkiyat_id)
    if not s:
        return False
    if s['Durum'] == 'TESLIM':
        raise ValueError('Teslim alınmış sevkiyat silinemez. Önce İPTAL\'e çevirin.')
    qexec("DELETE FROM grafik_sevkiyat WHERE Id=?", (sevkiyat_id,))
    audit.log_sil(kullanici, 'grafik_sevkiyat', sevkiyat_id,
                  aciklama=f"Sevkiyat silindi: {s['SevkiyatNo']}",
                  modul='grafik', alt_modul='maliyet')
    return True


def _masraf_tl_hesapla(tutar, para_birimi, kur):
    if para_birimi == 'TRY':
        return round(tutar, 2)
    return round(tutar * kur, 2)


def _kullanici_rol(kullanici):
    """Kullanıcının rol adını döndür (Yönetim/Grafik/...)."""
    r = qone("""SELECT r.RolAd FROM sistem_kullanici k
                LEFT JOIN sistem_rol r ON r.Id = k.RolId
                WHERE k.Kullanici=?""", (kullanici,))
    return (r or {}).get('RolAd') or ''


def onerilen_dagitim_yontemi(siparis_id):
    """
    K3: Sipariş kalemlerine bakarak en mantıklı dağıtım yöntemini öner.
    """
    if not siparis_id:
        return 'FOB'
    kalemler = q("SELECT Miktar, AgirlikKg, HacimM3, Tutar FROM grafik_cin_siparis_kalem WHERE SiparisId=?",
                 (siparis_id,))
    if not kalemler:
        return 'FOB'
    if sum(float(k['AgirlikKg'] or 0) for k in kalemler) > 0:
        return 'AGIRLIK'
    if sum(float(k['HacimM3'] or 0) for k in kalemler) > 0:
        return 'HACIM'
    if all((k['Miktar'] or 0) > 0 for k in kalemler):
        return 'MIKTAR'
    return 'FOB'


def numune_siparisleri(numune_id):
    """K4: Bu numuneden oluşan siparişler (çift yön bağlantı)."""
    return q("""
        SELECT s.Id, s.SiparisNo, s.Durum, s.ToplamTutar, s.ParaBirimi,
               s.SiparisTarihi, s.BeklenenCikisTarihi,
               t.Ad AS TedarikciAd, c.CName AS MusteriAd
        FROM grafik_cin_siparis s
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        LEFT JOIN Cari_Kart c ON c.CKod = s.MusteriCKod
        WHERE s.KaynakNumuneId = ?
        ORDER BY s.OlusturmaTarih DESC
    """, (numune_id,))


def _sevkiyat_toplam_masraf_guncelle(sevkiyat_id):
    t = qscalar("SELECT COALESCE(SUM(TutarTL),0) FROM grafik_sevkiyat_masraf WHERE SevkiyatId=?",
                (sevkiyat_id,)) or 0
    # TESLIM sonrası: dağıtımı silme (kilit koruma), sadece toplam güncelle
    s = qone("SELECT Durum FROM grafik_sevkiyat WHERE Id=?", (sevkiyat_id,))
    if s and s['Durum'] == 'TESLIM':
        qexec("UPDATE grafik_sevkiyat SET ToplamMasrafTL=? WHERE Id=?", (t, sevkiyat_id))
    else:
        qexec("UPDATE grafik_sevkiyat SET ToplamMasrafTL=?, DagitimHesaplandi=0 WHERE Id=?",
              (t, sevkiyat_id))
        qexec("DELETE FROM grafik_sevkiyat_dagitim WHERE SevkiyatId=?", (sevkiyat_id,))
    return t


def siparis_sevkiyatlar(siparis_id):
    """
    Parça 4: Bir siparişe bağlı tüm sevkiyatlar + her birinin özeti.
    Sipariş detayında 'Bağlı Sevkiyatlar' tablosunda kullanılır.

    Her satır için:
    - SevkiyatNo, NakliyeTipi, Durum, ToplamMasrafTL
    - GerceklesenVarisTarihi (Teslim Tarihi)
    - DagSayisi (dağıtım satır sayısı)
    - GercekDagSayisi (IsTahmini=0 olan satır sayısı — hepsi kesinleşmişse = DagSayisi)
    - IsGercek (0/1): dağıtım var ve TAMAMI kesinleşmişse 1
    """
    return q("""
        SELECT sv.Id, sv.SevkiyatNo, sv.NakliyeTipi, sv.Durum,
               sv.ToplamMasrafTL, sv.SevkTarihi, sv.BeklenenVarisTarihi,
               sv.GerceklesenVarisTarihi, sv.OlusturmaTarih,
               (SELECT COUNT(*) FROM grafik_sevkiyat_dagitim d
                WHERE d.SevkiyatId=sv.Id) AS DagSayisi,
               (SELECT COUNT(*) FROM grafik_sevkiyat_dagitim d
                WHERE d.SevkiyatId=sv.Id AND d.IsTahmini=0) AS GercekDagSayisi
        FROM grafik_sevkiyat sv
        WHERE sv.SiparisId = ?
        ORDER BY sv.OlusturmaTarih ASC
    """, (siparis_id,))


def siparis_sevkiyat_ozet(siparis_id):
    """
    Sipariş detayında üst bilgi kutusu için:
    - ToplamSevkiyat, TeslimSevkiyat, DevamEden
    - KismiTeslim: en az 1 TESLIM + en az 1 aktif (HAZIRLIK/YOLDA/GUMRUK) → True
    """
    r = qone("""
        SELECT
          COUNT(*) AS ToplamSevkiyat,
          SUM(CASE WHEN Durum='TESLIM' THEN 1 ELSE 0 END) AS TeslimSevkiyat,
          SUM(CASE WHEN Durum IN ('HAZIRLIK','YOLDA','GUMRUK') THEN 1 ELSE 0 END) AS DevamEden,
          SUM(CASE WHEN Durum='IPTAL' THEN 1 ELSE 0 END) AS IptalSevkiyat
        FROM grafik_sevkiyat WHERE SiparisId=?
    """, (siparis_id,))
    r = r or {'ToplamSevkiyat': 0, 'TeslimSevkiyat': 0, 'DevamEden': 0, 'IptalSevkiyat': 0}
    # Null güvenlik
    for k in ('ToplamSevkiyat','TeslimSevkiyat','DevamEden','IptalSevkiyat'):
        r[k] = r.get(k) or 0
    r['KismiTeslim'] = (r['TeslimSevkiyat'] > 0 and r['DevamEden'] > 0)
    return r


def _teslim_kilidi_kontrol(sevkiyat, kullanici_rol, eylem='degisiklik'):
    """
    K1: TESLIM durumundaki sevkiyatta masraf/dağıtım değişikliği reddedilir.
    Yönetim rolü override edebilir (ama ekstra audit log düşer).
    """
    if sevkiyat and sevkiyat['Durum'] == 'TESLIM':
        if kullanici_rol != 'Yönetim':
            raise ValueError(
                f"🔒 Teslim alınmış sevkiyatta {eylem} yapamazsınız. "
                f"Geçmiş maliyetlerin değişmemesi için kilitlenmiştir. "
                f"Yönetim rolü override edebilir."
            )
        return True  # Yönetim override etti
    return False


def _kullanici_rol(kullanici):
    """Kullanıcının rol adını döndürür (Yönetim/Grafik/Muhasebe/vs)."""
    r = qone("""SELECT r.Ad AS RolAd FROM sistem_kullanici k
                LEFT JOIN sistem_rol r ON r.Id=k.RolId
                WHERE k.KullaniciAdi=?""", (kullanici,))
    return r['RolAd'] if r else None


def onerilen_dagitim_yontemi(siparis_id):
    """K3: Kalemlerdeki alan durumuna göre en uygun yöntemi öner."""
    kalemler = q("""SELECT AgirlikKg, HacimM3, Miktar, Tutar
                    FROM grafik_cin_siparis_kalem WHERE SiparisId=?""",
                 (siparis_id,))
    if not kalemler:
        return 'FOB'
    tot_kg = sum(float(k['AgirlikKg'] or 0) for k in kalemler)
    tot_m3 = sum(float(k['HacimM3'] or 0) for k in kalemler)
    all_miktar = all((k['Miktar'] or 0) > 0 for k in kalemler)
    all_tutar = all((k['Tutar'] or 0) > 0 for k in kalemler)
    if tot_kg > 0:
        return 'AGIRLIK'
    if tot_m3 > 0:
        return 'HACIM'
    if all_miktar:
        return 'MIKTAR'
    if all_tutar:
        return 'FOB'
    return 'FOB'


def masraf_ekle(sevkiyat_id, veri, kullanici):
    s = sevkiyat_tek(sevkiyat_id)
    if not s:
        raise ValueError('Sevkiyat bulunamadı.')

    # K1: TESLIM kilidi
    rol = _kullanici_rol(kullanici)
    _teslim_kilidi_kontrol(s, rol, eylem='masraf eklenmesi')

    # H2: BirimSayi × BirimFiyat veya doğrudan Tutar
    try:
        birim_sayi = float(veri.get('BirimSayi') or 0)
        birim_fiyat = float(veri.get('BirimFiyat') or 0)
        tutar = float(veri.get('Tutar') or 0)
    except (TypeError, ValueError):
        raise ValueError('Sayı alanları geçerli değil. Lütfen nümerik değer girin.')

    if birim_sayi < 0 or birim_fiyat < 0 or tutar < 0:
        raise ValueError('Negatif değer kabul edilmez. Tutarlar pozitif olmalı.')

    if birim_sayi > 0 and birim_fiyat > 0:
        tutar = round(birim_sayi * birim_fiyat, 2)
    if tutar <= 0:
        raise ValueError('Tutar sıfırdan büyük olmalı. Ya Tutar ya da BirimSayi × BirimFiyat girin.')
    pb = (veri.get('ParaBirimi') or 'TRY').upper()
    if pb not in ('TRY', 'USD', 'EUR', 'CNY'):
        raise ValueError('Para birimi TRY, USD, EUR veya CNY olmalı.')

    # K2: IslemTarih + Kur snapshot (o tarihteki merkez bankası kuru)
    from datetime import date
    islem_tarih = veri.get('IslemTarih') or date.today().strftime('%Y-%m-%d')

    kur = 1.0
    if pb != 'TRY':
        # Kullanıcı manuel kur girdiyse onu kullan (uyarı verilmiş olacak)
        manuel_kur_raw = veri.get('KurSnapshot')
        if manuel_kur_raw not in (None, '', '0', '0.0'):
            try:
                manuel_kur = float(manuel_kur_raw)
            except (TypeError, ValueError):
                raise ValueError('Girilen kur geçerli bir sayı değil.')
            if manuel_kur <= 0:
                raise ValueError('Kur sıfır veya negatif olamaz. Geçerli bir kur girin.')
            kur = manuel_kur
        else:
            from modules.yonetim.queries import kur_guncel
            kr = kur_guncel(pb)
            if not kr:
                raise ValueError(
                    f'{pb} kuru bulunamadı. Önce "/yonetim/kur" sayfasından {pb} kurunu tanımlayın.'
                )
            kur = float(kr['MerkezKur'])

    tutar_tl = _masraf_tl_hesapla(tutar, pb, kur)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    mid = qexec("""INSERT INTO grafik_sevkiyat_masraf
                   (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi,
                    IslemTarih, KurSnapshot, TutarTL, BelgeNo, Aciklama,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sevkiyat_id,
                 (veri.get('Tip') or 'DIGER').upper(),
                 birim_sayi, birim_fiyat,
                 tutar, pb, islem_tarih, kur, tutar_tl,
                 veri.get('BelgeNo') or None,
                 veri.get('Aciklama') or None,
                 now, kullanici))
    _sevkiyat_toplam_masraf_guncelle(sevkiyat_id)

    # Yönetim TESLIM üzerine ekledi → ekstra audit
    if s['Durum'] == 'TESLIM' and rol == 'Yönetim':
        audit.log_olay(kullanici, 'TESLIM_SONRASI_MASRAF_EKLE', 'grafik_sevkiyat_masraf', mid,
                       aciklama=f"[KILIT AŞILDI] Teslim sonrası masraf: {veri.get('Tip')} {tutar:.2f} {pb}",
                       modul='grafik', alt_modul='maliyet')
    else:
        audit.log_ekle(kullanici, 'grafik_sevkiyat_masraf', mid,
                       aciklama=f"Masraf eklendi: {veri.get('Tip')} {tutar:.2f} {pb} = {tutar_tl:.2f} TRY ({islem_tarih})",
                       modul='grafik', alt_modul='maliyet')
    return mid


def masraf_sil(masraf_id, kullanici):
    m = qone("SELECT * FROM grafik_sevkiyat_masraf WHERE Id=?", (masraf_id,))
    if not m:
        return None
    s = sevkiyat_tek(m['SevkiyatId'])
    rol = _kullanici_rol(kullanici)
    _teslim_kilidi_kontrol(s, rol, eylem='masraf silinmesi')

    qexec("DELETE FROM grafik_sevkiyat_masraf WHERE Id=?", (masraf_id,))
    _sevkiyat_toplam_masraf_guncelle(m['SevkiyatId'])

    if s and s['Durum'] == 'TESLIM' and rol == 'Yönetim':
        audit.log_olay(kullanici, 'TESLIM_SONRASI_MASRAF_SIL', 'grafik_sevkiyat_masraf', masraf_id,
                       aciklama=f"[KILIT AŞILDI] Teslim sonrası masraf silindi: {m['Tip']} {m['TutarTL']:.2f} TRY",
                       modul='grafik', alt_modul='maliyet')
    else:
        audit.log_sil(kullanici, 'grafik_sevkiyat_masraf', masraf_id,
                      aciklama=f"Masraf silindi: {m['Tip']} {m['TutarTL']:.2f} TRY",
                      modul='grafik', alt_modul='maliyet')
    return m['SevkiyatId']


def masraf_guncelle(masraf_id, veri, kullanici):
    """
    EK-1: Masraf düzenleme (Parça 5).
    K1 TESLIM kilidi uygulanır.

    Kur snapshot mantığı:
    - Eğer IslemTarih değişmediyse → mevcut KurSnapshot KORUNUR (sessiz geçer)
    - IslemTarih değiştiyse → kullanıcı manuel kur girdiyse o kullanılır,
      aksi halde hata verir ("kur tanımlı değilse manuel girin")
    - Sessizce bugünkü kura DÖNMEZ.
    """
    m = qone("SELECT * FROM grafik_sevkiyat_masraf WHERE Id=?", (masraf_id,))
    if not m:
        raise ValueError('Masraf kaydı bulunamadı.')
    s = sevkiyat_tek(m['SevkiyatId'])
    rol = _kullanici_rol(kullanici)
    _teslim_kilidi_kontrol(s, rol, eylem='masraf düzenlemesi')

    # Numerik alanlar
    try:
        birim_sayi = float(veri.get('BirimSayi') or m['BirimSayi'] or 0)
        birim_fiyat = float(veri.get('BirimFiyat') or m['BirimFiyat'] or 0)
        tutar = float(veri.get('Tutar') or 0)
    except (TypeError, ValueError):
        raise ValueError('Sayı alanları geçerli değil. Lütfen nümerik değer girin.')

    if birim_sayi < 0 or birim_fiyat < 0 or tutar < 0:
        raise ValueError('Negatif değer kabul edilmez.')

    if birim_sayi > 0 and birim_fiyat > 0:
        tutar = round(birim_sayi * birim_fiyat, 2)
    if tutar <= 0:
        tutar = m['Tutar']  # eski tutarı koru
    if tutar <= 0:
        raise ValueError('Tutar sıfırdan büyük olmalı.')

    pb = (veri.get('ParaBirimi') or m['ParaBirimi'] or 'TRY').upper()
    if pb not in ('TRY', 'USD', 'EUR', 'CNY'):
        raise ValueError('Para birimi TRY, USD, EUR veya CNY olmalı.')

    # Kur snapshot mantığı
    from datetime import date as _date
    yeni_tarih = veri.get('IslemTarih') or m['IslemTarih'] or _date.today().strftime('%Y-%m-%d')
    eski_tarih = m['IslemTarih']
    eski_pb = m['ParaBirimi']

    tarih_degisti = (yeni_tarih != eski_tarih)
    pb_degisti = (pb != eski_pb)

    if pb == 'TRY':
        kur = 1.0
    else:
        if not tarih_degisti and not pb_degisti:
            # İkisi de aynı: mevcut snapshot korunur
            kur = float(m['KurSnapshot'] or 1.0)
        else:
            # Tarih veya PB değişti → yeni kur gerek
            manuel_kur_raw = veri.get('KurSnapshot')
            if manuel_kur_raw not in (None, '', '0', '0.0'):
                try:
                    manuel_kur = float(manuel_kur_raw)
                except (TypeError, ValueError):
                    raise ValueError('Girilen kur geçerli bir sayı değil.')
                if manuel_kur <= 0:
                    raise ValueError('Kur sıfır veya negatif olamaz.')
                kur = manuel_kur
            else:
                from modules.yonetim.queries import kur_guncel
                kr = kur_guncel(pb)
                if not kr:
                    raise ValueError(
                        f'{pb} kuru bulunamadı. İşlem tarihi veya para birimi değişti — '
                        f'lütfen yeni kuru manuel girin veya "/yonetim/kur" sayfasından tanımlayın.'
                    )
                kur = float(kr['MerkezKur'])

    tutar_tl = _masraf_tl_hesapla(tutar, pb, kur)

    eski_degerler = dict(m)
    yeni_degerler = {
        'Tip': (veri.get('Tip') or m['Tip']).upper(),
        'BirimSayi': birim_sayi, 'BirimFiyat': birim_fiyat,
        'Tutar': tutar, 'ParaBirimi': pb,
        'IslemTarih': yeni_tarih, 'KurSnapshot': kur, 'TutarTL': tutar_tl,
        'BelgeNo': veri.get('BelgeNo') or m['BelgeNo'],
        'Aciklama': veri.get('Aciklama') or m['Aciklama'],
    }

    qexec("""UPDATE grafik_sevkiyat_masraf
             SET Tip=?, BirimSayi=?, BirimFiyat=?, Tutar=?, ParaBirimi=?,
                 IslemTarih=?, KurSnapshot=?, TutarTL=?, BelgeNo=?, Aciklama=?
             WHERE Id=?""",
          (yeni_degerler['Tip'], yeni_degerler['BirimSayi'], yeni_degerler['BirimFiyat'],
           yeni_degerler['Tutar'], yeni_degerler['ParaBirimi'],
           yeni_degerler['IslemTarih'], yeni_degerler['KurSnapshot'], yeni_degerler['TutarTL'],
           yeni_degerler['BelgeNo'], yeni_degerler['Aciklama'], masraf_id))

    _sevkiyat_toplam_masraf_guncelle(m['SevkiyatId'])

    if s and s['Durum'] == 'TESLIM' and rol == 'Yönetim':
        audit.log_olay(kullanici, 'TESLIM_SONRASI_MASRAF_GUNCEL', 'grafik_sevkiyat_masraf', masraf_id,
                       aciklama=f"[KILIT AŞILDI] Masraf güncellendi: {yeni_degerler['Tip']} "
                               f"{tutar:.2f} {pb} (eski: {m['Tutar']:.2f} {eski_pb})",
                       modul='grafik', alt_modul='maliyet')
    else:
        audit.log_duzenle_coklu(kullanici, 'grafik_sevkiyat_masraf', masraf_id,
                                eski_degerler, yeni_degerler,
                                modul='grafik', alt_modul='maliyet')
    return m['SevkiyatId']


def dagitim_hesapla(sevkiyat_id, kullanici, manuel_oranlar=None):
    """
    5 dağıtım yöntemi: FOB / MIKTAR / AGIRLIK / HACIM / MANUEL
    H1: IsTahmini = sevkiyat TESLIM değilse 1, değilse 0
    H4: yönteme göre eksik alan sert validation
    K1: TESLIM sonrası sadece Yönetim
    """
    s = sevkiyat_tek(sevkiyat_id)
    if not s:
        raise ValueError('Sevkiyat bulunamadı.')
    if s['Durum'] == 'IPTAL':
        raise ValueError('İptal edilmiş sevkiyatta dağıtım hesaplanamaz.')

    rol = _kullanici_rol(kullanici)
    _teslim_kilidi_kontrol(s, rol, eylem='dağıtım yeniden hesaplanması')

    if not s['SiparisId']:
        raise ValueError('Siparişe bağlı olmayan sevkiyat (örn DHL numune) için dağıtım hesaplanamaz.')

    kalemler = q("""SELECT * FROM grafik_cin_siparis_kalem WHERE SiparisId=?""",
                 (s['SiparisId'],))
    if not kalemler:
        raise ValueError('Siparişte kalem yok.')

    toplam_masraf = float(s['ToplamMasrafTL'] or 0)
    yontem = s['DagitimYontemi']
    siparis_kur = float(s['SiparisKur'] or 0)
    if siparis_kur <= 0:
        raise ValueError('Sipariş kuru yok. Önce siparişi onaylayın.')

    # H4: Yönteme göre eksik alan kontrolü (sert validation)
    if yontem == 'FOB':
        eksik = [k for k in kalemler if not (k['Tutar'] or 0) > 0]
        if eksik:
            raise ValueError(
                f"FOB bazlı dağıtım için tüm kalemlerde Tutar sıfırdan büyük olmalı. "
                f"{len(eksik)} kalem eksik (kalem ID: {', '.join(str(k['Id']) for k in eksik[:5])}{'...' if len(eksik)>5 else ''})."
            )
        alan = 'Tutar'
    elif yontem == 'MIKTAR':
        eksik = [k for k in kalemler if not (k['Miktar'] or 0) > 0]
        if eksik:
            raise ValueError(
                f"Adet bazlı dağıtım için tüm kalemlerde Miktar sıfırdan büyük olmalı. "
                f"{len(eksik)} kalem eksik (kalem ID: {', '.join(str(k['Id']) for k in eksik[:5])}{'...' if len(eksik)>5 else ''})."
            )
        alan = 'Miktar'
    elif yontem == 'AGIRLIK':
        eksik = [k for k in kalemler if not (k['AgirlikKg'] or 0) > 0]
        if eksik:
            eksik_ids = ', '.join(str(k['Id']) for k in eksik[:5]) + ('...' if len(eksik) > 5 else '')
            raise ValueError(
                f"Ağırlık bazlı dağıtım için kalemlerde kg değeri olmalı. "
                f"{len(eksik)}/{len(kalemler)} kalemde kg eksik (kalem ID: {eksik_ids}). "
                f"Sipariş detayından kalemlere kg girin veya başka bir dağıtım yöntemi seçin."
            )
        alan = 'AgirlikKg'
    elif yontem == 'HACIM':
        eksik = [k for k in kalemler if not (k['HacimM3'] or 0) > 0]
        if eksik:
            eksik_ids = ', '.join(str(k['Id']) for k in eksik[:5]) + ('...' if len(eksik) > 5 else '')
            raise ValueError(
                f"Hacim bazlı dağıtım için kalemlerde m³ değeri olmalı. "
                f"{len(eksik)}/{len(kalemler)} kalemde m³ eksik (kalem ID: {eksik_ids}). "
                f"Sipariş detayından kalemlere m³ girin veya başka bir dağıtım yöntemi seçin."
            )
        alan = 'HacimM3'
    elif yontem == 'MANUEL':
        if not manuel_oranlar:
            raise ValueError('Manuel yöntem için her kaleme oran girilmeli (% cinsinden).')
        top_oran = sum(float(v or 0) for v in manuel_oranlar.values())
        if abs(top_oran - 100) > 0.5:
            raise ValueError(
                f'Manuel oranların toplamı %100 olmalı. Şu anki toplam: %{top_oran:.2f}. '
                f'Eksik: %{100-top_oran:.2f}' if top_oran < 100 else
                f'Manuel oranların toplamı %100 olmalı. Şu anki toplam: %{top_oran:.2f} (fazla).'
            )
        alan = None
    else:
        raise ValueError(f"Geçersiz dağıtım yöntemi: {yontem}")

    if alan:
        toplam = sum(float(k[alan] or 0) for k in kalemler)

    # Eski dağıtımı sil
    qexec("DELETE FROM grafik_sevkiyat_dagitim WHERE SevkiyatId=?", (sevkiyat_id,))

    # H1: IsTahmini bayrağı — TESLIM ise kesinleşmiş, değilse tahmini
    is_tahmini = 0 if s['Durum'] == 'TESLIM' else 1

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for k in kalemler:
        if yontem == 'MANUEL':
            oran_yuzde = float(manuel_oranlar.get(str(k['Id']), manuel_oranlar.get(k['Id'], 0)) or 0)
            oran = oran_yuzde / 100.0
            dag_agirlik = oran_yuzde
        else:
            deger = float(k[alan] or 0)
            oran = deger / toplam if toplam > 0 else 0
            dag_agirlik = deger

        masraf_payi = round(toplam_masraf * oran, 2)
        fob_usd = float(k['Tutar'] or 0)
        fob_tl = round(fob_usd * siparis_kur, 2)
        toplam_tl = round(fob_tl + masraf_payi, 2)
        birim_tl = round(toplam_tl / k['Miktar'], 4) if k['Miktar'] else 0

        qexec("""INSERT INTO grafik_sevkiyat_dagitim
                 (SevkiyatId, KalemId, Yontem, DagitimAgirligi, MasrafPayiTL,
                  FOBUSDTutar, FOBTLTutar, ToplamTLTutar, BirimMaliyetTL, IsTahmini, OlusturmaTarih)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (sevkiyat_id, k['Id'], yontem, dag_agirlik, masraf_payi,
               fob_usd, fob_tl, toplam_tl, birim_tl, is_tahmini, now))

    qexec("UPDATE grafik_sevkiyat SET DagitimHesaplandi=1 WHERE Id=?", (sevkiyat_id,))
    tahmini_etk = "TAHMİNİ" if is_tahmini else "KESİNLEŞMİŞ"
    audit.log_olay(kullanici, 'DAGITIM_HESAP', 'grafik_sevkiyat', sevkiyat_id,
                   aciklama=f"Dağıtım hesaplandı [{tahmini_etk}]: {yontem} yöntemi, {len(kalemler)} kalem, {toplam_masraf:.0f} TRY",
                   modul='grafik', alt_modul='maliyet')
    return len(kalemler)


# ============================================================
# CARİ HESAP ÖZETİ (Sipariş/Sevkiyat detayında gösterilir)
# ============================================================

def siparis_cari_ozet(siparis_id):
    """
    Bir çin siparişinin cari hesap durumunu özetler:
    - Tedarikçi + Cari_Kart bilgisi
    - Bağlı finans anlaşması (TL borç)
    - Avans/ödeme toplamı (varsa)
    - Kalan bakiye
    """
    s = qone("""
        SELECT s.Id, s.SiparisNo, s.ToplamTutar AS FOBUSDToplam, s.KurSnapshot,
               s.FinansAnlasmaId,
               t.Ad AS TedarikciAd, t.Kod AS TedarikciKod, t.CariCKod,
               c.CName AS CariAd,
               fa.ProjeKod, fa.ToplamTutar AS AnlasmaBorcTL, fa.ParaBirimi AS AnlasmaPB,
               fa.Durum AS AnlasmaDurum
        FROM grafik_cin_siparis s
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        LEFT JOIN Cari_Kart c ON c.CKod = t.CariCKod
        LEFT JOIN finans_anlasma fa ON fa.Id = s.FinansAnlasmaId
        WHERE s.Id = ?
    """, (siparis_id,))
    if not s:
        return None

    sonuc = dict(s)
    sonuc['AvansToplamTL'] = 0.0
    sonuc['KalanTL'] = float(s['AnlasmaBorcTL'] or 0)
    sonuc['OdemeSayi'] = 0

    if s['FinansAnlasmaId']:
        # finans_avans tablosundan ödenenleri topla (tüm avanslar ödenmiş sayılır — schema'da Durum yok)
        try:
            odemeler = q("""
                SELECT COALESCE(SUM(Tutar),0) AS Toplam, COUNT(*) AS Sayi
                FROM finans_avans
                WHERE AnlasmaId = ?
            """, (s['FinansAnlasmaId'],))
            if odemeler:
                sonuc['AvansToplamTL'] = float(odemeler[0]['Toplam'] or 0)
                sonuc['OdemeSayi'] = int(odemeler[0]['Sayi'] or 0)
                sonuc['KalanTL'] = float(s['AnlasmaBorcTL'] or 0) - sonuc['AvansToplamTL']
        except Exception:
            pass
    return sonuc


def numune_siparisleri(numune_id):
    """K4: Bir numuneden oluşturulmuş siparişleri listele."""
    return q("""
        SELECT s.Id, s.SiparisNo, s.Durum, s.ToplamTutar, s.SiparisTarihi,
               s.FinansAnlasmaId, t.Ad AS TedarikciAd
        FROM grafik_cin_siparis s
        LEFT JOIN grafik_tedarikci t ON t.Id = s.TedarikciId
        WHERE s.KaynakNumuneId = ?
        ORDER BY s.OlusturmaTarih DESC
    """, (numune_id,))


# ============================================================
# FİYAT TEKLİFİ (Parça 2 — R5, R9, H3, V6)
# ============================================================

TEKLIF_DURUMLARI = [
    ('ALINDI',       'Alındı',         '#0891b2'),
    ('SIPARIS_OLDU', 'Siparişe Oldu',  '#059669'),
    ('REDDEDILDI',   'Reddedildi',     '#6b7280'),
    ('SURESI_GECTI', 'Süresi Geçti',   '#dc2626'),
]

ULKE_KODLARI = [
    ('CN', '🇨🇳 Çin'),
    ('TR', '🇹🇷 Türkiye'),
    ('EU', '🇪🇺 Avrupa'),
    ('OT', '🌐 Diğer'),
]


def _sonraki_teklif_no():
    from datetime import date
    yil = date.today().year
    son = qscalar("""SELECT MAX(CAST(SUBSTR(TeklifNo, 10) AS INTEGER))
                     FROM grafik_fiyat_teklif WHERE TeklifNo LIKE ?""",
                  (f"TKF-{yil}-%",)) or 0
    return f"TKF-{yil}-{son+1:04d}"


def teklif_kpi():
    return {
        'alindi':       qscalar("SELECT COUNT(*) FROM grafik_fiyat_teklif WHERE Durum='ALINDI'") or 0,
        'siparis_oldu': qscalar("SELECT COUNT(*) FROM grafik_fiyat_teklif WHERE Durum='SIPARIS_OLDU'") or 0,
        'reddedildi':   qscalar("SELECT COUNT(*) FROM grafik_fiyat_teklif WHERE Durum='REDDEDILDI'") or 0,
        'suresi':       qscalar("SELECT COUNT(*) FROM grafik_fiyat_teklif WHERE Durum='SURESI_GECTI'") or 0,
        'toplam':       qscalar("SELECT COUNT(*) FROM grafik_fiyat_teklif") or 0,
    }


def teklif_liste(arama=None, durum=None, ulke=None):
    ks = ["1=1"]
    params = []
    if arama:
        ks.append("(t.TeklifNo LIKE ? OR t.TedarikciAd LIKE ? OR t.UrunAd LIKE ?)")
        params.extend([f'%{arama}%']*3)
    if durum:
        ks.append("t.Durum = ?")
        params.append(durum)
    if ulke:
        ks.append("t.UlkeKodu = ?")
        params.append(ulke)
    where = " AND ".join(ks)
    return q(f"""
        SELECT t.*,
               td.Ad AS KayitliTedarikciAd,
               c.CName AS MusteriAd,
               s.SiparisNo AS DonusumSiparisNo
        FROM grafik_fiyat_teklif t
        LEFT JOIN grafik_tedarikci td ON td.Id = t.TedarikciId
        LEFT JOIN Cari_Kart c ON c.CKod = t.MusteriCKod
        LEFT JOIN grafik_cin_siparis s ON s.Id = t.SiparisId
        WHERE {where}
        ORDER BY t.OlusturmaTarih DESC
    """, tuple(params))


def teklif_tek(teklif_id):
    return qone("""
        SELECT t.*,
               td.Ad AS KayitliTedarikciAd, td.Kod AS TedarikciKod, td.Ulke AS TedarikciUlke,
               c.CName AS MusteriAd,
               s.SiparisNo AS DonusumSiparisNo
        FROM grafik_fiyat_teklif t
        LEFT JOIN grafik_tedarikci td ON td.Id = t.TedarikciId
        LEFT JOIN Cari_Kart c ON c.CKod = t.MusteriCKod
        LEFT JOIN grafik_cin_siparis s ON s.Id = t.SiparisId
        WHERE t.Id = ?
    """, (teklif_id,))


def teklif_ekle(veri, kullanici):
    """
    R9/H3: Kur snapshot teklif tarihindeki merkez bankası kurundan bir kere alınır.
    Sonradan güncellemede kur değişmez.
    """
    from datetime import date
    pb = (veri.get('ParaBirimi') or 'USD').upper()
    if pb not in ('TRY', 'USD', 'EUR', 'CNY'):
        raise ValueError('Para birimi TRY/USD/EUR/CNY olmalı.')

    miktar = float(veri.get('Miktar') or 0)
    bf = float(veri.get('BirimFiyat') or 0)
    if miktar <= 0 or bf <= 0:
        raise ValueError('Miktar ve Birim Fiyat > 0 olmalı.')
    toplam = round(miktar * bf, 2)

    # Kur snapshot
    if pb == 'TRY':
        kur = 1.0
    else:
        from modules.yonetim.queries import kur_guncel
        kr = kur_guncel(pb)
        if not kr:
            raise ValueError(f'{pb} kuru tanımlı değil. Önce /yonetim/kur\'dan girin.')
        kur = float(kr['MerkezKur'])

    # Tedarikçi: ya kayıtlı ID ya da serbest metin
    ted_id = veri.get('TedarikciId')
    ted_ad = veri.get('TedarikciAd', '').strip() or None
    if ted_id:
        ted_id = int(ted_id)
        r = qone("SELECT Ad FROM grafik_tedarikci WHERE Id=?", (ted_id,))
        if not r:
            raise ValueError('Tedarikçi bulunamadı.')
        ted_ad = r['Ad']
    elif not ted_ad:
        raise ValueError('Tedarikçi seç veya adını yaz.')

    no = _sonraki_teklif_no()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tid = qexec("""INSERT INTO grafik_fiyat_teklif
                   (TeklifNo, UlkeKodu, TedarikciId, TedarikciAd, MusteriCKod,
                    UrunAd, UrunKodu, Miktar, BirimFiyat, ParaBirimi,
                    KurSnapshot, ToplamTutar, TeklifTarihi, GecerlilikTarihi,
                    Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ALINDI', ?, ?, ?)""",
                (no,
                 (veri.get('UlkeKodu') or 'CN').upper(),
                 ted_id, ted_ad,
                 veri.get('MusteriCKod') or None,
                 veri.get('UrunAd', '').strip() or None,
                 veri.get('UrunKodu', '').strip() or None,
                 miktar, bf, pb, kur, toplam,
                 veri.get('TeklifTarihi') or date.today().strftime('%Y-%m-%d'),
                 veri.get('GecerlilikTarihi') or None,
                 veri.get('Notlar', '').strip() or None,
                 now, kullanici))
    audit.log_ekle(kullanici, 'grafik_fiyat_teklif', tid,
                   aciklama=f"Teklif alındı: {no} — {ted_ad} / {miktar} × {bf} {pb} (kur {kur:.4f})",
                   modul='grafik', alt_modul='teklif')
    return tid, no


def teklif_guncelle(teklif_id, veri, kullanici):
    """Kur değişmez — sadece diğer alanlar güncellenebilir."""
    eski = teklif_tek(teklif_id)
    if not eski:
        raise ValueError('Teklif bulunamadı.')
    if eski['Durum'] == 'SIPARIS_OLDU':
        raise ValueError('Siparişe çevrilen teklif güncellenemez.')

    miktar = float(veri.get('Miktar') or eski['Miktar'])
    bf = float(veri.get('BirimFiyat') or eski['BirimFiyat'])
    toplam = round(miktar * bf, 2)

    yeni = {
        'UlkeKodu':         (veri.get('UlkeKodu') or eski['UlkeKodu']).upper(),
        'TedarikciAd':      veri.get('TedarikciAd') or eski['TedarikciAd'],
        'MusteriCKod':      veri.get('MusteriCKod') or None,
        'UrunAd':           veri.get('UrunAd') or None,
        'UrunKodu':         veri.get('UrunKodu') or None,
        'Miktar':           miktar,
        'BirimFiyat':       bf,
        'ToplamTutar':      toplam,
        'GecerlilikTarihi': veri.get('GecerlilikTarihi') or None,
        'Notlar':           veri.get('Notlar') or None,
    }
    qexec("""UPDATE grafik_fiyat_teklif
             SET UlkeKodu=?, TedarikciAd=?, MusteriCKod=?, UrunAd=?, UrunKodu=?,
                 Miktar=?, BirimFiyat=?, ToplamTutar=?,
                 GecerlilikTarihi=?, Notlar=?
             WHERE Id=?""",
          (yeni['UlkeKodu'], yeni['TedarikciAd'], yeni['MusteriCKod'],
           yeni['UrunAd'], yeni['UrunKodu'],
           yeni['Miktar'], yeni['BirimFiyat'], yeni['ToplamTutar'],
           yeni['GecerlilikTarihi'], yeni['Notlar'], teklif_id))
    audit.log_duzenle_coklu(kullanici, 'grafik_fiyat_teklif', teklif_id,
                            dict(eski), yeni, modul='grafik', alt_modul='teklif')


def teklif_durum_degistir(teklif_id, yeni_durum, kullanici):
    eski = teklif_tek(teklif_id)
    if not eski:
        raise ValueError('Teklif bulunamadı.')
    if yeni_durum not in [d[0] for d in TEKLIF_DURUMLARI]:
        raise ValueError(f"Geçersiz durum: {yeni_durum}")
    if eski['Durum'] == 'SIPARIS_OLDU' and yeni_durum != 'SIPARIS_OLDU':
        raise ValueError('Siparişe çevrilen teklif geri alınamaz.')
    qexec("UPDATE grafik_fiyat_teklif SET Durum=? WHERE Id=?", (yeni_durum, teklif_id))
    audit.log_olay(kullanici, 'DURUM_DEGIS', 'grafik_fiyat_teklif', teklif_id,
                   aciklama=f"Durum: {eski['Durum']} → {yeni_durum}",
                   modul='grafik', alt_modul='teklif')


def teklif_siparise_donustur(teklif_id, kullanici):
    """
    R9/H3: Teklifteki kur aynen siparişe taşınır.
    Yalnız CN (Çin) teklifleri için çalışır — diğer ülke siparişleri henüz modülleşmedi.
    """
    t = teklif_tek(teklif_id)
    if not t:
        raise ValueError('Teklif bulunamadı.')
    if t['Durum'] == 'SIPARIS_OLDU':
        raise ValueError('Bu teklif zaten siparişe çevrilmiş.')
    if t['Durum'] == 'REDDEDILDI':
        raise ValueError('Reddedilmiş teklif siparişe çevrilemez.')
    if t['UlkeKodu'] != 'CN':
        raise ValueError('Şu anda sadece Çin teklifleri siparişe çevrilebiliyor. TR/EU için modül hazırlanacak.')
    if not t['TedarikciId']:
        raise ValueError('Tedarikçi kayıtlı değil. Önce /grafik/tedarikci\'den ekleyin ve teklifi güncelleyin.')

    from datetime import date
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    no = _sonraki_siparis_no()

    sid = qexec("""INSERT INTO grafik_cin_siparis
                   (SiparisNo, TedarikciId, KaynakNumuneId, KaynakTeklifId,
                    MusteriCKod, SiparisTarihi, BeklenenCikisTarihi,
                    ParaBirimi, KurSnapshot, ToplamTutar, Durum, Notlar,
                    OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?, 'TASLAK', ?, ?, ?)""",
                (no, t['TedarikciId'], teklif_id,
                 t['MusteriCKod'],
                 date.today().strftime('%Y-%m-%d'),
                 t['ParaBirimi'], t['KurSnapshot'], t['ToplamTutar'],
                 f"Teklif {t['TeklifNo']} üzerinden oluşturuldu.\n{t['Notlar'] or ''}",
                 now, kullanici))

    # İlk kalem olarak teklif ürününü ekle
    if t['UrunAd']:
        qexec("""INSERT INTO grafik_cin_siparis_kalem
                 (SiparisId, Aciklama, Miktar, BirimFiyat, Tutar, OlusturmaTarih)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (sid,
               f"{t['UrunAd']}" + (f" ({t['UrunKodu']})" if t['UrunKodu'] else ''),
               int(t['Miktar']), t['BirimFiyat'], t['ToplamTutar'], now))
        # Toplam güncelle (kalem tek olduğu için zaten doğru ama yine de)
        _siparis_toplam_guncelle(sid)

    # Teklifi siparişe bağla
    qexec("UPDATE grafik_fiyat_teklif SET Durum='SIPARIS_OLDU', SiparisId=? WHERE Id=?",
          (sid, teklif_id))

    audit.log_olay(kullanici, 'TEKLIF_SIPARIS', 'grafik_fiyat_teklif', teklif_id,
                   aciklama=f"Teklif → Sipariş: {t['TeklifNo']} → {no} (kur {t['KurSnapshot']:.4f} taşındı)",
                   modul='grafik', alt_modul='teklif')
    return sid, no


def teklif_sil(teklif_id, kullanici):
    t = teklif_tek(teklif_id)
    if not t:
        return False
    if t['Durum'] == 'SIPARIS_OLDU':
        raise ValueError('Siparişe çevrilmiş teklif silinemez. Önce siparişi iptal edin.')
    qexec("DELETE FROM grafik_fiyat_teklif WHERE Id=?", (teklif_id,))
    audit.log_sil(kullanici, 'grafik_fiyat_teklif', teklif_id,
                  aciklama=f"Teklif silindi: {t['TeklifNo']}",
                  modul='grafik', alt_modul='teklif')
    return True


# ============================================================
# SÜREÇ AKIŞ ÇUBUĞU (Parça 3 — R11, H6)
# ============================================================

def siparis_akis(siparis_id):
    """
    Bir sipariş için 8 adım bayrağı + uyarılar döndürür.
    Template _akis_cubugu.html tarafından kullanılır.
    """
    s = siparis_tek(siparis_id)
    if not s:
        return {}

    # Teklif varlığı
    teklif = qone("SELECT Id FROM grafik_fiyat_teklif WHERE SiparisId=?", (siparis_id,))
    # İlk sevkiyat (varsa)
    sevkiyat = qone("""SELECT Id, Durum, ToplamMasrafTL FROM grafik_sevkiyat
                       WHERE SiparisId=? ORDER BY OlusturmaTarih DESC LIMIT 1""",
                    (siparis_id,))
    # Dağıtımda IsTahmini=0 var mı?
    gercek_dag = False
    if sevkiyat:
        gercek_dag = (qscalar("""SELECT COUNT(*) FROM grafik_sevkiyat_dagitim
                                 WHERE SevkiyatId=? AND IsTahmini=0""",
                              (sevkiyat['Id'],)) or 0) > 0

    durum = s['Durum']
    akis = {
        'adim_fiyat':    teklif is not None,
        'adim_siparis':  True,
        'adim_onay':     durum in ('ONAYLANDI', 'URETILIYOR', 'HAZIR', 'SEVKEDILDI', 'TAMAMLANDI'),
        'adim_uretim':   durum in ('URETILIYOR', 'HAZIR', 'SEVKEDILDI', 'TAMAMLANDI'),
        'adim_sevkiyat': sevkiyat is not None,
        'adim_masraf':   sevkiyat is not None and (sevkiyat['ToplamMasrafTL'] or 0) > 0,
        'adim_teslim':   sevkiyat is not None and sevkiyat['Durum'] == 'TESLIM',
        'adim_gercek':   gercek_dag,
        'siparis_no':    s['SiparisNo'],
        'teklif_id':     teklif['Id'] if teklif else None,
        'sevkiyat_id':   sevkiyat['Id'] if sevkiyat else None,
    }

    # Uyarılar (yumuşak, eksik adımı göster)
    uyarilar = []
    if akis['adim_onay'] and not akis['adim_sevkiyat']:
        uyarilar.append(('Sipariş onaylandı ama sevkiyat açılmamış.', '/grafik/sevkiyat'))
    if akis['adim_sevkiyat'] and not akis['adim_masraf']:
        uyarilar.append((f"Sevkiyat açık ama masraf girilmemiş.",
                        f'/grafik/sevkiyat/{sevkiyat["Id"]}'))
    if akis['adim_teslim'] and not akis['adim_gercek']:
        uyarilar.append(('Teslim alındı ama dağıtım hesaplanmamış — gerçek birim maliyet oluşmamış.',
                        f'/grafik/sevkiyat/{sevkiyat["Id"]}'))
    if durum == 'TASLAK':
        uyarilar.append(('Sipariş TASLAK — kalemleri tamamlayıp onayla.', None))

    akis['uyarilar'] = uyarilar
    return akis


def sevkiyat_akis(sevkiyat_id):
    """Sevkiyat detay sayfası için akış (ana kaynak siparis_akis)."""
    sv = sevkiyat_tek(sevkiyat_id)
    if not sv:
        return {}
    if sv['SiparisId']:
        akis = siparis_akis(sv['SiparisId'])
        # Sevkiyat detayındayız: bu sevkiyat ID'sini üste yaz
        akis['sevkiyat_id'] = sevkiyat_id
        return akis
    # Siparişsiz (DHL numune) sevkiyat — mini akış
    gercek = (qscalar("""SELECT COUNT(*) FROM grafik_sevkiyat_dagitim
                         WHERE SevkiyatId=? AND IsTahmini=0""", (sevkiyat_id,)) or 0) > 0
    return {
        'adim_fiyat':    False,
        'adim_siparis':  False,
        'adim_onay':     False,
        'adim_uretim':   False,
        'adim_sevkiyat': True,
        'adim_masraf':   (sv['ToplamMasrafTL'] or 0) > 0,
        'adim_teslim':   sv['Durum'] == 'TESLIM',
        'adim_gercek':   gercek,
        'sevkiyat_id':   sevkiyat_id,
        'uyarilar':      [('DHL numune sevkiyatı — sipariş zinciri dışı.', None)],
    }
