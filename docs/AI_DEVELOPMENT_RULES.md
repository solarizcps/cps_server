# AI GELİŞTİRME KURALLARI — Solariz CPS

Bu kurallar Claude / AI asistan ile yapılan geliştirme sürecinde uygulanır.

## 1. Önce RECON.

Herhangi bir kod değişikliğinden önce ilgili dosyalar, DB şeması ve mevcut davranış analiz edilir.
"Bence şöyle olmalı" yerine "gerçekte nasıl çalışıyor" sorusu sorulur.

## 2. Kök sebep bulunmadan kod yok.

Bir bug raporlandığında doğrudan fix yazmak yerine:
- Hangi endpoint/fonksiyon etkileniyor?
- DB'de hangi değerler bozuk?
- Sorun frontend mi backend mi?

sorularına yanıt bulunur. Sonra patch yazılır.

## 3. Çalışan CORE değişmez.

Stabil tag ile işaretlenmiş alan refactor, "iyileştirme" veya yeniden yazım için açılmaz.
Sadece tespit edilen somut bug için minimum değişiklik yapılır.

## 4. Minimum patch.

Her fix mümkün olan en az sayıda satırı değiştirir.
Geniş refactor, taşıma veya yeniden yapılandırma ayrı bir onay gerektirir.

## 5. Her değişiklik sonrası endpoint test.

```
/enjeksiyon              → 200
/planlama/operasyon-raporu → 200
/yonetim/kalip-yonetimi  → 200
```

Bu üç endpoint her commit öncesi kontrol edilir.

## 6. Commit öncesi: git diff kontrol.

`git diff --stat` çalıştırılır. Beklenen dosya sayısından fazlası varsa **DUR**.
Yanlışlıkla staging'e giren dosya commit edilmez.

## 7. Stable tag sonrası: mimari bozulmaz.

Tag sonrası yapılan değişiklikler:
- Mevcut snapshot mantığını bozmaz
- A/B bağımsızlığını bozmaz
- Geçmiş üretim değerlerini değiştirmez
- Fire veya operasyon raporu formüllerini sessizce değiştirmez

## 8. YASAK listesi (her zaman geçerli)

- DB reset / tablo silme
- Migration olmadan şema değişikliği
- Yetki sistemini bypass etme (`@login_required`'a düşürme)
- `git push --force` (main'e)
- Onaysız büyük refactor
- "Daha iyi olur" gerekçesiyle çalışan kodu değiştirme
