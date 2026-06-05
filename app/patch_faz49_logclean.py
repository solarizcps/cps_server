# FAZ 4.9 KAPANIS: F2.2 debug loglarini temizle
# Sadece [F2.2 write] log'unu sil
# [CPS LOCAL] PLAN darbogaz F2.2 yuklendi - korunacak
import io, sys, shutil, time

JS_PATH = r'C:\cps_dev\static\js\hedef.js'
MARKER = '/* FAZ 4.9 LOGCLEAN */'

with io.open(JS_PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: log clean zaten uygulanmis')
    sys.exit(0)

# [F2.2 write] log satirini sil
OLD = '''                tr2.setAttribute("data-f22-done", "1");
                try { console.log("[F2.2 write]", k, "yapilan=" + v.yapilan_darbogaz, "kalan=" + v.kalan_darbogaz); } catch (e) {}
            }'''

NEW = '''                tr2.setAttribute("data-f22-done", "1"); /* FAZ 4.9 LOGCLEAN */
            }'''

if OLD not in src:
    print('UYARI: [F2.2 write] log anchor bulunamadi (zaten silinmis olabilir)')
    # Yine de marker ekleyelim ki bir daha calismasin
    OLD2 = 'tr2.setAttribute("data-f22-done", "1");'
    NEW2 = 'tr2.setAttribute("data-f22-done", "1"); /* FAZ 4.9 LOGCLEAN */'
    if OLD2 in src:
        new_src = src.replace(OLD2, NEW2, 1)
    else:
        print('HATA: marker eklenemedi')
        sys.exit(1)
else:
    new_src = src.replace(OLD, NEW, 1)

bak = JS_PATH + '.bak_pre_logclean_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(JS_PATH, bak)
print('Yedek: ' + bak)

with io.open(JS_PATH, 'w', encoding='utf-8') as f:
    f.write(new_src)

azalan = len(src) - len(new_src)
print('OK: log clean uygulandi (' + str(azalan) + ' byte azaldi)')
print('Korunan: [CPS LOCAL] PLAN darbogaz F2.2 yuklendi')