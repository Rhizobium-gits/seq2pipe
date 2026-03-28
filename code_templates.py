#!/usr/bin/env python3
"""
code_templates.py
=================
LLM のコード生成成功率を向上させるためのテンプレートエンジン。

問題: qwen2.5-coder:7b は QIIME2 のエクスポート形式 (TSV) の
正確なヘッダ構造を知らない → KeyError, IndexError が頻発。

解決: データファイルを事前に inspect し、正確なカラム名・型・
サンプル数を含むコードテンプレートを生成して LLM に渡す。

LLM は「何を描くか」だけを考えればよく、
「どうデータを読むか」はテンプレートが保証する。
"""
from __future__ import annotations
from pathlib import Path


def build_data_preamble(
    export_files: dict[str, list[str]],
    metadata_path: str = "",
    group_column: str = "",
    figure_dir: str = "",
    step_num: int = 1,
    figure_prefix: str = "fig",
) -> str:
    """
    LLM に渡すコード生成プロンプトの先頭に付ける
    「データ読み込み済みテンプレート」を生成。

    これにより LLM は pd.read_csv の引数を間違えない。
    """
    lines = [
        "# === AUTO-GENERATED PREAMBLE (do NOT modify) ===",
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

    # ── Feature table ──
    ft_paths = export_files.get("feature_table", [])
    if ft_paths and Path(ft_paths[0]).exists():
        p = ft_paths[0]
        # Inspect header
        with open(p) as f:
            first = f.readline()
            if first.startswith("# "):
                header_line = f.readline().strip()
                lines.append(f"# Feature table: {p}")
                lines.append(f"# Header (after comment): {header_line[:100]}")
                lines.append(f"ft = pd.read_csv(r'{p}', sep='\\t', skiprows=1, index_col=0)")
            else:
                header_line = first.strip()
                lines.append(f"ft = pd.read_csv(r'{p}', sep='\\t', index_col=0)")
            cols = header_line.split("\t")
            n_samples = len(cols) - 1
            lines.append(f"# ft shape: ({{}}, {n_samples}) — rows=ASVs, cols=samples".format("n_asvs"))
            lines.append(f"ft_samples = list(ft.columns)  # {n_samples} sample IDs")
        lines.append("")

    # ── Taxonomy ──
    tax_paths = export_files.get("taxonomy", [])
    if tax_paths and Path(tax_paths[0]).exists():
        p = tax_paths[0]
        with open(p) as f:
            header = f.readline().strip().split("\t")
        lines.append(f"# Taxonomy: {p}")
        lines.append(f"# Columns: {header}")

        # Detect column names
        taxon_col = None
        for h in header:
            if h.lower() in ("taxon", "taxonomy", "lineage"):
                taxon_col = h
                break
        conf_col = None
        for h in header:
            if "confidence" in h.lower():
                conf_col = h
                break

        if taxon_col:
            lines.append(f"tax = pd.read_csv(r'{p}', sep='\\t', index_col=0)")
            lines.append(f"# Taxon column name: '{taxon_col}'")
            lines.append(f"tax['Genus'] = tax['{taxon_col}'].str.extract(r'g__([^;]+)')[0].fillna('Unknown').str.strip()")
            lines.append(f"tax['Phylum'] = tax['{taxon_col}'].str.extract(r'p__([^;]+)')[0].fillna('Unknown').str.strip()")
        else:
            lines.append(f"# WARNING: No 'Taxon' column found. Columns: {header}")
            lines.append(f"tax = pd.read_csv(r'{p}', sep='\\t', index_col=0)")
            lines.append(f"# tax columns: {header[1:] if len(header) > 1 else 'unknown'}")
        lines.append("")

    # ── Metadata ──
    if metadata_path and Path(metadata_path).exists():
        with open(metadata_path) as f:
            meta_header = f.readline().strip().split("\t")
            # skip q2:types
            second = f.readline().strip()
            has_q2types = second.startswith("#q2:")

        lines.append(f"# Metadata: {metadata_path}")
        lines.append(f"# Columns: {meta_header}")
        lines.append(f"meta = pd.read_csv(r'{metadata_path}', sep='\\t', comment='#')")
        lines.append(f"id_col = '{meta_header[0]}'")
        lines.append(f"meta = meta.set_index(id_col)")

        if group_column:
            lines.append(f"group_col = '{group_column}'")
            lines.append(f"groups = sorted(meta[group_col].dropna().unique())")
            lines.append(f"# Group column '{group_column}' — groups: see above")
        lines.append("")

    # ── Alpha diversity ──
    alpha_paths = export_files.get("alpha", [])
    if alpha_paths:
        lines.append("# Alpha diversity files:")
        for ap in alpha_paths:
            if Path(ap).exists():
                with open(ap) as f:
                    ah = f.readline().strip().split("\t")
                metric = Path(ap).parent.name or Path(ap).stem
                lines.append(f"#   {metric}: columns={ah}")
                lines.append(f"alpha_{metric.replace('-','_')} = pd.read_csv(r'{ap}', sep='\\t', index_col=0)")
        lines.append("")

    # ── Beta diversity ──
    beta_paths = export_files.get("beta", [])
    if beta_paths:
        lines.append("# Beta distance matrices:")
        for bp in beta_paths:
            if Path(bp).exists():
                metric = Path(bp).parent.name or Path(bp).stem
                lines.append(f"#   {metric}")
                lines.append(f"dm_{metric.replace('-','_')} = pd.read_csv(r'{bp}', sep='\\t', index_col=0)")
        lines.append("")

    # ── Figure save helper ──
    lines.append(f"def save_fig(name, fig=None):")
    lines.append(f"    path = os.path.join(FIGURE_DIR, f'ai{step_num:02d}_{{name}}.png')")
    lines.append(f"    (fig or plt.gcf()).savefig(path, dpi=DPI, bbox_inches='tight')")
    lines.append(f"    plt.close('all')")
    lines.append(f"    print(f'Saved: {{path}}')")
    lines.append(f"    return path")
    lines.append("")
    lines.append("# === END PREAMBLE ===")
    lines.append("# Your analysis code below. All data is already loaded.")
    lines.append("")

    return "\n".join(lines)


def build_template_prompt(
    preamble: str,
    analysis_description: str,
    research_question: str = "",
) -> str:
    """
    テンプレート付きの LLM プロンプトを構築。
    LLM は preamble のコードをそのまま使い、
    analysis_description に従って続きを書く。
    """
    return f"""The following Python preamble correctly loads all data files.
DO NOT modify the preamble. Write your analysis code AFTER it.

```python
{preamble}
```

## YOUR TASK
{analysis_description}

## RESEARCH QUESTION
{research_question}

## RULES
1. Use the variables already defined in the preamble (ft, tax, meta, group_col, etc.)
2. DO NOT re-read any files — they are already loaded
3. Use save_fig('description') to save figures
4. Print all statistical results to stdout
5. Return COMPLETE code including the preamble

Output ONLY Python code in ```python ... ```."""
