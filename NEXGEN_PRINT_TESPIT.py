# -*- coding: utf-8 -*-
"""
NEXGEN PRINT AGENT — WINDOWS COM PORT TESPİT SCRIPTI
=====================================================
Amaç:
  XP-365B için Windows COM port, Bluetooth eşleştirme ve
  pyserial durumunu tek seferde raporlar.

Kullanım:
  python NEXGEN_PRINT_TESPIT.py

Gereksinim:
  pip install pyserial
"""

import sys
import os
import platform

SEP = "=" * 60


def baslik(metin):
    print(f"\n{SEP}")
    print(f"  {metin}")
    print(SEP)


def durum(tamam, metin):
    simge = "[OK]  " if tamam else "[FAIL]"
    print(f"  {simge} {metin}")


# ─────────────────────────────────────────────────────────────
# 1. Sistem bilgisi
# ─────────────────────────────────────────────────────────────
baslik("1. SİSTEM")
print(f"  Python   : {sys.version}")
print(f"  Platform : {platform.platform()}")

# ─────────────────────────────────────────────────────────────
# 2. pyserial
# ─────────────────────────────────────────────────────────────
baslik("2. PYSERIAL")
try:
    import serial
    import serial.tools.list_ports
    durum(True, f"pyserial kurulu — v{serial.__version__}")
    PYSERIAL_OK = True
except ImportError:
    durum(False, "pyserial kurulu DEĞİL — pip install pyserial")
    PYSERIAL_OK = False

# ─────────────────────────────────────────────────────────────
# 3. COM port listesi
# ─────────────────────────────────────────────────────────────
baslik("3. COM PORTLARI")
if PYSERIAL_OK:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        durum(False, "Hiç COM port bulunamadı")
    else:
        print(f"  Toplam {len(ports)} port bulundu:\n")
        for p in sorted(ports, key=lambda x: x.device):
            print(f"  PORT   : {p.device}")
            print(f"  Açıklama: {p.description}")
            print(f"  HWID   : {p.hwid}")
            bt_ipucu = (
                "Bluetooth" in (p.description or "") or
                "RFCOMM" in (p.hwid or "") or
                "BT" in (p.description or "")
            )
            if bt_ipucu:
                print(f"  >>> BT ADAYI <<<")
            print()
else:
    print("  pyserial kurulu olmadığı için port listesi alınamadı.")

# ─────────────────────────────────────────────────────────────
# 4. Windows Bluetooth servisi
# ─────────────────────────────────────────────────────────────
baslik("4. WINDOWS BLUETOOTH DURUMU")
if sys.platform == "win32":
    try:
        import subprocess
        result = subprocess.run(
            ["sc", "query", "bthserv"],
            capture_output=True, text=True, timeout=5
        )
        if "RUNNING" in result.stdout:
            durum(True, "Bluetooth servisi RUNNING")
        elif "STOPPED" in result.stdout:
            durum(False, "Bluetooth servisi STOPPED — Bluetooth açık mı?")
        else:
            print(f"  SC çıktısı: {result.stdout.strip()[:200]}")
    except Exception as e:
        print(f"  SC sorgusu yapılamadı: {e}")

    # Bluetooth eşleşmiş cihazlar (WMI)
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class Bluetooth | Select-Object FriendlyName, Status | Format-Table -AutoSize"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            print("\n  Eşleşmiş Bluetooth cihazlar:")
            for line in result.stdout.strip().splitlines():
                if line.strip():
                    print(f"    {line}")
        else:
            print("  Eşleşmiş Bluetooth cihaz bulunamadı veya sorgu başarısız.")
    except Exception as e:
        print(f"  Bluetooth cihaz sorgusu: {e}")
else:
    print("  Bu kontrol yalnızca Windows'ta çalışır.")

# ─────────────────────────────────────────────────────────────
# 5. XP-365B için Outbound COM port tespiti
# ─────────────────────────────────────────────────────────────
baslik("5. XP-365B OUTBOUND COM PORT")
if PYSERIAL_OK:
    xprinter_adaylar = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").upper()
        hwid = (p.hwid or "").upper()
        if any(k in desc for k in ["XPRINTER", "XP-365", "BTSPP", "BLUETOOTH", "RFCOMM", "SPP"]):
            xprinter_adaylar.append(p)
        elif any(k in hwid for k in ["BLUETOOTH", "RFCOMM"]):
            xprinter_adaylar.append(p)

    if xprinter_adaylar:
        print(f"  {len(xprinter_adaylar)} aday bulundu:")
        for p in xprinter_adaylar:
            print(f"    >>> {p.device} — {p.description}")
    else:
        print("  XP-365B adayı otomatik tespit edilemedi.")
        print("  Lütfen Aygıt Yöneticisi > Portlar (COM ve LPT) bölümünü kontrol edin.")
        print("  Bluetooth üzerinden eşleşmiş XP-365B için 'Outbound' COM portuna bakın.")

# ─────────────────────────────────────────────────────────────
# 6. COM port açılabilirlik testi (opsiyonel)
# ─────────────────────────────────────────────────────────────
baslik("6. OPSIYONEL: BELIRLI BIR COM PORTU TEST ET")

TEST_PORT = os.environ.get("NEXGEN_TEST_COM_PORT", "")
if TEST_PORT:
    print(f"  Test portu: {TEST_PORT}")
    try:
        import serial as _s
        p = _s.Serial(TEST_PORT, baudrate=9600, timeout=2)
        durum(True, f"{TEST_PORT} başarıyla açıldı!")
        print(f"  Baud rate: {p.baudrate}")
        p.close()
        print("  Port kapatıldı.")
    except Exception as e:
        durum(False, f"{TEST_PORT} açılamadı: {e}")
else:
    print("  Belirli port test için şunu çalıştırın:")
    print("  set NEXGEN_TEST_COM_PORT=COM7 && python NEXGEN_PRINT_TESPIT.py")

# ─────────────────────────────────────────────────────────────
# 7. Sonuç özeti
# ─────────────────────────────────────────────────────────────
baslik("ÖZET — SONRAKI ADIMLAR")
if PYSERIAL_OK:
    ports = list(serial.tools.list_ports.comports())
    print(f"  pyserial     : HAZIR")
    print(f"  COM port sayısı: {len(ports)}")
    print()
    print("  Yapılacaklar:")
    print("  1. Aygıt Yöneticisi'nde XP-365B'nin Outbound COM portunun numarasını not et.")
    print("     (Bluetooth Bağlantısı > Standart Seri Bağlantı — Outbound olacak)")
    print("  2. Yukarıda tespit edilen COM numarasını (örn: COM7) bildirin.")
    print("  3. Baud rate: XP-365B varsayılanı 9600 bps (değiştirilmediyse).")
    print()
    print("  NOT: İki COM port oluşturulur:")
    print("    Incoming — yazıcı PC'ye bağlanmak istediğinde")
    print("    Outgoing — PC yazıcıya bağlandığında (bunu kullanacağız)")
else:
    print("  pyserial KURULU DEĞİL!")
    print("  Çözüm: pip install pyserial")
    print("  Sonra bu scripti tekrar çalıştırın.")

print(f"\n{SEP}\n")
