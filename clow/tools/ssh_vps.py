"""SSH & VPS Management Tools — acesso remoto, Nginx, SSL, monitoramento, cron, backup."""

from __future__ import annotations
import subprocess
import os
import json
from typing import Any
from .base import BaseTool


class SshConnectTool(BaseTool):
    name = "ssh_connect"
    description = "Executa comando em VPS remota via SSH. Requer host, user e key/password."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "IP ou hostname da VPS"},
                "user": {"type": "string", "description": "Usuario SSH (ex: root)"},
                "command": {"type": "string", "description": "Comando a executar no servidor"},
                "port": {"type": "integer", "description": "Porta SSH (padrao: 22)"},
                "key_path": {"type": "string", "description": "Caminho da chave SSH privada"},
                "password": {"type": "string", "description": "Senha SSH (usar key_path e preferivel)"},
            },
            "required": ["host", "user", "command"],
        }

    def execute(self, **kwargs: Any) -> str:
        host = kwargs["host"]
        user = kwargs["user"]
        command = kwargs["command"]
        port = kwargs.get("port", 22)
        key_path = kwargs.get("key_path", "")
        password = kwargs.get("password", "")

        ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                    "-p", str(port)]
        if key_path:
            ssh_cmd.extend(["-i", key_path])
        ssh_cmd.append(f"{user}@{host}")
        ssh_cmd.append(command)

        if password and not key_path:
            ssh_cmd = ["sshpass", "-p", password] + ssh_cmd

        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
            output = (result.stdout or "") + (result.stderr or "")
            return output[:5000] or "Comando executado sem output."
        except subprocess.TimeoutExpired:
            return "Erro: timeout (60s) ao conectar via SSH."
        except FileNotFoundError:
            return "Erro: sshpass nao instalado. Use key_path ou instale: apt-get install sshpass"
        except Exception as e:
            return f"Erro SSH: {e}"


class ManageProcessTool(BaseTool):
    name = "manage_process"
    description = "Gerencia processos e servicos do sistema. start/stop/restart/status/enable/disable."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart", "status", "enable", "disable", "list", "logs"],
                    "description": "Acao a executar no servico",
                },
                "service": {"type": "string", "description": "Nome do servico (ex: nginx, docker, postgresql)"},
                "lines": {"type": "integer", "description": "Numero de linhas de log (padrao: 30)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        service = kwargs.get("service", "")
        lines = kwargs.get("lines", 30)

        if action == "list":
            return self._run("systemctl list-units --type=service --state=running --no-pager | head -40")
        if not service:
            return "Erro: service e obrigatorio para esta acao."
        if action == "logs":
            return self._run(f"journalctl -u {service} --no-pager -n {lines}")
        if action in ("start", "stop", "restart", "status", "enable", "disable"):
            return self._run(f"systemctl {action} {service}")
        return f"Acao '{action}' nao reconhecida."

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return (r.stdout + r.stderr)[:5000] or "OK"
        except Exception as e:
            return f"Erro: {e}"


class ConfigureNginxTool(BaseTool):
    name = "configure_nginx"
    description = "Gerencia configuracoes Nginx. Cria/edita sites, testa config, reload."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_sites", "create_site", "enable_site", "disable_site",
                             "test_config", "reload", "read_site", "get_status"],
                    "description": "Acao Nginx",
                },
                "domain": {"type": "string", "description": "Dominio do site (ex: app.example.com)"},
                "config": {"type": "string", "description": "Conteudo da config Nginx (para create_site)"},
                "upstream_port": {"type": "integer", "description": "Porta do app backend (para proxy_pass)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        domain = kwargs.get("domain", "")
        config_content = kwargs.get("config", "")
        port = kwargs.get("upstream_port", 0)

        if action == "list_sites":
            return self._run("ls -la /etc/nginx/sites-enabled/ 2>/dev/null || ls -la /etc/nginx/conf.d/")
        elif action == "get_status":
            return self._run("nginx -t 2>&1 && systemctl status nginx --no-pager -l")
        elif action == "test_config":
            return self._run("nginx -t 2>&1")
        elif action == "reload":
            test = self._run("nginx -t 2>&1")
            if "successful" in test:
                return self._run("systemctl reload nginx") + "\nNginx recarregado."
            return f"Config invalida, reload cancelado:\n{test}"
        elif action == "read_site":
            if not domain:
                return "Erro: domain obrigatorio."
            for path in [f"/etc/nginx/sites-available/{domain}", f"/etc/nginx/conf.d/{domain}.conf"]:
                if os.path.exists(path):
                    return open(path).read()[:5000]
            return f"Config para '{domain}' nao encontrada."
        elif action == "create_site":
            if not domain:
                return "Erro: domain obrigatorio."
            if not config_content and port:
                config_content = self._proxy_template(domain, port)
            elif not config_content:
                return "Erro: config ou upstream_port obrigatorio."
            path = f"/etc/nginx/sites-available/{domain}"
            os.makedirs("/etc/nginx/sites-available", exist_ok=True)
            with open(path, "w") as f:
                f.write(config_content)
            return f"Config salva em {path}. Use enable_site + reload."
        elif action == "enable_site":
            if not domain:
                return "Erro: domain obrigatorio."
            src = f"/etc/nginx/sites-available/{domain}"
            dst = f"/etc/nginx/sites-enabled/{domain}"
            if not os.path.exists(src):
                return f"Config {src} nao existe."
            return self._run(f"ln -sf {src} {dst}")
        elif action == "disable_site":
            if not domain:
                return "Erro: domain obrigatorio."
            return self._run(f"rm -f /etc/nginx/sites-enabled/{domain}")
        return f"Acao '{action}' nao reconhecida."

    def _proxy_template(self, domain: str, port: int) -> str:
        return f"""server {{
    listen 80;
    server_name {domain};
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}"""

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            return (r.stdout + r.stderr)[:5000] or "OK"
        except Exception as e:
            return f"Erro: {e}"


class ManageSslTool(BaseTool):
    name = "manage_ssl"
    description = "Gerencia certificados SSL. Instala Let's Encrypt, renova, verifica status."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["install", "renew", "status", "list", "revoke"],
                    "description": "Acao SSL",
                },
                "domain": {"type": "string", "description": "Dominio para o certificado"},
                "email": {"type": "string", "description": "Email para Let's Encrypt (para install)"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        domain = kwargs.get("domain", "")
        email = kwargs.get("email", "")

        if action == "list":
            return self._run("certbot certificates 2>/dev/null || echo 'certbot nao instalado'")
        elif action == "status":
            if not domain:
                return self._run("certbot certificates")
            return self._run(f"echo | openssl s_client -connect {domain}:443 -servername {domain} 2>/dev/null | openssl x509 -noout -dates -subject 2>/dev/null || echo 'SSL nao ativo para {domain}'")
        elif action == "install":
            if not domain:
                return "Erro: domain obrigatorio."
            email_flag = f"--email {email}" if email else "--register-unsafely-without-email"
            return self._run(f"certbot --nginx -d {domain} {email_flag} --agree-tos --non-interactive 2>&1")
        elif action == "renew":
            return self._run("certbot renew --dry-run 2>&1")
        elif action == "revoke":
            if not domain:
                return "Erro: domain obrigatorio."
            return self._run(f"certbot revoke --cert-name {domain} --non-interactive 2>&1")
        return f"Acao '{action}' nao reconhecida."

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return (r.stdout + r.stderr)[:5000] or "OK"
        except Exception as e:
            return f"Erro: {e}"


class MonitorResourcesTool(BaseTool):
    name = "monitor_resources"
    description = "Monitora recursos do servidor: CPU, RAM, disco, rede, processos."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "check": {
                    "type": "string",
                    "enum": ["all", "cpu", "memory", "disk", "network", "top_processes"],
                    "description": "Recurso a verificar (padrao: all)",
                },
            },
        }

    def execute(self, **kwargs: Any) -> str:
        check = kwargs.get("check", "all")
        parts = []

        if check in ("all", "cpu"):
            parts.append("=== CPU ===\n" + self._run("uptime && nproc"))
        if check in ("all", "memory"):
            parts.append("=== MEMORIA ===\n" + self._run("free -h"))
        if check in ("all", "disk"):
            parts.append("=== DISCO ===\n" + self._run("df -h --total 2>/dev/null | grep -E 'Size|total|/$'"))
        if check in ("all", "network"):
            parts.append("=== REDE ===\n" + self._run("ss -tlnp 2>/dev/null | head -20"))
        if check in ("all", "top_processes"):
            parts.append("=== TOP PROCESSOS ===\n" + self._run("ps aux --sort=-%mem | head -10"))

        return "\n\n".join(parts) or "Nenhum dado disponivel."

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return (r.stdout or r.stderr)[:2000]
        except Exception as e:
            return f"Erro: {e}"


class ManageCronTool(BaseTool):
    name = "manage_cron"
    description = "Gerencia tarefas agendadas (cron). Lista, cria e remove cron jobs."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove"],
                    "description": "Acao cron",
                },
                "schedule": {"type": "string", "description": "Expressao cron (ex: '0 3 * * *' para 3h diario)"},
                "command": {"type": "string", "description": "Comando a agendar"},
                "comment": {"type": "string", "description": "Comentario identificador do job"},
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        schedule = kwargs.get("schedule", "")
        command = kwargs.get("command", "")
        comment = kwargs.get("comment", "clow-job")

        if action == "list":
            return self._run("crontab -l 2>/dev/null || echo 'Nenhum cron configurado.'")
        elif action == "add":
            if not schedule or not command:
                return "Erro: schedule e command obrigatorios."
            line = f"{schedule} {command} # {comment}"
            return self._run(f'(crontab -l 2>/dev/null; echo "{line}") | crontab -')
        elif action == "remove":
            if not comment:
                return "Erro: comment obrigatorio para identificar o job."
            return self._run(f"crontab -l 2>/dev/null | grep -v '# {comment}' | crontab -")
        return f"Acao '{action}' nao reconhecida."

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return (r.stdout + r.stderr)[:3000] or "OK"
        except Exception as e:
            return f"Erro: {e}"


class BackupTool(BaseTool):
    name = "backup_create"
    description = "Cria e restaura backups de arquivos e bancos de dados."
    requires_confirmation = True

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "restore"],
                    "description": "Acao de backup",
                },
                "source": {"type": "string", "description": "Caminho ou banco a fazer backup"},
                "backup_dir": {"type": "string", "description": "Diretorio de destino (padrao: ~/backups)"},
                "backup_file": {"type": "string", "description": "Arquivo de backup para restore"},
                "type": {
                    "type": "string",
                    "enum": ["files", "postgres", "mysql"],
                    "description": "Tipo de backup (padrao: files)",
                },
            },
            "required": ["action"],
        }

    def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        source = kwargs.get("source", "")
        backup_dir = kwargs.get("backup_dir", os.path.expanduser("~/backups"))
        backup_file = kwargs.get("backup_file", "")
        btype = kwargs.get("type", "files")

        os.makedirs(backup_dir, exist_ok=True)

        if action == "list":
            return self._run(f"ls -lah {backup_dir}/ 2>/dev/null | tail -20")
        elif action == "create":
            if not source:
                return "Erro: source obrigatorio."
            import time
            ts = time.strftime("%Y%m%d_%H%M%S")
            if btype == "files":
                name = os.path.basename(source.rstrip("/"))
                out = f"{backup_dir}/{name}-{ts}.tar.gz"
                return self._run(f"tar -czf {out} -C {os.path.dirname(source)} {name} 2>&1 && echo 'Backup: {out}'")
            elif btype == "postgres":
                out = f"{backup_dir}/pg-{ts}.sql.gz"
                return self._run(f"pg_dump {source} | gzip > {out} 2>&1 && echo 'Backup: {out}'")
            elif btype == "mysql":
                out = f"{backup_dir}/mysql-{ts}.sql.gz"
                return self._run(f"mysqldump {source} | gzip > {out} 2>&1 && echo 'Backup: {out}'")
        elif action == "restore":
            if not backup_file:
                return "Erro: backup_file obrigatorio."
            if backup_file.endswith(".tar.gz"):
                dest = source or "."
                return self._run(f"tar -xzf {backup_file} -C {dest} 2>&1")
            elif backup_file.endswith(".sql.gz"):
                if not source:
                    return "Erro: source (nome do banco) obrigatorio para restore SQL."
                return self._run(f"gunzip -c {backup_file} | psql {source} 2>&1")
        return f"Acao '{action}' nao reconhecida."

    def _run(self, cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            return (r.stdout + r.stderr)[:5000] or "OK"
        except Exception as e:
            return f"Erro: {e}"
