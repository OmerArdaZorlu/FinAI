"""Grafik testleri — çizimin çöküp çökmediği ve *neyi* çizdiği.

Grafiğin görünümü test edilmez; test edilen, grafiğe giren **veri**. Bir
çubuğun yüksekliği tablodaki sayıdan gelmiyorsa, defterde göze güzel görünen
ama yanlış bir sonuç okunur — ölçüm hatasının en sinsi türü budur.

Ağ erişimi gerektirmez; ekran da gerektirmez (Agg arka ucu).
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")   # import lab.plots'tan ÖNCE — pencere açmaya çalışmasın

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab import plots  # noqa: E402
from lab.analysis import bin_table  # noqa: E402
from lab.session import session_report  # noqa: E402
from tests.test_session import hourly_bars  # noqa: E402


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plots.plt.close("all")


def trending_bars(n: int = 300) -> pd.DataFrame:
    """Yükselen ama dalgalı bir seri — kanal hesabı için yeterli yapı taşır."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, n))
    ts = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": close, "high": close + 1.0, "low": close - 1.0, "close": close,
        "volume": 1_000, "trade_count": 10, "vwap": close,
    })


# ------------------------------------------------------------- ÖZELLİK --

def test_channel_bands_draws_price_and_position_panels():
    fig = plots.channel_bands(trending_bars(), n=20, last=100)
    price_ax, pos_ax = fig.axes
    assert pos_ax.get_ylim()[1] <= 1.1        # konum paneli [0,1] ölçeğinde
    assert len(price_ax.lines) == 3           # tepe, dip, kapanış


def test_channel_bands_never_plots_the_warmup_rows():
    """İlk n−1 barda pencere dolmaz; NaN uydurma değerle doldurulmamalı."""
    df = trending_bars(120)
    fig = plots.channel_bands(df, n=20, last=None)
    drawn = fig.axes[1].lines[0].get_xdata()
    assert len(drawn) == len(df) - 19


def test_channel_bands_honours_the_last_argument():
    fig = plots.channel_bands(trending_bars(300), n=20, last=50)
    assert len(fig.axes[1].lines[0].get_xdata()) == 50


# --------------------------------------------------------------- DİLİM --

def test_bin_chart_bar_heights_match_the_table():
    rng = np.random.default_rng(3)
    x = pd.Series(rng.uniform(0, 1, 500))
    y = pd.Series(rng.normal(0, 0.01, 500))
    bins = bin_table(x, y)

    fig = plots.bin_chart(bins)
    heights = [p.get_height() for p in fig.axes[0].patches]
    assert heights == pytest.approx(bins["ortalama_getiri"].tolist())


def test_bin_chart_colours_split_at_the_reference_line():
    """Renk, tabanın altı/üstü ayrımını taşır — sıfırın değil."""
    bins = pd.DataFrame(
        {"bar": [50, 50], "ortalama_getiri": [0.004, 0.001],
         "medyan_getiri": [0.004, 0.001], "yukari_orani": [0.5, 0.5],
         "std": [0.01, 0.01]},
        index=pd.IntervalIndex.from_breaks([0.0, 0.5, 1.0]),
    )
    fig = plots.bin_chart(bins, reference=0.002)
    colors = [p.get_facecolor() for p in fig.axes[0].patches]
    assert matplotlib.colors.to_hex(colors[0]) == plots.POS   # taban üstü
    assert matplotlib.colors.to_hex(colors[1]) == plots.NEG   # taban altı


# ------------------------------------------------------------ İSTİKRAR --

def test_rho_chart_keeps_label_order_top_to_bottom():
    fig = plots.rho_chart(["N=20", "N=50", "N=100"], [-0.04, -0.05, 0.01])
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels == ["N=20", "N=50", "N=100"]


def test_rho_chart_marks_the_min_rho_band():
    fig = plots.rho_chart(["a", "b"], [-0.2, 0.02], min_rho=0.05)
    band = [p for p in fig.axes[0].patches
            if matplotlib.colors.to_hex(p.get_facecolor()) == plots.BAND]
    assert len(band) == 1
    left = band[0].get_x()
    assert left == pytest.approx(-0.05)
    assert left + band[0].get_width() == pytest.approx(0.05)


def test_rho_chart_axis_is_symmetric_around_zero():
    fig = plots.rho_chart(["a"], [-0.3], min_rho=0.05)
    lo, hi = fig.axes[0].get_xlim()
    assert lo == pytest.approx(-hi)


# ---------------------------------------------------------------- SEANS --

def test_session_profile_bar_per_hour():
    report = session_report(hourly_bars(days=4))
    fig = plots.session_profile(report)
    # 16 saat + gösterge için eklenen 2 boş çubuk
    assert len(fig.axes[0].patches) == len(report) + 2
    labels = [t.get_text() for t in fig.axes[0].get_xticklabels()]
    assert labels[0] == "04" and labels[-1] == "19"


def test_session_profile_colours_by_session():
    report = session_report(hourly_bars(days=4))
    fig = plots.session_profile(report)
    bars = fig.axes[0].patches[:len(report)]
    colors = {h: matplotlib.colors.to_hex(b.get_facecolor())
              for h, b in zip(report.index, bars)}
    assert colors[4] == plots.ALT     # uzatılmış
    assert colors[11] == plots.POS    # düzenli
