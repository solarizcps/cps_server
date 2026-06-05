# Patch 7B: hedef_sablon_uygula INSERT'i routing-aware hale getir
import io, sys, shutil, time

PATH = r'C:\cps_dev\modules\hedef\routes.py'

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

# Idempotent kontrol
if '_resolve_target_emir(emir_no, sablon[' in src:
    print('SKIP: 7B zaten uygulanmis')
    sys.exit(0)

# Eski blok - hedef_sablon_uygula icindeki kritik mantık
OLD = """        kaynak = 'sablon:' + sablon['sablon_adi']
        max_row = conn.execute(
            "SELECT COALESCE(MAX(siralama), 0) FROM emir_alt_proses WHERE emir_no=?",
            (emir_no,)
        ).fetchone()
        max_sira = int(max_row[0] or 0)

        eklenen = []
        atlanan = []
        for p in prs:
            pa = p['proses_adi']
            mevcut = conn.execute(\"\"\"
                SELECT id FROM emir_alt_proses
                 WHERE emir_no=? AND proses_adi=? AND aktif=1
            \"\"\", (emir_no, pa)).fetchone()
            if mevcut:
                atlanan.append({'proses_adi': pa, 'mevcut_id': mevcut[0]})
                continue
            max_sira += 1
            cur = conn.execute(\"\"\"
                INSERT INTO emir_alt_proses
                    (emir_no, proses_adi, siralama, aktif, kaynak,
                     olusturan_id, olusturan_ad)
                VALUES (?, ?, ?, 1, ?, ?, ?)
            \"\"\", (emir_no, pa, max_sira, kaynak, uid, uad))
            eklenen.append({
                'id': cur.lastrowid,
                'proses_adi': pa,
                'siralama': max_sira,
            })"""

NEW = """        kaynak = 'sablon:' + sablon['sablon_adi']

        # === FAZ 4.7 ROUTING: ATKI/GOVDE alt emire yonlendir ===
        gercek_emir_no, routing_sebep = _resolve_target_emir(emir_no, sablon['sablon_adi'])
        try:
            from flask import current_app
            current_app.logger.info(
                f'sablon_uygula routing: ana={emir_no} -> hedef={gercek_emir_no} ({routing_sebep})'
            )
        except Exception:
            pass

        max_row = conn.execute(
            "SELECT COALESCE(MAX(siralama), 0) FROM emir_alt_proses WHERE emir_no=?",
            (gercek_emir_no,)
        ).fetchone()
        max_sira = int(max_row[0] or 0)

        eklenen = []
        atlanan = []
        for p in prs:
            pa = p['proses_adi']
            mevcut = conn.execute(\"\"\"
                SELECT id FROM emir_alt_proses
                 WHERE emir_no=? AND proses_adi=? AND aktif=1
            \"\"\", (gercek_emir_no, pa)).fetchone()
            if mevcut:
                atlanan.append({'proses_adi': pa, 'mevcut_id': mevcut[0]})
                continue
            max_sira += 1
            cur = conn.execute(\"\"\"
                INSERT INTO emir_alt_proses
                    (emir_no, proses_adi, siralama, aktif, kaynak,
                     olusturan_id, olusturan_ad)
                VALUES (?, ?, ?, 1, ?, ?, ?)
            \"\"\", (gercek_emir_no, pa, max_sira, kaynak, uid, uad))
            eklenen.append({
                'id': cur.lastrowid,
                'proses_adi': pa,
                'siralama': max_sira,
                'emir_no': gercek_emir_no,
            })"""

if OLD not in src:
    print('HATA: eski blok bulunamadi (routes.py degismis olabilir)')
    sys.exit(1)

new_src = src.replace(OLD, NEW, 1)

# Yedek
bak = PATH + '.bak_pre_routing_7b_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

print('OK: INSERT routing-aware (artis ' + str(len(new_src) - len(src)) + ' byte)')