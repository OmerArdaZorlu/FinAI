"""Ölçüm grafikleri — sayıyı doğrulamak için, sayının yerine geçmek için değil.

Bu modül `lab.analysis` çıktılarının görsel karşılığıdır. **Hiçbir karar
grafiğe bakarak verilmez**: karar `rank_correlation()` ile, sonucu görmeden
ilan edilmiş eşiklere göre verilir (ARCHITECTURE.md §7.4). Grafiğin işi
başka: sayının *nasıl* oluştuğunu göstermek.

Neden grafik gerekli
--------------------
Tek bir rho, birbirinden çok farklı üç durumu aynı sayıya indirir:

* dipten tepeye düzenli bir eğim (**monotonik** — gerçek mekanizma imzası),
* yalnızca iki uç dilimin taşıdığı bir ilişki (kırılgan),
* birkaç uç gözlemin sürüklediği bir ilişki (gürültü).

Dilim grafiği üçünü ayırt eder. Bu yüzden `bin_chart()` her dilimin
belirsizliğini de (±2 standart hata) çizer: dilim ortalamalarının hata
payları birbirini örtüyorsa, ortada "eğim" yoktur — kalem izleri vardır.

Sızıntı uyarısı
---------------
`channel_bands()` özelliği geçmişe bakan hâliyle çizer (`rolling`). Grafiğe
bakarken dip/tepe bariz görünür çünkü sonrasını da görüyorsunuz; canlı
sistemde o lüks yok. Grafikten "burada alırdım" çıkarımı yapmayın —
`lab/h001.py` başındaki sızıntı sözleşmesi bu yüzden var.

Tasarım
-------
Tek bir açık zemin (`#fcfcfb`) kullanılır; defter teması koyu olsa bile
grafik kendi zeminini boyar, böylece dışa aktarılan görsel her yerde okunur.
Renk paleti renk körlüğü ayrımı için doğrulanmıştır (mavi/kırmızı çifti
protan ΔE 21.6, mavi/turuncu 24.7) ve renk hiçbir yerde tek başına bilgi
taşımaz: her seri ayrıca etiketlenir.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# --- Palet. Zemin açık; koyu tema karşılığı bilinçli olarak yok. ---
SURFACE = "#fcfcfb"     # grafik zemini
INK = "#0b0b0b"         # başlık
INK_SOFT = "#52514e"    # alt başlık, eksen etiketi
MUTED = "#898781"       # tik etiketleri, dipnot
GRID = "#e1e0d9"        # ızgara (saç teli)
AXIS = "#c3c2b7"        # taban çizgisi

POS = "#2a78d6"         # mavi — tabanın üstü
NEG = "#e34948"         # kırmızı — tabanın altı
ALT = "#eb6834"         # turuncu — ikinci kategori
FILL = "#cde2fb"        # açık mavi dolgu (kanal bandı)
BAND = "#f0efec"        # nötr — "anlamsız" bölge

_FONTS = ["Segoe UI", "DejaVu Sans", "sans-serif"]


def _figure(figsize: tuple[float, float], title: str, subtitle: str = "",
            *, nrows: int = 1, height_ratios: Sequence[float] | None = None):
    """Ortak iskelet: zemin, başlık, ızgara, çerçevesiz eksen."""
    fig, axes = plt.subplots(
        nrows, 1, figsize=figsize, sharex=(nrows > 1),
        gridspec_kw={"height_ratios": height_ratios} if height_ratios else None,
    )
    fig.patch.set_facecolor(SURFACE)
    for ax in np.atleast_1d(axes):
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(AXIS)
        ax.tick_params(colors=MUTED, labelsize=9, length=0)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontfamily(_FONTS)

    top = np.atleast_1d(axes)[0]
    top.set_title(title, loc="left", color=INK, fontsize=13,
                  fontweight="bold", fontfamily=_FONTS, pad=30 if subtitle else 8)
    if subtitle:
        top.annotate(subtitle, xy=(0, 1), xytext=(0, 9), textcoords="offset points",
                     xycoords="axes fraction", color=INK_SOFT, fontsize=9.5,
                     fontfamily=_FONTS, va="bottom")
    return fig, axes


def _pct(ax, axis: str = "y", decimals: int = 2) -> None:
    """Getiri eksenini yüzde olarak biçimler — 0.0013 yerine %0.13."""
    fmt = plt.FuncFormatter(lambda v, _: f"%{100 * v:.{decimals}f}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


# ------------------------------------------------------------- ÖZELLİK --

def channel_bands(
    df: pd.DataFrame,
    n: int,
    *,
    last: int | None = 250,
    figsize: tuple[float, float] = (11, 6.5),
):
    """Kanalı ve kanal konumunu yan yana çizer — özelliğin ne ölçtüğü.

    Üst panel fiyatı, son `n` barın en yüksek/en düşük seviyesiyle birlikte
    gösterir; alt panel bunun 0–1 arası karşılığını. Pencere **bugün dahil,
    yalnızca geriye** bakar; bantlar bu yüzden fiyatı bir bar gecikmeyle
    değil, o barın kendisini de sayarak sarar.

    Args:
        df: Kanonik bar tablosu (`timestamp`, `high`, `low`, `close`).
        n: Kanal penceresi (bar).
        last: Yalnızca son bu kadar bar çizilir; `None` ise tamamı. Binlerce
            barı tek grafiğe sıkıştırmak, görülmesi gereken yapıyı siler.

    Returns:
        `matplotlib.figure.Figure`.
    """
    from lab.h001 import channel_position

    pos = channel_position(df, n)
    part = df.assign(kanal_konumu=pos)
    part = part.assign(
        tepe=df["high"].rolling(n).max(),
        dip=df["low"].rolling(n).min(),
    ).dropna(subset=["kanal_konumu"])
    if last is not None:
        part = part.iloc[-last:]

    span = f'{part["timestamp"].iloc[0].date()} → {part["timestamp"].iloc[-1].date()}'
    fig, (ax_p, ax_k) = _figure(
        figsize, f"Kanal konumu — N={n} bar",
        f"{len(part)} bar  |  {span}  |  pencere yalnızca geriye bakar",
        nrows=2, height_ratios=[2.4, 1],
    )

    t = part["timestamp"]
    ax_p.fill_between(t, part["dip"], part["tepe"], color=FILL, zorder=1,
                      label=f"son {n} barın aralığı")
    ax_p.plot(t, part["tepe"], color=AXIS, linewidth=1.0, zorder=2)
    ax_p.plot(t, part["dip"], color=AXIS, linewidth=1.0, zorder=2)
    ax_p.plot(t, part["close"], color=POS, linewidth=2.0, zorder=3, label="kapanış")
    ax_p.set_ylabel("fiyat", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)
    leg = ax_p.legend(loc="upper left", frameon=False, fontsize=9)
    for text in leg.get_texts():
        text.set_color(INK_SOFT)
        text.set_fontfamily(_FONTS)

    ax_k.plot(t, part["kanal_konumu"], color=POS, linewidth=1.6, zorder=3)
    ax_k.axhline(0.5, color=AXIS, linewidth=1.0, linestyle="--", zorder=2)
    ax_k.set_ylim(-0.05, 1.05)
    ax_k.set_yticks([0, 0.5, 1])
    ax_k.set_yticklabels(["0 · dip", "0.5", "1 · tepe"])
    ax_k.set_ylabel("kanal konumu", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)

    fig.tight_layout()
    return fig


# --------------------------------------------------------------- DİLİM --

def bin_chart(
    bins: pd.DataFrame,
    *,
    reference: float | None = None,
    figsize: tuple[float, float] = (10, 5.5),
):
    """Dilim tablosunu çizer — ilişki monotonik mi, yoksa tek uç mu parlıyor?

    Her çubuk bir dilimin ortalama ileri getirisi; dikey çizgi **±2 standart
    hata** (ortalamanın belirsizliği). Hata payları birbirini ve tabanı
    örtüyorsa görünen eğim gürültüdür.

    En iyi dilimi seçmek için değildir — bu p-hacking'dir ve karar zaten
    `rank_correlation()` ile verilmiştir (`lab/analysis.py`).

    Args:
        bins: `analysis.bin_table()` çıktısı.
        reference: Karşılaştırma tabanı (ör. `baseline()`'ın ortalama
            getirisi). Verilmezse dilimlerin ağırlıklı ortalaması kullanılır.

    Returns:
        `matplotlib.figure.Figure`.
    """
    if reference is None:
        reference = float(np.average(bins["ortalama_getiri"], weights=bins["bar"]))

    mean = bins["ortalama_getiri"].to_numpy(dtype=float)
    se = bins["std"].to_numpy(dtype=float) / np.sqrt(bins["bar"].to_numpy(dtype=float))
    x = np.arange(len(bins))
    colors = [POS if m >= reference else NEG for m in mean]

    fig, ax = _figure(
        figsize, "Dilim tablosu — kanal konumuna göre ileri getiri",
        "çubuk: dilim ortalaması   |   çizgi: ±2 standart hata   |   "
        "karar bu grafikte verilmez",
    )
    ax.bar(x, mean, width=0.78, color=colors, zorder=3)
    ax.errorbar(x, mean, yerr=2 * se, fmt="none", ecolor=INK_SOFT,
                elinewidth=1.4, capsize=4, zorder=4)
    ax.axhline(reference, color=INK_SOFT, linewidth=1.4, linestyle="--", zorder=5)
    ax.annotate(f"taban  %{100 * reference:.3f}", xy=(1, reference),
                xycoords=("axes fraction", "data"), xytext=(-4, 5),
                textcoords="offset points", ha="right", color=INK_SOFT,
                fontsize=9, fontfamily=_FONTS)

    ax.set_xticks(x)
    # `pd.cut(include_lowest=True)` ilk dilimin sol ucunu −0.001'e çeker;
    # etikette 0.0 yazmak doğru, kanal konumu [0, 1] aralığında tanımlı.
    ax.set_xticklabels([f"{max(iv.left, 0.0):.1f}–{iv.right:.1f}" for iv in bins.index],
                       rotation=45, ha="right")
    ax.set_xlabel("kanal konumu dilimi  (0 = dip, 1 = tepe)",
                  color=INK_SOFT, fontsize=10, fontfamily=_FONTS)
    ax.set_ylabel("ortalama ileri getiri", color=INK_SOFT, fontsize=10,
                  fontfamily=_FONTS)
    _pct(ax)

    fig.tight_layout()
    return fig


# ------------------------------------------------------------ İSTİKRAR --

def rho_chart(
    labels: Iterable,
    rhos: Iterable[float],
    *,
    min_rho: float = 0.0,
    title: str = "Sıra korelasyonu",
    subtitle: str = "",
    figsize: tuple[float, float] = (9, None),
):
    """rho değerlerini tek eksende karşılaştırır — pencere, dönem ya da kat.

    Ortadaki gri şerit `±min_rho`: bu şeridin içinde kalan bir rho, p değeri
    ne olursa olsun **ilan edilmiş eşiği geçmez**. Şeridi grafiğe koymak,
    "istatistiksel olarak anlamlı ama pratikte sıfır" sonucunu gözle görünür
    kılar.

    Mean-reversion hipotezi **negatif** rho bekler; işaretin gruplar arasında
    değişmesi etkinin kararsız olduğunun işaretidir.

    Args:
        labels: Grup adları (N değeri, dönem adı, kat numarası...).
        rhos: Her gruba karşılık gelen rho.
        min_rho: İlan edilmiş asgari etki büyüklüğü.

    Returns:
        `matplotlib.figure.Figure`.
    """
    labels = [str(v) for v in labels]
    values = np.asarray(list(rhos), dtype=float)
    width, height = figsize
    if height is None:
        height = 1.9 + 0.55 * len(labels)

    fig, ax = _figure((width, height), title, subtitle)
    y = np.arange(len(labels))[::-1]

    if min_rho > 0:
        ax.axvspan(-min_rho, min_rho, color=BAND, zorder=1)
        # Şeridin içine, en alta: üstte alt başlıkla çakışıyordu.
        ax.annotate(f"|rho| < {min_rho} · eşiğin altı", xy=(0, 0), xytext=(0, 6),
                    xycoords=("data", "axes fraction"), textcoords="offset points",
                    ha="center", va="bottom", color=MUTED, fontsize=9,
                    fontfamily=_FONTS)

    ax.barh(y, values, height=0.6,
            color=[NEG if v < 0 else POS for v in values], zorder=3)
    ax.axvline(0, color=AXIS, linewidth=1.2, zorder=4)

    # Az sayıda çubuk var; değeri doğrudan yazmak eksenden okumaktan doğru.
    pad = 0.04 * max(np.abs(values).max(), min_rho, 0.01)
    for yi, v in zip(y, values):
        ax.text(v + (pad if v >= 0 else -pad), yi, f"{v:+.3f}",
                ha="left" if v >= 0 else "right", va="center",
                color=INK_SOFT, fontsize=9.5, fontfamily=_FONTS)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("Spearman rho", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)
    ax.grid(axis="y", visible=False)
    limit = max(np.abs(values).max(), min_rho) * 1.35 + 0.01
    ax.set_xlim(-limit, limit)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------- SEANS --

def session_profile(
    report: pd.DataFrame,
    *,
    figsize: tuple[float, float] = (10, 5),
):
    """Saat bazında hacim payı — seans filtresinin neyi kestiği.

    Uzatılmış seans barları sayıca çoğunluktadır ama hacmin küçük bir kısmını
    taşır. Filtresiz bir kanal hesabında alt/üst çizgiyi çoğu zaman bu seyrek
    barlar belirler; grafiğin gösterdiği fark budur (`lab/session.py`).

    Args:
        report: `session.session_report()` çıktısı.

    Returns:
        `matplotlib.figure.Figure`.
    """
    duzenli = report["seans"] == "düzenli"
    payi = report["hacim_payi"].to_numpy(dtype=float)
    x = np.arange(len(report))

    fig, ax = _figure(
        figsize, "Seans profili — saat başına hacim payı",
        f'{int(duzenli.sum())} saat düzenli seans, hacmin '
        f'%{100 * payi[duzenli.to_numpy()].sum():.1f}\'ini taşıyor',
    )
    ax.bar(x, payi, width=0.78, zorder=3,
           color=[POS if d else ALT for d in duzenli])

    # Renk tek başına bilgi taşımasın: seans sınırları ayrıca işaretlenir.
    for handle, name in ((POS, "düzenli seans"), (ALT, "uzatılmış seans")):
        ax.bar([np.nan], [np.nan], color=handle, label=name)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=9.5)
    for text in leg.get_texts():
        text.set_color(INK_SOFT)
        text.set_fontfamily(_FONTS)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}" for h in report.index])
    ax.set_xlabel("borsa saati (New York)", color=INK_SOFT, fontsize=10,
                  fontfamily=_FONTS)
    ax.set_ylabel("hacim payı", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)
    _pct(ax, decimals=0)

    fig.tight_layout()
    return fig


# --------------------------------------------------------------- AL-SAT --

def _legend(ax, **kw) -> None:
    leg = ax.legend(frameon=False, fontsize=9.5, **kw)
    for text in leg.get_texts():
        text.set_color(INK_SOFT)
        text.set_fontfamily(_FONTS)


def trades_chart(
    df: pd.DataFrame,
    sonuc,
    *,
    last: int = 120,
    figsize: tuple[float, float] = (11, 5.5),
):
    """Fiyat, tepe/dip çizgileri ve al-sat noktaları — sistem ne yapıyor.

    Args:
        df: `backtest.calistir()`'a verilen bar tablosu.
        sonuc: `backtest.calistir()` çıktısı.
        last: Yalnızca son bu kadar bar çizilir.

    Returns:
        `matplotlib.figure.Figure`.
    """
    part = df.iloc[-last:]
    lines = sonuc.cizgiler.loc[part.index]
    t0, t1 = part["timestamp"].iloc[0], part["timestamp"].iloc[-1]
    tr = sonuc.islemler
    tr = tr[(tr["alis_zamani"] >= t0) & (tr["alis_zamani"] <= t1)] if len(tr) else tr

    n = sonuc.kurallar.n
    if getattr(sonuc.kurallar, "cizgi", "donchian") == "bollinger":
        baslik = f"Al-sat noktaları — {n} barlık ortalama ± {sonuc.kurallar.sapma_katsayisi:g} sapma"
    else:
        baslik = f"Al-sat noktaları — son {n} barın tepe ve dip çizgisi"
    fig, ax = _figure(
        figsize, baslik,
        f"{len(part)} bar  |  {t0.date()} → {t1.date()}  |  {len(tr)} işlem",
    )
    t = part["timestamp"]
    ax.plot(t, lines["tepe"], color=AXIS, linewidth=1.4, drawstyle="steps-post",
            label="tepe çizgisi (direnç)")
    ax.plot(t, lines["dip"], color=AXIS, linewidth=1.4, drawstyle="steps-post",
            linestyle="--", label="dip çizgisi (destek)")
    ax.plot(t, part["close"], color=INK_SOFT, linewidth=1.6, label="kapanış")

    if len(tr):
        tepe = tr[tr["sebep"] == "tepe"]   # dönem sonunda kapatılan işaretlenmez
        stop = tr[tr["sebep"] == "stop"]
        ax.scatter(tr["alis_zamani"], tr["alis"], marker="^", s=70, color=POS,
                   edgecolor=SURFACE, linewidth=1.2, zorder=5, label="al")
        ax.scatter(tepe["satis_zamani"], tepe["satis"], marker="v", s=70, color=ALT,
                   edgecolor=SURFACE, linewidth=1.2, zorder=5, label="tepede sat")
        ax.scatter(stop["satis_zamani"], stop["satis"], marker="X", s=70, color=NEG,
                   edgecolor=SURFACE, linewidth=1.2, zorder=5, label="zararına sat (stop)")
        takip = tr[tr["sebep"] == "takip"]
        if len(takip):
            ax.scatter(takip["satis_zamani"], takip["satis"], marker="D", s=55, color=ALT,
                       edgecolor=INK_SOFT, linewidth=1.2, zorder=5, label="takip eden stopla sat")

    ax.set_ylabel("fiyat", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)
    _legend(ax, loc="upper left", ncol=3)
    fig.tight_layout()
    return fig


def equity_chart(
    df: pd.DataFrame,
    sonuc,
    *,
    figsize: tuple[float, float] = (11, 5),
):
    """Başlangıçtaki 1 liranın zamanla ne olduğu: sistem vs başta al, sonda sat.

    Returns:
        `matplotlib.figure.Figure`.
    """
    m = sonuc.kurallar.maliyet
    al_tut = (df["close"] / df["close"].iloc[0] * (1 - m) / (1 + m)).to_numpy()
    sistem = sonuc.bakiye.to_numpy()
    t = df["timestamp"]

    fig, ax = _figure(
        figsize, "1 lira ne oldu — sistem ve başta al, sonda sat",
        "maliyet dahil  |  sistem yalnızca pozisyondayken piyasada",
    )
    ax.plot(t, al_tut, color=ALT, linewidth=2.0, label="başta al, sonda sat")
    ax.plot(t, sistem, color=POS, linewidth=2.0, label="sistem")
    ax.axhline(1.0, color=AXIS, linewidth=1.0, zorder=1)

    for y, color in ((al_tut[-1], ALT), (sistem[-1], POS)):
        ax.annotate(f"{y:.2f}", xy=(t.iloc[-1], y), xytext=(6, 0),
                    textcoords="offset points", va="center", color=INK_SOFT,
                    fontsize=10, fontfamily=_FONTS)

    ax.set_ylabel("1 liranın değeri", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)
    _legend(ax, loc="upper left")
    fig.tight_layout()
    return fig


# ------------------------------------------------- KABUL DEFTERİ ŞABLONU --
# 2026-09-11 eklendi. lab/KABUL-1_AAPL_takip_eden_stop.ipynb ve ondan
# türeyecek defterler kullanır.

# Tek renkli sıralı ramp (mavi 100 → 700), ısı haritası için
_MAVI_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
              "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]


def _ylabel(ax, text: str) -> None:
    ax.set_ylabel(text, color=INK_SOFT, fontsize=10, fontfamily=_FONTS)


def _end_label(ax, x, y, text: str) -> None:
    ax.annotate(text, xy=(x, y), xytext=(6, 0), textcoords="offset points",
                va="center", color=INK_SOFT, fontsize=10, fontfamily=_FONTS)


def price_split_chart(
    df: pd.DataFrame,
    kasa_baslangici: str,
    kasa_bitisi: str,
    *,
    sembol: str = "",
    figsize: tuple[float, float] = (11, 4.8),
):
    """Araştırma dönemindeki fiyat ve saklanan verinin (kasa) yeri.

    Kasa döneminin fiyatları **çizilmez**; sadece tarih aralığı gri alanla
    işaretlenir. `df` yalnızca araştırma verisi olmalı.
    """
    k0, k1 = pd.Timestamp(kasa_baslangici, tz="UTC"), pd.Timestamp(kasa_bitisi, tz="UTC")
    if df["timestamp"].iloc[-1] >= k0:
        raise ValueError("df kasa dönemini içeriyor; yalnızca araştırma verisi verin.")
    t0 = df["timestamp"].iloc[0]
    fig, ax = _figure(
        figsize, f"{sembol} — kullanılan veri ve saklanan veri",
        f"araştırma: {t0.date()} → {df['timestamp'].iloc[-1].date()}  |  "
        f"saklanan: {k0.date()} → {k1.date()} (açılmadı, fiyatı çizilmedi)",
    )
    ax.plot(df["timestamp"], df["close"], color=POS, linewidth=1.6, label="kapanış")
    ax.axvspan(k0, k1, color=BAND, zorder=1)
    ax.axvline(k0, color=AXIS, linewidth=1.2, zorder=2)
    ax.text(k0 + (k1 - k0) / 2, 0.5, "saklanan veri\naçılmadı", transform=ax.get_xaxis_transform(),
            ha="center", va="center", color=MUTED, fontsize=10, fontfamily=_FONTS)
    ax.set_xlim(t0, k1)
    _ylabel(ax, "fiyat")
    fig.tight_layout()
    return fig


def lines_chart(
    df: pd.DataFrame,
    sonuc,
    bas: str,
    son: str,
    *,
    figsize: tuple[float, float] = (11, 5.2),
):
    """Çizgilerin nasıl çizildiği: yakın plan, son N günlük pencere işaretli."""
    def _utc(x):
        x = pd.Timestamp(x)
        return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")

    t = df["timestamp"]
    m = (t >= _utc(bas)) & (t <= _utc(son))
    part, lines, sev = df[m], sonuc.cizgiler[m], sonuc.seviyeler[m]
    n = sonuc.kurallar.n
    fig, ax = _figure(
        figsize, f"Çizgiler nasıl çiziliyor — son {n} barın en yükseği ve en düşüğü",
        "her bar pencere bir bar kayar  |  o anki bar hesaba katılmaz  |  "
        "gri alan: son barın çizgilerini belirleyen pencere",
    )
    tt = part["timestamp"]
    # son barın penceresi: ondan önceki n bar
    i_son = part.index[-1]
    pencere = df.loc[i_son - n:i_son - 1, "timestamp"]
    ax.axvspan(pencere.iloc[0], pencere.iloc[-1], color=BAND, zorder=0)
    ax.fill_between(tt, lines["dip"], lines["tepe"], color=FILL, alpha=0.55, step="post", zorder=1)
    ax.plot(tt, lines["tepe"], color=INK_SOFT, linewidth=1.4, drawstyle="steps-post",
            label="tepe çizgisi (direnç)")
    ax.plot(tt, lines["dip"], color=INK_SOFT, linewidth=1.4, linestyle="--",
            drawstyle="steps-post", label="dip çizgisi (destek)")
    ax.plot(tt, sev["alis_seviyesi"], color=POS, linewidth=1.2, linestyle=":",
            drawstyle="steps-post", label="alış seviyesi (elde hisse yokken)")
    # Çizgiler en yüksek/en düşükten çizilir; kapanış tek başına bunu göstermez.
    ax.vlines(tt, part["low"], part["high"], color=INK_SOFT, linewidth=2.2, alpha=0.45,
              zorder=2, label="barın en düşüğü – en yükseği")
    ax.plot(tt, part["close"], color=INK, linewidth=1.8, label="kapanış")
    # Fiyatın çizgiyi kırdığı barlar: çizgi bir sonraki bardan itibaren yeni seviyeye kayar
    kirdi_ust = part["high"] > lines["tepe"]
    kirdi_alt = part["low"] < lines["dip"]
    ax.scatter(tt[kirdi_ust], part["high"][kirdi_ust], marker="^", s=34, color=ALT,
               zorder=4, label="tepeyi aştı → çizgi ertesi bar yükselir")
    ax.scatter(tt[kirdi_alt], part["low"][kirdi_alt], marker="v", s=34, color=NEG,
               zorder=4, label="dibi aştı → çizgi ertesi bar düşer")
    _ylabel(ax, "fiyat")
    _legend(ax, loc="upper left", ncol=2)
    fig.tight_layout()
    return fig


def trade_anatomy_chart(
    df: pd.DataFrame,
    sonuc,
    islem_no: int,
    *,
    pay: int = 10,
    figsize: tuple[float, float] = (11, 5.5),
):
    """Tek bir işlemin baştan sona hikâyesi: al, koruma seviyesi, tepeye değme, sat."""
    tr = sonuc.islemler.iloc[islem_no]
    t = df["timestamp"]
    i_al = int(np.searchsorted(t, tr["alis_zamani"]))
    i_sat = int(np.searchsorted(t, tr["satis_zamani"]))
    a, b = max(i_al - pay, 0), min(i_sat + pay, len(df) - 1)
    part = df.iloc[a:b + 1]
    lines, sev = sonuc.cizgiler.iloc[a:b + 1], sonuc.seviyeler.iloc[a:b + 1]
    tt = part["timestamp"]

    getiri = tr["getiri_maliyetli"]
    fig, ax = _figure(
        figsize, f"Bir işlemin anatomisi — {pd.Timestamp(tr['alis_zamani']).date()} → "
                 f"{pd.Timestamp(tr['satis_zamani']).date()}",
        f"{tr['bar']} bar tutuldu  |  satış sebebi: {tr['sebep']}  |  "
        f"maliyet dahil {getiri:+.1%}  |  kırmızı ve turuncu: o an geçerli satış seviyesi",
    )
    ax.plot(tt, lines["tepe"], color=AXIS, linewidth=1.3, drawstyle="steps-post",
            label="tepe çizgisi")
    ax.plot(tt, lines["dip"], color=AXIS, linewidth=1.3, linestyle="--",
            drawstyle="steps-post", label="dip çizgisi")
    ax.plot(tt, part["close"], color=INK, linewidth=1.8, label="kapanış")

    # Sadece bu işlemin seviyeleri: pencerede başka işlem varsa onlarınkini gösterme
    bu_islem = np.zeros(len(sev), dtype=bool)
    bu_islem[i_al - a:i_sat - a + 1] = True
    takipte = sev["takipte"].to_numpy()
    kor = sev["koruma"].where(bu_islem & ~takipte)
    tak = sev["koruma"].where(bu_islem & takipte)

    # Eksen fiyata göre kurulur. Zararına satış seviyesi fiyatın çok altında
    # olabilir (stop payı 2 gibi); onu çizmek için ekseni aşağı çekmek grafiği
    # okunmaz yapıyor — o durumda çizgi yerine not düşülür.
    alt = float(min(part["low"].min(), tak.min() if tak.notna().any() else np.inf))
    ust = float(max(part["high"].max(), lines["tepe"].max()))
    ax.set_ylim(alt - 0.06 * (ust - alt), ust + 0.10 * (ust - alt))

    # Yastık: takip başladıktan sonra fiyatın satış seviyesine olan mesafesi
    ax.fill_between(tt, tak, part["close"], where=tak.notna(),
                    color=FILL, alpha=0.5, step="post", zorder=0)
    ax.plot(tt, kor, color=NEG, linewidth=2.0, drawstyle="steps-post",
            label="zararına satış seviyesi")
    ax.plot(tt, tak, color=ALT, linewidth=2.0, drawstyle="steps-post",
            label="takip eden stop (sadece yukarı gider)")

    if kor.notna().any() and float(kor.min()) < ax.get_ylim()[0]:
        s = float(kor.iloc[int(np.argmax(kor.notna().to_numpy()))])
        ax.annotate(f"zararına satış seviyesi {s:,.0f}\n"
                    f"(alış fiyatının %{100 * (1 - s / tr['alis']):.0f} altı, grafiğin dışında)",
                    xy=(tr["alis_zamani"], ax.get_ylim()[0]), xytext=(8, 10),
                    textcoords="offset points", color=NEG, fontsize=9,
                    fontfamily=_FONTS, va="bottom",
                    bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5))

    ax.scatter([tr["alis_zamani"]], [tr["alis"]], marker="^", s=110, color=POS,
               edgecolor=SURFACE, linewidth=1.4, zorder=6, label="al")
    ax.scatter([tr["satis_zamani"]], [tr["satis"]], marker="D", s=80,
               color=ALT if tr["sebep"] == "takip" else NEG,
               edgecolor=INK_SOFT, linewidth=1.2, zorder=6, label="sat")
    ax.annotate(f"al {tr['alis']:,.0f}", xy=(tr["alis_zamani"], tr["alis"]),
                xytext=(0, -16), textcoords="offset points", ha="center",
                color=POS, fontsize=9.5, fontfamily=_FONTS)
    ax.annotate(f"sat {tr['satis']:,.0f}  ({getiri:+.0%})",
                xy=(tr["satis_zamani"], tr["satis"]), xytext=(10, -4),
                textcoords="offset points", ha="left",
                color=ALT if tr["sebep"] == "takip" else NEG, fontsize=9.5,
                fontfamily=_FONTS,
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5))
    # tepeye ilk değdiği an
    ilk = sev.index[bu_islem & takipte]
    if len(ilk):
        j = ilk[0]
        ax.scatter([df.loc[j, "timestamp"]], [df.loc[j, "high"]], marker="o", s=70,
                   facecolor="none", edgecolor=ALT, linewidth=2.0, zorder=6,
                   label="tepeye değdi → takip başladı")
    _ylabel(ax, "fiyat")
    _legend(ax, loc="upper left", ncol=2)
    fig.tight_layout()
    return fig


def grid_heatmap(
    skorlar: pd.DataFrame,
    secilen: dict,
    *,
    baslik: str = "Eğitimde denenen ayarlar",
    figsize: tuple[float, float] = (12, 4.2),
):
    """Eğitimde denenen tüm eşik kombinasyonları: her hücre 1 liranın değeri.

    Satır: alım payı, sütun: zararına satış payı, panel: takip mesafesi.
    Seçilen kombinasyon kalın çerçeveli.
    """
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    cmap = LinearSegmentedColormap.from_list("mavi", _MAVI_RAMP)
    deger = skorlar["egitim_getirisi"] + 1
    norm = Normalize(vmin=float(deger.min()), vmax=float(deger.max()))
    alimlar = sorted(skorlar["alim_payi"].unique())
    stoplar = sorted(skorlar["stop_payi"].unique())
    takipler = sorted(skorlar["takip_payi"].unique()) if "takip_payi" in skorlar else [None]

    fig, axes = plt.subplots(1, len(takipler), figsize=figsize, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, tk in zip(axes[0], takipler):
        s = skorlar if tk is None else skorlar[skorlar["takip_payi"] == tk]
        mat = (s.pivot(index="alim_payi", columns="stop_payi", values="egitim_getirisi")
                .reindex(index=alimlar, columns=stoplar) + 1)
        ax.imshow(mat.to_numpy(), cmap=cmap, norm=norm, aspect="auto")
        for r, al in enumerate(alimlar):
            for c_, st in enumerate(stoplar):
                v = mat.iloc[r, c_]
                koyu = norm(v) > 0.55
                ax.text(c_, r, f"{v:.2f}", ha="center", va="center", fontsize=10,
                        color=SURFACE if koyu else INK, fontfamily=_FONTS)
                if (secilen.get("alim_payi") == al and secilen.get("stop_payi") == st
                        and (tk is None or secilen.get("takip_payi") == tk)):
                    ax.add_patch(plt.Rectangle((c_ - 0.5, r - 0.5), 1, 1, fill=False,
                                               edgecolor=INK, linewidth=3))
        ax.set_xticks(range(len(stoplar)), [f"{v:g}" for v in stoplar])
        ax.set_yticks(range(len(alimlar)), [f"{v:g}" for v in alimlar])
        ax.set_xlabel("zararına satış payı", color=INK_SOFT, fontsize=9.5, fontfamily=_FONTS)
        if ax is axes[0][0]:
            ax.set_ylabel("alım payı", color=INK_SOFT, fontsize=9.5, fontfamily=_FONTS)
        ax.set_title("" if tk is None else f"takip mesafesi {tk:g}", color=INK_SOFT,
                     fontsize=10.5, fontfamily=_FONTS)
        ax.tick_params(colors=MUTED, length=0)
        for side in ax.spines.values():
            side.set_visible(False)
    fig.suptitle(baslik, x=0.01, ha="left", color=INK, fontsize=13, fontweight="bold",
                 fontfamily=_FONTS)
    fig.text(0.01, 0.885, "her hücre: eğitim döneminde 1 liranın değeri  |  kalın çerçeve: seçilen",
             color=INK_SOFT, fontsize=9.5, fontfamily=_FONTS)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    return fig


def compare_equity_chart(
    sistem: pd.Series,
    baseline: pd.Series,
    *,
    baslik: str = "1 lira ne oldu",
    alt_baslik: str = "",
    figsize: tuple[float, float] = (11, 5),
):
    """İki bakiye eğrisi: sistem ve başta al, sonda sat."""
    fig, ax = _figure(figsize, baslik, alt_baslik)
    ax.plot(baseline.index, baseline.to_numpy(), color=ALT, linewidth=2.0,
            label="başta al, sonda sat (baseline)")
    ax.plot(sistem.index, sistem.to_numpy(), color=POS, linewidth=2.0, label="sistem")
    ax.axhline(1.0, color=AXIS, linewidth=1.0, zorder=1)
    _end_label(ax, baseline.index[-1], baseline.iloc[-1], f"{baseline.iloc[-1]:.2f}")
    _end_label(ax, sistem.index[-1], sistem.iloc[-1], f"{sistem.iloc[-1]:.2f}")
    _ylabel(ax, "1 liranın değeri")
    _legend(ax, loc="upper left")
    fig.tight_layout()
    return fig


def gap_chart(
    seriler: dict[str, tuple[pd.Series, pd.Series]],
    *,
    baslik: str = "Sistem baseline'dan ne kadar önde",
    alt_baslik: str = "",
    figsize: tuple[float, float] = (11, 5),
):
    """Her veri için sistem ÷ baseline − 1, gün sonu değerleriyle.

    `seriler`: {"günlük": (sistem, baseline), ...}. Günlük, saatlik ve
    dakikalık aynı eksende kıyaslansın diye her gün son bar alınır.
    0'ın üstü: sistem önde. Eğri ne kadar erken yükselirse fark o kadar hızlı açılmış.
    """
    renkler = [INK_SOFT, ALT, POS]
    fig, ax = _figure(figsize, baslik, alt_baslik)
    ax.axhline(0, color=AXIS, linewidth=1.2, zorder=1)
    for (ad, (sis, base)), renk in zip(seriler.items(), renkler):
        fark = sis / base.reindex(sis.index) - 1
        gun = fark.groupby(fark.index.tz_convert("America/New_York").date).last()
        gun.index = pd.to_datetime(gun.index)
        ax.plot(gun.index, gun.to_numpy(), color=renk, linewidth=1.8, label=ad)
        _end_label(ax, gun.index[-1], gun.iloc[-1], f"{gun.iloc[-1]:+.0%}")
    _pct(ax, decimals=0)
    _ylabel(ax, "sistem, baseline'dan % önde")
    _legend(ax, loc="upper left")
    fig.tight_layout()
    return fig


def yearly_bars_chart(
    yillar: Sequence,
    sistem: Sequence[float],
    baseline: Sequence[float],
    *,
    baslik: str = "Yıl yıl getiri",
    alt_baslik: str = "",
    figsize: tuple[float, float] = (11, 5),
):
    """Her yıl sistem ve baseline yan yana; değerler çubukların üstünde."""
    x = np.arange(len(yillar))
    w = 0.38
    fig, ax = _figure(figsize, baslik, alt_baslik)
    ax.bar(x - w / 2 - 0.01, sistem, width=w, color=POS, zorder=3, label="sistem")
    ax.bar(x + w / 2 + 0.01, baseline, width=w, color=ALT, zorder=3,
           label="başta al, sonda sat (baseline)")
    ax.axhline(0, color=AXIS, linewidth=1.2, zorder=4)
    for xi, s, b in zip(x, sistem, baseline):
        for dx, v in ((-w / 2 - 0.01, s), (w / 2 + 0.01, b)):
            ax.annotate(f"{v:+.0%}", xy=(xi + dx, v), xytext=(0, 4 if v >= 0 else -4),
                        textcoords="offset points", ha="center",
                        va="bottom" if v >= 0 else "top", color=INK_SOFT, fontsize=8.5,
                        fontfamily=_FONTS)
    ax.set_xticks(x, [str(y) for y in yillar])
    _pct(ax, decimals=0)
    _ylabel(ax, "getiri")
    ax.margins(y=0.15)
    _legend(ax, loc="upper right")
    fig.tight_layout()
    return fig


def drawdown_chart(
    sistem: pd.Series,
    baseline: pd.Series,
    *,
    baslik: str = "Zirveden kayıp — paranın bir ara ne kadarı eridi",
    figsize: tuple[float, float] = (11, 4.6),
):
    """Her an, o ana kadarki en yüksek değere göre kayıp. 0 = zirvede."""
    dd_s = sistem / sistem.cummax() - 1
    dd_b = baseline / baseline.cummax() - 1
    fig, ax = _figure(
        figsize, baslik,
        f"en büyük kayıp: sistem {dd_s.min():.0%}  |  baseline {dd_b.min():.0%}",
    )
    ax.fill_between(dd_b.index, dd_b.to_numpy(), 0, color=ALT, alpha=0.18, zorder=1)
    ax.plot(dd_b.index, dd_b.to_numpy(), color=ALT, linewidth=1.6,
            label="başta al, sonda sat (baseline)")
    ax.plot(dd_s.index, dd_s.to_numpy(), color=POS, linewidth=1.8, label="sistem")
    ax.axhline(0, color=AXIS, linewidth=1.0)
    _pct(ax, decimals=0)
    _ylabel(ax, "zirveden kayıp")
    _legend(ax, loc="lower left")
    fig.tight_layout()
    return fig


def trade_returns_chart(
    islemler: pd.DataFrame,
    *,
    baslik: str = "İşlem başına getiri (maliyet dahil)",
    figsize: tuple[float, float] = (11, 4.8),
):
    """Her işlem bir çubuk. Renk kazanç/kayıp, çubuğun ucundaki işaret satış sebebi."""
    g = islemler["getiri_maliyetli"].to_numpy()
    x = np.arange(len(g))
    kaz = int((g > 0).sum())
    fig, ax = _figure(figsize, baslik,
                      f"{len(g)} işlem  |  {kaz} kazançlı, {len(g) - kaz} zararlı  |  "
                      f"ortalama {g.mean():+.1%}")
    ax.bar(x, g, width=0.7, color=[POS if v > 0 else NEG for v in g], zorder=3)
    ax.axhline(0, color=AXIS, linewidth=1.2, zorder=4)
    isaret = {"takip": ("D", "takip eden stopla satış"), "stop": ("X", "zararına satış"),
              "donem_sonu": ("o", "yıl/dönem sonunda kapatıldı"), "tepe": ("v", "tepede satış")}
    for sebep, (mk, ad) in isaret.items():
        m = (islemler["sebep"] == sebep).to_numpy()
        if m.any():
            ax.scatter(x[m], g[m], marker=mk, s=45, color=SURFACE, edgecolor=INK_SOFT,
                       linewidth=1.3, zorder=5, label=ad)
    ax.set_xticks(x, [pd.Timestamp(t).strftime("%Y-%m") for t in islemler["alis_zamani"]],
                  rotation=60, ha="right", fontsize=8)
    _pct(ax, decimals=0)
    _ylabel(ax, "getiri")
    _legend(ax, loc="upper left", ncol=3)
    ax.margins(y=0.2)
    fig.tight_layout()
    return fig


def test_trades_chart(
    df: pd.DataFrame,
    yil_sonuclari: dict,
    *,
    figsize: tuple[float, float] = (12, 5.5),
):
    """Tüm test yılları tek grafikte: fiyat, çizgiler, al-sat noktaları, yıl sınırları."""
    n = next(iter(yil_sonuclari.values())).kurallar.n
    parca_c, parca_l, tr = [], [], []
    for yil in sorted(yil_sonuclari):
        s = yil_sonuclari[yil]
        parca_l.append(s.cizgiler.iloc[n:])
        tr.append(s.islemler)
    lines = pd.concat(parca_l)
    part = df.loc[lines.index]
    tr = pd.concat(tr, ignore_index=True)
    tt = part["timestamp"]
    fig, ax = _figure(
        figsize, "Test yıllarındaki tüm işlemler",
        f"{tt.iloc[0].date()} → {tt.iloc[-1].date()}  |  {len(tr)} işlem  |  "
        "dikey çizgiler: yıl sınırları (her yıl ayrı eğitildi)",
    )
    ax.plot(tt, lines["tepe"], color=AXIS, linewidth=1.0, drawstyle="steps-post",
            label="tepe çizgisi")
    ax.plot(tt, lines["dip"], color=AXIS, linewidth=1.0, linestyle="--",
            drawstyle="steps-post", label="dip çizgisi")
    ax.plot(tt, part["close"], color=INK_SOFT, linewidth=1.4, label="kapanış")
    for yil in sorted(yil_sonuclari)[1:]:
        ax.axvline(pd.Timestamp(f"{yil}-01-01", tz="UTC"), color=GRID, linewidth=2, zorder=0)
    ax.scatter(tr["alis_zamani"], tr["alis"], marker="^", s=70, color=POS,
               edgecolor=SURFACE, linewidth=1.2, zorder=5, label="al")
    for sebep, mk, renk, ad in (("takip", "D", ALT, "takip eden stopla sat"),
                                ("stop", "X", NEG, "zararına sat"),
                                ("donem_sonu", "o", MUTED, "yıl sonunda kapatıldı")):
        m = tr["sebep"] == sebep
        if m.any():
            ax.scatter(tr.loc[m, "satis_zamani"], tr.loc[m, "satis"], marker=mk, s=60,
                       color=renk, edgecolor=INK_SOFT, linewidth=1.0, zorder=5, label=ad)
    _ylabel(ax, "fiyat")
    _legend(ax, loc="upper left", ncol=3)
    fig.tight_layout()
    return fig
