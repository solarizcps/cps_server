# -*- coding: utf-8 -*-
"""
NexGen Data-Fix — N330/N550 kategori KATKI → BOYA
==================================================

Operasyon karari: N550 ve N330 karbon siyah pigmenttir (BOYA).

Kullanim:
  python app/scripts/nexgen_karbon_siyah_boya_kategori_fix.py           <- onizleme
  python app/scripts/nexgen_karbon_siyah_boya_kategori_fix.py --confirm <- uygula

KURAL:
  --confirm olmadan HICBIR UPDATE YAPILMAZ.
  Idempotent: kategori zaten BOYA ise SKIP.

Dokunulan alan: yalnizca nexgen_stok_kart.kategori (+ guncelleme_tarihi)
Hedef kodlar: NEX-09-01 (N550), NEX-09-02 (N330)
"""

import os
import sys
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

HEDEF_KODLAR = ('NEX-09-01', 'NEX-09-02')

SAYIM_TABLOLARI = (
    ('nexgen_recete_kalem', 42),
    ('nexgen_recete_kalem', 43),
    ('nexgen_arge_test_kalem', 42),
    ('nexgen_arge_test_kalem', 43),
    ('nexgen_stok_hareket', 42),
    ('nexgen_stok_hareket', 43),
    ('nexgen_hammadde_fiyat', 42),
    ('nexgen_hammadde_fiyat', 43),
)


def _sayim(cur, tablo, stok_id):
    return cur.execute(
        f"SELECT COUNT(*) FROM {tablo} WHERE stok_kart_id=?",
        (stok_id,),
    ).fetchone()[0]


def rapor(cur):
    print('\n' + '=' * 60)
    print('NexGen N330/N550 BOYA Kategori Data-Fix')
    print('=' * 60)

    kartlar = cur.execute(
        """
        SELECT id, kod, ad, kategori, alt_kategori, aile_id, birim, aktif
        FROM nexgen_stok_kart
        WHERE kod IN (?, ?)
        ORDER BY kod
        """,
        HEDEF_KODLAR,
    ).fetchall()

    if len(kartlar) != 2:
        print(f'  HATA: Beklenen 2 kart, bulunan {len(kartlar)}')
        return None

    print('\n[Mevcut kartlar]')
    guncellenecek = 0
    for k in kartlar:
        durum = 'GUNCELLENECEK' if k['kategori'] == 'KATKI' else 'SKIP (zaten BOYA veya farkli)'
        if k['kategori'] == 'KATKI':
            guncellenecek += 1
        print(f"  {k['kod']:12s} id={k['id']} kategori={k['kategori']:8s} alt_kategori={k['alt_kategori']}  [{durum}]")

    print('\n[Referans sayilari — degismemeli]')
    sayimlar = {}
    for tablo, sid in SAYIM_TABLOLARI:
        n = _sayim(cur, tablo, sid)
        key = f'{tablo}:{sid}'
        sayimlar[key] = n
        print(f'  {key:40s} {n}')

    return {'kartlar': kartlar, 'guncellenecek': guncellenecek, 'sayimlar': sayimlar}


def uygula(cur):
    cur.execute(
        """
        UPDATE nexgen_stok_kart
        SET kategori = 'BOYA',
            guncelleme_tarihi = ?
        WHERE kod IN (?, ?)
          AND kategori = 'KATKI'
        """,
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),) + HEDEF_KODLAR,
    )
    return cur.rowcount


def dogrula(cur, onceki_sayimlar):
    print('\n[Dogrulama]')
    ok = True
    for k in cur.execute(
        "SELECT kod, kategori FROM nexgen_stok_kart WHERE kod IN (?, ?) ORDER BY kod",
        HEDEF_KODLAR,
    ):
        if k['kategori'] != 'BOYA':
            print(f"  FAIL {k['kod']} kategori={k['kategori']} (beklenen BOYA)")
            ok = False
        else:
            print(f"  OK   {k['kod']} kategori=BOYA")

    for key, once in onceki_sayimlar.items():
        tablo, sid = key.rsplit(':', 1)
        simdi = _sayim(cur, tablo, int(sid))
        if simdi != once:
            print(f'  FAIL {key} once={once} simdi={simdi}')
            ok = False
        else:
            print(f'  OK   {key} = {simdi} (degismedi)')

    return ok


def main():
    confirm = '--confirm' in sys.argv
    if not os.path.exists(DB_PATH):
        print(f'HATA: DB bulunamadi: {DB_PATH}')
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    info = rapor(cur)
    if info is None:
        con.close()
        sys.exit(1)

    if info['guncellenecek'] == 0:
        print('\nGuncellenecek kart yok (idempotent SKIP).')
        dogrula(cur, info['sayimlar'])
        con.close()
        return

    if not confirm:
        print(f"\n{info['guncellenecek']} kart guncellenecek.")
        print('Uygulamak icin: python app/scripts/nexgen_karbon_siyah_boya_kategori_fix.py --confirm')
        con.close()
        return

    n = uygula(cur)
    con.commit()
    print(f'\nUPDATE tamamlandi: {n} satir')

    if not dogrula(cur, info['sayimlar']):
        con.close()
        sys.exit(1)

    print('\nData-fix basarili.')
    con.close()


if __name__ == '__main__':
    main()
