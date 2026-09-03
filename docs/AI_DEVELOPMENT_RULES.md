# CPS AI Geliştirme Kuralları

## Amaç

CPS geliştirme geçmişi canonical, doğrulanabilir ve otomatik push/deploy durumu ile takip edilir.
AI ajanları manuel hatırlatma gerektirmeden aynı süreci izler.

## Kayıt türleri

### commit
- `commit_sha` zorunlu (40 karakter Git SHA)
- `related_commits` ile destek commitleri gruplanır
- Test kanıtı yoksa `ONAYLANDI`; pytest kanıtı varsa `KILITLI`
- Deploy kanıtı yoksa `DEPLOYMENT_UNKNOWN`

### verified_uncommitted
- Commit henüz yok; working tree doğrulandı
- `worktree_fingerprint`, `verification_date`, `verification_evidence` zorunlu
- Status yalnız `TEST` veya `ONAYLANDI`
- `KILITLI` ve `CANLIDA` yasak
- Fingerprint değişince kayıt `NEEDS_REVIEW` olarak işaretlenmeli

## Faz adlandırma

- Gerçek faz kodu varsa onu kullan (ör. `ATP_U3C_MANUAL_REORDER_API`)
- Yoksa açıklayıcı `BACKFILL_*` veya `UNCOMMITTED_*` kullan
- Aynı iş kuralını tek belirsiz kayıtta birleştirme

## Commit politikası

1. Yalnız ilgili TOML, fragment ve gerekli metadata stage et
2. `_audit_out`, temp DB, screenshot commit etme
3. Otomatik push/deploy yapma
4. Canonical DB'ye yazma

## Test kapısı

```bash
python tools/validate_release_history.py
python -m pytest tests/tools/test_validate_release_history_v1.py tests/tools/test_release_history_ui_v2.py -q
python tools/release_state.py
```

## Deploy entegrasyonu

Pazartesi deploy komutu çalıştırıldığında `tools/record_deploy_event.py` (gelecek entegrasyon) şunları yazar:

- deployment commit SHA
- tarih/saat
- hedef server etiketi
- deploy yapan kullanıcı
- restart yapıldı mı
- HTTP smoke sonucu
- migration sonucu
- rollback commit (varsa)

Manifest: `var/release/deployment_manifest.json` (Git'e alınmaz).

`DEPLOYED_VERIFIED` yalnız manifest SHA = server HEAD ve HTTP smoke PASS ise.

## Kilitli kural değişikliği

`locked_rules` alanındaki kurallar Adem'in açık onayı olmadan değiştirilemez.
