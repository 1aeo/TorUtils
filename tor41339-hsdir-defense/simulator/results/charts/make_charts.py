#!/usr/bin/env python3
"""Charts for the tor#41339 closed-lab off-vs-on matrix (x86, private chutney net).

Input: simulator/results/results-x86-full.csv (neutral columns).
Same net-health gate as simulator/scripts/analyze.py: a rep is valid iff
legit_attempts >= 30. Cell value = median over valid reps (served fraction =
median(load_recv) / median(load_issued), as in analyze.py). Individual valid
reps are drawn as dots; dropped reps are counted and annotated, never hidden.

Usage: make_charts.py <results.csv> <outdir>
Writes <name>.svg/.png (light) and <name>-dark.svg/.png, plus charts-data.csv
and charts-data.md (the table view).
"""
import csv, statistics, sys, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib import font_manager

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
GATE = 30

MODES = ["unpatched", "patched-observe", "patched-0001", "patched-0002", "patched-both"]
MODE_LABEL = {
    "unpatched": "Unpatched 0.4.9.14",
    "patched-observe": "Patched, count-only (default)",
    "patched-0001": "Patched, 0001 enforcing",
    "patched-0002": "Patched, 0002 enforcing",
    "patched-both": "Patched, 0001 + 0002 enforcing",
}
LOADS = ["fetch", "reuse-5", "reuse-22", "onehop", "adapted"]
LOAD_LABEL = {
    "none": "No load",
    "fetch": "Fetch\n(1 req/circuit)",
    "reuse-5": "Reuse-5\n(5 req/circuit)",
    "reuse-22": "Reuse-22\n(22 req/circuit)",
    "onehop": "One-hop\n(unlisted prev hop)",
    "adapted": "Adapted\n(1 req/circ, listed hop)",
}

# Reference palette (dataviz skill), categorical slots 1-5, validated for
# adjacent pairs in both modes (CVD dE 9.1 light / 8.4 dark).
THEMES = {
    "light": dict(series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
                  surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7"),
    "dark": dict(series=["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
                 surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835"),
}

for fam in ("Inter", "DejaVu Sans"):
    if any(fam == f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = fam
        break


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


rows = [r for r in csv.DictReader(open(SRC)) if not r.get("error")]
cells = {}
for r in rows:
    cells.setdefault((r["mode"], r["load"]), []).append(r)


def valid(r):
    la = num(r.get("legit_attempts"))
    return la is not None and la >= GATE


def cell(mode, load):
    rs = cells.get((mode, load), [])
    ok = [r for r in rs if valid(r)]
    def med(k):
        v = [num(r.get(k)) for r in ok]
        v = [x for x in v if x is not None]
        return statistics.median(v) if v else None
    iss, rcv = med("load_issued"), med("load_recv")
    served = rcv / iss if (iss and rcv is not None) else None
    rep_served = []
    for r in ok:
        i, v = num(r.get("load_issued")), num(r.get("load_recv"))
        if i and v is not None:
            rep_served.append(v / i)
    la, lo = med("legit_attempts"), med("legit_ok")
    legit = lo / la if (la and lo is not None) else None
    rep_legit = [num(r["legit_ok"]) / num(r["legit_attempts"]) for r in ok
                 if num(r.get("legit_attempts"))]
    bw = med("bytes_written")
    rep_bw = [num(r["bytes_written"]) for r in ok if num(r.get("bytes_written")) is not None]
    return dict(n=len(rs), n_ok=len(ok), served=served, rep_served=rep_served,
                legit=legit, rep_legit=rep_legit, bytes_w=bw, rep_bw=rep_bw)


DATA = {(m, l): cell(m, l) for m in MODES for l in ["none"] + LOADS}

# ---------------------------------------------------------------- table view
with open(os.path.join(OUT, "charts-data.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["configuration", "load", "valid_reps", "total_reps", "served_fraction_median",
                "stock_client_success_median", "target_bytes_written_median"])
    for m in MODES:
        for l in ["none"] + LOADS:
            c = DATA[(m, l)]
            if not c["n"]:
                continue
            w.writerow([m, l, c["n_ok"], c["n"],
                        "" if c["served"] is None else f"{c['served']:.3f}",
                        "" if c["legit"] is None else f"{c['legit']:.3f}",
                        "" if c["bytes_w"] is None else f"{c['bytes_w']:.0f}"])
with open(os.path.join(OUT, "charts-data.md"), "w") as fh:
    fh.write("| Configuration | Load | Valid / total reps | Served fraction | "
             "Stock-client success | Target bytes written (MB) |\n|---|---|---|---|---|---|\n")
    for m in MODES:
        for l in ["none"] + LOADS:
            c = DATA[(m, l)]
            if not c["n"]:
                continue
            sv = "-" if c["served"] is None else f"{c['served']:.2f}"
            lg = "-" if c["legit"] is None else f"{c['legit']:.3f}"
            by = "-" if c["bytes_w"] is None else f"{c['bytes_w'] / 1e6:.2f}"
            fh.write(f"| {MODE_LABEL[m]} | {l} | {c['n_ok']} / {c['n']} | {sv} | {lg} | {by} |\n")


# ---------------------------------------------------------------- helpers
def style_axes(ax, t):
    ax.set_facecolor(t["surface"])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.spines["bottom"].set_linewidth(1)
    ax.tick_params(colors=t["muted"], labelcolor=t["ink2"], length=0, labelsize=9.5)
    ax.yaxis.grid(True, color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def rounded_bar(ax, x, w, h, color, t, radius_px=4):
    """Bar anchored at y=0 with 4px-rounded data end (top) and a square base."""
    if h <= 0:
        return
    fig = ax.figure
    fig.canvas.draw()
    bbox = ax.get_window_extent()
    x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
    px_per_x = bbox.width / (x1 - x0); px_per_y = bbox.height / (y1 - y0)
    r_y = radius_px / px_per_y
    r_x = radius_px / px_per_x
    r = min(r_x, w / 2)
    aspect = (r_y / r_x) if r_x else 1
    if h * px_per_y < 2 * radius_px:      # too short to round: plain rect
        ax.add_patch(Rectangle((x - w / 2, 0), w, h, facecolor=color, edgecolor="none", zorder=3))
        return
    ax.add_patch(FancyBboxPatch((x - w / 2, 0), w, h,
                                boxstyle=f"round,pad=0,rounding_size={r}",
                                mutation_aspect=aspect, facecolor=color,
                                edgecolor="none", zorder=3))
    ax.add_patch(Rectangle((x - w / 2, 0), w, h - r_y, facecolor=color,
                           edgecolor="none", zorder=3))


def legend(fig, ax, t, handles_colors, ncol=3, y=0.905):
    from matplotlib.patches import Patch
    hs = [Patch(facecolor=c, edgecolor="none", label=lab) for lab, c in handles_colors]
    leg = fig.legend(handles=hs, loc="upper left", bbox_to_anchor=(0.06, y), ncol=ncol,
                     frameon=False, fontsize=9.5, handlelength=1.0, handleheight=1.0,
                     columnspacing=1.6, labelcolor=t["ink2"])
    return leg


def header(fig, t, title, sub):
    fig.text(0.06, 0.975, title, ha="left", va="top", fontsize=14, fontweight="semibold",
             color=t["ink"])
    fig.text(0.06, 0.935, sub, ha="left", va="top", fontsize=9.5, color=t["ink2"])


def footer(fig, t, text):
    fig.text(0.06, 0.018, text, ha="left", va="bottom", fontsize=8.5, color=t["muted"])


def dropped_note():
    parts = []
    for m in MODES:
        for l in ["none"] + LOADS:
            c = DATA[(m, l)]
            if c["n"] and c["n_ok"] < c["n"]:
                parts.append(f"{MODE_LABEL[m]} / {l}: {c['n'] - c['n_ok']} of {c['n']}")
    tot = sum(c["n"] for c in DATA.values()); okk = sum(c["n_ok"] for c in DATA.values())
    return (f"Net-health gate: reps with < {GATE} stock-client attempts are dropped as lab transients "
            f"({tot - okk} of {tot} reps). † marks a cell with dropped reps: " + "; ".join(parts) + ".")


def save(fig, name, mode):
    suffix = "" if mode == "light" else "-dark"
    for ext in ("svg", "png"):
        fig.savefig(os.path.join(OUT, f"{name}{suffix}.{ext}"), dpi=160,
                    facecolor=fig.get_facecolor())
    plt.close(fig)


# ---------------------------------------------------------------- chart 1
def chart_served(mode):
    t = THEMES[mode]
    fig = plt.figure(figsize=(11, 6.4), facecolor=t["surface"])
    ax = fig.add_axes([0.07, 0.19, 0.9, 0.6])
    style_axes(ax, t)
    n = len(MODES); group_w = 0.82; bw = group_w / n
    gap = 0.012                      # surface gap between adjacent bars
    ax.set_xlim(-0.6, len(LOADS) - 0.4); ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_xticks(range(len(LOADS)))
    ax.set_xticklabels([LOAD_LABEL[l] for l in LOADS])
    ax.set_ylabel("Requests served by the target HSDir", color=t["ink2"], fontsize=9.5)
    for gi, l in enumerate(LOADS):
        for si, m in enumerate(MODES):
            c = DATA[(m, l)]
            x = gi - group_w / 2 + bw * (si + 0.5)
            if c["served"] is None:
                continue
            rounded_bar(ax, x, bw - gap, c["served"], t["series"][si], t)
            for k, v in enumerate(c["rep_served"]):
                ax.plot(x + (k - (len(c["rep_served"]) - 1) / 2) * bw * 0.18, v, "o",
                        ms=3.6, mfc=t["ink"], mec=t["surface"], mew=0.9, zorder=5)
            if c["served"] < 0.1:
                ax.text(x, c["served"] + 0.035, f"{c['served']:.0%}", ha="center",
                        va="bottom", fontsize=8.5, color=t["ink"], zorder=6)
            if c["n_ok"] < c["n"]:
                ax.text(x, max(c["rep_served"] + [c["served"]]) + (0.1 if c["served"] < 0.1 else 0.035),
                        "†", ha="center", va="bottom", fontsize=10, color=t["ink2"], zorder=6)
    header(fig, t, "Requests served at the target HSDir, by load profile and configuration",
           "Median of valid reps (bar) and each valid rep (dot). Private loopback chutney "
           "network, x86-64, 60 s per rep, 3 reps per cell.")
    legend(fig, ax, t, [(MODE_LABEL[m], t["series"][i]) for i, m in enumerate(MODES)], ncol=3, y=0.905)
    footer(fig, t, "\n".join(__import__("textwrap").wrap(dropped_note(), 175)))
    save(fig, "served-fraction", mode)


# ---------------------------------------------------------------- chart 2
_allrep = [v for c in DATA.values() for v in c["rep_legit"]]
LO, HI = min(_allrep), max(_allrep)


def chart_legit(mode):
    t = THEMES[mode]
    loads = ["none"] + LOADS
    fig = plt.figure(figsize=(11, 6.0), facecolor=t["surface"])
    ax = fig.add_axes([0.07, 0.2, 0.9, 0.57])
    style_axes(ax, t)
    n = len(MODES); group_w = 0.78; step = group_w / n
    ax.set_xlim(-0.6, len(loads) - 0.4); ax.set_ylim(0.95, 1.005)
    ax.set_yticks([0.95, 0.96, 0.97, 0.98, 0.99, 1.0])
    ax.set_yticklabels(["95%", "96%", "97%", "98%", "99%", "100%"])
    ax.set_xticks(range(len(loads)))
    ax.set_xticklabels([LOAD_LABEL[l] for l in loads])
    ax.set_ylabel("Stock-client fetch success", color=t["ink2"], fontsize=9.5)
    for gi, l in enumerate(loads):
        for si, m in enumerate(MODES):
            c = DATA[(m, l)]
            if c["legit"] is None:
                continue
            x = gi - group_w / 2 + step * (si + 0.5)
            for k, v in enumerate(c["rep_legit"]):
                ax.plot(x, v, "o", ms=4, mfc="none", mec=t["ink2"], mew=0.9, zorder=4)
            ax.plot(x, c["legit"], "o", ms=8.5, mfc=t["series"][si], mec=t["surface"],
                    mew=2, zorder=5)
            if c["legit"] < 0.995:
                ax.text(x + step * 0.42, c["legit"], f"{c['legit']:.1%}", ha="left",
                        va="center", fontsize=8.5, color=t["ink"], zorder=6)
            if c["n_ok"] < c["n"]:
                ax.text(x, c["legit"] + 0.0018, "†", ha="center", va="bottom", fontsize=10,
                        color=t["ink2"], zorder=6)
    header(fig, t, "Stock-client descriptor-fetch success during each cell",
           "Filled dot: median of valid reps; ring: each valid rep. The y-axis starts at 95% "
           f"to show small differences; every valid rep is between {LO:.1%} and {HI:.1%}.")
    from matplotlib.lines import Line2D
    hs = [Line2D([], [], marker="o", ls="none", ms=8, mfc=t["series"][i], mec="none",
                 label=MODE_LABEL[m]) for i, m in enumerate(MODES)]
    fig.legend(handles=hs, loc="upper left", bbox_to_anchor=(0.06, 0.9), ncol=3,
               frameon=False, fontsize=9.5, handletextpad=0.3, columnspacing=1.6,
               labelcolor=t["ink2"])
    footer(fig, t, "\n".join(__import__("textwrap").wrap(dropped_note(), 175)))
    save(fig, "stock-client-success", mode)


# ---------------------------------------------------------------- chart 3
def chart_bytes(mode):
    t = THEMES[mode]
    loads = ["reuse-5", "reuse-22"]
    fig = plt.figure(figsize=(9, 6.2), facecolor=t["surface"])
    ax = fig.add_axes([0.09, 0.22, 0.86, 0.53])
    style_axes(ax, t)
    n = len(MODES); group_w = 0.84; bw = group_w / n; gap = 0.01
    ymax = max(DATA[(m, l)]["bytes_w"] or 0 for m in MODES for l in loads) / 1e6
    ax.set_xlim(-0.55, len(loads) + 0.05); ax.set_ylim(0, ymax * 1.18)
    ax.set_xticks(range(len(loads)))
    ax.set_xticklabels([LOAD_LABEL[l] for l in loads])
    ax.set_ylabel("Bytes written by the target HSDir per 60 s rep (MB)", color=t["ink2"],
                  fontsize=9.5)
    base = DATA[("unpatched", "none")]["bytes_w"] / 1e6
    ax.axhline(base, color=t["muted"], linewidth=1, zorder=2)
    ax.text(len(loads) - 0.43, base + ymax * 0.015, f"No-load baseline\n(unpatched, {base:.1f} MB)",
            ha="left", va="bottom", fontsize=8.5, color=t["ink2"])
    for gi, l in enumerate(loads):
        ref = DATA[("unpatched", l)]["bytes_w"]
        for si, m in enumerate(MODES):
            c = DATA[(m, l)]
            if c["bytes_w"] is None:
                continue
            x = gi - group_w / 2 + bw * (si + 0.5)
            rounded_bar(ax, x, bw - gap, c["bytes_w"] / 1e6, t["series"][si], t)
            for k, v in enumerate(c["rep_bw"]):
                ax.plot(x + (k - (len(c["rep_bw"]) - 1) / 2) * bw * 0.2, v / 1e6, "o",
                        ms=3.6, mfc=t["ink"], mec=t["surface"], mew=0.9, zorder=5)
            if m in ("unpatched", "patched-both"):
                lab = f"{c['bytes_w']/1e6:.1f} MB"
                if m == "patched-both":
                    lab += "\n" + f"{(c['bytes_w'] - ref) / ref:+.0%}".replace("-", "\u2212")
                ax.text(x, max(c["rep_bw"] + [c["bytes_w"]]) / 1e6 + ymax * 0.035, lab,
                        ha="center", va="bottom", fontsize=8.5, color=t["ink"], zorder=6,
                        bbox=dict(boxstyle="round,pad=0.2", fc=t["surface"], ec="none"))
            if c["n_ok"] < c["n"]:
                ax.text(x + bw * 0.32, c["bytes_w"] / 1e6 + ymax * 0.02, "†", ha="center",
                        va="bottom", fontsize=10, color=t["ink2"], zorder=6)
    header(fig, t, "Bytes written by the target HSDir under the circuit-reuse loads",
           "Median of valid reps (bar) and each valid rep (dot). The change shown is relative "
           "to unpatched under the same load.")
    legend(fig, ax, t, [(MODE_LABEL[m], t["series"][i]) for i, m in enumerate(MODES)], ncol=2, y=0.905)
    footer(fig, t, "\n".join(__import__("textwrap").wrap(dropped_note(), 140)))
    save(fig, "target-bytes-reuse", mode)


for mode in ("light", "dark"):
    chart_served(mode)
    chart_legit(mode)
    chart_bytes(mode)
print("ok")
