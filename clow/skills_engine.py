"""Clow Skills Engine — gera documentos via Code Execution API beta."""
from __future__ import annotations
import base64
import time
from pathlib import Path
from anthropic import Anthropic

from .generators.base import STATIC_DIR, file_url, slugify

BETA_FLAGS = [
    "code-execution-2025-08-25",
    "files-api-2025-04-14",
]

SKILL_MAP = {
    "xlsx": {"lib": "openpyxl", "label": "Planilha Excel", "ext": ".xlsx"},
    "pptx": {"lib": "python-pptx", "label": "Apresentacao PowerPoint", "ext": ".pptx"},
    "pdf": {"lib": "reportlab", "label": "Documento PDF", "ext": ".pdf"},
    "docx": {"lib": "python-docx", "label": "Documento Word", "ext": ".docx"},
}

CLOW_BRAND = """
Aplique esta identidade visual do Clow:
- Cor primaria: #7C5CFC (roxo vibrante)
- Cor secundaria: #6B4FE0 (roxo escuro)
- Headers: fundo #7C5CFC, texto branco, font-weight bold
- Textos: Satoshi ou IBM Plex Sans (NAO use Arial, Calibri ou fonts genericas)
- Footer: "Gerado por Clow AI"
- Formato monetario: R$ brasileiro
- Datas: DD/MM/YYYY
- Idioma: portugues brasileiro
- Graficos: paleta roxa (#7C5CFC, #6B4FE0, #9B8AFB, #C4B5FD)
"""


def _get_client() -> Anthropic:
    from .config import ANTHROPIC_API_KEY
    return Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_with_skills(
    prompt: str,
    skill_type: str,
    model: str = "claude-haiku-4-5-20251001",
    user_id: str = "",
) -> dict:
    """Gera documento via Code Execution beta. Claude escreve e executa codigo no sandbox."""
    client = _get_client()
    skill_info = SKILL_MAP.get(skill_type)
    if not skill_info:
        raise ValueError(f"Skill '{skill_type}' nao reconhecida")

    ext = skill_info["ext"]
    lib = skill_info["lib"]

    system_prompt = f"""Voce e um especialista em gerar arquivos {ext} profissionais usando Python.
Instrucoes:
1. Escreva um script Python completo usando {lib}
2. O arquivo DEVE ser salvo em /tmp/output/result{ext}
3. No final, leia o arquivo e imprima o base64 entre tags: <FILE_B64>...conteudo base64...</FILE_B64>
4. Use: import base64; data = open('/tmp/output/result{ext}', 'rb').read(); print(f'<FILE_B64>{{base64.b64encode(data).decode()}}</FILE_B64>')
5. Gere conteudo profissional, detalhado, com dados de exemplo realistas
{CLOW_BRAND}
IMPORTANTE: Sempre termine com o print do base64 entre as tags FILE_B64."""

    full_prompt = f"Crie o seguinte arquivo {ext}: {prompt}"

    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=BETA_FLAGS,
        system=system_prompt,
        tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
        messages=[{"role": "user", "content": full_prompt}],
    )

    # Log usage
    if user_id and response.usage:
        try:
            from .database import log_usage
            inp = response.usage.input_tokens
            out = response.usage.output_tokens
            cost = (inp * 0.25 + out * 1.25) / 1_000_000 if "haiku" in model else (inp * 3.0 + out * 15.0) / 1_000_000
            log_usage(user_id, model, inp, out, cost, f"skills_{skill_type}")
        except Exception:
            pass

    # Extrair base64 do output
    b64_data = _extract_b64(response)
    text_parts = _extract_text(response)

    if b64_data:
        return _save_file(b64_data, skill_type, prompt)

    # Se nao extraiu base64, tenta fallback
    raise RuntimeError(f"Code execution nao retornou arquivo. Texto: {' '.join(text_parts)[:200]}")


def _extract_b64(response) -> str | None:
    """Extrai base64 do output do code execution."""
    for block in response.content:
        # Check bash results
        if hasattr(block, "content"):
            content = block.content
            if isinstance(content, dict):
                stdout = content.get("stdout", "")
                if "<FILE_B64>" in stdout:
                    start = stdout.index("<FILE_B64>") + 10
                    end = stdout.index("</FILE_B64>")
                    return stdout[start:end].strip()
            elif isinstance(content, list):
                for sub in content:
                    if hasattr(sub, "type"):
                        sub_dict = sub.model_dump() if hasattr(sub, "model_dump") else {}
                        stdout = sub_dict.get("stdout", "")
                        if isinstance(stdout, str) and "<FILE_B64>" in stdout:
                            start = stdout.index("<FILE_B64>") + 10
                            end = stdout.index("</FILE_B64>")
                            return stdout[start:end].strip()
            elif hasattr(content, "stdout"):
                stdout = content.stdout or ""
                if "<FILE_B64>" in stdout:
                    start = stdout.index("<FILE_B64>") + 10
                    end = stdout.index("</FILE_B64>")
                    return stdout[start:end].strip()

        # Direct text blocks sometimes contain it
        if hasattr(block, "text") and "<FILE_B64>" in (block.text or ""):
            text = block.text
            start = text.index("<FILE_B64>") + 10
            end = text.index("</FILE_B64>")
            return text[start:end].strip()

    return None


def _extract_text(response) -> list[str]:
    parts = []
    for block in response.content:
        if hasattr(block, "text") and block.text:
            parts.append(block.text)
    return parts


def _save_file(b64_data: str, skill_type: str, prompt: str) -> dict:
    """Decodifica base64 e salva arquivo."""
    skill_info = SKILL_MAP[skill_type]
    ext = skill_info["ext"]

    out_dir = STATIC_DIR / "files"
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(prompt[:40])
    ts = int(time.time())
    filename = f"{slug}-{ts}{ext}"
    filepath = out_dir / filename

    data = base64.b64decode(b64_data)
    filepath.write_bytes(data)

    url = file_url(f"static/files/{filename}")
    size = len(data)
    size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.1f} MB"

    return {
        "type": skill_type,
        "name": filename,
        "url": url,
        "size": size_str,
        "method": "skills_api",
    }
