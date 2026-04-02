"""ClowSpinner — feedback visual pulsante estilo Claude Code.

Thread daemon que anima o simbolo ∞ pulsando em roxo enquanto
o agente trabalha. Funciona durante bash commands longos, pytest,
build, deploy — qualquer operacao demorada.

Compativel com Windows (cmd, PowerShell) e Unix. ANSI puro, sem curses.
"""

from __future__ import annotations
import sys
import os
import threading


# Frames ANSI com fade in/fade out roxo (8 frames, ciclo ~1.2s)
_FRAMES = [
    "\033[38;5;55m\u221e\033[0m",    # roxo muito escuro
    "\033[38;5;56m\u221e\033[0m",    # escuro
    "\033[38;5;93m\u221e\033[0m",    # medio
    "\033[38;5;129m\u221e\033[0m",   # medio-brilhante
    "\033[38;5;165m\u221e\033[0m",   # brilhante (peak)
    "\033[38;5;129m\u221e\033[0m",   # medio-brilhante (volta)
    "\033[38;5;93m\u221e\033[0m",    # medio (volta)
    "\033[38;5;56m\u221e\033[0m",    # escuro (volta)
]

# Fallback para terminais sem UTF-8
_FRAMES_ASCII = [f.replace("\u221e", "*") for f in _FRAMES]

_INTERVAL = 0.15   # 150ms entre frames
_LABEL_COLOR = "\033[2m"  # dim/cinza
_RESET = "\033[0m"


def _get_terminal_width() -> int:
    """Largura do terminal, fallback 80."""
    try:
        return os.get_terminal_size().columns
    except (ValueError, OSError):
        return 80


class ClowSpinner:
    """Spinner ∞ roxo pulsante para feedback visual.

    Uso:
        spinner = ClowSpinner()
        spinner.start("Pensando...")
        # ... operacao demorada ...
        spinner.stop()
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._label = ""
        self._lock = threading.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, label: str = "") -> None:
        """Inicia a animacao com label opcional.

        Se ja estiver rodando, para e reinicia com novo label.
        """
        if self._running:
            self.stop()

        self._label = label
        self._stop_event.clear()
        self._running = True

        self._thread = threading.Thread(
            target=self._animate,
            daemon=True,
            name="clow-spinner",
        )
        self._thread.start()

    def stop(self) -> None:
        """Para a animacao e limpa a linha."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None

        # Limpa a linha inteira
        self._clear_line()

    def update_label(self, new_label: str) -> None:
        """Troca o texto sem reiniciar a animacao."""
        with self._lock:
            self._label = new_label

    def _animate(self) -> None:
        """Loop de animacao — roda na thread daemon."""
        frame_idx = 0
        use_ascii = False

        while not self._stop_event.is_set():
            # Escolhe frame
            frames = _FRAMES_ASCII if use_ascii else _FRAMES
            inf = frames[frame_idx % len(frames)]

            # Le label com lock
            with self._lock:
                label = self._label

            # Monta linha: "  ∞ label"
            if label:
                line = f"  {inf} {_LABEL_COLOR}{label}{_RESET}"
            else:
                line = f"  {inf}"

            # Escreve com \r para sobrescrever a linha
            try:
                sys.stdout.write(f"\r{line}")
                # Limpa o resto da linha com espacos
                width = _get_terminal_width()
                # Calcula tamanho visivel (sem ANSI escapes)
                visible_len = len(f"  \u221e {label}") if label else len("  \u221e")
                padding = max(0, width - visible_len - 1)
                sys.stdout.write(" " * padding)
                sys.stdout.write("\r")  # Volta cursor pro inicio
                sys.stdout.write(f"\r{line}")
                sys.stdout.flush()
            except UnicodeEncodeError:
                use_ascii = True
                continue
            except (BrokenPipeError, OSError):
                break

            frame_idx += 1
            self._stop_event.wait(_INTERVAL)

        # Limpa ao sair
        self._clear_line()

    def _clear_line(self) -> None:
        """Limpa a linha inteira."""
        try:
            width = _get_terminal_width()
            sys.stdout.write("\r" + " " * width + "\r")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass
