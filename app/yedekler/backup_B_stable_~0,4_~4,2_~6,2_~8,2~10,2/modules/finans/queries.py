# -*- coding: utf-8 -*-
"""
CPS DEV - Finans v2 Queries
Yeni şema:
  finans_anlasma
  finans_anlasma_model
  finans_avans + finans_avans_mahsup
  finans_odeme_plan + finans_odeme_cek
"""
from db import q, qone, qscalar, qexec, get_conn
from datetime import datetime, timedelta
from modules import audit


# ============================================================
# KPI (dashboard için)
# ============================================================

def kpi_toplam_alacak():
    return qscalar("SELECT COALESCE(SUM(Borc - Alacak), 0) FROM Cari_Har WHERE CKod IN (SELECT CKod FROM Cari_Kart WHERE CTip IN (1, 3))") or 0

def kpi_toplam_borc():
    return qscalar("SELECT COALESCE(SUM(Alacak - Borc), 0) FROM Cari_Har WHERE CKod IN (SELECT CKod FROM Cari_Kart WHERE CTip IN (2, 3))") or 0

def kpi_banka_toplam():
    return qscalar("SELECT COALESCE(SUM(Bakiye), 0) FROM Banka_Kart WHERE Aktif = 1 AND Doviz = 'TL'") or 0

def kpi_kasa_toplam():
    return qscalar("SELECT COALESCE(SUM(Bakiye), 0) FROM Kasa_Kart") or 0

def kpi_vadesi_yaklasan_cek(gun=30):
    bugun = datetime.now().date()
    son = (bugun + timedelta(days=gun)).strftime('%Y-%m-%d')
    return qscalar("""
        SELECT COALESCE(SUM(Tutar), 0) FROM Cek_Senet
        WHERE Durum = 'PORTFOY' AND VadeTarih <= ? AND VadeTarih >= ?
    """, (son, bugun.strftime('%Y-%m-%d'))) or 0

def kpi_son_30_gun_ozet():
    bas = (datetime.now().date() - timedelta(days=30)).strftime('%Y-%m-%d')
    g  = qscalar("SELECT COALESCE(SUM(Alacak), 0) FROM Cari_Har WHERE Tarih >= ?", (bas,)) or 0
    gi = qscalar("SELECT COALESCE(SUM(Borc), 0) FROM Cari_Har WHERE Tarih >= ?", (bas,)) or 0
    return {'gelir': g, 'gider': gi, 'net': g - gi}


# ============================================================
# ANLAŞMA (v2)
# ============================================================

def anlasma_liste(durum=None):
    """
    Anlaşma listesi. Her anlaşma için:
      - toplam miktar (modellerden sum)
      - avans toplamı
      - mahsup edilmiş avans
      - ödeme planı toplamı
      - tahsil edilen plan
    """
    rows = q("""
        SELECT a.Id, a.ProjeKod, a.ProjeAdi, a.CKod, a.BaslangicTarih, a.BitisTarih,
               a.ToplamTutar, a.KdvOrani, a.Durum, a.Notlar, a.OlusturmaTarih,
               c.CName,
               COALESCE((SELECT SUM(Miktar) FROM finans_anlasma_model WHERE AnlasmaId = a.Id), 0) AS ToplamMiktar,
               COALESCE((SELECT COUNT(*) FROM finans_anlasma_model WHERE AnlasmaId = a.Id), 0) AS ModelSayi,
               COALESCE((SELECT SUM(Tutar) FROM finans_avans WHERE AnlasmaId = a.Id), 0) AS AvansToplam,
               COALESCE((SELECT SUM(m.GerceklesenTutar) FROM finans_avans_mahsup m
                         JOIN finans_avans av ON av.Id = m.AvansId
                         WHERE av.AnlasmaId = a.Id AND m.Durum = 'MAHSUP_EDILDI'), 0) AS MahsupEdilen,
               COALESCE((SELECT SUM(Tutar) FROM finans_odeme_plan WHERE AnlasmaId = a.Id), 0) AS PlanToplam,
               COALESCE((SELECT SUM(Tutar) FROM finans_odeme_plan WHERE AnlasmaId = a.Id AND Durum = 'GELDI'), 0) AS TahsilEdilen,
               (SELECT COUNT(*) FROM finans_odeme_plan WHERE AnlasmaId = a.Id) AS PlanSatirSayi,
               (SELECT COUNT(*) FROM finans_odeme_plan WHERE AnlasmaId = a.Id AND Durum = 'GELDI') AS GeldiSayi
        FROM finans_anlasma a
        LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
        {where}
        ORDER BY a.BaslangicTarih DESC
    """.format(where="WHERE a.Durum = ?" if durum else ""),
    (durum,) if durum else ())

    for r in rows:
        r['Kalan'] = (r['ToplamTutar'] or 0) - (r['TahsilEdilen'] or 0) - (r['MahsupEdilen'] or 0)
        r['KalanAvans'] = (r['AvansToplam'] or 0) - (r['MahsupEdilen'] or 0)
    return rows


def anlasma_detay(anlasma_id):
    r = qone("""
        SELECT a.*, c.CName, c.Sehir
        FROM finans_anlasma a
        LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
        WHERE a.Id = ?
    """, (anlasma_id,))
    return r


def anlasma_modelleri(anlasma_id):
    return q("""
        SELECT Id, Sira, ModelKod, ModelAdi, Renk, Miktar, BirimFiyat, Notu
        FROM finans_anlasma_model
        WHERE AnlasmaId = ?
        ORDER BY Sira, Id
    """, (anlasma_id,))


def anlasma_avanslari(anlasma_id):
    """Avanslar + her avansın altındaki mahsup satırları."""
    avanslar = q("""
        SELECT Id, AvansTarih, Tutar, OdemeTipi, TeminatMektup,
               TeminatTutar, TeminatNotu, Aciklama
        FROM finans_avans
        WHERE AnlasmaId = ?
        ORDER BY AvansTarih, Id
    """, (anlasma_id,))
    for av in avanslar:
        av['mahsuplar'] = q("""
            SELECT Id, Sira, MahsupTarih, Tutar, GerceklesenTutar,
                   GerceklesenTarih, Durum, Aciklama
            FROM finans_avans_mahsup
            WHERE AvansId = ?
            ORDER BY Sira, MahsupTarih
        """, (av['Id'],))
        av['mahsup_toplam']      = sum((m['Tutar'] or 0) for m in av['mahsuplar'])
        av['mahsup_edilen']      = sum((m['GerceklesenTutar'] or 0) for m in av['mahsuplar'] if m['Durum'] == 'MAHSUP_EDILDI')
        av['mahsup_kalan']       = av['Tutar'] - av['mahsup_edilen']
    return avanslar


def anlasma_odeme_plani(anlasma_id):
    """Ödeme planı satırları + çek batch'leri. Efektif durum (gecikmiş) dahil."""
    bugun = datetime.now().date().strftime('%Y-%m-%d')
    rows = q("""
        SELECT p.Id, p.ModelId, p.Sira, p.PlanTarih, p.OdemeTipi, p.Tutar, p.CekAdeti,
               p.GerceklesenTutar, p.GerceklesenTarih, p.Durum, p.Aciklama, p.CariHarId,
               m.ModelAdi, m.Renk, m.ModelKod
        FROM finans_odeme_plan p
        LEFT JOIN finans_anlasma_model m ON m.Id = p.ModelId
        WHERE p.AnlasmaId = ?
        ORDER BY p.Sira, p.PlanTarih
    """, (anlasma_id,))
    for r in rows:
        # Efektif durum (gecikme)
        if r['Durum'] == 'BEKLIYOR' and r['PlanTarih'] and r['PlanTarih'] < bugun:
            r['EfektifDurum'] = 'GECIKMIS'
        else:
            r['EfektifDurum'] = r['Durum']
        # Çek batch
        r['cekler'] = []
        if r['OdemeTipi'] == 'CEK':
            r['cekler'] = q("""
                SELECT Id, CekSira, CekNo, CekBanka, CekAlimTarih, CekVadeTarih,
                       Tutar, Durum, TahsilTarih, Notu
                FROM finans_odeme_cek
                WHERE OdemePlanId = ?
                ORDER BY CekSira, CekVadeTarih
            """, (r['Id'],))
    return rows


def anlasma_ozet_kartlar(anlasma_id):
    """6 KPI kartı için hesaplar (detay sayfasında)."""
    a = anlasma_detay(anlasma_id)
    if not a:
        return None
    toplam = a['ToplamTutar'] or 0

    avans_top = qscalar("SELECT COALESCE(SUM(Tutar),0) FROM finans_avans WHERE AnlasmaId = ?", (anlasma_id,)) or 0
    mahsup_ed = qscalar("""
        SELECT COALESCE(SUM(m.GerceklesenTutar),0)
        FROM finans_avans_mahsup m JOIN finans_avans a ON a.Id = m.AvansId
        WHERE a.AnlasmaId = ? AND m.Durum = 'MAHSUP_EDILDI'
    """, (anlasma_id,)) or 0
    mahsup_pl = qscalar("""
        SELECT COALESCE(SUM(m.Tutar),0)
        FROM finans_avans_mahsup m JOIN finans_avans a ON a.Id = m.AvansId
        WHERE a.AnlasmaId = ?
    """, (anlasma_id,)) or 0

    plan_top   = qscalar("SELECT COALESCE(SUM(Tutar),0) FROM finans_odeme_plan WHERE AnlasmaId = ?", (anlasma_id,)) or 0
    tahsil     = qscalar("SELECT COALESCE(SUM(Tutar),0) FROM finans_odeme_plan WHERE AnlasmaId = ? AND Durum = 'GELDI'", (anlasma_id,)) or 0

    return {
        'toplam':          toplam,
        'avans_alinan':    avans_top,
        'avans_mahsup_edilen': mahsup_ed,
        'avans_kalan':     avans_top - mahsup_ed,
        'avans_plan':      mahsup_pl,
        'plan_toplam':     plan_top,
        'tahsil_edilen':   tahsil,
        'kalan':           toplam - tahsil - mahsup_ed,
        'net_plan_hedef':  toplam - avans_top,  # ödeme planı bu kadar olmalı
    }


def anlasma_kpi():
    """Anlaşma listesi üstünde KPI kartları."""
    aktif = qscalar("SELECT COUNT(*) FROM finans_anlasma WHERE Durum = 'AKTIF'") or 0
    portfoy = qscalar("""
        SELECT COALESCE(SUM(ToplamTutar),0) FROM finans_anlasma WHERE Durum = 'AKTIF'
    """) or 0
    tahsil_toplam = qscalar("""
        SELECT COALESCE(SUM(p.Tutar), 0)
        FROM finans_odeme_plan p JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        WHERE a.Durum = 'AKTIF' AND p.Durum = 'GELDI'
    """) or 0
    kalan = portfoy - tahsil_toplam

    bugun = datetime.now().date()
    bu_ay_son = (bugun.replace(day=1) + timedelta(days=32)).replace(day=1).strftime('%Y-%m-%d')
    bu_ay_beklenen = qscalar("""
        SELECT COALESCE(SUM(Tutar), 0)
        FROM finans_odeme_plan p JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        WHERE a.Durum = 'AKTIF' AND p.Durum = 'BEKLIYOR'
          AND p.PlanTarih <= ? AND p.PlanTarih >= ?
    """, (bu_ay_son, bugun.strftime('%Y-%m-%d'))) or 0

    geciken_tutar = qscalar("""
        SELECT COALESCE(SUM(Tutar), 0)
        FROM finans_odeme_plan p JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        WHERE a.Durum = 'AKTIF' AND p.Durum = 'BEKLIYOR' AND p.PlanTarih < ?
    """, (bugun.strftime('%Y-%m-%d'),)) or 0
    geciken_adet = qscalar("""
        SELECT COUNT(*)
        FROM finans_odeme_plan p JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        WHERE a.Durum = 'AKTIF' AND p.Durum = 'BEKLIYOR' AND p.PlanTarih < ?
    """, (bugun.strftime('%Y-%m-%d'),)) or 0

    return {
        'aktif': aktif,
        'portfoy': portfoy,
        'kalan': kalan,
        'bu_ay_beklenen': bu_ay_beklenen,
        'geciken_tutar': geciken_tutar,
        'geciken_adet': geciken_adet,
    }


# ============================================================
# GECİKEN ÖDEMELER — detaylı liste (PARÇA 8a D maddesi)
# ============================================================

def geciken_odeme_liste():
    """
    Bugünden önce vadesi geçmiş, durumu BEKLİYOR ve anlaşması AKTİF olan
    ödeme planı satırları. En eski vade üstte.
    Dashboard'daki 'geciken_adet' / 'geciken_tutar' sayacı ile aynı mantık.
    """
    from datetime import datetime as _dt
    bugun = _dt.now().strftime('%Y-%m-%d')
    return q("""
        SELECT p.Id            AS PlanId,
               p.AnlasmaId,
               p.PlanTarih,
               p.OdemeTipi,
               p.Tutar,
               p.CekAdeti,
               p.Aciklama,
               p.Durum          AS PlanDurum,
               a.ProjeKod,
               a.ProjeAdi,
               a.CKod,
               a.Durum          AS AnlasmaDurum,
               c.CName          AS MusteriAd,
               (julianday(?) - julianday(p.PlanTarih)) AS GecikmeGun
        FROM finans_odeme_plan p
        JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
        WHERE a.Durum = 'AKTIF'
          AND p.Durum = 'BEKLIYOR'
          AND p.PlanTarih < ?
        ORDER BY p.PlanTarih ASC
    """, (bugun, bugun))


# ============================================================
# DASHBOARD — Yaklaşan ödemeler + yaklaşan mahsuplar
# ============================================================

def yaklasan_odemeler(gun=30):
    """Önümüzdeki N gün içinde beklenen ödeme planı satırları (+ gecikmişler)."""
    bugun = datetime.now().date()
    son = (bugun + timedelta(days=gun)).strftime('%Y-%m-%d')
    return q("""
        SELECT p.Id, p.AnlasmaId, p.PlanTarih, p.OdemeTipi, p.Tutar, p.CekAdeti,
               p.Aciklama, p.Durum,
               a.ProjeKod, a.ProjeAdi, a.CKod,
               c.CName
        FROM finans_odeme_plan p
        JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
        WHERE p.Durum = 'BEKLIYOR'
          AND a.Durum = 'AKTIF'
          AND p.PlanTarih <= ?
        ORDER BY p.PlanTarih ASC
    """, (son,))


def yaklasan_mahsuplar(gun=30):
    """Önümüzdeki N gün içinde beklenen avans mahsupları."""
    bugun = datetime.now().date()
    son = (bugun + timedelta(days=gun)).strftime('%Y-%m-%d')
    return q("""
        SELECT m.Id, m.AvansId, m.MahsupTarih, m.Tutar, m.Aciklama, m.Durum,
               av.AnlasmaId,
               a.ProjeKod, a.ProjeAdi, a.CKod,
               c.CName
        FROM finans_avans_mahsup m
        JOIN finans_avans av ON av.Id = m.AvansId
        JOIN finans_anlasma a ON a.Id = av.AnlasmaId
        LEFT JOIN Cari_Kart c ON c.CKod = a.CKod
        WHERE m.Durum = 'BEKLIYOR'
          AND a.Durum = 'AKTIF'
          AND m.MahsupTarih <= ?
        ORDER BY m.MahsupTarih ASC
    """, (son,))


# ============================================================
# CARİ (mevcut, değişmeden)
# ============================================================

def musteri_listesi():
    return q("""
        SELECT CKod, CName, Sehir, CTip, Bakiye
        FROM Cari_Kart WHERE CTip IN (1, 3) AND Aktif = 1 ORDER BY CName
    """)

def cari_listesi(tip=None):
    if tip == 'musteri':
        where = "CTip IN (1, 3)"
    elif tip == 'tedarikci':
        where = "CTip IN (2, 3)"
    else:
        where = "1=1"
    return q(f"""
        SELECT CKod, CName, CTip, Sehir, Telefon, Bakiye
        FROM Cari_Kart WHERE {where} AND Aktif = 1 ORDER BY CName
    """)

def cari_detay(ckod):
    return qone("SELECT * FROM Cari_Kart WHERE CKod = ?", (ckod,))

def cari_ozet(ckod):
    """Cari detay sayfası için KPI özetleri."""
    r = qone("""
        SELECT
            COUNT(*) AS HareketSayisi,
            COALESCE(SUM(Borc), 0) AS ToplamBorc,
            COALESCE(SUM(Alacak), 0) AS ToplamAlacak,
            COALESCE(SUM(Borc - Alacak), 0) AS Bakiye,
            MIN(Tarih) AS IlkIslem,
            MAX(Tarih) AS SonIslem
        FROM Cari_Har WHERE CKod = ?
    """, (ckod,))
    if r:
        r['ToplamBorc']   = r.get('ToplamBorc') or 0
        r['ToplamAlacak'] = r.get('ToplamAlacak') or 0
        r['Bakiye']       = r.get('Bakiye') or 0
    return r

def cari_hareketler(ckod, bas_tarih=None, bit_tarih=None):
    where = "CKod = ?"
    params = [ckod]
    if bas_tarih:
        where += " AND Tarih >= ?"; params.append(bas_tarih)
    if bit_tarih:
        where += " AND Tarih <= ?"; params.append(bit_tarih)
    # Ters sırada al, running balance hesapla, tekrar DESC sırala
    rows = q(f"""
        SELECT * FROM Cari_Har WHERE {where}
        ORDER BY Tarih ASC, Id ASC
    """, tuple(params))
    bakiye = 0
    for r in rows:
        bakiye += (r.get('Borc') or 0) - (r.get('Alacak') or 0)
        r['Bakiye'] = bakiye
    rows.reverse()  # Yeni tarihli en üstte
    return rows

def cari_anlasmalari(ckod):
    return q("""
        SELECT a.Id, a.ProjeKod, a.ProjeAdi, a.BaslangicTarih, a.BitisTarih,
               a.ToplamTutar, a.Durum,
               COALESCE((SELECT SUM(Tutar) FROM finans_odeme_plan
                         WHERE AnlasmaId = a.Id AND Durum = 'GELDI'), 0) AS TahsilEdilen
        FROM finans_anlasma a
        WHERE a.CKod = ?
        ORDER BY a.BaslangicTarih DESC
    """, (ckod,))


# ============================================================
# ANLAŞMA YAZMA (create/update/durum)
# ============================================================

def anlasma_olustur(veri, modeller, avanslar, plan_satirlari, kullanici='sistem'):
    """
    veri: dict(ProjeKod, ProjeAdi, CKod, BaslangicTarih, BitisTarih, ToplamTutar, KdvOrani, Notlar)
    modeller: [dict(ModelKod, ModelAdi, Renk, Miktar, BirimFiyat, Notu)]
    avanslar: [dict(AvansTarih, Tutar, OdemeTipi, TeminatMektup, TeminatTutar, TeminatNotu, Aciklama,
                    mahsuplar: [dict(MahsupTarih, Tutar, Aciklama)])]
    plan_satirlari: [dict(PlanTarih, OdemeTipi, Tutar, CekAdeti, ModelSira, Aciklama,
                          cekler: [dict(CekNo, CekBanka, CekAlimTarih, CekVadeTarih, Tutar, Notu)])]
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO finans_anlasma
              (ProjeKod, ProjeAdi, CKod, BaslangicTarih, BitisTarih, ToplamTutar, KdvOrani,
               Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'AKTIF', ?, ?, ?)
        """, (
            veri['ProjeKod'], veri['ProjeAdi'], veri['CKod'],
            veri.get('BaslangicTarih'), veri.get('BitisTarih'),
            float(veri.get('ToplamTutar') or 0),
            float(veri.get('KdvOrani') or 10),
            veri.get('Notlar'),
            datetime.now().date().strftime('%Y-%m-%d'),
            kullanici,
        ))
        anlasma_id = cur.lastrowid

        # Modeller
        model_id_by_sira = {}
        for i, m in enumerate(modeller, 1):
            cur.execute("""
                INSERT INTO finans_anlasma_model
                  (AnlasmaId, Sira, ModelKod, ModelAdi, Renk, Miktar, BirimFiyat, Notu)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                anlasma_id, i,
                m.get('ModelKod') or None, m['ModelAdi'],
                m.get('Renk') or None,
                int(m.get('Miktar') or 0),
                float(m.get('BirimFiyat') or 0),
                m.get('Notu') or None,
            ))
            model_id_by_sira[i] = cur.lastrowid

        # Avanslar + mahsuplar
        for av in avanslar:
            cur.execute("""
                INSERT INTO finans_avans
                  (AnlasmaId, AvansTarih, Tutar, OdemeTipi, TeminatMektup, TeminatTutar, TeminatNotu, Aciklama)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                anlasma_id, av['AvansTarih'], float(av.get('Tutar') or 0),
                av.get('OdemeTipi', 'HAVALE'),
                1 if av.get('TeminatMektup') else 0,
                float(av.get('TeminatTutar') or 0),
                av.get('TeminatNotu'),
                av.get('Aciklama'),
            ))
            av_id = cur.lastrowid

            # Cari_Har'a avans kaydı
            cur.execute("""
                INSERT INTO Cari_Har (CKod, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak)
                VALUES (?, ?, ?, 'AVANS', ?, 0, ?)
            """, (veri['CKod'], av['AvansTarih'], f"AV{av_id:04d}",
                  f"{veri['ProjeKod']} - Ön avans",
                  float(av.get('Tutar') or 0)))

            for j, mh in enumerate(av.get('mahsuplar') or [], 1):
                cur.execute("""
                    INSERT INTO finans_avans_mahsup
                      (AvansId, Sira, MahsupTarih, Tutar, Durum, Aciklama)
                    VALUES (?, ?, ?, ?, 'BEKLIYOR', ?)
                """, (av_id, j, mh['MahsupTarih'], float(mh.get('Tutar') or 0), mh.get('Aciklama')))

        # Ödeme plan satırları + çekler
        for i, p in enumerate(plan_satirlari, 1):
            mid = model_id_by_sira.get(int(p.get('ModelSira') or 0))
            cur.execute("""
                INSERT INTO finans_odeme_plan
                  (AnlasmaId, ModelId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?)
            """, (
                anlasma_id, mid, i,
                p['PlanTarih'], p['OdemeTipi'],
                float(p.get('Tutar') or 0),
                int(p.get('CekAdeti') or 1),
                p.get('Aciklama'),
            ))
            plan_id = cur.lastrowid

            # Çek batch
            for k, c in enumerate(p.get('cekler') or [], 1):
                cur.execute("""
                    INSERT INTO finans_odeme_cek
                      (OdemePlanId, CekSira, CekNo, CekBanka, CekAlimTarih, CekVadeTarih, Tutar, Durum, Notu)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?)
                """, (plan_id, k, c.get('CekNo'), c.get('CekBanka'),
                      c.get('CekAlimTarih'), c.get('CekVadeTarih'),
                      float(c.get('Tutar') or 0), c.get('Notu')))

        conn.commit()

        # AUDIT
        audit.log_ekle(kullanici, 'finans_anlasma', anlasma_id, anlasma_id=anlasma_id,
                       aciklama=f"Anlaşma oluşturuldu: {veri['ProjeKod']} — {veri['ProjeAdi']} ({float(veri.get('ToplamTutar') or 0):,.0f} ₺)")
        if modeller:
            audit.log(kullanici, 'EKLE', 'finans_anlasma_model', 0, anlasma_id=anlasma_id,
                      aciklama=f"{len(modeller)} model eklendi")
        if avanslar:
            top_av = sum(float(a.get('Tutar') or 0) for a in avanslar)
            audit.log(kullanici, 'EKLE', 'finans_avans', 0, anlasma_id=anlasma_id,
                      aciklama=f"{len(avanslar)} avans eklendi (toplam {top_av:,.0f} ₺)")
        if plan_satirlari:
            top_pl = sum(float(p.get('Tutar') or 0) for p in plan_satirlari)
            audit.log(kullanici, 'EKLE', 'finans_odeme_plan', 0, anlasma_id=anlasma_id,
                      aciklama=f"{len(plan_satirlari)} ödeme planı satırı eklendi (toplam {top_pl:,.0f} ₺)")

        return anlasma_id
    finally:
        conn.close()


def anlasma_guncelle(anlasma_id, veri, modeller, avanslar, plan_satirlari, kullanici='sistem'):
    """
    Mevcut anlaşmayı günceller. Modeller / Avanslar / Plan için:
    - Id'si olanlar güncellenir
    - Id'si olmayanlar yeni eklenir
    - Formda gelmeyen (silinmiş) kayıtlar silinir
    Ödenmiş taksitler ve tahsil edilmiş çekler değiştirilemez.
    """
    eski_anl = qone("SELECT * FROM finans_anlasma WHERE Id = ?", (anlasma_id,))
    if not eski_anl:
        raise ValueError(f"Anlaşma bulunamadı: {anlasma_id}")

    conn = get_conn()
    try:
        cur = conn.cursor()

        # 1) Ana bilgiler
        yeni_anl = {
            'ProjeKod':       veri.get('ProjeKod'),
            'ProjeAdi':       veri.get('ProjeAdi'),
            'CKod':           veri.get('CKod'),
            'BaslangicTarih': veri.get('BaslangicTarih') or None,
            'BitisTarih':     veri.get('BitisTarih') or None,
            'ToplamTutar':    float(veri.get('ToplamTutar') or 0),
            'KdvOrani':       float(veri.get('KdvOrani') or 10),
            'Notlar':         veri.get('Notlar') or None,
        }
        cur.execute("""
            UPDATE finans_anlasma SET
                ProjeKod=?, ProjeAdi=?, CKod=?, BaslangicTarih=?, BitisTarih=?,
                ToplamTutar=?, KdvOrani=?, Notlar=?,
                SonDuzenleyen=?, SonDuzenlemeTarih=?
            WHERE Id=?
        """, (yeni_anl['ProjeKod'], yeni_anl['ProjeAdi'], yeni_anl['CKod'],
              yeni_anl['BaslangicTarih'], yeni_anl['BitisTarih'],
              yeni_anl['ToplamTutar'], yeni_anl['KdvOrani'], yeni_anl['Notlar'],
              kullanici, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              anlasma_id))
        eski_alan = {k: eski_anl[k] for k in yeni_anl.keys()}
        audit.log_duzenle_coklu(kullanici, 'finans_anlasma', anlasma_id, eski_alan, yeni_anl, anlasma_id=anlasma_id, conn=conn)

        # 2) MODELLER
        eski_modeller = {m['Id']: dict(m) for m in q("SELECT * FROM finans_anlasma_model WHERE AnlasmaId=?", (anlasma_id,))}
        gelen_ids = set()
        model_id_by_sira = {}

        for i, m in enumerate(modeller, 1):
            mid = int(m.get('Id') or 0)
            yeni_m = {
                'Sira': i, 'ModelKod': m.get('ModelKod') or None,
                'ModelAdi': m.get('ModelAdi'), 'Renk': m.get('Renk') or None,
                'Miktar': int(m.get('Miktar') or 0),
                'BirimFiyat': float(m.get('BirimFiyat') or 0),
                'Notu': m.get('Notu') or None,
            }
            if mid and mid in eski_modeller:
                gelen_ids.add(mid)
                cur.execute("""
                    UPDATE finans_anlasma_model SET Sira=?, ModelKod=?, ModelAdi=?, Renk=?, Miktar=?, BirimFiyat=?, Notu=?
                    WHERE Id=?
                """, (yeni_m['Sira'], yeni_m['ModelKod'], yeni_m['ModelAdi'], yeni_m['Renk'],
                      yeni_m['Miktar'], yeni_m['BirimFiyat'], yeni_m['Notu'], mid))
                audit.log_duzenle_coklu(kullanici, 'finans_anlasma_model', mid,
                                        {k: eski_modeller[mid].get(k) for k in yeni_m}, yeni_m,
                                        anlasma_id=anlasma_id, conn=conn)
                model_id_by_sira[i] = mid
            else:
                cur.execute("""
                    INSERT INTO finans_anlasma_model (AnlasmaId, Sira, ModelKod, ModelAdi, Renk, Miktar, BirimFiyat, Notu)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (anlasma_id, yeni_m['Sira'], yeni_m['ModelKod'], yeni_m['ModelAdi'],
                      yeni_m['Renk'], yeni_m['Miktar'], yeni_m['BirimFiyat'], yeni_m['Notu']))
                new_id = cur.lastrowid
                model_id_by_sira[i] = new_id
                audit.log_ekle(kullanici, 'finans_anlasma_model', new_id, anlasma_id=anlasma_id,
                               aciklama=f"Model eklendi: {yeni_m['ModelAdi']} / {yeni_m['Renk'] or '—'} × {yeni_m['Miktar']}", conn=conn)

        for eski_id, eski_m in eski_modeller.items():
            if eski_id not in gelen_ids:
                cur.execute("DELETE FROM finans_anlasma_model WHERE Id=?", (eski_id,))
                audit.log_sil(kullanici, 'finans_anlasma_model', eski_id, anlasma_id=anlasma_id,
                              aciklama=f"Model silindi: {eski_m['ModelAdi']}", conn=conn)

        # 3) AVANSLAR + MAHSUPLAR
        eski_avanslar = {a['Id']: dict(a) for a in q("SELECT * FROM finans_avans WHERE AnlasmaId=?", (anlasma_id,))}
        gelen_av_ids = set()

        for av in avanslar:
            av_id = int(av.get('Id') or 0)
            yeni_av = {
                'AvansTarih':    av.get('AvansTarih'),
                'Tutar':         float(av.get('Tutar') or 0),
                'OdemeTipi':     av.get('OdemeTipi', 'HAVALE'),
                'TeminatMektup': 1 if av.get('TeminatMektup') else 0,
                'TeminatTutar':  float(av.get('TeminatTutar') or 0),
                'TeminatNotu':   av.get('TeminatNotu'),
                'Aciklama':      av.get('Aciklama'),
            }
            if av_id and av_id in eski_avanslar:
                gelen_av_ids.add(av_id)
                cur.execute("""
                    UPDATE finans_avans SET
                        AvansTarih=?, Tutar=?, OdemeTipi=?, TeminatMektup=?,
                        TeminatTutar=?, TeminatNotu=?, Aciklama=?
                    WHERE Id=?
                """, (yeni_av['AvansTarih'], yeni_av['Tutar'], yeni_av['OdemeTipi'],
                      yeni_av['TeminatMektup'], yeni_av['TeminatTutar'],
                      yeni_av['TeminatNotu'], yeni_av['Aciklama'], av_id))
                audit.log_duzenle_coklu(kullanici, 'finans_avans', av_id,
                                        {k: eski_avanslar[av_id].get(k) for k in yeni_av}, yeni_av,
                                        anlasma_id=anlasma_id, conn=conn)
            else:
                cur.execute("""
                    INSERT INTO finans_avans
                      (AnlasmaId, AvansTarih, Tutar, OdemeTipi, TeminatMektup, TeminatTutar, TeminatNotu, Aciklama)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (anlasma_id, yeni_av['AvansTarih'], yeni_av['Tutar'], yeni_av['OdemeTipi'],
                      yeni_av['TeminatMektup'], yeni_av['TeminatTutar'],
                      yeni_av['TeminatNotu'], yeni_av['Aciklama']))
                av_id = cur.lastrowid
                audit.log_ekle(kullanici, 'finans_avans', av_id, anlasma_id=anlasma_id,
                               aciklama=f"Avans eklendi: {yeni_av['Tutar']:,.0f} ₺ ({yeni_av['AvansTarih']}, conn=conn)")

            # Mahsuplar
            eski_mhs = {m['Id']: dict(m) for m in q("SELECT * FROM finans_avans_mahsup WHERE AvansId=?", (av_id,))}
            gelen_mh_ids = set()
            for j, mh in enumerate(av.get('mahsuplar') or [], 1):
                mh_id = int(mh.get('Id') or 0)
                yeni_mh = {
                    'Sira': j, 'MahsupTarih': mh.get('MahsupTarih'),
                    'Tutar': float(mh.get('Tutar') or 0),
                    'Aciklama': mh.get('Aciklama') or None,
                }
                if mh_id and mh_id in eski_mhs:
                    if eski_mhs[mh_id].get('Durum') == 'MAHSUP_EDILDI':
                        continue  # gerçekleşmiş mahsup değişmez
                    gelen_mh_ids.add(mh_id)
                    cur.execute("""
                        UPDATE finans_avans_mahsup SET Sira=?, MahsupTarih=?, Tutar=?, Aciklama=?
                        WHERE Id=?
                    """, (yeni_mh['Sira'], yeni_mh['MahsupTarih'], yeni_mh['Tutar'],
                          yeni_mh['Aciklama'], mh_id))
                    audit.log_duzenle_coklu(kullanici, 'finans_avans_mahsup', mh_id,
                                            {k: eski_mhs[mh_id].get(k) for k in yeni_mh}, yeni_mh,
                                            anlasma_id=anlasma_id, conn=conn)
                else:
                    cur.execute("""
                        INSERT INTO finans_avans_mahsup (AvansId, Sira, MahsupTarih, Tutar, Durum, Aciklama)
                        VALUES (?,?,?,?,'BEKLIYOR',?)
                    """, (av_id, yeni_mh['Sira'], yeni_mh['MahsupTarih'], yeni_mh['Tutar'], yeni_mh['Aciklama']))
                    new_mh_id = cur.lastrowid
                    audit.log_ekle(kullanici, 'finans_avans_mahsup', new_mh_id, anlasma_id=anlasma_id,
                                   aciklama=f"Mahsup eklendi: {yeni_mh['Tutar']:,.0f} ₺ ({yeni_mh['MahsupTarih']}, conn=conn)")

            for e_id, e in eski_mhs.items():
                if e_id not in gelen_mh_ids and e.get('Durum') != 'MAHSUP_EDILDI':
                    cur.execute("DELETE FROM finans_avans_mahsup WHERE Id=?", (e_id,))
                    audit.log_sil(kullanici, 'finans_avans_mahsup', e_id, anlasma_id=anlasma_id,
                                  aciklama=f"Mahsup silindi: {e.get('Tutar', 0):,.0f} ₺", conn=conn)

        for e_id, e in eski_avanslar.items():
            if e_id not in gelen_av_ids:
                cur.execute("DELETE FROM finans_avans WHERE Id=?", (e_id,))
                audit.log_sil(kullanici, 'finans_avans', e_id, anlasma_id=anlasma_id,
                              aciklama=f"Avans silindi: {e.get('Tutar', 0):,.0f} ₺", conn=conn)

        # 4) ÖDEME PLANI + ÇEKLER
        eski_plan = {p['Id']: dict(p) for p in q("SELECT * FROM finans_odeme_plan WHERE AnlasmaId=?", (anlasma_id,))}
        gelen_pl_ids = set()

        for i, p in enumerate(plan_satirlari, 1):
            pl_id = int(p.get('Id') or 0)
            mid = model_id_by_sira.get(int(p.get('ModelSira') or 0)) if p.get('ModelSira') else None
            yeni_pl = {
                'ModelId': mid, 'Sira': i,
                'PlanTarih': p.get('PlanTarih'), 'OdemeTipi': p.get('OdemeTipi'),
                'Tutar': float(p.get('Tutar') or 0),
                'CekAdeti': int(p.get('CekAdeti') or 1),
                'Aciklama': p.get('Aciklama') or None,
            }
            if pl_id and pl_id in eski_plan:
                if eski_plan[pl_id]['Durum'] == 'GELDI':
                    # Tahsil edilmiş satırın tutarı/tarihi değişmez
                    yeni_pl['Tutar']     = eski_plan[pl_id]['Tutar']
                    yeni_pl['PlanTarih'] = eski_plan[pl_id]['PlanTarih']
                    yeni_pl['OdemeTipi'] = eski_plan[pl_id]['OdemeTipi']
                gelen_pl_ids.add(pl_id)
                cur.execute("""
                    UPDATE finans_odeme_plan SET ModelId=?, Sira=?, PlanTarih=?, OdemeTipi=?, Tutar=?, CekAdeti=?, Aciklama=?
                    WHERE Id=?
                """, (yeni_pl['ModelId'], yeni_pl['Sira'], yeni_pl['PlanTarih'], yeni_pl['OdemeTipi'],
                      yeni_pl['Tutar'], yeni_pl['CekAdeti'], yeni_pl['Aciklama'], pl_id))
                audit.log_duzenle_coklu(kullanici, 'finans_odeme_plan', pl_id,
                                        {k: eski_plan[pl_id].get(k) for k in yeni_pl}, yeni_pl,
                                        anlasma_id=anlasma_id, conn=conn)
            else:
                cur.execute("""
                    INSERT INTO finans_odeme_plan
                      (AnlasmaId, ModelId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?)
                """, (anlasma_id, yeni_pl['ModelId'], yeni_pl['Sira'], yeni_pl['PlanTarih'],
                      yeni_pl['OdemeTipi'], yeni_pl['Tutar'], yeni_pl['CekAdeti'], yeni_pl['Aciklama']))
                pl_id = cur.lastrowid
                audit.log_ekle(kullanici, 'finans_odeme_plan', pl_id, anlasma_id=anlasma_id,
                               aciklama=f"Plan satırı eklendi: {yeni_pl['OdemeTipi']} {yeni_pl['Tutar']:,.0f} ₺ ({yeni_pl['PlanTarih']}, conn=conn)")

            # Çekler
            eski_cekler = {c['Id']: dict(c) for c in q("SELECT * FROM finans_odeme_cek WHERE OdemePlanId=?", (pl_id,))}
            gelen_c_ids = set()
            for k, c in enumerate(p.get('cekler') or [], 1):
                c_id = int(c.get('Id') or 0)
                yeni_c = {
                    'CekSira': k, 'CekNo': c.get('CekNo'),
                    'CekBanka': c.get('CekBanka'),
                    'CekAlimTarih': c.get('CekAlimTarih'),
                    'CekVadeTarih': c.get('CekVadeTarih'),
                    'Tutar': float(c.get('Tutar') or 0),
                    'Notu': c.get('Notu'),
                }
                if c_id and c_id in eski_cekler:
                    if eski_cekler[c_id].get('Durum') == 'TAHSIL':
                        gelen_c_ids.add(c_id)
                        continue
                    gelen_c_ids.add(c_id)
                    cur.execute("""
                        UPDATE finans_odeme_cek SET CekSira=?, CekNo=?, CekBanka=?, CekAlimTarih=?, CekVadeTarih=?, Tutar=?, Notu=?
                        WHERE Id=?
                    """, (yeni_c['CekSira'], yeni_c['CekNo'], yeni_c['CekBanka'], yeni_c['CekAlimTarih'],
                          yeni_c['CekVadeTarih'], yeni_c['Tutar'], yeni_c['Notu'], c_id))
                    audit.log_duzenle_coklu(kullanici, 'finans_odeme_cek', c_id,
                                            {k2: eski_cekler[c_id].get(k2) for k2 in yeni_c}, yeni_c,
                                            anlasma_id=anlasma_id, conn=conn)
                else:
                    cur.execute("""
                        INSERT INTO finans_odeme_cek
                          (OdemePlanId, CekSira, CekNo, CekBanka, CekAlimTarih, CekVadeTarih, Tutar, Durum, Notu)
                        VALUES (?,?,?,?,?,?,?,'BEKLIYOR',?)
                    """, (pl_id, yeni_c['CekSira'], yeni_c['CekNo'], yeni_c['CekBanka'],
                          yeni_c['CekAlimTarih'], yeni_c['CekVadeTarih'], yeni_c['Tutar'], yeni_c['Notu']))
                    new_c_id = cur.lastrowid
                    audit.log_ekle(kullanici, 'finans_odeme_cek', new_c_id, anlasma_id=anlasma_id,
                                   aciklama=f"Çek eklendi: {yeni_c.get('CekBanka') or ''} no {yeni_c.get('CekNo') or '—'} / {yeni_c['Tutar']:,.0f} ₺", conn=conn)

            for e_id, e in eski_cekler.items():
                if e_id not in gelen_c_ids and e.get('Durum') != 'TAHSIL':
                    cur.execute("DELETE FROM finans_odeme_cek WHERE Id=?", (e_id,))
                    audit.log_sil(kullanici, 'finans_odeme_cek', e_id, anlasma_id=anlasma_id,
                                  aciklama=f"Çek silindi: {e.get('CekNo') or '—'}", conn=conn)

        for e_id, e in eski_plan.items():
            if e_id not in gelen_pl_ids and e.get('Durum') != 'GELDI':
                cur.execute("DELETE FROM finans_odeme_plan WHERE Id=?", (e_id,))
                audit.log_sil(kullanici, 'finans_odeme_plan', e_id, anlasma_id=anlasma_id,
                              aciklama=f"Plan satırı silindi: {e.get('OdemeTipi')} {e.get('Tutar', 0):,.0f} ₺", conn=conn)

        conn.commit()
        return anlasma_id
    finally:
        conn.close()


def anlasma_durum_guncelle(anlasma_id, yeni_durum, kullanici='sistem'):
    eski = qscalar("SELECT Durum FROM finans_anlasma WHERE Id = ?", (anlasma_id,))
    qexec("""
        UPDATE finans_anlasma SET Durum = ?, SonDuzenleyen = ?, SonDuzenlemeTarih = ?
        WHERE Id = ?
    """, (yeni_durum, kullanici, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), anlasma_id))
    audit.log(kullanici, 'DURUM', 'finans_anlasma', anlasma_id, anlasma_id=anlasma_id,
              alan='Durum', eski=eski, yeni=yeni_durum,
              aciklama=f"Durum değişti: {eski} → {yeni_durum}")
    return True


def odeme_plan_gerceklesti(plan_id, gerc_tarih, gerc_tutar, kullanici='sistem'):
    """Plan satırını GELDI yapar + Cari_Har kaydı düşer + tüm satırlar GELDI ise anlaşmayı TAMAMLANDI yapar."""
    p = qone("""
        SELECT p.*, a.ProjeKod, a.CKod
        FROM finans_odeme_plan p JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        WHERE p.Id = ?
    """, (plan_id,))
    if not p or p['Durum'] == 'GELDI':
        return False

    qexec("""
        INSERT INTO Cari_Har (CKod, Tarih, BelgeNo, BelgeTip, Aciklama, Borc, Alacak)
        VALUES (?, ?, ?, 'TAHSILAT', ?, 0, ?)
    """, (p['CKod'], gerc_tarih, f"OP{plan_id:04d}",
          f"{p['ProjeKod']} - {p.get('Aciklama') or p['OdemeTipi']}", gerc_tutar))
    cari_har_id = qscalar("SELECT last_insert_rowid()")

    qexec("""
        UPDATE finans_odeme_plan
        SET Durum = 'GELDI', GerceklesenTarih = ?, GerceklesenTutar = ?, CariHarId = ?
        WHERE Id = ?
    """, (gerc_tarih, gerc_tutar, cari_har_id, plan_id))

    audit.log(kullanici, 'ODEME_GELDI', 'finans_odeme_plan', plan_id,
              anlasma_id=p['AnlasmaId'],
              aciklama=f"Ödeme tahsil edildi: {gerc_tutar:,.0f} ₺ ({gerc_tarih}) — {p.get('Aciklama') or p['OdemeTipi']}")

    # Tamamlandı kontrolü
    kalan = qscalar("""
        SELECT COUNT(*) FROM finans_odeme_plan
        WHERE AnlasmaId = ? AND Durum != 'GELDI'
    """, (p['AnlasmaId'],)) or 0
    kalan_mahsup = qscalar("""
        SELECT COUNT(*) FROM finans_avans_mahsup m
        JOIN finans_avans av ON av.Id = m.AvansId
        WHERE av.AnlasmaId = ? AND m.Durum = 'BEKLIYOR'
    """, (p['AnlasmaId'],)) or 0
    if kalan == 0 and kalan_mahsup == 0:
        anlasma_durum_guncelle(p['AnlasmaId'], 'TAMAMLANDI', kullanici)
    return True


def odeme_plan_geri_al(plan_id, kullanici='sistem'):
    p = qone("SELECT * FROM finans_odeme_plan WHERE Id = ?", (plan_id,))
    if not p or p['Durum'] != 'GELDI':
        return False
    if p['CariHarId']:
        qexec("DELETE FROM Cari_Har WHERE Id = ?", (p['CariHarId'],))
    qexec("""
        UPDATE finans_odeme_plan
        SET Durum = 'BEKLIYOR', GerceklesenTarih = NULL, GerceklesenTutar = NULL, CariHarId = NULL
        WHERE Id = ?
    """, (plan_id,))
    audit.log(kullanici, 'ODEME_GERI', 'finans_odeme_plan', plan_id,
              anlasma_id=p['AnlasmaId'],
              aciklama=f"Tahsilat geri alındı: {p.get('Tutar', 0):,.0f} ₺")
    return True


def mahsup_gerceklesti(mahsup_id, gerc_tarih, gerc_tutar, kullanici='sistem'):
    m = qone("""
        SELECT m.*, a.AnlasmaId FROM finans_avans_mahsup m
        JOIN finans_avans a ON a.Id = m.AvansId
        WHERE m.Id = ?
    """, (mahsup_id,))
    if not m or m['Durum'] == 'MAHSUP_EDILDI':
        return False
    qexec("""
        UPDATE finans_avans_mahsup
        SET Durum = 'MAHSUP_EDILDI', GerceklesenTutar = ?, GerceklesenTarih = ?
        WHERE Id = ?
    """, (gerc_tutar, gerc_tarih, mahsup_id))
    audit.log(kullanici, 'MAHSUP_YAPILDI', 'finans_avans_mahsup', mahsup_id,
              anlasma_id=m['AnlasmaId'],
              aciklama=f"Mahsup yapıldı: {gerc_tutar:,.0f} ₺ ({gerc_tarih})")
    return True


def mahsup_geri_al(mahsup_id, kullanici='sistem'):
    m = qone("""
        SELECT m.*, a.AnlasmaId FROM finans_avans_mahsup m
        JOIN finans_avans a ON a.Id = m.AvansId
        WHERE m.Id = ?
    """, (mahsup_id,))
    if not m:
        return False
    qexec("""
        UPDATE finans_avans_mahsup
        SET Durum = 'BEKLIYOR', GerceklesenTutar = NULL, GerceklesenTarih = NULL
        WHERE Id = ?
    """, (mahsup_id,))
    audit.log(kullanici, 'MAHSUP_GERI', 'finans_avans_mahsup', mahsup_id,
              anlasma_id=m['AnlasmaId'],
              aciklama=f"Mahsup geri alındı: {m.get('Tutar', 0):,.0f} ₺")
    return True


# ============================================================
# ORTALAMA ÇEK VADESİ - 2 KPI
# ============================================================

def kpi_cek_ortalama_vade():
    """
    2 ayrı KPI:
    - portfoy_kalan_gun: Portföy çekleri bugünden ort. kaç gün sonra tahsil edilecek (ağırlıklı)
    - alis_vade_gun: Çekler ortalama kaç günlük vadeyle alınıyor (alış → vade arası, ağırlıklı)
    """
    from datetime import date
    bugun_s = date.today().strftime('%Y-%m-%d')

    # Aktif anlaşmaların portföydeki (bekleyen) çekleri
    rows = q("""
        SELECT c.CekAlimTarih, c.CekVadeTarih, c.Tutar
        FROM finans_odeme_cek c
        JOIN finans_odeme_plan p ON p.Id = c.OdemePlanId
        JOIN finans_anlasma a ON a.Id = p.AnlasmaId
        WHERE c.Durum = 'BEKLIYOR'
          AND a.Durum = 'AKTIF'
          AND c.CekVadeTarih >= ?
    """, (bugun_s,))

    if not rows:
        return {'portfoy_kalan_gun': 0, 'alis_vade_gun': 0, 'portfoy_adet': 0, 'portfoy_tutar': 0}

    from datetime import datetime as _dt
    def parse(s):
        try:
            return _dt.strptime(str(s)[:10], '%Y-%m-%d').date()
        except Exception:
            return None

    today = date.today()

    toplam_tutar = 0.0
    agirlikli_kalan = 0.0
    agirlikli_vade_suresi = 0.0
    alim_olan_tutar = 0.0

    for r in rows:
        t = float(r['Tutar'] or 0)
        if t <= 0:
            continue
        vade = parse(r['CekVadeTarih'])
        alim = parse(r['CekAlimTarih'])
        if not vade:
            continue
        toplam_tutar += t
        agirlikli_kalan += (vade - today).days * t
        if alim:
            agirlikli_vade_suresi += (vade - alim).days * t
            alim_olan_tutar += t

    return {
        'portfoy_kalan_gun': round(agirlikli_kalan / toplam_tutar) if toplam_tutar > 0 else 0,
        'alis_vade_gun':     round(agirlikli_vade_suresi / alim_olan_tutar) if alim_olan_tutar > 0 else 0,
        'portfoy_adet':      len(rows),
        'portfoy_tutar':     toplam_tutar,
    }


# ============================================================
# KULLANICI / LOG YARDIMCI
# ============================================================

def anlasma_logu(anlasma_id):
    """Anlaşma detay sayfasında göstermek için."""
    return audit.anlasma_log(anlasma_id)


# ============================================================
# ÖDEME PLANI ŞABLONLARI (Parça 3 — R10, H5)
# ============================================================

# Şablonlar: [(etiket, yüzde, +gün_offset)]
# Kullanıcı uyguladıktan sonra tüm satırları düzenleyebilir/silebilir/ekleyebilir.
ODEME_SABLONLARI = {
    'PESIN': {
        'ad': '%100 Peşin',
        'aciklama': 'Tek ödeme, baştan.',
        'satirlar': [('Peşin', 100, 0, 'HAVALE')],
    },
    'ON_KALAN': {
        'ad': '%30 Peşin + %70 Kalan',
        'aciklama': 'Klasik iki taksit — peşinat + son ödeme.',
        'satirlar': [
            ('Peşinat',    30, 0,  'HAVALE'),
            ('Kalan',      70, 60, 'HAVALE'),
        ],
    },
    'ON_YOL_SEVK': {
        'ad': '%30 + %40 Yükleme + %30 Sevk Sonrası',
        'aciklama': 'Üç taksit — güvenli akış.',
        'satirlar': [
            ('Peşinat',            30, 0,  'HAVALE'),
            ('Yükleme Öncesi',     40, 30, 'HAVALE'),
            ('Sevk Sonrası',       30, 75, 'HAVALE'),
        ],
    },
    'CEK_PESIN': {
        'ad': '%50 Peşin + %50 Vadeli Çek',
        'aciklama': 'Müşterilerden yaygın.',
        'satirlar': [
            ('Peşin',              50, 0,  'HAVALE'),
            ('30 gün vadeli çek',  50, 30, 'CEK'),
        ],
    },
    'SEVK_SONRASI': {
        'ad': '%100 Sevk Sonrası',
        'aciklama': 'Sadece sevk sonrası ödeme.',
        'satirlar': [('Sevk sonrası', 100, 30, 'HAVALE')],
    },
}


def odeme_sablon_uygula(anlasma_id, sablon_kod, baslangic_tarih, kullanici, mevcut_plan_sil=False):
    """
    Anlaşmaya ödeme şablonundan başlangıç plan satırları oluştur.
    - Kullanıcı sonrasında plan satırlarını serbestçe düzenleyebilir.
    - mevcut_plan_sil=True: önce tüm plan satırlarını siler (yeniden başlat).
    - mevcut_plan_sil=False (default): mevcut plan yanına ekler.
    """
    from datetime import datetime as _dt, timedelta
    if sablon_kod not in ODEME_SABLONLARI:
        raise ValueError(f"Bilinmeyen şablon: {sablon_kod}")
    anl = qone("SELECT * FROM finans_anlasma WHERE Id=?", (anlasma_id,))
    if not anl:
        raise ValueError("Anlaşma bulunamadı.")

    toplam = float(anl['ToplamTutar'] or 0)
    if toplam <= 0:
        raise ValueError("Anlaşmanın toplam tutarı 0 — önce tutarı girin.")

    try:
        bas = _dt.strptime(baslangic_tarih, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError("Başlangıç tarihi geçersiz (YYYY-AA-GG).")

    sablon = ODEME_SABLONLARI[sablon_kod]
    satirlar = sablon['satirlar']

    if mevcut_plan_sil:
        # Önce eşlenmiş çekleri sil
        qexec("""DELETE FROM finans_odeme_cek
                 WHERE OdemePlanId IN (SELECT Id FROM finans_odeme_plan WHERE AnlasmaId=?)""",
              (anlasma_id,))
        qexec("DELETE FROM finans_odeme_plan WHERE AnlasmaId=?", (anlasma_id,))

    # Sıra numarasını mevcut + 1'den başlat
    son_sira = qscalar("SELECT COALESCE(MAX(Sira),0) FROM finans_odeme_plan WHERE AnlasmaId=?",
                       (anlasma_id,)) or 0

    eklenen = []
    for i, (etiket, yuzde, gun_offset, odeme_tipi) in enumerate(satirlar, 1):
        tutar = round(toplam * yuzde / 100, 2)
        plan_tarih = (bas + timedelta(days=gun_offset)).strftime('%Y-%m-%d')
        son_sira += 1
        pid = qexec("""INSERT INTO finans_odeme_plan
                       (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, Durum, Aciklama)
                       VALUES (?, ?, ?, ?, ?, 'BEKLIYOR', ?)""",
                    (anlasma_id, son_sira, plan_tarih, odeme_tipi, tutar,
                     f"Şablon: {sablon['ad']} — {etiket} (%{yuzde})"))
        eklenen.append((pid, etiket, tutar, plan_tarih))

    audit.log_olay(kullanici, 'SABLON_UYGULA', 'finans_anlasma', anlasma_id,
                   anlasma_id=anlasma_id,
                   aciklama=f"Ödeme şablonu uygulandı: {sablon['ad']} "
                           f"({len(satirlar)} satır, başlangıç: {baslangic_tarih})",
                   modul='finans', alt_modul='anlasma')
    return eklenen
