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

import sys
import csv
import gzip
import argparse
import datetime
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from code_agent import (
    run_code_agent, run_auto_agent, run_coding_agent, run_refinement_loop,
    CodeExecutionResult, AutoAgentResult,
)
from pipeline_runner import PipelineConfig, run_pipeline, get_exported_files
from chat_agent import run_terminal_chat


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


def _run_refinement_session(
    result: CodeExecutionResult,
    export_files: dict,
    output_dir: str,
    fig_dir,
    model: str,
    metadata_path: str = "",
):
    """
    解析完了後の振り返り・修正ループ。

    ユーザーが自然言語で修正指示を入力するたびに LLM がコードを修正・再実行する。
    空 Enter / 'quit' / 'done' で終了。
    """
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

    return params


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
    )
    _print_result(result)
    # 振り返り・修正モード（--auto でなければ起動）
    if not args.auto and result.success:
        _run_refinement_session(
            result=result,
            export_files=export_files,
            output_dir=pipeline_result.output_dir,
            fig_dir=fig_dir,
            model=model,
            metadata_path=metadata_path,
        )


if __name__ == "__main__":
    main()
