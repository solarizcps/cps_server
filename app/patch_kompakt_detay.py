# Patch: Kompakt detay panel CSS (sadece hedef.css)
import io, sys, shutil, time

PATH = r'C:\cps_dev\static\css\hedef.css'
MARKER = '/* === FAZ 4.7 KOMPAKT DETAY PANEL ==='

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: kompakt detay panel CSS zaten var')
    sys.exit(0)

CSS = '''

/* === FAZ 4.7 KOMPAKT DETAY PANEL === */
/* Container: max-height + scroll */
.pdv3-icerik {
  max-height: 280px !important;
  overflow-y: auto !important;
  padding: 10px 14px !important;
  animation-duration: 0.15s !important;
}

/* Meta grid: ust bilgi kompakt */
.pdv3-meta {
  padding: 8px 10px !important;
  gap: 6px 12px !important;
  margin-bottom: 8px !important;
}
.pdv3-meta-item .label { font-size: 9px !important; }
.pdv3-meta-item .val { font-size: 12px !important; }
.pdv3-meta-item .val.mono { font-size: 11px !important; }
.pdv3-meta-item .breakdown { font-size: 10px !important; }

/* TAKILDI bandi */
.pdv3-takildi {
  padding: 6px 10px !important;
  margin-bottom: 6px !important;
  gap: 8px !important;
}
.pdv3-takildi-ikon { font-size: 14px !important; }
.pdv3-takildi-etiket { font-size: 10px !important; padding: 2px 6px !important; }
.pdv3-takildi-yer { font-size: 12px !important; }
.pdv3-takildi-zaman { font-size: 10px !important; }

/* ATKI/GOVDE bloklari */
.pdv3-blok {
  padding: 8px 10px !important;
  margin-bottom: 6px !important;
}
.pdv3-blok-baslik {
  margin-bottom: 6px !important;
  gap: 8px !important;
}
.pdv3-blok-ikon { font-size: 14px !important; }
.pdv3-blok-ad { font-size: 12px !important; }
.pdv3-blok-emir { font-size: 11px !important; }
.pdv3-blok-model { font-size: 11px !important; }

/* Proses grid */
.pdv3-proses-grid { gap: 4px !important; }
.pdv3-proses {
  padding: 5px 8px !important;
}
.pdv3-proses-head {
  margin-bottom: 3px !important;
  gap: 6px !important;
}
.pdv3-ikon {
  width: 18px !important;
  height: 18px !important;
  font-size: 11px !important;
}
.pdv3-proses-adi { font-size: 12px !important; }
.pdv3-rozet { font-size: 9px !important; padding: 1px 5px !important; }
.pdv3-bar-wrap { height: 3px !important; margin: 2px 0 !important; }
.pdv3-detay { font-size: 10px !important; }
.pdv3-detay-kaynak { font-size: 9px !important; }

/* Ana emir secondary (gri kutu altta) */
.pdv3-ana-secondary {
  padding: 6px 10px !important;
  margin-top: 6px !important;
}
.pdv3-ana-baslik {
  font-size: 10px !important;
  margin-bottom: 4px !important;
}
.pdv3-ana-baslik small { font-size: 10px !important; }
.pdv3-ana-satirlar { gap: 1px !important; }
.pdv3-ana-proses {
  font-size: 11px !important;
  padding: 1px 0 !important;
  gap: 6px !important;
}
.pdv3-ana-zaman { font-size: 9px !important; }

/* Bos / loading / error mesajlar */
.pdv3-empty,
.pdv3-loading,
.pdv3-error {
  padding: 8px !important;
  font-size: 11px !important;
}

/* Scrollbar - hafif gorunsun */
.pdv3-icerik::-webkit-scrollbar { width: 6px; }
.pdv3-icerik::-webkit-scrollbar-track { background: transparent; }
.pdv3-icerik::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}
.pdv3-icerik::-webkit-scrollbar-thumb:hover { background: #9ca3af; }
/* === /FAZ 4.7 KOMPAKT DETAY PANEL === */
'''

# Yedek
bak = PATH + '.bak_pre_kompakt_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(src + CSS)

print('OK: kompakt detay panel CSS eklendi (' + str(len(CSS)) + ' byte)')