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
        ax.annotate(f"|rho| < {min_rho} · eşiğin altı", xy=(0, 1), xytext=(0, 6),
                    xycoords=("data", "axes fraction"), textcoords="offset points",
                    ha="center", color=MUTED, fontsize=9, fontfamily=_FONTS)

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
