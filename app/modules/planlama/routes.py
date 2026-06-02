# -*- coding: utf-8 -*-



"""



SOLARIZ CPS - PLANLAMA / KARAR MASASI (Faz 2)



==============================================



Operasyon karar masasi.



- Kart + durum odakli gorunum



- Sadece okuma, henuz yazma yok



- Korgun + CPS verileri ayri tutulur



"""



from flask import Blueprint, render_template, jsonify, session, redirect, url_for

from modules.auth import yetki_gerekli, yetki_var

from db import get_conn as _get_conn_plan











planlama_bp = Blueprint(



    'planlama_bp',



    __name__,



    url_prefix='/planlama'



)











# =====================================================



# MOCK VERI - Faz 3'te Korgun + CPS'den otomatik beslenecek



# =====================================================



MOCK_SIPARISLER = [



    {



        "siparis_no": "33680",



        "emir_no": "E.110626",



        "model": "BRP-9000",



        "musteri": "Lc Waikiki",



        "miktar": 1200,



        "termin": "2026-05-31",



        



        "zaman": {



            "kova": "BU_HAFTA",



            "termin_durumu": "yaklasiyor"



        },



        



        "musteri_etiketleri": ["LCW", "NAKIT"],



        "oncelik": "NORMAL",



        



        "korgun": {



            "yapilan": 480,



            "kalan": 720,



            "yuzde": 28.1,



            "son_proses": "MAMUL / Temizleme"



        },



        



        "cps": {



            "darbogaz": {



                "var": True,



                "ana": "MAMUL",



                "alt_proses": "Temizleme",



                "sapma": 88.6,



                "seviye": "KRITIK"



            },



            "production_ready": {



                "durum": "HAZIR",



                "detay": [



                    {"parca": "EVA", "durum": "tamam"},



                    {"parca": "Patch", "durum": "tamam"},



                    {"parca": "Isik", "durum": "tamam"},



                    {"parca": "Toka", "durum": "tamam"}



                ],



                "bloke_sebebi": None,



                "tahmini_hazir": None



            },



            "notlar": ["Halil onayi bekleniyor"]



        }



    },



    {



        "siparis_no": "33700",



        "emir_no": "E.110700",



        "model": "XYZ-5000",



        "musteri": "Boyner",



        "miktar": 600,



        "termin": "2026-06-15",



        



        "zaman": {



            "kova": "SONRAKI_HAFTA",



            "termin_durumu": "normal"



        },



        



        "musteri_etiketleri": [],



        "oncelik": "NORMAL",



        



        "korgun": {



            "yapilan": 30,



            "kalan": 570,



            "yuzde": 5.0,



            "son_proses": "GOVDE / Kesim"



        },



        



        "cps": {



            "darbogaz": {



                "var": False,



                "ana": None,



                "alt_proses": None,



                "sapma": 0,



                "seviye": "NORMAL"



            },



            "production_ready": {



                "durum": "KISMI",



                "detay": [



                    {"parca": "EVA", "durum": "tamam"},



                    {"parca": "Patch", "durum": "tamam"},



                    {"parca": "Isik", "durum": "3 gun sonra"},



                    {"parca": "Toka", "durum": "tamam"}



                ],



                "bloke_sebebi": "Isik 3 gun sonra gelecek",



                "tahmini_hazir": "2026-05-09"



            },



            "notlar": []



        }



    },



    {



        "siparis_no": "33750",



        "emir_no": "E.110750",



        "model": "DEF-7000",



        "musteri": "Koton",



        "miktar": 800,



        "termin": "2026-05-25",



        



        "zaman": {



            "kova": "BU_AY",



            "termin_durumu": "yaklasiyor"



        },



        



        "musteri_etiketleri": [],



        "oncelik": "ACIL",



        



        "korgun": {



            "yapilan": 0,



            "kalan": 800,



            "yuzde": 0,



            "son_proses": "Henuz baslamadi"



        },



        



        "cps": {



            "darbogaz": {



                "var": False,



                "ana": None,



                "alt_proses": None,



                "sapma": 0,



                "seviye": "NORMAL"



            },



            "production_ready": {



                "durum": "BLOKE",



                "detay": [



                    {"parca": "EVA", "durum": "tamam"},



                    {"parca": "Patch", "durum": "tamam"},



                    {"parca": "Isik", "durum": "tamam"},



                    {"parca": "Toka", "durum": "EKSIK"}



                ],



                "bloke_sebebi": "Toka eksik - tedarikciden termin bekleniyor",



                "tahmini_hazir": None



            },



            "notlar": ["ACIL: tedarikciye baski yapilmasi gerekiyor"]



        }



    },



    {



        "siparis_no": "33800",



        "emir_no": "E.110800",



        "model": "GHI-9000",



        "musteri": "Lc Waikiki",



        "miktar": 2000,



        "termin": "2026-08-15",



        



        "zaman": {



            "kova": "3_AY",



            "termin_durumu": "uzak"



        },



        



        "musteri_etiketleri": ["LCW"],



        "oncelik": "NORMAL",



        



        "korgun": {



            "yapilan": 0,



            "kalan": 2000,



            "yuzde": 0,



            "son_proses": "Henuz baslamadi"



        },



        



        "cps": {



            "darbogaz": {



                "var": False,



                "ana": None,



                "alt_proses": None,



                "sapma": 0,



                "seviye": "NORMAL"



            },



            "production_ready": {



                "durum": "BILINMIYOR",



                "detay": [],



                "bloke_sebebi": "Henuz degerlendirilmedi",



                "tahmini_hazir": None



            },



            "notlar": []



        }



    },



    {



        "siparis_no": "33638",



        "emir_no": "E.110626",



        "model": "CRX-71033-LCW",



        "musteri": "Lc Waikiki",



        "miktar": 7000,



        "termin": "2026-05-31",



        



        "zaman": {



            "kova": "BU_HAFTA",



            "termin_durumu": "yaklasiyor"



        },



        



        "musteri_etiketleri": ["LCW", "NAKIT"],



        "oncelik": "NORMAL",



        



        "korgun": {



            "yapilan": 1970,



            "kalan": 5030,



            "yuzde": 28.1,



            "son_proses": "GOVDE / Kesim"



        },



        



        "cps": {



            "darbogaz": {



                "var": False,



                "ana": None,



                "alt_proses": None,



                "sapma": 0,



                "seviye": "NORMAL"



            },



            "production_ready": {



                "durum": "HAZIR",



                "detay": [



                    {"parca": "EVA", "durum": "tamam"},



                    {"parca": "Patch", "durum": "tamam"},



                    {"parca": "Isik", "durum": "tamam"},



                    {"parca": "Toka", "durum": "tamam"}



                ],



                "bloke_sebebi": None,



                "tahmini_hazir": None



            },



            "notlar": []



        }



    }



]











# =====================================================



# ENDPOINT 1: HTML SAYFA



# =====================================================



# ============================================================

# FAZ KOPRU-1 EK (13.05.2026): KOK ROUTE REDIRECT

# /planlama/ -> /planlama/karar-masasi

# Modul standardi: her CPS modulu kok URL'de calismali.

# ============================================================

@planlama_bp.route('/')

def kok():

    return redirect(url_for('planlama_bp.karar_masasi'))





@planlama_bp.route('/karar-masasi', methods=['GET'])

@yetki_gerekli('planlama.karar_masasi', 'can_view')



def karar_masasi():



    return render_template('planlama/karar_masasi.html')











# =====================================================



# ENDPOINT 2: JSON VERI



# =====================================================



# =====================================================

# KARAR MASASI v3 — MOCK VERI MOTORU (Faz 1)

# =====================================================

from datetime import datetime, timedelta



KM_BUGUN_STR = "2026-05-06"  # Mock bugun



def _km_termin_durum(termin_str, bugun_str=KM_BUGUN_STR):

    """termin durumu: uzak / yakin / gecti"""

    try:

        termin = datetime.strptime(termin_str, "%Y-%m-%d").date()

        bugun = datetime.strptime(bugun_str, "%Y-%m-%d").date()

        kalan_gun = (termin - bugun).days

        if kalan_gun < 0:

            return ("gecti", kalan_gun)

        elif kalan_gun <= 7:

            return ("yakin", kalan_gun)

        else:

            return ("uzak", kalan_gun)

    except Exception:

        return ("uzak", 999)





def _km_satir_rengi(satir):

    """Renk onceligi: BLOKE > GECIKMIS > NAKIT > KISMI > HAZIR"""

    # 1. BLOKE

    if satir.get("uretilebilirlik") == "BLOKE":

        return "bloke"

    # 2. GECIKMIS

    durum, _ = _km_termin_durum(satir.get("termin", ""))

    if durum == "gecti":

        return "gecikmis"

    # 3. NAKIT/VIP

    etiketler = satir.get("musteri_etiketleri", []) or []

    if any(e.upper() in ["NAKIT", "NAKİT", "VIP"] for e in etiketler):

        return "nakit"

    # 4. KISMI

    if satir.get("uretilebilirlik") == "KISMI":

        return "kismi"

    # 5. HAZIR (default)

    return "hazir"





def _km_skor(satir):

    """Akilli sira skoru. Yuksek skor = yukari"""

    skor = 0

    renk = satir.get("satir_rengi", "hazir")



    if renk == "bloke":      skor += 1000

    elif renk == "gecikmis": skor += 800

    elif renk == "nakit":    skor += 600

    elif renk == "kismi":    skor += 400

    elif renk == "hazir":    skor += 200



    # Termin yakinligi

    _, kalan_gun = _km_termin_durum(satir.get("termin", ""))

    if kalan_gun >= 0:

        skor += max(0, 200 - kalan_gun * 5)

    else:

        skor += 250  # gecikmis ekstra puan



    # Darbogaz siddeti

    darbogaz = satir.get("darbogaz", {})

    if darbogaz.get("var"):

        skor += int(darbogaz.get("sapma", 0))



    # Bant atanmamis

    if not satir.get("bant"):

        skor += 50



    # NAKIT/VIP etiketleri ekstra

    etiketler = satir.get("musteri_etiketleri", []) or []

    if any(e.upper() in ["NAKIT", "NAKİT"] for e in etiketler):

        skor += 100

    if "VIP" in [e.upper() for e in etiketler]:

        skor += 80



    return skor







# ── CORE_ILISKI Org Katmanı (FAZ43 PARÇA 3) ─────────────────────

_km_org_cache = {}  # {darb_alt: org_dict} — istek başı önbellek



_DARB_PROSES_MAP = {

    "Temizleme":       "35",

    "Saya":            "15",

    "Saya Kontrol":    "18",

    "Kesim":           "02",

    "Enjeksiyon":      "26",

    "Monta":           "30",

    "Mekval":          "32",

    "Eva Hazir":       "50",

    "Saya Hazir":      "42",

    "Monta Baslayacak":"28",

}



def _km_org_katman(darb_alt):

    """

    Darboğaz proses adından (ör: 'Temizleme') → org bilgisi.

    Önbellekli. Crash vermez.

    """

    global _km_org_cache

    if darb_alt is None:

        return {"ekip": None, "lider": None, "vardiya": None, "proses": None, "durum": "yok"}

    if darb_alt in _km_org_cache:

        return _km_org_cache[darb_alt]



    proses_kod = _DARB_PROSES_MAP.get(darb_alt)

    if not proses_kod:

        sonuc = {"ekip": None, "lider": None, "vardiya": None,

                 "proses": darb_alt, "durum": "belirsiz"}

        _km_org_cache[darb_alt] = sonuc

        return sonuc



    try:

        con = _get_conn_plan()

        row = con.execute("""

            SELECT

                em.ad               AS ekip_ad,

                em.kod              AS ekip_kod,

                lider.gercek_ad     AS lider_ad,

                lider.kullanici_adi AS lider_kadi,

                ev.vardiya_adi      AS vardiya,

                kup.iliski_tipi     AS iliski

            FROM proses_usta_atama pua

            JOIN kullanici_profil kp

                ON kp.kullanici_adi = pua.usta_kullanici AND pua.aktif=1

            JOIN kullanici_ekip ke

                ON ke.kullanici_profil_id = kp.id AND ke.aktif=1

            JOIN ekip_master em

                ON em.id = ke.ekip_id

            JOIN kullanici_profil lider

                ON lider.id = em.lider_kullanici_profil_id

            LEFT JOIN ekip_vardiya ev

                ON ev.ekip_id = em.id

            LEFT JOIN kullanici_proses kup

                ON kup.kullanici_profil_id = kp.id AND kup.aktif=1

            WHERE pua.proses_kod = ?

            LIMIT 1

        """, (proses_kod,)).fetchone()

        con.close()



        if row:

            durum = "tam" if (row["ekip_ad"] and row["lider_ad"] and row["vardiya"])                    else "eksik"

            sonuc = {

                "ekip":    row["ekip_ad"],

                "lider":   row["lider_ad"],

                "lider_kadi": row["lider_kadi"],

                "vardiya": row["vardiya"],

                "proses":  darb_alt,

                "durum":   durum,

            }

        else:

            sonuc = {"ekip": None, "lider": None, "vardiya": None,

                     "proses": darb_alt, "durum": "kritik"}

    except Exception:

        sonuc = {"ekip": None, "lider": None, "vardiya": None,

                 "proses": darb_alt, "durum": "hata"}



    _km_org_cache[darb_alt] = sonuc

    return sonuc



# ── END CORE_ILISKI Org Katmanı ──────────────────────────────────

# ── CORE_ILISKI Org Risk Skoru (FAZ43 PARÇA 3 Sprint 2) ─────────

def _km_org_risk_hesapla(darbogaz, org):

    """

    Saf/read-only. Crash vermez.

    darbogaz: {"var":bool,"sapma":int,...}

    org:      {"ekip":str,"lider":str,"vardiya":str,"durum":str}

    → {"skor":int, "seviye":str, "neden":str, "renk":str}

    """

    if not darbogaz or not darbogaz.get("var"):

        return {"skor": 0, "seviye": "yok", "neden": "Darboğaz yok", "renk": "gray"}



    skor = 0

    nedenler = []

    sapma = int(darbogaz.get("sapma") or 0)



    # 1. Darboğaz şiddeti

    if sapma >= 70:

        skor += 50; nedenler.append(f"Darboğaz +%{sapma}")

    elif sapma >= 30:

        skor += 30; nedenler.append(f"Darboğaz +%{sapma}")

    elif sapma > 0:

        skor += 15; nedenler.append(f"Darboğaz +%{sapma}")



    # 2. Org durumu

    if not org or org.get("durum") in ("kritik", "hata", "belirsiz", None):

        skor += 40; nedenler.append("Org resolve edilemedi")

    elif org.get("durum") == "eksik":

        skor += 20; nedenler.append("Ekip/lider eksik")

    # durum=="tam" → skor artmaz



    # 3. Lider eksik

    if org and org.get("ekip") and not org.get("lider"):

        skor += 15; nedenler.append("Lider atanmamış")



    # 4. Vardiya eksik

    if org and org.get("ekip") and not org.get("vardiya"):

        skor += 5; nedenler.append("Vardiya tanımsız")



    skor = min(skor, 100)



    if skor >= 70:

        return {"skor": skor, "seviye": "kritik", "renk": "red",

                "neden": " + ".join(nedenler) or "Kritik"}

    elif skor >= 35:

        return {"skor": skor, "seviye": "orta", "renk": "orange",

                "neden": " + ".join(nedenler) or "Orta"}

    elif skor > 0:

        return {"skor": skor, "seviye": "dusuk", "renk": "green",

                "neden": " + ".join(nedenler) or "Düşük"}

    else:

        return {"skor": 0, "seviye": "dusuk", "renk": "green", "neden": "Normal"}



# ── END Risk Skoru ───────────────────────────────────────────────

# ── CORE_ILISKI Müdahale Öneri Motoru (FAZ43 Sprint 3) ──────────

def _km_mudahale_oneri(darbogaz, org, risk):

    """

    Saf/read-only. Crash vermez.

    risk: {"skor":int, "seviye":str}

    → {"tip":str, "oncelik":str, "mesaj":str, "ikon":str, "renk":str}

    """

    if not darbogaz or not darbogaz.get("var"):

        return {"tip": "takip", "oncelik": "dusuk",

                "mesaj": "Takip et", "ikon": "🟢", "renk": "#16a34a"}



    skor    = int((risk or {}).get("skor") or 0)

    sapma   = int((darbogaz or {}).get("sapma") or 0)

    ekip    = (org or {}).get("ekip")

    lider   = (org or {}).get("lider")

    vardiya = (org or {}).get("vardiya")

    bridge  = (org or {}).get("durum") not in ("kritik", "hata", "belirsiz", None)



    # Kural 1: Kritik insan eksikliği

    if not bridge and sapma >= 50:

        return {"tip": "acil", "oncelik": "kritik",

                "mesaj": "Kritik: Org bağlantısı eksik",

                "ikon": "🔴", "renk": "#dc2626"}



    # Kural 2: Yüksek sapma + org eksik

    if sapma >= 70 and (not ekip or not lider):

        return {"tip": "acil", "oncelik": "kritik",

                "mesaj": f"Acil müdahale — %{sapma} sapma",

                "ikon": "🔴", "renk": "#dc2626"}



    # Kural 3: Risk kritik seviyede

    if skor >= 70:

        return {"tip": "acil", "oncelik": "kritik",

                "mesaj": f"Acil müdahale — risk %{skor}",

                "ikon": "🔴", "renk": "#dc2626"}



    # Kural 4: Yüksek sapma (50-70), org var

    if sapma >= 50:

        return {"tip": "guclendir", "oncelik": "yuksek",

                "mesaj": f"Vardiya güçlendir — %{sapma} sapma",

                "ikon": "🟠", "renk": "#ea580c"}



    # Kural 5: Risk orta veya lider eksik

    if skor >= 35 or (ekip and not lider):

        return {"tip": "kontrol", "oncelik": "orta",

                "mesaj": "Lider kontrolü öner",

                "ikon": "🟡", "renk": "#ca8a04"}



    # Kural 6: Orta sapma (15-50)

    if sapma >= 15:

        return {"tip": "kontrol", "oncelik": "orta",

                "mesaj": f"İzle + lider bilgilendir",

                "ikon": "🟡", "renk": "#ca8a04"}



    # Kural 7: Düşük sapma

    return {"tip": "takip", "oncelik": "dusuk",

            "mesaj": "Takip et", "ikon": "🟢", "renk": "#16a34a"}



# ── END Müdahale Öneri ───────────────────────────────────────────



# ── CORE_ILISKI Görev/Push Hazırlık Payload (FAZ43 Sprint 4) ────

def _km_gorev_hazirlik_payload(satir, org, risk, mudahale):

    if not mudahale or mudahale.get('tip') == 'takip':

        return {'hazir': False}

    tip     = mudahale.get('tip', 'takip')

    oncelik = mudahale.get('oncelik', 'dusuk')

    sapma   = int((satir.get('darbogaz') or {}).get('sapma') or 0)

    proses  = (satir.get('darbogaz') or {}).get('alt') or ''

    sip_no  = satir.get('siparis_no') or ''

    musteri = satir.get('musteri') or ''

    model   = satir.get('model') or ''

    skor    = int((risk or {}).get('skor') or 0)

    ekip    = (org or {}).get('ekip') or ''

    lider   = (org or {}).get('lider_kadi') or (org or {}).get('lider') or ''

    if tip == 'acil':

        hedef_kisi = lider or 'yonetim'

        konu  = 'ACİL: ' + proses + ' darboğazı +%' + str(sapma)

        mesaj = musteri + '/' + model + ' siparişinde ' + proses + ' +%' + str(sapma) + ' sapma. Acil müdahale.'

    elif tip == 'guclendir':

        hedef_kisi = lider or 'planlama'

        konu  = 'Vardiya güçlendir: ' + proses + ' +%' + str(sapma)

        mesaj = proses + ' prosesinde +%' + str(sapma) + ' sapma. Ek vardiya değerlendirilmeli.'

    else:

        hedef_kisi = lider or 'planlama'

        konu  = 'Lider kontrolü: ' + proses + ' +%' + str(sapma)

        mesaj = proses + ' prosesinde +%' + str(sapma) + ' sapma. Lider kontrolü önerilir.'

    return {

        'hazir': True, 'hedef_kisi': hedef_kisi, 'hedef_ekip': ekip,

        'konu': konu, 'mesaj': mesaj, 'oncelik': oncelik,

        'kaynak': 'karar_masasi', 'siparis_no': sip_no,

        'musteri': musteri, 'model': model,

        'proses': proses, 'risk_skoru': skor, 'mudahale_tip': tip,

    }

# ── END Görev Payload ────────────────────────────────────────







def _km_mock_satirlar():

    """22 satir gercek fabrika benzeri mock veri"""

    raw = [

        # ============== BLOKE (3 satir) ==============

        {"musteri":"Koton","etiketler":[],"sip":"33750","emir":"110750","model":"DEF-7000","renk":"Siyah","beden":"36-40",

         "adet":800,"yapilan":0,"termin":"2026-05-25","oncelik":"ACIL","bant":None,

         "patch":"tamam","isik":"tamam","toka":"yok","uretilebilirlik":"BLOKE",

         "bloke_sebebi":"Toka tedarik bekliyor",

         "darbogaz":{"var":False},

         "not":"ACIL: tedarikciye baski",

         "talimat":""},

        {"musteri":"Defacto","etiketler":[],"sip":"33780","emir":"110780","model":"PTK-2000","renk":"Lacivert","beden":"36-41",

         "adet":1500,"yapilan":0,"termin":"2026-06-10","oncelik":"NORMAL","bant":None,

         "patch":"yok","isik":"tamam","toka":"tamam","uretilebilirlik":"BLOKE",

         "bloke_sebebi":"Patch eksik",

         "darbogaz":{"var":False},

         "not":"Patch tedariki gec",

         "talimat":""},

        {"musteri":"Lc Waikiki","etiketler":["NAKIT"],"sip":"33820","emir":"110820","model":"CRX-71050","renk":"Beyaz","beden":"23-32",

         "adet":2400,"yapilan":120,"termin":"2026-05-30","oncelik":"NAKIT","bant":None,

         "patch":"tamam","isik":"yok","toka":"tamam","uretilebilirlik":"BLOKE",

         "bloke_sebebi":"Isik gelmedi",

         "darbogaz":{"var":False},

         "not":"NAKIT musteri, isik gelmesi kritik",

         "talimat":""},



        # ============== GECIKMIS (2 satir) ==============

        {"musteri":"Tedi Discount","etiketler":[],"sip":"33459","emir":"109158","model":"CRP-82046","renk":"Pembe","beden":"23-32",

         "adet":3000,"yapilan":2402,"termin":"2026-04-28","oncelik":"GECIKTI","bant":"B-3",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":True,"ana":"GOVDE","alt":"Saya","sapma":45},

         "not":"Termin gecti, musteriyle yeni tarih",

         "talimat":"Bant-3 oncelik, mesai gerekir"},

        {"musteri":"Boyner","etiketler":[],"sip":"33465","emir":"109200","model":"FLT-3500","renk":"Bej","beden":"36-41",

         "adet":1200,"yapilan":1080,"termin":"2026-05-02","oncelik":"GECIKTI","bant":"B-2",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"%90 bitti, son sevkiyat",

         "talimat":"Mekval bandında bitir"},



        # ============== NAKIT/VIP (4 satir) ==============

        {"musteri":"Lc Waikiki","etiketler":["NAKIT"],"sip":"33680","emir":"110626","model":"BRP-9000","renk":"Beyaz","beden":"23-32",

         "adet":1200,"yapilan":480,"termin":"2026-05-31","oncelik":"NAKIT","bant":"B-2",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":True,"ana":"MAMUL","alt":"Temizleme","sapma":88},

         "not":"Halil onayi bekleniyor",

         "talimat":"Temizleme bandını boşalt"},

        {"musteri":"Lc Waikiki","etiketler":["NAKIT"],"sip":"33681","emir":"110627","model":"BRP-9000","renk":"Siyah","beden":"23-32",

         "adet":1200,"yapilan":600,"termin":"2026-05-31","oncelik":"NAKIT","bant":"B-2",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"BRP-9000 ikinci renk",

         "talimat":"Aynı bantta seri devam"},

        {"musteri":"Pera Boutique","etiketler":["VIP"],"sip":"33800","emir":"110800","model":"VIP-5500","renk":"Krem","beden":"36-40",

         "adet":400,"yapilan":160,"termin":"2026-05-20","oncelik":"NAKIT","bant":"B-1",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"VIP musteri, ozel paketleme",

         "talimat":"Kalite ozel kontrol"},

        {"musteri":"Şahin Taban","etiketler":["NAKIT"],"sip":"33660","emir":"110660","model":"CRP-8130-L","renk":"Beyaz","beden":"23-32",

         "adet":600,"yapilan":600,"termin":"2026-06-30","oncelik":"NAKIT","bant":"B-1",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"E-ticaret, bitti, sevk hazir",

         "talimat":"Sevk paketle"},



        # ============== KISMI (4 satir) ==============

        {"musteri":"Boyner","etiketler":[],"sip":"33700","emir":"110700","model":"XYZ-5000","renk":"Lacivert","beden":"36-41",

         "adet":600,"yapilan":30,"termin":"2026-06-15","oncelik":"NORMAL","bant":None,

         "patch":"tamam","isik":"bekle","toka":"tamam","uretilebilirlik":"KISMI",

         "bloke_sebebi":"Isik 3 gun sonra",

         "darbogaz":{"var":False},

         "not":"Isik geldiginde basla",

         "talimat":""},

        {"musteri":"Tedi Discount","etiketler":[],"sip":"33850","emir":"110850","model":"TDD-4400","renk":"Pembe","beden":"26-33",

         "adet":2000,"yapilan":200,"termin":"2026-06-25","oncelik":"NORMAL","bant":None,

         "patch":"bekle","isik":"tamam","toka":"tamam","uretilebilirlik":"KISMI",

         "bloke_sebebi":"Patch yarin gelir",

         "darbogaz":{"var":False},

         "not":"",

         "talimat":""},

        {"musteri":"Lc Waikiki","etiketler":[],"sip":"33870","emir":"110870","model":"GRX-8800","renk":"Mavi","beden":"33-38",

         "adet":1800,"yapilan":900,"termin":"2026-07-10","oncelik":"NORMAL","bant":"B-3",

         "patch":"tamam","isik":"tamam","toka":"bekle","uretilebilirlik":"KISMI",

         "bloke_sebebi":"Toka 2 gun sonra",

         "darbogaz":{"var":True,"ana":"ATKI","alt":"Kesim","sapma":22},

         "not":"Kesim hizi dustu",

         "talimat":"Kesim bandında hızlanma gerek"},

        {"musteri":"İsna Tekstil","etiketler":[],"sip":"33577","emir":"110577","model":"YPF-9024","renk":"Mavi","beden":"26-33",

         "adet":1500,"yapilan":960,"termin":"2026-06-05","oncelik":"NORMAL","bant":"B-2",

         "patch":"tamam","isik":"bekle","toka":"tamam","uretilebilirlik":"KISMI",

         "bloke_sebebi":"Isik partisi yarin",

         "darbogaz":{"var":False},

         "not":"İsna stetch parti",

         "talimat":""},



        # ============== HAZIR — normal akis (9 satir) ==============

        {"musteri":"Lc Waikiki","etiketler":[],"sip":"33638","emir":"110626","model":"CRX-71033-LCW","renk":"Beyaz","beden":"33-38",

         "adet":7000,"yapilan":1970,"termin":"2026-05-31","oncelik":"NORMAL","bant":"B-1",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"",

         "talimat":"Monta hattını besle"},

        {"musteri":"Lc Waikiki","etiketler":[],"sip":"33635","emir":"110510","model":"CRX-71037-LCW","renk":"Siyah","beden":"23-32",

         "adet":5760,"yapilan":2880,"termin":"2026-06-10","oncelik":"NORMAL","bant":"B-1",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"",

         "talimat":"Saya devam"},

        {"musteri":"Lc Waikiki","etiketler":[],"sip":"33657","emir":"110687","model":"CRX-71043","renk":"Kirmizi","beden":"33-38",

         "adet":6160,"yapilan":4400,"termin":"2026-05-25","oncelik":"NORMAL","bant":"B-1",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"VENOM serisi, %71 bitti",

         "talimat":"Kesim son parti, monta basla"},

        {"musteri":"Tedi Discount","etiketler":[],"sip":"33456","emir":"109131","model":"CRP-8128-L","renk":"Beyaz","beden":"33-38",

         "adet":3200,"yapilan":3200,"termin":"2026-05-15","oncelik":"NORMAL","bant":"B-2",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"Bitti",

         "talimat":"Sevkiyat hazırla"},

        {"musteri":"Terteks (Twigy)","etiketler":[],"sip":"33443","emir":"108918","model":"CRP-82063-TWG","renk":"Beyaz","beden":"23-32",

         "adet":2160,"yapilan":1800,"termin":"2026-06-20","oncelik":"NORMAL","bant":"B-3",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"",

         "talimat":"Monta devam"},

        {"musteri":"Terteks (Twigy)","etiketler":[],"sip":"33443","emir":"108978","model":"CRP-82066-TWG","renk":"Siyah","beden":"23-32",

         "adet":1800,"yapilan":1200,"termin":"2026-06-20","oncelik":"NORMAL","bant":"B-3",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":True,"ana":"GOVDE","alt":"Saya","sapma":12},

         "not":"Hafif sapma izle",

         "talimat":"Saya hizi normal"},

        {"musteri":"Genceller (Esem)","etiketler":[],"sip":"33658","emir":"110778","model":"CRM-4750-ESM","renk":"Mavi","beden":"36-44",

         "adet":3600,"yapilan":2400,"termin":"2026-06-05","oncelik":"NORMAL","bant":"B-2",

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"E-ticaret",

         "talimat":"Kesim devam"},

        {"musteri":"Genceller (Esem)","etiketler":[],"sip":"33658","emir":"110917","model":"CRF-8250-ESM","renk":"Lacivert","beden":"36-44",

         "adet":1200,"yapilan":600,"termin":"2026-06-12","oncelik":"NORMAL","bant":None,

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"Bant atanacak",

         "talimat":""},

        {"musteri":"Boyner","etiketler":[],"sip":"33890","emir":"110890","model":"BNR-7700","renk":"Bej","beden":"36-41",

         "adet":900,"yapilan":300,"termin":"2026-07-25","oncelik":"NORMAL","bant":None,

         "patch":"tamam","isik":"tamam","toka":"tamam","uretilebilirlik":"HAZIR",

         "bloke_sebebi":None,

         "darbogaz":{"var":False},

         "not":"Yaz koleksiyonu",

         "talimat":""},

    ]



    # Her satiri zenginlestir

    satirlar = []

    for i, r in enumerate(raw, 1):

        kalan = r["adet"] - r["yapilan"]

        ilerleme = round(r["yapilan"] / r["adet"] * 100, 1) if r["adet"] > 0 else 0

        durum, kalan_gun = _km_termin_durum(r["termin"])

        gunluk_hedef = 0

        kac_gun = 0

        if r.get("bant") and kalan > 0:

            # Bant varsa bir hedef var

            gunluk_hedef = max(100, min(600, int(kalan / max(kalan_gun, 1))))

            kac_gun = int(kalan / gunluk_hedef) if gunluk_hedef > 0 else 0



        # Darbogaz ikon tipi

        darbogaz = dict(r["darbogaz"])

        if darbogaz.get("var"):

            darbogaz["ikon_tipi"] = "alev"

        elif r["uretilebilirlik"] == "BLOKE":

            darbogaz = {"var": True, "ikon_tipi": "paket-yok",

                        "metin": r.get("bloke_sebebi", "")}



        s = {

            "satir_id": f"S{i:03d}",

            "musteri": r["musteri"],

            "musteri_etiketleri": r["etiketler"],

            "siparis_no": r["sip"],

            "emir_no": r["emir"],

            "model": r["model"],

            "renk": r["renk"],

            "beden": r["beden"],

            "siparis_adet": r["adet"],

            "yapilan": r["yapilan"],

            "kalan": kalan,

            "ilerleme_yuzde": ilerleme,

            "termin": r["termin"],

            "kalan_gun": kalan_gun,

            "termin_durumu": durum,

            "oncelik": r["oncelik"],

            "bant": r["bant"],

            "gunluk_hedef": gunluk_hedef,

            "kac_gunde_biter": kac_gun,

            "hazirlik": {

                "patch": r["patch"],

                "isik":  r["isik"],

                "toka":  r["toka"]

            },

            "uretilebilirlik": r["uretilebilirlik"],

            "bloke_sebebi": r.get("bloke_sebebi"),

            "darbogaz": darbogaz,

            "planlama_notu": r.get("not", ""),

            "usta_talimati": r.get("talimat", "")

        }

        s["satir_rengi"] = _km_satir_rengi(s)

        s["skor"] = _km_skor(s)

        # CORE_ILISKI Org Katmanı

        _darb_alt = s.get("darbogaz", {}).get("alt")

        if s.get("darbogaz", {}).get("var") and _darb_alt:

            s["organizasyon"] = _km_org_katman(_darb_alt)

        else:

            s["organizasyon"] = {"ekip": None, "lider": None, "vardiya": None,

                                  "proses": None, "durum": "yok"}

        # CORE_ILISKI Org Risk Skoru

        s["organizasyon_risk"] = _km_org_risk_hesapla(s.get("darbogaz"), s.get("organizasyon"))

        # CORE_ILISKI Müdahale Önerisi

        s["mudahale_onerisi"] = _km_mudahale_oneri(

            s.get("darbogaz"), s.get("organizasyon"), s.get("organizasyon_risk"))

        # CORE_ILISKI Görev Hazırlık Payload

        s["gorev_hazirlik"] = _km_gorev_hazirlik_payload(

            s, s.get("organizasyon"), s.get("organizasyon_risk"), s.get("mudahale_onerisi"))

        satirlar.append(s)



    # Akilli sira: skor azalan

    satirlar.sort(key=lambda x: -x["skor"])

    for i, s in enumerate(satirlar, 1):

        s["plan_sirasi"] = i



    return satirlar





def _km_ozet(satirlar):

    """KPI bandi sayilarini mock satirlardan otomatik hesapla"""

    bugun = datetime.strptime(KM_BUGUN_STR, "%Y-%m-%d").date()

    hafta_sonu = bugun + timedelta(days=7)



    bu_hafta = 0

    kritik = 0

    hazir = 0

    bloke = 0

    darbogaz = 0

    termin_riski = 0



    for s in satirlar:

        termin = datetime.strptime(s["termin"], "%Y-%m-%d").date()

        if bugun <= termin <= hafta_sonu:

            bu_hafta += 1

        if s["termin_durumu"] == "gecti":

            kritik += 1

        if s["uretilebilirlik"] == "HAZIR" and s["satir_rengi"] != "gecikmis":

            hazir += 1

        if s["uretilebilirlik"] == "BLOKE":

            bloke += 1

        if s.get("darbogaz", {}).get("var") and s.get("darbogaz", {}).get("ikon_tipi") == "alev":

            darbogaz += 1

        if s["termin_durumu"] == "yakin" and s["uretilebilirlik"] != "HAZIR":

            termin_riski += 1



    return {

        "toplam_siparis": len(satirlar),

        "bu_hafta_plan": bu_hafta,

        "kritik_geciken": kritik,

        "uretime_hazir": hazir,

        "bloke": bloke,

        "darbogazli": darbogaz,

        "gunluk_kapasite": 8500,

        "termin_riski": termin_riski

    }



@planlama_bp.route('/karar-masasi/data', methods=['GET'])

@yetki_gerekli('planlama.karar_masasi', 'can_view')

def karar_masasi_data():

    global _km_org_cache

    _km_org_cache = {}  # her istekte önbelleği sıfırla

    try:

        satirlar = _km_mock_satirlar()

        ozet = _km_ozet(satirlar)

        return jsonify({

            "ok": True,

            "kaynak": "MOCK",

            "satir_sayisi": len(satirlar),

            "uretim_tarihi": KM_BUGUN_STR,

            "satirlar": satirlar,

            "ozet": ozet,

            "akilli_sira": True

        })

    except Exception as e:

        import traceback

        return jsonify({

            "ok": False,

            "hata": str(e),

            "traceback": traceback.format_exc()

        }), 500







# ════════════════════════════════════════════════════════════════
# FAZ43 SPRINT 5 — Manuel Görev Oluştur
# POST /api/planlama/karar-masasi/gorev-olustur
# Hedef: tasks tablosu (INSERT, mevcut şema bozulmaz)
# BEGIN FAZ43_SP5_GOREV
# ════════════════════════════════════════════════════════════════

@planlama_bp.route('/api/karar-masasi/gorev-olustur', methods=['POST'])
@yetki_gerekli('planlama.karar_masasi', 'can_create')
def km_gorev_olustur():
    from flask import request as _req, session as _ses
    from db import get_conn as _gc
    import json as _json
    from datetime import datetime as _dt

    kullanici = _ses.get('kullanici') or {}
    olusturan = (kullanici.get('KullaniciAdi') or
                 kullanici.get('kullanici_adi') or 'sistem')

    body = _req.get_json(silent=True) or {}
    gh   = body.get('gorev_hazirlik') or body  # payload direkt veya sarılı

    # Validasyon
    if not gh.get('hazir'):
        return jsonify({"ok": False, "hata": "Görev hazır değil"}), 400
    konu = (gh.get('konu') or '').strip()
    if not konu:
        return jsonify({"ok": False, "hata": "Konu boş olamaz"}), 400

    sip_no   = gh.get('siparis_no') or ''
    proses   = gh.get('proses') or ''
    hedef    = gh.get('hedef_kisi') or ''
    ekip     = gh.get('hedef_ekip') or ''
    mesaj    = gh.get('mesaj') or ''
    oncelik  = gh.get('oncelik') or 'orta'
    risk     = int(gh.get('risk_skoru') or 0)
    musteri  = gh.get('musteri') or ''
    model    = gh.get('model') or ''
    satir_id = gh.get('satir_id') or ''

    # Oncelik map
    oncelik_map = {'dusuk':'dusuk','orta':'orta','yuksek':'yuksek','kritik':'kritik'}
    oncelik = oncelik_map.get(oncelik, 'orta')

    con = _gc()
    try:
        # Duplicate kontrol
        dup = con.execute("""
            SELECT id FROM tasks
            WHERE auto_source='karar_masasi'
              AND related_order_no=?
              AND baglam_id=?
              AND status NOT IN ('tamamlandi','iptal')
        """, (sip_no, satir_id)).fetchone()

        if dup:
            return jsonify({
                "ok": True,
                "task_id": dup[0],
                "duplicate": True,
                "mesaj": "Bu satır için zaten açık görev var"
            })

        now = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        baglam_ozet = f"{proses} +risk%{risk} | {mesaj[:80]}"

        con.execute("""
            INSERT INTO tasks
              (title, description, task_type, priority, status,
               created_by, assigned_to, department,
               related_order_no, related_model, related_customer,
               baglam_tipi, baglam_id, baglam_ozet,
               auto_source, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            konu, mesaj,
            'karar_masasi_mudahale', oncelik, 'bekliyor',
            olusturan, hedef, 'uretim',
            sip_no, model, musteri,
            'karar_masasi', satir_id, baglam_ozet,
            'karar_masasi', now, now
        ))
        con.commit()
        new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # bildirim_log INSERT — hedef kullanıcıya gorev_yeni bildirimi
        try:
            import json as _json2
            # tasks_users tablosundan kullanici_id bul
            tu = con.execute(
                "SELECT id, rol FROM tasks_users WHERE kullanici_adi=? AND aktif=1 LIMIT 1",
                (hedef,)
            ).fetchone()
            if tu:
                _bildirim_mesaj = "Yeni gorev: " + konu
                _bildirim_veri  = _json2.dumps({
                    "task_id":    new_id,
                    "title":      konu,
                    "priority":   oncelik,
                    "status":     "bekliyor",
                    "siparis_no": sip_no,
                    "proses":     proses,
                    "kaynak":     "karar_masasi"
                }, ensure_ascii=False)
                con.execute("""
                    INSERT INTO bildirim_log
                      (kullanici_id, rol, tip, mesaj, veri_json,
                       gonderim_zamani, okundu_mu, push_gonderildi_mi)
                    VALUES (?,?,?,?,?,?,0,0)
                """, (tu[0], tu[1], 'gorev_yeni',
                      _bildirim_mesaj, _bildirim_veri, _dt.now().strftime('%Y-%m-%d %H:%M:%S')))
                con.commit()
        except Exception as _be:
            pass  # bildirim hatası task'ı etkilemez

        return jsonify({
            "ok": True,
            "task_id": new_id,
            "duplicate": False,
            "mesaj": "Görev oluşturuldu (#" + str(new_id) + ")"
        })
    except Exception as e:
        con.rollback()
        import traceback
        return jsonify({"ok": False, "hata": str(e),
                        "tb": traceback.format_exc()}), 500
    finally:
        con.close()

# END FAZ43_SP5_GOREV
# ════════════════════════════════════════════════════════════════

# ============== FAZ 4.3 - USTAYA GONDER ==============

# Karar Masasi satirini usta_gorevleri tablosuna gonderir

# Hicbir mevcut sisteme dokunmaz, sadece SQLite



from flask import jsonify as _jsonify, request as _flask_request, session as _flask_session

from modules.usta import gorev_db as _gorev_db





@planlama_bp.route('/karar-masasi/ustaya-gonder', methods=['POST'])

@yetki_gerekli('planlama.karar_masasi', 'can_create')

def karar_masasi_ustaya_gonder():

    """

    Karar Masasi satirini usta_gorevleri tablosuna ekler.



    Body:

    {

        "satir_id": "MOCK_001",

        "atanan_usta": "Hasan" | "" (opsiyonel),

        "olusturan_notu": "Acil" (opsiyonel),

        "snapshot": {

            "siparis_no": "33680",       <- zorunlu

            "musteri": "Lc Waikiki",     <- zorunlu

            "model": "BRP-9000",         <- zorunlu

            "emir_no": "110626",

            "bant": "B-2",

            "kalan": 720,

            "uretilebilirlik": "HAZIR",

            "darbogaz_metin": "Temizleme +88%",

            "talimat": "Temizleme bandini bosalt",

            "musteri_etiketi": "NAKIT",

            "termin": "2026-05-31",

            "termin_durumu": "uzak",

            "skor": 75

        }

    }

    """

    # Login kontrolu

    kullanici = _flask_session.get('kullanici')

    if not kullanici:

        return _jsonify({

            "ok": False,

            "hata": "yetki_yok",

            "mesaj": "Login gerekli"

        }), 401



    olusturan_ad = (

        kullanici.get('AdSoyad') or

        kullanici.get('KullaniciAdi') or

        'bilinmeyen'

    )



    body = _flask_request.get_json(silent=True) or {}

    snapshot = body.get('snapshot') or {}



    # Snapshot validasyonu

    if not snapshot:

        return _jsonify({

            "ok": False,

            "hata": "snapshot_eksik",

            "mesaj": "snapshot alani zorunlu"

        }), 400



    # gorev_db.gorev_ekle icin payload hazirla

    payload = {

        "karar_masasi_satir_id": body.get('satir_id'),

        "siparis_no": snapshot.get('siparis_no'),

        "emir_no": snapshot.get('emir_no'),

        "musteri": snapshot.get('musteri'),

        "model": snapshot.get('model'),

        "bant": snapshot.get('bant'),

        "hedef_adet": snapshot.get('kalan') or 0,

        "kalan_adet": snapshot.get('kalan'),

        "uretilebilirlik": snapshot.get('uretilebilirlik'),

        "darbogaz": snapshot.get('darbogaz_metin'),

        "talimat": snapshot.get('talimat'),

        "oncelik": snapshot.get('skor') or 50,

        "musteri_etiketi": snapshot.get('musteri_etiketi'),

        "atanan_usta": body.get('atanan_usta'),

        "olusturan": olusturan_ad,

        "olusturan_notu": body.get('olusturan_notu'),

        "termin": snapshot.get('termin'),

        "termin_durumu": snapshot.get('termin_durumu'),

    }



    sonuc = _gorev_db.gorev_ekle(payload)



    if not sonuc.get("ok"):

        return _jsonify(sonuc), 400



    return _jsonify(sonuc)





# =============================================================================

# F9_5_1_OPERASYON_RAPORU_BEGIN

# F9.5.1 - OPERASYON RAPORU (BACKEND HESAP MOTORU)

# =============================================================================

# 4 yeni endpoint:

#   GET  /planlama/operasyon-raporu              (sayfa - F9.5.2'de doldurulacak)

#   GET  /planlama/api/operasyon/genel           (4 makine ozet)

#   GET  /planlama/api/operasyon/makine/<id>     (makine detay)

#   GET  /planlama/api/operasyon/event-timeline/<rapor_id>

# Kaynak: planlama/hesap.py (saf hesap motoru)



import sqlite3 as _f951_sqlite3

import os as _f951_os

from datetime import datetime as _f951_dt, timedelta as _f951_td

from flask import request as _f951_request, jsonify as _f951_jsonify



from modules.planlama.hesap import (

    vardiya_aralik as _f951_vardiya_aralik,

    rapor_aggregate as _f951_rapor_aggregate,

    olay_timeline_olustur as _f951_olay_timeline,

)





def _f951_db_path():

    """CPS standart DB yolu (enjeksiyon ile ayni pattern)"""

    base = _f951_os.path.dirname(_f951_os.path.dirname(_f951_os.path.dirname(_f951_os.path.abspath(__file__))))

    return _f951_os.path.join(base, "mock_data.db")





def _f951_simdi_vardiyasi():

    """Su anki saate gore aktif vardiya tahmini"""

    h = _f951_dt.now().hour

    if 7 <= h < 17:

        return "gunduz"

    return "gece"





def _f951_parse_filtre():

    """Query parametrelerini valide et"""

    tarih = _f951_request.args.get("tarih")

    vardiya = _f951_request.args.get("vardiya")

    

    if not tarih:

        tarih = _f951_dt.now().strftime("%Y-%m-%d")

    if not vardiya:

        vardiya = _f951_simdi_vardiyasi()

    

    # Validasyon

    try:

        tarih_dt = _f951_dt.strptime(tarih, "%Y-%m-%d")

    except ValueError:

        return None, None, "Tarih formati hatali (YYYY-MM-DD bekleniyor)"

    

    bugun = _f951_dt.now().date()

    if tarih_dt.date() > bugun + _f951_td(days=1):

        return None, None, "Gelecek tarih sorgulanamaz"

    if tarih_dt.date() < bugun - _f951_td(days=365):

        return None, None, "365 gunden eski tarih sorgulanamaz"

    

    if vardiya not in ("gunduz", "gece"):

        return None, None, "Gecersiz vardiya (gunduz/gece bekleniyor)"

    

    return tarih, vardiya, None





# -----------------------------------------------------------------------------

# Endpoint 1: SAYFA (placeholder - F9.5.2'de doldurulacak)

# -----------------------------------------------------------------------------

@planlama_bp.route("/operasyon-raporu", methods=["GET"])

@yetki_gerekli('planlama.operasyon_raporu', 'can_view')

def f951_operasyon_raporu_sayfa():

    """Operasyon raporu sayfasi (F9.5.2'de UI gelecek)"""

    if not yetki_var('planlama.operasyon_raporu', 'can_view'):

        return redirect(url_for("auth_bp.giris"))

    

    return render_template("planlama/operasyon_raporu.html")





# -----------------------------------------------------------------------------

# Endpoint 2: GENEL (4 makine ozet)

# -----------------------------------------------------------------------------

@planlama_bp.route("/api/operasyon/genel", methods=["GET"])

@yetki_gerekli('planlama.operasyon_raporu', 'can_view')

def f951_api_operasyon_genel():

    """4 makinenin ozet rapor verilerini doner"""

    

    tarih, vardiya, hata = _f951_parse_filtre()

    if hata:

        return _f951_jsonify({"ok": False, "hata": hata}), 400

    

    aralik = _f951_vardiya_aralik(tarih, vardiya)

    

    con = _f951_sqlite3.connect(_f951_db_path(), timeout=10)

    

    makineler = []

    for makine_id in [1, 2, 3, 4]:

        # Makine bilgisi

        cur = con.cursor()

        cur.execute("SELECT kod, ad, istasyon_sayisi FROM enj_makine WHERE id = ?", (makine_id,))

        mk = cur.fetchone()

        if not mk:

            continue

        m_kod, m_ad, ist_sayi = mk

        

        # Aggregate hesap

        agg = _f951_rapor_aggregate(con, makine_id, tarih, vardiya)

        

        if agg is None:

            # Rapor yok

            makineler.append({

                "makine_id": makine_id,

                "makine_kod": m_kod,

                "makine_ad": m_ad,

                "istasyon_sayisi": ist_sayi,

                "slot_sayisi": ist_sayi * 2,

                "rapor_id": None,

                "rapor_durum": "rapor_yok",

                "anlik_durum": None,

                "uretim": None,

                "saatlik": None,

                "olay_ozet": None,

                "korgun": None,

                "slot_dakika_dagilim": None,

                "uyarilar": [{

                    "kod": "RAPOR_YOK",

                    "seviye": "warning",

                    "mesaj": f"Bu makinede bugun {vardiya} vardiyasi icin rapor acilmamis"

                }],

            })

            continue

        

        # Slotlar detay degil ozet doner (kart icin)

        slotlar_detayli = agg.pop("slotlar", [])

        agg["makine_kod"] = m_kod

        agg["makine_ad"] = m_ad

        agg["istasyon_sayisi"] = ist_sayi

        agg["slot_sayisi"] = ist_sayi * 2

        agg["rapor_durum"] = "calisiyor"

        

        makineler.append(agg)

    

    con.close()

    

    return _f951_jsonify({

        "ok": True,

        "filtre": {

            "tarih": tarih,

            "vardiya": vardiya,

            "vardiya_baslangic": aralik["baslangic"].strftime("%H:%M"),

            "vardiya_bitis": aralik["bitis"].strftime("%H:%M"),

            "vardiya_sure_dk": aralik["sure_dk"],

            "vardiya_aktif": aralik["aktif_mi"],

            "vardiya_gecen_dk": aralik["gecen_dk"],

            "vardiya_kalan_dk": aralik["kalan_dk"],

        },

        "makineler": makineler,

        "olusturuldu": _f951_dt.now().strftime("%Y-%m-%d %H:%M:%S"),

    })





# -----------------------------------------------------------------------------

# Endpoint 3: MAKINE DETAY

# -----------------------------------------------------------------------------

@planlama_bp.route("/api/operasyon/makine/<int:makine_id>", methods=["GET"])

@yetki_gerekli('planlama.operasyon_raporu', 'can_view')

def f951_api_operasyon_makine(makine_id):

    """Tek makine icin detay rapor (slot grid + saatlik + olay)"""

    

    if makine_id not in (1, 2, 3, 4):

        return _f951_jsonify({"ok": False, "hata": "Gecersiz makine_id"}), 400

    

    tarih, vardiya, hata = _f951_parse_filtre()

    if hata:

        return _f951_jsonify({"ok": False, "hata": hata}), 400

    

    con = _f951_sqlite3.connect(_f951_db_path(), timeout=10)

    

    # Makine bilgisi

    cur = con.cursor()

    cur.execute("SELECT kod, ad, istasyon_sayisi FROM enj_makine WHERE id = ?", (makine_id,))

    mk = cur.fetchone()

    if not mk:

        con.close()

        return _f951_jsonify({"ok": False, "hata": "Makine bulunamadi"}), 404

    

    m_kod, m_ad, ist_sayi = mk

    

    # Aggregate

    agg = _f951_rapor_aggregate(con, makine_id, tarih, vardiya)

    

    if agg is None:

        con.close()

        return _f951_jsonify({

            "ok": True,

            "makine": {

                "makine_id": makine_id,

                "makine_kod": m_kod,

                "makine_ad": m_ad,

                "istasyon_sayisi": ist_sayi,

                "rapor_durum": "rapor_yok",

            },

            "uyarilar": [{

                "kod": "RAPOR_YOK",

                "seviye": "warning",

                "mesaj": "Bu makinede bu vardiya icin rapor acilmamis"

            }],

        })

    

    agg["makine_kod"] = m_kod

    agg["makine_ad"] = m_ad

    agg["istasyon_sayisi"] = ist_sayi

    

    con.close()

    

    return _f951_jsonify({

        "ok": True,

        "makine": agg,

        "olusturuldu": _f951_dt.now().strftime("%Y-%m-%d %H:%M:%S"),

    })





# -----------------------------------------------------------------------------

# Endpoint 4: EVENT TIMELINE

# -----------------------------------------------------------------------------

@planlama_bp.route("/api/operasyon/event-timeline/<int:rapor_id>", methods=["GET"])

@yetki_gerekli('planlama.operasyon_raporu', 'can_view')

def f951_api_event_timeline(rapor_id):

    """Bir raporun tum olaylarini kronolojik sirada doner"""

    

    limit = _f951_request.args.get("limit", 200, type=int)

    if limit > 500:

        limit = 500

    if limit < 1:

        limit = 200

    

    con = _f951_sqlite3.connect(_f951_db_path(), timeout=10)

    

    # Rapor var mi kontrol

    cur = con.cursor()

    cur.execute("SELECT id FROM enj_gunluk_rapor WHERE id = ?", (rapor_id,))

    if not cur.fetchone():

        con.close()

        return _f951_jsonify({"ok": False, "hata": "Rapor bulunamadi"}), 404

    

    olaylar = _f951_olay_timeline(con, rapor_id, limit=limit)

    con.close()

    

    return _f951_jsonify({

        "ok": True,

        "rapor_id": rapor_id,

        "olaylar": olaylar,

        "toplam": len(olaylar),

        "limit": limit,

    })





# =============================================================================

# F9_5_1_OPERASYON_RAPORU_END

# =============================================================================





# =============================================================================

# F9_5_2_OPERASYON_GECMIS_BEGIN

# F9.5.2 - OPERASYON RAPORU / GECMIS EXCEL DETAY (BACKEND ENDPOINT)

# =============================================================================

# Patch:    OP_RAPOR_V2_GECMIS

# Snapshot: STABLE_OP_RAPOR_V2_GECMIS_PRE_PATCH_20260515_153601

# Doku:     docs/OP_RAPOR_V2_GECMIS_SQL_v1.md

# Tarih:    2026-05-15

#

# 1 yeni endpoint:

#   GET  /planlama/api/operasyon/gecmis

#

# Bu blok bagimsiz. F9.5.1 endpoint'leri ve CANLI ekran dokunulmaz.

# Helper prefix: _f9_5_2_ (F9.5.1'in _f951_ prefixinden ayri)





def _f9_5_2_parse_params():

    """GECMIS endpoint icin query parametrelerini parse + validate eder.

    Donus: (params_dict, hata_str_or_None)

    """

    r = _f951_request

    p = {}



    tarih_bas = (r.args.get('tarih_bas') or '').strip()

    tarih_bit = (r.args.get('tarih_bit') or '').strip()

    if not tarih_bas:

        return None, 'tarih_bas zorunlu (YYYY-MM-DD)'

    if not tarih_bit:

        return None, 'tarih_bit zorunlu (YYYY-MM-DD)'

    try:

        d1 = _f951_dt.strptime(tarih_bas, '%Y-%m-%d')

        d2 = _f951_dt.strptime(tarih_bit, '%Y-%m-%d')

    except Exception:

        return None, 'tarih formati YYYY-MM-DD olmali'

    if d2 < d1:

        return None, 'tarih_bit, tarih_bas tan kucuk olamaz'

    p['tarih_bas'] = tarih_bas

    p['tarih_bit'] = tarih_bit



    def _opt(key, allowed=None, as_int=False):

        v = r.args.get(key)

        if v is None or v == '':

            return None

        v = v.strip()

        if as_int:

            try:

                return int(v)

            except Exception:

                return None

        if allowed and v not in allowed:

            return None

        return v



    p['makine_id']  = _opt('makine_id', as_int=True)

    p['operator']   = _opt('operator')

    p['kalip_tipi'] = _opt('kalip_tipi', allowed={'GOVDE', 'ATKI'})

    p['vardiya']    = _opt('vardiya', allowed={'gunduz', 'mesai', 'gece'})

    p['durum']      = _opt('durum', allowed={'CLS', 'KLP', 'ARZ', 'KPL'})

    p['arama']      = _opt('arama')



    try:

        sayfa = int(r.args.get('sayfa', 1))

        if sayfa < 1:

            sayfa = 1

    except Exception:

        sayfa = 1

    try:

        boyut = int(r.args.get('boyut', 50))

        if boyut < 1:

            boyut = 50

        if boyut > 250:

            boyut = 250

    except Exception:

        boyut = 50

    p['sayfa']  = sayfa

    p['boyut']  = boyut

    p['offset'] = (sayfa - 1) * boyut



    return p, None





def _f9_5_2_sn_to_hhmmss(sn):

    """Saniye -> HH:MM:SS string."""

    if sn is None:

        return None

    sn = int(sn)

    h, rem = divmod(sn, 3600)

    m, s = divmod(rem, 60)

    return '{:02d}:{:02d}:{:02d}'.format(h, m, s)





def _f9_5_2_anomali_label(seviye):

    if seviye == 1:

        return 'Uzun sureli (2sa+)'

    if seviye == 2:

        return 'ANOMALI (4sa+)'

    return None





def _f9_5_2_gosterim_not(sebep_ad, notu):

    if sebep_ad and notu:

        return sebep_ad + ' . ' + notu

    if sebep_ad:

        return sebep_ad

    if notu:

        return notu

    return '-'





def _f9_5_2_sql_with():

    return '''

WITH

saatlik_olaylar AS (

  SELECT

    'TUR'                                          AS satir_tipi,

    sk.id                                          AS satir_id,

    gr.tarih                                       AS tarih,

    sk.saat_baslangic || '-' || sk.saat_bitis      AS saat_araligi,

    sk.saat_baslangic                              AS sirala_zaman,

    m.kod                                          AS makine_kod,

    NULL                                           AS istasyon_label,

    gr.kullanici_adi                               AS operator,

    gr.vardiya                                     AS vardiya,

    k.kalip_kod                                    AS kalip_kod,

    NULL                                           AS kalip_kod_eski,

    k.kalip_tipi                                   AS kalip_tipi,

    sk.tur_adet                                    AS tur,

    (sk.tur_adet * COALESCE(gr.teorik_cift_tur,0)) AS teorik_cift,

    NULL                                           AS net_cift,

    NULL                                           AS fire,

    NULL                                           AS verim_yuzde,

    0                                              AS ariza_saniye,

    0                                              AS kalip_degisim_saniye,

    UPPER(COALESCE(sk.durum, 'CALISIYOR'))         AS durum_ham,

    sk.aciklama                                    AS not_aciklama,

    NULL                                           AS sebep_ad,

    NULL                                           AS sebep_detay,

    sk.rapor_id                                    AS rapor_id,

    0                                              AS anomali_seviye

  FROM enj_saatlik_kayit sk

  JOIN enj_gunluk_rapor  gr ON gr.id = sk.rapor_id

  JOIN enj_makine        m  ON m.id  = gr.makine_id

  LEFT JOIN enj_kalip    k  ON k.id  = gr.kalip_id

),

ariza_olaylar AS (

  SELECT

    'ARIZA'                                        AS satir_tipi,

    e.id                                           AS satir_id,

    e.tarih                                        AS tarih,

    strftime('%H:%M', s.zaman) || '-' ||

      strftime('%H:%M', e.zaman)                   AS saat_araligi,

    strftime('%H:%M', s.zaman)                     AS sirala_zaman,

    m.kod                                          AS makine_kod,

    m.kod || '-' || isd.istasyon_no || isd.slot    AS istasyon_label,

    e.kullanici_adi                                AS operator,

    e.vardiya                                      AS vardiya,

    k.kalip_kod                                    AS kalip_kod,

    NULL                                           AS kalip_kod_eski,

    k.kalip_tipi                                   AS kalip_tipi,

    NULL AS tur, NULL AS teorik_cift, NULL AS net_cift,

    NULL AS fire, NULL AS verim_yuzde,

    CAST((julianday(e.zaman) - julianday(s.zaman)) * 86400 AS INTEGER)

                                                   AS ariza_saniye,

    0                                              AS kalip_degisim_saniye,

    'ARIZA'                                        AS durum_ham,

    json_extract(s.meta_json, '$.tetik_detay.ariza_sebep_detay') AS not_aciklama,

    asb.ad                                         AS sebep_ad,

    json_extract(s.meta_json, '$.tetik_detay.ariza_sebep')       AS sebep_detay,

    e.rapor_id                                     AS rapor_id,

    CASE

      WHEN (julianday(e.zaman) - julianday(s.zaman)) * 86400 >= 14400 THEN 2

      WHEN (julianday(e.zaman) - julianday(s.zaman)) * 86400 >=  7200 THEN 1

      ELSE 0

    END                                            AS anomali_seviye

  FROM enj_event_log e

  JOIN enj_event_log s

    ON s.rapor_id    = e.rapor_id

   AND s.istasyon_id = e.istasyon_id

   AND s.event_group = 'ARIZA'

   AND s.event_type  = 'ARIZA_START'

   AND s.zaman       < e.zaman

   AND s.id = (

     SELECT MAX(s2.id) FROM enj_event_log s2

     WHERE s2.rapor_id    = e.rapor_id

       AND s2.istasyon_id = e.istasyon_id

       AND s2.event_group = 'ARIZA'

       AND s2.event_type  = 'ARIZA_START'

       AND s2.zaman       < e.zaman

   )

  JOIN enj_makine                m   ON m.id   = e.makine_id

  LEFT JOIN enj_istasyon_durumu  isd ON isd.id = e.istasyon_id

  LEFT JOIN enj_kalip            k   ON k.id   = isd.kalip_id

  LEFT JOIN enj_aksama_sebep     asb ON asb.id =

    CAST(json_extract(s.meta_json, '$.tetik_detay.aksama_sebep_id') AS INTEGER)

  WHERE e.event_group = 'ARIZA' AND e.event_type = 'ARIZA_END'

),

setup_olaylar AS (

  SELECT

    'SETUP'                                        AS satir_tipi,

    e.id                                           AS satir_id,

    e.tarih                                        AS tarih,

    strftime('%H:%M', s.zaman) || '-' ||

      strftime('%H:%M', e.zaman)                   AS saat_araligi,

    strftime('%H:%M', s.zaman)                     AS sirala_zaman,

    m.kod                                          AS makine_kod,

    m.kod || '-' || isd.istasyon_no || isd.slot    AS istasyon_label,

    e.kullanici_adi                                AS operator,

    e.vardiya                                      AS vardiya,

    k_yeni.kalip_kod                               AS kalip_kod,

    k_eski.kalip_kod                               AS kalip_kod_eski,

    COALESCE(k_yeni.kalip_tipi, k_eski.kalip_tipi) AS kalip_tipi,

    NULL AS tur, NULL AS teorik_cift, NULL AS net_cift,

    NULL AS fire, NULL AS verim_yuzde,

    0                                              AS ariza_saniye,

    CAST((julianday(e.zaman) - julianday(s.zaman)) * 86400 AS INTEGER)

                                                   AS kalip_degisim_saniye,

    'SETUP'                                        AS durum_ham,

    'Kalip degisim'                                AS not_aciklama,

    NULL                                           AS sebep_ad,

    NULL                                           AS sebep_detay,

    e.rapor_id                                     AS rapor_id,

    CASE

      WHEN (julianday(e.zaman) - julianday(s.zaman)) * 86400 >= 14400 THEN 2

      WHEN (julianday(e.zaman) - julianday(s.zaman)) * 86400 >=  7200 THEN 1

      ELSE 0

    END                                            AS anomali_seviye

  FROM enj_event_log e

  JOIN enj_event_log s

    ON s.rapor_id    = e.rapor_id

   AND s.istasyon_id = e.istasyon_id

   AND s.event_group = 'SETUP'

   AND s.event_type  = 'SETUP_START'

   AND s.zaman       < e.zaman

   AND s.id = (

     SELECT MAX(s2.id) FROM enj_event_log s2

     WHERE s2.rapor_id    = e.rapor_id

       AND s2.istasyon_id = e.istasyon_id

       AND s2.event_group = 'SETUP'

       AND s2.event_type  = 'SETUP_START'

       AND s2.zaman       < e.zaman

   )

  JOIN enj_makine                m       ON m.id      = e.makine_id

  LEFT JOIN enj_istasyon_durumu  isd     ON isd.id    = e.istasyon_id

  LEFT JOIN enj_kalip            k_eski  ON k_eski.id = isd.setup_kalip_id_eski

  LEFT JOIN enj_kalip            k_yeni  ON k_yeni.id = isd.setup_kalip_id_yeni

  WHERE e.event_group = 'SETUP' AND e.event_type = 'SETUP_END'

),

foto_haritasi AS (

  SELECT rapor_id, 1 AS foto_var FROM enj_foto GROUP BY rapor_id

),

olaylar AS (

  SELECT o.*, COALESCE(fh.foto_var, 0) AS foto_var

  FROM (

    SELECT * FROM saatlik_olaylar

    UNION ALL

    SELECT * FROM ariza_olaylar

    UNION ALL

    SELECT * FROM setup_olaylar

  ) o

  LEFT JOIN foto_haritasi fh ON fh.rapor_id = o.rapor_id

)

'''





def _f9_5_2_sql_where():

    return '''

WHERE tarih BETWEEN :tarih_bas AND :tarih_bit

  AND (:makine_id  IS NULL OR makine_kod IN (

        SELECT kod FROM enj_makine WHERE id = :makine_id))

  AND (:operator   IS NULL OR operator   = :operator)

  AND (:kalip_tipi IS NULL OR kalip_tipi = :kalip_tipi)

  AND (:vardiya    IS NULL OR vardiya    = :vardiya)

  AND (:durum IS NULL OR (

       (:durum = 'CLS' AND durum_ham = 'CALISIYOR')

    OR (:durum = 'KLP' AND durum_ham = 'SETUP')

    OR (:durum = 'ARZ' AND durum_ham = 'ARIZA')

    OR (:durum = 'KPL' AND durum_ham = 'KAPALI')

  ))

  AND (:arama IS NULL OR

       makine_kod   LIKE '%' || :arama || '%' OR

       kalip_kod    LIKE '%' || :arama || '%' OR

       operator     LIKE '%' || :arama || '%' OR

       not_aciklama LIKE '%' || :arama || '%' OR

       sebep_ad     LIKE '%' || :arama || '%')

'''





@planlama_bp.route('/api/operasyon/gecmis', methods=['GET'])

@yetki_gerekli('planlama.operasyon_raporu', 'can_view')

def f9_5_2_api_operasyon_gecmis():

    """Operasyon Raporu - GECMIS / EXCEL DETAY sekmesi.

    Tur + Ariza + Setup olaylarinin tek listede birlestirilmis hali.

    Server-side filtre + pagination + KPI ozet.

    """



    p, hata = _f9_5_2_parse_params()

    if hata:

        return _f951_jsonify({'ok': False, 'hata': hata}), 400



    con = _f951_sqlite3.connect(_f951_db_path(), timeout=30)

    con.row_factory = _f951_sqlite3.Row

    cur = con.cursor()



    cte   = _f9_5_2_sql_with()

    where = _f9_5_2_sql_where()



    bind = {

        'tarih_bas':  p['tarih_bas'],

        'tarih_bit':  p['tarih_bit'],

        'makine_id':  p['makine_id'],

        'operator':   p['operator'],

        'kalip_tipi': p['kalip_tipi'],

        'vardiya':    p['vardiya'],

        'durum':      p['durum'],

        'arama':      p['arama'],

    }



    sql_count = cte + ' SELECT COUNT(*) AS adet FROM olaylar ' + where

    cur.execute(sql_count, bind)

    toplam_kayit = cur.fetchone()['adet'] or 0

    toplam_sayfa = (toplam_kayit + p['boyut'] - 1) // p['boyut'] if toplam_kayit > 0 else 0



    sql_dagilim = cte + ' SELECT satir_tipi, COUNT(*) AS adet FROM olaylar ' + where + ' GROUP BY satir_tipi'

    cur.execute(sql_dagilim, bind)

    tip_dagilimi = {'tur': 0, 'ariza': 0, 'setup': 0}

    for row in cur.fetchall():

        st = (row['satir_tipi'] or '').upper()

        if st == 'TUR':

            tip_dagilimi['tur'] = row['adet']

        elif st == 'ARIZA':

            tip_dagilimi['ariza'] = row['adet']

        elif st == 'SETUP':

            tip_dagilimi['setup'] = row['adet']



    sql_kpi = cte + '''

SELECT

  SUM(CASE WHEN satir_tipi='TUR' THEN tur         ELSE 0 END) AS toplam_tur,

  SUM(CASE WHEN satir_tipi='TUR' THEN teorik_cift ELSE 0 END) AS toplam_teorik,

  (SELECT SUM(net_cikan_cift)   FROM enj_gunluk_rapor

     WHERE tarih BETWEEN :tarih_bas AND :tarih_bit) AS toplam_net,

  (SELECT SUM(toplam_fire_cift) FROM enj_gunluk_rapor

     WHERE tarih BETWEEN :tarih_bas AND :tarih_bit) AS toplam_fire,

  SUM(ariza_saniye)         AS toplam_ariza_sn,

  SUM(kalip_degisim_saniye) AS toplam_kalip_dgs_sn

FROM olaylar ''' + where

    cur.execute(sql_kpi, bind)

    kpi_row = cur.fetchone()

    toplam_tur          = kpi_row['toplam_tur']          or 0

    toplam_teorik       = kpi_row['toplam_teorik']       or 0

    toplam_net          = kpi_row['toplam_net']          or 0

    toplam_fire         = kpi_row['toplam_fire']         or 0

    toplam_ariza_sn     = kpi_row['toplam_ariza_sn']     or 0

    toplam_kalip_dgs_sn = kpi_row['toplam_kalip_dgs_sn'] or 0



    verim = 0.0

    if toplam_teorik > 0:

        verim = round(100.0 - (toplam_fire / toplam_teorik * 100.0), 2)



    kpi = {

        'toplam_tur':              int(toplam_tur),

        'teorik_cift':             int(toplam_teorik),

        'net_cift':                int(toplam_net),

        'fire':                    int(toplam_fire),

        'ortalama_verim_yuzde':    verim,

        'toplam_ariza_sn':         int(toplam_ariza_sn),

        'toplam_ariza_hhmmss':     _f9_5_2_sn_to_hhmmss(toplam_ariza_sn) or '00:00:00',

        'toplam_kalip_degisim_sn': int(toplam_kalip_dgs_sn),

        'toplam_kalip_degisim_hhmmss': _f9_5_2_sn_to_hhmmss(toplam_kalip_dgs_sn) or '00:00:00',

    }



    sql_liste = cte + ' SELECT * FROM olaylar ' + where + ' ORDER BY tarih DESC, sirala_zaman DESC LIMIT :boyut OFFSET :offset'

    bind_liste = dict(bind)

    bind_liste['boyut']  = p['boyut']

    bind_liste['offset'] = p['offset']

    cur.execute(sql_liste, bind_liste)



    durum_map = {'CALISIYOR': 'CLS', 'SETUP': 'KLP', 'ARIZA': 'ARZ', 'KAPALI': 'KPL', 'DURUS': 'DRS'}

    satirlar = []

    for r in cur.fetchall():

        d = dict(r)

        durum_label = durum_map.get((d.get('durum_ham') or '').upper(), d.get('durum_ham'))

        sebep_ad = d.get('sebep_ad')

        notu     = d.get('not_aciklama')

        ariza_sn = d.get('ariza_saniye') if d.get('ariza_saniye') else None

        kalip_sn = d.get('kalip_degisim_saniye') if d.get('kalip_degisim_saniye') else None

        satirlar.append({

            'satir_tipi':   d.get('satir_tipi'),

            'satir_id':     d.get('satir_id'),

            'tarih':        d.get('tarih'),

            'saat_araligi': d.get('saat_araligi'),

            'makine':       d.get('makine_kod'),

            'istasyon':     d.get('istasyon_label'),

            'operator':     d.get('operator'),

            'vardiya':      d.get('vardiya'),

            'kalip': {

                'kod':      d.get('kalip_kod'),

                'kod_eski': d.get('kalip_kod_eski'),

                'tipi':     d.get('kalip_tipi'),

            },

            'tur':         d.get('tur'),

            'teorik_cift': d.get('teorik_cift'),

            'net_cift':    d.get('net_cift'),

            'fire':        d.get('fire'),

            'verim_yuzde': d.get('verim_yuzde'),

            'ariza_sn':             ariza_sn,

            'ariza_hhmmss':         _f9_5_2_sn_to_hhmmss(ariza_sn),

            'kalip_degisim_sn':     kalip_sn,

            'kalip_degisim_hhmmss': _f9_5_2_sn_to_hhmmss(kalip_sn),

            'durum':        durum_label,

            'durum_label':  durum_label,

            'sebep_ad':     sebep_ad,

            'sebep_detay':  d.get('sebep_detay'),

            'not':          notu,

            'gosterim_not': _f9_5_2_gosterim_not(sebep_ad, notu),

            'foto_var':     bool(d.get('foto_var') or 0),

            'anomali_seviye': d.get('anomali_seviye') or 0,

            'anomali_label':  _f9_5_2_anomali_label(d.get('anomali_seviye') or 0),

        })



    con.close()



    return _f951_jsonify({

        'ok': True,

        'filtreler': {

            'tarih_bas':  p['tarih_bas'],

            'tarih_bit':  p['tarih_bit'],

            'makine_id':  p['makine_id'],

            'operator':   p['operator'],

            'kalip_tipi': p['kalip_tipi'],

            'vardiya':    p['vardiya'],

            'durum':      p['durum'],

            'arama':      p['arama'],

            'sayfa':      p['sayfa'],

            'boyut':      p['boyut'],

        },

        'sayfalama': {

            'toplam_kayit': int(toplam_kayit),

            'toplam_sayfa': int(toplam_sayfa),

            'sayfa':        p['sayfa'],

            'boyut':        p['boyut'],

        },

        'tip_dagilimi': tip_dagilimi,

        'kpi': kpi,

        'satirlar': satirlar,

        'olusturuldu': _f951_dt.now().strftime('%Y-%m-%d %H:%M:%S'),

    })





# =============================================================================

# F9_5_2_OPERASYON_GECMIS_END

# =============================================================================

