#!/bin/bash
# ============================================================
# QIIME2 Local AI Agent — セットアップスクリプト
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
echo "║     QIIME2 Local AI Agent — セットアップ             ║"
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
if pgrep -x "ollama" &>/dev/null; then
    success "Ollama サービス: 既に起動中"
else
    info "Ollama サービスを起動します..."
    if [[ "$OS" == "Darwin" ]]; then
        # macOS: バックグラウンドで起動
        nohup ollama serve > /tmp/ollama.log 2>&1 &
        sleep 3
    else
        # Linux: systemd 経由
        if command -v systemctl &>/dev/null; then
            systemctl --user enable --now ollama 2>/dev/null || \
            nohup ollama serve > /tmp/ollama.log 2>&1 &
        else
            nohup ollama serve > /tmp/ollama.log 2>&1 &
        fi
        sleep 3
    fi

    # 起動確認（最大 15 秒待機）
    for i in {1..15}; do
        if curl -s http://localhost:11434/api/tags &>/dev/null; then
            success "Ollama サービスが起動しました"
            break
        fi
        if [[ $i -eq 15 ]]; then
            warn "Ollama の起動確認がタイムアウトしました。手動で 'ollama serve' を実行してください。"
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
# STEP 5: Docker Desktop の確認
# ============================================================
echo ""
info "Docker Desktop の状態を確認します..."

DOCKER_PATH="/Applications/Docker.app/Contents/Resources/bin/docker"
if [[ -f "$DOCKER_PATH" ]] || command -v docker &>/dev/null; then
    DOCKER_CMD="${DOCKER_PATH:-docker}"
    if "$DOCKER_CMD" info &>/dev/null 2>&1; then
        success "Docker Desktop: 起動中"
        "$DOCKER_CMD" --version
    else
        warn "Docker Desktop がインストールされていますが、起動していません。"
        warn "Docker Desktop を起動してから QIIME2 解析を開始してください。"
    fi
else
    warn "Docker Desktop が見つかりません。"
    echo ""
    echo "  QIIME2 の実行には Docker Desktop が必要です。"
    echo "  以下からダウンロードしてインストールしてください:"
    echo "  → https://www.docker.com/products/docker-desktop/"
    echo ""
    echo "  ※ Apple Silicon Mac の場合は「Apple Chip」版を選択してください"
fi

# ============================================================
# STEP 6: QIIME2 Docker イメージの確認（オプション）
# ============================================================
DOCKER_CMD="/Applications/Docker.app/Contents/Resources/bin/docker"
[[ ! -f "$DOCKER_CMD" ]] && DOCKER_CMD="docker"

if command -v "$DOCKER_CMD" &>/dev/null && "$DOCKER_CMD" info &>/dev/null 2>&1; then
    echo ""
    read -rp "QIIME2 Docker イメージ (quay.io/qiime2/amplicon:2026.1) を今すぐプルしますか? [y/N]: " PULL_QIIME2
    if [[ "${PULL_QIIME2,,}" == "y" ]]; then
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
echo "  1. Docker Desktop を起動してください（アプリケーションから）"
echo ""
echo "  2. Ollama を起動してください（既に起動中なら不要）:"
echo -e "     ${CYAN}ollama serve${RESET}"
echo ""
echo "  3. エージェントを起動してください:"
echo -e "     ${CYAN}./launch.sh${RESET}"
echo ""
echo "  ※ 初回 QIIME2 解析時に Docker イメージ (~4GB) を自動取得します"
echo "  ※ 分類器 (SILVA 138) の構築には別途 30GB のディスクと 2-5 時間が必要です"
echo ""
