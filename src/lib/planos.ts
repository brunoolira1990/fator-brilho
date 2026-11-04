/**
 * Fonte única dos três planos. A vitrine (/) mostra `preco` e `itens`; o checkout
 * (/api/checkout) cobra `valor`. Um número só existe em um lugar — se o preço
 * mudar, muda aqui e a vitrine e a cobrança mudam juntas.
 *
 * Os itens são transcritos literalmente da spec do Bruno; se um recurso não está
 * nesta lista, ele não aparece na vitrine.
 *
 * `valor` vai para o Asaas em reais, como número JSON (147 = R$ 147,00).
 * Os slugs batem com o check constraint estetica_plano_ativo_check do banco
 * (supabase-asaas.sql) — as duas listas precisam continuar iguais.
 */
export type SlugPlano = 'essencial' | 'profissional' | 'premium';

export type Plano = {
  slug: SlugPlano;
  nome: string;
  /** Texto da vitrine. */
  preco: string;
  /** Valor numérico enviado ao Asaas. */
  valor: number;
  destaque: boolean;
  itens: string[];
};

export const PLANOS: Plano[] = [
  {
    slug: 'essencial',
    nome: 'Essencial',
    preco: 'R$ 97',
    valor: 97,
    destaque: false,
    itens: [
      'Site profissional de 1 página',
      'Botão de WhatsApp integrado',
      'Galeria Antes/Depois (até 5 fotos)',
      'Hospedagem e domínio inclusos',
      'Painel de controle básico',
    ],
  },
  {
    slug: 'profissional',
    nome: 'Profissional',
    preco: 'R$ 147',
    valor: 147,
    destaque: true,
    itens: [
      'Tudo do Essencial, mais:',
      'Galeria Antes/Depois ilimitada',
      'Lista de serviços personalizada',
      'Otimização do Google Meu Negócio',
      'Suporte via WhatsApp',
    ],
  },
  {
    slug: 'premium',
    nome: 'Premium',
    preco: 'R$ 297',
    valor: 297,
    destaque: false,
    itens: [
      'Tudo do Profissional, mais:',
      'Sistema de lembretes de manutenção (em breve)',
      'Página de agendamento (em breve)',
      'Atendimento prioritário',
    ],
  },
];

/**
 * Slug validado contra a whitelist. Nada de usar direto o que veio da URL: é isso
 * que impede um ?plano=<script> de virar texto na tela e é isso que garante que o
 * valor cobrado é um dos três do cardápio.
 */
export function planoPorSlug(bruto: unknown): Plano | null {
  if (typeof bruto !== 'string') return null;

  const slug = bruto.trim().toLowerCase() as SlugPlano;

  return PLANOS.find((plano) => plano.slug === slug) ?? null;
}

/** O nome do plano para o título da página de cadastro; null = sem plano. */
export function nomeDoPlano(bruto: unknown): string | null {
  return planoPorSlug(bruto)?.nome ?? null;
}
