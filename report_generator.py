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


# ─────────────────────────────────────────────────────────────────────────────
# 解析カテゴリ・手法情報（HTML レポート用）
# ─────────────────────────────────────────────────────────────────────────────

_ANALYSIS_CATEGORIES = [
    {
        "id": "qc",
        "title": "品質管理・シーケンス深度",
        "description": (
            "生シーケンスリードを DADA2 アルゴリズムでデノイジングし、"
            "シーケンスエラーを除去して正確な ASV (Amplicon Sequence Variant) を推定する。"
            "シーケンス深度とラレファクション解析により、サンプリングが群集多様性を"
            "十分に捉えているかを評価する。"
        ),
        "figures": ["fig01", "fig02", "fig12", "fig16", "fig18"],
        "methods": [
            {
                "name": "DADA2 Denoising",
                "equation": None,
                "description": (
                    "シーケンスランごとのエラー率をモデル化し、"
                    "ノイズリードから正確な ASV を推定するアルゴリズム。"
                    "品質フィルタリング、デノイジング、キメラ除去を統合的に行う。"
                ),
                "reveals": (
                    "各サンプルのデノイジング効率（入力リード数 vs 出力 ASV 数）、"
                    "キメラ除去率、全体的なデータ品質を評価できる。"
                ),
            },
            {
                "name": "Rarefaction Analysis",
                "equation": "E[S<sub>n</sub>] = S &minus; &Sigma;<sub>i</sub> C(N &minus; N<sub>i</sub>, n) / C(N, n)",
                "description": (
                    "リード数を段階的にサブサンプリングし、各深度での種数（ASV 数）を推定する。"
                    "曲線がプラトーに達すればサンプリングは十分と判断できる。"
                ),
                "reveals": (
                    "各サンプルのシーケンス深度が群集多様性を十分に捕捉しているか、"
                    "追加シーケンスが必要かを判断できる。"
                ),
            },
            {
                "name": "Rank-Abundance Curve",
                "equation": None,
                "description": (
                    "ASV を相対存在量の降順にランク付けしてプロットする。"
                    "曲線の傾きが群集の均等度を反映する。"
                ),
                "reveals": (
                    "群集が少数の優占種に支配されているか（急傾斜）、"
                    "均等に分布しているか（緩傾斜）を視覚的に評価できる。"
                ),
            },
        ],
    },
    {
        "id": "alpha",
        "title": "アルファ多様性",
        "description": (
            "アルファ多様性は個々のサンプル内の多様性を定量化する。"
            "種数（リッチネス）、分布の均等性（イーブンネス）、情報量（エントロピー）など、"
            "相補的な複数の指標で群集構造の異なる側面を捉える。"
        ),
        "figures": ["fig03", "fig04", "fig11", "fig28"],
        "methods": [
            {
                "name": "Shannon Entropy",
                "equation": "H&prime; = &minus;&Sigma;<sub>i=1</sub><sup>S</sup> p<sub>i</sub> ln(p<sub>i</sub>)",
                "description": (
                    "情報理論に基づく多様性指標。リッチネスとイーブンネスの両方を考慮する。"
                    "値が大きいほど多様性が高い。希少種に敏感。"
                ),
                "reveals": "群集全体の複雑さ。希少種の存在が指標値に大きく影響する。",
            },
            {
                "name": "Simpson's Diversity Index",
                "equation": "D = 1 &minus; &Sigma;<sub>i=1</sub><sup>S</sup> p<sub>i</sub><sup>2</sup>",
                "description": (
                    "ランダムに選んだ 2 個体が異なる種に属する確率。"
                    "0（多様性なし）から 1（無限多様性）の範囲をとる。"
                    "Shannon より優占種の影響を受けやすい。"
                ),
                "reveals": "群集の優占構造。優占種が存在するとき値が低下する。",
            },
            {
                "name": "Pielou's Evenness",
                "equation": "J = H&prime; / ln(S)",
                "description": (
                    "Shannon エントロピーを最大可能エントロピーで正規化した指標。"
                    "0（1 種が完全優占）から 1（完全均等分布）の範囲。"
                ),
                "reveals": "リッチネスに依存しない、種の分布均等性の評価。",
            },
            {
                "name": "Observed ASVs (Richness)",
                "equation": "S = |{ASV : count &gt; 0}|",
                "description": "各サンプルで検出された固有 ASV の単純カウント。",
                "reveals": "存在量分布を考慮しない、生の分類学的リッチネス。",
            },
        ],
    },
    {
        "id": "beta",
        "title": "ベータ多様性・オーディネーション",
        "description": (
            "ベータ多様性はサンプル間の組成的差異を定量化する。"
            "距離行列をオーディネーション手法で 2 次元に投影し、"
            "高次元の群集データを視覚的に解釈可能にする。"
        ),
        "figures": ["fig05", "fig06", "fig07", "fig08", "fig09", "fig17", "fig24"],
        "methods": [
            {
                "name": "Bray-Curtis Dissimilarity",
                "equation": "BC<sub>jk</sub> = 1 &minus; 2&Sigma; min(x<sub>ij</sub>, x<sub>ik</sub>) / &Sigma;(x<sub>ij</sub> + x<sub>ik</sub>)",
                "description": (
                    "存在量ベースの非類似度指標。共有種の存在量に重みを置く。"
                    "0（完全一致）から 1（共有種なし）の範囲。"
                ),
                "reveals": "種の存在量を重視したサンプル間の組成的類似性。",
            },
            {
                "name": "Jaccard Distance",
                "equation": "J<sub>jk</sub> = 1 &minus; |A &cap; B| / |A &cup; B|",
                "description": (
                    "在/不在データに基づく非類似度指標。"
                    "存在量を考慮せず、共有種の有無のみで評価する。"
                ),
                "reveals": "存在量に依存しない、種の共有パターン。",
            },
            {
                "name": "UniFrac Distance",
                "equation": "UF<sub>w</sub> = &Sigma;<sub>i</sub> b<sub>i</sub> |p<sub>iA</sub> &minus; p<sub>iB</sub>| / &Sigma;<sub>i</sub> b<sub>i</sub>",
                "description": (
                    "系統樹上の枝長を利用した系統学的距離。"
                    "Unweighted は在/不在、Weighted は存在量も考慮する。"
                ),
                "reveals": "分類学的手法では捉えられない、進化的関係に基づく群集間差異。",
            },
            {
                "name": "PCoA (Principal Coordinates Analysis)",
                "equation": "maximize: &Sigma; &lambda;<sub>k</sub> / &Sigma; &lambda;<sub>i</sub>  (first k axes)",
                "description": (
                    "距離行列の固有値分解により、ペアワイズ距離の分散を"
                    "最大限説明する軸を求める。各軸の分散説明率 (%) が有効性を示す。"
                ),
                "reveals": "群集変動の主要な軸とサンプルのクラスタリングパターン。",
            },
            {
                "name": "NMDS (Non-metric MDS)",
                "equation": "minimize: stress = &radic;(&Sigma;(d<sub>ij</sub> &minus; &delta;<sub>ij</sub>)&sup2; / &Sigma; d<sub>ij</sub>&sup2;)",
                "description": (
                    "距離の順位関係を保存する反復的オーディネーション。"
                    "Stress &lt; 0.1 で良好なフィット、&lt; 0.05 で優秀。"
                ),
                "reveals": "PCoA では捉えにくい非線形的な群集構造。",
            },
            {
                "name": "UPGMA Dendrogram",
                "equation": "d<sub>UV</sub> = (d<sub>US</sub> + d<sub>VS</sub>) / 2",
                "description": (
                    "平均連結法による階層的クラスタリング。"
                    "距離行列からサンプルの階層的類似関係を構築する。"
                ),
                "reveals": "サンプル間の階層的グループ構造と自然なクラスタリング。",
            },
        ],
    },
    {
        "id": "taxonomy",
        "title": "分類学的組成",
        "description": (
            "参照データベース (SILVA, Greengenes2) を用いた Naive Bayes 分類器で "
            "ASV に分類学的帰属（門 → 綱 → 目 → 科 → 属）を付与する。"
            "各分類階級での相対存在量プロファイルが群集構造を明らかにする。"
        ),
        "figures": ["fig14", "fig26", "fig27", "fig21", "fig13", "fig15", "fig10", "fig19"],
        "methods": [
            {
                "name": "Relative Abundance",
                "equation": "RA<sub>i</sub> = count<sub>i</sub> / &Sigma;<sub>j</sub> count<sub>j</sub> &times; 100%",
                "description": (
                    "各分類群のリード数をサンプル総リード数で割った割合。"
                    "門・綱・目・科・属の各階級で算出し、群集構造を多角的に把握する。"
                ),
                "reveals": "各サンプルの優占分類群と、サンプル間の組成的差異。",
            },
            {
                "name": "Naive Bayes Classifier",
                "equation": "P(taxon|seq) &prop; P(seq|taxon) &middot; P(taxon)",
                "description": (
                    "QIIME2 feature-classifier による ASV の分類学的帰属。"
                    "参照データベース上で学習した k-mer 頻度分布から事後確率を計算する。"
                ),
                "reveals": "検出された配列変異体の生物学的同定（門から属レベルまで）。",
            },
        ],
    },
    {
        "id": "statistical",
        "title": "生態学的・統計学的解析",
        "description": (
            "コア群集の同定、分類群間相関、差次的存在量解析、"
            "サンプル間共有 ASV パターンなど、高度な統計手法で"
            "群集の生態学的特徴を明らかにする。"
        ),
        "figures": ["fig22", "fig20", "fig23", "fig25", "fig29"],
        "methods": [
            {
                "name": "Core Microbiome Analysis",
                "equation": "Core = {taxon : prevalence &ge; threshold}",
                "description": (
                    "定義した閾値（例: 80%）以上のサンプルに出現する分類群を同定する。"
                    "サンプル横断的に安定して存在する群集メンバーを特定する。"
                ),
                "reveals": "生態学的ベースラインを形成する安定した群集構成員。",
            },
            {
                "name": "Co-occurrence Network",
                "equation": "&rho;<sub>ij</sub> = cov(x<sub>i</sub>, x<sub>j</sub>) / (&sigma;<sub>i</sub> &sigma;<sub>j</sub>),&ensp; |&rho;| &gt; threshold",
                "description": (
                    "分類群をノード、有意な存在量相関をエッジとするネットワーク。"
                    "正の相関は共生・ニッチ共有、負の相関は競合を示唆する。"
                ),
                "reveals": "分類群間の潜在的な生態学的相互作用パターン。",
            },
            {
                "name": "Differential Abundance (Volcano Plot)",
                "equation": "t<sub>i</sub> = (x&#772;<sub>A</sub> &minus; x&#772;<sub>B</sub>) / SE<sub>pooled</sub>,&ensp; q = BH-adjusted p",
                "description": (
                    "各分類群のグループ間存在量差を検定し、"
                    "Benjamini-Hochberg 法で多重検定補正を行う (FDR q &lt; 0.05)。"
                ),
                "reveals": "条件間で有意に増減する分類群（バイオマーカー候補）。",
            },
            {
                "name": "Spearman Rank Correlation",
                "equation": "&rho;<sub>s</sub> = 1 &minus; 6&Sigma; d<sub>i</sub>&sup2; / n(n&sup2; &minus; 1)",
                "description": (
                    "分類群間の存在量のノンパラメトリック順位相関。"
                    "階層的クラスタリングで相関パターンをヒートマップ表示する。"
                ),
                "reveals": "共存在量パターンと、潜在的な機能的ギルドの同定。",
            },
            {
                "name": "ASV Overlap Analysis",
                "equation": "|S<sub>A</sub> &cap; S<sub>B</sub> &cap; &hellip;| for all combinations",
                "description": (
                    "サンプル間で共有される ASV の集合論的解析。"
                    "UpSet プロット形式で組み合わせごとの共有・固有 ASV 数を表示する。"
                ),
                "reveals": "サンプル固有 vs 共通 ASV の分布、コア群集のパターン。",
            },
        ],
    },
]


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
:root {
  --c-text: #1e293b;
  --c-muted: #64748b;
  --c-bg: #f8fafc;
  --c-card: #ffffff;
  --c-border: #e2e8f0;
  --c-accent: #2563eb;
  --c-accent-bg: #eff6ff;
  --c-heading: #0f172a;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Hiragino Sans', 'Noto Sans JP', sans-serif;
  background: var(--c-bg); color: var(--c-text); line-height: 1.75; font-size: 15px;
}
header {
  background: var(--c-heading); color: #fff; padding: 2.8rem 2rem; text-align: center;
}
header h1 { font-size: 1.5rem; font-weight: 600; letter-spacing: 0.02em; }
header .sub { color: rgba(255,255,255,0.5); font-size: 0.85rem; margin-top: 0.4rem; }
.container { max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; }
nav.toc {
  background: var(--c-card); border: 1px solid var(--c-border);
  border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1.5rem;
}
nav.toc h2 {
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--c-muted); margin-bottom: 0.6rem;
}
nav.toc ol { padding-left: 1.4rem; columns: 2; column-gap: 2rem; }
nav.toc li { font-size: 0.88rem; padding: 0.15rem 0; break-inside: avoid; }
nav.toc a { color: var(--c-accent); text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
.section {
  background: var(--c-card); border: 1px solid var(--c-border);
  border-radius: 8px; padding: 1.8rem 2rem; margin-bottom: 1.5rem;
}
.section-title {
  font-size: 1.15rem; font-weight: 600; color: var(--c-heading);
  padding-bottom: 0.5rem; border-bottom: 2px solid var(--c-border); margin-bottom: 1rem;
}
.section-desc {
  font-size: 0.9rem; color: var(--c-muted); margin-bottom: 1.4rem; line-height: 1.7;
}
.summary-box {
  background: var(--c-accent-bg); border-left: 3px solid var(--c-accent);
  padding: 0.9rem 1.1rem; border-radius: 0 6px 6px 0; font-size: 0.93rem;
}
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.55rem 0.8rem; border-bottom: 1px solid var(--c-border); }
th { background: var(--c-bg); font-weight: 600; width: 40%; }
.methods-grid { display: grid; gap: 0.8rem; margin-bottom: 1.5rem; }
.method-item {
  border: 1px solid var(--c-border); border-radius: 6px;
  padding: 1rem 1.2rem; background: var(--c-bg);
}
.method-item h4 { font-size: 0.92rem; font-weight: 600; color: var(--c-heading); margin-bottom: 0.4rem; }
.eq {
  font-family: Georgia, 'Times New Roman', serif; font-size: 1rem;
  color: var(--c-accent); background: var(--c-card);
  border: 1px solid var(--c-border); border-radius: 4px;
  padding: 0.4rem 0.7rem; margin: 0.4rem 0; display: inline-block; line-height: 1.6;
}
.method-desc { font-size: 0.86rem; color: var(--c-text); margin-bottom: 0.25rem; line-height: 1.65; }
.method-reveals { font-size: 0.84rem; color: var(--c-muted); }
.method-reveals strong { color: var(--c-text); }
.fig-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr)); gap: 1rem;
}
.fig-card {
  border: 1px solid var(--c-border); border-radius: 6px;
  overflow: hidden; background: var(--c-card);
}
.fig-card img { width: 100%; height: auto; display: block; }
.fig-caption { padding: 0.7rem 0.9rem; }
.fig-caption strong { display: block; font-size: 0.9rem; color: var(--c-heading); margin-bottom: 0.15rem; }
.fig-caption p { font-size: 0.83rem; color: var(--c-muted); }
.step-list { list-style: none; padding: 0; }
.step-list li {
  padding: 0.3rem 0; font-size: 0.88rem; display: flex; align-items: center; gap: 0.5rem;
}
.dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.dot-ok { background: #16a34a; }
.dot-fail { background: #dc2626; }
.dot-warn { background: #d97706; }
footer { text-align: center; padding: 2rem; font-size: 0.8rem; color: var(--c-muted); }
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>seq2pipe Analysis Report — {date}</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>seq2pipe Analysis Report</h1>
  <p class="sub">{datetime_str} | 16S rRNA Amplicon Sequencing</p>
</header>
<div class="container">
{toc_section}
{summary_section}
{params_section}
{steps_section}
{analysis_sections}
</div>
<footer>Generated by seq2pipe | QIIME2 + {model}</footer>
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
    datetime_str = now.strftime("%Y-%m-%d %H:%M")

    # ── サマリーセクション ────────────────────────────────────────────
    summary_text = interpretations.get("SUMMARY", "")
    if summary_text:
        summary_section = (
            '<div class="section" id="summary">'
            '<h2 class="section-title">Summary</h2>'
            f'<div class="summary-box">{summary_text}</div>'
            '</div>'
        )
    else:
        summary_section = ""

    # ── パラメータセクション ──────────────────────────────────────────
    _PARAM_LABELS = {
        "trim_left_f":    "trim-left-f (forward trim bases)",
        "trim_left_r":    "trim-left-r (reverse trim bases)",
        "trunc_len_f":    "trunc-len-f (forward truncation length)",
        "trunc_len_r":    "trunc-len-r (reverse truncation length)",
        "sampling_depth": "sampling-depth (diversity analysis depth)",
        "n_threads":      "Threads",
        "read_len_f":     "Forward read length",
        "read_len_r":     "Reverse read length",
    }
    rows = ""
    if fastq_dir:
        rows += f"<tr><th>FASTQ directory</th><td>{fastq_dir}</td></tr>"
    if n_samples:
        rows += f"<tr><th>Samples</th><td>{n_samples} (paired-end)</td></tr>"
    for k, v in dada2_params.items():
        label = _PARAM_LABELS.get(k, k)
        if v:
            rows += f"<tr><th>{label}</th><td>{v}</td></tr>"
    if rows:
        params_section = (
            '<div class="section" id="params">'
            '<h2 class="section-title">Parameters</h2>'
            f'<table><tbody>{rows}</tbody></table>'
            '</div>'
        )
    else:
        params_section = ""

    # ── パイプラインステップセクション ─────────────────────────────────
    step_items = ""
    for s in completed_steps:
        text = s.lstrip("\u2705\u26a0\ufe0f\u274c ")
        dot_cls = "dot-warn" if "\u26a0" in s else "dot-ok"
        step_items += f'<li><span class="dot {dot_cls}"></span>{text}</li>'
    for s in failed_steps:
        text = s.lstrip("\u274c ")
        step_items += f'<li><span class="dot dot-fail"></span>{text}</li>'

    if step_items:
        steps_section = (
            '<div class="section" id="steps">'
            '<h2 class="section-title">Pipeline Steps</h2>'
            '<p class="section-desc">'
            'QIIME2 (DADA2 denoising / MAFFT-FastTree phylogeny / diversity) + '
            'Python (matplotlib, seaborn, pandas, scipy, scikit-learn)'
            '</p>'
            f'<ul class="step-list">{step_items}</ul>'
            '</div>'
        )
    else:
        steps_section = ""

    # ── カテゴリ別解析セクション（手法 + 図） ─────────────────────────
    analysis_html = ""
    categorized = set()

    for cat in _ANALYSIS_CATEGORIES:
        cat_figs = []
        for prefix in cat["figures"]:
            for fp in fig_files:
                if fp.stem.startswith(prefix):
                    cat_figs.append(fp)
                    categorized.add(fp.stem)

        if not cat_figs:
            continue

        # 手法カード
        methods_html = ""
        for m in cat["methods"]:
            eq_html = ""
            if m.get("equation"):
                eq_html = f'<div class="eq">{m["equation"]}</div>'
            methods_html += (
                '<div class="method-item">'
                f'<h4>{m["name"]}</h4>'
                f'{eq_html}'
                f'<p class="method-desc">{m["description"]}</p>'
                f'<p class="method-reveals"><strong>知見:</strong> {m["reveals"]}</p>'
                '</div>'
            )

        # 図カード
        fig_html = ""
        for fp in cat_figs:
            title = _fig_title(str(fp))
            interp = interpretations.get(fp.stem, "")
            try:
                data_uri = _encode_image(str(fp))
            except Exception:
                continue
            caption_p = f"<p>{interp}</p>" if interp else ""
            fig_html += (
                '<div class="fig-card">'
                f'<img src="{data_uri}" alt="{title}" loading="lazy">'
                '<div class="fig-caption">'
                f'<strong>{title}</strong>'
                f'{caption_p}'
                '</div></div>'
            )

        analysis_html += (
            f'<div class="section" id="{cat["id"]}">'
            f'<h2 class="section-title">{cat["title"]}</h2>'
            f'<p class="section-desc">{cat["description"]}</p>'
            f'<div class="methods-grid">{methods_html}</div>'
            f'<div class="fig-grid">{fig_html}</div>'
            '</div>'
        )

    # ── 未分類図（adaptive / カスタム） ───────────────────────────────
    remaining = [fp for fp in fig_files if fp.stem not in categorized]
    if remaining:
        fig_html = ""
        for fp in remaining:
            title = _fig_title(str(fp))
            interp = interpretations.get(fp.stem, "")
            try:
                data_uri = _encode_image(str(fp))
            except Exception:
                continue
            caption_p = f"<p>{interp}</p>" if interp else ""
            fig_html += (
                '<div class="fig-card">'
                f'<img src="{data_uri}" alt="{title}" loading="lazy">'
                '<div class="fig-caption">'
                f'<strong>{title}</strong>'
                f'{caption_p}'
                '</div></div>'
            )
        analysis_html += (
            '<div class="section" id="additional">'
            '<h2 class="section-title">Adaptive Analysis</h2>'
            '<p class="section-desc">'
            'LLM エージェントがデータの特徴を分析し、自動生成した追加可視化。'
            '</p>'
            f'<div class="fig-grid">{fig_html}</div>'
            '</div>'
        )

    # ── 目次 ──────────────────────────────────────────────────────────
    toc_items = ""
    if summary_text:
        toc_items += '<li><a href="#summary">Summary</a></li>'
    if rows:
        toc_items += '<li><a href="#params">Parameters</a></li>'
    if step_items:
        toc_items += '<li><a href="#steps">Pipeline Steps</a></li>'
    for cat in _ANALYSIS_CATEGORIES:
        has_figs = any(
            fp.stem.startswith(prefix)
            for prefix in cat["figures"]
            for fp in fig_files
        )
        if has_figs:
            toc_items += f'<li><a href="#{cat["id"]}">{cat["title"]}</a></li>'
    if remaining:
        toc_items += '<li><a href="#additional">Adaptive Analysis</a></li>'

    toc_section = (
        '<nav class="toc">'
        '<h2>Contents</h2>'
        f'<ol>{toc_items}</ol>'
        '</nav>'
    ) if toc_items else ""

    # ── HTML 組み立て・保存 ───────────────────────────────────────────
    html = _HTML_TEMPLATE.format(
        css=_CSS,
        date=date_str,
        datetime_str=datetime_str,
        toc_section=toc_section,
        summary_section=summary_section,
        params_section=params_section,
        steps_section=steps_section,
        analysis_sections=analysis_html,
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
