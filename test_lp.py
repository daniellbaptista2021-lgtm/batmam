from clow.agent import Agent

a = Agent(cwd="/root/clow", auto_approve=True)

prompt = (
    "Cria uma landing page premium para a barbearia JJ Barbers "
    "e salva em /root/clow/static/files/jj-barbers.html\n\n"
    "Fontes: Playfair Display titulos, Barlow body, Google Fonts.\n"
    "Paleta: preto #0A0A0A, dourado #C9A84C, branco sujo #F5F0E8, cinza #1A1A1A.\n"
    "Animacoes fade-in staggered, hover nos cards. Titulos peso 900 tamanho 4rem+.\n\n"
    "Secoes: Hero fullscreen com JJ Barbers dourado grande + botao CTA, "
    "Sobre nos, Servicos em cards com precos, Galeria 6 fotos, "
    "Depoimentos 3 clientes, Localizacao com horario, Footer.\n\n"
    "Extras: botao WhatsApp flutuante verde, responsivo mobile-first, "
    "HTML unico com CSS e JS inline, scroll suave, menu hamburguer mobile.\n\n"
    "IMPORTANTE: Use a ferramenta Write para criar o arquivo HTML completo."
)

r = a.run_turn(prompt)
print("DONE:", len(r), "chars")
print(r[:300])
