# D5 FAZ C.5 P6 - CONFIG + AUDIT IYILESTIRME RAPORU

**Tarih:** 18.05.2026 09:30
**Sprint:** D5 Faz C.5 / P6: Config + Audit
**Sonuc:** BASARILI - sifir saha kesintisi, sifir kullanici-gorunur davranis degisimi

## Yapilan (3 degisiklik)

### 1. config.py - USE_CPS_NATIVE_PROSES flag
- Config sinifi icine eklendi (4-bosluk indent)
- Deger: **False**
- Amac: P4 lazy hook + C.8 FLAG flip oncesi altyapi
- Runtime erisilebilir: hasattr(Config, 'USE_CPS_NATIVE_PROSES') = True

### 2. _sablon_uygula_internal INSERT - sablon_id ekle
- L2815 INSERT statement: 7 kolon -> 8 kolon
- Yeni kolon: sablon_id (mevcut tablo semasi)
- Yeni placeholder: ?
- Etki: trigger ve manuel /sablon/uygula INSERT'leri artik sablon_id yazar
- Eski kayitlar dokunulmaz (NULL kalir, P6 oncesi davranis korunur)

### 3. /sablon/geri-al kaynak pattern - CPS_TRIGGER kapsami
- L1159-1172: cps_trigger_pattern eklendi
- 3 SQL'de AND kaynak LIKE ? -> AND (kaynak LIKE ? OR kaynak LIKE ?)
- Yeni bind: (sablon_kaynak_pattern, cps_trigger_pattern)
- Sablon_id verilirse: cps_trigger_pattern 'CPS_TRIGGER%:<sablon_adi>'
- Etki: artik CPS_TRIGGER_C5 / _C6 / ... kayitlari da geri alinabilir
- Korunan: manuel, 5055_IMPORT, LEGACY_5055 kayitlari hala dokunulmaz

## Hash karsilastirmasi

| Dosya | Onceki (P5) | Yeni (P6) |
|-------|-------------|-----------|
| config.py | D8121045BB25B6D5 | **2F6BFFBAECC77EF1** |
| hedef/routes.py | DD83F35FAC5CCEC1 | **7EAC892167AFEAD1** |
| personel_giris/routes.py | 41B220D201B0E1F8 | 41B220D201B0E1F8 (DOKUNULMAZ) |

## Atomic move sirasi

1. config.py move (0.23 ms) -> Flask reload 5 sn -> health 200
2. routes.py move (0.25 ms) -> Flask reload 5 sn -> 5/5 smoke PASS

## Test sonuclari

### Pre-P6 verify
- Config attribute test (importlib): hasattr=True, value=False, korunan attr'lar 6/6
- AST + py_compile: PASS
- Marker check: 6 yeni + 12 korunan PASS

### Post-P6 canli verify
- **A:** trigger ile 4 yeni INSERT (111005)
  - id 2278-2281, kaynak=CPS_TRIGGER_C5:Atki LCW, **sablon_id=1** (P6 oncesi NULL'du)
- **B:** /sablon/geri-al sonucu:
  - silinen_proses_sayisi: 4 (P6 oncesi 0 olurdu)
  - etkilenen_emir_sayisi: 1
  - HTTP 200, ok=true
- **Final DB:**
  - emir_alt_proses[111005] aktif=1: 0
  - emir_alt_proses[111005] aktif=0: 8 (4 P5 + 4 P6, audit korundu)
  - CPS_TRIGGER aktif kayit GLOBAL: 0
  - uretim_kayit: 1380 (dokunulmadi)

### Endpoint smoke (5/5 PASS)
- /personel-giris/health: 200
- /personel-giris/prosesler/110393: CPS_NATIVE
- /hedef/sablon/liste: 200
- /hedef/sablon-eslesme/liste: 200
- /hedef/sablon/trigger-test/111005: JSON dry_run=True

## Saha etkisi

- Patch oncesi uretim_kayit: 1380
- Patch sirasinda yeni kayit: 0
- DB integrity: ok
- Saha kesintisi: 0

## Sonraki adim

**P4** - personel_giris lazy hook (DOKUNULMAZ alan, YUKSEK risk)
- USE_CPS_NATIVE_PROSES flag mevcut, False
- Lazy hook bu flag'i okuyacak, False oldugu icin tetiklenmeyecek
- Sahaya etki yok
- Tasarim onayi ve sprint sirasi Adem'den ozel onay gerektirir

**C.8** - FLAG flip (gelecek sprint, P4 sonrasi)

## Rollback yedek
- config.py.YEDEK_D5_FAZC5_P6_20260518_093009
- routes.py.YEDEK_D5_FAZC5_P6_20260518_093009