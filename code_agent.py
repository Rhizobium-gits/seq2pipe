#!/usr/bin/env python3
"""
code_agent.py
=============
LLM に Python 解析コードを生成させ、実行・エラー修正・パッケージ
インストール確認を行うモジュール。
"""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent


# ─────────────────────────────────────────────────────────────────────────────
# 結果オブジェクト
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CodeExecutionResult:
    """コード生成・実行の結果"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    code: str = ""
    figures: list = field(default_factory=list)
    retry_count: int = 0
    error_message: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# プロンプト構築
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(
    export_files: dict,
    user_prompt: str,
    figure_dir: str,
    metadata_path: str = "",
    plot_config: Optional[dict] = None,
) -> str:
    """LLM へのコード生成プロンプトを組み立てる"""
    cfg = plot_config or {}
    dpi     = cfg.get("dpi", 150)
    figsize = cfg.get("figsize", [10, 6])

    lines = [
        "You are a microbiome bioinformatics expert.",
        "Write a single, complete, self-contained Python script that analyzes and visualizes",
        "the QIIME2-exported data listed below.",
        "",
        "## Available files",
    ]
    for category, paths in export_files.items():
        for p in paths:
            lines.append(f"  [{category}] {p}")
    if metadata_path:
        lines.append(f"  [metadata] {metadata_path}")

    lines += [
        "",
        f"## Output directory for figures: {figure_dir}",
        f"## DPI: {dpi}",
        f"## figsize: {figsize}",
        "",
        "## User request",
        user_prompt.strip() or (
            "Generate: (1) genus-level stacked bar chart of relative abundance, "
            "(2) alpha diversity boxplot (Shannon), (3) beta diversity PCoA (Bray-Curtis)."
        ),
        "",
        "## FILE FORMAT — read exactly as described",
        "",
        "### [feature_table] TSV  (exported from QIIME2 via biom convert)",
        "  - First line  : '# Constructed from biom file'  ← comment, skip it",
        "  - Second line : '#OTU ID\\t<sample1>\\t<sample2>...'  ← use as header",
        "  - Remaining   : Feature ID (ASV/OTU) | per-sample read counts",
        "  - Read with   :",
        "      ft = pd.read_csv(path, sep='\\t', skiprows=1, index_col=0)",
        "      ft.index.name = 'Feature ID'",
        "",
        "### [taxonomy] taxonomy.tsv",
        "  - Columns: Feature ID (index) | Taxon | Confidence",
        "  - Taxon format: 'd__Bacteria; p__Firmicutes; c__Clostridia; o__...; f__...; g__Genus; s__species'",
        "  - Read with   : tax = pd.read_csv(path, sep='\\t', index_col=0)",
        "  - Get genus   : tax['genus'] = tax['Taxon'].str.extract(r'g__([^;]+)').fillna('Unknown').str.strip()",
        "",
        "### [alpha] alpha-diversity TSV",
        "  - Columns: sample-id (index) | metric value (shannon / observed_features / faith_pd ...)",
        "  - Read with   : alpha = pd.read_csv(path, sep='\\t', index_col=0)",
        "",
        "### [beta] distance-matrix TSV",
        "  - Square symmetric matrix; row names = column names = sample IDs",
        "  - Read with   : dm = pd.read_csv(path, sep='\\t', index_col=0)",
        "  - PCoA with sklearn :",
        "      from sklearn.manifold import MDS",
        "      coords = MDS(n_components=2, dissimilarity='precomputed', random_state=42).fit_transform(dm.values)",
        "",
        "## Code requirements",
        "1. First two lines MUST be:",
        "      import matplotlib",
        "      matplotlib.use('Agg')",
        "2. Define at the top:",
        f"      FIGURE_DIR = r'{figure_dir}'",
        f"      DPI = {dpi}",
        "      import os; os.makedirs(FIGURE_DIR, exist_ok=True)",
        "3. Save every figure:",
        "      plt.savefig(os.path.join(FIGURE_DIR, 'name.png'), dpi=DPI, bbox_inches='tight')",
        "      plt.close()",
        "4. All axis labels, titles, legend entries in English.",
        "5. Use try/except around each section so one failure does not stop the whole script.",
        "6. Output ONLY the Python code, wrapped in ```python ... ```.",
        "7. Do NOT use plt.show().",
        "",
        "## COMMON MISTAKES — avoid these",
        "- DO NOT: from scipy.stats import boxplot  ← scipy.stats has NO boxplot function",
        "  CORRECT: plt.boxplot(data)  or  seaborn.boxplot(data=df, ...)",
        "- DO NOT: import biom  ← use pd.read_csv() directly on .tsv files",
        "- DO NOT hardcode data values — always read from the file paths listed above",
        "- TAXONOMY str.extract RETURNS DataFrame, not Series:",
        "  WRONG: tax['Taxon'].str.extract(r'g__([^;]+)').fillna('Unknown').str.strip()",
        "  RIGHT: tax['Taxon'].str.extract(r'g__([^;]+)')[0].fillna('Unknown').str.strip()",
        "- DO NOT use bare 'except Exception as e: print(...)' — it hides real errors.",
        "  Instead: let errors propagate (no try/except) or use 'raise' inside except.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# マニフェスト用プロンプト構築
# ─────────────────────────────────────────────────────────────────────────────

def _build_manifest_prompt(
    manifest_path: str,
    user_prompt: str,
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    plot_config: Optional[dict] = None,
) -> str:
    """マニフェストファイルからフルパイプラインを実行するプロンプトを構築"""
    import csv

    # マニフェストを読んでサンプル数・構造を確認
    samples = []
    try:
        with open(manifest_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                sid = row.get("sample-id") or row.get("sampleid") or ""
                if sid:
                    samples.append(sid)
    except Exception:
        pass

    qiime_bin = (
        str(Path(_agent.QIIME2_CONDA_BIN) / "qiime")
        if _agent.QIIME2_CONDA_BIN and Path(_agent.QIIME2_CONDA_BIN).exists()
        else "qiime"
    )
    biom_bin = (
        str(Path(_agent.QIIME2_CONDA_BIN) / "biom")
        if _agent.QIIME2_CONDA_BIN and Path(_agent.QIIME2_CONDA_BIN).exists()
        else "biom"
    )

    cfg = plot_config or {}
    sample_preview = ", ".join(samples[:5]) + ("..." if len(samples) > 5 else "")

    lines = [
        "あなたはQIIME2とPythonを使ったマイクロバイオーム解析の専門家です。",
        "以下のマニフェストファイルからQIIME2パイプラインを実行し、",
        "解析・可視化まで行う完全なPythonスクリプトを1つ書いてください。",
        "",
        "## QIIME2 実行環境",
        f"qiime コマンド: {qiime_bin}",
        f"biom コマンド: {biom_bin}",
        "",
        "## マニフェストファイル",
        f"パス: {manifest_path}",
        "形式: PairedEndFastqManifestPhred33V2（タブ区切り、ヘッダ: sample-id / forward-absolute-filepath / reverse-absolute-filepath）",
        f"サンプル数: {len(samples)}",
        f"サンプルID例: {sample_preview}",
        "",
    ]

    if metadata_path:
        lines += [
            "## メタデータファイル",
            f"パス: {metadata_path}",
            "(sample-id 列とグループ情報を含む TSV)",
            "",
        ]

    lines += [
        f"## 出力先ディレクトリ: {output_dir}",
        f"## 図の保存先ディレクトリ: {figure_dir}",
        f"## DPI: {cfg.get('dpi', 150)}",
        f"## figsize: {cfg.get('figsize', [10, 6])}",
        "",
        "## ユーザーの要求",
        user_prompt if user_prompt.strip() else (
            "属レベル相対存在量の積み上げ棒グラフ、Shannon α多様性、Bray-Curtis PCoA を生成してください。"
        ),
        "",
        "## コードの要件",
        "- import matplotlib; matplotlib.use('Agg') を最初に書く",
        "- QIIME2 コマンドは subprocess.run([qiime_cmd, ...], check=True, capture_output=True, text=True) で実行する",
        "  例: result = subprocess.run(['/path/to/qiime', 'tools', 'import', ...], check=True, capture_output=True, text=True)",
        "- 各ステップの returncode != 0 のとき stderr を表示して sys.exit(1) で停止する",
        "- 図は plt.savefig() で保存し plt.show() は使わない",
        "- タイトル・ラベルは英語で書く（日本語フォント依存を避けるため）",
        "- コードのみを出力する。説明文は不要",
        "- コードは ```python ... ``` で囲む",
        "",
        "## QIIME2パイプラインの推奨フロー",
        "1. qiime tools import でマニフェストからインポート",
        "   --type 'SampleData[PairedEndSequencesWithQuality]'",
        "   --input-format PairedEndFastqManifestPhred33V2",
        "2. qiime dada2 denoise-paired でデノイジング",
        "   推奨: --p-trim-left-f 0 --p-trim-left-r 0 --p-trunc-len-f 250 --p-trunc-len-r 200 --p-n-threads 0",
        "3. qiime taxa collapse --p-level 6 で属レベルに集約",
        "4. qiime tools export で feature-table.biom をエクスポート",
        "5. biom convert -i feature-table.biom -o feature-table.tsv --to-tsv でTSVに変換",
        "6. pandasでTSVを読み込んで相対存在量を計算・matplotlib で可視化",
        "7. 多様性解析が必要な場合は qiime diversity core-metrics-phylogenetic などを使用",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# コード抽出
# ─────────────────────────────────────────────────────────────────────────────

def _extract_code(content: str) -> str:
    """LLM レスポンスから Python コードブロックを抽出する"""
    # ```python ... ``` または ``` ... ```
    match = re.search(r'```(?:python)?\s*([\s\S]*?)```', content)
    if match:
        return match.group(1).strip()
    # フォールバック: import から始まる行以降
    for i, line in enumerate(content.splitlines()):
        if line.strip().startswith(("import ", "from ")):
            return "\n".join(content.splitlines()[i:]).strip()
    return content.strip()


# ─────────────────────────────────────────────────────────────────────────────
# コード実行
# ─────────────────────────────────────────────────────────────────────────────

def _run_code(
    code: str,
    output_dir: str,
    figure_dir: str,
    log_callback: Optional[Callable[[str], None]] = None,
) -> tuple:
    """
    コードを一時ファイルに書き込んで QIIME2_PYTHON で実行する。
    戻り値: (success: bool, stdout: str, stderr: str, new_figures: list[str])
    """
    py_exec = _agent.QIIME2_PYTHON
    if not py_exec or not Path(py_exec).exists():
        py_exec = sys.executable

    fig_dir = Path(figure_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)

    # 実行前の図ファイル一覧
    existing = set(fig_dir.glob("*.png")) | set(fig_dir.glob("*.pdf")) | set(fig_dir.glob("*.svg"))

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, encoding='utf-8'
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        proc = subprocess.run(
            [py_exec, tmp_path],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=output_dir,
        )

        if log_callback:
            for line in proc.stdout.splitlines():
                log_callback(line)
            if proc.stderr:
                for line in proc.stderr.splitlines()[:20]:
                    log_callback(f"[stderr] {line}")

        new_figs = sorted(
            (set(fig_dir.glob("*.png")) | set(fig_dir.glob("*.pdf")) | set(fig_dir.glob("*.svg")))
            - existing
        )
        return (
            proc.returncode == 0,
            proc.stdout,
            proc.stderr,
            [str(f) for f in new_figs],
        )
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ModuleNotFoundError 検出
# ─────────────────────────────────────────────────────────────────────────────

_PIP_NAME_MAP = {
    "sklearn": "scikit-learn",
    "skbio":   "scikit-bio",
    "Bio":     "biopython",
    "cv2":     "opencv-python",
    "PIL":     "Pillow",
}

def _detect_missing_module(stderr: str) -> Optional[str]:
    """stderr から ModuleNotFoundError のパッケージ名を抽出する"""
    match = re.search(r"No module named '([^']+)'", stderr)
    if match:
        mod = match.group(1).split(".")[0]
        return _PIP_NAME_MAP.get(mod, mod)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# pip インストール
# ─────────────────────────────────────────────────────────────────────────────

def pip_install(
    package: str,
    log_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """QIIME2 conda 環境の pip でパッケージをインストールする"""
    conda_bin = _agent.QIIME2_CONDA_BIN
    if conda_bin and Path(conda_bin).exists():
        pip_exec = str(Path(conda_bin) / "pip")
    else:
        pip_exec = str(Path(sys.executable).parent / "pip")

    if log_callback:
        log_callback(f"[pip] インストール中: {package}")

    proc = subprocess.run(
        [pip_exec, "install", package],
        capture_output=True, text=True, timeout=180,
    )
    if log_callback:
        for line in proc.stdout.splitlines()[-3:]:
            log_callback(f"[pip] {line}")
        if proc.returncode != 0:
            for line in proc.stderr.splitlines()[-5:]:
                log_callback(f"[pip error] {line}")
    return proc.returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# メインエントリポイント
# ─────────────────────────────────────────────────────────────────────────────

def run_code_agent(
    export_files: dict,
    user_prompt: str,
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_retries: int = 3,
    plot_config: Optional[dict] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> CodeExecutionResult:
    """
    LLM で Python 解析コードを生成・実行するエージェント。

    Parameters
    ----------
    export_files : dict
        pipeline_runner.get_exported_files() の戻り値
    user_prompt : str
        ユーザーの解析指示（自然言語）
    output_dir : str
        作業ディレクトリ
    figure_dir : str
        図の保存先
    model : str, optional
        Ollama モデル名（None なら DEFAULT_MODEL）
    max_retries : int
        エラー時の最大リトライ回数（デフォルト 3）
    install_callback : (pkg: str) -> bool, optional
        パッケージインストール許可を求めるコールバック。
        True を返すとインストール実行。
        None の場合はインストールしない。
    """
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    _log("LLM にコード生成を依頼中...")

    # ── STEP 1: 初回コード生成 ────────────────────────────────────────
    system_msg = {
        "role": "system",
        "content": (
            "You are a microbiome analysis expert. "
            "Generate only Python code without any explanation. "
            "Wrap code in ```python ... ```."
        ),
    }
    user_msg = {
        "role": "user",
        "content": _build_prompt(
            export_files, user_prompt, figure_dir, metadata_path, plot_config
        ),
    }
    messages = [system_msg, user_msg]

    try:
        response = _agent.call_ollama(messages, model)
    except Exception as e:
        return CodeExecutionResult(
            success=False,
            error_message=f"Ollama 接続エラー: {e}",
        )

    code = _extract_code(response.get("content", ""))
    if not code:
        return CodeExecutionResult(
            success=False,
            error_message="LLM がコードを生成しませんでした",
        )
    _log(f"コード生成完了 ({len(code.splitlines())} 行)")

    # ── STEP 2: 実行 + リトライループ ────────────────────────────────
    last_code = code
    last_stderr = ""

    for attempt in range(max_retries + 1):
        _log(f"コード実行中... (試行 {attempt + 1}/{max_retries + 1})")

        success, stdout, stderr, new_figs = _run_code(
            last_code, output_dir, figure_dir, log_callback
        )

        if success and new_figs:
            _log(f"実行成功。生成された図: {len(new_figs)} 件")
            return CodeExecutionResult(
                success=True,
                stdout=stdout,
                stderr=stderr,
                code=last_code,
                figures=new_figs,
                retry_count=attempt,
            )

        if success and not new_figs:
            # exit 0 だが図が生成されていない → try/except による silent failure を疑う
            _log("⚠️  exit 0 だが図が未生成。サイレントエラーとして再試行します。")
            last_stderr = (
                "Script exited with code 0 but NO figures were saved to FIGURE_DIR.\n"
                "This usually means an error was silently caught by a try/except block.\n"
                f"Script stdout (look for 'Error:' lines):\n{stdout[:800]}\n\n"
                "Fix: remove broad except clauses (or re-raise), and ensure "
                "plt.savefig() is actually executed with the correct FIGURE_DIR path."
            )
        else:
            last_stderr = stderr

        # ModuleNotFoundError の処理
        missing_pkg = _detect_missing_module(stderr)
        if missing_pkg:
            _log(f"未インストールパッケージを検出: {missing_pkg}")
            approved = install_callback(missing_pkg) if install_callback else False
            if approved:
                ok = pip_install(missing_pkg, log_callback)
                if ok:
                    _log(f"{missing_pkg} のインストール完了。再実行します。")
                    continue   # 同じコードで再実行（コード修正不要）
            else:
                _log(f"{missing_pkg} のインストールをスキップしました。")

        if attempt >= max_retries:
            break

        # LLM にエラーを渡してコード修正を依頼
        _log(f"エラーを LLM に渡してコード修正を依頼中...")
        messages.append({
            "role": "assistant",
            "content": f"```python\n{last_code}\n```",
        })
        messages.append({
            "role": "user",
            "content": (
                f"The code produced the following error:\n"
                f"```\n{stderr[:1500]}\n```\n\n"
                f"Please fix the code and output the complete corrected version "
                f"wrapped in ```python ... ```."
            ),
        })

        try:
            fix_response = _agent.call_ollama(messages, model)
        except Exception as e:
            _log(f"Ollama 接続エラー: {e}")
            break

        fixed = _extract_code(fix_response.get("content", ""))
        if fixed:
            last_code = fixed
            _log(f"修正済みコード受信 ({len(last_code.splitlines())} 行)")
        else:
            _log("コード修正に失敗しました。")
            break

    return CodeExecutionResult(
        success=False,
        stdout="",
        stderr=last_stderr,
        code=last_code,
        figures=[],
        retry_count=max_retries,
        error_message=last_stderr[:500],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 自律エージェント（Auto Agent）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AutoAgentResult:
    """自律エージェントの実行結果"""
    rounds: list = field(default_factory=list)       # list[CodeExecutionResult]
    total_figures: list = field(default_factory=list)
    completed: bool = False                           # ANALYSIS_COMPLETE を受信したか


def _build_auto_initial_prompt(
    export_files: dict,
    figure_dir: str,
    metadata_path: str = "",
    plot_config: Optional[dict] = None,
) -> str:
    """自律エージェント用の初回プロンプト（ユーザー指示なし・AI が計画立案）"""
    cfg     = plot_config or {}
    dpi     = cfg.get("dpi", 150)
    figsize = cfg.get("figsize", [10, 6])

    lines = [
        "You are an autonomous microbiome bioinformatics analysis agent.",
        "Analyze the QIIME2-exported data listed below, one analysis per round.",
        "",
        "## PROTOCOL",
        "- Each response: write EXACTLY ONE complete Python script in ```python ... ```.",
        "- After the script runs you receive the result and plan the next analysis.",
        "- When you have completed a comprehensive suite, respond with: ANALYSIS_COMPLETE",
        "",
        "## Recommended analysis plan (adapt to available files; skip if file unavailable):",
        "  Round 1  — Data quality: per-sample read depth bar + ASV frequency histogram",
        "  Round 2  — Denoising stats: input→filtered→denoised→merged→non-chimeric (if available)",
        "  Round 3  — Phylum-level stacked bar chart (relative abundance)",
        "  Round 4  — Genus-level stacked bar chart (top 15 genera + 'Other')",
        "  Round 5  — Genus heatmap (top 25 genera × samples, z-score, seaborn clustermap)",
        "  Round 6  — Top 10 genus box plots (abundance distribution across samples)",
        "  Round 7  — Alpha diversity: Shannon + Observed features box/violin plots",
        "  Round 8  — Alpha rarefaction curves (subsample feature table at 10 depths)",
        "  Round 9  — Beta PCoA: ALL available distance matrices (Bray-Curtis, Jaccard, UniFrac)",
        "  Round 10 — PCA on CLR-transformed feature table (sklearn PCA, biplot if possible)",
        "  Round 11 — NMDS ordination (Bray-Curtis, metric=False, print stress in title)",
        "  Round 12 — Sample-to-sample Spearman correlation heatmap (genus-level)",
        "",
        "## Available files",
    ]
    for category, paths in export_files.items():
        for p in paths:
            lines.append(f"  [{category}] {p}")
    if metadata_path:
        lines.append(f"  [metadata] {metadata_path}")

    lines += [
        "",
        f"## Figure output directory : {figure_dir}",
        f"## DPI: {dpi}    figsize: {figsize}",
        "",
        "## FILE FORMATS — read exactly as described",
        "",
        "### [feature_table] feature-table.tsv  (QIIME2 biom export)",
        "  - Line 1  : '# Constructed from biom file'  ← comment, SKIP",
        "  - Line 2  : '#OTU ID\\t<sample1>\\t<sample2>...'  ← use as header",
        "  - Read:   ft = pd.read_csv(path, sep='\\t', skiprows=1, index_col=0)",
        "  - ft shape: (n_features × n_samples)",
        "",
        "### [taxonomy] taxonomy.tsv",
        "  - Columns : Feature ID (index) | Taxon | Confidence",
        "  - Phylum  : tax['phylum'] = tax['Taxon'].str.extract(r'p__([^;]+)').fillna('Unknown').str.strip()",
        "  - Genus   : tax['genus']  = tax['Taxon'].str.extract(r'g__([^;]+)').fillna('Unknown').str.strip()",
        "",
        "### [alpha] alpha-diversity TSV (one file per metric)",
        "  - Columns : sample-id (index) | metric value",
        "  - Read:   alpha = pd.read_csv(path, sep='\\t', index_col=0)",
        "  - Metric name is in the column after the index; get it with: col = alpha.columns[0]",
        "  - Multiple files may exist: shannon, observed_features, chao1, faith_pd — use all",
        "",
        "### [beta] distance-matrix TSV (one file per metric)",
        "  - Square symmetric matrix; row names = column names = sample IDs",
        "  - Read:   dm = pd.read_csv(path, sep='\\t', index_col=0)",
        "  - Multiple files: bray_curtis, jaccard, unweighted_unifrac, weighted_unifrac — use all",
        "",
        "### [denoising] denoising-stats.tsv",
        "  - Columns: sample-id (index) | input | filtered | denoised | merged | non-chimeric",
        "  - Read:   stats = pd.read_csv(path, sep='\\t', index_col=0)",
        "",
        "## ANALYSIS METHOD REFERENCE",
        "",
        "### PCA (Principal Component Analysis) on feature table",
        "  # CLR (center log-ratio) transform to handle compositional data",
        "  ra = ft.div(ft.sum(axis=0), axis=1)           # relative abundance (features × samples)",
        "  clr = np.log(ra.T + 1e-6)                     # samples × features, add pseudocount",
        "  clr = clr - clr.mean(axis=1).values[:,None]   # center each sample",
        "  from sklearn.decomposition import PCA",
        "  pca = PCA(n_components=2)",
        "  coords = pca.fit_transform(clr)                # shape: (n_samples, 2)",
        "  # variance explained: pca.explained_variance_ratio_",
        "",
        "### PCoA (Principle Coordinate Analysis) — metric MDS on distance matrix",
        "  from sklearn.manifold import MDS",
        "  pcoa = MDS(n_components=2, dissimilarity='precomputed', metric=True, random_state=42)",
        "  coords = pcoa.fit_transform(dm.values)         # shape: (n_samples, 2)",
        "",
        "### NMDS (Non-Metric Multidimensional Scaling)",
        "  nmds = MDS(n_components=2, dissimilarity='precomputed', metric=False,",
        "             random_state=42, max_iter=500, n_init=4)",
        "  coords = nmds.fit_transform(dm.values)",
        "  stress = nmds.stress_   # print in plot title (good if < 0.2)",
        "",
        "### Rarefaction curve (subsample simulation)",
        "  import numpy as np",
        "  min_depth = int(ft.sum(axis=0).min())",
        "  depths = np.linspace(100, min_depth, 10).astype(int)",
        "  mean_richness = []",
        "  for d in depths:",
        "      sub = ft.apply(lambda c: pd.Series(",
        "          np.random.multinomial(d, c/c.sum()) if c.sum() >= d else c.values,",
        "          index=c.index), axis=0)",
        "      mean_richness.append((sub > 0).sum(axis=0).mean())",
        "",
        "### Phylum / Genus aggregation from feature_table + taxonomy",
        "  # merge on Feature ID index, then groupby",
        "  merged = ft.join(tax[['genus']], how='left')",
        "  merged['genus'] = merged['genus'].fillna('Unknown')",
        "  genus_table = merged.groupby('genus').sum()   # shape: (n_genera × n_samples)",
        "  rel = genus_table.div(genus_table.sum(axis=0), axis=1)  # relative abundance",
        "  top15 = rel.sum(axis=1).nlargest(15).index",
        "  plot_data = rel.loc[top15].T                  # shape: (n_samples × 15)",
        "",
        "## Code requirements",
        "1. First two lines MUST be:",
        "      import matplotlib",
        "      matplotlib.use('Agg')",
        "2. Define at the top:",
        f"      FIGURE_DIR = r'{figure_dir}'",
        f"      DPI = {dpi}",
        "      import os; os.makedirs(FIGURE_DIR, exist_ok=True)",
        "3. Include the round number in every filename: e.g. 'round1_summary.png'",
        "4. Save and close every figure:",
        "      plt.savefig(os.path.join(FIGURE_DIR, 'roundN_name.png'), dpi=DPI, bbox_inches='tight')",
        "      plt.close()",
        "5. All labels, titles, legend entries in English.",
        "6. try/except around each major section — one failure must not stop other sections.",
        "7. No plt.show().",
        "",
        "## Begin: write code for Round 1 now.",
    ]
    return "\n".join(lines)


def run_auto_agent(
    export_files: dict,
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_rounds: int = 6,
    plot_config: Optional[dict] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> AutoAgentResult:
    """
    自律的に解析を進める AI エージェント。

    LLM が解析計画を自ら立て、ラウンドごとにコードを生成・実行し、
    結果を受け取って次の解析を決める。
    「ANALYSIS_COMPLETE」を受信するか max_rounds に達したら終了。
    """
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    results: list = []
    all_figures: list = []

    messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous microbiome analysis agent. "
                "Each response must contain ONE complete Python script in ```python...``` "
                "OR the text ANALYSIS_COMPLETE when all analyses are done."
            ),
        },
        {
            "role": "user",
            "content": _build_auto_initial_prompt(
                export_files, figure_dir, metadata_path, plot_config
            ),
        },
    ]

    for round_n in range(1, max_rounds + 1):
        _log(f"\n{'─' * 44}")
        _log(f"  🤖 Round {round_n} / {max_rounds}")
        _log(f"{'─' * 44}")
        _log("次の解析を計画中...")

        try:
            response = _agent.call_ollama(messages, model)
        except Exception as e:
            _log(f"Ollama エラー: {e}")
            break

        content = response.get("content", "")

        # 終了宣言
        if "ANALYSIS_COMPLETE" in content:
            _log("✅ AI が全解析完了と判断しました。")
            return AutoAgentResult(
                rounds=results, total_figures=all_figures, completed=True
            )

        code = _extract_code(content)
        if not code:
            _log("コードが見つかりませんでした。続行を促します。")
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "No Python code was found in your response. "
                    "Please write the next analysis as a complete Python script "
                    "in ```python...``` or respond with ANALYSIS_COMPLETE."
                ),
            })
            continue

        _log(f"コード生成完了 ({len(code.splitlines())} 行)")

        # ── 実行 + リトライ（最大 3 回）────────────────────────────────
        last_code   = code
        last_stderr = ""
        round_success = False
        new_figs: list = []

        for attempt in range(3):
            _log(f"実行中... (試行 {attempt + 1}/3)")
            success, stdout, stderr, figs = _run_code(
                last_code, output_dir, figure_dir, log_callback
            )

            if success:
                round_success = True
                new_figs = figs
                break

            last_stderr = stderr

            # ModuleNotFoundError 処理
            missing_pkg = _detect_missing_module(stderr)
            if missing_pkg:
                _log(f"未インストールパッケージ: {missing_pkg}")
                approved = install_callback(missing_pkg) if install_callback else False
                if approved and pip_install(missing_pkg, log_callback):
                    continue

            if attempt < 2:
                _log("LLM にコード修正を依頼中...")
                fix_msgs = messages + [
                    {"role": "assistant", "content": f"```python\n{last_code}\n```"},
                    {
                        "role": "user",
                        "content": (
                            f"Error:\n```\n{stderr[:1000]}\n```\n"
                            "Fix and return the complete corrected code in ```python...```."
                        ),
                    },
                ]
                try:
                    fix_resp = _agent.call_ollama(fix_msgs, model)
                    fixed = _extract_code(fix_resp.get("content", ""))
                    if fixed:
                        last_code = fixed
                        _log(f"修正済みコード受信 ({len(last_code.splitlines())} 行)")
                except Exception:
                    pass

        # ── ラウンド結果を記録 ───────────────────────────────────────
        results.append(CodeExecutionResult(
            success=round_success,
            stdout="",
            stderr=last_stderr,
            code=last_code,
            figures=new_figs,
            retry_count=0,
            error_message=last_stderr[:300] if not round_success else "",
        ))
        all_figures.extend(new_figs)

        if round_success:
            _log(f"✅ Round {round_n} 成功")
            if new_figs:
                _log(f"📊 図を保存: {[Path(f).name for f in new_figs]}")
            status_line = f"Round {round_n} succeeded."
            if new_figs:
                status_line += f" New figures saved: {[Path(f).name for f in new_figs]}."
        else:
            _log(f"❌ Round {round_n} 失敗")
            status_line = f"Round {round_n} failed. Error: {last_stderr[:200]}"

        all_names = [Path(f).name for f in all_figures]
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                f"{status_line}\n"
                f"All figures generated so far: {all_names}\n\n"
                f"Proceed with Round {round_n + 1}, "
                f"or respond ANALYSIS_COMPLETE if done."
            ),
        })

    return AutoAgentResult(rounds=results, total_figures=all_figures, completed=False)


# ─────────────────────────────────────────────────────────────────────────────
# Tool-Calling Coding Agent（vibe-local スタイル）
# ─────────────────────────────────────────────────────────────────────────────

# ── ツール定義（Ollama /api/chat に渡す JSON スキーマ）──────────────────────
_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file's contents. ALWAYS call this before writing analysis code "
                "to understand the exact column names, header structure, and data format."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum lines to return (default 100)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file (creates or overwrites). "
                "Use to create Python analysis scripts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path of the file to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute a Python script file. Returns stdout, stderr, and exit code. "
                "If it fails, immediately call write_file to fix the script, "
                "then call run_python again — repeat until exit code is 0."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the .py file to execute",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory, optionally filtered by glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory path to list",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter (e.g. '*.tsv', '*.png'). Defaults to '*'.",
                    },
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_package",
            "description": (
                "Install a Python package via pip. "
                "Use only when run_python fails with ModuleNotFoundError."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "package": {
                        "type": "string",
                        "description": "Package name to install (e.g. 'scikit-learn', 'seaborn')",
                    },
                },
                "required": ["package"],
            },
        },
    },
]


def _exec_tool(
    tool_name: str,
    tool_args: dict,
    output_dir: str,
    figure_dir: str,
    log_callback: Optional[Callable[[str], None]],
    install_callback: Optional[Callable[[str], bool]],
) -> tuple:
    """
    ツール呼び出しを実行する。
    戻り値: (result_str: str, new_figures: list[str])
    """
    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    # ── read_file ─────────────────────────────────────────────────────────
    if tool_name == "read_file":
        path = tool_args.get("path", "")
        max_lines = int(tool_args.get("max_lines", 100))
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            truncated = len(lines) > max_lines
            content = "".join(lines[:max_lines])
            if truncated:
                content += f"\n... ({len(lines) - max_lines} more lines truncated)"
            _log(f"  ← read {Path(path).name} ({len(lines)} lines)")
            return content or "(empty file)", []
        except FileNotFoundError:
            return f"ERROR: file not found: {path}", []
        except Exception as e:
            return f"ERROR reading {path}: {e}", []

    # ── write_file ────────────────────────────────────────────────────────
    elif tool_name == "write_file":
        path = tool_args.get("path", "")
        content = tool_args.get("content", "")
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # アトミック書き込み（クラッシュセーフ）
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tmp",
                dir=p.parent, delete=False, encoding="utf-8",
            ) as f:
                f.write(content)
                tmp = f.name
            Path(tmp).replace(path)
            n = len(content.splitlines())
            _log(f"  ← wrote {Path(path).name} ({n} lines)")
            return f"OK: wrote {n} lines to {path}", []
        except Exception as e:
            return f"ERROR writing {path}: {e}", []

    # ── run_python ────────────────────────────────────────────────────────
    elif tool_name == "run_python":
        path = tool_args.get("path", "")
        py_exec = _agent.QIIME2_PYTHON
        if not py_exec or not Path(py_exec).exists():
            py_exec = sys.executable

        fig_dir = Path(figure_dir)
        fig_dir.mkdir(parents=True, exist_ok=True)
        before = (
            set(fig_dir.glob("*.png"))
            | set(fig_dir.glob("*.pdf"))
            | set(fig_dir.glob("*.svg"))
        )

        try:
            proc = subprocess.run(
                [py_exec, path],
                capture_output=True, text=True,
                timeout=300, cwd=output_dir,
            )
        except subprocess.TimeoutExpired:
            return "ERROR: execution timed out (300 seconds)", []
        except Exception as e:
            return f"ERROR launching process: {e}", []

        after = (
            set(fig_dir.glob("*.png"))
            | set(fig_dir.glob("*.pdf"))
            | set(fig_dir.glob("*.svg"))
        )
        new_figs = [str(f) for f in sorted(after - before)]

        parts = []
        if proc.stdout.strip():
            parts.append(f"STDOUT:\n{proc.stdout[:3000]}")
        if proc.returncode != 0 and proc.stderr.strip():
            parts.append(f"STDERR:\n{proc.stderr[:3000]}")
            if log_callback:
                for line in proc.stderr.splitlines()[:10]:
                    log_callback(f"    [err] {line}")
        parts.append(f"EXIT CODE: {proc.returncode}")
        if new_figs:
            parts.append(f"NEW FIGURES: {[Path(f).name for f in new_figs]}")
            _log(f"  ← 📊 {[Path(f).name for f in new_figs]}")

        _log(f"  ← run {Path(path).name} → exit {proc.returncode}")
        return "\n".join(parts), new_figs

    # ── list_files ────────────────────────────────────────────────────────
    elif tool_name == "list_files":
        directory = tool_args.get("directory", "")
        pattern = tool_args.get("pattern", "*")
        try:
            files = sorted(Path(directory).glob(pattern))
            if not files:
                return f"(no files matching '{pattern}' in {directory})", []
            return "\n".join(str(f) for f in files), []
        except Exception as e:
            return f"ERROR: {e}", []

    # ── install_package ───────────────────────────────────────────────────
    elif tool_name == "install_package":
        package = tool_args.get("package", "")
        _log(f"  ⚠️  パッケージ '{package}' のインストールが要求されました")
        approved = install_callback(package) if install_callback else False
        if not approved:
            return (
                f"DECLINED: user declined to install '{package}'. "
                "Try an alternative approach without this package.", []
            )
        ok = pip_install(package, log_callback)
        return (
            f"OK: installed {package}" if ok
            else f"ERROR: failed to install {package}"
        ), []

    else:
        return f"ERROR: unknown tool '{tool_name}'", []


def _parse_text_tool_calls(content: str) -> list:
    """
    tool_calls が空のとき、テキスト content から JSON ツール呼び出しを抽出する。
    qwen2.5-coder 等、ツール API に非対応なモデル向けフォールバック。

    対応フォーマット:
      {"name": "...", "arguments": {...}}
      [{"name": "...", "arguments": {...}}, ...]
    """
    if not content:
        return []

    tool_calls = []

    # パターン1: ツール呼び出し JSON が複数行にわたる場合も含め全体を検索
    # ```json ... ``` ブロック内を優先
    for block in re.findall(r'```(?:json)?\s*([\s\S]*?)```', content):
        try:
            obj = json.loads(block.strip())
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if isinstance(item, dict) and "name" in item and (
                    "arguments" in item or "parameters" in item
                ):
                    args = item.get("arguments") or item.get("parameters") or {}
                    tool_calls.append({
                        "function": {"name": item["name"], "arguments": args}
                    })
        except (json.JSONDecodeError, TypeError):
            pass

    if tool_calls:
        return tool_calls

    # パターン2: content 全体が JSON (単一ツール呼び出し)
    try:
        obj = json.loads(content.strip())
        items = obj if isinstance(obj, list) else [obj]
        for item in items:
            if isinstance(item, dict) and "name" in item:
                args = item.get("arguments") or item.get("parameters") or {}
                tool_calls.append({
                    "function": {"name": item["name"], "arguments": args}
                })
        if tool_calls:
            return tool_calls
    except (json.JSONDecodeError, TypeError):
        pass

    # パターン3: テキスト内に埋め込まれた JSON オブジェクトをスキャン
    for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*\}', content):
        try:
            obj = json.loads(match.group(0))
            if "name" in obj:
                args = obj.get("arguments") or obj.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append({
                    "function": {"name": obj["name"], "arguments": args}
                })
        except (json.JSONDecodeError, TypeError):
            pass

    # パターン4a: name なし JSON をヒューリスティックで推論
    # モデルが {"path": "...", "content": "..."} を出力した場合に write_file として解釈
    if not tool_calls:
        try:
            obj = json.loads(content.strip())
            if isinstance(obj, dict) and "name" not in obj:
                if "path" in obj and "content" in obj:
                    tool_calls.append({"function": {"name": "write_file", "arguments": obj}})
                elif "path" in obj and str(obj.get("path", "")).endswith(".py"):
                    tool_calls.append({"function": {"name": "run_python", "arguments": obj}})
                elif "directory" in obj:
                    tool_calls.append({"function": {"name": "list_files", "arguments": obj}})
        except (json.JSONDecodeError, TypeError):
            pass

    if tool_calls:
        return tool_calls

    # パターン4b: ```json コードブロック内の name なし JSON にも同様に適用
    if not tool_calls:
        for block in re.findall(r'```(?:json)?\s*([\s\S]*?)```', content):
            try:
                obj = json.loads(block.strip())
                if isinstance(obj, dict) and "name" not in obj:
                    if "path" in obj and "content" in obj:
                        tool_calls.append({"function": {"name": "write_file", "arguments": obj}})
                        break
                    elif "path" in obj and str(obj.get("path", "")).endswith(".py"):
                        tool_calls.append({"function": {"name": "run_python", "arguments": obj}})
                        break
                    elif "directory" in obj:
                        tool_calls.append({"function": {"name": "list_files", "arguments": obj}})
                        break
            except (json.JSONDecodeError, TypeError):
                pass

    if tool_calls:
        return tool_calls

    # パターン4: 壊れた JSON を寛容にパース（name/arguments を正規表現で抽出）
    if not tool_calls:
        m_name = re.search(r'"name"\s*:\s*"([^"]+)"', content)
        m_path = re.search(r'"path"\s*:\s*"([^"]+)"', content)
        m_dir  = re.search(r'"directory"\s*:\s*"([^"]+)"', content)
        m_pkg  = re.search(r'"package"\s*:\s*"([^"]+)"', content)
        if m_name:
            name = m_name.group(1)
            if name in ("read_file", "write_file", "run_python", "list_files", "install_package"):
                args: dict = {}
                if m_path:
                    args["path"] = m_path.group(1)
                if m_dir:
                    args["directory"] = m_dir.group(1)
                if m_pkg:
                    args["package"] = m_pkg.group(1)
                # write_file の content は JSON 破損しやすいので別途抽出
                if name == "write_file" and '"content"' in content:
                    # content の開始位置を特定
                    cm = re.search(r'"content"\s*:\s*"', content)
                    if cm:
                        start = cm.end()
                        # エスケープシーケンスを処理しつつ content を抽出
                        raw = content[start:]
                        extracted = []
                        i = 0
                        while i < len(raw):
                            c = raw[i]
                            if c == '\\' and i + 1 < len(raw):
                                nc = raw[i + 1]
                                if nc == 'n': extracted.append('\n')
                                elif nc == 't': extracted.append('\t')
                                elif nc == '"': extracted.append('"')
                                elif nc == '\\': extracted.append('\\')
                                else: extracted.append(c + nc)
                                i += 2
                            elif c == '"':
                                break  # content 文字列の終端
                            else:
                                extracted.append(c)
                                i += 1
                        file_content = "".join(extracted)
                        if len(file_content) > 10:
                            args["content"] = file_content
                if args or name in ("list_files",):
                    tool_calls.append({"function": {"name": name, "arguments": args}})

    return tool_calls


def run_coding_agent(
    export_files: dict,
    user_prompt: str,
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_steps: int = 30,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> CodeExecutionResult:
    """
    vibe-local スタイルのツール呼び出し型コーディングエージェント。

    従来の「スクリプト一括生成→実行」と異なり、LLM が:
      1. list_files でファイルを探索
      2. read_file でデータの実際のフォーマットを確認
      3. write_file で解析スクリプトを作成
      4. run_python で実行
      5. エラーが出たら write_file で修正 → run_python を繰り返す
    という自律的なループで「必ず動くコード」を作り上げる。

    user_prompt が空の場合は包括的な解析を自律実行（自律モード）。
    user_prompt が指定された場合はその内容に従う（指示モード）。
    """
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    # ── システムプロンプト（vibe-local "TOOL FIRST" 設計） ────────────────
    system_content = "\n".join([
        "You are an autonomous microbiome bioinformatics coding agent.",
        "",
        "## CRITICAL RULES — follow exactly, no exceptions",
        "1. TOOL FIRST: Call a tool immediately. Never write explanations before acting.",
        "2. READ BEFORE CODING: Call read_file on data files before writing analysis code.",
        "   You MUST verify column names, delimiter, skiprows, and data structure — do not assume.",
        "3. NEVER GIVE UP: If run_python fails, diagnose STDERR, call write_file to fix,",
        "   then run_python again. Repeat until EXIT CODE: 0. Fix silently.",
        "4. COMPLETE SCRIPT: Write all analysis sections into one .py file.",
        "   Each section in a try/except block — one failure must not stop others.",
        "5. DONE WHEN FIGURES ARE SAVED: Stop calling tools when all requested figures",
        "   are saved in FIGURE_DIR. Respond with a brief summary of what was generated.",
        "",
        "## WORKFLOW",
        "Step 1 → list_files to explore directories",
        "Step 2 → read_file on each data file (100 lines is enough to understand format)",
        "Step 3 → write_file to create analysis.py",
        "Step 4 → run_python on analysis.py",
        "Step 5 → If EXIT CODE != 0: read STDERR, write_file to fix, run_python again",
        "Step 6 → Repeat Step 5 until EXIT CODE: 0",
        "",
        "## FILE FORMATS",
        "",
        "feature_table (feature-table.tsv):",
        "  Line 1: '# Constructed from biom file'  ← SKIP (skiprows=1)",
        "  Line 2: '#OTU ID\\t<sample1>\\t...'      ← header",
        "  ft = pd.read_csv(path, sep='\\t', skiprows=1, index_col=0)  # shape: features × samples",
        "",
        "taxonomy (taxonomy.tsv):",
        "  Columns: Feature ID (index) | Taxon | Confidence",
        "  Phylum: tax['phylum'] = tax['Taxon'].str.extract(r'p__([^;]+)').fillna('Unknown').str.strip()",
        "  Genus:  tax['genus']  = tax['Taxon'].str.extract(r'g__([^;]+)').fillna('Unknown').str.strip()",
        "",
        "alpha-diversity TSV (one file per metric; metric name = first column after index):",
        "  alpha = pd.read_csv(path, sep='\\t', index_col=0)  # shape: samples × 1",
        "  Possible metrics: shannon, observed_features, chao1, faith_pd — ALL available files",
        "",
        "beta distance-matrix TSV (one file per metric):",
        "  dm = pd.read_csv(path, sep='\\t', index_col=0)  # square symmetric, samples × samples",
        "  Possible metrics: bray_curtis, jaccard, unweighted_unifrac, weighted_unifrac",
        "",
        "denoising-stats.tsv:",
        "  stats = pd.read_csv(path, sep='\\t', index_col=0)",
        "  Columns: input | filtered | denoised | merged | non-chimeric | passed filter",
        "",
        "## ANALYSIS IMPLEMENTATIONS",
        "",
        "Genus/phylum aggregation:",
        "  merged = ft.join(tax[['genus']], how='left').fillna({'genus': 'Unknown'})",
        "  genus_tbl = merged.groupby('genus').sum()              # features → genus",
        "  rel = genus_tbl.div(genus_tbl.sum(axis=0), axis=1)    # relative abundance",
        "  top15 = rel.sum(axis=1).nlargest(15).index",
        "  others = rel.loc[~rel.index.isin(top15)].sum()",
        "  plot_df = rel.loc[top15].T                             # samples × genera",
        "  plot_df['Other'] = others.values",
        "",
        "PCA (CLR-transformed):",
        "  ra = ft.div(ft.sum(axis=0), axis=1)                   # features × samples",
        "  clr = np.log(ra.T + 1e-6)                             # samples × features",
        "  clr = clr - clr.mean(axis=1).values[:, None]",
        "  from sklearn.decomposition import PCA",
        "  pca = PCA(n_components=2); coords = pca.fit_transform(clr)",
        "  # variance: pca.explained_variance_ratio_",
        "",
        "PCoA (metric MDS on distance matrix):",
        "  from sklearn.manifold import MDS",
        "  pcoa = MDS(n_components=2, dissimilarity='precomputed', metric=True, random_state=42)",
        "  coords = pcoa.fit_transform(dm.values)  # dm must be square float matrix",
        "",
        "NMDS (non-metric MDS):",
        "  nmds = MDS(n_components=2, dissimilarity='precomputed', metric=False,",
        "             random_state=42, max_iter=500, n_init=4)",
        "  coords = nmds.fit_transform(dm.values)",
        "  stress = round(nmds.stress_, 4)  # print in title; good < 0.2",
        "",
        "Rarefaction curves:",
        "  min_d = int(ft.sum(axis=0).min())",
        "  depths = np.linspace(100, min_d, 10).astype(int)",
        "  richness = []",
        "  for d in depths:",
        "      sub = ft.apply(lambda c: pd.Series(",
        "          np.random.multinomial(d, c/c.sum()) if c.sum()>=d else c.values,",
        "          index=c.index), axis=0)",
        "      richness.append((sub > 0).sum(axis=0).mean())",
        "",
        "## PYTHON SCRIPT TEMPLATE",
        "import matplotlib",
        "matplotlib.use('Agg')  # MUST be first",
        "import matplotlib.pyplot as plt",
        "import pandas as pd",
        "import numpy as np",
        "import os",
        f"FIGURE_DIR = r'{figure_dir}'",
        "DPI = 150",
        "os.makedirs(FIGURE_DIR, exist_ok=True)",
        "",
        "try:  # --- Section: figure name ---",
        "    # ... analysis code ...",
        "    plt.savefig(os.path.join(FIGURE_DIR, 'figNN_name.png'), dpi=DPI, bbox_inches='tight')",
        "    plt.close()",
        "    print('figNN saved')",
        "except Exception as e:",
        "    print(f'figNN failed: {e}')",
        "",
        "NEVER plt.show(). ALWAYS plt.savefig() + plt.close().",
        "Print 'figNN saved' on success so you can verify which figures were generated.",
        "",
        "## COMMON MISTAKES — avoid these",
        "- WRONG: from scipy.stats import boxplot  ← scipy.stats has NO boxplot",
        "  RIGHT:  plt.boxplot(data)  or  import seaborn; seaborn.boxplot(data=df)",
        "- WRONG: import biom  ← not available; use pd.read_csv() on .tsv files",
        "- WRONG: hardcoding data values — ALWAYS read from file paths in the task",
        "- WRONG: plt.show()  ← never; always plt.savefig() + plt.close()",
        "- TAXONOMY str.extract RETURNS DataFrame (not Series):",
        "  WRONG: tax['Taxon'].str.extract(r'g__([^;]+)').fillna('Unknown').str.strip()",
        "  RIGHT:  tax['Taxon'].str.extract(r'g__([^;]+)')[0].fillna('Unknown').str.strip()",
        "- DO NOT use bare except: print(e) — it hides errors and prevents figure generation.",
        "  Instead: write code without try/except, or use 'raise' inside except blocks.",
    ])

    # ── 初回ユーザーメッセージ ─────────────────────────────────────────────
    file_lines = []
    for cat, paths in export_files.items():
        for p in paths:
            file_lines.append(f"  [{cat}] {p}")
    if metadata_path:
        file_lines.append(f"  [metadata] {metadata_path}")

    auto_task = "\n".join([
        "Perform a COMPREHENSIVE microbiome analysis.",
        "Write ALL figures to FIGURE_DIR. Skip any figure gracefully if required data is unavailable.",
        "",
        "## Phase 1 — Data Quality & Summary",
        "  fig01_read_depth.png    Per-sample total read counts (bar chart, sorted descending)",
        "  fig02_feature_hist.png  ASV/OTU frequency histogram (log x-axis, log y-axis)",
        "  fig03_denoising.png     DADA2 stats: grouped bar input/filtered/denoised/merged/non-chimeric",
        "                          (only if denoising file is available)",
        "",
        "## Phase 2 — Taxonomic Composition",
        "  fig04_phylum_bar.png    Phylum-level stacked bar (relative abundance, all phyla)",
        "  fig05_genus_bar.png     Genus-level stacked bar (top 15 genera + 'Other')",
        "  fig06_genus_heatmap.png Genus heatmap: top 25 genera × samples, z-score per row,",
        "                          seaborn clustermap with hierarchical clustering",
        "  fig07_genus_boxplot.png Top 10 genus abundance box + strip plot across samples",
        "",
        "## Phase 3 — Alpha Diversity",
        "  fig08_alpha_multi.png   All available alpha metrics in subplots (Shannon, Observed,",
        "                          Chao1, Faith PD — include whichever files exist)",
        "  fig09_rarefaction.png   Rarefaction curves: mean observed features vs subsampling depth",
        "",
        "## Phase 4 — Beta Diversity Ordination",
        "  fig10_pcoa_all.png      PCoA for ALL available beta matrices in subplots",
        "                          (Bray-Curtis, Jaccard, unweighted/weighted UniFrac)",
        "  fig11_pca.png           PCA on CLR-transformed feature table; label axes with",
        "                          % variance explained; scatter + sample ID labels",
        "  fig12_nmds_bray.png     NMDS on Bray-Curtis (metric=False); show stress in title",
        "",
        "## Phase 5 — Sample Relationships & Summary",
        "  fig13_sample_corr.png   Sample-to-sample Spearman correlation heatmap (genus-level)",
        "  fig14_top_taxa_pie.png  Pie chart of mean relative abundance at genus level (top 10)",
        "",
        "Rules:",
        "- dpi=150, bbox_inches='tight', clear English axis labels, plt.close() after each figure",
        "- try/except around every figure section; print 'figXX saved' on success",
        "- For ordination figures with multiple matrices, use matplotlib subplots",
        "- Use seaborn color palettes for aesthetics when appropriate",
    ])
    task = user_prompt.strip() if user_prompt.strip() else auto_task

    initial_content = "\n".join([
        "## Available QIIME2-exported data files (exact paths)",
        *file_lines,
        "",
        f"## FIGURE_DIR: {figure_dir}",
        f"## Script path: {output_dir}/analysis.py",
        "",
        "## Your task",
        task,
        "",
        "## Start",
        "Call list_files first, then read_file on key data files, then write_file to create",
        f"analysis.py at {output_dir}/analysis.py, then call run_python to execute it.",
    ])

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": initial_content},
    ]

    all_figs: list = []
    final_code     = ""
    final_error    = ""
    success        = False
    total_steps    = 0
    _run_python_count = 0   # run_python が実行された回数（進捗確認用）

    _log("🤖 コーディングエージェント起動（tool-calling モード）")
    _log(f"   最大 {max_steps} ステップ  |  Ctrl+C で中断")
    _log("")

    for step in range(1, max_steps + 1):
        # ── フォールバック判定1: 5 ステップ経過して run_python すら呼ばれていない ──
        # ── フォールバック判定2: run_python を 3 回以上呼んでも図が未生成 ──
        if not all_figs and (
            (step == 6 and _run_python_count == 0)
            or (_run_python_count >= 3)
        ):
            _log("  ⚠️  ツール呼び出しループが進捗しません。1ショット生成にフォールバックします...")
            fallback = run_code_agent(
                export_files=export_files,
                user_prompt=user_prompt,
                output_dir=output_dir,
                figure_dir=figure_dir,
                metadata_path=metadata_path,
                model=model,
                max_retries=3,
                log_callback=log_callback,
                install_callback=install_callback,
            )
            return fallback
        total_steps = step
        _log(f"[step {step}/{max_steps}] 送信中...")

        try:
            response = _agent.call_ollama(messages, model, tools=_TOOL_DEFS)
        except KeyboardInterrupt:
            _log("\n⚠️  中断されました。")
            break
        except Exception as e:
            _log(f"Ollama エラー: {e}")
            final_error = str(e)
            break

        content    = response.get("content", "")
        tool_calls = response.get("tool_calls", [])

        # アシスタントメッセージを会話履歴に追加
        assistant_msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            # フォールバック: テキスト内 JSON をツール呼び出しとして解釈
            parsed = _parse_text_tool_calls(content)
            if parsed:
                _log(f"  ℹ️  テキストからツール呼び出し {len(parsed)} 件を解析しました")
                # assistant メッセージを tool_calls 付きで上書き
                messages[-1]["tool_calls"] = parsed
                tool_calls = parsed
            else:
                # 図がまだ生成されていない場合は継続を促す
                _ran_python = any(
                    m.get("role") == "tool" and m.get("name") == "run_python"
                    for m in messages
                )
                if not all_figs and not _ran_python and step < max_steps - 2:
                    if content:
                        _log(f"  ← モデル応答（データ出力と判断）: {content[:80]}...")
                    _log("  ℹ️  まだ図が生成されていません。スクリプト作成を促します...")
                    messages.append({
                        "role": "user",
                        "content": (
                            "You have read the data. Now proceed to the next step:\n"
                            "1. Call write_file to create the analysis script at "
                            f"{output_dir}/analysis.py\n"
                            "2. Call run_python to execute it.\n"
                            "Do NOT output data or summaries — call write_file NOW."
                        ),
                    })
                    continue

                # ツール呼び出しなし → エージェントが完了と判断
                if content:
                    _log(f"エージェント応答: {content[:300]}")
                _log("✅ エージェントがタスクを完了しました。")
                success = True
                break

        # ── 各ツール呼び出しを実行 ────────────────────────────────────────
        for tc in tool_calls:
            fn         = tc.get("function", {})
            tool_name  = fn.get("name", "")
            raw_args   = fn.get("arguments", {})

            # arguments が JSON 文字列で返ってくる場合に対応
            if isinstance(raw_args, str):
                try:
                    tool_args = json.loads(raw_args)
                except Exception:
                    tool_args = {}
            elif isinstance(raw_args, dict):
                tool_args = raw_args
            else:
                tool_args = {}

            # 引数のプレビュー表示
            preview = ", ".join(
                f"{k}={repr(str(v))[:60]}" for k, v in tool_args.items()
            )
            _log(f"  🔧 {tool_name}({preview})")

            tool_result, new_figs = _exec_tool(
                tool_name, tool_args,
                output_dir, figure_dir,
                log_callback, install_callback,
            )
            all_figs.extend(new_figs)
            if tool_name == "run_python":
                _run_python_count += 1

            # run_python 成功時: 最後のスクリプトのコードを保存
            if tool_name == "run_python" and "EXIT CODE: 0" in tool_result:
                success = True
                script_path = tool_args.get("path", "")
                if script_path and Path(script_path).exists():
                    try:
                        final_code = Path(script_path).read_text(encoding="utf-8")
                    except Exception:
                        pass

            # ツール結果を会話履歴に追加（長すぎる場合は切り捨て）
            messages.append({
                "role":    "tool",
                "name":    tool_name,
                "content": tool_result[:4000],
            })

            # write_file で .py ファイルを書いた後、run_python を即時注入
            if (
                tool_name == "write_file"
                and "OK: wrote" in tool_result
                and tool_args.get("path", "").endswith(".py")
            ):
                script_path = tool_args.get("path", "")
                _log(f"  → auto-injecting run_python for {Path(script_path).name}")
                # run_python ツールを直接実行
                run_result, run_figs = _exec_tool(
                    "run_python", {"path": script_path},
                    output_dir, figure_dir,
                    log_callback, install_callback,
                )
                all_figs.extend(run_figs)
                _run_python_count += 1  # auto-inject 分もカウント
                if "EXIT CODE: 0" in run_result and run_figs:
                    success = True
                    try:
                        final_code = Path(script_path).read_text(encoding="utf-8")
                    except Exception:
                        pass
                # 実行結果を会話に追加
                messages.append({
                    "role":    "tool",
                    "name":    "run_python",
                    "content": run_result[:4000],
                })
                # auto-inject でも exit 0 だが図が生成されていない場合は本番コード強制
                if (
                    "EXIT CODE: 0" in run_result
                    and not run_figs
                    and not all_figs
                    and step < max_steps - 2
                ):
                    _log("  ℹ️  auto-inject: exit 0 でも図が未生成。本番コードの作成を促します...")
                    _file_refs = "\n".join(
                        f"  [{cat}] {p}"
                        for cat, paths in export_files.items()
                        for p in paths
                    )
                    messages.append({
                        "role": "user",
                        "content": (
                            "The script ran with EXIT CODE: 0 but NO figures were saved.\n"
                            "The script likely hardcoded data or had a silent error in a try/except.\n\n"
                            "IMPORTANT: Read data from the ACTUAL FILES listed below — do NOT hardcode values.\n\n"
                            "CORRECT FILE PATHS:\n"
                            f"{_file_refs}\n\n"
                            f"FIGURE_DIR = r'{figure_dir}'\n"
                            f"Script path: {output_dir}/analysis.py\n\n"
                            "Call write_file NOW with a script that:\n"
                            "  1. Uses pd.read_csv() on the EXACT paths above\n"
                            "  2. Generates the requested figures\n"
                            "  3. Saves each with plt.savefig() to FIGURE_DIR\n"
                            "Add print() after each plt.savefig() to confirm the save."
                        ),
                    })

            # run_python が exit 0 でも図が生成されていない場合は継続
            if (
                tool_name == "run_python"
                and "EXIT CODE: 0" in tool_result
                and not new_figs
                and not all_figs
                and step < max_steps - 2
            ):
                _log("  ℹ️  スクリプトは成功しましたが図が未生成です。本番コードの作成を促します...")
                # 正確なファイルパスを再掲する
                _file_refs = "\n".join(
                    f"  [{cat}] {p}"
                    for cat, paths in export_files.items()
                    for p in paths
                )
                messages.append({
                    "role": "user",
                    "content": (
                        "The script ran with EXIT CODE: 0 but NO figures were saved to FIGURE_DIR.\n"
                        "The script was likely empty or a stub.\n\n"
                        "CORRECT FILE PATHS — use these EXACT paths in your script:\n"
                        f"{_file_refs}\n\n"
                        f"FIGURE_DIR = r'{figure_dir}'\n"
                        f"Script path: {output_dir}/analysis.py\n\n"
                        "Call write_file NOW with a COMPLETE Python analysis script that:\n"
                        "  1. Reads the exact paths listed above\n"
                        "  2. Generates figures fig01–fig14 as described in the task\n"
                        "  3. Saves each with plt.savefig() to FIGURE_DIR\n"
                        "Use only the exact paths listed above. Do NOT guess paths."
                    ),
                })

    return CodeExecutionResult(
        success=success,
        stdout="",
        stderr=final_error,
        code=final_code,
        figures=all_figs,
        retry_count=total_steps,
        error_message=final_error[:500] if not success else "",
    )


# ─────────────────────────────────────────────────────────────────────────────
# マニフェストエージェント（フルパイプライン + 解析）
# ─────────────────────────────────────────────────────────────────────────────

def run_manifest_agent(
    manifest_path: str,
    user_prompt: str,
    output_dir: str,
    figure_dir: str,
    metadata_path: str = "",
    model: Optional[str] = None,
    max_retries: int = 3,
    plot_config: Optional[dict] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    install_callback: Optional[Callable[[str], bool]] = None,
) -> CodeExecutionResult:
    """
    マニフェストファイルから QIIME2 パイプライン + 解析コードを
    LLM に生成させて実行するエージェント。

    Parameters
    ----------
    manifest_path : str
        QIIME2 形式のマニフェスト TSV（PairedEndFastqManifestPhred33V2）
    user_prompt : str
        やりたい解析の自然言語指示
    output_dir : str
        QIIME2 成果物・中間ファイルの出力先
    figure_dir : str
        図の保存先
    """
    if model is None:
        model = _agent.DEFAULT_MODEL

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    _log("LLM にパイプライン＋解析コードの生成を依頼中...")

    system_msg = {
        "role": "system",
        "content": (
            "You are a microbiome analysis expert using QIIME2 and Python. "
            "Generate only Python code without any explanation. "
            "Wrap code in ```python ... ```."
        ),
    }
    user_msg = {
        "role": "user",
        "content": _build_manifest_prompt(
            manifest_path, user_prompt, output_dir, figure_dir,
            metadata_path, plot_config,
        ),
    }
    messages = [system_msg, user_msg]

    try:
        response = _agent.call_ollama(messages, model)
    except Exception as e:
        return CodeExecutionResult(
            success=False,
            error_message=f"Ollama 接続エラー: {e}",
        )

    code = _extract_code(response.get("content", ""))
    if not code:
        return CodeExecutionResult(
            success=False,
            error_message="LLM がコードを生成しませんでした",
        )
    _log(f"コード生成完了 ({len(code.splitlines())} 行)")

    last_code = code
    last_stderr = ""

    for attempt in range(max_retries + 1):
        _log(f"コード実行中... (試行 {attempt + 1}/{max_retries + 1})")

        success, stdout, stderr, new_figs = _run_code(
            last_code, output_dir, figure_dir, log_callback
        )

        if success:
            _log(f"実行成功。生成された図: {len(new_figs)} 件")
            return CodeExecutionResult(
                success=True,
                stdout=stdout,
                stderr=stderr,
                code=last_code,
                figures=new_figs,
                retry_count=attempt,
            )

        last_stderr = stderr

        missing_pkg = _detect_missing_module(stderr)
        if missing_pkg:
            _log(f"未インストールパッケージを検出: {missing_pkg}")
            approved = install_callback(missing_pkg) if install_callback else False
            if approved:
                ok = pip_install(missing_pkg, log_callback)
                if ok:
                    _log(f"{missing_pkg} のインストール完了。再実行します。")
                    continue
            else:
                _log(f"{missing_pkg} のインストールをスキップしました。")

        if attempt >= max_retries:
            break

        _log("エラーを LLM に渡してコード修正を依頼中...")
        messages.append({
            "role": "assistant",
            "content": f"```python\n{last_code}\n```",
        })
        messages.append({
            "role": "user",
            "content": (
                f"The code produced the following error:\n"
                f"```\n{stderr[:1500]}\n```\n\n"
                f"Please fix the code and output the complete corrected version "
                f"wrapped in ```python ... ```."
            ),
        })

        try:
            fix_response = _agent.call_ollama(messages, model)
        except Exception as e:
            _log(f"Ollama 接続エラー: {e}")
            break

        fixed = _extract_code(fix_response.get("content", ""))
        if fixed:
            last_code = fixed
            _log(f"修正済みコード受信 ({len(last_code.splitlines())} 行)")
        else:
            _log("コード修正に失敗しました。")
            break

    return CodeExecutionResult(
        success=False,
        stdout="",
        stderr=last_stderr,
        code=last_code,
        figures=[],
        retry_count=max_retries,
        error_message=last_stderr[:500],
    )
