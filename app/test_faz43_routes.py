import sys
sys.path.insert(0, r"C:\cps_dev")
from app import app

print("=" * 60)
print("KAYITLI ROUTE'LAR (FAZ 4.3 yeni eklenenler)")
print("=" * 60)
yeni = []
mevcut = []
for rule in app.url_map.iter_rules():
    if "ustaya-gonder" in str(rule) or "/api/gorevler" in str(rule) or "/api/gorev/" in str(rule):
        yeni.append(f"  [YENI] {rule.methods} {rule.rule}")
    elif "karar-masasi" in str(rule) or "/usta" in str(rule):
        mevcut.append(f"  [MEV.] {rule.methods} {rule.rule}")

print("\nYENI EKLENEN ENDPOINTLER:")
for r in yeni:
    print(r)

print(f"\nMEVCUT ETKILENMEYEN ROUTE'LAR ({len(mevcut)}):")
for r in mevcut:
    print(r)

print(f"\n[OK] Toplam yeni: {len(yeni)}, mevcut: {len(mevcut)}")