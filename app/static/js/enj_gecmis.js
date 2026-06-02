/* PATCH_3B13_DENSITY_FINAL
 * Saat: "07-08" | Personel null→"0 Kisi" | 3.B.10 DOM restore
 */
(function () {
  'use strict';
  var state = { aktifTab:'gunluk', filtre:{}, limit:100, offset:0, toplam:0, aktifDetayId:null };

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    if (s===null||s===undefined) return '';
    return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function fmtNum(n) {
    if (n===null||n===undefined||n==='') return '<span class="empty">-</span>';
    var v=Number(n); return isNaN(v)?'<span class="empty">-</span>':Math.round(v).toLocaleString('tr-TR');
  }
  function fmtPct(n) {
    if (n===null||n===undefined) return '<span class="empty">-</span>';
    var cls=n>=90?'v-ok':n>=70?'v-mid':'v-bad';
    return '<span class="'+cls+'">%'+n.toFixed(1)+'</span>';
  }
  function verimMiniCls(n) { return n==null?'':n>=90?'verim-ok':n>=70?'verim-mid':'verim-bad'; }
  function verimLabel(n) { return n==null?'-':n>=90?'Iyi':n>=70?'Orta':'Dusuk'; }
  function fmtTarih(s) {
    if (!s) return '-';
    var p=s.split('-'); return p.length===3?p[2]+'.'+p[1]+'.'+p[0]:s;
  }
  function fmtVardiya(v) {
    if (v==='gunduz') return 'Gunduz';
    if (v==='gece') return 'Gece';
    if (v==='mesai') return 'Mesai';
    return v||'-';
  }
  function vardiyaSaat(v) {
    if (v==='gunduz') return '07:00 - 17:00';
    if (v==='gece') return '17:00 - 03:00';
    if (v==='mesai') return '17:00 - 19:00';
    return '';
  }
  function fmtVardiyaBaslik(v) {
    var ad=fmtVardiya(v),saat=vardiyaSaat(v);
    return saat?ad+' ('+saat+')':ad;
  }

  /* Saat format: "07:00" → "07", aralik "07-08" */
  function fmtSaatKisa(s) {
    var bas=s.saat_baslangic, bit=s.saat_bitis;
    function h(st) { return st?String(st).replace(/:.*/,''):''; }
    var h1=h(bas), h2=h(bit);
    if (h1&&!h2) {
      var n=(parseInt(h1,10)+1)%24;
      h2=(n<10?'0':'')+n;
    }
    return (h1&&h2)?h1+'-'+h2:(h1||'-');
  }

  function durumLabel(d) {
    if (!d) return null;
    var m={calisiyor:'Calisiyor',durus:'Durus',yavas:'Yavas',mola:'Mola',ariza:'Ariza',kapali:'Vardiya Bitti'};
    return m[d]||d;
  }
  function durumDot(d) {
    if (!d) return 'dot-kap';
    if (d==='calisiyor') return 'dot-cal';
    if (d==='mola'||d==='yavas') return 'dot-mol';
    if (d==='ariza'||d==='durus') return 'dot-arz';
    return 'dot-kap';
  }
  function durumRenkCls(d) {
    if (!d) return 'durum-kap';
    if (d==='calisiyor') return 'durum-cal';
    if (d==='mola'||d==='yavas') return 'durum-mol';
    if (d==='ariza'||d==='durus') return 'durum-arz';
    return 'durum-kap';
  }
  function birlestirDurum(da,db) {
    var la=durumLabel(da),lb=durumLabel(db);
    if (!la&&!lb) return {txt:'Vardiya Bitti',dot:'dot-kap',cls:'durum-kap'};
    if (la===lb) return {txt:la,dot:durumDot(da),cls:durumRenkCls(da)};
    var onc={ariza:5,durus:4,mola:3,yavas:2,kapali:1,calisiyor:0};
    var oa=onc[da]!=null?onc[da]:0, ob=onc[db]!=null?onc[db]:0;
    var kotu=oa>=ob?da:db, txt;
    if (la==='Calisiyor'&&lb&&lb!=='Calisiyor') txt='B:'+lb;
    else if (lb==='Calisiyor'&&la&&la!=='Calisiyor') txt='A:'+la;
    else if (la&&!lb) txt=la; else if (lb&&!la) txt=lb;
    else txt='A:'+(la||'-')+'/B:'+(lb||'-');
    return {txt:txt,dot:durumDot(kotu),cls:durumRenkCls(kotu)};
  }
  function birlestirSebep(sa,sb) {
    if (!sa&&!sb) return '';
    if (sa&&sb&&sa===sb) return esc(sa);
    if (sa&&!sb) return esc(sa);
    if (!sa&&sb) return esc(sb);
    return esc(sa)+'/'+esc(sb);
  }
  function renkHex(ad) {
    if (!ad) return '#9CA3AF';
    var k=String(ad).toLowerCase().trim();
    var m={siyah:'#111827',beyaz:'#FAFAFA',gri:'#6B7280',kirmizi:'#DC2626',mavi:'#2563EB',
           lacivert:'#1E3A8A',yesil:'#16A34A',sari:'#EAB308',turuncu:'#F97316',
           pembe:'#EC4899',mor:'#9333EA',kahve:'#92400E',kahverengi:'#92400E',
           bej:'#D4A574',krem:'#FEF3C7',altin:'#D4A52F',gumus:'#CBD5E1'};
    for (var key in m) { if (k.indexOf(key)!==-1) return m[key]; }
    return '#9CA3AF';
  }

  function uyariGoster(msg){el('gec-uyari-msg').textContent=msg;el('gec-uyari').classList.add('aktif');}
  function uyariGizle(){el('gec-uyari').classList.remove('aktif');}
  function bugun(){return new Date().toISOString().slice(0,10);}
  function gunOnce(g){var d=new Date();d.setDate(d.getDate()-g);return d.toISOString().slice(0,10);}
  function buAy(){return new Date().toISOString().slice(0,7);}

  function tabAktif(tab) {
    state.aktifTab=tab;
    document.querySelectorAll('.filt-tab').forEach(function(t){t.classList.toggle('aktif',t.dataset.tab===tab);});
    el('grp-gunluk').className=tab==='gunluk'?'grp':'grp gizli';
    el('grp-haftalik').className=tab==='haftalik'?'grp':'grp gizli';
    el('grp-aylik').className=tab==='aylik'?'grp':'grp gizli';
    el('grp-aralik-bas').className=tab==='aralik'?'grp':'grp gizli';
    el('grp-aralik-bit').className=tab==='aralik'?'grp':'grp gizli';
  }
  function filtreVarsayilan() {
    el('f-tarih-tek').value=bugun(); el('f-tarih-hafta').value=gunOnce(6);
    el('f-tarih-ay').value=buAy(); el('f-tarih-bas').value=gunOnce(7); el('f-tarih-bit').value=bugun();
    el('f-makine').value=''; el('f-vardiya').value=''; el('f-operator').value='';
    el('f-problemli').checked=false; el('f-fireli').checked=false;
    tabAktif('gunluk');
  }
  function tarihAralikHesap() {
    if (state.aktifTab==='gunluk'){var t=el('f-tarih-tek').value||bugun();return{bas:t,bit:t};}
    if (state.aktifTab==='haftalik'){
      var hb=el('f-tarih-hafta').value||gunOnce(6),hd=new Date(hb);
      hd.setDate(hd.getDate()+6);return{bas:hb,bit:hd.toISOString().slice(0,10)};
    }
    if (state.aktifTab==='aylik'){
      var ay=el('f-tarih-ay').value||buAy(),parts=ay.split('-');
      var yil=parseInt(parts[0],10),ayn=parseInt(parts[1],10);
      var ilk=yil+'-'+(ayn<10?'0':'')+ayn+'-01',sd=new Date(yil,ayn,0);
      return{bas:ilk,bit:sd.toISOString().slice(0,10)};
    }
    return{bas:el('f-tarih-bas').value||gunOnce(7),bit:el('f-tarih-bit').value||bugun()};
  }
  function filtreOku() {
    var tar=tarihAralikHesap();
    return{tarih_baslangic:tar.bas,tarih_bitis:tar.bit,
      makine_id:el('f-makine').value,vardiya:el('f-vardiya').value,
      operator:el('f-operator').value.trim(),
      sadece_problemli:el('f-problemli').checked?'1':'',
      sadece_fireli:el('f-fireli').checked?'1':'',
    };
  }
  function listeYukle() {
    uyariGizle(); state.aktifDetayId=null; state.filtre=filtreOku();
    var p=new URLSearchParams();
    p.set('tarih_baslangic',state.filtre.tarih_baslangic);
    p.set('tarih_bitis',state.filtre.tarih_bitis);
    if(state.filtre.makine_id)p.set('makine_id',state.filtre.makine_id);
    if(state.filtre.vardiya)p.set('vardiya',state.filtre.vardiya);
    if(state.filtre.operator)p.set('operator',state.filtre.operator);
    if(state.filtre.sadece_problemli)p.set('sadece_problemli','1');
    if(state.filtre.sadece_fireli)p.set('sadece_fireli','1');
    p.set('limit',state.limit); p.set('offset',state.offset);
    el('gec-tbody').innerHTML='<tr><td colspan="14" style="padding:26px;color:#6B7280;">Yukleniyor...</td></tr>';
    fetch('/enjeksiyon/api/raporlar?'+p.toString())
      .then(function(r){return r.json();})
      .then(function(d){
        if(!d||!d.ok){uyariGoster('Liste yuklenemedi');el('gec-tbody').innerHTML='<tr><td colspan="14" style="padding:26px;color:#DC2626;">Hata</td></tr>';return;}
        state.toplam=d.toplam||0; listeRender(d.kayitlar||[]); pagRender();
      }).catch(function(e){uyariGoster('Hata: '+(e.message||e));el('gec-tbody').innerHTML='<tr><td colspan="14" style="padding:26px;color:#DC2626;">Baglanti hatasi</td></tr>';});
  }
  function listeRender(kayitlar) {
    el('gec-toplam').textContent=state.toplam; el('gec-gosterilen').textContent=kayitlar.length;
    if(!kayitlar.length){el('gec-tbody').innerHTML='<tr><td colspan="14" style="padding:26px;color:#9CA3AF;">Sonuc bulunamadi</td></tr>';return;}
    var html='';
    kayitlar.forEach(function(k){
      var o=k.ozet||{},v1=o.v1_kayit;
      var opB=(k.operator==='bilinmeyen')?'<span class="badge b-q">?</span>':(v1?'<span class="badge b-v1">V1</span>':'');
      var fC=(o.fire>0)?'fire-on':'';
      var pB=(o.problemli_saat_sayisi>0)?'<span class="badge b-prob">'+o.problemli_saat_sayisi+' s</span>':'<span class="empty">-</span>';
      html+='<tr class="satir'+(v1?' v1':'')+'" data-rapor-id="'+k.id+'">';
      html+='<td class="expand-ico">&#9656;</td>';
      html+='<td class="col-l">'+fmtTarih(k.tarih)+'</td>';
      html+='<td>'+fmtVardiya(k.vardiya)+'</td>';
      html+='<td class="col-l">'+esc(k.makine_ad||'-')+'</td>';
      html+='<td class="col-l">'+esc(k.operator||'-')+' '+opB+'</td>';
      html+='<td>'+(k.personel_sayisi!=null?k.personel_sayisi:'<span class="empty">-</span>')+'</td>';
      html+='<td class="num">'+fmtNum(o.toplam_tur_a)+'</td><td class="num">'+fmtNum(o.toplam_tur_b)+'</td>';
      html+='<td class="num">'+fmtNum(o.toplam_uretim_a)+'</td><td class="num">'+fmtNum(o.toplam_uretim_b)+'</td>';
      html+='<td class="num '+fC+'">'+fmtNum(o.fire)+'</td>';
      html+='<td class="num">'+fmtNum(o.net)+'</td>';
      html+='<td>'+fmtPct(o.verim_yuzde)+'</td><td>'+pB+'</td></tr>';
      html+='<tr class="det-row" data-detay-for="'+k.id+'" style="display:none;"><td colspan="14"></td></tr>';
    });
    el('gec-tbody').innerHTML=html;
  }
  function pagRender() {
    var ts=Math.max(1,Math.ceil(state.toplam/state.limit)),as=Math.floor(state.offset/state.limit)+1;
    el('gec-sayfa').textContent=as+' / '+ts;
    el('btn-onceki').disabled=(state.offset<=0);
    el('btn-sonraki').disabled=(state.offset+state.limit>=state.toplam);
  }
  function detayKapat() {
    if(!state.aktifDetayId)return;
    var dr=document.querySelector('tr.det-row[data-detay-for="'+state.aktifDetayId+'"]');
    if(dr){dr.style.display='none';dr.querySelector('td').innerHTML='';}
    var s=document.querySelector('tr.satir[data-rapor-id="'+state.aktifDetayId+'"]');
    if(s){s.classList.remove('aktif');var ic=s.querySelector('.expand-ico');if(ic)ic.innerHTML='&#9656;';}
    state.aktifDetayId=null;
  }
  function detayAc(rid) {
    if(state.aktifDetayId===rid){detayKapat();return;}
    if(state.aktifDetayId!==null)detayKapat();
    state.aktifDetayId=rid;
    var s=document.querySelector('tr.satir[data-rapor-id="'+rid+'"]');
    if(s){s.classList.add('aktif');var ic=s.querySelector('.expand-ico');if(ic)ic.innerHTML='&#9662;';}
    var dr=document.querySelector('tr.det-row[data-detay-for="'+rid+'"]');
    if(!dr)return;
    dr.style.display='';
    dr.querySelector('td').innerHTML='<div class="det-cont"><div style="text-align:center;padding:18px;color:#6B7280;">Yukleniyor...</div></div>';
    fetch('/enjeksiyon/api/raporlar/'+rid+'/detay')
      .then(function(r){return r.json();})
      .then(function(d){
        if(!d||!d.ok){dr.querySelector('td').innerHTML='<div class="det-cont" style="color:#DC2626;text-align:center;padding:18px;">Detay yuklenemedi</div>';return;}
        detayRender(dr.querySelector('td'),d,rid);
      }).catch(function(){dr.querySelector('td').innerHTML='<div class="det-cont" style="color:#DC2626;text-align:center;padding:18px;">Baglanti hatasi</div>';});
  }

  function detayRender(targetTd, d, rid) {
    var r=d.rapor||{},o=d.ozet||{},saatlik=d.saatlik||[],slotlar=d.slotlar||[];
    var fireCift=o.fire||0,toplamUr=o.toplam_uretim||0,netCift=o.net||0;
    var fireY=null;
    if(toplamUr>0&&fireCift>0) fireY=(fireCift/toplamUr)*100;
    var temiz=(fireCift===0);

    var html='<div class="det-cont">';
    html+='<div class="det-bas">';
    html+='<div><h3>'+fmtTarih(r.tarih)+' &mdash; '+fmtVardiyaBaslik(r.vardiya)+' &mdash; '+esc(r.makine_ad||'?')+'</h3>';
    html+='<div class="meta">Operator: <b>'+esc(r.kullanici_adi||'-')+'</b>';
    /* Personel: null veya 0 → "0 Kisi" */
    var persS = (r.personel_sayisi!=null) ? r.personel_sayisi : 0;
    html+=' &middot; Personel: <b>'+persS+' Kisi</b>';
    html+='</div></div>';
    html+='<button class="det-kapat" data-kapat="'+rid+'">Detaylari Kapat &#9650;</button>';
    html+='</div>';
    html+='<div class="det-grid">';

    /* === SOL === */
    html+='<div class="det-sol">';
    html+='<div class="op-uretim">';
    html+='<div class="hd"><div class="ikon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20V8l6-4 6 4v12H2z"></path><path d="M14 8h8v12h-8"></path></svg></div>';
    html+='<span class="lbl">Toplam Uretim (Net)</span></div>';
    html+='<div class="val">'+fmtNum(netCift)+'<span class="birim">cift</span></div>';
    html+='<div class="alt">';
    html+='<div class="ab a"><div class="l">A Tarafi</div><div class="n">'+fmtNum(o.toplam_uretim_a)+'<span class="u">cift</span></div></div>';
    html+='<div class="ab b"><div class="l">B Tarafi</div><div class="n">'+fmtNum(o.toplam_uretim_b)+'<span class="u">cift</span></div></div>';
    html+='</div></div>';

    html+='<div class="'+(temiz?'op-fire temiz':'op-fire')+'">';
    html+='<div class="hd"><div class="ikon">';
    html+=temiz
      ?'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
      :'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"></path></svg>';
    html+='</div><span class="lbl">Fire (Gun Sonu)</span></div>';
    if(temiz){html+='<div class="val">0<span class="birim">cift</span></div><div class="yuzde">Temiz</div>';}
    else{
      html+='<div class="val">'+fmtNum(fireCift)+'<span class="birim">cift</span></div>';
      if(fireY!=null)html+='<div class="yuzde">%'+fireY.toFixed(1)+' fire</div>';
    }
    html+='<div class="alt-info">Toplam Ham Uretim: <b>'+fmtNum(toplamUr)+' cift</b></div>';
    html+='</div>';

    var vV=(o.verim_yuzde!=null?'%'+o.verim_yuzde.toFixed(1):'-'),prS=o.problemli_saat_sayisi||0;
    html+='<div class="op-mini-grid">';
    html+='<div class="op-mini '+verimMiniCls(o.verim_yuzde)+'"><div class="ikon verim"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg></div><div class="icerik"><div class="lbl">Verim</div><div class="val">'+vV+'</div><div class="alt">'+verimLabel(o.verim_yuzde)+'</div></div></div>';
    /* Personel mini kart: null → "0" */
    var persN=(r.personel_sayisi!=null)?r.personel_sayisi:0;
    html+='<div class="op-mini"><div class="ikon personel"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg></div><div class="icerik"><div class="lbl">Personel</div><div class="val">'+persN+'</div><div class="alt">Kisi</div></div></div>';
    html+='<div class="op-mini"><div class="ikon tur"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg></div><div class="icerik"><div class="lbl">Tur A / Tur B</div><div class="val">'+(o.toplam_tur_a||0)+' / '+(o.toplam_tur_b||0)+'</div><div class="alt">cift</div></div></div>';
    html+='<div class="op-mini"><div class="ikon problem"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg></div><div class="icerik"><div class="lbl">Problem Saati</div><div class="val">'+prS+' s</div><div class="alt">Toplam</div></div></div>';
    html+='</div>';
    html+='</div>'; /* det-sol */

    /* === ORTA === */
    html+='<div class="det-orta">';
    html+='<h4>Saatlik Akis <span class="'+(prS>0?'saytac-prob':'saytac-norm')+'">('+saatlik.length+' saat)'+(prS>0?' &middot; '+prS+' problemli':'')+'</span></h4>';
    html+='<div class="ic">';
    if(!saatlik.length){
      html+='<div style="text-align:center;padding:18px;color:#9CA3AF;">Kayit yok</div>';
    } else {
      html+='<table class="saat-tbl"><thead><tr>';
      html+='<th>Saat</th><th>A Tur</th><th>B Tur</th><th>Uretim (cift)</th>';
      html+='<th class="col-durum">Durum</th><th class="col-sebep">Sebep</th>';
      html+='</tr></thead><tbody>';
      saatlik.forEach(function(s){
        var cA=s.cevrim_a_eff||0,cB=s.cevrim_b_eff||0;
        var uA=s.uretilen_a||0,uB=s.uretilen_b||0,top=uA+uB;
        var dur=birlestirDurum(s.durum_a_eff,s.durum_b_eff);
        var seb=birlestirSebep(s.sebep_a_ad,s.sebep_b_ad);
        var prob=(dur.cls!=='durum-cal'&&dur.cls!=='durum-kap');
        html+='<tr class="'+(prob?'problem-row':'')+'">';
        html+='<td class="saat-col">'+fmtSaatKisa(s)+'</td>';
        html+='<td>'+cA+'</td><td>'+cB+'</td>';
        html+='<td class="uretim-c">'+(top?fmtNum(top):'<span class="empty">-</span>')+'</td>';
        html+='<td class="durum-c '+dur.cls+'"><span class="dot '+dur.dot+'"></span>'+dur.txt+'</td>';
        html+='<td class="sebep-c">'+(seb||'<span class="empty">-</span>')+'</td>';
        html+='</tr>';
      });
      html+='</tbody></table>';
    }
    html+='</div>';
    if(saatlik.length>0) html+='<div class="alt-link">Tum saatleri goster ('+saatlik.length+' saat) &#9662;</div>';
    html+='</div>'; /* det-orta */

    /* === SAG === */
    var ist={};
    slotlar.forEach(function(s){if(!ist[s.istasyon_no])ist[s.istasyon_no]={};ist[s.istasyon_no][s.slot]=s;});
    var istN=Object.keys(ist).sort(function(a,b){return parseInt(a)-parseInt(b);});
    var aktS=0;
    istN.forEach(function(no){var a=ist[no]['A'],b=ist[no]['B'];if((a&&a.aktif)||(b&&b.aktif))aktS++;});

    html+='<div class="det-sag">';
    html+='<h4>Kalip / Istasyon Listesi <span class="akt">'+aktS+' istasyon aktif</span></h4>';
    html+='<div class="ic">';
    if(!slotlar.length){
      html+='<div style="text-align:center;padding:18px;color:#9CA3AF;">Istasyon kaydi yok</div>';
    } else {
      html+='<table class="ist-tbl"><thead><tr><th class="no-head">Istasyon</th><th class="a-head">A Tarafi</th><th class="b-head">B Tarafi</th></tr></thead><tbody>';
      istN.forEach(function(no){
        var a=ist[no]['A']||{},b=ist[no]['B']||{};
        var tp=(!a.aktif&&!b.aktif);
        html+='<tr class="'+(tp?'tum-pasif':'')+'">';
        html+='<td class="no">'+no+'</td>';
        /* A */
        html+='<td class="a-col">';
        html+='<div class="kalip">'+(tp?'&mdash; pasif &mdash;':esc(a.kalip_kod||'-'))+'</div>';
        if(!tp){
          html+='<div class="ist-info">';
          if(a.renk)html+='<span class="renk-info"><span class="renk-dot" style="background:'+renkHex(a.renk)+'"></span>'+esc(a.renk)+'</span>';
          if(a.pisme_suresi_sn!=null)html+='<span class="pisme-pill pisme-a">'+a.pisme_suresi_sn+' sn</span>';
          html+='</div>';
        }
        html+='</td>';
        /* B */
        html+='<td class="b-col">';
        html+='<div class="kalip">'+(tp?'&mdash; pasif &mdash;':esc(b.kalip_kod||'-'))+'</div>';
        if(!tp){
          html+='<div class="ist-info">';
          if(b.renk)html+='<span class="renk-info"><span class="renk-dot" style="background:'+renkHex(b.renk)+'"></span>'+esc(b.renk)+'</span>';
          if(b.pisme_suresi_sn!=null)html+='<span class="pisme-pill pisme-b">'+b.pisme_suresi_sn+' sn</span>';
          html+='</div>';
        }
        html+='</td>';
        html+='</tr>';
      });
      html+='</tbody></table>';
    }
    html+='</div>';
    html+='<div class="alt-not">Renk bilgisi son kayittaki aktiftir.</div>';
    html+='</div>'; /* det-sag */
    html+='</div>'; /* det-grid */

    /* LEGEND */
    html+='<div class="det-legend">';
    html+='<div class="legend-box dr"><h5>Durum Renkleri</h5><div class="grid2">';
    html+='<div class="row"><span class="ldot dot-cal"></span>Calisiyor</div>';
    html+='<div class="row"><span class="ldot dot-mol"></span>Mola</div>';
    html+='<div class="row"><span class="ldot dot-arz"></span>Ariza/Durus</div>';
    html+='<div class="row"><span class="ldot dot-kap"></span>Vardiya Bitti</div>';
    html+='</div></div>';
    html+='<div class="legend-box"><h5>Problem Kurallari</h5>';
    html+='<div class="row"><span class="lbadge prob">2s</span>2+ saniye durus &rarr; Problemli saat</div>';
    html+='<div class="row"><span class="lbadge uyari">1s</span>1 saniye &rarr; Uyari (sayilmaz)</div>';
    html+='</div>';
    html+='<div class="legend-box"><h5>Aciklamalar</h5><ul>';
    html+='<li>Fire gun sonunda hesaplanir.</li>';
    html+='<li>Fire; net uretimden dusulerek verim hesaplanir.</li>';
    html+='<li>Saatlik: aktif istasyonlarin A+B toplamidir.</li>';
    html+='</ul></div></div>';

    html+='</div>'; /* det-cont */
    targetTd.innerHTML=html;
    var kb=targetTd.querySelector('[data-kapat]');
    if(kb)kb.addEventListener('click',function(e){e.stopPropagation();detayKapat();});
  }

  function bind() {
    document.querySelectorAll('.filt-tab').forEach(function(t){
      t.addEventListener('click',function(e){tabAktif(e.currentTarget.dataset.tab);});
    });
    el('btn-filtrele').addEventListener('click',function(){state.offset=0;listeYukle();});
    el('btn-temizle').addEventListener('click',function(){filtreVarsayilan();state.offset=0;listeYukle();});
    el('btn-onceki').addEventListener('click',function(){if(state.offset>=state.limit){state.offset-=state.limit;listeYukle();}});
    el('btn-sonraki').addEventListener('click',function(){if(state.offset+state.limit<state.toplam){state.offset+=state.limit;listeYukle();}});
    el('gec-tbody').addEventListener('click',function(e){
      if(e.target.closest('[data-kapat]'))return;
      var tr=e.target.closest('tr.satir[data-rapor-id]');
      if(!tr)return;
      var rid=parseInt(tr.dataset.raporId,10);
      if(!isNaN(rid))detayAc(rid);
    });
  }
  document.addEventListener('DOMContentLoaded',function(){filtreVarsayilan();bind();listeYukle();});
})();
