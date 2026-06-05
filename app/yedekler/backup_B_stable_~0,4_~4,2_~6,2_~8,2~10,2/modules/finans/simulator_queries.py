# -*- coding: utf-8 -*-
"""
CPS DEV — Ön Maliyet ve Karar Simülatörü (Parça 7a)
Finans modülü altında — /finans/simulator

Bu modül:
- Simülasyon + seçenek CRUD
- Hesaplama motoru (FOB, nakliye, vergi, ek, marj)
- Geçmiş veri kıyas motoru (4 kıyas: navlun, tedarikçi, birim maliyet, marj)
- Kural bazlı yorum üretimi (deterministik)
- Öneri skoru hesaplama (maliyet %50 + marj %30 + süre %20)
"""
from datetime import datetime, timedelta, date
from db import q, qone, qexec, qscalar
from modules import audit


# Sabit değerler
DURUMLAR = ['TASLAK', 'KARAR', 'ARSIVLENMIS']


# =========================================================
# SERİ NUMARASI
# =========================================================
def _sonraki_simulasyon_no():
    yil = date.today().year
    son = qscalar("""SELECT MAX(CAST(SUBSTR(SimulasyonNo, 10) AS INTEGER))
                     FROM finans_simulasyon WHERE SimulasyonNo LIKE ?""",
                  (f'SIM-{yil}-%',)) or 0
    return f'SIM-{yil}-{son + 1:04d}'


# =========================================================
# SIMÜLASYON CRUD
# =========================================================
def simulasyon_liste(durum=None):
    where = ''
    params = []
    if durum:
        where = 'WHERE s.Durum = ?'
        params.append(durum)
    return q(f"""
        SELECT s.*,
               (SELECT COUNT(*) FROM finans_simulasyon_secenek WHERE SimulasyonId = s.Id) AS SecenekSayisi,
               (SELECT Etiket FROM finans_simulasyon_secenek WHERE Id = s.SecilenSecenekId) AS SecilenEtiket
        FROM finans_simulasyon s
        {where}
        ORDER BY s.OlusturmaTarih DESC
    """, params)


def simulasyon_tek(sim_id):
    return qone("SELECT * FROM finans_simulasyon WHERE Id=?", (sim_id,))


def simulasyon_olustur(veri, kullanici):
    baslik = (veri.get('Baslik') or '').strip()
    if not baslik:
        raise ValueError('Başlık zorunlu.')
    try:
        hedef_miktar = int(veri.get('HedefMiktar') or 0)
    except (TypeError, ValueError):
        raise ValueError('Hedef miktar geçerli bir sayı olmalı.')
    if hedef_miktar <= 0:
        raise ValueError('Hedef miktar sıfırdan büyük olmalı.')

    hedef_satis = veri.get('HedefCiftSatis')
    if hedef_satis not in (None, ''):
        try:
            hedef_satis = float(hedef_satis)
            if hedef_satis <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError('Hedef satış fiyatı geçerli bir pozitif sayı olmalı.')
    else:
        hedef_satis = None

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sno = _sonraki_simulasyon_no()
    sid = qexec("""INSERT INTO finans_simulasyon
                   (SimulasyonNo, Baslik, UrunAdi, HedefMiktar, HedefCiftSatis,
                    HedefTeslimTarih, Notlar, Durum, OlusturmaTarih, OlusturanKullanici)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'TASLAK', ?, ?)""",
                (sno, baslik, veri.get('UrunAdi') or None, hedef_miktar, hedef_satis,
                 veri.get('HedefTeslimTarih') or None, veri.get('Notlar') or None,
                 now, kullanici))
    audit.log_olay(kullanici, 'SIMULASYON_OLUSTUR', 'finans_simulasyon', sid,
                   aciklama=f'Simülasyon oluşturuldu: {sno} — {baslik}',
                   modul='finans', alt_modul='simulator')
    return sid, sno


def simulasyon_guncelle(sim_id, veri, kullanici):
    s = simulasyon_tek(sim_id)
    if not s:
        raise ValueError('Simülasyon bulunamadı.')
    if s['Durum'] == 'KARAR':
        raise ValueError('Karar verilmiş simülasyon değiştirilemez. Önce karardan çıkarın.')

    hedef_satis = veri.get('HedefCiftSatis')
    if hedef_satis not in (None, ''):
        try:
            hedef_satis = float(hedef_satis)
        except (TypeError, ValueError):
            raise ValueError('Hedef satış fiyatı geçerli bir sayı olmalı.')
    else:
        hedef_satis = None

    qexec("""UPDATE finans_simulasyon
             SET Baslik=?, UrunAdi=?, HedefMiktar=?, HedefCiftSatis=?,
                 HedefTeslimTarih=?, Notlar=?
             WHERE Id=?""",
          (veri.get('Baslik', s['Baslik']),
           veri.get('UrunAdi') or None,
           int(veri.get('HedefMiktar') or s['HedefMiktar']),
           hedef_satis,
           veri.get('HedefTeslimTarih') or None,
           veri.get('Notlar') or None,
           sim_id))
    # Satış fiyatı değiştiyse tüm seçeneklerin marjını yeniden hesapla
    _tum_secenekleri_yeniden_hesapla(sim_id)
    audit.log_olay(kullanici, 'SIMULASYON_GUNCELLE', 'finans_simulasyon', sim_id,
                   modul='finans', alt_modul='simulator')


def simulasyon_sil(sim_id, kullanici):
    s = simulasyon_tek(sim_id)
    if not s:
        return False
    if s['Durum'] == 'KARAR':
        raise ValueError('Karar verilmiş simülasyon silinemez. Önce arşivleyin.')
    qexec("DELETE FROM finans_simulasyon WHERE Id=?", (sim_id,))
    audit.log_olay(kullanici, 'SIMULASYON_SIL', 'finans_simulasyon', sim_id,
                   aciklama=f'Silindi: {s["SimulasyonNo"]}',
                   modul='finans', alt_modul='simulator')
    return True


def simulasyon_karar(sim_id, secenek_id, kullanici):
    s = simulasyon_tek(sim_id)
    if not s:
        raise ValueError('Simülasyon bulunamadı.')
    if s['Durum'] == 'ARSIVLENMIS':
        raise ValueError('Arşivlenmiş simülasyonda karar değiştirilemez.')
    sc = qone("SELECT Etiket FROM finans_simulasyon_secenek WHERE Id=? AND SimulasyonId=?",
              (secenek_id, sim_id))
    if not sc:
        raise ValueError('Seçenek bu simülasyona ait değil.')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    qexec("""UPDATE finans_simulasyon
             SET Durum='KARAR', SecilenSecenekId=?, KararVerenKullanici=?, KararTarihi=?
             WHERE Id=?""",
          (secenek_id, kullanici, now, sim_id))
    audit.log_olay(kullanici, 'SIMULASYON_KARAR', 'finans_simulasyon', sim_id,
                   aciklama=f'Karar: {s["SimulasyonNo"]} → Seçenek "{sc["Etiket"]}" seçildi',
                   modul='finans', alt_modul='simulator')


def simulasyon_arsivle(sim_id, kullanici):
    s = simulasyon_tek(sim_id)
    if not s:
        return False
    qexec("UPDATE finans_simulasyon SET Durum='ARSIVLENMIS' WHERE Id=?", (sim_id,))
    audit.log_olay(kullanici, 'SIMULASYON_ARSIVLE', 'finans_simulasyon', sim_id,
                   aciklama=f'Arşivlendi: {s["SimulasyonNo"]}',
                   modul='finans', alt_modul='simulator')
    return True


# =========================================================
# HESAPLAMA MOTORU
# =========================================================
def _toplam_hesapla(veri, hedef_miktar, hedef_satis):
    """
    Ham form verisinden toplam maliyet + birim + marj hesaplar.
    Canlı hesap API + secenek_ekle/guncelle içinde kullanılır.
    """
    def f(x, d=0.0):
        try:
            return float(x or d)
        except (TypeError, ValueError):
            return d

    birim_fiyat = f(veri.get('BirimFiyat'))
    kur = f(veri.get('KurSnapshot'), 1.0)
    nakliye_sabit = f(veri.get('NakliyeSabitMaliyet'))
    nakliye_birim = f(veri.get('NakliyeBirimMaliyet'))
    nakliye_kg = f(veri.get('NakliyeAgirlikKg'))
    nakliye_kur = f(veri.get('NakliyeKur'), 1.0)
    vergi_yuzde = f(veri.get('GumrukVergisiYuzde'))
    sigorta_yuzde = f(veri.get('SigortaYuzde'))
    musavir = f(veri.get('MusavirMaliyeti'))
    diger = f(veri.get('DigerMaliyet'))

    toplam_fob = birim_fiyat * hedef_miktar * kur
    toplam_nakliye = (nakliye_sabit * nakliye_kur) + (nakliye_birim * nakliye_kg * nakliye_kur)
    toplam_sigorta = toplam_fob * sigorta_yuzde / 100
    toplam_vergi = (toplam_fob + toplam_nakliye + toplam_sigorta) * vergi_yuzde / 100
    toplam_extras = musavir + diger
    toplam_tl = toplam_fob + toplam_nakliye + toplam_sigorta + toplam_vergi + toplam_extras

    birim_tl = toplam_tl / hedef_miktar if hedef_miktar > 0 else 0
    kg_tl = toplam_tl / nakliye_kg if nakliye_kg > 0 else 0

    marj = None
    if hedef_satis and hedef_satis > 0:
        marj = (hedef_satis - birim_tl) / hedef_satis * 100

    return {
        'ToplamFOB': round(toplam_fob, 2),
        'ToplamNakliye': round(toplam_nakliye, 2),
        'ToplamSigorta': round(toplam_sigorta, 2),
        'ToplamVergi': round(toplam_vergi, 2),
        'ToplamExtras': round(toplam_extras, 2),
        'ToplamMaliyetTL': round(toplam_tl, 2),
        'BirimMaliyetTL': round(birim_tl, 4),
        'KgMaliyetTL': round(kg_tl, 4),
        'MarjYuzde': round(marj, 2) if marj is not None else None,
    }


def _tum_secenekleri_yeniden_hesapla(sim_id):
    """Satış fiyatı değişince tüm seçenek marjlarını günceller."""
    s = simulasyon_tek(sim_id)
    if not s:
        return
    for sc in q("SELECT * FROM finans_simulasyon_secenek WHERE SimulasyonId=?", (sim_id,)):
        hesap = _toplam_hesapla(dict(sc), s['HedefMiktar'], s['HedefCiftSatis'])
        qexec("""UPDATE finans_simulasyon_secenek
                 SET ToplamMaliyetTL=?, BirimMaliyetTL=?, KgMaliyetTL=?, MarjYuzde=?
                 WHERE Id=?""",
              (hesap['ToplamMaliyetTL'], hesap['BirimMaliyetTL'],
               hesap['KgMaliyetTL'], hesap['MarjYuzde'], sc['Id']))


# =========================================================
# SEÇENEK CRUD
# =========================================================
def secenek_liste(sim_id):
    return q("SELECT * FROM finans_simulasyon_secenek WHERE SimulasyonId=? ORDER BY Sira ASC, Id ASC",
             (sim_id,))


def secenek_tek(sec_id):
    return qone("SELECT * FROM finans_simulasyon_secenek WHERE Id=?", (sec_id,))


def secenek_ekle(sim_id, veri, kullanici):
    s = simulasyon_tek(sim_id)
    if not s:
        raise ValueError('Simülasyon bulunamadı.')
    if s['Durum'] == 'ARSIVLENMIS':
        raise ValueError('Arşivlenmiş simülasyona seçenek eklenemez.')

    etiket = (veri.get('Etiket') or '').strip()
    if not etiket:
        raise ValueError('Seçenek etiketi zorunlu.')

    # Validation: negatif değer yasağı
    for alan in ['BirimFiyat', 'KurSnapshot', 'NakliyeSabitMaliyet', 'NakliyeBirimMaliyet',
                 'NakliyeAgirlikKg', 'GumrukVergisiYuzde', 'SigortaYuzde',
                 'MusavirMaliyeti', 'DigerMaliyet']:
        try:
            val = float(veri.get(alan) or 0)
            if val < 0:
                raise ValueError(f'{alan} negatif olamaz.')
        except (TypeError, ValueError):
            raise ValueError(f'{alan} geçerli bir sayı olmalı.')

    hesap = _toplam_hesapla(veri, s['HedefMiktar'], s['HedefCiftSatis'])
    sira = (qscalar("SELECT MAX(Sira) FROM finans_simulasyon_secenek WHERE SimulasyonId=?",
                    (sim_id,)) or 0) + 1
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sec_id = qexec("""INSERT INTO finans_simulasyon_secenek
                      (SimulasyonId, Sira, Etiket, Ulke, TedarikciAd, TedarikciId, KaynakTeklifId,
                       BirimFiyat, ParaBirimi, KurSnapshot,
                       NakliyeTipi, NakliyeGunSuresi, NakliyeSabitMaliyet, NakliyeBirimMaliyet,
                       NakliyeParaBirimi, NakliyeKur, NakliyeAgirlikKg,
                       GumrukVergisiYuzde, SigortaYuzde, MusavirMaliyeti, DigerMaliyet, DigerMaliyetAciklama,
                       ToplamFOB, ToplamNakliye, ToplamSigorta, ToplamVergi, ToplamExtras,
                       ToplamMaliyetTL, BirimMaliyetTL, KgMaliyetTL, MarjYuzde,
                       Notlar, OlusturmaTarih, OlusturanKullanici)
                      VALUES (?, ?, ?, ?, ?, ?, ?,  ?, ?, ?,  ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?,  ?, ?, ?)""",
                   (sim_id, sira, etiket,
                    veri.get('Ulke') or None,
                    veri.get('TedarikciAd') or None,
                    veri.get('TedarikciId') or None,
                    veri.get('KaynakTeklifId') or None,
                    float(veri.get('BirimFiyat') or 0),
                    (veri.get('ParaBirimi') or 'USD').upper(),
                    float(veri.get('KurSnapshot') or 1.0),
                    (veri.get('NakliyeTipi') or '').upper() or None,
                    int(veri.get('NakliyeGunSuresi') or 0),
                    float(veri.get('NakliyeSabitMaliyet') or 0),
                    float(veri.get('NakliyeBirimMaliyet') or 0),
                    (veri.get('NakliyeParaBirimi') or 'USD').upper(),
                    float(veri.get('NakliyeKur') or 1.0),
                    float(veri.get('NakliyeAgirlikKg') or 0),
                    float(veri.get('GumrukVergisiYuzde') or 18),
                    float(veri.get('SigortaYuzde') or 0.5),
                    float(veri.get('MusavirMaliyeti') or 0),
                    float(veri.get('DigerMaliyet') or 0),
                    veri.get('DigerMaliyetAciklama') or None,
                    hesap['ToplamFOB'], hesap['ToplamNakliye'], hesap['ToplamSigorta'],
                    hesap['ToplamVergi'], hesap['ToplamExtras'],
                    hesap['ToplamMaliyetTL'], hesap['BirimMaliyetTL'], hesap['KgMaliyetTL'],
                    hesap['MarjYuzde'],
                    veri.get('Notlar') or None, now, kullanici))
    audit.log_olay(kullanici, 'SECENEK_EKLE', 'finans_simulasyon_secenek', sec_id,
                   aciklama=f'Seçenek: {etiket} — {hesap["ToplamMaliyetTL"]:,.0f} TL',
                   modul='finans', alt_modul='simulator')
    return sec_id


def secenek_guncelle(sec_id, veri, kullanici):
    sc = secenek_tek(sec_id)
    if not sc:
        raise ValueError('Seçenek bulunamadı.')
    s = simulasyon_tek(sc['SimulasyonId'])
    if s['Durum'] == 'ARSIVLENMIS':
        raise ValueError('Arşivlenmiş simülasyondaki seçenek düzenlenemez.')

    hesap = _toplam_hesapla(veri, s['HedefMiktar'], s['HedefCiftSatis'])
    qexec("""UPDATE finans_simulasyon_secenek SET
             Etiket=?, Ulke=?, TedarikciAd=?, TedarikciId=?, KaynakTeklifId=?,
             BirimFiyat=?, ParaBirimi=?, KurSnapshot=?,
             NakliyeTipi=?, NakliyeGunSuresi=?, NakliyeSabitMaliyet=?, NakliyeBirimMaliyet=?,
             NakliyeParaBirimi=?, NakliyeKur=?, NakliyeAgirlikKg=?,
             GumrukVergisiYuzde=?, SigortaYuzde=?, MusavirMaliyeti=?, DigerMaliyet=?, DigerMaliyetAciklama=?,
             ToplamFOB=?, ToplamNakliye=?, ToplamSigorta=?, ToplamVergi=?, ToplamExtras=?,
             ToplamMaliyetTL=?, BirimMaliyetTL=?, KgMaliyetTL=?, MarjYuzde=?,
             Notlar=?
             WHERE Id=?""",
          ((veri.get('Etiket') or sc['Etiket']).strip(),
           veri.get('Ulke') or sc['Ulke'],
           veri.get('TedarikciAd') or sc['TedarikciAd'],
           veri.get('TedarikciId') or sc['TedarikciId'],
           veri.get('KaynakTeklifId') or sc['KaynakTeklifId'],
           float(veri.get('BirimFiyat') or 0),
           (veri.get('ParaBirimi') or 'USD').upper(),
           float(veri.get('KurSnapshot') or 1.0),
           (veri.get('NakliyeTipi') or '').upper() or None,
           int(veri.get('NakliyeGunSuresi') or 0),
           float(veri.get('NakliyeSabitMaliyet') or 0),
           float(veri.get('NakliyeBirimMaliyet') or 0),
           (veri.get('NakliyeParaBirimi') or 'USD').upper(),
           float(veri.get('NakliyeKur') or 1.0),
           float(veri.get('NakliyeAgirlikKg') or 0),
           float(veri.get('GumrukVergisiYuzde') or 18),
           float(veri.get('SigortaYuzde') or 0.5),
           float(veri.get('MusavirMaliyeti') or 0),
           float(veri.get('DigerMaliyet') or 0),
           veri.get('DigerMaliyetAciklama') or None,
           hesap['ToplamFOB'], hesap['ToplamNakliye'], hesap['ToplamSigorta'],
           hesap['ToplamVergi'], hesap['ToplamExtras'],
           hesap['ToplamMaliyetTL'], hesap['BirimMaliyetTL'], hesap['KgMaliyetTL'],
           hesap['MarjYuzde'],
           veri.get('Notlar') or None,
           sec_id))
    audit.log_olay(kullanici, 'SECENEK_GUNCELLE', 'finans_simulasyon_secenek', sec_id,
                   modul='finans', alt_modul='simulator')


def secenek_sil(sec_id, kullanici):
    sc = secenek_tek(sec_id)
    if not sc:
        return False
    s = simulasyon_tek(sc['SimulasyonId'])
    if s['SecilenSecenekId'] == sec_id:
        raise ValueError('Karar verilmiş seçenek silinemez.')
    qexec("DELETE FROM finans_simulasyon_secenek WHERE Id=?", (sec_id,))
    audit.log_olay(kullanici, 'SECENEK_SIL', 'finans_simulasyon_secenek', sec_id,
                   aciklama=f'Silindi: {sc["Etiket"]}',
                   modul='finans', alt_modul='simulator')
    return True


# =========================================================
# GEÇMİŞ KIYAS MOTORU (Parça 7a özellik)
# =========================================================
# Minimum örnek eşikleri
MIN_NAVLUN = 3
MIN_TEDARIKCI = 2
MIN_BIRIM_MAL = 5
MIN_MARJ = 3


def _gecmis_tarih(ay):
    return (date.today() - timedelta(days=ay * 30)).strftime('%Y-%m-%d')


def _yorum_etiket(fark_yuzde, tur):
    """Kurallar → yorum + renk."""
    if tur == 'navlun':
        if fark_yuzde <= -10: return ('belirgin ucuz', 'yesil', 'daha ucuz')
        if fark_yuzde <= -3:  return ('ortalamanın altında', 'yesil', 'daha ucuz')
        if fark_yuzde <= 3:   return ('ortalama seviyede', 'gri', 'benzer')
        if fark_yuzde <= 10:  return ('biraz pahalı', 'turuncu', 'daha pahalı')
        return ('belirgin pahalı', 'kirmizi', 'daha pahalı')
    if tur == 'tedarikci':
        if fark_yuzde <= -5: return ('geçmiş fiyatın altında', 'yesil', 'daha ucuz')
        if fark_yuzde <= 5:  return ('geçmiş fiyat seviyesinde', 'gri', 'benzer')
        if fark_yuzde <= 15: return ('geçmiş siparişe göre daha pahalı', 'turuncu', 'daha pahalı')
        return ('belirgin fiyat artışı', 'kirmizi', 'daha pahalı')
    if tur == 'birim_mal':
        if fark_yuzde <= -10: return ('ortalamanın belirgin altında', 'yesil', 'daha düşük')
        if fark_yuzde <= -3:  return ('ortalamanın altında', 'yesil', 'daha düşük')
        if fark_yuzde <= 3:   return ('ortalamaya yakın', 'gri', 'benzer')
        if fark_yuzde <= 10:  return ('ortalamanın üstünde', 'turuncu', 'daha yüksek')
        return ('ortalamanın belirgin üstünde', 'kirmizi', 'daha yüksek')
    return ('', 'gri', '')


def _navlun_birim_maliyet(sevkiyat_id):
    """
    Bir sevkiyatın nakliye maliyetini kg/m³/toplam bazında normalize eder.
    Returns (birim_tutar, birim, guvenilirlik)
      - birim: 'kg' | 'm3' | 'toplam'
      - guvenilirlik: 'yuksek' (kg) | 'orta' (m3) | 'dusuk' (toplam)
    """
    navlun_tl = qscalar("""SELECT COALESCE(SUM(TutarTL),0) FROM grafik_sevkiyat_masraf
                           WHERE SevkiyatId=? AND Tip IN ('NAVLUN','AWB_FEE','YAKIT')""",
                        (sevkiyat_id,)) or 0
    if navlun_tl <= 0:
        return (None, None, None)

    toplam_kg = qscalar("""SELECT COALESCE(SUM(k.AgirlikKg),0)
                           FROM grafik_cin_siparis_kalem k
                           JOIN grafik_sevkiyat sv ON sv.SiparisId = k.SiparisId
                           WHERE sv.Id=?""", (sevkiyat_id,)) or 0
    if toplam_kg > 0:
        return (navlun_tl / toplam_kg, 'kg', 'yuksek')

    toplam_m3 = qscalar("""SELECT COALESCE(SUM(k.HacimM3),0)
                           FROM grafik_cin_siparis_kalem k
                           JOIN grafik_sevkiyat sv ON sv.SiparisId = k.SiparisId
                           WHERE sv.Id=?""", (sevkiyat_id,)) or 0
    if toplam_m3 > 0:
        return (navlun_tl / toplam_m3, 'm3', 'orta')

    return (navlun_tl, 'toplam', 'dusuk')


def _kiyas_navlun(secenek, ay):
    """Navlun kıyası (kg/m³/toplam normalize)."""
    nak_tipi = secenek.get('NakliyeTipi')
    if not nak_tipi or nak_tipi == 'DHL':
        return {'durum': 'uygulanmadi', 'mesaj': 'Navlun kıyası bu nakliye tipi için anlamlı değil.'}

    secim_kg = secenek.get('NakliyeAgirlikKg') or 0
    navlun_tl = (secenek.get('ToplamNakliye') or 0)
    if secim_kg <= 0 or navlun_tl <= 0:
        return {'durum': 'yetersiz_veri', 'mesaj': 'Seçenekte kg / navlun girilmemiş.'}

    mevcut_kg_tl = navlun_tl / secim_kg

    # Geçmiş sevkiyatlar
    tarih_basla = _gecmis_tarih(ay)
    sevkler = q("""SELECT Id FROM grafik_sevkiyat
                   WHERE NakliyeTipi = ? AND Durum = 'TESLIM'
                   AND OlusturmaTarih >= ?""",
                (nak_tipi, tarih_basla))

    normalized = []
    for sv in sevkler:
        birim, birim_tip, _ = _navlun_birim_maliyet(sv['Id'])
        if birim and birim_tip == 'kg':
            normalized.append(birim)

    if len(normalized) < MIN_NAVLUN:
        return {'durum': 'yetersiz_veri',
                'mesaj': f'Son {ay} ayda yeterli {nak_tipi.lower()} sevkiyat verisi yok '
                        f'({len(normalized)}/{MIN_NAVLUN}).'}

    ref_ort = sum(normalized) / len(normalized)
    fark_yuzde = (mevcut_kg_tl - ref_ort) / ref_ort * 100 if ref_ort > 0 else 0
    yorum, renk, karsilastirma = _yorum_etiket(fark_yuzde, 'navlun')
    yon = 'daha düşük' if fark_yuzde < 0 else ('daha yüksek' if fark_yuzde > 0 else 'benzer')
    cumle = (f'{nak_tipi.capitalize()} maliyeti son {len(normalized)} benzer sevkiyata göre '
             f'kg başı %{abs(fark_yuzde):.1f} {yon}.')
    return {
        'durum': 'hesaplandi', 'fark_yuzde': round(fark_yuzde, 1),
        'mevcut_kg_tl': round(mevcut_kg_tl, 2),
        'referans_kg_tl': round(ref_ort, 2),
        'ornek_sayisi': len(normalized),
        'yorum': yorum, 'renk': renk, 'cumle': cumle,
    }


def _kiyas_tedarikci(secenek, ay):
    ted_id = secenek.get('TedarikciId')
    if not ted_id:
        return {'durum': 'uygulanmadi', 'mesaj': 'Kayıtlı tedarikçi seçilmemiş.'}

    mevcut_fiyat = float(secenek.get('BirimFiyat') or 0)
    mevcut_pb = secenek.get('ParaBirimi')
    if mevcut_fiyat <= 0:
        return {'durum': 'yetersiz_veri', 'mesaj': 'Birim fiyat girilmemiş.'}

    tarih_basla = _gecmis_tarih(ay)
    # Aynı tedarikçiden, aynı PB'de geçmiş siparişlerin birim fiyat ortalaması
    gecmis = q("""SELECT k.BirimFiyat FROM grafik_cin_siparis_kalem k
                  JOIN grafik_cin_siparis s ON s.Id = k.SiparisId
                  WHERE s.TedarikciId = ? AND s.ParaBirimi = ?
                  AND s.OlusturmaTarih >= ? AND k.BirimFiyat > 0""",
               (ted_id, mevcut_pb, tarih_basla))
    if len(gecmis) < MIN_TEDARIKCI:
        return {'durum': 'yetersiz_veri',
                'mesaj': f'Bu tedarikçiyle {mevcut_pb} bazında son {ay} ay geçmiş yetersiz '
                        f'({len(gecmis)}/{MIN_TEDARIKCI}).'}

    ref = sum(float(g['BirimFiyat']) for g in gecmis) / len(gecmis)
    fark_yuzde = (mevcut_fiyat - ref) / ref * 100 if ref > 0 else 0
    yorum, renk, _ = _yorum_etiket(fark_yuzde, 'tedarikci')
    yon = 'daha düşük' if fark_yuzde < 0 else ('daha yüksek' if fark_yuzde > 0 else 'benzer')
    cumle = (f'Bu tedarikçi geçmiş {len(gecmis)} sipariş ortalamasına göre %{abs(fark_yuzde):.1f} {yon} '
             f'(ort: {mevcut_pb} {ref:.4f}).')
    return {
        'durum': 'hesaplandi', 'fark_yuzde': round(fark_yuzde, 1),
        'mevcut': mevcut_fiyat, 'referans': round(ref, 4),
        'ornek_sayisi': len(gecmis),
        'yorum': yorum, 'renk': renk, 'cumle': cumle,
    }


def _kiyas_birim_maliyet(secenek, ay):
    mevcut_birim = float(secenek.get('BirimMaliyetTL') or 0)
    if mevcut_birim <= 0:
        return {'durum': 'yetersiz_veri', 'mesaj': 'Birim maliyet hesaplanmamış.'}

    tarih_basla = _gecmis_tarih(ay)
    # Son teslim edilmiş ve dağıtımı GERÇEK olan siparişlerin çift başı maliyetini çıkar
    gecmis = q("""SELECT
                    (SUM(d.MasrafPayiTL) + SUM(k.Tutar * s.KurSnapshot)) AS ToplamTL,
                    SUM(k.Miktar) AS ToplamMiktar
                  FROM grafik_sevkiyat_dagitim d
                  JOIN grafik_sevkiyat sv ON sv.Id = d.SevkiyatId
                  JOIN grafik_cin_siparis_kalem k ON k.Id = d.KalemId
                  JOIN grafik_cin_siparis s ON s.Id = k.SiparisId
                  WHERE d.IsTahmini = 0 AND sv.Durum = 'TESLIM'
                  AND sv.OlusturmaTarih >= ?
                  GROUP BY sv.Id
                  HAVING ToplamMiktar > 0""",
               (tarih_basla,))
    if len(gecmis) < MIN_BIRIM_MAL:
        return {'durum': 'yetersiz_veri',
                'mesaj': f'Son {ay} ayda yeterli TESLIM+GERÇEK veri yok '
                        f'({len(gecmis)}/{MIN_BIRIM_MAL}).'}

    birim_tutarlar = [float(g['ToplamTL']) / float(g['ToplamMiktar']) for g in gecmis]
    ref = sum(birim_tutarlar) / len(birim_tutarlar)
    fark_yuzde = (mevcut_birim - ref) / ref * 100 if ref > 0 else 0
    yorum, renk, _ = _yorum_etiket(fark_yuzde, 'birim_mal')
    yon = 'daha düşük' if fark_yuzde < 0 else 'daha yüksek'
    cumle = (f'Birim maliyet son {len(gecmis)} teslim edilmiş siparişin ortalamasından '
             f'%{abs(fark_yuzde):.1f} {yon} ({ref:.2f} TL ortalama).')
    return {
        'durum': 'hesaplandi', 'fark_yuzde': round(fark_yuzde, 1),
        'mevcut': round(mevcut_birim, 2), 'referans': round(ref, 2),
        'ornek_sayisi': len(gecmis),
        'yorum': yorum, 'renk': renk, 'cumle': cumle,
    }


def _kiyas_marj(secenek, simulasyon, ay):
    mevcut_marj = secenek.get('MarjYuzde')
    if mevcut_marj is None:
        return {'durum': 'uygulanmadi', 'mesaj': 'Hedef satış fiyatı girilmediği için marj hesabı yok.'}

    tarih_basla = _gecmis_tarih(ay)
    gecmis = q("""SELECT sec.MarjYuzde FROM finans_simulasyon sim
                  JOIN finans_simulasyon_secenek sec ON sec.Id = sim.SecilenSecenekId
                  WHERE sim.Durum = 'KARAR' AND sec.MarjYuzde IS NOT NULL
                  AND sim.KararTarihi >= ? AND sim.Id != ?""",
               (tarih_basla, simulasyon['Id']))
    if len(gecmis) < MIN_MARJ:
        return {'durum': 'yetersiz_veri',
                'mesaj': f'Son {ay} ayda karar verilmiş yeterli simülasyon yok '
                        f'({len(gecmis)}/{MIN_MARJ}).'}

    ref = sum(float(g['MarjYuzde']) for g in gecmis) / len(gecmis)
    fark_pp = mevcut_marj - ref  # puan olarak fark
    # Marj için özel kural: puan bazlı
    if fark_pp <= -3:
        yorum, renk = 'geçmiş benzer işe göre düşük, dikkat', 'kirmizi'
    elif fark_pp <= 3:
        yorum, renk = 'geçmiş benzer işe göre ortalama seviyede', 'gri'
    elif fark_pp <= 8:
        yorum, renk = 'geçmiş benzer işe göre iyi', 'yesil'
    else:
        yorum, renk = 'geçmiş benzer işe göre oldukça iyi', 'yesil'

    yon = 'aşağıda' if fark_pp < 0 else 'yukarıda'
    cumle = (f'Marj geçmiş benzer {len(gecmis)} karara göre {abs(fark_pp):.1f} puan {yon} '
             f'(ort: %{ref:.1f}).')
    return {
        'durum': 'hesaplandi', 'fark_pp': round(fark_pp, 1),
        'mevcut': round(mevcut_marj, 1), 'referans': round(ref, 1),
        'ornek_sayisi': len(gecmis),
        'yorum': yorum, 'renk': renk, 'cumle': cumle,
    }


def gecmis_kiyas_hesapla(secenek, simulasyon, ay=6):
    """
    4 kıyası hesaplar. ay: 3, 6, 12 — default 6.
    """
    try:
        ay = int(ay)
        if ay not in (3, 6, 12):
            ay = 6
    except (TypeError, ValueError):
        ay = 6

    return {
        'ay': ay,
        'navlun':     _kiyas_navlun(secenek, ay),
        'tedarikci':  _kiyas_tedarikci(secenek, ay),
        'birim_mal':  _kiyas_birim_maliyet(secenek, ay),
        'marj':       _kiyas_marj(secenek, simulasyon, ay),
    }


# =========================================================
# ÖNERİ SKORU (maliyet %50 + marj %30 + süre %20)
# =========================================================
def oneri_skorla(secenekler, satis_fiyati_var_mi):
    """
    Her seçenek için 0-100 skor üretir.
    satis_fiyati_var_mi=False ise: maliyet %80 + süre %20
    satis_fiyati_var_mi=True ise: maliyet %50 + marj %30 + süre %20
    """
    if not secenekler:
        return {}

    maliyetler = [s['ToplamMaliyetTL'] or float('inf') for s in secenekler]
    sureler = [s['NakliyeGunSuresi'] or 999 for s in secenekler]
    en_ucuz = min(maliyetler)
    en_kisa = min(sureler) if sureler else 1

    marjlar = [s.get('MarjYuzde') for s in secenekler if s.get('MarjYuzde') is not None]
    en_yuksek_marj = max(marjlar) if marjlar else None

    skorlar = {}
    for sc in secenekler:
        tl = sc['ToplamMaliyetTL'] or float('inf')
        maliyet_skor = (en_ucuz / tl) * 100 if tl > 0 else 0

        sure = sc['NakliyeGunSuresi'] or 999
        sure_skor = (en_kisa / sure) * 100 if sure > 0 else 0

        if satis_fiyati_var_mi and en_yuksek_marj is not None and sc.get('MarjYuzde') is not None:
            # Marj negatif olabilir; normalize et (en düşükten en yükseğe 0-100)
            if en_yuksek_marj > 0:
                marj_skor = max(0, (sc['MarjYuzde'] / en_yuksek_marj) * 100)
            else:
                marj_skor = 0
            toplam = (maliyet_skor * 0.5) + (marj_skor * 0.3) + (sure_skor * 0.2)
            detay = {'maliyet_skor': round(maliyet_skor, 1),
                     'marj_skor': round(marj_skor, 1),
                     'sure_skor': round(sure_skor, 1),
                     'agirlik': '50/30/20'}
        else:
            toplam = (maliyet_skor * 0.8) + (sure_skor * 0.2)
            detay = {'maliyet_skor': round(maliyet_skor, 1),
                     'sure_skor': round(sure_skor, 1),
                     'agirlik': '80/20 (satış fiyatı yok)'}

        skorlar[sc['Id']] = {'toplam': round(toplam, 1), 'detay': detay}

    return skorlar


def en_iyiler(secenekler):
    """En ucuz, en hızlı, en iyi marj — rozet için."""
    if not secenekler:
        return {}

    # En ucuz
    en_ucuz = min(secenekler, key=lambda s: s['ToplamMaliyetTL'] or float('inf'))
    # En hızlı (0 olanları göz ardı et — giriş eksik)
    hizli_aday = [s for s in secenekler if (s['NakliyeGunSuresi'] or 0) > 0]
    en_hizli = min(hizli_aday, key=lambda s: s['NakliyeGunSuresi']) if hizli_aday else None
    # En iyi marj
    marjli = [s for s in secenekler if s.get('MarjYuzde') is not None]
    en_marj = max(marjli, key=lambda s: s['MarjYuzde']) if marjli else None

    return {
        'en_ucuz_id': en_ucuz['Id'],
        'en_hizli_id': en_hizli['Id'] if en_hizli else None,
        'en_marj_id': en_marj['Id'] if en_marj else None,
    }


def en_onerilen(secenekler, skorlar):
    """En yüksek toplam skor."""
    if not secenekler or not skorlar:
        return None
    return max(secenekler, key=lambda s: skorlar.get(s['Id'], {}).get('toplam', 0))
