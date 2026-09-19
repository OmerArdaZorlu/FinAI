/* Gösterge hesapları — saf fonksiyonlar, çizimle ilgisi yok.
 *
 * Hepsi {time, value} dizisi döndürür; değeri olmayan barlar (pencere henüz
 * dolmadıysa) ATLANIR, uydurulmaz. Girdi: mum dizisi (time/open/high/low/
 * close/volume), zamana göre sıralı.
 *
 * Hesap ekranda YÜKLÜ barlardan yapılır. Geriye sürükleyip daha fazla veri
 * gelince yeniden hesaplanır; o yüzden yüklü verinin en solunda gösterge
 * birkaç bar eksik başlar — periyot dolmadan değer yoktur.
 */
(function () {
  "use strict";

  const G = {};

  function nokta(mumlar, i, deger) {
    return { time: mumlar[i].time, value: deger };
  }

  // Basit hareketli ortalama.
  G.sma = function (mumlar, periyot, alan = "close") {
    const out = [];
    let toplam = 0;
    for (let i = 0; i < mumlar.length; i++) {
      toplam += mumlar[i][alan];
      if (i >= periyot) toplam -= mumlar[i - periyot][alan];
      if (i >= periyot - 1) out.push(nokta(mumlar, i, toplam / periyot));
    }
    return out;
  };

  // Üssel hareketli ortalama. İlk değer ilk `periyot` barın ortalaması.
  G.ema = function (mumlar, periyot, alan = "close") {
    if (mumlar.length < periyot) return [];
    const k = 2 / (periyot + 1), out = [];
    let e = 0;
    for (let i = 0; i < periyot; i++) e += mumlar[i][alan];
    e /= periyot;
    out.push(nokta(mumlar, periyot - 1, e));
    for (let i = periyot; i < mumlar.length; i++) {
      e = mumlar[i][alan] * k + e * (1 - k);
      out.push(nokta(mumlar, i, e));
    }
    return out;
  };

  // Bollinger: orta = SMA, bantlar = orta ± k × standart sapma (nüfus sapması).
  G.bollinger = function (mumlar, periyot, k) {
    const ust = [], orta = [], alt = [];
    let toplam = 0, kareToplam = 0;
    for (let i = 0; i < mumlar.length; i++) {
      const c = mumlar[i].close;
      toplam += c; kareToplam += c * c;
      if (i >= periyot) {
        const e = mumlar[i - periyot].close;
        toplam -= e; kareToplam -= e * e;
      }
      if (i >= periyot - 1) {
        const ort = toplam / periyot;
        const sapma = Math.sqrt(Math.max(0, kareToplam / periyot - ort * ort));
        ust.push(nokta(mumlar, i, ort + k * sapma));
        orta.push(nokta(mumlar, i, ort));
        alt.push(nokta(mumlar, i, ort - k * sapma));
      }
    }
    return { ust, orta, alt };
  };

  // RSI (Wilder). İlk değer ilk `periyot` barın ortalama kazanç/kaybından.
  G.rsi = function (mumlar, periyot) {
    if (mumlar.length <= periyot) return [];
    let kazanc = 0, kayip = 0;
    for (let i = 1; i <= periyot; i++) {
      const d = mumlar[i].close - mumlar[i - 1].close;
      if (d >= 0) kazanc += d; else kayip -= d;
    }
    kazanc /= periyot; kayip /= periyot;
    const deger = (k, z) => (z === 0 ? 100 : 100 - 100 / (1 + k / z));
    const out = [nokta(mumlar, periyot, deger(kazanc, kayip))];
    for (let i = periyot + 1; i < mumlar.length; i++) {
      const d = mumlar[i].close - mumlar[i - 1].close;
      kazanc = (kazanc * (periyot - 1) + (d > 0 ? d : 0)) / periyot;
      kayip = (kayip * (periyot - 1) + (d < 0 ? -d : 0)) / periyot;
      out.push(nokta(mumlar, i, deger(kazanc, kayip)));
    }
    return out;
  };

  // MACD = hızlı EMA − yavaş EMA; sinyal = MACD'nin EMA'sı; histogram = fark.
  G.macd = function (mumlar, hizli, yavas, sinyalPeriyot) {
    const h = G.ema(mumlar, hizli), y = G.ema(mumlar, yavas);
    if (!y.length) return { macd: [], sinyal: [], histogram: [] };
    const kaydir = h.length - y.length;
    const macd = y.map((p, i) => ({ time: p.time, value: h[i + kaydir].value - p.value }));
    // Sinyal, MACD çizgisinin EMA'sı: aynı fonksiyonu 'value' alanıyla kullan.
    const sinyal = G.ema(macd.map((p) => ({ time: p.time, close: p.value })), sinyalPeriyot);
    const fark = macd.length - sinyal.length;
    const histogram = sinyal.map((p, i) => ({ time: p.time, value: macd[i + fark].value - p.value }));
    return { macd, sinyal, histogram };
  };

  // Awesome Oscillator: orta fiyatın 5 ve 34 barlık SMA farkı.
  G.ao = function (mumlar, kisa = 5, uzun = 34) {
    const orta = mumlar.map((m) => ({ time: m.time, close: (m.high + m.low) / 2 }));
    const k = G.sma(orta, kisa), u = G.sma(orta, uzun);
    if (!u.length) return [];
    const kaydir = k.length - u.length;
    return u.map((p, i) => ({ time: p.time, value: k[i + kaydir].value - p.value }));
  };

  // Hacim: mum yönüne göre renkli çubuk.
  G.hacim = function (mumlar, yukariRenk, asagiRenk) {
    return mumlar.map((m) => ({
      time: m.time,
      value: m.volume,
      color: m.close >= m.open ? yukariRenk : asagiRenk,
    }));
  };

  window.Gosterge = G;
})();
