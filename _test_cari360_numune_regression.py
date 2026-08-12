# -*- coding: utf-8 -*-
"""
CARI360-NUMUNE-UI-01 — Backend regression testleri
Canonical DB'ye YAZMA YOK. Tüm testler read-only.

Testler:
A — API contract: page/page_size/total_count/total_pages var
B — Grain: duplicate numune yok (aynı id birden fazla gelmiyor)
C — Deterministic ordering: page1 ve page2 overlap yok
D — total_count/total_pages doğru
E — Formül: aktif_arge_testi.ana_formul_grup_kodu canonical
F — Formül yok → None (uydurma yok)
G — renk: raw değer, uydurma yok
H — vedat_sonuc canonical
I — vedat_numune_miktari canonical (ham değer)
J — numune_adedi canonical (ham sayı)
K — durum canonical
L — AR-GE bağlantılı numune expand verisi dolu
M — Üretim sekmesi import'ları bozulmamış
"""
import sys, os, sqlite3, hashlib, math
sys.stdout.reconfigure(encoding='utf-8')

# Canonical DB path
DB = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app', 'mock_data.db'))

# SHA lock
with open(DB, 'rb') as _f:
    _SHA_BEFORE = hashlib.sha256(_f.read()).hexdigest()
SHA_EXPECTED = '2469406a7dde9b8a0fe8442da1e61fae40a4760d663d46a73dfd51e662caf008'

def con_ro():
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c

def _service_call(cari_id, page=1, page_size=10):
    """load_cari360_numuneler doğrudan çağrı."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app', 'modules', 'nexgen'))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
    from modules.nexgen.cari360_ops_read_service import load_cari360_numuneler
    con = con_ro()
    try:
        # page_size max 100 servis içinde kırpılıyor; büyük sorgu için çok sayfa topluyoruz
        return load_cari360_numuneler(con, cari_id, kullanici_id=1, yk=None,
                                      page=page, page_size=min(page_size, 100))
    finally:
        con.close()

def _service_call_all(cari_id):
    """Tüm sayfaları toplayıp birleştirir."""
    first = _service_call(cari_id, page=1, page_size=100)
    total = first.get('total_count', 0)
    pages = first.get('total_pages', 1)
    liste = list(first.get('liste', []))
    for p in range(2, pages + 1):
        d = _service_call(cari_id, page=p, page_size=100)
        liste.extend(d.get('liste', []))
    first['liste'] = liste
    return first

PASS = []
FAIL = []

def ok(name):
    PASS.append(name)
    print(f'  PASS  {name}')

def fail(name, reason):
    FAIL.append(name)
    print(f'  FAIL  {name}: {reason}')

print('=== CARI360 NUMUNE REGRESSION ===\n')

# SHA BEFORE
print('[SHA]')
if _SHA_BEFORE == SHA_EXPECTED:
    ok('SHA_before_match')
else:
    fail('SHA_before_match', f'got {_SHA_BEFORE}')

# --- Cari 1 (162 numune, pagination için yeterli) ---
print('\n[A] API Contract')
try:
    d = _service_call(cari_id=1, page=1, page_size=10)
    for key in ('liste', 'count', 'page', 'page_size', 'total_count', 'total_pages', 'ozet'):
        if key in d:
            ok(f'A_key_{key}')
        else:
            fail(f'A_key_{key}', 'missing')
except Exception as e:
    fail('A_service_call', str(e))
    d = {}

print('\n[B] Grain: no duplicate id')
try:
    ids = [n['id'] for n in d.get('liste', [])]
    if len(ids) == len(set(ids)):
        ok('B_no_duplicate_id')
    else:
        fail('B_no_duplicate_id', f'dups: {[x for x in ids if ids.count(x) > 1]}')
except Exception as e:
    fail('B_grain', str(e))

print('\n[C] Pagination overlap page1 vs page2')
try:
    d1 = _service_call(cari_id=1, page=1, page_size=10)
    d2 = _service_call(cari_id=1, page=2, page_size=10)
    ids1 = {n['id'] for n in d1.get('liste', [])}
    ids2 = {n['id'] for n in d2.get('liste', [])}
    overlap = ids1 & ids2
    if not overlap:
        ok('C_no_overlap_p1_p2')
    else:
        fail('C_no_overlap_p1_p2', f'overlap ids: {overlap}')
    if len(d1.get('liste', [])) == 10:
        ok('C_p1_count_10')
    else:
        fail('C_p1_count_10', f'got {len(d1.get("liste",[]))}')
except Exception as e:
    fail('C_pagination', str(e))

print('\n[D] total_count / total_pages correct')
try:
    total = d.get('total_count', 0)
    ps = d.get('page_size', 10)
    tp = d.get('total_pages', 0)
    expected_pages = max(1, math.ceil(total / ps)) if total > 0 else 0
    if tp == expected_pages:
        ok(f'D_total_pages_correct ({total} kayıt → {tp} sayfa)')
    else:
        fail('D_total_pages_correct', f'expected {expected_pages}, got {tp}')
    # Actual DB count
    con = con_ro()
    db_cnt = con.execute(
        "SELECT COUNT(*) FROM nexgen_numune_talep WHERE cari_id=1 AND COALESCE(aktif,1)=1"
    ).fetchone()[0]
    con.close()
    if total == db_cnt:
        ok(f'D_total_count_matches_db ({db_cnt})')
    else:
        fail('D_total_count_matches_db', f'service={total}, db={db_cnt}')
except Exception as e:
    fail('D_total_pages', str(e))

print('\n[E] Formül: aktif_arge_testi.ana_formul_grup_kodu')
try:
    con = con_ro()
    row = con.execute("""
        SELECT n.id FROM nexgen_numune_talep n
        JOIN nexgen_arge_test a ON a.id = n.arge_test_id
        WHERE n.cari_id=1 AND COALESCE(n.aktif,1)=1
          AND a.ana_formul_grup_kodu IS NOT NULL AND a.ana_formul_grup_kodu != ''
        LIMIT 1
    """).fetchone()
    con.close()
    if row:
        nid = row[0]
        d_all = _service_call_all(cari_id=1)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            if hit.get('ana_formul_grup_kodu'):
                ok(f'E_formul_kod_present (id={nid}, kod={hit["ana_formul_grup_kodu"]})')
            else:
                fail('E_formul_kod_present', f'id={nid} arge bağlı ama kod=None')
        else:
            fail('E_formul_kod_present', f'id={nid} listede bulunamadı')
    else:
        ok('E_formul_skip (no arge+formul in cari_id=1)')
except Exception as e:
    fail('E_formul', str(e))

print('\n[F] Formül yok → ana_formul_grup_kodu = None')
try:
    con = con_ro()
    row_no_arge = con.execute("""
        SELECT id FROM nexgen_numune_talep
        WHERE cari_id=1 AND COALESCE(aktif,1)=1
          AND arge_test_id IS NULL
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    con.close()
    if row_no_arge:
        nid = row_no_arge[0]
        d_all = _service_call_all(cari_id=1)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            if hit.get('ana_formul_grup_kodu') is None:
                ok(f'F_formul_none_no_arge (id={nid})')
            else:
                fail('F_formul_none_no_arge', f'id={nid} arge yok ama kod={hit["ana_formul_grup_kodu"]}')
        else:
            fail('F_formul_none', f'id={nid} listede yok')
    else:
        ok('F_formul_skip')
except Exception as e:
    fail('F_formul_none', str(e))

print('\n[G] Renk: raw değer, split yok')
try:
    con = con_ro()
    row_renk = con.execute("""
        SELECT id, renk_kodu FROM nexgen_numune_talep
        WHERE cari_id=1 AND COALESCE(aktif,1)=1
          AND renk_kodu IS NOT NULL AND renk_kodu != ''
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    con.close()
    if row_renk:
        nid, raw_renk = row_renk[0], row_renk[1]
        d_all = _service_call_all(cari_id=1)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            if hit.get('renk') == raw_renk:
                ok(f'G_renk_raw_match (id={nid}, renk={raw_renk!r})')
            else:
                fail('G_renk_raw_match', f'expected {raw_renk!r} got {hit.get("renk")!r}')
        else:
            fail('G_renk', f'id={nid} listede yok')
    else:
        ok('G_renk_skip (no renk_kodu in cari_id=1)')
except Exception as e:
    fail('G_renk', str(e))

print('\n[H] vedat_sonuc canonical')
try:
    con = con_ro()
    row_vs = con.execute("""
        SELECT id, vedat_sonuc, cari_id FROM nexgen_numune_talep
        WHERE COALESCE(aktif,1)=1 AND vedat_sonuc IS NOT NULL AND vedat_sonuc != ''
          AND cari_id IS NOT NULL
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    con.close()
    if row_vs:
        nid, vs, cari = row_vs[0], row_vs[1], row_vs[2]
        # Use large page_size to find this record
        d_all = _service_call_all(cari_id=cari)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            if hit.get('vedat_sonuc') == vs:
                ok('H_vedat_sonuc (id=' + str(nid) + ', sonuc=' + repr(vs) + ')')
            else:
                fail('H_vedat_sonuc', 'expected ' + repr(vs) + ' got ' + repr(hit.get('vedat_sonuc')))
        else:
            fail('H_vedat_sonuc', 'id=' + str(nid) + ' listede yok (total=' + str(d_all.get('total_count')) + ')')
    else:
        ok('H_vedat_sonuc_skip (no dolu miktar with cari_id)')
except Exception as e:
    fail('H_vedat_sonuc', str(e))

print('\n[I] vedat_numune_miktari canonical ham değer')
try:
    con = con_ro()
    row_m = con.execute("""
        SELECT id, vedat_numune_miktari, cari_id FROM nexgen_numune_talep
        WHERE COALESCE(aktif,1)=1 AND vedat_numune_miktari IS NOT NULL
          AND vedat_numune_miktari != '' AND vedat_numune_miktari != 0
          AND cari_id IS NOT NULL
        LIMIT 1
    """).fetchone()
    con.close()
    if row_m:
        nid, mik, cari = row_m[0], row_m[1], row_m[2]
        d_all = _service_call_all(cari_id=cari)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            if hit.get('vedat_numune_miktari') == mik:
                ok('I_miktar_ham (id=' + str(nid) + ', mik=' + repr(mik) + ')')
            else:
                fail('I_miktar_ham', 'expected ' + repr(mik) + ' got ' + repr(hit.get('vedat_numune_miktari')))
        else:
            fail('I_miktar_ham', 'id=' + str(nid) + ' listede yok (cari=' + str(cari) + ' total=' + str(d_all.get('total_count')) + ')')
    else:
        ok('I_miktar_skip (no dolu miktar with cari_id)')
except Exception as e:
    fail('I_miktar', str(e))

print('\n[J] numune_adedi canonical ham sayı')
try:
    con = con_ro()
    row_ad = con.execute("""
        SELECT id, numune_adedi, cari_id FROM nexgen_numune_talep
        WHERE COALESCE(aktif,1)=1 AND numune_adedi IS NOT NULL AND numune_adedi != 0
          AND cari_id IS NOT NULL
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    con.close()
    if row_ad:
        nid, adedi, cari = row_ad[0], row_ad[1], row_ad[2]
        d_all = _service_call(cari_id=cari, page=1, page_size=200)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            if hit.get('numune_adedi') == adedi:
                ok(f'J_adedi_ham (id={nid}, adedi={adedi!r})')
            else:
                fail('J_adedi_ham', f'expected {adedi!r} got {hit.get("numune_adedi")!r}')
        else:
            fail('J_adedi_ham', f'id={nid} listede yok')
    else:
        ok('J_adedi_skip')
except Exception as e:
    fail('J_adedi', str(e))

print('\n[K] Durum canonical')
try:
    d_all = _service_call_all(cari_id=1)
    con = con_ro()
    db_durumlar = {r[0]: r[1] for r in con.execute(
        "SELECT id, durum FROM nexgen_numune_talep WHERE cari_id=1 AND COALESCE(aktif,1)=1"
    ).fetchall()}
    con.close()
    mismatches = []
    for n in d_all.get('liste', []):
        expected = db_durumlar.get(n['id'])
        if n.get('durum') != expected:
            mismatches.append(f'id={n["id"]} exp={expected!r} got={n["durum"]!r}')
    if not mismatches:
        ok('K_durum_canonical_all')
    else:
        fail('K_durum_canonical_all', f'{len(mismatches)} mismatch: {mismatches[:3]}')
except Exception as e:
    fail('K_durum', str(e))

print('\n[L] AR-GE bağlantılı numune expand verisi')
try:
    con = con_ro()
    row_arge = con.execute("""
        SELECT id, arge_test_id, cari_id FROM nexgen_numune_talep
        WHERE cari_id=1 AND COALESCE(aktif,1)=1 AND arge_test_id IS NOT NULL
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    con.close()
    if row_arge:
        nid, arge_id, cari = row_arge[0], row_arge[1], row_arge[2]
        d_all = _service_call_all(cari_id=cari)
        hit = next((n for n in d_all.get('liste', []) if n['id'] == nid), None)
        if hit:
            akt = hit.get('aktif_arge_testi')
            if akt and akt.get('id') == arge_id:
                ok(f'L_arge_expand_present (numune_id={nid}, arge_id={arge_id})')
            else:
                fail('L_arge_expand_present', f'aktif_arge_testi={akt}')
        else:
            fail('L_arge_expand', f'id={nid} listede yok')
    else:
        ok('L_arge_skip (no arge bağlı)')
except Exception as e:
    fail('L_arge', str(e))

print('\n[M] Üretim import bozulmamış')
try:
    from modules.nexgen.cari360_ops_read_service import load_cari360_uretim
    ok('M_uretim_import_ok')
except Exception as e:
    fail('M_uretim_import', str(e))

# SHA AFTER
print('\n[SHA_AFTER]')
with open(DB, 'rb') as f:
    sha_after = hashlib.sha256(f.read()).hexdigest()
if sha_after == SHA_EXPECTED:
    ok('SHA_after_unchanged')
else:
    fail('SHA_after_unchanged', f'SHA changed! {sha_after}')

# Summary
print(f'\n{"="*50}')
print(f'PASS: {len(PASS)}  FAIL: {len(FAIL)}')
if FAIL:
    print('FAILED TESTS:')
    for f_ in FAIL:
        print('  - ' + f_)
    sys.exit(1)
else:
    print('ALL PASS')
