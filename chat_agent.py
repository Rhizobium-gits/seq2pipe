#!/usr/bin/env python3
"""
chat_agent.py
=============
対話型解析エージェント。

実験系やデータ形式を自然言語で説明しながら、
会話をしつつどんどん解析を進めていくモード。

使い方:
    from chat_agent import InteractiveSession

    session = InteractiveSession(
        export_dir="~/data/exported",
        output_dir="~/analysis/output",
        figure_dir="~/analysis/figures",
        model="qwen2.5-coder:7b",
    )

    # 実験の説明
    print(session.setup("マウス腸内フローラの16Sデータ。抗生物質投与群と対照群の比較"))

    # 対話ループ
    result = session.chat("まずアルファ多様性を群間で比較して")
    print(result["text"])   # 自然言語サマリー
    print(result["figures"]) # 生成された図のパス一覧
"""

from __future__ import annotations

import re
import glob
import json
import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import qiime2_agent as _agent
from code_agent import run_code_agent, CodeExecutionResult


# ─────────────────────────────────────────────────────────────────────────────
# ファイル自動発見
# ─────────────────────────────────────────────────────────────────────────────

_FILE_PATTERNS = {
    "feature_table": ["feature-table.tsv", "feature_table.tsv"],
    "taxonomy":      ["taxonomy/taxonomy.tsv"],
    "denoising":     ["denoising_stats/stats.tsv", "denoising-stats/stats.tsv"],
    "alpha":         ["alpha/**/*.tsv"],
    "beta":          ["beta/**/*.tsv"],
    "metadata":      ["metadata.tsv", "sample-metadata.tsv", "sample_metadata.tsv"],
}


def discover_export_files(export_dir: str | Path) -> dict[str, list[str]]:
    """エクスポートディレクトリをスキャンしてファイルを分類する。"""
    base = Path(export_dir).expanduser()
    result: dict[str, list[str]] = {}
    for category, patterns in _FILE_PATTERNS.items():
        found: list[str] = []
        for pat in patterns:
            found.extend(glob.glob(str(base / pat), recursive=True))
        if found:
            result[category] = sorted(set(found))
    return result


def _file_summary(export_files: dict[str, list[str]]) -> str:
    lines = []
    for cat, paths in export_files.items():
        for p in paths:
            lines.append(f"  [{cat}] {Path(p).name}  ({p})")
    return "\n".join(lines) if lines else "  （ファイルが見つかりませんでした）"


# ─────────────────────────────────────────────────────────────────────────────
# セッションコンテキスト
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisFinding:
    """1ターンの解析結果。コンテキスト蓄積に使用。"""
    step: int
    user_request: str
    analysis_description: str    # 実際に何の解析をしたか
    result_summary: str          # LLM による自然言語サマリー
    figures: list[str] = field(default_factory=list)
    success: bool = True


@dataclass
class SessionContext:
    experiment_description: str = ""
    groups: list[str] = field(default_factory=list)
    data_type: str = ""
    notes: str = ""                            # 追加のメモ（ユーザーから得た情報）
    findings: list[AnalysisFinding] = field(default_factory=list)
    all_figures: list[str] = field(default_factory=list)

    def to_context_block(self) -> str:
        """コード生成プロンプトに挿入する実験コンテキスト文字列。"""
        parts = ["## EXPERIMENT CONTEXT (use this to guide analysis)"]
        if self.experiment_description:
            parts.append(f"Experiment: {self.experiment_description}")
        if self.data_type:
            parts.append(f"Data type: {self.data_type}")
        if self.groups:
            parts.append(f"Groups: {', '.join(self.groups)}")
        if self.notes:
            parts.append(f"Notes: {self.notes}")

        if self.findings:
            parts.append("\n## PREVIOUS ANALYSES (results so far)")
            for f in self.findings[-4:]:   # 直近4件まで参照
                parts.append(f"  Step {f.step}: {f.analysis_description}")
                if f.result_summary:
                    # 先頭180文字だけ（プロンプト肥大化防止）
                    parts.append(f"  → {f.result_summary[:180]}")
                if f.figures:
                    parts.append(f"  → Figures: {', '.join(Path(p).name for p in f.figures)}")

        return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# インタラクティブセッション
# ─────────────────────────────────────────────────────────────────────────────

class InteractiveSession:
    """
    対話型マイクロバイオーム解析セッション。

    1. setup()  — 実験の説明を受けてコンテキストを構築
    2. chat()   — 解析指示を受けてコードを生成・実行・結果をサマリー
    3. get_summary() — セッション全体のサマリー
    """

    def __init__(
        self,
        export_dir: str | Path,
        output_dir: str | Path,
        figure_dir: str | Path,
        model: str | None = None,
        log_callback=None,
        install_callback=None,
    ):
        self.export_dir  = Path(export_dir).expanduser()
        self.output_dir  = Path(output_dir).expanduser()
        self.figure_dir  = Path(figure_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.figure_dir.mkdir(parents=True, exist_ok=True)

        self.model            = model or _agent.DEFAULT_MODEL
        self._log             = log_callback or (lambda m: None)
        self._install_cb      = install_callback
        self.ctx              = SessionContext()
        self._llm_history: list[dict] = []   # LLM 会話履歴（サマリー用）
        self._step            = 0

        # ファイル自動発見
        self.export_files = discover_export_files(self.export_dir)

    # ── 1. setup ──────────────────────────────────────────────────────────────

    def setup(self, description: str) -> str:
        """
        実験の説明を受け取り、コンテキストを構築する。
        Returns: アシスタントからのウェルカムメッセージ（自然言語）
        """
        self.ctx.experiment_description = description

        # LLM にコンテキスト解析 + ウェルカムメッセージを生成させる
        n_files = sum(len(v) for v in self.export_files.values())
        file_block = _file_summary(self.export_files)

        prompt = (
            "You are a microbiome bioinformatics assistant.\n"
            "The user has described their experiment. Respond in the SAME LANGUAGE the user used.\n\n"
            f"User's description:\n{description}\n\n"
            f"Available export files ({n_files} files found):\n{file_block}\n\n"
            "Please:\n"
            "1. Briefly confirm what you understood (experiment type, groups, data).\n"
            "2. List the key files available.\n"
            "3. Suggest 2-3 concrete analysis options to start with.\n"
            "Keep it under 200 words. Be friendly and practical."
        )

        reply = self._call_llm_simple(prompt)

        # 履歴に追加
        self._llm_history.append({"role": "user", "content": description})
        self._llm_history.append({"role": "assistant", "content": reply})

        return reply

    # ── 2. chat ───────────────────────────────────────────────────────────────

    def chat(self, user_input: str) -> dict:
        """
        ユーザーの解析指示を受けて、コードを生成・実行し結果をサマリーする。

        Returns:
            {
                "text":    str,          # 自然言語サマリー + 次の提案
                "figures": list[str],    # 生成された図のパス
                "step":    int,
                "success": bool,
            }
        """
        self._step += 1
        self._llm_history.append({"role": "user", "content": user_input})
        self._log(f"\n🔬 [Step {self._step}] 解析実行中...")

        # コード生成用プロンプト（コンテキスト付き）
        code_prompt = self._build_code_prompt(user_input)

        # コード生成・実行
        result = run_code_agent(
            export_files=self.export_files,
            user_prompt=code_prompt,
            output_dir=str(self.output_dir),
            figure_dir=str(self.figure_dir),
            model=self.model,
            max_retries=3,
            log_callback=self._log,
            install_callback=self._install_cb,
        )

        # 結果のサマリー（自然言語）
        summary_text = self._summarize(user_input, result)

        # コンテキストに記録
        finding = AnalysisFinding(
            step=self._step,
            user_request=user_input,
            analysis_description=user_input[:120],
            result_summary=summary_text,
            figures=result.figures,
            success=result.success,
        )
        self.ctx.findings.append(finding)
        self.ctx.all_figures.extend(result.figures)

        self._llm_history.append({"role": "assistant", "content": summary_text})

        return {
            "text":    summary_text,
            "figures": result.figures,
            "step":    self._step,
            "success": result.success,
        }

    # ── 3. summary ────────────────────────────────────────────────────────────

    def get_summary(self) -> str:
        """セッション全体のサマリーを返す。"""
        if not self.ctx.findings:
            return "まだ解析は実行されていません。"

        lines = [
            "=" * 55,
            "📊 解析セッション サマリー",
            "=" * 55,
            f"実験: {self.ctx.experiment_description[:120]}",
            f"総ステップ数: {self._step}",
            f"生成された図: {len(self.ctx.all_figures)} 件",
            "",
        ]
        for f in self.ctx.findings:
            icon = "✅" if f.success else "❌"
            lines.append(f"{icon} Step {f.step}: {f.user_request[:70]}")
            if f.figures:
                for fig in f.figures:
                    lines.append(f"     📊 {Path(fig).name}")
        lines.append("")
        lines.append(f"図の保存先: {self.figure_dir}")
        lines.append("=" * 55)
        return "\n".join(lines)

    # ── 内部メソッド ──────────────────────────────────────────────────────────

    def _build_code_prompt(self, user_request: str) -> str:
        """コンテキスト情報を含んだコード生成用プロンプト。"""
        ctx_block = self.ctx.to_context_block()
        if ctx_block:
            return f"{ctx_block}\n\n## CURRENT ANALYSIS REQUEST\n{user_request}"
        return user_request

    def _summarize(self, user_request: str, result: CodeExecutionResult) -> str:
        """解析結果を自然言語でサマリーし、次のステップを提案する。"""
        if not result.success and not result.figures:
            return (
                f"⚠️ 解析中にエラーが発生しました。\n"
                f"エラー内容: {(result.error_message or '')[:300]}\n\n"
                "プロンプトを変えるか、別のアプローチを試してみてください。"
            )

        fig_names = [Path(f).name for f in result.figures]
        stdout_snip = (result.stdout or "")[:400]

        # LLM にサマリーを生成させる
        summary_prompt = (
            f"Microbiome analysis result summary.\n\n"
            f"User requested: \"{user_request}\"\n"
            f"Figures generated: {', '.join(fig_names) if fig_names else 'none'}\n"
            f"Script output:\n{stdout_snip}\n\n"
            f"Previous context:\n{self.ctx.to_context_block()[:400]}\n\n"
            "Write a concise summary (3-5 sentences) in the SAME LANGUAGE the user uses:\n"
            "1. What was analyzed and what the result shows\n"
            "2. Any notable biological interpretation\n"
            "3. Suggest 1-2 natural next analysis steps"
        )

        summary = self._call_llm_simple(summary_prompt)

        # 図リストを末尾に追加
        if fig_names:
            summary += "\n\n📊 生成された図:\n" + "\n".join(f"  • {n}" for n in fig_names)

        return summary

    def _call_llm_simple(self, prompt: str) -> str:
        """サマリー・ウェルカム用の単純な LLM 呼び出し。"""
        try:
            resp = _agent.call_ollama(
                [{"role": "user", "content": prompt}],
                self.model,
            )
            return resp.get("content", "（応答なし）").strip()
        except Exception as e:
            return f"（LLM 呼び出しエラー: {e}）"


# ─────────────────────────────────────────────────────────────────────────────
# CLIターミナルモード（スタンドアロン実行用）
# ─────────────────────────────────────────────────────────────────────────────

_HELP_TEXT = """
コマンド一覧:
  summary  — これまでの解析をまとめて表示
  figures  — 生成された図のパスを一覧表示
  context  — 現在の実験コンテキストを確認
  help     — このヘルプを表示
  exit     — 終了
"""


def run_terminal_chat(
    export_dir: str | Path,
    output_dir: str | None = None,
    figure_dir: str | None = None,
    model: str | None = None,
    log_callback=None,
    install_callback=None,
):
    """ターミナルでの対話型解析セッションを実行する。"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path.home() / "seq2pipe_results" / ts
    out_dir = output_dir or str(base / "output")
    fig_dir = figure_dir or str(base / "figures")

    def _log(m: str):
        # コード生成の詳細ログは薄く表示
        if m.startswith("  "):
            print(f"\033[2m{m}\033[0m", flush=True)
        else:
            print(m, flush=True)

    if log_callback:
        _log = log_callback  # noqa: F811

    def _install_cb(pkg: str) -> bool:
        ans = input(f"\n⚠️  パッケージ '{pkg}' が必要です。インストールしますか? [Y/n]: ").strip().lower()
        return ans != "n"

    _cb = install_callback or _install_cb

    print()
    print("─" * 55)
    print("🧬  seq2pipe  対話型解析モード")
    print("─" * 55)
    print(f"  エクスポートデータ: {export_dir}")
    print(f"  図の出力先        : {fig_dir}")
    print("─" * 55)

    session = InteractiveSession(
        export_dir=export_dir,
        output_dir=out_dir,
        figure_dir=fig_dir,
        model=model,
        log_callback=_log,
        install_callback=_cb,
    )

    if not session.export_files:
        print(f"\n❌ {export_dir} に QIIME2 エクスポートファイルが見つかりません。")
        print("   feature-table.tsv / taxonomy/taxonomy.tsv などを確認してください。")
        return

    n = sum(len(v) for v in session.export_files.values())
    print(f"\n✅ {n} ファイルを検出しました:")
    for cat, paths in session.export_files.items():
        for p in paths:
            print(f"   [{cat}] {Path(p).name}")

    # ── 実験の説明 ──────────────────────────────────────────────────────────
    print()
    print("実験の概要を教えてください。")
    print("（例: マウス腸内フローラ 16S データ。抗生物質投与群 vs 対照群、各 10 匹）")
    print()
    try:
        description = input("あなた> ").strip()
    except (EOFError, KeyboardInterrupt):
        print(); return

    if not description:
        description = "QIIME2 で処理したマイクロバイオームデータ"

    print("\n🤖 考え中...\n")
    welcome = session.setup(description)
    print(f"🤖  {welcome}\n")

    # ── メインループ ─────────────────────────────────────────────────────────
    print("─" * 55)
    print("解析指示を入力してください。(help でコマンド一覧)\n")

    while True:
        try:
            user_input = input("あなた> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        # 特殊コマンド
        cmd = user_input.lower()
        if cmd in ("exit", "quit", "q"):
            break
        if cmd == "summary":
            print("\n" + session.get_summary() + "\n")
            continue
        if cmd == "figures":
            figs = session.ctx.all_figures
            if figs:
                print("\n📊 生成された図:")
                for f in figs:
                    print(f"   {f}")
                print()
            else:
                print("\n（まだ図は生成されていません）\n")
            continue
        if cmd == "context":
            print("\n" + session.ctx.to_context_block() + "\n")
            continue
        if cmd == "help":
            print(_HELP_TEXT)
            continue

        # 解析実行
        print()
        result = session.chat(user_input)
        print()
        print(f"🤖  {result['text']}\n")
        print("─" * 55)

    # セッション終了
    print("\n" + session.get_summary())
    print("\n👋 セッションを終了しました。\n")


# ─────────────────────────────────────────────────────────────────────────────
# スタンドアロン実行
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(
        description="seq2pipe 対話型解析モード",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python chat_agent.py ~/data/exported/\n"
            "  python chat_agent.py ~/data/exported/ --model qwen2.5-coder:7b"
        ),
    )
    parser.add_argument("export_dir", help="QIIME2 エクスポートディレクトリ")
    parser.add_argument("--output-dir", help="出力ディレクトリ（省略時は ~/seq2pipe_results/<timestamp>/）")
    parser.add_argument("--figure-dir", help="図の出力ディレクトリ")
    parser.add_argument("--model",      help="使用する Ollama モデル名")
    args = parser.parse_args()

    run_terminal_chat(
        export_dir=args.export_dir,
        output_dir=args.output_dir,
        figure_dir=args.figure_dir,
        model=args.model,
    )
