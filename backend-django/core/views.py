"""
Views da API.

Três públicos diferentes passam por aqui:

 - o painel Astro, autenticado pelo cookie de token (EsteticaView, ViewSets,
   CheckoutView);
 - qualquer visitante, para a página pública /site/<slug> (PublicoView, PlanosView);
 - o Asaas, para o webhook, que autentica pelo header `asaas-access-token` e não por
   usuário nenhum (AsaasWebhookView).

A resposta é sempre JSON no formato `{ ok, ... }`, que é o contrato que o frontend já
consome hoje.
"""

import hmac
import json
import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import asaas
from .limpeza import LIMITE_GALERIA, LIMITE_SERVICOS
from .models import Estetica, Galeria, Servico
from .planos import PLANOS, plano_por_slug
from .serializers import (
    EsteticaSerializer,
    GaleriaSerializer,
    LoginSerializer,
    PublicoSerializer,
    RegistroSerializer,
    ServicoSerializer,
)

logger = logging.getLogger(__name__)

STATUS_PAGO = {"CONFIRMED", "RECEIVED"}


def _resposta(mensagem: str, codigo: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"ok": False, "error": mensagem}, status=codigo)


def _chave_token(usuario) -> Token:
    """Um token por usuário, criado na primeira necessidade."""
    token, _ = Token.objects.get_or_create(user=usuario)

    return token


def _grava_cookie(response: Response, token: str) -> None:
    """
    Nome do cookie fixo, valor = a chave do token.

    `set_cookie` tem a assinatura `set_cookie(key, value='', ...)`: esquecer o valor
    posicional cria um cookie vazio, que autentica nada — e o login devolve 200 como
    se tivesse funcionado. Está coberto por teste (AutenticacaoTests).
    """
    response.set_cookie(
        settings.TOKEN_COOKIE,
        token,
        max_age=settings.TOKEN_COOKIE_AGE,
        httponly=True,
        # Em produção o par None + Secure é o que permite o cookie atravessar do
        # domínio da API para o do frontend. Em http local o navegador recusaria
        # None+Secure, então fica Lax sem secure.
        secure=not settings.DEBUG,
        samesite="None" if not settings.DEBUG else "Lax",
        path="/",
    )


class RegistroView(APIView):
    """Cadastro de conta nova + a estética vazia dela, numa transação."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serie = RegistroSerializer(data=request.data)

        if not serie.is_valid():
            return Response({"ok": False, "error": _primeiro_erro(serie)}, status=400)

        email = serie.validated_data["email"]

        with transaction.atomic():
            # username é o que as tabelas de autenticação indexam; o e-mail é a
            # identidade que o cliente digita. Manter os dois iguais evita a pergunta
            # "qual dos dois eu uso para entrar?".
            usuario = User.objects.create_user(username=email, email=email, password=serie.validated_data["senha"])
            estetica = Estetica.objects.create(user=usuario, nome_negocio=serie.validated_data.get("nome_negocio", ""))

        token = _chave_token(usuario)
        resposta = Response({"ok": True, "email": usuario.email, "id": estetica.pk}, status=201)
        _grava_cookie(resposta, token.key)

        return resposta


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serie = LoginSerializer(data=request.data)

        if not serie.is_valid():
            return Response({"ok": False, "error": _primeiro_erro(serie)}, status=400)

        login = serie.validated_data["login"].strip()
        usuario = authenticate(request, username=login, password=serie.validated_data["senha"])

        if usuario is None:
            # Mensagem única para "não existe" e "senha errada": a diferença entre as
            # duas é um catálogo de contas válido.
            return _resposta("E-mail ou senha incorretos.", 401)

        if not usuario.is_active:
            return _resposta("Esta conta está desativada.", 403)

        token = _chave_token(usuario)
        resposta = Response({"ok": True, "email": usuario.email, "administrador": usuario.is_staff})
        _grava_cookie(resposta, token.key)

        return resposta


class LogoutView(APIView):
    def post(self, request):
        token = getattr(request, "auth", None)

        if token is not None:
            token.delete()

        resposta = Response({"ok": True})
        resposta.delete_cookie(settings.TOKEN_COOKIE, path="/")

        return resposta


class EsteticaView(APIView):
    """
    GET devolve a estética + as duas listas; PUT grava tudo numa transação.

    O PUT aceita `servicos` e `galeria` no mesmo corpo porque é assim que o painel
    funciona: uma tela, um botão Salvar. Ausente = não mexe; `[]` = esvaziou de
    propósito. As duas coisas eram distintas no endpoint antigo e continuam sendo.
    """

    def get(self, request):
        estetica = Estetica.objects.filter(user=request.user).first()
        serie = EsteticaSerializer(estetica) if estetica else None

        return Response(
            {
                "ok": True,
                "data": serie.data if serie else None,
                # O painel Astro é renderizado no servidor e mostra o e-mail da conta na
                # barra lateral; sem isto a tela precisaria de um endpoint só para isso.
                # `username` é o e-mail em toda conta criada pelo painel (RegistroView),
                # então o fallback só pega conta criada no admin com login à parte.
                "email": request.user.email or request.user.username,
                "servicos": ServicoSerializer(self._servicos(request), many=True).data,
                "galeria": GaleriaSerializer(self._galeria(request), many=True).data,
            }
        )

    def put(self, request):
        corpo = request.data if isinstance(request.data, dict) else {}

        estetica = Estetica.objects.filter(user=request.user).first()
        criado_agora = False

        with transaction.atomic():
            if estetica is None:
                # Primeira escrita de quem acabou de se cadastrar: a linha nasce aqui.
                estetica = Estetica.objects.create(user=request.user)
                criado_agora = True

            serie = EsteticaSerializer(estetica, data=corpo, partial=True)

            if not serie.is_valid():
                return Response({"ok": False, "error": _primeiro_erro(serie)}, status=400)

            serie.save()

            erro_listas = self._substitui_listas(request, estetica, corpo)

            if erro_listas:
                # Levantar aqui desfaz também o save de cima: ou entra tudo, ou nada.
                raise serializers.ValidationError({"detail": erro_listas})

            if criado_agora:
                estetica.refresh_from_db()

            return Response(
                {
                    "ok": True,
                    "data": EsteticaSerializer(estetica).data,
                    # Mesma shape do GET: o painel espelha a resposta depois de salvar
                    # sem precisar de uma segunda chamada (e sem tela mostrando um e-mail
                    # que sumiu).
                    "email": request.user.email or request.user.username,
                    "servicos": ServicoSerializer(self._servicos(request), many=True).data,
                    "galeria": GaleriaSerializer(self._galeria(request), many=True).data,
                }
            )

    def _servicos(self, request):
        return Servico.objects.filter(estetica__user=request.user)

    def _galeria(self, request):
        return Galeria.objects.filter(estetica__user=request.user)

    def _substitui_listas(self, request, estetica, corpo) -> str | None:
        """Troca a lista inteira. Erro em string = nada foi gravado (transação)."""
        if "servicos" in corpo and corpo["servicos"] is not None:
            linhas = corpo["servicos"]

            if not isinstance(linhas, list):
                return "Serviços: envie uma lista de itens."

            if len(linhas) > LIMITE_SERVICOS:
                return f"Serviços: use no máximo {LIMITE_SERVICOS} cards."

            estetica.servicos.all().delete()

            for indice, item in enumerate(linhas):
                serie = ServicoSerializer(data={**(item if isinstance(item, dict) else {}), "ordem": indice})

                if not serie.is_valid():
                    return f"Serviço {indice + 1}: {_primeiro_erro(serie)}"

                serie.save(estetica=estetica, ordem=indice)

        if "galeria" in corpo and corpo["galeria"] is not None:
            linhas = corpo["galeria"]

            if not isinstance(linhas, list):
                return "Galeria: envie uma lista de itens."

            if len(linhas) > LIMITE_GALERIA:
                return f"Galeria: use no máximo {LIMITE_GALERIA} pares de fotos."

            estetica.galerias.all().delete()

            for indice, item in enumerate(linhas):
                serie = GaleriaSerializer(data={**(item if isinstance(item, dict) else {}), "ordem": indice})

                if not serie.is_valid():
                    return f"Galeria {indice + 1}: {_primeiro_erro(serie)}"

                serie.save(estetica=estetica, ordem=indice)

        return None


class ServicoViewSet(viewsets.ModelViewSet):
    """CRUD unitário para quem quiser editar um card por vez."""

    serializer_class = ServicoSerializer

    def get_queryset(self):
        return Servico.objects.filter(estetica__user=self.request.user)

    def perform_create(self, serializer):
        estetica = self._estetica()

        if estetica is None:
            raise serializers.ValidationError({"detail": "Salve seus dados antes de adicionar serviços."})

        if estetica.servicos.count() >= LIMITE_SERVICOS:
            raise serializers.ValidationError({"detail": f"Serviços: use no máximo {LIMITE_SERVICOS} cards."})

        serializer.save(estetica=estetica, ordem=estetica.servicos.count())

    def _estetica(self):
        return Estetica.objects.filter(user=self.request.user).first()


class GaleriaViewSet(viewsets.ModelViewSet):
    serializer_class = GaleriaSerializer

    def get_queryset(self):
        return Galeria.objects.filter(estetica__user=self.request.user)

    def perform_create(self, serializer):
        estetica = self._estetica()

        if estetica is None:
            raise serializers.ValidationError({"detail": "Salve seus dados antes de adicionar fotos."})

        if estetica.galerias.count() >= LIMITE_GALERIA:
            raise serializers.ValidationError({"detail": f"Galeria: use no máximo {LIMITE_GALERIA} pares de fotos."})

        serializer.save(estetica=estetica, ordem=estetica.galerias.count())

    def _estetica(self):
        return Estetica.objects.filter(user=self.request.user).first()


class PublicoView(APIView):
    """A página /site/<slug> do cliente. Sem login, sem dados de cobrança."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        estetica = (
            Estetica.objects.filter(slug=slug)
            .prefetch_related("servicos", "galerias")
            .first()
        )

        if estetica is None:
            return _resposta("Página não encontrada.", 404)

        resposta = Response({"ok": True, "data": PublicoSerializer(estetica).data})

        # Cache de conteúdo público. `public` aqui é seguro por uma razão concreta: esta
        # view tem `authentication_classes = []` e não lê cookie nenhum, então não existe
        # resposta que dependa de quem pediu — não há o que vazar entre visitas. O
        # max-age curto (60 s) é o preço de o dono editar o preço de um serviço e a
        # vitrine demorar um minuto para refletir; o s-maxage maior (5 min) é o que
        # interessa, porque é o CDN da Vercel servindo a página de todos os clientes sem
        # chegar nesta função quando ela está fria.
        #
        # Só a resposta 200 ganha o header. O 404 acima continua sem cache de propósito:
        # slug que hoje não existe pode ser cadastrado amanhã, e um "não existe" guardado
        # no CDN por cinco minutos seria um site novo invisível.
        resposta["Cache-Control"] = "public, max-age=60, s-maxage=300"

        return resposta


class PlanosView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "ok": True,
                "planos": [
                    {
                        "slug": plano.slug,
                        "nome": plano.nome,
                        "preco": plano.preco,
                        "valor": plano.valor,
                        "destaque": plano.destaque,
                        "itens": plano.itens,
                    }
                    for plano in PLANOS
                ],
            }
        )


class CheckoutView(APIView):
    """
    Abre o checkout com assinatura no Asaas e devolve o link.

    Ordem de checagem é a do endpoint antigo: sessão, plano, CPF/CNPJ, cliente no
    Asaas, checkout. Cada etapa errada tem mensagem própria, e nenhuma escrita no
    Asaas acontece antes de o cadastro do cliente estar completo.
    """

    def post(self, request):
        plano = plano_por_slug(request.data.get("plano") if isinstance(request.data, dict) else None)

        if plano is None:
            return _resposta("Plano inválido: escolha essencial, profissional ou premium.")

        estetica = Estetica.objects.filter(user=request.user).first()

        if estetica is None:
            return _resposta("Preencha seus dados no painel antes de assinar.", 400)

        if not estetica.cpf_cnpj:
            return _resposta("Antes de assinar, preencha o CPF ou CNPJ no painel (Dados da sua estética).", 400)

        email = request.user.email or request.user.username

        if not email:
            return _resposta("Sua conta precisa de um e-mail para a cobrança.", 400)

        base = _base_do_site(request)

        if not base:
            return _resposta("Falta SITE_URL no ambiente para montar o retorno do checkout.", 500)

        resultado = _garante_cliente_no_asaas(estetica, email)

        if not resultado.ok:
            return _resposta(resultado.erro, 502 if resultado.status == 0 else resultado.status or 502)

        checkout = asaas.criar_checkout_assinatura(
            customer_id=resultado.dados["id"],
            plano=plano,
            success_url=f"{base}/dashboard?pagamento=sucesso",
            cancel_url=f"{base}/dashboard?pagamento=cancelado",
            referencia=f"{estetica.pk}|{plano.slug}",
        )

        if not checkout.ok:
            return _resposta(checkout.erro, checkout.status or 502)

        return Response(
            {"ok": True, "link": checkout.dados["link"], "checkoutId": checkout.dados["id"], "plano": plano.slug}
        )


class AsaasWebhookView(APIView):
    """
    Webhook do Asaas. Sem usuário, sem sessão: a autenticação é o header
    `asaas-access-token` comparado com ASAAS_WEBHOOK_TOKEN.

    A regra de resposta (e por que ela não é "200 para tudo") é a que foi acordada na
    fase do Astro: 401 para token divergente, porque é erro de configuração e precisa
    aparecer; 200 para o que chegou e foi deliberadamente ignorado, porque reenviar
    isso não serve a nada e 15 falhas consecutivas pausam a fila de eventos da conta;
    500 quando a culpa é nossa e o reenvio ajuda.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        esperado = (settings.ASAAS_WEBHOOK_TOKEN or "").strip()

        if not esperado:
            logger.error("[asaas:webhook] Falta ASAAS_WEBHOOK_TOKEN no ambiente.")

            return _resposta("Falta ASAAS_WEBHOOK_TOKEN no ambiente.", 500)

        recebido = request.headers.get("asaas-access-token", "")

        if not recebido or not hmac.compare_digest(recebido, esperado):
            logger.error("[asaas:webhook] Token ausente ou divergente.")

            return _resposta("Token do webhook inválido.", 401)

        try:
            corpo = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"ok": True, "ignorado": "corpo inválido"})

        if not isinstance(corpo, dict):
            return Response({"ok": True, "ignorado": "corpo vazio"})

        evento = corpo.get("event")

        # O campo do evento é `event` (não existe `eventType` no payload do Asaas).
        if evento != "CHECKOUT_PAID":
            return Response({"ok": True, "ignorado": evento or "sem evento"})

        checkout = corpo.get("checkout") if isinstance(corpo.get("checkout"), dict) else {}
        checkout_id = checkout.get("id") if isinstance(checkout.get("id"), str) else ""
        referencia = checkout.get("externalReference") if isinstance(checkout.get("externalReference"), str) else ""

        if not checkout_id or "|" not in referencia:
            logger.error("[asaas:webhook] CHECKOUT_PAID sem checkout.id ou externalReference suficiente.")

            return Response({"ok": True, "ignorado": "payload incompleto"})

        pedaco = referencia.split("|")

        if len(pedaco) != 2:
            return Response({"ok": True, "ignorado": "referência inválida"})

        id_estetica, slug = pedaco

        if not id_estetica.isdigit():
            return Response({"ok": True, "ignorado": "referência inválida"})

        plano = plano_por_slug(slug)

        if plano is None:
            return Response({"ok": True, "ignorado": "plano desconhecido"})

        estetica = Estetica.objects.filter(pk=int(id_estetica)).first()

        # Antes de gastar uma chamada no Asaas: se a referência aponta para uma conta
        # que não existe aqui, não há o que ativar, e reenviar não muda nada.
        if estetica is None:
            return Response({"ok": True, "ignorado": "usuário sem cadastro"})

        lista = asaas.pagamentos_do_checkout(checkout_id)

        if not lista.ok:
            logger.error("[asaas:webhook] não consegui conferir o checkout %s: %s", checkout_id, lista.erro)

            return _resposta("falha ao consultar o Asaas", 500)

        pago = next(
            (
                pagamento
                for pagamento in lista.dados
                if pagamento.get("status") in STATUS_PAGO
                and abs(float(pagamento.get("value", 0)) - plano.valor) < 0.01
            ),
            None,
        )

        if pago is None:
            # O evento chegou e a API ainda não mostra o dinheiro: 500 para o Asaas
            # reenviar, e a próxima entrega ativa o plano.
            logger.error("[asaas:webhook] checkout %s sem pagamento confirmado de R$ %s", checkout_id, plano.valor)

            return _resposta("pagamento ainda não confirmado", 500)

        cliente_do_pagamento = pago.get("customer") if isinstance(pago.get("customer"), str) else ""

        # Defesa: o pagamento precisa pertencer ao cliente que guardamos para este
        # usuário. Se divergir, alguém mexeu na referência — e não é ativando na sorte.
        if estetica.asaas_customer_id and cliente_do_pagamento and estetica.asaas_customer_id != cliente_do_pagamento:
            logger.error("[asaas:webhook] cliente do pagamento não bate com o banco para %s", estetica.pk)

            return _resposta("cliente divergente", 500)

        estetica.plano_ativo = plano.slug
        estetica.asaas_customer_id = estetica.asaas_customer_id or cliente_do_pagamento
        estetica.save(update_fields=["plano_ativo", "asaas_customer_id", "atualizado_em"])

        logger.info("[asaas:webhook] plano %s ativado para %s (pagamento %s)", plano.slug, estetica.pk, pago.get("id"))

        # Reentrega do mesmo evento escreve os mesmos valores: a operação é idempotente.
        return Response({"ok": True, "ativado": plano.slug, "pagamento": pago.get("id")})


def _base_do_site(request) -> str:
    """
    SITE_URL do ambiente quando existir; senão a origem que chamou a API. O backend e
    o painel são domínios diferentes, então a origem da request (a API) nunca serve de
    fallback — quem serve é o header Origin do navegador, que é o endereço do painel.
    """
    bruta = (settings.SITE_URL or "").strip()

    if not bruta:
        bruta = (request.headers.get("origin") or "").strip()

    return bruta.rstrip("/")


def _garante_cliente_no_asaas(estetica: Estetica, email: str) -> asaas.Resultado:
    if estetica.asaas_customer_id:
        return asaas.Resultado.sucesso({"id": estetica.asaas_customer_id})

    nome = estetica.nome_negocio or email.split("@")[0]
    criado = asaas.criar_cliente_asaas(
        nome=nome,
        email=email,
        cpf_cnpj=estetica.cpf_cnpj,
        referencia=str(estetica.pk),
    )

    if not criado.ok:
        # A criação pode ter funcionado do lado do Asaas e a resposta ter se perdido.
        recuperado = asaas.cliente_por_referencia(str(estetica.pk))

        if not recuperado.ok:
            return recuperado

        if recuperado.dados is None:
            return criado

        criado = recuperado

    estetica.asaas_customer_id = criado.dados["id"]
    estetica.save(update_fields=["asaas_customer_id", "atualizado_em"])

    return criado


def _primeiro_erro(serie) -> str:
    """A primeira mensagem legível, na ordem dos campos, como o cliente já vê hoje."""
    for campo, mensagens in serie.errors.items():
        mensagem = mensagens[0] if isinstance(mensagens, list) and mensagens else mensagens

        if isinstance(mensagem, dict):
            mensagem = next(iter(mensagem.values()), ["sem detalhe"])[0]

        if campo == "detail":
            return str(mensagem)

        return str(mensagem)

    return "Dados inválidos."
