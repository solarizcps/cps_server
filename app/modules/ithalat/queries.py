# -*- coding: utf-8 -*-
"""
CPS DEV - Ithalat Modulu - Sorgular ve Hesaplamalar
====================================================
BLOK 4.5 + 4.6-* + URUN KARTI

YENI (bu versiyonda):
  urun_kart_getir(arama)
    - 3 stratejiyle parti arar (FOB/Urun kodu, GTIP, genis LIKE)
    - Adet IS NULL veya <= 0 olan partileri TAMAMEN dislar
    - Agirlikli ortalama hesaplar (tum alimlar)
    - Son 3 parti gosterim icin
    - Tedarikci ve tasima kirilimlari
"""
import logging
import hashlib
import os
import re
import json
from datetime import datetime, date, timedelta
from db import q, qone, qscalar, qexec
from modules import audit

log = logging.getLogger("cps.ithalat")

# =====================================================================
# SABITLER
# =====================================================================
DURUM_TASLAK, DURUM_AKTIF = 'TASLAK', 'AKTIF'
DURUM_TESLIM, DURUM_KAPALI, DURUM_IPTAL = 'TESLIM', 'KAPALI', 'IPTAL'
GECERLI_DURUMLAR = {DURUM_TASLAK, DURUM_AKTIF, DURUM_TESLIM,
                    DURUM_KAPALI, DURUM_IPTAL}

DURUM_ETIKET = {
    'TASLAK': 'Taslak', 'AKTIF':  'Yolda', 'TESLIM': 'Geldi',
    'KAPALI': 'Kapali', 'IPTAL':  'Iptal',
}

TIP_FOB, TIP_NAVLUN, TIP_GUMRUK = 'FOB', 'NAVLUN', 'GUMRUK'
TIP_SIGORTA, TIP_DEPOLAMA = 'SIGORTA', 'DEPOLAMA'
TIP_KOMISYON, TIP_LIMAN, TIP_DIGER = 'KOMISYON', 'LIMAN', 'DIGER'
GECERLI_TIPLER = {TIP_FOB, TIP_NAVLUN, TIP_GUMRUK, TIP_SIGORTA,
                  TIP_DEPOLAMA, TIP_KOMISYON, TIP_LIMAN, TIP_DIGER}

KAYNAK_TAHMINI, KAYNAK_GERCEKLESEN = 'TAHMINI', 'GERCEKLESEN'
GECERLI_KAYNAKLAR = {KAYNAK_TAHMINI, KAYNAK_GERCEKLESEN}

PLAN_BEKLIYOR, PLAN_KISMEN = 'BEKLIYOR', 'KISMEN_ODENDI'
PLAN_ODENDI, PLAN_IPTAL = 'ODENDI', 'IPTAL'

PARSE_BEKLIYOR       = 'BEKLIYOR'
PARSE_OK             = 'OK'
PARSE_HATA           = 'HATA'
PARSE_DESTEKLENMIYOR = 'DESTEKLENMIYOR'
PARSE_INSAN_ONAYI    = 'INSAN_ONAYI_BEKLIYOR'
PARSE_ZATEN_ISLENDI  = 'ZATEN_ISLENDI'
PARSE_YENIDEN        = 'YENIDEN_ISLENDI'


# =====================================================================
# YARDIMCILAR
# =====================================================================
def _simdi():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _yeni_parti_kodu():
    try:
        yil = datetime.now().year
        prefix = f"ITH-{yil}-"
        r = qone(
            "SELECT Kod FROM ithalat_parti "
            "WHERE Kod LIKE ? ORDER BY Kod DESC LIMIT 1",
            (prefix + '%',),
        )
        son = 0
        if r:
            try:
                son = int(r['Kod'].split('-')[-1])
            except Exception:
                son = 0
        return f"{prefix}{son + 1:04d}"
    except Exception:
        return f"ITH-{datetime.now().strftime('%Y-%m%d-%H%M%S')}"


# ===== ITHALAT_KUR_FIX BEGIN =====
def _kur_hesapla(tutar, para_birimi, parti_para, manuel_kur=None,
                 okunan_kur=None, ana_kur_try=None):
    """Kalem -> parti para birimi.
    Hiyerarsi (PATCH 2):
      1) Ayni para birimi -> 1.0
      2) manuel_kur verilmis -> direkt carpan (mevcut davranis)
      3) okunan_kur (belgeden TCMB) -> 1 USD = X TRY semantigi
      4) ana_kur_try (parti fallback) -> ayni semantik
      5) Hicbiri yoksa -> (None, None) - kalem havada kalir
    Diger capraz birimler (EUR vs.) -> (None, None) guvenli.
    """
    try:
        if tutar is None:
            return None, None
        if para_birimi == parti_para:
            return 1.0, float(tutar)
        if manuel_kur is not None and float(manuel_kur) > 0:
            kur = float(manuel_kur)
            return kur, float(tutar) * kur
        pp = (parti_para or '').upper()
        pb = (para_birimi or '').upper()
        # Belgeden okunan kur (parser bagladi)
        if okunan_kur is not None and float(okunan_kur) > 0:
            okur = float(okunan_kur)
            if pp == 'USD' and pb == 'TRY':
                kur = 1.0 / okur
                return kur, float(tutar) * kur
            if pp == 'TRY' and pb == 'USD':
                kur = okur
                return kur, float(tutar) * kur
        # Parti seviye ana kur (fallback)
        if ana_kur_try is not None and float(ana_kur_try) > 0:
            akur = float(ana_kur_try)
            if pp == 'USD' and pb == 'TRY':
                kur = 1.0 / akur
                return kur, float(tutar) * kur
            if pp == 'TRY' and pb == 'USD':
                kur = akur
                return kur, float(tutar) * kur
        return None, None
    except Exception:
        return None, None
# ===== ITHALAT_KUR_FIX END =====


def dosya_hash_hesapla(dosya_yol):
    try:
        if not dosya_yol or not os.path.isfile(dosya_yol):
            return None
        h = hashlib.sha256()
        with open(dosya_yol, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        log.warning("dosya_hash_hesapla hata: %s", e)
        return None


# =====================================================================
# PARTI - CRUD (mevcut, dokunulmadi)
# =====================================================================
def parti_olustur(
    baslik, olusturan, para_birimi='USD',
    tedarikci_id=None, tedarikci_kod=None, tedarikci_ad=None,
    siparis_id=None, yukleme_tarih=None, tahmini_varis_tarih=None,
    toplam_kg=None, toplam_cift=None, aciklama=None,
    departman_kod=None,
):
    try:
        if not baslik or not para_birimi:
            return None
        kod = _yeni_parti_kodu()
        simdi = _simdi()
        parti_id = qexec("""
            INSERT INTO ithalat_parti
                (Kod, Baslik, TedarikciId, TedarikciKod, TedarikciAd,
                 SiparisId, ParaBirimi, Durum,
                 YuklemeTarih, TahminiVarisTarih,
                 ToplamKg, ToplamCift,
                 OlusturanKullanici, DepartmanKod, OlusmaTarih, Aciklama)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            kod, baslik[:200], tedarikci_id, tedarikci_kod, tedarikci_ad,
            siparis_id, para_birimi[:5], DURUM_TASLAK,
            yukleme_tarih, tahmini_varis_tarih,
            toplam_kg, toplam_cift,
            olusturan, departman_kod, simdi, aciklama,
        ))
        audit.log(
            olusturan, 'EKLE', 'ithalat_parti', parti_id,
            aciklama=f"Parti olusturuldu: {kod} - {baslik}",
            modul='ithalat', alt_modul='parti',
        )
        return parti_id
    except Exception as e:
        log.exception("parti_olustur hata: %s", e)
        return None


def parti_getir(parti_id):
    try:
        return qone("SELECT * FROM ithalat_parti WHERE Id = ?", (parti_id,))
    except Exception as e:
        log.exception("parti_getir hata: %s", e)
        return None


def parti_guncelle(parti_id, kullanici, **alanlar):
    try:
        IZINLI = {
            'Baslik': 'baslik', 'TedarikciId': 'tedarikci_id',
            'TedarikciKod': 'tedarikci_kod', 'TedarikciAd': 'tedarikci_ad',
            'SiparisId': 'siparis_id',
            'YuklemeTarih': 'yukleme_tarih',
            'TahminiVarisTarih': 'tahmini_varis_tarih',
            'GerceklesenVarisTarih': 'gerceklesen_varis_tarih',
            'ToplamKg': 'toplam_kg', 'ToplamCift': 'toplam_cift',
            'Aciklama': 'aciklama',
        }
        set_parts, params = [], []
        for db_col, py_key in IZINLI.items():
            if py_key in alanlar:
                set_parts.append(f"{db_col} = ?")
                params.append(alanlar[py_key])
        if not set_parts:
            return True
        params.append(parti_id)
        qexec(f"UPDATE ithalat_parti SET {', '.join(set_parts)} WHERE Id = ?",
              tuple(params))
        audit.log(kullanici, 'GUNCELLE', 'ithalat_parti', parti_id,
                  aciklama="Parti guncellendi",
                  modul='ithalat', alt_modul='parti')
        return True
    except Exception as e:
        log.exception("parti_guncelle hata: %s", e)
        return False


def parti_durum_degistir(parti_id, yeni_durum, kullanici, not_metni=None):
    try:
        if yeni_durum not in GECERLI_DURUMLAR:
            return False
        parti = parti_getir(parti_id)
        if not parti:
            return False
        onceki = parti['Durum']
        if onceki == yeni_durum:
            return True
        if yeni_durum == DURUM_KAPALI:
            qexec("UPDATE ithalat_parti SET Durum=?, KapamaTarih=? WHERE Id=?",
                  (yeni_durum, _simdi(), parti_id))
        else:
            qexec("UPDATE ithalat_parti SET Durum=? WHERE Id=?",
                  (yeni_durum, parti_id))
        aciklama = f"Durum: {onceki} -> {yeni_durum}"
        if not_metni:
            aciklama += f". Not: {not_metni[:200]}"
        audit.log(kullanici, 'DURUM_DEGISIM', 'ithalat_parti', parti_id,
                  aciklama=aciklama, modul='ithalat', alt_modul='parti')
        return True
    except Exception as e:
        log.exception("parti_durum_degistir hata: %s", e)
        return False


# =====================================================================
# MALIYET KALEM - TAM CRUD (mevcut)
# =====================================================================
def maliyet_kalem_ekle(
    parti_id, tip, tutar, para_birimi, kaynak,
    kullanici=None, aciklama=None, alt_kod=None, manuel_kur=None,
    okunan_kur=None,
    fatura_no=None, fatura_tarih=None,
    cari_id=None, cari_kod=None, cari_ad=None,
    odeme_plan_id=None, not_metni=None,
    kaynak_belge_id=None, kaynak_belge_ref=None,
    guvenlik_bypass=False,  # YENI: Testler icin bypass flag'i (default False)
):
    """
    Maliyet kalemi ekle.

    GUVENLIK FILTRESI (kuralina gore 10M TRY / 1M USD ustu otomatik RED):
      - TRY > 10,000,000 -> reddedilir (log'a yazilir, None doner)
      - USD/EUR/GBP > 1,000,000 -> reddedilir
      - Tutar negatif veya 0 -> reddedilir
      - guvenlik_bypass=True ise kontroller atlanir (ozel durum)
    """
    try:
        if tip not in GECERLI_TIPLER: return None
        if kaynak not in GECERLI_KAYNAKLAR: return None
        if tutar is None: return None
        try:
            tutar_f = float(tutar)
        except Exception:
            return None
        if tutar_f < 0: return None

        # ==== GUVENLIK FILTRESI ====
        if not guvenlik_bypass:
            para_up = str(para_birimi or '').upper()
            # TRY icin 10M tavan
            if para_up == 'TRY' and tutar_f > 10_000_000:
                log.error(
                    "GUVENLIK FILTRESI: Mantıksız TRY tutar RED "
                    "(parti=%s tip=%s tutar=%.2f TRY ref=%s) - kalem olusturulmadi",
                    parti_id, tip, tutar_f, kaynak_belge_ref,
                )
                audit.log(
                    kullanici or 'sistem', 'RED',
                    'ithalat_maliyet_kalem', 0,
                    aciklama=(f"GUVENLIK RED: Mantıksız TRY tutar "
                              f"parti={parti_id} tip={tip} "
                              f"tutar={tutar_f:.2f} ref={kaynak_belge_ref}"),
                    modul='ithalat', alt_modul='maliyet',
                )
                return None
            # USD/EUR/GBP icin 1M tavan
            if para_up in ('USD', 'EUR', 'GBP') and tutar_f > 1_000_000:
                log.error(
                    "GUVENLIK FILTRESI: Mantıksız %s tutar RED "
                    "(parti=%s tip=%s tutar=%.2f %s ref=%s) - kalem olusturulmadi",
                    para_up, parti_id, tip, tutar_f, para_up, kaynak_belge_ref,
                )
                audit.log(
                    kullanici or 'sistem', 'RED',
                    'ithalat_maliyet_kalem', 0,
                    aciklama=(f"GUVENLIK RED: Mantıksız {para_up} tutar "
                              f"parti={parti_id} tip={tip} tutar={tutar_f:.2f}"),
                    modul='ithalat', alt_modul='maliyet',
                )
                return None
            # CNY icin 10M tavan
            if para_up == 'CNY' and tutar_f > 10_000_000:
                log.error(
                    "GUVENLIK FILTRESI: Mantıksız CNY tutar RED "
                    "(parti=%s tip=%s tutar=%.2f)",
                    parti_id, tip, tutar_f,
                )
                return None

        parti = parti_getir(parti_id)
        if not parti: return None

        parti_para = parti['ParaBirimi']
        kur_degeri, tutar_parti = _kur_hesapla(
            tutar, para_birimi, parti_para, manuel_kur,
            okunan_kur=okunan_kur,
            ana_kur_try=(parti['AnaKurTRY'] if 'AnaKurTRY' in parti.keys() else None),
        )
        simdi = _simdi()
        kalem_id = qexec("""
            INSERT INTO ithalat_maliyet_kalem
                (PartiId, Tip, AltKod, Aciklama, Kaynak,
                 Tutar, ParaBirimi, KurTarihi, KurDegeri, TutarPartiPara,
                 FaturaNo, FaturaTarih,
                 CariId, CariKod, CariAd, OdemePlanId,
                 OlusturanKullanici, OlusmaTarih, NotMetni,
                 Iptal, KaynakBelgeId, KaynakBelgeRef, OkunanKur)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    0, ?, ?, ?)
        """, (
            parti_id, tip, alt_kod, aciklama, kaynak,
            tutar, para_birimi[:5], simdi, kur_degeri, tutar_parti,
            fatura_no, fatura_tarih,
            cari_id, cari_kod, cari_ad, odeme_plan_id,
            kullanici, simdi, not_metni,
            kaynak_belge_id, kaynak_belge_ref, okunan_kur,
        ))
        audit.log(
            kullanici or 'sistem', 'EKLE',
            'ithalat_maliyet_kalem', kalem_id,
            aciklama=f"Maliyet: PartiId={parti_id} Tip={tip} "
                     f"Kaynak={kaynak} Tutar={tutar} {para_birimi}"
                     + (f" [belge_ref={kaynak_belge_ref}]" if kaynak_belge_ref else ""),
            modul='ithalat', alt_modul='maliyet',
        )
        return kalem_id
    except Exception as e:
        log.exception("maliyet_kalem_ekle hata: %s", e)
        return None


def maliyet_kalem_liste(parti_id, iptal_dahil=False):
    try:
        where_iptal = "" if iptal_dahil else "AND (Iptal IS NULL OR Iptal = 0)"
        sql = f"""
            SELECT * FROM ithalat_maliyet_kalem
            WHERE PartiId = ? {where_iptal}
            ORDER BY Iptal ASC, Tip ASC, Kaynak ASC, Id ASC
        """
        return q(sql, (parti_id,))
    except Exception as e:
        log.exception("maliyet_kalem_liste hata: %s", e)
        return []


def maliyet_kalem_getir(kalem_id):
    try:
        return qone("SELECT * FROM ithalat_maliyet_kalem WHERE Id = ?", (kalem_id,))
    except Exception as e:
        log.exception("maliyet_kalem_getir hata: %s", e)
        return None


def maliyet_kalem_guncelle(kalem_id, kullanici, **alanlar):
    try:
        kalem = maliyet_kalem_getir(kalem_id)
        if not kalem: return False
        parti = parti_getir(kalem['PartiId'])
        if not parti: return False

        IZINLI = {
            'Tip': 'tip', 'AltKod': 'alt_kod', 'Aciklama': 'aciklama',
            'Kaynak': 'kaynak', 'Tutar': 'tutar',
            'ParaBirimi': 'para_birimi',
            'FaturaNo': 'fatura_no', 'FaturaTarih': 'fatura_tarih',
            'CariId': 'cari_id', 'CariKod': 'cari_kod', 'CariAd': 'cari_ad',
            'OdemePlanId': 'odeme_plan_id', 'NotMetni': 'not_metni',
        }
        yeni_tutar = alanlar.get('tutar', kalem['Tutar'])
        yeni_para = alanlar.get('para_birimi', kalem['ParaBirimi'])
        manuel_kur = alanlar.get('manuel_kur')
        okunan_kur = alanlar.get('okunan_kur')
        kur_guncelle = (
            ('tutar' in alanlar and float(alanlar['tutar']) != float(kalem['Tutar'])) or
            ('para_birimi' in alanlar and alanlar['para_birimi'] != kalem['ParaBirimi']) or
            manuel_kur is not None or
            okunan_kur is not None
        )
        set_parts, params = [], []
        for db_col, py_key in IZINLI.items():
            if py_key in alanlar:
                set_parts.append(f"{db_col} = ?")
                params.append(alanlar[py_key])
        if kur_guncelle:
            kur_degeri, tutar_parti = _kur_hesapla(
                yeni_tutar, yeni_para, parti['ParaBirimi'], manuel_kur,
                okunan_kur=okunan_kur,
                ana_kur_try=(parti['AnaKurTRY'] if 'AnaKurTRY' in parti.keys() else None),
            )
            set_parts.extend(['KurTarihi = ?', 'KurDegeri = ?', 'TutarPartiPara = ?'])
            params.extend([_simdi(), kur_degeri, tutar_parti])
            if okunan_kur is not None:
                set_parts.append('OkunanKur = ?')
                params.append(okunan_kur)
        if not set_parts: return True
        params.append(kalem_id)
        qexec(f"UPDATE ithalat_maliyet_kalem SET {', '.join(set_parts)} WHERE Id = ?",
              tuple(params))
        audit.log(kullanici, 'GUNCELLE', 'ithalat_maliyet_kalem', kalem_id,
                  aciklama="Maliyet kalemi guncellendi",
                  modul='ithalat', alt_modul='maliyet')
        return True
    except Exception as e:
        log.exception("maliyet_kalem_guncelle hata: %s", e)
        return False


def maliyet_kalem_sil(kalem_id, kullanici):
    try:
        kalem = maliyet_kalem_getir(kalem_id)
        if not kalem: return False
        qexec("DELETE FROM ithalat_maliyet_kalem WHERE Id = ?", (kalem_id,))
        audit.log(kullanici, 'SIL', 'ithalat_maliyet_kalem', kalem_id,
                  aciklama=f"Maliyet silindi: Tip={kalem['Tip']} "
                           f"Kaynak={kalem['Kaynak']} Tutar={kalem['Tutar']}",
                  modul='ithalat', alt_modul='maliyet')
        return True
    except Exception as e:
        log.exception("maliyet_kalem_sil hata: %s", e)
        return False


def kalem_iptal_topluca(parti_id, kaynak_belge_ref, kullanici, sebep=None):
    try:
        if not kaynak_belge_ref:
            return {'iptal_edilen': 0, 'hata': 'Kaynak ref bos'}

        rows = q("""
            SELECT Id FROM ithalat_maliyet_kalem
            WHERE PartiId = ? AND KaynakBelgeRef = ?
              AND (Iptal IS NULL OR Iptal = 0)
        """, (parti_id, kaynak_belge_ref))

        if not rows:
            return {'iptal_edilen': 0}

        kalem_idler = [r['Id'] for r in rows]
        simdi = _simdi()
        iptal_sebep = (sebep or 'Yeniden parse icin iptal')[:500]

        placeholder = ','.join('?' for _ in kalem_idler)
        qexec(f"""
            UPDATE ithalat_maliyet_kalem
            SET Iptal = 1, IptalSebep = ?, IptalTarih = ?
            WHERE Id IN ({placeholder})
        """, (iptal_sebep, simdi) + tuple(kalem_idler))

        audit.log(
            kullanici, 'IPTAL', 'ithalat_maliyet_kalem', 0,
            aciklama=(f"Toplu iptal: PartiId={parti_id} "
                      f"BelgeRef={kaynak_belge_ref} "
                      f"Kalem sayisi={len(kalem_idler)} "
                      f"Sebep: {iptal_sebep}"),
            modul='ithalat', alt_modul='maliyet',
        )
        return {'iptal_edilen': len(kalem_idler)}
    except Exception as e:
        log.exception("kalem_iptal_topluca hata: %s", e)
        return {'iptal_edilen': 0, 'hata': str(e)[:100]}


# =====================================================================
# BELGE PARSE DURUMU (mevcut)
# =====================================================================
def belge_parse_durum_ekle_veya_guncelle(
    belge_id, parti_id, belge_tipi=None,
    parse_durum=None, parse_mesaj='',
    kaynak_belge_ref=None, dosya_hash=None,
    uygulanan_kalem_sayisi=0, kaynak_belge_id_list=None,
    parseden=None, not_metni=None,
    kaynak_ref=None,  # alias for kaynak_belge_ref - backward compat
    **kwargs,  # Bilinmeyen parametreleri sessiz yut (forward compat)
):
    """
    belge_parse tablosuna ekle veya guncelle.

    Geriye donuk uyum:
      - kaynak_ref parametresi kaynak_belge_ref'in alias'idir
      - bilinmeyen keyword parametreleri **kwargs ile yutulur
        (log'a yazilir ama hata firlatilmaz)
    """
    # Alias birlestir - kaynak_ref oncelikli (yeni cagrilar kullaniyor)
    if kaynak_ref is not None and not kaynak_belge_ref:
        kaynak_belge_ref = kaynak_ref

    # Bilinmeyen parametreler varsa log'a yaz
    if kwargs:
        log.warning(
            "belge_parse_durum_ekle_veya_guncelle: bilinmeyen parametreler atlandi: %s",
            list(kwargs.keys()),
        )

    try:
        # belge_tipi zorunlu degil - mevcut kayit varsa alabiliriz
        if belge_tipi is None:
            mevcut_tam = qone(
                "SELECT BelgeTipi FROM ithalat_belge_parse WHERE BelgeId = ?",
                (belge_id,),
            )
            if mevcut_tam:
                belge_tipi = mevcut_tam.get('BelgeTipi')
            else:
                # Yine yoksa belge tablosundan cek
                try:
                    b = qone(
                        "SELECT BelgeTipi FROM belge WHERE Id = ?",
                        (belge_id,),
                    )
                    if b:
                        belge_tipi = b.get('BelgeTipi')
                except Exception:
                    pass
            if not belge_tipi:
                belge_tipi = 'DIGER'  # son care

        mevcut = qone(
            "SELECT Id FROM ithalat_belge_parse WHERE BelgeId = ?",
            (belge_id,),
        )
        simdi = _simdi()
        kalem_idler_str = None
        if kaynak_belge_id_list:
            try:
                kalem_idler_str = json.dumps(list(kaynak_belge_id_list))
            except Exception:
                kalem_idler_str = str(kaynak_belge_id_list)[:500]

        if mevcut:
            qexec("""
                UPDATE ithalat_belge_parse
                SET ParseDurum = ?, ParseMesaj = ?,
                    KaynakBelgeRef = COALESCE(?, KaynakBelgeRef),
                    DosyaHash = COALESCE(?, DosyaHash),
                    UygulananKalemSayisi = ?, KaynakBelgeIdList = ?,
                    Parseden = ?, GuncellemeTarih = ?,
                    NotMetni = COALESCE(?, NotMetni)
                WHERE Id = ?
            """, (
                parse_durum, (parse_mesaj or '')[:1000],
                kaynak_belge_ref, dosya_hash,
                uygulanan_kalem_sayisi, kalem_idler_str,
                parseden, simdi, not_metni,
                mevcut['Id'],
            ))
            return mevcut['Id']
        else:
            yeni_id = qexec("""
                INSERT INTO ithalat_belge_parse
                    (BelgeId, PartiId, BelgeTipi,
                     ParseDurum, ParseMesaj,
                     KaynakBelgeRef, DosyaHash,
                     UygulananKalemSayisi, KaynakBelgeIdList,
                     Parseden, ParseTarih, NotMetni)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                belge_id, parti_id, belge_tipi,
                parse_durum, (parse_mesaj or '')[:1000],
                kaynak_belge_ref, dosya_hash,
                uygulanan_kalem_sayisi, kalem_idler_str,
                parseden, simdi, not_metni,
            ))
            return yeni_id
    except Exception as e:
        log.exception("belge_parse_durum_ekle_veya_guncelle hata: %s", e)
        return None


def belge_parse_durum_getir(belge_id):
    try:
        return qone(
            "SELECT * FROM ithalat_belge_parse WHERE BelgeId = ?",
            (belge_id,),
        )
    except Exception as e:
        log.exception("belge_parse_durum_getir hata: %s", e)
        return None


def belge_parse_ref_kontrol(parti_id, kaynak_belge_ref):
    """
    Ayni parti + ayni kaynak_ref icin SUCCESS durumunda parse var mi?

    Basarili durumlar: OK, YENIDEN_ISLENDI, UYGULANDI
      - OK: Eski sistem (direkt uygula)
      - YENIDEN_ISLENDI: Override uygulama
      - UYGULANDI: Yeni preview sistemi (kullanici onay ile)

    Donus: row veya None
    """
    try:
        if not kaynak_belge_ref:
            return None
        return qone("""
            SELECT BelgeId, ParseTarih, ParseDurum, UygulananKalemSayisi
            FROM ithalat_belge_parse
            WHERE PartiId = ? AND KaynakBelgeRef = ?
              AND ParseDurum IN ('OK', 'YENIDEN_ISLENDI', 'UYGULANDI')
            ORDER BY ParseTarih DESC
            LIMIT 1
        """, (parti_id, kaynak_belge_ref))
    except Exception as e:
        log.exception("belge_parse_ref_kontrol hata: %s", e)
        return None


def aktif_maliyet_kalem_ref_kontrol(parti_id, kaynak_belge_ref):
    """
    EN SAGLAM KONTROL: Maliyet tablosunda ayni parti + ayni kaynak_ref ile
    AKTIF (Iptal=0) kalem var mi?

    belge_parse tablosu senkronsuz kalabilir ama maliyet tablosu asil truth.

    Donus: aktif kalem sayisi (int). 0 ise yok.
    """
    try:
        if not kaynak_belge_ref:
            return 0
        r = qone("""
            SELECT COUNT(*) AS Adet
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ? AND KaynakBelgeRef = ?
              AND (Iptal IS NULL OR Iptal = 0)
        """, (parti_id, kaynak_belge_ref))
        return int(r['Adet'] if r and r.get('Adet') else 0)
    except Exception as e:
        log.exception("aktif_maliyet_kalem_ref_kontrol hata: %s", e)
        return 0


def aktif_maliyet_kalem_belge_id_kontrol(belge_id):
    """
    Belirli bir BelgeId icin aktif (Iptal=0) kalem var mi?
    UYGULANDI_BOS durumunu tespit etmek icin.

    Donus: aktif kalem sayisi (int).
    """
    try:
        if not belge_id:
            return 0
        r = qone("""
            SELECT COUNT(*) AS Adet
            FROM ithalat_maliyet_kalem
            WHERE KaynakBelgeId = ?
              AND (Iptal IS NULL OR Iptal = 0)
        """, (int(belge_id),))
        return int(r['Adet'] if r and r.get('Adet') else 0)
    except Exception as e:
        log.exception("aktif_maliyet_kalem_belge_id_kontrol hata: %s", e)
        return 0


def belge_parse_hash_kontrol(dosya_hash):
    try:
        if not dosya_hash:
            return None
        return qone("""
            SELECT BelgeId, PartiId, ParseTarih, ParseDurum, KaynakBelgeRef
            FROM ithalat_belge_parse
            WHERE DosyaHash = ? AND ParseDurum IN ('OK', 'YENIDEN_ISLENDI')
            ORDER BY ParseTarih DESC
            LIMIT 1
        """, (dosya_hash,))
    except Exception as e:
        log.exception("belge_parse_hash_kontrol hata: %s", e)
        return None


def belge_parse_liste(parti_id):
    try:
        return q("""
            SELECT * FROM ithalat_belge_parse
            WHERE PartiId = ?
            ORDER BY ParseTarih DESC
        """, (parti_id,))
    except Exception as e:
        log.exception("belge_parse_liste hata: %s", e)
        return []


# =====================================================================
# PARSE SONUC UYGULA (mevcut)
# =====================================================================
def parse_sonuc_uygula(parti_id, belge_id, parse_sonuc, kullanici,
                       kaynak_belge_ref_override=None,
                       yeniden_isle=False):
    sonuc = {
        'uygulanan': 0, 'atlanan': 0, 'hata': 0,
        'kalem_idler': [],
        'parse_durum': PARSE_HATA,
        'kaynak_belge_ref': None,
        'onceki_kalemler_iptal': 0,
        'mesaj': '',
    }

    try:
        if hasattr(parse_sonuc, 'kalemler'):
            kalemler = parse_sonuc.kalemler or []
            basarili = bool(parse_sonuc.basarili)
            parser_mesaj = getattr(parse_sonuc, 'mesaj', '')
            parser_durum = getattr(parse_sonuc, 'durum', PARSE_HATA)
            parser_ref = getattr(parse_sonuc, 'kaynak_ref', None)
            parser_hash = getattr(parse_sonuc, 'dosya_hash', None)
            insan_onayi_flag = getattr(parse_sonuc, 'insan_onayi_bekliyor', False)
        elif isinstance(parse_sonuc, dict):
            kalemler = parse_sonuc.get('kalemler') or []
            basarili = bool(parse_sonuc.get('basarili'))
            parser_mesaj = parse_sonuc.get('mesaj', '')
            parser_durum = parse_sonuc.get('durum', PARSE_HATA)
            parser_ref = parse_sonuc.get('kaynak_ref')
            parser_hash = parse_sonuc.get('dosya_hash')
            insan_onayi_flag = parse_sonuc.get('insan_onayi_bekliyor', False)
        else:
            sonuc['mesaj'] = 'Gecersiz parse sonucu formati'
            sonuc['parse_durum'] = PARSE_HATA
            return sonuc

        kaynak_ref = kaynak_belge_ref_override or parser_ref
        sonuc['kaynak_belge_ref'] = kaynak_ref

        from modules import belge as belge_svc
        belge_row = belge_svc.belge_tek(belge_id)
        belge_tipi = (belge_row.get('BelgeTipi') if belge_row else 'DIGER') or 'DIGER'

        parti = parti_getir(parti_id)
        if not parti:
            sonuc['mesaj'] = f"Parti bulunamadi: {parti_id}"
            sonuc['parse_durum'] = PARSE_HATA
            belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum=PARSE_HATA,
                parse_mesaj=sonuc['mesaj'],
                kaynak_belge_ref=kaynak_ref,
                dosya_hash=parser_hash,
                parseden=kullanici,
            )
            return sonuc

        if not basarili and not insan_onayi_flag:
            sonuc['mesaj'] = parser_mesaj or 'Parse basarisiz'
            sonuc['parse_durum'] = (
                parser_durum if parser_durum in
                (PARSE_DESTEKLENMIYOR, PARSE_INSAN_ONAYI) else PARSE_HATA
            )
            belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum=sonuc['parse_durum'],
                parse_mesaj=sonuc['mesaj'],
                kaynak_belge_ref=kaynak_ref,
                dosya_hash=parser_hash,
                parseden=kullanici,
            )
            return sonuc

        if insan_onayi_flag and not kaynak_ref:
            sonuc['mesaj'] = parser_mesaj or (
                f"Parse tamam ({len(kalemler)} kalem) ama PI No bulunamadi. "
                "Manuel ref ile 'yine de uygula' gerekli."
            )
            sonuc['parse_durum'] = PARSE_INSAN_ONAYI
            belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum=PARSE_INSAN_ONAYI,
                parse_mesaj=sonuc['mesaj'],
                kaynak_belge_ref=None,
                dosya_hash=parser_hash,
                parseden=kullanici,
                not_metni=json.dumps({
                    'kalem_sayisi': len(kalemler),
                    'dosya_hash': parser_hash,
                }),
            )
            return sonuc

        if kaynak_ref and not yeniden_isle:
            onceki = belge_parse_ref_kontrol(parti_id, kaynak_ref)
            if onceki:
                sonuc['mesaj'] = (
                    f"Bu belge ({kaynak_ref}) zaten islenmis "
                    f"(belge #{onceki['BelgeId']}, "
                    f"{onceki['ParseTarih'][:16]}). "
                    f"Yeniden islemek icin 'Yeniden Isle' butonunu kullanin."
                )
                sonuc['parse_durum'] = PARSE_ZATEN_ISLENDI
                belge_parse_durum_ekle_veya_guncelle(
                    belge_id=belge_id, parti_id=parti_id,
                    belge_tipi=belge_tipi,
                    parse_durum=PARSE_ZATEN_ISLENDI,
                    parse_mesaj=sonuc['mesaj'],
                    kaynak_belge_ref=kaynak_ref,
                    dosya_hash=parser_hash,
                    parseden=kullanici,
                )
                return sonuc

        if yeniden_isle and kaynak_ref:
            iptal_sonuc = kalem_iptal_topluca(
                parti_id=parti_id,
                kaynak_belge_ref=kaynak_ref,
                kullanici=kullanici,
                sebep=f"Yeniden parse (yeni belge #{belge_id})",
            )
            sonuc['onceki_kalemler_iptal'] = iptal_sonuc.get('iptal_edilen', 0)

        if not kalemler:
            sonuc['mesaj'] = parser_mesaj or 'Uygulanacak kalem yok'
            sonuc['parse_durum'] = PARSE_OK
            belge_parse_durum_ekle_veya_guncelle(
                belge_id=belge_id, parti_id=parti_id,
                belge_tipi=belge_tipi,
                parse_durum=PARSE_OK,
                parse_mesaj=sonuc['mesaj'],
                kaynak_belge_ref=kaynak_ref,
                dosya_hash=parser_hash,
                uygulanan_kalem_sayisi=0,
                parseden=kullanici,
            )
            return sonuc

        for kalem in kalemler:
            try:
                tip = str(kalem.get('tip') or '').upper()
                tutar = kalem.get('tutar')
                para = str(kalem.get('para_birimi') or 'USD').upper()
                kaynak = str(kalem.get('kaynak') or KAYNAK_TAHMINI).upper()

                if tip not in GECERLI_TIPLER:
                    sonuc['atlanan'] += 1
                    continue
                if tutar is None or float(tutar) <= 0:
                    sonuc['atlanan'] += 1
                    continue
                if kaynak not in GECERLI_KAYNAKLAR:
                    kaynak = KAYNAK_TAHMINI

                mevcut_not = kalem.get('not_metni') or ''
                belge_ref_str = f"[belge #{belge_id}]"
                if kaynak_ref:
                    belge_ref_str = f"[belge #{belge_id} · {kaynak_ref}]"
                if belge_ref_str not in mevcut_not:
                    yeni_not = (mevcut_not + ' ' + belge_ref_str).strip()[:500]
                else:
                    yeni_not = mevcut_not

                kalem_id = maliyet_kalem_ekle(
                    parti_id=parti_id, tip=tip, tutar=float(tutar),
                    para_birimi=para, kaynak=kaynak, kullanici=kullanici,
                    aciklama=kalem.get('aciklama'),
                    alt_kod=kalem.get('alt_kod'),
                    manuel_kur=kalem.get('manuel_kur'),
                    okunan_kur=kalem.get('okunan_kur'),  # PATCH 3
                    fatura_no=kalem.get('fatura_no'),
                    fatura_tarih=kalem.get('fatura_tarih'),
                    cari_kod=kalem.get('cari_kod'),
                    cari_ad=kalem.get('cari_ad'),
                    odeme_plan_id=kalem.get('odeme_plan_id'),
                    not_metni=yeni_not,
                    kaynak_belge_id=belge_id,
                    kaynak_belge_ref=kaynak_ref,
                )
                if kalem_id:
                    sonuc['uygulanan'] += 1
                    sonuc['kalem_idler'].append(kalem_id)
                else:
                    sonuc['hata'] += 1
            except Exception as e:
                log.exception("parse_sonuc_uygula - kalem hatasi: %s", e)
                sonuc['hata'] += 1

        parse_durum_son = (
            PARSE_YENIDEN if yeniden_isle else PARSE_OK
        ) if sonuc['uygulanan'] > 0 else PARSE_HATA

        sonuc['parse_durum'] = parse_durum_son
        sonuc['mesaj'] = (
            f"{sonuc['uygulanan']} kalem eklendi"
            + (f", {sonuc['onceki_kalemler_iptal']} eski kalem iptal edildi"
               if sonuc['onceki_kalemler_iptal'] else '')
            + (f", {sonuc['atlanan']} atlandi" if sonuc['atlanan'] else '')
            + (f", {sonuc['hata']} hata" if sonuc['hata'] else '')
        )

        belge_parse_durum_ekle_veya_guncelle(
            belge_id=belge_id, parti_id=parti_id,
            belge_tipi=belge_tipi,
            parse_durum=parse_durum_son,
            parse_mesaj=sonuc['mesaj'],
            kaynak_belge_ref=kaynak_ref,
            dosya_hash=parser_hash,
            uygulanan_kalem_sayisi=sonuc['uygulanan'],
            kaynak_belge_id_list=sonuc['kalem_idler'],
            parseden=kullanici,
        )

        if sonuc['uygulanan'] > 0:
            audit.log(
                kullanici, 'EKLE', 'ithalat_maliyet_kalem', 0,
                aciklama=(
                    f"Parse ile otomatik ekleme: PartiId={parti_id} "
                    f"belge_id={belge_id} "
                    + (f"ref={kaynak_ref} " if kaynak_ref else '')
                    + (f"yeniden_isle=1 " if yeniden_isle else '')
                    + f"uygulanan={sonuc['uygulanan']} "
                    f"atlanan={sonuc['atlanan']} hata={sonuc['hata']} "
                    f"iptal_edilen={sonuc['onceki_kalemler_iptal']}"
                ),
                modul='ithalat', alt_modul='maliyet',
            )

        return sonuc

    except Exception as e:
        log.exception("parse_sonuc_uygula fail-safe: %s", e)
        sonuc['mesaj'] = f"Uygulama hatasi: {str(e)[:100]}"
        sonuc['parse_durum'] = PARSE_HATA
        return sonuc


# =====================================================================
# PARTI OZET (mevcut)
# =====================================================================
def parti_ozet(parti_id):
    try:
        parti = parti_getir(parti_id)
        if not parti: return {}

        # Tip + Kaynak bazinda toplam (parti para birimine cevrilmis tutarlar)
        rows = q("""
            SELECT Tip, Kaynak, SUM(TutarPartiPara) AS Toplam
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ? AND TutarPartiPara IS NOT NULL
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, Kaynak
        """, (parti_id,))

        # Tip bazinda kullanilan para birimleri (karisik tespiti icin)
        para_rows = q("""
            SELECT Tip, ParaBirimi, COUNT(*) AS Adet
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ?
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, ParaBirimi
        """, (parti_id,))

        tip_bazinda = {}
        for r in rows:
            tip = r['Tip']
            if tip not in tip_bazinda:
                tip_bazinda[tip] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            tip_bazinda[tip][r['Kaynak']] = float(r['Toplam'] or 0)

        tip_paralar = {}  # {tip: set(['USD', 'TRY'])}
        for r in para_rows:
            tip = r['Tip']
            pb = r['ParaBirimi']
            if tip not in tip_paralar:
                tip_paralar[tip] = set()
            if pb:
                tip_paralar[tip].add(pb)

        tahmini_toplam = sum(v['TAHMINI'] for v in tip_bazinda.values())
        gerceklesen = sum(v['GERCEKLESEN'] for v in tip_bazinda.values())

        # YENI: Siniflandirma + ESLESEN toplamlar
        etkin_toplam = 0.0
        eslesen_tahmini = 0.0
        eslesen_gerceklesen = 0.0
        eslesen_sayi = 0
        bekleyen_sayi = 0
        tahmini_yok_sayi = 0
        herhangi_karisik = False

        tip_detay = []
        for tip, vals in tip_bazinda.items():
            t_tahmini = vals['TAHMINI']
            t_gercek = vals['GERCEKLESEN']
            t_etkin = t_gercek if t_gercek > 0 else t_tahmini
            etkin_toplam += t_etkin

            # Siniflandirma
            if t_tahmini > 0 and t_gercek > 0:
                sinif = 'ESLESEN'
                sapma = round(((t_gercek - t_tahmini) / t_tahmini) * 100, 2)
                eslesen_tahmini += t_tahmini
                eslesen_gerceklesen += t_gercek
                eslesen_sayi += 1
            elif t_tahmini > 0 and t_gercek == 0:
                sinif = 'BEKLIYOR'
                sapma = None
                bekleyen_sayi += 1
            elif t_tahmini == 0 and t_gercek > 0:
                sinif = 'TAHMINI_YOK'
                sapma = None
                tahmini_yok_sayi += 1
            else:
                sinif = 'YOK'
                sapma = None

            paralar = sorted(tip_paralar.get(tip, []))
            tip_karisik = len(paralar) > 1
            if tip_karisik:
                herhangi_karisik = True

            tip_detay.append({
                'tip': tip,
                'tahmini': t_tahmini, 'gerceklesen': t_gercek,
                'etkin': t_etkin, 'sapma_yuzde': sapma,
                'bekliyor': (t_gercek == 0 and t_tahmini > 0),
                # YENI
                'sinif': sinif,
                'para_birimleri': paralar,
                'para_birimi_karisik': tip_karisik,
            })

        kg_mal = None
        cift_mal = None
        if parti.get('ToplamKg') and parti['ToplamKg'] > 0:
            kg_mal = round(etkin_toplam / parti['ToplamKg'], 4)
        if parti.get('ToplamCift') and parti['ToplamCift'] > 0:
            cift_mal = round(etkin_toplam / parti['ToplamCift'], 4)

        # Genel sapma artik SADECE ESLESEN tiplerden
        sapma_genel = None
        if eslesen_tahmini > 0:
            sapma_genel = round(
                ((eslesen_gerceklesen - eslesen_tahmini) / eslesen_tahmini) * 100, 2,
            )

        # UI icin hazir kapsam metni
        if sapma_genel is not None:
            sapma_kapsam_metni = f"{eslesen_sayi} tip karsilastirildi"
        elif (bekleyen_sayi + tahmini_yok_sayi) > 0:
            sapma_kapsam_metni = "Karsilastirilabilir tip yok"
        else:
            sapma_kapsam_metni = "Hesaplanamaz"

        return {
            'parti': parti,
            'tahmini_toplam': round(tahmini_toplam, 4),
            'gerceklesen_toplam': round(gerceklesen, 4),
            'etkin_toplam': round(etkin_toplam, 4),
            'kg_maliyet': kg_mal, 'cift_maliyet': cift_mal,
            'sapma_yuzde': sapma_genel,
            'tip_detay': sorted(tip_detay, key=lambda x: x['tip']),
            'para_birimi': parti['ParaBirimi'],
            # YENI alanlar
            'eslesen_tahmini_toplam':     round(eslesen_tahmini, 4),
            'eslesen_gerceklesen_toplam': round(eslesen_gerceklesen, 4),
            'eslesen_tip_sayisi':         eslesen_sayi,
            'bekleyen_tip_sayisi':        bekleyen_sayi,
            'tahmini_yok_tip_sayisi':     tahmini_yok_sayi,
            'para_birimi_karisik':        herhangi_karisik,
            'sapma_kapsam_metni':         sapma_kapsam_metni,
            'sapma_guvenilir': bool(sapma_genel is not None and not herhangi_karisik),
        }
    except Exception as e:
        log.exception("parti_ozet hata: %s", e)
        return {}


def parti_detay(parti_id, iptal_dahil=False):
    try:
        ozet = parti_ozet(parti_id)
        if not ozet: return {}
        ozet['kalemler'] = maliyet_kalem_liste(parti_id, iptal_dahil=iptal_dahil)
        ozet['odeme_planlari'] = odeme_plan_liste(parti_id)
        ozet['hareketler'] = odeme_hareket_liste(parti_id)
        ozet['durum_gecmisi'] = durum_gecmisi(parti_id)
        ozet['belge_parse_kayitlari'] = belge_parse_liste(parti_id)
        return ozet
    except Exception as e:
        log.exception("parti_detay hata: %s", e)
        return {}


# =====================================================================
# PARTI LISTE (mevcut)
# =====================================================================
def parti_liste(durum=None, tedarikci_kod=None, ara=None,
                tarih_bas=None, limit=500):
    try:
        where = ["1=1"]
        params = []
        if durum:
            where.append("Durum = ?")
            params.append(durum)
        if tedarikci_kod:
            where.append("TedarikciKod = ?")
            params.append(tedarikci_kod)
        if ara:
            where.append("(Baslik LIKE ? OR Kod LIKE ? OR TedarikciAd LIKE ?)")
            like = f"%{ara}%"
            params.extend([like, like, like])
        if tarih_bas:
            where.append("OlusmaTarih >= ?")
            params.append(tarih_bas)

        sql = f"""
            SELECT * FROM ithalat_parti
            WHERE {' AND '.join(where)}
            ORDER BY Id DESC
            LIMIT {int(limit)}
        """
        partiler = q(sql, tuple(params))
        if not partiler: return []

        parti_ids = [p['Id'] for p in partiler]
        ozet_dict = _parti_ozet_toplu(parti_ids)
        odeme_dict = _parti_odeme_eklentileri(parti_ids)

        sonuc = []
        for p in partiler:
            pid = p['Id']
            ozet = ozet_dict.get(pid, {})
            odeme = odeme_dict.get(pid, {})
            sonuc.append({
                'id': pid, 'kod': p['Kod'], 'baslik': p['Baslik'],
                'tedarikci_kod': p['TedarikciKod'],
                'tedarikci_ad': p['TedarikciAd'],
                'durum': p['Durum'], 'para_birimi': p['ParaBirimi'],
                'toplam_kg': p['ToplamKg'], 'toplam_cift': p['ToplamCift'],
                'tahmini_varis_tarih': p['TahminiVarisTarih'],
                'olusma_tarih': p['OlusmaTarih'],
                'tahmini_toplam': ozet.get('tahmini_toplam'),
                'gerceklesen_toplam': ozet.get('gerceklesen_toplam'),
                'etkin_toplam': ozet.get('etkin_toplam'),
                'kg_maliyet': ozet.get('kg_maliyet'),
                'cift_maliyet': ozet.get('cift_maliyet'),
                'sapma_yuzde': ozet.get('sapma_yuzde'),
                'ilk_odeme_tarih': odeme.get('ilk_odeme_tarih'),
                'geciken_odeme': odeme.get('geciken_odeme', False),
            })
        return sonuc
    except Exception as e:
        log.exception("parti_liste hata: %s", e)
        return []


def _parti_ozet_toplu(parti_ids):
    try:
        if not parti_ids: return {}
        placeholder = ','.join('?' for _ in parti_ids)
        rows = q(f"""
            SELECT k.PartiId, k.Tip, k.Kaynak,
                   SUM(k.TutarPartiPara) AS Toplam,
                   p.ToplamKg, p.ToplamCift
            FROM ithalat_maliyet_kalem k
            JOIN ithalat_parti p ON p.Id = k.PartiId
            WHERE k.PartiId IN ({placeholder})
              AND k.TutarPartiPara IS NOT NULL
              AND (k.Iptal IS NULL OR k.Iptal = 0)
            GROUP BY k.PartiId, k.Tip, k.Kaynak, p.ToplamKg, p.ToplamCift
        """, tuple(parti_ids))

        parti_data = {}
        for r in rows:
            pid = r['PartiId']
            if pid not in parti_data:
                parti_data[pid] = {
                    'tipler': {}, 'kg': r['ToplamKg'], 'cift': r['ToplamCift'],
                }
            d = parti_data[pid]
            if r['Tip'] not in d['tipler']:
                d['tipler'][r['Tip']] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            d['tipler'][r['Tip']][r['Kaynak']] = float(r['Toplam'] or 0)

        sonuc = {}
        for pid, d in parti_data.items():
            tahmini_toplam = sum(v['TAHMINI'] for v in d['tipler'].values())
            gerceklesen = sum(v['GERCEKLESEN'] for v in d['tipler'].values())
            etkin = 0.0
            # YENI: sadece ESLESEN tiplerden sapma hesabi
            eslesen_tahmini = 0.0
            eslesen_gerceklesen = 0.0
            eslesen_sayi = 0
            for vals in d['tipler'].values():
                t_tahmini = vals['TAHMINI']
                t_gercek = vals['GERCEKLESEN']
                etkin += (t_gercek if t_gercek > 0 else t_tahmini)
                if t_tahmini > 0 and t_gercek > 0:
                    eslesen_tahmini += t_tahmini
                    eslesen_gerceklesen += t_gercek
                    eslesen_sayi += 1
            kg_mal = round(etkin / d['kg'], 4) if (d['kg'] and d['kg'] > 0) else None
            cift_mal = round(etkin / d['cift'], 4) if (d['cift'] and d['cift'] > 0) else None
            # Sapma sadece ESLESEN tiplerden
            sapma = None
            if eslesen_tahmini > 0:
                sapma = round(
                    ((eslesen_gerceklesen - eslesen_tahmini) / eslesen_tahmini) * 100, 2,
                )
            sonuc[pid] = {
                'tahmini_toplam': round(tahmini_toplam, 2),
                'gerceklesen_toplam': round(gerceklesen, 2),
                'etkin_toplam': round(etkin, 2),
                'kg_maliyet': kg_mal, 'cift_maliyet': cift_mal,
                'sapma_yuzde': sapma,
                # YENI
                'eslesen_tip_sayisi': eslesen_sayi,
            }
        return sonuc
    except Exception as e:
        log.exception("_parti_ozet_toplu hata: %s", e)
        return {}


def _parti_odeme_eklentileri(parti_ids):
    try:
        if not parti_ids: return {}
        bugun = date.today().isoformat()
        placeholder = ','.join('?' for _ in parti_ids)
        rows = q(f"""
            SELECT PartiId,
                   MIN(CASE WHEN Durum IN ('BEKLIYOR','KISMEN_ODENDI')
                            THEN PlanlananTarih END) AS IlkAcik,
                   MAX(CASE
                       WHEN Durum IN ('BEKLIYOR','KISMEN_ODENDI')
                        AND PlanlananTarih < ?
                       THEN 1 ELSE 0 END) AS GecikmeVar
            FROM ithalat_odeme_plan
            WHERE PartiId IN ({placeholder})
            GROUP BY PartiId
        """, (bugun,) + tuple(parti_ids))
        sonuc = {}
        for r in rows:
            sonuc[r['PartiId']] = {
                'ilk_odeme_tarih': r['IlkAcik'],
                'geciken_odeme': bool(r['GecikmeVar']),
            }
        return sonuc
    except Exception as e:
        log.exception("_parti_odeme_eklentileri hata: %s", e)
        return {}


def parti_liste_kpi():
    try:
        bugun = date.today().isoformat()
        hafta = (date.today() + timedelta(days=7)).isoformat()
        son_12_ay = (date.today() - timedelta(days=365)).isoformat()

        r = qone("""
            SELECT COUNT(*) AS sayi FROM ithalat_parti
            WHERE Durum <> 'IPTAL' AND OlusmaTarih >= ?
        """, (son_12_ay,))
        toplam_parti = int(r['sayi'] or 0) if r else 0

        r = qone("SELECT COUNT(*) AS sayi FROM ithalat_parti WHERE Durum = 'AKTIF'")
        aktif_parti = int(r['sayi'] or 0) if r else 0

        aktif_tutar = 0.0
        aktif_para = 'USD'
        if aktif_parti > 0:
            aktif_partiler = q("SELECT Id, ParaBirimi FROM ithalat_parti WHERE Durum='AKTIF'")
            if aktif_partiler:
                ozet_dict = _parti_ozet_toplu([p['Id'] for p in aktif_partiler])
                for p in aktif_partiler:
                    o = ozet_dict.get(p['Id'], {})
                    aktif_tutar += o.get('etkin_toplam', 0) or 0
                para_sayim = {}
                for p in aktif_partiler:
                    pb = p['ParaBirimi']
                    para_sayim[pb] = para_sayim.get(pb, 0) + 1
                if para_sayim:
                    aktif_para = max(para_sayim, key=para_sayim.get)

        r = qone("""
            SELECT COUNT(*) AS sayi,
                   COALESCE(SUM(Tutar - COALESCE(OdenenTutar, 0)), 0) AS tutar
            FROM ithalat_odeme_plan
            WHERE Durum IN ('BEKLIYOR', 'KISMEN_ODENDI')
              AND PlanlananTarih BETWEEN ? AND ?
        """, (bugun, hafta))
        odeme_adet = int(r['sayi'] or 0) if r else 0
        odeme_tutar = float(r['tutar'] or 0) if r else 0.0

        odeme_para = 'USD'
        if odeme_adet > 0:
            r = qone("""
                SELECT ParaBirimi, COUNT(*) AS sayi
                FROM ithalat_odeme_plan
                WHERE Durum IN ('BEKLIYOR', 'KISMEN_ODENDI')
                  AND PlanlananTarih BETWEEN ? AND ?
                GROUP BY ParaBirimi
                ORDER BY sayi DESC
                LIMIT 1
            """, (bugun, hafta))
            if r: odeme_para = r['ParaBirimi']

        r = qone("""
            SELECT COUNT(DISTINCT PartiId) AS sayi FROM (
                SELECT pl.PartiId
                FROM ithalat_odeme_plan pl
                JOIN ithalat_parti p ON p.Id = pl.PartiId
                WHERE pl.Durum IN ('BEKLIYOR', 'KISMEN_ODENDI')
                  AND pl.PlanlananTarih < ?
                  AND p.Durum <> 'IPTAL'
                UNION
                SELECT p.Id AS PartiId
                FROM ithalat_parti p
                JOIN (
                    SELECT PartiId,
                           SUM(CASE WHEN Kaynak='TAHMINI'     THEN TutarPartiPara ELSE 0 END) AS Tahmini,
                           SUM(CASE WHEN Kaynak='GERCEKLESEN' THEN TutarPartiPara ELSE 0 END) AS Gerceklesen
                    FROM ithalat_maliyet_kalem
                    WHERE TutarPartiPara IS NOT NULL
                      AND (Iptal IS NULL OR Iptal = 0)
                    GROUP BY PartiId
                ) m ON m.PartiId = p.Id
                WHERE p.Durum NOT IN ('IPTAL', 'KAPALI')
                  AND m.Tahmini > 0 AND m.Gerceklesen > 0
                  AND ABS((m.Gerceklesen - m.Tahmini) / m.Tahmini) > 0.10
            ) AS Riskli
        """, (bugun,))
        riskli_parti = int(r['sayi'] or 0) if r else 0

        return {
            'toplam_parti': toplam_parti, 'aktif_parti': aktif_parti,
            'aktif_tutar': round(aktif_tutar, 2), 'aktif_para': aktif_para,
            'bu_hafta_odeme_adet': odeme_adet,
            'bu_hafta_odeme_tutar': round(odeme_tutar, 2),
            'bu_hafta_odeme_para': odeme_para,
            'riskli_parti': riskli_parti,
        }
    except Exception as e:
        log.exception("parti_liste_kpi hata: %s", e)
        return {
            'toplam_parti': None, 'aktif_parti': None,
            'aktif_tutar': None, 'aktif_para': None,
            'bu_hafta_odeme_adet': None, 'bu_hafta_odeme_tutar': None,
            'bu_hafta_odeme_para': None, 'riskli_parti': None,
        }


# =====================================================================
# LOOKUP - TEDARIKCI
# =====================================================================
def tedarikci_normalize(tedarikci_ad):
    """
    Tedarikci adini 3 parcaya ayir: orijinal, gorunen, kod.

    Kural:
      - Orijinal: parser'dan gelen ham ad (silinmeyecek)
      - Gorunen: ASCII/Latin harf yogunluklu kisim (Cince blokta dahil degil)
      - Kod: (ileride CariKod - simdilik None)

    Ornekler:
      "承钰寰球贸易有限公司 Chengyu Global" -> gorunen="Chengyu Global"
      "Chengyu Global Trading Co., Limited" -> gorunen=orijinal
      "承钰寰球贸易有限公司" -> gorunen=orijinal (fallback - Cince de olsa)

    Donus: {
        'orijinal_ad':  'Original name (as is)',
        'gorunen_ad':   'Name to show in UI (Latin-preferred)',
        'cari_kod':     None,  # ileride ERP entegrasyonu
    }
    """
    if not tedarikci_ad:
        return {'orijinal_ad': None, 'gorunen_ad': None, 'cari_kod': None}

    orijinal = str(tedarikci_ad).strip()
    if not orijinal:
        return {'orijinal_ad': None, 'gorunen_ad': None, 'cari_kod': None}

    # ASCII/Latin bolumunu cikarmaya calis
    # CJK Unicode aralik: \u4e00-\u9fff (ana) + \u3000-\u303f (punct)
    # ASCII (Latin): \u0020-\u007e
    import re as _re

    # Once hem Latin hem CJK var mi kontrol
    cjk_var = bool(_re.search(r'[\u4e00-\u9fff\u3000-\u303f]', orijinal))
    latin_var = bool(_re.search(r'[A-Za-z]{2,}', orijinal))

    gorunen = orijinal  # default fallback
    if cjk_var and latin_var:
        # Latin bolumunu cek - 2+ harf iceren kelimeleri birlestir
        latin_parcalar = _re.findall(
            r'[A-Za-z][A-Za-z0-9\-\.\,\s&\']*[A-Za-z0-9\.]',
            orijinal,
        )
        if latin_parcalar:
            # En uzun Latin parcasini al (firma adi genelde en uzun)
            latin_parcalar.sort(key=len, reverse=True)
            gorunen = latin_parcalar[0].strip(' ,.')

    return {
        'orijinal_ad':  orijinal[:200],
        'gorunen_ad':   (gorunen or orijinal)[:200],
        'cari_kod':     None,  # ileride ERP'den doldurulacak
    }


def tedarikci_lookup():
    try:
        rows = q("""
            SELECT DISTINCT
                   COALESCE(TedarikciKod, '') AS Kod,
                   COALESCE(TedarikciAd, '') AS Ad
            FROM ithalat_parti
            WHERE (TedarikciKod IS NOT NULL OR TedarikciAd IS NOT NULL)
              AND Durum <> 'IPTAL'
            ORDER BY Ad, Kod
        """)
        sonuc = []
        for r in rows:
            kod = (r['Kod'] or '').strip()
            ad = (r['Ad'] or '').strip()
            if not kod and not ad: continue
            sonuc.append({'kod': kod or ad, 'ad': ad or kod})
        return sonuc
    except Exception as e:
        log.exception("tedarikci_lookup hata: %s", e)
        return []


def tedarikci_arama(q_str, limit=10):
    """
    Tedarikci autocomplete - mevcut ithalat partilerindeki
    tedarikcilerden kullanici girdisiyle eslesen ilk N kayit.

    q_str: arama terimi (min 1 karakter)
    limit: max sonuc sayisi (default 10)

    Donus: [{'kod': 'WUXI', 'ad': 'Wuxi Rubber Co.'}]
    Cari_Kart MSSQL tablosu prod'da var ama mock ortamda yok.
    Sadece ithalat_parti tablosundaki tekil tedarikcilerden arama.
    """
    try:
        q_str = (q_str or '').strip()
        if not q_str:
            return []
        limit = int(limit) if limit else 10
        if limit < 1: limit = 1
        if limit > 50: limit = 50

        like = f"%{q_str}%"
        rows = q("""
            SELECT DISTINCT
                   COALESCE(TedarikciKod, '') AS Kod,
                   COALESCE(TedarikciAd, '')  AS Ad
            FROM ithalat_parti
            WHERE (TedarikciKod IS NOT NULL OR TedarikciAd IS NOT NULL)
              AND Durum <> 'IPTAL'
              AND (TedarikciAd LIKE ? OR TedarikciKod LIKE ?)
            ORDER BY Ad, Kod
        """, (like, like))

        sonuc = []
        gorulen = set()
        for r in rows:
            kod = (r['Kod'] or '').strip()
            ad = (r['Ad'] or '').strip()
            if not kod and not ad: continue
            key = (kod + '|' + ad).lower()
            if key in gorulen: continue
            gorulen.add(key)
            sonuc.append({'kod': kod or ad, 'ad': ad or kod})
            if len(sonuc) >= limit: break
        return sonuc
    except Exception as e:
        log.exception("tedarikci_arama hata: %s", e)
        return []


# =====================================================================
# ODEME PLANI + HAREKET (mevcut)
# =====================================================================
def odeme_plan_liste(parti_id):
    try:
        bugun = date.today().isoformat()
        rows = q("""
            SELECT pl.*,
                   CASE
                       WHEN pl.Durum IN ('BEKLIYOR', 'KISMEN_ODENDI')
                        AND pl.PlanlananTarih < ?
                       THEN 1 ELSE 0
                   END AS Gecikmis
            FROM ithalat_odeme_plan pl
            WHERE pl.PartiId = ?
            ORDER BY pl.Sira ASC, pl.PlanlananTarih ASC
        """, (bugun, parti_id))
        for r in rows:
            tutar = float(r.get('Tutar') or 0)
            odenen = float(r.get('OdenenTutar') or 0)
            r['Kalan'] = max(tutar - odenen, 0)
        return rows
    except Exception as e:
        log.exception("odeme_plan_liste hata: %s", e)
        return []


def odeme_plan_getir(plan_id):
    try:
        return qone("SELECT * FROM ithalat_odeme_plan WHERE Id = ?", (plan_id,))
    except Exception as e:
        log.exception("odeme_plan_getir hata: %s", e)
        return None


def odeme_plan_ekle(
    parti_id, planlanan_tarih, tutar, para_birimi,
    kullanici, sira=None, aciklama=None, odeme_tipi=None,
    cari_id=None, cari_kod=None, cari_ad=None, not_metni=None,
):
    try:
        if tutar is None or float(tutar) <= 0: return None
        if sira is None:
            r = qone(
                "SELECT COALESCE(MAX(Sira), 0) + 1 AS yeni "
                "FROM ithalat_odeme_plan WHERE PartiId = ?", (parti_id,))
            sira = r['yeni'] if r else 1
        simdi = _simdi()
        plan_id = qexec("""
            INSERT INTO ithalat_odeme_plan
                (PartiId, Sira, Aciklama, PlanlananTarih,
                 Tutar, ParaBirimi, OdemeTipi,
                 CariId, CariKod, CariAd,
                 OlusturanKullanici, OlusmaTarih, NotMetni)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            parti_id, sira, (aciklama or '')[:200], planlanan_tarih,
            tutar, para_birimi[:5], odeme_tipi,
            cari_id, cari_kod, cari_ad, kullanici, simdi, not_metni,
        ))
        audit.log(kullanici, 'EKLE', 'ithalat_odeme_plan', plan_id,
                  aciklama=f"Odeme plani: PartiId={parti_id} Sira={sira} "
                           f"Tutar={tutar} {para_birimi}",
                  modul='ithalat', alt_modul='odeme')
        return plan_id
    except Exception as e:
        log.exception("odeme_plan_ekle hata: %s", e)
        return None


def odeme_plan_guncelle(plan_id, kullanici, **alanlar):
    try:
        plan = odeme_plan_getir(plan_id)
        if not plan: return False
        if plan['Durum'] == PLAN_IPTAL: return False

        IZINLI = {
            'Aciklama': 'aciklama', 'PlanlananTarih': 'planlanan_tarih',
            'Tutar': 'tutar', 'ParaBirimi': 'para_birimi',
            'OdemeTipi': 'odeme_tipi', 'CariId': 'cari_id',
            'CariKod': 'cari_kod', 'CariAd': 'cari_ad',
            'NotMetni': 'not_metni', 'Sira': 'sira',
        }
        set_parts, params = [], []
        for db_col, py_key in IZINLI.items():
            if py_key in alanlar:
                set_parts.append(f"{db_col} = ?")
                params.append(alanlar[py_key])
        if not set_parts: return True
        params.append(plan_id)
        qexec(f"UPDATE ithalat_odeme_plan SET {', '.join(set_parts)} WHERE Id = ?",
              tuple(params))
        if 'tutar' in alanlar or 'para_birimi' in alanlar:
            _plan_odenen_yenile(plan_id)
        audit.log(kullanici, 'GUNCELLE', 'ithalat_odeme_plan', plan_id,
                  aciklama="Plan guncellendi",
                  modul='ithalat', alt_modul='odeme')
        return True
    except Exception as e:
        log.exception("odeme_plan_guncelle hata: %s", e)
        return False


def odeme_plan_iptal(plan_id, kullanici, sebep=None):
    try:
        plan = odeme_plan_getir(plan_id)
        if not plan: return False
        r = qone("""
            SELECT COUNT(*) AS sayi FROM ithalat_odeme_hareket
            WHERE OdemePlanId = ? AND Iptal = 0
        """, (plan_id,))
        if r and r['sayi'] > 0: return False
        qexec("UPDATE ithalat_odeme_plan SET Durum = ?, NotMetni = ? WHERE Id = ?",
              (PLAN_IPTAL, (sebep or '')[:500], plan_id))
        audit.log(kullanici, 'IPTAL', 'ithalat_odeme_plan', plan_id,
                  aciklama=f"Plan iptal. Sebep: {sebep or '-'}",
                  modul='ithalat', alt_modul='odeme')
        return True
    except Exception as e:
        log.exception("odeme_plan_iptal hata: %s", e)
        return False


def _plan_odenen_yenile(plan_id):
    try:
        r = qone("""
            SELECT COALESCE(SUM(Tutar), 0) AS toplam
            FROM ithalat_odeme_hareket
            WHERE OdemePlanId = ? AND Iptal = 0
        """, (plan_id,))
        odenen = float(r['toplam'] or 0) if r else 0
        plan = odeme_plan_getir(plan_id)
        if not plan: return
        tutar = float(plan['Tutar'] or 0)
        if odenen <= 0:
            yeni_durum = PLAN_BEKLIYOR
            tamamlanma = None
        elif odenen + 0.01 < tutar:
            yeni_durum = PLAN_KISMEN
            tamamlanma = None
        else:
            yeni_durum = PLAN_ODENDI
            tamamlanma = _simdi()
        if plan['Durum'] != PLAN_IPTAL:
            qexec("""UPDATE ithalat_odeme_plan
                     SET OdenenTutar = ?, Durum = ?, TamamlanmaTarih = ?
                     WHERE Id = ?""",
                  (odenen, yeni_durum, tamamlanma, plan_id))
    except Exception as e:
        log.exception("_plan_odenen_yenile hata: %s", e)


def odeme_hareket_liste(parti_id):
    try:
        return q("""
            SELECT * FROM ithalat_odeme_hareket
            WHERE PartiId = ?
            ORDER BY Tarih DESC, Id DESC
        """, (parti_id,))
    except Exception as e:
        log.exception("odeme_hareket_liste hata: %s", e)
        return []


def odeme_hareket_getir(hareket_id):
    try:
        return qone("SELECT * FROM ithalat_odeme_hareket WHERE Id = ?", (hareket_id,))
    except Exception as e:
        log.exception("odeme_hareket_getir hata: %s", e)
        return None


def odeme_hareket_ekle(
    parti_id, tarih, tutar, para_birimi,
    kullanici, odeme_plan_id=None,
    odeme_yontemi=None, banka_ref=None,
    cari_id=None, cari_kod=None, cari_ad=None,
    manuel_kur=None, not_metni=None,
):
    try:
        if tutar is None or float(tutar) <= 0: return None
        parti = parti_getir(parti_id)
        if not parti: return None
        parti_para = parti['ParaBirimi']
        kur_degeri, tutar_parti = _kur_hesapla(
            tutar, para_birimi, parti_para, manuel_kur,
            ana_kur_try=(parti['AnaKurTRY'] if 'AnaKurTRY' in parti.keys() else None),
        )
        simdi = _simdi()
        hareket_id = qexec("""
            INSERT INTO ithalat_odeme_hareket
                (PartiId, OdemePlanId, Tarih, Tutar, ParaBirimi,
                 KurTarihi, KurDegeri, TutarPartiPara,
                 OdemeYontemi, BankaRef,
                 CariId, CariKod, CariAd,
                 NotMetni, KaydedenKullanici, OlusmaTarih)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            parti_id, odeme_plan_id, tarih, tutar, para_birimi[:5],
            simdi, kur_degeri, tutar_parti,
            odeme_yontemi, banka_ref,
            cari_id, cari_kod, cari_ad,
            not_metni, kullanici, simdi,
        ))
        if odeme_plan_id:
            _plan_odenen_yenile(odeme_plan_id)
        audit.log(kullanici, 'EKLE', 'ithalat_odeme_hareket', hareket_id,
                  aciklama=f"Odeme hareketi: PartiId={parti_id} "
                           f"PlanId={odeme_plan_id} Tutar={tutar} {para_birimi}",
                  modul='ithalat', alt_modul='odeme')
        return hareket_id
    except Exception as e:
        log.exception("odeme_hareket_ekle hata: %s", e)
        return None


def odeme_hareket_iptal(hareket_id, kullanici, sebep=None):
    try:
        hareket = odeme_hareket_getir(hareket_id)
        if not hareket: return False
        if hareket['Iptal']: return True
        qexec("UPDATE ithalat_odeme_hareket SET Iptal = 1, IptalSebep = ? WHERE Id = ?",
              ((sebep or '')[:500], hareket_id))
        if hareket.get('OdemePlanId'):
            _plan_odenen_yenile(hareket['OdemePlanId'])
        audit.log(kullanici, 'IPTAL', 'ithalat_odeme_hareket', hareket_id,
                  aciklama=f"Hareket iptal. Sebep: {sebep or '-'}",
                  modul='ithalat', alt_modul='odeme')
        return True
    except Exception as e:
        log.exception("odeme_hareket_iptal hata: %s", e)
        return False


# =====================================================================
# DURUM GECMISI
# =====================================================================
def durum_gecmisi(parti_id, limit=50):
    try:
        return q("""
            SELECT Id, Tarih, KullaniciAdi AS Kullanici,
                   Aciklama, Islem
            FROM sistem_audit
            WHERE TabloAdi = 'ithalat_parti'
              AND KayitId = ?
              AND Islem IN ('DURUM_DEGISIM', 'EKLE')
            ORDER BY Tarih DESC, Id DESC
            LIMIT ?
        """, (parti_id, int(limit)))
    except Exception as e:
        log.exception("durum_gecmisi hata: %s", e)
        return []


def geciken_odemeler():
    try:
        bugun = date.today().isoformat()
        return q("""
            SELECT pl.Id AS plan_id, pl.PartiId AS parti_id,
                   p.Kod AS parti_kod, p.Baslik AS parti_baslik,
                   pl.Sira, pl.Aciklama, pl.PlanlananTarih AS planlanan_tarih,
                   pl.Tutar AS tutar, pl.ParaBirimi AS para_birimi,
                   pl.OdenenTutar AS odenen,
                   pl.CariKod AS cari_kod, pl.CariAd AS cari_ad
            FROM ithalat_odeme_plan pl
            JOIN ithalat_parti p ON p.Id = pl.PartiId
            WHERE pl.Durum IN ('BEKLIYOR', 'KISMEN_ODENDI')
              AND pl.PlanlananTarih < ?
            ORDER BY pl.PlanlananTarih ASC
        """, (bugun,))
    except Exception as e:
        log.exception("geciken_odemeler hata: %s", e)
        return []


# =====================================================================
# YENI: URUN KARTI
# =====================================================================
# Eslesen partileri aramanin 3 stratejisi:
# 1. Proforma FOB kalemi: Aciklama LIKE 'Urun:%' + arama icerir
# 2. GTIP tam eslesme: GUMRUK kalemi NotMetni icinde "GTIP: {arama}"
# 3. Genis LIKE: Aciklama veya NotMetni icinde arama icerir (fallback)
#
# Kural: ToplamCift IS NULL veya <= 0 olan partiler TAMAMEN dislanir
# Kural: Ortalama TUM eslesen partiler uzerinden (son 3 sadece gosterim)
# Kural: Navlun ortalama sadece NAVLUN+USD olan partiler
# Kural: FOB ortalama sadece FOB+USD olan partiler

def _adet_gecerli_parti_idler(aday_parti_idler):
    """
    Aday parti ID'lerinden sadece ToplamCift > 0 olanlari dondurur.
    Boylece tum sonraki hesap bu filtrelenmis listeyle yapilir.
    """
    if not aday_parti_idler:
        return []
    try:
        placeholder = ','.join('?' for _ in aday_parti_idler)
        rows = q(f"""
            SELECT Id FROM ithalat_parti
            WHERE Id IN ({placeholder})
              AND ToplamCift IS NOT NULL
              AND ToplamCift > 0
        """, tuple(aday_parti_idler))
        return [r['Id'] for r in rows]
    except Exception as e:
        log.exception("_adet_gecerli_parti_idler hata: %s", e)
        return []


def _parti_idler_strateji1(arama):
    """
    Strateji 1: FOB + TAHMINI + Aciklama 'Urun:%' prefix + arama icerir
    Proforma parser'dan gelen FOB kalemlerinin aciklamasi "Urun: 2507-3 (...)" formatinda.
    """
    try:
        if not arama:
            return []
        like_arama = f"%{arama}%"
        rows = q("""
            SELECT DISTINCT k.PartiId
            FROM ithalat_maliyet_kalem k
            INNER JOIN ithalat_parti p ON p.Id = k.PartiId
            WHERE k.Tip = 'FOB'
              AND k.Kaynak = 'TAHMINI'
              AND k.Aciklama LIKE 'Urun:%'
              AND k.Aciklama LIKE ?
              AND (k.Iptal IS NULL OR k.Iptal = 0)
              AND p.ToplamCift IS NOT NULL
              AND p.ToplamCift > 0
            ORDER BY k.PartiId DESC
        """, (like_arama,))
        return [r['PartiId'] for r in rows]
    except Exception as e:
        log.exception("_parti_idler_strateji1 hata: %s", e)
        return []


def _parti_idler_strateji2_gtip(arama):
    """
    Strateji 2: GTIP tam eslesme.
    Beyanname parser'dan gelen GUMRUK kalemlerinin NotMetni icinde
    "GTIP: 39013000" sablonunda gecer.
    LIKE ile kabaca filtrele, sonra Python regex ile tam eslesme dogrula.
    """
    try:
        if not arama:
            return []
        # Bosluk, virgul veya nokta ile sinirlandirilmis tam eslesme icin
        # LIKE yeterli degil; Python regex ile kontrol gerekir.
        # Once genis LIKE ile aday partileri cek:
        like_arama = f"%GTIP: {arama}%"
        aday = q("""
            SELECT DISTINCT k.PartiId, k.NotMetni
            FROM ithalat_maliyet_kalem k
            INNER JOIN ithalat_parti p ON p.Id = k.PartiId
            WHERE k.Tip = 'GUMRUK'
              AND k.NotMetni LIKE ?
              AND (k.Iptal IS NULL OR k.Iptal = 0)
              AND p.ToplamCift IS NOT NULL
              AND p.ToplamCift > 0
            ORDER BY k.PartiId DESC
        """, (like_arama,))

        # Regex dogrulama: "GTIP: 39013000" (sonunda rakam olmasin - tam eslesme)
        tam_pat = re.compile(r'GTIP:\s*' + re.escape(arama) + r'(?!\d)')
        sonuc = []
        gorulen = set()
        for r in aday:
            pid = r['PartiId']
            if pid in gorulen:
                continue
            not_metni = r.get('NotMetni') or ''
            if tam_pat.search(not_metni):
                sonuc.append(pid)
                gorulen.add(pid)
        return sonuc
    except Exception as e:
        log.exception("_parti_idler_strateji2_gtip hata: %s", e)
        return []


def _parti_idler_strateji3_fallback(arama):
    """
    Strateji 3: Aciklama veya NotMetni icinde arama gecer (geniste, fallback).
    """
    try:
        if not arama:
            return []
        like_arama = f"%{arama}%"
        rows = q("""
            SELECT DISTINCT k.PartiId
            FROM ithalat_maliyet_kalem k
            INNER JOIN ithalat_parti p ON p.Id = k.PartiId
            WHERE (k.Aciklama LIKE ? OR k.NotMetni LIKE ?)
              AND (k.Iptal IS NULL OR k.Iptal = 0)
              AND p.ToplamCift IS NOT NULL
              AND p.ToplamCift > 0
            ORDER BY k.PartiId DESC
        """, (like_arama, like_arama))
        return [r['PartiId'] for r in rows]
    except Exception as e:
        log.exception("_parti_idler_strateji3_fallback hata: %s", e)
        return []


def _parti_tasima_tipi(parti_id):
    """
    NAVLUN kalemleri icinden en yuksek tutarli alt_kod = tasima tipi.
    AIR / SEA / TRUCK / RAIL
    Sadece gercek tasima alt_kod'lari - EXW_HANDLING/FUEL/HANDLING haric.
    """
    try:
        rows = q("""
            SELECT AltKod, SUM(Tutar) AS toplam
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ?
              AND Tip = 'NAVLUN'
              AND AltKod IN ('AIR', 'SEA', 'TRUCK', 'RAIL')
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY AltKod
            ORDER BY toplam DESC
            LIMIT 1
        """, (parti_id,))
        return rows[0]['AltKod'] if rows else None
    except Exception as e:
        log.exception("_parti_tasima_tipi hata: %s", e)
        return None


def _parti_gerceklesen_toplamlar(parti_id):
    """
    Partinin GERCEKLESEN kalemlerini tip x para_birimi bazinda topla.

    Donus: {
        'USD': {'FOB': X, 'NAVLUN': Y, 'GUMRUK': Z, 'SIGORTA': ...,
                '_TOPLAM': sum},
        'TRY': {...},
    }
    Yalnizca GERCEKLESEN + Iptal=0 kalemler dahil.
    """
    try:
        rows = q("""
            SELECT Tip, ParaBirimi, SUM(Tutar) AS toplam
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ?
              AND Kaynak = 'GERCEKLESEN'
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, ParaBirimi
        """, (parti_id,))

        toplamlar = {}
        for r in rows:
            para = r['ParaBirimi']
            tip = r['Tip']
            tutar = float(r['toplam'] or 0)
            if para not in toplamlar:
                toplamlar[para] = {'_TOPLAM': 0.0}
            toplamlar[para][tip] = tutar
            toplamlar[para]['_TOPLAM'] += tutar
        return toplamlar
    except Exception as e:
        log.exception("_parti_gerceklesen_toplamlar hata: %s", e)
        return {}


def _parti_etkin_tip_toplamlar(parti_id, para):
    """
    Bir para biriminde, her tip icin etkin toplam:
      gerceklesen varsa gerceklesen, yoksa tahmini.
    Donus: {'FOB': X, 'NAVLUN': Y, ...}
    """
    try:
        rows = q("""
            SELECT Tip, Kaynak, SUM(Tutar) AS toplam
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ?
              AND ParaBirimi = ?
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, Kaynak
        """, (parti_id, para))

        tip_bazinda = {}
        for r in rows:
            tip = r['Tip']
            if tip not in tip_bazinda:
                tip_bazinda[tip] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            tip_bazinda[tip][r['Kaynak']] = float(r['toplam'] or 0)

        etkin = {}
        for tip, vals in tip_bazinda.items():
            etkin[tip] = vals['GERCEKLESEN'] if vals['GERCEKLESEN'] > 0 else vals['TAHMINI']
        return etkin
    except Exception as e:
        log.exception("_parti_etkin_tip_toplamlar hata: %s", e)
        return {}


def _parti_gtip_bul(parti_id):
    try:
        rows = q("""
            SELECT NotMetni
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ?
              AND Tip = 'GUMRUK'
              AND NotMetni LIKE '%GTIP:%'
              AND (Iptal IS NULL OR Iptal = 0)
            LIMIT 5
        """, (parti_id,))

        if not rows:
            return None

        # Her satirda GTIP ara, ilki dondur
        pat = re.compile(r'GTIP:\s*(\d{6,12})')
        for r in rows:
            metin = r.get('NotMetni') or ''
            m = pat.search(metin)
            if m:
                return m.group(1)
        return None
    except Exception as e:
        log.exception("_parti_gtip_bul hata: %s", e)
        return None


def _kiyas_kriteri_belirle(strateji_adi, parti_ozetleri, bu_parti_ozet=None):
    """
    Eslesen partiler arasinda kiyas kriterinin guvenirligini belirle.

    Kurallar:
      strateji = 'urun_kodu' ise:
          - Tum partilerde ayni GTIP varsa     -> 'urun_kodu_gtip' (en guvenilir)
          - Bir kismi GTIP yoksa               -> 'urun_kodu_kismi_gtip' (kismi)
          - Farkli GTIP varsa                  -> 'urun_kodu_farkli_gtip' (supheli)
          - Hic GTIP yoksa                     -> 'urun_kodu_only'
      strateji = 'gtip' ise                    -> 'gtip_only'
      strateji = 'genis_arama' ise             -> 'genis_arama'

    Donus: dict
      {
        'kriter': 'urun_kodu_gtip' | ...,
        'kriter_aciklama': 'Aciklayici metin',
        'gtip_eslesme_sayisi': int,
        'gtip_olmayan_sayisi': int,
        'farkli_gtip_sayisi': int,
        'farkli_tedarikci_sayisi': int,
        'bu_parti_gtip': str | None,
        'guvenilirlik': 'yuksek' | 'orta' | 'dusuk' | 'yok',
      }
    """
    try:
        # Tedarikciler (tekil)
        tedarikciler = set()
        for p in parti_ozetleri:
            ad = p.get('tedarikci_ad')
            if ad and ad != '—':
                tedarikciler.add(ad)

        # Bu partinin GTIP'i (referans)
        ref_gtip = None
        if bu_parti_ozet:
            ref_gtip = bu_parti_ozet.get('gtip')

        # GTIP sayim - bu parti DISINDA kalan partiler uzerinde
        digerleri = [p for p in parti_ozetleri
                     if bu_parti_ozet is None
                     or p.get('parti_id') != bu_parti_ozet.get('parti_id')]

        gtip_eslesme = 0
        gtip_olmayan = 0
        gtip_farkli = 0

        for p in digerleri:
            pg = p.get('gtip')
            if pg is None:
                gtip_olmayan += 1
            elif ref_gtip is None:
                # Bu partide GTIP yok, ama digerinde var
                # Bu durumda eslesme sayilmaz
                gtip_olmayan += 1
            elif pg == ref_gtip:
                gtip_eslesme += 1
            else:
                gtip_farkli += 1

        sonuc = {
            'gtip_eslesme_sayisi':    gtip_eslesme,
            'gtip_olmayan_sayisi':    gtip_olmayan,
            'farkli_gtip_sayisi':     gtip_farkli,
            'farkli_tedarikci_sayisi': len(tedarikciler),
            'bu_parti_gtip':          ref_gtip,
        }

        # Kriter belirleme
        if strateji_adi == 'urun_kodu':
            if len(digerleri) == 0:
                sonuc['kriter'] = 'urun_kodu_tek_alim'
                sonuc['kriter_aciklama'] = (
                    'Bu urun sadece bu partide yer aliyor, '
                    'kiyas icin gecmis alim yok'
                )
                sonuc['guvenilirlik'] = 'yok'
            elif gtip_farkli > 0:
                sonuc['kriter'] = 'urun_kodu_farkli_gtip'
                sonuc['kriter_aciklama'] = (
                    f"Urun kodu ayni ama {gtip_farkli} partide GTIP farkli. "
                    "Farkli mal olabilir, kiyas dikkatli yorumlanmali."
                )
                sonuc['guvenilirlik'] = 'dusuk'
            elif gtip_eslesme > 0 and gtip_olmayan == 0:
                sonuc['kriter'] = 'urun_kodu_gtip'
                sonuc['kriter_aciklama'] = (
                    f"Urun kodu + GTIP eslesmesi "
                    f"({gtip_eslesme} eski alim). "
                    "Guvenilir kiyas."
                )
                sonuc['guvenilirlik'] = 'yuksek'
            elif gtip_eslesme > 0 and gtip_olmayan > 0:
                sonuc['kriter'] = 'urun_kodu_kismi_gtip'
                sonuc['kriter_aciklama'] = (
                    f"Urun kodu tum alimlarda ayni. "
                    f"{gtip_eslesme} partide GTIP de ayni, "
                    f"{gtip_olmayan} partide GTIP bilgisi yok (beyanname eklenmemis)."
                )
                sonuc['guvenilirlik'] = 'orta'
            else:
                # gtip_eslesme = 0, gtip_olmayan = len(digerleri)
                sonuc['kriter'] = 'urun_kodu_only'
                if ref_gtip is None:
                    sonuc['kriter_aciklama'] = (
                        "Urun koduna gore kiyaslandi. "
                        "Hicbir partide (bu dahil) GTIP bilgisi yok, "
                        "beyannameler henuz yuklenmemis olabilir."
                    )
                else:
                    sonuc['kriter_aciklama'] = (
                        "Urun koduna gore kiyaslandi. "
                        "Diger partilerde GTIP bilgisi yok."
                    )
                sonuc['guvenilirlik'] = 'orta'
        elif strateji_adi == 'gtip':
            sonuc['kriter'] = 'gtip_only'
            sonuc['kriter_aciklama'] = (
                "GTIP koduna gore kiyaslandi "
                "(urun kodu eslesmesi bulunamadi)"
            )
            sonuc['guvenilirlik'] = 'orta'
        elif strateji_adi == 'genis_arama':
            sonuc['kriter'] = 'genis_arama'
            sonuc['kriter_aciklama'] = (
                "Genis metin aramasi ile eslesme bulundu. "
                "Urun kodu veya GTIP net degil, kiyas yaklasik."
            )
            sonuc['guvenilirlik'] = 'dusuk'
        else:
            sonuc['kriter'] = 'bilinmiyor'
            sonuc['kriter_aciklama'] = 'Kiyas kriteri belirlenemedi'
            sonuc['guvenilirlik'] = 'dusuk'

        return sonuc

    except Exception as e:
        log.exception("_kiyas_kriteri_belirle hata: %s", e)
        return {
            'kriter': 'hata',
            'kriter_aciklama': 'Kriter hesaplanamadi',
            'guvenilirlik': 'dusuk',
            'gtip_eslesme_sayisi':     0,
            'gtip_olmayan_sayisi':     0,
            'farkli_gtip_sayisi':      0,
            'farkli_tedarikci_sayisi': 0,
            'bu_parti_gtip':           None,
        }


def _parti_urun_kart_ozeti(parti_id):
    """
    Bir parti icin urun kart verisi.
    Kural: Parti GERCEKLESEN kalemi olmalidir (yoksa ortalamaya dahil edilmez).
    """
    try:
        parti = parti_getir(parti_id)
        if not parti:
            return None
        adet = parti.get('ToplamCift')
        if not adet or adet <= 0:
            return None

        # Gerceklesen toplamlar
        gerc = _parti_gerceklesen_toplamlar(parti_id)
        # Eger hicbir GERCEKLESEN kalem yoksa bu parti ortalamaya dahil edilmez
        if not gerc:
            return None

        # Etkin toplamlar (gerceklesen yoksa tahmini) - gosterim icin
        etkin_usd = _parti_etkin_tip_toplamlar(parti_id, 'USD')
        etkin_try = _parti_etkin_tip_toplamlar(parti_id, 'TRY')
        etkin_toplam_usd = sum(etkin_usd.values())
        etkin_toplam_try = sum(etkin_try.values())

        fob_usd_g = gerc.get('USD', {}).get('FOB', 0.0)
        navlun_usd_g = gerc.get('USD', {}).get('NAVLUN', 0.0)

        cift_maliyet_usd = etkin_toplam_usd / adet if etkin_toplam_usd > 0 else None
        cift_maliyet_try = etkin_toplam_try / adet if etkin_toplam_try > 0 else None

        return {
            'parti_id':         parti_id,
            'kod':              parti.get('Kod'),
            'baslik':           parti.get('Baslik'),
            'tarih':            (parti.get('OlusmaTarih') or '')[:10],
            'tedarikci_ad':     parti.get('TedarikciAd') or parti.get('TedarikciKod') or '—',
            'toplam_cift':      int(adet),
            'durum':            parti.get('Durum'),
            'para_birimi':      parti.get('ParaBirimi'),
            'gtip':             _parti_gtip_bul(parti_id),  # YENI: beyannameden GTIP
            # Hesaplar
            'etkin_toplam_usd': round(etkin_toplam_usd, 2) if etkin_toplam_usd else 0,
            'etkin_toplam_try': round(etkin_toplam_try, 2) if etkin_toplam_try else 0,
            'cift_maliyet_usd': round(cift_maliyet_usd, 4) if cift_maliyet_usd else None,
            'cift_maliyet_try': round(cift_maliyet_try, 4) if cift_maliyet_try else None,
            'fob_birim_usd':    round(fob_usd_g / adet, 4) if fob_usd_g > 0 else None,
            'navlun_cift_usd':  round(navlun_usd_g / adet, 4) if navlun_usd_g > 0 else None,
            'tasima_tipi':      _parti_tasima_tipi(parti_id),
            # Ortalamalar icin ham veriler
            '_ham_fob_usd':    fob_usd_g,
            '_ham_navlun_usd': navlun_usd_g,
        }
    except Exception as e:
        log.exception("_parti_urun_kart_ozeti hata: %s", e)
        return None


def _agirlikli_ortalama(partiler, deger_anahtar, adet_anahtar='toplam_cift',
                        filtre_anahtar=None):
    """
    Genel amacli agirlikli ortalama.

      ort = sum(deger * adet) / sum(adet)
    deger = parti icindeki birim deger (cift_maliyet_usd, fob_birim_usd, vs)
    adet = toplam_cift

    filtre_anahtar: Bu anahtarin degeri > 0 olan partiler dahil edilir.
      Orn: FOB ortalamasinda sadece _ham_fob_usd > 0 olan partiler.

    Donus: (ort_deger, dahil_edilen_parti_sayisi, dahil_toplam_cift)
    """
    try:
        pay = 0.0
        payda = 0.0
        dahil_sayi = 0
        dahil_cift = 0
        for p in partiler:
            deger = p.get(deger_anahtar)
            adet = p.get(adet_anahtar) or 0
            if deger is None:
                continue
            if adet <= 0:
                continue
            if filtre_anahtar is not None:
                filtre_deger = p.get(filtre_anahtar) or 0
                if filtre_deger <= 0:
                    continue
            pay += float(deger) * adet
            payda += adet
            dahil_sayi += 1
            dahil_cift += adet
        if payda <= 0:
            return None, 0, 0
        return round(pay / payda, 4), dahil_sayi, int(dahil_cift)
    except Exception as e:
        log.exception("_agirlikli_ortalama hata: %s", e)
        return None, 0, 0


def urun_kart_getir(arama, son_gosterim_limit=3, bu_parti_id=None):
    """
    Urun kart endpoint'inin ana fonksiyonu.

    arama: string (kullanicidan gelen arama)
    son_gosterim_limit: UI'da gosterilecek son N parti (default 3)
    bu_parti_id: int | None. Kiyaslama kaynagi parti ID'si.
                 Verilirse: 'bu parti haric ortalama' ve 'sapma %' hesaplanir.

    Donus: dict (response formati - routes kullanir)
    Fail-safe: hata olursa bulundu=False dondurur.
    """
    bos_sonuc = {
        'arama': arama or '',
        'bulundu': False,
        'strateji': None,
        'toplam_alim': 0,
        'son_alim_tarihi': None,
        'mesaj': '',
        'bu_parti_id': bu_parti_id,
        'partiler': [],
        'ortalama': None,
        'kiyas': None,
        'tedarikci_kirilim': [],
        'tasima_kirilim': [],
    }

    try:
        arama = (arama or '').strip()
        if not arama:
            bos_sonuc['mesaj'] = 'Arama terimi bos'
            return bos_sonuc

        # 3 stratejiyi sirayla dene
        strateji_adi = None
        parti_idler = _parti_idler_strateji1(arama)
        if parti_idler:
            strateji_adi = 'urun_kodu'
        else:
            parti_idler = _parti_idler_strateji2_gtip(arama)
            if parti_idler:
                strateji_adi = 'gtip'
            else:
                parti_idler = _parti_idler_strateji3_fallback(arama)
                if parti_idler:
                    strateji_adi = 'genis_arama'

        if not parti_idler:
            bos_sonuc['mesaj'] = 'Eslesen parti bulunamadi'
            return bos_sonuc

        # Emniyet: adet kontrolu tekrar
        parti_idler = _adet_gecerli_parti_idler(parti_idler)
        if not parti_idler:
            bos_sonuc['strateji'] = strateji_adi
            bos_sonuc['mesaj'] = 'Eslesme var ama hicbirinde gecerli cift adedi yok'
            return bos_sonuc

        # Her parti icin ozet
        parti_ozetleri = []
        for pid in parti_idler:
            ozet = _parti_urun_kart_ozeti(pid)
            if ozet:
                parti_ozetleri.append(ozet)

        if not parti_ozetleri:
            bos_sonuc['strateji'] = strateji_adi
            bos_sonuc['mesaj'] = 'Gecerli (GERCEKLESEN kalem) parti bulunamadi'
            return bos_sonuc

        # Tarihe gore azalan sirala (en yeni ilk)
        parti_ozetleri.sort(
            key=lambda p: (p.get('tarih') or ''),
            reverse=True,
        )

        # ==================================================================
        # TUM ALIMLARIN AGIRLIKLI ORTALAMALARI (bu parti DAHIL)
        # ==================================================================
        ort_cift_usd, _, _ = _agirlikli_ortalama(
            parti_ozetleri, 'cift_maliyet_usd',
        )
        ort_cift_try, dahil_try, _ = _agirlikli_ortalama(
            parti_ozetleri, 'cift_maliyet_try',
        )
        ort_fob_usd, fob_dahil, _ = _agirlikli_ortalama(
            parti_ozetleri, 'fob_birim_usd',
            filtre_anahtar='_ham_fob_usd',
        )
        ort_navlun_usd, navlun_dahil, _ = _agirlikli_ortalama(
            parti_ozetleri, 'navlun_cift_usd',
            filtre_anahtar='_ham_navlun_usd',
        )
        toplam_cift_tum = sum(p['toplam_cift'] for p in parti_ozetleri)

        ortalama = {
            'hesaplama_tipi':   'agirlikli',
            'kapsam':           'tum_alimlar',
            'dahil_edilen_alim': len(parti_ozetleri),
            'toplam_cift':      toplam_cift_tum,
            'cift_maliyet_usd': ort_cift_usd,
            'cift_maliyet_try': ort_cift_try,
            'cift_maliyet_try_dahil': dahil_try,
            'fob_birim_usd':    ort_fob_usd,
            'fob_dahil_alim':   fob_dahil,
            'navlun_cift_usd':  ort_navlun_usd,
            'navlun_dahil_alim': navlun_dahil,
        }

        # ==================================================================
        # MIN / MAX parti (cift_maliyet_usd bazli, sadece USD degeri olanlar)
        # ==================================================================
        min_parti = None
        max_parti = None
        usd_olan = [p for p in parti_ozetleri if p.get('cift_maliyet_usd') is not None]
        if usd_olan:
            min_p = min(usd_olan, key=lambda p: p['cift_maliyet_usd'])
            max_p = max(usd_olan, key=lambda p: p['cift_maliyet_usd'])
            min_parti = {
                'parti_id': min_p['parti_id'],
                'kod': min_p['kod'],
                'tarih': min_p['tarih'],
                'cift_maliyet_usd': min_p['cift_maliyet_usd'],
                'tedarikci_ad': min_p['tedarikci_ad'],
            }
            max_parti = {
                'parti_id': max_p['parti_id'],
                'kod': max_p['kod'],
                'tarih': max_p['tarih'],
                'cift_maliyet_usd': max_p['cift_maliyet_usd'],
                'tedarikci_ad': max_p['tedarikci_ad'],
            }

        # ==================================================================
        # KIYAS: bu_parti_id verildiyse
        # ==================================================================
        kiyas = None
        bu_parti_ozet = None
        if bu_parti_id is not None:
            try:
                bu_parti_id_int = int(bu_parti_id)
                bu_parti_ozet = next(
                    (p for p in parti_ozetleri if p['parti_id'] == bu_parti_id_int),
                    None,
                )
            except Exception:
                bu_parti_ozet = None

        if bu_parti_ozet:
            # Bu parti haric ortalama (kiyaslamanin ana metrigi)
            digerleri = [p for p in parti_ozetleri
                         if p['parti_id'] != bu_parti_ozet['parti_id']]

            onceki_ort_usd, onceki_dahil_usd, _ = _agirlikli_ortalama(
                digerleri, 'cift_maliyet_usd',
            )
            onceki_ort_try, onceki_dahil_try, _ = _agirlikli_ortalama(
                digerleri, 'cift_maliyet_try',
            )

            bu_cift_usd = bu_parti_ozet.get('cift_maliyet_usd')
            bu_cift_try = bu_parti_ozet.get('cift_maliyet_try')

            # Sapma hesabi USD (ana metrik)
            sapma_usd = None
            sapma_yon_usd = None
            if bu_cift_usd is not None and onceki_ort_usd and onceki_ort_usd > 0:
                sapma_usd = round(
                    ((bu_cift_usd - onceki_ort_usd) / onceki_ort_usd) * 100, 2,
                )
                if sapma_usd > 0.01:
                    sapma_yon_usd = 'pahali'
                elif sapma_usd < -0.01:
                    sapma_yon_usd = 'ucuz'
                else:
                    sapma_yon_usd = 'esit'

            # Sapma TRY
            sapma_try = None
            sapma_yon_try = None
            if bu_cift_try is not None and onceki_ort_try and onceki_ort_try > 0:
                sapma_try = round(
                    ((bu_cift_try - onceki_ort_try) / onceki_ort_try) * 100, 2,
                )
                if sapma_try > 0.01:
                    sapma_yon_try = 'pahali'
                elif sapma_try < -0.01:
                    sapma_yon_try = 'ucuz'
                else:
                    sapma_yon_try = 'esit'

            # Para birimi uyari - bu parti ile digerler karisik mi?
            bu_para_var = set()
            if bu_cift_usd is not None: bu_para_var.add('USD')
            if bu_cift_try is not None: bu_para_var.add('TRY')
            dig_para_var = set()
            for p in digerleri:
                if p.get('cift_maliyet_usd') is not None: dig_para_var.add('USD')
                if p.get('cift_maliyet_try') is not None: dig_para_var.add('TRY')
            para_birimi_karisik = (
                (bu_para_var - dig_para_var) or (dig_para_var - bu_para_var)
            ) and len(digerleri) > 0

            # YENI: Kiyas kriteri analizi (bu_parti referansiyla)
            kriter_bilgi = _kiyas_kriteri_belirle(
                strateji_adi, parti_ozetleri, bu_parti_ozet,
            )

            kiyas = {
                'bu_parti': {
                    'parti_id': bu_parti_ozet['parti_id'],
                    'kod': bu_parti_ozet['kod'],
                    'tarih': bu_parti_ozet['tarih'],
                    'cift_maliyet_usd': bu_cift_usd,
                    'cift_maliyet_try': bu_cift_try,
                    'tedarikci_ad': bu_parti_ozet['tedarikci_ad'],
                    'gtip': bu_parti_ozet.get('gtip'),
                },
                'onceki_ortalama': {
                    'dahil_edilen_alim_usd': onceki_dahil_usd,
                    'dahil_edilen_alim_try': onceki_dahil_try,
                    'cift_maliyet_usd': onceki_ort_usd,
                    'cift_maliyet_try': onceki_ort_try,
                },
                'sapma_usd': sapma_usd,
                'sapma_yon_usd': sapma_yon_usd,
                'sapma_try': sapma_try,
                'sapma_yon_try': sapma_yon_try,
                'para_birimi_karisik': bool(para_birimi_karisik),
                'min_parti': min_parti,
                'max_parti': max_parti,
                'yeterli_veri': len(digerleri) > 0,
                # YENI alanlar
                'kriter':                 kriter_bilgi.get('kriter'),
                'kriter_aciklama':        kriter_bilgi.get('kriter_aciklama'),
                'gtip_eslesme_sayisi':    kriter_bilgi.get('gtip_eslesme_sayisi', 0),
                'gtip_olmayan_sayisi':    kriter_bilgi.get('gtip_olmayan_sayisi', 0),
                'farkli_gtip_sayisi':     kriter_bilgi.get('farkli_gtip_sayisi', 0),
                'farkli_tedarikci_sayisi': kriter_bilgi.get('farkli_tedarikci_sayisi', 0),
                'bu_parti_gtip':          kriter_bilgi.get('bu_parti_gtip'),
                'guvenilirlik':           kriter_bilgi.get('guvenilirlik'),
            }
        else:
            # bu_parti_id verilmediyse de kriter bilgisi hesaplanabilir
            kriter_bilgi = _kiyas_kriteri_belirle(
                strateji_adi, parti_ozetleri, None,
            )
            kiyas = {
                'bu_parti': None,
                'onceki_ortalama': None,
                'sapma_usd': None,
                'sapma_yon_usd': None,
                'sapma_try': None,
                'sapma_yon_try': None,
                'para_birimi_karisik': False,
                'min_parti': min_parti,
                'max_parti': max_parti,
                'yeterli_veri': False,
                'kriter':                 kriter_bilgi.get('kriter'),
                'kriter_aciklama':        kriter_bilgi.get('kriter_aciklama'),
                'gtip_eslesme_sayisi':    kriter_bilgi.get('gtip_eslesme_sayisi', 0),
                'gtip_olmayan_sayisi':    kriter_bilgi.get('gtip_olmayan_sayisi', 0),
                'farkli_gtip_sayisi':     kriter_bilgi.get('farkli_gtip_sayisi', 0),
                'farkli_tedarikci_sayisi': kriter_bilgi.get('farkli_tedarikci_sayisi', 0),
                'bu_parti_gtip':          kriter_bilgi.get('bu_parti_gtip'),
                'guvenilirlik':           kriter_bilgi.get('guvenilirlik'),
            }

        # ==================================================================
        # HER PARTIYE fark_yuzde + en_dusuk/en_yuksek flag'leri
        # ==================================================================
        for p in parti_ozetleri:
            cift = p.get('cift_maliyet_usd')
            if cift is not None:
                # En dusuk/yuksek flag
                p['en_dusuk_mu'] = (
                    min_parti is not None and p['parti_id'] == min_parti['parti_id']
                )
                p['en_yuksek_mu'] = (
                    max_parti is not None and p['parti_id'] == max_parti['parti_id']
                )
                # Bu partinin cift_maliyet_usd'si vs DIGERLERININ ortalamasi
                digerleri_icin_fark = [
                    q_p for q_p in parti_ozetleri
                    if q_p['parti_id'] != p['parti_id']
                ]
                ref_ort, _, _ = _agirlikli_ortalama(
                    digerleri_icin_fark, 'cift_maliyet_usd',
                )
                if ref_ort and ref_ort > 0:
                    fark_yz = round(((cift - ref_ort) / ref_ort) * 100, 2)
                    p['fark_yuzde'] = fark_yz
                    if fark_yz > 0.01:
                        p['fark_yon'] = 'pahali'
                    elif fark_yz < -0.01:
                        p['fark_yon'] = 'ucuz'
                    else:
                        p['fark_yon'] = 'esit'
                else:
                    p['fark_yuzde'] = None
                    p['fark_yon'] = None
            else:
                p['en_dusuk_mu'] = False
                p['en_yuksek_mu'] = False
                p['fark_yuzde'] = None
                p['fark_yon'] = None

        # ==================================================================
        # Gosterim icin son N (tarih sirasina gore, zaten siralandi)
        # ==================================================================
        son_partiler = parti_ozetleri[:int(son_gosterim_limit)]
        son_tarih = parti_ozetleri[0].get('tarih') if parti_ozetleri else None

        # ==================================================================
        # KIRILIMLAR (mevcut)
        # ==================================================================
        # Tedarikci kirilimi
        ted_gruplu = {}
        for p in parti_ozetleri:
            ad = p.get('tedarikci_ad') or '—'
            if ad not in ted_gruplu:
                ted_gruplu[ad] = {'ad': ad, 'alim_sayisi': 0, 'toplam_cift': 0,
                                  '_pay_usd': 0.0}
            ted_gruplu[ad]['alim_sayisi'] += 1
            ted_gruplu[ad]['toplam_cift'] += p['toplam_cift']
            if p.get('cift_maliyet_usd') is not None:
                ted_gruplu[ad]['_pay_usd'] += p['cift_maliyet_usd'] * p['toplam_cift']
        tedarikci_kirilim = []
        for ad, g in ted_gruplu.items():
            ort = (g['_pay_usd'] / g['toplam_cift']) if g['toplam_cift'] > 0 else None
            tedarikci_kirilim.append({
                'ad':          ad,
                'alim_sayisi': g['alim_sayisi'],
                'toplam_cift': g['toplam_cift'],
                'ort_cift_usd': round(ort, 4) if ort else None,
            })
        tedarikci_kirilim.sort(key=lambda x: x['alim_sayisi'], reverse=True)

        # Tasima kirilimi
        tas_gruplu = {}
        for p in parti_ozetleri:
            tip = p.get('tasima_tipi')
            navlun_usd = p.get('_ham_navlun_usd') or 0
            if not tip or navlun_usd <= 0:
                continue
            if tip not in tas_gruplu:
                tas_gruplu[tip] = {'tip': tip, 'alim_sayisi': 0,
                                   'toplam_cift': 0, '_pay_navlun_usd': 0.0}
            tas_gruplu[tip]['alim_sayisi'] += 1
            tas_gruplu[tip]['toplam_cift'] += p['toplam_cift']
            tas_gruplu[tip]['_pay_navlun_usd'] += navlun_usd
        tasima_kirilim = []
        for tip, g in tas_gruplu.items():
            ort = (g['_pay_navlun_usd'] / g['toplam_cift']) if g['toplam_cift'] > 0 else None
            tasima_kirilim.append({
                'tip':              tip,
                'alim_sayisi':      g['alim_sayisi'],
                'toplam_cift':      g['toplam_cift'],
                'ort_navlun_cift_usd': round(ort, 4) if ort else None,
            })
        tasima_kirilim.sort(key=lambda x: x['alim_sayisi'], reverse=True)

        # Son partilerden iç (_ham) alanlari temizle
        partiler_temiz = []
        for p in son_partiler:
            p2 = {k: v for k, v in p.items() if not k.startswith('_')}
            partiler_temiz.append(p2)

        return {
            'arama':             arama,
            'bulundu':           True,
            'strateji':          strateji_adi,
            'toplam_alim':       len(parti_ozetleri),
            'son_alim_tarihi':   son_tarih,
            'bu_parti_id':       bu_parti_id,
            'mesaj':             '',
            'partiler':          partiler_temiz,
            'ortalama':          ortalama,
            'kiyas':             kiyas,
            'tedarikci_kirilim': tedarikci_kirilim,
            'tasima_kirilim':    tasima_kirilim,
        }

    except Exception as e:
        log.exception("urun_kart_getir fail-safe: %s", e)
        bos_sonuc['mesaj'] = f"Hata: {str(e)[:100]}"
        return bos_sonuc


# =====================================================================
# PARSE ONAY SISTEMI (Faz 1+2 guven skoru)
# =====================================================================
# Preview JSON dosyalari icin guvenli klasor
# GUVENLIK KURALI 3: Kullanicinin dosya adini KULLANMA, BelgeId bazli
# isimlendirme kullan (belge_id zaten unique int)

def _parse_onay_klasor():
    """
    Preview JSON dosyalarinin saklanacagi klasor.
    Config'i Flask app'inden veya ENV'den alir, yoksa fallback.
    """
    root = None
    # 1) Flask app.config'den dene
    try:
        from flask import current_app
        root = current_app.config.get('UPLOAD_ROOT') or \
               current_app.config.get('UPLOAD_FOLDER')
    except Exception:
        root = None

    # 2) config module'den dene (eger global bir Config varsa)
    if not root:
        try:
            from config import Config as _Cfg
            root = getattr(_Cfg, 'UPLOAD_ROOT', None) or \
                   getattr(_Cfg, 'UPLOAD_FOLDER', None)
        except Exception:
            pass

    # 3) Environment variable fallback
    if not root:
        root = os.environ.get('CPS_UPLOAD_ROOT')

    # 4) Son care: calisma dizininde uploads/
    if not root:
        root = os.path.join(os.getcwd(), 'uploads')

    klasor = os.path.join(root, '_parse_onay')
    try:
        os.makedirs(klasor, exist_ok=True)
    except Exception as e:
        log.error("_parse_onay klasoru olusturulamadi: %s (yol=%s)", e, klasor)
        raise  # try/except icinden kurtarma, hata yukari iletilmeli

    return klasor


def _parse_onay_dosya_yolu(belge_id):
    """
    GUVENLIK KURALI 3: Dosya yolu SADECE belge_id'den uretilir.
    Kullanicinin dosya adi ASLA kullanilmaz.

    belge_id pozitif int zorunlu - path traversal korumasi.
    Donus: tam path veya None (gecersiz belge_id)
    """
    try:
        bid = int(belge_id)
        if bid <= 0:
            log.error("_parse_onay_dosya_yolu: gecersiz belge_id=%r", belge_id)
            return None
    except (TypeError, ValueError) as e:
        log.error("_parse_onay_dosya_yolu: belge_id int'e cevrilemedi: %r (%s)",
                  belge_id, e)
        return None

    try:
        klasor = _parse_onay_klasor()
    except Exception as e:
        log.error("_parse_onay_dosya_yolu: klasor alinamadi: %s", e)
        return None

    # Sabit format, sadece pozitif int - path traversal imkansiz
    return os.path.join(klasor, f'belge_{bid}.json')


def parse_onay_kaydet(belge_id, parti_id, parse_sonuc_dict, ek_bilgi=None):
    """
    Preview JSON'i guvenli klasore yaz.

    YENI: Duplicate tespiti - aynı kaynak_ref bu partide zaten uygulanmis mi
    kontrol eder, ek_bilgi'ye 'is_duplicate' ve 'existing_ref' ekler.
    UI bu flag'e bakip duplicate modunda baslar (Override butonu direkt goster).

    Donus: dosya_yol (str) - basarili
           None - hata
    """
    try:
        yol = _parse_onay_dosya_yolu(belge_id)
        if not yol:
            log.error("parse_onay_kaydet: dosya yolu uretilemedi, belge_id=%r",
                      belge_id)
            return None

        # Duplicate tespit - kaynak_ref varsa kontrol et
        is_duplicate = False
        existing_ref_info = None
        kaynak_ref = (parse_sonuc_dict or {}).get('kaynak_ref')
        if kaynak_ref and parti_id:
            try:
                mevcut = belge_parse_ref_kontrol(parti_id, kaynak_ref)
                if mevcut:
                    is_duplicate = True
                    existing_ref_info = {
                        'kaynak_ref':    kaynak_ref,
                        'onceki_belge_id': mevcut.get('BelgeId'),
                        'onceki_tarih':   str(mevcut.get('ParseTarih') or ''),
                        'onceki_durum':   mevcut.get('ParseDurum'),
                        'onceki_kalem_sayisi': mevcut.get('UygulananKalemSayisi', 0),
                    }
                    log.info("DUPLICATE tespit: belge_id=%s, ref=%s",
                             belge_id, kaynak_ref)
            except Exception as _e:
                log.warning("duplicate tespit hata: %s", _e)

        icerik = {
            'belge_id':        int(belge_id),
            'parti_id':        int(parti_id) if parti_id else None,
            'olusma_tarih':    _simdi(),
            'parse':           parse_sonuc_dict,
            'ek_bilgi':        ek_bilgi or {},
            # YENI alanlar:
            'is_duplicate':    is_duplicate,
            'existing_ref':    existing_ref_info,
        }

        klasor = os.path.dirname(yol)
        if not os.path.isdir(klasor):
            try:
                os.makedirs(klasor, exist_ok=True)
            except Exception as e:
                log.error("parse_onay_kaydet: klasor olusturulamadi: %s (%s)",
                          klasor, e)
                return None

        with open(yol, 'w', encoding='utf-8') as f:
            json.dump(icerik, f, ensure_ascii=False, indent=2, default=str)

        if os.path.isfile(yol):
            boyut = os.path.getsize(yol)
            log.info("parse_onay kaydedildi: %s (%d byte, belge_id=%s, duplicate=%s)",
                     yol, boyut, belge_id, is_duplicate)
            return yol
        else:
            log.error("parse_onay_kaydet: yazildi ama dosya bulunamadi: %s", yol)
            return None

    except Exception as e:
        log.exception("parse_onay_kaydet hata (belge_id=%r): %s", belge_id, e)
        return None


def parse_onay_getir(belge_id):
    """
    Preview JSON'i oku.
    Donus: dict veya None (bulunamadi / bozuk)

    Hata durumunda detayli log yazar.
    """
    try:
        yol = _parse_onay_dosya_yolu(belge_id)
        if not yol:
            log.warning("parse_onay_getir: dosya yolu uretilemedi, belge_id=%r",
                        belge_id)
            return None
        if not os.path.isfile(yol):
            log.info("parse_onay_getir: dosya yok (belge_id=%s, yol=%s)",
                     belge_id, yol)
            return None
        with open(yol, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.exception("parse_onay_getir hata (belge_id=%r): %s", belge_id, e)
        return None


def parse_onay_debug(belge_id):
    """
    Debug endpoint'i icin yardimci.
    Dosya yolu, var mi, icerik var mi bilgisi doner.
    """
    try:
        bid_raw = belge_id
        try:
            bid = int(belge_id)
        except Exception:
            return {
                'ok': False,
                'belge_id_raw': repr(bid_raw),
                'hata': 'belge_id int degil',
            }

        yol = _parse_onay_dosya_yolu(bid)
        if not yol:
            return {
                'ok': False,
                'belge_id': bid,
                'hata': 'dosya yolu uretilemedi (belge_id <= 0?)',
            }

        klasor = os.path.dirname(yol)
        return {
            'ok': True,
            'belge_id': bid,
            'beklenen_yol': yol,
            'klasor': klasor,
            'klasor_var': os.path.isdir(klasor),
            'dosya_var': os.path.isfile(yol),
            'dosya_boyut': os.path.getsize(yol) if os.path.isfile(yol) else None,
            'cwd': os.getcwd(),
        }
    except Exception as e:
        log.exception("parse_onay_debug hata: %s", e)
        return {'ok': False, 'hata': str(e)[:200]}


def parse_onay_sil(belge_id):
    """
    Preview JSON'i sil (onaylandi veya reddedildi).
    Donus: bool
    """
    try:
        yol = _parse_onay_dosya_yolu(belge_id)
        if not yol:
            return False
        if os.path.isfile(yol):
            os.remove(yol)
            log.info("parse_onay silindi: belge_id=%s", belge_id)
        return True
    except Exception as e:
        log.exception("parse_onay_sil hata: %s", e)
        return False


def parse_onay_uygula(belge_id, parti_id, kullanici,
                       ekstra_kalemler_dahil=False,
                       override_duplicate=False,
                       secilen_oneriler=None):
    """
    Kullanici preview modal'da "Onayla ve Uygula" basti.

    Parametreler:
        override_duplicate (bool):
            False -> ayni kaynak_ref zaten islenmisse UYARI doner, yazmaz
            True  -> override - eski kalemleri iptal et, yeniden yaz

        secilen_oneriler (list|None):
            ONERI_BEKLIYOR akisi icin - kullanicinin secilip duzenledigi oneriler.
            Format:
              [
                {'aciklama':..., 'tutar':..., 'para_birimi':...,
                 'tip':..., 'kaynak':...}, ...
              ]
            Bu liste geldiginde JSON'daki orijinal kalemler YERINE bu kullanilir.

    Packing List ozel davranis:
        - Maliyet kalemi URETMEZ
        - Sadece parti metadata'sini gunceller
    """
    try:
        onay = parse_onay_getir(belge_id)
        if not onay:
            return {
                'ok': False, 'uygulanan_kalem_sayisi': 0,
                'mesaj': '', 'hata': 'Onay bekleyen parse verisi bulunamadi',
            }

        parse_data = onay.get('parse') or {}
        ek_bilgi = onay.get('ek_bilgi') or {}
        belge_tipi = (ek_bilgi.get('belge_tipi') or '').upper()
        kaynak_ref = parse_data.get('kaynak_ref')
        parti_bilgi_parse = parse_data.get('parti_bilgi') or {}

        # Kalem listesini belirle:
        # 1. secilen_oneriler varsa (ONERI_BEKLIYOR akisi) onu kullan
        # 2. Yoksa parse_data['kalemler'] kullan (BEKLIYOR_ONAY akisi)
        if secilen_oneriler is not None:
            # ONERI AKISI - kullanicinin sectigi/duzenledigi oneriler
            # P3.2: UI kur_onerisi'ni postlamaz (parser meta verisi).
            # Orijinal JSON'daki oneriler listesinden tutar+para match ile cikar.
            _orj_oneriler = parse_data.get('oneriler') or []
            def _orijinal_oneriler_ile_kur_esitle(secilen):
                # Once secilen'de kur_onerisi varsa onu kullan
                k = secilen.get('kur_onerisi')
                if k is not None:
                    return k
                # Yoksa tutar + para_birimi match ile orijinalden bul
                try:
                    s_tutar = float(secilen.get('tutar') or 0)
                except Exception:
                    return None
                s_para = (secilen.get('para_birimi') or '').upper()
                for orj in _orj_oneriler:
                    try:
                        if abs(float(orj.get('tutar') or 0) - s_tutar) < 0.01 \
                           and (orj.get('para_birimi') or '').upper() == s_para:
                            return orj.get('kur_onerisi')
                    except Exception:
                        continue
                return None

            kalemler = []
            for o in secilen_oneriler:
                try:
                    tutar = float(o.get('tutar') or 0)
                except Exception:
                    continue
                if tutar <= 0:
                    continue
                tip = (o.get('tip') or 'DIGER').upper()
                if tip not in GECERLI_TIPLER:
                    tip = 'DIGER'
                kaynak = (o.get('kaynak') or 'GERCEKLESEN').upper()
                if kaynak not in GECERLI_KAYNAKLAR:
                    kaynak = 'GERCEKLESEN'
                kalemler.append({
                    'tip':          tip,
                    'kaynak':       kaynak,
                    'tutar':        tutar,
                    'para_birimi':  (o.get('para_birimi') or 'TRY').upper(),
                    'aciklama':     (o.get('aciklama') or '')[:500],
                    'alt_kod':      o.get('alt_kod'),
                    'fatura_no':    kaynak_ref,
                    'cari_ad':      o.get('cari_ad'),
                    'not_metni':    'Kullanici oneri ekranindan secildi',
                    # PATCH 3.2: UI kur_onerisi yoksa orijinal JSON'dan eslest
                    'okunan_kur':   _orijinal_oneriler_ile_kur_esitle(o),
                })
            log.info("Oneri akisi: %d secilen kalem (belge_id=%s)",
                     len(kalemler), belge_id)
        else:
            # STANDART AKIS - JSON'daki otomatik kalemler
            kalemler = list(parse_data.get('kalemler') or [])

        # ================================================================
        # PACKING LIST OZEL AKIS - maliyet URETMEZ
        # ================================================================
        if belge_tipi == 'PACKING_LIST':
            return _packing_list_uygula(
                belge_id=belge_id, parti_id=parti_id,
                kullanici=kullanici, kaynak_ref=kaynak_ref,
                parti_bilgi=parti_bilgi_parse,
            )

        # ================================================================
        # STANDART AKIS - FOB/NAVLUN/GUMRUK kalem yazar
        # ================================================================

        # Ekstra kalemler de dahil edilecekse
        if ekstra_kalemler_dahil:
            for ek in (parse_data.get('ekstra_kalemler') or []):
                k = {
                    'tip':         ek.get('tip_onerisi') or 'DIGER',
                    'kaynak':      ek.get('kaynak') or 'GERCEKLESEN',
                    'tutar':       ek.get('tutar'),
                    'para_birimi': ek.get('para_birimi') or 'USD',
                    'aciklama':    ek.get('etiket') or ek.get('aciklama') or 'Ekstra kalem',
                    'fatura_no':   kaynak_ref,
                    'not_metni':   'Parser tarafindan tespit edildi (ekstra)',
                }
                if k['tutar']:
                    kalemler.append(k)

        if not kalemler:
            return {'ok': False, 'uygulanan_kalem_sayisi': 0,
                    'mesaj': '', 'hata': 'Uygulanacak kalem yok'}

        # ---- DUPLICATE KONTROL (ÇİFT KATMAN) ----
        # 1. Katman: belge_parse tablosunda daha önce UYGULANDI var mı?
        # 2. Katman: ithalat_maliyet_kalem tablosunda aktif kalem var mı?
        #   Her iki katmanda da asıl truth ithalat_maliyet_kalem'dir.
        if kaynak_ref and not override_duplicate:
            aktif_kalem_sayisi = aktif_maliyet_kalem_ref_kontrol(parti_id, kaynak_ref)
            parse_kayit = belge_parse_ref_kontrol(parti_id, kaynak_ref)

            if aktif_kalem_sayisi > 0 or parse_kayit:
                # Mevcut durumu bildir
                bilgi_parcalari = []
                if aktif_kalem_sayisi > 0:
                    bilgi_parcalari.append(
                        f"{aktif_kalem_sayisi} aktif maliyet kalemi mevcut"
                    )
                if parse_kayit:
                    tarih_kisa = (parse_kayit.get('ParseTarih') or '')[:16]
                    bilgi_parcalari.append(
                        f"onceki uygulama: {tarih_kisa}"
                    )

                return {
                    'ok': False,
                    'uygulanan_kalem_sayisi': 0,
                    'mesaj': '',
                    'duplicate_uyari': (
                        f"Bu referans ({kaynak_ref}) daha once islenmis. "
                        + ('(' + ' | '.join(bilgi_parcalari) + '). ' if bilgi_parcalari else '')
                        + "Yeniden uygulamak icin override secenegi: "
                        "eski aktif kalemler IPTAL edilip yenileri yazilir."
                    ),
                    'kaynak_ref': kaynak_ref,
                    'duplicate': True,
                    'mevcut_aktif_kalem': aktif_kalem_sayisi,
                    'hata': None,
                }

        # ---- OVERRIDE MODUNDA: Eski kalemleri iptal et (maliyet tablosundan!) ----
        iptal_edilen = 0
        if override_duplicate and kaynak_ref:
            # Once eski kalemleri iptal et
            iptal_sonuc = kalem_iptal_topluca(
                parti_id=parti_id,
                kaynak_belge_ref=kaynak_ref,
                kullanici=kullanici,
                sebep=f"Override: yeni belge #{belge_id}",
            )
            iptal_edilen = iptal_sonuc.get('iptal_edilen', 0)
            log.info("Override - iptal edilen kalem: %d (parti=%s, ref=%s)",
                     iptal_edilen, parti_id, kaynak_ref)

        # ---- UYGULA ----
        from modules.ithalat.parser._base import ParseSonuc as _PS
        ps = _PS()
        ps.basarili = True
        ps.durum = _PS.DURUM_OK
        ps.kalemler = kalemler
        ps.parti_bilgi = parti_bilgi_parse
        ps.uyarilar = parse_data.get('uyarilar') or []
        ps.kaynak_ref = kaynak_ref
        ps.dosya_hash = parse_data.get('dosya_hash')

        # Biz override icin eski kalemleri zaten iptal ettik (yukarida).
        # parse_sonuc_uygula icindeki duplicate kontrolunu BYPASS etmek icin
        # yeniden_isle=True gecir ama bu sefer iptal_topluca bir sey bulmayacak
        # cunku aktif kalem kalmadi.
        sonuc = parse_sonuc_uygula(
            parti_id=parti_id,
            belge_id=belge_id,
            parse_sonuc=ps,
            kullanici=kullanici,
            yeniden_isle=bool(override_duplicate),
        )

        parse_onay_sil(belge_id)

        mesaj_ek = ''
        # Biz iptal ettiysek iptal_edilen kullan, yoksa parse_sonuc_uygula sonucundan
        toplam_iptal = iptal_edilen
        if isinstance(sonuc, dict):
            toplam_iptal = max(toplam_iptal, sonuc.get('onceki_kalemler_iptal', 0))
        if toplam_iptal > 0:
            mesaj_ek = f" ({toplam_iptal} eski kalem iptal edildi)"

        belge_parse_durum_ekle_veya_guncelle(
            belge_id=belge_id,
            parti_id=parti_id,
            parse_durum='UYGULANDI',
            parse_mesaj=(
                f'Kullanici onayi ile uygulandi ({len(kalemler)} kalem)'
                + mesaj_ek
            ),
            kaynak_ref=kaynak_ref,
        )

        return {
            'ok': True,
            'uygulanan_kalem_sayisi': (
                sonuc.get('uygulanan', 0) if isinstance(sonuc, dict) else len(kalemler)
            ),
            'mesaj': f"{len(kalemler)} kalem maliyete eklendi" + mesaj_ek,
            'hata': None,
        }
    except Exception as e:
        log.exception("parse_onay_uygula hata: %s", e)
        return {'ok': False, 'uygulanan_kalem_sayisi': 0,
                'mesaj': '', 'hata': f'Sunucu hatasi: {str(e)[:120]}'}


def _packing_list_uygula(belge_id, parti_id, kullanici,
                          kaynak_ref, parti_bilgi):
    """
    Packing List kullanici onayi uygulamasi.
    Maliyet kalemi URETMEZ. Sadece parti.ToplamCift, ToplamKg, Aciklama guncellenir.

    Kural: Parti'de ALAN ZATEN DOLUYSA overwrite ETMEZ, sadece uyari verir.
    """
    try:
        parti = parti_getir(parti_id)
        if not parti:
            return {
                'ok': False, 'uygulanan_kalem_sayisi': 0,
                'mesaj': '', 'hata': 'Parti bulunamadi',
            }

        guncellemeler = {}   # sadece gerçekten guncellenen alanlar
        atlamalar = []        # "zaten dolu" uyarilari

        # Toplam Cift
        yeni_cift = parti_bilgi.get('toplam_cift')
        if yeni_cift and yeni_cift > 0:
            mevcut_cift = parti.get('ToplamCift')
            if not mevcut_cift or mevcut_cift == 0:
                guncellemeler['toplam_cift'] = int(yeni_cift)
            else:
                atlamalar.append(
                    f"Toplam cift zaten dolu ({mevcut_cift}) - "
                    f"Packing List: {int(yeni_cift)} - overwrite edilmedi"
                )

        # Toplam Kg
        yeni_kg = parti_bilgi.get('toplam_kg')
        if yeni_kg and yeni_kg > 0:
            mevcut_kg = parti.get('ToplamKg')
            if not mevcut_kg or mevcut_kg == 0:
                guncellemeler['toplam_kg'] = float(yeni_kg)
            else:
                atlamalar.append(
                    f"Toplam kg zaten dolu ({mevcut_kg}) - "
                    f"Packing List: {yeni_kg} - overwrite edilmedi"
                )

        # Tedarikci ad
        yeni_ted = parti_bilgi.get('tedarikci_ad')
        if yeni_ted:
            mevcut_ted = (parti.get('TedarikciAd') or '').strip()
            if not mevcut_ted:
                guncellemeler['tedarikci_ad'] = yeni_ted[:200]
            # Dolu ise atlamaya gerek yok - sessizce korur

        # Aciklama ekleme (CBM, koli)
        yeni_aciklama_ek = parti_bilgi.get('aciklama_ekle')
        if yeni_aciklama_ek:
            mevcut_aciklama = parti.get('Aciklama') or ''
            # Duplicate kontrol - ayni metin zaten var mi?
            if yeni_aciklama_ek not in mevcut_aciklama:
                yeni = mevcut_aciklama + ('\n' if mevcut_aciklama else '') + yeni_aciklama_ek
                guncellemeler['aciklama'] = yeni[:2000]
            # Yoksa duplicate, sessizce gec

        # Parti'yi guncelle (yalnizca degisiklik varsa)
        if guncellemeler:
            # parti_guncelle(parti_id, kullanici, **alanlar) imzasi
            parti_guncelle(parti_id, kullanici, **guncellemeler)

        # Preview JSON sil
        parse_onay_sil(belge_id)

        # belge_parse durumu UYGULANDI
        belge_parse_durum_ekle_veya_guncelle(
            belge_id=belge_id,
            parti_id=parti_id,
            parse_durum='UYGULANDI',
            parse_mesaj=(
                f'Packing List islendi - '
                f'{len(guncellemeler)} parti alani guncellendi'
                + (f', {len(atlamalar)} alan atlandi' if atlamalar else '')
            ),
            kaynak_ref=kaynak_ref,
        )

        mesaj_parcalari = []
        if guncellemeler:
            alanlar = ', '.join(guncellemeler.keys())
            mesaj_parcalari.append(f"Parti alanlari guncellendi: {alanlar}")
        if atlamalar:
            mesaj_parcalari.append(
                f"{len(atlamalar)} alan overwrite edilmedi (zaten dolu)"
            )
        if not mesaj_parcalari:
            mesaj_parcalari.append("Degisiklik yapilmadi - tum alanlar zaten dolu")

        return {
            'ok': True,
            'uygulanan_kalem_sayisi': 0,  # kalem yok
            'parti_guncellemeleri': guncellemeler,
            'atlamalar': atlamalar,
            'mesaj': 'Packing List islendi — ' + ' | '.join(mesaj_parcalari),
            'hata': None,
            'packing_list': True,
        }

    except Exception as e:
        log.exception("_packing_list_uygula hata: %s", e)
        return {'ok': False, 'uygulanan_kalem_sayisi': 0,
                'mesaj': '', 'hata': f'Sunucu hatasi: {str(e)[:120]}'}


def parse_onay_reddet(belge_id, parti_id, kullanici, sebep=None):
    """
    Kullanici preview modal'da "Reddet" basti.
    JSON silinir, belge diske kalir.
    """
    try:
        onay = parse_onay_getir(belge_id)
        if not onay:
            # Zaten yok - ok say
            return {'ok': True, 'mesaj': 'Preview zaten yoktu'}

        parse_onay_sil(belge_id)

        # belge_parse durumu guncelle
        belge_parse_durum_ekle_veya_guncelle(
            belge_id=belge_id,
            parti_id=parti_id,
            parse_durum='REDDEDILDI',
            parse_mesaj=sebep or f'Kullanici ({kullanici}) reddetti',
        )

        return {'ok': True, 'mesaj': 'Önizleme reddedildi, belge kaydı korundu'}
    except Exception as e:
        log.exception("parse_onay_reddet hata: %s", e)
        return {'ok': False, 'mesaj': '', 'hata': str(e)[:120]}



# =====================================================================
# PATCH 4 - ANA KUR YONETIMI + BACKFILL
# =====================================================================
def ana_kur_guncelle(parti_id, ana_kur_try, kullanici):
    """
    PATCH 4: Parti.AnaKurTRY guncelle + NULL kalemleri yeniden hesapla.

    Akis:
      1) parti.AnaKurTRY, AnaKurGuncelleyen, AnaKurGuncellemeTarih yaz
      2) Parti icindeki TutarPartiPara IS NULL veya KurDegeri IS NULL olan
         kalemleri _kur_hesapla(yeni ana_kur ile) ile yeniden hesapla
      3) Audit log

    Donus: {'ok': bool, 'ana_kur_try': float, 'guncellenen_kalem': int, 'hata': str}
    """
    try:
        ana_kur = float(ana_kur_try)
        if not (1 < ana_kur < 1000):
            return {'ok': False, 'hata': 'Ana kur 1-1000 araliginda olmali'}

        parti = parti_getir(parti_id)
        if not parti:
            return {'ok': False, 'hata': 'Parti bulunamadi'}

        simdi = _simdi()
        qexec(
            "UPDATE ithalat_parti "
            "SET AnaKurTRY = ?, AnaKurGuncelleyen = ?, AnaKurGuncellemeTarih = ? "
            "WHERE Id = ?",
            (ana_kur, kullanici, simdi, parti_id),
        )

        # Backfill: NULL kalemleri yeniden hesapla
        parti_para = parti['ParaBirimi']
        guncellenen = 0
        kalemler = q(
            "SELECT Id, Tutar, ParaBirimi, KurDegeri, OkunanKur "
            "FROM ithalat_maliyet_kalem "
            "WHERE PartiId = ? AND (Iptal IS NULL OR Iptal = 0) "
            "  AND (TutarPartiPara IS NULL OR KurDegeri IS NULL)",
            (parti_id,),
        )
        for k in kalemler:
            kur_deg, tutar_parti = _kur_hesapla(
                k['Tutar'], k['ParaBirimi'], parti_para,
                manuel_kur=None,
                okunan_kur=k['OkunanKur'],
                ana_kur_try=ana_kur,
            )
            if kur_deg is not None and tutar_parti is not None:
                qexec(
                    "UPDATE ithalat_maliyet_kalem "
                    "SET KurDegeri = ?, TutarPartiPara = ?, KurTarihi = ? "
                    "WHERE Id = ?",
                    (kur_deg, tutar_parti, simdi, k['Id']),
                )
                guncellenen += 1

        audit.log(
            kullanici or 'sistem', 'GUNCELLE',
            'ithalat_parti', parti_id,
            aciklama=(
                f"AnaKurTRY={ana_kur} guncellendi, "
                f"{guncellenen} kalem yeniden hesaplandi"
            ),
            modul='ithalat', alt_modul='parti',
        )

        return {
            'ok': True,
            'ana_kur_try': ana_kur,
            'guncellenen_kalem': guncellenen,
        }

    except Exception as e:
        log.exception("ana_kur_guncelle hata: %s", e)
        return {'ok': False, 'hata': f'Hata: {str(e)[:100]}'}
