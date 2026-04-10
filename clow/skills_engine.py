"""Clow Skills Engine — gera documentos via DeepSeek."""
from __future__ import annotations
import base64
import time
from pathlib import Path
from openai import OpenAI

from .generators.base import STATIC_DIR, file_url, slugify

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


def _get_client() -> OpenAI:
    from .config import get_deepseek_client_kwargs
    return OpenAI(**get_deepseek_client_kwargs())


def generate_with_skills(
    prompt: str,
    skill_type: str,
    model: str = "",
    user_id: str = "",
) -> dict:
    """Gera documento via DeepSeek. Pede script Python que gera o arquivo e retorna base64."""
    from . import config
    client = _get_client()
    model = model or config.CLOW_MODEL
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
Retorne APENAS o script Python completo, sem explicacao."""

    full_prompt = f"Crie o seguinte arquivo {ext}: {prompt}"

    response = client.chat.completions.create(
        model=model,
        max_tokens=16000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt},
        ],
    )

    # Log usage
    if user_id and response.usage:
        try:
            from .database import log_usage
            inp = response.usage.prompt_tokens or 0
            out = response.usage.completion_tokens or 0
            cost = (inp * config.DEEPSEEK_INPUT_PRICE_PER_MTOK + out * config.DEEPSEEK_OUTPUT_PRICE_PER_MTOK) / 1_000_000
            log_usage(user_id, model, inp, out, cost, f"skills_{skill_type}")
        except Exception:
            pass

    # Executa script Python retornado pelo modelo
    script = response.choices[0].message.content or ""
    if script.startswith("```"):
        script = script.split("```")[1]
        if script.startswith("python"):
            script = script[6:]
        script = script.rsplit("```", 1)[0]

    import subprocess, os
    os.makedirs("/tmp/output", exist_ok=True)
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True, text=True, timeout=60,
    )

    b64_data = None
    output = result.stdout
    if "<FILE_B64>" in output:
        start = output.index("<FILE_B64>") + 10
        end = output.index("</FILE_B64>")
        b64_data = output[start:end].strip()

    if b64_data:
        return _save_file(b64_data, skill_type, prompt)

    raise RuntimeError(f"Script nao retornou arquivo. stdout={output[:200]} stderr={result.stderr[:200]}")


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
