'''
Sinyal Engine - D6.1-B

Operasyon sinyal motoru MVP. Manuel tetik destekli, idempotent.

Rules:
  R001 DURGUN_EMIR_7G - aktif (7g+ hareket gormeyen emirler)
  R004 PERSONEL_BUGUN_0 - PASIF (FLAG=False, Adem karari bekleniyor)
'''
import sqlite3
import json
from typing import List, Dict, Optional


# Feature flags
FEATURE_FLAGS = {
    'R001_DURGUN_EMIR_7G': True,
    'R004_PERSONEL_BUGUN_0': False,  # Adem karari bekleniyor
}


class Rule_R001_DurgunEmir7G:
    '''7g+ hareket gormeyen aktif emirler.'''
    id = 'R001'
    sinyal_tipi = 'DURGUN_EMIR_7G'
    seviye = 'WARN'

    def hesapla(self, conn) -> List[Dict]:
        '''
        Aktif emirlerde son hareketi 7+ gun once olanlari bul.
        uretim_kayit.emir_no INTEGER, emir_alt_proses.emir_no TEXT
        CAST ile uyumlu join.
        '''
        rows = conn.execute('''
            SELECT eap.emir_no,
                   MAX(u.olusturma) son_hareket,
                   ROUND(julianday('now')-julianday(MAX(u.olusturma)), 1) gun_durgun
              FROM emir_alt_proses eap
              LEFT JOIN uretim_kayit u
                     ON CAST(u.emir_no AS TEXT) = eap.emir_no
                    AND u.onay_durum='onaylandi'
             WHERE eap.aktif=1
             GROUP BY eap.emir_no
            HAVING son_hareket IS NOT NULL
               AND gun_durgun >= 7.0
             ORDER BY gun_durgun DESC
        ''').fetchall()

        return [
            {
                'sinyal_tipi': self.sinyal_tipi,
                'seviye': self.seviye,
                'emir_no': r['emir_no'],
                'mesaj': f'Emir {r["emir_no"]} son {r["gun_durgun"]:.1f} gundur durgun',
                'aksiyon_onerisi': 'Planlama/Halil kontrol etsin',
                'kaynak': 'RULE_ENGINE',
                'rule_id': self.id,
                'meta_json': json.dumps({
                    'gun_durgun': r['gun_durgun'],
                    'son_hareket': r['son_hareket']
                })
            }
            for r in rows
        ]


class Rule_R004_PersonelBugun0:
    '''
    30g aktif personel + bugun 0 cift + saat>12.
    PASIF (FLAG=False) - sadece tablo doldurma icin var.
    '''
    id = 'R004'
    sinyal_tipi = 'PERSONEL_BUGUN_0'
    seviye = 'INFO'

    def hesapla(self, conn) -> List[Dict]:
        # FLAG kapali oldugundan engine zaten skip eder
        return []


# Rule registry
RULES = {
    'R001': Rule_R001_DurgunEmir7G(),
    'R004': Rule_R004_PersonelBugun0(),
}


def save_signal(conn, sig: Dict, dry_run: bool = False) -> Dict:
    '''
    Idempotent save:
    - Ayni rule_id + emir_no + durum=AKTIF varsa UPDATE (tekrar_sayisi++, son_tetiklenme)
    - Yoksa INSERT
    '''
    if dry_run:
        return {
            'action': 'DRY_RUN',
            'rule_id': sig['rule_id'],
            'emir_no': sig.get('emir_no'),
            'signal_preview': {
                'sinyal_tipi': sig['sinyal_tipi'],
                'seviye': sig['seviye'],
                'mesaj': sig['mesaj']
            }
        }

    existing = conn.execute('''
        SELECT id, tekrar_sayisi FROM operasyon_sinyal
         WHERE rule_id=? AND emir_no=? AND durum='AKTIF'
         LIMIT 1
    ''', (sig['rule_id'], sig.get('emir_no'))).fetchone()

    if existing:
        new_tekrar = existing['tekrar_sayisi'] + 1
        conn.execute('''
            UPDATE operasyon_sinyal
               SET tekrar_sayisi = ?,
                   son_tetiklenme = datetime('now', 'localtime')
             WHERE id = ?
        ''', (new_tekrar, existing['id']))
        return {
            'action': 'UPDATE',
            'id': existing['id'],
            'rule_id': sig['rule_id'],
            'emir_no': sig.get('emir_no'),
            'tekrar_sayisi': new_tekrar
        }
    else:
        cur = conn.execute('''
            INSERT INTO operasyon_sinyal
                (sinyal_tipi, seviye, emir_no, proses_adi, proses_kodu,
                 personel_id, personel_ad,
                 mesaj, aksiyon_onerisi,
                 kaynak, rule_id, durum,
                 tekrar_sayisi, son_tetiklenme,
                 meta_json)
            VALUES (?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?, 'AKTIF',
                    1, datetime('now', 'localtime'),
                    ?)
        ''', (
            sig['sinyal_tipi'], sig['seviye'], sig.get('emir_no'),
            sig.get('proses_adi'), sig.get('proses_kodu'),
            sig.get('personel_id'), sig.get('personel_ad'),
            sig['mesaj'], sig.get('aksiyon_onerisi'),
            sig['kaynak'], sig['rule_id'],
            sig.get('meta_json')
        ))
        return {
            'action': 'INSERT',
            'id': cur.lastrowid,
            'rule_id': sig['rule_id'],
            'emir_no': sig.get('emir_no')
        }


def run_rule(rule_id: str, conn, dry_run: bool = True) -> Dict:
    '''Tek kural calistir.'''
    if rule_id not in RULES:
        return {'ok': False, 'mesaj': f'Bilinmeyen rule: {rule_id}'}

    flag_key = f'{rule_id}_{RULES[rule_id].sinyal_tipi}'
    if not FEATURE_FLAGS.get(flag_key, False):
        return {
            'ok': True,
            'rule_id': rule_id,
            'skipped': True,
            'reason': f'FEATURE_FLAGS[{flag_key}] = False'
        }

    rule = RULES[rule_id]
    signals = rule.hesapla(conn)

    sonuclar = []
    insert_count = 0
    update_count = 0

    for sig in signals:
        result = save_signal(conn, sig, dry_run=dry_run)
        sonuclar.append(result)
        if result['action'] == 'INSERT':
            insert_count += 1
        elif result['action'] == 'UPDATE':
            update_count += 1

    return {
        'ok': True,
        'rule_id': rule_id,
        'sinyal_tipi': rule.sinyal_tipi,
        'toplam_sinyal': len(signals),
        'insert': insert_count,
        'update': update_count,
        'dry_run': dry_run,
        'orneklem': sonuclar[:5]  # Ilk 5
    }


def run_all_rules(conn, dry_run: bool = True, rule_filter: Optional[str] = None) -> Dict:
    '''Tum aktif kurallari calistir.'''
    sonuclar = {}
    for rule_id in RULES.keys():
        if rule_filter and rule_id != rule_filter:
            continue
        sonuclar[rule_id] = run_rule(rule_id, conn, dry_run=dry_run)

    toplam_insert = sum(r.get('insert', 0) for r in sonuclar.values())
    toplam_update = sum(r.get('update', 0) for r in sonuclar.values())
    toplam_sinyal = sum(r.get('toplam_sinyal', 0) for r in sonuclar.values())

    return {
        'ok': True,
        'dry_run': dry_run,
        'rule_filter': rule_filter,
        'toplam_sinyal': toplam_sinyal,
        'toplam_insert': toplam_insert,
        'toplam_update': toplam_update,
        'rules': sonuclar
    }


if __name__ == '__main__':
    # CLI test
    import sys, os
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'app/mock_data.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    dry = '--apply' not in sys.argv
    result = run_all_rules(conn, dry_run=dry)
    if not dry:
        conn.commit()
    conn.close()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


# === D6.1-C SERVICE FUNCTIONS BASLANGIC ===


def list_signals(conn, durum=None, seviye=None, rule_id=None, limit=100, offset=0):
    '''Filtreli sinyal listesi.

    durum: 'AKTIF' / 'GORULDU' / 'DISMISS' / 'RESOLVED' / 'TUM' / None (default AKTIF)
    seviye: 'INFO' / 'WARN' / 'CRITIC' / None
    rule_id: 'R001' vb / None
    limit: max 500
    offset: sayfalama
    '''
    if durum is None:
        durum = 'AKTIF'
    if limit > 500:
        limit = 500
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0

    where_parts = []
    params = []

    if durum != 'TUM':
        where_parts.append('durum = ?')
        params.append(durum)
    if seviye:
        where_parts.append('seviye = ?')
        params.append(seviye)
    if rule_id:
        where_parts.append('rule_id = ?')
        params.append(rule_id)

    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    # Toplam (filtre kapsami)
    toplam_q = f'SELECT COUNT(*) FROM operasyon_sinyal {where_sql}'
    toplam = conn.execute(toplam_q, params).fetchone()[0]

    # Sayfalama
    list_q = f'''
        SELECT id, sinyal_tipi, seviye, emir_no, proses_adi, proses_kodu,
               personel_id, personel_ad, mesaj, aksiyon_onerisi,
               kaynak, rule_id, durum,
               gorulen_kullanici_id, gorulen_zaman,
               cozulen_zaman, cozulen_aciklama,
               tekrar_sayisi, son_tetiklenme, meta_json, olusturma
          FROM operasyon_sinyal
        {where_sql}
         ORDER BY olusturma DESC, id DESC
         LIMIT ? OFFSET ?
    '''
    rows = conn.execute(list_q, params + [limit, offset]).fetchall()
    sinyaller = [dict(r) for r in rows]

    return {
        'ok': True,
        'toplam': toplam,
        'limit': limit,
        'offset': offset,
        'sinyaller': sinyaller,
        'filtre': {
            'durum': durum,
            'seviye': seviye,
            'rule_id': rule_id
        }
    }


def get_signal(conn, signal_id):
    '''Tek sinyal detay. None varsa.'''
    r = conn.execute('''
        SELECT * FROM operasyon_sinyal WHERE id = ?
    ''', (signal_id,)).fetchone()
    return dict(r) if r else None


def dismiss_signal(conn, signal_id, kullanici_id, kullanici_adi, aciklama):
    '''Durum -> DISMISS. Idempotent.

    - kullanici_id: int veya None
    - kullanici_adi: str (zorunlu, audit)
    - aciklama: str (>=3 char, validation route'da yapildi)
    '''
    sig = get_signal(conn, signal_id)
    if not sig:
        return {'ok': False, 'kod': 404, 'mesaj': 'Sinyal yok'}

    # Idempotent: zaten DISMISS ise no-op
    if sig['durum'] == 'DISMISS':
        return {
            'ok': True,
            'no_op': True,
            'mesaj': 'Zaten DISMISS',
            'mevcut_durum': sig['durum']
        }

    # gorulen_kullanici_id daha once dolduysa koru
    set_gorulen_id = sig['gorulen_kullanici_id'] if sig['gorulen_kullanici_id'] is not None else kullanici_id
    set_gorulen_zaman = sig['gorulen_zaman'] if sig['gorulen_zaman'] else None

    # aciklama'ya kullanici_adi'ni ekle (audit trail)
    full_aciklama = f'[{kullanici_adi}] {aciklama}'

    if set_gorulen_zaman:
        # Yalniz cozulen alanlari guncelle
        conn.execute('''
            UPDATE operasyon_sinyal
               SET durum = 'DISMISS',
                   gorulen_kullanici_id = COALESCE(gorulen_kullanici_id, ?),
                   cozulen_zaman = datetime('now', 'localtime'),
                   cozulen_aciklama = ?
             WHERE id = ?
        ''', (set_gorulen_id, full_aciklama, signal_id))
    else:
        # Hem gorulen hem cozulen alanlari doldur
        conn.execute('''
            UPDATE operasyon_sinyal
               SET durum = 'DISMISS',
                   gorulen_kullanici_id = ?,
                   gorulen_zaman = datetime('now', 'localtime'),
                   cozulen_zaman = datetime('now', 'localtime'),
                   cozulen_aciklama = ?
             WHERE id = ?
        ''', (set_gorulen_id, full_aciklama, signal_id))

    yeni_sig = get_signal(conn, signal_id)
    return {
        'ok': True,
        'no_op': False,
        'eski_durum': sig['durum'],
        'yeni_durum': 'DISMISS',
        'sinyal': yeni_sig
    }


def resolve_signal(conn, signal_id, kullanici_id, kullanici_adi, aciklama):
    '''Durum -> RESOLVED. Idempotent.

    DISMISS -> RESOLVED de serbest (Halil hatasini duzeltebilir).
    '''
    sig = get_signal(conn, signal_id)
    if not sig:
        return {'ok': False, 'kod': 404, 'mesaj': 'Sinyal yok'}

    if sig['durum'] == 'RESOLVED':
        return {
            'ok': True,
            'no_op': True,
            'mesaj': 'Zaten RESOLVED',
            'mevcut_durum': sig['durum']
        }

    set_gorulen_id = sig['gorulen_kullanici_id'] if sig['gorulen_kullanici_id'] is not None else kullanici_id
    full_aciklama = f'[{kullanici_adi}] {aciklama}'

    if sig['gorulen_zaman']:
        conn.execute('''
            UPDATE operasyon_sinyal
               SET durum = 'RESOLVED',
                   gorulen_kullanici_id = COALESCE(gorulen_kullanici_id, ?),
                   cozulen_zaman = datetime('now', 'localtime'),
                   cozulen_aciklama = ?
             WHERE id = ?
        ''', (set_gorulen_id, full_aciklama, signal_id))
    else:
        conn.execute('''
            UPDATE operasyon_sinyal
               SET durum = 'RESOLVED',
                   gorulen_kullanici_id = ?,
                   gorulen_zaman = datetime('now', 'localtime'),
                   cozulen_zaman = datetime('now', 'localtime'),
                   cozulen_aciklama = ?
             WHERE id = ?
        ''', (set_gorulen_id, full_aciklama, signal_id))

    yeni_sig = get_signal(conn, signal_id)
    return {
        'ok': True,
        'no_op': False,
        'eski_durum': sig['durum'],
        'yeni_durum': 'RESOLVED',
        'sinyal': yeni_sig
    }


def get_ozet(conn):
    '''KPI ozet: durum/seviye/tip dagilim.'''
    durum_rows = conn.execute('''
        SELECT durum, COUNT(*) cnt FROM operasyon_sinyal GROUP BY durum
    ''').fetchall()
    seviye_rows = conn.execute('''
        SELECT seviye, COUNT(*) cnt FROM operasyon_sinyal GROUP BY seviye
    ''').fetchall()
    tip_rows = conn.execute('''
        SELECT sinyal_tipi, COUNT(*) cnt FROM operasyon_sinyal GROUP BY sinyal_tipi
    ''').fetchall()
    toplam = conn.execute('SELECT COUNT(*) FROM operasyon_sinyal').fetchone()[0]

    durum_d = {r['durum']: r['cnt'] for r in durum_rows}
    return {
        'ok': True,
        'toplam': toplam,
        'aktif': durum_d.get('AKTIF', 0),
        'goruldu': durum_d.get('GORULDU', 0),
        'dismiss': durum_d.get('DISMISS', 0),
        'resolved': durum_d.get('RESOLVED', 0),
        'durum_dagilim': durum_d,
        'seviye_dagilim': {r['seviye']: r['cnt'] for r in seviye_rows},
        'tip_dagilim': {r['sinyal_tipi']: r['cnt'] for r in tip_rows}
    }


# === D6.1-C SERVICE FUNCTIONS SONU ===
