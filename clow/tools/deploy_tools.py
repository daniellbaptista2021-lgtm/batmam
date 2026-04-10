"""Deploy Tools — Vercel (API REST) e VPS (Nginx/Docker/PM2)."""

from __future__ import annotations
import subprocess
import os
import json
import time
import logging
import hashlib
from pathlib import Path
from typing import Any
from .base import BaseTool

logger = logging.getLogger(__name__)

VERCEL_API = "https://api.vercel.com"


def _get_vercel_token(user_id: str = "") -> str:
    """Busca token Vercel: env var > credential_manager > default."""
    token = os.getenv("VERCEL_TOKEN", "")
    if token:
        return token
    if user_id:
        try:
            from ..credentials.credential_manager import load_credential
            creds = load_credential(user_id, "vercel")
            if creds:
                return creds.get("token", "")
        except Exception:
            pass
    return os.getenv("VERCEL_DEFAULT_TOKEN", "")


def _vercel_request(method: str, path: str, token: str,
                    data: dict | None = None, timeout: int = 30) -> dict:
    """Faz request para Vercel API."""
    import urllib.request
    import urllib.error

    url = f"{VERCEL_API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode()[:500]
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        return {"error": str(e)}


class DeployVercelTool(BaseTool):
    name = "deploy_vercel"
    description = (
        "Gerencia projetos e deploys no Vercel via API. "
        "Acoes: login, whoami, list_projects, create_project, deploy, "
        "list_deployments, rollback, add_domain, list_domains, "
        "set_env, list_env, remove_env, get_project, delete_project."
    )
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "login", "whoami",
                        "list_projects", "create_project", "get_project", "delete_project",
                        "deploy", "list_deployments", "rollback",
                        "add_domain", "list_domains", "remove_domain",
                        "set_env", "list_env", "remove_env",
                    ],
                    "description": "Acao Vercel",
                },
                "token": {"type": "string", "description": "Token Vercel (para login)"},
                "user_id": {"type": "string", "description": "ID do usuario (para credenciais)"},
                "project_name": {"type": "string", "description": "Nome do projeto"},
                "project_dir": {"type": "string", "description": "Diretorio local do projeto (para deploy)"},
                "framework": {
                    "type": "string",
                    "enum": ["nextjs", "vite", "create-react-app", "static", "nuxtjs", "svelte", "gatsby", "other"],
                    "description": "Framework do projeto (para create_project/deploy)",
                },
                "domain": {"type": "string", "description": "Dominio customizado (ex: app.example.com)"},
                "deployment_id": {"type": "string", "description": "ID do deployment (para rollback)"},
                "env_key": {"type": "string", "description": "Nome da variavel de ambiente"},
                "env_value": {"type": "string", "description": "Valor da variavel"},
                "env_target": {
                    "type": "string",
                    "enum": ["production", "preview", "development"],
                    "description": "Ambiente da variavel (padrao: production)",
                },
                "prod": {"type": "boolean", "description": "Deploy em producao (padrao: true)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        user_id = kwargs.get("user_id", "system")

        # ── Login / Auth ──
        if action == "login":
            token = kwargs.get("token", "")
            if not token:
                return (
                    "Para autenticar no Vercel:\n"
                    "1. Acesse vercel.com/account/tokens\n"
                    "2. Crie um token com escopo Full Access\n"
                    "3. Cole o token aqui usando: deploy_vercel(action='login', token='seu_token')"
                )
            # Valida token
            result = _vercel_request("GET", "/v2/user", token)
            if "error" in result:
                return f"Token invalido: {result['error']}"
            # Salva credencial
            try:
                from ..credentials.credential_manager import save_credential
                save_credential(user_id, "vercel", {"token": token})
            except Exception:
                pass
            user_data = result.get("user", {})
            return f"Autenticado como: {user_data.get('name', '')} ({user_data.get('email', '')})"

        # Token obrigatorio para demais acoes
        token = _get_vercel_token(user_id)
        if not token:
            return (
                "Token Vercel nao configurado.\n"
                "Use: deploy_vercel(action='login', token='seu_token')\n"
                "Gere em: vercel.com/account/tokens"
            )

        if action == "whoami":
            result = _vercel_request("GET", "/v2/user", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            u = result.get("user", {})
            return f"Conta: {u.get('name', '')} | Email: {u.get('email', '')} | ID: {u.get('id', '')}"

        # ── Projetos ──
        elif action == "list_projects":
            result = _vercel_request("GET", "/v9/projects?limit=20", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            projects = result.get("projects", [])
            if not projects:
                return "Nenhum projeto encontrado."
            lines = []
            for p in projects:
                framework = p.get("framework", "static")
                lines.append(f"  {p['name']} ({framework}) — ID: {p['id']}")
            return f"Projetos Vercel ({len(projects)}):\n" + "\n".join(lines)

        elif action == "create_project":
            name = kwargs.get("project_name", "")
            framework = kwargs.get("framework", "static")
            if not name:
                return "Erro: project_name obrigatorio."
            result = _vercel_request("POST", "/v10/projects", token, {
                "name": name,
                "framework": framework if framework != "other" else None,
            })
            if "error" in result:
                return f"Erro: {result['error']}"
            return f"Projeto criado: {result.get('name', name)} | ID: {result.get('id', '')}"

        elif action == "get_project":
            name = kwargs.get("project_name", "")
            if not name:
                return "Erro: project_name obrigatorio."
            result = _vercel_request("GET", f"/v9/projects/{name}", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            p = result
            domains = [a.get("domain", "") for a in p.get("alias", [])]
            return (
                f"Projeto: {p.get('name', '')}\n"
                f"Framework: {p.get('framework', 'N/A')}\n"
                f"ID: {p.get('id', '')}\n"
                f"Dominios: {', '.join(domains) or 'nenhum'}"
            )

        elif action == "delete_project":
            name = kwargs.get("project_name", "")
            if not name:
                return "Erro: project_name obrigatorio."
            result = _vercel_request("DELETE", f"/v9/projects/{name}", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            return f"Projeto '{name}' deletado."

        # ── Deploy ──
        elif action == "deploy":
            return self._deploy(kwargs, token)

        elif action == "list_deployments":
            name = kwargs.get("project_name", "")
            path = "/v6/deployments?limit=10"
            if name:
                # Busca project id primeiro
                proj = _vercel_request("GET", f"/v9/projects/{name}", token)
                if not proj.get("error"):
                    path += f"&projectId={proj['id']}"
            result = _vercel_request("GET", path, token)
            if "error" in result:
                return f"Erro: {result['error']}"
            deps = result.get("deployments", [])
            if not deps:
                return "Nenhum deployment encontrado."
            lines = []
            for d in deps:
                st = {"READY": "OK", "ERROR": "ERRO", "BUILDING": "BUILD"}.get(d.get("readyState", ""), "?")
                url = d.get("url", "")
                created = time.strftime("%d/%m %H:%M", time.localtime(d.get("createdAt", 0) / 1000))
                lines.append(f"  [{st}] {d.get('name','')} — {url} ({created}) ID:{d.get('uid','')[:8]}")
            return f"Deployments ({len(deps)}):\n" + "\n".join(lines)

        elif action == "rollback":
            dep_id = kwargs.get("deployment_id", "")
            name = kwargs.get("project_name", "")
            if not dep_id:
                return "Erro: deployment_id obrigatorio. Use list_deployments para ver IDs."
            result = _vercel_request("PATCH", f"/v13/deployments/{dep_id}/rollback", token, {
                "name": name,
            })
            if "error" in result:
                return f"Erro: {result['error']}"
            return f"Rollback iniciado para deployment {dep_id}."

        # ── Dominios ──
        elif action == "add_domain":
            name = kwargs.get("project_name", "")
            domain = kwargs.get("domain", "")
            if not name or not domain:
                return "Erro: project_name e domain obrigatorios."
            result = _vercel_request("POST", f"/v10/projects/{name}/domains", token, {
                "name": domain,
            })
            if "error" in result:
                return f"Erro: {result['error']}"
            return (
                f"Dominio '{domain}' adicionado ao projeto '{name}'.\n"
                f"Configure o DNS: CNAME {domain} → cname.vercel-dns.com"
            )

        elif action == "list_domains":
            name = kwargs.get("project_name", "")
            if not name:
                return "Erro: project_name obrigatorio."
            result = _vercel_request("GET", f"/v9/projects/{name}/domains", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            domains = result.get("domains", [])
            if not domains:
                return "Nenhum dominio configurado."
            lines = [f"  {d.get('name', '')} — verificado: {'sim' if d.get('verified') else 'nao'}" for d in domains]
            return f"Dominios do projeto '{name}':\n" + "\n".join(lines)

        elif action == "remove_domain":
            name = kwargs.get("project_name", "")
            domain = kwargs.get("domain", "")
            if not name or not domain:
                return "Erro: project_name e domain obrigatorios."
            result = _vercel_request("DELETE", f"/v9/projects/{name}/domains/{domain}", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            return f"Dominio '{domain}' removido."

        # ── Variaveis de Ambiente ──
        elif action == "set_env":
            name = kwargs.get("project_name", "")
            key = kwargs.get("env_key", "")
            value = kwargs.get("env_value", "")
            target = kwargs.get("env_target", "production")
            if not name or not key or not value:
                return "Erro: project_name, env_key e env_value obrigatorios."
            result = _vercel_request("POST", f"/v10/projects/{name}/env", token, {
                "key": key,
                "value": value,
                "target": [target],
                "type": "encrypted",
            })
            if "error" in result:
                return f"Erro: {result['error']}"
            return f"Variavel '{key}' definida para {target} no projeto '{name}'."

        elif action == "list_env":
            name = kwargs.get("project_name", "")
            if not name:
                return "Erro: project_name obrigatorio."
            result = _vercel_request("GET", f"/v9/projects/{name}/env", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            envs = result.get("envs", [])
            if not envs:
                return "Nenhuma variavel de ambiente."
            lines = [f"  {e.get('key', '')} ({', '.join(e.get('target', []))}) — ID: {e.get('id', '')[:8]}" for e in envs]
            return f"Variaveis ({len(envs)}):\n" + "\n".join(lines)

        elif action == "remove_env":
            name = kwargs.get("project_name", "")
            key = kwargs.get("env_key", "")
            if not name or not key:
                return "Erro: project_name e env_key obrigatorios."
            # Busca ID da variavel
            envs_result = _vercel_request("GET", f"/v9/projects/{name}/env", token)
            envs = envs_result.get("envs", [])
            env_id = None
            for e in envs:
                if e.get("key") == key:
                    env_id = e.get("id")
                    break
            if not env_id:
                return f"Variavel '{key}' nao encontrada."
            result = _vercel_request("DELETE", f"/v9/projects/{name}/env/{env_id}", token)
            if "error" in result:
                return f"Erro: {result['error']}"
            return f"Variavel '{key}' removida."

        return f"Acao '{action}' nao reconhecida."

    def _deploy(self, kwargs: dict, token: str) -> str:
        """Deploy de pasta local via Vercel API (file upload)."""
        project_dir = kwargs.get("project_dir", ".")
        project_name = kwargs.get("project_name", "")
        framework = kwargs.get("framework", "static")
        prod = kwargs.get("prod", True)

        if not os.path.isdir(project_dir):
            return f"Erro: diretorio '{project_dir}' nao existe."

        # 1. Coleta arquivos para upload
        files = []
        base = Path(project_dir).resolve()
        skip_dirs = {".git", "node_modules", ".next", "__pycache__", ".venv", "venv", ".vercel"}

        for root, dirs, filenames in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in filenames:
                fpath = Path(root) / fname
                rel = str(fpath.relative_to(base))
                try:
                    content = fpath.read_bytes()
                    if len(content) > 10_000_000:  # Skip >10MB
                        continue
                    sha = hashlib.sha1(content).hexdigest()
                    files.append({
                        "file": rel,
                        "sha": sha,
                        "size": len(content),
                        "data": content,
                    })
                except Exception:
                    continue

        if not files:
            return "Erro: nenhum arquivo encontrado para deploy."

        # 2. Upload arquivos para Vercel
        import urllib.request
        import urllib.error

        for f in files:
            try:
                req = urllib.request.Request(
                    f"{VERCEL_API}/v2/files",
                    data=f["data"],
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/octet-stream",
                        "x-vercel-digest": f["sha"],
                    },
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=30)
            except urllib.error.HTTPError as e:
                if e.code != 409:  # 409 = already exists, OK
                    return f"Erro upload {f['file']}: HTTP {e.code}"
            except Exception as e:
                return f"Erro upload {f['file']}: {e}"

        # 3. Cria deployment
        file_entries = [{"file": f["file"], "sha": f["sha"], "size": f["size"]} for f in files]

        deploy_data = {
            "name": project_name or base.name,
            "files": file_entries,
            "projectSettings": {
                "framework": framework if framework != "other" else None,
            },
        }
        if prod:
            deploy_data["target"] = "production"

        result = _vercel_request("POST", "/v13/deployments", token, deploy_data)
        if "error" in result:
            return f"Erro ao criar deployment: {result['error']}"

        deploy_url = result.get("url", "")
        deploy_id = result.get("id", "")
        ready_state = result.get("readyState", "BUILDING")
        alias = result.get("alias", [])
        prod_url = alias[0] if alias else deploy_url

        # 4. Aguarda build (poll por ate 120s)
        if ready_state != "READY":
            for _ in range(24):
                time.sleep(5)
                status = _vercel_request("GET", f"/v13/deployments/{deploy_id}", token)
                ready_state = status.get("readyState", "")
                if ready_state == "READY":
                    alias = status.get("alias", [])
                    prod_url = alias[0] if alias else status.get("url", deploy_url)
                    break
                elif ready_state == "ERROR":
                    return f"Build falhou. ID: {deploy_id}\nVerifique logs com: deploy_vercel(action='list_deployments')"

        total_size = sum(f["size"] for f in files)
        size_str = f"{total_size / 1024:.0f}KB" if total_size < 1_000_000 else f"{total_size / 1_000_000:.1f}MB"

        return (
            f"Deploy concluido!\n"
            f"  URL: https://{prod_url}\n"
            f"  Projeto: {deploy_data['name']}\n"
            f"  Arquivos: {len(files)} ({size_str})\n"
            f"  Status: {ready_state}\n"
            f"  ID: {deploy_id}"
        )


class DeployVpsTool(BaseTool):
    name = "deploy_vps"
    description = "Deploy na VPS. Git pull + build + restart via PM2, Docker Compose ou systemd."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["git_deploy", "docker_deploy", "pm2_deploy", "status"],
                    "description": "Tipo de deploy",
                },
                "project_dir": {"type": "string", "description": "Diretorio do projeto na VPS"},
                "branch": {"type": "string", "description": "Branch git (padrao: main)"},
                "service_name": {"type": "string", "description": "Nome do servico PM2 ou container"},
                "compose_file": {"type": "string", "description": "Caminho do docker-compose.yml"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        cwd = kwargs.get("project_dir", ".")
        branch = kwargs.get("branch", "main")
        service = kwargs.get("service_name", "app")
        compose = kwargs.get("compose_file", "docker-compose.yml")

        if action == "git_deploy":
            cmds = [
                f"cd {cwd}",
                f"git fetch origin && git reset --hard origin/{branch}",
                "npm install --production 2>/dev/null || pip install -r requirements.txt 2>/dev/null || true",
                f"pm2 restart {service} 2>/dev/null || systemctl restart {service} 2>/dev/null || echo 'Reinicie manualmente'",
            ]
            return self._run(" && ".join(cmds))

        elif action == "docker_deploy":
            cmds = [
                f"cd {cwd}",
                f"git pull origin {branch} 2>/dev/null || true",
                f"docker compose -f {compose} pull 2>/dev/null || docker-compose -f {compose} pull",
                f"docker compose -f {compose} up -d --build 2>/dev/null || docker-compose -f {compose} up -d --build",
            ]
            return self._run(" && ".join(cmds))

        elif action == "pm2_deploy":
            cmds = [
                f"cd {cwd}",
                f"git pull origin {branch}",
                "npm install --production 2>/dev/null || true",
                f"pm2 restart {service} || pm2 start ecosystem.config.js 2>/dev/null || pm2 start index.js --name {service}",
                "pm2 save",
            ]
            return self._run(" && ".join(cmds))

        elif action == "status":
            parts = []
            parts.append("=== PM2 ===\n" + self._run("pm2 list 2>/dev/null || echo 'PM2 nao instalado'"))
            parts.append("=== Docker ===\n" + self._run("docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo 'Docker nao disponivel'"))
            return "\n\n".join(parts)

        return f"Acao '{action}' nao reconhecida."

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            return (r.stdout + r.stderr)[:5000] or "OK"
        except Exception as e:
            return f"Erro: {e}"
