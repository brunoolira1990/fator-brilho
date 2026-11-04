"""
Fonte única dos três planos, agora no backend.

Port fiel de `src/lib/planos.ts`: os mesmos slugs, o mesmo preço de vitrine e o mesmo
`valor` que vai para o Asaas. Quando o frontend terminar de apontar para cá, o
arquivo TypeScript é apagado e esta vira a única lista — ter as duas vivas é o que
permite preço cobrado diferente de preço anunciado.

Os slugs batem com as choices de `core.models.PLANOS`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Plano:
    slug: str
    nome: str
    preco: str
    valor: float
    destaque: bool
    itens: list[str]


PLANOS: list[Plano] = [
    Plano(
        slug="essencial",
        nome="Essencial",
        preco="R$ 97",
        valor=97.0,
        destaque=False,
        itens=[
            "Site profissional de 1 página",
            "Botão de WhatsApp integrado",
            "Galeria Antes/Depois (até 5 fotos)",
            "Hospedagem e domínio inclusos",
            "Painel de controle básico",
        ],
    ),
    Plano(
        slug="profissional",
        nome="Profissional",
        preco="R$ 147",
        valor=147.0,
        destaque=True,
        itens=[
            "Tudo do Essencial, mais:",
            "Galeria Antes/Depois ilimitada",
            "Lista de serviços personalizada",
            "Otimização do Google Meu Negócio",
            "Suporte via WhatsApp",
        ],
    ),
    Plano(
        slug="premium",
        nome="Premium",
        preco="R$ 297",
        valor=297.0,
        destaque=False,
        itens=[
            "Tudo do Profissional, mais:",
            "Sistema de lembretes de manutenção (em breve)",
            "Página de agendamento (em breve)",
            "Atendimento prioritário",
        ],
    ),
]


def plano_por_slug(bruto: object) -> Plano | None:
    """
    Slug validado contra a whitelist. Nada de usar direto o que veio da URL: é isso
    que impede um ?plano=<script> de virar texto na tela e garante que o valor
    cobrado é um dos três do cardápio.
    """
    if not isinstance(bruto, str):
        return None

    slug = bruto.strip().lower()

    return next((plano for plano in PLANOS if plano.slug == slug), None)


def nome_do_plano(bruto: object) -> str | None:
    plano = plano_por_slug(bruto)

    return plano.nome if plano else None
