#!/usr/bin/env python3
"""
analysis_templates.py
=====================
テンプレートベースの解析コード生成。
LLM に頼らず、確実に動作する Python コードテンプレートを提供する。
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# テンプレートマッチング
# ─────────────────────────────────────────────────────────────────────────────

# 順序重要: 具体的なパターンを先に、汎用的なものを後に
_TEMPLATE_KEYWORDS = [
    ("alpha_group_comparison", [
        r"alpha.*(comparison|kruskal|test|統計|compar)",
        r"(group\s+comparison|compare\s+.*alpha|compar.*diversity)",
        r"多様性.*(比較|検定|群)", r"群.*多様性",
        r"kruskal.*wallis", r"mann.*whitney",
    ]),
    ("phylum_barplot", [
        r"phylum.*(bar|abundance|level)", r"門.*(棒|バー)",
        r"bar.*phylum",
    ]),
    ("genus_barplot", [
        r"stacked\s*bar", r"genus.*(bar|abundance)", r"bar.*genus",
        r"relative\s*abundance.*bar", r"属.*(棒|バー)", r"棒.*属",
        r"組成.*bar", r"bar.*組成", r"stacked.*abundance",
    ]),
    ("alpha_boxplot", [
        r"alpha.*box", r"shannon.*box", r"diversity.*box",
        r"alpha.*比較", r"多様性.*box", r"shannon",
        r"alpha.*diversity", r"observed.*features.*box",
    ]),
    ("beta_pcoa", [
        r"pcoa", r"beta.*scatter", r"bray.*curtis.*plot",
        r"beta.*diversity.*plot", r"ordination",
        r"ベータ.*多様性", r"主座標",
    ]),
    ("denoising_stats", [
        r"denoising", r"denois", r"filtering.*stats",
        r"read.*count", r"ノイズ除去", r"前処理.*統計",
    ]),
    ("heatmap", [
        r"heatmap", r"heat\s*map", r"ヒートマップ",
        r"top.*taxa.*heat", r"abundance.*heat",
    ]),
    ("rarefaction", [
        r"rarefaction", r"希薄化", r"レアファクション",
        r"species.*richness.*depth",
    ]),
]


def match_template(description: str) -> Optional[str]:
    """解析の説明文からテンプレート名を返す。マッチしなければ None。"""
    desc_lower = description.lower()
    for name, patterns in _TEMPLATE_KEYWORDS:
        for pat in patterns:
            if re.search(pat, desc_lower, re.IGNORECASE):
                return name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# コード生成
# ─────────────────────────────────────────────────────────────────────────────

def generate_code(
    template_name: str,
    figure_dir: str,
    export_files: dict,
    metadata_path: str = "",
    group_col: str = "",
) -> Optional[str]:
    """
    テンプレート名に対応する実行可能な Python コードを返す。
    必要なファイルがなければ None。
    """
    gen = _GENERATORS.get(template_name)
    if gen is None:
        return None
    return gen(figure_dir, export_files, metadata_path, group_col)


def _get_path(export_files: dict, category: str, index: int = 0) -> Optional[str]:
    paths = export_files.get(category, [])
    return paths[index] if index < len(paths) else None


def _detect_group_col(metadata_path: str) -> str:
    """メタデータから最適なグループ列を自動検出する。"""
    if not metadata_path or not Path(metadata_path).exists():
        return ""
    try:
        with open(metadata_path) as f:
            header = f.readline().strip().split("\t")
        # sample-id 以外で、典型的なグループ列を優先
        priority = [
            "gravity", "treatment", "group", "condition", "genotype",
            "diet", "timepoint", "donor", "sample-type", "site",
        ]
        cols = [c for c in header if c.lower() != "sample-id" and c.lower() != "#sampleid"]
        for prio in priority:
            for c in cols:
                if prio in c.lower():
                    return c
        # 最初の非ID列
        return cols[0] if cols else ""
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# 各テンプレート
# ─────────────────────────────────────────────────────────────────────────────

def _gen_genus_barplot(figure_dir, export_files, metadata_path, group_col):
    ft_path = _get_path(export_files, "feature_table")
    tax_path = _get_path(export_files, "taxonomy")
    if not ft_path or not tax_path:
        return None
    group_col = group_col or _detect_group_col(metadata_path)
    meta_block = ""
    if metadata_path and group_col:
        meta_block = f"""
# メタデータでグループ化
meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')
meta.columns = [c.strip() for c in meta.columns]
id_col = meta.columns[0]
meta = meta.set_index(id_col)
if '{group_col}' in meta.columns:
    # サンプルをグループ順にソート
    common = rel_genus.columns.intersection(meta.index)
    rel_genus = rel_genus[sorted(common, key=lambda s: str(meta.loc[s, '{group_col}']) if s in meta.index else '')]
"""
    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

# データ読み込み
ft = pd.read_csv(r'{ft_path}', sep='\\t', skiprows=1, index_col=0)
ft.index.name = 'Feature ID'
tax = pd.read_csv(r'{tax_path}', sep='\\t', index_col=0)

# 属レベルの抽出
tax['genus'] = tax['Taxon'].str.extract(r'g__([^;]+)')[0].fillna('Unknown').str.strip()
tax.loc[tax['genus'] == '', 'genus'] = 'Unknown'

# 属ごとに集計
ft_tax = ft.copy()
ft_tax['genus'] = tax.reindex(ft_tax.index)['genus'].fillna('Unknown')
genus_table = ft_tax.groupby('genus').sum()

# 相対存在量
rel_genus = genus_table.div(genus_table.sum(axis=0), axis=1)

# Top 15 属
top15 = rel_genus.sum(axis=1).nlargest(15).index.tolist()
other = rel_genus.loc[~rel_genus.index.isin(top15)].sum(axis=0)
plot_df = rel_genus.loc[rel_genus.index.isin(top15)].copy()
plot_df.loc['Other'] = other
{meta_block}
# プロット
fig, ax = plt.subplots(1, 1, figsize=(max(14, len(plot_df.columns) * 0.3), 8))
colors = plt.cm.tab20(range(len(plot_df)))
plot_df.T.plot(kind='bar', stacked=True, ax=ax, color=colors, width=0.9, edgecolor='none')
ax.set_ylabel('Relative Abundance', fontsize=12)
ax.set_xlabel('Sample', fontsize=12)
ax.set_title('Genus-level Relative Abundance (Top 15)', fontsize=14)
ax.legend(title='Genus', bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8)
ax.set_ylim(0, 1)
plt.xticks(rotation=90, fontsize=7)
plt.tight_layout()
plt.savefig(os.path.join(FIGURE_DIR, 'genus_barplot.png'), dpi=DPI, bbox_inches='tight')
plt.close()
print('Saved: genus_barplot.png')
"""


def _gen_alpha_boxplot(figure_dir, export_files, metadata_path, group_col):
    alpha_paths = export_files.get("alpha", [])
    if not alpha_paths:
        return None
    group_col = group_col or _detect_group_col(metadata_path)

    meta_load = ""
    group_logic = ""
    if metadata_path and group_col:
        meta_load = f"""
meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')
meta.columns = [c.strip() for c in meta.columns]
id_col = meta.columns[0]
meta = meta.set_index(id_col)
"""
        group_logic = f"""
    if meta is not None and '{group_col}' in meta.columns:
        common = alpha_df.index.intersection(meta.index)
        merged = alpha_df.loc[common].copy()
        merged['{group_col}'] = meta.loc[common, '{group_col}']
        import seaborn as sns
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.boxplot(data=merged, x='{group_col}', y=val_col, ax=ax, palette='Set2')
        sns.stripplot(data=merged, x='{group_col}', y=val_col, ax=ax, color='black', alpha=0.5, size=3)
        ax.set_title(f'{{metric_name}} by {group_col}', fontsize=14)
        ax.set_ylabel(metric_name, fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        fname = f'alpha_{{metric_name}}_by_{group_col}.png'
        plt.savefig(os.path.join(FIGURE_DIR, fname), dpi=DPI, bbox_inches='tight')
        plt.close()
        print(f'Saved: {{fname}}')
"""

    alpha_paths_str = repr(alpha_paths)

    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

meta = None
{meta_load}

alpha_files = {alpha_paths_str}

for apath in alpha_files:
    try:
        alpha_df = pd.read_csv(apath, sep='\\t', index_col=0)
        val_col = [c for c in alpha_df.columns if c != 'sample-id'][0] if len(alpha_df.columns) > 0 else alpha_df.columns[0]
        metric_name = os.path.basename(os.path.dirname(apath))
        if not metric_name or metric_name == 'alpha':
            metric_name = val_col

        # 全サンプル boxplot
        fig, ax = plt.subplots(figsize=(10, 6))
        alpha_df[val_col].plot(kind='box', ax=ax)
        ax.set_title(f'Alpha Diversity: {{metric_name}}', fontsize=14)
        ax.set_ylabel(metric_name, fontsize=12)
        plt.tight_layout()
        fname = f'alpha_{{metric_name}}_boxplot.png'
        plt.savefig(os.path.join(FIGURE_DIR, fname), dpi=DPI, bbox_inches='tight')
        plt.close()
        print(f'Saved: {{fname}}')

{group_logic}
    except Exception as e:
        print(f'Error processing {{apath}}: {{e}}')
"""


def _gen_beta_pcoa(figure_dir, export_files, metadata_path, group_col):
    beta_paths = export_files.get("beta", [])
    if not beta_paths:
        return None
    group_col = group_col or _detect_group_col(metadata_path)

    # Bray-Curtis を優先
    bc_path = None
    for p in beta_paths:
        if "bray" in p.lower():
            bc_path = p
            break
    if bc_path is None:
        bc_path = beta_paths[0]

    color_block = ""
    if metadata_path and group_col:
        color_block = f"""
try:
    meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')
    meta.columns = [c.strip() for c in meta.columns]
    id_col = meta.columns[0]
    meta = meta.set_index(id_col)
    if '{group_col}' in meta.columns:
        groups = meta.reindex(dm.index)['{group_col}'].fillna('Unknown')
        unique_groups = groups.unique()
        cmap = plt.cm.tab10
        colors = {{g: cmap(i / max(len(unique_groups)-1, 1)) for i, g in enumerate(unique_groups)}}
        for g in unique_groups:
            mask = groups == g
            ax.scatter(coords[mask, 0], coords[mask, 1], c=[colors[g]], label=str(g), s=50, alpha=0.8, edgecolors='white', linewidth=0.5)
        ax.legend(title='{group_col}', bbox_to_anchor=(1.02, 1), loc='upper left')
        has_groups = True
except Exception:
    pass
"""

    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

dm = pd.read_csv(r'{bc_path}', sep='\\t', index_col=0)

# PCoA (eigendecomposition)
n = dm.shape[0]
A = -0.5 * dm.values ** 2
row_mean = A.mean(axis=1, keepdims=True)
col_mean = A.mean(axis=0, keepdims=True)
grand_mean = A.mean()
B = A - row_mean - col_mean + grand_mean

eigenvalues, eigenvectors = np.linalg.eigh(B)
idx = np.argsort(eigenvalues)[::-1]
eigenvalues = eigenvalues[idx]
eigenvectors = eigenvectors[:, idx]

# 正の固有値のみ
pos = eigenvalues > 0
eigenvalues_pos = eigenvalues[pos]
eigenvectors_pos = eigenvectors[:, pos]

coords = eigenvectors_pos[:, :2] * np.sqrt(eigenvalues_pos[:2])

# 寄与率
total_var = eigenvalues_pos.sum()
pc1_pct = eigenvalues_pos[0] / total_var * 100
pc2_pct = eigenvalues_pos[1] / total_var * 100

fig, ax = plt.subplots(figsize=(10, 8))
has_groups = False
{color_block}
if not has_groups:
    ax.scatter(coords[:, 0], coords[:, 1], s=50, alpha=0.8, edgecolors='white', linewidth=0.5)

ax.set_xlabel(f'PC1 ({{pc1_pct:.1f}}%)', fontsize=12)
ax.set_ylabel(f'PC2 ({{pc2_pct:.1f}}%)', fontsize=12)
ax.set_title('PCoA of Beta Diversity', fontsize=14)
ax.axhline(0, color='gray', linewidth=0.5, linestyle='--')
ax.axvline(0, color='gray', linewidth=0.5, linestyle='--')
plt.tight_layout()
plt.savefig(os.path.join(FIGURE_DIR, 'beta_pcoa.png'), dpi=DPI, bbox_inches='tight')
plt.close()
print('Saved: beta_pcoa.png')
"""


def _gen_denoising_stats(figure_dir, export_files, metadata_path, group_col):
    dn_path = _get_path(export_files, "denoising")
    if not dn_path:
        return None
    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

stats = pd.read_csv(r'{dn_path}', sep='\\t', index_col=0, comment='#')

# 数値列を選択
cols_to_plot = []
for c in ['input', 'filtered', 'denoised', 'merged', 'non-chimeric']:
    matches = [sc for sc in stats.columns if c in sc.lower()]
    if matches:
        cols_to_plot.append(matches[0])

if not cols_to_plot:
    cols_to_plot = [c for c in stats.columns if stats[c].dtype in ['int64', 'float64']][:5]

plot_data = stats[cols_to_plot].copy()

# サンプル数が多い場合は平均値のバーチャート
if len(plot_data) > 30:
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # 左: 平均値バーチャート
    means = plot_data.mean()
    stds = plot_data.std()
    ax = axes[0]
    x = range(len(means))
    bars = ax.bar(x, means, yerr=stds, capsize=3, color=['#4C72B0', '#55A868', '#C44E52', '#8172B2', '#CCB974'][:len(means)], edgecolor='white')
    ax.set_xticks(x)
    ax.set_xticklabels([c.replace('_', '\\n') for c in cols_to_plot], rotation=45, ha='right', fontsize=9)
    ax.set_ylabel('Read Count', fontsize=12)
    ax.set_title('Denoising Statistics (Mean ± SD)', fontsize=14)
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f'{{int(m):,}}', ha='center', va='bottom', fontsize=8)

    # 右: 歩留まり率
    if 'input' in cols_to_plot[0].lower():
        input_col = cols_to_plot[0]
        retention = (plot_data.div(plot_data[input_col], axis=0) * 100)
        ax2 = axes[1]
        bp = ax2.boxplot([retention[c].dropna().values for c in cols_to_plot],
                         labels=[c.replace('_', '\\n') for c in cols_to_plot],
                         patch_artist=True)
        colors = ['#4C72B0', '#55A868', '#C44E52', '#8172B2', '#CCB974'][:len(cols_to_plot)]
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax2.set_ylabel('Retention (%)', fontsize=12)
        ax2.set_title('Read Retention Rate', fontsize=14)
        plt.setp(ax2.get_xticklabels(), rotation=45, ha='right', fontsize=9)
    else:
        axes[1].set_visible(False)

    plt.tight_layout()
    plt.savefig(os.path.join(FIGURE_DIR, 'denoising_stats.png'), dpi=DPI, bbox_inches='tight')
    plt.close()
    print('Saved: denoising_stats.png')
else:
    # サンプル数が少ない場合は全サンプル表示
    fig, ax = plt.subplots(figsize=(max(12, len(plot_data) * 0.5), 6))
    x = np.arange(len(plot_data))
    width = 0.15
    colors = ['#4C72B0', '#55A868', '#C44E52', '#8172B2', '#CCB974']
    for i, col in enumerate(cols_to_plot):
        ax.bar(x + i * width, plot_data[col], width, label=col, color=colors[i % len(colors)])
    ax.set_xticks(x + width * (len(cols_to_plot) - 1) / 2)
    ax.set_xticklabels(plot_data.index, rotation=90, fontsize=7)
    ax.set_ylabel('Read Count', fontsize=12)
    ax.set_title('Denoising Statistics per Sample', fontsize=14)
    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(FIGURE_DIR, 'denoising_stats.png'), dpi=DPI, bbox_inches='tight')
    plt.close()
    print('Saved: denoising_stats.png')
"""


def _gen_alpha_group_comparison(figure_dir, export_files, metadata_path, group_col):
    alpha_paths = export_files.get("alpha", [])
    if not alpha_paths or not metadata_path:
        return None
    group_col = group_col or _detect_group_col(metadata_path)
    if not group_col:
        return None

    alpha_paths_str = repr(alpha_paths)
    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import os
from scipy import stats as sp_stats

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')
meta.columns = [c.strip() for c in meta.columns]
id_col = meta.columns[0]
meta = meta.set_index(id_col)

alpha_files = {alpha_paths_str}

import seaborn as sns

for apath in alpha_files:
    try:
        alpha_df = pd.read_csv(apath, sep='\\t', index_col=0)
        val_col = [c for c in alpha_df.columns if c != 'sample-id'][0]
        metric_name = os.path.basename(os.path.dirname(apath))
        if not metric_name or metric_name == 'alpha':
            metric_name = val_col

        common = alpha_df.index.intersection(meta.index)
        merged = alpha_df.loc[common].copy()
        merged['{group_col}'] = meta.loc[common, '{group_col}']

        # Kruskal-Wallis test
        groups = [g[val_col].values for _, g in merged.groupby('{group_col}')]
        if len(groups) >= 2:
            h_stat, p_val = sp_stats.kruskal(*groups)
        else:
            h_stat, p_val = 0, 1

        fig, ax = plt.subplots(figsize=(10, 6))
        sns.boxplot(data=merged, x='{group_col}', y=val_col, ax=ax, palette='Set2')
        sns.stripplot(data=merged, x='{group_col}', y=val_col, ax=ax, color='black', alpha=0.4, size=3)
        ax.set_title(f'{{metric_name}} by {group_col}\\n(Kruskal-Wallis H={{h_stat:.2f}}, p={{p_val:.4f}})', fontsize=13)
        ax.set_ylabel(metric_name, fontsize=12)
        ax.set_xlabel('{group_col}', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        fname = f'alpha_{{metric_name}}_group_comparison.png'
        plt.savefig(os.path.join(FIGURE_DIR, fname), dpi=DPI, bbox_inches='tight')
        plt.close()
        print(f'Saved: {{fname}}')

    except Exception as e:
        print(f'Error: {{e}}')
"""


def _gen_heatmap(figure_dir, export_files, metadata_path, group_col):
    ft_path = _get_path(export_files, "feature_table")
    tax_path = _get_path(export_files, "taxonomy")
    if not ft_path or not tax_path:
        return None
    group_col = group_col or _detect_group_col(metadata_path)

    meta_block = ""
    if metadata_path and group_col:
        meta_block = f"""
try:
    meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')
    meta.columns = [c.strip() for c in meta.columns]
    id_col = meta.columns[0]
    meta = meta.set_index(id_col)
    if '{group_col}' in meta.columns:
        common = rel_genus.columns.intersection(meta.index)
        rel_genus = rel_genus[sorted(common, key=lambda s: str(meta.loc[s, '{group_col}']) if s in meta.index else '')]
except Exception:
    pass
"""

    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

ft = pd.read_csv(r'{ft_path}', sep='\\t', skiprows=1, index_col=0)
ft.index.name = 'Feature ID'
tax = pd.read_csv(r'{tax_path}', sep='\\t', index_col=0)

tax['genus'] = tax['Taxon'].str.extract(r'g__([^;]+)')[0].fillna('Unknown').str.strip()
tax.loc[tax['genus'] == '', 'genus'] = 'Unknown'

ft_tax = ft.copy()
ft_tax['genus'] = tax.reindex(ft_tax.index)['genus'].fillna('Unknown')
genus_table = ft_tax.groupby('genus').sum()
rel_genus = genus_table.div(genus_table.sum(axis=0), axis=1)

top20 = rel_genus.mean(axis=1).nlargest(20).index.tolist()
if 'Unknown' in top20:
    top20.remove('Unknown')
    top20 = top20[:20]

plot_data = rel_genus.loc[top20]
{meta_block}
import seaborn as sns
fig, ax = plt.subplots(figsize=(max(14, len(plot_data.columns) * 0.25), 8))
sns.heatmap(plot_data, cmap='YlOrRd', ax=ax, xticklabels=True, yticklabels=True,
            linewidths=0.1, linecolor='white')
ax.set_title('Top 20 Genera Relative Abundance Heatmap', fontsize=14)
ax.set_xlabel('Sample', fontsize=11)
ax.set_ylabel('Genus', fontsize=11)
plt.xticks(fontsize=6, rotation=90)
plt.yticks(fontsize=9)
plt.tight_layout()
plt.savefig(os.path.join(FIGURE_DIR, 'genus_heatmap.png'), dpi=DPI, bbox_inches='tight')
plt.close()
print('Saved: genus_heatmap.png')
"""


def _gen_phylum_barplot(figure_dir, export_files, metadata_path, group_col):
    ft_path = _get_path(export_files, "feature_table")
    tax_path = _get_path(export_files, "taxonomy")
    if not ft_path or not tax_path:
        return None

    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

ft = pd.read_csv(r'{ft_path}', sep='\\t', skiprows=1, index_col=0)
ft.index.name = 'Feature ID'
tax = pd.read_csv(r'{tax_path}', sep='\\t', index_col=0)

tax['phylum'] = tax['Taxon'].str.extract(r'p__([^;]+)')[0].fillna('Unknown').str.strip()
tax.loc[tax['phylum'] == '', 'phylum'] = 'Unknown'

ft_tax = ft.copy()
ft_tax['phylum'] = tax.reindex(ft_tax.index)['phylum'].fillna('Unknown')
phylum_table = ft_tax.groupby('phylum').sum()
rel_phylum = phylum_table.div(phylum_table.sum(axis=0), axis=1)

mean_abundance = rel_phylum.mean(axis=1).sort_values(ascending=True)
top10 = mean_abundance.tail(10)

fig, ax = plt.subplots(figsize=(10, 6))
colors = plt.cm.Set3(range(len(top10)))
bars = ax.barh(range(len(top10)), top10.values, color=colors, edgecolor='white')
ax.set_yticks(range(len(top10)))
ax.set_yticklabels(top10.index, fontsize=10)
ax.set_xlabel('Mean Relative Abundance', fontsize=12)
ax.set_title('Top 10 Phyla by Mean Relative Abundance', fontsize=14)
for bar, val in zip(bars, top10.values):
    ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height()/2,
            f'{{val:.3f}}', va='center', fontsize=9)
plt.tight_layout()
plt.savefig(os.path.join(FIGURE_DIR, 'phylum_barplot.png'), dpi=DPI, bbox_inches='tight')
plt.close()
print('Saved: phylum_barplot.png')
"""


def _gen_rarefaction(figure_dir, export_files, metadata_path, group_col):
    ft_path = _get_path(export_files, "feature_table")
    if not ft_path:
        return None

    return f"""import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

FIGURE_DIR = r'{figure_dir}'
DPI = 150
os.makedirs(FIGURE_DIR, exist_ok=True)

ft = pd.read_csv(r'{ft_path}', sep='\\t', skiprows=1, index_col=0)
ft.index.name = 'Feature ID'

# Rarefaction curve calculation
depths = np.linspace(100, ft.sum(axis=0).max(), 20).astype(int)
n_samples = min(len(ft.columns), 50)
sample_cols = ft.sum(axis=0).nlargest(n_samples).index.tolist()

fig, ax = plt.subplots(figsize=(10, 6))
cmap = plt.cm.viridis

for j, sample in enumerate(sample_cols):
    counts = ft[sample].values
    counts = counts[counts > 0]
    total = counts.sum()

    richness = []
    for d in depths:
        if d >= total:
            richness.append((counts > 0).sum())
        else:
            # Rarefaction: expected species for subsampled depth
            n_features = len(counts)
            expected = 0
            for c in counts:
                if c > 0:
                    # Probability of NOT sampling this feature
                    from scipy.special import comb
                    if total - c >= d:
                        prob_absent = comb(total - c, d, exact=False) / comb(total, d, exact=False) if comb(total, d, exact=False) > 0 else 0
                    else:
                        prob_absent = 0
                    expected += (1 - prob_absent)
            richness.append(expected)

    color = cmap(j / max(n_samples - 1, 1))
    ax.plot(depths, richness, color=color, alpha=0.5, linewidth=0.8)

ax.set_xlabel('Sequencing Depth', fontsize=12)
ax.set_ylabel('Observed Features', fontsize=12)
ax.set_title('Rarefaction Curves', fontsize=14)
plt.tight_layout()
plt.savefig(os.path.join(FIGURE_DIR, 'rarefaction_curve.png'), dpi=DPI, bbox_inches='tight')
plt.close()
print('Saved: rarefaction_curve.png')
"""


# ─────────────────────────────────────────────────────────────────────────────
# テンプレートレジストリ
# ─────────────────────────────────────────────────────────────────────────────

_GENERATORS = {
    "genus_barplot": _gen_genus_barplot,
    "alpha_boxplot": _gen_alpha_boxplot,
    "beta_pcoa": _gen_beta_pcoa,
    "denoising_stats": _gen_denoising_stats,
    "alpha_group_comparison": _gen_alpha_group_comparison,
    "heatmap": _gen_heatmap,
    "phylum_barplot": _gen_phylum_barplot,
    "rarefaction": _gen_rarefaction,
}
