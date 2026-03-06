#!/usr/bin/env python3
"""
test/example_mode3_chat.py
===========================
モード 3（--chat 対話モード）のローカル実行例。

ユーザーが実験の説明をすると、LLM が解析プランを立て、
全解析を自動実行した後、対話で追加解析を指示できる。

実行コマンド:
    ./launch.sh --fastq-dir ~/input --chat
    ./launch.sh --export-dir ~/seq2pipe_results/.../exported/ --chat

フロー:
    cli.py main()
      ├─ (--fastq-dir 指定時) run_pipeline()   # 先に QIIME2 パイプライン実行
      └─ run_terminal_chat(export_dir, ...)    # chat_agent.py に移行
          └─ InteractiveSession
              ├─ .setup()                      # 実験説明を聞く
              │   └─ ユーザー: "ヒト便検体10サンプル、V3-V4、MiSeq 300bp PE"
              │
              ├─ .plan_analysis_suite()        # LLM が解析プラン作成
              │   └─ LLM: "以下の5つの解析を実行します:
              │         1. α多様性（Shannon, Faith PD）
              │         2. β多様性 PCoA（Bray-Curtis, UniFrac）
              │         3. 属レベル組成
              │         4. 門レベル組成
              │         5. サンプル間類似性ヒートマップ"
              │
              ├─ .run_planned()                # 全プラン自動実行
              │   └─ LLM がプランの各項目をコード生成・実行
              │
              ├─ .chat()                       # 対話ループ
              │   └─ ユーザー: "Prevotella の分布をもっと詳しく"
              │   └─ LLM: コード生成 → 実行 → 図生成
              │   └─ ユーザー: "デンドログラムも作って"
              │   └─ LLM: コード生成 → 実行 → 図生成
              │   └─ ユーザー: "レポート"
              │
              └─ .generate_report()            # TeX/PDF レポート自動生成
                  └─ lualatex/xelatex でコンパイル
"""

# ─── LLM が対話中に生成するコードの典型例 ─────────────────────────────
# chat_agent.py の InteractiveSession.chat() 内で
# ユーザーの自然言語指示に応じて LLM が生成・実行する。

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

EXPORT = Path("~/seq2pipe_results/20260303_120000/exported").expanduser()
FIG_DIR = Path("~/seq2pipe_results/20260303_120000/figures").expanduser()


# ── ユーザー: "Prevotella の分布をもっと詳しく見せて" ──
def chat_prevotella_detail():
    """LLM が対話指示に応じて生成するコード"""
    ft = pd.read_csv(EXPORT / "feature_table" / "feature-table.biom.tsv",
                     sep="\t", skiprows=1, index_col=0)
    ft = ft.select_dtypes(include=[np.number])
    tax = pd.read_csv(EXPORT / "taxonomy" / "taxonomy.tsv", sep="\t", index_col=0)

    common = ft.index.intersection(tax.index)
    genera = tax.loc[common, "Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown")
    ft_g = ft.loc[common].copy()
    ft_g["Genus"] = genera.values
    genus_rel = ft_g.groupby("Genus").sum()
    genus_rel = genus_rel.div(genus_rel.sum(axis=0), axis=1) * 100

    # Prevotella の全種を表示
    prevotella_asvs = tax.loc[
        tax["Taxon"].str.contains("g__Prevotella", na=False), "Taxon"
    ]
    species = prevotella_asvs.str.extract(r"s__([^;]+)")[0].fillna("Unassigned")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 左: サンプル間の Prevotella 存在量
    if "Prevotella" in genus_rel.index:
        vals = genus_rel.loc["Prevotella"]
        axes[0].bar(vals.index, vals.values, color="salmon")
        axes[0].set_title("Prevotella Relative Abundance")
        axes[0].set_ylabel("Relative Abundance (%)")
        axes[0].tick_params(axis="x", rotation=45)

    # 右: Prevotella 内の種レベル構成
    sp_counts = species.value_counts().head(10)
    axes[1].barh(sp_counts.index, sp_counts.values, color="lightcoral")
    axes[1].set_title("Prevotella Species (ASV count)")
    axes[1].set_xlabel("Number of ASVs")

    plt.tight_layout()
    plt.savefig(FIG_DIR / "chat_prevotella_detail.png", dpi=200)
    plt.close()
    print("chat_prevotella_detail.png saved")


# ── ユーザー: "サンプル間の類似性をヒートマップで" ──
def chat_similarity_heatmap():
    """LLM が対話指示に応じて生成するコード"""
    dm_path = EXPORT / "beta" / "braycurtis_distance_matrix" / "distance-matrix.tsv"
    dm = pd.read_csv(dm_path, sep="\t", index_col=0)

    fig, ax = plt.subplots(figsize=(8, 7))
    sns.heatmap(1 - dm, annot=True, fmt=".2f", cmap="YlGnBu",
                xticklabels=dm.columns, yticklabels=dm.index, ax=ax)
    ax.set_title("Sample Similarity (1 - Bray-Curtis)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "chat_similarity_heatmap.png", dpi=200)
    plt.close()
    print("chat_similarity_heatmap.png saved")


# ── ユーザー: "レポート" → TeX/PDF 自動生成 ──
# chat_agent.py の InteractiveSession.generate_report() が呼ばれ、
# 以下の処理が実行される:
#   1. 全生成図を収集
#   2. LLM に各図の解説を生成させる
#   3. LaTeX テンプレートに埋め込み
#   4. lualatex または xelatex でコンパイル
#   5. report.tex + report.pdf を出力
