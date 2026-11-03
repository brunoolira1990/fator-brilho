export const SLUG_MIN = 3;
export const SLUG_MAX = 63;

/**
 * "Estética do Bruno" -> "estetica-do-bruno".
 *
 * Morou aqui (e não dentro do endpoint) porque o formulário do painel precisa do
 * mesmo cálculo para mostrar o link antes de salvar. Server e client nunca
 * discutam qual é o endereço do site do cliente.
 */
export function gerarSlug(bruto: string): string {
  return bruto
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[\s_/]+/g, '-')
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Erro em pt-BR, ou null quando o slug pode virar link. Slug vazio também é null: o link é opcional. */
export function validarSlug(slug: string): string | null {
  if (slug === '') {
    return null;
  }

  if (slug.length < SLUG_MIN) {
    return `Link do site: use pelo menos ${SLUG_MIN} caracteres (ex: estetica-do-bruno).`;
  }

  if (slug.length > SLUG_MAX) {
    return `Link do site: use no máximo ${SLUG_MAX} caracteres.`;
  }

  if (!/^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$/.test(slug)) {
    return 'Link do site: use letras minúsculas, números e hífen, sem começar nem terminar com hífen.';
  }

  return null;
}
