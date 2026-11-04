"""
Tratamento único de erro da API.

Todo ponto de entrada já devolve `{"ok": false, "error": "..."}` quando a validação
falha, porque é esse o contrato que o painel Astro lê. O que escapava dessa regra era
o erro gerado pelo próprio DRF — 401, 403, 404 e o `ValidationError` lançado dentro de
`perform_create` — que vinha como `{"detail": "..."}`.

Este handler fecha a porta: qualquer resposta de erro sai no mesmo formato. O texto é
fixo em pt-BR para 401/403/404 por dois motivos: (a) com `LANGUAGE_CODE = "pt-br"` o
DRF já traduz as próprias mensagens, então comparar pela string em inglês não funciona
nem nunca ia funcionar; (b) a mensagem crua do DRF não diz ao cliente nada que ele
possa fazer, e o diagnóstico real fica no log.
"""

import logging

from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

# O que o cliente lê, por status. Nada além disso vaza para a tela.
_TEXTO_POR_STATUS = {
    401: "Sessão expirada. Entre novamente para continuar.",
    403: "Você não tem permissão para esta operação.",
    404: "Não encontrado.",
}


def _mensagem(bruto: object) -> str:
    """Primeira mensagem legível, atravessando lista e dicionário."""
    if isinstance(bruto, str):
        return bruto

    if isinstance(bruto, list):
        for item in bruto:
            texto = _mensagem(item)

            if texto:
                return texto

        return ""

    if isinstance(bruto, dict):
        for chave in ("detail", "non_field_errors"):
            if chave in bruto:
                texto = _mensagem(bruto[chave])

                if texto:
                    return texto

        for valor in bruto.values():
            texto = _mensagem(valor)

            if texto:
                return texto

    return ""


def tratar_excecao(exc, context):
    resposta = exception_handler(exc, context)

    if resposta is None:
        # Erro que o DRF não converte em resposta (500 de verdade): deixa o Django tratar.
        return None

    dados = resposta.data

    if isinstance(dados, dict) and "ok" in dados:
        return resposta

    original = _mensagem(dados)
    mensagem = _TEXTO_POR_STATUS.get(resposta.status_code) or original or "Não foi possível completar a operação."

    if resposta.status_code in _TEXTO_POR_STATUS:
        # O texto trocado é do cliente; o que o desenvolvedor precisa ver é o original.
        logger.warning("[api:%s] %s", resposta.status_code, original)

    resposta.data = {"ok": False, "error": mensagem}

    return resposta
