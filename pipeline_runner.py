#!/usr/bin/env python3
"""
pipeline_runner.py
==================
qiime2_agent.tool_run_qiime2_pipeline を Streamlit から呼び出すための
ラッパーモジュール。グローバル変数を注入して stdout をキャプチャする。
"""

import sys
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# qiime2_agent をインポート（if __name__ == "__main__" ガード済み）
sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent


# ─────────────────────────────────────────────────────────────────────────────
# 設定・結果の値オブジェクト
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """パイプライン実行パラメータ"""
    fastq_dir: str
    paired_end: bool = True
    trim_left_f: int = 17
    trim_left_r: int = 21
    trunc_len_f: int = 270
    trunc_len_r: int = 220
    metadata_path: str = ""
    classifier_path: str = ""
    n_threads: int = 4
    sampling_depth: int = 5000
    group_column: str = ""
    output_dir: str = ""   # 空なら ~/seq2pipe_results/<timestamp>/ を自動生成


@dataclass
class PipelineResult:
    """パイプライン実行結果"""
    success: bool
    output_dir: str
    export_dir: str
    log_lines: list = field(default_factory=list)
    error_message: str = ""
    completed_steps: list = field(default_factory=list)
    failed_steps: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# stdout キャプチャ用 Tee クラス
# ─────────────────────────────────────────────────────────────────────────────

class _Tee:
    """print() をオリジナル stdout と log_callback の両方に送る"""
    def __init__(self, original, callback):
        self._orig = original
        self._cb = callback
        self.encoding = getattr(original, 'encoding', 'utf-8')

    def write(self, s):
        try:
            self._orig.write(s)
        except Exception:
            pass
        line = s.rstrip('\n').rstrip()
        if line and self._cb:
            try:
                self._cb(line)
            except Exception:
                pass

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass

    def reconfigure(self, **kwargs):
        # sys.stdout.reconfigure() が呼ばれても壊れないようにするスタブ
        pass

    def isatty(self):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# パイプライン実行
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    config: PipelineConfig,
    log_callback: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """
    QIIME2 フルパイプラインを実行する。

    qiime2_agent のグローバル変数を注入してから
    tool_run_qiime2_pipeline を呼び出す。
    stdout を _Tee でキャプチャして log_callback に転送する。
    """
    # ── 出力ディレクトリの決定 ────────────────────────────────────────
    if config.output_dir:
        out_dir = Path(config.output_dir)
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path.home() / "seq2pipe_results" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # ── グローバル注入 ────────────────────────────────────────────────
    _agent.SESSION_OUTPUT_DIR = str(out_dir)
    _agent.SESSION_FIGURE_DIR = str(fig_dir)
    _agent.AUTO_YES = True   # input() をスキップして自律実行

    # ── stdout キャプチャ開始 ─────────────────────────────────────────
    log_lines = []

    def _log(line: str):
        log_lines.append(line)
        if log_callback:
            log_callback(line)

    orig_stdout = sys.stdout
    sys.stdout = _Tee(orig_stdout, _log)

    try:
        result_text = _agent.tool_run_qiime2_pipeline(
            fastq_dir=config.fastq_dir,
            paired_end=config.paired_end,
            trim_left_f=config.trim_left_f,
            trim_left_r=config.trim_left_r,
            trunc_len_f=config.trunc_len_f,
            trunc_len_r=config.trunc_len_r,
            metadata_path=config.metadata_path,
            classifier_path=config.classifier_path,
            n_threads=config.n_threads,
            sampling_depth=config.sampling_depth,
            group_column=config.group_column,
        )

        lines = result_text.splitlines()
        success = not any(l.startswith("❌") for l in lines[:5])

        return PipelineResult(
            success=success,
            output_dir=str(out_dir),
            export_dir=str(out_dir / "exported"),
            log_lines=log_lines,
            error_message="" if success else result_text[:500],
            completed_steps=[l for l in lines if l.startswith("✅")],
            failed_steps=[l for l in lines if l.startswith("❌")],
        )

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log(f"パイプラインエラー: {e}")
        return PipelineResult(
            success=False,
            output_dir=str(out_dir),
            export_dir=str(out_dir / "exported"),
            log_lines=log_lines,
            error_message=f"{e}\n{tb}",
        )

    finally:
        sys.stdout = orig_stdout


# ─────────────────────────────────────────────────────────────────────────────
# エクスポートファイルの分類
# ─────────────────────────────────────────────────────────────────────────────

def get_exported_files(export_dir: str) -> dict:
    """
    exported/ ディレクトリを走査してカテゴリ別ファイル辞書を返す。

    戻り値例:
    {
        "feature_table": ["/path/exported/feature-table.tsv"],
        "taxonomy":      ["/path/exported/taxonomy/taxonomy.tsv"],
        "denoising":     ["/path/exported/denoising_stats/stats.tsv"],
        "alpha":         ["/path/exported/alpha/shannon_vector/alpha-diversity.tsv", ...],
        "beta":          ["/path/exported/beta/bray_curtis.../distance-matrix.tsv", ...],
    }
    """
    base = Path(export_dir)
    result = {
        "feature_table": [],
        "taxonomy": [],
        "denoising": [],
        "alpha": [],
        "beta": [],
    }

    if not base.exists():
        return result

    # feature-table.tsv
    ft = base / "feature-table.tsv"
    if ft.exists():
        result["feature_table"].append(str(ft))

    # taxonomy/taxonomy.tsv
    tax = base / "taxonomy" / "taxonomy.tsv"
    if tax.exists():
        result["taxonomy"].append(str(tax))

    # denoising_stats/*.tsv
    ds = base / "denoising_stats"
    if ds.exists():
        result["denoising"] = [str(f) for f in ds.glob("*.tsv")]

    # alpha/<metric>/*.tsv
    alpha_base = base / "alpha"
    if alpha_base.exists():
        for metric_dir in sorted(alpha_base.iterdir()):
            result["alpha"] += [str(f) for f in metric_dir.glob("*.tsv")]

    # beta/<matrix>/*.tsv
    beta_base = base / "beta"
    if beta_base.exists():
        for matrix_dir in sorted(beta_base.iterdir()):
            result["beta"] += [str(f) for f in matrix_dir.glob("*.tsv")]

    return result
