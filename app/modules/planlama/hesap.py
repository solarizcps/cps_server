# F9_5_3_FIRE_AB_FIX_BEGIN - 22.05.2026
# slot_teorik_cift: bagli x kbc x tur
# saatlik_tur_toplam: A/B ayrimi
# makine_teorik_brut_net_fire: A/B + fire breakdown + fallback
# rapor_aggregate: saatlik dict
# _bagli_kalip_coz: yardimci
# F9_5_3_FIRE_AB_FIX_END

# F9_5_3_FIX1_SLOT_KALIP_BAGLI_BEGIN - 22.05.2026
# rapor_aggregate SQL genisletildi: varsayilan_bagli_kalip, kalip_tipi, bagli_kalip_adet
# Slot dict + kalip dict bu alanlari icerir
# _bagli_kalip_coz artik dogru veriyi alir
# F9_5_3_FIX1_SLOT_KALIP_BAGLI_END

# F9_5_4B_KALIP_OZET_BEGIN - 22.05.2026
# - SQL: i.renk eklendi
# - slot_dict: renk_ad, renk_kod
# - _renk_ad_coz yardimci
# - makine_teorik_brut_net_fire: a_kalip_ozet, b_kalip_ozet
# F9_5_4B_KALIP_OZET_END

# -*- coding: utf-8 -*-
"""
SOLARIZ CPS - PLANLAMA HESAP MOTORU
====================================
F9.5.1 BACKEND HESAP MOTORU

Operasyon raporu icin saf hesaplama fonksiyonlari.

KRITIK MIMARI KURALLAR:
1) HAM VERI DOKUNULMAZ - sadece OKU
2) Eksik veri TAHMIN EDILMEZ - None doner + uyari ekler
3) Tum fonksiyonlar PURE (yan etki yok)
4) ARIZA_RISKI yeni HIBRIT alt tip
5) F9.6+ icin geriye uyumluluk korunacak

MODUL YAPISI:
  vardiya_aralik              - vardiya zaman penceresi
  slot_sure_dagilim           - event_log reconstruct (slot bazli)
  makine_hibrit_durum_genisletilmis - 6 tip + ARIZA_RISKI
  saatlik_tur_toplam          - enj_saatlik_kayit'tan SUM
  slot_teorik_cift            - tek slot teorik hesap
  makine_teorik_brut_net_fire - makine bazli birlestirik
  setup_ariza_olay_ozet       - olay sayim + sure
  korgun_eslesme              - korgun farkı
  eksik_veri_uyarilari        - tum eksiklikleri topla
  olay_timeline_olustur       - kronolojik olay listesi
  rapor_aggregate             - HEPSINI BIRLEŞTIR (ana entry)
"""

import sqlite3
import json
from datetime import datetime, timedelta


# =============================================================================
# F9_5_1_HESAP_BEGIN
# =============================================================================


# ----- VARDIYA SABITLERI -----
VARDIYA_GUNDUZ_BAS = "07:00"
VARDIYA_GUNDUZ_BIT = "17:00"
VARDIYA_GUNDUZ_DK  = 600

VARDIYA_GECE_BAS = "17:00"
VARDIYA_GECE_BIT = "07:00"
VARDIYA_GECE_DK  = 840

DURUM_TIPLERI = ("AKTIF", "KAPALI", "SETUP", "ARIZA")


# ----- HIBRIT EŞIKLERI (V1, V2'de yorum eklenince güncellenebilir) -----
ARIZA_RISKI_SLOT_ORAN = 0.50   # ariza_slot / toplam_slot >= 0.50 -> risk
ARIZA_RISKI_SURE_ORAN = 0.15   # ariza_dakika / vardiya_dakika >= 0.15 -> risk


# =============================================================================
# 1. VARDIYA ARALIGI
# =============================================================================
def vardiya_aralik(tarih_str, vardiya, simdi_dt=None):
    """
    Vardiyanin zaman aralığını ve durumunu döner.
    
    Args:
        tarih_str: 'YYYY-MM-DD' format
        vardiya:   'gunduz' veya 'gece'
        simdi_dt:  datetime (test icin override)
    
    Returns:
        dict: {
            'baslangic': datetime,
            'bitis': datetime,
            'sure_dk': int,
            'aktif_mi': bool (vardiya su an devam ediyor mu),
            'gecen_dk': int,
            'kalan_dk': int,
        }
    """
    if simdi_dt is None:
        simdi_dt = datetime.now()
    
    tarih = datetime.strptime(tarih_str, "%Y-%m-%d").date()
    
    if vardiya == "gunduz":
        baslangic = datetime.combine(tarih, datetime.strptime(VARDIYA_GUNDUZ_BAS, "%H:%M").time())
        bitis = datetime.combine(tarih, datetime.strptime(VARDIYA_GUNDUZ_BIT, "%H:%M").time())
        sure_dk = VARDIYA_GUNDUZ_DK
    elif vardiya == "gece":
        baslangic = datetime.combine(tarih, datetime.strptime(VARDIYA_GECE_BAS, "%H:%M").time())
        bitis = datetime.combine(tarih, datetime.strptime(VARDIYA_GECE_BIT, "%H:%M").time()) + timedelta(days=1)
        sure_dk = VARDIYA_GECE_DK
    else:
        raise ValueError(f"Gecersiz vardiya: {vardiya}")
    
    aktif_mi = baslangic <= simdi_dt <= bitis
    
    if simdi_dt < baslangic:
        gecen_dk = 0
        kalan_dk = sure_dk
    elif simdi_dt > bitis:
        gecen_dk = sure_dk
        kalan_dk = 0
    else:
        gecen = (simdi_dt - baslangic).total_seconds() / 60
        gecen_dk = int(gecen)
        kalan_dk = sure_dk - gecen_dk
    
    return {
        "baslangic": baslangic,
        "bitis": bitis,
        "sure_dk": sure_dk,
        "aktif_mi": aktif_mi,
        "gecen_dk": gecen_dk,
        "kalan_dk": kalan_dk,
    }


# =============================================================================
# 2. SLOT SURE DAĞILIMI (event_log reconstruct)
# =============================================================================
def slot_sure_dagilim(con, istasyon_id, rapor_id, aralik):
    """
    Bir slotun vardiya süresince hangi durumda ne kadar kaldığını hesaplar.
    
    KAYNAK: enj_event_log
    YONTEM: event'leri kronolojik sırala, ardışık event arasındaki süreyi
            önceki duruma yaz.
    
    Returns:
        dict: {
            'AKTIF': dk, 'KAPALI': dk, 'SETUP': dk, 'ARIZA': dk,
            'toplam_dk': sum,
            'uyarilar': [...]
        }
    """
    sureler = {d: 0 for d in DURUM_TIPLERI}
    uyarilar = []
    
    cur = con.cursor()
    
    # Vardiya baslangicindan ONCE son durumu bul (ilk durum tahmini)
    cur.execute("""
        SELECT yeni_deger, meta_json, event_type
        FROM enj_event_log
        WHERE istasyon_id = ? AND zaman < ?
        ORDER BY zaman DESC LIMIT 1
    """, (istasyon_id, aralik["baslangic"].strftime("%Y-%m-%d %H:%M:%S")))
    
    onceki = cur.fetchone()
    
    if onceki:
        # Eski event'i (A_B_TOGGLE) - yeni_deger 0/1 ise legacy
        yeni_deg = onceki[0]
        meta = onceki[1]
        etip = onceki[2]
        
        if etip == "A_B_TOGGLE":
            # Legacy: 0=KAPALI, 1=AKTIF (durum bilgisi yok)
            mevcut_durum = "AKTIF" if str(yeni_deg) == "1" else "KAPALI"
            uyarilar.append({
                "kod": "LEGACY_EVENT",
                "seviye": "info",
                "mesaj": "Eski sistemden devralinan slot (A_B_TOGGLE)",
            })
        else:
            # Yeni event - meta_json'da durum bilgisi olabilir
            try:
                meta_d = json.loads(meta) if meta else {}
                mevcut_durum = meta_d.get("yeni_durum") or yeni_deg or "KAPALI"
            except Exception:
                mevcut_durum = yeni_deg or "KAPALI"
    else:
        # Hic event yok - varsayilan KAPALI
        mevcut_durum = "KAPALI"
    
    # Vardiya icindeki event'leri sirala
    cur.execute("""
        SELECT id, event_type, onceki_deger, yeni_deger, meta_json, zaman
        FROM enj_event_log
        WHERE istasyon_id = ?
          AND zaman >= ?
          AND zaman <= ?
        ORDER BY zaman ASC, id ASC
    """, (
        istasyon_id,
        aralik["baslangic"].strftime("%Y-%m-%d %H:%M:%S"),
        aralik["bitis"].strftime("%Y-%m-%d %H:%M:%S"),
    ))
    
    eventler = cur.fetchall()
    
    mevcut_baslangic = aralik["baslangic"]
    
    for ev in eventler:
        ev_id, ev_type, onc_deg, yeni_deg, meta, zaman_str = ev
        
        try:
            zaman = datetime.strptime(zaman_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                zaman = datetime.strptime(zaman_str, "%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                continue
        
        if zaman < mevcut_baslangic:
            continue
        
        # Bu event'e kadar gecen sure mevcut duruma yazilir
        gecen_sn = (zaman - mevcut_baslangic).total_seconds()
        gecen_dk = gecen_sn / 60.0
        
        if mevcut_durum in sureler:
            sureler[mevcut_durum] += gecen_dk
        
        # Durum guncelle
        if ev_type == "A_B_TOGGLE":
            yeni_durum = "AKTIF" if str(yeni_deg) == "1" else "KAPALI"
        elif ev_type in ("SETUP_START",):
            yeni_durum = "SETUP"
        elif ev_type in ("SETUP_END",):
            try:
                meta_d = json.loads(meta) if meta else {}
                yeni_durum = meta_d.get("hedef_durum") or "AKTIF"
            except Exception:
                yeni_durum = "AKTIF"
        elif ev_type in ("ARIZA_START",):
            yeni_durum = "ARIZA"
        elif ev_type in ("ARIZA_END",):
            try:
                meta_d = json.loads(meta) if meta else {}
                yeni_durum = meta_d.get("hedef_durum") or "AKTIF"
            except Exception:
                yeni_durum = "AKTIF"
        elif ev_type == "DURUM_DEGISIM":
            try:
                meta_d = json.loads(meta) if meta else {}
                yeni_durum = meta_d.get("yeni_durum") or yeni_deg or mevcut_durum
            except Exception:
                yeni_durum = yeni_deg or mevcut_durum
        else:
            yeni_durum = mevcut_durum  # bilinmeyen event - durum aynı kalır
        
        if yeni_durum not in DURUM_TIPLERI:
            yeni_durum = "KAPALI"
        
        mevcut_durum = yeni_durum
        mevcut_baslangic = zaman
    
    # Son event'ten vardiya sonuna kadar (veya su ana kadar)
    son_zaman = min(aralik["bitis"], datetime.now())
    if son_zaman > mevcut_baslangic:
        gecen_dk = (son_zaman - mevcut_baslangic).total_seconds() / 60.0
        if mevcut_durum in sureler:
            sureler[mevcut_durum] += gecen_dk
    
    # Int'e yuvarla
    for k in sureler:
        sureler[k] = int(round(sureler[k]))
    
    sureler["toplam_dk"] = sum(sureler[d] for d in DURUM_TIPLERI)
    sureler["uyarilar"] = uyarilar
    
    return sureler


# =============================================================================
# 3. MAKINE HIBRIT DURUMU (6 TIP + ARIZA_RISKI)
# =============================================================================
def makine_hibrit_durum_genisletilmis(slotlar, sureler_listesi=None, vardiya_dk=600):
    """
    Makinenin anlik durumunu siniflar.
    
    6 tip (oncelik sirasi):
        1. TUMUYLA_AKTIF    - tum slot AKTIF
        2. TUMUYLA_KAPALI   - tum slot KAPALI
        3. ARIZA_RISKI      - %50+ slot ariza VEYA >%15 vardiya ariza suresi (YENI)
        4. ARIZA_VE_SETUP   - aktif yok, ariza+setup
        5. TUMUYLA_ARIZA    - aktif yok, sadece ariza
        6. TUMUYLA_SETUP    - aktif yok, sadece setup
        7. HIBRIT           - karma (en az 1 aktif + en az 1 farkli)
        8. DURUYOR          - hicbiri (sadece kapali ama 0 sayilanlar)
    
    Args:
        slotlar:          [{'durum': 'AKTIF', ...}, ...]
        sureler_listesi:  [{'AKTIF': dk, 'ARIZA': dk, ...}, ...] (opsiyonel, ariza_risk icin)
        vardiya_dk:       vardiya toplam dakika
    
    Returns:
        dict: {
            'tip': str,
            'sayim': {'AKTIF': n, 'KAPALI': n, 'SETUP': n, 'ARIZA': n},
            'toplam_slot': int,
            'aktif_oran': float,
            'detay': str,
        }
    """
    sayim = {d: 0 for d in DURUM_TIPLERI}
    
    for s in slotlar:
        d = s.get("durum", "KAPALI")
        if d in sayim:
            sayim[d] += 1
        else:
            sayim["KAPALI"] += 1
    
    toplam = len(slotlar) or 1
    aktif = sayim["AKTIF"]
    kapali = sayim["KAPALI"]
    setup = sayim["SETUP"]
    ariza = sayim["ARIZA"]
    aktif_oran = aktif / toplam if toplam > 0 else 0
    
    # ARIZA RISKI HESABI (sureler varsa)
    ariza_risk_var = False
    if sureler_listesi and vardiya_dk > 0:
        toplam_ariza_dk = sum(s.get("ARIZA", 0) for s in sureler_listesi)
        if toplam_ariza_dk / vardiya_dk >= ARIZA_RISKI_SURE_ORAN:
            ariza_risk_var = True
    
    if ariza / toplam >= ARIZA_RISKI_SLOT_ORAN:
        ariza_risk_var = True
    
    # KARARLAR
    if aktif == toplam:
        tip = "TUMUYLA_AKTIF"
        detay = f"{aktif} slot uretimde"
    elif kapali == toplam:
        tip = "TUMUYLA_KAPALI"
        detay = "Hicbir slot acik degil"
    elif ariza_risk_var:
        tip = "ARIZA_RISKI"
        detay = f"{ariza} slot ariza · risk esigi asildi"
    elif aktif == 0:
        if ariza > 0 and setup > 0:
            tip = "ARIZA_VE_SETUP"
            detay = f"{ariza} ariza + {setup} setup"
        elif ariza > 0:
            tip = "TUMUYLA_ARIZA"
            detay = f"{ariza} slot ariza"
        elif setup > 0:
            tip = "TUMUYLA_SETUP"
            detay = f"{setup} slot setup"
        else:
            tip = "DURUYOR"
            detay = "Aktif slot yok"
    else:
        tip = "HIBRIT"
        detay = f"{aktif}A · {setup}S · {ariza}A · {kapali}K"
    
    return {
        "tip": tip,
        "sayim": sayim,
        "toplam_slot": toplam,
        "aktif_oran": round(aktif_oran, 3),
        "detay": detay,
    }


# =============================================================================
# 4. SAATLIK TUR TOPLAMI
# =============================================================================
def saatlik_tur_toplam(con, rapor_id):
    """F9_5_3: A/B (cevrim_a, cevrim_b) ayrimi. 'toplam' geri uyumlu."""
    cur = con.cursor()
    cur.execute("""
        SELECT saat_baslangic, tur_adet, durum, aksama_sebep_id, aciklama,
               cevrim_a, cevrim_b, uretilen_a, uretilen_b
        FROM enj_saatlik_kayit
        WHERE rapor_id = ?
        ORDER BY saat_baslangic
    """, (rapor_id,))
    rows = cur.fetchall()
    toplam = toplam_a = toplam_b = uretim_a_db = uretim_b_db = 0
    dolu = bos = aksamali = 0
    detaylar = []
    for r in rows:
        saat, tur, durum, aks_id, acik, cev_a, cev_b, ur_a, ur_b = r
        tur_int = tur or 0
        a_int = cev_a or 0
        b_int = cev_b or 0
        toplam += tur_int
        toplam_a += a_int
        toplam_b += b_int
        uretim_a_db += (ur_a or 0)
        uretim_b_db += (ur_b or 0)
        if tur_int > 0 or a_int > 0 or b_int > 0:
            dolu += 1
        else:
            bos += 1
        if durum and durum != "calisiyor":
            aksamali += 1
        detaylar.append({
            "saat": saat, "tur_adet": tur,
            "cevrim_a": cev_a, "cevrim_b": cev_b,
            "uretilen_a": ur_a, "uretilen_b": ur_b,
            "durum": durum, "aksama_sebep_id": aks_id, "aciklama": acik,
        })
    uyarilar = []
    if not rows:
        uyarilar.append({"kod":"SAATLIK_KAYIT_YOK","seviye":"warning","mesaj":"Saatlik kayit yok"})
    elif bos > 0:
        uyarilar.append({"kod":"TUR_KAYDI_KISMI","seviye":"info","mesaj":str(dolu)+"/"+str(len(rows))+" girilmis"})
    if toplam > 0 and (toplam_a + toplam_b) > 0:
        fark = abs(toplam - (toplam_a + toplam_b))
        if fark > max(2, toplam * 0.1):
            uyarilar.append({"kod":"VERI_TUTARSIZ_AB","seviye":"warning",
                             "mesaj":"Tur="+str(toplam)+" A+B="+str(toplam_a+toplam_b)})
    return {
        "toplam": toplam, "toplam_a": toplam_a, "toplam_b": toplam_b,
        "uretim_a_db": uretim_a_db, "uretim_b_db": uretim_b_db,
        "kayit_sayisi": len(rows), "dolu_kayit": dolu,
        "bos_kayit": bos, "aksamali_kayit": aksamali,
        "uyarilar": uyarilar, "detaylar": detaylar,
    }



# =============================================================================
# 5. SLOT TEORIK CIFT
# =============================================================================
def _bagli_kalip_coz(slot, kalip):
    """F9_5_3: Bagli kalip oncelik: slot > kalip default > None."""
    if isinstance(slot, dict):
        sb = slot.get("bagli_kalip_adet")
        if sb and sb > 0:
            return int(sb), "slot"
    if kalip:
        vb = kalip.get("varsayilan_bagli_kalip")
        if vb and vb > 0:
            return int(vb), "kalip_default"
    return None, "eksik"


def slot_teorik_cift(slot, kalip, tur_toplam, sureler, vardiya_dk):
    """F9_5_3: teorik = bagli x kbc x tur. kapasite_cift OKUNMUYOR."""
    durum = (slot.get("durum") or "").upper() if isinstance(slot, dict) else "AKTIF"
    if durum != "AKTIF":
        return 0, None, None
    if not kalip:
        return None, "SLOT_KALIPSIZ", None
    kbc = kalip.get("kalip_basi_cift")
    if not kbc or kbc <= 0:
        return None, "KAPASITE_EKSIK", None
    # F9_5_4D_BAGLI_FIX_BEGIN
    # DOGRU MANTIK: her yuvada (slot) maks 1 kalip baglanir.
    # bagli_kalip_adet alani semantik hatali (her yerde 8 yaziliyor).
    # Slot iterasyonu zaten her aktif slot icin += yapiyor,
    # bu yuzden bagli ile carpmak GEREKLI DEGIL ve YANLIS sonuca yol acar.
    # Yeni formul: 1 kalip * KBC * tur
    bagli = 1
    kaynak = "slot_basi_1_kalip_varsayim"
    if tur_toplam is None or tur_toplam < 0:
        return 0, None, None
    kalip_tipi = (kalip.get("kalip_tipi") or "GOVDE").upper()
    teorik = bagli * kbc * tur_toplam
    # F9_5_4D_BAGLI_FIX_END
    return int(teorik), None, kalip_tipi



# =============================================================================
# 6. MAKINE TEORIK / BRUT / NET / FIRE
# =============================================================================
def makine_teorik_brut_net_fire(rapor, slotlar_zenginlestirilmis, saatlik_obj, vardiya_dk):
    """F9_5_3: A/B uretim + fire breakdown + fallback + tutarsizlik uyarilari."""
    uyarilar = []
    tur_a = saatlik_obj.get("toplam_a", 0) or 0
    tur_b = saatlik_obj.get("toplam_b", 0) or 0
    eski_sistem_fallback = False
    if tur_a == 0 and tur_b == 0 and saatlik_obj.get("toplam", 0) > 0:
        te = saatlik_obj["toplam"]
        tur_a = te // 2
        tur_b = te - tur_a
        eski_sistem_fallback = True
        uyarilar.append({"kod":"ESKI_SISTEM_FALLBACK","seviye":"info",
                         "mesaj":"Eski sistem raporu - A/B tur tahmini bolundu."})
    slot_kalipsiz = kapasite_eksik = bagli_eksik = 0
    teorik_a = teorik_b = uretim_a = uretim_b = 0
    aktif_a = aktif_b = teorik_govde = teorik_atki = 0
    for s in slotlar_zenginlestirilmis:
        slot_kod = (s.get("slot") or "").upper()
        is_a = (slot_kod == "A")
        is_b = (slot_kod == "B")
        if not (is_a or is_b):
            continue
        tur_bu = tur_a if is_a else tur_b
        sonuc = slot_teorik_cift(s, s.get("kalip"), tur_bu, s.get("sureler"), vardiya_dk)
        if len(sonuc) == 3:
            t, sebep, kalip_tipi = sonuc
        else:
            t, sebep = sonuc
            kalip_tipi = None
        if sebep == "SLOT_KALIPSIZ":
            slot_kalipsiz += 1
            continue
        if sebep == "KAPASITE_EKSIK":
            kapasite_eksik += 1
            continue
        if sebep == "BAGLI_KALIP_EKSIK":
            bagli_eksik += 1
            continue
        if t is None or t == 0:
            continue
        if is_a:
            teorik_a += t
            uretim_a += t
            aktif_a += 1
        else:
            teorik_b += t
            uretim_b += t
            aktif_b += 1
        if kalip_tipi == "ATKI":
            teorik_atki += t
        else:
            teorik_govde += t
    if slot_kalipsiz > 0:
        uyarilar.append({"kod":"SLOT_KALIPSIZ","seviye":"warning","mesaj":str(slot_kalipsiz)+" slot kalipsiz"})
    if kapasite_eksik > 0:
        uyarilar.append({"kod":"KAPASITE_EKSIK","seviye":"warning","mesaj":str(kapasite_eksik)+" kbc eksik"})
    if bagli_eksik > 0:
        uyarilar.append({"kod":"BAGLI_KALIP_EKSIK","seviye":"warning","mesaj":str(bagli_eksik)+" bagli eksik"})
    teorik_toplam = teorik_a + teorik_b
    brut_cift = uretim_a + uretim_b
    teorik_son = teorik_toplam if teorik_toplam > 0 else None
    brut_son = brut_cift if brut_cift > 0 else None
    fire_cift = rapor.get("toplam_fire_cift") if rapor else None
    fire_kg = rapor.get("fire_kg") if rapor else None
    fire_orani = rapor.get("fire_orani") if rapor else None
    teknik_kg = rapor.get("teknik_fire_kg") if rapor else None
    bos_atis_kg = rapor.get("bos_atis_kg") if rapor else None
    yolluk_kg = rapor.get("yolluk_fire_kg") if rapor else None
    if fire_orani is None and fire_cift is not None and brut_son and brut_son > 0:
        fire_orani = round((fire_cift / brut_son) * 100, 2)
    net = rapor.get("net_cikan_cift") if rapor else None
    net_kaynak = "manuel" if net is not None else None
    if net is None and brut_son is not None and fire_cift is not None:
        net = brut_son - fire_cift
        net_kaynak = "otomatik"
    if net is None:
        uyarilar.append({"kod":"NET_HESAPLANAMADI","seviye":"info","mesaj":"Net hesaplanamadi"})
    verim = None
    if net is not None and teorik_son and teorik_son > 0:
        verim = round((net / teorik_son) * 100, 1)
    fire_seviye = None
    if fire_orani is not None:
        if fire_orani >= 6.0:
            fire_seviye = "kirmizi"
        elif fire_orani >= 3.0:
            fire_seviye = "sari"
        else:
            fire_seviye = "normal"
    ur_a_db = saatlik_obj.get("uretim_a_db", 0) or 0
    ur_b_db = saatlik_obj.get("uretim_b_db", 0) or 0
    if ur_a_db > 0 and uretim_a > 0:
        if abs(ur_a_db - uretim_a) > max(20, uretim_a * 0.3):
            uyarilar.append({"kod":"VERI_TUTARSIZ_URETIM_A","seviye":"warning",
                             "mesaj":"A slot="+str(uretim_a)+" db="+str(ur_a_db)})
    if ur_b_db > 0 and uretim_b > 0:
        if abs(ur_b_db - uretim_b) > max(20, uretim_b * 0.3):
            uyarilar.append({"kod":"VERI_TUTARSIZ_URETIM_B","seviye":"warning",
                             "mesaj":"B slot="+str(uretim_b)+" db="+str(ur_b_db)})
    if tur_a > 500 or tur_b > 500:
        uyarilar.append({"kod":"VERI_TUTARSIZ_TUR","seviye":"warning",
                         "mesaj":"Anormal tur A:"+str(tur_a)+" B:"+str(tur_b)})
    # F9_5_4B_KALIP_OZET_BEGIN: Dominant A/B kalip hesabi
    from collections import Counter
    _a_sayim = Counter()
    _b_sayim = Counter()
    _a_meta = {}
    _b_meta = {}
    for _s in slotlar_zenginlestirilmis:
        _sk = (_s.get("slot") or "").upper()
        _is_a = (_sk == "A")
        _is_b = (_sk == "B")
        if not (_is_a or _is_b):
            continue
        _sd = (_s.get("durum") or "").upper()
        if _sd != "AKTIF":
            continue
        _kalip = _s.get("kalip") or {}
        _kid = _kalip.get("id")
        if _kid is None:
            continue
        if _is_a:
            _a_sayim[_kid] += 1
            if _kid not in _a_meta:
                _a_meta[_kid] = {"kod": _kalip.get("kod"), "renk_ad": _s.get("renk_ad"), "renk_kod": _s.get("renk_kod")}
        else:
            _b_sayim[_kid] += 1
            if _kid not in _b_meta:
                _b_meta[_kid] = {"kod": _kalip.get("kod"), "renk_ad": _s.get("renk_ad"), "renk_kod": _s.get("renk_kod")}

    def _kalip_ozet(_sayim, _meta):
        if not _sayim:
            return None
        _dom_id, _dom_count = _sayim.most_common(1)[0]
        _m = _meta[_dom_id]
        return {
            "kod": _m["kod"],
            "renk_ad": _m["renk_ad"],
            "renk_kod": _m["renk_kod"],
            "farkli_sayi": len(_sayim) - 1,
            "aktif_slot": sum(_sayim.values()),
        }

    a_kalip_ozet = _kalip_ozet(_a_sayim, _a_meta)
    b_kalip_ozet = _kalip_ozet(_b_sayim, _b_meta)
    # F9_5_4B_KALIP_OZET_END

    
    return {
        "teorik_cift": teorik_son, "teorik_a": teorik_a, "teorik_b": teorik_b,
        "teorik_govde": teorik_govde, "teorik_atki": teorik_atki,
        "brut_cift": brut_son, "uretilen_a": uretim_a, "uretilen_b": uretim_b,
        "tur_a": tur_a, "tur_b": tur_b,
        "aktif_a_slot": aktif_a, "aktif_b_slot": aktif_b,
        "net_cift": net, "net_kaynak": net_kaynak,
        "fire_cift": fire_cift, "fire_kg": fire_kg, "fire_orani": fire_orani,
        "teknik_fire_kg": teknik_kg, "bos_atis_kg": bos_atis_kg,
        "yolluk_fire_kg": yolluk_kg, "fire_seviye": fire_seviye,
        "verim_yuzde": verim, "eski_sistem_fallback": eski_sistem_fallback,
        "uyarilar": uyarilar,
        "a_kalip_ozet": a_kalip_ozet,
        "b_kalip_ozet": b_kalip_ozet,
    }



# =============================================================================
# 7. SETUP / ARIZA OLAY OZETI
# =============================================================================
def setup_ariza_olay_ozet(con, rapor_id):
    """
    SETUP_END ve ARIZA_END event'lerinden sayim + sure ozet.
    
    Returns:
        dict: {
            'setup_sayi': int,
            'setup_toplam_dk': int,
            'ariza_sayi': int,
            'ariza_toplam_dk': int,
        }
    """
    cur = con.cursor()
    cur.execute("""
        SELECT event_type, meta_json
        FROM enj_event_log
        WHERE rapor_id = ?
          AND event_type IN ('SETUP_END', 'ARIZA_END')
        ORDER BY zaman ASC
    """, (rapor_id,))
    
    setup_sayi = 0
    setup_dk = 0
    ariza_sayi = 0
    ariza_dk = 0
    
    for ev_type, meta in cur.fetchall():
        try:
            meta_d = json.loads(meta) if meta else {}
        except Exception:
            meta_d = {}
        
        sure = meta_d.get("sure_dakika") or meta_d.get("sure_dk") or 0
        try:
            sure = int(sure)
        except Exception:
            sure = 0
        
        if ev_type == "SETUP_END":
            setup_sayi += 1
            setup_dk += sure
        elif ev_type == "ARIZA_END":
            ariza_sayi += 1
            ariza_dk += sure
    
    return {
        "setup_sayi": setup_sayi,
        "setup_toplam_dk": setup_dk,
        "ariza_sayi": ariza_sayi,
        "ariza_toplam_dk": ariza_dk,
    }


# =============================================================================
# 8. KORGUN ESLESME
# =============================================================================
def korgun_eslesme(rapor):
    """
    Korgun kapanis verisini sunar (V1'de manuel/rapor uzerinde).
    
    Returns:
        dict: {
            'korgun_cift': int|None,
            'fark_cift': int|None,
            'uyarilar': [...]
        }
    """
    uyarilar = []
    
    korgun = None
    fark = None
    
    if rapor:
        korgun = rapor.get("korgun_kapatti_cift")
        fark = rapor.get("fark_cift")
    
    if korgun is None:
        uyarilar.append({
            "kod": "KORGUN_VERI_YOK",
            "seviye": "info",
            "mesaj": "Korgun kapanis verisi yok (V2'de otomatik sync)",
        })
    
    return {
        "korgun_cift": korgun,
        "fark_cift": fark,
        "uyarilar": uyarilar,
    }


# =============================================================================
# 9. EKSIK VERI UYARILARI (TOPLAYICI)
# =============================================================================
def eksik_veri_uyarilari(*uyari_kaynaklari):
    """
    Tum altsistemlerden gelen uyarilari birlestirir, deduplicate eder.
    
    Args:
        *kaynaklar: liste listesi
    
    Returns:
        list: [{'kod', 'seviye', 'mesaj'}, ...] (dedup edilmis)
    """
    toplu = []
    seen_kodlar = set()
    
    for kaynak in uyari_kaynaklari:
        if not kaynak:
            continue
        for u in kaynak:
            if not u:
                continue
            kod = u.get("kod")
            if kod in seen_kodlar:
                # Ayni kod tekrar gelirse mesaji birlestirebiliriz (V2)
                continue
            seen_kodlar.add(kod)
            toplu.append(u)
    
    return toplu


# =============================================================================
# 10. OLAY TIMELINE
# =============================================================================
EVENT_TIP_MAP = {
    "SETUP_START":   {"ikon": "tool",            "renk": "amber",   "metin": "Setup baslatildi"},
    "SETUP_END":     {"ikon": "check",           "renk": "yesil",   "metin": "Setup tamamlandi"},
    "ARIZA_START":   {"ikon": "alert-triangle",  "renk": "kirmizi", "metin": "Ariza bildirildi"},
    "ARIZA_END":     {"ikon": "check",           "renk": "yesil",   "metin": "Ariza kapatildi"},
    "DURUM_DEGISIM": {"ikon": "switch",          "renk": "gri",     "metin": "Durum degisti"},
    "A_B_TOGGLE":    {"ikon": "toggle-right",    "renk": "gri",     "metin": "A/B toggle (legacy)"},
    "TOPLU_X":       {"ikon": "x",               "renk": "gri",     "metin": "Toplu kapatma"},
    "TOPLU_A":       {"ikon": "play",            "renk": "yesil",   "metin": "Toplu A aktif"},
    "TOPLU_B":       {"ikon": "play",            "renk": "yesil",   "metin": "Toplu B aktif"},
    "SSR_SYNC":      {"ikon": "refresh",         "renk": "gri",     "metin": "Sistem sync"},
}


def olay_timeline_olustur(con, rapor_id, limit=200):
    """
    Vardiya boyunca tum olaylar kronolojik sira.
    
    Returns:
        list: [{'id', 'zaman', 'tip', 'istasyon_id', 'istasyon_label',
                'ikon', 'renk', 'metin', 'detay': {...}}, ...]
    """
    cur = con.cursor()
    cur.execute("""
        SELECT e.id, e.event_type, e.event_group, e.zaman, e.istasyon_id,
               e.onceki_deger, e.yeni_deger, e.meta_json,
               i.istasyon_no, i.slot
        FROM enj_event_log e
        LEFT JOIN enj_istasyon_durumu i ON i.id = e.istasyon_id
        WHERE e.rapor_id = ?
        ORDER BY e.zaman DESC, e.id DESC
        LIMIT ?
    """, (rapor_id, limit))
    
    olaylar = []
    for r in cur.fetchall():
        ev_id, ev_type, ev_grp, zaman, ist_id, onc, yeni, meta, ist_no, slot = r
        
        tip_info = EVENT_TIP_MAP.get(ev_type, {"ikon": "info", "renk": "gri", "metin": ev_type})
        
        ist_label = f"IST{ist_no}-{slot}" if ist_no and slot else None
        
        try:
            meta_d = json.loads(meta) if meta else {}
        except Exception:
            meta_d = {}
        
        olaylar.append({
            "id": ev_id,
            "zaman": zaman,
            "tip": ev_type,
            "grup": ev_grp,
            "istasyon_id": ist_id,
            "istasyon_label": ist_label,
            "ikon": tip_info["ikon"],
            "renk": tip_info["renk"],
            "metin": tip_info["metin"],
            "onceki": onc,
            "yeni": yeni,
            "detay": meta_d,
        })
    
    return olaylar


# =============================================================================
# 11. RAPOR AGGREGATE (ANA ENTRY)
# =============================================================================

def _renk_ad_coz(renk_str):
    """F9_5_4B_KALIP_OZET: '0001 - SIYAH' -> ('0001', 'SIYAH')"""
    if not renk_str:
        return None, None
    s = renk_str.strip()
    if " - " in s:
        parts = s.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return None, s


def rapor_aggregate(con, makine_id, tarih_str, vardiya, simdi_dt=None):
    """
    Tek makine icin TUM raporu birlestirir (genel endpoint icin).
    
    Returns:
        dict veya None (rapor yoksa)
    """
    cur = con.cursor()
    
    # 1) Rapor cek
    cur.execute("""
        SELECT * FROM enj_gunluk_rapor
        WHERE makine_id = ? AND tarih = ? AND vardiya = ?
        LIMIT 1
    """, (makine_id, tarih_str, vardiya))
    
    row = cur.fetchone()
    if not row:
        return None
    
    # Kolon isimlerini al
    cur.execute("PRAGMA table_info(enj_gunluk_rapor)")
    kols = [c[1] for c in cur.fetchall()]
    rapor = dict(zip(kols, row))
    rapor_id = rapor["id"]
    
    # 2) Vardiya araligi
    aralik = vardiya_aralik(tarih_str, vardiya, simdi_dt=simdi_dt)
    vardiya_dk = aralik["sure_dk"]
    
    # 3) Slotlar
    cur.execute("""
        SELECT i.id, i.istasyon_no, i.slot, i.durum, i.kalip_id,
               k.kalip_kod, k.model_kod, k.kalip_basi_cift, k.kapasite_cift,
               k.varsayilan_bagli_kalip, k.kalip_tipi,
               i.bagli_kalip_adet,
               i.renk
        FROM enj_istasyon_durumu i
        LEFT JOIN enj_kalip k ON k.id = i.kalip_id
        WHERE i.rapor_id = ?
        ORDER BY i.istasyon_no, i.slot
    """, (rapor_id,))
    
    slotlar_raw = cur.fetchall()
    slotlar_zenginlestirilmis = []
    
    for sr in slotlar_raw:
        i_id, i_no, i_slot, i_durum, k_id, k_kod, k_mod, k_kbc, k_kap, k_vbk, k_tipi, i_bagli, i_renk = sr
        
        # Slot sure dagilimi
        sureler = slot_sure_dagilim(con, i_id, rapor_id, aralik)
        
        # F9_5_4B_KALIP_OZET: renk parsing
        _renk_kod, _renk_ad = _renk_ad_coz(i_renk)
        slot_dict = {
            "istasyon_id": i_id,
            "istasyon_no": i_no,
            "slot": i_slot,
            "durum": i_durum,
            "bagli_kalip_adet": i_bagli,
            "renk": i_renk,
            "renk_kod": _renk_kod,
            "renk_ad": _renk_ad,
            "kalip": {
                "id": k_id,
                "kod": k_kod,
                "model_kod": k_mod,
                "kalip_basi_cift": k_kbc,
                "kapasite_cift": k_kap,
                "varsayilan_bagli_kalip": k_vbk,
                "kalip_tipi": k_tipi,
            } if k_id else None,
            "sureler": sureler,
        }
        slotlar_zenginlestirilmis.append(slot_dict)
    
    # 4) Hibrit durum
    sureler_listesi = [s["sureler"] for s in slotlar_zenginlestirilmis]
    durum = makine_hibrit_durum_genisletilmis(
        [{"durum": s["durum"]} for s in slotlar_zenginlestirilmis],
        sureler_listesi=sureler_listesi,
        vardiya_dk=vardiya_dk,
    )
    
    # 5) Saatlik tur
    saatlik = saatlik_tur_toplam(con, rapor_id)
    
    # 6) Teorik/Brut/Net/Fire
    uretim = makine_teorik_brut_net_fire(
        rapor,
        slotlar_zenginlestirilmis,
        saatlik,
        vardiya_dk,
    )
    
    # 7) Setup/Ariza ozet
    olay_ozet = setup_ariza_olay_ozet(con, rapor_id)
    
    # 8) Korgun eslesme
    korgun = korgun_eslesme(rapor)
    
    # 9) Slot-dakika dagilimi (zaman bazli)
    slot_dakika = {d: 0 for d in DURUM_TIPLERI}
    for s in slotlar_zenginlestirilmis:
        for d in DURUM_TIPLERI:
            slot_dakika[d] += s["sureler"].get(d, 0)
    slot_dakika_toplam = sum(slot_dakika.values())
    
    # 10) Uyarilari birlestir
    uyarilar = eksik_veri_uyarilari(
        saatlik.get("uyarilar"),
        uretim.get("uyarilar"),
        korgun.get("uyarilar"),
    )
    
    return {
        "rapor_id": rapor_id,
        "makine_id": makine_id,
        "tarih": tarih_str,
        "vardiya": vardiya,
        # P4: personel_sayisi = max(A_personel, B_personel) backend tarafindan sync ediliyor
        "personel_sayisi": rapor.get("personel_sayisi"),
        "aralik": {
            "baslangic": aralik["baslangic"].strftime("%Y-%m-%d %H:%M"),
            "bitis": aralik["bitis"].strftime("%Y-%m-%d %H:%M"),
            "sure_dk": vardiya_dk,
            "aktif_mi": aralik["aktif_mi"],
            "gecen_dk": aralik["gecen_dk"],
            "kalan_dk": aralik["kalan_dk"],
        },
        "anlik_durum": durum,
        "uretim": uretim,
        "saatlik": saatlik,
        "olay_ozet": olay_ozet,
        "korgun": korgun,
        "slot_dakika_dagilim": {
            "AKTIF": slot_dakika["AKTIF"],
            "KAPALI": slot_dakika["KAPALI"],
            "SETUP": slot_dakika["SETUP"],
            "ARIZA": slot_dakika["ARIZA"],
            "toplam": slot_dakika_toplam,
        },
        "slotlar": slotlar_zenginlestirilmis,
        "uyarilar": uyarilar,
    }


# =============================================================================
# F9_5_1_HESAP_END
# =============================================================================
