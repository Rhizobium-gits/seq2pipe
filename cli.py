#!/usr/bin/env python3
"""
cli.py
======
seq2pipe ターミナル版エントリポイント。

基本的な使い方:
    ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py

引数で指定する場合:
    ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py \\
        --manifest manifest.tsv \\
        --prompt "属レベルの積み上げ棒グラフと Shannon 多様性を作りたい"

既存エクスポートデータだけを使う場合:
    ~/miniforge3/envs/qiime2/bin/python ~/seq2pipe/cli.py \\
        --export-dir ~/seq2pipe_results/20240101_120000/exported/
"""

import re
import sys
import csv
import gzip
import argparse
import datetime
import statistics
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from code_agent import (
    run_code_agent, run_auto_agent, run_coding_agent, run_refinement_loop,
    CodeExecutionResult, AutoAgentResult,
)
from pipeline_runner import PipelineConfig, run_pipeline, get_exported_files
from chat_agent import run_terminal_chat
from report_generator import generate_html_report, generate_latex_report
from analysis import run_comprehensive_analysis


# ─────────────────────────────────────────────────────────────────────────────
# ターミナル表示ユーティリティ
# ─────────────────────────────────────────────────────────────────────────────

def _hr(width=60):
    print("─" * width)

def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val if val else default

def _ask_bool(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        val = input(f"{prompt} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return default if not val else val.startswith("y")

def _log(line: str):
    print(line, flush=True)

def _install_callback(pkg: str) -> bool:
    return _ask_bool(f"\n⚠️  パッケージ '{pkg}' が必要です。インストールしますか?", True)

def _print_result(result: CodeExecutionResult):
    _hr()
    if result.success:
        print("✅ 解析完了！")
        if result.figures:
            print(f"\n📊 生成された図 ({len(result.figures)} 件):")
            for f in result.figures:
                print(f"   {f}")
    else:
        print(f"❌ 実行失敗（{result.retry_count} 回試行）")
        if result.error_message:
            print(f"\nエラー:\n{result.error_message[:600]}")
        if result.code:
            print("\n--- 最後に生成されたコード（先頭50行）---")
            for line in result.code.splitlines()[:50]:
                print("  " + line)
    _hr()


def _print_auto_result(result: AutoAgentResult):
    _hr()
    n_rounds  = len(result.rounds)
    n_success = sum(1 for r in result.rounds if r.success)
    n_figs    = len(result.total_figures)

    if result.completed:
        print(f"✅ 自律解析完了！  ({n_rounds} ラウンド / {n_success} 成功 / 図 {n_figs} 件)")
    else:
        print(f"⏹  最大ラウンド数に到達  ({n_rounds} ラウンド / {n_success} 成功 / 図 {n_figs} 件)")

    if result.total_figures:
        print()
        print("📊 生成された図:")
        for f in result.total_figures:
            print(f"   {f}")
    _hr()


_REPORT_KEYWORDS = {
    "レポート", "report", "レポートを出力", "レポート出力", "レポート生成",
    "まとめ", "サマリー", "summary", "html", "レポートを作って",
    "レポートください", "レポートを作成", "レポートをください",
}

# PDF/LaTeX レポートを優先するキーワード
_PDF_REPORT_KEYWORDS = {
    "pdf", "PDF", "latex", "LaTeX", "tex", "TeX",
    "PDFレポート", "pdfレポート", "PDF出力", "pdf出力",
    "PDFで", "pdfで", "PDF形式", "pdf形式",
}


def _run_refinement_session(
    result: CodeExecutionResult,
    export_files: dict,
    output_dir: str,
    fig_dir,
    model: str,
    metadata_path: str = "",
    report_context: Optional[dict] = None,
):
    """
    解析完了後の振り返り・修正ループ。

    - 自然言語で修正指示 → LLM がコードを修正・再実行
    - 「レポート」と入力 → HTML レポートを生成
    - 空 Enter / 'quit' / 'done' で終了
    """
    report_context = report_context or {}

    # analysis.py が存在すれば読み込む（run_coding_agent が tool 経由で書き出した場合）
    current_code = result.code or ""
    analysis_py = Path(output_dir) / "analysis.py"
    if not current_code and analysis_py.exists():
        try:
            current_code = analysis_py.read_text(encoding="utf-8")
        except Exception:
            pass

    if not current_code:
        print("⚠️  修正モードを起動できません（解析コードが見つかりません）。")
        return

    # 現在の図一覧を表示
    fig_dir_path = Path(fig_dir)
    all_figs = sorted(
        list(fig_dir_path.glob("*.jpg")) + list(fig_dir_path.glob("*.png"))
        + list(fig_dir_path.glob("*.jpeg"))
    )

    _hr()
    print("  ✏️  振り返り・修正モード")
    print("  生成された図に対して自然言語で修正を指示できます。")
    print("  例: 「積み上げ棒グラフの凡例を外に出して」")
    print("      「PCoA の点を大きくして、サンプル名を表示して」")
    print("      「色盲対応のパレットに変えて」")
    print("      「Shannon 多様性のグラフにグループ比較の p 値を追加して」")
    print("  📄 レポート出力:")
    print("      HTML: 「レポート」と入力")
    print("      PDF:  「PDFレポート」または「PDF」と入力")
    print("  終了: 空 Enter / quit / done")
    _hr()

    if all_figs:
        print(f"\n📊 現在の図 ({len(all_figs)} 件):")
        for f in all_figs:
            print(f"   {f}")
        print()

    while True:
        try:
            feedback = input("✏️  修正内容> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not feedback or feedback.lower() in ("quit", "exit", "done", "終了", "q"):
            print("修正モードを終了します。")
            break

        # ── レポート生成コマンド ──────────────────────────────────────
        _fb_lower = feedback.strip().lower()
        _want_pdf = (
            _fb_lower in {k.lower() for k in _PDF_REPORT_KEYWORDS}
            or any(kw.lower() in _fb_lower for kw in ("pdf", "latex", "tex"))
        )
        _want_report = (
            _fb_lower in {k.lower() for k in _REPORT_KEYWORDS}
            or any(kw in feedback for kw in ("レポート", "まとめ", "report", "Report"))
            or _want_pdf
        )

        if _want_report:
            print()
            _report_kwargs = dict(
                fig_dir=str(fig_dir_path),
                output_dir=output_dir,
                fastq_dir=report_context.get("fastq_dir", ""),
                n_samples=report_context.get("n_samples", 0),
                dada2_params=report_context.get("dada2_params", {}),
                completed_steps=report_context.get("completed_steps", []),
                failed_steps=report_context.get("failed_steps", []),
                export_files=export_files,
                user_prompt=report_context.get("user_prompt", ""),
                model=model,
                log_callback=_log,
            )
            try:
                if _want_pdf:
                    print("📐 PDF レポートを生成しています（LaTeX）...")
                    report_path = generate_latex_report(**_report_kwargs)
                else:
                    print("📄 HTML レポートを生成しています...")
                    report_path = generate_html_report(**_report_kwargs)
                _hr()
                ext = Path(report_path).suffix.upper().lstrip(".")
                print(f"✅ {ext} レポート生成完了！")
                print(f"\n📄 ファイル: {report_path}")
                try:
                    subprocess.Popen(["open", report_path])
                    print("   (自動オープンを試みました)")
                except Exception:
                    pass
            except Exception as e:
                print(f"❌ レポート生成失敗: {e}")
            _hr()
            print()
            continue

        # ── 通常の修正指示 ────────────────────────────────────────────
        print()
        refined = run_refinement_loop(
            feedback=feedback,
            existing_code=current_code,
            export_files=export_files,
            output_dir=output_dir,
            figure_dir=str(fig_dir_path),
            metadata_path=metadata_path,
            model=model,
            log_callback=_log,
            install_callback=_install_callback,
        )

        _hr()
        if refined.success:
            print("✅ 修正完了！")
            if refined.figures:
                print(f"\n📊 更新された図 ({len(refined.figures)} 件):")
                for f in refined.figures:
                    print(f"   {f}")
            # 次の反復のためにコードを更新
            current_code = refined.code or current_code
        else:
            print(f"❌ 修正失敗（{refined.retry_count} 回試行）")
            if refined.error_message:
                print(f"\nエラー:\n{refined.error_message[:400]}")
        _hr()
        print()


def _select_mode() -> str:
    """起動モードをインタラクティブに選択する"""
    print("モードを選択してください:")
    print()
    print("  1. 解析モード        やりたい解析を自然言語で一回指定して実行")
    print("                       AI がファイルを読んで → コードを書いて → 実行 → エラー修正")
    print()
    print("  2. 自律エージェント  AI が自分でファイルを調べて包括的な解析を全自動実行")
    print("                       指示不要。動くコードができるまで自律的に修正を繰り返す")
    print()
    print("  3. 対話モード        実験の説明から始めて会話しながら解析を積み重ねる")
    print("                       「次はベータ多様性も見て」など自然な流れで進められる")
    print()
    choice = _ask("選択 (1/2/3)", "1")
    return choice.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Ollama 確認 + モデル選択
# ─────────────────────────────────────────────────────────────────────────────

def _select_model(preferred: str = "") -> str:
    if not _agent.check_ollama_running():
        print("❌ Ollama が起動していません。")
        print("   別のターミナルで: ollama serve")
        sys.exit(1)

    models = _agent.get_available_models()
    if not models:
        print(f"❌ Ollama にモデルがありません。")
        print(f"   ollama pull {_agent.DEFAULT_MODEL}")
        sys.exit(1)

    if preferred and preferred in models:
        print(f"✅ モデル: {preferred}")
        return preferred

    if len(models) == 1:
        print(f"✅ モデル: {models[0]}")
        return models[0]

    print("利用可能なモデル:")
    for i, m in enumerate(models):
        print(f"  {i + 1}. {m}")
    raw = _ask(f"モデルを選択 (1-{len(models)})", "1")
    try:
        return models[int(raw) - 1]
    except (ValueError, IndexError):
        return models[0]


# ─────────────────────────────────────────────────────────────────────────────
# 起動バナー
# ─────────────────────────────────────────────────────────────────────────────

# 行ごとのバナーテキスト
_BANNER_LINES = [
    r" ███████╗███████╗ ██████╗ ██████╗",
    r" ██╔════╝██╔════╝██╔═══██╗╚════██╗",
    r" ███████╗█████╗  ██║   ██║  ▄╔═╝",
    r" ╚════██║██╔══╝  ██║▄▄ ██║ ██╔╝",
    r" ███████║███████╗╚██████╔╝██████╗",
    r" ╚══════╝╚══════╝ ╚══▀▀═╝ ╚═════╝",
    r" ██████╗ ██╗██████╗ ███████╗",
    r" ██╔══██╗██║██╔══██╗██╔════╝",
    r" ██████╔╝██║██████╔╝█████╗",
    r" ██╔═══╝ ██║██╔═══╝ ██╔══╝",
    r" ██║     ██║██║     ███████╗",
    r" ╚═╝     ╚═╝╚═╝     ╚══════╝",
]

# 12 行を上から虹色グラデーション（赤→橙→黄→緑→シアン→青→マゼンタ）
_LINE_COLORS = [
    "\033[91m",   # bright red
    "\033[33m",   # orange
    "\033[93m",   # bright yellow
    "\033[92m",   # bright green
    "\033[92m",   # bright green
    "\033[96m",   # bright cyan
    "\033[96m",   # bright cyan
    "\033[94m",   # bright blue
    "\033[94m",   # bright blue
    "\033[95m",   # bright magenta
    "\033[95m",   # bright magenta
    "\033[91m",   # bright red (wrap)
]


def _print_banner():
    import time
    import random

    RESET = "\033[0m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    HIDE  = "\033[?25l"
    SHOW  = "\033[?25h"
    CLR   = "\033[J"

    # 空白以外の全セル (row, col) を収集
    all_cells = [
        (i, j)
        for i, line in enumerate(_BANNER_LINES)
        for j, ch in enumerate(line)
        if ch != ' '
    ]

    def _render(revealed: set, colored: set) -> str:
        """
        revealed: 表示済み（シアン白）
        colored : 最終色に移行済み
        """
        parts = ["\n"]
        for i, (line, line_color) in enumerate(zip(_BANNER_LINES, _LINE_COLORS)):
            row = ""
            for j, ch in enumerate(line):
                if ch == ' ':
                    row += ' '
                elif (i, j) in colored:
                    row += f"\033[1m{line_color}{ch}{RESET}"
                elif (i, j) in revealed:
                    row += f"\033[97;1m{ch}{RESET}"   # 白く光る
                else:
                    row += f"\033[90m·{RESET}"          # 未表示は暗いドット
            parts.append(row + "\n")
        return "".join(parts)

    n_up = len(_BANNER_LINES) + 1
    UP   = f"\033[{n_up}A"

    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    if not is_tty:
        sys.stdout.write(
            "\n" + "".join(
                f"\033[1m{col}{l}{RESET}\n"
                for l, col in zip(_BANNER_LINES, _LINE_COLORS)
            )
        )
        sys.stdout.flush()
    else:
        sys.stdout.write(HIDE)
        sys.stdout.flush()
        try:
            # ── Phase 1: 暗いドット状態で開始 ────────────────────────
            revealed: set = set()
            colored:  set = set()
            sys.stdout.write(_render(revealed, colored))
            sys.stdout.flush()
            time.sleep(0.12)

            # ── Phase 2: ランダム散布でドットが出現（白く光る）──────
            scatter = list(all_cells)
            random.shuffle(scatter)
            batch = max(1, len(scatter) // 30)   # 約30フレームで全点灯
            for start in range(0, len(scatter), batch):
                revealed.update(scatter[start : start + batch])
                sys.stdout.write(UP + CLR + _render(revealed, colored))
                sys.stdout.flush()
                time.sleep(0.035)

            time.sleep(0.08)

            # ── Phase 3: 斜め波でカラー化（左上→右下へコロコロ）────
            wave_order = sorted(all_cells, key=lambda rc: rc[0] + rc[1])
            batch = max(1, len(wave_order) // 25)   # 約25フレームで色づく
            for start in range(0, len(wave_order), batch):
                colored.update(wave_order[start : start + batch])
                sys.stdout.write(UP + CLR + _render(revealed, colored))
                sys.stdout.flush()
                time.sleep(0.028)

        except Exception:
            pass
        finally:
            sys.stdout.write(SHOW)
            sys.stdout.flush()

    print(f"  {DIM}sequence -> pipeline{RESET}")
    print()
    print(f"  {BOLD}QIIME2 AI Analysis Agent{RESET}")
    print(f"  {DIM}マニフェスト TSV と自然言語プロンプトで解析を自動化{RESET}")
    print()
    print("─" * 48)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# FASTQ 自動解析ユーティリティ
# ─────────────────────────────────────────────────────────────────────────────

# 代表的な 16S rRNA プライマー配列（フォワード側）
_16S_PRIMERS_FWD = {
    "27F":   "AGAGTTTGATCMTGGCTCAG",    # V1-V2
    "341F":  "CCTACGGGNGGCWGCAG",        # V3-V4
    "515F":  "GTGYCAGCMGCCGCGGTAA",      # V4
    "515Fn": "GTGCCAGCMGCCGCGGTAA",      # V4 (Caporaso)
    "799F":  "AACMGGATTAGATACCCKG",       # V5-V6
}

# 代表的な 16S rRNA プライマー配列（リバース側）
_16S_PRIMERS_REV = {
    "338R":  "TGCTGCCTCCCGTAGGAGT",      # V1-V2  (27F pair)
    "534R":  "ATTACCGCGGCTGCTGG",         # V1-V3  (27F pair)
    "785R":  "GACTACHVGGGTATCTAATCC",     # V3-V4  (341F pair)
    "806R":  "GGACTACNVGGGTWTCTAAT",      # V4     (515F pair)
    "806Rb": "GGACTACHVGGGTWTCTAAT",      # V4     (515F pair variant)
    "907R":  "CCGTCAATTCMTTTRAGTTT",      # V5     (515F pair)
    "926R":  "CCGTCAATTCMTTTRAGT",        # V5-V6  (515F pair variant)
    "1100R": "GGGTTGCGCTCGTTG",           # V6     (799F pair)
    "1391R": "GACGGGCGGTGTGTRCA",         # V7-V9
    "1492R": "TACGGYTACCTTGTTACGACTT",    # near-full (27F pair)
}

# よく使われるプライマーペアの対応関係
_PRIMER_PAIRS = {
    "27F":   ["338R", "534R", "1492R"],
    "341F":  ["785R", "806R"],
    "515F":  ["806R", "806Rb", "907R", "926R"],
    "515Fn": ["806R", "806Rb", "907R", "926R"],
    "799F":  ["1100R", "1391R"],
}

# IUPAC 曖昧塩基 → 正規表現変換テーブル
_IUPAC_RE = {
    "M": "[AC]", "R": "[AG]", "W": "[AT]", "S": "[CG]",
    "Y": "[CT]", "K": "[GT]", "V": "[ACG]", "H": "[ACT]",
    "D": "[AGT]", "B": "[CGT]", "N": "[ACGT]",
}


def _iupac_to_regex(seq: str) -> str:
    """IUPAC 曖昧塩基を含む配列を正規表現パターンに変換する。"""
    return "".join(_IUPAC_RE.get(c, c) for c in seq.upper())


def _iupac_bases(code: str) -> set:
    """IUPAC コードが許容する塩基セットを返す。"""
    _expand = {
        "A": {"A"}, "C": {"C"}, "G": {"G"}, "T": {"T"},
        "M": {"A", "C"}, "R": {"A", "G"}, "W": {"A", "T"},
        "S": {"C", "G"}, "Y": {"C", "T"}, "K": {"G", "T"},
        "V": {"A", "C", "G"}, "H": {"A", "C", "T"},
        "D": {"A", "G", "T"}, "B": {"C", "G", "T"}, "N": {"A", "C", "G", "T"},
    }
    return _expand.get(code.upper(), {"A", "C", "G", "T"})


def _primer_match_score(read_seq: str, primer_seq: str, check_len: int = 15) -> int:
    """リード先頭と primer の一致塩基数を返す（IUPAC 曖昧塩基考慮）。"""
    n = min(check_len, len(primer_seq), len(read_seq))
    return sum(1 for i in range(n) if read_seq[i].upper() in _iupac_bases(primer_seq[i]))


def _detect_seq_type(r1_files: list, r2_files: list,
                     sample_size: int = 500) -> dict:
    """
    FASTQ 先頭リードから 16S アンプリコン vs ショットガンメタゲノムを判定する。

    4 指標のスコアリング方式:
      - リード長の変動係数 (CV)
      - リード数
      - ユニーク配列の割合
      - 16S プライマー配列の一致率
    """
    result = {
        "seq_type": "unknown",
        "confidence": 0.0,
        "evidence": {
            "read_length_cv": 0.0,
            "read_count_est": 0,
            "unique_ratio": 0.0,
            "primer_match": "",
            "primer_match_rate": 0.0,
        },
        "reasons": [],
    }

    if not r1_files:
        return result

    # --- FASTQ リーダー（先頭 n リードの配列を返す）---
    def _read_seqs(fq_path, n=500):
        opener = gzip.open if str(fq_path).endswith(".gz") else open
        seqs = []
        try:
            with opener(fq_path, "rt") as f:
                for i, line in enumerate(f):
                    if i % 4 == 1:
                        seqs.append(line.strip())
                    if len(seqs) >= n:
                        break
        except Exception:
            pass
        return seqs

    seqs = _read_seqs(r1_files[0], sample_size)
    if not seqs:
        return result

    amplicon_score = 0.0
    shotgun_score = 0.0
    reasons = []

    # ── 指標 1: リード長の変動係数 (CV) ─────────────────────────────────
    lengths = [len(s) for s in seqs]
    mean_len = statistics.mean(lengths)
    stdev_len = statistics.stdev(lengths) if len(lengths) > 1 else 0.0
    cv = stdev_len / mean_len if mean_len > 0 else 0.0
    result["evidence"]["read_length_cv"] = round(cv, 4)

    if cv < 0.02:
        amplicon_score += 2.0
        reasons.append(f"リード長が均一 (CV={cv:.4f})")
    elif cv > 0.05:
        shotgun_score += 2.0
        reasons.append(f"リード長にばらつき (CV={cv:.4f})")
    else:
        amplicon_score += 0.5
        reasons.append(f"リード長のばらつきは中間的 (CV={cv:.4f})")

    # ── 指標 2: リード数の推定 ──────────────────────────────────────────
    opener = gzip.open if str(r1_files[0]).endswith(".gz") else open
    try:
        line_count = 0
        with opener(r1_files[0], "rt") as f:
            for _ in f:
                line_count += 1
        read_count = line_count // 4
    except Exception:
        read_count = 0
    result["evidence"]["read_count_est"] = read_count

    if read_count > 500_000:
        shotgun_score += 1.5
        reasons.append(f"リード数が多い ({read_count:,})")
    elif read_count < 200_000:
        amplicon_score += 1.0
        reasons.append(f"リード数がアンプリコン範囲 ({read_count:,})")
    else:
        reasons.append(f"リード数は中間的 ({read_count:,})")

    # ── 指標 3: ユニーク配列の割合 ──────────────────────────────────────
    unique_seqs = set(seqs)
    unique_ratio = len(unique_seqs) / len(seqs) if seqs else 0.0
    result["evidence"]["unique_ratio"] = round(unique_ratio, 4)

    if unique_ratio > 0.95:
        shotgun_score += 2.0
        reasons.append(f"ユニーク配列率が非常に高い ({unique_ratio:.1%})")
    elif unique_ratio < 0.70:
        amplicon_score += 1.5
        reasons.append(f"ユニーク配列率が低い ({unique_ratio:.1%})")
    else:
        reasons.append(f"ユニーク配列率は中間的 ({unique_ratio:.1%})")

    # ── 指標 4: 16S プライマー配列の検出（フォワード）─────────────────
    #   ミスマッチ許容マッチング: 15bp 中 12bp 以上一致で match とみなす
    _CHECK_LEN = 15
    _MIN_MATCH = 12  # 15bp 中 12bp 一致 → 最大 3 ミスマッチ許容

    best_fwd_primer = ""
    best_fwd_rate = 0.0
    check_seqs = seqs[:200]

    for name, primer_seq in _16S_PRIMERS_FWD.items():
        match_count = sum(
            1 for s in check_seqs
            if _primer_match_score(s, primer_seq, _CHECK_LEN) >= _MIN_MATCH
        )
        rate = match_count / len(check_seqs) if check_seqs else 0.0
        if rate > best_fwd_rate:
            best_fwd_rate = rate
            best_fwd_primer = name

    # ── 指標 4b: 16S プライマー配列の検出（リバース・R2から）──────────
    best_rev_primer = ""
    best_rev_rate = 0.0
    if r2_files:
        r2_seqs = _read_seqs(r2_files[0], 200)
        if r2_seqs:
            for name, primer_seq in _16S_PRIMERS_REV.items():
                match_count = sum(
                    1 for s in r2_seqs
                    if _primer_match_score(s, primer_seq, _CHECK_LEN) >= _MIN_MATCH
                )
                rate = match_count / len(r2_seqs) if r2_seqs else 0.0
                if rate > best_rev_rate:
                    best_rev_rate = rate
                    best_rev_primer = name

    best_rate = max(best_fwd_rate, best_rev_rate)
    result["evidence"]["primer_match"] = best_fwd_primer if best_fwd_rate > 0.3 else ""
    result["evidence"]["primer_match_rate"] = round(best_fwd_rate, 4)
    result["evidence"]["primer_rev_match"] = best_rev_primer if best_rev_rate > 0.3 else ""
    result["evidence"]["primer_rev_match_rate"] = round(best_rev_rate, 4)
    result["evidence"]["fwd_primer_len"] = len(_16S_PRIMERS_FWD.get(best_fwd_primer, "")) if best_fwd_rate > 0.3 else 0
    result["evidence"]["rev_primer_len"] = len(_16S_PRIMERS_REV.get(best_rev_primer, "")) if best_rev_rate > 0.3 else 0

    if best_rate > 0.7:
        amplicon_score += 3.0
        parts = []
        if best_fwd_rate > 0.3:
            parts.append(f"Fwd={best_fwd_primer} ({best_fwd_rate:.0%})")
        if best_rev_rate > 0.3:
            parts.append(f"Rev={best_rev_primer} ({best_rev_rate:.0%})")
        reasons.append(f"16S プライマーが高率で一致: {', '.join(parts)}")
    elif best_rate > 0.3:
        amplicon_score += 1.5
        reasons.append(f"16S プライマーが部分的に一致 ({best_fwd_primer} {best_fwd_rate:.0%})")
    else:
        shotgun_score += 0.5
        reasons.append("既知の 16S プライマー配列は検出されず")

    # ── 総合判定 ────────────────────────────────────────────────────────
    total = amplicon_score + shotgun_score
    if total == 0:
        result["seq_type"] = "unknown"
        result["confidence"] = 0.0
    elif amplicon_score > shotgun_score:
        result["seq_type"] = "amplicon"
        result["confidence"] = round(amplicon_score / total, 2)
    else:
        result["seq_type"] = "shotgun"
        result["confidence"] = round(shotgun_score / total, 2)

    result["reasons"] = reasons
    return result


def _detect_dada2_params(fastq_dir: str) -> dict:
    """
    FASTQ ディレクトリを解析して DADA2 パラメータを自動推定する。

    戻り値例:
    {
        "trim_left_f": 0,    # プライマー長が不明なので 0
        "trim_left_r": 0,
        "trunc_len_f": 260,  # リード長 * 0.87 (末尾品質低下分カット)
        "trunc_len_r": 200,
        "n_samples": 10,
        "read_len_f": 301,
        "read_len_r": 301,
        "sampling_depth": 5000,  # 最小リード数 * 0.8 を目安
    }
    """
    d = Path(fastq_dir).expanduser()
    r1_files = sorted(d.glob("*_R1*.fastq.gz")) + sorted(d.glob("*_R1*.fastq"))
    r2_files = sorted(d.glob("*_R2*.fastq.gz")) + sorted(d.glob("*_R2*.fastq"))

    def _sample_read_lengths(fq_path: Path, n: int = 200) -> list:
        try:
            opener = gzip.open if str(fq_path).endswith(".gz") else open
            lengths = []
            with opener(fq_path, "rt") as f:
                for i, line in enumerate(f):
                    if i % 4 == 1:
                        lengths.append(len(line.strip()))
                    if len(lengths) >= n:
                        break
            return lengths
        except Exception:
            return []

    def _count_reads(fq_path: Path) -> int:
        """ファイル全体のリード数を概算（先頭 4000 行 → 1000 リード）"""
        try:
            opener = gzip.open if str(fq_path).endswith(".gz") else open
            count = 0
            with opener(fq_path, "rt") as f:
                for i, _ in enumerate(f):
                    if i % 4 == 0:
                        count += 1
            return count
        except Exception:
            return 0

    params = {
        "trim_left_f": 0,
        "trim_left_r": 0,
        "trunc_len_f": 250,
        "trunc_len_r": 200,
        "n_samples": len(r1_files),
        "read_len_f": 0,
        "read_len_r": 0,
        "sampling_depth": 5000,
    }

    if not r1_files:
        return params

    # ── フォワードリード長を検出 ──────────────────────────────────────
    fwd_lengths = _sample_read_lengths(r1_files[0])
    if fwd_lengths:
        med_f = int(statistics.median(fwd_lengths))
        params["read_len_f"] = med_f
        # 末尾約 10~15% をカット（品質低下領域を除去）
        params["trunc_len_f"] = max(200, int(med_f * 0.87))

    # ── リバースリード長を検出 ────────────────────────────────────────
    if r2_files:
        rev_lengths = _sample_read_lengths(r2_files[0])
        if rev_lengths:
            med_r = int(statistics.median(rev_lengths))
            params["read_len_r"] = med_r
            # リバースは品質低下が早いので約 20% カット
            params["trunc_len_r"] = max(150, int(med_r * 0.80))

    # ── サンプリング深度の推定（全サンプルからリード数を取得）──────────
    read_counts = []
    for f in r1_files[:5]:  # 先頭 5 サンプルのみカウント（速度優先）
        n = _count_reads(f)
        if n > 0:
            read_counts.append(n)
    if read_counts:
        min_reads = min(read_counts)
        # 最少リード数の 80% を sampling_depth に（最低 1000）
        params["sampling_depth"] = max(1000, int(min_reads * 0.8))

    # ── シーケンスタイプ判定 (16S amplicon vs shotgun) ─────────────────
    seq_type_result = _detect_seq_type(r1_files, r2_files)
    params["seq_type"] = seq_type_result["seq_type"]
    params["seq_type_confidence"] = seq_type_result["confidence"]
    params["seq_type_evidence"] = seq_type_result["evidence"]
    params["seq_type_reasons"] = seq_type_result["reasons"]

    # ── プライマー自動検出 → trim_left / trunc_len を補正 ─────────────
    evidence = seq_type_result["evidence"]
    fwd_primer_len = evidence.get("fwd_primer_len", 0)
    rev_primer_len = evidence.get("rev_primer_len", 0)

    if fwd_primer_len > 0:
        params["trim_left_f"] = fwd_primer_len
        params["detected_fwd_primer"] = evidence.get("primer_match", "")
    if rev_primer_len > 0:
        params["trim_left_r"] = rev_primer_len
        params["detected_rev_primer"] = evidence.get("primer_rev_match", "")

    # プライマー除去後のリード長に基づいて trunc_len を再計算
    if fwd_primer_len > 0 and params["read_len_f"] > 0:
        effective_f = params["read_len_f"] - fwd_primer_len
        # プライマー除去後のリードの 90% を使用（品質低下分のみカット）
        params["trunc_len_f"] = max(200, min(int(effective_f * 0.95), effective_f))
    if rev_primer_len > 0 and params["read_len_r"] > 0:
        effective_r = params["read_len_r"] - rev_primer_len
        # リバースは品質低下が早いので 85% を使用
        params["trunc_len_r"] = max(150, min(int(effective_r * 0.90), effective_r))

    return params


def _find_classifier() -> str:
    """
    SILVA 分類器 QZA をよく使われる場所から自動探索する。
    見つかればパスを返す。見つからなければ空文字を返す。
    """
    candidates = [
        Path.home() / "seq2pipe" / "silva-138-99-nb-classifier.qza",
        Path.home() / "seq2pipe" / "silva-138-99-classifier.qza",
        Path.home() / "classifiers" / "silva-138-99-nb-classifier.qza",
        Path.home() / "silva-138-99-nb-classifier.qza",
        Path("/usr/local/share/qiime2/silva-138-99-nb-classifier.qza"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="seq2pipe",
        description="seq2pipe — マニフェスト TSV と自然言語プロンプトで QIIME2 + 解析を自動実行",
    )
    parser.add_argument("--fastq-dir",    help="FASTQ ファイルが入ったディレクトリのパス")
    parser.add_argument("--manifest",     help="（後方互換）マニフェスト TSV のパス。--fastq-dir 優先")
    parser.add_argument("--metadata",     help="メタデータ TSV のパス（省略可）")
    parser.add_argument("--prompt",       help="やりたい解析の内容（省略時は対話入力）")
    parser.add_argument("--output-dir",   help="出力ディレクトリ（省略時は ~/seq2pipe_results/<timestamp>/）")
    parser.add_argument("--model",        help="Ollama モデル名（省略時は自動選択）")
    parser.add_argument("--export-dir",   help="既存の exported/ ディレクトリ（コード生成のみ実行）")
    parser.add_argument("--auto",         action="store_true", help="自律エージェントモードで起動（完全無人実行）")
    parser.add_argument("--chat",         action="store_true", help="対話モードで起動（実験説明から会話で解析を進める）")
    parser.add_argument("--max-rounds",   type=int, default=15, help="自律エージェントの最大ラウンド数（デフォルト 15）")
    # DADA2 パラメータ（省略時は FASTQ から自動検出）
    parser.add_argument("--trim-left-f",  type=int, default=None, help="DADA2: フォワード先頭トリム長（デフォルト: 自動検出）")
    parser.add_argument("--trim-left-r",  type=int, default=None, help="DADA2: リバース先頭トリム長（デフォルト: 自動検出）")
    parser.add_argument("--trunc-len-f",  type=int, default=None, help="DADA2: フォワードトランケーション長（デフォルト: 自動検出）")
    parser.add_argument("--trunc-len-r",  type=int, default=None, help="DADA2: リバーストランケーション長（デフォルト: 自動検出）")
    parser.add_argument("--threads",      type=int, default=4,    help="スレッド数（デフォルト: 4）")
    parser.add_argument("--sampling-depth", type=int, default=None, help="多様性解析のサンプリング深度（デフォルト: 自動検出）")
    parser.add_argument("--classifier",   help="SILVA 分類器 QZA のパス（省略時は自動探索）")
    parser.add_argument("--force-amplicon", action="store_true",
                        help="シーケンスタイプ判定をスキップし 16S アンプリコンとして処理する")
    args = parser.parse_args()

    _print_banner()

    model = _select_model(args.model or "")

    # ── 対話モード（--chat）───────────────────────────────────────────────
    # --fastq-dir が指定されていれば先に QIIME2 パイプラインを実行してからチャットへ
    # --export-dir だけが指定されている場合は既存データから直接チャットへ
    if args.chat:
        if args.fastq_dir or args.manifest:
            # FASTQ ディレクトリが指定 → --chat は「モード3」として後続パイプライン経由で処理
            # args.chat を一時的に無効化し mode="3" として通常フローへ流す
            pass  # fall through to main pipeline with mode="3"
        else:
            # export-dir だけ → 既存データから直接チャット
            export_dir = args.export_dir or _ask("QIIME2 エクスポートディレクトリのパス")
            if not export_dir or not Path(export_dir).exists():
                print(f"❌ ディレクトリが存在しません: {export_dir}")
                sys.exit(1)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = args.output_dir or str(Path.home() / "seq2pipe_results" / ts)
            fig_dir_chat = Path(output_dir) / "figures"
            fig_dir_chat.mkdir(parents=True, exist_ok=True)
            run_terminal_chat(
                export_dir=export_dir,
                output_dir=output_dir,
                figure_dir=str(fig_dir_chat),
                model=model,
                log_callback=_log,
                install_callback=_install_callback,
            )
            return

    # モード選択（--auto / --chat フラグで省略可）
    if args.auto:
        mode = "2"
    elif args.chat:
        mode = "3"
    else:
        mode = _select_mode()

    # 出力ディレクトリを決定
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path.home() / "seq2pipe_results" / ts
    fig_dir = output_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # ── 既存エクスポートデータからコード生成のみ ─────────────────────
    if args.export_dir:
        export_dir = args.export_dir
        if not Path(export_dir).exists():
            print(f"❌ ディレクトリが存在しません: {export_dir}")
            sys.exit(1)
        export_files = get_exported_files(export_dir)
        if not any(export_files.values()):
            print(f"❌ エクスポートファイルが見つかりません: {export_dir}")
            sys.exit(1)

        print(f"📂 エクスポートデータ: {export_dir}")
        _hr()
        print(f"出力先: {output_dir}")
        _hr()
        print()

        # モード3: 対話モード
        if mode == "3":
            run_terminal_chat(
                export_dir=export_dir,
                output_dir=str(output_dir),
                figure_dir=str(fig_dir),
                model=model,
                log_callback=_log,
                install_callback=_install_callback,
            )
            return

        user_prompt = ""
        if mode != "2":
            user_prompt = args.prompt or _ask("やりたい解析を入力してください", "")
        else:
            print("🤖 自律エージェントモードで解析を開始します")
            print(f"   最大 {args.max_rounds} ステップ（Ctrl+C で中断）")
            print()

        result = run_coding_agent(
            export_files=export_files,
            user_prompt=user_prompt,
            output_dir=str(Path(export_dir).parent),
            figure_dir=str(fig_dir),
            model=model,
            max_steps=args.max_rounds * 4,   # ラウンド数×4 ステップ（list+read+write+run）
            log_callback=_log,
            install_callback=_install_callback,
        )
        _print_result(result)
        # 振り返り・修正モード（--auto でなければ起動）
        if not args.auto and result.success:
            _run_refinement_session(
                result=result,
                export_files=export_files,
                output_dir=str(Path(export_dir).parent),
                fig_dir=fig_dir,
                model=model,
                metadata_path=args.metadata or "",
                report_context={
                    "fastq_dir": "",
                    "n_samples": 0,
                    "dada2_params": {},
                    "completed_steps": [],
                    "failed_steps": [],
                    "user_prompt": user_prompt,
                },
            )
        return

    # ── フルパイプライン: FASTQ ディレクトリを直接指定 ───────────────
    if not args.fastq_dir and not args.manifest and not args.auto:
        print("FASTQ ファイルが入ったディレクトリのパスを指定してください。")
        print("（例: /Users/yourname/input  または  ~/microbiome-data）")
    fastq_dir_raw = args.fastq_dir or args.manifest or _ask("FASTQ ディレクトリのパス")
    fastq_dir = str(Path(fastq_dir_raw).expanduser().resolve())
    if not Path(fastq_dir).exists():
        print(f"❌ ディレクトリが存在しません: {fastq_dir}")
        sys.exit(1)

    # --auto モードではメタデータは省略（対話なし）
    if args.auto:
        metadata_path = args.metadata or ""
    else:
        metadata_path = args.metadata or _ask("メタデータ TSV のパス（省略可）", "")
    if metadata_path and not Path(metadata_path).exists():
        print(f"⚠️  メタデータファイルが見つかりません（スキップ）: {metadata_path}")
        metadata_path = ""

    user_prompt = ""
    if mode != "2":
        print()
        print("やりたい解析を自然言語で入力してください。")
        print("例: 属レベルの積み上げ棒グラフ、Shannon 多様性のグループ比較、Bray-Curtis PCoA")
        user_prompt = args.prompt or _ask("解析内容", "")

    # ── DADA2 パラメータ: CLI 指定 → 自動検出 の優先順位で決定 ──────
    print()
    print("🔍 FASTQ を解析中...")
    auto_params = _detect_dada2_params(fastq_dir)

    # ── シーケンスタイプ判定結果のチェック ─────────────────────────────
    _seq_type = auto_params.get("seq_type", "unknown")
    _seq_conf = auto_params.get("seq_type_confidence", 0.0)
    _seq_reasons = auto_params.get("seq_type_reasons", [])
    _seq_evidence = auto_params.get("seq_type_evidence", {})

    if _seq_type == "shotgun" and not args.force_amplicon:
        print()
        print("=" * 60)
        print("  ショットガンメタゲノムデータの可能性があります")
        print("=" * 60)
        print(f"  判定: {_seq_type} (確信度: {_seq_conf:.0%})")
        print()
        print("  判定根拠:")
        for reason in _seq_reasons:
            print(f"    - {reason}")
        print()
        print("  seq2pipe は 16S rRNA アンプリコン解析専用です。")
        print("  ショットガンデータでは正しい結果が得られません。")
        print("=" * 60)
        print()

        if args.auto:
            print("--auto モードではショットガンデータの処理を中断します。")
            print("16S アンプリコンデータであることが確実な場合は")
            print("--force-amplicon フラグを使用してください。")
            sys.exit(1)
        else:
            if not _ask_bool("それでも 16S アンプリコンとして処理を続行しますか?", False):
                print("中断しました。")
                sys.exit(0)
            print()

    elif _seq_type == "amplicon":
        _primer_fwd = _seq_evidence.get("primer_match", "")
        _primer_rev = _seq_evidence.get("primer_rev_match", "")
        _fwd_len = _seq_evidence.get("fwd_primer_len", 0)
        _rev_len = _seq_evidence.get("rev_primer_len", 0)
        if _primer_fwd or _primer_rev:
            parts = []
            if _primer_fwd:
                parts.append(f"Fwd={_primer_fwd} ({_fwd_len}bp)")
            if _primer_rev:
                parts.append(f"Rev={_primer_rev} ({_rev_len}bp)")
            print(f"  ✅ 16S アンプリコンデータを検出 (確信度: {_seq_conf:.0%})")
            print(f"  🧬 プライマー自動検出: {', '.join(parts)}")
            print(f"     → trim_left を自動設定: F={_fwd_len} R={_rev_len}")
        else:
            print(f"  ✅ 16S アンプリコンデータを検出 (確信度: {_seq_conf:.0%})")
            print(f"  ⚠️  プライマー配列は検出されず — trim_left=0 のまま")

    n_samples   = auto_params["n_samples"]
    read_len_f  = auto_params["read_len_f"]
    read_len_r  = auto_params["read_len_r"]

    trim_left_f  = args.trim_left_f  if args.trim_left_f  is not None else auto_params["trim_left_f"]
    trim_left_r  = args.trim_left_r  if args.trim_left_r  is not None else auto_params["trim_left_r"]
    trunc_len_f  = args.trunc_len_f  if args.trunc_len_f  is not None else auto_params["trunc_len_f"]
    trunc_len_r  = args.trunc_len_r  if args.trunc_len_r  is not None else auto_params["trunc_len_r"]
    sampling_dep = args.sampling_depth if args.sampling_depth is not None else auto_params["sampling_depth"]
    n_threads    = args.threads

    _hr()
    print(f"📂 FASTQ ディレクトリ : {fastq_dir}")
    print(f"   サンプル数         : {n_samples} サンプル（ペアエンド）")
    if read_len_f:
        print(f"   リード長 (F/R)     : {read_len_f}bp / {read_len_r or '?'}bp")
    print(f"   シーケンスタイプ   : {_seq_type} (確信度: {_seq_conf:.0%})")
    if metadata_path:
        print(f"📋 メタデータ         : {metadata_path}")
    print(f"💾 出力先             : {output_dir}")
    print(f"🧬 DADA2 パラメータ:")
    print(f"   trim_left  F={trim_left_f}  R={trim_left_r}")
    print(f"   trunc_len  F={trunc_len_f}  R={trunc_len_r}")
    print(f"   sampling_depth={sampling_dep}  threads={n_threads}")
    if mode == "2":
        print(f"🤖 モード              : 自律エージェント（最大 {args.max_rounds} ラウンド）")
    _hr()
    print()

    # --auto でない場合は続行確認
    if not args.auto:
        if not _ask_bool("上記の設定で解析を開始しますか?", True):
            print("中断しました。")
            sys.exit(0)
        print()

    # ── SILVA 分類器パスを決定 ────────────────────────────────────────
    classifier_path = ""
    if args.classifier:
        if Path(args.classifier).exists():
            classifier_path = args.classifier
        else:
            print(f"⚠️  指定された分類器が見つかりません: {args.classifier}")
    if not classifier_path:
        classifier_path = _find_classifier()
    if classifier_path:
        print(f"🔬 SILVA 分類器    : {classifier_path}")
    else:
        print("⚠️  SILVA 分類器が見つかりません。分類学的注釈をスキップします。")
        print("   taxonomy を有効にするには以下を実行してください：")
        print("   wget -O ~/seq2pipe/silva-138-99-nb-classifier.qza \\")
        print("     https://data.qiime2.org/classifiers/sklearn-1.4.2/silva/silva-138-99-nb-classifier.qza")

    # ── STEP 1: QIIME2 パイプライン実行（既存の実証済みコードを使用）──
    print("─" * 48)
    print("  🚀 STEP 1/2 : QIIME2 パイプライン実行中")
    print("─" * 48)
    config = PipelineConfig(
        fastq_dir=fastq_dir,
        paired_end=True,
        trim_left_f=trim_left_f,
        trim_left_r=trim_left_r,
        trunc_len_f=trunc_len_f,
        trunc_len_r=trunc_len_r,
        metadata_path=metadata_path,
        classifier_path=classifier_path,
        n_threads=n_threads,
        sampling_depth=sampling_dep,
        output_dir=str(output_dir),
    )
    pipeline_result = run_pipeline(config=config, log_callback=_log)

    if not pipeline_result.success:
        print(f"\n❌ パイプライン失敗: {pipeline_result.error_message[:400]}")
        sys.exit(1)

    print(f"\n✅ パイプライン完了 → {pipeline_result.output_dir}")
    print()

    # ── STEP 1.5: 包括的解析（LLM 不要・確定的に図を生成）──────────────
    print("─" * 48)
    print("  📊 STEP 1.5 : 包括的解析・可視化（確定的処理）")
    print("─" * 48)
    analysis_summary = {}
    try:
        result_1_5 = run_comprehensive_analysis(
            export_dir=pipeline_result.export_dir,
            figure_dir=str(fig_dir),
            session_dir=pipeline_result.output_dir,
            log_callback=_log,
        )
        # 後方互換: 旧版はリストを返す、新版は (list, dict) を返す
        if isinstance(result_1_5, tuple):
            analysis_figs, analysis_summary = result_1_5
        else:
            analysis_figs = result_1_5
            analysis_summary = {}
        if analysis_figs:
            print(f"\n✅ 包括的解析完了: {len(analysis_figs)} 件の図を生成")
        else:
            print("\n⚠️  包括的解析: 図が生成されませんでした")
    except Exception as e:
        print(f"\n⚠️  包括的解析でエラー（パイプラインは継続）: {e}")
    print()

    # ── モード 3: パイプライン完了後に対話チャットへ移行 ──────────────
    if mode == "3":
        print("─" * 48)
        print("  💬 STEP 2/2 : 対話モード（チャット）")
        print("─" * 48)
        run_terminal_chat(
            export_dir=pipeline_result.export_dir,
            output_dir=pipeline_result.output_dir,
            figure_dir=str(fig_dir),
            model=model,
            log_callback=_log,
            install_callback=_install_callback,
        )
        return

    # ── STEP 2: LLM による解析コード生成・実行 ────────────────────────
    print("─" * 48)
    step2_label = "自律エージェント" if mode == "2" else "LLM 解析コード生成・実行"
    print(f"  🤖 STEP 2/2 : {step2_label}")
    print("─" * 48)
    export_files = get_exported_files(pipeline_result.export_dir)
    total = sum(len(v) for v in export_files.values())
    print(f"エクスポートファイル: {total} 件")
    for cat, paths in export_files.items():
        if paths:
            print(f"  [{cat}] {len(paths)} ファイル")
    print()

    if mode == "2":
        print("🤖 自律エージェントモードで解析を開始します")
        print(f"   最大 {args.max_rounds * 3} ステップ（Ctrl+C で中断）")
        print()

    result = run_coding_agent(
        export_files=export_files,
        user_prompt=user_prompt,          # mode 1: ユーザー指定 / mode 2: ""（自律）
        output_dir=pipeline_result.output_dir,
        figure_dir=str(fig_dir),
        metadata_path=metadata_path,
        model=model,
        max_steps=args.max_rounds * 4,    # ラウンド数×4 ステップ（list+read+write+run）
        log_callback=_log,
        install_callback=_install_callback,
        analysis_summary=analysis_summary if mode == "2" else None,
    )
    _report_ctx = {
        "fastq_dir": fastq_dir,
        "n_samples": n_samples,
        "dada2_params": {
            "trim_left_f": trim_left_f,
            "trim_left_r": trim_left_r,
            "trunc_len_f": trunc_len_f,
            "trunc_len_r": trunc_len_r,
            "sampling_depth": sampling_dep,
            "n_threads": n_threads,
        },
        "completed_steps": getattr(pipeline_result, "completed_steps", []),
        "failed_steps": getattr(pipeline_result, "failed_steps", []),
        "user_prompt": user_prompt,
    }

    _print_result(result)

    # --auto モード: 解析完了後に HTML レポートを自動生成
    if args.auto and result.success:
        print()
        print("─" * 48)
        print("  📄 STEP 3/3 : レポート自動生成")
        print("─" * 48)
        try:
            report_path = generate_html_report(
                fig_dir=str(fig_dir),
                output_dir=pipeline_result.output_dir,
                fastq_dir=fastq_dir,
                n_samples=n_samples,
                dada2_params=_report_ctx["dada2_params"],
                completed_steps=_report_ctx["completed_steps"],
                failed_steps=_report_ctx["failed_steps"],
                export_files=export_files,
                user_prompt=user_prompt,
                model=model,
                log_callback=_log,
            )
            print(f"✅ HTML レポート生成完了: {report_path}")
            try:
                import subprocess as _sp
                _sp.Popen(["open", report_path])
            except Exception:
                pass
        except Exception as e:
            print(f"⚠️  レポート生成失敗（解析結果は保存済み）: {e}")

    # 振り返り・修正モード（--auto でなければ起動）
    if not args.auto and result.success:
        _run_refinement_session(
            result=result,
            export_files=export_files,
            output_dir=pipeline_result.output_dir,
            fig_dir=fig_dir,
            model=model,
            metadata_path=metadata_path,
            report_context=_report_ctx,
        )


if __name__ == "__main__":
    main()
