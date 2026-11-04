import { useState } from 'react';
import { abreCheckout } from '../lib/api';

type PlanoVitrine = { slug: string; nome: string; preco: string };

type Props = {
  /** Os três planos de src/lib/planos.ts; o preço exibido aqui é o mesmo cobrado. */
  planos: PlanoVitrine[];
};

/**
 * Botões de assinatura do painel. Chamam POST /api/checkout/ no Django e mandam o
 * usuário para o link que o Asaas devolveu — nada de montar página de pagamento aqui.
 *
 * O plano nunca é confiado a esta tela: a API valida o slug na whitelist e usa o
 * valor da mesma fonte. Trocar o botão no DevTools não muda o valor cobrado.
 *
 * A chamada passa por `src/lib/api.ts`, não por `fetch` cru, por dois motivos: o
 * endereço da API agora é outro projeto (PUBLIC_API_URL), e o cookie de sessão só
 * vai junto com `credentials: 'include'` — que só a camada centralizada garante.
 */
export default function AssinaturaPlanos({ planos }: Props) {
  const [enviando, setEnviando] = useState<string | null>(null);
  const [erro, setErro] = useState('');

  const assinar = async (slug: string) => {
    setEnviando(slug);
    setErro('');

    const resultado = await abreCheckout(slug);

    if (!resultado.ok) {
      // Sessão vencida: melhor voltar para o login do que mostrar erro opaco.
      if (resultado.status === 401) {
        window.location.href = '/login';
        return;
      }

      setErro(resultado.error);
      setEnviando(null);
      return;
    }

    // O link do Asaas é sempre HTTPS; conferir antes de navegar é o que impede um
    // corpo inesperado virar redirecionamento para onde não queremos.
    if (!resultado.link.startsWith('https://')) {
      setErro('Não foi possível abrir o checkout.');
      setEnviando(null);
      return;
    }

    // Deixamos o botão travado: o navegador está indo para o Asaas.
    window.location.href = resultado.link;
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3">
        {planos.map((plano) => (
          <button
            key={plano.slug}
            type="button"
            disabled={enviando !== null}
            onClick={() => void assinar(plano.slug)}
            className="px-4 py-2.5 rounded-lg text-sm font-bold text-white bg-[#075E54] hover:bg-[#064a42] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {enviando === plano.slug ? 'Abrindo checkout…' : `Assinar ${plano.nome} · ${plano.preco}`}
          </button>
        ))}
      </div>

      {erro ? (
        <p role="alert" className="text-sm text-red-400">
          {erro}
        </p>
      ) : null}
    </div>
  );
}
