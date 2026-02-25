#!/usr/bin/env python3
"""
cli.py
======
seq2pipe ターミナル版エントリポイント。

使い方:
    ~/miniforge3/envs/qiime2/bin/python cli.py
    ~/miniforge3/envs/qiime2/bin/python cli.py --fastq-dir /path/to/fastq
"""

import sys
import argparse
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from pipeline_runner import PipelineConfig, run_pipeline, get_exported_files
from code_agent import run_code_agent


# ─────────────────────────────────────────────────────────────────────────────
# ターミナル表示ユーティリティ
# ─────────────────────────────────────────────────────────────────────────────

def _hr(char="─", width=60):
    print(char * width)

def _section(title: str):
    _hr()
    print(f"  {title}")
    _hr()

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
    if not val:
        return default
    return val.startswith("y")

def _log(line: str):
    print(line, flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Ollama 接続確認
# ─────────────────────────────────────────────────────────────────────────────

def _check_ollama() -> str:
    """Ollama の動作確認 + モデル選択。モデル名を返す。"""
    if not _agent.check_ollama_running():
        print("❌ Ollama が起動していません。")
        print("   別のターミナルで: ollama serve")
        sys.exit(1)

    models = _agent.get_available_models()
    if not models:
        print("❌ Ollama にモデルがありません。")
        print(f"   ollama pull {_agent.DEFAULT_MODEL}")
        sys.exit(1)

    if len(models) == 1:
        print(f"✅ モデル: {models[0]}")
        return models[0]

    print("利用可能なモデル:")
    for i, m in enumerate(models):
        print(f"  {i + 1}. {m}")
    raw = _ask(f"モデルを選択 (1-{len(models)})", default="1")
    try:
        idx = int(raw) - 1
        return models[max(0, min(idx, len(models) - 1))]
    except ValueError:
        return models[0]


# ─────────────────────────────────────────────────────────────────────────────
# パラメータ入力
# ─────────────────────────────────────────────────────────────────────────────

def _collect_params(args: argparse.Namespace) -> PipelineConfig:
    _section("📂 入力ファイル")

    fastq_dir = args.fastq_dir or _ask("FASTQ ディレクトリ")
    if not fastq_dir or not Path(fastq_dir).exists():
        print(f"❌ ディレクトリが存在しません: {fastq_dir}")
        sys.exit(1)

    metadata_path = args.metadata or _ask("メタデータ TSV (省略可)", "")
    classifier_path = args.classifier or _ask("分類器 .qza (省略可)", "")

    _section("⚙️  デノイジング設定")
    paired_end  = _ask_bool("ペアエンド?", True)
    trim_left_f = int(_ask("trim-left-f",  str(args.trim_left_f)))
    trunc_len_f = int(_ask("trunc-len-f",  str(args.trunc_len_f)))
    if paired_end:
        trim_left_r = int(_ask("trim-left-r", str(args.trim_left_r)))
        trunc_len_r = int(_ask("trunc-len-r", str(args.trunc_len_r)))
    else:
        trim_left_r, trunc_len_r = 0, 0

    _section("🌿 多様性解析設定")
    n_threads      = int(_ask("スレッド数",   str(args.n_threads)))
    sampling_depth = int(_ask("サンプリング深度", str(args.sampling_depth)))
    group_column   = args.group_column or _ask("グループ列名 (省略可)", "")

    return PipelineConfig(
        fastq_dir=fastq_dir,
        paired_end=paired_end,
        trim_left_f=trim_left_f,
        trim_left_r=trim_left_r,
        trunc_len_f=trunc_len_f,
        trunc_len_r=trunc_len_r,
        metadata_path=metadata_path,
        classifier_path=classifier_path,
        n_threads=n_threads,
        sampling_depth=sampling_depth,
        group_column=group_column,
        output_dir=args.output_dir or "",
    )


# ─────────────────────────────────────────────────────────────────────────────
# パッケージインストール許可コールバック
# ─────────────────────────────────────────────────────────────────────────────

def _install_callback(pkg: str) -> bool:
    return _ask_bool(f"\n⚠️  パッケージ '{pkg}' が必要です。インストールしますか?", True)


# ─────────────────────────────────────────────────────────────────────────────
# コード生成のみモード
# ─────────────────────────────────────────────────────────────────────────────

def _run_code_only_mode(args: argparse.Namespace, model: str):
    export_dir = args.export_dir or _ask("エクスポートディレクトリ (exported/)")
    if not export_dir or not Path(export_dir).exists():
        print(f"❌ ディレクトリが存在しません: {export_dir}")
        sys.exit(1)

    export_files = get_exported_files(export_dir)
    total = sum(len(v) for v in export_files.values())
    if total == 0:
        print(f"❌ エクスポートファイルが見つかりません: {export_dir}")
        sys.exit(1)

    print(f"✅ エクスポートファイル: {total} 件")
    for cat, paths in export_files.items():
        if paths:
            print(f"   [{cat}] {len(paths)} ファイル")

    _section("💬 解析プロンプト")
    print("LLM に行わせる解析を自然言語で入力してください。")
    print("(空 Enter でデフォルト: 属レベル棒グラフ・α多様性・PCoA)")
    user_prompt = _ask("プロンプト", "")

    fig_dir = str(Path(export_dir).parent / "figures")
    out_dir = str(Path(export_dir).parent)

    _section("🤖 コード生成・実行")
    result = run_code_agent(
        export_files=export_files,
        user_prompt=user_prompt,
        output_dir=out_dir,
        figure_dir=fig_dir,
        model=model,
        log_callback=_log,
        install_callback=_install_callback,
    )

    _print_code_result(result)


# ─────────────────────────────────────────────────────────────────────────────
# 結果表示
# ─────────────────────────────────────────────────────────────────────────────

def _print_code_result(result):
    _hr()
    if result.success:
        print(f"✅ コード実行成功！")
        if result.figures:
            print(f"📊 生成された図 ({len(result.figures)} 件):")
            for f in result.figures:
                print(f"   {f}")
    else:
        print(f"❌ コード実行失敗（{result.retry_count} 回試行）")
        if result.error_message:
            print("\n--- エラー ---")
            print(result.error_message[:500])
        print("\n--- 最後のコード ---")
        print(textwrap.indent(result.code[:1000], "  "))
    _hr()


# ─────────────────────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="seq2pipe",
        description="QIIME2 AI Agent — ターミナル版",
    )
    parser.add_argument("--fastq-dir",       help="FASTQ ディレクトリ")
    parser.add_argument("--metadata",        help="メタデータ TSV")
    parser.add_argument("--classifier",      help="分類器 .qza")
    parser.add_argument("--output-dir",      help="出力ディレクトリ（省略時は自動生成）")
    parser.add_argument("--trim-left-f",     type=int, default=17)
    parser.add_argument("--trim-left-r",     type=int, default=21)
    parser.add_argument("--trunc-len-f",     type=int, default=270)
    parser.add_argument("--trunc-len-r",     type=int, default=220)
    parser.add_argument("--n-threads",       type=int, default=4)
    parser.add_argument("--sampling-depth",  type=int, default=5000)
    parser.add_argument("--group-column",    default="")
    parser.add_argument("--prompt",          help="解析プロンプト（省略時は対話入力）")
    parser.add_argument("--export-dir",      help="コード生成のみモード用: exported/ のパス")
    parser.add_argument("--code-only",       action="store_true",
                        help="パイプラインをスキップしてコード生成のみ実行")
    parser.add_argument("--model",           help="Ollama モデル名")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  🧬 seq2pipe — QIIME2 AI Agent")
    print("=" * 60)
    print()

    # Ollama 確認 + モデル選択
    model = args.model or _check_ollama()

    # ── コード生成のみモード ──────────────────────────────────────────
    if args.code_only or args.export_dir:
        _run_code_only_mode(args, model)
        return

    # ── フルパイプラインモード ────────────────────────────────────────
    config = _collect_params(args)

    _section("🚀 QIIME2 パイプライン実行")
    pipeline_result = run_pipeline(config=config, log_callback=_log)

    _hr()
    if pipeline_result.success:
        print(f"✅ パイプライン完了 → {pipeline_result.output_dir}")
        for step in pipeline_result.completed_steps:
            print(f"   {step}")
    else:
        print(f"❌ パイプライン失敗")
        print(pipeline_result.error_message[:500])
        if not _ask_bool("失敗しましたが、コード生成を続けますか?", False):
            sys.exit(1)

    # ── 解析プロンプト ────────────────────────────────────────────────
    _section("💬 解析プロンプト")
    print("LLM に行わせる解析を自然言語で入力してください。")
    print("(空 Enter でデフォルト: 属レベル棒グラフ・α多様性・PCoA)")
    user_prompt = args.prompt or _ask("プロンプト", "")

    # ── コード生成・実行 ──────────────────────────────────────────────
    _section("🤖 コード生成・実行")
    export_files = get_exported_files(pipeline_result.export_dir)
    total = sum(len(v) for v in export_files.values())
    print(f"エクスポートファイル: {total} 件")

    fig_dir = str(Path(pipeline_result.output_dir) / "figures")
    code_result = run_code_agent(
        export_files=export_files,
        user_prompt=user_prompt,
        output_dir=pipeline_result.output_dir,
        figure_dir=fig_dir,
        metadata_path=config.metadata_path,
        model=model,
        log_callback=_log,
        install_callback=_install_callback,
    )

    _print_code_result(code_result)


if __name__ == "__main__":
    main()
