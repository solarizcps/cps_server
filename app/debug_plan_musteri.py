# -*- coding: utf-8 -*-
"""
debug_plan_musteri.py
---------------------
PLAN ekraninda musteri alani neden "-" geliyor?
3 farkli noktadan teshis - kod yazma yok, dosya degistirme yok.

Cikti net olsun, hangi adimda nerede sorun var bulmak icin.
"""
import sys
import os
import json

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CPS_ROOT = r"C:\cps_dev"
sys.path.insert(0, CPS_ROOT)


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# ===========================================================
section("1) get_emir_ozet(110626) - cari_adi geliyor mu?")
# ===========================================================
try:
    from modules.common import korgun as _kk
    ozet = _kk.get_emir_ozet(110626)
    print("Donen tum alanlar:")
    print(json.dumps(ozet, indent=2, default=str, ensure_ascii=False))
    print()
    print(f"  ozet.get('cari_adi'): {ozet.get('cari_adi')!r}")
    print(f"  ozet.get('musteri'):  {ozet.get('musteri')!r}")
    print(f"  ozet.get('siparisler'): {len(ozet.get('siparisler',[]) or [])} satir")
    sips = ozet.get('siparisler', []) or []
    for s in sips[:3]:
        print(f"    -> sip_no={s.get('sip_no')}, cari_adi={s.get('cari_adi')!r}")
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ===========================================================
section("2) Siparis_Kay + Cari_Kart JOIN - 33558 ve 33638 icin")
# ===========================================================
try:
    from modules.common import korgun as _kk
    con = _kk._baglan()
    cur = con.cursor()
    cur.execute("""
        SELECT sk.SipNo, sk.CariKod, ck.CKod, ck.CName
          FROM Siparis_Kay sk
          LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
         WHERE sk.SipNo IN (33558, 33638)
    """)
    rows = cur.fetchall()
    print(f"Satir sayisi: {len(rows)}")
    for r in rows:
        print(f"  SipNo={r[0]}, sk.CariKod={r[1]!r}, ck.CKod={r[2]!r}, ck.CName={r[3]!r}")

    # Alternatif: Siparis_Har'a baglanip kontrol
    print()
    print("Alternatif: Siparis_Har -> Siparis_Kay -> Cari_Kart")
    cur.execute("""
        SELECT DISTINCT
            sh.SipNo,
            sh.SKOD,
            sk.CariKod,
            ISNULL(ck.CName, '-') AS CariAdi
          FROM Siparis_Har sh
          LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
          LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
         WHERE sh.SKOD = 'CRX-71033-LCW'
           AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
    """)
    rows2 = cur.fetchall()
    print(f"Satir sayisi: {len(rows2)}")
    for r in rows2[:5]:
        print(f"  SipNo={r[0]}, SKOD={r[1]}, CariKod={r[2]!r}, CariAdi={r[3]!r}")

    cur.close()
    con.close()
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ===========================================================
section("3) /hedef/plan endpoint manuel SQL - PLAN_ZENGIN_V1 batch")
# ===========================================================
# routes.py'da kullanilan batch SQL'i aynen calistir, donen MusteriAdi'na bak
try:
    from modules.common import korgun as _kk
    con = _kk._baglan()
    cur = con.cursor()
    emir_listesi = [110626]
    placeholders = ','.join(['%s'] * len(emir_listesi))
    cur.execute(f"""
        SELECT
            e.EmirNo,
            e.ModelKod,
            (SELECT TOP 1 ck.CName
               FROM Siparis_Har sh3 WITH(NOLOCK)
               LEFT JOIN Siparis_Kay sk3 ON sk3.SipNo = sh3.SipNo
               LEFT JOIN Cari_Kart ck ON ck.CKod = sk3.CariKod
              WHERE sh3.SKOD = e.ModelKod
                AND LTRIM(RTRIM(ISNULL(sh3.Durum,''))) = '') AS MusteriAdi
          FROM Urt_Emir e WITH(NOLOCK)
         WHERE e.EmirNo IN ({placeholders})
    """, tuple(emir_listesi))
    rows = cur.fetchall()
    print("Routes.py'daki batch SQL'in MusteriAdi sutununu kopyaladik:")
    for r in rows:
        print(f"  EmirNo={r[0]}, ModelKod={r[1]!r}, MusteriAdi={r[2]!r}")
    cur.close()
    con.close()
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ===========================================================
section("4) /hedef/plan HTTP endpoint - canli yanit")
# ===========================================================
print("Bu adim PowerShell'den manuel calistirilacak (login session gerekiyor):")
print()
print("Browser console'da:")
print("  fetch('/hedef/plan',{credentials:'include'})")
print("    .then(r=>r.json())")
print("    .then(d=>{")
print("      var e = (d.emirler||[]).find(x=>String(x.emir_no)==='110626');")
print("      if(e) console.table([{")
print("        emir_no: e.emir_no,")
print("        musteri: e.musteri,")
print("        cari_adi: e.cari_adi,")
print("        siparisler: e.siparisler,")
print("        keys: Object.keys(e).join(',')")
print("      }]);")
print("      else console.log('110626 yok');")
print("    })")


# ===========================================================
section("5) get_siparis_emirleri(33558) - alternatif yol")
# ===========================================================
try:
    from modules.common import korgun as _kk
    sip = _kk.get_siparis_emirleri(33558)
    print(f"ok={sip.get('ok')}, emir_sayisi={sip.get('emir_sayisi')}")
    print(f"siparis_toplam={sip.get('siparis_toplam')}")
    if sip.get('emirler'):
        ana = [e for e in sip['emirler'] if e.get('EmirTip') == 'ana']
        for e in ana[:3]:
            print(f"  EmirNo={e['EmirNo']}, CariAdi={e.get('CariAdi')!r}, ModelKod={e.get('ModelKod')!r}")
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ===========================================================
section("OZET - SORUN HARITAS\u0130")
# ===========================================================
print("""
  Beklenen sonuc:
  - Bolum 1: ozet['cari_adi'] = 'Lc Waikiki' (boyle ise sorun yok, frontend'e bakmamiz lazim)
  - Bolum 2: SipNo 33558 ve 33638 icin CariAdi = 'Lc Waikiki' (varsa baglanti dogru)
  - Bolum 3: routes.py'in MusteriAdi sutunu = 'Lc Waikiki' (boyle ise frontend'e bak)
            = None ise routes.py SQL'i hatali

  Sorunlar:
  A) Bolum 1 None doner -> get_emir_ozet musteri vermiyor
     COZUM: routes.py icinde ozet'ten cari_adi kullan
  B) Bolum 2 dolu ama Bolum 3 None -> routes.py'daki batch SQL bozuk
     COZUM: routes.py SQL'i duzelt
  C) Bolum 3 dolu, frontend "-" gosteriyor -> frontend bind hatasi
     COZUM: Frontend incelenmeli (ama kullanici kurali: frontend dokunma)

  Ek alternatif:
  - Bolum 5 get_siparis_emirleri zaten musteri donduruyor, oradan da alabiliriz
""")
