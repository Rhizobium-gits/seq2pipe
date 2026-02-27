#!/bin/bash
# ============================================================
# seq2pipe — セットアップスクリプト
# Ollama のインストール・モデルのダウンロードを自動で行います
# ============================================================
set -euo pipefail

# カラー定義
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }

# ============================================================
# バナー
# ============================================================
echo -e "${CYAN}${BOLD}"
echo "╔═══════════════════════════════════════════════════════╗"
echo "║     seq2pipe — セットアップ                           ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ============================================================
# OS 確認
# ============================================================
OS="$(uname -s)"
ARCH="$(uname -m)"
info "OS: $OS / アーキテクチャ: $ARCH"

# ============================================================
# STEP 1: Homebrew の確認（macOS）
# ============================================================
if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
        warn "Homebrew が見つかりません。インストールします..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
        success "Homebrew: $(brew --version | head -1)"
    fi
fi

# ============================================================
# STEP 2: Ollama のインストール
# ============================================================
if command -v ollama &>/dev/null; then
    success "Ollama: $(ollama --version 2>/dev/null || echo 'インストール済み')"
else
    info "Ollama をインストールします..."

    if [[ "$OS" == "Darwin" ]]; then
        # macOS: Homebrew 経由
        if command -v brew &>/dev/null; then
            brew install ollama
        else
            # 直接ダウンロード
            info "Ollama を直接ダウンロードします..."
            curl -fsSL https://ollama.com/install.sh | sh
        fi
    elif [[ "$OS" == "Linux" ]]; then
        curl -fsSL https://ollama.com/install.sh | sh
    else
        error "サポートされていない OS です: $OS"
    fi

    success "Ollama のインストールが完了しました"
fi

# ============================================================
# STEP 3: Ollama サービスの起動
# ============================================================
# プロセス名ではなく API 応答で確認（Codespaces / systemd 対応）
if curl -s http://localhost:11434/api/tags &>/dev/null; then
    success "Ollama サービス: 既に起動中"
else
    info "Ollama サービスを起動します..."
    OLLAMA_BG_PID=""
    if [[ "$OS" == "Darwin" ]]; then
        # macOS: バックグラウンドで直接起動
        nohup ollama serve > /tmp/ollama.log 2>&1 &
        OLLAMA_BG_PID=$!
        info "Ollama をバックグラウンドで起動しました (PID: $OLLAMA_BG_PID)"
    else
        # Linux: service マネージャーを試みるが exit code は信頼しない
        # systemd が動いていれば起動される。動いていなくても後段の nohup で補完する
        if command -v systemctl &>/dev/null; then
            timeout 5 systemctl is-active --quiet ollama 2>/dev/null || \
            timeout 5 sudo systemctl start ollama 2>/dev/null || \
            timeout 5 systemctl --user start ollama 2>/dev/null || true
        fi
        if command -v service &>/dev/null; then
            timeout 5 service ollama start 2>/dev/null || true
        fi
        # API が応答しない場合は必ず nohup で直接起動（service/systemctl の exit code 不問）
        if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
            nohup ollama serve > /tmp/ollama.log 2>&1 &
            OLLAMA_BG_PID=$!
            info "Ollama をバックグラウンドで起動しました (PID: $OLLAMA_BG_PID)"
        fi
    fi

    # 起動確認（最大 120 秒待機、Codespaces のコールドスタートに対応）
    info "Ollama の起動を待っています（最大 120 秒）..."
    for i in {1..120}; do
        if curl -s http://localhost:11434/api/tags &>/dev/null; then
            success "Ollama サービスが起動しました（${i} 秒）"
            break
        fi
        # バックグラウンドプロセスがクラッシュしていたら早期終了
        if [[ -n "${OLLAMA_BG_PID:-}" ]] && ! kill -0 "$OLLAMA_BG_PID" 2>/dev/null; then
            warn "Ollama プロセスがクラッシュしました。ログ:"
            cat /tmp/ollama.log 2>/dev/null | tail -20
            exit 1
        fi
        if [[ $i -eq 120 ]]; then
            warn "Ollama の起動確認がタイムアウトしました（120 秒）。"
            warn "ログ (/tmp/ollama.log):"
            cat /tmp/ollama.log 2>/dev/null | tail -20
            warn "別ターミナルで 'ollama serve' を実行してから setup.sh を再実行してください。"
            exit 1
        fi
        # 進捗表示（10 秒ごと）
        if (( i % 10 == 0 )); then
            info "  待機中... ${i}/120 秒"
        fi
        sleep 1
    done
fi

# ============================================================
# STEP 4: LLM モデルの選択とダウンロード
# ============================================================
echo ""
echo -e "${BOLD}使用するモデルを選択してください:${RESET}"
echo ""
echo "  1) qwen2.5-coder:7b  [推奨] コード生成に特化、高精度（約 4.7GB）"
echo "     → RAM 8GB 以上推奨、Apple Silicon Mac で最速"
echo ""
echo "  2) qwen2.5-coder:3b  [軽量] 精度はやや落ちるが高速（約 1.9GB）"
echo "     → RAM 4GB 以上、古い Mac でも動作"
echo ""
echo "  3) llama3.2:3b       [汎用] 会話能力が高い（約 2.0GB）"
echo "     → コード生成は qwen2.5-coder より低め"
echo ""
echo "  4) qwen3:8b          [最高品質] 推論能力も高い（約 5.2GB）"
echo "     → RAM 16GB 以上推奨"
echo ""
echo "  s) スキップ（既存モデルをそのまま使用）"
echo ""
read -rp "選択 [1/2/3/4/s]: " MODEL_CHOICE

case "$MODEL_CHOICE" in
    1|"") MODEL="qwen2.5-coder:7b" ;;
    2)    MODEL="qwen2.5-coder:3b" ;;
    3)    MODEL="llama3.2:3b" ;;
    4)    MODEL="qwen3:8b" ;;
    s|S)
        info "モデルのダウンロードをスキップします"
        MODEL=""
        ;;
    *)
        MODEL="qwen2.5-coder:7b"
        warn "無効な選択です。デフォルト ($MODEL) を使用します"
        ;;
esac

if [[ -n "$MODEL" ]]; then
    # 既にインストール済みか確認
    if ollama list 2>/dev/null | grep -q "^${MODEL%%:*}"; then
        success "モデル '$MODEL' は既にインストールされています"
    else
        info "モデル '$MODEL' をダウンロードします（回線速度により数分〜十数分かかります）..."
        ollama pull "$MODEL"
        success "モデル '$MODEL' のダウンロードが完了しました"
    fi

    # 使用モデルを設定ファイルに保存
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo "QIIME2_AI_MODEL=$MODEL" > "$SCRIPT_DIR/.env"
    success "モデル設定を .env に保存しました"
fi

# ============================================================
# STEP 5: conda / miniforge の確認・インストール
# ============================================================
echo ""
info "conda（miniforge）を確認します..."

CONDA_CMD=""
for _c in conda mamba micromamba; do
    if command -v "$_c" &>/dev/null; then
        CONDA_CMD="$_c"
        break
    fi
done
# PATH 非登録でも直接バイナリを探す
if [[ -z "$CONDA_CMD" ]]; then
    for _p in \
        "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" \
        "$HOME/anaconda3/bin/conda" "$HOME/mambaforge/bin/conda"; do
        if [[ -x "$_p" ]]; then
            CONDA_CMD="$_p"
            break
        fi
    done
fi

if [[ -n "$CONDA_CMD" ]]; then
    success "conda: $("$CONDA_CMD" --version 2>/dev/null || echo '検出済み')"
else
    warn "conda が見つかりません。Miniforge3 をインストールします..."
    if [[ "$OS" == "Darwin" ]]; then
        if [[ "$ARCH" == "arm64" ]]; then
            _MF_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh"
        else
            _MF_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-x86_64.sh"
        fi
    else
        _MF_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
    fi
    curl -fsSL -o /tmp/miniforge_install.sh "$_MF_URL"
    bash /tmp/miniforge_install.sh -b -p "$HOME/miniforge3"
    rm -f /tmp/miniforge_install.sh
    CONDA_CMD="$HOME/miniforge3/bin/conda"
    # 現シェルで conda を有効化
    # shellcheck disable=SC1091
    source "$HOME/miniforge3/etc/profile.d/conda.sh" 2>/dev/null || true
    success "Miniforge3 のインストールが完了しました: $HOME/miniforge3"
fi

# ============================================================
# STEP 6: QIIME2 conda 環境の確認・インストール
# ============================================================
echo ""
info "QIIME2 conda 環境を確認します..."

# 既存の qiime2* 環境を検索
_QIIME2_BIN=""
if [[ -n "$CONDA_CMD" ]]; then
    _CONDA_BASE="$("$CONDA_CMD" info --base 2>/dev/null || echo '')"
    if [[ -n "$_CONDA_BASE" && -d "$_CONDA_BASE/envs" ]]; then
        for _env_dir in "$_CONDA_BASE/envs"/qiime2*; do
            if [[ -x "$_env_dir/bin/qiime" ]]; then
                _QIIME2_BIN="$_env_dir/bin"
                break
            fi
        done
    fi
fi

if [[ -n "$_QIIME2_BIN" ]]; then
    success "QIIME2 conda 環境: $_QIIME2_BIN"
else
    echo ""
    warn "QIIME2 conda 環境が見つかりません。"
    echo ""
    read -rp "QIIME2 を今すぐインストールしますか？（約 3-5 GB・数十分かかります）[y/N]: " _INSTALL_QIIME2
    if [[ "$(echo "$_INSTALL_QIIME2" | tr "A-Z" "a-z")" == "y" ]]; then
        # プラットフォーム別 yml URL
        _QIIME2_VER="2024.10"
        if [[ "$OS" == "Darwin" ]]; then
            _YML_URL="https://data.qiime2.org/distro/amplicon/qiime2-amplicon-${_QIIME2_VER}-py310-osx-conda.yml"
        else
            _YML_URL="https://data.qiime2.org/distro/amplicon/qiime2-amplicon-${_QIIME2_VER}-py310-linux-conda.yml"
        fi
        QENV_NAME="qiime2-amplicon-${_QIIME2_VER}"
        QYML_FILE="/tmp/qiime2-env.yml"

        info "YML download: ${_YML_URL}"
        curl -fsSL -o "${QYML_FILE}" "${_YML_URL}"

        info "QIIME2 conda env create: ${QENV_NAME}"
        info "  (network speed: 10-60 min)"
        # Apple Silicon (arm64): QIIME2 deps require x86_64 packages via Rosetta 2
        if [[ "$(uname -m)" == "arm64" && "${OS}" == "Darwin" ]]; then
            info "  Apple Silicon detected: using CONDA_SUBDIR=osx-64 (Rosetta 2)"
            CONDA_SUBDIR=osx-64 "${CONDA_CMD}" env create -n "${QENV_NAME}" --file "${QYML_FILE}" -y
            # persist subdir so future conda installs in this env also use osx-64
            "${CONDA_CMD}" env config vars set CONDA_SUBDIR=osx-64 -n "${QENV_NAME}" 2>/dev/null || true
        else
            "${CONDA_CMD}" env create -n "${QENV_NAME}" --file "${QYML_FILE}" -y
        fi
        rm -f "${QYML_FILE}"

        QCONDA_BASE="$("${CONDA_CMD}" info --base 2>/dev/null || echo '')"
        _QIIME2_BIN="${QCONDA_BASE}/envs/${QENV_NAME}/bin"
        success "QIIME2 (${QENV_NAME}) install done"
        success "  path: ${_QIIME2_BIN}"
    else
        warn "QIIME2 のインストールをスキップしました。"
        warn "後でインストールする場合は ./setup.sh を再実行してください。"
    fi
fi

# QIIME2 環境の Python パッケージ（pandas / matplotlib 等）確認
if [[ -n "$_QIIME2_BIN" && -x "$_QIIME2_BIN/python3" ]]; then
    _QIIME2_PYTHON="$_QIIME2_BIN/python3"
    MISSING_QIIME2_PKGS=()
    for _pkg in matplotlib seaborn scikit-learn statsmodels; do
        if ! "$_QIIME2_PYTHON" -c "import $_pkg" &>/dev/null 2>&1; then
            MISSING_QIIME2_PKGS+=("$_pkg")
        fi
    done
    if [[ ${#MISSING_QIIME2_PKGS[@]} -gt 0 ]]; then
        info "QIIME2 環境に不足パッケージを追加: ${MISSING_QIIME2_PKGS[*]}"
        "$_QIIME2_BIN/pip" install --quiet "${MISSING_QIIME2_PKGS[@]}" tectonic 2>/dev/null || true
    fi
fi

# ============================================================
# STEP 7: Docker の確認・インストール（Linux のみ自動インストール）
# ============================================================
echo ""
info "Docker の状態を確認します..."

# プラットフォーム別 Docker コマンドの解決
if [[ "$OS" == "Darwin" ]]; then
    DOCKER_CMD="/Applications/Docker.app/Contents/Resources/bin/docker"
    [[ ! -f "$DOCKER_CMD" ]] && DOCKER_CMD="$(command -v docker || echo '')"
else
    DOCKER_CMD="$(command -v docker || echo '')"
fi

if [[ -n "$DOCKER_CMD" ]] && command -v "$DOCKER_CMD" &>/dev/null; then
    if "$DOCKER_CMD" info &>/dev/null 2>&1; then
        success "Docker: 起動中"
        "$DOCKER_CMD" --version
    else
        warn "Docker がインストールされていますが、起動していません。"
        if [[ "$OS" == "Darwin" ]]; then
            warn "Docker Desktop を起動してから QIIME2 解析を開始してください。"
        elif [[ "$OS" == "Linux" ]]; then
            warn "Docker サービスを起動します..."
            if command -v systemctl &>/dev/null; then
                sudo systemctl start docker 2>/dev/null && \
                    success "Docker サービスを起動しました" || \
                    warn "sudo systemctl start docker を手動で実行してください"
            else
                sudo service docker start 2>/dev/null || \
                    warn "sudo service docker start を手動で実行してください"
            fi
        fi
    fi
else
    if [[ "$OS" == "Darwin" ]]; then
        warn "Docker Desktop が見つかりません。"
        echo ""
        echo "  QIIME2 の実行には Docker Desktop が必要です:"
        echo "  → https://www.docker.com/products/docker-desktop/"
        echo "  ※ Apple Silicon Mac の場合は「Apple Chip」版を選択してください"
    elif [[ "$OS" == "Linux" ]]; then
        warn "Docker が見つかりません。Docker Engine をインストールします..."
        echo ""
        read -rp "Docker Engine を自動インストールしますか? (sudo 権限が必要) [y/N]: " INSTALL_DOCKER
        if [[ "$(echo "$INSTALL_DOCKER" | tr "A-Z" "a-z")" == "y" ]]; then
            info "Docker 公式スクリプトでインストールします..."
            curl -fsSL https://get.docker.com | sudo sh
            # 現ユーザーを docker グループに追加（sudo なしで使えるように）
            sudo usermod -aG docker "$USER"
            # Docker サービスを起動・自動起動設定
            if command -v systemctl &>/dev/null; then
                sudo systemctl enable --now docker
            fi
            success "Docker Engine のインストールが完了しました"
            warn "グループ変更を反映するため、一度ログアウト／再ログインしてください。"
            warn "または 'newgrp docker' を実行してから launch.sh を再起動してください。"
        else
            echo "  インストール手順: https://docs.docker.com/engine/install/"
        fi
    fi
    DOCKER_CMD=""
fi

# ============================================================
# STEP 8: Python ダウンストリーム解析パッケージのインストール
# ============================================================
echo ""
info "Python ダウンストリーム解析パッケージを確認します..."

PYTHON_CMD="$(command -v python3 || command -v python || echo '')"
if [[ -z "$PYTHON_CMD" ]]; then
    warn "Python が見つかりません。パッケージのインストールをスキップします。"
else
    PY_VERSION="$("$PYTHON_CMD" --version 2>&1)"
    success "Python: $PY_VERSION"

    # 必要パッケージの確認
    MISSING_PKGS=()
    for pkg in numpy pandas matplotlib seaborn scipy scikit-learn; do
        if ! "$PYTHON_CMD" -c "import $(echo $pkg | tr '-' '_' | cut -d'[' -f1)" &>/dev/null 2>&1; then
            MISSING_PKGS+=("$pkg")
        fi
    done

    if [[ ${#MISSING_PKGS[@]} -eq 0 ]]; then
        success "Python 解析パッケージ: すべてインストール済み"
    else
        echo ""
        warn "以下のパッケージが不足しています: ${MISSING_PKGS[*]}"
        echo ""
        read -rp "Python ダウンストリーム解析パッケージをインストールしますか? [y/N]: " INSTALL_PY_PKGS
        if [[ "$(echo "$INSTALL_PY_PKGS" | tr "A-Z" "a-z")" == "y" ]]; then
            info "パッケージをインストールします..."
            "$PYTHON_CMD" -m pip install --quiet \
                numpy pandas matplotlib seaborn scipy scikit-learn \
                biom-format networkx statsmodels
            success "Python パッケージのインストールが完了しました"
            success "  インストール済み: numpy, pandas, matplotlib, seaborn, scipy,"
            success "                   scikit-learn, biom-format, networkx, statsmodels"
        else
            info "スキップしました。後でインストールする場合:"
            echo "  pip install numpy pandas matplotlib seaborn scipy scikit-learn biom-format networkx statsmodels"
        fi
    fi
fi

# ============================================================
# STEP 9: QIIME2 Docker イメージの確認（オプション）
# ============================================================
if [[ -n "$DOCKER_CMD" ]] && [[ -x "$DOCKER_CMD" ]] && "$DOCKER_CMD" info &>/dev/null 2>&1; then
    echo ""
    read -rp "QIIME2 Docker イメージ (quay.io/qiime2/amplicon:2026.1) を今すぐプルしますか? [y/N]: " PULL_QIIME2
    if [[ "$(echo "$PULL_QIIME2" | tr "A-Z" "a-z")" == "y" ]]; then
        info "QIIME2 Docker イメージをダウンロードします（約 2-4 GB）..."
        "$DOCKER_CMD" pull quay.io/qiime2/amplicon:2026.1
        success "QIIME2 Docker イメージの取得が完了しました"
    else
        info "QIIME2 Docker イメージのダウンロードはスキップします（初回解析時に自動取得）"
    fi
fi

# ============================================================
# 完了メッセージ
# ============================================================
echo ""
echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════════════╗"
echo "║  セットアップが完了しました！                         ║"
echo "╚═══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo "次のステップ:"
echo ""
if [[ "$OS" == "Darwin" ]]; then
    echo "  1. Docker Desktop を起動してください（アプリケーションから）"
elif [[ "$OS" == "Linux" ]]; then
    echo "  1. Docker が起動していない場合: sudo systemctl start docker"
else
    echo "  1. Docker を起動してください"
fi
echo ""
echo "  2. Ollama を起動してください（既に起動中なら不要）:"
echo -e "     ${CYAN}ollama serve${RESET}"
echo ""
echo "  3. エージェントを起動してください:"
echo -e "     ${CYAN}./launch.sh${RESET}"
echo ""
echo "  ※ 初回 QIIME2 解析時に Docker イメージ (~4GB) を自動取得します"
echo "  ※ 分類器 (SILVA 138) の構築には別途 30GB のディスクと 2-5 時間が必要です"
echo "  ※ Python 解析パッケージ未インストールの場合:"
echo "     pip install numpy pandas matplotlib seaborn scipy scikit-learn biom-format networkx statsmodels"
echo ""
