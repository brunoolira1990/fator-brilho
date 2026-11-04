import type { APIRoute } from 'astro';
import { createHash, timingSafeEqual } from 'node:crypto';
import { createClient } from '@supabase/supabase-js';
import { variavel } from '../../../lib/env';
import { planoPorSlug } from '../../../lib/planos';

/**
 * Webhook do Asaas — o último pedaço de Supabase que ainda vive no frontend.
 *
 * O painel, a página pública e o checkout já falam só com o Django. Este arquivo fica
 * porque a URL do webhook no painel do Asaas ainda aponta para este endereço, e trocar
 * essa URL é decisão do dono da conta: enquanto não trocar, os dois canais precisam
 * existir, e apagar este handler significaria perder ativação de assinatura paga.
 *
 * Ele é deliberadamente autossuficiente: `json`, o client do Supabase com service role
 * e a consulta de pagamento ao Asaas estavam em `src/lib/supabase-ssr.ts`,
 * `src/lib/supabase-admin.ts` e `src/lib/asaas.ts`, os três arquivos que a migração
 * esvaziou. Moveram-se para cá com o mesmo comportamento em vez de ficarem vivos só
 * para servir um handler morto. Quando a URL apontar para o Django
 * (`POST /api/webhooks/asaas/`), este arquivo inteiro vai junto — e com ele o último
 * `@supabase/*` do bundle.
 *
 * A regra de resposta, e por que ela não é "200 para tudo":
 *  - 401 quando o asaas-access-token não bate: é erro de configuração e precisa
 *    aparecer, não ser engolido.
 *  - 200 para o que a gente recebeu e decidiu ignorar (evento que não é
 *    CHECKOUT_PAID, payload que nunca vai ser interpretável). Reenviar isso não
 *    serve a ninguém e 15 falhas consecutivas pausam a fila de eventos da conta.
 *  - 500 só quando a culpa é nossa e um reenvio ajuda: o Asaas entrega "pelo menos
 *    uma vez", então reenviar é o mecanismo de repetição que temos.
 *
 * O evento por si só não ativa nada: a ativação depende de conferir o pagamento na
 * API do Asaas (GET /v3/payments?checkoutSession=...) antes de escrever no banco.
 */

const BASE_ASAAS = 'https://api.asaas.com/v3';
const TIMEOUT_MS = 20_000;

const PADRAO_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Pagamento que o Asaas considera pago em cartão. */
const STATUS_PAGO = new Set(['CONFIRMED', 'RECEIVED']);

type PagamentoAsaas = {
  id: string;
  status: string;
  value: number;
  customer?: string;
};

function json(status: number, payload: Record<string, unknown>) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

/**
 * Comparação em tempo constante. Hash primeiro fixa o tamanho dos buffers, senão
 * timingSafeEqual joga RangeError quando o token atacante tem outro comprimento —
 * e o comprimento viraria canal de informação.
 */
function tokensIguais(recebido: string, esperado: string): boolean {
  const a = createHash('sha256').update(recebido).digest();
  const b = createHash('sha256').update(esperado).digest();

  return timingSafeEqual(a, b);
}

/**
 * Cliente com a service role key, usado só aqui.
 *
 * Por que existe: o RLS da `estetica` no Supabase é `auth.uid() = id`, e o Asaas chega
 * no webhook sem sessão de usuário nenhum — pela via normal ele não conseguiria
 * escrever em lugar algum. A service role atravessa o RLS por definição, e ela só é
 * lida no servidor (não tem prefixo PUBLIC_, então não entra no bundle do navegador).
 *
 * Falta a variável = erro alto, com instrução. Silenciar isso deixaria o webhook
 * respondendo 200 para assinaturas pagas que nunca foram ativadas.
 */
function criarSupabaseAdmin() {
  const url = import.meta.env.PUBLIC_SUPABASE_URL;
  const chave = variavel('SUPABASE_SERVICE_ROLE_KEY');

  if (!chave) {
    throw new Error('Falta SUPABASE_SERVICE_ROLE_KEY no ambiente (.env e no projeto da Vercel).');
  }

  return createClient(url, chave, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

/**
 * Asaas responde erro com `errors: [...]`, mas o formato do item não é garantido
 * em todas as páginas da doc. Varre o que existir em vez de assumir uma chave.
 */
function descricaoDoErro(bruto: unknown, status: number): string {
  if (bruto && typeof bruto === 'object' && Array.isArray((bruto as { errors?: unknown }).errors)) {
    const itens = (bruto as { errors: unknown[] }).errors
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const objeto = item as Record<string, unknown>;
          const texto = objeto.description ?? objeto.message ?? objeto.code;

          return typeof texto === 'string' ? texto : JSON.stringify(objeto);
        }

        return String(item);
      })
      .filter(Boolean);

    if (itens.length > 0) return itens.join('; ');
  }

  return `Asaas respondeu ${status}.`;
}

type Resultado<T> = { ok: true; dados: T } | { ok: false; status: number; erro: string };

/** Única chamada de saída deste handler: GET /payments. Tudo o mais morreu com o checkout. */
async function chamarAsaas<T>(caminho: string): Promise<Resultado<T>> {
  const chave = variavel('ASAAS_API_KEY');

  if (!chave) {
    return { ok: false, status: 0, erro: 'Falta ASAAS_API_KEY no ambiente.' };
  }

  let resposta: Response;

  try {
    resposta = await fetch(`${BASE_ASAAS}${caminho}`, {
      method: 'GET',
      headers: {
        access_token: chave,
        'content-type': 'application/json',
        'user-agent': 'FatorBrilhoSaaS/1.0.0',
      },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (erro) {
    const nome = (erro as { name?: string }).name;
    const motivo = nome === 'TimeoutError' ? `sem resposta em ${TIMEOUT_MS / 1000}s` : (erro as Error).message;

    return { ok: false, status: 0, erro: `Não foi possível falar com o Asaas (${motivo}).` };
  }

  let corpo: unknown = null;

  try {
    corpo = await resposta.json();
  } catch {
    corpo = null;
  }

  if (!resposta.ok) {
    return { ok: false, status: resposta.status, erro: descricaoDoErro(corpo, resposta.status) };
  }

  return { ok: true, dados: corpo as T };
}

async function pagamentosDoCheckout(checkoutId: string): Promise<Resultado<PagamentoAsaas[]>> {
  if (!/^[A-Za-z0-9-]{8,64}$/.test(checkoutId)) {
    return { ok: false, status: 400, erro: 'Id de checkout com formato inesperado.' };
  }

  const resposta = await chamarAsaas<{ data?: unknown }>(
    `/payments?checkoutSession=${encodeURIComponent(checkoutId)}&limit=20`
  );

  if (!resposta.ok) return resposta;

  const bruto = Array.isArray(resposta.dados.data) ? resposta.dados.data : [];

  const pagamentos = bruto.filter((item): item is PagamentoAsaas => {
    if (!item || typeof item !== 'object') return false;

    const linha = item as Record<string, unknown>;

    return typeof linha.id === 'string' && typeof linha.status === 'string' && typeof linha.value === 'number';
  });

  return { ok: true, dados: pagamentos };
}

export const POST: APIRoute = async (context) => {
  const esperado = variavel('ASAAS_WEBHOOK_TOKEN');

  if (!esperado) {
    console.error('[asaas:webhook] Falta ASAAS_WEBHOOK_TOKEN no ambiente.');

    return json(500, { ok: false, error: 'Falta ASAAS_WEBHOOK_TOKEN no ambiente.' });
  }

  const recebido = context.request.headers.get('asaas-access-token');

  if (!recebido || !tokensIguais(recebido, esperado)) {
    console.error('[asaas:webhook] Token ausente ou divergente.');

    return json(401, { ok: false, error: 'Token do webhook inválido.' });
  }

  let corpo: unknown;

  try {
    corpo = await context.request.json();
  } catch {
    console.error('[asaas:webhook] Corpo não é JSON.');

    return json(200, { ok: true, ignorado: 'corpo inválido' });
  }

  if (!corpo || typeof corpo !== 'object') {
    return json(200, { ok: true, ignorado: 'corpo vazio' });
  }

  const evento = (corpo as Record<string, unknown>).event;

  // O campo do evento é `event` (não existe `eventType` no payload do Asaas).
  if (typeof evento !== 'string' || evento !== 'CHECKOUT_PAID') {
    return json(200, { ok: true, ignorado: evento ?? 'sem evento' });
  }

  const checkoutBruto = (corpo as Record<string, unknown>).checkout;
  const checkout = (checkoutBruto && typeof checkoutBruto === 'object' ? checkoutBruto : {}) as Record<string, unknown>;

  const checkoutId = typeof checkout.id === 'string' ? checkout.id : '';
  const referencia = typeof checkout.externalReference === 'string' ? checkout.externalReference : '';

  if (!checkoutId || !referencia.includes('|')) {
    console.error('[asaas:webhook] CHECKOUT_PAID sem checkout.id ou externalReference suficiente.');

    return json(200, { ok: true, ignorado: 'payload incompleto' });
  }

  // externalReference é o que o /api/checkout escreve: "<uuid do usuário>|<slug do plano>".
  const [usuarioId, slug] = referencia.split('|');

  if (!usuarioId || !PADRAO_UUID.test(usuarioId)) {
    console.error('[asaas:webhook] externalReference com id fora do formato de uuid.');

    return json(200, { ok: true, ignorado: 'referência inválida' });
  }

  const plano = planoPorSlug(slug);

  if (!plano) {
    console.error(`[asaas:webhook] plano desconhecido na referência: ${slug}`);

    return json(200, { ok: true, ignorado: 'plano desconhecido' });
  }

  try {
    // 1) Conferir na API que aquele checkout tem pagamento pago, do valor do plano.
    const lista = await pagamentosDoCheckout(checkoutId);

    if (!lista.ok) {
      console.error(`[asaas:webhook] não consegui conferir o checkout ${checkoutId}: ${lista.erro}`);

      return json(500, { ok: false, error: 'falha ao consultar o Asaas' });
    }

    const pago = lista.dados.find(
      (pagamento) => STATUS_PAGO.has(pagamento.status) && Math.abs(pagamento.value - plano.valor) < 0.01
    );

    if (!pago) {
      // O evento chegou, a API ainda não mostra o dinheiro. 500 para o Asaas
      // reenviar; quando confirmar, a mesma entrega seguinte ativa o plano.
      console.error(`[asaas:webhook] checkout ${checkoutId} sem pagamento confirmado de R$ ${plano.valor}.`);

      return json(500, { ok: false, error: 'pagamento ainda não confirmado' });
    }

    // 2) Escrever com a service role (o webhook não tem sessão de usuário).
    const admin = criarSupabaseAdmin();

    const { data: linha, error: erroLeitura } = await admin
      .from('estetica')
      .select('id, asaas_customer_id, plano_ativo')
      .eq('id', usuarioId)
      .maybeSingle();

    if (erroLeitura) {
      console.error(`[asaas:webhook] leitura da linha ${usuarioId} falhou: ${erroLeitura.message}`);

      return json(500, { ok: false, error: 'falha ao ler o banco' });
    }

    if (!linha) {
      console.error(`[asaas:webhook] linha ${usuarioId} não existe no banco.`);

      return json(200, { ok: true, ignorado: 'usuário sem cadastro' });
    }

    const registro = linha as { id: string; asaas_customer_id: string | null; plano_ativo: string | null };
    const clienteDoPagamento = typeof pago.customer === 'string' ? pago.customer : null;

    // Defesa: o pagamento precisa pertencer ao cliente que guardamos para este
    // usuário. Se divergir, alguém mexeu na referência — e não é ativando na sorte.
    if (registro.asaas_customer_id && clienteDoPagamento && registro.asaas_customer_id !== clienteDoPagamento) {
      console.error(`[asaas:webhook] cliente do pagamento não bate com o banco para ${usuarioId}.`);

      return json(500, { ok: false, error: 'cliente divergente' });
    }

    const { error: erroGravar } = await admin
      .from('estetica')
      .update({
        plano_ativo: plano.slug,
        asaas_customer_id: registro.asaas_customer_id ?? clienteDoPagamento,
      })
      .eq('id', usuarioId);

    if (erroGravar) {
      console.error(`[asaas:webhook] gravação falhou para ${usuarioId}: ${erroGravar.message}`);

      return json(500, { ok: false, error: 'falha ao gravar o plano' });
    }

    console.log(`[asaas:webhook] plano ${plano.slug} ativado para ${usuarioId} (pagamento ${pago.id}).`);

    // Reentrega do mesmo evento escreve os mesmos valores: a operação é idempotente.
    return json(200, { ok: true, ativado: plano.slug, pagamento: pago.id });
  } catch (erro) {
    console.error(`[asaas:webhook] exceção: ${(erro as Error).message}`);

    return json(500, { ok: false, error: 'erro interno' });
  }
};
