"""
Testes da API do Django.

Cobrem as três garantias que o sistema inteiro depende e que não podem ser provadas
por leitura de código:

 1. A resposta de erro é sempre `{ok: false, error}` com o texto que o cliente lê, em
    qualquer caminho — inclusive os erros que o DRF gera sozinho.
 2. Nada de um usuário aparece para outro usuário (painel e CRUD unitário).
 3. O webhook só ativa plano depois de conferir o dinheiro no Asaas — e nada aqui
    toca a conta de produção: toda chamada ao Asaas é simulada com `mock`.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import bcrypt
from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from . import asaas
from .management.commands.importa_supabase import hash_de_senha
from .models import Estetica, Galeria, Servico

# O cabeçalho que autoriza método não-seguro. Sem ele, o cookie de token é lido por
# qualquer <form> de outro site — ver core/authentication.py.
ASSINADO = {"HTTP_X_FATOR_BRILHO": "1"}

URL_REGISTRO = "/api/auth/registro/"
URL_LOGIN = "/api/auth/login/"
URL_LOGOUT = "/api/auth/logout/"
URL_ESTETICA = "/api/estetica/"
URL_SERVICOS = "/api/servicos/"
URL_GALERIA = "/api/galeria/"
URL_CHECKOUT = "/api/checkout/"
URL_PLANOS = "/api/planos/"
URL_WEBHOOK = "/api/webhooks/asaas/"


def corpo(resposta) -> dict:
    return resposta.json()


def erro(resposta) -> str:
    dados = corpo(resposta)
    if dados.get("ok") is not False:
        raise AssertionError(f"esperava ok:false, veio {dados}")

    return dados["error"]


class ComConta(APITestCase):
    """Conta com token já no cookie do client; o login em si é testado à parte."""

    email = "dono@exemplo.com"
    senha = "senha-forte-9"

    def setUp(self):
        super().setUp()

        self.usuario = User.objects.create_user(username=self.email, email=self.email, password=self.senha)
        self.estetica = Estetica.objects.create(user=self.usuario, nome_negocio="Estética do Bruno")
        self.token = Token.objects.create(user=self.usuario)
        self.client.cookies[settings.TOKEN_COOKIE] = self.token.key

    def outra_conta(self, email="vizinha@exemplo.com"):
        usuario = User.objects.create_user(username=email, email=email, password=self.senha)
        estetica = Estetica.objects.create(user=usuario, nome_negocio="Estética Vizinha")

        return usuario, estetica

    def client_outra(self, email="vizinha@exemplo.com"):
        """Um segundo navegador, com o token da segunda conta."""
        from rest_framework.test import APIClient

        usuario, estetica = self.outra_conta(email)
        cliente = APIClient()
        cliente.cookies[settings.TOKEN_COOKIE] = Token.objects.create(user=usuario).key

        return cliente, estetica


# ----------------------------------------------------------------------------------
# Registro / login / logout
# ----------------------------------------------------------------------------------


class AutenticacaoTests(APITestCase):
    def test_registro_cria_usuario_estetica_e_cookie_seguro(self):
        resposta = self.client.post(
            URL_REGISTRO,
            {"email": "Nova@Exemplo.com", "senha": "senha-forte-9", "nome_negocio": "Estética Nova"},
            format="json",
            **ASSINADO,
        )

        self.assertEqual(resposta.status_code, 201, corpo(resposta))
        self.assertTrue(corpo(resposta)["ok"])

        usuario = User.objects.get()

        # O e-mail é gravado em minúsculas: a validação de duplicado compara em
        # minúsculas também, e "entrar com a mesma conta" não pode depender do Shift.
        self.assertEqual(usuario.username, "nova@exemplo.com")
        self.assertEqual(usuario.password[:7], "pbkdf2_")  # nada de senha em texto puro

        estetica = Estetica.objects.get()
        self.assertEqual(estetica.user, usuario)
        self.assertEqual(estetica.nome_negocio, "Estética Nova")
        self.assertIsNone(estetica.slug)

        cookie = resposta.cookies[settings.TOKEN_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "None")  # o painel é outro site
        self.assertEqual(cookie["path"], "/")
        self.assertEqual(corpo(resposta)["id"], estetica.pk)

    def test_registro_repetido_recusa_com_frase_em_portugues(self):
        self.client.post(URL_REGISTRO, {"email": "a@x.com", "senha": "senha-forte-9"}, format="json", **ASSINADO)
        resposta = self.client.post(URL_REGISTRO, {"email": "A@X.com", "senha": "outra-senha-9"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Já existe uma conta com esse e-mail.")
        self.assertEqual(User.objects.count(), 1)

    def test_registro_senha_curta_e_recusada(self):
        resposta = self.client.post(URL_REGISTRO, {"email": "a@x.com", "senha": "123"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "A senha precisa de pelo menos 8 caracteres.")

    def test_login_errado_devolve_a_mesma_mensagem_para_conta_e_senha(self):
        User.objects.create_user(username="a@x.com", email="a@x.com", password="senha-forte-9")

        senha_errada = self.client.post(URL_LOGIN, {"login": "a@x.com", "senha": "errada-de-verdade"}, format="json", **ASSINADO)
        conta_inexistente = self.client.post(URL_LOGIN, {"login": "ninguem@x.com", "senha": "errada-de-verdade"}, format="json", **ASSINADO)

        for resposta in (senha_errada, conta_inexistente):
            self.assertEqual(resposta.status_code, 401)
            self.assertEqual(erro(resposta), "E-mail ou senha incorretos.")

    def test_login_ok_autoriza_get_sem_cabechalho_e_put_com(self):
        User.objects.create_user(username="a@x.com", email="a@x.com", password="senha-forte-9")

        login = self.client.post(URL_LOGIN, {"login": "a@x.com", "senha": "senha-forte-9"}, format="json", **ASSINADO)
        self.assertEqual(login.status_code, 200, corpo(login))
        self.assertIn(settings.TOKEN_COOKIE, login.cookies)

        # GET é seguro: o cookie basta.
        self.assertEqual(self.client.get(URL_ESTETICA).status_code, 200)

        # PUT sem o cabeçalho é a cara de um <form> cross-site: barrado.
        sem_cabecalho = self.client.put(URL_ESTETICA, {"nome_negocio": "X"}, format="json")
        self.assertEqual(sem_cabecalho.status_code, 401, corpo(sem_cabecalho))

        # PUT com o cabeçalho é a nossa aplicação.
        com_cabecalho = self.client.put(URL_ESTETICA, {"nome_negocio": "X"}, format="json", **ASSINADO)
        self.assertEqual(com_cabecalho.status_code, 200, corpo(com_cabecalho))

    def test_sem_cookie_nem_header_devolve_401_no_formato_do_painel(self):
        from rest_framework.test import APIClient

        resposta = APIClient().get(URL_ESTETICA)

        self.assertEqual(resposta.status_code, 401)
        self.assertIs(False, corpo(resposta)["ok"])
        self.assertEqual(erro(resposta), "Sessão expirada. Entre novamente para continuar.")

    def test_header_authorization_funciona_para_chamada_de_servidor(self):
        User.objects.create_user(username="a@x.com", email="a@x.com", password="senha-forte-9")
        token = Token.objects.create(user=User.objects.get())

        from rest_framework.test import APIClient

        cliente = APIClient()
        cliente.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        resposta = cliente.put(URL_ESTETICA, {"nome_negocio": "Pelo header"}, format="json", **ASSINADO)
        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        self.assertEqual(corpo(resposta)["data"]["nome_negocio"], "Pelo header")

    def test_logout_de_conta_nao_autenticada_e_401(self):
        from rest_framework.test import APIClient

        resposta = APIClient().post(URL_LOGOUT, {}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 401)
        self.assertIs(False, corpo(resposta)["ok"])


class LogoutTests(ComConta):
    def test_logout_apaga_token_e_limpa_cookie(self):
        resposta = self.client.post(URL_LOGOUT, {}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        self.assertFalse(Token.objects.filter(user=self.usuario).exists())
        self.assertEqual(resposta.cookies[settings.TOKEN_COOKIE].value, "")

        # Reenviar o cookie antigo não reautentica: a linha sumiu do banco.
        self.client.cookies[settings.TOKEN_COOKIE] = self.token.key
        self.assertEqual(self.client.get(URL_ESTETICA).status_code, 401)


# ----------------------------------------------------------------------------------
# Painel: GET/PUT /api/estetica/
# ----------------------------------------------------------------------------------


class PainelTests(ComConta):
    def test_get_devolve_estetica_listas_e_null_quando_nao_publicado(self):
        dados = corpo(self.client.get(URL_ESTETICA))

        self.assertTrue(dados["ok"])
        self.assertEqual(dados["data"]["nome_negocio"], "Estética do Bruno")
        self.assertIsNone(dados["data"]["slug"])
        self.assertEqual(dados["servicos"], [])
        self.assertEqual(dados["galeria"], [])
        # O layout do painel mostra o e-mail da conta e a página é SSR: o e-mail vem
        # no corpo, em vez de um segundo endpoint só para saber quem está logado.
        self.assertEqual(dados["email"], "dono@exemplo.com")
        # O painel não precisa de cpf/cobrança para renderizar, mas precisa poder
        # mostrar o que já existe; o que NÃO pode vazar é a página pública.
        self.assertEqual(dados["data"]["plano_ativo"], "")

    def test_get_e_put_tem_a_mesma_shape(self):
        """
        O painel espelha a resposta do PUT sem segunda chamada, então os dois corpos
        precisam ter as mesmas chaves. Esta é a prova negativa: se o PUT deixar de
        devolver `email` (ou `data`), a comparação de chaves quebra antes de qualquer
        tela mostrar um dado a menos.
        """
        obtido = sorted(corpo(self.client.get(URL_ESTETICA)))
        gravado = sorted(
            corpo(self.client.put(URL_ESTETICA, {"nome_negocio": "Estética do Bruno"}, format="json", **ASSINADO))
        )

        self.assertEqual(obtido, ["data", "email", "galeria", "ok", "servicos"])
        self.assertEqual(obtido, gravado)

    def test_put_grava_normalizado(self):
        resposta = self.client.put(
            URL_ESTETICA,
            {
                "nome_negocio": "  Estética do Bruno  ",
                "whatsapp": "5511999998888",
                "instagram": "@brunopolish",
                "endereco": "Rua X, 100",
                "cor_principal": "#ABC",
                "slug": "  Estética do Bruno ",
            },
            format="json",
            **ASSINADO,
        )

        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        dados = corpo(resposta)["data"]
        self.assertEqual(dados["nome_negocio"], "Estética do Bruno")
        self.assertEqual(dados["instagram"], "brunopolish")  # sem @
        self.assertEqual(dados["cor_principal"], "#abc")  # minúsculas
        self.assertEqual(dados["slug"], "estetica-do-bruno")  # acento e espaço viram link

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.slug, "estetica-do-bruno")
        self.assertTrue(self.estetica.publicada)

    def test_put_cor_invalida(self):
        resposta = self.client.put(URL_ESTETICA, {"cor_principal": "azul"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Cor principal inválida: use o formato #RRGGBB.")

    def test_put_whatsapp_com_letra(self):
        resposta = self.client.put(URL_ESTETICA, {"whatsapp": "discar 9999"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "WhatsApp: use apenas números, com opcional + no início.")

    def test_put_cpf_sem_digitos_suficientes(self):
        resposta = self.client.put(URL_ESTETICA, {"cpf_cnpj": "123.456"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("11 dígitos (CPF) ou 14 dígitos (CNPJ)", erro(resposta))

    def test_put_slug_linkado_de_menos(self):
        resposta = self.client.put(URL_ESTETICA, {"slug": "ab"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("pelo menos 3 caracteres", erro(resposta))

    def test_slug_vazio_convive_entre_contas(self):
        """O bug que este teste existe para nunca voltar: '' único colide na 2ª conta."""
        primeiro = self.client.put(URL_ESTETICA, {"slug": ""}, format="json", **ASSINADO)
        self.assertEqual(primeiro.status_code, 200, corpo(primeiro))

        cliente, _ = self.client_outra()
        segundo = cliente.put(URL_ESTETICA, {"slug": ""}, format="json", **ASSINADO)
        self.assertEqual(segundo.status_code, 200, corpo(segundo))

        self.assertEqual(Estetica.objects.filter(slug__isnull=True).count(), 2)

    def test_slug_repetido_devolve_a_frase_do_bruno(self):
        _, vizinha = self.outra_conta()
        vizinha.slug = "estetica-bruno"
        vizinha.save(update_fields=["slug"])

        resposta = self.client.put(URL_ESTETICA, {"slug": "Estética Bruno"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(
            erro(resposta),
            "Esse link já pertence a outra estética. Escolha outro e salve novamente.",
        )

    def test_put_sem_lista_nao_apaga_lista(self):
        Servico.objects.create(estetica=self.estetica, nome="Espelhamento", preco="R$ 880")

        resposta = self.client.put(URL_ESTETICA, {"nome_negocio": "Outro Nome"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        self.assertEqual(Servico.objects.count(), 1)
        self.assertEqual(len(corpo(resposta)["servicos"]), 1)

    def test_put_lista_vazia_esvazia_de_proposito(self):
        Servico.objects.create(estetica=self.estetica, nome="Espelhamento")
        Galeria.objects.create(estetica=self.estetica, antes_url="/hero.jpg")

        resposta = self.client.put(URL_ESTETICA, {"servicos": [], "galeria": []}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        self.assertEqual(Servico.objects.count(), 0)
        self.assertEqual(Galeria.objects.count(), 0)

    def test_put_com_servico_invalido_nao_destroi_os_antigos(self):
        """Transação: ou entra a lista nova inteira, ou as linhas velhas continuam lá."""
        Servico.objects.create(estetica=self.estetica, nome="Polimento", ordem=0)
        Servico.objects.create(estetica=self.estetica, nome="Higienização", ordem=1)

        resposta = self.client.put(
            URL_ESTETICA,
            {"servicos": [{"nome": "Espelhamento"}, {"nome": "Vitrificação"}, {"nome": "   "}]},
            format="json",
            **ASSINADO,
        )

        self.assertEqual(resposta.status_code, 400, corpo(resposta))
        self.assertEqual(erro(resposta), "Serviço 3: informe nome do serviço.")
        self.assertEqual([s.nome for s in Servico.objects.order_by("ordem")], ["Polimento", "Higienização"])

    def test_put_mais_de_doze_servicos_e_recusado(self):
        lista = [{"nome": f"Serviço {i}"} for i in range(13)]
        resposta = self.client.put(URL_ESTETICA, {"servicos": lista}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Serviços: use no máximo 12 cards.")

    def test_put_mais_de_doze_fotos_e_recusado(self):
        lista = [{"antes_url": f"/a{i}.jpg"} for i in range(13)]
        resposta = self.client.put(URL_ESTETICA, {"galeria": lista}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Galeria: use no máximo 12 pares de fotos.")

    def test_put_galeria_sem_url_e_recusada(self):
        resposta = self.client.put(URL_ESTETICA, {"galeria": [{"legenda": "sem foto"}]}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Galeria 1: informe a URL da foto antes ou da depois.")

    def test_put_galeria_javascript_e_recusada(self):
        resposta = self.client.put(
            URL_ESTETICA,
            {"galeria": [{"antes_url": "javascript:alert(1)"}]},
            format="json",
            **ASSINADO,
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("URL do antes inválida", erro(resposta))

    def test_put_galeria_ordem_vem_da_posicao(self):
        resposta = self.client.put(
            URL_ESTETICA,
            {"galeria": [{"antes_url": "/b.jpg"}, {"antes_url": "/a.jpg", "depois_url": "/z.jpg"}]},
            format="json",
            **ASSINADO,
        )

        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        linhas = corpo(resposta)["galeria"]
        self.assertEqual([l["ordem"] for l in linhas], [0, 1])
        self.assertEqual(linhas[1]["depois_url"], "/z.jpg")

    def test_put_sem_nome_no_item_devolve_a_frase_nossa(self):
        """Ausente e vazio dão a mesma frase; não o "Este campo é obrigatório." do DRF."""
        resposta = self.client.put(URL_ESTETICA, {"servicos": [{}]}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400, corpo(resposta))
        self.assertEqual(erro(resposta), "Serviço 1: informe nome do serviço.")

    def test_put_instagram_grande_demais(self):
        resposta = self.client.put(URL_ESTETICA, {"instagram": "a" * 65}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Instagram: use no máximo 64 caracteres.")

    def test_put_lista_servico_com_descricao_grande(self):
        resposta = self.client.put(
            URL_ESTETICA,
            {"servicos": [{"nome": "Espelhamento", "descricao": "x" * 241}]},
            format="json",
            **ASSINADO,
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Serviço 1: Descrição tem mais de 240 caracteres.")

    def test_put_servicos_nao_aceita_lista_solta(self):
        resposta = self.client.put(URL_ESTETICA, {"servicos": {"nome": "um"}}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Serviços: envie uma lista de itens.")


# ----------------------------------------------------------------------------------
# CRUD unitário e isolamento entre contas
# ----------------------------------------------------------------------------------


class CrudTests(ComConta):
    def test_post_cria_servico_na_conta_certa(self):
        resposta = self.client.post(URL_SERVICOS, {"nome": "Espelhamento", "preco": "R$ 880"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 201, corpo(resposta))
        servico = Servico.objects.get()
        self.assertEqual(servico.estetica, self.estetica)
        self.assertEqual(servico.ordem, 0)

    def test_post_nao_tem_estetica_pedest_e_salvar_dados(self):
        from rest_framework.test import APIClient

        usuario = User.objects.create_user(username="so-login@x.com", email="so-login@x.com", password="senha-forte-9")
        cliente = APIClient()
        cliente.cookies[settings.TOKEN_COOKIE] = Token.objects.create(user=usuario).key

        resposta = cliente.post(URL_SERVICOS, {"nome": "Espelhamento"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400, corpo(resposta))
        self.assertEqual(erro(resposta), "Salve seus dados antes de adicionar serviços.")

    def test_patch_parcial_muda_so_o_preco(self):
        """O `self.partial` de ServicoSerializer: sem ele, PATCH sem nome viraria erro."""
        servico = Servico.objects.create(estetica=self.estetica, nome="Espelhamento", preco="R$ 880")

        resposta = self.client.patch(f"{URL_SERVICOS}{servico.pk}/", {"preco": "R$ 950"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 200, corpo(resposta))
        servico.refresh_from_db()
        self.assertEqual(servico.preco, "R$ 950")
        self.assertEqual(servico.nome, "Espelhamento")

    def test_limite_de_doze_no_viewset(self):
        Servico.objects.bulk_create([Servico(estetica=self.estetica, nome=f"S{i}", ordem=i) for i in range(12)])

        resposta = self.client.post(URL_SERVICOS, {"nome": "Décimo terceiro"}, format="json", **ASSINADO)

        # Este 400 nasce dentro de perform_create, ou seja: passa pelo exception
        # handler. Se a resposta sair em {detail}, o contrato do painel quebrou.
        self.assertEqual(resposta.status_code, 400, corpo(resposta))
        self.assertEqual(erro(resposta), "Serviços: use no máximo 12 cards.")

    def test_vizinha_nao_ve_nao_edita_nao_apaga(self):
        servico = Servico.objects.create(estetica=self.estetica, nome="Espelhamento")
        foto = Galeria.objects.create(estetica=self.estetica, antes_url="/hero.jpg")
        cliente, _ = self.client_outra()

        self.assertEqual(cliente.get(URL_SERVICOS).json(), [])
        self.assertEqual(cliente.get(URL_GALERIA).json(), [])
        self.assertEqual(cliente.get(f"{URL_SERVICOS}{servico.pk}/").status_code, 404)
        self.assertEqual(erro(cliente.get(f"{URL_SERVICOS}{servico.pk}/")), "Não encontrado.")

        patch = cliente.patch(f"{URL_SERVICOS}{servico.pk}/", {"nome": "meu"}, format="json", **ASSINADO)
        self.assertEqual(patch.status_code, 404, corpo(patch))

        delete = cliente.delete(f"{URL_GALERIA}{foto.pk}/", **ASSINADO)
        self.assertEqual(delete.status_code, 404)

        servico.refresh_from_db()
        self.assertEqual(servico.nome, "Espelhamento")
        self.assertEqual(Galeria.objects.count(), 1)

    def test_painel_de_vizinha_mostra_sua_propria_estetica(self):
        cliente, vizinha = self.client_outra()

        dados = corpo(cliente.get(URL_ESTETICA))
        self.assertEqual(dados["data"]["id"], vizinha.pk)
        self.assertEqual(dados["data"]["nome_negocio"], "Estética Vizinha")
        self.assertEqual(dados["servicos"], [])


# ----------------------------------------------------------------------------------
# Página pública
# ----------------------------------------------------------------------------------


class PublicoTests(ComConta):
    def setUp(self):
        super().setUp()

        self.estetica.slug = "estetica-do-bruno"
        self.estetica.whatsapp = "5511999998888"
        self.estetica.instagram = "brunopolish"
        self.estetica.cor_principal = "#075e54"
        self.estetica.cpf_cnpj = "12345678901"
        self.estetica.asaas_customer_id = "cli_secreto"
        self.estetica.plano_ativo = "profissional"
        self.estetica.save()

        Servico.objects.create(estetica=self.estetica, nome="Espelhamento", preco="R$ 880", ordem=0)
        Galeria.objects.create(estetica=self.estetica, antes_url="/hero.jpg", depois_url="/hero2.jpg", ordem=0)

    def test_visita_sem_login_ve_a_pagina(self):
        from rest_framework.test import APIClient

        resposta = APIClient().get("/api/publico/estetica-do-bruno/")

        self.assertEqual(resposta.status_code, 200, corpo(resposta))

        dados = corpo(resposta)["data"]
        self.assertEqual(dados["nome_negocio"], "Estética do Bruno")
        self.assertEqual(dados["servicos"][0]["preco"], "R$ 880")
        self.assertEqual(dados["galerias"][0]["antes_url"], "/hero.jpg")

    def test_pagina_publica_nao_vaza_nada_de_cobranca(self):
        from rest_framework.test import APIClient

        texto = json.dumps(corpo(APIClient().get("/api/publico/estetica-do-bruno/")))

        for vedado in ("cpf_cnpj", "asaas_customer_id", "plano_ativo", "12345678901", "cli_secreto", "dono@exemplo.com", "profissional"):
            self.assertNotIn(vedado, texto)

    def test_slug_inexistente_e_404_em_formato_de_erro(self):
        from rest_framework.test import APIClient

        resposta = APIClient().get("/api/publico/nao-existe-aqui/")

        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(erro(resposta), "Página não encontrada.")

    def test_pagina_publica_vem_com_cache_de_cdn(self):
        from rest_framework.test import APIClient

        resposta = APIClient().get("/api/publico/estetica-do-bruno/")

        # O header é o que permite ao CDN da Vercel servir a vitrine do cliente sem
        # invocar esta função de novo — sem ele, cada visita é um cold start Python e
        # uma query no Postgres. É medido aqui e não "confiado no código" porque o
        # frontend lê a resposta pela reescrita do vercel.json, e quem decide o cache é
        # o cabeçalho, não a intenção escrita no comentário.
        self.assertEqual(resposta["Cache-Control"], "public, max-age=60, s-maxage=300")

    def test_404_publico_nao_ganha_cache(self):
        from rest_framework.test import APIClient

        resposta = APIClient().get("/api/publico/nao-existe-aqui/")

        # "não existe" guardado no CDN por cinco minutos deixaria um site recém-criado
        # invisível, então o cache é só da resposta 200.
        self.assertFalse(resposta.has_header("Cache-Control"))


class PlanosTests(APITestCase):
    def test_tres_planos_com_o_preco_da_vitrine(self):
        dados = corpo(self.client.get(URL_PLANOS))

        self.assertTrue(dados["ok"])
        self.assertEqual([p["slug"] for p in dados["planos"]], ["essencial", "profissional", "premium"])
        self.assertEqual([p["valor"] for p in dados["planos"]], [97, 147, 297])
        self.assertEqual([p["preco"] for p in dados["planos"]], ["R$ 97", "R$ 147", "R$ 297"])
        self.assertTrue(dados["planos"][1]["destaque"])


# ----------------------------------------------------------------------------------
# Checkout
# ----------------------------------------------------------------------------------


@override_settings(SITE_URL="https://fator-brilho.vercel.app", ASAAS_API_KEY="$aact_teste_local")
class CheckoutTests(ComConta):
    def preenche_cobranca(self):
        resposta = self.client.put(
            URL_ESTETICA,
            {"nome_negocio": "Estética do Bruno", "cpf_cnpj": "12345678901"},
            format="json",
            **ASSINADO,
        )
        self.assertEqual(resposta.status_code, 200, corpo(resposta))

    def test_plano_fora_do_cardapio_e_recusado(self):
        resposta = self.client.post(URL_CHECKOUT, {"plano": "gold"}, format="json", **ASSINADO)

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(erro(resposta), "Plano inválido: escolha essencial, profissional ou premium.")

    def test_sem_cpf_nao_se_mexe_no_asaas(self):
        with mock.patch("core.asaas.criar_cliente_asaas") as criar:
            resposta = self.client.post(URL_CHECKOUT, {"plano": "profissional"}, format="json", **ASSINADO)

            self.assertEqual(resposta.status_code, 400)
            self.assertIn("CPF ou CNPJ", erro(resposta))
            criar.assert_not_called()

    def test_checkout_ok_devolve_link_e_grava_cliente(self):
        self.preenche_cobranca()

        with (
            mock.patch("core.asaas.criar_cliente_asaas", return_value=asaas.Resultado.sucesso({"id": "cli_novo"})) as criar,
            mock.patch(
                "core.asaas.criar_checkout_assinatura",
                return_value=asaas.Resultado.sucesso({"id": "cs_abc123", "link": "https://checkout.asaas.com/cs_abc123"}),
            ) as checkout,
        ):
            resposta = self.client.post(URL_CHECKOUT, {"plano": "profissional"}, format="json", **ASSINADO)

            self.assertEqual(resposta.status_code, 200, corpo(resposta))
            dados = corpo(resposta)
            self.assertEqual(dados["link"], "https://checkout.asaas.com/cs_abc123")
            self.assertEqual(dados["plano"], "profissional")

            self.estetica.refresh_from_db()
            self.assertEqual(self.estetica.asaas_customer_id, "cli_novo")

            criar.assert_called_once()
            parametros = checkout.call_args.kwargs
            self.assertEqual(parametros["customer_id"], "cli_novo")
            self.assertEqual(parametros["referencia"], f"{self.estetica.pk}|profissional")
            self.assertEqual(parametros["success_url"], "https://fator-brilho.vercel.app/dashboard?pagamento=sucesso")
            self.assertEqual(parametros["plano"].valor, 147)

    def test_cliente_ja_gravado_nao_cria_de_novo(self):
        self.preenche_cobranca()
        self.estetica.asaas_customer_id = "cli_antigo"
        self.estetica.save(update_fields=["asaas_customer_id"])

        with (
            mock.patch("core.asaas.criar_cliente_asaas") as criar,
            mock.patch(
                "core.asaas.criar_checkout_assinatura",
                return_value=asaas.Resultado.sucesso({"id": "cs_abc123", "link": "https://checkout.asaas.com/x"}),
            ),
        ):
            resposta = self.client.post(URL_CHECKOUT, {"plano": "essencial"}, format="json", **ASSINADO)

            self.assertEqual(resposta.status_code, 200, corpo(resposta))
            criar.assert_not_called()

    def test_asaas_recusa_cliente_e_a_resposta_vira_erro_legivel(self):
        self.preenche_cobranca()

        with (
            mock.patch("core.asaas.criar_cliente_asaas", return_value=asaas.Resultado.falha(400, "CPF/CNPJ inválido.")),
            mock.patch("core.asaas.cliente_por_referencia", return_value=asaas.Resultado.sucesso(None)),
            mock.patch("core.asaas.criar_checkout_assinatura") as checkout,
        ):
            resposta = self.client.post(URL_CHECKOUT, {"plano": "profissional"}, format="json", **ASSINADO)

            self.assertEqual(resposta.status_code, 400, corpo(resposta))
            self.assertEqual(erro(resposta), "CPF/CNPJ inválido.")
            checkout.assert_not_called()

    def test_cliente_criado_no_asaas_mas_resposta_perdida_e_recuperado(self):
        """Idempotência: o POST falhou, mas o cliente existe lá — não se cria outro."""
        self.preenche_cobranca()

        with (
            mock.patch("core.asaas.criar_cliente_asaas", return_value=asaas.Resultado.falha(0, "timeout")),
            mock.patch("core.asaas.cliente_por_referencia", return_value=asaas.Resultado.sucesso({"id": "cli_ja_existe"})),
            mock.patch(
                "core.asaas.criar_checkout_assinatura",
                return_value=asaas.Resultado.sucesso({"id": "cs_1", "link": "https://checkout.asaas.com/cs_1"}),
            ),
        ):
            resposta = self.client.post(URL_CHECKOUT, {"plano": "premium"}, format="json", **ASSINADO)

            self.assertEqual(resposta.status_code, 200, corpo(resposta))

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.asaas_customer_id, "cli_ja_existe")

    def test_sem_asaas_nao_se_conhece_o_valor(self):
        """Resultado falha(0) = nem chegamos no Asaas: vira 502, nunca 200."""
        self.preenche_cobranca()

        with (
            mock.patch("core.asaas.criar_cliente_asaas", return_value=asaas.Resultado.falha(0, "sem resposta em 20s")),
            mock.patch("core.asaas.cliente_por_referencia", return_value=asaas.Resultado.falha(0, "sem resposta em 20s")),
        ):
            resposta = self.client.post(URL_CHECKOUT, {"plano": "profissional"}, format="json", **ASSINADO)

            self.assertEqual(resposta.status_code, 502, corpo(resposta))
            self.assertEqual(erro(resposta), "sem resposta em 20s")


# ----------------------------------------------------------------------------------
# Webhook do Asaas
# ----------------------------------------------------------------------------------


@override_settings(ASAAS_WEBHOOK_TOKEN="token-de-teste")
class WebhookTests(ComConta):
    def setUp(self):
        super().setUp()

        self.estetica.slug = "estetica-do-bruno"
        self.estetica.cpf_cnpj = "12345678901"
        self.estetica.save()

    def chama(self, payload: dict, token="token-de-teste"):
        return self.client.post(
            URL_WEBHOOK,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ASAAS_ACCESS_TOKEN=token,
        )

    def pago(self, valor=147.0, status="CONFIRMED", customer="cli_x"):
        return asaas.Resultado.sucesso([{"id": "pay_1", "status": status, "value": valor, "customer": customer}])

    def test_token_ausente_ou_divergente_e_401(self):
        divergente = self.chama({"event": "CHECKOUT_PAID"}, token="senha-de-outro")
        ausente = self.client.post(URL_WEBHOOK, data=json.dumps({"event": "CHECKOUT_PAID"}), content_type="application/json")

        for resposta in (divergente, ausente):
            self.assertEqual(resposta.status_code, 401, corpo(resposta))
            self.assertEqual(erro(resposta), "Token do webhook inválido.")

    def test_sem_token_configurado_e_500_para_nao_ativar_no_escuro(self):
        with override_settings(ASAAS_WEBHOOK_TOKEN=""):
            resposta = self.chama({"event": "CHECKOUT_PAID"})

            self.assertEqual(resposta.status_code, 500)
            self.assertIn("ASAAS_WEBHOOK_TOKEN", erro(resposta))

    def test_evento_que_nos_nao_tratamos_e_ignorado_com_200(self):
        """Reenviar SUBSCRIPTION_PAID não serve a nada; 15 falhas pausam a fila da conta."""
        for evento in ("SUBSCRIPTION_PAID", "PAYMENT_CONFIRMED"):
            resposta = self.chama({"event": evento})

            self.assertEqual(resposta.status_code, 200, corpo(resposta))
            self.assertEqual(corpo(resposta)["ignorado"], evento)

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.plano_ativo, "")

    def test_payload_incompleto_e_ignorado(self):
        casos = [
            {"event": "CHECKOUT_PAID", "checkout": {"id": "", "externalReference": f"{self.estetica.pk}|profissional"}},
            {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": "sem-barra"}},
        ]

        for payload in casos:
            resposta = self.chama(payload)
            self.assertEqual(resposta.status_code, 200, corpo(resposta))
            self.assertEqual(corpo(resposta)["ignorado"], "payload incompleto")

    def test_referencia_adulterada_e_ignorada(self):
        """Nenhuma dessas chega ao Asaas: a checagem local vem antes da chamada."""
        casos = {
            "999|profissional": "usuário sem cadastro",
            "abc|profissional": "referência inválida",
            "1|gold": "plano desconhecido",
            "1|profissional|extra": "referência inválida",
        }

        for referencia, esperado in casos.items():
            with mock.patch("core.asaas.pagamentos_do_checkout") as pagamentos:
                resposta = self.chama({"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": referencia}})

                self.assertEqual(resposta.status_code, 200, corpo(resposta))
                self.assertEqual(corpo(resposta)["ignorado"], esperado)
                pagamentos.assert_not_called()

    def test_referencia_aponta_para_conta_inexistente(self):
        with mock.patch("core.asaas.pagamentos_do_checkout") as pagamentos:
            resposta = self.chama(
                {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": "4242|profissional"}}
            )

            self.assertEqual(resposta.status_code, 200, corpo(resposta))
            self.assertEqual(corpo(resposta)["ignorado"], "usuário sem cadastro")
            pagamentos.assert_not_called()

    def test_evento_antes_do_dinheiro_aparecer_e_500_para_reenvio(self):
        with mock.patch("core.asaas.pagamentos_do_checkout", return_value=asaas.Resultado.sucesso([])):
            resposta = self.chama(
                {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|profissional"}}
            )

            self.assertEqual(resposta.status_code, 500, corpo(resposta))
            self.assertEqual(erro(resposta), "pagamento ainda não confirmado")

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.plano_ativo, "")

    def test_consulta_ao_asaas_falhou_e_500(self):
        with mock.patch("core.asaas.pagamentos_do_checkout", return_value=asaas.Resultado.falha(0, "sem resposta")):
            resposta = self.chama(
                {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|profissional"}}
            )

            self.assertEqual(resposta.status_code, 500, corpo(resposta))
            self.assertEqual(erro(resposta), "falha ao consultar o Asaas")

    def test_valor_diferente_do_plano_nao_ativa(self):
        """R$ 97 pago não pode virar plano Profissional por causa de um id trocado."""
        with mock.patch("core.asaas.pagamentos_do_checkout", return_value=self.pago(valor=97.0)):
            resposta = self.chama(
                {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|profissional"}}
            )

            self.assertEqual(resposta.status_code, 500, corpo(resposta))

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.plano_ativo, "")

    def test_pagamento_confirmado_ativa_o_plano(self):
        for status_pago in ("CONFIRMED", "RECEIVED"):
            self.estetica.plano_ativo = ""
            self.estetica.save(update_fields=["plano_ativo"])

            with mock.patch("core.asaas.pagamentos_do_checkout", return_value=self.pago(status=status_pago)):
                resposta = self.chama(
                    {
                        "event": "CHECKOUT_PAID",
                        "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|profissional"},
                    }
                )

                self.assertEqual(resposta.status_code, 200, corpo(resposta))
                self.assertEqual(corpo(resposta)["ativado"], "profissional")

            self.estetica.refresh_from_db()
            self.assertEqual(self.estetica.plano_ativo, "profissional")
            self.assertEqual(self.estetica.asaas_customer_id, "cli_x")

    def test_pagamento_pendente_nao_ativa(self):
        with mock.patch("core.asaas.pagamentos_do_checkout", return_value=self.pago(status="PENDING")):
            resposta = self.chama(
                {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|premium"}}
            )

            self.assertEqual(resposta.status_code, 500, corpo(resposta))

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.plano_ativo, "")

    def test_cliente_do_pagamento_divergente_do_banco_e_500(self):
        self.estetica.asaas_customer_id = "cli_dono_verdadeiro"
        self.estetica.save(update_fields=["asaas_customer_id"])

        with mock.patch("core.asaas.pagamentos_do_checkout", return_value=self.pago(customer="cli_de_outro")):
            resposta = self.chama(
                {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|profissional"}}
            )

            self.assertEqual(resposta.status_code, 500, corpo(resposta))
            self.assertEqual(erro(resposta), "cliente divergente")

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.plano_ativo, "")

    def test_reentrega_do_mesmo_evento_nao_muda_nada(self):
        payload = {"event": "CHECKOUT_PAID", "checkout": {"id": "cs_abc123", "externalReference": f"{self.estetica.pk}|essencial"}}

        with mock.patch("core.asaas.pagamentos_do_checkout", return_value=asaas.Resultado.sucesso(
            [{"id": "pay_1", "status": "CONFIRMED", "value": 97.0, "customer": "cli_x"}]
        )):
            primeira = self.chama(payload)
            segunda = self.chama(payload)

            self.assertEqual(primeira.status_code, 200, corpo(primeira))
            self.assertEqual(segunda.status_code, 200, corpo(segunda))
            self.assertEqual(corpo(segunda)["pagamento"], corpo(primeira)["pagamento"])

        self.estetica.refresh_from_db()
        self.assertEqual(self.estetica.plano_ativo, "essencial")

    def test_corpo_que_nao_e_json_util_e_ignorado_com_200(self):
        bruto = self.client.post(
            URL_WEBHOOK,
            data=b"<!DOCTYPE html>",
            content_type="application/json",
            HTTP_ASAAS_ACCESS_TOKEN="token-de-teste",
        )

        self.assertEqual(bruto.status_code, 200, corpo(bruto))
        self.assertIn(corpo(bruto)["ignorado"], ("corpo inválido", "corpo vazio"))


# ----------------------------------------------------------------------------------
# Importação do dump do Supabase
# ----------------------------------------------------------------------------------


def registro_dump(**campos):
    """Uma linha de `public.estetica` no formato que scripts/exporta_supabase.py escreve."""
    base = {
        "id_supabase": "11111111-1111-1111-1111-111111111111",
        "nome_negocio": "Estética Real",
        "whatsapp": "5511999998888",
        "instagram": "esteticareal",
        "endereco": "Rua do Brilho, 10",
        "cor_principal": "#075E54",
        "cpf_cnpj": "12345678901",
        "asaas_customer_id": "cli_certo",
        "plano_ativo": "profissional",
        "slug_estetica": "estetica-real",
        "created_at": "2025-03-04T10:00:00+00:00",
        "servicos": [{"id": "s1", "nome": "Polimento", "preco": "R$ 300", "ordem": 1}],
        "galeria": [{"id": "g1", "antes_url": "/antes.jpg", "depois_url": "/depois.jpg", "legenda": "Farol", "ordem": 1}],
    }

    return {**base, **campos}


class ImportacaoSupabaseTests(TestCase):
    """
    O import é a única peça do projeto que escreve dados reais de cliente. Os testes
    abaixo não cobrem só "importa certo": cobram principalmente "recusa antes de
    destruir", que é o que separa uma migration de dados de um `UPDATE` no escuro.
    """

    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)

    def roda(self, dump: dict, **opcoes) -> str:
        """Roda o comando com a saída capturada: o relatório é parte do que testamos."""
        caminho = Path(self.pasta.name) / "supabase.json"
        caminho.write_text(json.dumps(dump), encoding="utf-8")
        saida = io.StringIO()
        call_command("importa_supabase", arquivo=str(caminho), stdout=saida, **opcoes)

        return saida.getvalue()

    def hash_bcrypt(self, senha="senha-forte-9") -> str:
        """O `$2b$...` cru, do jeito que o Supabase guardava — sem o prefixo do Django."""
        return bcrypt.hashpw(senha.encode(), bcrypt.gensalt(rounds=4)).decode()

    # -- conversão do hash ---------------------------------------------------------

    def test_bcrypt_cru_ganha_prefixo_e_a_mesma_senha_loga(self):
        bruto = self.hash_bcrypt()

        self.assertFalse(bruto.startswith("bcrypt$"), "o dump cru não traz o prefixo do Django")

        convertido = hash_de_senha(bruto)

        self.assertEqual(convertido, f"bcrypt${bruto}")

        # Medido: no hash cru o Django lê o algoritmo antes do primeiro `$`, que é
        # string vazia, e devolve False (identify_hasher levanta ValueError). Com
        # `bcrypt$` na frente a mesma senha verifica — é isto que evita que cliente
        # antigo precise redefinir a senha depois da migração.
        self.assertTrue(check_password("senha-forte-9", convertido))
        self.assertFalse(check_password("senha-forte-9", bruto))

        with self.assertRaises(ValueError):
            identify_hasher(bruto)

        self.assertEqual(identify_hasher(convertido).algorithm, "bcrypt")

    def test_hash_ja_convertido_passa_intacto(self):
        bruto = self.hash_bcrypt()

        self.assertEqual(hash_de_senha(f"bcrypt${bruto}"), f"bcrypt${bruto}")
        self.assertEqual(hash_de_senha(f"bcrypt_sha256${bruto}"), f"bcrypt_sha256${bruto}")

    def test_pbkdf2_do_django_passa_intacto(self):
        criado = make_password("outra-senha-9")

        self.assertEqual(hash_de_senha(criado), criado)

    def test_hash_sem_formato_conhecido_para_o_comando(self):
        with self.assertRaises(CommandError):
            hash_de_senha("senha-em-texto-plano")

        self.assertIsNone(hash_de_senha(None))
        self.assertIsNone(hash_de_senha(""))

    # -- import do que tem dono ----------------------------------------------------

    def test_importa_conta_estetica_servicos_e_fotos(self):
        bruto = self.hash_bcrypt()

        self.roda({"esteticas_com_dono": [registro_dump(usuario={"email": "dono@exemplo.com", "hash": bruto})], "esteticas_orfas": []})

        usuario = User.objects.get(username="dono@exemplo.com")
        estetica = Estetica.objects.get(user=usuario)

        self.assertEqual(estetica.nome_negocio, "Estética Real")
        self.assertEqual(estetica.slug, "estetica-real")
        self.assertEqual(estetica.plano_ativo, "profissional")
        self.assertEqual(estetica.cor_principal, "#075e54")
        self.assertEqual(usuario.password.split("$")[0], "bcrypt")
        self.assertTrue(usuario.check_password("senha-forte-9"))
        self.assertEqual([s.nome for s in estetica.servicos.all()], ["Polimento"])
        self.assertEqual([g.antes_url for g in estetica.galerias.all()], ["/antes.jpg"])

        # auto_now_add não aceita valor de migration; o update posterior é o que preserva
        # a data antiga. Sem isto, toda conta importada nasceria "hoje".
        self.assertEqual(estetica.criado_em.year, 2025)

    def test_rodar_duas_vezes_nao_duplica_nem_reescreve_senha(self):
        dump = {"esteticas_com_dono": [registro_dump(usuario={"email": "dono@exemplo.com", "hash": self.hash_bcrypt()})], "esteticas_orfas": []}

        self.roda(dump)
        senha_da_primeira = User.objects.get(username="dono@exemplo.com").password
        self.roda(dump)

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Estetica.objects.count(), 1)
        self.assertEqual(Servico.objects.count(), 1)
        self.assertEqual(Galeria.objects.count(), 1)

        # Reimportar o hash velho não pode desfazer a troca de senha de quem já migrou.
        usuario = User.objects.get(username="dono@exemplo.com")
        usuario.set_password("senha-nova-dele-9")
        usuario.save()

        self.roda(dump)

        self.assertTrue(User.objects.get(username="dono@exemplo.com").check_password("senha-nova-dele-9"))

    def test_slug_em_uso_por_outra_conta_nao_e_roubado(self):
        vizinha = User.objects.create_user(username="vizinha@exemplo.com", email="vizinha@exemplo.com", password="senha-forte-9")
        Estetica.objects.create(user=vizinha, nome_negocio="Estética Vizinha", slug="estetica-real")

        self.roda({"esteticas_com_dono": [registro_dump(usuario={"email": "dono@exemplo.com", "hash": self.hash_bcrypt()})], "esteticas_orfas": []})

        self.assertEqual(Estetica.objects.filter(user__username="vizinha@exemplo.com").count(), 1)
        self.assertFalse(User.objects.filter(username="dono@exemplo.com").exists(), "recusou antes de criar a conta")

    def test_duas_linhas_para_o_mesmo_dono_ficam_paradas(self):
        hash_ = self.hash_bcrypt()
        dump = {
            "esteticas_com_dono": [
                registro_dump(id_supabase="aaaa", usuario={"email": "dono@exemplo.com", "hash": hash_}),
                registro_dump(id_supabase="bbbb", nome_negocio="Estética Segunda", slug_estetica="estetica-segunda", usuario={"email": "dono@exemplo.com", "hash": hash_}),
            ],
            "esteticas_orfas": [],
        }

        saida = self.roda(dump)

        # O painel mostra uma estética por conta; importar as duas deixaria a primeira
        # invisível para o dono. Nenhuma das duas entra, e o relatório diz o id de cada
        # uma para a decisão não ter que ser reaberta no banco.
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Estetica.objects.count(), 0)
        self.assertIn("[aaaa]", saida)
        self.assertIn("[bbbb]", saida)
        self.assertIn("mais de uma estética no dump para dono@exemplo.com", saida)

    # -- órfãs ---------------------------------------------------------------------

    def test_orfa_fica_parada_sem_destino(self):
        self.roda({"esteticas_com_dono": [], "esteticas_orfas": [registro_dump(id_supabase="deadbeef", nome_negocio="Estética Órfã")]})

        self.assertEqual(Estetica.objects.count(), 0)

    def test_duas_orfas_sem_orfa_id_recusa_e_nao_escolhe_sozinha(self):
        User.objects.create_user(username="novo@exemplo.com", email="novo@exemplo.com", password="senha-forte-9")
        dump = {
            "esteticas_com_dono": [],
            "esteticas_orfas": [
                registro_dump(id_supabase="cafe0001", nome_negocio="Estética Um"),
                registro_dump(id_supabase="cafe0002", nome_negocio="Estética Dois", slug_estetica="estetica-dois"),
            ],
        }

        with self.assertRaises(CommandError) as captura:
            self.roda(dump, importar_orfas="novo@exemplo.com")

        texto = str(captura.exception)

        self.assertIn("--orfa", texto)
        self.assertIn("cafe0001", texto, "a mensagem tem que listar as opções com o id")
        self.assertEqual(Estetica.objects.count(), 0)

    def test_orfa_escolhida_vai_para_a_conta_nova(self):
        User.objects.create_user(username="novo@exemplo.com", email="novo@exemplo.com", password="senha-forte-9")
        dump = {
            "esteticas_com_dono": [],
            "esteticas_orfas": [
                registro_dump(id_supabase="cafe0001", nome_negocio="Estética Um"),
                registro_dump(id_supabase="cafe0002", nome_negocio="Estética Dois", slug_estetica="estetica-dois"),
            ],
        }

        self.roda(dump, importar_orfas="novo@exemplo.com", orfas=["cafe0002"])

        estetica = Estetica.objects.get(user__username="novo@exemplo.com")

        self.assertEqual(estetica.nome_negocio, "Estética Dois")
        self.assertEqual(estetica.slug, "estetica-dois")
        self.assertEqual(Servico.objects.count(), 1)
        self.assertEqual(Estetica.objects.count(), 1)

    def test_destino_que_ja_tem_estetica_e_recusado(self):
        dono = User.objects.create_user(username="dono@exemplo.com", email="dono@exemplo.com", password="senha-forte-9")
        atual = Estetica.objects.create(user=dono, nome_negocio="Site Publicado", slug="site-publicado")

        with self.assertRaises(CommandError) as captura:
            self.roda({"esteticas_com_dono": [], "esteticas_orfas": [registro_dump(id_supabase="cafe0001")]}, importar_orfas="dono@exemplo.com")

        self.assertIn("já tem uma estética", str(captura.exception))

        atual.refresh_from_db()

        self.assertEqual(atual.nome_negocio, "Site Publicado", "o site publicado não foi tocado")
        self.assertEqual(atual.slug, "site-publicado")

    def test_orfa_id_sem_importar_orfas_nao_adivinha_dono(self):
        User.objects.create_user(username="novo@exemplo.com", email="novo@exemplo.com", password="senha-forte-9")
        dump = {"esteticas_com_dono": [], "esteticas_orfas": [registro_dump(id_supabase="cafe0001")]}

        with self.assertRaises(CommandError) as captura:
            self.roda(dump, orfas=["cafe0001"])

        self.assertIn("DE QUEM", str(captura.exception))
        self.assertEqual(Estetica.objects.count(), 0)

    def test_destino_inexistente_para_com_erro_claro(self):
        with self.assertRaises(CommandError) as captura:
            self.roda({"esteticas_com_dono": [], "esteticas_orfas": [registro_dump(id_supabase="cafe0001")]}, importar_orfas="ninguem@exemplo.com")

        self.assertIn("não existe conta", str(captura.exception))

    def test_orfa_id_desconhecido_lista_as_opcoes(self):
        User.objects.create_user(username="novo@exemplo.com", email="novo@exemplo.com", password="senha-forte-9")
        dump = {"esteticas_com_dono": [], "esteticas_orfas": [registro_dump(id_supabase="cafe0001", nome_negocio="Estética Um")]}

        with self.assertRaises(CommandError) as captura:
            self.roda(dump, importar_orfas="novo@exemplo.com", orfas=["nao-existe"])

        self.assertIn("cafe0001", str(captura.exception))
        self.assertEqual(Estetica.objects.count(), 0)

    def test_apenas_relatorio_nao_escreve(self):
        self.roda({"esteticas_com_dono": [registro_dump(usuario={"email": "dono@exemplo.com", "hash": self.hash_bcrypt()})], "esteticas_orfas": []}, apenas_relatorio=True)

        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Estetica.objects.count(), 0)

    def test_arquivo_inexistente_aponta_o_exporta(self):
        with self.assertRaises(CommandError) as captura:
            call_command("importa_supabase", arquivo=str(Path(self.pasta.name) / "nao-tem.json"))

        self.assertIn("exporta_supabase", str(captura.exception))


class GarantiaDeBancoEmDeploy(SimpleTestCase):
    """O settings.py não pode aceitar SQLite num deploy.

    A checagem é provada em subprocess porque ela acontece na importação do módulo de
    settings: dentro do processo de teste o módulo já foi importado uma vez, e recarregá-lo
    deixaria duas versões de `DATABASES` vivas. Cada subprocess abaixo é o ambiente real de
    um container recém-criado, com as variáveis fixadas de propósito -- inclusive como
    string vazia, porque `load_dotenv` não sobrescreve o que já existe no ambiente.
    """

    RAIZ = Path(settings.BASE_DIR)

    def rode(self, **variaveis: str) -> subprocess.CompletedProcess[str]:
        ambiente = os.environ.copy()
        for nome in ("DJANGO_SECRET_KEY", "DATABASE_URL", "DATABASE_URL_UNPOOLED", "DJANGO_BUILD_SEM_BANCO"):
            ambiente[nome] = ""
        ambiente.update(variaveis)
        return subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "ERROR"],
            cwd=self.RAIZ,
            env=ambiente,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_deploy_sem_url_de_banco_recusa_subir(self):
        # DJANGO_SECRET_KEY definida é o que diz "isto é um deploy": no notebook ela
        # não existe, e é exatamente assim que o teste local continua em SQLite.
        resposta = self.rode(DJANGO_SECRET_KEY="segredo-de-teste")

        # returncode != 0 é o que distingue recusar de advertir: com aviso o comando
        # terminaria em 0 e o container subiria no arquivo errado.
        self.assertNotEqual(resposta.returncode, 0, resposta.stdout + resposta.stderr)
        self.assertIn("Deploy sem banco externo", resposta.stderr)
        self.assertIn("ImproperlyConfigured", resposta.stderr)

    def test_etapa_de_build_sem_banco_e_liberada(self):
        # É a linha do `RUN collectstatic` do Dockerfile.vercel: o `docker build` não
        # recebe as variáveis do projeto e collectstatic não abre conexão.
        resposta = self.rode(DJANGO_SECRET_KEY="segredo-de-teste", DJANGO_BUILD_SEM_BANCO="1")

        self.assertEqual(resposta.returncode, 0, resposta.stdout + resposta.stderr)

    def test_url_de_banco_presente_libera_a_checagem(self):
        resposta = self.rode(
            DJANGO_SECRET_KEY="segredo-de-teste",
            DATABASE_URL="postgres://usuario:senha@host.exemplo:5432/banco",
        )

        self.assertEqual(resposta.returncode, 0, resposta.stdout + resposta.stderr)

    def test_url_nao_poolada_e_a_escolhida(self):
        # O pool transacional do Neon não aceita `set_config` de variável de sessão, e o
        # Django executa isso ao conectar -- por isso a conexão direta vence quando existe.
        def engine(**variaveis: str) -> str:
            ambiente = os.environ.copy()
            for nome in ("DJANGO_SECRET_KEY", "DATABASE_URL", "DATABASE_URL_UNPOOLED"):
                ambiente[nome] = ""
            ambiente.update(variaveis)
            resposta = subprocess.run(
                [
                    sys.executable,
                    "manage.py",
                    "shell",
                    "-c",
                    "from django.conf import settings; print(settings.DATABASES['default']['ENGINE'])",
                ],
                cwd=self.RAIZ,
                env=ambiente,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(resposta.returncode, 0, resposta.stdout + resposta.stderr)
            return resposta.stdout.strip().splitlines()[-1]

        comum = engine(DATABASE_URL="postgres://a:b@pool.exemplo:5432/db", DATABASE_URL_UNPOOLED="")
        direta = engine(DATABASE_URL="postgres://a:b@pool.exemplo:5432/db", DATABASE_URL_UNPOOLED="postgres://a:b@direta.exemplo:5432/db")

        self.assertTrue(comum.endswith("postgresql"), comum)
        self.assertEqual(comum, direta, "as duas strings apontam para o mesmo Postgres")


class CriaAdminTest(TestCase):
    """O superusuário do /admin nasce de variável de ambiente, sem quebrar deploy.

    O que está em jogo aqui não é criar um usuário -- é o comportamento nas bordas: sem
    variável, com variável incompleta, com a conta já existente e na segunda execução.
    Cada uma dessas é um deploy que aconteceria de verdade na Vercel, e a que não tem
    teste é a que quebra o container às 3h.
    """

    def roda(self, ambiente: dict[str, str] | None = None) -> tuple[str, str]:
        variaveis = {"DJANGO_SUPERUSER_EMAIL": "", "DJANGO_SUPERUSER_PASSWORD": ""}
        variaveis.update(ambiente or {})
        saida, erro = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, variaveis, clear=False):
            call_command("cria_admin", stdout=saida, stderr=erro)
        return saida.getvalue(), erro.getvalue()

    def test_cria_superusuario_que_consegue_logar(self):
        saida, _ = self.roda({"DJANGO_SUPERUSER_EMAIL": "dono@exemplo.com", "DJANGO_SUPERUSER_PASSWORD": "senha-forte-9"})

        usuario = User.objects.get(username="dono@exemplo.com")
        self.assertTrue(usuario.is_staff)
        self.assertTrue(usuario.is_superuser)
        self.assertEqual(usuario.email, "dono@exemplo.com")
        self.assertTrue(usuario.check_password("senha-forte-9"))
        self.assertIn("criado", saida)

    def test_email_com_maiusculas_nao_vira_segunda_conta(self):
        # O painel minúsculiza o e-mail antes de usar como username; o comando tem que
        # bater com essa regra, senão "Dono@Exemplo.com" criaria um segundo usuário.
        User.objects.create_user(username="dono@exemplo.com", email="dono@exemplo.com", password="senha-forte-9")

        _, erro = self.roda({"DJANGO_SUPERUSER_EMAIL": "Dono@Exemplo.com", "DJANGO_SUPERUSER_PASSWORD": "outra-senha-9"})

        self.assertEqual(User.objects.count(), 1)
        self.assertIn("já existe", erro)

    def test_sem_variaveis_avisa_e_nao_falha(self):
        saida, _ = self.roda()

        self.assertEqual(User.objects.count(), 0)
        self.assertIn("não definidas", saida)

    def test_variavel_incompleta_nao_cria_meio_administrador(self):
        self.roda({"DJANGO_SUPERUSER_EMAIL": "dono@exemplo.com"})
        self.roda({"DJANGO_SUPERUSER_PASSWORD": "senha-forte-9"})

        self.assertEqual(User.objects.count(), 0)

    def test_segunda_vez_nao_duplica_nem_reescreve_senha(self):
        ambiente = {"DJANGO_SUPERUSER_EMAIL": "dono@exemplo.com", "DJANGO_SUPERUSER_PASSWORD": "senha-forte-9"}
        self.roda(ambiente)
        Usuario = User.objects.get(username="dono@exemplo.com")
        hash_original = Usuario.password

        # Redeploy com a mesma variável, e também com uma senha diferente na mão de
        # quem só quis consertar o acesso: nenhum dos dois tocava a senha existente.
        self.roda(ambiente)
        self.roda({"DJANGO_SUPERUSER_EMAIL": "dono@exemplo.com", "DJANGO_SUPERUSER_PASSWORD": "senha-nova-9"})

        usuario = User.objects.get(username="dono@exemplo.com")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(usuario.password, hash_original)
        self.assertIn("já é superusuário", self.roda(ambiente)[0])

    def test_conta_comum_existente_nao_e_promovida(self):
        User.objects.create_user(username="dono@exemplo.com", email="dono@exemplo.com", password="senha-forte-9")

        _, erro = self.roda({"DJANGO_SUPERUSER_EMAIL": "dono@exemplo.com", "DJANGO_SUPERUSER_PASSWORD": "senha-forte-9"})

        usuario = User.objects.get(username="dono@exemplo.com")
        self.assertFalse(usuario.is_staff, "deploy não promove ninguém a administrador em silêncio")
        self.assertIn("NÃO foi promovida", erro)
