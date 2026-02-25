#!/usr/bin/env python3
"""
code_agent.py
=============
LLM に Python 解析コードを生成させ、実行・エラー修正・パッケージ
インストール確認を行うモジュール。
"""

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
        "## Recommended analysis plan (adapt to available files):",
        "  Round 1 — Summary statistics (sample count, feature count, read-depth distribution)",
        "  Round 2 — Genus-level stacked bar chart (relative abundance, top genera)",
        "  Round 3 — Alpha diversity boxplot (Shannon; observed_features if available)",
        "  Round 4 — Beta diversity PCoA (Bray-Curtis distance matrix → MDS)",
        "  Round 5 — Taxonomy heatmap (top 20 genera, z-score normalized)",
        "  Round 6 — Any additional insight you find relevant",
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
        "## FILE FORMAT — read exactly as described",
        "",
        "### [feature_table] TSV  (exported from QIIME2 via biom convert)",
        "  - Line 1  : '# Constructed from biom file'  ← skip",
        "  - Line 2  : '#OTU ID\\t<sample1>\\t<sample2>...'  ← header",
        "  - Read:   ft = pd.read_csv(path, sep='\\t', skiprows=1, index_col=0)",
        "",
        "### [taxonomy] taxonomy.tsv",
        "  - Columns : Feature ID (index) | Taxon | Confidence",
        "  - Genus   : tax['genus'] = tax['Taxon'].str.extract(r'g__([^;]+)').fillna('Unknown').str.strip()",
        "",
        "### [alpha] alpha-diversity TSV",
        "  - Columns : sample-id (index) | metric value",
        "  - Read:   alpha = pd.read_csv(path, sep='\\t', index_col=0)",
        "",
        "### [beta] distance-matrix TSV",
        "  - Square symmetric matrix; row = column = sample IDs",
        "  - Read:   dm = pd.read_csv(path, sep='\\t', index_col=0)",
        "  - PCoA:   from sklearn.manifold import MDS",
        "            coords = MDS(n_components=2, dissimilarity='precomputed', random_state=42).fit_transform(dm.values)",
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
        "6. try/except around each major section.",
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
