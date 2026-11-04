/** Contato da agência (Fator Brilho), não do cliente. O número do cliente fica no banco. */
export const WHATSAPP_AGENCIA = '5511942733689';

export const MENSAGEM_ATIVACAO = 'Olá! Quero ativar minha assinatura do Fator Brilho SaaS.';

export function waAgencia(mensagem: string = MENSAGEM_ATIVACAO): string {
  return `https://wa.me/${WHATSAPP_AGENCIA}?text=${encodeURIComponent(mensagem)}`;
}
