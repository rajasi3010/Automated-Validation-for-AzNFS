#!/usr/bin/env python3
"""Render a polished high-level pipeline flowchart PNG for the solution slide."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

plt.rcParams["font.family"] = "DejaVu Sans"

NAVY  = "#1B1B2F"
AZURE = "#0078D4"
GREY  = "#6B6B7B"
GREEN = "#107C10"
INK   = "#1F2430"
WHITE = "#FFFFFF"

# title, subtitle, band color
stages = [
    ("Azure Marketplace", "source of new\ndistro images",      GREY),
    ("Phase 1 \u2013 Discover", "detect new distros\n& versions",    AZURE),
    ("Phase 2 \u2013 Check",    "AzNFS package\nready on PMC?",       AZURE),
    ("Phase 3 \u2013 Validate", "install, mount &\ntest on a real VM", AZURE),
    ("Result + Email",     "supported /\nunsupported",          GREEN),
]

fig, ax = plt.subplots(figsize=(13.4, 4.4), dpi=200)
ax.set_xlim(0, 134)
ax.set_ylim(0, 44)
ax.axis("off")
fig.patch.set_facecolor(WHITE)

ax.text(3, 40, "How the tool works", fontsize=23, fontweight="bold",
        color=INK, ha="left", va="center")
ax.text(3, 35.2, "Runs automatically on a schedule \u2014 from Marketplace to verdict, no manual effort",
        fontsize=12.5, color=GREY, ha="left", va="center")

box_w, box_h = 22.0, 13.0
gap = 4.2
y = 13.5
x = 3.0
band_h = 4.6

for i, (title, sub, col) in enumerate(stages):
    # soft shadow
    ax.add_patch(FancyBboxPatch((x + 0.5, y - 0.6), box_w, box_h,
                 boxstyle="round,pad=0,rounding_size=1.6",
                 linewidth=0, facecolor="#0000000D", zorder=2))
    # card outline
    ax.add_patch(FancyBboxPatch((x, y), box_w, box_h,
                 boxstyle="round,pad=0,rounding_size=1.6",
                 linewidth=2, edgecolor=col, facecolor=WHITE, zorder=3))
    # top band (rounded top) + square filler to meet body
    ax.add_patch(FancyBboxPatch((x, y + box_h - band_h), box_w, band_h,
                 boxstyle="round,pad=0,rounding_size=1.6",
                 linewidth=0, facecolor=col, zorder=4))
    ax.add_patch(Rectangle((x, y + box_h - band_h), box_w, band_h * 0.5,
                 linewidth=0, facecolor=col, zorder=4))
    # title on band
    ax.text(x + box_w / 2, y + box_h - band_h / 2, title,
            fontsize=12, fontweight="bold", color=WHITE,
            ha="center", va="center", zorder=6)
    # subtitle in body
    ax.text(x + box_w / 2, y + (box_h - band_h) / 2, sub,
            fontsize=11.5, color=INK, ha="center", va="center", zorder=6)

    if i < len(stages) - 1:
        s0 = x + box_w + 0.5
        s1 = x + box_w + gap - 0.5
        ax.add_patch(FancyArrowPatch((s0, y + box_h / 2), (s1, y + box_h / 2),
                     arrowstyle="-|>", mutation_scale=20,
                     linewidth=2.6, color=AZURE, zorder=5))
    x += box_w + gap

# bottom caption bar
ax.add_patch(FancyBboxPatch((3, 3.6), 127.8, 5.0,
             boxstyle="round,pad=0,rounding_size=1.4",
             linewidth=0, facecolor="#F3F6FB", zorder=1))
ax.text(66.9, 6.1,
        "Scheduled & unattended    \u2022    Shared state DB tracks what\u2019s validated"
        "    \u2022    Email only when action is needed",
        fontsize=11.5, color=GREY, ha="center", va="center", zorder=2)

out = "flowchart-tool-overview.png"
fig.savefig(out, bbox_inches="tight", facecolor=WHITE, pad_inches=0.25)
print("saved", out)
