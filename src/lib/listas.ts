import { urlDeImagem } from './urls';

/** O que o painel manda no PUT. Tudo stringcão: o servidor decide o que é null. */
export type ServicoInput = { nome?: unknown; preco?: unknown; descricao?: unknown };
export type GaleriaInput = { antes_url?: unknown; depois_url?: unknown; legenda?: unknown };

/** O que vai para o banco, já limpo e com a ordem de exibição. */
export type LinhaServico = { nome: string; preco: string | null; descricao: string | null; ordem: number };
export type LinhaGaleria = {
  antes_url: string | null;
  depois_url: string | null;
  legenda: string | null;
  ordem: number;
};

export const LIMITE_SERVICOS = 12;
export const LIMITE_GALERIA = 12;

const NOMES = [
  { chave: 'nome', rotulo: 'Nome do serviço', max: 80, obrigatorio: true },
  { chave: 'preco', rotulo: 'Preço', max: 40, obrigatorio: false },
  { chave: 'descricao', rotulo: 'Descrição', max: 240, obrigatorio: false },
] as const;

const GALERIA = [
  { chave: 'antes_url', rotulo: 'URL do antes', max: 500, obrigatorio: false },
  { chave: 'depois_url', rotulo: 'URL do depois', max: 500, obrigatorio: false },
  { chave: 'legenda', rotulo: 'Legenda', max: 120, obrigatorio: false },
] as const;

export type ValidaçãoListas = { servicos: LinhaServico[] | null; galeria: LinhaGaleria[] | null } | { erro: string };

function limpa(valor: unknown): string | null {
  if (valor === undefined || valor === null) return null;
  if (typeof valor !== 'string') return null;
  const limpo = valor.trim();
  return limpo === '' ? null : limpo;
}

/**
 * null = a chave não veio no corpo; o endpoint deixa as listas como estão.
 * [] = o cliente esvaziou a lista de propósito; o endpoint apaga tudo.
 * Confundir os dois jogaria fora o trabalho de quem salvou só o endereço.
 */
function pegueLista(
  body: Record<string, unknown>,
  chave: 'servicos' | 'galeria',
  rotulo: string
): { erro: string } | { lista: unknown[] | null } {
  const valor = body[chave];

  if (valor === undefined || valor === null) {
    return { lista: null };
  }

  if (!Array.isArray(valor)) {
    return { erro: `${rotulo}: envie uma lista de itens.` };
  }

  return { lista: valor };
}

function normalizaItem(
  item: unknown,
  colunas: readonly { chave: string; rotulo: string; max: number; obrigatorio: boolean }[],
  numero: number,
  rotuloItem: string
): { erro: string } | { valores: Record<string, string | null> } {
  if (typeof item !== 'object' || item === null) {
    return { erro: `${rotuloItem} ${numero}: cada item precisa ser um objeto.` };
  }

  const bruto = item as Record<string, unknown>;
  const valores: Record<string, string | null> = {};

  for (const { chave, rotulo, max, obrigatorio } of colunas) {
    const campo = bruto[chave];

    if (campo !== undefined && campo !== null && typeof campo !== 'string') {
      return { erro: `${rotuloItem} ${numero}: ${rotulo} precisa ser um texto.` };
    }

    const limpo = limpa(campo);

    if (limpo && limpo.length > max) {
      return { erro: `${rotuloItem} ${numero}: ${rotulo} tem mais de ${max} caracteres.` };
    }

    if (obrigatorio && !limpo) {
      return { erro: `${rotuloItem} ${numero}: informe ${rotulo.toLowerCase()}.` };
    }

    valores[chave] = limpo;
  }

  return { valores };
}

export function normalizarListas(body: Record<string, unknown>): ValidaçãoListas {
  const saida: { servicos: LinhaServico[] | null; galeria: LinhaGaleria[] | null } = {
    servicos: null,
    galeria: null,
  };

  const pedidosServicos = pegueLista(body, 'servicos', 'Serviços');

  if ('erro' in pedidosServicos) {
    return { erro: pedidosServicos.erro };
  }

  const servicos = pedidosServicos.lista;

  if (servicos !== null) {
    if (servicos.length > LIMITE_SERVICOS) {
      return { erro: `Serviços: use no máximo ${LIMITE_SERVICOS} cards.` };
    }

    const linhas: LinhaServico[] = [];

    for (let i = 0; i < servicos.length; i++) {
      const r = normalizaItem(servicos[i], NOMES, i + 1, 'Serviço');

      if ('erro' in r) return { erro: r.erro };

      linhas.push({
        nome: r.valores.nome as string,
        preco: r.valores.preco,
        descricao: r.valores.descricao,
        ordem: i,
      });
    }

    saida.servicos = linhas;
  }

  const pedidosGaleria = pegueLista(body, 'galeria', 'Galeria');

  if ('erro' in pedidosGaleria) {
    return { erro: pedidosGaleria.erro };
  }

  const galeria = pedidosGaleria.lista;

  if (galeria !== null) {
    if (galeria.length > LIMITE_GALERIA) {
      return { erro: `Galeria: use no máximo ${LIMITE_GALERIA} pares de fotos.` };
    }

    const linhas: LinhaGaleria[] = [];

    for (let i = 0; i < galeria.length; i++) {
      const r = normalizaItem(galeria[i], GALERIA, i + 1, 'Galeria');

      if ('erro' in r) return { erro: r.erro };

      // O campo é de imagem: aceita http(s) e caminho do próprio site, e descarta
      // javascript:/data:text/html que alguém pudesse escrever direto no banco.
      const antes = urlDeImagem(r.valores.antes_url);
      const depois = urlDeImagem(r.valores.depois_url);

      if (r.valores.antes_url && !antes) {
        return { erro: `Galeria ${i + 1}: URL do antes inválida. Use http(s):// ou um caminho /...` };
      }

      if (r.valores.depois_url && !depois) {
        return { erro: `Galeria ${i + 1}: URL do depois inválida. Use http(s):// ou um caminho /...` };
      }

      if (!antes && !depois) {
        return { erro: `Galeria ${i + 1}: informe a URL da foto antes ou da depois.` };
      }

      linhas.push({ antes_url: antes, depois_url: depois, legenda: r.valores.legenda, ordem: i });
    }

    saida.galeria = linhas;
  }

  return saida;
}
