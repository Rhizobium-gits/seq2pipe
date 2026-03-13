#!/usr/bin/env python3
"""
chat_agent.py
=============
研究目的を聞いてから自律的に複数の解析を実行し、
最後に TeX / PDF レポートを出力する対話型エージェント。

流れ:
  1. 実験の説明・研究目的を自然言語で入力
  2. LLM が解析プランを自動作成（5〜8 ステップ）
  3. 各解析を run_code_agent で自動実行
  4. report/ に TeX + PDF レポートを出力
  5. そのまま追加の会話・解析も可能

使い方:
    python chat_agent.py ~/data/exported/
    python cli.py --chat --export-dir ~/data/exported/
"""

from __future__ import annotations

import re
import glob
import shutil
import datetime
import subprocess
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
    step: int
    description: str        # 解析の説明（1行）
    code_prompt: str        # run_code_agent に渡したプロンプト
    result_summary: str     # LLM による自然言語サマリー
    figures: list[str] = field(default_factory=list)
    stdout: str = ""
    success: bool = True


@dataclass
class SessionContext:
    experiment_description: str = ""
    research_goals: str = ""
    lang: str = "ja"                  # "ja" | "en"
    findings: list[AnalysisFinding] = field(default_factory=list)
    all_figures: list[str] = field(default_factory=list)

    def to_context_block(self, max_findings: int = 4) -> str:
        parts = ["## EXPERIMENT CONTEXT"]
        if self.experiment_description:
            parts.append(f"Experiment: {self.experiment_description}")
        if self.research_goals:
            parts.append(f"Research goals: {self.research_goals}")
        if self.findings:
            parts.append("\n## PREVIOUS ANALYSES")
            for f in self.findings[-max_findings:]:
                parts.append(f"  Step {f.step}: {f.description}")
                if f.result_summary:
                    parts.append(f"  → {f.result_summary[:180]}")
                if f.figures:
                    parts.append(f"  → Figures: {', '.join(Path(p).name for p in f.figures)}")
        return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# インタラクティブセッション
# ─────────────────────────────────────────────────────────────────────────────

class InteractiveSession:
    """
    研究目的から解析プランを自動作成し、
    全自動で複数解析を実行して TeX/PDF レポートを生成する。
    """

    def __init__(
        self,
        export_dir: str | Path,
        output_dir: str | Path,
        figure_dir: str | Path,
        model: str | None = None,
        log_callback=None,
        install_callback=None,
        metadata_path: str = "",
    ):
        self.export_dir   = Path(export_dir).expanduser()
        self.output_dir   = Path(output_dir).expanduser()
        self.figure_dir   = Path(figure_dir).expanduser()
        self.report_dir   = self.figure_dir.parent / "report"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.figure_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self.model        = model or _agent.DEFAULT_MODEL
        self._log         = log_callback or (lambda m: print(m, flush=True))
        self._install_cb  = install_callback
        self.metadata_path = metadata_path
        self.ctx          = SessionContext()
        self.export_files = discover_export_files(self.export_dir)
        # メタデータが外部パスで指定されている場合、export_files に追加
        if metadata_path and Path(metadata_path).exists():
            self.export_files.setdefault("metadata", [])
            if metadata_path not in self.export_files["metadata"]:
                self.export_files["metadata"].append(metadata_path)

    # ── setup ─────────────────────────────────────────────────────────────────

    def setup(self, description: str, goals: str = "", lang: str = "ja") -> str:
        """実験の説明と研究目的を受け取り、ウェルカムメッセージを返す。"""
        self.ctx.experiment_description = description
        self.ctx.research_goals = goals
        self.ctx.lang = lang

        n = sum(len(v) for v in self.export_files.values())
        file_block = _file_summary(self.export_files)

        # メタデータの列名情報を含める
        metadata_info = ""
        if self.metadata_path and Path(self.metadata_path).exists():
            try:
                with open(self.metadata_path) as f:
                    cols = f.readline().strip().split("\t")
                metadata_info = f"\nMetadata columns available: {', '.join(cols)}"
            except Exception:
                pass

        prompt = (
            f"You are a microbiome bioinformatics assistant. Respond in {'Japanese' if lang == 'ja' else 'English'}.\n\n"
            f"Experiment: {description}\n"
            f"Research goals: {goals}\n"
            f"{metadata_info}\n\n"
            f"Available files ({n} found):\n{file_block}\n\n"
            "Briefly confirm what you understood and suggest a concrete analysis plan "
            "(5-7 steps) for these goals. Focus on analyses that use the metadata columns "
            "for group comparisons. Keep it under 200 words."
        )
        return self._call_llm(prompt)

    # ── plan ──────────────────────────────────────────────────────────────────

    def plan_analysis_suite(self) -> list[str]:
        """
        実験説明と研究目的から解析プランを LLM に生成させる。
        Returns: 解析の説明リスト（各要素が run_code_agent に渡すプロンプトになる）
        """
        available = list(self.export_files.keys())
        file_block = _file_summary(self.export_files)

        # メタデータの列名を解析プランに含める
        metadata_info = ""
        if self.metadata_path and Path(self.metadata_path).exists():
            try:
                with open(self.metadata_path) as f:
                    header = f.readline().strip()
                    type_line = f.readline().strip()  # #q2:types line
                    first_data = f.readline().strip()
                cols = header.split("\t")
                metadata_info = (
                    f"\n\nMetadata columns: {', '.join(cols)}\n"
                    f"Metadata path: {self.metadata_path}\n"
                    f"Example row: {first_data}\n"
                    "IMPORTANT: Use these metadata columns for grouping, coloring, and statistical comparisons. "
                    "The metadata file is a TSV with sample-id as the first column."
                )
            except Exception:
                pass

        prompt = (
            "You are planning a microbiome analysis pipeline.\n\n"
            f"Experiment: {self.ctx.experiment_description}\n"
            f"Research goals: {self.ctx.research_goals}\n\n"
            f"Available data: {', '.join(available)}\n"
            f"Files:\n{file_block}\n"
            f"{metadata_info}\n\n"
            "List 5-8 specific analyses to run, ordered logically. "
            "Each should be ONE concrete figure/visualization task.\n"
            "IMPORTANT: The analyses MUST directly address the user's research goals above. "
            "Use the metadata grouping variables (e.g. gravity, timepoint, donor) for comparisons.\n"
            "Format: one analysis per line, starting with a number and period.\n"
            "Example:\n"
            "1. Plot genus-level stacked bar chart of relative abundance grouped by treatment condition.\n"
            "2. Compare Shannon alpha diversity between gravity groups with boxplot and Kruskal-Wallis test.\n"
            "3. PCoA of Bray-Curtis distances colored by gravity condition.\n"
            "Keep each description under 40 words. Focus on what figures to generate and what grouping to use."
        )

        content = self._call_llm(prompt)

        # 番号付きリストを解析
        analyses = []
        for line in content.splitlines():
            m = re.match(r"^\s*\d+[\.\)]\s*(.+)", line.strip())
            if m:
                analyses.append(m.group(1).strip())

        if not analyses:
            # フォールバック: デフォルト解析セット
            analyses = _default_analyses(available)

        return analyses[:8]  # 最大8ステップ

    # ── run_planned ───────────────────────────────────────────────────────────

    def run_planned(
        self,
        analyses: list[str],
        progress_callback=None,
    ) -> list[AnalysisFinding]:
        """
        解析リストを順番に実行する。
        progress_callback(step, total, description) が渡されると進捗通知。
        """
        total = len(analyses)
        for i, desc in enumerate(analyses, 1):
            if progress_callback:
                progress_callback(i, total, desc)
            self._log(f"\n{'─'*55}")
            self._log(f"[{i}/{total}] {desc}")
            self._log(f"{'─'*55}")

            result = self._run_one(desc)

            # 簡易サマリー（LLM 呼び出し節約のため短文）
            n_figs = len(result.figures)
            summary = (
                f"{desc} — {'成功' if result.success else '失敗'} "
                f"({'図 ' + str(n_figs) + ' 件生成' if n_figs else 'エラー'})"
            )

            finding = AnalysisFinding(
                step=len(self.ctx.findings) + 1,
                description=desc,
                code_prompt=desc,
                result_summary=summary,
                figures=result.figures,
                stdout=result.stdout or "",
                success=result.success,
            )
            self.ctx.findings.append(finding)
            self.ctx.all_figures.extend(result.figures)

            if result.figures:
                self._log(f"  ✅ 図: {[Path(f).name for f in result.figures]}")
            else:
                self._log(f"  {'✅' if result.success else '⚠️ '} 図なし")

        return self.ctx.findings

    # ── chat（個別ターン）────────────────────────────────────────────────────

    def chat(self, user_input: str) -> dict:
        """ユーザーの解析指示を1回受けてコードを生成・実行し結果をサマリーする。"""
        self._log(f"\n🔬 解析中: {user_input[:80]}...")
        result = self._run_one(user_input)
        summary = self._summarize(user_input, result)

        finding = AnalysisFinding(
            step=len(self.ctx.findings) + 1,
            description=user_input[:120],
            code_prompt=user_input,
            result_summary=summary,
            figures=result.figures,
            stdout=result.stdout or "",
            success=result.success,
        )
        self.ctx.findings.append(finding)
        self.ctx.all_figures.extend(result.figures)

        return {
            "text":    summary,
            "figures": result.figures,
            "success": result.success,
        }

    # ── レポート生成 ──────────────────────────────────────────────────────────

    def generate_report(self) -> dict:
        """
        全解析結果を TeX + PDF レポートとして出力する。
        report/ ディレクトリに report_ja.tex / report_ja.pdf (または en) を保存。
        Returns: {"tex_path": str, "pdf_path": str | None, "report_dir": str}
        """
        lang = self.ctx.lang
        self._log("\n📄 レポートを生成しています...")

        # 各図の説明を LLM に書かせる
        figure_descriptions = self._generate_figure_descriptions(lang)

        # TeX ソース構築
        tex_content = _build_tex(
            lang=lang,
            experiment_description=self.ctx.experiment_description,
            research_goals=self.ctx.research_goals,
            findings=self.ctx.findings,
            figure_descriptions=figure_descriptions,
            figure_dir=self.figure_dir,
            report_dir=self.report_dir,
        )

        fname = f"report_{lang}.tex"
        tex_path = self.report_dir / fname
        tex_path.write_text(tex_content, encoding="utf-8")
        self._log(f"  ✅ TeX 保存: {tex_path}")

        # PDF コンパイル
        pdf_path = _compile_tex(tex_path, self._log)

        return {
            "tex_path":   str(tex_path),
            "pdf_path":   str(pdf_path) if pdf_path else None,
            "report_dir": str(self.report_dir),
        }

    # ── summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> str:
        if not self.ctx.findings:
            return "まだ解析は実行されていません。"
        lines = [
            "=" * 55,
            "📊 解析セッション サマリー",
            "=" * 55,
            f"実験: {self.ctx.experiment_description[:100]}",
            f"ステップ数: {len(self.ctx.findings)} / 図: {len(self.ctx.all_figures)} 件",
            "",
        ]
        for f in self.ctx.findings:
            icon = "✅" if f.success else "❌"
            lines.append(f"{icon} Step {f.step}: {f.description[:70]}")
            for fig in f.figures:
                lines.append(f"     📊 {Path(fig).name}")
        lines += ["", f"図の保存先: {self.figure_dir}", f"レポート: {self.report_dir}", "=" * 55]
        return "\n".join(lines)

    # ── 内部メソッド ──────────────────────────────────────────────────────────

    def _run_one(self, user_request: str) -> CodeExecutionResult:
        """コンテキスト付きプロンプトでコード生成・実行。"""
        ctx_block = self.ctx.to_context_block()
        prompt = f"{ctx_block}\n\n## CURRENT TASK\n{user_request}" if ctx_block else user_request
        return run_code_agent(
            export_files=self.export_files,
            user_prompt=prompt,
            output_dir=str(self.output_dir),
            figure_dir=str(self.figure_dir),
            metadata_path=self.metadata_path,
            model=self.model,
            max_retries=3,
            log_callback=self._log,
            install_callback=self._install_cb,
        )

    def _summarize(self, request: str, result: CodeExecutionResult) -> str:
        if not result.success and not result.figures:
            return (
                f"⚠️ エラーが発生しました: {(result.error_message or '')[:200]}\n"
                "別の表現で指示を変えて試してみてください。"
            )
        fig_names = [Path(f).name for f in result.figures]
        prompt = (
            f"Summarize in {'Japanese' if self.ctx.lang == 'ja' else 'English'} "
            f"(3-4 sentences).\n"
            f"Analysis: {request}\n"
            f"Figures: {', '.join(fig_names) if fig_names else 'none'}\n"
            f"Output: {(result.stdout or '')[:300]}\n"
            "Include biological interpretation and suggest 1-2 next steps."
        )
        summary = self._call_llm(prompt)
        if fig_names:
            summary += "\n\n📊 " + "\n📊 ".join(fig_names)
        return summary

    def _generate_figure_descriptions(self, lang: str) -> dict[str, str]:
        """
        各図ファイル名 → TeX 用説明文（手法 + 解釈）の辞書を生成する。
        """
        desc: dict[str, str] = {}
        for finding in self.ctx.findings:
            for fig_path in finding.figures:
                fig_name = Path(fig_path).name
                prompt = (
                    f"Write a {'Japanese' if lang == 'ja' else 'English'} figure caption "
                    f"(2-3 sentences) for a scientific paper.\n"
                    f"Analysis performed: {finding.description}\n"
                    f"Figure file: {fig_name}\n"
                    f"Result context: {finding.stdout[:200]}\n"
                    "Include: what was measured, method used, key finding. "
                    "Do NOT start with 'Figure' or a number."
                )
                desc[fig_name] = self._call_llm(prompt)
        return desc

    def _call_llm(self, prompt: str) -> str:
        try:
            resp = _agent.call_ollama(
                [{"role": "user", "content": prompt}],
                self.model,
            )
            return resp.get("content", "").strip()
        except Exception as e:
            return f"（LLM エラー: {e}）"


# ─────────────────────────────────────────────────────────────────────────────
# デフォルト解析セット（LLM のプランニングが失敗した場合のフォールバック）
# ─────────────────────────────────────────────────────────────────────────────

def _default_analyses(available: list[str]) -> list[str]:
    analyses = []
    if "denoising" in available:
        analyses.append(
            "Plot denoising statistics: grouped bar chart showing input, filtered, denoised, "
            "merged, and non-chimeric read counts per sample."
        )
    if "alpha" in available:
        analyses.append(
            "Plot Shannon alpha diversity per sample as a boxplot with individual data points (stripplot). "
            "Use seaborn modern style."
        )
        analyses.append(
            "Plot all alpha diversity metrics (Shannon, Faith PD, observed features, evenness) "
            "side by side as boxplots."
        )
    if "feature_table" in available and "taxonomy" in available:
        analyses.append(
            "Plot relative abundance stacked bar chart at genus level (top 15 genera + Other), "
            "one bar per sample. Use tab20 palette."
        )
        analyses.append(
            "Plot top 10 most abundant phyla as a horizontal bar chart of mean relative abundance."
        )
    if "beta" in available:
        analyses.append(
            "Plot PCoA of Bray-Curtis distances as scatter plot with sample labels. "
            "Use modern seaborn white style."
        )
    if len(analyses) < 4 and "feature_table" in available:
        analyses.append(
            "Plot rarefaction curve: species richness (observed features) vs. sequencing depth, "
            "one line per sample."
        )
    return analyses


# ─────────────────────────────────────────────────────────────────────────────
# TeX レポートビルダー
# ─────────────────────────────────────────────────────────────────────────────

def _tex_escape(text: str) -> str:
    """LaTeX の特殊文字をエスケープ。"""
    for ch, rep in [
        ("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
        ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
        ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}"),
    ]:
        text = text.replace(ch, rep)
    return text


def _build_tex(
    lang: str,
    experiment_description: str,
    research_goals: str,
    findings: list[AnalysisFinding],
    figure_descriptions: dict[str, str],
    figure_dir: Path,
    report_dir: Path,
) -> str:
    """TeX ソース文字列を組み立てる。"""
    is_ja = (lang == "ja")
    today = datetime.date.today().isoformat()

    total_figs = sum(len(f.figures) for f in findings)
    total_steps = len(findings)

    L: list[str] = []

    # ── プリアンブル ─────────────────────────────────────────────────────────
    if is_ja:
        L += [
            r"\documentclass[a4paper,12pt]{article}",
            r"\usepackage{xeCJK}",
            r"\setCJKmainfont{Hiragino Mincho ProN}",
        ]
    else:
        L += [r"\documentclass[a4paper,12pt]{article}"]

    L += [
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{geometry}",
        r"\usepackage{caption}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{parskip}",
        r"\geometry{margin=2.5cm}",
        r"\captionsetup{font=small, labelfont=bf}",
        "",
        r"\title{" + ("マイクロバイオーム解析レポート" if is_ja else "Microbiome Analysis Report") + "}",
        r"\author{seq2pipe}",
        r"\date{" + today + "}",
        r"\begin{document}",
        r"\maketitle",
        r"\tableofcontents",
        r"\newpage",
        "",
    ]

    # ── 概要 ─────────────────────────────────────────────────────────────────
    if is_ja:
        L += [
            r"\section{解析概要}",
            r"\subsection{実験系}",
            _tex_escape(experiment_description),
            "",
        ]
        if research_goals:
            L += [
                r"\subsection{研究目的}",
                _tex_escape(research_goals),
                "",
            ]
        L += [
            r"\subsection{解析サマリー}",
            r"\begin{tabular}{ll}",
            r"\toprule",
            f"解析ステップ数 & {total_steps} \\\\",
            f"生成された図 & {total_figs} 件 \\\\",
            f"実行日時 & {today} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\newpage",
            "",
        ]
    else:
        L += [
            r"\section{Overview}",
            r"\subsection{Experimental Setup}",
            _tex_escape(experiment_description),
            "",
        ]
        if research_goals:
            L += [
                r"\subsection{Research Goals}",
                _tex_escape(research_goals),
                "",
            ]
        L += [
            r"\subsection{Analysis Summary}",
            r"\begin{tabular}{ll}",
            r"\toprule",
            f"Analysis steps & {total_steps} \\\\",
            f"Figures generated & {total_figs} \\\\",
            f"Date & {today} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
            r"\newpage",
            "",
        ]

    # ── 各解析セクション ──────────────────────────────────────────────────────
    results_title = "解析結果" if is_ja else "Results"
    L.append(f"\\section{{{results_title}}}")
    L.append("")

    for finding in findings:
        if not finding.figures:
            continue  # 図がない解析はスキップ

        # subsection タイトル = 解析の説明（先頭60文字）
        sec_title = _tex_escape(finding.description[:60])
        L.append(f"\\subsection{{{sec_title}}}")
        L.append("")

        for fig_path in finding.figures:
            fig_name = Path(fig_path).name
            # report/ から figures/ への相対パス
            rel = Path("..") / "figures" / fig_name

            # キャプション（LLM 生成 or フォールバック）
            caption_text = figure_descriptions.get(fig_name, finding.description)
            caption_escaped = _tex_escape(caption_text)

            L += [
                r"\begin{figure}[htbp]",
                r"  \centering",
                f"  \\includegraphics[width=0.92\\textwidth]{{{rel}}}",
                f"  \\caption{{{caption_escaped}}}",
                f"  \\label{{fig:{fig_name.replace('.', '_')}}}",
                r"\end{figure}",
                "",
            ]

    # ── 手法セクション ────────────────────────────────────────────────────────
    methods_title = "手法" if is_ja else "Methods"
    L.append(r"\newpage")
    L.append(f"\\section{{{methods_title}}}")
    L.append("")

    for finding in findings:
        if not finding.figures:
            continue
        sec_title = _tex_escape(finding.description[:60])
        L.append(f"\\subsection{{{sec_title}}}")
        if is_ja:
            L.append(
                "本解析は seq2pipe の LLM コードエージェント（qwen2.5-coder）によって自動生成された "
                "Python スクリプトで実行されました。可視化には matplotlib / seaborn を使用しました。"
            )
        else:
            L.append(
                "This analysis was performed by a Python script automatically generated by "
                "seq2pipe's LLM code agent. Visualization used matplotlib / seaborn."
            )
        L.append("")

    L.append(r"\end{document}")
    return "\n".join(L)


def _compile_tex(tex_path: Path, log=None) -> Optional[Path]:
    """tectonic または pdflatex で TeX を PDF にコンパイルする。"""
    _log = log or (lambda m: None)

    # tectonic を優先（自動フォントダウンロード対応）
    tectonic = shutil.which("tectonic")
    if tectonic:
        try:
            proc = subprocess.run(
                [tectonic, str(tex_path)],
                capture_output=True, text=True,
                timeout=180, cwd=str(tex_path.parent),
            )
            pdf = tex_path.with_suffix(".pdf")
            if proc.returncode == 0 and pdf.exists():
                _log(f"  ✅ PDF 生成: {pdf}")
                return pdf
            else:
                _log(f"  ⚠️  tectonic エラー: {proc.stderr[:300]}")
        except subprocess.TimeoutExpired:
            _log("  ⏱️  tectonic タイムアウト")
        except Exception as e:
            _log(f"  ❌ tectonic: {e}")

    # pdflatex フォールバック（日本語は xelatex）
    engine = "xelatex" if "\\usepackage{xeCJK}" in tex_path.read_text() else "pdflatex"
    latex_bin = shutil.which(engine)
    if latex_bin:
        try:
            for _ in range(2):   # 目次のために2回
                subprocess.run(
                    [latex_bin, "-interaction=nonstopmode", str(tex_path)],
                    capture_output=True, text=True,
                    timeout=180, cwd=str(tex_path.parent),
                )
            pdf = tex_path.with_suffix(".pdf")
            if pdf.exists():
                _log(f"  ✅ PDF 生成: {pdf}")
                return pdf
        except Exception as e:
            _log(f"  ❌ {engine}: {e}")

    _log("  ⚠️  PDF コンパイラが見つかりません（tectonic / pdflatex / xelatex）")
    _log("     brew install tectonic  または  brew install --cask mactex")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLIターミナルモード
# ─────────────────────────────────────────────────────────────────────────────

_HELP = """
コマンド:
  summary    これまでの解析サマリーを表示
  figures    生成された図のパスを一覧
  report     今すぐレポートを生成（解析途中でも可）
  context    現在の実験コンテキストを表示
  help       このヘルプ
  exit       終了
"""


def run_terminal_chat(
    export_dir: str | Path,
    output_dir: str | None = None,
    figure_dir: str | None = None,
    model: str | None = None,
    log_callback=None,
    install_callback=None,
    initial_prompt: str = "",
    metadata_path: str = "",
):
    """ターミナルで対話型解析セッションを実行する。"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path.home() / "seq2pipe_results" / ts
    out_dir = output_dir or str(base / "output")
    fig_dir = figure_dir or str(base / "figures")

    def _log(m: str):
        # コード生成の詳細は薄く表示
        if m.startswith("  ") and not m.startswith("  ✅") and not m.startswith("  ⚠️"):
            print(f"\033[2m{m}\033[0m", flush=True)
        else:
            print(m, flush=True)

    if log_callback:
        _log = log_callback  # noqa: F811

    def _install_cb(pkg: str) -> bool:
        ans = input(f"\n⚠️  '{pkg}' が必要です。インストールしますか? [Y/n]: ").strip().lower()
        return ans != "n"

    _cb = install_callback or _install_cb

    print()
    print("─" * 55)
    print("🧬  seq2pipe  対話型自律解析モード")
    print("─" * 55)
    print(f"  データ : {export_dir}")
    print(f"  図    : {fig_dir}")
    print("─" * 55)

    session = InteractiveSession(
        export_dir=export_dir,
        output_dir=out_dir,
        figure_dir=fig_dir,
        model=model,
        log_callback=_log,
        install_callback=_cb,
        metadata_path=metadata_path,
    )

    if not session.export_files:
        print(f"\n❌ {export_dir} に QIIME2 エクスポートファイルが見つかりません。")
        return

    n = sum(len(v) for v in session.export_files.values())
    print(f"\n✅ {n} ファイルを検出:")
    for cat, paths in session.export_files.items():
        for p in paths:
            print(f"   [{cat}] {Path(p).name}")

    # ── initial_prompt が渡されている場合はそれを使う ─────────────────────────
    if initial_prompt:
        lang = "ja"
        description = initial_prompt
        goals = initial_prompt
        print(f"\n📝 解析指示を受け取りました:")
        # 最初の100文字を表示
        preview = initial_prompt[:150].replace("\n", " ")
        print(f"   {preview}{'...' if len(initial_prompt) > 150 else ''}")
    else:
        # ── 言語選択 ──────────────────────────────────────────────────────────
        print()
        lang_raw = _input_safe("レポート言語を選択してください [ja/en]", default="ja")
        lang = "en" if lang_raw.strip().lower().startswith("e") else "ja"

        # ── 実験説明 ──────────────────────────────────────────────────────────
        print()
        print("【1/2】実験の概要を教えてください。")
        print("  （例: マウス腸内フローラ 16S。抗生物質投与群 vs 対照群、各 10 匹）")
        description = _input_safe("あなた", required=True)
        if not description:
            description = "QIIME2 で処理したマイクロバイオームデータ"

        print()
        print("【2/2】知りたいこと・研究の目的を教えてください。")
        print("  （例: 抗生物質が多様性と菌叢組成に与える影響。Lactobacillus の変化を見たい）")
        goals = _input_safe("あなた", required=False)

    # ── セットアップ ──────────────────────────────────────────────────────────
    print("\n🤖 考え中...\n")
    welcome = session.setup(description, goals, lang)
    print(f"🤖  {welcome}\n")

    # ── 解析プランの作成 ──────────────────────────────────────────────────────
    print("─" * 55)
    print("📋 解析プランを作成しています...")
    analyses = session.plan_analysis_suite()

    print(f"\n以下の解析を実行します（{len(analyses)} ステップ）:\n")
    for i, a in enumerate(analyses, 1):
        print(f"  {i}. {a}")

    print()
    go = _input_safe("このプランで解析を開始しますか？ [Y/n]", default="y")
    if go.strip().lower() == "n":
        print("解析プランを変更したい場合は解析内容を直接入力してください。")

    else:
        # ── 全自動解析実行 ────────────────────────────────────────────────────
        print()
        session.run_planned(analyses)

        # ── レポート生成 ──────────────────────────────────────────────────────
        print()
        rpt = session.generate_report()
        print(f"\n📄 レポート保存先: {rpt['report_dir']}")
        if rpt["tex_path"]:
            print(f"   TeX : {rpt['tex_path']}")
        if rpt["pdf_path"]:
            print(f"   PDF : {rpt['pdf_path']}")

    # ── 追加の会話ループ ──────────────────────────────────────────────────────
    print()
    print("─" * 55)
    print("追加の解析指示があれば入力してください。(help / exit)\n")

    while True:
        user_input = _input_safe("あなた", required=False)
        if user_input is None:
            break
        if not user_input:
            continue
        cmd = user_input.lower().strip()
        if cmd in ("exit", "quit", "q"):
            break
        if cmd == "help":
            print(_HELP)
            continue
        if cmd == "summary":
            print("\n" + session.get_summary() + "\n")
            continue
        if cmd == "figures":
            figs = session.ctx.all_figures
            print("\n📊 生成された図:" if figs else "\n（まだ図はありません）")
            for f in figs:
                print(f"   {f}")
            print()
            continue
        if cmd == "context":
            print("\n" + session.ctx.to_context_block() + "\n")
            continue
        if cmd == "report":
            rpt = session.generate_report()
            print(f"📄 レポート: {rpt['report_dir']}")
            if rpt["pdf_path"]:
                print(f"   PDF: {rpt['pdf_path']}")
            continue

        result = session.chat(user_input)
        print(f"\n🤖  {result['text']}\n")
        print("─" * 55)

    # 終了
    print("\n" + session.get_summary())
    print("\n👋 終了しました。\n")


def _input_safe(prompt: str, default: str = "", required: bool = False) -> Optional[str]:
    """入力ヘルパー。EOF / Ctrl+C で None を返す。"""
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{hint}> ").strip()
        return val if val else (default if default else ("" if not required else None))
    except (EOFError, KeyboardInterrupt):
        print()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# スタンドアロン実行
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(
        description="seq2pipe 対話型自律解析モード",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例:\n  python chat_agent.py ~/data/exported/\n  python chat_agent.py ~/data/exported/ --model qwen2.5-coder:7b",
    )
    parser.add_argument("export_dir", help="QIIME2 エクスポートディレクトリ")
    parser.add_argument("--output-dir")
    parser.add_argument("--figure-dir")
    parser.add_argument("--model")
    args = parser.parse_args()

    run_terminal_chat(
        export_dir=args.export_dir,
        output_dir=args.output_dir,
        figure_dir=args.figure_dir,
        model=args.model,
    )
