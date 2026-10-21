"""One Matplotlib look for every chart in the program, taken from the design tokens: Segoe UI text, brand colours, light horizontal gridlines,
no top/right frame, no legend box.  Importing this module applies the style (``apply_style`` is idempotent).

Figures are always closed by their screen (``plt.close(fig)`` when the screen closes); see ``DashboardApp._close_figures`` and
``ReportsView._new_fig``.
"""
import matplotlib

from ui import theme as T

PALETTE = [T.PRIMARY, T.INFO, T.ACCENT, T.WARNING, T.DANGER_SOFT, T.TEXT_MUTED]


def apply_style():
    matplotlib.rcParams.update({
        "font.family": [T.FAMILY, "DejaVu Sans"],
        "font.size": 10,
        "text.color": T.TEXT,
        "figure.facecolor": T.SURFACE,
        "axes.facecolor": T.SURFACE,
        "axes.edgecolor": T.BORDER_STRONG,
        "axes.labelcolor": T.TEXT_SECONDARY,
        "axes.titlecolor": T.TEXT,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.axisbelow": True,
        "grid.color": T.BORDER,
        "grid.linewidth": 0.8,
        "xtick.color": T.TEXT_SECONDARY,
        "ytick.color": T.TEXT_SECONDARY,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.frameon": False,
        "legend.fontsize": 10,
        "axes.prop_cycle": matplotlib.cycler(color=PALETTE),
        "savefig.facecolor": T.SURFACE,
    })


apply_style()
