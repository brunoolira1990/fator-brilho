"""
Normalização e validação de texto, portas exatas de `src/lib/slug.ts`,
`src/lib/urls.ts` e da limpeza que o endpoint do Astro fazia antes de escrever.

As mensagens continuam em pt-BR e com o mesmo texto porque elas são o que o
cliente lê na tela; mudar a palavra aqui é quebrar a paridade com o formulário.
"""

import re
import unicodedata

SLUG_MIN = 3
SLUG_MAX = 63

LIMITE_SERVICOS = 12
LIMITE_GALERIA = 12

_COMBINING = re.compile(r"[\u0300-\u036f]")
_SEPARADORES = re.compile(r"[\s_/]+")
_NAO_SLUG = re.compile(r"[^a-z0-9-]")
_HIFENS_DUPLOS = re.compile(r"-{2,}")
_PADRAO_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
_HTTP = re.compile(r"^https?://", re.I)


def gerar_slug(bruto: str) -> str:
    """"Estética do Bruno" -> "estetica-do-bruno"."""
    texto = bruto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = _COMBINING.sub("", texto)
    texto = _SEPARADORES.sub("-", texto)
    texto = _NAO_SLUG.sub("", texto)
    texto = _HIFENS_DUPLOS.sub("-", texto)

    return texto.strip("-")


def validar_slug(slug: str) -> str | None:
    """Erro em pt-BR, ou None quando o slug pode virar link. Vazio também é None: o link é opcional."""
    if slug == "":
        return None

    if len(slug) < SLUG_MIN:
        return f"Link do site: use pelo menos {SLUG_MIN} caracteres (ex: estetica-do-bruno)."

    if len(slug) > SLUG_MAX:
        return f"Link do site: use no máximo {SLUG_MAX} caracteres."

    if not _PADRAO_SLUG.match(slug):
        return "Link do site: use letras minúsculas, números e hífen, sem começar nem terminar com hífen."

    return None


def url_de_imagem(valor: object) -> str | None:
    """
    Guarda de URL de imagem: só http(s) ou caminho do próprio site. Um `javascript:`
    ou `data:text/html` escrito direto na coluna viraria payload na página pública.
    """
    if not isinstance(valor, str):
        return None

    bruto = valor.strip()

    if bruto == "":
        return None

    if _HTTP.match(bruto):
        return bruto

    if bruto.startswith("/") and not bruto.startswith("//"):
        return bruto

    return None


def limpa_texto(valor: object) -> str | None:
    """Anything que não seja texto vira None; string vazia também."""
    if not isinstance(valor, str):
        return None

    bruto = valor.strip()

    return bruto or None
