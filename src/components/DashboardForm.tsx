import { useEffect, useState } from 'react';
import type { SubmitEvent } from 'react';

type Campos = {
  nome_negocio: string;
  whatsapp: string;
  instagram: string;
  endereco: string;
  cor_principal: string;
};

const CAMPOS_VAZIOS: Campos = {
  nome_negocio: '',
  whatsapp: '',
  instagram: '',
  endereco: '',
  cor_principal: '#075E54',
};

const inputClass =
  'bg-slate-950 border border-slate-700 text-white rounded-lg p-3 w-full focus:ring-2 focus:ring-emerald-500 placeholder:text-slate-400';

const rotulos: Record<keyof Campos, string> = {
  nome_negocio: 'Nome do negócio',
  whatsapp: 'WhatsApp',
  instagram: 'Instagram',
  endereco: 'Endereço',
  cor_principal: 'Cor principal',
};

export default function DashboardForm() {
  const [campos, setCampos] = useState<Campos>(CAMPOS_VAZIOS);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState('');
  const [erro, setErro] = useState('');

  useEffect(() => {
    let vivo = true;

    async function carregar() {
      try {
        const response = await fetch('/api/estetica');
        const result = await response.json();

        if (!vivo) return;

        if (!result.ok) {
          setErro(String(result.error ?? 'Não foi possível carregar seus dados.'));
        } else if (result.data) {
          setCampos({
            nome_negocio: result.data.nome_negocio ?? '',
            whatsapp: result.data.whatsapp ?? '',
            instagram: result.data.instagram ?? '',
            endereco: result.data.endereco ?? '',
            cor_principal: result.data.cor_principal ?? CAMPOS_VAZIOS.cor_principal,
          });
        }
      } catch {
        if (vivo) setErro('Não foi possível falar com o servidor.');
      }

      if (vivo) setCarregando(false);
    }

    carregar();

    return () => {
      vivo = false;
    };
  }, []);

  const salvar = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSalvando(true);
    setErro('');
    setMensagem('');

    try {
      const response = await fetch('/api/estetica', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(campos),
      });
      const result = await response.json();

      if (!result.ok) {
        setErro(String(result.error ?? 'Falha ao salvar.'));
        setSalvando(false);
        return;
      }

      setMensagem('Salvo com sucesso!');
    } catch {
      setErro('Não foi possível falar com o servidor.');
    }

    setSalvando(false);
  };

  const atualizar = (chave: keyof Campos, valor: string) => {
    setCampos((atual) => ({ ...atual, [chave]: valor }));
    setMensagem('');
  };

  if (carregando) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-2xl w-full mx-auto shadow-2xl">
        <p className="text-slate-400">Carregando seus dados…</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-2xl w-full mx-auto shadow-2xl">
      <h2 className="font-display text-3xl font-bold uppercase tracking-tight">Dados da sua estética</h2>

      <form onSubmit={salvar} className="mt-8 space-y-5">
        {(['nome_negocio', 'whatsapp', 'instagram'] as const).map((chave) => (
          <div key={chave}>
            <label htmlFor={chave} className="block text-sm text-slate-300 mb-2">
              {rotulos[chave]}
            </label>
            <input
              id={chave}
              type={chave === 'whatsapp' ? 'tel' : 'text'}
              value={campos[chave]}
              onChange={(event) => atualizar(chave, event.target.value)}
              placeholder={
                chave === 'whatsapp'
                  ? '5511999999999'
                  : chave === 'instagram'
                    ? 'suaestetica'
                    : 'Estética do Bruno'
              }
              className={inputClass}
            />
          </div>
        ))}

        <div>
          <label htmlFor="endereco" className="block text-sm text-slate-300 mb-2">
            {rotulos.endereco}
          </label>
          <textarea
            id="endereco"
            rows={3}
            value={campos.endereco}
            onChange={(event) => atualizar('endereco', event.target.value)}
            placeholder="Rua Exemplo, 123 - Moema, São Paulo - SP"
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor="cor_principal" className="block text-sm text-slate-300 mb-2">
            {rotulos.cor_principal}
          </label>
          <div className="flex items-center gap-4">
            <input
              id="cor_principal"
              type="color"
              value={campos.cor_principal}
              onChange={(event) => atualizar('cor_principal', event.target.value)}
              className="h-12 w-16 shrink-0 cursor-pointer rounded-lg border border-slate-700 bg-slate-950 p-1"
            />
            <span className="text-sm text-slate-400 font-mono">{campos.cor_principal}</span>
          </div>
        </div>

        {erro && (
          <p role="alert" className="text-sm text-red-400">
            {erro}
          </p>
        )}

        {mensagem && (
          <p role="status" className="text-sm text-emerald-400">
            {mensagem}
          </p>
        )}

        <button
          type="submit"
          disabled={salvando}
          className="bg-[#075E54] hover:bg-[#064a42] text-white font-bold py-3 rounded-lg w-full transition disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {salvando ? 'Salvando…' : 'Salvar'}
        </button>
      </form>
    </div>
  );
}
