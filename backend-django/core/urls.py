from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AsaasWebhookView,
    CheckoutView,
    EsteticaView,
    GaleriaViewSet,
    LoginView,
    LogoutView,
    PlanosView,
    PublicoView,
    RegistroView,
    ServicoViewSet,
)

# `trailing_slash_default` ligado porque é assim que o frontend já chama
# (/api/servicos/), e uma URL que muda de forma entre dev e prod é bug à espera.
router = DefaultRouter()
router.register("servicos", ServicoViewSet, basename="servico")
router.register("galeria", GaleriaViewSet, basename="galeria")

urlpatterns = [
    path("auth/registro/", RegistroView.as_view(), name="registro"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("estetica/", EsteticaView.as_view(), name="estetica"),
    path("planos/", PlanosView.as_view(), name="planos"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    # O Asaas não manda JSON com `event` por acaso, e o caminho é o que foi cadastrado
    # no painel dele: /api/webhooks/asaas/.
    path("webhooks/asaas/", AsaasWebhookView.as_view(), name="webhook-asaas"),
    path("publico/<slug:slug>/", PublicoView.as_view(), name="publico"),
    path("", include(router.urls)),
]
