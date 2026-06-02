# -*- coding: utf-8 -*-
"""
Parça 8a: Çin Ofis Excel Import — CRUD ve İş Mantığı
Finans modülü altında.
"""
import os
import json
from datetime import datetime, date
from db import q, qone, qexec, qscalar
from modules import audit


# =========================================================
# IMPORT LOG CRUD
# =========================================================
def import_log_liste(limit=50):
    return q("""SELECT l.*,
                       (SELECT SiparisNo FROM grafik_cin_siparis WHERE Id = l.SiparisId) AS SiparisNo
                FROM cin_ofis_import_log l
                ORDER BY l.Id DESC LIMIT ?""", (limit,))


def import_log_tek(log_id):
    return qone("SELECT * FROM cin_ofis_import_log WHERE Id=?", (log_id,))


def odeme_taslak_liste(log_id):
    return q("SELECT * FROM cin_ofis_odeme_taslak WHERE ImportLogId=? ORDER BY Sira",
             (log_id,))


def dosya_referans_liste(log_id):
    return q("SELECT * FROM cin_ofis_dosya_referans WHERE ImportLogId=? ORDER BY Sira",
             (log_id,))


def duplicate_kontrol(order_code):
    """Aynı Order Code daha önce kayıt edilmiş mi (IPTAL hariç)?"""
    return qone("""SELECT l.*, s.SiparisNo, s.Durum as SiparisDurum
                   FROM cin_ofis_import_log l
                   LEFT JOIN grafik_cin_siparis s ON s.Id = l.SiparisId
                   WHERE l.OrderCode = ?
                     AND l.Durum IN ('BASARILI','REVIZE_EDILDI','ON_IZLEME')
                   ORDER BY l.Id DESC LIMIT 1""", (order_code,))


def log_onizleme_kaydet(parse_data, dosya_adi, kur_info, kullanici):
    """Parse sonrası önizleme için geçici log oluştur."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order_code = parse_data['INFO'].get('Order Code', '')

    # Duplicate tespiti
    onceki = duplicate_kontrol(order_code)
    onceki_id = onceki['Id'] if onceki else None

    log_id = qexec("""INSERT INTO cin_ofis_import_log
                      (OrderCode, DosyaAdi, ParseOzet, Dil, TemplateSurum, Durum,
                       OncekiImportId,
                       KurPB, KurDeger, KurKaynagi, KurTarihi,
                       SistemKurDeger, ExcelKurDeger, KurFarkiYuzde,
                       OlusturmaTarih, OlusturanKullanici)
                      VALUES (?, ?, ?, ?, ?, 'ON_IZLEME',
                              ?,
                              ?, ?, ?, ?,
                              ?, ?, ?,
                              ?, ?)""",
                   (order_code, dosya_adi, json.dumps(parse_data, ensure_ascii=False),
                    parse_data.get('_lang', 'CN'),
                    parse_data.get('_template_version', 'v1.0'),
                    onceki_id,
                    kur_info.get('pb'), kur_info.get('kur'),
                    kur_info.get('kaynak'), kur_info.get('islem_tarih'),
                    kur_info.get('sistem_kur'), kur_info.get('excel_rate'),
                    kur_info.get('fark_yuzde'),
                    now, kullanici))

    # Ödeme taslakları
    for i, p in enumerate(parse_data.get('PAYMENT', []), 1):
        qexec("""INSERT INTO cin_ofis_odeme_taslak
                 (ImportLogId, Sira, OdemeTipi, Oran, Tutar, ParaBirimi, PlanTarih, Tetikleyici, Notlar)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (log_id, i, p.get('Type'), p.get('Ratio'), p.get('Amount'),
               kur_info.get('pb'), p.get('Due Date'), p.get('Trigger'), p.get('Notes')))

    # Dosya referansları
    for i, f in enumerate(parse_data.get('FILES', []), 1):
        qexec("""INSERT INTO cin_ofis_dosya_referans
                 (ImportLogId, Sira, DosyaAdi, DosyaTipi, Gerekli, Aciklama)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (log_id, i, f.get('File Name'), f.get('Type'),
               1 if (f.get('Required') or '').strip().lower() in ('yes', 'y', '是', '1') else 0,
               f.get('Description')))

    audit.log_olay(kullanici, 'CIN_OFIS_UPLOAD_BASLADI', 'cin_ofis_import_log', log_id,
                   aciklama=f'Excel: {dosya_adi}, Order: {order_code}',
                   modul='finans', alt_modul='cin_ofis')
    return log_id, onceki


def siparis_olustur(log_id, kullanici, kur_karari=None, revizyon=False):
    """
    Önizleme onayı sonrası gerçek sipariş + kalem + ek + ödeme taslağı kaydı.
    kur_karari: {'kaynak': 'SISTEM_OTOMATIK' | 'EXCEL_OVERRIDE', 'kur': float, 'gerekce': str}

    Atomicity: Tek connection + transaction içinde tüm insertler yapılır.
    Herhangi bir adımda hata olursa rollback — yarım sipariş, yarım kalem, yarım log olmaz.
    """
    from db import get_conn

    log = import_log_tek(log_id)
    if not log:
        raise ValueError('İçe aktarma kaydı bulunamadı.')
    if log['Durum'] != 'ON_IZLEME':
        raise ValueError(f'Bu içe aktarma zaten işlenmiş (Durum: {log["Durum"]}).')

    parse_data = json.loads(log['ParseOzet'])
    info = parse_data['INFO']
    items = parse_data.get('ITEMS', [])
    order_code = log['OrderCode']

    # Ön validasyon — veri eksikse hiçbir şey yapma
    if not items:
        raise ValueError('Sipariş oluşturulamaz: ITEMS boş.')
    if not info.get('Currency'):
        raise ValueError('Sipariş oluşturulamaz: Currency eksik.')

    # Kur kararı
    if kur_karari:
        kaynak = kur_karari.get('kaynak', 'SISTEM_OTOMATIK')
        kur = float(kur_karari.get('kur') or log['SistemKurDeger'] or 1)
        gerekce = kur_karari.get('gerekce') or None
    else:
        kaynak = log['KurKaynagi'] or 'SISTEM_OTOMATIK'
        kur = log['KurDeger'] or log['SistemKurDeger'] or 1
        gerekce = None

    # Sipariş no — önceden üret (aynı connection üzerinde)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pb = info.get('Currency') or 'USD'
    etd = info.get('Expected ETD') or None
    tedarikci_ad = (info.get('Supplier Name') or '').strip()

    # TRANSACTION İÇİNDE TÜM İŞLEM
    conn = get_conn()
    try:
        cur = conn.cursor()
        # SQLite'ta manuel transaction — autocommit kapalı kalır
        # sqlite3 default DEFERRED transaction açar

        # Revizyon
        onceki_log = None
        if log['OncekiImportId']:
            onceki_log = import_log_tek(log['OncekiImportId'])
            if onceki_log and onceki_log['SiparisId'] and revizyon:
                cur.execute("""UPDATE grafik_cin_siparis
                               SET Durum = 'IPTAL',
                                   Notlar = COALESCE(Notlar, '') || char(10) ||
                                            ? || ' tarafından ' || ? || ' Excel revizyon yeniden import edildi.'
                               WHERE Id = ?""",
                            (kullanici, datetime.now().strftime('%Y-%m-%d %H:%M'),
                             onceki_log['SiparisId']))
                cur.execute("UPDATE cin_ofis_import_log SET Durum='REVIZE_EDILDI' WHERE Id=?",
                            (onceki_log['Id'],))

        # Tedarikçi eşleştir / oluştur
        tedarikci_id = None
        tedarikci_durum = None  # 'EXACT' / 'FUZZY' / 'YENI'
        if tedarikci_ad:
            # 1. Exact match
            cur.execute("SELECT Id, Kod FROM grafik_tedarikci WHERE LOWER(Ad) = LOWER(?) AND Aktif=1",
                        (tedarikci_ad,))
            row = cur.fetchone()
            if row:
                tedarikci_id = row[0]
                tedarikci_durum = 'EXACT'
            else:
                # 2. Fuzzy match (ilk 10 karakter)
                search_key = tedarikci_ad[:10].strip()
                if search_key:
                    cur.execute("""SELECT Id, Kod FROM grafik_tedarikci
                                   WHERE Ad LIKE ? AND Aktif=1 LIMIT 1""",
                                (f'%{search_key}%',))
                    row = cur.fetchone()
                    if row:
                        tedarikci_id = row[0]
                        tedarikci_durum = 'FUZZY'

            if not tedarikci_id:
                # 3. Yeni tedarikçi oluştur — Kod otomatik üret
                # Kod formatı: CN-XXXX (4 harf) → çakışma varsa sayı ekle
                import re
                kelimeler = re.findall(r'[A-Za-z0-9]+', tedarikci_ad.upper())
                if kelimeler:
                    # İlk kelimenin ilk 4 harfi
                    base = kelimeler[0][:4]
                else:
                    base = 'SUP'
                # Önek belirle — Çince ise CN, değilse kelimelerin ilk harflerinden
                prefix = 'CN'
                # Çakışma kontrolü
                kod = f'{prefix}-{base}'
                n = 1
                while True:
                    cur.execute("SELECT Id FROM grafik_tedarikci WHERE Kod=?", (kod,))
                    if not cur.fetchone():
                        break
                    n += 1
                    kod = f'{prefix}-{base}{n}'
                    if n > 999:
                        # Son çare — unique id
                        kod = f'{prefix}-SUP-{now.replace(":","").replace("-","").replace(" ","")[-8:]}'
                        break

                cur.execute("""INSERT INTO grafik_tedarikci
                               (Kod, Ad, Ulke, Iletisim, NakliyeTipi, Aktif,
                                OlusturmaTarih, OlusturanKullanici)
                               VALUES (?, ?, 'Çin', ?, 'FOB', 1, ?, ?)""",
                            (kod, tedarikci_ad, info.get('Supplier Contact'),
                             now, kullanici))
                tedarikci_id = cur.lastrowid
                tedarikci_durum = 'YENI'

        # Sipariş No otomatik üret (transaction içinde — race-safe)
        cur.execute("""SELECT SiparisNo FROM grafik_cin_siparis
                       WHERE SiparisNo LIKE 'CIN-2026-%'
                       ORDER BY Id DESC LIMIT 1""")
        son = cur.fetchone()
        if son:
            try:
                n = int(str(son[0]).split('-')[-1]) + 1
            except (ValueError, IndexError):
                n = 1
        else:
            n = 1
        sno = f'CIN-2026-{n:04d}'

        # Notlar hazırla
        notlar_parcalari = [
            f'[ÇİN İÇE AKTARMA] Sipariş Kodu: {order_code}',
            f'Ürün (genel): {items[0].get("Product Name") if items else "—"}',
            f'Toplam konteyner: {info.get("Total Container Count", "—")}',
            f'Nakliye: {info.get("Shipment Type", "—")}',
            f'Limanlar: {info.get("Loading Port", "—")} → {info.get("Discharge Port", "—")}',
        ]
        if info.get('Notes'):
            notlar_parcalari.append(f'Not: {info.get("Notes")}')

        toplam_tutar = sum(float(i.get('Qty', 0) or 0) * float(i.get('Unit Price', 0) or 0)
                          for i in items)

        # SİPARİŞ
        cur.execute("""INSERT INTO grafik_cin_siparis
                       (SiparisNo, TedarikciId, Durum, ParaBirimi, KurSnapshot,
                        ToplamTutar, BeklenenCikisTarihi, Notlar,
                        OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, 'CIN_IMPORT_KONTROL', ?, ?,
                               ?, ?, ?,
                               ?, ?)""",
                    (sno, tedarikci_id, pb, kur,
                     toplam_tutar, etd, '\n'.join(notlar_parcalari),
                     now, kullanici))
        siparis_id = cur.lastrowid

        # KALEMLER
        for it in items:
            urun_ad = (it.get('Product Name') or '').strip() or '—'
            aciklama = it.get('Description') or ''
            miktar = float(it.get('Qty') or 0)
            birim_fiyat = float(it.get('Unit Price') or 0)
            agirlik = float(it.get('Weight (kg)') or 0)
            cont_type = (it.get('Container Type') or '').strip()
            cont_group = (it.get('Container Group') or '').strip()
            cont_qty = int(it.get('Container Qty') or 1)
            quality = (it.get('Quality') or '').strip()
            unit = (it.get('Unit') or '').strip()

            kalem_aciklama = urun_ad
            if aciklama:
                kalem_aciklama += f' — {aciklama}'
            if cont_group or cont_type:
                kalem_aciklama += f' [{cont_group}'
                if cont_type:
                    kalem_aciklama += f' × {cont_qty}× {cont_type}'
                kalem_aciklama += ']'

            cur.execute("""INSERT INTO grafik_cin_siparis_kalem
                           (SiparisId, VaryantId, UrunId, Aciklama, Miktar, CiftSayi,
                            BirimFiyat, Tutar, AgirlikKg, HacimM3, OlusturmaTarih)
                           VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, ?)""",
                        (siparis_id, kalem_aciklama,
                         miktar, int(miktar),
                         birim_fiyat, miktar * birim_fiyat, agirlik, now))
            kalem_id = cur.lastrowid

            cur.execute("""INSERT INTO cin_ofis_kalem_ek
                           (KalemId, ContainerGroup, ContainerType, ContainerQty,
                            Quality, ProductName, Unit)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (kalem_id, cont_group, cont_type, cont_qty, quality, urun_ad, unit))

        # LOG GÜNCELLE
        cur.execute("""UPDATE cin_ofis_import_log SET
                       Durum = 'BASARILI',
                       SiparisId = ?,
                       KurDeger = ?, KurKaynagi = ?,
                       KurOnayKullanici = ?, KurOnayGerekce = ?
                       WHERE Id = ?""",
                    (siparis_id, kur, kaynak,
                     kullanici if kaynak == 'EXCEL_OVERRIDE' else None,
                     gerekce, log_id))

        # COMMIT — hepsi başarılı
        conn.commit()

    except Exception as e:
        # ROLLBACK — yarım veri oluşmaz
        try: conn.rollback()
        except Exception: pass
        raise ValueError(f'Sipariş oluşturulamadı: {e}') from e
    finally:
        try: conn.close()
        except Exception: pass

    # AUDIT — transaction DIŞINDA (hızlı, opsiyonel, commit başarılı olduğu için)
    if kaynak == 'EXCEL_OVERRIDE':
        audit.log_olay(kullanici, 'CIN_OFIS_KUR_OVERRIDE', 'cin_ofis_import_log', log_id,
                       aciklama=(f'Excel kuru kullanıldı: {pb} sistem={log["SistemKurDeger"]:.4f} '
                                f'excel={kur:.4f} fark=%{log["KurFarkiYuzde"] or 0:.1f} | '
                                f'Gerekçe: {gerekce or "—"} | order={order_code}'),
                       modul='finans', alt_modul='cin_ofis')

    if log['OncekiImportId'] and revizyon and onceki_log:
        audit.log_olay(kullanici, 'CIN_OFIS_IMPORT_REVIZYON', 'cin_ofis_import_log', log_id,
                      aciklama=f'Eski import #{onceki_log["Id"]} → sipariş #{onceki_log["SiparisId"]} IPTAL',
                      modul='finans', alt_modul='cin_ofis')

    audit.log_olay(kullanici, 'CIN_OFIS_EXCEL_IMPORT', 'grafik_cin_siparis', siparis_id,
                   aciklama=(f'Order: {order_code} → {sno} | Kur: {pb} {kur:.4f} ({kaynak}) | '
                            f'Kalemler: {len(items)} | Tutar: {toplam_tutar:,.2f} {pb}'),
                   modul='finans', alt_modul='cin_ofis')

    return siparis_id, sno


def import_iptal(log_id, kullanici, sebep=''):
    """Önizleme aşamasında iptal."""
    log = import_log_tek(log_id)
    if not log or log['Durum'] != 'ON_IZLEME':
        raise ValueError('Sadece ON_IZLEME durumunda iptal edilebilir.')
    qexec("UPDATE cin_ofis_import_log SET Durum='IPTAL' WHERE Id=?", (log_id,))
    audit.log_olay(kullanici, 'CIN_OFIS_IMPORT_IPTAL', 'cin_ofis_import_log', log_id,
                   aciklama=sebep or 'Önizleme iptal',
                   modul='finans', alt_modul='cin_ofis')


# =========================================================
# KONTROL TAMAMLAMA (Yönetim)
# =========================================================
def kontrol_onkosullar(siparis_id):
    """
    Sipariş ONAYLANDI'ya geçebilmek için ön koşulları denetler.
    Returns: (checks_list, tumu_ok)
    """
    s = qone("SELECT * FROM grafik_cin_siparis WHERE Id=?", (siparis_id,))
    if not s:
        return ([], False)

    checks = []

    # İlgili import log
    log = qone("SELECT * FROM cin_ofis_import_log WHERE SiparisId=? AND Durum='BASARILI' ORDER BY Id DESC LIMIT 1",
               (siparis_id,))

    # 1. Müşteri
    mkd = s['MusteriCKod']
    checks.append({
        'ad': 'Müşteri atandı',
        'ok': bool(mkd),
        'mesaj': 'Siparişe müşteri ataması yapılmalı' if not mkd else f'✓ {mkd}',
    })

    # 2. Anlaşma
    anlasma = None
    if mkd:
        anlasma = qone("SELECT Id, ProjeKod FROM finans_anlasma WHERE ProjeKod = ?",
                       (s['SiparisNo'],))
    checks.append({
        'ad': 'Finans anlaşması oluştu',
        'ok': bool(anlasma),
        'mesaj': 'Anlaşma oluşturulmalı (ProjeKod=sipariş no)' if not anlasma else f'✓ Anlaşma #{anlasma["Id"]}',
    })

    # 3. Ödeme planı — taslak varsa anlaşmaya taşınmış mı
    if log:
        taslak_sayi = qscalar("SELECT COUNT(*) FROM cin_ofis_odeme_taslak WHERE ImportLogId=?",
                              (log['Id'],)) or 0
        if taslak_sayi > 0 and anlasma:
            plan_sayi = qscalar("SELECT COUNT(*) FROM finans_odeme_plan WHERE AnlasmaId=?",
                                (anlasma['Id'],)) or 0
            checks.append({
                'ad': f'Ödeme planı anlaşmaya taşındı ({taslak_sayi} taslak)',
                'ok': plan_sayi >= taslak_sayi,
                'mesaj': 'Ödeme taslaklarını anlaşmaya taşıyın' if plan_sayi < taslak_sayi
                         else f'✓ {plan_sayi} plan satırı',
            })
        elif taslak_sayi > 0:
            checks.append({
                'ad': 'Ödeme planı taslağı anlaşmaya taşınmalı',
                'ok': False,
                'mesaj': f'{taslak_sayi} taslak satırı var, anlaşma oluşturulunca taşıyın',
            })

    # 4. Zorunlu dosyalar
    if log:
        required = q("SELECT DosyaAdi FROM cin_ofis_dosya_referans WHERE ImportLogId=? AND Gerekli=1",
                     (log['Id'],))
        upload_dir = os.path.join('uploads', 'cin_ofis', log['OrderCode'])
        eksikler = []
        for r in required:
            if not os.path.exists(os.path.join(upload_dir, r['DosyaAdi'])):
                eksikler.append(r['DosyaAdi'])
        checks.append({
            'ad': f'Zorunlu dosyalar yüklendi ({len(required) - len(eksikler)}/{len(required)})',
            'ok': len(eksikler) == 0,
            'mesaj': f'Eksik: {", ".join(eksikler)}' if eksikler else '✓ Tümü yüklendi',
        })

    # 5. FOB toplam
    fob = qscalar("SELECT COALESCE(SUM(Tutar),0) FROM grafik_cin_siparis_kalem WHERE SiparisId=?",
                  (siparis_id,)) or 0
    checks.append({
        'ad': 'FOB toplam hesaplandı',
        'ok': fob > 0,
        'mesaj': f'Toplam: {fob:,.2f} {s["ParaBirimi"]}' if fob > 0 else 'Kalemler eksik',
    })

    # 6. Navlun/vergi notu
    notlar = (s['Notlar'] or '').lower()
    has_info = any(k in notlar for k in ('navlun', '运费', 'vergi', '税', 'maliyet', '成本'))
    checks.append({
        'ad': 'Navlun/vergi bilgisi not alanında',
        'ok': has_info,
        'mesaj': 'Sipariş notlarına tahmini navlun ve vergi ekleyin' if not has_info else '✓ Var',
    })

    tumu_ok = all(c['ok'] for c in checks)
    return (checks, tumu_ok)


def kontrol_tamamla(siparis_id, kullanici):
    """CIN_IMPORT_KONTROL → ONAYLANDI (sadece Yönetim, ön koşullar tam)."""
    s = qone("SELECT * FROM grafik_cin_siparis WHERE Id=?", (siparis_id,))
    if not s:
        raise ValueError('Sipariş bulunamadı.')
    if s['Durum'] != 'CIN_IMPORT_KONTROL':
        raise ValueError('Sipariş CIN_IMPORT_KONTROL durumunda değil.')

    checks, tumu_ok = kontrol_onkosullar(siparis_id)
    if not tumu_ok:
        eksikler = [c['ad'] for c in checks if not c['ok']]
        raise ValueError(f'Ön koşullar eksik: {"; ".join(eksikler)}')

    qexec("UPDATE grafik_cin_siparis SET Durum='ONAYLANDI' WHERE Id=?", (siparis_id,))
    audit.log_olay(kullanici, 'CIN_IMPORT_ONAYLA', 'grafik_cin_siparis', siparis_id,
                   aciklama=f'{s["SiparisNo"]} kontrolü tamamlandı, ONAYLANDI',
                   modul='grafik', alt_modul='cin_siparis')


def kontrol_reddet(siparis_id, sebep, kullanici):
    """CIN_IMPORT_KONTROL → IPTAL (sadece Yönetim)."""
    s = qone("SELECT * FROM grafik_cin_siparis WHERE Id=?", (siparis_id,))
    if not s:
        raise ValueError('Sipariş bulunamadı.')
    if s['Durum'] != 'CIN_IMPORT_KONTROL':
        raise ValueError('Sipariş CIN_IMPORT_KONTROL durumunda değil.')
    if not (sebep or '').strip():
        raise ValueError('Reddetme sebebi zorunlu.')

    qexec("""UPDATE grafik_cin_siparis
             SET Durum='IPTAL',
                 Notlar = COALESCE(Notlar, '') || char(10) || '[KONTROL REDDEDILDI] ' || ?
             WHERE Id=?""", (sebep, siparis_id))
    audit.log_olay(kullanici, 'CIN_IMPORT_REDDET', 'grafik_cin_siparis', siparis_id,
                   aciklama=f'{s["SiparisNo"]} reddedildi | Sebep: {sebep}',
                   modul='grafik', alt_modul='cin_siparis')


# =========================================================
# KUR KİLİDİ (Yönetim override)
# =========================================================
def siparis_kur_override(siparis_id, yeni_kur, gerekce, kullanici):
    """Sipariş KurSnapshot değiştirir — sadece Yönetim tarafından çağrılır."""
    s = qone("SELECT * FROM grafik_cin_siparis WHERE Id=?", (siparis_id,))
    if not s:
        raise ValueError('Sipariş bulunamadı.')
    yeni_kur = float(yeni_kur)
    if yeni_kur <= 0:
        raise ValueError('Kur pozitif olmalı.')
    if not (gerekce or '').strip():
        raise ValueError('Kur değişikliği gerekçesi zorunlu.')

    eski_kur = s['KurSnapshot']
    if abs(yeni_kur - eski_kur) < 0.0001:
        return False  # değişim yok

    qexec("UPDATE grafik_cin_siparis SET KurSnapshot=? WHERE Id=?", (yeni_kur, siparis_id))
    # Toplam tutar yeniden hesap (FOB kalem×kur değil, sipariş seviyesinde sadece bilgi)
    # ToplamTutar zaten PB cinsinden, kur değişimi TL dönüşümde etki eder

    audit.log_olay(kullanici, 'SIPARIS_KUR_OVERRIDE', 'grafik_cin_siparis', siparis_id,
                   aciklama=(f'{s["SiparisNo"]} kur {eski_kur:.4f} → {yeni_kur:.4f} '
                            f'({s["ParaBirimi"]}) | Gerekçe: {gerekce}'),
                   modul='grafik', alt_modul='cin_siparis')
    return True
