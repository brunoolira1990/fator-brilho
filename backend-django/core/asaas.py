"""
Cliente da API do Asaas (v3, produção) — port de `src/lib/asaas.ts`.

Regras que a documentação manda e o código obedece (as mesmas que foram medidas na
fase anterior, quando a integração ainda morava no Astro):

 - Autenticação é o header `access_token`, não Bearer. O `$` faz parte da chave.
 - Chave com prefixo `$aact_prod_` = produção (https://api.asaas.com/v3);
   `$aact_hmlg_` = sandbox (https://api-sandbox.asaas.com/v3).
 - POST /v3/customers exige `name` e `cpfCnpj`.
 - POST /v3/checkouts exige `billingTypes`, `chargeTypes`, `callback` (com
   successUrl E cancelUrl) e `items[]` com `name` (até 30), `quantity`, `value` e
   `imageBase64` obrigatório/non-nullable.
 - Associar a cobrança a um cliente já cadastrado é o campo `customer` (e nunca
   `customer` + `customerData` na mesma request).
 - O webhook chama o campo do evento de `event`, não `eventType`.
 - `GET /v3/payments?checkoutSession=` é a junta que permite conferir o dinheiro
   antes de ativar plano.

Sem dependência nova: urllib da stdlib. Em serverless o custo de abrir TCP por
chamada não é o gargalo aqui — são no máximo três chamadas por request.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings

from .planos import Plano

TIMEOUT_S = 20


@dataclass(frozen=True)
class Resultado:
    """Ok carrega `dados`; erro carrega `status` (0 = nem chegamos no Asaas) e `erro`."""

    ok: bool
    dados: object = None
    status: int = 0
    erro: str = ""

    @staticmethod
    def sucesso(dados: object) -> "Resultado":
        return Resultado(ok=True, dados=dados)

    @staticmethod
    def falha(status: int, erro: str) -> "Resultado":
        return Resultado(ok=False, status=status, erro=erro)


def chave_asaas() -> str | None:
    return (settings.ASAAS_API_KEY or "").strip() or None


def asaas_configurado() -> bool:
    return bool(chave_asaas())


def base_asaas() -> str:
    # O ambiente se escolhe pela chave: quem tem a sandbox no lugar da produção
    # não quer acordar cobrando gente de verdade.
    return (
        "https://api-sandbox.asaas.com/v3"
        if chave_asaas().startswith("$aact_hmlg_")
        else "https://api.asaas.com/v3"
    )


def _descricao_do_erro(bruto: object, status: int) -> str:
    """
    O Asaas responde erro com `errors: [...]`, mas o formato do item não é garantido.
    Varre o que existir em vez de assumir uma chave.
    """
    if isinstance(bruto, dict) and isinstance(bruto.get("errors"), list):
        itens = []

        for item in bruto["errors"]:
            if isinstance(item, str):
                itens.append(item)
            elif isinstance(item, dict):
                texto = item.get("description") or item.get("message") or item.get("code")
                itens.append(texto if isinstance(texto, str) else json.dumps(item, ensure_ascii=False))
            else:
                itens.append(str(item))

        itens = [item for item in itens if item]

        if itens:
            return "; ".join(itens)

    return f"Asaas respondeu {status}."


def _chamar(caminho: str, method: str = "GET", corpo: dict | None = None) -> Resultado:
    chave = chave_asaas()

    if not chave:
        return Resultado.falha(0, "Falta ASAAS_API_KEY no ambiente.")

    requisicao = urllib.request.Request(
        f"{base_asaas()}{caminho}",
        method=method,
        data=None if corpo is None else json.dumps(corpo).encode("utf-8"),
        headers={
            "access_token": chave,
            "content-type": "application/json",
            "user-agent": "FatorBrilhoSaaS/1.0.0",
        },
    )

    try:
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_S) as resposta:
            status = resposta.status
            bruto = resposta.read()
    except urllib.error.HTTPError as erro:
        try:
            bruto = erro.read()
        except Exception:  # noqa: BLE001 - corpo pode já ter sido consumido
            bruto = b""

        try:
            corpo_erro = json.loads(bruto.decode("utf-8")) if bruto else None
        except (ValueError, UnicodeDecodeError):
            corpo_erro = None

        return Resultado.falha(erro.code, _descricao_do_erro(corpo_erro, erro.code))
    except Exception as erro:  # noqa: BLE001 - rede, DNS, timeout: nada aqui é acionável
        return Resultado.falha(0, f"Não foi possível falar com o Asaas ({erro.__class__.__name__}: {erro}).")

    try:
        dados = json.loads(bruto.decode("utf-8")) if bruto else None
    except (ValueError, UnicodeDecodeError):
        dados = None

    if 200 <= status < 300:
        return Resultado.sucesso(dados)

    return Resultado.falha(status, _descricao_do_erro(dados, status))


def hoje_sao_paulo() -> str:
    """'Hoje' no fuso do cliente, em yyyy-mm-dd. UTC viraria sábado às 21h de sexta."""
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")


def criar_cliente_asaas(nome: str, email: str, cpf_cnpj: str, referencia: str) -> Resultado:
    resposta = _chamar(
        "/customers",
        method="POST",
        corpo={
            "name": nome,
            "email": email,
            "cpfCnpj": cpf_cnpj,
            "externalReference": referencia,
        },
    )

    if not resposta.ok:
        return resposta

    id_ = resposta.dados.get("id") if isinstance(resposta.dados, dict) else None

    if not isinstance(id_, str) or not id_:
        return Resultado.falha(502, "O Asaas criou o cliente mas não devolveu o id.")

    return Resultado.sucesso({"id": id_})


def cliente_por_referencia(referencia: str) -> Resultado:
    """
    Recuperação idempotente: se a criação falhou depois de o Asaas já ter gravado, o
    mesmo CPF/CNPJ não pode virar dois clientes. Buscamos pelo externalReference, que
    é a primary key do usuário e por construção é um por conta.
    """
    resposta = _chamar(
        f"/customers?externalReference={urllib.parse.quote(referencia, safe='')}&limit=1"
    )

    if not resposta.ok:
        return resposta

    linhas = resposta.dados.get("data") if isinstance(resposta.dados, dict) else None
    primeira = linhas[0] if isinstance(linhas, list) and linhas else None
    id_ = primeira.get("id") if isinstance(primeira, dict) else None

    return Resultado.sucesso({"id": id_} if isinstance(id_, str) and id_ else None)


def criar_checkout_assinatura(
    customer_id: str, plano: Plano, success_url: str, cancel_url: str, referencia: str
) -> Resultado:
    nome_item = f"Plano {plano.nome}"

    resposta = _chamar(
        "/checkouts",
        method="POST",
        corpo={
            "customer": customer_id,
            "billingTypes": ["CREDIT_CARD"],
            "chargeTypes": ["RECURRENT"],
            "externalReference": referencia,
            "subscription": {"cycle": "MONTHLY", "nextDueDate": hoje_sao_paulo()},
            "callback": {"successUrl": success_url, "cancelUrl": cancel_url},
            "items": [
                {
                    # Máximo de 30 no schema; "Plano Profissional" tem 18.
                    "name": nome_item[:30],
                    "quantity": 1,
                    "value": plano.valor,
                    # Obrigatório e non-nullable, e não temos arte para o item.
                    "imageBase64": "",
                }
            ],
        },
    )

    if not resposta.ok:
        return resposta

    dados = resposta.dados if isinstance(resposta.dados, dict) else {}
    link = dados.get("link")

    if not isinstance(link, str) or not link.startswith("https://"):
        return Resultado.falha(502, "O Asaas não devolveu um link de checkout.")

    id_ = dados.get("id")

    return Resultado.sucesso({"id": id_ if isinstance(id_, str) else "", "link": link})


def pagamentos_do_checkout(checkout_id: str) -> Resultado:
    if not checkout_id or not (8 <= len(checkout_id) <= 64) or not checkout_id.replace("-", "").isalnum():
        return Resultado.falha(400, "Id de checkout com formato inesperado.")

    resposta = _chamar(f"/payments?checkoutSession={urllib.parse.quote(checkout_id, safe='')}&limit=20")

    if not resposta.ok:
        return resposta

    bruto = resposta.dados.get("data") if isinstance(resposta.dados, dict) else None
    linhas = bruto if isinstance(bruto, list) else []

    pagamentos = [
        linha
        for linha in linhas
        if isinstance(linha, dict)
        and isinstance(linha.get("id"), str)
        and isinstance(linha.get("status"), str)
        and isinstance(linha.get("value"), (int, float))
    ]

    return Resultado.sucesso(pagamentos)
