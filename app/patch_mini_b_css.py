# ADIM B: .plan-detay-mini CSS ekle (idempotent)
import io, sys, shutil, time

PATH = r'C:\cps_dev\static\css\hedef.css'
MARKER = '/* === FAZ 4.7 MINI DETAY ==='

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM B zaten uygulanmis')
    sys.exit(0)

CSS = '''

/* === FAZ 4.7 MINI DETAY === */
.plan-detay-mini > td {
  font-size: 12px;
  padding: 6px 12px;
  color: #374151;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
  line-height: 1.65;
}
.plan-detay-mini-line { display: block; }
.plan-detay-mini-arrow { color: #9ca3af; margin-right: 4px; }
.plan-detay-mini-kat {
  font-weight: 600;
  color: #111827;
  margin-right: 6px;
}
.plan-detay-mini-mesaj { color: #9ca3af; font-style: italic; }
.plan-detay-mini-loading,
.plan-detay-mini-error { color: #9ca3af; font-style: italic; }
.plan-detay-mini-error { color: #dc2626; font-style: normal; }
/* === /FAZ 4.7 MINI DETAY === */
'''

bak = PATH + '.bak_pre_mini_b_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(src + CSS)

print('OK: ADIM B mini CSS eklendi (' + str(len(CSS)) + ' byte)')