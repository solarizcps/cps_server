# -*- coding: utf-8 -*-
"""
CPS DEV — UYGULANDI_BOS Kesif Raporu (SALT OKUNUR)
====================================================

AMAC:
  ithalat_belge_parse tablosunda ParseDurum='UYGULANDI' olan ama
  ithalat_maliyet_kalem tablosunda AKTIF kalemi olmayan kayitlari bulur.
  Bunlar "UYGULANDI ama BOS" (UYGULANDI_BOS) adaylaridir.

GUVENLIK:
  - Veritabani READ-ONLY modda acilir (sqlite 'mode=ro' URI).
  - Script sadece SELECT kullanir; INSERT / UPDATE / DELETE YOKTUR.
  - Hicbir parti / kalem / belge kaydi DEGISMEZ.
  - Hicbir dosya SILINMEZ.
  - DB kilidine BILE dokunulmaz (read-only mode).

CIKTI:
  - Toplam UYGULANDI kayit sayisi
  - UYGULANDI_BOS aday sayisi ve detaylari
  - Her aday icin: belge id, dosya adi, parse tarihi, ref, parti bilgisi,
    iptal edilmis kalem sayisi (varsa)
  - sistem_belge kaydi var mi kontrol
  - Parti bazli gruplama
  - Onerilen aksiyon seviyesi (secim kullanicida kalir)

NASIL CALISTIRILIR:
  cd C:\\cps_dev
  python kesif_uygulandi_bos.py
"""

import os
import sys
import sqlite3

# Windows CMD UTF-8 problemini onle
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


# =============================================================
# AYARLAR
# =============================================================
DB_YOL = 'mock_data.db'


def yaz(msg=''):
    print(msg)


def bolum(ad):
    yaz('')
    yaz('=' * 70)
    yaz('  ' + ad)
    yaz('=' * 70)


def main():
    yaz('')
    yaz('=' * 70)
    yaz('  CPS DEV — UYGULANDI_BOS KESIF RAPORU')
    yaz('  Mod: SALT OKUNUR (READ-ONLY) — DB\'ye dokunulmaz')
    yaz('=' * 70)

    # --- DB var mi? ---
    if not os.path.isfile(DB_YOL):
        yaz(f'\nHATA: DB dosyasi bulunamadi: {DB_YOL}')
        yaz('  Bu scripti C:\\cps_dev\\ dizininde calistir.')
        sys.exit(1)

    # --- READ-ONLY ac ---
    try:
        # URI modu ile salt-okunur baglanti
        abs_yol = os.path.abspath(DB_YOL).replace('\\', '/')
        conn = sqlite3.connect(f'file:{abs_yol}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        yaz(f'\nHATA: DB read-only modda acilamadi: {e}')
        sys.exit(2)

    c = conn.cursor()

    # --- 1) UYGULANDI kayitlarini cek ---
    c.execute("""
        SELECT
            ibp.Id              AS parse_id,
            ibp.BelgeId         AS belge_id,
            ibp.PartiId         AS parti_id,
            ibp.BelgeTipi       AS belge_tipi,
            ibp.ParseDurum      AS parse_durum,
            ibp.ParseTarih      AS parse_tarih,
            ibp.KaynakBelgeRef  AS kaynak_ref,
            ibp.UygulananKalemSayisi AS kalem_sayisi_deklare,
            ibp.Parseden        AS parseden,
            ibp.ParseMesaj      AS parse_mesaj
        FROM ithalat_belge_parse ibp
        WHERE ibp.ParseDurum = 'UYGULANDI'
        ORDER BY ibp.PartiId, ibp.ParseTarih DESC
    """)
    uygulandi_kayitlari = [dict(r) for r in c.fetchall()]

    bolum('1. GENEL SAYIM')
    yaz(f'  Toplam UYGULANDI parse kaydi : {len(uygulandi_kayitlari)}')

    if not uygulandi_kayitlari:
        yaz('  (Hic UYGULANDI kaydi yok - incelenecek bir sey yok)')
        conn.close()
        return

    # --- 2) Her kayit icin aktif kalem sayisi ---
    adaylar = []
    normal = []

    for kayit in uygulandi_kayitlari:
        bid = kayit['belge_id']

        # Aktif kalem sayimi (Iptal=0 veya NULL)
        c.execute("""
            SELECT COUNT(*) AS adet
            FROM ithalat_maliyet_kalem
            WHERE KaynakBelgeId = ?
              AND (Iptal IS NULL OR Iptal = 0)
        """, (bid,))
        aktif_sayi = c.fetchone()['adet']

        # Iptal edilmis kalem sayimi (tarihi bilgi icin)
        c.execute("""
            SELECT COUNT(*) AS adet
            FROM ithalat_maliyet_kalem
            WHERE KaynakBelgeId = ?
              AND Iptal = 1
        """, (bid,))
        iptal_sayi = c.fetchone()['adet']

        kayit['aktif_kalem_sayisi'] = aktif_sayi
        kayit['iptal_kalem_sayisi'] = iptal_sayi

        if aktif_sayi == 0:
            adaylar.append(kayit)
        else:
            normal.append(kayit)

    yaz(f'  UYGULANDI + aktif kalem VAR  : {len(normal)} (normal, dokunulmayacak)')
    yaz(f'  UYGULANDI + aktif kalem YOK  : {len(adaylar)} (UYGULANDI_BOS adayi)')

    if not adaylar:
        yaz('\n  Hic aday yok - temizlenecek bir kayit bulunmadi.')
        conn.close()
        return

    # --- 3) Her aday icin zenginlestirme ---
    for a in adaylar:
        bid = a['belge_id']
        pid = a['parti_id']

        # sistem_belge kaydi
        c.execute("""
            SELECT OrijinalAd, DiskYol, DosyaBoyut, Yukleyen, YuklemeTarih, Aktif
            FROM sistem_belge
            WHERE Id = ?
        """, (bid,))
        sb = c.fetchone()
        if sb:
            a['sistem_belge_var']  = True
            a['dosya_adi']         = sb['OrijinalAd']
            a['disk_yol']          = sb['DiskYol']
            a['disk_boyut']        = sb['DosyaBoyut']
            a['yukleyen']          = sb['Yukleyen']
            a['yukleme_tarih']     = sb['YuklemeTarih']
            a['belge_aktif']       = bool(sb['Aktif'])
        else:
            a['sistem_belge_var']  = False
            a['dosya_adi']         = '(kayit yok)'
            a['disk_yol']          = None

        # Parti bilgisi
        c.execute("""
            SELECT Kod, Baslik, Durum
            FROM ithalat_parti
            WHERE Id = ?
        """, (pid,))
        p = c.fetchone()
        if p:
            a['parti_kod']    = p['Kod']
            a['parti_baslik'] = p['Baslik']
            a['parti_durum']  = p['Durum']
        else:
            a['parti_kod']    = '(parti yok!)'
            a['parti_baslik'] = None
            a['parti_durum']  = None

    # --- 4) Aday tablosu ---
    bolum('2. UYGULANDI_BOS ADAY KAYITLAR (' + str(len(adaylar)) + ' adet)')
    for i, a in enumerate(adaylar, 1):
        yaz('')
        yaz(f'  [{i:02d}] parse_id={a["parse_id"]}  belge_id={a["belge_id"]}  '
            f'parti_id={a["parti_id"]}')
        yaz(f'       Tipi      : {a["belge_tipi"]}')
        yaz(f'       Dosya     : {a["dosya_adi"]}')
        yaz(f'       Parse tar : {a["parse_tarih"]}')
        yaz(f'       Parseden  : {a["parseden"]}')
        yaz(f'       Ref       : {a["kaynak_ref"]}')
        yaz(f'       Parti     : {a["parti_kod"]} [{a["parti_durum"]}]  '
            f'({(a["parti_baslik"] or "")[:50]})')
        yaz(f'       sistem_belge var mi : {a["sistem_belge_var"]}')
        if a['sistem_belge_var']:
            aktif_str = 'aktif' if a.get('belge_aktif') else 'INAKTIF'
            yaz(f'       Belge kaydi durumu  : {aktif_str}')
            yaz(f'       Disk yol            : {a.get("disk_yol") or "-"}')
        yaz(f'       Deklare edilen kalem : {a["kalem_sayisi_deklare"]}')
        yaz(f'       Aktif kalem (SIMDI)  : {a["aktif_kalem_sayisi"]}')
        yaz(f'       Iptal edilmis kalem  : {a["iptal_kalem_sayisi"]}')
        mesaj = (a['parse_mesaj'] or '')[:150]
        if mesaj:
            yaz(f'       Parse mesaj : {mesaj}')

    # --- 5) Parti bazli gruplama ---
    bolum('3. PARTI BAZLI OZET')
    parti_grup = {}
    for a in adaylar:
        k = (a['parti_id'], a['parti_kod'] or '?')
        parti_grup.setdefault(k, []).append(a)

    for (pid, pkod), lst in sorted(parti_grup.items(), key=lambda x: -len(x[1])):
        yaz(f'  Parti {pkod} (id={pid}): {len(lst)} UYGULANDI_BOS kayit')
        for a in lst:
            yaz(f'     - belge_id={a["belge_id"]}  {a["belge_tipi"]:<14s}  '
                f'{(a["dosya_adi"] or "")[:50]}')

    # --- 6) Degerlendirme ---
    bolum('4. DEGERLENDIRME')

    yorum_sayac = {
        'eski_uygulama_iptal_edilmis': 0,   # iptal_sayi > 0
        'hic_kalem_yazilmamis':        0,   # iptal_sayi == 0 and deklare == 0
        'deklare_var_kayip_var':        0,   # iptal_sayi == 0 and deklare > 0
    }

    for a in adaylar:
        if a['iptal_kalem_sayisi'] > 0:
            yorum_sayac['eski_uygulama_iptal_edilmis'] += 1
        elif a['kalem_sayisi_deklare'] == 0:
            yorum_sayac['hic_kalem_yazilmamis'] += 1
        else:
            yorum_sayac['deklare_var_kayip_var'] += 1

    yaz('')
    yaz(f'  A) Eskiden yazilip sonradan iptal edilmis  : '
        f'{yorum_sayac["eski_uygulama_iptal_edilmis"]} kayit')
    yaz('     (normal override akisi - kalemler iptal edilmis, yenileri yazilmis)')
    yaz('')
    yaz(f'  B) Hic kalem yazilmamis (deklare=0)        : '
        f'{yorum_sayac["hic_kalem_yazilmamis"]} kayit')
    yaz('     (packing list veya bilgi amacli belgeler olabilir)')
    yaz('')
    yaz(f'  C) Kalem deklare edilmis ama kayip         : '
        f'{yorum_sayac["deklare_var_kayip_var"]} kayit')
    yaz('     (elle DELETE edilmis veya veri tutarsizligi - KRITIK)')

    # --- 7) Oneriler ---
    bolum('5. ONERI SEVIYELERI (karar kullanicinindir)')
    yaz('')
    yaz('  Secenek A — SADECE UI (DB dokunulmaz)')
    yaz('    - Frontend\'de "UYGULANDI_BOS" rozetini ve partideki kalem sayisindan')
    yaz('      bu kayitlari exclude et. DB aynen kalir. Audit izi bozulmaz.')
    yaz('    - Dokunulan: static/js (+belki css). DB/backend dokunulmaz.')
    yaz('    - Risk: Cok dusuk. Geri alma: patch yedeginden 1 komut.')
    yaz('')
    yaz('  Secenek B — PARSE DURUMU SOFT-UPDATE (onerilir)')
    yaz('    - ithalat_belge_parse.ParseDurum: "UYGULANDI" -> "UYGULANDI_BOS"')
    yaz('    - sistem_audit tablosuna log yazilir (kim, ne zaman, ne sebeple).')
    yaz('    - DB kaydi silinmez, sadece etiket degisir.')
    yaz('    - Dokunulan: sadece N UPDATE satiri (N=aday sayisi).')
    yaz('    - Risk: Dusuk. Geri alma: mock_data.db yedeginden geri yukle')
    yaz('      veya tek UPDATE ile eski "UYGULANDI" durumuna ceviri.')
    yaz('')
    yaz('  Secenek C — HARD DELETE (ONERILMEZ)')
    yaz('    - ithalat_belge_parse tablosundan DELETE.')
    yaz('    - Audit izi kaybolur, ileride bulma zorlasir.')
    yaz('    - Risk: Orta. Geri alma: DB yedegi gerekir.')
    yaz('')
    yaz('  Onerim: SECENEK B.')
    yaz('    (veri kalır, etiket degisir, UI yumusak gecer, audit tutulur)')

    yaz('')
    yaz('=' * 70)
    yaz('  RAPOR BITTI — DB\'ye HIC DOKUNULMADI')
    yaz('=' * 70)
    yaz('')

    conn.close()


if __name__ == '__main__':
    main()
