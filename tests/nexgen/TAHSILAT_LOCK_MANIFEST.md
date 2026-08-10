# TAHSILAT LOCK MANIFEST

Permanent kritik davranış envanteri — Tahsilat CEK/Vade regression LOCK'ları.

---

## TAHSILAT-CEK-VADE-LOCK

| Alan | Değer |
|------|-------|
| **LOCK NAME** | TAHSILAT-CEK-VADE-LOCK |
| **İş Kuralı** | CEK ödeme tipinde `cek_vade_gun` canonical olarak `nexgen_planlama_siparis.vade_gun` kolonuna yazılır. JSON-only kalamaz. |
| **Canonical Kaynak** | `nexgen_planlama_siparis.vade_gun` |
| **Gerçek Kullanıcı Senaryosu** | PZM-2026-0222, CEK, 185 gün — Erhan Tahsilat ekranında Onaylanan Vade = 185 |
| **Exact Regression Test** | `test_insert_cek_185_vade_gun_canonical`, `test_update_cek_vade_gun_canonical` |
| **Test Dosyası** | `tests/nexgen/test_pzm_cek_vade_db_lock.py` |
| **Beklenen Sonuç** | INSERT/UPDATE sonrası `SELECT vade_gun FROM nexgen_planlama_siparis` → `185` (veya güncellenen değer) |
| **Kapanış Kanıtı** | PZM-2026-0222, CEK 185 gün, DB `vade_gun=185`, kullanıcı ekran onayı PASS |

**Koruma regressionları (manifest referansı):**
- NAKIT → `test_insert_nakit_vade_gun_zero` (`test_pzm_cek_vade_db_lock.py`)
- VADELI → `test_insert_vadeli_vade_gun_preserved` (`test_pzm_cek_vade_db_lock.py`)
- Validation layer → `tests/nexgen/test_pzm_cek_vade_gun.py`

---

## TAHSILAT-HEDEF-VADE-LOCK

| Alan | Değer |
|------|-------|
| **LOCK NAME** | TAHSILAT-HEDEF-VADE-LOCK |
| **İş Kuralı** | `hedef_vade_tarihi = gercek_sevk_tarihi + onaylanan_vade_gun` (ISO format) |
| **Canonical Kaynak** | `acik_planlar()` response → `hedef_vade_tarihi` |
| **Gerçek Kullanıcı Senaryosu** | PZM-2026-0222 + MSV-2026-0166: sevk 2026-08-10, vade 185 gün → hedef 2027-02-11 |
| **Exact Regression Test** | `test_cek_hedef_vade_185_gun` |
| **Test Dosyası** | `tests/nexgen/test_mo_tahsilat_regression.py` (`TestAcikPlanlarHedefVade`) |
| **Beklenen Sonuç** | `gercek_sevk_tarihi='2026-08-10'`, `onaylanan_vade_gun=185`, `hedef_vade_tarihi='2027-02-11'` |
| **Kapanış Kanıtı** | Erhan Tahsilat: Gerçek Sevk 10.08.2026, Hedef Vade 2027-02-11, ekran onayı PASS |

---

## TAHSILAT-SEVK-SNAPSHOT-LOCK

| Alan | Değer |
|------|-------|
| **LOCK NAME** | TAHSILAT-SEVK-SNAPSHOT-LOCK |
| **İş Kuralı** | Sevk anında 3 alan ayrı ayrı snapshot: `birim_fiyat_snapshot`, `para_birimi_snapshot`, `fiyat_kaynagi`. Kalem net fiyat varsa `fiyat_kaynagi='KALEM_NET'`. |
| **Canonical Kaynak** | `mo_sevkiyat_service._coz_sevk_fiyat_snapshot()` satır 212 |
| **Gerçek Kullanıcı Senaryosu** | PZM-2026-0222 sevkiyat fiyat snapshot zinciri |
| **Exact Regression Test** | `test_coz_sevk_fiyat_snapshot_uc_alan`, `test_sevk_kalem_db_snapshot_uc_alan` |
| **Test Dosyası** | `tests/nexgen/test_mo_tahsilat_regression.py` (`TestRegressionSevkSnapshotLock`) |
| **Beklenen Sonuç** | `birim_fiyat_snapshot=2.0`, `para_birimi_snapshot='USD'`, `fiyat_kaynagi='KALEM_NET'` |
| **Kapanış Kanıtı** | E2E sevk snapshot doğrulandı, regression PASS |

---

## TAHSILAT-GERCEK-SEVK-LOCK

| Alan | Değer |
|------|-------|
| **LOCK NAME** | TAHSILAT-GERCEK-SEVK-LOCK |
| **İş Kuralı** | `SEVK_EDILDI` sevkiyat varsa `gercek_sevk_tarihi` = MIN(sevk_tarihi). Sevkiyat yoksa `None`. |
| **Canonical Kaynak** | `mo_sevkiyat_service.gercek_sevk_tarihi()`, `acik_planlar()` |
| **Gerçek Kullanıcı Senaryosu** | MSV-2026-0166 SEVK_EDILDI → `gercek_sevk_tarihi=2026-08-10` |
| **Exact Regression Test** | `test_sevk_edildi_gercek_sevk_tarihi`, `test_sevk_yok_gercek_sevk_none` |
| **Test Dosyası** | `tests/nexgen/test_mo_tahsilat_regression.py` (`TestGercekSevkLock`) |
| **Beklenen Sonuç** | Sevk var → ISO tarih; sevk yok → `None` |
| **Kapanış Kanıtı** | PZM-2026-0222 / MSV-2026-0166, Gerçek Sevk 10.08.2026, ekran PASS |

---

## TAHSILAT-TCMB-SATIS-LOCK

| Alan | Değer |
|------|-------|
| **LOCK NAME** | TAHSILAT-TCMB-SATIS-LOCK |
| **İş Kuralı** | Kur kaynağı `sistem_kur.Satis`. MerkezKur fallback YOK. Gelecek güne fallback YOK. Kur yoksa fail. |
| **Canonical Kaynak** | `sistem_kur.Satis` via `mo_tahsilat_kur_service.tcmb_satis_kur_oku()` |
| **Gerçek Kullanıcı Senaryosu** | Tahsilat TRY hedef hesabı TCMB Satış üzerinden |
| **Exact Regression Test** | `test_e_satis_not_merkez_kur`, `test_f5_no_future_fallback`, `test_validation_satis_null` |
| **Test Dosyası** | `tests/nexgen/test_mo_tahsilat_kur_service.py`, `tests/nexgen/test_mo_tahsilat_kayit_tcmb_write.py` |
| **Beklenen Sonuç** | `tcmb_satis_kur` = Satis kolonu; MerkezKur kullanılmaz; eksik kur → `MoTahsilatKurError` |
| **Kapanış Kanıtı** | 107/107 Tahsilat regression PASS, TCMB write integration PASS |

---

## E2E Kapanış Özeti (PZM-2026-0222)

| Kanıt | Değer |
|-------|-------|
| Sipariş | PZM-2026-0222 |
| Ödeme | CEK |
| Onaylanan Vade | 185 gün |
| Sevkiyat | MSV-2026-0166, SEVK_EDILDI |
| Gerçek Sevk | 2026-08-10 |
| Hedef Vade | 2027-02-11 |
| Kullanıcı Ekran Onayı | PASS |

---

## Master Runner Kapsamı

Unit modülleri (`app/_browser_tahsilat_regression_runner.py`):
- `tests.nexgen.test_mo_tahsilat_regression`
- `tests.nexgen.test_mo_tahsilat_kur_service`
- `tests.nexgen.test_mo_tahsilat_kayit_tcmb_write`
- `tests.nexgen.test_pzm_cek_vade_gun`
- `tests.nexgen.test_pzm_cek_vade_db_lock`
- `tests.nexgen.test_mo_vade_kontrol_service`

Browser scriptleri (korunur):
- `app/_browser_faz_tahsilat_sevk_ui_1.py`
- `app/_browser_faz_tahsilat_tcmb_try_ui_1.py`
- `browser_ui_lock` (popup dismiss helper dahil)

**Not:** Bu 3 browser dosyası şu an untracked — controlled commit'te track edilmeli.
