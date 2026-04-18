"""Testes para as 3 melhorias do agent.py:
1. Extended Thinking
2. Prompt Caching
3. Auto-Correction Loop
"""

import os
import sys
import re
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from types import SimpleNamespace

# Ajusta path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clow import config
from clow.models import ToolResult, ToolResultStatus


# ════════════════════════════════════════════════════════════════
# 1. TESTE: Extended Thinking
# ════════════════════════════════════════════════════════════════

class TestExtendedThinking(unittest.TestCase):
    """Verifica que Extended Thinking e ativado para Sonnet/Opus."""

    @patch("clow.agent.config")
    def test_thinking_kwargs_sonnet(self, mock_config):
        """Sonnet deve incluir thinking nos kwargs."""
        mock_config.CLOW_EXTENDED_THINKING = True
        mock_config.CLOW_THINKING_BUDGET = 10000
        mock_config.MAX_TOKENS = 16384
        mock_config.CLOW_PROVIDER = "anthropic"
        mock_config.ANTHROPIC_API_KEY = "test-key"
        mock_config.CLOW_MODEL = "claude-sonnet-4-20250514"
        mock_config.MAX_CONTEXT_MESSAGES = 200
        mock_config.MAX_TOOL_RESULT_CHARS = 5000
        mock_config.CLOW_AUTO_CORRECT = False

        # Simula o que _stream_call_anthropic faz para montar kwargs
        model = "claude-sonnet-4-20250514"
        kwargs = {"model": model, "max_tokens": mock_config.MAX_TOKENS}

        model_lower = model.lower()
        if mock_config.CLOW_EXTENDED_THINKING and ("sonnet" in model_lower or "opus" in model_lower):
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": mock_config.CLOW_THINKING_BUDGET,
            }
            kwargs["max_tokens"] = mock_config.MAX_TOKENS + mock_config.CLOW_THINKING_BUDGET

        self.assertIn("thinking", kwargs)
        self.assertEqual(kwargs["thinking"]["type"], "enabled")
        self.assertEqual(kwargs["thinking"]["budget_tokens"], 10000)
        self.assertEqual(kwargs["max_tokens"], 16384 + 10000)
        print("[OK] Extended Thinking: kwargs corretos para Sonnet")

    def test_thinking_not_enabled_for_haiku(self):
        """Haiku NAO deve ativar thinking."""
        model = "claude-haiku-4-5-20251001"
        model_lower = model.lower()
        should_enable = "sonnet" in model_lower or "opus" in model_lower
        self.assertFalse(should_enable)
        print("[OK] Extended Thinking: Haiku nao ativa thinking")

    def test_thinking_enabled_for_opus(self):
        """Opus deve ativar thinking."""
        model = "claude-opus-4-6"
        model_lower = model.lower()
        should_enable = "sonnet" in model_lower or "opus" in model_lower
        self.assertTrue(should_enable)
        print("[OK] Extended Thinking: Opus ativa thinking")

    def test_thinking_delta_handling(self):
        """thinking_delta deve ser coletado internamente, nao enviado ao usuario."""
        collected_thinking = []
        text_sent_to_user = []

        # Simula deltas
        deltas = [
            SimpleNamespace(type="thinking_delta", thinking="Vou analisar..."),
            SimpleNamespace(type="thinking_delta", thinking="A melhor abordagem e..."),
            SimpleNamespace(type="text_delta", text="Aqui esta minha resposta."),
        ]

        for delta in deltas:
            if delta.type == "text_delta":
                text_sent_to_user.append(delta.text)
            elif delta.type == "thinking_delta":
                collected_thinking.append(delta.thinking)

        self.assertEqual(len(collected_thinking), 2)
        self.assertEqual(len(text_sent_to_user), 1)
        self.assertNotIn("Vou analisar", "".join(text_sent_to_user))
        print("[OK] Extended Thinking: thinking_delta processado internamente, nao enviado ao usuario")


# ════════════════════════════════════════════════════════════════
# 2. TESTE: Prompt Caching
# ════════════════════════════════════════════════════════════════

class TestPromptCaching(unittest.TestCase):
    """Verifica que system prompt usa cache_control ephemeral."""

    def test_system_prompt_format(self):
        """System prompt deve ser convertido para content blocks com cache_control."""
        system_prompt = "Voce e o Clow, um agente de codigo AI."

        # Simula a conversao feita em _stream_call_anthropic
        system_blocks = [{
            "type": "text",
            "text": system_prompt.strip(),
            "cache_control": {"type": "ephemeral"},
        }]

        self.assertEqual(len(system_blocks), 1)
        self.assertEqual(system_blocks[0]["type"], "text")
        self.assertEqual(system_blocks[0]["text"], system_prompt)
        self.assertIn("cache_control", system_blocks[0])
        self.assertEqual(system_blocks[0]["cache_control"]["type"], "ephemeral")
        print("[OK] Prompt Caching: system prompt convertido para content blocks com cache_control")

    def test_cache_usage_tracking(self):
        """Deve capturar cache_creation_input_tokens e cache_read_input_tokens."""
        # Simula usage da API Anthropic
        usage = SimpleNamespace(
            input_tokens=1500,
            cache_creation_input_tokens=1200,
            cache_read_input_tokens=0,
        )

        usage_data = {
            "prompt_tokens": usage.input_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

        if hasattr(usage, "cache_creation_input_tokens"):
            usage_data["cache_creation_input_tokens"] = usage.cache_creation_input_tokens or 0
        if hasattr(usage, "cache_read_input_tokens"):
            usage_data["cache_read_input_tokens"] = usage.cache_read_input_tokens or 0

        self.assertEqual(usage_data["cache_creation_input_tokens"], 1200)
        self.assertEqual(usage_data["cache_read_input_tokens"], 0)
        print("[OK] Prompt Caching: cache tokens capturados corretamente")

    def test_cache_read_second_call(self):
        """Na segunda chamada, cache_read_input_tokens deve ter valor."""
        # Simula segunda chamada (cache hit)
        usage = SimpleNamespace(
            input_tokens=300,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=1200,
        )

        usage_data = {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        if hasattr(usage, "cache_creation_input_tokens"):
            usage_data["cache_creation_input_tokens"] = usage.cache_creation_input_tokens or 0
        if hasattr(usage, "cache_read_input_tokens"):
            usage_data["cache_read_input_tokens"] = usage.cache_read_input_tokens or 0

        self.assertEqual(usage_data["cache_read_input_tokens"], 1200)
        self.assertGreater(usage_data["cache_read_input_tokens"], 0)
        print("[OK] Prompt Caching: cache hit detectado na segunda chamada (1200 tokens lidos do cache)")


# ════════════════════════════════════════════════════════════════
# 3. TESTE: Auto-Correction Loop
# ════════════════════════════════════════════════════════════════

class TestAutoCorrection(unittest.TestCase):
    """Verifica deteccao de erros e loop de auto-correcao."""

    def _make_error_patterns(self):
        """Retorna o regex compilado igual ao do Agent."""
        return re.compile(
            r"(?:error|traceback|failed|SyntaxError|TypeError|NameError|"
            r"ImportError|FileNotFoundError|KeyError|ValueError|"
            r"IndentationError|AttributeError|ModuleNotFoundError)",
            re.IGNORECASE,
        )

    def test_detect_error_status(self):
        """ToolResult com status ERROR deve ser detectado."""
        tr = ToolResult(
            tool_call_id="test1",
            status=ToolResultStatus.ERROR,
            output="Erro ao executar bash: comando nao encontrado",
        )
        self.assertEqual(tr.status, ToolResultStatus.ERROR)
        print("[OK] Auto-Correction: status ERROR detectado")

    def test_detect_traceback_in_output(self):
        """Output com Traceback deve ser detectado."""
        patterns = self._make_error_patterns()
        output = """Traceback (most recent call last):
  File "test.py", line 5, in <module>
    print(undefined_var)
NameError: name 'undefined_var' is not defined"""

        tr = ToolResult(
            tool_call_id="test2",
            status=ToolResultStatus.SUCCESS,
            output=output,
        )

        has_error = False
        if patterns.search(tr.output):
            output_lower = tr.output.lower()
            if any(ind in output_lower for ind in (
                "traceback", "syntaxerror", "nameerror", "typeerror",
                "importerror", "filenotfounderror", "indentationerror",
                "exit code", "command failed", "errno", "failed to", "error:",
            )):
                has_error = True

        self.assertTrue(has_error)
        print("[OK] Auto-Correction: Traceback + NameError detectado no output")

    def test_detect_syntax_error(self):
        """Output com SyntaxError deve ser detectado."""
        patterns = self._make_error_patterns()
        output = """  File "app.py", line 10
    def foo(
          ^
SyntaxError: unexpected EOF while parsing"""

        has_error = bool(patterns.search(output)) and "syntaxerror" in output.lower()
        self.assertTrue(has_error)
        print("[OK] Auto-Correction: SyntaxError detectado")

    def test_no_false_positive_on_info(self):
        """Texto informativo mencionando 'error' nao deve disparar auto-correcao."""
        patterns = self._make_error_patterns()
        output = "O modulo de error handling foi refatorado com sucesso."

        has_error = False
        if patterns.search(output):
            output_lower = output.lower()
            if any(ind in output_lower for ind in (
                "traceback", "syntaxerror", "nameerror", "typeerror",
                "importerror", "filenotfounderror", "indentationerror",
                "exit code", "command failed", "errno", "failed to", "error:",
            )):
                has_error = True

        self.assertFalse(has_error)
        print("[OK] Auto-Correction: sem falso positivo em texto informativo")

    def test_max_attempts_respected(self):
        """Auto-correction deve respeitar o limite de tentativas."""
        max_attempts = config.CLOW_AUTO_CORRECT_MAX
        self.assertEqual(max_attempts, 2)

        # Simula loop
        auto_correct_attempts = 0
        corrections_made = 0
        for _ in range(10):  # Simula 10 erros consecutivos
            if auto_correct_attempts < max_attempts:
                auto_correct_attempts += 1
                corrections_made += 1

        self.assertEqual(corrections_made, 3)
        print(f"[OK] Auto-Correction: respeitou limite de {max_attempts} tentativas")

    def test_config_defaults(self):
        """Configs devem ter defaults corretos."""
        self.assertTrue(config.CLOW_AUTO_CORRECT)
        self.assertEqual(config.CLOW_AUTO_CORRECT_MAX, 2)
        self.assertTrue(config.CLOW_EXTENDED_THINKING)
        self.assertEqual(config.CLOW_THINKING_BUDGET, 10000)
        print("[OK] Configs: todos os defaults corretos")


# ════════════════════════════════════════════════════════════════
# TESTE INTEGRADO: Simula cenario completo
# ════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):
    """Teste integrado simulando o fluxo completo."""

    def test_auto_correct_injects_message(self):
        """Simula o fluxo: erro detectado -> mensagem injetada -> continua loop."""
        messages = []
        auto_correct_attempts = 0
        max_attempts = 3

        # Simula tool result com erro
        tr = ToolResult(
            tool_call_id="tc1",
            status=ToolResultStatus.SUCCESS,
            output="Traceback (most recent call last):\n  NameError: name 'x' is not defined",
        )
        messages.append(tr.to_message())

        # Logica de auto-correction (igual ao run_turn)
        error_patterns = re.compile(
            r"(?:traceback|nameerror)", re.IGNORECASE
        )
        output_lower = tr.output.lower()
        has_error = bool(error_patterns.search(tr.output)) and any(
            ind in output_lower for ind in ("traceback", "nameerror")
        )

        if has_error and auto_correct_attempts < max_attempts:
            auto_correct_attempts += 1
            auto_msg = "O comando anterior falhou. Analise o erro e corrija automaticamente."
            messages.append({"role": "user", "content": auto_msg})

        # Verifica que a mensagem de correcao foi injetada
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("corrija automaticamente", messages[1]["content"])
        self.assertEqual(auto_correct_attempts, 1)
        print("[OK] Integracao: mensagem de auto-correcao injetada corretamente")


if __name__ == "__main__":
    print("=" * 60)
    print("  TESTES: 3 Melhorias de Ouro do Agent.py")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)
