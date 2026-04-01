from flask import Flask, render_template_string, request

app = Flask(__name__)

# Configurações
LOGO = "SulAmérica - Assistência Funeral"
COR_PRIMARIA = "#002d62"  # Azul escuro
COR_SECUNDARIA = "#ff7900"  # Laranja
CONSULTOR_NOME = "João da Silva"
CONSULTOR_TEL = "(11) 91234-5678"

PLANOS = [
    ("Individual", "Individual - a partir de R$29,90/mês", 29.90),
    ("Familiar_Cônjuge", "Familiar com Cônjuge - a partir de R$39,90/mês", 39.90),
    ("Cônjuge_Filhos", "Com Cônjuge e Filhos até 21 anos - a partir de R$49,90/mês", 49.90),
    ("Familiar_Completo", "Familiar Completo (cônjuge, filhos até 21, pai, mãe, sogro e sogra) - a partir de R$89,90/mês", 89.90),
]

BADGES = [
    "Não tem fidelidade!",
    "Não tem taxa de adesão!",
    "Documentação enviada antecipada, sem pagamento de adesão!",
]

RODAPE = "Inclusão de dependentes à parte, sujeito a regras de contratação, consulte um corretor."

# Página inicial
INDEX_HTML = f"""
<!DOCTYPE html>
<html lang='pt-br'>
<head>
    <meta charset='UTF-8'>
    <title>{LOGO}</title>
</head>
<body style='background: #f6f8fa; font-family: Arial, sans-serif; margin:0;'>
    <div style='background: {COR_PRIMARIA}; color: white; padding: 32px 0; text-align: center;'>
        <span style='font-size: 2.2em; font-weight: bold; letter-spacing: 1px;'>{LOGO}</span>
    </div>
    <div style='max-width: 420px; background: white; margin: 32px auto; padding: 32px 28px 24px 28px; border-radius: 12px; box-shadow: 0 2px 12px #002d6233;'>
        <form method="POST" action="/cotacao">
            <label style='font-weight:bold; color:{COR_PRIMARIA};'>Nome completo:</label><br>
            <input name='nome' required style='width:100%;padding:8px;margin-bottom:16px;border:1px solid #ccc;border-radius:6px;'><br>
            <label style='font-weight:bold; color:{COR_PRIMARIA};'>Telefone:</label><br>
            <input name='telefone' required style='width:100%;padding:8px;margin-bottom:16px;border:1px solid #ccc;border-radius:6px;'><br>
            <label style='font-weight:bold; color:{COR_PRIMARIA};'>E-mail:</label><br>
            <input name='email' type='email' required style='width:100%;padding:8px;margin-bottom:16px;border:1px solid #ccc;border-radius:6px;'><br>
            <label style='font-weight:bold; color:{COR_PRIMARIA};'>Tipo de plano:</label><br>
            <select name='plano' required style='width:100%;padding:8px;margin-bottom:24px;border:1px solid #ccc;border-radius:6px;'>
                {''.join([f'<option value="{p[0]}">{p[1]}</option>' for p in PLANOS])}
            </select><br>
            <button type='submit' style='width:100%;background:{COR_SECUNDARIA};color:white;font-size:1.1em;padding:12px;border:none;border-radius:6px;font-weight:bold;cursor:pointer;'>Solicitar Cotação</button>
        </form>
        <div style='margin-top:28px; text-align:center;'>
            {''.join([f'<span style="display:inline-block;background:#2ecc40;color:white;padding:6px 12px;margin:4px 2px;border-radius:16px;font-size:0.98em;font-weight:600;">{badge}</span>' for badge in BADGES])}
        </div>
    </div>
    <div style='max-width:420px;margin:0 auto 16px auto;text-align:center;color:#555;font-size:0.96em;'>
        <span style='color:{COR_PRIMARIA};font-weight:bold;'>Consultor:</span> {CONSULTOR_NOME} <span style='color:{COR_SECUNDARIA};font-weight:bold;'>{CONSULTOR_TEL}</span>
    </div>
    <footer style='background:#eee;color:#444;text-align:center;padding:14px 0;font-size:0.93em;border-top:1px solid #ddd;'>
        {RODAPE}
    </footer>
</body>
</html>
"""

# Página de confirmação
CONFIRM_HTML = f"""
<!DOCTYPE html>
<html lang='pt-br'>
<head>
    <meta charset='UTF-8'>
    <title>Confirmação - {LOGO}</title>
</head>
<body style='background: #f6f8fa; font-family: Arial, sans-serif; margin:0;'>
    <div style='background: {COR_PRIMARIA}; color: white; padding: 32px 0; text-align: center;'>
        <span style='font-size: 2.2em; font-weight: bold; letter-spacing: 1px;'>{LOGO}</span>
    </div>
    <div style='max-width: 420px; background: white; margin: 32px auto; padding: 32px 28px 24px 28px; border-radius: 12px; box-shadow: 0 2px 12px #002d6233;'>
        <h2 style='color:{COR_PRIMARIA};margin-bottom:18px;'>Cotação Recebida!</h2>
        <div style='margin-bottom:18px;'>
            <b>Nome:</b> {{nome}}<br>
            <b>Telefone:</b> {{telefone}}<br>
            <b>E-mail:</b> {{email}}<br>
            <b>Plano escolhido:</b> {{plano_nome}}<br>
            <b>Valor:</b> <span style='color:{COR_SECUNDARIA};font-size:1.1em;font-weight:bold;'>R${{valor}}/mês</span>
        </div>
        <div style='margin-top:18px; text-align:center;'>
            {''.join([f'<span style="display:inline-block;background:#2ecc40;color:white;padding:6px 12px;margin:4px 2px;border-radius:16px;font-size:0.98em;font-weight:600;">{badge}</span>' for badge in BADGES])}
        </div>
        <a href='/' style='display:block;margin-top:28px;color:{COR_PRIMARIA};font-weight:bold;text-decoration:underline;'>Voltar</a>
    </div>
    <div style='max-width:420px;margin:0 auto 16px auto;text-align:center;color:#555;font-size:0.96em;'>
        <span style='color:{COR_PRIMARIA};font-weight:bold;'>Consultor:</span> {CONSULTOR_NOME} <span style='color:{COR_SECUNDARIA};font-weight:bold;'>{CONSULTOR_TEL}</span>
    </div>
    <footer style='background:#eee;color:#444;text-align:center;padding:14px 0;font-size:0.93em;border-top:1px solid #ddd;'>
        {RODAPE}
    </footer>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def index():
    return render_template_string(INDEX_HTML)

@app.route('/cotacao', methods=['POST'])
def cotacao():
    nome = request.form.get('nome', '')
    telefone = request.form.get('telefone', '')
    email = request.form.get('email', '')
    plano_key = request.form.get('plano', '')
    plano_nome = next((p[1] for p in PLANOS if p[0] == plano_key), 'Plano não encontrado')
    valor = next((f"{p[2]:.2f}" for p in PLANOS if p[0] == plano_key), '--')
    return render_template_string(CONFIRM_HTML, nome=nome, telefone=telefone, email=email, plano_nome=plano_nome, valor=valor)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
