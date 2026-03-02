#!/usr/bin/env python3
"""
report_generator.py
===================
QIIME2 解析結果を HTML レポートとして出力する。

- 生成された図（JPG/PNG）を base64 で埋め込み
- LLM が各図の解釈文と総合サマリーを日本語で生成
- 解析パラメータ・手法・完了ステップを記録
"""

import base64
import datetime
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent


# ─────────────────────────────────────────────────────────────────────────────
# 図ファイル名 → 日本語タイトル
# ─────────────────────────────────────────────────────────────────────────────

_FIG_TITLE_MAP = {
    # analysis.py 決定論的解析 (fig01-fig25)
    "fig01": "DADA2 デノイジング統計",
    "fig02": "サンプル別シーケンス深度",
    "fig03": "アルファ多様性（複数指標ボックスプロット）",
    "fig04": "Shannon 多様性指数（サンプル別）",
    "fig05": "PCoA（Bray-Curtis）",
    "fig06": "PCoA（Jaccard）",
    "fig07": "PCoA（Unweighted UniFrac）",
    "fig08": "PCoA（Weighted UniFrac）",
    "fig09": "ベータ多様性距離行列ヒートマップ",
    "fig10": "上位 30 ASV ヒートマップ",
    "fig11": "アルファ多様性指標間相関",
    "fig12": "ASV リッチネス vs シーケンス深度",
    "fig13": "属レベル相対存在量（積み上げ棒グラフ）",
    "fig14": "門レベル相対存在量（積み上げ棒グラフ）",
    "fig15": "属レベルヒートマップ",
    "fig16": "ラレファクションカーブ",
    "fig17": "NMDS（Bray-Curtis）",
    "fig18": "Rank-Abundance カーブ",
    "fig19": "分類学的 Alluvial プロット（門→綱→目）",
    "fig20": "属間共起ネットワーク",
    "fig21": "科レベル相対存在量（積み上げ棒グラフ）",
    "fig22": "コアマイクロバイオーム（出現頻度 vs 存在量）",
    "fig23": "差次的存在量ボルケーノプロット",
    "fig24": "サンプルデンドログラム（UPGMA）",
    "fig25": "属間 Spearman 相関クラスターマップ",
    "fig26": "綱レベル相対存在量（積み上げ棒グラフ）",
    "fig27": "目レベル相対存在量（積み上げ棒グラフ）",
    "fig28": "Simpson 多様性 + Pielou 均等度",
    "fig29": "サンプル間 ASV 共有パターン",
    # 1ショット生成の代表的なファイル名（code_agent 用）
    "genus_stacked_bar": "属レベル相対存在量（積み上げ棒グラフ）",
    "phylum_bar": "門レベル相対存在量",
    "shannon": "Shannon α多様性",
    "shannon_boxplot": "Shannon α多様性（箱ひげ図）",
    "alpha": "α多様性",
    "pcoa": "主座標分析 (PCoA)",
    "pcoa_plot": "主座標分析 (PCoA)",
    "pca": "主成分分析 (PCA)",
    "nmds": "NMDS オーディネーション",
    "beta": "β多様性",
    "heatmap": "ヒートマップ",
    "rarefaction": "ラレファクションカーブ",
    "denoising": "DADA2 デノイジング統計",
    "read_depth": "サンプル別リード深度",
    "taxonomy": "分類学的組成",
    "corr": "サンプル間相関",
    "pie": "分類群パイチャート",
    "volcano": "ボルケーノプロット",
    "network": "共起ネットワーク",
    "alluvial": "Alluvial プロット",
    "dendrogram": "デンドログラム",
    "core": "コアマイクロバイオーム",
    "rank_abundance": "Rank-Abundance カーブ",
    "family": "科レベル組成",
    "adaptive": "適応型解析",
    "simpson": "Simpson 多様性",
    "pielou": "Pielou 均等度",
    "overlap": "ASV 共有パターン",
}


def _fig_title(path: str) -> str:
    stem = Path(path).stem.lower()
    # 完全一致
    if stem in _FIG_TITLE_MAP:
        return _FIG_TITLE_MAP[stem]
    # 部分一致（先頭キーから検索）
    for key, title in _FIG_TITLE_MAP.items():
        if stem.startswith(key) or key in stem:
            return title
    return Path(path).stem.replace("_", " ").title()


def _encode_image(path: str) -> str:
    """画像を base64 data URI に変換する"""
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
    }.get(ext, "image/png")
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


# ─────────────────────────────────────────────────────────────────────────────
# LLM による解釈生成
# ─────────────────────────────────────────────────────────────────────────────

def _llm_interpretations(
    fig_paths: list,
    user_prompt: str,
    model: str,
    n_samples: int,
    dada2_params: dict,
    log_callback: Optional[Callable],
) -> dict:
    """
    LLM に各図の解釈文と総合サマリーを生成させる。

    戻り値: {"SUMMARY": "...", "fig01_xxx": "...", ...}
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    if not model or not fig_paths:
        return {}

    param_str = "  ".join(
        f"{k}={v}" for k, v in (dada2_params or {}).items()
        if k in ("trunc_len_f", "trunc_len_r", "sampling_depth")
    )
    fig_list_str = "\n".join(
        f"- {Path(f).name} ({_fig_title(f)})" for f in fig_paths
    )

    prompt = "\n".join([
        "You are a microbiome bioinformatics expert writing a results report in Japanese.",
        f"- Sample count: {n_samples}" if n_samples else "",
        f"- DADA2 parameters: {param_str}" if param_str else "",
        f"- Analysis request: {user_prompt}" if user_prompt else "",
        "",
        "The following figures were generated:",
        fig_list_str,
        "",
        "Write the following in Japanese:",
        "1. SUMMARY: A 2-3 sentence overall summary of the microbiome analysis.",
        "2. For each figure, one sentence interpretation (filename stem as key).",
        "",
        "Output format (exactly as shown, no extra lines):",
        "SUMMARY: [overall summary]",
        *[f"{Path(f).stem}: [interpretation]" for f in fig_paths],
    ])

    _log("📝 LLM がレポート解釈文を生成中...")
    try:
        response = _agent.call_ollama(
            [
                {"role": "system", "content": "Microbiome expert. Write concise Japanese interpretations."},
                {"role": "user",   "content": prompt},
            ],
            model,
        )
        content = response.get("content", "")
    except Exception as e:
        _log(f"  ⚠️  LLM 呼び出し失敗: {e}")
        return {}

    result = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key and val:
            result[key] = val
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HTML テンプレート
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; background: #f4f6f8; color: #2c3e50; line-height: 1.65; }
header { background: linear-gradient(135deg, #154360, #117a65); color: white; padding: 2.5rem 3rem; }
header h1 { font-size: 2rem; letter-spacing: 0.03em; }
header p { opacity: 0.8; margin-top: 0.5rem; font-size: 0.93rem; }
.container { max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; }
.card { background: white; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,0.07); padding: 1.8rem 2rem; margin-bottom: 1.8rem; }
.card h2 { font-size: 1.25rem; color: #154360; border-bottom: 2px solid #d5eaf7; padding-bottom: 0.5rem; margin-bottom: 1.2rem; }
.card h3 { font-size: 1rem; color: #1a7a62; margin: 1rem 0 0.4rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }
th, td { text-align: left; padding: 0.55rem 0.9rem; border-bottom: 1px solid #eaf0f6; }
th { background: #eaf4fb; color: #154360; font-weight: 600; width: 40%; }
tr:hover { background: #f8fbfe; }
.summary-box { background: #e8f8f5; border-left: 4px solid #117a65; padding: 1rem 1.2rem; border-radius: 0 6px 6px 0; font-size: 0.97rem; color: #0e6655; margin-bottom: 0.5rem; }
.step-list { list-style: none; padding: 0; }
.step-list li { padding: 0.3rem 0; font-size: 0.91rem; color: #34495e; }
.step-list li::before { content: '✅  '; }
.step-failed::before { content: '❌  ' !important; color: #c0392b; }
.step-skipped::before { content: '⚠️  ' !important; color: #d4ac0d; }
.fig-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 1.4rem; }
.fig-card { border: 1px solid #d5eaf7; border-radius: 8px; overflow: hidden; background: #fafcfe; }
.fig-card img { width: 100%; height: auto; display: block; }
.fig-caption { padding: 0.9rem 1rem; }
.fig-caption strong { display: block; font-size: 0.95rem; color: #154360; margin-bottom: 0.35rem; }
.fig-caption p { font-size: 0.87rem; color: #5d6d7e; }
footer { text-align: center; padding: 2rem; font-size: 0.82rem; color: #a9b7c6; }
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>seq2pipe 解析レポート — {date}</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>🧬 seq2pipe 解析レポート</h1>
  <p>生成日時: {datetime_str} &nbsp;|&nbsp; QIIME2 マイクロバイオームパイプライン</p>
</header>
<div class="container">
{summary_section}
{params_section}
{methods_section}
{figures_section}
</div>
<footer>Generated by seq2pipe &nbsp;|&nbsp; QIIME2 + Ollama ({model})</footer>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# メイン関数
# ─────────────────────────────────────────────────────────────────────────────

def generate_html_report(
    fig_dir: str,
    output_dir: str,
    fastq_dir: str = "",
    n_samples: int = 0,
    dada2_params: Optional[dict] = None,
    completed_steps: Optional[list] = None,
    failed_steps: Optional[list] = None,
    export_files: Optional[dict] = None,
    user_prompt: str = "",
    model: str = "",
    log_callback: Optional[Callable] = None,
) -> str:
    """
    HTML レポートを生成して output_dir/report.html に保存する。
    戻り値: 生成されたファイルのパス
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    dada2_params   = dada2_params   or {}
    completed_steps = completed_steps or []
    failed_steps    = failed_steps    or []
    export_files    = export_files    or {}

    # ── 図ファイル収集 ────────────────────────────────────────────────
    fig_dir_path = Path(fig_dir)
    fig_files = sorted(
        list(fig_dir_path.glob("*.jpg"))
        + list(fig_dir_path.glob("*.jpeg"))
        + list(fig_dir_path.glob("*.png")),
        key=lambda p: p.name,
    )

    # ── LLM 解釈生成 ─────────────────────────────────────────────────
    interpretations: dict = {}
    if model and fig_files:
        interpretations = _llm_interpretations(
            [str(f) for f in fig_files],
            user_prompt, model, n_samples, dada2_params, log_callback,
        )

    now = datetime.datetime.now()
    date_str     = now.strftime("%Y-%m-%d")
    datetime_str = now.strftime("%Y年%m月%d日 %H:%M")

    # ── サマリーセクション ────────────────────────────────────────────
    summary_text = interpretations.get("SUMMARY", "")
    if summary_text:
        summary_section = (
            '<div class="card">'
            '<h2>総合サマリー</h2>'
            f'<div class="summary-box">{summary_text}</div>'
            '</div>'
        )
    else:
        summary_section = ""

    # ── パラメータセクション ──────────────────────────────────────────
    _PARAM_LABELS = {
        "trim_left_f":    "trim-left-f（フォワード先頭トリム塩基数）",
        "trim_left_r":    "trim-left-r（リバース先頭トリム塩基数）",
        "trunc_len_f":    "trunc-len-f（フォワードトランケーション長）",
        "trunc_len_r":    "trunc-len-r（リバーストランケーション長）",
        "sampling_depth": "sampling-depth（多様性解析深度）",
        "n_threads":      "スレッド数",
        "read_len_f":     "フォワードリード長",
        "read_len_r":     "リバースリード長",
    }
    rows = ""
    if fastq_dir:
        rows += f"<tr><th>FASTQ ディレクトリ</th><td>{fastq_dir}</td></tr>"
    if n_samples:
        rows += f"<tr><th>サンプル数</th><td>{n_samples} サンプル（ペアエンド）</td></tr>"
    for k, v in dada2_params.items():
        label = _PARAM_LABELS.get(k, k)
        if v:
            rows += f"<tr><th>{label}</th><td>{v}</td></tr>"
    if rows:
        params_section = (
            '<div class="card">'
            '<h2>解析パラメータ</h2>'
            f'<table><tbody>{rows}</tbody></table>'
            '</div>'
        )
    else:
        params_section = ""

    # ── 手法セクション ────────────────────────────────────────────────
    step_items = ""
    for s in completed_steps:
        cls = "step-skipped" if s.startswith("⚠️") else ""
        text = s.lstrip("✅⚠️ ")
        step_items += f'<li class="{cls}">{text}</li>'
    for s in failed_steps:
        text = s.lstrip("❌ ")
        step_items += f'<li class="step-failed">{text}</li>'

    if step_items:
        methods_section = (
            '<div class="card">'
            '<h2>解析手法・パイプラインステップ</h2>'
            '<h3>使用ソフトウェア</h3>'
            '<p style="font-size:0.9rem;color:#5d6d7e;margin-bottom:0.8rem">'
            'QIIME2（DADA2 デノイジング / MAFFT-FastTree 系統発生 / 多様性解析）+ Python（matplotlib, seaborn, pandas）'
            '</p>'
            '<h3>実行ステップ</h3>'
            f'<ul class="step-list">{step_items}</ul>'
            '</div>'
        )
    else:
        methods_section = (
            '<div class="card">'
            '<h2>解析手法</h2>'
            '<p>QIIME2 パイプライン: DADA2 デノイジング → 系統発生ツリー → 多様性解析 → 可視化</p>'
            '</div>'
        )

    # ── 図セクション ──────────────────────────────────────────────────
    if fig_files:
        fig_cards = ""
        for fp in fig_files:
            title = _fig_title(str(fp))
            interp = interpretations.get(fp.stem, "")
            try:
                data_uri = _encode_image(str(fp))
            except Exception:
                continue
            caption_p = f"<p>{interp}</p>" if interp else ""
            fig_cards += (
                '<div class="fig-card">'
                f'<img src="{data_uri}" alt="{title}" loading="lazy">'
                '<div class="fig-caption">'
                f'<strong>{title}</strong>'
                f'{caption_p}'
                '</div>'
                '</div>'
            )
        figures_section = (
            '<div class="card">'
            f'<h2>解析結果 — 図（{len(fig_files)} 件）</h2>'
            f'<div class="fig-grid">{fig_cards}</div>'
            '</div>'
        )
    else:
        figures_section = (
            '<div class="card">'
            '<h2>解析結果</h2>'
            '<p>図ファイルが見つかりませんでした。</p>'
            '</div>'
        )

    # ── HTML 組み立て・保存 ───────────────────────────────────────────
    html = _HTML_TEMPLATE.format(
        css=_CSS,
        date=date_str,
        datetime_str=datetime_str,
        summary_section=summary_section,
        params_section=params_section,
        methods_section=methods_section,
        figures_section=figures_section,
        model=model or "local LLM",
    )

    report_path = Path(output_dir) / "report.html"
    report_path.write_text(html, encoding="utf-8")
    _log(f"📄 レポートを保存しました: {report_path}")
    return str(report_path)


# ─────────────────────────────────────────────────────────────────────────────
# LaTeX / PDF レポート生成
# ─────────────────────────────────────────────────────────────────────────────

def _escape_latex(text: str) -> str:
    """LaTeX 特殊文字をエスケープする（通常テキスト用）"""
    conv = [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\textasciicircum{}"),
        ("<",  r"\textless{}"),
        (">",  r"\textgreater{}"),
    ]
    for old, new in conv:
        text = text.replace(old, new)
    return text


def _find_latex_engine() -> Optional[str]:
    """利用可能な LaTeX エンジン名を返す。なければ None。"""
    for engine in ("lualatex", "xelatex"):
        try:
            r = subprocess.run([engine, "--version"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return engine
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


def _build_latex_doc(
    engine: Optional[str],
    date_str: str,
    summary_text: str,
    fastq_dir: str,
    n_samples: int,
    dada2_params: dict,
    completed_steps: list,
    failed_steps: list,
    model: str,
    fig_paths: list,
    interpretations: dict,
) -> str:
    """LaTeX ドキュメント文字列を返す"""

    # ── プリアンブル ─────────────────────────────────────────────────
    if engine == "lualatex":
        preamble = r"""\documentclass[a4paper,12pt]{article}
\usepackage[hiragino-pron]{luatexja-preset}
"""
    elif engine == "xelatex":
        preamble = r"""\documentclass[a4paper,12pt]{article}
\usepackage{xeCJK}
\setCJKmainfont{Hiragino Mincho ProN}
\setCJKsansfont{Hiragino Kaku Gothic ProN}
"""
    else:
        # コンパイル不可の場合も有効な .tex として出力
        preamble = r"""\documentclass[a4paper,12pt]{article}
% NOTE: Japanese support requires lualatex + luatexja-preset, or xelatex + xeCJK.
% Compile with: lualatex report.tex
"""

    preamble += r"""
\usepackage[top=25mm,bottom=25mm,left=28mm,right=28mm]{geometry}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{float}
\usepackage{xcolor}
\usepackage{hyperref}
\usepackage{caption}
\usepackage{fancyhdr}
\usepackage{tcolorbox}

\definecolor{teal}{RGB}{17,122,101}
\definecolor{navy}{RGB}{21,67,96}
\hypersetup{colorlinks=true, linkcolor=navy, urlcolor=teal, pdfborder={0 0 0}}
\captionsetup{font=small, labelfont=bf, labelsep=period, justification=centering}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\color{navy}seq2pipe 解析レポート}
\fancyhead[R]{\small\thepage}
\renewcommand{\headrulewidth}{0.5pt}
"""

    # ── タイトル ─────────────────────────────────────────────────────
    title_block = r"""
\title{\textbf{seq2pipe 解析レポート}\\[0.5em]
  \large QIIME2 マイクロバイオームパイプライン}
\date{""" + _escape_latex(date_str) + r"""}
\author{自動生成 --- """ + _escape_latex(model or "local LLM") + r"""}
"""

    # ── 本文 ─────────────────────────────────────────────────────────
    body_parts = [
        r"\begin{document}",
        r"\maketitle",
        r"\thispagestyle{fancy}",
    ]

    # サマリー
    if summary_text:
        body_parts += [
            r"\section*{総合サマリー}",
            r"\begin{tcolorbox}[colback=teal!8!white, colframe=teal, boxrule=1pt, arc=4pt]",
            _escape_latex(summary_text),
            r"\end{tcolorbox}",
        ]

    # パラメータ表
    _PARAM_LABELS = {
        "trim_left_f":    r"trim-left-f（フォワード先頭トリム塩基数）",
        "trim_left_r":    r"trim-left-r（リバース先頭トリム塩基数）",
        "trunc_len_f":    r"trunc-len-f（フォワードトランケーション長）",
        "trunc_len_r":    r"trunc-len-r（リバーストランケーション長）",
        "sampling_depth": r"sampling-depth（多様性解析サンプリング深度）",
        "n_threads":      r"スレッド数",
    }
    rows = []
    if fastq_dir:
        rows.append(("FASTQディレクトリ", fastq_dir))
    if n_samples:
        rows.append(("サンプル数", f"{n_samples} サンプル（ペアエンド）"))
    for k, v in dada2_params.items():
        if v:
            rows.append((_PARAM_LABELS.get(k, k), str(v)))

    if rows:
        tbl = "\n".join(
            r"  " + _escape_latex(k) + r" & " + _escape_latex(str(v)) + r" \\"
            for k, v in rows
        )
        body_parts += [
            r"\section*{解析パラメータ}",
            r"\begin{center}",
            r"\begin{tabular}{>{\bfseries}p{0.45\linewidth}p{0.48\linewidth}}",
            r"\toprule",
            tbl,
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{center}",
        ]

    # 手法・ステップ
    all_steps = [("ok", s) for s in completed_steps] + [("fail", s) for s in failed_steps]
    if all_steps:
        items = []
        for kind, s in all_steps:
            text = _escape_latex(s.lstrip("✅⚠️❌ "))
            mark = r"\textcolor{red}{$\times$}" if kind == "fail" else r"\textcolor{teal}{$\checkmark$}"
            items.append(rf"  \item[{mark}] {text}")
        body_parts += [
            r"\section*{解析手法・パイプラインステップ}",
            r"\noindent\textbf{使用ソフトウェア}: QIIME2（DADA2 / MAFFT-FastTree / 多様性解析）+ Python（matplotlib, seaborn, pandas）\\[0.5em]",
            r"\begin{description}",
        ] + items + [r"\end{description}"]

    # 図セクション
    if fig_paths:
        body_parts.append(
            rf"\section*{{解析結果図（{len(fig_paths)} 件）}}"
        )
        # 2列レイアウト
        pairs = [fig_paths[i:i+2] for i in range(0, len(fig_paths), 2)]
        for pair in pairs:
            body_parts.append(r"\begin{figure}[H]")
            body_parts.append(r"  \centering")
            width = r"0.48\linewidth" if len(pair) == 2 else r"0.85\linewidth"
            for fp in pair:
                p = Path(fp)
                title = _escape_latex(_fig_title(str(fp)))
                interp_raw = interpretations.get(p.stem, "")
                interp = _escape_latex(interp_raw)
                # graphicx: パスに空白が含まれる場合はブレース内に
                safe_path = str(p).replace("\\", "/")
                caption_text = (
                    r"\textbf{" + title + r"}"
                    + (r"\\[0.2em] \small " + interp if interp else "")
                )
                body_parts += [
                    r"  \begin{minipage}{" + width + r"}",
                    r"    \centering",
                    r"    \includegraphics[width=\linewidth]{" + safe_path + r"}",
                    r"    \captionof{figure}{" + caption_text + r"}",
                    r"  \end{minipage}",
                ]
                if len(pair) == 2 and fp == pair[0]:
                    body_parts.append(r"  \hfill")
            body_parts.append(r"\end{figure}")
            body_parts.append("")

    body_parts.append(r"\end{document}")

    return preamble + title_block + "\n".join(body_parts) + "\n"


def generate_latex_report(
    fig_dir: str,
    output_dir: str,
    fastq_dir: str = "",
    n_samples: int = 0,
    dada2_params: Optional[dict] = None,
    completed_steps: Optional[list] = None,
    failed_steps: Optional[list] = None,
    export_files: Optional[dict] = None,
    user_prompt: str = "",
    model: str = "",
    log_callback: Optional[Callable] = None,
) -> str:
    """
    LaTeX レポートを生成して output_dir/report.tex を保存し、
    LaTeX エンジンが利用可能なら output_dir/report.pdf にコンパイルする。
    戻り値: PDF パス（コンパイル成功時）または TEX パス
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    dada2_params    = dada2_params    or {}
    completed_steps = completed_steps or []
    failed_steps    = failed_steps    or []

    # ── 図ファイル収集 ────────────────────────────────────────────────
    fig_dir_path = Path(fig_dir)
    fig_files = sorted(
        list(fig_dir_path.glob("*.jpg"))
        + list(fig_dir_path.glob("*.jpeg"))
        + list(fig_dir_path.glob("*.png")),
        key=lambda p: p.name,
    )

    # ── LLM 解釈生成 ─────────────────────────────────────────────────
    interpretations: dict = {}
    if model and fig_files:
        interpretations = _llm_interpretations(
            [str(f) for f in fig_files],
            user_prompt, model, n_samples, dada2_params, log_callback,
        )

    now = datetime.datetime.now()
    date_str = now.strftime("%Y年%m月%d日")

    # ── LaTeX エンジン検出 ────────────────────────────────────────────
    engine = _find_latex_engine()
    if engine:
        _log(f"📐 LaTeX エンジン検出: {engine}")
    else:
        _log("⚠️  lualatex / xelatex が見つかりません。.tex ファイルのみ保存します。")
        _log("   MacTeX のインストール: https://tug.org/mactex/")

    # ── .tex 生成 ─────────────────────────────────────────────────────
    summary_text = interpretations.get("SUMMARY", "")
    tex_content = _build_latex_doc(
        engine=engine,
        date_str=date_str,
        summary_text=summary_text,
        fastq_dir=fastq_dir,
        n_samples=n_samples,
        dada2_params=dada2_params,
        completed_steps=completed_steps,
        failed_steps=failed_steps,
        model=model,
        fig_paths=[str(f) for f in fig_files],
        interpretations=interpretations,
    )

    out_dir = Path(output_dir)
    tex_path = out_dir / "report.tex"
    tex_path.write_text(tex_content, encoding="utf-8")
    _log(f"📄 report.tex を保存しました: {tex_path}")

    if not engine:
        return str(tex_path)

    # ── PDF コンパイル（2 回実行で参照解決） ──────────────────────────
    pdf_path = out_dir / "report.pdf"
    compile_ok = False
    for pass_num in range(1, 3):
        _log(f"🔧 {engine} コンパイル中... ({pass_num}/2)")
        try:
            proc = subprocess.run(
                [
                    engine,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={out_dir}",
                    str(tex_path),
                ],
                capture_output=True,
                timeout=120,
                cwd=str(out_dir),
            )
            if proc.returncode != 0:
                # エラーログを表示（最後の 30 行）
                err_lines = proc.stdout.decode(errors="replace").splitlines()
                for ln in err_lines[-30:]:
                    if ln.strip():
                        _log(f"  [latex] {ln}")
                _log(f"❌ {engine} がエラーで終了しました (pass {pass_num})")
                break
            compile_ok = True
        except subprocess.TimeoutExpired:
            _log("❌ LaTeX コンパイルがタイムアウトしました（120秒）")
            break
        except FileNotFoundError:
            _log(f"❌ {engine} が見つかりません")
            break

    if compile_ok and pdf_path.exists():
        # 補助ファイルを削除
        for ext in (".aux", ".log", ".out", ".toc"):
            (out_dir / ("report" + ext)).unlink(missing_ok=True)
        _log(f"✅ PDF レポートを生成しました: {pdf_path}")
        return str(pdf_path)
    else:
        _log(f"⚠️  PDF 生成失敗。.tex ファイルを手動でコンパイルしてください: {tex_path}")
        return str(tex_path)
