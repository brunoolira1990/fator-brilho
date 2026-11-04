from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Tudo que o painel Astro consome mora sob /api/, inclusive o webhook do Asaas.
    path("api/", include("core.urls")),
]
