import sys
sys.path.insert(0, r'C:\cps_dev')

from modules.hedef import korgun_v2 as kv2

print('MOCK_MODE:', kv2.MOCK_MODE)
print()
print('=== _sql_get_siparis_listesi ===')
try:
    sip = kv2._sql_get_siparis_listesi()
    print('Donen siparis sayisi:', len(sip))
    for s in sip[:5]:
        print(s)
except Exception as e:
    import traceback
    traceback.print_exc()

print()
print('=== _sql_siparis_listesi_full ===')
try:
    full = kv2._sql_siparis_listesi_full()
    print('Donen siparis sayisi:', len(full))
    for s in full[:5]:
        print(s)
except Exception as e:
    import traceback
    traceback.print_exc()

print()
print('=== get_siparis_listesi (canli) ===')
try:
    g = kv2.get_siparis_listesi()
    print('Donen sayisi:', len(g))
    for s in g[:5]:
        print(s)
except Exception as e:
    import traceback
    traceback.print_exc()