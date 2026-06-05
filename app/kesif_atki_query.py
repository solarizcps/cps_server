import sqlite3
c = sqlite3.connect(r'C:\cps_dev\mock_data.db')

# Tip kontrolu - emir_no kolonunun tipi
print('=== Schema yenileme ===')
for r in c.execute("SELECT sql FROM sqlite_master WHERE name='emir_alt_proses'"):
    print(r[0])

print()
print('=== ADIM A2 SQL aynen test - emir_no=110649 (string) ===')
for r in c.execute("""
    SELECT
        ap.proses_adi AS proses_adi,
        COALESCE(SUM(uk.miktar), 0) AS yapilan
    FROM emir_alt_proses ap
    LEFT JOIN uretim_kayit uk
      ON CAST(uk.emir_no AS TEXT) = ap.emir_no
     AND LOWER(TRIM(uk.proses_adi)) = LOWER(TRIM(ap.proses_adi))
     AND uk.onay_durum IN ('onaylandi','bekliyor')
    WHERE ap.emir_no = ?
      AND ap.aktif = 1
    GROUP BY ap.proses_adi, ap.siralama, ap.id
    ORDER BY ap.siralama, ap.id
""", ('110649',)):
    print(r)

print()
print('=== Same query, emir_no integer 110649 ===')
for r in c.execute("""
    SELECT
        ap.proses_adi AS proses_adi,
        COALESCE(SUM(uk.miktar), 0) AS yapilan
    FROM emir_alt_proses ap
    LEFT JOIN uretim_kayit uk
      ON CAST(uk.emir_no AS TEXT) = ap.emir_no
     AND LOWER(TRIM(uk.proses_adi)) = LOWER(TRIM(ap.proses_adi))
     AND uk.onay_durum IN ('onaylandi','bekliyor')
    WHERE ap.emir_no = ?
      AND ap.aktif = 1
    GROUP BY ap.proses_adi, ap.siralama, ap.id
    ORDER BY ap.siralama, ap.id
""", (110649,)):
    print(r)

print()
print('=== Direct check - emir_alt_proses for 110649 ===')
for r in c.execute("SELECT id, emir_no, proses_adi, aktif FROM emir_alt_proses WHERE emir_no='110649' AND aktif=1"):
    print(r)

c.close()
print('TAMAM')