#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════╗
# ║  Batmam — Instalador Universal                  ║
# ║  Funciona em: Ubuntu, Debian, macOS, WSL, VPS   ║
# ╚══════════════════════════════════════════════════╝

set -e

BATMAM_VERSION="0.1.0"
BATMAM_HOME="$HOME/.batmam"
BATMAM_REPO="https://github.com/daniel/batmam.git"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_banner() {
    echo -e "${YELLOW}"
    echo " ____        _"
    echo "| __ )  __ _| |_ _ __ ___   __ _ _ __ ___"
    echo "|  _ \\ / _\` | __| '_ \` _ \\ / _\` | '_ \` _ \\"
    echo "| |_) | (_| | |_| | | | | | (_| | | | | | |"
    echo "|____/ \\__,_|\\__|_| |_| |_|\\__,_|_| |_| |_|"
    echo -e "${NC}"
    echo -e "${CYAN}  Instalador v${BATMAM_VERSION}${NC}"
    echo ""
}

log_info() { echo -e "  ${CYAN}→${NC} $1"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }

# ── Detecta sistema ──────────────────────────────────────
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS_NAME="$ID"
            OS_VERSION="$VERSION_ID"
        else
            OS_NAME="linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS_NAME="macos"
    else
        OS_NAME="unknown"
    fi
    log_info "Sistema detectado: ${BOLD}${OS_NAME}${NC}"
}

# ── Instala dependências do sistema ─────────────────────
install_system_deps() {
    log_info "Verificando dependências do sistema..."

    # Python 3.10+
    if command -v python3 &>/dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        log_ok "Python ${PYTHON_VERSION} encontrado"
    else
        log_warn "Python3 não encontrado. Instalando..."
        case "$OS_NAME" in
            ubuntu|debian)
                sudo apt-get update -qq
                sudo apt-get install -y -qq python3 python3-pip python3-venv
                ;;
            fedora|rhel|centos)
                sudo dnf install -y python3 python3-pip
                ;;
            macos)
                if command -v brew &>/dev/null; then
                    brew install python@3.12
                else
                    log_err "Instale o Homebrew primeiro: https://brew.sh"
                    exit 1
                fi
                ;;
            *)
                log_err "Instale Python 3.10+ manualmente e rode este script novamente."
                exit 1
                ;;
        esac
        log_ok "Python instalado"
    fi

    # pip
    if ! python3 -m pip --version &>/dev/null; then
        log_warn "pip não encontrado. Instalando..."
        case "$OS_NAME" in
            ubuntu|debian) sudo apt-get install -y -qq python3-pip ;;
            *) python3 -m ensurepip --upgrade 2>/dev/null || true ;;
        esac
    fi

    # venv — instala o pacote correto para a versão do Python
    if ! python3 -m venv --help &>/dev/null 2>&1; then
        log_warn "python3-venv não encontrado. Instalando..."
        PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        case "$OS_NAME" in
            ubuntu|debian)
                sudo apt-get update -qq
                sudo apt-get install -y -qq "python${PY_VER}-venv" python3-venv 2>/dev/null || \
                sudo apt-get install -y -qq python3-venv
                ;;
            fedora|rhel|centos)
                sudo dnf install -y python3-libs
                ;;
        esac
    fi

    # git
    if ! command -v git &>/dev/null; then
        log_warn "git não encontrado. Instalando..."
        case "$OS_NAME" in
            ubuntu|debian) sudo apt-get install -y -qq git ;;
            fedora|rhel|centos) sudo dnf install -y git ;;
            macos) xcode-select --install 2>/dev/null || true ;;
        esac
    fi
}

# ── Instala o Batmam ────────────────────────────────────
install_batmam() {
    log_info "Instalando Batmam..."

    # Cria diretório home
    mkdir -p "$BATMAM_HOME"
    mkdir -p "$BATMAM_HOME/sessions"
    mkdir -p "$BATMAM_HOME/memory"
    mkdir -p "$BATMAM_HOME/plugins"

    # Se já existe instalação, atualiza
    if [ -d "$BATMAM_HOME/app" ]; then
        log_info "Instalação existente encontrada. Atualizando..."
        cd "$BATMAM_HOME/app"
        if [ -d ".git" ]; then
            git pull --quiet 2>/dev/null || true
        fi
    else
        # Verifica se o código fonte está local
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/batmam" ]; then
            log_info "Instalando a partir do diretório local..."
            cp -r "$SCRIPT_DIR" "$BATMAM_HOME/app"
        else
            log_info "Clonando repositório..."
            git clone --quiet "$BATMAM_REPO" "$BATMAM_HOME/app" 2>/dev/null || {
                # Se o repo não existe ainda, copia local
                log_warn "Repo não acessível. Usando cópia local se disponível."
                if [ -d "/home/daniel/batmam/batmam" ]; then
                    cp -r /home/daniel/batmam "$BATMAM_HOME/app"
                else
                    log_err "Não foi possível baixar o Batmam."
                    exit 1
                fi
            }
        fi
    fi

    # Cria venv
    log_info "Criando ambiente virtual..."
    cd "$BATMAM_HOME/app"

    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi

    # Instala dependências
    log_info "Instalando dependências..."
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -e .

    log_ok "Batmam instalado em $BATMAM_HOME/app"
}

# ── Configura CLI global ────────────────────────────────
setup_cli() {
    log_info "Configurando comando global 'batmam'..."

    # Cria wrapper script
    WRAPPER="$BATMAM_HOME/bin/batmam"
    mkdir -p "$BATMAM_HOME/bin"

    cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/usr/bin/env bash
# Batmam CLI wrapper
BATMAM_HOME="$HOME/.batmam"
exec "$BATMAM_HOME/app/.venv/bin/python" -m batmam "$@"
WRAPPER_EOF
    chmod +x "$WRAPPER"

    # Adiciona ao PATH
    SHELL_RC=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.profile" ]; then
        SHELL_RC="$HOME/.profile"
    fi

    PATH_LINE='export PATH="$HOME/.batmam/bin:$PATH"'

    if [ -n "$SHELL_RC" ]; then
        if ! grep -q '.batmam/bin' "$SHELL_RC" 2>/dev/null; then
            echo "" >> "$SHELL_RC"
            echo "# Batmam" >> "$SHELL_RC"
            echo "$PATH_LINE" >> "$SHELL_RC"
            log_ok "PATH adicionado ao $SHELL_RC"
        else
            log_ok "PATH já configurado em $SHELL_RC"
        fi
    fi

    # Também cria symlink em /usr/local/bin se possível
    if [ -w /usr/local/bin ]; then
        ln -sf "$WRAPPER" /usr/local/bin/batmam
        log_ok "Symlink criado em /usr/local/bin/batmam"
    elif command -v sudo &>/dev/null; then
        sudo ln -sf "$WRAPPER" /usr/local/bin/batmam 2>/dev/null && \
            log_ok "Symlink criado em /usr/local/bin/batmam" || true
    fi

    export PATH="$BATMAM_HOME/bin:$PATH"
}

# ── Configura API key ───────────────────────────────────
setup_api_key() {
    ENV_FILE="$BATMAM_HOME/app/.env"

    if [ -f "$ENV_FILE" ] && grep -q "OPENAI_API_KEY" "$ENV_FILE"; then
        log_ok "API key já configurada"
        return
    fi

    echo ""
    echo -e "  ${BOLD}Configuração da API Key${NC}"
    echo ""
    echo -e "  O Batmam precisa de uma API key da OpenAI."
    echo -e "  Obtenha em: ${CYAN}https://platform.openai.com/api-keys${NC}"
    echo ""
    read -rp "  Cole sua OpenAI API key (ou Enter para pular): " API_KEY

    if [ -n "$API_KEY" ]; then
        cat > "$ENV_FILE" << EOF
OPENAI_API_KEY=${API_KEY}
BATMAM_MODEL=gpt-4.1
EOF
        chmod 600 "$ENV_FILE"
        log_ok "API key salva em $ENV_FILE"
    else
        log_warn "API key não configurada. Defina OPENAI_API_KEY depois."
        cat > "$ENV_FILE" << EOF
OPENAI_API_KEY=
BATMAM_MODEL=gpt-4.1
EOF
    fi
}

# ── Verifica instalação ────────────────────────────────
verify_install() {
    echo ""
    log_info "Verificando instalação..."

    if "$BATMAM_HOME/bin/batmam" --version 2>/dev/null; then
        log_ok "Batmam funcionando!"
    else
        log_err "Algo deu errado. Tente rodar manualmente:"
        echo "  $BATMAM_HOME/app/.venv/bin/python -m batmam --version"
        return 1
    fi
}

# ── Mensagem final ──────────────────────────────────────
print_success() {
    echo ""
    echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Batmam instalado com sucesso!${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Para começar:${NC}"
    echo -e "    ${CYAN}batmam${NC}                    — abre o REPL"
    echo -e "    ${CYAN}batmam \"sua pergunta\"${NC}     — prompt direto"
    echo -e "    ${CYAN}batmam -m gpt-4.1${NC}         — escolher modelo"
    echo -e "    ${CYAN}batmam -y${NC}                  — auto-approve"
    echo ""
    echo -e "  ${BOLD}Diretórios:${NC}"
    echo -e "    App:      $BATMAM_HOME/app/"
    echo -e "    Sessions: $BATMAM_HOME/sessions/"
    echo -e "    Memory:   $BATMAM_HOME/memory/"
    echo -e "    Plugins:  $BATMAM_HOME/plugins/"
    echo -e "    Config:   $BATMAM_HOME/settings.json"
    echo ""
    echo -e "  ${YELLOW}Reinicie o terminal ou rode:${NC}"
    echo -e "    source ~/.bashrc  ${CYAN}# ou ~/.zshrc${NC}"
    echo ""
}

# ── Desinstalação ───────────────────────────────────────
uninstall() {
    echo -e "${YELLOW}Desinstalando Batmam...${NC}"
    rm -rf "$BATMAM_HOME/app"
    rm -f "$BATMAM_HOME/bin/batmam"
    rm -f /usr/local/bin/batmam 2>/dev/null || sudo rm -f /usr/local/bin/batmam 2>/dev/null || true
    log_ok "Batmam desinstalado. Sessões e memória preservadas em $BATMAM_HOME/"
    echo "  Para remover tudo: rm -rf $BATMAM_HOME"
}

# ── Main ────────────────────────────────────────────────
main() {
    print_banner

    case "${1:-}" in
        --uninstall|-u)
            uninstall
            exit 0
            ;;
        --help|-h)
            echo "Uso: ./install.sh [opções]"
            echo ""
            echo "Opções:"
            echo "  (sem args)     Instala o Batmam"
            echo "  --uninstall    Desinstala o Batmam"
            echo "  --help         Mostra esta ajuda"
            exit 0
            ;;
    esac

    detect_os
    install_system_deps
    install_batmam
    setup_cli
    setup_api_key
    verify_install
    print_success
}

main "$@"
