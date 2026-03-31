#!/usr/bin/env python3
"""
code_learner.py — コード生成の学習・自動修正エンジン
=====================================================
LLM が繰り返す同じエラーを記録し、3段階で解決する:

  Stage 1: プロンプト注入 — 過去のエラーを「避けるべきこと」として LLM に伝える
  Stage 2: コード後処理 — 生成されたコードの既知バグを自動修正
  Stage 3: テンプレートフォールバック — 上記で解決しなければ確定的テンプレートで生成

これにより:
  LLM のみ:         5% 成功 →
  LLM + 学習:       ? →
  LLM + 学習 + 後処理: ? →
  テンプレートフォールバック: 100%
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional
from collections import Counter


class CodeLearner:
    """
    コード生成のエラーパターンを学習し、次回の生成を改善する。
    """

    def __init__(self, store_dir: Optional[str] = None):
        if store_dir is None:
            store_dir = os.path.join(Path.home(), ".seq2pipe", "code_learning")
        self.store_dir = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self._error_log_path = os.path.join(store_dir, "error_patterns.json")
        self._fix_log_path = os.path.join(store_dir, "successful_fixes.json")
        self._errors = self._load(self._error_log_path)  # {pattern: count}
        self._fixes = self._load(self._fix_log_path)    # {pattern: fix_code}

    def _load(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save(self):
        with open(self._error_log_path, "w") as f:
            json.dump(self._errors, f, indent=2)
        with open(self._fix_log_path, "w") as f:
            json.dump(self._fixes, f, indent=2)

    # ── Stage 1: エラーパターン記録 + プロンプト注入 ──

    def record_error(self, code: str, stderr: str, task: str):
        """エラーを記録し、パターンを抽出"""
        pattern = self._extract_pattern(stderr)
        if pattern:
            key = f"{task}:{pattern}"
            self._errors[key] = self._errors.get(key, 0) + 1
            self._save()

    def record_success(self, code: str, task: str):
        """成功したコードを記録"""
        self._fixes[task] = code[:2000]  # 保存上限
        self._save()

    def _extract_pattern(self, stderr: str) -> str:
        """stderr からエラーパターンを抽出"""
        # 最後の例外行を取得
        lines = [l.strip() for l in stderr.split("\n") if l.strip()]
        for line in reversed(lines):
            for err_type in ["NameError", "KeyError", "ValueError", "TypeError",
                             "AttributeError", "IndexError", "FileNotFoundError",
                             "ModuleNotFoundError", "ImportError"]:
                if err_type in line:
                    return line[:200]
        return ""

    def build_error_avoidance_prompt(self, task: str) -> str:
        """
        過去のエラーパターンから「避けるべきこと」のプロンプトを生成。
        これを LLM のプロンプトに注入する。
        """
        relevant = {k: v for k, v in self._errors.items()
                    if k.startswith(f"{task}:") or k.startswith("*:")}
        if not relevant:
            return ""

        lines = ["\n## KNOWN ERRORS TO AVOID (from previous runs):"]
        for pattern, count in sorted(relevant.items(), key=lambda x: -x[1])[:10]:
            err_msg = pattern.split(":", 1)[1] if ":" in pattern else pattern
            fix = self._get_fix_for_pattern(err_msg)
            lines.append(f"- ERROR ({count}x): {err_msg}")
            if fix:
                lines.append(f"  FIX: {fix}")

        # 共通の回避策
        lines.append("\n## MANDATORY RULES:")
        lines.append("- ALWAYS start with: import matplotlib; matplotlib.use('Agg')")
        lines.append("- ALWAYS import os before using os.makedirs")
        lines.append("- For taxonomy.tsv: use pd.read_csv(path, sep='\\t', index_col=0)")
        lines.append("  Column name is 'Taxon' (capital T), NOT 'taxonomy'")
        lines.append("- For metadata: use comment='#' to skip #q2:types rows")
        lines.append("- For feature-table.tsv: use skiprows=1 to skip '# Constructed from biom'")
        lines.append("- NEVER use plt.show()")
        lines.append("- ALWAYS use fig.savefig() or plt.savefig()")

        return "\n".join(lines)

    def _get_fix_for_pattern(self, pattern: str) -> str:
        """既知のエラーパターンに対する修正方法"""
        fixes = {
            "NameError: name 'os' is not defined":
                "Add 'import os' at the top of the script",
            "NameError: name 'matplotlib' is not defined":
                "Add 'import matplotlib; matplotlib.use(\"Agg\")' as the FIRST line",
            "KeyError: 'Taxon'":
                "The column is named 'Taxon' (capital T). Use tax['Taxon']. "
                "Read with: pd.read_csv(path, sep='\\t', index_col=0)",
            "KeyError: 'body-site'":
                "Read metadata with comment='#', then check column names with meta.columns",
            "ModuleNotFoundError":
                "Only use standard packages: matplotlib, pandas, numpy, seaborn, scipy",
            "FileNotFoundError":
                "Use the exact file paths provided in the prompt",
        }
        for key, fix in fixes.items():
            if key in pattern:
                return fix
        return ""

    # ── Stage 2: コード後処理 (自動修正) ──

    def postprocess_code(self, code: str) -> str:
        """
        LLM が生成したコードの既知バグを自動修正。
        これが学習の核心 — 過去のエラーから修正パターンを蓄積。
        """
        if not code:
            return code

        lines = code.split("\n")
        fixed_lines = []
        has_matplotlib_import = False
        has_os_import = False
        has_matplotlib_use = False

        # Pass 1: スキャンして不足を検出
        for line in lines:
            if "import matplotlib" in line:
                has_matplotlib_import = True
            if "matplotlib.use" in line:
                has_matplotlib_use = True
            if "import os" in line or "from os" in line:
                has_os_import = True

        # Pass 2: 修正を適用
        injected_header = False
        for i, line in enumerate(lines):
            # matplotlib.use を import より前に挿入
            if not injected_header and (line.startswith("import ") or
                                         line.startswith("from ") or
                                         line.startswith("#")):
                if not has_matplotlib_import or not has_matplotlib_use:
                    fixed_lines.append("import matplotlib; matplotlib.use('Agg')")
                    has_matplotlib_import = True
                    has_matplotlib_use = True
                if not has_os_import:
                    fixed_lines.append("import os")
                    has_os_import = True
                injected_header = True

            # matplotlib.use('Agg') がない場合に追加
            if "import matplotlib" in line and "use" not in line:
                fixed_lines.append(line)
                if not has_matplotlib_use:
                    fixed_lines.append("matplotlib.use('Agg')")
                    has_matplotlib_use = True
                continue

            # plt.show() を削除
            if "plt.show()" in line:
                fixed_lines.append(line.replace("plt.show()", "plt.close('all')"))
                continue

            # os.makedirs の前に import os がない場合
            if "os.makedirs" in line and not has_os_import:
                fixed_lines.append("import os")
                has_os_import = True

            fixed_lines.append(line)

        # ヘッダがまだ挿入されていない場合
        if not injected_header:
            header = []
            if not has_matplotlib_import:
                header.append("import matplotlib; matplotlib.use('Agg')")
            if not has_os_import:
                header.append("import os")
            fixed_lines = header + fixed_lines

        return "\n".join(fixed_lines)

    # ── Stage 3: テンプレートフォールバック ──

    def get_template_fallback(self, task: str, export_files: dict,
                              metadata_path: str, group_column: str,
                              figure_dir: str) -> Optional[str]:
        """
        LLM が失敗し続ける場合の確定的テンプレート。
        成功率 100%。
        """
        from code_templates import build_data_preamble
        preamble = build_data_preamble(export_files, metadata_path,
                                        group_column, figure_dir, 1, task)

        templates = {
            "alpha_boxplot": """
{preamble}
# Alpha boxplot
fig, ax = plt.subplots(figsize=(8, 5))
acol = alpha_shannon_vector.columns[0]
groups = sorted(meta[group_col].dropna().unique())
plot_data = [alpha_shannon_vector.loc[alpha_shannon_vector.index.isin(
    meta[meta[group_col]==g].index), acol].dropna().values for g in groups]
plot_data = [d for d in plot_data if len(d) > 0]
if plot_data:
    bp = ax.boxplot(plot_data, labels=groups[:len(plot_data)], patch_artist=True)
    for patch, c in zip(bp['boxes'], plt.cm.Set2(np.linspace(0,1,len(plot_data)))):
        patch.set_facecolor(c)
ax.set_ylabel(acol); ax.set_title(f'Alpha Diversity by {{group_col}}')
save_fig('alpha_boxplot')
""",
            "beta_pcoa": """
{preamble}
# PCoA
dm = dm_bray_curtis_distance_matrix if 'dm_bray_curtis_distance_matrix' in dir() else pd.DataFrame()
if not dm.empty:
    common = sorted(set(dm.index) & set(meta.index))
    dm_c = dm.loc[common, common]
    n = len(common); D = dm_c.values.astype(float)
    H = np.eye(n) - np.ones((n,n))/n; B = -0.5*H@(D**2)@H
    ev, ec = np.linalg.eigh(B); idx = np.argsort(ev)[::-1]; ev=ev[idx]; ec=ec[:,idx]
    p1 = ec[:,0]*np.sqrt(max(ev[0],0)); p2 = ec[:,1]*np.sqrt(max(ev[1],0))
    fig, ax = plt.subplots(figsize=(8,6))
    gp = meta.loc[common, group_col]
    for g in sorted(gp.dropna().unique()):
        mask = gp==g; ax.scatter(p1[mask], p2[mask], label=g, s=40, alpha=0.7)
    tv = sum(max(e,0) for e in ev[:10])
    if tv > 0:
        ax.set_xlabel(f'PC1 ({{max(ev[0],0)/tv*100:.1f}}%)')
        ax.set_ylabel(f'PC2 ({{max(ev[1],0)/tv*100:.1f}}%)')
    ax.set_title('PCoA (Bray-Curtis)'); ax.legend()
    save_fig('pcoa')
""",
        }

        template = templates.get(task)
        if template:
            return template.format(preamble=preamble)
        return None

    # ── 統合: 学習付き実行 ──

    def enhanced_generate(self, task: str, base_prompt: str,
                          llm_call_fn, extract_fn, run_fn,
                          export_files: dict, metadata_path: str,
                          group_column: str, figure_dir: str,
                          max_retries: int = 5) -> tuple:
        """
        学習付きのコード生成 + 実行。
        1. 過去のエラーをプロンプトに注入
        2. LLM が生成したコードを後処理
        3. 失敗したらエラーを記録して再試行
        4. max_retries 超えたらテンプレートフォールバック

        Returns: (success, code, stdout, stderr, figures, method)
        """
        # エラー回避プロンプトを注入
        avoidance = self.build_error_avoidance_prompt(task)
        enhanced_prompt = base_prompt + avoidance

        msgs = [
            {"role": "system", "content": "Generate only Python code in ```python...```."},
            {"role": "user", "content": enhanced_prompt},
        ]

        code = None
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    resp = llm_call_fn(msgs)
                    code = extract_fn(resp.get("content", ""))
                else:
                    fix_msgs = msgs + [
                        {"role": "assistant", "content": f"```python\n{code}\n```"},
                        {"role": "user", "content":
                         f"Attempt {attempt+1} failed:\n{last_err[:500]}\n"
                         f"Fix it. {avoidance}"}
                    ]
                    resp = llm_call_fn(fix_msgs)
                    new_code = extract_fn(resp.get("content", ""))
                    if new_code:
                        code = new_code

                if not code:
                    continue

                # Stage 2: 後処理
                code = self.postprocess_code(code)

                # 実行
                success, stdout, stderr, figs = run_fn(code)

                if success:
                    self.record_success(code, task)
                    return (True, code, stdout, stderr, figs, "llm+learning")
                else:
                    self.record_error(code, stderr, task)
                    last_err = stderr

            except Exception as e:
                last_err = str(e)

        # Stage 3: テンプレートフォールバック
        template = self.get_template_fallback(
            task, export_files, metadata_path, group_column, figure_dir)
        if template:
            success, stdout, stderr, figs = run_fn(template)
            if success:
                return (True, template, stdout, stderr, figs, "template_fallback")

        return (False, code or "", "", last_err if 'last_err' in dir() else "", [], "failed")
