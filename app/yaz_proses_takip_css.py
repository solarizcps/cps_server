# -*- coding: utf-8 -*-
"""proses_takip.css dosyasini garantili UTF-8 olarak yazar."""
import os

YOL = r'C:\cps_dev\static\css\proses_takip.css'

CSS = r'''/* =====================================================
   SOLARIZ CPS - PLANLAMA / PROSES TAKIP (MVP)
   Korgun canli uretim verisi - operasyon gorunumu
   Tum class'lar .pt- prefix ile izole
   ===================================================== */

/* ============ TOOLBAR ============ */
.pt-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 2px solid #f0f0f0;
}
.pt-toolbar h1 {
  font-size: 20px;
  margin: 0 0 3px 0;
  color: #2c3e50;
  font-weight: 700;
}
.pt-toolbar p {
  font-size: 12.5px;
  color: #6c757d;
  margin: 0;
}
.pt-toolbar-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.pt-veri-kaynak {
  background: #fff3cd;
  color: #856404;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.pt-veri-kaynak.korgun { background: #d1ecf1; color: #0c5460; }
.pt-veri-kaynak.mock { background: #f8d7da; color: #721c24; }
.pt-veri-kaynak.beklemede { background: #e2e3e5; color: #495057; }
.pt-sorgu-suresi {
  font-size: 11px;
  color: #6c757d;
  font-family: monospace;
}

/* ============ UYARI BANDI (mock fallback) ============ */
.pt-uyari-bandi {
  background: #fff3cd;
  border: 1px solid #ffeaa7;
  border-left: 4px solid #f0ad4e;
  color: #856404;
  padding: 10px 14px;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 500;
}

/* ============ ANA YERLEŞİM (sol filtre + sağ panel) ============ */
.pt-layout {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.pt-filtre-paneli {
  width: 250px;
  flex-shrink: 0;
  background: white;
  border: 1px solid #e9ecef;
  border-radius: 10px;
  padding: 14px;
  position: sticky;
  top: 14px;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
}
.pt-filtre-paneli.kapali {
  width: 0;
  padding: 0;
  border: none;
  overflow: hidden;
}
.pt-ana-panel {
  flex: 1;
  min-width: 0;
}

/* ============ SOL FİLTRE PANELİ ============ */
.pt-filtre-baslik {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
  color: #2c3e50;
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}
.pt-toggle-btn {
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 10px;
  cursor: pointer;
  color: #495057;
  transition: all 0.15s;
}
.pt-toggle-btn:hover { background: #fff5e6; border-color: #f27a1a; color: #f27a1a; }

.pt-flt-grup {
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f5f5f5;
}
.pt-flt-grup:last-child { border-bottom: none; }
.pt-flt-grup-baslik {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  font-weight: 700;
  color: #495057;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
  cursor: pointer;
  user-select: none;
}
.pt-flt-grup-baslik:hover { color: #f27a1a; }
.pt-flt-grup-baslik small {
  font-size: 9px;
  font-weight: 400;
  color: #f0ad4e;
  letter-spacing: 0;
  text-transform: none;
  margin-left: 4px;
}
.pt-flt-tumu {
  font-size: 10px;
  color: #f27a1a;
  font-weight: 600;
  cursor: pointer;
  text-transform: none;
  letter-spacing: 0;
}
.pt-flt-tumu:hover { text-decoration: underline; }

.pt-checklist {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}
.pt-checklist label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  cursor: pointer;
  padding: 3px 0;
  color: #495057;
  user-select: none;
}
.pt-checklist label:hover { color: #2c3e50; }
.pt-checklist input[type="checkbox"] { accent-color: #f27a1a; cursor: pointer; }
.pt-renk {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pt-tarih-grup {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pt-period-group {
  display: flex;
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  padding: 3px;
  gap: 2px;
}
.pt-period-btn {
  flex: 1;
  padding: 5px 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  color: #6c757d;
  transition: all 0.15s;
}
.pt-period-btn:hover { background: white; color: #f27a1a; }
.pt-period-btn.aktif {
  background: #f27a1a;
  color: white;
  box-shadow: 0 1px 4px rgba(242, 122, 26, 0.3);
}
.pt-tarih-aralik {
  display: flex;
  gap: 6px;
}
.pt-tarih-aralik input[type="date"] {
  flex: 1;
  padding: 5px 7px;
  font-size: 11.5px;
  border: 1px solid #dee2e6;
  border-radius: 5px;
  color: #495057;
}

.pt-flt-grup input[type="text"] {
  width: 100%;
  padding: 6px 9px;
  font-size: 12px;
  border: 1px solid #dee2e6;
  border-radius: 5px;
  margin-bottom: 5px;
  color: #495057;
  font-family: inherit;
}
.pt-flt-grup input[type="text"]:focus {
  outline: none;
  border-color: #f27a1a;
  box-shadow: 0 0 0 2px rgba(242, 122, 26, 0.15);
}

.pt-aksiyon {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.pt-btn-goster {
  flex: 2;
  padding: 8px;
  background: #f27a1a;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.3px;
}
.pt-btn-goster:hover { background: #e06d10; box-shadow: 0 2px 6px rgba(242, 122, 26, 0.4); }
.pt-btn-sifirla {
  flex: 1;
  padding: 8px;
  background: white;
  color: #6c757d;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.pt-btn-sifirla:hover { background: #f8f9fa; color: #495057; }

/* ============ ÖZET BANDI ============ */
.pt-ozet-bandi {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 0;
  background: white;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 12px;
}
.pt-ozet-h {
  padding: 8px 10px;
  border-right: 1px solid #f0f0f0;
  text-align: center;
}
.pt-ozet-h:last-child { border-right: none; }
.pt-ozet-lbl {
  font-size: 9.5px;
  color: #6c757d;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  font-weight: 600;
  margin-bottom: 3px;
}
.pt-ozet-v {
  font-size: 17px;
  font-weight: 700;
  color: #2c3e50;
  font-variant-numeric: tabular-nums;
}
.pt-ozet-v.pt-sari { color: #f0ad4e; }
.pt-ozet-v.pt-mavi { color: #2196f3; }
.pt-ozet-v.pt-yesil { color: #28a745; }

/* ============ TABLO KARTI ============ */
.pt-tablo-kart {
  background: white;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.pt-tablo-scroll {
  overflow: auto;
  max-height: calc(100vh - 280px);
  min-height: 300px;
}
.pt-tablo {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.pt-tablo thead tr {
  background: #f8f9fa;
}
.pt-tablo th {
  padding: 8px 10px;
  font-size: 10.5px;
  font-weight: 700;
  color: #495057;
  text-align: left;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  border-bottom: 1px solid #dee2e6;
  white-space: nowrap;
  position: sticky;
  top: 0;
  background: #f8f9fa;
  z-index: 2;
}
.pt-tablo tbody tr {
  border-bottom: 1px solid #f5f5f5;
  transition: background 0.1s;
}
.pt-tablo tbody tr:hover {
  background: #fff8f0;
}
.pt-tablo td {
  padding: 7px 10px;
  color: #495057;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
.pt-tablo td.pt-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  color: #2196f3;
}
.pt-empty {
  text-align: center !important;
  padding: 40px 20px !important;
  color: #6c757d;
  font-size: 13px;
}

.pt-tag {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 10.5px;
  font-family: monospace;
  background: #f1f3f5;
  color: #495057;
  border: 1px solid #e9ecef;
}
.pt-durum-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 10px;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.pt-durum-badge.basl { background: #fff3cd; color: #856404; }
.pt-durum-badge.devam { background: #d1ecf1; color: #0c5460; }
.pt-durum-badge.biten { background: #d4edda; color: #155724; }

.pt-tablo-alt {
  padding: 8px 14px;
  font-size: 11px;
  color: #6c757d;
  border-top: 1px solid #f0f0f0;
  background: #fafbfc;
}

/* ============ RESPONSIVE ============ */
@media (max-width: 1100px) {
  .pt-layout { flex-direction: column; }
  .pt-filtre-paneli {
    width: 100%;
    max-height: none;
    position: static;
  }
  .pt-ozet-bandi { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 600px) {
  .pt-ozet-bandi { grid-template-columns: repeat(2, 1fr); }
}
'''

os.makedirs(os.path.dirname(YOL), exist_ok=True)

with open(YOL, 'w', encoding='utf-8') as f:
    f.write(CSS)

print(f"[OK] Yazildi: {YOL}")
print(f"[OK] Boyut: {os.path.getsize(YOL)} byte")

# Dogrulama
with open(YOL, 'r', encoding='utf-8') as f:
    icerik = f.read()
print(f"[OK] Okundu: {len(icerik)} karakter")
print(f"[OK] '.pt-toolbar' var mi: {'.pt-toolbar' in icerik}")
print(f"[OK] '.pt-layout' var mi: {'.pt-layout' in icerik}")
print(f"[OK] '.pt-tablo' var mi: {'.pt-tablo' in icerik}")