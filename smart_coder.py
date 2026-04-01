#!/usr/bin/env python3
"""
smart_coder.py — LLM の推論力だけを活かすコード生成
=====================================================
LLM に「コード全体」を書かせると 12% しか成功しない。
原因: import 忘れ、ファイル形式の無知、モジュール不在。

解決: コードを 3 層に分離し、LLM には「中間層だけ」書かせる。

  Layer A (確定的): import + データ読み込み + 保存関数  ← テンプレート
  Layer B (LLM):    分析ロジック (統計検定、可視化)     ← ここだけ LLM
  Layer C (確定的): 図の保存 + stdout 出力              ← テンプレート

LLM は「データは既に df に入っている。群は groups にある。
       fig, ax を作って描画せよ」だけを考える。
import もファイル読み込みも不要。
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Optional, Callable


def build_scaffold(
    export_files: dict[str, list[str]],
    metadata_path: str,
    group_column: str,
    figure_dir: str,
    task_key: str,
    step_num: int = 1,
) -> tuple[str, str, str]:
    """
    確定的な Layer A (前半) と Layer C (後半) を生成。
    LLM は Layer B (中間) だけを書く。

    Returns: (layer_a, layer_b_prompt, layer_c)
    """
    # ── Layer A: データ読み込み（確定的、エラーなし）──
    layer_a_lines = [
        "import matplotlib; matplotlib.use('Agg')",
        "import matplotlib.pyplot as plt",
        "import pandas as pd",
        "import numpy as np",
        "import os",
        "",
        f"FIGURE_DIR = r'{figure_dir}'",
        "DPI = 150",
        "os.makedirs(FIGURE_DIR, exist_ok=True)",
        "",
    ]

    # Feature table
    ft_paths = export_files.get("feature_table", [])
    if ft_paths and Path(ft_paths[0]).exists():
        with open(ft_paths[0]) as f:
            first = f.readline()
        if first.startswith("# "):
            layer_a_lines.append(f"ft = pd.read_csv(r'{ft_paths[0]}', sep='\\t', skiprows=1, index_col=0)")
        else:
            layer_a_lines.append(f"ft = pd.read_csv(r'{ft_paths[0]}', sep='\\t', index_col=0)")
        layer_a_lines.append("ft_samples = list(ft.columns)")
        layer_a_lines.append(f"print(f'Feature table: {{ft.shape[0]}} ASVs x {{ft.shape[1]}} samples')")
        layer_a_lines.append("")

    # Taxonomy
    tax_paths = export_files.get("taxonomy", [])
    if tax_paths and Path(tax_paths[0]).exists():
        with open(tax_paths[0]) as f:
            header = f.readline().strip().split("\t")
        taxon_col = next((h for h in header if h.lower() in ("taxon", "taxonomy")), None)
        layer_a_lines.append(f"tax = pd.read_csv(r'{tax_paths[0]}', sep='\\t', index_col=0)")
        if taxon_col:
            layer_a_lines.append(f"tax['Genus'] = tax['{taxon_col}'].str.extract(r'g__([^;]+)')[0].fillna('Unknown')")
            layer_a_lines.append(f"tax['Phylum'] = tax['{taxon_col}'].str.extract(r'p__([^;]+)')[0].fillna('Unknown')")
        layer_a_lines.append("")

    # Metadata
    if metadata_path and Path(metadata_path).exists():
        layer_a_lines.append(f"meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')")
        layer_a_lines.append("meta = meta.set_index(meta.columns[0])")
        layer_a_lines.append(f"group_col = '{group_column}'")
        layer_a_lines.append("groups = sorted(meta[group_col].dropna().unique())")
        layer_a_lines.append(f"print(f'Groups ({{group_col}}): {{groups}}')")
        layer_a_lines.append("")

    # Alpha
    alpha_paths = export_files.get("alpha", [])
    for i, ap in enumerate(alpha_paths):
        if Path(ap).exists():
            name = Path(ap).parent.name or f"alpha_{i}"
            vname = f"alpha_{name}".replace("-", "_")
            layer_a_lines.append(f"{vname} = pd.read_csv(r'{ap}', sep='\\t', index_col=0)")

    # Beta
    beta_paths = export_files.get("beta", [])
    for i, bp in enumerate(beta_paths):
        if Path(bp).exists():
            name = Path(bp).parent.name or f"beta_{i}"
            vname = f"dm_{name}".replace("-", "_")
            layer_a_lines.append(f"{vname} = pd.read_csv(r'{bp}', sep='\\t', index_col=0)")

    layer_a_lines += [
        "",
        "# ═══ ALL DATA LOADED. Variables available: ═══",
        "# ft: feature table (ASVs × samples)",
        "# tax: taxonomy (if available), with .Genus and .Phylum columns",
        "# meta: metadata, indexed by sample ID",
        "# group_col: grouping column name",
        "# groups: list of group labels",
        "# alpha_*: alpha diversity DataFrames",
        "# dm_*: distance matrix DataFrames",
        "# ═══ YOUR ANALYSIS CODE BELOW ═══",
        "",
    ]

    layer_a = "\n".join(layer_a_lines)

    # ── Layer B prompt: LLM が書く部分の指示 ──
    task_prompts = {
        "alpha_boxplot": (
            "Create a boxplot of alpha diversity (use alpha_shannon_vector or the first alpha_* variable) "
            "grouped by group_col. Color each group differently. "
            "Run Kruskal-Wallis test: from scipy.stats import kruskal — if scipy not available, "
            "compute manually. Annotate the p-value on the plot. "
            "Store the figure in variable 'fig'."
        ),
        "genus_barplot": (
            "Create a stacked bar chart of the top 15 genera (use tax['Genus'] and ft). "
            "Compute relative abundance per sample, group by genus, take top 15 by mean abundance. "
            "Plot with matplotlib stacked bar. Store the figure in variable 'fig'."
        ),
        "beta_pcoa": (
            "Perform PCoA on the first dm_* distance matrix. "
            "Use numpy eigendecomposition: center the distance matrix with H = I - 1/n, "
            "B = -0.5 * H @ D^2 @ H, then np.linalg.eigh(B). "
            "Plot PC1 vs PC2, color by group_col. DO NOT use skbio. "
            "Store the figure in variable 'fig'."
        ),
        "rarefaction": (
            "Plot rarefaction curves per group. For each group, for increasing depths, "
            "estimate the expected number of observed ASVs using: "
            "E[S] = sum(1 - (1-p_i)^d for each ASV with proportion p_i). "
            "Plot depth vs expected richness, one line per group. "
            "Store the figure in variable 'fig'."
        ),
        "cooccurrence_network": (
            "Compute Spearman correlation between the top 20 ASVs (by total abundance) "
            "using ft.T.corr(method='spearman'). "
            "Plot as a heatmap with plt.imshow, cmap='RdBu_r', vmin=-1, vmax=1. "
            "Store the figure in variable 'fig'."
        ),
    }

    layer_b_prompt = task_prompts.get(task_key,
        f"Create a visualization for '{task_key}'. Store figure in variable 'fig'.")

    # ── Layer C: 保存（確定的）──
    layer_c = f"""
# ═══ SAVE (do not modify) ═══
try:
    fig_path = os.path.join(FIGURE_DIR, 'ai{step_num:02d}_{task_key}.png')
    fig.savefig(fig_path, dpi=DPI, bbox_inches='tight')
    plt.close('all')
    print(f'Saved: {{fig_path}}')
except Exception as e:
    print(f'Save error: {{e}}')
    plt.close('all')
"""
    return layer_a, layer_b_prompt, layer_c


class SmartCoder:
    """
    LLM に分析ロジックだけを書かせるコード生成エンジン。

    使い方:
        coder = SmartCoder()
        result = coder.generate(task, export_files, metadata, group, figdir,
                                llm_call, run_code)
    """

    def __init__(self, log_callback: Optional[Callable] = None):
        self._log = log_callback or (lambda msg: print(msg))

    def generate(
        self,
        task_key: str,
        export_files: dict,
        metadata_path: str,
        group_column: str,
        figure_dir: str,
        llm_call: Callable,
        extract_code: Callable,
        run_code: Callable,
        max_retries: int = 5,
        step_num: int = 1,
    ) -> dict:
        """
        3層分離コード生成。

        Returns: {"success": bool, "code": str, "method": str,
                  "attempts": int, "figures": list}
        """
        layer_a, task_prompt, layer_c = build_scaffold(
            export_files, metadata_path, group_column, figure_dir,
            task_key, step_num)

        # LLM への指示: Layer B だけを書け
        llm_prompt = f"""You are writing ONLY the analysis section of a Python script.
The data is ALREADY LOADED into these variables:
- ft: feature table DataFrame (rows=ASVs, cols=samples)
- meta: metadata DataFrame (indexed by sample ID)
- group_col: '{group_column}' (string)
- groups: {group_column} unique values
- alpha_*: alpha diversity DataFrames
- dm_*: distance matrix DataFrames
- tax: taxonomy DataFrame with .Genus and .Phylum (if available)

matplotlib, pandas, numpy are ALREADY IMPORTED.
DO NOT import anything. DO NOT read any files. They are loaded.

YOUR TASK: {task_prompt}

RULES:
1. DO NOT write import statements
2. DO NOT read files with pd.read_csv
3. Use ONLY the pre-loaded variables above
4. Create fig, ax = plt.subplots(...)
5. DO NOT call plt.show() or fig.savefig() — handled after your code
6. Print statistical results with print()

Write ONLY the analysis code (no imports, no file loading, no saving):"""

        msgs = [
            {"role": "system", "content":
             "Write ONLY analysis code. No imports. No file reading. No saving. "
             "Variables ft, meta, group_col, groups, alpha_*, dm_* are already loaded."},
            {"role": "user", "content": llm_prompt},
        ]

        for attempt in range(max_retries):
            self._log(f"    [{task_key}] Attempt {attempt+1}/{max_retries}")

            try:
                if attempt == 0:
                    resp = llm_call(msgs)
                else:
                    # 具体的エラーフィードバック
                    fix_prompt = (
                        f"Your code failed with:\n{last_err[:500]}\n\n"
                        f"Remember: all data is ALREADY in ft, meta, group_col, groups.\n"
                        f"DO NOT import anything. DO NOT read files.\n"
                        f"Fix ONLY the analysis logic:"
                    )
                    msgs_fix = msgs + [
                        {"role": "assistant", "content": f"```python\n{layer_b}\n```"},
                        {"role": "user", "content": fix_prompt},
                    ]
                    resp = llm_call(msgs_fix)

                layer_b = extract_code(resp.get("content", ""))
                if not layer_b:
                    continue

                # Layer B をクリーニング: import 文や file 読み込みを除去
                layer_b = self._clean_layer_b(layer_b)

                # 3層を結合
                full_code = layer_a + layer_b + "\n" + layer_c

                # 実行
                success, stdout, stderr, figs = run_code(full_code)

                if success:
                    self._log(f"    [{task_key}] SUCCESS on attempt {attempt+1}")
                    return {"success": True, "code": full_code, "method": "smart_coder",
                            "attempts": attempt+1, "figures": figs}
                else:
                    last_err = stderr
                    # エラー行を Layer B 内に限定して報告
                    self._log(f"    [{task_key}] Error: {self._extract_error(stderr)}")

            except Exception as e:
                last_err = str(e)
                self._log(f"    [{task_key}] Exception: {e}")

        # フォールバック: 確定的テンプレート
        self._log(f"    [{task_key}] All attempts failed → template fallback")
        template = self._get_fallback(task_key, layer_a, layer_c)
        if template:
            success, stdout, stderr, figs = run_code(template)
            if success:
                return {"success": True, "code": template, "method": "template_fallback",
                        "attempts": max_retries, "figures": figs}

        return {"success": False, "code": "", "method": "failed",
                "attempts": max_retries, "figures": []}

    def _clean_layer_b(self, code: str) -> str:
        """Layer B から import 文やファイル読み込みを除去"""
        lines = []
        for line in code.split("\n"):
            stripped = line.strip()
            # import 文を除去
            if stripped.startswith("import ") or stripped.startswith("from "):
                continue
            # pd.read_csv を除去
            if "pd.read_csv" in stripped or "read_csv" in stripped:
                continue
            # matplotlib.use を除去
            if "matplotlib.use" in stripped:
                continue
            # os.makedirs (既にある)
            if "os.makedirs" in stripped and "FIGURE_DIR" in stripped:
                continue
            # plt.show を除去
            if "plt.show()" in stripped:
                continue
            # savefig を除去 (Layer C が担当)
            if ".savefig(" in stripped:
                continue
            lines.append(line)
        return "\n".join(lines)

    def _extract_error(self, stderr: str) -> str:
        """stderr から最終エラー行を抽出"""
        lines = [l.strip() for l in stderr.split("\n") if l.strip()]
        for line in reversed(lines):
            for et in ["Error", "Exception"]:
                if et in line:
                    return line[:100]
        return lines[-1][:100] if lines else "unknown"

    def _get_fallback(self, task_key: str, layer_a: str, layer_c: str) -> Optional[str]:
        """確定的フォールバックコード"""
        fallbacks = {
            "alpha_boxplot": """
# Fallback: alpha boxplot
alpha_var = [v for k,v in locals().items() if k.startswith('alpha_') and hasattr(v,'columns')]
if alpha_var:
    alpha_df = alpha_var[0]
    acol = alpha_df.columns[0]
    common = sorted(set(meta.index) & set(alpha_df.index))
    fig, ax = plt.subplots(figsize=(8, 5))
    plot_data = []
    for g in groups:
        sids = meta.loc[common][meta.loc[common, group_col]==g].index
        vals = alpha_df.loc[alpha_df.index.isin(sids), acol].dropna().values
        if len(vals) > 0: plot_data.append(vals)
    if plot_data:
        bp = ax.boxplot(plot_data, labels=groups[:len(plot_data)], patch_artist=True)
        for patch, c in zip(bp['boxes'], plt.cm.Set2(np.linspace(0,1,len(plot_data)))): patch.set_facecolor(c)
    ax.set_ylabel(acol); ax.set_title(f'Alpha Diversity by {group_col}')
else:
    fig, ax = plt.subplots(); ax.text(0.5,0.5,'No alpha data',ha='center')
""",
            "beta_pcoa": """
# Fallback: PCoA
dm_var = [v for k,v in locals().items() if k.startswith('dm_') and hasattr(v,'shape')]
if dm_var:
    dm = dm_var[0]
    common = sorted(set(dm.index) & set(meta.index))
    dm_c = dm.loc[common, common]
    n = len(common); D = dm_c.values.astype(float)
    H = np.eye(n) - np.ones((n,n))/n; B = -0.5*H@(D**2)@H
    ev,ec = np.linalg.eigh(B); idx = np.argsort(ev)[::-1]; ev=ev[idx]; ec=ec[:,idx]
    p1 = ec[:,0]*np.sqrt(max(ev[0],0)); p2 = ec[:,1]*np.sqrt(max(ev[1],0))
    fig, ax = plt.subplots(figsize=(8,6))
    gp = meta.loc[common, group_col]
    for g in sorted(gp.dropna().unique()): mask=gp==g; ax.scatter(p1[mask],p2[mask],label=g,s=40,alpha=0.7)
    tv=sum(max(e,0) for e in ev[:10])
    if tv>0: ax.set_xlabel(f'PC1 ({max(ev[0],0)/tv*100:.1f}%)'); ax.set_ylabel(f'PC2 ({max(ev[1],0)/tv*100:.1f}%)')
    ax.set_title('PCoA (Bray-Curtis)'); ax.legend()
else:
    fig, ax = plt.subplots(); ax.text(0.5,0.5,'No beta data',ha='center')
""",
            "genus_barplot": """
# Fallback: genus barplot
if 'tax' in dir() and hasattr(tax, 'Genus'):
    fc = ft.loc[:, ft.columns.isin(meta.index)]
    fc_g = fc.copy(); fc_g['Genus'] = tax.reindex(fc.index)['Genus'].fillna('Unknown')
    gs = fc_g.groupby('Genus').sum(); gr = gs.div(gs.sum())*100
    top = gr.mean(axis=1).nlargest(15).index; gt = gr.loc[top]
    fig, ax = plt.subplots(figsize=(12,6))
    gt.T.plot(kind='bar', stacked=True, ax=ax, colormap='tab20')
    ax.set_title('Top 15 Genera'); ax.legend(bbox_to_anchor=(1.05,1), fontsize=5)
else:
    fig, ax = plt.subplots(); ax.text(0.5,0.5,'No taxonomy data',ha='center')
""",
            "rarefaction": """
# Fallback: rarefaction
fc = ft.loc[:, ft.columns.isin(meta.index)]
fig, ax = plt.subplots(figsize=(8,5))
for g in groups:
    sids = [s for s in meta[meta[group_col]==g].index if s in fc.columns]
    if not sids: continue
    depths=[]; rich=[]
    mx = int(fc[sids].sum().min()) if sids else 0
    for d in range(100, max(mx,200), max(mx//20,100)):
        obs=[]
        for s in sids:
            col=fc[s].values; total=col.sum()
            if total<d: continue
            p=col/total; obs.append(sum(1-(1-pi)**d for pi in p if pi>0))
        if obs: depths.append(d); rich.append(np.mean(obs))
    if depths: ax.plot(depths, rich, label=g, linewidth=2)
ax.set_xlabel('Depth'); ax.set_ylabel('Expected ASVs'); ax.set_title('Rarefaction'); ax.legend()
""",
            "cooccurrence_network": """
# Fallback: correlation heatmap
fc = ft.loc[:, ft.columns.isin(meta.index)]
top20 = fc.sum(axis=1).nlargest(20).index; ftt = fc.loc[top20].T
corr = ftt.corr(method='spearman')
fig, ax = plt.subplots(figsize=(8,7))
im = ax.imshow(corr.values, cmap='RdBu_r', vmin=-1, vmax=1)
ax.set_xticks(range(len(corr))); ax.set_xticklabels([str(x)[:8] for x in corr.columns], rotation=90, fontsize=4)
ax.set_yticks(range(len(corr))); ax.set_yticklabels([str(x)[:8] for x in corr.index], fontsize=4)
ax.set_title('Top 20 ASV Correlation'); plt.colorbar(im, ax=ax)
""",
        }

        fb = fallbacks.get(task_key)
        if fb:
            return layer_a + fb + "\n" + layer_c
        return None
