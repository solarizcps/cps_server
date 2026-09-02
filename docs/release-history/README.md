# CPS Geliştirme ve Sürüm Geçmişi (V1)

Bu dizin, Solariz CPS geliştirmelerinin dosya tabanlı canonical kayıtlarını tanımlar.

## Yapı

| Konum | Amaç |
|-------|------|
| `changes/records/<module>/<PHASE_CODE>.toml` | Tam faz kaydı (iş kuralları, test, commit) |
| `changes/fragments/<module>.<PHASE_CODE>.release` | Towncrier changelog satırı |
| `docs/release-history/schema.toml` | Şema ve allowlist tanımı |
| `tools/validate_release_history.py` | Salt okunur doğrulama |

## Durum değerleri

`TASLAK`, `TEST`, `ONAYLANDI`, `KILITLI`, `GERI_ALINDI`

## Doğrulama

```powershell
python tools/validate_release_history.py
```

Towncrier (dev-only, izole venv):

```powershell
python -m towncrier build --version unreleased
python -m towncrier check --compare-with HEAD
```

## V2

CPS read-only ekranı (`/yonetim/surum-gecmisi`) bu kayıtları okuyacak; V1 yalnız altyapı kurar.

## V2 güvenlik limitleri (runtime loader)

`app/services/release_history_service.py` aşağıdaki sabit limitleri uygular:

| Sabit | Değer | Davranış |
|-------|-------|----------|
| `MAX_RECORDS` | 1000 | Deterministik sıralı ilk 1000 aday dosya işlenir; fazlası skip |
| `MAX_TOML_BYTES` | 256 KiB | Limit üstü dosya skip |
| `MAX_TEXT_LENGTH` | 20_000 | Metin alanları güvenli kırpma |
| `MAX_LIST_ITEMS` | 500 | Liste alanları güvenli kırpma |

Symlink, root dışı `resolve()` yolu ve normal olmayan dosyalar skip edilir. Skip/hata durumunda gerçek dosya yolu UI'ya yansımaz.
