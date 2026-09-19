/* KABUL-1 paneli — grafik, çizgi seçimi, kontrol terminali.
 *
 * Sunucu yalnızca okur; komutlar bayrak dosyası bırakır (bkz. src/arayuz/komut.py).
 * Zaman ekseni New York duvar saatidir (sunucu çevirip veriyor).
 */
(function () {
  "use strict";

  const LWC = window.LightweightCharts;
  // Sunucunun veri biçimi sürümü (src/arayuz/sunucu.py → ARAYUZ_SURUMU).
  const SURUM = 5;

  // Çizgiler: sıra = palet slot sırası (stil.css). Renk varlığa bağlı, sıraya değil.
  const CIZGILER = [
    { ad: "tepe",       baslik: "Upper band",  renk: "--seri-tepe" },
    { ad: "dip",        baslik: "Lower band",  renk: "--seri-dip" },
    { ad: "alis",       baslik: "Entry (buy limit)", kisa: "Entry", renk: "--seri-alis" },
    { ad: "zarar_stop", baslik: "Stop loss",   renk: "--seri-zarar" },
    { ad: "takip_stop", baslik: "Trailing stop", renk: "--seri-takip" },
  ];
  const KATMANLAR = ["canli", "backtest"];
  const KISA = { canli: "L", backtest: "B" };
  const KATMAN_ADI = { canli: "Live", backtest: "Backtest" };
  const SEBEP_ADI = { stop: "stop loss", takip: "trailing stop", tepe: "upper band", donem_sonu: "period end" };
  // Bar aralıkları. Kurallar SAATLİK çalışır: canlı ve backtest çizgileri
  // yalnızca 1H'de gösterilir (başka aralıkta hizaları yanlış olurdu).
  const TF = [
    { ad: "1Min", baslik: "1m", gun: 2 },
    { ad: "1Hour", baslik: "1H", gun: 60 },
    { ad: "1Day", baslik: "1D", gun: 400 },
  ];
  const KURAL_TF = "1Hour";
  const tfBilgi = (ad) => TF.find((t) => t.ad === ad) || TF[1];

  // Göstergeler. `panel: true` olanlar grafiğin ALTINDA ayrı panelde çizilir
  // (ölçekleri fiyattan bambaşka); ötekiler fiyatın üstüne.
  const GOSTERGELER = [
    { ad: "sma", baslik: "SMA", renk: "--gosterge-1", ayar: { periyot: 20 } },
    { ad: "ema", baslik: "EMA", renk: "--gosterge-2", ayar: { periyot: 50 } },
    { ad: "bb", baslik: "Bollinger", renk: "--gosterge-3", ayar: { periyot: 20, k: 2 } },
    { ad: "volume", baslik: "Volume", panel: true, ayar: {} },
    { ad: "rsi", baslik: "RSI", panel: true, renk: "--gosterge-1", ayar: { periyot: 14 } },
    { ad: "macd", baslik: "MACD", panel: true, renk: "--gosterge-2", ayar: { hizli: 12, yavas: 26, sinyal: 9 } },
    { ad: "ao", baslik: "AO", panel: true, ayar: { kisa: 5, uzun: 34 } },
  ];

  // -------------------------------------------------------------- durum --
  const VARSAYILAN = {
    sembol: null,
    tf: KURAL_TF,
    gosterge: Object.fromEntries(GOSTERGELER.map((g) => [g.ad, { acik: false, ...g.ayar }])),
    katman: { canli: true, backtest: false },
    cizgi: {
      canli: { tepe: true, dip: true, alis: true, zarar_stop: true, takip_stop: true, islemler: true },
      backtest: { tepe: true, dip: true, alis: false, zarar_stop: true, takip_stop: true, islemler: true },
    },
  };
  let durum = oku("panel.durum", VARSAYILAN);
  durum = Object.assign({}, VARSAYILAN, durum);
  durum.cizgi = Object.assign({}, VARSAYILAN.cizgi, durum.cizgi || {});
  durum.gosterge = Object.assign({}, VARSAYILAN.gosterge, durum.gosterge || {});
  if (!TF.some((t) => t.ad === durum.tf)) durum.tf = KURAL_TF;

  // Adres çubuğu kaydedilmiş seçimi ezer: ?sembol=AAPL&katman=canli,backtest
  // (belirli bir görünümü bağlantı olarak paylaşmak için).
  (function () {
    const p = new URLSearchParams(location.search);
    if (p.get("sembol")) durum.sembol = p.get("sembol").toUpperCase();
    if (p.get("tf") && TF.some((t) => t.ad === p.get("tf"))) durum.tf = p.get("tf");
    if (p.has("katman")) {
      const secili = p.get("katman").split(",");
      for (const k of KATMANLAR) durum.katman[k] = secili.includes(k);
    }
  })();

  let yapilandirma = null;
  // Grafikte ŞU AN olan veri (yüklü pencere; bkz. "yükleme").
  let veri = { mumlar: [], canli: null, backtest: bosBacktest() };

  function bosBacktest() {
    return { cizgiler: {}, islemler: [], ozet: null, kasa_baslangici: null };
  }

  function oku(anahtar, varsayilan) {
    try {
      const v = localStorage.getItem(anahtar);
      return v ? JSON.parse(v) : JSON.parse(JSON.stringify(varsayilan));
    } catch (e) { return JSON.parse(JSON.stringify(varsayilan)); }
  }
  function yaz(anahtar, deger) {
    try { localStorage.setItem(anahtar, JSON.stringify(deger)); } catch (e) { /* önemsiz */ }
  }
  function kaydet() { yaz("panel.durum", durum); }

  const $ = (s) => document.querySelector(s);
  // Renkler CSS değişkenlerinden bir kez okunur; fare her kıpırdadığında
  // getComputedStyle çağırmak takılma yapıyordu. Tema değişince silinir.
  const renkOnbellek = {};
  const renk = (degisken) => (renkOnbellek[degisken] ??=
    getComputedStyle(document.documentElement).getPropertyValue(degisken).trim());

  async function getir(yol) {
    const r = await fetch(yol, { cache: "no-store" });
    if (!r.ok) throw new Error(`${yol}: HTTP ${r.status}`);
    return r.json();
  }

  // ------------------------------------------------------------ grafik --
  let grafik = null, mumSerisi = null;
  const seriler = {};   // seriler[katman][cizgi] = LineSeries

  function grafikKur() {
    grafik = LWC.createChart($("#grafik"), {
      autoSize: true,
      layout: { background: { type: "solid", color: renk("--yuzey") }, textColor: renk("--soluk"),
                fontFamily: getComputedStyle(document.body).fontFamily, attributionLogo: true },
      grid: { vertLines: { color: renk("--izgara") }, horzLines: { color: renk("--izgara") } },
      rightPriceScale: { borderColor: renk("--eksen") },
      // minBarSpacing: varsayılan 0.5 px'te 900 px'e en çok ~1800 mum sığar;
      // araştırma dönemi (8.5 yıl, 15 bin mum) son yıla daralıyordu.
      timeScale: { borderColor: renk("--eksen"), timeVisible: true, secondsVisible: false,
                   minBarSpacing: 0.02 },
      crosshair: { mode: LWC.CrosshairMode.Normal },
    });
    mumSerisi = grafik.addCandlestickSeries({
      upColor: renk("--mum-yukari"), downColor: renk("--mum-asagi"),
      borderUpColor: renk("--mum-yukari"), borderDownColor: renk("--mum-asagi"),
      wickUpColor: renk("--mum-yukari"), wickDownColor: renk("--mum-asagi"),
      priceLineVisible: false, lastValueVisible: true,
    });
    for (const k of KATMANLAR) {
      seriler[k] = {};
      for (const c of CIZGILER) {
        seriler[k][c.ad] = grafik.addLineSeries({
          color: renk(c.renk),
          lineWidth: 2,
          lineStyle: k === "canli" ? LWC.LineStyle.Solid : LWC.LineStyle.Dashed,
          lineType: LWC.LineType.WithSteps,       // seviye bar boyunca sabit
          priceLineVisible: false,
          lastValueVisible: true,
          title: `${KISA[k]} ${c.kisa || c.baslik}`,   // eksende doğrudan etiket
          crosshairMarkerVisible: false,
        });
      }
    }
    grafik.subscribeCrosshairMove(degerPaneli);
    // Geriye sürükleyip yüklü verinin başına yarım ekran kadar yaklaşınca,
    // görünen genişliğin 2 katı kadar eski veri istenir.
    grafik.timeScale().subscribeVisibleTimeRangeChange((r) => {
      if (r && yuklu && !genisliyor && kapsam && yuklu.bas > kapsam.ilk) {
        const genislik = r.to - r.from;
        if (r.from - yuklu.bas < genislik / 2) yukleSol(Math.max(kapsam.ilk, yuklu.bas - 2 * genislik));
      }
    });
    grafik.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (esitleniyor || !r) return;
      esitleniyor = true;
      for (const p of Object.values(altPaneller)) p.grafik.timeScale().setVisibleLogicalRange(r);
      esitleniyor = false;
    });
    // Tema değişirse renkleri yenile.
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(renkleriYenile);
  }

  function renkleriYenile() {
    for (const k of Object.keys(renkOnbellek)) delete renkOnbellek[k];
    grafik.applyOptions({
      layout: { background: { type: "solid", color: renk("--yuzey") }, textColor: renk("--soluk") },
      grid: { vertLines: { color: renk("--izgara") }, horzLines: { color: renk("--izgara") } },
      rightPriceScale: { borderColor: renk("--eksen") }, timeScale: { borderColor: renk("--eksen") },
    });
    mumSerisi.applyOptions({
      upColor: renk("--mum-yukari"), downColor: renk("--mum-asagi"),
      borderUpColor: renk("--mum-yukari"), borderDownColor: renk("--mum-asagi"),
      wickUpColor: renk("--mum-yukari"), wickDownColor: renk("--mum-asagi"),
    });
    for (const k of KATMANLAR) for (const c of CIZGILER) seriler[k][c.ad].applyOptions({ color: renk(c.renk) });
    for (const ad of Object.keys(altPaneller)) altPanelSil(ad);     // yeni renklerle kurulur
    gostergeleriCiz();
    isaretleriCiz();
  }

  // Kural çizgileri yalnızca saatlikte anlamlı (kurallar saatlik hesaplanıyor).
  const kuralTfMi = () => durum.tf === KURAL_TF;

  function gorunurlukUygula() {
    for (const k of KATMANLAR) {
      for (const c of CIZGILER) {
        seriler[k][c.ad].applyOptions({
          visible: !!(kuralTfMi() && durum.katman[k] && durum.cizgi[k][c.ad]),
        });
      }
    }
    isaretleriCiz();
  }

  // Sunucu, çizginin olmadığı yeri değersiz nokta ({time}) olarak gönderir.
  // Kütüphane (v4.2) bu noktalarda çizgiyi KOPARMIYOR, iki yanı birleştiriyor:
  // pozisyon açıkken alış seviyesi, motorun çalışmadığı günler uzun yatay
  // çizgi gibi görünüyordu. Basamaklı çizgide bir parça, başladığı noktanın
  // rengini alır; boşluğun ilk noktası saydam yapılır ve değeri bir sonraki
  // değere eşitlenir (yoksa dikey basamak görünür). Diğer boş noktalar atılır.
  const SAYDAM = "rgba(0,0,0,0)";
  // Sondaki boşluk saydam yapılmaz: son parça orada biter, kopacak bir şey
  // yok — ve eksendeki son değer etiketi son noktanın rengini alır.
  // Tek geçiş: "sonraki değer" sondan başa bir kez hesaplanır. (Önceki sürüm
  // her boşlukta dizinin kalanını tarıyordu — backtest'teki binlerce ardışık
  // boşlukta karesel büyüyüp grafiği donduruyordu.)
  function kopukVeri(dizi) {
    const sonrakiDeger = new Array(dizi.length);
    let s;
    for (let i = dizi.length - 1; i >= 0; i--) {
      sonrakiDeger[i] = s;
      if (dizi[i].value !== undefined) s = dizi[i].value;
    }
    const cikti = [];
    let sonTamam = false;
    for (let i = 0; i < dizi.length; i++) {
      const p = dizi[i];
      if (p.value !== undefined) { cikti.push(p); continue; }
      const onceki = cikti[cikti.length - 1];
      if (!onceki || onceki.color === SAYDAM || sonTamam) continue;   // baştaki / ardışık boşluk
      if (sonrakiDeger[i] !== undefined) cikti.push({ time: p.time, value: sonrakiDeger[i], color: SAYDAM });
      else { cikti.push({ time: p.time, value: onceki.value }); sonTamam = true; }
    }
    return cikti;
  }

  // Mumlarda olmayan bir zamana işaret konursa kütüphane onu yok sayar;
  // en yakın mumun zamanına oturtulur.
  function enYakinMum(t) {
    const m = veri.mumlar;
    if (!m.length) return null;
    let lo = 0, hi = m.length - 1;
    if (t <= m[0].time) return m[0].time;
    if (t >= m[hi].time) return m[hi].time;
    while (hi - lo > 1) {
      const orta = (lo + hi) >> 1;
      if (m[orta].time <= t) lo = orta; else hi = orta;
    }
    return (t - m[lo].time) <= (m[hi].time - t) ? m[lo].time : m[hi].time;
  }

  // Barın zamanı → o bardaki işlemler (değer paneli ayrıntıyı buradan gösterir).
  let islemHaritasi = new Map();

  function isaretleriCiz() {
    const isaretler = [];
    islemHaritasi = new Map();
    for (const k of KATMANLAR) {
      if (!kuralTfMi() || !durum.katman[k] || !durum.cizgi[k].islemler || !veri[k]) continue;
      for (const i of veri[k].islemler) {
        const t = enYakinMum(i.time);
        if (t === null) continue;
        const al = i.yon === "al";
        const sebepRengi = i.sebep === "takip" ? "--seri-takip" : "--seri-zarar";
        // Yazı kısa tutulur — uzun etiketler komşu işaretlerle çakışıyor.
        // Sebep rengiyle belli; ayrıntı imleç bara gelince değer panelinde.
        const yazi = !al && i.getiri != null
          ? `${i.getiri >= 0 ? "+" : ""}${(i.getiri * 100).toFixed(1)}%` : "";
        if (!islemHaritasi.has(t)) islemHaritasi.set(t, []);
        islemHaritasi.get(t).push({ katman: k, ...i });
        isaretler.push({
          time: t,
          position: al ? "belowBar" : "aboveBar",
          shape: al ? "arrowUp" : "arrowDown",
          color: renk(al ? "--seri-alis" : sebepRengi),
          text: yazi,
          size: 1,
        });
      }
    }
    isaretler.sort((a, b) => a.time - b.time);
    mumSerisi.setMarkers(isaretler);
  }

  function sayi(x) { return x == null ? "—" : Number(x).toFixed(2); }

  function degerPaneli(p) {
    const kutu = $("#deger-paneli");
    const parca = [];
    const mum = p && p.time !== undefined ? p.seriesData.get(mumSerisi) : null;
    const ham = veri.mumlar[veri.mumlar.length - 1];
    const son = mum || ham;
    if (son) {
      const t = new Date(son.time * 1000);
      const z = t.toISOString().slice(0, 16).replace("T", " ");
      parca.push(`<span class="d"><b>${durum.sembol}</b> · ${tfBilgi(durum.tf).baslik} · ${z} NY</span>`);
      parca.push(`<span class="d">O <b>${sayi(son.open)}</b></span><span class="d">H <b>${sayi(son.high)}</b></span>` +
                 `<span class="d">L <b>${sayi(son.low)}</b></span><span class="d">C <b>${sayi(son.close)}</b></span>`);
      const fark = son.close - son.open;
      const yuzde = son.open ? (fark / son.open) * 100 : 0;
      parca.push(`<span class="d degisim" data-yon="${fark >= 0 ? "yukari" : "asagi"}">` +
                 `${fark >= 0 ? "+" : ""}${sayi(fark)} (${fark >= 0 ? "+" : ""}${yuzde.toFixed(2)}%)</span>`);
      const hacim = veri.mumlar.find((x) => x.time === son.time);
      if (hacim && hacim.volume) parca.push(`<span class="d">Vol <b>${Math.round(hacim.volume).toLocaleString("en-US")}</b></span>`);
    }
    if (p && p.time !== undefined) {
      for (const k of KATMANLAR) {
        if (!durum.katman[k]) continue;
        for (const c of CIZGILER) {
          if (!durum.cizgi[k][c.ad]) continue;
          const d = p.seriesData.get(seriler[k][c.ad]);
          if (!d || d.value === undefined || d.color === SAYDAM) continue;   // boşluk
          parca.push(`<span class="d"><span class="ornek${k === "backtest" ? " kesikli" : ""}" ` +
                     `style="border-color:${renk(c.renk)}"></span>${KISA[k]} ${c.kisa || c.baslik} <b>${sayi(d.value)}</b></span>`);
        }
      }
      for (const i of islemHaritasi.get(p.time) || []) {
        const al = i.yon === "al";
        let metin = `${KATMAN_ADI[i.katman]} ${al ? "BUY" : "SELL (" + (SEBEP_ADI[i.sebep] || i.sebep) + ")"} <b>${sayi(i.fiyat)}</b>`;
        if (!al && i.getiri != null) metin += ` · net of costs <b>${(i.getiri * 100).toFixed(1)}%</b>`;
        if (i.istenen != null) metin += ` · requested ${sayi(i.istenen)}`;
        parca.push(`<span class="d">${al ? "▲" : "▼"} ${metin}</span>`);
      }
    }
    kutu.innerHTML = parca.join("");
  }

  // ------------------------------------------------------ çizgi seçimi --
  function secimleriCiz() {
    for (const k of KATMANLAR) {
      const ana = document.querySelector(`input[data-katman="${k}"]`);
      ana.checked = !!durum.katman[k];
      ana.onchange = () => {
        durum.katman[k] = ana.checked; kaydet(); secimleriCiz(); gorunurlukUygula();
        if (k === "backtest" && ana.checked) backtesteGit();
      };

      const kutu = document.querySelector(`[data-katman-listesi="${k}"]`);
      kutu.innerHTML = "";
      ana.disabled = !kuralTfMi();
      const etiket = ana.closest(".katman").querySelector(".stil-ornek");
      etiket.textContent = kuralTfMi() ? "" : "1H only";
      etiket.classList.toggle("yazi", !kuralTfMi());
      const ogeler = CIZGILER.map((c) => ({ ad: c.ad, baslik: c.baslik, renk: c.renk }))
        .concat([{ ad: "islemler", baslik: "Trades (▲ buy, ▼ sell)", renk: null }]);
      for (const o of ogeler) {
        const lab = document.createElement("label");
        if (!durum.katman[k]) lab.className = "pasif";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !!durum.cizgi[k][o.ad];
        cb.disabled = !durum.katman[k] || !kuralTfMi();
        cb.onchange = () => { durum.cizgi[k][o.ad] = cb.checked; kaydet(); gorunurlukUygula(); };
        const ornek = document.createElement("span");
        if (o.renk) {
          ornek.className = "ornek" + (k === "backtest" ? " kesikli" : "");
          ornek.style.borderColor = renk(o.renk);
        } else {
          ornek.className = "ornek isaret";
        }
        lab.append(cb, ornek, document.createTextNode(o.baslik));
        kutu.appendChild(lab);
      }
    }
  }

  // ------------------------------------------------------- göstergeler --
  // Hesap `gosterge.js`'te (saf fonksiyonlar), burada yalnızca çizim.
  // Fiyatın üstündekiler ana grafikte; ötekiler altta AYRI panelde, çünkü
  // hacim ve osilatörlerin ölçeği fiyatla aynı değil.
  const ustSeriler = {};        // ad → [LineSeries]
  const altPaneller = {};       // ad → { kutu, grafik, seriler }
  let esitleniyor = false;

  function gostergeAyar(ad) { return durum.gosterge[ad] || {}; }
  const gostergeAcik = (ad) => !!gostergeAyar(ad).acik;

  function ustSeri(ad, sayi, secenek) {
    if (!ustSeriler[ad]) {
      ustSeriler[ad] = Array.from({ length: sayi }, () => grafik.addLineSeries({
        lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, ...secenek,
      }));
    }
    return ustSeriler[ad];
  }

  function ustGostergeleriCiz() {
    const m = veri.mumlar;
    const a = gostergeAyar("sma");
    ustSeri("sma", 1, { color: renk("--gosterge-1"), title: "SMA" })[0]
      .setData(gostergeAcik("sma") && m.length ? Gosterge.sma(m, Math.max(2, a.periyot | 0)) : []);
    const e = gostergeAyar("ema");
    ustSeri("ema", 1, { color: renk("--gosterge-2"), title: "EMA" })[0]
      .setData(gostergeAcik("ema") && m.length ? Gosterge.ema(m, Math.max(2, e.periyot | 0)) : []);

    const b = gostergeAyar("bb");
    const bbSeriler = ustSeri("bb", 3, { color: renk("--gosterge-3") });
    bbSeriler[1].applyOptions({ lineStyle: LWC.LineStyle.Dotted });
    if (gostergeAcik("bb") && m.length) {
      const d = Gosterge.bollinger(m, Math.max(2, b.periyot | 0), Number(b.k) || 2);
      bbSeriler[0].setData(d.ust); bbSeriler[1].setData(d.orta); bbSeriler[2].setData(d.alt);
    } else {
      for (const seri of bbSeriler) seri.setData([]);
    }
  }

  function altPanelKur(ad, baslik) {
    const kutu = document.createElement("div");
    kutu.className = "alt-panel";
    const etiket = document.createElement("span");
    etiket.className = "etiket";
    etiket.textContent = baslik;
    const tuval = document.createElement("div");
    tuval.className = "tuval";
    kutu.append(etiket, tuval);
    $("#alt-paneller").append(kutu);
    const g = LWC.createChart(tuval, {
      autoSize: true,
      layout: { background: { type: "solid", color: renk("--yuzey") }, textColor: renk("--soluk"),
                fontFamily: getComputedStyle(document.body).fontFamily, attributionLogo: false },
      grid: { vertLines: { color: renk("--izgara") }, horzLines: { visible: false } },
      rightPriceScale: { borderColor: renk("--eksen"), scaleMargins: { top: 0.15, bottom: 0.05 } },
      timeScale: { borderColor: renk("--eksen"), timeVisible: true, secondsVisible: false,
                   minBarSpacing: 0.02, visible: false },
      crosshair: { mode: LWC.CrosshairMode.Normal },
      handleScale: false, handleScroll: false,          // kaydırma ana grafikten
    });
    // Zaman ekseni ana grafiğe bağlı: aynı barlar görünsün.
    g.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (esitleniyor || !r) return;
      esitleniyor = true;
      grafik.timeScale().setVisibleLogicalRange(r);
      esitleniyor = false;
    });
    return { kutu, grafik: g, seriler: {}, etiket };
  }

  function altPanelSil(ad) {
    const p = altPaneller[ad];
    if (!p) return;
    p.grafik.remove();
    p.kutu.remove();
    delete altPaneller[ad];
  }

  function altGostergeleriCiz() {
    const m = veri.mumlar;
    for (const g of GOSTERGELER.filter((x) => x.panel)) {
      if (!gostergeAcik(g.ad)) { altPanelSil(g.ad); continue; }
      const a = gostergeAyar(g.ad);
      if (!altPaneller[g.ad]) altPaneller[g.ad] = altPanelKur(g.ad, g.baslik);
      const p = altPaneller[g.ad];
      const seri = (ad, tip, secenek) => {
        if (!p.seriler[ad]) {
          p.seriler[ad] = tip === "histogram"
            ? p.grafik.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false, ...secenek })
            : p.grafik.addLineSeries({ lineWidth: 1, priceLineVisible: false,
                                       lastValueVisible: false, crosshairMarkerVisible: false, ...secenek });
        }
        return p.seriler[ad];
      };
      if (g.ad === "volume") {
        seri("v", "histogram", { priceFormat: { type: "volume" } })
          .setData(Gosterge.hacim(m, renk("--mum-yukari"), renk("--mum-asagi")));
        p.etiket.textContent = "Volume";
      } else if (g.ad === "rsi") {
        const periyot = Math.max(2, a.periyot | 0);
        const cizgi = seri("rsi", "line", { color: renk("--gosterge-1") });
        cizgi.setData(Gosterge.rsi(m, periyot));
        cizgi.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
        if (!p.seviyeler) {
          p.seviyeler = [70, 30].map((v) => cizgi.createPriceLine({
            price: v, color: renk("--eksen"), lineStyle: LWC.LineStyle.Dashed, lineWidth: 1,
            axisLabelVisible: false, title: "",
          }));
        }
        p.etiket.textContent = `RSI ${periyot}`;
      } else if (g.ad === "macd") {
        const d = Gosterge.macd(m, Math.max(2, a.hizli | 0), Math.max(3, a.yavas | 0),
                                Math.max(2, a.sinyal | 0));
        seri("hist", "histogram", {}).setData(d.histogram.map((x) => ({
          ...x, color: x.value >= 0 ? renk("--mum-yukari") : renk("--mum-asagi"),
        })));
        seri("macd", "line", { color: renk("--gosterge-2") }).setData(d.macd);
        seri("sinyal", "line", { color: renk("--gosterge-3") }).setData(d.sinyal);
        p.etiket.textContent = `MACD ${a.hizli}/${a.yavas}/${a.sinyal}`;
      } else if (g.ad === "ao") {
        const d = Gosterge.ao(m, Math.max(2, a.kisa | 0), Math.max(3, a.uzun | 0));
        seri("ao", "histogram", {}).setData(d.map((x, i) => ({
          ...x, color: i && x.value < d[i - 1].value ? renk("--mum-asagi") : renk("--mum-yukari"),
        })));
        p.etiket.textContent = `AO ${a.kisa}/${a.uzun}`;
      }
    }
    altPanelleriEsitle();
  }

  function altPanelleriEsitle() {
    const r = grafik.timeScale().getVisibleLogicalRange();
    if (!r) return;
    esitleniyor = true;
    for (const p of Object.values(altPaneller)) p.grafik.timeScale().setVisibleLogicalRange(r);
    esitleniyor = false;
  }

  function gostergeleriCiz() {
    ustGostergeleriCiz();
    altGostergeleriCiz();
  }

  // Menü: onay kutusu + periyot kutuları. Seçim kaydedilir.
  function gostergeMenusunuCiz() {
    const kutu = $("#gosterge-panel");
    kutu.replaceChildren();
    for (const g of GOSTERGELER) {
      if (g.panel && kutu.children.length && !kutu.querySelector(".gosterge-ayrac")
          && GOSTERGELER.findIndex((x) => x.panel) === GOSTERGELER.indexOf(g)) {
        const ayrac = document.createElement("hr");
        ayrac.className = "gosterge-ayrac";
        kutu.append(ayrac);
      }
      const satir = document.createElement("div");
      satir.className = "gosterge-satir";
      const lab = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = gostergeAcik(g.ad);
      cb.onchange = () => {
        durum.gosterge[g.ad] = { ...gostergeAyar(g.ad), acik: cb.checked };
        kaydet();
        gostergeleriCiz();
        gostergeDugmesiniYaz();
      };
      lab.append(cb, document.createTextNode(g.baslik));
      satir.append(lab);
      for (const [ad, varsayilan] of Object.entries(g.ayar)) {
        const sayi = document.createElement("input");
        sayi.type = "number";
        sayi.min = "1";
        sayi.title = ad;
        sayi.value = gostergeAyar(g.ad)[ad] ?? varsayilan;
        sayi.onchange = () => {
          durum.gosterge[g.ad] = { ...gostergeAyar(g.ad), [ad]: Number(sayi.value) || varsayilan };
          kaydet();
          gostergeleriCiz();
        };
        satir.append(sayi);
      }
      kutu.append(satir);
    }
  }

  function gostergeDugmesiniYaz() {
    const n = GOSTERGELER.filter((g) => gostergeAcik(g.ad)).length;
    $("#gosterge-dugme").innerHTML = `<span aria-hidden="true">ƒx</span> Indicators${n ? ` (${n})` : ""}`;
  }

  function gostergeMenusunuKur() {
    const dugme = $("#gosterge-dugme"), panel = $("#gosterge-panel");
    gostergeMenusunuCiz();
    gostergeDugmesiniYaz();
    dugme.onclick = () => {
      panel.hidden = !panel.hidden;
      dugme.setAttribute("aria-expanded", String(!panel.hidden));
    };
    document.addEventListener("click", (e) => {
      if (!panel.hidden && !panel.contains(e.target) && e.target !== dugme && !dugme.contains(e.target)) {
        panel.hidden = true;
        dugme.setAttribute("aria-expanded", "false");
      }
    });
  }

  // ------------------------------------------------------ bar aralığı --
  function tfDugmeleriniCiz() {
    const kutu = $("#tf-dugmeler");
    kutu.replaceChildren(...TF.map((t) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(t.ad === durum.tf));
      b.textContent = t.baslik;
      const var_ = !kapsam || !kapsam.araliklar || kapsam.araliklar.includes(t.ad);
      b.disabled = !var_;
      if (!var_) b.title = "No data for this interval";
      b.onclick = () => tfSec(t.ad);
      return b;
    }));
  }

  function tfSec(tf) {
    if (tf === durum.tf) return;
    durum.tf = tf;
    kaydet();
    tfDugmeleriniCiz();
    secimleriCiz();
    yukle();
  }

  function btOzetYaz() {
    const o = veri.backtest.ozet;
    $("#bt-ozet").textContent = o ? `${o.islem} trades · $1 → $${Number(o.lira).toFixed(2)} net` : "";
  }

  function kasaZamani() {
    return kapsam ? kapsam.kasa : Infinity;
  }

  // Backtest kasa başlangıcında biter. Kutu işaretlendiğinde grafik kasa
  // dönemindeyse (hiç backtest çizgisi yoksa) araştırma döneminin son
  // günlerine kayar.
  async function backtesteGit() {
    if (!kapsam || !yuklu) return;
    const g = grafik.timeScale().getVisibleRange();
    if (g && g.from < kasaZamani()) {
      if (await btTamamla()) cizimiYenile(true);
      return;
    }
    await pencereyeGit({ from: kasaZamani() - ACILIS_GUN * 86400, to: kasaZamani() });
  }

  // ------------------------------------------------------------ izleme --
  // Alpaca'nın "Watchlist"i gibi: arama + sınıf seçici, sınıf başlıkları altında.
  let izlemeListesi = [];
  let pozisyonListesi = [];

  function degisimYaz(el, d) {
    el.textContent = d == null ? "—" : `${d >= 0 ? "+" : ""}${Number(d).toFixed(2)}%`;
    el.dataset.yon = d == null ? "" : d >= 0 ? "yukari" : "asagi";
  }

  function izlemeBirlesik() {
    // Depodaki semboller + Alpaca'daki pozisyonların sembolleri (grafiği olmasa da).
    const liste = izlemeListesi.map((h) => ({ ...h }));
    for (const p of pozisyonListesi) {
      if (!liste.some((h) => h.sembol === p.sembol)) {
        liste.push({ sembol: p.sembol, sinif: p.sinif, fiyat: p.fiyat, degisim: null, grafiksiz: true });
      }
    }
    return liste;
  }

  function izlemeCiz() {
    const kutu = $("#izleme-liste");
    const ara = $("#izleme-ara").value.trim().toUpperCase();
    const secili = $("#izleme-sinif").value;
    const kapali = durum.izlemeKapali || {};
    const liste = izlemeBirlesik().filter((h) =>
      (!ara || h.sembol.includes(ara)) && (secili === "All" || h.sinif === secili));
    const parcalar = [];
    for (const sinif of yapilandirma.siniflar) {
      const grup = liste.filter((h) => h.sinif === sinif).sort((a, b) => a.sembol.localeCompare(b.sembol));
      if (!grup.length) continue;
      const bolum = document.createElement("div");
      bolum.className = "izleme-grup";
      const bas = document.createElement("button");
      bas.type = "button";
      bas.className = "izleme-grup-baslik";
      bas.setAttribute("aria-expanded", String(!kapali[sinif]));
      bas.innerHTML = `<span class="ok" aria-hidden="true">▾</span>${sinif}<span class="sayi">${grup.length}</span>`;
      bas.onclick = () => { durum.izlemeKapali = { ...kapali, [sinif]: !kapali[sinif] }; kaydet(); izlemeCiz(); };
      bolum.append(bas);
      if (!kapali[sinif]) {
        for (const h of grup) {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "izleme-satir";
          b.setAttribute("aria-pressed", String(h.sembol === durum.sembol));
          b.disabled = !!h.grafiksiz;
          if (h.grafiksiz) b.title = "No chart data";
          const ad = document.createElement("span");
          ad.className = "ad";
          ad.textContent = h.sembol;
          const fiyat = document.createElement("span");
          fiyat.className = "fiyat";
          fiyat.textContent = h.fiyat == null ? "—" : sayi(h.fiyat);
          const deg = document.createElement("span");
          deg.className = "degisim";
          degisimYaz(deg, h.degisim);
          b.append(ad, fiyat, deg);
          b.onclick = () => sembolSec(h.sembol);
          bolum.append(b);
        }
      }
      parcalar.push(bolum);
    }
    if (!parcalar.length) {
      const bos = document.createElement("p");
      bos.className = "bos";
      bos.textContent = "No symbols.";
      parcalar.push(bos);
    }
    kutu.replaceChildren(...parcalar);
  }

  function sembolSec(sembol) {
    if (sembol === durum.sembol || !izlemeListesi.some((h) => h.sembol === sembol)) return;
    durum.sembol = sembol;
    kaydet();
    izlemeCiz();
    yukle();
  }

  function baslikFiyatYaz() {
    const h = izlemeListesi.find((x) => x.sembol === durum.sembol);
    const el = $("#baslik-fiyat");
    el.replaceChildren();
    if (!h || h.fiyat == null) return;
    const f = document.createElement("span");
    f.textContent = `$${sayi(h.fiyat)}`;
    const d = document.createElement("span");
    d.className = "degisim";
    degisimYaz(d, h.degisim);
    el.append(f, d);
  }

  async function izlemeYenile() {
    try {
      izlemeListesi = await getir("/api/izleme");
      izlemeCiz();
      baslikFiyatYaz();
    } catch (e) { /* sessiz: bir sonraki yenilemede tekrar */ }
  }

  function seciciDoldur(sel, secenekler) {
    sel.replaceChildren(...secenekler.map((s) => { const o = document.createElement("option"); o.textContent = s; return o; }));
  }

  // ---------------------------------------------------------- tablolar --
  // Alpaca'dan salt-okur (sunucu 10 sn önbellekli). Panel emir göndermez.
  const para = (x) => x == null ? "—" : `$${Number(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const adetYaz = (x) => x == null ? "—" : Number(x).toLocaleString("en-US", { maximumFractionDigits: 6 });
  let emirListesi = [];

  function hucre(tr, metin, sinif) {
    const td = document.createElement("td");
    td.textContent = metin;
    if (sinif) td.className = sinif;
    tr.append(td);
    return td;
  }

  function bosSatir(govde, sutun, metin) {
    const tr = document.createElement("tr");
    const td = hucre(tr, metin, "bos");
    td.colSpan = sutun;
    govde.replaceChildren(tr);
  }

  let pozHata = null, emirHata = null;

  function pozisyonlariCiz() {
    const govde = $("#poz-govde");
    const sinif = $("#poz-sinif").value, yon = $("#poz-yon").value;
    const liste = pozisyonListesi.filter((p) => (sinif === "All" || p.sinif === sinif) && (yon === "All" || p.yon === yon));
    if (pozHata) return bosSatir(govde, 9, `Alpaca unreachable — ${pozHata}`);
    if (!liste.length) return bosSatir(govde, 9, pozisyonListesi.length ? "No positions match the filters." : "No open positions.");
    govde.replaceChildren(...liste.map((p) => {
      const tr = document.createElement("tr");
      const ad = hucre(tr, p.sembol, "sembol");
      if (izlemeListesi.some((h) => h.sembol === p.sembol)) { tr.classList.add("tiklanir"); tr.onclick = () => sembolSec(p.sembol); }
      ad.title = p.sembol;
      hucre(tr, p.sinif); hucre(tr, p.yon);
      hucre(tr, adetYaz(p.adet), "s"); hucre(tr, para(p.ort_maliyet), "s"); hucre(tr, para(p.fiyat), "s");
      hucre(tr, para(p.piyasa_degeri), "s");
      const kz = hucre(tr, para(p.kz), "s kz");
      const kzy = hucre(tr, p.kz_yuzde == null ? "—" : `${p.kz_yuzde >= 0 ? "+" : ""}${p.kz_yuzde.toFixed(2)}%`, "s kz");
      for (const td of [kz, kzy]) td.dataset.yon = p.kz == null ? "" : p.kz >= 0 ? "yukari" : "asagi";
      return tr;
    }));
  }

  const DURUM_GRUBU = {
    Open: ["new", "accepted", "pending_new", "partially_filled", "held", "accepted_for_bidding",
           "pending_replace", "pending_cancel", "calculated", "done_for_day"],
    Filled: ["filled"],
    Canceled: ["canceled", "expired", "replaced", "rejected", "stopped", "suspended"],
  };

  function emirTipi(e) {
    const ad = { limit: "Limit", market: "Market", stop: "Stop", stop_limit: "Stop Limit", trailing_stop: "Trailing Stop" }[e.tip] || e.tip;
    const seviye = e.tip === "stop" ? e.stop : e.tip === "stop_limit" ? e.stop : e.limit;
    return seviye == null ? ad : `${ad} @ ${para(seviye)}`;
  }

  function zamanYaz(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString("en-US", {
      month: "short", day: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  }

  function emirleriCiz() {
    const govde = $("#emir-govde");
    const ara = $("#emir-ara").value.trim().toUpperCase();
    const dg = $("#emir-durum").value, yon = $("#emir-yon").value.toLowerCase();
    const liste = emirListesi.filter((e) =>
      (!ara || (e.sembol || "").toUpperCase().includes(ara) || (e.kimlik || "").toUpperCase().includes(ara)) &&
      (dg === "All" || (DURUM_GRUBU[dg] || []).includes(e.durum)) &&
      (yon === "all" || e.yon === yon));
    if (emirHata) return bosSatir(govde, 8, `Alpaca unreachable — ${emirHata}`);
    if (!liste.length) return bosSatir(govde, 8, emirListesi.length ? "No orders match the filters." : "No orders yet.");
    govde.replaceChildren(...liste.map((e) => {
      const tr = document.createElement("tr");
      hucre(tr, e.sembol, "sembol").title = e.kimlik || "";
      hucre(tr, emirTipi(e));
      hucre(tr, e.yon);
      hucre(tr, adetYaz(e.adet), "s"); hucre(tr, adetYaz(e.dolan), "s"); hucre(tr, para(e.dolan_fiyat), "s");
      const d = hucre(tr, e.durum, "durum");
      d.dataset.durum = DURUM_GRUBU.Filled.includes(e.durum) ? "dolu" : DURUM_GRUBU.Open.includes(e.durum) ? "acik" : "kapali";
      hucre(tr, zamanYaz(e.gonderildi), "zaman");
      return tr;
    }));
  }

  async function tablolariYenile() {
    try {
      const [p, e] = await Promise.all([getir("/api/pozisyonlar"), getir("/api/emirler")]);
      pozisyonListesi = p.satirlar; pozHata = p.hata;
      emirListesi = e.satirlar; emirHata = e.hata;
      pozisyonlariCiz();
      emirleriCiz();
      izlemeCiz();
    } catch (err) { /* sessiz: bir sonraki yenilemede tekrar */ }
  }

  function filtreleriKur() {
    const siniflar = ["All"].concat(yapilandirma.siniflar);
    seciciDoldur($("#izleme-sinif"), siniflar);
    seciciDoldur($("#poz-sinif"), siniflar);
    $("#izleme-ara").addEventListener("input", izlemeCiz);
    $("#izleme-sinif").addEventListener("change", izlemeCiz);
    $("#poz-sinif").addEventListener("change", pozisyonlariCiz);
    $("#poz-yon").addEventListener("change", pozisyonlariCiz);
    $("#emir-ara").addEventListener("input", emirleriCiz);
    $("#emir-durum").addEventListener("change", emirleriCiz);
    $("#emir-yon").addEventListener("change", emirleriCiz);
  }

  // ------------------------------------------------------------ yükleme --
  // EKRANA GÖRE: açılışta ekranda görünecek sürenin 2 katı yüklenir. Geriye
  // sürükleyip yüklü verinin başına yaklaşınca, görünen genişliğin 2 katı
  // kadar daha eski veri istenip sola eklenir. Aralık düğmesi, hedef pencere
  // zaten yüklüyse yalnızca pencereyi kaydırır.
  //
  // Arada 30 sn'de bir yalnızca işaretler sorulur: yeni mum → sona eklenir;
  // yeni karar → küçük canlı katman yenilenir; depo baştan indirildiyse
  // (tam_yenileme) her şey baştan.
  let yukleniyor = false;
  let bekleyenYukleme = false;
  let isaret = null;           // son tam yüklemedeki işaretler (/api/ozet)
  let kapsam = null;           // /api/kapsam: verinin sınırları (grafik zamanı)
  let yuklu = null;            // { bas } — grafikteki mumlar bas'tan sona kadar (delik yok)
  let btBas = null;            // backtest'in yüklendiği baş (null: hiç yüklenmedi)
  let btHam = {};              // çizgi → ham noktalar (kopukVeri öncesi)
  let nesil = 0;               // baştan yüklemede eski istekleri geçersiz kılar
  let genisliyor = false;
  const sembolQ = () => `sembol=${encodeURIComponent(durum.sembol)}`;
  const barQ = () => `${sembolQ()}&tf=${durum.tf}`;

  function mumlaraCevir(p) {
    const n = p.time.length, out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = { time: p.time[i], open: p.open[i], high: p.high[i],
                                           low: p.low[i], close: p.close[i], volume: p.volume ? p.volume[i] : 0 };
    return out;
  }

  function cizgiyeCevir(c) {
    const n = c.time.length, out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = c.value[i] === null ? { time: c.time[i] } : { time: c.time[i], value: c.value[i] };
    return out;
  }

  // Grafiği bellekteki veriden kurar. `pencereyiKoru`: görünen aralık aynı kalsın.
  function cizimiYenile(pencereyiKoru) {
    const pencere = pencereyiKoru ? grafik.timeScale().getVisibleRange() : null;
    mumSerisi.setData(veri.mumlar);
    for (const cz of CIZGILER) {
      seriler.backtest[cz.ad].setData(durum.katman.backtest ? kopukVeri(btHam[cz.ad] || []) : []);
    }
    gostergeleriCiz();
    isaretleriCiz();
    if (pencere) grafik.timeScale().setVisibleRange(pencere);
    btOzetYaz();
  }

  function btEkle(d, bas) {
    // Gelen parça yüklü backtest'in SOLUNA eklenir (daha eski).
    for (const cz of CIZGILER) btHam[cz.ad] = cizgiyeCevir(d.cizgiler[cz.ad]).concat(btHam[cz.ad] || []);
    veri.backtest.islemler = d.islemler.concat(veri.backtest.islemler);
    veri.backtest.ozet = d.ozet || veri.backtest.ozet;
    veri.backtest.kasa_baslangici = d.kasa_baslangici;
    btBas = bas;
  }

  // Backtest katmanı açıksa, yüklü mumların backtest'i eksik kalmasın.
  // Bir şey indirdiyse true (çizim yenilenmeli).
  async function btTamamla() {
    if (!kuralTfMi() || !durum.katman.backtest || !yuklu) return false;
    if (btBas !== null && btBas <= yuklu.bas) return false;
    const gen = nesil;
    const bit = btBas === null ? "" : `&bit=${btBas}`;
    const d = await getir(`/api/katman/backtest?${sembolQ()}&bas=${yuklu.bas}${bit}`);
    if (gen !== nesil) return false;
    btEkle(d, yuklu.bas);
    return true;
  }

  // [bas, yuklu.bas) aralığını iste, sola ekle, görünen pencereyi koru.
  async function yukleSol(bas) {
    if (!yuklu || genisliyor || bas >= yuklu.bas) return;
    genisliyor = true;
    const gen = nesil;
    try {
      const istekler = [getir(`/api/barlar?${barQ()}&bas=${bas}&bit=${yuklu.bas}`)];
      const btIste = kuralTfMi() && durum.katman.backtest && btBas !== null && btBas <= yuklu.bas;
      if (btIste) istekler.push(getir(`/api/katman/backtest?${sembolQ()}&bas=${bas}&bit=${yuklu.bas}`));
      const [b, d] = await Promise.all(istekler);
      if (gen !== nesil) return;
      veri.mumlar = mumlaraCevir(b).concat(veri.mumlar);
      yuklu.bas = bas;
      if (btIste) btEkle(d, bas);
      await btTamamla();
      if (gen !== nesil) return;
      cizimiYenile(true);
    } catch (e) {
      terminaleYaz(`Geçmiş yüklenemedi: ${e.message}`, "hata");
    } finally {
      genisliyor = false;
    }
  }

  // Açılış penceresi: son ACILIS_GUN gün. Sağda 2 saat pay: motorun son
  // kararı henüz oluşmamış bir sonraki bara çizilir; pencere son mumda
  // kesilirse o nokta dışarıda kalır.
  function acilisPenceresi() {
    const son = veri.mumlar.length ? veri.mumlar[veri.mumlar.length - 1].time : kapsam.son;
    return { from: son - tfBilgi(durum.tf).gun * 86400, to: son + 2 * 3600 };
  }

  // Pencerenin 2 katını kapsayacak baş (verinin başıyla sınırlı).
  const ikiKatBas = (pen) => Math.max(kapsam.ilk, pen.to - 2 * (pen.to - pen.from));

  // Hedef pencere yüklüyse yalnızca kaydır; değilse eksik sol kısmı iste.
  async function pencereyeGit(pen) {
    if (!kapsam || !yuklu) return;
    const bas = ikiKatBas(pen);
    if (bas < yuklu.bas) await yukleSol(bas);
    if (await btTamamla()) cizimiYenile(false);
    grafik.timeScale().setVisibleRange(pen);
  }

  function bekleyeniCalistir() {
    if (!bekleyenYukleme) return;
    bekleyenYukleme = false;
    yukle();
  }

  function bosCanli() {
    return { cizgiler: Object.fromEntries(CIZGILER.map((c) => [c.ad, []])), islemler: [], sinyal_sayisi: 0 };
  }

  function canliCiz(c) {
    veri.canli = c;
    for (const cz of CIZGILER) seriler.canli[cz.ad].setData(kopukVeri(c.cizgiler[cz.ad] || []));
  }

  function sunucuEski(neden) {
    const m = `Panel sunucusu eski (${neden}) — kapatıp yeniden başlat: python -m src.arayuz`;
    terminaleYaz(m, "hata");
    $("#baslik-bar").textContent = "⚠ server outdated — restart it";
  }

  // Baştan yükleme: açılışta, sembol değişince, depo baştan indirilince.
  async function yukle() {
    if (!durum.sembol) return;
    if (yukleniyor) { bekleyenYukleme = true; return; }     // kaybolmasın
    yukleniyor = true;
    const gen = ++nesil;
    yuklu = null; btBas = null; btHam = {}; genisliyor = false;
    veri = { mumlar: [], canli: null, backtest: bosBacktest() };
    try {
      // İşaretler ÖNCE alınır: yükleme sırasında gelen yeni bar kaçmasın.
      const [o, k, c] = await Promise.all([
        getir(`/api/ozet?${sembolQ()}`), getir(`/api/kapsam?${barQ()}`),
        kuralTfMi() ? getir(`/api/katman/canli?${sembolQ()}`) : Promise.resolve(bosCanli()),
      ]);
      if (gen !== nesil) return;
      isaret = o.isaretler;
      kapsam = k;
      tfDugmeleriniCiz();
      canliCiz(c);
      $("#baslik-sembol").textContent = durum.sembol;
      basligiYaz(k.son_iso);
      baslikFiyatYaz();
      if (k.ilk === null) { cizimiYenile(false); return; }
      // Açılış: ekranda görünecek sürenin 2 katı.
      const pen = acilisPenceresi();
      const bas = ikiKatBas(pen);
      const b = await getir(`/api/barlar?${barQ()}&bas=${bas}`);
      if (gen !== nesil) return;
      veri.mumlar = mumlaraCevir(b);
      yuklu = { bas };
      await btTamamla();
      if (gen !== nesil) return;
      cizimiYenile(false);
      gorunurlukUygula();
      grafik.timeScale().setVisibleRange(acilisPenceresi());
      degerPaneli(null);
    } catch (e) {
      if (String(e.message).includes("HTTP 404")) sunucuEski("bilinmeyen adres");
      else terminaleYaz(`Veri yüklenemedi: ${e.message}`, "hata");
    } finally {
      yukleniyor = false;
      bekleyeniCalistir();
    }
  }

  function basligiYaz(son) {
    $("#baslik-bar").textContent = son
      ? `Last bar ${son.slice(0, 16).replace("T", " ")} UTC · ${tfBilgi(durum.tf).baslik}`
      : "No data";
  }

  // Yalnızca değişeni al. Sırası önemli: yeni mum canlı çizginin yerini de
  // etkiler (son kararın barı depoya gelince), o yüzden mumdan sonra canlı.
  async function degisiklikleriAl(yeni) {
    if (!yeni || !isaret || yukleniyor || !yuklu) return;
    if (yeni.tam_yenileme !== isaret.tam_yenileme) { await yukle(); return; }
    const barDegisti = yeni.son_bar !== isaret.son_bar;
    const kararDegisti = yeni.son_sinyal !== isaret.son_sinyal;
    if (!barDegisti && !kararDegisti) return;
    yukleniyor = true;
    try {
      if (barDegisti) {
        const son = veri.mumlar.length ? veri.mumlar[veri.mumlar.length - 1].time : 0;
        const b = await getir(`/api/barlar?${barQ()}&sonra=${son}`);
        for (const m of mumlaraCevir(b)) { mumSerisi.update(m); veri.mumlar.push(m); }
        if (b.time.length) kapsam.son = b.time[b.time.length - 1];
        basligiYaz(b.son);
      }
      if (kuralTfMi()) canliCiz(await getir(`/api/katman/canli?${sembolQ()}`));
      gostergeleriCiz();
      isaretleriCiz();
      isaret = yeni;
      degerPaneli(null);
    } catch (e) {
      /* sessiz: bir sonraki yoklamada tekrar denenir */
    } finally {
      yukleniyor = false;
      bekleyeniCalistir();
    }
  }

  async function ozetYenile() {
    try {
      const o = await getir(durum.sembol ? `/api/ozet?sembol=${encodeURIComponent(durum.sembol)}` : "/api/ozet");
      const r = $("#rozet-dongu");
      if (o.dongu_ayakta) {
        const t = o.son_tur;
        r.innerHTML = `<span class="isaret" aria-hidden="true"></span>Engine: running` +
          (t ? ` · last run ${t.baslangic_utc.slice(11, 16)} UTC ${TUR_SONUCU[t.sonuc] || t.sonuc}` : "");
        r.dataset.seviye = !t ? "uyari" : t.sonuc === "hata" ? "kotu"
          : t.sonuc === "durduruldu" ? "uyari" : "iyi";
      } else {
        r.innerHTML = `<span class="isaret" aria-hidden="true"></span>Engine: stopped`;
        r.dataset.seviye = "kotu";
      }
      const f = $("#rozet-bayrak");
      if (o.dur) { f.textContent = "EMERGENCY STOP active"; f.className = "rozet tehlike"; f.hidden = false; }
      else if (o.duraklat) { f.textContent = "PAUSED"; f.className = "rozet tehlike"; f.hidden = false; }
      else f.hidden = true;
      await degisiklikleriAl(o.isaretler);
    } catch (e) { /* sessiz: bir sonraki yenilemede tekrar */ }
  }

  const SEVIYE_ADI = { bilgi: "info", uyari: "warning", kotu: "critical" };
  const TUR_SONUCU = { tamam: "ok", hata: "error", durduruldu: "halted" };

  function isoTarih(iso) {
    return new Date(iso.replace(/\+0000$/, "Z"));
  }

  function trSaati(iso) {
    const d = isoTarih(iso);
    return isNaN(d) ? iso.slice(0, 16) : d.toLocaleString("tr-TR", {
      timeZone: "Europe/Istanbul", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  }

  function uyariSatiri(u) {
    const li = document.createElement("li");
    const satir = document.createElement("div");
    satir.className = "uyari-satir";
    satir.dataset.seviye = u.seviye;
    const isaret = document.createElement("span");
    isaret.className = "isaret";
    isaret.title = SEVIYE_ADI[u.seviye] || u.seviye;
    const zaman = document.createElement("span");
    zaman.className = "zaman";
    zaman.textContent = trSaati(u.son_utc);
    const konu = document.createElement("span");
    konu.className = "konu";
    konu.textContent = u.konu;
    satir.append(isaret, zaman, konu);
    if (u.tekrar > 1) {
      const t = document.createElement("span");
      t.className = "tekrar";
      t.textContent = `×${u.tekrar}`;
      t.title = `ilk: ${trSaati(u.ilk_utc)}`;
      satir.append(t);
    }
    li.append(satir);
    if (u.mesaj && u.mesaj !== u.konu) {
      const d = document.createElement("details");
      const s = document.createElement("summary");
      s.textContent = "details";
      const pre = document.createElement("pre");
      pre.textContent = u.mesaj;
      d.append(s, pre);
      li.append(d);
    }
    return li;
  }

  async function uyarilariYenile() {
    try {
      const liste = await getir("/api/uyarilar?adet=20");
      $("#uyari-listesi").replaceChildren(...liste.map(uyariSatiri));
      $("#uyari-bos").hidden = liste.length > 0;
      const gun = Date.now() - 24 * 3600 * 1000;
      const yakin = liste.filter((u) => u.seviye !== "bilgi" && isoTarih(u.son_utc) > gun);
      $("#uyari-ozet").textContent = (yakin.length ? `${yakin.length} issues in last 24h · ` : "") + "Istanbul time";
    } catch (e) { /* sessiz: bir sonraki yenilemede tekrar */ }
  }

  async function saglikYenile(taze) {
    const d = $("#saglik-dugme");
    d.querySelector(".yazi").textContent = "Health…";
    try {
      const s = await getir(`/api/saglik${taze ? "?taze=true" : ""}`);
      const kotu = s.kontroller.filter((k) => k.seviye === "kotu");
      const uyari = s.kontroller.filter((k) => k.seviye === "uyari");
      d.dataset.seviye = kotu.length ? "kotu" : uyari.length ? "uyari" : "iyi";
      d.querySelector(".yazi").textContent = kotu.length ? `Health: ${kotu.length} issue${kotu.length > 1 ? "s" : ""}`
        : uyari.length ? `Health: ${uyari.length} warning${uyari.length > 1 ? "s" : ""}` : "Health: OK";
      d.title = s.kontroller.map((k) => `${k.seviye === "iyi" ? "✓" : k.seviye === "uyari" ? "!" : "✗"} ${k.ad}: ${k.mesaj}`).join("\n");
    } catch (e) {
      d.dataset.seviye = "kotu";
      d.querySelector(".yazi").textContent = "Health: unavailable";
    }
  }

  // ---------------------------------------------------------- terminal --
  const gecmis = oku("panel.gecmis", []);
  let gecmisIndeks = gecmis.length;

  function terminaleYaz(metin, sinif) {
    const cikti = $("#terminal-cikti");
    const span = document.createElement("span");
    if (sinif) span.className = sinif;
    span.textContent = metin + "\n";
    cikti.appendChild(span);
    cikti.scrollTop = cikti.scrollHeight;
  }

  async function komutGonder(metin) {
    let anahtar = "";
    try { anahtar = localStorage.getItem("panel.anahtar") || ""; } catch (e) { /* yok */ }
    const r = await fetch("/api/komut", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Arayuz-Anahtari": anahtar },
      body: JSON.stringify({ metin }),
    });
    if (r.status === 401) {
      const yeni = window.prompt("Komut anahtarı (.env → ARAYUZ_ANAHTARI):");
      if (yeni) {
        try { localStorage.setItem("panel.anahtar", yeni); } catch (e) { /* yok */ }
        return komutGonder(metin);
      }
      return { metin: "Anahtar girilmedi — komut gönderilmedi.", basarili: false };
    }
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      return { metin: j.detail || `HTTP ${r.status}`, basarili: false };
    }
    return r.json();
  }

  function terminalKur() {
    terminaleYaz("KABUL-1 console. Type /help for commands.", "soluk");
    const girdi = $("#terminal-girdi");
    $("#terminal-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const metin = girdi.value.trim();
      if (!metin) return;
      girdi.value = "";
      gecmis.push(metin);
      while (gecmis.length > 50) gecmis.shift();
      gecmisIndeks = gecmis.length;
      yaz("panel.gecmis", gecmis);
      terminaleYaz("> " + metin, "girdi");
      try {
        const s = await komutGonder(metin);
        terminaleYaz(s.metin, s.tehlikeli ? "uyari" : s.basarili ? "" : "hata");
      } catch (err) {
        terminaleYaz("Komut gönderilemedi: " + err.message, "hata");
      }
      ozetYenile();
      saglikYenile(false);
      uyarilariYenile();
    });
    girdi.addEventListener("keydown", (e) => {
      if (e.key === "ArrowUp" && gecmisIndeks > 0) { gecmisIndeks--; girdi.value = gecmis[gecmisIndeks]; e.preventDefault(); }
      if (e.key === "ArrowDown") {
        gecmisIndeks = Math.min(gecmis.length, gecmisIndeks + 1);
        girdi.value = gecmis[gecmisIndeks] || "";
        e.preventDefault();
      }
    });
  }

  // ------------------------------------------------------------ başlat --
  async function basla() {
    grafikKur();
    terminalKur();
    $("#saglik-dugme").addEventListener("click", () => saglikYenile(true));
    try {
      yapilandirma = await getir("/api/yapilandirma");
      if (yapilandirma.surum !== SURUM) sunucuEski(`sürüm ${yapilandirma.surum ?? "yok"}, sayfa ${SURUM}`);
      filtreleriKur();
      tfDugmeleriniCiz();
      gostergeMenusunuKur();
      izlemeListesi = await getir("/api/izleme");
      if (!durum.sembol || !izlemeListesi.some((h) => h.sembol === durum.sembol)) durum.sembol = yapilandirma.motor_sembolu;
      izlemeCiz();
      secimleriCiz();
      tablolariYenile();
      await yukle();
    } catch (e) {
      terminaleYaz("Panel başlatılamadı: " + e.message, "hata");
    }
    ozetYenile();
    saglikYenile(false);
    uyarilariYenile();
    setInterval(() => { ozetYenile(); uyarilariYenile(); izlemeYenile(); tablolariYenile(); }, 30000);
    setInterval(() => saglikYenile(false), 120000);
  }

  basla();
})();
