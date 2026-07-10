# -*- coding: utf-8 -*-
"""
NexGen Print Agent — v1.0
=========================
Windows konsolunda çalışan tek yazıcı baskı ajanı.

Akış:
  1. CPS'den PENDING iş alır  (GET /nexgen/api/print-agent/next)
  2. base64 payload'ı bayt'a çevirir
  3. pyserial ile Bluetooth COM portuna bağlanır
  4. TSPL baytları yazar + flush
  5. Başarı veya hatayı CPS'e bildirir
  6. 2 saniye bekler, tekrar dener
  7. Ctrl+C ile düzgün kapanır

Kullanım:
  python app/tools/nexgen_print_agent.py

Config (ortam değişkenleri):
  NEXGEN_PRINT_SERVER_URL   = http://127.0.0.1:8080   (varsayılan)
  NEXGEN_PRINT_AGENT_KEY    = <gizli key>              (zorunlu)
  NEXGEN_PRINT_COM_PORT     = COM7                     (zorunlu)
  NEXGEN_PRINT_BAUDRATE     = 9600                     (varsayılan)
  NEXGEN_PRINT_POLL_SECONDS = 2                        (varsayılan)

Kurulum:
  pip install pyserial requests

NOT: Agent key asla loglanmaz.
"""

import os
import sys
import time
import base64
import signal
import logging
import traceback

# ─────────────────────────────────────────────────────────────
# Loglama — sadece konsol, zaman damgalı
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [AGENT] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger('nexgen_print_agent')

# ─────────────────────────────────────────────────────────────
# Config — ortam değişkenlerinden
# NEXGEN_PRINT_AGENT_KEY  : zorunlu
# NEXGEN_PRINT_COM_PORT   : zorunlu (örn: COM7)
# NEXGEN_PRINT_BAUDRATE   : zorunlu (XP-365B için genellikle 9600)
# NEXGEN_PRINT_SERVER_URL : varsayılan http://127.0.0.1:8080
# NEXGEN_PRINT_POLL_SECONDS: varsayılan 2
# ─────────────────────────────────────────────────────────────
SERVER_URL   = os.environ.get('NEXGEN_PRINT_SERVER_URL', 'http://127.0.0.1:8080').rstrip('/')
AGENT_KEY    = os.environ.get('NEXGEN_PRINT_AGENT_KEY',  '')
COM_PORT     = os.environ.get('NEXGEN_PRINT_COM_PORT',   '')
_BAUDRATE_STR = os.environ.get('NEXGEN_PRINT_BAUDRATE',  '')
BAUDRATE     = int(_BAUDRATE_STR) if _BAUDRATE_STR else 0
POLL_SECS    = float(os.environ.get('NEXGEN_PRINT_POLL_SECONDS', '2'))

# ─────────────────────────────────────────────────────────────
# Bağımlılık kontrolleri
# ─────────────────────────────────────────────────────────────
def _bagimlilik_kontrol():
    hatalar = []

    try:
        import serial  # noqa: F401
    except ImportError:
        hatalar.append("pyserial kurulu değil. Çözüm: pip install pyserial")

    try:
        import requests  # noqa: F401
    except ImportError:
        hatalar.append("requests kurulu değil. Çözüm: pip install requests")

    if not AGENT_KEY:
        hatalar.append("NEXGEN_PRINT_AGENT_KEY ortam değişkeni tanımlanmadı.")

    if not COM_PORT:
        hatalar.append("NEXGEN_PRINT_COM_PORT ortam değişkeni tanımlanmadı. (Örn: COM7)")

    if not BAUDRATE:
        hatalar.append(
            "NEXGEN_PRINT_BAUDRATE ortam değişkeni tanımlanmadı. "
            "XP-365B fabrika varsayılanı genellikle 9600 — "
            "NEXGEN_PRINT_TESPIT.py ile doğrulayın."
        )

    return hatalar

# ─────────────────────────────────────────────────────────────
# HTTP istemcisi
# ─────────────────────────────────────────────────────────────
_HEADERS = None


def _headers():
    global _HEADERS
    if _HEADERS is None:
        _HEADERS = {'X-NexGen-Agent-Key': AGENT_KEY}
    return _HEADERS


def _sonraki_is_al():
    """GET /nexgen/api/print-agent/next — PENDING iş varsa döner."""
    import requests as _req
    url = f"{SERVER_URL}/nexgen/api/print-agent/next"
    try:
        r = _req.get(url, headers=_headers(), timeout=10)
        r.raise_for_status()
        return r.json()
    except _req.exceptions.ConnectionError:
        log.warning("CPS sunucusuna bağlanılamadı: %s", SERVER_URL)
        return None
    except _req.exceptions.Timeout:
        log.warning("CPS isteği zaman aşımına uğradı.")
        return None
    except Exception as e:
        log.error("_sonraki_is_al hata: %s", e)
        return None


def _basari_bildir(job_id):
    """POST /nexgen/api/print-agent/<job_id>/success"""
    import requests as _req
    url = f"{SERVER_URL}/nexgen/api/print-agent/{job_id}/success"
    try:
        r = _req.post(url, headers=_headers(), timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("Başarı bildirimi gönderilemedi job_id=%s: %s", job_id, e)
        return False


def _hata_bildir(job_id, hata_mesaj):
    """POST /nexgen/api/print-agent/<job_id>/fail"""
    import requests as _req
    url = f"{SERVER_URL}/nexgen/api/print-agent/{job_id}/fail"
    try:
        r = _req.post(
            url,
            headers={**_headers(), 'Content-Type': 'application/json'},
            json={'hata': str(hata_mesaj)[:500]},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("Hata bildirimi gönderilemedi job_id=%s: %s", job_id, e)
        return False

# ─────────────────────────────────────────────────────────────
# Yazıcı: pyserial ile COM portuna yaz
# ─────────────────────────────────────────────────────────────
def _yazici_gonder(payload_bytes):
    """
    TSPL baytlarını Bluetooth COM portuna yazar.

    Dönüş: (True, byte_sayisi) veya (False, hata_mesaji)
    """
    import serial as _serial

    if not COM_PORT:
        return False, "COM_PORT tanımlanmamış"
    if not BAUDRATE:
        return False, "BAUDRATE tanımlanmamış"

    try:
        port = _serial.Serial(
            port=COM_PORT,
            baudrate=BAUDRATE,
            bytesize=_serial.EIGHTBITS,
            parity=_serial.PARITY_NONE,
            stopbits=_serial.STOPBITS_ONE,
            timeout=5,
            write_timeout=10,
        )
    except _serial.SerialException as e:
        return False, f"COM port açılamadı ({COM_PORT}): {e}"
    except Exception as e:
        return False, f"Port hatası: {e}"

    try:
        yazilan = port.write(payload_bytes)
        port.flush()
        return True, yazilan
    except _serial.SerialTimeoutException:
        return False, f"Yazıcı yanıt vermedi (timeout) — {COM_PORT}"
    except Exception as e:
        return False, f"Yazma hatası: {e}"
    finally:
        try:
            port.close()
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────
# Test baskısı — gerçek veri olmadan da test edilebilir
# ─────────────────────────────────────────────────────────────
def _test_baskisi():
    """
    Gerçek etiket verisi olmadan basit TSPL testi.
    Komut satırından: python nexgen_print_agent.py --test
    """
    from datetime import datetime
    simdi = datetime.now().strftime('%d.%m.%Y %H:%M')
    tspl_lines = [
        "SIZE 40 mm,80 mm",
        "GAP 3 mm,0 mm",
        "DIRECTION 0",
        "REFERENCE 0,0",
        "CODEPAGE 857",
        "SPEED 4",
        "DENSITY 10",
        "CLS",
        "BAR 0,0,320,30",
        'REVERSE 6,4,308,24,"4",0,1,1,"NEXGEN TEST"',
        f'TEXT 6,36,"4",0,1,1,"AGENT v1.0"',
        "BAR 0,62,320,1",
        f'TEXT 6,70,"3",0,1,1,"{simdi}"',
        f'TEXT 6,88,"3",0,1,1,"COM: {COM_PORT}"',
        "BAR 0,106,320,1",
        'BARCODE 10,114,"128",55,1,0,2,4,"TEST-CODE128-001"',
        'TEXT 6,182,"3",0,1,1,"TEST-CODE128-001"',
        "PRINT 1,1",
    ]
    tspl_str = "\r\n".join(tspl_lines) + "\r\n"
    payload  = tspl_str.encode('cp857', errors='replace')

    log.info("Test baskısı gönderiliyor — %d bayt → %s", len(payload), COM_PORT)
    tamam, sonuc = _yazici_gonder(payload)
    if tamam:
        log.info("TEST BASISI BASARILI — %s bayt yazıldı.", sonuc)
    else:
        log.error("TEST BASISI BASARISIZ — %s", sonuc)
    return tamam

# ─────────────────────────────────────────────────────────────
# Ana döngü
# ─────────────────────────────────────────────────────────────
_calisıyor = True


def _dur(signum, frame):
    global _calisıyor
    log.info("Durdurma sinyali alındı — agent kapatılıyor...")
    _calisıyor = False


def _is_isle(is_data):
    """Tek bir print job'ı işler."""
    job_id    = is_data['job_id']
    etiket_id = is_data.get('etiket_id', '?')
    payload_b64 = is_data.get('payload_base64', '')

    log.info("İş alındı — job_id=%s etiket_id=%s", job_id, etiket_id)

    # base64 → bytes
    try:
        payload_bytes = base64.b64decode(payload_b64)
    except Exception as e:
        hata = f"base64 çözme hatası: {e}"
        log.error(hata)
        _hata_bildir(job_id, hata)
        return

    log.info("Payload boyutu: %d bayt", len(payload_bytes))

    # Yazıcıya gönder
    tamam, sonuc = _yazici_gonder(payload_bytes)

    if tamam:
        log.info("Baskı başarılı — job_id=%s  %s bayt yazıldı.", job_id, sonuc)
        _basari_bildir(job_id)
    else:
        log.error("Baskı başarısız — job_id=%s  hata: %s", job_id, sonuc)
        _hata_bildir(job_id, str(sonuc))


def ana_dongu():
    global _calisıyor

    signal.signal(signal.SIGINT, _dur)
    signal.signal(signal.SIGTERM, _dur)

    log.info("NexGen Print Agent başlatıldı.")
    log.info("Sunucu : %s", SERVER_URL)
    log.info("COM    : %s @ %d baud", COM_PORT, BAUDRATE)
    log.info("Pollng : %.1f sn", POLL_SECS)
    log.info("(Çıkmak için Ctrl+C)")

    hata_sayac = 0
    MAX_HATA   = 10  # art arda bu kadar hata olursa 30 sn bekle

    while _calisıyor:
        try:
            veri = _sonraki_is_al()

            if veri is None:
                # Sunucuya ulaşılamadı
                hata_sayac += 1
                if hata_sayac >= MAX_HATA:
                    log.warning("Art arda %d hata — 30 sn bekleniyor...", hata_sayac)
                    time.sleep(30)
                    hata_sayac = 0
                else:
                    time.sleep(POLL_SECS)
                continue

            hata_sayac = 0

            if veri.get('job_id') is None:
                # Kuyruk boş
                time.sleep(POLL_SECS)
                continue

            _is_isle(veri)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("Beklenmeyen hata: %s", e)
            log.debug(traceback.format_exc())
            time.sleep(POLL_SECS)

    log.info("Agent durduruldu.")


# ─────────────────────────────────────────────────────────────
# Giriş noktası
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Bağımlılık kontrolü
    hatalar = _bagimlilik_kontrol()
    if hatalar:
        print("\n[HATA] Agent başlatılamıyor:\n")
        for h in hatalar:
            print(f"  - {h}")
        print()
        print("Ortam değişkenleri:")
        print("  set NEXGEN_PRINT_AGENT_KEY=<gizli>")
        print("  set NEXGEN_PRINT_COM_PORT=COM7")
        print("  set NEXGEN_PRINT_BAUDRATE=9600")
        print("  set NEXGEN_PRINT_SERVER_URL=http://127.0.0.1:8080")
        print()
        sys.exit(1)

    # --test modu
    if '--test' in sys.argv:
        print("\n--- TEST BASISI MODU ---\n")
        tamam = _test_baskisi()
        sys.exit(0 if tamam else 1)

    # Normal çalışma
    ana_dongu()
