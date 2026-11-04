"""
Autenticação por token, mas transportada em cookie HttpOnly.

Por que cookie e não o header `Authorization` com o token no `localStorage`: o painel
é o Astro, que renderiza `/dashboard` no servidor e precisa decidir "está logado?"
antes de devolver o HTML. Um cookie via junto com a requisição; um valor de
`localStorage` não existe no servidor e obrigaria a página a virar ilha cliente, com
redirecionamento depois do paint. E o token deixa de ser legível por qualquer XSS.

O preço de usar cookie numa API é CSRF, e o DRF não protege isso sozinho: `APIView`
é `csrf_exempt` por construção. A defesa aqui é o cabeçalho `X-Fator-Brilho: 1` em
todo método não-seguro. Um `<form>` de outro site consegue enviar o cookie, mas não
consegue definir um cabeçalho customizado sem passar pelo preflight CORS — que ele
não passa, porque a origem não está na lista.
"""

from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

NAO_SEGURO = {"POST", "PUT", "PATCH", "DELETE"}
CABECALHO = "X-Fator-Brilho"


class TokenCookieAuthentication(TokenAuthentication):
    def authenticate(self, request):
        token = request.COOKIES.get(settings.TOKEN_COOKIE)

        if not token:
            # Sem cookie não é falha, é "não sou eu": deixa o TokenAuthentication do
            # header tentar em seguida (curl, testes, chamadas de servidor).
            return None

        if request.method.upper() in NAO_SEGURO and request.headers.get(CABECALHO) != "1":
            raise exceptions.AuthenticationFailed(
                f"requisição não-segura sem o cabeçalho {CABECALHO}: 1"
            )

        return self.authenticate_credentials(token)

    def authenticate_header(self, request):
        return self.keyword
