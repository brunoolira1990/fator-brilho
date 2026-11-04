"""
Serializers da API do painel e da página pública.

A regra de ouro é a mesma do endpoint antigo do Astro: nada chega ao banco sem
passar pela normalização, e a mensagem de erro é o texto que o cliente lê. Por isso
as validações estão aqui (e não espalhadas nas views) — é o único lugar que o
`is_valid()` consulta.
"""

import re

from django.contrib.auth.models import User
from rest_framework import serializers

from .limpeza import gerar_slug, url_de_imagem, validar_slug
from .models import Estetica, Galeria, Servico


class EsteticaSerializer(serializers.ModelSerializer):
    # Declarado em vez de gerado: `serializers.SlugField` traz o regex do Django e
    # recusaria "Estética do Bruno" antes de qualquer normalização. O que chega do
    # painel é texto livre, e quem decide o que vira link é `validate_slug` — igual
    # ao endpoint antigo do Astro.
    slug = serializers.CharField(max_length=80, required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Estetica
        fields = [
            "id",
            "nome_negocio",
            "whatsapp",
            "instagram",
            "endereco",
            "cor_principal",
            "slug",
            "plano_ativo",
            "asaas_customer_id",
            "cpf_cnpj",
        ]
        # O plano é consequência do pagamento confirmado no webhook, e o id do
        # Asaas é consequência do checkout. Nenhum dos dois se edita por aqui.
        read_only_fields = ["id", "plano_ativo", "asaas_customer_id"]
        # Os validadores do modelo (RegexValidator de cor e de CPF/CNPJ) e o max_length
        # do varchar rodam ANTES dos nossos validate_*, e devolveriam a frase genérica
        # do Django. Aqui eles são desligados de propósito: quem fala com o cliente é a
        # mensagem em pt-BR abaixo, e o limite continua sendo conferido por ela.
        extra_kwargs = {
            "nome_negocio": {"max_length": None},
            "whatsapp": {"max_length": None},
            "instagram": {"max_length": None},
            "endereco": {"max_length": None},
            "cor_principal": {"max_length": None, "validators": []},
            "cpf_cnpj": {"max_length": None, "validators": []},
        }

    def validate_nome_negocio(self, valor):
        texto = (valor or "").strip()

        if len(texto) > 120:
            raise serializers.ValidationError("Nome do negócio: use no máximo 120 caracteres.")

        return texto

    def validate_whatsapp(self, valor):
        texto = (valor or "").strip()

        if texto and not re.fullmatch(r"\+?[\d\s().-]+", texto):
            raise serializers.ValidationError("WhatsApp: use apenas números, com opcional + no início.")

        if len(texto) > 20:
            raise serializers.ValidationError("WhatsApp: use no máximo 20 caracteres.")

        return texto

    def validate_instagram(self, valor):
        texto = (valor or "").strip().lstrip("@")

        if texto and not re.fullmatch(r"[\w.]+", texto):
            raise serializers.ValidationError("Instagram: use apenas letras, números, ponto e underscore.")

        if len(texto) > 64:
            raise serializers.ValidationError("Instagram: use no máximo 64 caracteres.")

        return texto

    def validate_endereco(self, valor):
        texto = (valor or "").strip()

        if len(texto) > 300:
            raise serializers.ValidationError("Endereço: use no máximo 300 caracteres.")

        return texto

    def validate_cor_principal(self, valor):
        texto = (valor or "").strip()

        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", texto):
            raise serializers.ValidationError("Cor principal inválida: use o formato #RRGGBB.")

        return texto.lower()

    def validate_slug(self, valor):
        slug = gerar_slug(valor or "")
        erro = validar_slug(slug)

        if erro:
            raise serializers.ValidationError(erro)

        if not slug:
            # Link vazio = site não publicado. None no banco, não "": é o que permite
            # que várias contas convivam sem slug sob um índice único.
            return None

        # Unique no banco, mas o Postgres devolve 23505 cru. Aqui vira frase.
        query = Estetica.objects.filter(slug=slug)
        if self.instance is not None:
            query = query.exclude(pk=self.instance.pk)

        if query.exists():
            raise serializers.ValidationError("Esse link já pertence a outra estética. Escolha outro e salve novamente.")

        return slug

    def validate_cpf_cnpj(self, valor):
        digitos = "".join(character for character in (valor or "") if character.isdigit())

        if digitos and len(digitos) not in (11, 14):
            raise serializers.ValidationError(
                "CPF/CNPJ: use 11 dígitos (CPF) ou 14 dígitos (CNPJ), com ou sem máscara."
            )

        return digitos


class ServicoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servico
        fields = ["id", "nome", "preco", "descricao", "ordem"]
        read_only_fields = ["id", "ordem"]
        # `nome` com required=False: um item sem nome na lista tem que cair na frase do
        # Bruno ("informe nome do serviço."), e não no "Este campo é obrigatório." do
        # DRF. A checagem de presença é feita em validate(), abaixo.
        extra_kwargs = {
            "nome": {"required": False, "allow_blank": True, "allow_null": True, "max_length": None},
            "preco": {"max_length": None},
            "descricao": {"max_length": None},
        }

    def validate_nome(self, valor):
        texto = (valor or "").strip()

        if not texto:
            raise serializers.ValidationError("informe nome do serviço.")

        if len(texto) > 80:
            raise serializers.ValidationError("Nome do serviço tem mais de 80 caracteres.")

        return texto

    def validate(self, attrs):
        # PATCH de um campo só (mudar apenas o preço) não precisa reenviar o nome.
        if self.partial:
            return attrs

        # required=False faz o campo sumir de validated_data quando a chave não vem;
        # é aqui que "não veio" e "veio vazio" viram a mesma mensagem.
        nome = (attrs.get("nome") or "").strip()

        if not nome:
            raise serializers.ValidationError({"nome": "informe nome do serviço."})

        attrs["nome"] = nome

        return attrs

    def validate_preco(self, valor):
        texto = (valor or "").strip()

        if len(texto) > 40:
            raise serializers.ValidationError("Preço tem mais de 40 caracteres.")

        return texto

    def validate_descricao(self, valor):
        texto = (valor or "").strip()

        if len(texto) > 240:
            raise serializers.ValidationError("Descrição tem mais de 240 caracteres.")

        return texto


class GaleriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Galeria
        fields = ["id", "antes_url", "depois_url", "legenda", "ordem"]
        read_only_fields = ["id", "ordem"]
        # Mesmo motivo de EsteticaSerializer/ServicoSerializer: o limite é conferido por
        # _valida_url, para que a mensagem seja a nossa, não a genérica do Django.
        extra_kwargs = {
            "antes_url": {"max_length": None},
            "depois_url": {"max_length": None},
            "legenda": {"max_length": None},
        }

    def validate_antes_url(self, valor):
        return self._valida_url(valor, "antes")

    def validate_depois_url(self, valor):
        return self._valida_url(valor, "depois")

    def _valida_url(self, valor, rotulo):
        bruto = (valor or "").strip()

        if not bruto:
            return ""

        url = url_de_imagem(bruto)

        if not url:
            raise serializers.ValidationError(f"URL do {rotulo} inválida. Use http(s):// ou um caminho /...")

        if len(url) > 500:
            raise serializers.ValidationError(f"URL do {rotulo} tem mais de 500 caracteres.")

        return url

    def validate(self, attrs):
        antes = attrs.get("antes_url", getattr(self.instance, "antes_url", ""))
        depois = attrs.get("depois_url", getattr(self.instance, "depois_url", ""))

        if not antes and not depois:
            raise serializers.ValidationError({"depois_url": "informe a URL da foto antes ou da depois."})

        return attrs

    def validate_legenda(self, valor):
        texto = (valor or "").strip()

        if len(texto) > 120:
            raise serializers.ValidationError("Legenda tem mais de 120 caracteres.")

        return texto


class PublicoSerializer(serializers.ModelSerializer):
    """O que a página /site/<slug> renderiza. Nada de e-mail, documento ou id do Asaas."""

    servicos = ServicoSerializer(many=True, read_only=True)
    galerias = GaleriaSerializer(many=True, read_only=True)

    class Meta:
        model = Estetica
        fields = [
            "nome_negocio",
            "whatsapp",
            "instagram",
            "endereco",
            "cor_principal",
            "slug",
            "servicos",
            "galerias",
        ]


class LoginSerializer(serializers.Serializer):
    login = serializers.CharField(max_length=254)
    senha = serializers.CharField(max_length=128, trim_whitespace=False)


class RegistroSerializer(serializers.Serializer):
    email = serializers.EmailField()
    # max_length fica no campo; min_length é proposital um validate_* próprio, com a
    # frase em pt-BR. Deixar o DRF reclamar em inglês ("at least 8 characters",
    # traduzido) seria uma mensagem órfã no meio de um formulário inteiro em português.
    senha = serializers.CharField(max_length=128, trim_whitespace=False)
    nome_negocio = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate_email(self, valor):
        email = valor.strip().lower()

        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise serializers.ValidationError("Já existe uma conta com esse e-mail.")

        return email

    def validate_senha(self, valor):
        if len(valor) < 8:
            raise serializers.ValidationError("A senha precisa de pelo menos 8 caracteres.")

        return valor
