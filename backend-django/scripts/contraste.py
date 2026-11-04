"""
Mede contraste WCAG 2.x (razão de luminância relativa) antes de qualquer cor entrar
no admin. Rode: python scripts/contraste.py

Regra do projeto: texto pequeno precisa de 4.5:1, texto grande (>=18.66px bold ou
24px) 3:1. Nada é aplicado com cor "no olho".
"""

"""
Pares medidos no admin REAL, rodando `getComputedStyle` na página servida por
manage.py runserver em 2026-11-04 (não cores chutadas do Bootstrap):
 - corpo da página ......... #2b3035  (rgb(43, 48, 53))
 - barra de navegação ...... #212529  (rgb(33, 37, 41))
 - texto do dark mode ...... #dee2e6
 - link de sidebar ......... rgba(255,255,255,.65) -> #969ba0 aproximado
O fundo do conteúdo é #2b3035, e é contra ele que link e texto têm que passar; os
pares antigos usavam #212529, que é só a barra de cima.
"""

CORPO = "#2b3035"
BARRA = "#212529"

# (rótulo, primeiro plano, fundo, exige 4.5:1?)
PAIRS = [
    ("branco sobre o verde do produto", "#ffffff", "#075E54"),
    ("branco sobre o verde escuro (hover)", "#ffffff", "#064a42"),
    ("branco sobre o verde (pressed)", "#ffffff", "#053a34"),
    ("verde do produto sobre branco", "#075E54", "#ffffff"),
    ("texto do dark mode sobre o corpo", "#dee2e6", CORPO),
    ("texto do dark mode sobre a barra", "#dee2e6", BARRA),
    ("texto secundário sobre o corpo", "#adb5bd", CORPO),
    ("link emerald sobre o corpo", "#34d399", CORPO),
    ("link emerald sobre a barra", "#34d399", BARRA),
    # Não é par de texto: o verde do produto entra como SUPERFÍCIE com texto branco
    # (linha 1). Medido aqui só para registrar que ele não pode virar cor de link.
    ("verde do produto sobre o corpo", "#075E54", CORPO, False),
    ("verde do produto sobre a barra", "#075E54", BARRA, False),
    # candidatos a cor de link/acento no admin escuro, para a decisão não precisar
    # ser reaberta na próxima vez que alguém quiser "um verde mais escuro no link".
    ("link: teal-400 sobre o corpo", "#2dd4bf", CORPO),
    ("link: teal-300 sobre o corpo", "#5eead4", CORPO),
    # Candidato rejeitado (4.12:1), medido e mantido aqui.
    ("link: teal-600 sobre o corpo", "#0d9488", CORPO, False),
    # link padrão do jazzmin no sidebar: rgba(255,255,255,.65) medido na página.
    # Composto sobre a barra #212529: 0.65*255 + 0.35*33 = 177 (R), 179 (G), 180 (B).
    ("link de sidebar (branco 65%) sobre a barra", "#b1b3b4", BARRA),
    ("link de sidebar (branco 65%) sobre o corpo", "#b5b7b8", CORPO),
    # Botões da linha de salvar do admin. Medidos na página real: "Salvar" vinha
    # btn-success (#198754) e os secundários btn-info (#0dcaf0) — verde e ciano do
    # Bootstrap, não a marca. Aqui entram como superfície com texto branco.
    ("branco sobre o verde do produto (botão Salvar)", "#ffffff", "#075E54"),
    ("branco sobre o cinza da barra (botões secundários)", "#ffffff", "#343a40"),
    ("preto sobre o ciano original do btn-info", "#000000", "#0dcaf0"),
]



def _canal(bruto: str) -> float:
    valor = int(bruto, 16) / 255

    return valor / 12.92 if valor <= 0.04045 else ((valor + 0.055) / 1.055) ** 2.4


def luminancia(hex_cor: str) -> float:
    cor = hex_cor.lstrip("#")

    if len(cor) == 3:
        cor = "".join(letra * 2 for letra in cor)

    r, g, b = (_canal(cor[0:2]), _canal(cor[2:4]), _canal(cor[4:6]))

    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def razao(uma: str, duas: str) -> float:
    a, b = luminancia(uma), luminancia(duas)
    mais, menos = max(a, b), min(a, b)

    return (mais + 0.05) / (menos + 0.05)


def main() -> int:
    print(f"{'par'.ljust(52)} {'foreground':>10} {'background':>10} {'razão':>8}  AA 4.5  AAA 7")
    falhas = 0

    for par in PAIRS:
        rotulo, frente, verso = par[0], par[1], par[2]
        exige = par[3] if len(par) > 3 else True
        r = razao(frente, verso)
        aa = "sim" if r >= 4.5 else "NÃO"
        aaa = "sim" if r >= 7 else "não"

        if exige and r < 4.5:
            falhas += 1

        marcador = "" if exige else "  (medida, não é par de texto)"
        print(f"{rotulo.ljust(52)} {frente.upper():>10} {verso.upper():>10} {r:>7.2f}:1  {aa:>6}  {aaa:>5}{marcador}")

    print(f"\n{falhas} par(es) abaixo de 4.5:1 (texto pequeno).")

    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
