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
    lines = [
        "あなたはマイクロバイオーム解析の専門家です。",
        "以下のエクスポート済み QIIME2 データを使って解析する Python コードを書いてください。",
        "",
        "## 利用可能なファイル",
    ]
    for category, paths in export_files.items():
        for p in paths:
            lines.append(f"  [{category}] {p}")

    if metadata_path:
        lines.append(f"  [metadata] {metadata_path}")

    cfg = plot_config or {}
    lines += [
        "",
        f"## 出力先（図を保存するディレクトリ）: {figure_dir}",
        f"## DPI: {cfg.get('dpi', 150)}",
        f"## figsize: {cfg.get('figsize', [10, 6])}",
        "",
        "## ユーザーの要求",
        user_prompt if user_prompt.strip() else (
            "属レベル相対存在量の積み上げ棒グラフ、α多様性グラフ、PCoA を生成してください。"
        ),
        "",
        "## 制約",
        "- matplotlib の Agg バックエンド: import matplotlib; matplotlib.use('Agg') を先頭に書く",
        "- 図は plt.savefig() で保存し plt.show() は使わない",
        "- タイトル・ラベルは英語で書く（日本語フォント依存を避けるため）",
        "- コードのみを出力する。説明文は不要",
        "- コードは ```python ... ``` で囲む",
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
