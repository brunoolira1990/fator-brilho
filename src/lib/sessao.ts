import type { APIContext } from 'astro';
import { painel, type Painel, type Sucesso } from './api';

export type Sessao = Sucesso<Painel>;

/**
 * Sessão das telas de painel, decidida pela API do Django — não por um token que este
 * servidor guarda.
 *
 * O cookie do token é HttpOnly e, em produção, nasce no domínio deste frontend — a
 * chamada `/api/*` é reescrita pelo `vercel.json` para o Django, então o navegador vê
 * uma origem só e o cabeçalho `cookie` chega aqui junto com a request da página. O que
 * faz o SSR saber "está logado?" é repassar esse cabeçalho na chamada à API (com a URL
 * da request como base, porque no Node caminho relativo não é endereço). É também o
 * motivo de o login não devolver o token para o JavaScript ler: /dashboard precisa da
 * resposta da API antes de existir HTML na tela.
 *
 * Os dois motivos de recusa são separados de propósito. 401 é "não há sessão" e manda
 * para /login; qualquer outra falha (API fora do ar, CORS, DNS) devolve 502 com a
 * mensagem — porque redirecionar um servidor caído para /login faria a tela mentir para
 * o dono, dizendo que ele saiu da conta.
 */
export async function exigeSessao(
  context: APIContext
): Promise<{ sessao: Sessao } | { redirecionar: Response }> {
  const resultado = await painel(context.request.headers.get('cookie'), context.request.url);

  if (resultado.ok) {
    return { sessao: resultado };
  }

  if (resultado.status === 401) {
    // 303 como `Astro.redirect`: a browser troca o método por GET ao seguir.
    return { redirecionar: new Response(null, { status: 303, headers: { location: '/login' } }) };
  }

  return {
    redirecionar: new Response(resultado.error, {
      status: 502,
      headers: { 'content-type': 'text/plain; charset=utf-8' },
    }),
  };
}
