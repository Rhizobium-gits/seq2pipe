#!/usr/bin/env python3
"""
test/example_mode1_specified.py
================================
モード 1（指定解析モード）のローカル実行例。

ユーザーが --prompt で解析内容を指定 → LLM がコードを書いて実行 → 振り返りループ。

実行コマンド:
    ./launch.sh --fastq-dir ~/input --prompt "属レベルの積み上げ棒グラフ"

または既存エクスポートデータから:
    ./launch.sh --export-dir ~/seq2pipe_results/.../exported/ \
        --prompt "Shannon 多様性のサンプル別プロット"

フロー:
    cli.py main()
      ├─ _detect_dada2_params(fastq_dir)    # FASTQ からパラメータ自動推定
      ├─ _detect_seq_type()                  # 16S / ショットガン判定
      ├─ run_pipeline(config)                # STEP 1: QIIME2 パイプライン実行
      │   └─ qiime2_agent.run_agent_loop()   #   LLM が QIIME2 コマンドを生成・実行
      ├─ run_comprehensive_analysis()        # STEP 1.5: 29 図の決定論的生成
      ├─ run_coding_agent(                   # STEP 2: LLM コード生成
      │     user_prompt="属レベルの積み上げ棒グラフ",
      │     ...)
      │   └─ LLM ループ:
      │       1. list_files → ファイル一覧取得
      │       2. read_file → データ形式確認
      │       3. write_file → Python スクリプト生成
      │       4. run_python → 実行
      │       5. エラー → write_file で修正 → 再実行
      └─ _run_refinement_session()           # 振り返り・修正ループ
          └─ ユーザー: "色を変えて" → LLM が修正コード生成
"""

# ─── LLM が実際に生成するコードの典型例 ───────────────────────────────
# 以下は「属レベルの積み上げ棒グラフ」と指示した場合に
# code_agent.py の LLM ループが生成・実行する Python コードの再現例。
# LLM は毎回 read_file でデータ形式を確認してからコードを書くため、
# 列名やファイルパスは実データに基づいて正確に生成される。

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

# ── LLM が list_files → read_file で確認した実際のパス ──
EXPORT_DIR = Path("~/seq2pipe_results/20260303_120000/exported").expanduser()
FIGURE_DIR = Path("~/seq2pipe_results/20260303_120000/figures").expanduser()

# ── データ読み込み（LLM が read_file で列名を確認済み）──
ft_path = EXPORT_DIR / "feature_table" / "feature-table.biom.tsv"
tax_path = EXPORT_DIR / "taxonomy" / "taxonomy.tsv"

# Feature table: 行=ASV, 列=サンプル
ft = pd.read_csv(ft_path, sep="\t", skiprows=1, index_col=0)
ft = ft.select_dtypes(include=[np.number])

# Taxonomy: Feature ID → Taxon 文字列
tax = pd.read_csv(tax_path, sep="\t", index_col=0)

# ── 属レベルの抽出 ──
common = ft.index.intersection(tax.index)
ft_c = ft.loc[common]
genera = tax.loc[common, "Taxon"].str.extract(r"g__([^;]+)")[0].fillna("Unknown").str.strip()
genera = genera.replace("", "Unknown")

# ── 属ごとに集約（相対存在量）──
ft_c["Genus"] = genera.values
genus_table = ft_c.groupby("Genus").sum()
genus_rel = genus_table.div(genus_table.sum(axis=0), axis=1) * 100

# ── Top 15 + Other ──
top15 = genus_rel.mean(axis=1).sort_values(ascending=False).head(15).index
other = genus_rel.loc[~genus_rel.index.isin(top15)].sum(axis=0)
plot_df = genus_rel.loc[top15].copy()
plot_df.loc["Other"] = other

# ── 積み上げ棒グラフ ──
fig, ax = plt.subplots(figsize=(12, 6))
plot_df.T.plot(kind="bar", stacked=True, ax=ax, colormap="tab20")
ax.set_ylabel("Relative Abundance (%)")
ax.set_xlabel("Sample")
ax.set_title("Genus-level Composition (Top 15)")
ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
plt.tight_layout()
plt.savefig(FIGURE_DIR / "genus_composition.png", dpi=200, bbox_inches="tight")
plt.close()
print("genus_composition.png saved")


# ─── 振り返りモードでの修正例 ───────────────────────────────────────
# ユーザー: "色をパステルカラーにして凡例を下に"
# → LLM が以下のような修正コードを生成:

# fig, ax = plt.subplots(figsize=(12, 7))
# plot_df.T.plot(kind="bar", stacked=True, ax=ax, colormap="Pastel1")
# ax.set_ylabel("Relative Abundance (%)")
# ax.set_xlabel("Sample")
# ax.set_title("Genus-level Composition (Top 15)")
# ax.legend(bbox_to_anchor=(0.5, -0.15), loc="upper center",
#           ncol=4, fontsize=8)
# plt.tight_layout()
# plt.savefig(FIGURE_DIR / "genus_composition.png", dpi=200, bbox_inches="tight")
# plt.close()
