#!/usr/bin/env python3
"""
app.py
======
seq2pipe Streamlit GUI アプリケーション。

起動方法:
    ~/miniforge3/envs/qiime2/bin/streamlit run app.py
    → ブラウザで http://localhost:8501 が開く
"""

import sys
import time
import queue
import tempfile
import threading
from pathlib import Path

import streamlit as st

# スレッドセーフなログキュー（バックグラウンドスレッド → メインスレッド）
_log_queue: queue.Queue = queue.Queue()

sys.path.insert(0, str(Path(__file__).parent))
import qiime2_agent as _agent
from pipeline_runner import PipelineConfig, PipelineResult, run_pipeline, get_exported_files
from code_agent import run_code_agent, CodeExecutionResult, pip_install


# ─────────────────────────────────────────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="seq2pipe",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
# セッションステートの初期化
# ─────────────────────────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "running": False,
        "log_lines": [],
        "pipeline_result": None,
        "code_result": None,
        "last_export_dir": "",
        "pending_install_pkg": None,
        "install_approved": None,
        "metadata_temp_path": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# キューに溜まったログを session_state へ移す（毎 rerun で実行）
while not _log_queue.empty():
    try:
        st.session_state["log_lines"].append(_log_queue.get_nowait())
    except queue.Empty:
        break


# ─────────────────────────────────────────────────────────────────────────────
# サイドバー: パラメータ入力
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🧬 seq2pipe")
    st.caption("QIIME2 AI Agent GUI")
    st.divider()

    st.subheader("入力ファイル")
    fastq_dir = st.text_input(
        "FASTQ ディレクトリ",
        placeholder="/path/to/fastq/",
        help="シングルエンドまたはペアエンドの FASTQ ファイルが入ったディレクトリ",
    )
    metadata_file = st.file_uploader(
        "メタデータ (TSV)",
        type=["tsv", "txt", "csv"],
        help="サンプルメタデータファイルをアップロードするか、パスで指定してください",
    )
    if metadata_file is not None:
        # アップロードされたファイルを一時ディレクトリに保存
        tmp_dir = Path(tempfile.gettempdir()) / "seq2pipe"
        tmp_dir.mkdir(exist_ok=True)
        tmp_path = str(tmp_dir / metadata_file.name)
        with open(tmp_path, "wb") as _f:
            _f.write(metadata_file.getvalue())
        st.session_state["metadata_temp_path"] = tmp_path
        st.caption(f"✅ {metadata_file.name} を読み込みました")
    metadata_path = st.session_state.get("metadata_temp_path", "") or st.text_input(
        "またはパスで指定",
        placeholder="/path/to/sample-metadata.tsv",
        label_visibility="collapsed",
    )
    classifier_path = st.text_input(
        "分類器 (.qza、省略可)",
        placeholder="/path/to/silva-classifier.qza",
        help="未指定の場合は分類ステップをスキップ",
    )

    st.subheader("デノイジング設定")
    paired_end = st.checkbox("ペアエンド", value=True)

    col1, col2 = st.columns(2)
    with col1:
        trim_left_f = st.number_input("trim-left-f", value=17, min_value=0, max_value=50)
        trunc_len_f = st.number_input("trunc-len-f", value=270, min_value=50, max_value=500)
    with col2:
        _disabled_r = not paired_end
        trim_left_r = st.number_input("trim-left-r", value=21, min_value=0, max_value=50,
                                       disabled=_disabled_r)
        trunc_len_r = st.number_input("trunc-len-r", value=220, min_value=50, max_value=500,
                                       disabled=_disabled_r)

    st.subheader("多様性解析設定")
    n_threads    = st.slider("スレッド数", 1, 16, 4)
    sampling_depth = st.number_input("サンプリング深度", value=5000, min_value=100, step=500)
    group_column = st.text_input("グループ列名（省略可）", placeholder="treatment")

    st.subheader("LLM モデル")
    ollama_ok = _agent.check_ollama_running()
    if ollama_ok:
        available_models = _agent.get_available_models()
        if available_models:
            selected_model = st.selectbox("Ollama モデル", available_models)
        else:
            st.warning("モデルが見つかりません。`ollama pull qwen2.5-coder:7b` を実行してください。")
            selected_model = _agent.DEFAULT_MODEL
    else:
        st.error("Ollama が起動していません。`ollama serve` を実行してください。")
        selected_model = _agent.DEFAULT_MODEL

    st.divider()
    st.caption(f"QIIME2: {_agent.QIIME2_CONDA_BIN or '未検出'}")


# ─────────────────────────────────────────────────────────────────────────────
# メインエリア
# ─────────────────────────────────────────────────────────────────────────────

st.title("seq2pipe — QIIME2 AI Agent")

tab_run, tab_log, tab_result, tab_fig = st.tabs(["▶ 実行", "📋 ログ", "📁 結果ファイル", "📊 図"])


# ══════════════════════════════════════════════════════════════════════════════
# 実行タブ
# ══════════════════════════════════════════════════════════════════════════════
with tab_run:
    st.subheader("解析プロンプト")
    user_prompt = st.text_area(
        label="LLM に行わせる解析を自然言語で記述してください",
        placeholder=(
            "例: 属レベルの相対存在量を積み上げ棒グラフで可視化してください。"
            "また Shannon 多様性をグループ間で比較してください。"
        ),
        height=130,
        label_visibility="collapsed",
    )

    st.divider()
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        run_full = st.button(
            "🚀 QIIME2 パイプライン + コード生成",
            disabled=st.session_state["running"] or not fastq_dir,
            type="primary",
            use_container_width=True,
            help="QIIME2 パイプラインを実行後、LLM でコードを生成して解析します",
        )
    with col_btn2:
        run_code_only = st.button(
            "💡 コード生成のみ",
            disabled=st.session_state["running"],
            use_container_width=True,
            help="既にパイプラインを実行済みの場合、コード生成・実行のみ行います",
        )

    # コード生成のみモード用: エクスポートディレクトリの直接指定
    _last_export = st.session_state.get("last_export_dir", "")
    _code_only_dir_input = st.text_input(
        "エクスポートディレクトリ（コード生成のみモード用）",
        value=_last_export,
        placeholder="/path/to/seq2pipe_results/20240101_120000/exported/",
        help="パイプライン実行済みの exported/ ディレクトリを直接指定できます",
    )
    if _code_only_dir_input:
        st.session_state["_code_only_export_dir"] = _code_only_dir_input

    # ── 実行状態インジケータ ──────────────────────────────────────────
    if st.session_state["running"]:
        st.info("⏳ 実行中... ログタブで進捗を確認できます。")
        st.progress(0.5)

    # ── パッケージインストール確認ダイアログ ──────────────────────────
    if st.session_state["pending_install_pkg"]:
        pkg = st.session_state["pending_install_pkg"]
        st.warning(f"パッケージ `{pkg}` が見つかりません。インストールしますか？")
        col_yes, col_no, _ = st.columns([1, 1, 3])
        with col_yes:
            if st.button(f"✅ インストール", key="btn_install_yes"):
                st.session_state["install_approved"] = True
                st.session_state["pending_install_pkg"] = None
                st.rerun()
        with col_no:
            if st.button("❌ スキップ", key="btn_install_no"):
                st.session_state["install_approved"] = False
                st.session_state["pending_install_pkg"] = None
                st.rerun()

    # ── 最終結果サマリー ──────────────────────────────────────────────
    pipeline_result: PipelineResult = st.session_state.get("pipeline_result")
    code_result: CodeExecutionResult = st.session_state.get("code_result")

    if pipeline_result and not st.session_state["running"]:
        if pipeline_result.success:
            st.success(f"✅ パイプライン完了 → `{pipeline_result.output_dir}`")
            for step in pipeline_result.completed_steps[:5]:
                st.caption(step)
        else:
            st.error("❌ パイプライン失敗")
            st.code(pipeline_result.error_message[:300], language="text")

    if code_result and not st.session_state["running"]:
        if code_result.success:
            st.success(f"✅ コード実行成功（図 {len(code_result.figures)} 件）")
        else:
            st.error(f"❌ コード実行失敗（{code_result.retry_count} 回試行）")
            with st.expander("エラー詳細"):
                st.code(code_result.stderr[:800], language="text")
            with st.expander("実行されたコード"):
                st.code(code_result.code, language="python")


# ══════════════════════════════════════════════════════════════════════════════
# ログタブ
# ══════════════════════════════════════════════════════════════════════════════
with tab_log:
    log_placeholder = st.empty()
    if st.session_state["log_lines"]:
        # 直近 300 行を表示
        log_text = "\n".join(st.session_state["log_lines"][-300:])
        log_placeholder.code(log_text, language="text")
    else:
        log_placeholder.info("ログはここに表示されます。")

    if st.button("ログをクリア", key="clear_log"):
        st.session_state["log_lines"] = []
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# 結果ファイルタブ
# ══════════════════════════════════════════════════════════════════════════════
with tab_result:
    if pipeline_result and pipeline_result.success:
        out_path = Path(pipeline_result.output_dir)
        st.subheader(f"出力ディレクトリ: `{out_path}`")

        all_files = sorted(out_path.rglob("*"))
        file_count = sum(1 for f in all_files if f.is_file())
        st.caption(f"{file_count} 件のファイル")

        shown = 0
        for f in all_files:
            if not f.is_file():
                continue
            if shown >= 200:
                st.caption("... (以下省略)")
                break
            rel = f.relative_to(out_path)
            col_path, col_dl = st.columns([4, 1])
            with col_path:
                suffix = f.suffix.lower()
                icon = "📊" if suffix == ".pdf" else "📋" if suffix == ".csv" else "📄"
                st.text(f"{icon} {rel}")
            with col_dl:
                try:
                    with open(f, "rb") as fh:
                        st.download_button(
                            "DL", fh.read(),
                            file_name=f.name,
                            key=f"dl_{rel}",
                            label_visibility="collapsed",
                        )
                except Exception:
                    pass
            shown += 1
    else:
        st.info("パイプラインを実行すると、ここに出力ファイル一覧が表示されます。")


# ══════════════════════════════════════════════════════════════════════════════
# 図タブ
# ══════════════════════════════════════════════════════════════════════════════
with tab_fig:
    if code_result and code_result.figures:
        st.subheader(f"生成された図 ({len(code_result.figures)} 件)")
        for fig_path in code_result.figures:
            p = Path(fig_path)
            if not p.exists():
                continue
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg"):
                st.image(str(p), caption=p.name, use_container_width=True)
            elif p.suffix.lower() == ".pdf":
                col_name, col_dl = st.columns([3, 1])
                with col_name:
                    st.write(f"📊 `{p.name}`")
                with col_dl:
                    with open(p, "rb") as fh:
                        st.download_button(
                            "ダウンロード",
                            fh.read(),
                            file_name=p.name,
                            mime="application/pdf",
                            key=f"figdl_{p.name}",
                        )
    elif pipeline_result and pipeline_result.success:
        # figures/ フォルダの PNG/PDF を表示
        fig_dir = Path(pipeline_result.output_dir) / "figures"
        if fig_dir.exists():
            pngs = list(fig_dir.glob("*.png"))
            if pngs:
                for p in pngs[:20]:
                    st.image(str(p), caption=p.name, use_container_width=True)
            else:
                st.info("PNG ファイルはありません（PDF はダウンロードから確認できます）。")
    else:
        st.info("解析を実行すると、生成された図がここに表示されます。")


# ─────────────────────────────────────────────────────────────────────────────
# バックグラウンドスレッド
# ─────────────────────────────────────────────────────────────────────────────

def _log(line: str):
    """バックグラウンドスレッドからキューにログを追記（スレッドセーフ）"""
    _log_queue.put(str(line))


def _make_install_callback():
    """
    バックグラウンドスレッドから Streamlit UI に
    インストール確認を依頼するコールバックを生成する。
    session_state をセマフォとして使い、最大 60 秒ポーリング。
    """
    def _cb(pkg: str) -> bool:
        st.session_state["pending_install_pkg"] = pkg
        st.session_state["install_approved"] = None
        for _ in range(120):   # 0.5s × 120 = 60s
            time.sleep(0.5)
            approved = st.session_state.get("install_approved")
            if approved is not None:
                st.session_state["install_approved"] = None
                return bool(approved)
        # タイムアウト → スキップ
        st.session_state["pending_install_pkg"] = None
        return False
    return _cb


def _thread_full_pipeline(
    config: PipelineConfig,
    user_prompt_text: str,
    model: str,
):
    """QIIME2 パイプライン + コード生成をバックグラウンドで実行"""
    try:
        _log("=== QIIME2 パイプライン 開始 ===")
        result = run_pipeline(config=config, log_callback=_log)
        st.session_state["pipeline_result"] = result

        if not result.success:
            _log(f"パイプライン失敗: {result.error_message[:200]}")
            return

        _log("=== パイプライン完了。コード生成フェーズへ ===")
        export_files = get_exported_files(result.export_dir)
        _log(f"エクスポートファイル: {sum(len(v) for v in export_files.values())} 件")

        fig_dir = str(Path(result.output_dir) / "figures")
        code_result = run_code_agent(
            export_files=export_files,
            user_prompt=user_prompt_text,
            output_dir=result.output_dir,
            figure_dir=fig_dir,
            metadata_path=config.metadata_path,
            model=model,
            log_callback=_log,
            install_callback=_make_install_callback(),
        )
        st.session_state["code_result"] = code_result
        st.session_state["last_export_dir"] = result.export_dir

        if code_result.success:
            _log(f"コード実行成功。図: {len(code_result.figures)} 件")
        else:
            _log(f"コード実行失敗（{code_result.retry_count} 回試行）")

    except Exception as e:
        import traceback
        _log(f"予期しないエラー: {e}")
        _log(traceback.format_exc())
    finally:
        st.session_state["running"] = False


def _thread_code_only(
    user_prompt_text: str,
    export_dir: str,
    model: str,
):
    """既存エクスポートデータを使ったコード生成のみ"""
    try:
        export_files = get_exported_files(export_dir)
        if not any(export_files.values()):
            _log(f"エクスポートファイルが見つかりません: {export_dir}")
            return

        fig_dir = str(Path(export_dir).parent / "figures")
        code_result = run_code_agent(
            export_files=export_files,
            user_prompt=user_prompt_text,
            output_dir=str(Path(export_dir).parent),
            figure_dir=fig_dir,
            model=model,
            log_callback=_log,
            install_callback=_make_install_callback(),
        )
        st.session_state["code_result"] = code_result

        if code_result.success:
            _log(f"コード実行成功。図: {len(code_result.figures)} 件")
        else:
            _log(f"コード実行失敗（{code_result.retry_count} 回試行）")

    except Exception as e:
        import traceback
        _log(f"予期しないエラー: {e}")
        _log(traceback.format_exc())
    finally:
        st.session_state["running"] = False


# ─────────────────────────────────────────────────────────────────────────────
# ボタンイベント処理
# ─────────────────────────────────────────────────────────────────────────────

if run_full and not st.session_state["running"]:
    st.session_state["running"] = True
    st.session_state["log_lines"] = []
    st.session_state["pipeline_result"] = None
    st.session_state["code_result"] = None

    config = PipelineConfig(
        fastq_dir=fastq_dir,
        paired_end=paired_end,
        trim_left_f=int(trim_left_f),
        trim_left_r=int(trim_left_r),
        trunc_len_f=int(trunc_len_f),
        trunc_len_r=int(trunc_len_r),
        metadata_path=metadata_path,
        classifier_path=classifier_path,
        n_threads=int(n_threads),
        sampling_depth=int(sampling_depth),
        group_column=group_column,
    )
    threading.Thread(
        target=_thread_full_pipeline,
        args=(config, user_prompt, selected_model),
        daemon=True,
    ).start()
    st.rerun()

if run_code_only and not st.session_state["running"]:
    export_dir = st.session_state.get("last_export_dir", "") or st.session_state.get("_code_only_export_dir", "")
    if not export_dir:
        st.error(
            "エクスポートディレクトリが指定されていません。"
            "パイプラインを先に実行するか、下の入力欄にパスを入力してください。"
        )
    else:
        st.session_state["running"] = True
        st.session_state["log_lines"] = []
        st.session_state["code_result"] = None
        threading.Thread(
            target=_thread_code_only,
            args=(user_prompt, export_dir, selected_model),
            daemon=True,
        ).start()
        st.rerun()

# 実行中はオートリフレッシュ（1秒ごとにログを更新）
if st.session_state["running"] or st.session_state.get("pending_install_pkg"):
    time.sleep(1)
    st.rerun()
