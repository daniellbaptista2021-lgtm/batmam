"""Deploy webhook — DESABILITADO POR SEGURANÇA.

O endpoint de auto-deploy via GitHub foi permanentemente bloqueado.
Deploy deve ser feito manualmente pelo administrador via terminal.
"""

import sys
from http.server import HTTPServer, BaseHTTPRequestHandler


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "Deploy automatico desabilitado por seguranca."}')

    def do_GET(self):
        self.send_response(403)
        self.end_headers()
        self.wfile.write(b'{"error": "Desabilitado."}')

    def log_message(self, format, *args):
        pass  # Sem logs — nao vazar informacao


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)  # Apenas loopback
    print(f"[WEBHOOK] Bloqueado — deploy automatico desabilitado.")
    server.serve_forever()
