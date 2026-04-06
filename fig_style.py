#!/usr/bin/env python3
"""
fig_style.py — 出版品質の図スタイル設定
========================================
全ての図で文字が読める・凡例が被らない・ラベルが切れない
を保証するスタイル設定と便利関数。

使い方:
    from fig_style import apply_style, smart_legend, truncate_labels, save_fig

    apply_style()
    fig, ax = plt.subplots(figsize=(9, 6))
    ...
    smart_legend(ax, title="Group")
    save_fig(fig, "my_plot", figure_dir)
"""
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path


def apply_style():
    """出版品質のスタイルを適用"""
    matplotlib.use("Agg")
    plt.rcParams.update({
        # フォントサイズ（全て読める最小サイズ以上）
        "font.size": 11,
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.labelsize": 12,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "legend.title_fontsize": 10,

        # 図のサイズとDPI
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "figure.figsize": (9, 6),

        # 背景
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",

        # スパイン
        "axes.spines.top": False,
        "axes.spines.right": False,

        # グリッド
        "axes.grid": False,

        # 線幅
        "axes.linewidth": 0.8,
        "lines.linewidth": 2.0,

        # カラー
        "axes.prop_cycle": plt.cycler("color", [
            "#4C72B0", "#DD8452", "#55A868", "#C44E52",
            "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]),
    })


def smart_legend(ax, title=None, max_items=10, outside=False):
    """
    凡例を自動配置。データに被らない位置を選ぶ。
    items が多い場合は外に出す。
    """
    handles, labels = ax.get_legend_handles_labels()
    n = len(labels)

    if n == 0:
        return

    # 項目が多い or outside指定 → 図の外
    if n > max_items or outside:
        ax.legend(handles, labels, title=title,
                  bbox_to_anchor=(1.02, 1), loc="upper left",
                  fontsize=max(7, 9 - n // 5), frameon=True,
                  fancybox=True, edgecolor="#ccc")
    else:
        # best 位置 + 半透明背景
        ax.legend(handles, labels, title=title,
                  loc="best", frameon=True, fancybox=True,
                  facecolor="white", framealpha=0.9, edgecolor="#ccc")


def truncate_labels(labels, max_len=12, suffix=".."):
    """長いラベルを切り詰め"""
    result = []
    for l in labels:
        s = str(l)
        if len(s) > max_len:
            result.append(s[:max_len - len(suffix)] + suffix)
        else:
            result.append(s)
    return result


def rotate_xlabels(ax, n_labels=None, max_horizontal=6):
    """
    x軸ラベルを自動回転。
    少なければ水平、多ければ45度、非常に多ければ90度。
    """
    if n_labels is None:
        n_labels = len(ax.get_xticklabels())

    if n_labels <= max_horizontal:
        ax.set_xticklabels(ax.get_xticklabels(), rotation=0, ha="center")
    elif n_labels <= max_horizontal * 3:
        ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha="right")
    else:
        ax.set_xticklabels(ax.get_xticklabels(), rotation=90, ha="center")


def add_stat_annotation(ax, text, position="top-right"):
    """統計検定結果を図に追加（読みやすいボックス付き）"""
    pos_map = {
        "top-right": (0.98, 0.95, "right", "top"),
        "top-left": (0.02, 0.95, "left", "top"),
        "bottom-right": (0.98, 0.05, "right", "bottom"),
    }
    x, y, ha, va = pos_map.get(position, (0.98, 0.95, "right", "top"))

    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va,
            fontsize=10, family="monospace",
            bbox=dict(boxstyle="round,pad=0.5",
                      facecolor="lightyellow",
                      edgecolor="#ccc", alpha=0.9))


def genus_to_label(asv_id, tax_df):
    """ASV ID → 属名に変換（重複番号付き）"""
    if tax_df is None or "Genus" not in tax_df.columns:
        return str(asv_id)[:12]
    genus = tax_df.loc[asv_id, "Genus"] if asv_id in tax_df.index else "Unknown"
    return str(genus)[:20]


def save_fig(fig, name, figure_dir, step_num=None):
    """図を保存して閉じる"""
    if step_num is not None:
        filename = f"ai{step_num:02d}_{name}.png"
    else:
        filename = f"{name}.png"
    path = Path(figure_dir) / filename
    fig.savefig(str(path), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved: {path}")
    return str(path)
