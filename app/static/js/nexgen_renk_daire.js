/* NexGen RF renk önizleme dairesi — Renk Merkezi + tablet ortak */
(function (global) {
  function rmRenkDaire(rfAdi) {
    const ad = (rfAdi || '').toUpperCase();
    const eslesme = [
      [['SİYAH', 'SIYAH', 'BLACK'], { bg: '#1a1a1a', fg: '#fff' }],
      [['BEYAZ', 'WHITE', 'OPTİK', 'OPTIK'], { bg: '#f5f5f5', fg: '#555' }],
      [['GRİ', 'GRI', 'GRAY', 'GREY', 'FÜME', 'FUME', 'SILVER', 'GÜMÜŞ'], { bg: '#9ca3af', fg: '#fff' }],
      [['PEMBE', 'PINK', 'ROSE'], { bg: '#f9a8d4', fg: '#831843' }],
      [['KIRMIZI', 'KIRIM', 'RED'], { bg: '#ef4444', fg: '#fff' }],
      [['MAVİ', 'MAVI', 'BLUE', 'LACIVERT'], { bg: '#3b82f6', fg: '#fff' }],
      [['YEŞİL', 'YESIL', 'GREEN'], { bg: '#22c55e', fg: '#fff' }],
      [['SARI', 'YELLOW', 'GOLD', 'ALTIN'], { bg: '#fbbf24', fg: '#78350f' }],
      [['TURUNCU', 'ORANGE'], { bg: '#f97316', fg: '#fff' }],
      [['MOR', 'PURPLE', 'VİOLE', 'VIOLE'], { bg: '#a855f7', fg: '#fff' }],
      [['KAHVE', 'BROWN', 'TABA', 'KREM', 'CREAM', 'BEJ', 'BEIGE'], { bg: '#d97706', fg: '#fff' }],
      [['BAKLAVA', 'EKRU', 'EKRÜ'], { bg: '#e8d5b7', fg: '#6b4226' }],
      [['LACIVERT'], { bg: '#1e3a5f', fg: '#fff' }],
    ];
    for (const [keys, renk] of eslesme) {
      if (keys.some(function (k) { return ad.includes(k); })) return renk;
    }
    let h = 0;
    for (let i = 0; i < ad.length; i++) h = (h * 31 + ad.charCodeAt(i)) & 0xffffff;
    const bg = '#' + ('000000' + (h & 0xffffff).toString(16)).slice(-6);
    return { bg: bg, fg: '#fff' };
  }

  function nxRenkDaireStyle(dc) {
    dc = dc || { bg: '#9ca3af', fg: '#fff' };
    const border = dc.bg === '#f5f5f5' ? '#d1d5db' : dc.bg;
    return 'background:' + dc.bg + ';color:' + dc.fg + ';border-color:' + border;
  }

  global.rmRenkDaire = rmRenkDaire;
  global.nxRenkDaireStyle = nxRenkDaireStyle;
})(typeof window !== 'undefined' ? window : this);
