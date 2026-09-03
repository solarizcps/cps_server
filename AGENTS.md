# CPS Agent Kuralları

Bu depoda çalışmadan önce bu dosyayı ve `docs/AI_DEVELOPMENT_RULES.md` dosyasını okuyun.

## Zorunlu süreç

1. İlgili modülün son kayıtlarını `changes/records/<module>/` altından oku.
2. Kilitli kuralları (`locked_rules`) çıkar; değiştirmek için Adem onayı gerekir.
3. Minimum patch yap; global sidebar/base.html değiştirme.
4. Testleri çalıştır.
5. Her anlamlı faz için TOML + fragment ekle.
6. `python tools/validate_release_history.py` PASS olmadan faz tamamlandı deme.
7. Committe yalnız ilgili dosyaları stage et.
8. Deploy manifest doğrulanmadan CANLIDA deme.
9. Kanıtsız kaydı KILITLI yapma.
10. Commit bekleyen iş için `verified_uncommitted` kaydı kullan; KILITLI yasak.

## Release history

- Kayıtlar: `changes/records/<module>/<PHASE>.toml`
- Fragment: `changes/fragments/<module>.<PHASE>.release`
- Şema: `docs/release-history/schema.toml`
- Validator: `tools/validate_release_history.py`
- Deploy state: `tools/release_state.py` → `var/release/deployment_state.json`

## Pre-commit

```powershell
powershell -File tools/install_release_hooks.ps1
```

Production dosyası commit edilirken eşleşen release kaydı zorunludur.
