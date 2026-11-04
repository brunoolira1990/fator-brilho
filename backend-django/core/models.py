from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import models

PLANO_ESSENCIAL = "essencial"
PLANO_PROFISSIONAL = "profissional"
PLANO_PREMIUM = "premium"

PLANOS = [
    (PLANO_ESSENCIAL, "Essencial"),
    (PLANO_PROFISSIONAL, "Profissional"),
    (PLANO_PREMIUM, "Premium"),
]

valida_hex = RegexValidator(
    regex=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$",
    message="cor_principal precisa virar #rgb ou #rrggbb.",
)


class Estetica(models.Model):
    """
    O site de um cliente. OneToOne com User em vez de PK = id do usuário, como o
    Supabase fazia: aqui o login é a tabela `auth_user` do Django, e o `id` desta
    linha é interno. O que o frontend conhece é o `user` e o `slug`.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="estetica",
        verbose_name="dono",
    )
    nome_negocio = models.CharField("nome do negócio", max_length=120, blank=True)
    whatsapp = models.CharField(
        "whatsapp",
        max_length=20,
        blank=True,
        help_text="Somente dígitos com DDI, ex. 5511999999999.",
    )
    instagram = models.CharField("instagram", max_length=64, blank=True)
    endereco = models.TextField("endereço", blank=True)
    cor_principal = models.CharField(
        "cor principal",
        max_length=7,
        blank=True,
        default="#075E54",
        validators=[valida_hex],
    )
    # Slug vazio = site não publicado, igual ao comportamento atual do painel.
    # `null` (e não "") é obrigatório aqui: unique=True com string vazia faria a
    # segunda conta cadastrada colidir com a primeira antes de publicar qualquer
    # site. No Postgres, NULLs não violam índice único — foi assim que o Supabase
    # funcionou desde o supabase-add-slug.sql.
    slug = models.SlugField("slug do site", max_length=80, blank=True, null=True, unique=True)
    plano_ativo = models.CharField(
        "plano ativo",
        max_length=20,
        blank=True,
        choices=PLANOS,
    )
    asaas_customer_id = models.CharField("cliente no Asaas", max_length=60, blank=True)
    # A cobrança recorrente do Asaas não existe sem CPF/CNPJ do responsável, por isso
    # a coluna está aqui; sem ela o checkout devolve 400 e a assinatura não abre.
    cpf_cnpj = models.CharField(
        "CPF ou CNPJ",
        max_length=14,
        blank=True,
        validators=[RegexValidator(regex=r"^\d{11}$|^\d{14}$", message="use 11 dígitos (CPF) ou 14 (CNPJ), sem máscara.")],
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "estética"
        verbose_name_plural = "estéticas"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.nome_negocio or f"estética {self.pk}"

    @property
    def publicada(self) -> bool:
        return bool(self.slug)


class Servico(models.Model):
    """
    Item da lista de serviços. `preco` continua texto porque os dados que já existem
    são "R$ 880" e a página pública imprime a string como está. Trocar por Decimal é
    uma decisão de apresentação, não de modelagem, e ia reescrever o painel inteiro.
    """

    estetica = models.ForeignKey(
        Estetica,
        on_delete=models.CASCADE,
        related_name="servicos",
        verbose_name="estética",
    )
    nome = models.CharField("nome", max_length=80)
    preco = models.CharField("preço", max_length=40, blank=True)
    descricao = models.CharField("descrição", max_length=240, blank=True)
    ordem = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        verbose_name = "serviço"
        verbose_name_plural = "serviços"
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.nome} ({self.estetica_id})"


class Galeria(models.Model):
    """
    Par antes/depois. `URLField` está fora de propósito: os registros atuais salvam
    caminho relativo ("/hero.jpg"), e o validator do URLField exige scheme.
    """

    estetica = models.ForeignKey(
        Estetica,
        on_delete=models.CASCADE,
        related_name="galerias",
        verbose_name="estética",
    )
    antes_url = models.CharField("antes", max_length=500, blank=True)
    depois_url = models.CharField("depois", max_length=500, blank=True)
    legenda = models.CharField("legenda", max_length=120, blank=True)
    ordem = models.PositiveIntegerField("ordem", default=0)

    class Meta:
        verbose_name = "galeria"
        verbose_name_plural = "galerias"
        ordering = ["ordem", "id"]

    def __str__(self):
        return self.legenda or f"galeria {self.pk}"
