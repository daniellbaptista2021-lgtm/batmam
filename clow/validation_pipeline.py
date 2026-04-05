"""Validation Pipeline — validacao multi-camada de componentes Clow.

Valida skills, tools, hooks e configs com 3 validadores + orquestrador:
  - StructuralValidator: YAML frontmatter, campos obrigatorios, tamanho
  - SemanticValidator: prompt injection, secrets, padroes perigosos
  - ReferenceValidator: URLs seguras, file references existem

Inspirado no pipeline de 5 camadas do claude-code-templates (MIT License).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationIssue:
    level: str  # "error", "warning", "info"
    code: str
    message: str
    line: int = 0
    file: str = ""


@dataclass
class ValidationResult:
    validator: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    @property
    def score(self) -> int:
        """Score de 0 a 100."""
        if not self.issues:
            return 100
        deductions = sum(
            30 if i.level == "error" else 10 if i.level == "warning" else 0
            for i in self.issues
        )
        return max(0, 100 - deductions)


# ══════════════════════════════════════════════════════════════
# STRUCTURAL VALIDATOR
# ══════════════════════════════════════════════════════════════

class StructuralValidator:
    """Valida estrutura: frontmatter YAML, campos obrigatorios, tamanho."""

    name = "structural"

    def validate(self, content: str, file_path: str = "") -> ValidationResult:
        result = ValidationResult(validator=self.name)

        if not content.strip():
            result.issues.append(ValidationIssue("error", "S001", "Arquivo vazio", file=file_path))
            return result

        # Check file size
        if len(content) > 100_000:
            result.issues.append(ValidationIssue("error", "S002",
                                                 f"Arquivo muito grande: {len(content)} bytes (max 100KB)", file=file_path))

        # Check UTF-8 encoding
        try:
            content.encode("utf-8")
        except UnicodeEncodeError:
            result.issues.append(ValidationIssue("error", "S003", "Encoding invalido (requer UTF-8)", file=file_path))

        # Check YAML frontmatter for markdown files
        if file_path.endswith(".md"):
            if content.startswith("---"):
                end = content.find("---", 3)
                if end == -1:
                    result.issues.append(ValidationIssue("error", "S010", "Frontmatter nao fechado", file=file_path))
                else:
                    frontmatter = content[3:end].strip()
                    self._validate_frontmatter(frontmatter, result, file_path)
            else:
                result.issues.append(ValidationIssue("warning", "S011", "Sem YAML frontmatter", file=file_path))

        # Check for suspicious content
        if "\t" in content and "    " in content:
            result.issues.append(ValidationIssue("warning", "S020",
                                                 "Mistura tabs e espacos", file=file_path))

        # Line length check
        for i, line in enumerate(content.splitlines(), 1):
            if len(line) > 500:
                result.issues.append(ValidationIssue("warning", "S021",
                                                     f"Linha muito longa: {len(line)} chars", line=i, file=file_path))
                break  # Report only first

        return result

    def _validate_frontmatter(self, fm: str, result: ValidationResult, file_path: str) -> None:
        lines = fm.splitlines()
        fields: dict[str, str] = {}
        for line in lines:
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip()] = val.strip()

        # Check for description
        if "description" not in fields and "desc" not in fields:
            result.issues.append(ValidationIssue("warning", "S012",
                                                 "Frontmatter sem campo 'description'", file=file_path))

        # Check description length
        desc = fields.get("description", fields.get("desc", ""))
        if desc and len(desc) < 10:
            result.issues.append(ValidationIssue("warning", "S013",
                                                 f"Description muito curta: {len(desc)} chars (min 10)", file=file_path))


# ══════════════════════════════════════════════════════════════
# SEMANTIC VALIDATOR
# ══════════════════════════════════════════════════════════════

# Patterns that indicate prompt injection or dangerous content
_DANGEROUS_PATTERNS = [
    (r'(?i)ignore\s+(all\s+)?previous\s+instructions', 'Prompt injection: ignore previous instructions'),
    (r'(?i)you\s+are\s+now\s+(a\s+)?different', 'Prompt injection: role override'),
    (r'(?i)system\s*:\s*you\s+are', 'Prompt injection: fake system message'),
    (r'(?i)jailbreak|DAN\s+mode|ignore\s+rules', 'Prompt injection: jailbreak attempt'),
    (r'(?i)pretend\s+you\s+(are|have)\s+no\s+restrictions', 'Prompt injection: restriction bypass'),
    (r'(?i)(steal|exfiltrate|harvest)\s+(credentials?|tokens?|keys?|passwords?)', 'Credential harvesting'),
    (r'(?i)curl\s+.*\|\s*(bash|sh)', 'Remote code execution: pipe to shell'),
    (r'(?i)eval\s*\(.*\bfetch\b', 'Remote code execution: eval with fetch'),
    (r'(?i)base64\s*-d\s*.*\|\s*(bash|sh|python)', 'Obfuscated code execution'),
    (r'(?i)reverse\s+shell|bind\s+shell|nc\s+-e', 'Reverse/bind shell attempt'),
]

_SUSPICIOUS_PATTERNS = [
    (r'(?i)exec\s*\(', 'Dynamic code execution (exec)'),
    (r'(?i)__import__\s*\(', 'Dynamic import'),
    (r'(?i)subprocess\.call\s*\(.*shell\s*=\s*True', 'Shell injection risk'),
    (r'(?i)os\.system\s*\(', 'OS command execution'),
]

# Secret patterns (subset — for quick validation, not full scanner)
_EMBEDDED_SECRETS = [
    (r'sk-ant-api\d{2}-[A-Za-z0-9\-_]{20,}', 'Embedded Anthropic API key'),
    (r'sk_live_[0-9a-zA-Z]{24,}', 'Embedded Stripe live key'),
    (r'ghp_[0-9a-zA-Z]{36}', 'Embedded GitHub token'),
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', 'Embedded private key'),
    (r'(?i)password\s*=\s*["\'][^"\']{8,}["\']', 'Hardcoded password'),
]


class SemanticValidator:
    """Detecta prompt injection, secrets hardcoded, padroes perigosos."""

    name = "semantic"

    def validate(self, content: str, file_path: str = "") -> ValidationResult:
        result = ValidationResult(validator=self.name)

        for i, line in enumerate(content.splitlines(), 1):
            # Dangerous patterns (errors)
            for pattern, desc in _DANGEROUS_PATTERNS:
                if re.search(pattern, line):
                    result.issues.append(ValidationIssue("error", "M001", desc, line=i, file=file_path))

            # Suspicious patterns (warnings)
            for pattern, desc in _SUSPICIOUS_PATTERNS:
                if re.search(pattern, line):
                    result.issues.append(ValidationIssue("warning", "M002", desc, line=i, file=file_path))

            # Embedded secrets (errors)
            for pattern, desc in _EMBEDDED_SECRETS:
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                if re.search(pattern, line):
                    result.issues.append(ValidationIssue("error", "M003", desc, line=i, file=file_path))

        # Check for HTML/script injection
        if re.search(r'<script\b', content, re.IGNORECASE):
            result.issues.append(ValidationIssue("warning", "M010", "Contem tag <script>", file=file_path))
        if re.search(r'on(click|load|error|mouseover)\s*=', content, re.IGNORECASE):
            result.issues.append(ValidationIssue("warning", "M011", "Contem event handler HTML", file=file_path))

        return result


# ══════════════════════════════════════════════════════════════
# REFERENCE VALIDATOR
# ══════════════════════════════════════════════════════════════

_UNSAFE_PROTOCOLS = {"file://", "javascript:", "data:", "vbscript:"}
_PRIVATE_IP_PATTERNS = [
    r'https?://10\.\d+\.\d+\.\d+',
    r'https?://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+',
    r'https?://192\.168\.\d+\.\d+',
    r'https?://127\.\d+\.\d+\.\d+',
    r'https?://localhost',
]


class ReferenceValidator:
    """Valida URLs seguras e file references existem."""

    name = "reference"

    def validate(self, content: str, file_path: str = "", base_dir: str = "") -> ValidationResult:
        result = ValidationResult(validator=self.name)

        # Extract URLs
        urls = re.findall(r'https?://[^\s\'"<>\)]+', content)
        file_refs = re.findall(r'(?:src|href|path|file)\s*[=:]\s*["\']([^"\']+)["\']', content)

        # Check URLs
        for url in urls:
            # Unsafe protocols
            for proto in _UNSAFE_PROTOCOLS:
                if url.lower().startswith(proto):
                    result.issues.append(ValidationIssue("error", "R001",
                                                         f"Protocolo inseguro: {proto}", file=file_path))

            # Private IPs
            for pattern in _PRIVATE_IP_PATTERNS:
                if re.match(pattern, url):
                    result.issues.append(ValidationIssue("warning", "R002",
                                                         f"URL com IP privado: {url[:60]}", file=file_path))
                    break

            # HTTP (not HTTPS) for external URLs
            if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
                result.issues.append(ValidationIssue("warning", "R003",
                                                     f"URL sem HTTPS: {url[:60]}", file=file_path))

        # Check file references
        if base_dir:
            base = Path(base_dir)
            for ref in file_refs:
                if ref.startswith(("http://", "https://", "#", "data:", "/")):
                    continue
                ref_path = base / ref
                if not ref_path.exists():
                    result.issues.append(ValidationIssue("warning", "R010",
                                                         f"Arquivo referenciado nao existe: {ref}", file=file_path))

        return result


# ══════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

class ValidationOrchestrator:
    """Coordena todos os validadores e gera resultado agregado."""

    def __init__(self) -> None:
        self.validators = [
            StructuralValidator(),
            SemanticValidator(),
            ReferenceValidator(),
        ]

    def validate(self, content: str, file_path: str = "", base_dir: str = "") -> dict:
        """Valida conteudo com todos os validadores.

        Returns dict com:
            results: lista de ValidationResult
            score: 0-100 (media dos scores)
            is_valid: bool (sem erros)
            summary: str
        """
        results = []
        for v in self.validators:
            if isinstance(v, ReferenceValidator):
                r = v.validate(content, file_path, base_dir)
            else:
                r = v.validate(content, file_path)
            results.append(r)

        total_errors = sum(r.error_count for r in results)
        total_warnings = sum(r.warning_count for r in results)
        avg_score = sum(r.score for r in results) // len(results) if results else 100
        is_valid = total_errors == 0

        badge = "🟢" if avg_score >= 90 else "🟡" if avg_score >= 70 else "🟠" if avg_score >= 50 else "🔴"

        summary = f"{badge} Score: {avg_score}/100 — {total_errors} erro(s), {total_warnings} aviso(s)"

        return {
            "results": [
                {
                    "validator": r.validator,
                    "is_valid": r.is_valid,
                    "score": r.score,
                    "errors": r.error_count,
                    "warnings": r.warning_count,
                    "issues": [
                        {"level": i.level, "code": i.code, "message": i.message,
                         "line": i.line, "file": i.file}
                        for i in r.issues
                    ],
                }
                for r in results
            ],
            "score": avg_score,
            "is_valid": is_valid,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "summary": summary,
        }

    def validate_file(self, file_path: str) -> dict:
        """Valida um arquivo do disco."""
        p = Path(file_path)
        if not p.exists():
            return {"score": 0, "is_valid": False, "summary": f"Arquivo nao encontrado: {file_path}",
                    "results": [], "total_errors": 1, "total_warnings": 0}
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            return {"score": 0, "is_valid": False, "summary": f"Erro ao ler: {e}",
                    "results": [], "total_errors": 1, "total_warnings": 0}
        return self.validate(content, file_path, str(p.parent))

    def validate_directory(self, dir_path: str, pattern: str = "**/*.md") -> dict:
        """Valida todos os arquivos matching pattern em um diretorio."""
        d = Path(dir_path)
        if not d.is_dir():
            return {"files": [], "total_score": 0, "total_errors": 0}

        file_results = []
        for f in d.glob(pattern):
            r = self.validate_file(str(f))
            file_results.append({"file": str(f), **r})

        total_score = sum(r["score"] for r in file_results) // len(file_results) if file_results else 100
        total_errors = sum(r["total_errors"] for r in file_results)
        total_warnings = sum(r["total_warnings"] for r in file_results)

        return {
            "files": file_results,
            "total_score": total_score,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "file_count": len(file_results),
            "summary": f"Validados {len(file_results)} arquivos — Score medio: {total_score}/100",
        }
