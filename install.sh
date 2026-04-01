#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════╗
# ║  Clow — Instalador Universal                  ║
# ║  Funciona em: Ubuntu, Debian, macOS, WSL, VPS   ║
# ╚══════════════════════════════════════════════════╝

set -e

CLOW_VERSION="0.1.0"
CLOW_HOME="$HOME/.clow"
CLOW_REPO="https://github.com/daniel/clow.git"

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
    echo -e "${CYAN}  Instalador v${CLOW_VERSION}${NC}"
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

    # venv + ensurepip — testa com criação real de venv temporário
    _TESTVENV=$(mktemp -d)
    if ! python3 -m venv "$_TESTVENV" &>/dev/null 2>&1; then
        rm -rf "$_TESTVENV"
        log_warn "python3-venv/ensurepip não funcional. Instalando..."
        PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        case "$OS_NAME" in
            ubuntu|debian)
                apt-get update -qq
                apt-get install -y -qq "python${PY_VER}-venv" 2>/dev/null || \
                apt-get install -y -qq python3-venv
                ;;
            fedora|rhel|centos)
                dnf install -y python3-libs
                ;;
        esac
        log_ok "python3-venv instalado"
    else
        rm -rf "$_TESTVENV"
        log_ok "python3-venv OK"
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

# ── Instala o Clow ────────────────────────────────────
install_clow() {
    log_info "Instalando Clow..."

    # Cria diretório home
    mkdir -p "$CLOW_HOME"
    mkdir -p "$CLOW_HOME/sessions"
    mkdir -p "$CLOW_HOME/memory"
    mkdir -p "$CLOW_HOME/plugins"

    # Se já existe instalação, atualiza
    if [ -d "$CLOW_HOME/app" ]; then
        log_info "Instalação existente encontrada. Atualizando..."
        cd "$CLOW_HOME/app"
        if [ -d ".git" ]; then
            git pull --quiet 2>/dev/null || true
        fi
    else
        # Verifica se o código fonte está local
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/clow" ]; then
            log_info "Instalando a partir do diretório local..."
            cp -r "$SCRIPT_DIR" "$CLOW_HOME/app"
        else
            log_info "Clonando repositório..."
            git clone --quiet "$CLOW_REPO" "$CLOW_HOME/app" 2>/dev/null || {
                # Se o repo não existe ainda, copia local
                log_warn "Repo não acessível. Usando cópia local se disponível."
                if [ -d "/home/daniel/clow/clow" ]; then
                    cp -r /home/daniel/clow "$CLOW_HOME/app"
                else
                    log_err "Não foi possível baixar o Clow."
                    exit 1
                fi
            }
        fi
    fi

    # Cria venv
    log_info "Criando ambiente virtual..."
    cd "$CLOW_HOME/app"

    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi

    # Instala dependências
    log_info "Instalando dependências..."
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -e .

    log_ok "Clow instalado em $CLOW_HOME/app"
}

# ── Configura CLI global ────────────────────────────────
setup_cli() {
    log_info "Configurando comando global 'clow'..."

    # Cria wrapper script
    WRAPPER="$CLOW_HOME/bin/clow"
    mkdir -p "$CLOW_HOME/bin"

    cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/usr/bin/env bash
# Clow CLI wrapper
CLOW_HOME="$HOME/.clow"
exec "$CLOW_HOME/app/.venv/bin/python" -m clow "$@"
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

    PATH_LINE='export PATH="$HOME/.clow/bin:$PATH"'

    if [ -n "$SHELL_RC" ]; then
        if ! grep -q '.clow/bin' "$SHELL_RC" 2>/dev/null; then
            echo "" >> "$SHELL_RC"
            echo "# Clow" >> "$SHELL_RC"
            echo "$PATH_LINE" >> "$SHELL_RC"
            log_ok "PATH adicionado ao $SHELL_RC"
        else
            log_ok "PATH já configurado em $SHELL_RC"
        fi
    fi

    # Também cria symlink em /usr/local/bin se possível
    if [ -w /usr/local/bin ]; then
        ln -sf "$WRAPPER" /usr/local/bin/clow
        log_ok "Symlink criado em /usr/local/bin/clow"
    elif command -v sudo &>/dev/null; then
        sudo ln -sf "$WRAPPER" /usr/local/bin/clow 2>/dev/null && \
            log_ok "Symlink criado em /usr/local/bin/clow" || true
    fi

    export PATH="$CLOW_HOME/bin:$PATH"
}

# ── Configura API key ───────────────────────────────────
setup_api_key() {
    ENV_FILE="$CLOW_HOME/app/.env"

    if [ -f "$ENV_FILE" ] && grep -q "OPENAI_API_KEY" "$ENV_FILE"; then
        log_ok "API key já configurada"
        return
    fi

    echo ""
    echo -e "  ${BOLD}Configuração da API Key${NC}"
    echo ""
    echo -e "  O Clow precisa de uma API key da OpenAI."
    echo -e "  Obtenha em: ${CYAN}https://platform.openai.com/api-keys${NC}"
    echo ""
    read -rp "  Cole sua OpenAI API key (ou Enter para pular): " API_KEY

    if [ -n "$API_KEY" ]; then
        cat > "$ENV_FILE" << EOF
OPENAI_API_KEY=${API_KEY}
CLOW_MODEL=gpt-4.1
EOF
        chmod 600 "$ENV_FILE"
        log_ok "API key salva em $ENV_FILE"
    else
        log_warn "API key não configurada. Defina OPENAI_API_KEY depois."
        cat > "$ENV_FILE" << EOF
OPENAI_API_KEY=
CLOW_MODEL=gpt-4.1
EOF
    fi
}

# ── Verifica instalação ────────────────────────────────
verify_install() {
    echo ""
    log_info "Verificando instalação..."

    if "$CLOW_HOME/bin/clow" --version 2>/dev/null; then
        log_ok "Clow funcionando!"
    else
        log_err "Algo deu errado. Tente rodar manualmente:"
        echo "  $CLOW_HOME/app/.venv/bin/python -m clow --version"
        return 1
    fi
}

# ── Mensagem final ──────────────────────────────────────
print_success() {
    echo ""
    echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Clow instalado com sucesso!${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}Para começar:${NC}"
    echo -e "    ${CYAN}clow${NC}                    — abre o REPL"
    echo -e "    ${CYAN}clow \"sua pergunta\"${NC}     — prompt direto"
    echo -e "    ${CYAN}clow -m gpt-4.1${NC}         — escolher modelo"
    echo -e "    ${CYAN}clow -y${NC}                  — auto-approve"
    echo ""
    echo -e "  ${BOLD}Diretórios:${NC}"
    echo -e "    App:      $CLOW_HOME/app/"
    echo -e "    Sessions: $CLOW_HOME/sessions/"
    echo -e "    Memory:   $CLOW_HOME/memory/"
    echo -e "    Plugins:  $CLOW_HOME/plugins/"
    echo -e "    Config:   $CLOW_HOME/settings.json"
    echo ""
    echo -e "  ${YELLOW}Reinicie o terminal ou rode:${NC}"
    echo -e "    source ~/.bashrc  ${CYAN}# ou ~/.zshrc${NC}"
    echo ""
}

# ── Desinstalação ───────────────────────────────────────
uninstall() {
    echo -e "${YELLOW}Desinstalando Clow...${NC}"
    rm -rf "$CLOW_HOME/app"
    rm -f "$CLOW_HOME/bin/clow"
    rm -f /usr/local/bin/clow 2>/dev/null || sudo rm -f /usr/local/bin/clow 2>/dev/null || true
    log_ok "Clow desinstalado. Sessões e memória preservadas em $CLOW_HOME/"
    echo "  Para remover tudo: rm -rf $CLOW_HOME"
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
            echo "  (sem args)     Instala o Clow"
            echo "  --uninstall    Desinstala o Clow"
            echo "  --help         Mostra esta ajuda"
            exit 0
            ;;
    esac

    detect_os
    install_system_deps
    install_clow
    setup_cli
    setup_api_key
    verify_install
    print_success
}

main "$@"
