#!/usr/bin/env python3
"""
tests/test_analysis.py
======================
seq2pipe の Python 解析コード（_analysis_code）を
モック QIIME2 エクスポートデータで検証するテスト。

実行方法:
    ~/miniforge3/envs/qiime2/bin/python3 tests/test_analysis.py

要件:
    - numpy, pandas, matplotlib, seaborn, scipy (QIIME2 conda env)
"""

import sys
import os
import tempfile
import shutil
import textwrap
from pathlib import Path

# ─── ルートを sys.path に追加して qiime2_agent をインポート ───────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# モックデータ作成ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

N_ASV = 120
N_SAMPLE = 10
SAMPLES = [f"SampleID.{i}" for i in range(1, N_SAMPLE + 1)]
ASV_IDS = [f"ASV{i:04d}" for i in range(1, N_ASV + 1)]

TAXA = [
    "d__Bacteria; p__Firmicutes; c__Bacilli; o__Lactobacillales; f__Lactobacillaceae; g__Lactobacillus; s__acidophilus",
    "d__Bacteria; p__Firmicutes; c__Bacilli; o__Lactobacillales; f__Streptococcaceae; g__Streptococcus; s__thermophilus",
    "d__Bacteria; p__Bacteroidota; c__Bacteroidia; o__Bacteroidales; f__Bacteroidaceae; g__Bacteroides; s__fragilis",
    "d__Bacteria; p__Proteobacteria; c__Gammaproteobacteria; o__Enterobacterales; f__Enterobacteriaceae; g__Escherichia-Shigella; s__coli",
    "d__Bacteria; p__Actinobacteriota; c__Actinobacteria; o__Bifidobacteriales; f__Bifidobacteriaceae; g__Bifidobacterium; s__longum",
    "d__Bacteria; p__Firmicutes; c__Clostridia; o__Clostridiales; f__Lachnospiraceae; g__Roseburia; s__intestinalis",
    "d__Bacteria; p__Bacteroidota; c__Bacteroidia; o__Bacteroidales; f__Prevotellaceae; g__Prevotella; s__copri",
    "d__Bacteria; p__Firmicutes; c__Clostridia; o__Clostridiales; f__Ruminococcaceae; g__Ruminococcus; s__gnavus",
    "d__Bacteria; p__Verrucomicrobiota; c__Verrucomicrobiae; o__Verrucomicrobiales; f__Akkermansiaceae; g__Akkermansia; s__muciniphila",
]


def create_mock_export_dir(base_dir: Path) -> Path:
    """モック QIIME2 エクスポートディレクトリを作成して返す。"""
    rng = np.random.default_rng(seed=42)
    export_dir = base_dir / "exported"
    export_dir.mkdir(parents=True)

    # ── 1. feature-table.tsv (BIOM 形式: 1行目ヘッダーをスキップ) ───────────
    counts = rng.integers(0, 500, size=(N_ASV, N_SAMPLE)).astype(float)
    counts[rng.random(size=(N_ASV, N_SAMPLE)) < 0.7] = 0  # スパース化

    table_tsv = export_dir / "feature-table.tsv"
    with open(table_tsv, "w") as f:
        f.write("# Constructed from biom file\n")
        f.write("# OTU ID\t" + "\t".join(SAMPLES) + "\n")
        for asv_id, row in zip(ASV_IDS, counts):
            f.write(asv_id + "\t" + "\t".join(str(v) for v in row) + "\n")

    # ── 2. taxonomy/taxonomy.tsv ──────────────────────────────────────────────
    tax_dir = export_dir / "taxonomy"
    tax_dir.mkdir()
    taxon_list = [TAXA[i % len(TAXA)] for i in range(N_ASV)]
    tax_df = pd.DataFrame(
        {"Taxon": taxon_list, "Confidence": rng.uniform(0.7, 1.0, N_ASV)},
        index=pd.Index(ASV_IDS, name="Feature ID"),
    )
    tax_df.to_csv(tax_dir / "taxonomy.tsv", sep="\t")

    # ── 3. denoising_stats/stats.tsv ─────────────────────────────────────────
    stats_dir = export_dir / "denoising_stats"
    stats_dir.mkdir()
    stats_data = {
        "input":          rng.integers(50000, 100000, N_SAMPLE),
        "filtered":       rng.integers(40000, 90000,  N_SAMPLE),
        "denoised":       rng.integers(35000, 85000,  N_SAMPLE),
        "merged":         rng.integers(30000, 80000,  N_SAMPLE),
        "non-chimeric":   rng.integers(25000, 75000,  N_SAMPLE),
    }
    stats_df = pd.DataFrame(stats_data, index=pd.Index(SAMPLES, name="sample-id"))
    stats_df.to_csv(stats_dir / "stats.tsv", sep="\t")

    # ── 4. alpha/ ─────────────────────────────────────────────────────────────
    alpha_base = export_dir / "alpha"
    for metric, values in {
        "shannon_vector":           rng.uniform(3, 5, N_SAMPLE),
        "faith_pd_vector":          rng.uniform(10, 30, N_SAMPLE),
        "evenness_vector":          rng.uniform(0.5, 1.0, N_SAMPLE),
        "observed_features_vector": rng.integers(50, 200, N_SAMPLE).astype(float),
    }.items():
        d = alpha_base / metric
        d.mkdir(parents=True)
        pd.DataFrame(
            {metric: values},
            index=pd.Index(SAMPLES, name="sample-id"),
        ).to_csv(d / "alpha-diversity.tsv", sep="\t")

    # ── 5. beta/ ──────────────────────────────────────────────────────────────
    beta_base = export_dir / "beta"
    for matrix_name in ["bray_curtis_distance_matrix", "unweighted_unifrac_distance_matrix"]:
        d = beta_base / matrix_name
        d.mkdir(parents=True)
        # 対称距離行列
        raw = rng.uniform(0, 1, (N_SAMPLE, N_SAMPLE))
        sym = (raw + raw.T) / 2
        np.fill_diagonal(sym, 0)
        dist_df = pd.DataFrame(sym, index=SAMPLES, columns=SAMPLES)
        dist_df.to_csv(d / "distance-matrix.tsv", sep="\t")

    return export_dir


# ─────────────────────────────────────────────────────────────────────────────
# 解析コードを文字列として構築（qiime2_agent の _analysis_code と同等）
# ─────────────────────────────────────────────────────────────────────────────

def build_analysis_code(out_dir: str, export_dir: str, fig_dir: str) -> str:
    """qiime2_agent.py の _analysis_code f-string と同等のコードを返す。"""
    return textwrap.dedent(f"""\
        import io, os, sys, glob, zipfile
        from pathlib import Path
        import numpy as np
        import pandas as pd
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import seaborn as sns
        from scipy import stats

        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')

        session_dir = Path({repr(out_dir)})
        export_dir  = Path({repr(export_dir)})
        fig_dir     = Path({repr(fig_dir)})
        fig_dir.mkdir(parents=True, exist_ok=True)

        dpi       = 150
        font_size = 11
        plt.rcParams.update({{
            'figure.dpi'       : dpi,
            'font.size'        : font_size,
            'axes.spines.top'  : False,
            'axes.spines.right': False,
            'savefig.dpi'      : dpi,
        }})

        import matplotlib.font_manager as _fm
        _jp_candidates = ['Hiragino Sans', 'Hiragino Maru Gothic Pro', 'AppleGothic', 'IPAexGothic']
        for _fc in _jp_candidates:
            if any(f.name == _fc for f in _fm.fontManager.ttflist):
                plt.rcParams['font.family'] = _fc
                break

        warnings_list = []

        # 1. Feature table
        asv_table = None
        table_tsv = export_dir / "feature-table.tsv"
        if table_tsv.exists():
            asv_table = pd.read_csv(table_tsv, sep='\\t', skiprows=1, index_col=0)
            asv_table = asv_table.astype(float)
            print(f"✅ ASV table: {{asv_table.shape[0]}} ASV x {{asv_table.shape[1]}} サンプル")
            asv_table.to_csv(fig_dir / "asv_counts.csv")
        else:
            warnings_list.append("⚠️ feature-table.tsv が見つかりません")

        # 2. Taxonomy
        taxonomy = None
        tax_tsv = export_dir / "taxonomy" / "taxonomy.tsv"
        if tax_tsv.exists():
            taxonomy = pd.read_csv(tax_tsv, sep='\\t', index_col=0)
            print(f"✅ Taxonomy: {{len(taxonomy)}} ASV の分類情報")

        # 3. 属レベル集計・相対存在量・積み上げ棒グラフ
        genus_rel = None
        if asv_table is not None and taxonomy is not None:
            def _parse_level(taxon_str, prefix):
                if not isinstance(taxon_str, str):
                    return "Unclassified"
                for part in taxon_str.split(';'):
                    part = part.strip()
                    if part.startswith(prefix + '__'):
                        val = part[len(prefix) + 2:].strip()
                        return val if val else f"Unclassified {{prefix}}"
                return "Unclassified"

            taxonomy['Phylum'] = taxonomy['Taxon'].apply(lambda x: _parse_level(x, 'p'))
            taxonomy['Family'] = taxonomy['Taxon'].apply(lambda x: _parse_level(x, 'f'))
            taxonomy['Genus']  = taxonomy['Taxon'].apply(lambda x: _parse_level(x, 'g'))
            taxonomy.to_csv(fig_dir / "taxonomy_parsed.csv")

            merged = asv_table.join(taxonomy[['Phylum', 'Family', 'Genus']])
            sample_cols = asv_table.columns.tolist()
            genus_counts = merged.groupby('Genus')[sample_cols].sum()
            genus_counts.to_csv(fig_dir / "genus_counts.csv")

            genus_rel = genus_counts.div(genus_counts.sum(axis=0), axis=1) * 100
            genus_rel.to_csv(fig_dir / "genus_relative_abundance.csv")
            print(f"✅ 属レベル集計: {{genus_counts.shape[0]}} 属")

            top_n = 10
            top_genera = genus_rel.mean(axis=1).sort_values(ascending=False).head(top_n).index.tolist()
            plot_df = genus_rel.loc[top_genera].copy()
            plot_df.loc['Other'] = genus_rel.drop(index=top_genera).sum(axis=0)
            plot_df = plot_df.T

            colors = list(plt.cm.tab20.colors[:top_n]) + [(0.75, 0.75, 0.75)]
            fig, ax = plt.subplots(figsize=(max(10, len(plot_df) * 0.9), 6))
            plot_df.plot(kind='bar', stacked=True, ax=ax, color=colors,
                         width=0.8, edgecolor='white', linewidth=0.3)
            ax.set_xlabel('Sample ID', fontsize=font_size)
            ax.set_ylabel('Relative abundance (%)', fontsize=font_size)
            ax.set_title('Genus-level composition (Top 10)', fontsize=font_size + 2, fontweight='bold')
            ax.tick_params(axis='x', rotation=45)
            ax.legend(title='Genus', bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=font_size - 2)
            ax.set_ylim(0, 100)
            plt.tight_layout()
            plt.savefig(fig_dir / 'genus_composition_stacked.pdf', bbox_inches='tight')
            plt.close()
            print('✅ 属レベル積み上げ棒グラフ: genus_composition_stacked.pdf')

            phylum_counts = merged.groupby('Phylum')[sample_cols].sum()
            phylum_rel    = phylum_counts.div(phylum_counts.sum(axis=0), axis=1) * 100
            phylum_rel.to_csv(fig_dir / "phylum_relative_abundance.csv")
            print('✅ 門レベル相対存在量: phylum_relative_abundance.csv')

        # 4. DADA2 統計
        stats_files = list((export_dir / "denoising_stats").glob("*.tsv")) \\
                      if (export_dir / "denoising_stats").exists() else []
        if stats_files:
            try:
                stats_df = pd.read_csv(stats_files[0], sep='\\t', index_col=0)
                req_cols = ['input', 'non-chimeric']
                if all(c in stats_df.columns for c in req_cols):
                    stats_df.to_csv(fig_dir / "dada2_stats.csv")
                    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
                    x = range(len(stats_df))
                    axes[0].bar(x, stats_df['input'],        label='Input',       alpha=0.8, color='#4C72B0')
                    axes[0].bar(x, stats_df.get('filtered', stats_df['non-chimeric']),
                                                              label='Filtered',    alpha=0.8, color='#DD8452')
                    axes[0].bar(x, stats_df['non-chimeric'], label='Non-chimeric', alpha=0.8, color='#55A868')
                    axes[0].set_xticks(list(x))
                    axes[0].set_xticklabels(stats_df.index, rotation=45, ha='right')
                    axes[0].set_xlabel('Sample ID')
                    axes[0].set_ylabel('Read count')
                    axes[0].set_title('DADA2 read counts', fontweight='bold')
                    axes[0].legend()
                    retention = stats_df['non-chimeric'] / stats_df['input'] * 100
                    axes[1].bar(x, retention, color='#55A868', alpha=0.85)
                    axes[1].set_xticks(list(x))
                    axes[1].set_xticklabels(stats_df.index, rotation=45, ha='right')
                    axes[1].set_xlabel('Sample ID')
                    axes[1].set_ylabel('Retention (%)')
                    axes[1].set_title('DADA2 retention rate', fontweight='bold')
                    axes[1].set_ylim(0, 100)
                    axes[1].axhline(70, ls='--', color='tomato', lw=1, label='70% baseline')
                    axes[1].legend()
                    plt.tight_layout()
                    plt.savefig(fig_dir / 'dada2_stats.pdf', bbox_inches='tight')
                    plt.close()
                    print('✅ DADA2統計グラフ: dada2_stats.pdf')
            except Exception as e:
                warnings_list.append(f'DADA2統計グラフ生成失敗: {{e}}')

        # 5. α多様性
        alpha_dir = export_dir / "alpha"
        alpha_data = {{}}
        metric_labels = {{
            'shannon_vector'           : "Shannon diversity index",
            'faith_pd_vector'          : "Faith's phylogenetic diversity",
            'evenness_vector'          : 'Pielou evenness',
            'observed_features_vector' : 'Observed features (ASVs)',
        }}
        if alpha_dir.exists():
            for metric_dir in sorted(alpha_dir.iterdir()):
                tsv_files = list(metric_dir.glob("*.tsv"))
                if tsv_files:
                    try:
                        df = pd.read_csv(tsv_files[0], sep='\\t', index_col=0)
                        if len(df.columns) >= 1:
                            alpha_data[metric_dir.name] = df.iloc[:, 0]
                            print(f"✅ α多様性 {{metric_dir.name}}: {{len(df)}} サンプル")
                    except Exception as e:
                        warnings_list.append(f"α多様性読み込み失敗 ({{metric_dir.name}}): {{e}}")

        if alpha_data:
            alpha_df = pd.DataFrame(alpha_data)
            alpha_df.to_csv(fig_dir / "alpha_diversity.csv")
            n = len(alpha_df.columns)
            fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), squeeze=False)
            for i, col in enumerate(alpha_df.columns):
                ax = axes[0][i]
                vals = alpha_df[col].dropna()
                ax.bar(range(len(vals)), vals.values, color='steelblue', alpha=0.85, edgecolor='white')
                ax.set_xticks(range(len(vals)))
                ax.set_xticklabels(vals.index, rotation=45, ha='right', fontsize=font_size - 2)
                ax.set_ylabel(metric_labels.get(col, col), fontsize=font_size)
                ax.set_title(metric_labels.get(col, col), fontsize=font_size + 1, fontweight='bold')
            plt.tight_layout()
            plt.savefig(fig_dir / 'alpha_diversity.pdf', bbox_inches='tight')
            plt.close()
            print('✅ α多様性グラフ: alpha_diversity.pdf')

        # 6. β多様性 PCoA
        beta_dir = export_dir / "beta"
        if beta_dir.exists():
            for matrix_dir in sorted(beta_dir.iterdir()):
                tsv_files = list(matrix_dir.glob("*.tsv"))
                if not tsv_files:
                    continue
                try:
                    dist_df = pd.read_csv(tsv_files[0], sep='\\t', index_col=0)
                    n = len(dist_df)
                    D = dist_df.values.astype(float)
                    J = np.eye(n) - np.ones((n, n)) / n
                    B = -0.5 * J @ (D ** 2) @ J
                    eigvals, eigvecs = np.linalg.eigh(B)
                    idx = np.argsort(eigvals)[::-1]
                    eigvals, eigvecs = eigvals[idx], eigvecs[:, idx]
                    pos = eigvals > 1e-10
                    coords = eigvecs[:, pos] * np.sqrt(eigvals[pos])
                    var_exp = eigvals[pos] / eigvals[pos].sum() * 100

                    n_pcs = min(3, coords.shape[1])
                    pcoa_df = pd.DataFrame(
                        coords[:, :n_pcs],
                        index=dist_df.index,
                        columns=[f'PC{{i+1}}' for i in range(n_pcs)]
                    )
                    pcoa_df.to_csv(fig_dir / f"pcoa_{{matrix_dir.name}}.csv")

                    fig, ax = plt.subplots(figsize=(7, 6))
                    ax.scatter(pcoa_df['PC1'], pcoa_df['PC2'],
                               s=120, alpha=0.85, color='steelblue',
                               edgecolors='white', linewidths=0.6)
                    for sid, row in pcoa_df.iterrows():
                        ax.annotate(str(sid), (row['PC1'], row['PC2']),
                                    textcoords='offset points', xytext=(6, 4),
                                    fontsize=font_size - 3)
                    ax.set_xlabel(f"PC1 ({{var_exp[0]:.1f}}%)", fontsize=font_size)
                    ax.set_ylabel(f"PC2 ({{var_exp[1]:.1f}}%)" if len(var_exp) > 1 else "PC2",
                                  fontsize=font_size)
                    title = matrix_dir.name.replace('_distance_matrix', '').replace('_', ' ').title()
                    ax.set_title(f'PCoA – {{title}}', fontsize=font_size + 1, fontweight='bold')
                    plt.tight_layout()
                    plt.savefig(fig_dir / f'pcoa_{{matrix_dir.name}}.pdf', bbox_inches='tight')
                    plt.close()
                    print(f'✅ PCoA: pcoa_{{matrix_dir.name}}.pdf')
                except Exception as e:
                    warnings_list.append(f'PCoA失敗 ({{matrix_dir.name}}): {{e}}')

        # 完了
        print('\\n' + '='*60)
        print('✅ Python 解析・可視化 完了')
        print(f'📁 出力先: {{fig_dir}}')
        for f in sorted(fig_dir.glob('*.pdf')):
            print(f'  📊 {{f.name}}')
        for f in sorted(fig_dir.glob('*.csv')):
            print(f'  📋 {{f.name}}')
        if warnings_list:
            print('\\n⚠️ 警告:')
            for w in warnings_list:
                print(f'  {{w}}')
    """)


# ─────────────────────────────────────────────────────────────────────────────
# テスト実行
# ─────────────────────────────────────────────────────────────────────────────

def run_test():
    """モックデータで解析コードを実行し、出力ファイルの存在を検証する。"""
    tmpdir = tempfile.mkdtemp(prefix="seq2pipe_test_")
    try:
        base      = Path(tmpdir)
        out_dir   = base
        export_dir = create_mock_export_dir(base)
        fig_dir   = base / "figures"
        fig_dir.mkdir()

        # テストパスをファイルに書き出す（デバッグ用）
        with open("/tmp/seq2pipe_test_paths.txt", "w") as f:
            f.write(f"{tmpdir}\n{export_dir}\n{fig_dir}\n")

        print("=" * 60)
        print("seq2pipe 解析コード テスト")
        print(f"一時ディレクトリ: {tmpdir}")
        print("=" * 60)

        code = build_analysis_code(str(out_dir), str(export_dir), str(fig_dir))
        exec(compile(code, "<test_analysis>", "exec"), {"__name__": "__test__"})

        # ── 出力ファイル検証 ──────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("【出力ファイル検証】")
        expected_pdfs = [
            "genus_composition_stacked.pdf",
            "dada2_stats.pdf",
            "alpha_diversity.pdf",
            "pcoa_bray_curtis_distance_matrix.pdf",
            "pcoa_unweighted_unifrac_distance_matrix.pdf",
        ]
        expected_csvs = [
            "asv_counts.csv",
            "taxonomy_parsed.csv",
            "genus_counts.csv",
            "genus_relative_abundance.csv",
            "phylum_relative_abundance.csv",
            "dada2_stats.csv",
            "alpha_diversity.csv",
            "pcoa_bray_curtis_distance_matrix.csv",
            "pcoa_unweighted_unifrac_distance_matrix.csv",
        ]

        all_ok = True
        for fname in expected_pdfs + expected_csvs:
            path = fig_dir / fname
            ok = path.exists() and path.stat().st_size > 0
            status = "✅" if ok else "❌"
            print(f"  {status} {fname}")
            if not ok:
                all_ok = False

        print()
        if all_ok:
            print("✅ 全テスト PASSED")
            return 0
        else:
            print("❌ 一部のファイルが生成されていません")
            return 1

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_test())
