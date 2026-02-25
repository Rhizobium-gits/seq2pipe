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
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from code_agent import run_manifest_agent, run_code_agent, CodeExecutionResult
from pipeline_runner import get_exported_files


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

_BANNER = r"""
 ███████╗███████╗ ██████╗ ██████╗
 ██╔════╝██╔════╝██╔═══██╗╚════██╗
 ███████╗█████╗  ██║   ██║  ▄╔═╝
 ╚════██║██╔══╝  ██║▄▄ ██║ ██╔╝
 ███████║███████╗╚██████╔╝██████╗
 ╚══════╝╚══════╝ ╚══▀▀═╝ ╚═════╝
 ██████╗ ██╗██████╗ ███████╗
 ██╔══██╗██║██╔══██╗██╔════╝
 ██████╔╝██║██████╔╝█████╗
 ██╔═══╝ ██║██╔═══╝ ██╔══╝
 ██║     ██║██║     ███████╗
 ╚═╝     ╚═╝╚═╝     ╚══════╝
"""

def _print_banner():
    import time

    RESET = "\033[0m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    CYAN  = "\033[96m"
    HIDE  = "\033[?25l"   # カーソル非表示
    SHOW  = "\033[?25h"   # カーソル表示
    CLR   = "\033[J"      # カーソル以降を消去

    # アニメーション: (カラーコード, 表示秒数)
    # 蛍光灯がチカチカしながら点灯するイメージ
    _FLICKER = [
        ("\033[90m",   0.09),   # 暗い（消灯）
        ("\033[96;1m", 0.07),   # 明るいシアン（点灯）
        ("\033[90m",   0.05),   # 暗い
        ("\033[96;1m", 0.08),   # 点灯
        ("\033[90m",   0.04),   # 暗い
        ("\033[2m",    0.05),   # うっすら
        ("\033[96;1m", 0.07),   # 点灯
        ("\033[90m",   0.03),   # 暗い
        ("\033[96m",   0.12),   # 安定（通常シアン）
    ]

    is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    if not is_tty:
        # パイプ・リダイレクト時はアニメーションなし
        print(CYAN + _BANNER + RESET)
    else:
        n_up = _BANNER.count("\n") + 1   # print() が加える改行分 +1
        UP   = f"\033[{n_up}A"

        sys.stdout.write(HIDE)
        sys.stdout.flush()
        try:
            # 最初は暗い状態で描画
            sys.stdout.write("\033[90m" + _BANNER + RESET)
            sys.stdout.flush()
            time.sleep(0.08)

            for color, delay in _FLICKER:
                sys.stdout.write(UP + CLR + color + _BANNER + RESET)
                sys.stdout.flush()
                time.sleep(delay)
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
# メイン
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="seq2pipe",
        description="seq2pipe — マニフェスト TSV と自然言語プロンプトで QIIME2 + 解析を自動実行",
    )
    parser.add_argument("--manifest",   help="マニフェスト TSV のパス")
    parser.add_argument("--metadata",   help="メタデータ TSV のパス（省略可）")
    parser.add_argument("--prompt",     help="やりたい解析の内容（省略時は対話入力）")
    parser.add_argument("--output-dir", help="出力ディレクトリ（省略時は ~/seq2pipe_results/<timestamp>/）")
    parser.add_argument("--model",      help="Ollama モデル名（省略時は自動選択）")
    parser.add_argument("--export-dir", help="既存の exported/ ディレクトリ（コード生成のみ実行）")
    args = parser.parse_args()

    _print_banner()

    model = _select_model(args.model or "")

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
        user_prompt = args.prompt or _ask("やりたい解析を入力してください", "")
        _hr()
        print(f"出力先: {output_dir}")
        _hr()
        print()

        result = run_code_agent(
            export_files=export_files,
            user_prompt=user_prompt,
            output_dir=str(Path(export_dir).parent),
            figure_dir=str(fig_dir),
            model=model,
            log_callback=_log,
            install_callback=_install_callback,
        )
        _print_result(result)
        return

    # ── マニフェストからフルパイプライン（メインフロー）──────────────
    print("マニフェスト TSV（sample-id / forward / reverse のパスを含む）を指定してください。")
    manifest_path = args.manifest or _ask("マニフェスト TSV のパス")
    if not manifest_path or not Path(manifest_path).exists():
        print(f"❌ ファイルが存在しません: {manifest_path}")
        sys.exit(1)

    metadata_path = args.metadata or _ask("メタデータ TSV のパス（省略可）", "")
    if metadata_path and not Path(metadata_path).exists():
        print(f"⚠️  メタデータファイルが見つかりません（スキップ）: {metadata_path}")
        metadata_path = ""

    print()
    print("やりたい解析を自然言語で入力してください。")
    print("例: 属レベルの積み上げ棒グラフ、Shannon 多様性のグループ比較、Bray-Curtis PCoA")
    user_prompt = args.prompt or _ask("解析内容", "")

    _hr()
    print(f"📂 マニフェスト : {manifest_path}")
    if metadata_path:
        print(f"📋 メタデータ  : {metadata_path}")
    print(f"💾 出力先      : {output_dir}")
    _hr()
    print()

    result = run_manifest_agent(
        manifest_path=manifest_path,
        user_prompt=user_prompt,
        output_dir=str(output_dir),
        figure_dir=str(fig_dir),
        metadata_path=metadata_path,
        model=model,
        log_callback=_log,
        install_callback=_install_callback,
    )

    _print_result(result)


if __name__ == "__main__":
    main()
