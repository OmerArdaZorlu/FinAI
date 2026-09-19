/* KABUL-1 paneli — grafik, çizgi seçimi, kontrol terminali.
 *
 * Sunucu yalnızca okur; komutlar bayrak dosyası bırakır (bkz. src/arayuz/komut.py).
 * Zaman ekseni New York duvar saatidir (sunucu çevirip veriyor).
 */
(function () {
  "use strict";

  const LWC = window.LightweightCharts;

  // Çizgiler: sıra = palet slot sırası (stil.css). Renk varlığa bağlı, sıraya değil.
  const CIZGILER = [
    { ad: "tepe",       baslik: "tepe",        renk: "--seri-tepe" },
    { ad: "dip",        baslik: "dip",         renk: "--seri-dip" },
    { ad: "alis",       baslik: "alış seviyesi", renk: "--seri-alis" },
    { ad: "zarar_stop", baslik: "zarar stopu", renk: "--seri-zarar" },
    { ad: "takip_stop", baslik: "takip stopu", renk: "--seri-takip" },
  ];
  const KATMANLAR = ["canli", "backtest"];
  const KISA = { canli: "C", backtest: "B" };

  // -------------------------------------------------------------- durum --
  const VARSAYILAN = {
    sembol: null,
    aralik: "60g",
    katman: { canli: true, backtest: false },
    cizgi: {
      canli: { tepe: true, dip: true, alis: true, zarar_stop: true, takip_stop: true, islemler: true },
      backtest: { tepe: true, dip: true, alis: false, zarar_stop: true, takip_stop: true, islemler: true },
    },
  };
  let durum = oku("panel.durum", VARSAYILAN);
  durum = Object.assign({}, VARSAYILAN, durum);
  durum.cizgi = Object.assign({}, VARSAYILAN.cizgi, durum.cizgi || {});

  // Adres çubuğu kaydedilmiş seçimi ezer: ?sembol=AAPL&aralik=arastirma&katman=canli,backtest
  // (belirli bir görünümü bağlantı olarak paylaşmak için).
  (function () {
    const p = new URLSearchParams(location.search);
    if (p.get("sembol")) durum.sembol = p.get("sembol").toUpperCase();
    if (p.get("aralik")) durum.aralik = p.get("aralik");
    if (p.has("katman")) {
      const secili = p.get("katman").split(",");
      for (const k of KATMANLAR) durum.katman[k] = secili.includes(k);
    }
  })();

  let yapilandirma = null;
  let veri = { mumlar: [], canli: null, backtest: null };

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
  const renk = (degisken) => getComputedStyle(document.documentElement).getPropertyValue(degisken).trim();

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
      timeScale: { borderColor: renk("--eksen"), timeVisible: true, secondsVisible: false },
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
          title: `${KISA[k]} ${c.baslik}`,        // eksende doğrudan etiket
          crosshairMarkerVisible: false,
        });
      }
    }
    grafik.subscribeCrosshairMove(degerPaneli);
    // Tema değişirse renkleri yenile.
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(renkleriYenile);
  }

  function renkleriYenile() {
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
    isaretleriCiz();
  }

  function gorunurlukUygula() {
    for (const k of KATMANLAR) {
      for (const c of CIZGILER) {
        seriler[k][c.ad].applyOptions({ visible: !!(durum.katman[k] && durum.cizgi[k][c.ad]) });
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
  function kopukVeri(dizi) {
    const cikti = [];
    for (let i = 0; i < dizi.length; i++) {
      const p = dizi[i];
      if (p.value !== undefined) { cikti.push(p); continue; }
      const onceki = cikti[cikti.length - 1];
      if (!onceki || onceki.color === SAYDAM || onceki.son) continue;   // baştaki / ardışık boşluk
      const sonraki = dizi.slice(i + 1).find((q) => q.value !== undefined);
      cikti.push(sonraki ? { time: p.time, value: sonraki.value, color: SAYDAM }
                         : { time: p.time, value: onceki.value, son: true });
    }
    return cikti.map(({ son, ...p }) => p);
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
      if (!durum.katman[k] || !durum.cizgi[k].islemler || !veri[k]) continue;
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
    const son = mum || veri.mumlar[veri.mumlar.length - 1];
    if (son) {
      const t = new Date(son.time * 1000);
      const z = t.toISOString().slice(0, 16).replace("T", " ");
      parca.push(`<span class="d">${z} NY</span>`);
      parca.push(`<span class="d">A <b>${sayi(son.open)}</b></span><span class="d">Y <b>${sayi(son.high)}</b></span>` +
                 `<span class="d">D <b>${sayi(son.low)}</b></span><span class="d">K <b>${sayi(son.close)}</b></span>`);
    }
    if (p && p.time !== undefined) {
      for (const k of KATMANLAR) {
        if (!durum.katman[k]) continue;
        for (const c of CIZGILER) {
          if (!durum.cizgi[k][c.ad]) continue;
          const d = p.seriesData.get(seriler[k][c.ad]);
          if (!d || d.value === undefined || d.color === SAYDAM) continue;   // boşluk
          parca.push(`<span class="d"><span class="ornek${k === "backtest" ? " kesikli" : ""}" ` +
                     `style="border-color:${renk(c.renk)}"></span>${KISA[k]} ${c.baslik} <b>${sayi(d.value)}</b></span>`);
        }
      }
      for (const i of islemHaritasi.get(p.time) || []) {
        const al = i.yon === "al";
        let metin = `${i.katman === "canli" ? "Canlı" : "Backtest"} ${al ? "ALIŞ" : "SATIŞ (" + i.sebep + ")"} <b>${sayi(i.fiyat)}</b>`;
        if (!al && i.getiri != null) metin += ` · maliyet dahil <b>${(i.getiri * 100).toFixed(1)}%</b>`;
        if (i.istenen != null) metin += ` · istenen ${sayi(i.istenen)}`;
        parca.push(`<span class="d">${al ? "▲" : "▼"} ${metin}</span>`);
      }
    }
    kutu.innerHTML = parca.join("");
  }

  // ---------------------------------------------------------- yan panel --
  function hisseleriCiz(liste) {
    const ul = $("#hisseler");
    ul.innerHTML = "";
    for (const h of liste) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.className = "hisse";
      b.type = "button";
      b.setAttribute("aria-pressed", String(h.sembol === durum.sembol));
      let alt = "";
      if (h.motor && h.pozisyon && h.pozisyon.acik) {
        const p = h.pozisyon;
        alt = `${p.adet} adet · giriş ${sayi(p.giris)} · ${p.takipte ? "takip" : "stop"} ${sayi(p.stop)}`;
      } else if (h.motor) {
        alt = "nakitte";
      } else {
        alt = "yalnızca izleniyor";
      }
      b.innerHTML = `<div class="ust"><span class="ad">${h.sembol}</span>` +
                    (h.motor ? `<span class="etiket-motor">motor</span>` : "") +
                    `</div><div class="alt">${alt}</div>`;
      b.addEventListener("click", () => { durum.sembol = h.sembol; kaydet(); hisseleriCiz(liste); yukle(true); });
      li.appendChild(b);
      ul.appendChild(li);
    }
  }

  function araliklariCiz() {
    const kutu = $("#araliklar");
    kutu.innerHTML = "";
    for (const [anahtar, ad] of Object.entries(yapilandirma.araliklar)) {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(anahtar === durum.aralik));
      b.textContent = ad;
      b.addEventListener("click", () => { durum.aralik = anahtar; kaydet(); araliklariCiz(); yukle(true); });
      kutu.appendChild(b);
    }
  }

  function secimleriCiz() {
    for (const k of KATMANLAR) {
      const ana = document.querySelector(`input[data-katman="${k}"]`);
      ana.checked = !!durum.katman[k];
      ana.onchange = () => { durum.katman[k] = ana.checked; kaydet(); secimleriCiz(); gorunurlukUygula(); };

      const kutu = document.querySelector(`[data-katman-listesi="${k}"]`);
      kutu.innerHTML = "";
      const ogeler = CIZGILER.map((c) => ({ ad: c.ad, baslik: c.baslik, renk: c.renk }))
        .concat([{ ad: "islemler", baslik: "işlemler (▲ al, ▼ sat)", renk: null }]);
      for (const o of ogeler) {
        const lab = document.createElement("label");
        if (!durum.katman[k]) lab.className = "pasif";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = !!durum.cizgi[k][o.ad];
        cb.disabled = !durum.katman[k];
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

  function notlariYaz() {
    const cn = $("#canli-not"), bn = $("#backtest-not");
    const c = veri.canli;
    if (c && c.not) { cn.textContent = c.not; cn.hidden = false; }
    else if (c && c.sinyal_sayisi === 0) {
      cn.textContent = "Bu aralıkta motor kaydı yok — paper koşusu başlayınca dolacak.";
      cn.hidden = false;
    } else cn.hidden = true;

    const b = veri.backtest;
    if (b && b.ozet) {
      $("#bt-ozet").textContent = `${b.ozet.islem} işlem, 1 → ${Number(b.ozet.lira).toFixed(2)} (maliyet dahil).`;
    }
    const cizgiVar = b && Object.values(b.cizgiler).some((l) => l.some((p) => p.value !== undefined));
    if (b && !cizgiVar) {
      bn.textContent = `Kasa (${b.kasa_baslangici} sonrası) kapalı — backtest orada hesaplanmıyor. ` +
                       "Görmek için aralığı “Araştırma dönemi” yap.";
      bn.hidden = false;
    } else bn.hidden = true;
  }

  // ------------------------------------------------------------ yükleme --
  let yukleniyor = false;
  async function yukle(sigdir) {
    if (!durum.sembol || yukleniyor) return;
    yukleniyor = true;
    const q = `sembol=${encodeURIComponent(durum.sembol)}&aralik=${durum.aralik}`;
    try {
      const [b, c, t] = await Promise.all([
        getir(`/api/barlar?${q}`), getir(`/api/katman/canli?${q}`), getir(`/api/katman/backtest?${q}`),
      ]);
      veri = { mumlar: b.mumlar, canli: c, backtest: t };
      mumSerisi.setData(b.mumlar);
      for (const k of KATMANLAR) for (const cz of CIZGILER) seriler[k][cz.ad].setData(kopukVeri(veri[k].cizgiler[cz.ad] || []));
      gorunurlukUygula();
      notlariYaz();
      $("#baslik-sembol").textContent = durum.sembol;
      $("#baslik-bar").textContent = b.son ? `son bar ${b.son.slice(0, 16).replace("T", " ")} UTC · 1 saat` : "veri yok";
      degerPaneli(null);
      if (sigdir) grafik.timeScale().fitContent();
    } catch (e) {
      terminaleYaz(`Veri yüklenemedi: ${e.message}`, "hata");
    } finally {
      yukleniyor = false;
    }
  }

  async function ozetYenile() {
    try {
      const o = await getir("/api/ozet");
      const r = $("#rozet-dongu");
      if (o.dongu_ayakta) {
        const t = o.son_tur;
        r.innerHTML = `<span class="isaret" aria-hidden="true"></span>döngü ayakta` +
          (t ? ` · son tur ${t.baslangic_utc.slice(11, 16)} UTC ${t.sonuc}` : "");
        r.dataset.seviye = !t ? "uyari" : t.sonuc === "hata" ? "kotu"
          : t.sonuc === "durduruldu" ? "uyari" : "iyi";
      } else {
        r.innerHTML = `<span class="isaret" aria-hidden="true"></span>döngü ÇALIŞMIYOR`;
        r.dataset.seviye = "kotu";
      }
      const f = $("#rozet-bayrak");
      if (o.dur) { f.textContent = "ACİL DURDURMA etkin"; f.className = "rozet tehlike"; f.hidden = false; }
      else if (o.duraklat) { f.textContent = "DURAKLATILDI"; f.className = "rozet tehlike"; f.hidden = false; }
      else f.hidden = true;
    } catch (e) { /* sessiz: bir sonraki yenilemede tekrar */ }
  }

  const SEVIYE_ADI = { bilgi: "bilgi", uyari: "uyarı", kotu: "kötü" };

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
      s.textContent = "ayrıntı";
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
      $("#uyari-ozet").textContent = yakin.length ? `son 24 saatte ${yakin.length} sorun · TR saati` : "TR saati";
    } catch (e) { /* sessiz: bir sonraki yenilemede tekrar */ }
  }

  async function saglikYenile(taze) {
    const d = $("#saglik-dugme");
    d.querySelector(".yazi").textContent = "sağlık…";
    try {
      const s = await getir(`/api/saglik${taze ? "?taze=true" : ""}`);
      const kotu = s.kontroller.filter((k) => k.seviye === "kotu");
      const uyari = s.kontroller.filter((k) => k.seviye === "uyari");
      d.dataset.seviye = kotu.length ? "kotu" : uyari.length ? "uyari" : "iyi";
      d.querySelector(".yazi").textContent = kotu.length ? `sağlık: ${kotu.length} sorun`
        : uyari.length ? `sağlık: ${uyari.length} uyarı` : "sağlık: iyi";
      d.title = s.kontroller.map((k) => `${k.seviye === "iyi" ? "✓" : k.seviye === "uyari" ? "!" : "✗"} ${k.ad}: ${k.mesaj}`).join("\n");
    } catch (e) {
      d.dataset.seviye = "kotu";
      d.querySelector(".yazi").textContent = "sağlık: bakılamadı";
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
    terminaleYaz("KABUL-1 kontrol terminali. Komutlar için /yardim", "soluk");
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
      const hisseler = await getir("/api/hisseler");
      if (!durum.sembol || !hisseler.some((h) => h.sembol === durum.sembol)) durum.sembol = yapilandirma.motor_sembolu;
      if (!yapilandirma.araliklar[durum.aralik]) durum.aralik = "60g";
      hisseleriCiz(hisseler);
      araliklariCiz();
      secimleriCiz();
      await yukle(true);
    } catch (e) {
      terminaleYaz("Panel başlatılamadı: " + e.message, "hata");
    }
    ozetYenile();
    saglikYenile(false);
    uyarilariYenile();
    setInterval(() => { yukle(false); ozetYenile(); uyarilariYenile(); }, 30000);
    setInterval(() => saglikYenile(false), 120000);
  }

  basla();
})();
