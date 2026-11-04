/**
 * Camada única de acesso à API do Django.
 *
 * Antes cada tela chamava `fetch` com o caminho que lembrava; agora o caminho, o
 * formato do corpo e o tipo da resposta moram aqui, e a tela só enxerga a união
 * discriminada `{ok: true, ...} | {ok: false, error, status}` — que é exatamente o
 * contrato que `core/views.py` devolve (inclusive nos erros que o DRF gera sozinho,
 * normalizados por `core/excecoes.py`). Isso é o que permite ao `astro check` reclamar
 * se o backend deixar de devolver uma chave, em vez de a tela mostrar `undefined`.
 *
 * Por que função e não um client do Supabase: o painel é renderizado no servidor
 * (`output: 'server'`), e a decisão "está logado?" acontece antes de devolver o HTML.
 * Um token em `localStorage` não existe no servidor — um cookie, sim. Então o login
 * devolve o token em cookie HttpOnly (`fb_token`), o navegador guarda, e toda chamada
 * sai com `credentials: 'include'`. No SSR o navegador não existe, então quem renderiza
 * repassa o cabeçalho `cookie` da request (`{ cookie }` em cada função abaixo) e a URL
 * da própria request (`{ base }`), porque em produção a chamada é na mesma origem e o
 * `fetch` do Node não aceita caminho relativo.
 *
 * O cabeçalho `X-Fator-Brilho: 1` em método não-seguro não é decorativo: é a defesa
 * de CSRF da API (`core/authentication.py`). `APIView` é `csrf_exempt` por construção,
 * e um `<form>` de outro site envia o cookie mas não consegue enviar cabeçalho
 * customizado. Por isso o logout do painel deixou de ser `<form method="POST">` e
 * passou a ser fetch — um form não passa por aqui.
 */

/** Métodos que a API exige assinados. GET fica de fora de propósito. */
const NAO_SEGURO = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export const CABECALHO_SESSAO = 'X-Fator-Brilho';

/**
 * Origem da chamada.
 *
 * Em PRODUÇÃO a resposta é string vazia, que significa "a mesma origem desta página".
 * É decisão deliberada e não esquecimento: o `vercel.json` da raiz reescreve `/api/*`
 * para o domínio do Django, então o navegador e o SSR chamam `fator-brilho.vercel.app`
 * e a Vercel entrega a requisição ao backend. Consequência direta — e o motivo de a
 * reescrita existir — é que o cookie do token nasce no host do frontend, sem atributo
 * `Domain=`, e por isso o SSR consegue lê-lo em `/dashboard`. Apontar o navegador para
 * `api-fator-brilho.vercel.app` em produção recriaria o problema que a reescrita
 * resolveu, por isso `PUBLIC_API_URL` não é consultada aqui no build de produção.
 *
 * Em DEV a reescrita não existe (o `astro dev` não lê `vercel.json`), e aí a chamada é
 * ao endereço do `runserver`: `PUBLIC_API_URL`, com o 8010 como padrão porque a 8000
 * está ocupada pelo Docker nesta máquina. Cross-origin por porta, o que mantém o CORS
 * do Django relevante no dev, mas o cookie continua sendo o mesmo host (`localhost`),
 * e navegador não separa cookie por porta.
 */
export function origemDaApi(): string {
  if (import.meta.env.PROD) return '';

  const bruto = String(import.meta.env.PUBLIC_API_URL ?? '').trim().replace(/\/+$/, '');

  return bruto || 'http://localhost:8010';
}

export type Falha = { ok: false; error: string; status: number };
/**
 * `status` está nos dois lados da união de propósito: as telas decidem por ele
 * (401 no painel = redireciona para /login; 404 na página pública = /404) sem
 * precisar de uma segunda chamada e sem comparar texto de mensagem.
 */
export type Sucesso<T> = { ok: true; status: number } & T;
export type Resposta<T> = Sucesso<T> | Falha;

export type CamposEstetica = {
  id: number;
  nome_negocio: string;
  whatsapp: string;
  instagram: string;
  endereco: string;
  cor_principal: string;
  /** null = site não publicado. O banco guarda NULL, não string vazia. */
  slug: string | null;
  plano_ativo: string;
  asaas_customer_id: string;
  cpf_cnpj: string;
};

export type ServicoLinha = { id: number; nome: string; preco: string; descricao: string; ordem: number };
export type GaleriaLinha = { id: number; antes_url: string; depois_url: string; legenda: string; ordem: number };

/** O corpo de `/api/estetica/` — igual no GET e no PUT (prova: test_get_e_put_tem_a_mesma_shape). */
export type Painel = {
  data: CamposEstetica | null;
  email: string;
  servicos: ServicoLinha[];
  galeria: GaleriaLinha[];
};

/** O que `/api/publico/<slug>/` devolve: sem e-mail, sem documento, sem id do Asaas. */
export type SitePublico = {
  nome_negocio: string;
  whatsapp: string;
  instagram: string;
  endereco: string;
  cor_principal: string;
  slug: string | null;
  servicos: ServicoLinha[];
  galerias: GaleriaLinha[];
};

export type PlanoPublico = {
  slug: string;
  nome: string;
  preco: string;
  valor: number;
  destaque: boolean;
  itens: string[];
};

/** O que o painel envia no PUT. Ausente = não mexe; `[]` = esvaziou de propósito. */
export type PainelEdicao = {
  nome_negocio?: string;
  whatsapp?: string;
  instagram?: string;
  endereco?: string;
  cpf_cnpj?: string;
  cor_principal?: string;
  slug?: string;
  servicos?: { nome: string; preco: string; descricao: string }[];
  galeria?: { antes_url: string; depois_url: string; legenda: string }[];
};

type Chamar = {
  metodo?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  corpo?: unknown;
  /** Cabeçalho `cookie` da request, para a chamada de servidor manter a sessão do dono. */
  cookie?: string | null;
  /**
   * URL da request atual, obrigatória no SSR quando a origem é a mesma (`''`):
   * `fetch('/api/...')` funciona no navegador, mas no Node uma URL relativa não é
   * endereço nenhum. Quem renderiza no servidor passa `context.request.url`; no
   * cliente estas funções rodam no navegador e não precisam.
   */
  base?: string | null;
};

async function chamar<T>(caminho: string, { metodo = 'GET', corpo, cookie, base }: Chamar = {}): Promise<Resposta<T>> {
  const origem = origemDaApi();

  let url: string;

  if (origem) {
    // Dev: endereço absoluto do runserver.
    url = `${origem}${caminho}`;
  } else if (base) {
    // Produção em SSR: mesma origem da request que está sendo atendida.
    url = new URL(caminho, base).href;
  } else if (typeof document === 'undefined') {
    // Produção em SSR sem a URL da request: falha explícita, e não um
    // "Failed to parse URL" do Node virando "não foi possível falar com o servidor".
    return {
      ok: false,
      error: 'Chamada de servidor sem a URL da request (base). Quem renderiza precisa passá-la.',
      status: 500,
    };
  } else {
    // Produção no navegador: caminho relativo à página, reescrito pelo vercel.json.
    url = caminho;
  }

  const headers: Record<string, string> = {};

  if (corpo !== undefined) headers['content-type'] = 'application/json';
  if (NAO_SEGURO.has(metodo)) headers[CABECALHO_SESSAO] = '1';
  if (cookie) headers.cookie = cookie;

  let response: Response;

  try {
    response = await fetch(url, {
      method: metodo,
      headers,
      // É isto que faz o cookie HttpOnly ir e voltar. Sem 'include', o navegador manda
      // a requisição sem credencial e a API responde 401 mesmo com a sessão gravada.
      credentials: 'include',
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    // DNS, conexão recusada, CORS bloqueado: o fetch estoura antes de haver resposta.
    return { ok: false, error: 'Não foi possível falar com o servidor. Tente novamente.', status: 0 };
  }

  let dados: unknown;

  try {
    dados = await response.json();
  } catch {
    // Página de erro do provedor (HTML) no lugar do JSON: não mostrar `[object Object]`.
    return { ok: false, error: `O servidor respondeu com uma mensagem inválida (${response.status}).`, status: response.status };
  }

  const bruto = (dados && typeof dados === 'object' ? dados : {}) as Record<string, unknown>;
  const texto = typeof bruto.error === 'string' ? bruto.error : '';

  if (bruto.ok !== true) {
    return {
      ok: false,
      error: texto || `Não foi possível completar a operação (${response.status}).`,
      status: response.status,
    };
  }

  // `status` continua dentro do objeto de sucesso: as telas leem `result.status === 401`
  // e `result.email` como está hoje, sem segunda chamada para saber quem está logado.
  return { ...(bruto as T), ok: true, status: response.status };
}

// ----------------------------------------------------------------------------------
// Sessão
// ----------------------------------------------------------------------------------

export function entra(email: string, senha: string) {
  // `login` e `senha` são os nomes do LoginSerializer, não do formulário antigo.
  return chamar<{ email: string; administrador: boolean }>('/api/auth/login/', {
    metodo: 'POST',
    corpo: { login: email, senha },
  });
}

export function registra(email: string, senha: string, nomeNegocio = '') {
  return chamar<{ email: string; id: number }>('/api/auth/registro/', {
    metodo: 'POST',
    corpo: { email, senha, nome_negocio: nomeNegocio },
  });
}

export function sai(cookie?: string | null, base?: string | null) {
  return chamar<Record<string, never>>('/api/auth/logout/', { metodo: 'POST', cookie, base });
}

// ----------------------------------------------------------------------------------
// Painel (autenticado)
// ----------------------------------------------------------------------------------

/** `base` só importa no SSR (ver `chamar`): quem renderiza `/dashboard` passa a URL da request. */
export function painel(cookie?: string | null, base?: string | null) {
  return chamar<Painel>('/api/estetica/', { cookie, base });
}

export function salvaPainel(edicao: PainelEdicao, cookie?: string | null, base?: string | null) {
  return chamar<Painel>('/api/estetica/', { metodo: 'PUT', corpo: edicao, cookie, base });
}

export function abreCheckout(plano: string, cookie?: string | null, base?: string | null) {
  return chamar<{ link: string; checkoutId: string; plano: string }>('/api/checkout/', {
    metodo: 'POST',
    corpo: { plano },
    cookie,
    base,
  });
}

// ----------------------------------------------------------------------------------
// Público (sem sessão)
// ----------------------------------------------------------------------------------

/**
 * `slug` vai na URL do jeito que chegou da rota, que já foi filtrada por
 * `SLUG_OK` na página. A API responde 404 com `{ok:false}` para slug inexistente, e
 * isso é "esse site não existe" — não confundir com a rede caiu, que tem status 0.
 */
export function sitePublico(slug: string, base?: string | null) {
  return chamar<{ data: SitePublico }>(`/api/publico/${encodeURIComponent(slug)}/`, { base });
}

export function planos(base?: string | null) {
  return chamar<{ planos: PlanoPublico[] }>('/api/planos/', { base });
}
