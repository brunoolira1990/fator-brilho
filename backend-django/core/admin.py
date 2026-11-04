from django.contrib import admin

from .models import Estetica, Galeria, Servico


class ServicoInline(admin.TabularInline):
    model = Servico
    extra = 0
    fields = ("nome", "preco", "descricao", "ordem")


class GaleriaInline(admin.TabularInline):
    model = Galeria
    extra = 0
    fields = ("antes_url", "depois_url", "legenda", "ordem")


@admin.register(Estetica)
class EsteticaAdmin(admin.ModelAdmin):
    """
    A tela do dono do SaaS: bater o cliente pelo nome ou pelo link, ver se o plano
    está ativo e editar o cadastro inteiro — inclusive as listas, pelos inlines.
    """

    list_display = ("nome_negocio", "dono", "slug", "plano_ativo", "publicada", "criado_em")
    list_filter = ("plano_ativo",)
    search_fields = ("nome_negocio", "slug", "user__email")
    ordering = ("-criado_em",)
    inlines = [ServicoInline, GaleriaInline]
    readonly_fields = ("criado_em", "atualizado_em")
    fields = (
        "user",
        "nome_negocio",
        "whatsapp",
        "instagram",
        "endereco",
        "cor_principal",
        "slug",
        "plano_ativo",
        "cpf_cnpj",
        "asaas_customer_id",
        "criado_em",
        "atualizado_em",
    )
    # `publicada` é property, não coluna: entra como coluna da lista mas não é
    # editável, por isso está fora de `fields`.
    list_display_links = ("nome_negocio",)

    @admin.display(description="dono", ordering="user__email")
    def dono(self, objeto):
        return objeto.user.email or objeto.user.username

    @admin.display(boolean=True, description="no ar")
    def publicada(self, objeto):
        return objeto.publicada


@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    list_display = ("nome", "preco", "estetica", "ordem")
    list_filter = ("estetica",)
    search_fields = ("nome", "descricao")
    ordering = ("estetica", "ordem")


@admin.register(Galeria)
class GaleriaAdmin(admin.ModelAdmin):
    list_display = ("legenda", "estetica", "ordem")
    list_filter = ("estetica",)
    search_fields = ("legenda",)
    ordering = ("estetica", "ordem")


# Os cabeçalhos aparecem na aba do navegador, no topo do admin e na tela de login.
# O jazzmin lê JAZZMIN_SETTINGS, e estes três são o que o Django usa se a config dele
# faltar.
admin.site.site_header = "Fator Brilho - Admin"
admin.site.site_title = "Fator Brilho - Admin"
admin.site.index_title = "Clientes"
