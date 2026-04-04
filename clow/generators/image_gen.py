"""Gerador de imagens via Pollinations.ai (free, sem API key)."""

import urllib.parse
import requests
import os
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_image(prompt: str, width: int = 1024, height: int = 1024, timeout: int = 120) -> tuple[str | None, str | None]:
    """
    Gera imagem via Pollinations.ai usando Flux model.
    
    Args:
        prompt: Descrição da imagem em inglês
        width: Largura em pixels (padrão 1024)
        height: Altura em pixels (padrão 1024)
        timeout: Timeout em segundos (padrão 120)
    
    Returns:
        Tupla (filepath, filename) ou (None, None) em caso de erro
    """
    try:
        # URL-encode o prompt
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&model=flux&nologo=true"
        
        logger.info(f"Gerando imagem: {prompt[:50]}...")
        
        response = requests.get(url, timeout=timeout)
        
        if response.status_code == 200:
            # Cria diretório se não existir
            file_dir = str(Path(__file__).parent.parent.parent / "static" / "files")
            os.makedirs(file_dir, exist_ok=True)
            
            # Salva arquivo com timestamp
            filename = f"{int(time.time() * 1000)}_generated.png"
            filepath = os.path.join(file_dir, filename)
            
            with open(filepath, "wb") as f:
                f.write(response.content)
            
            logger.info(f"Imagem salva em {filepath}")
            return filepath, filename
        else:
            logger.error(f"Pollinations retornou {response.status_code}")
            return None, None
            
    except requests.Timeout:
        logger.error(f"Timeout ao gerar imagem (>{timeout}s)")
        return None, None
    except Exception as e:
        logger.error(f"Erro ao gerar imagem: {e}")
        return None, None


def optimize_prompt_for_image(user_prompt: str, llm_client) -> str:
    """
    Otimiza prompt do usuário em português para prompt de image em inglês.
    Usa Claude API para gerar um prompt detalhado e visual.
    
    Args:
        user_prompt: Pedido do usuário em português
        llm_client: Cliente da API (Claude)
    
    Returns:
        Prompt otimizado em inglês para Pollinations
    """
    try:
        system = """Você é um expert em prompts para geração de imagens. 
Seu trabalho é transformar pedidos em português em prompts detalhados e visuais em inglês para Flux/DALL-E.

Regras:
- Seja descritivo e específico
- Inclua estilo visual, cores, iluminação, composição
- Use termos profissionais (photography, illustration, 3D render, digital art, etc)
- Máximo 150 caracteres
- Sempre retorne APENAS o prompt, sem explicações

Exemplo:
Input: "Cria um criativo pra anúncio de seguro de vida"
Output: "Professional life insurance advertisement with happy family protected by golden shield, modern clean design, blue and white corporate colors, studio lighting, premium quality"
"""
        
        response = llm_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[
                {"role": "user", "content": f"Transforme este pedido em um prompt de imagem em inglês:\n\n{user_prompt}"}
            ],
            system=system
        )
        
        optimized = response.content[0].text.strip()
        logger.info(f"Prompt otimizado: {optimized}")
        return optimized
        
    except Exception as e:
        logger.error(f"Erro ao otimizar prompt: {e}")
        # Fallback: retorna prompt original com alguns ajustes
        return user_prompt.replace("cria", "create").replace("gera", "generate").replace("desenha", "design")
