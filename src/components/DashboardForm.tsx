import { useEffect, useState } from 'react';
import type { SubmitEvent } from 'react';
import { gerarSlug } from '../lib/slug';
import { LIMITE_GALERIA, LIMITE_SERVICOS } from '../lib/listas';

type Campos = {
  nome_negocio: string;
  whatsapp: string;
  instagram: string;
  endereco: string;
  cor_principal: string;
  slug_estetica: string;
};

type ServicoEdicao = { nome: string; preco: string; descricao: string };
type GaleriaEdicao = { antes_url: string; depois_url: string; legenda: string };

const CAMPOS_VAZIOS: Campos = {
  nome_negocio: '',
  whatsapp: '',
  instagram: '',
  endereco: '',
  cor_principal: '#075E54',
  slug_estetica: '',
};

const SERVICO_VAZIO: ServicoEdicao = { nome: '', preco: '', descricao: '' };
const GALERIA_VAZIA: GaleriaEdicao = { antes_url: '', depois_url: '', legenda: '' };

const inputClass =
  'bg-slate-950 border border-slate-700 text-white rounded-lg p-3 w-full focus:ring-2 focus:ring-emerald-500 placeholder:text-slate-400';

const rotulos: Record<keyof Campos, string> = {
  nome_negocio: 'Nome do negócio',
  whatsapp: 'WhatsApp',
  instagram: 'Instagram',
  endereco: 'Endereço',
  cor_principal: 'Cor principal',
  slug_estetica: 'Link do site (slug)',
};

/**
 * A mesma shape nos dois sentidos: GET carrega, PUT devolve a linha já normalizada.
 * Tudo vem do banco como texto livre, então nada aqui é confiável: a linha é
 * sobreposta aos padrões e a cor só entra se for um #RRGGBB de verdade (o
 * <input type="color"> trava em qualquer outro valor).
 */
function preencherDaLinha(linha: Record<string, unknown>): Campos {
  const lida = (chave: keyof Campos) => (typeof linha[chave] === 'string' ? (linha[chave] as string) : '');
  const cor = lida('cor_principal');

  return {
    ...CAMPOS_VAZIOS,
    nome_negocio: lida('nome_negocio'),
    whatsapp: lida('whatsapp'),
    instagram: lida('instagram'),
    endereco: lida('endereco'),
    cor_principal: /^#[\da-f]{6}$/i.test(cor) ? cor : CAMPOS_VAZIOS.cor_principal,
    slug_estetica: lida('slug_estetica'),
  };
}

/** Linhas do banco -> estado do formulário. null no banco é campo vazio na tela. */
function servicosDaResposta(lista: unknown): ServicoEdicao[] {
  if (!Array.isArray(lista)) return [];

  return lista
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      nome: typeof item.nome === 'string' ? item.nome : '',
      preco: typeof item.preco === 'string' ? item.preco : '',
      descricao: typeof item.descricao === 'string' ? item.descricao : '',
    }));
}

function galeriaDaResposta(lista: unknown): GaleriaEdicao[] {
  if (!Array.isArray(lista)) return [];

  return lista
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      antes_url: typeof item.antes_url === 'string' ? item.antes_url : '',
      depois_url: typeof item.depois_url === 'string' ? item.depois_url : '',
      legenda: typeof item.legenda === 'string' ? item.legenda : '',
    }));
}

export default function DashboardForm() {
  const [campos, setCampos] = useState<Campos>(CAMPOS_VAZIOS);
  const [servicos, setServicos] = useState<ServicoEdicao[]>([]);
  const [galeria, setGaleria] = useState<GaleriaEdicao[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState('');
  const [erro, setErro] = useState('');
  const [pendencia, setPendencia] = useState('');

  useEffect(() => {
    let vivo = true;

    async function carregar() {
      try {
        const response = await fetch('/api/estetica');
        const result = await response.json();

        if (!vivo) return;

        if (!result.ok) {
          setErro(String(result.error ?? 'Não foi possível carregar seus dados.'));
        } else {
          if (result.data && typeof result.data === 'object') {
            setCampos(preencherDaLinha(result.data));
          }

          setServicos(servicosDaResposta(result.servicos));
          setGaleria(galeriaDaResposta(result.galeria));

          if (typeof result.pendencia === 'string') {
            setPendencia(result.pendencia);
          }
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
        body: JSON.stringify({ ...campos, servicos, galeria }),
      });
      const result = await response.json();

      if (!result.ok) {
        setErro(String(result.error ?? 'Falha ao salvar.'));
        setSalvando(false);
        return;
      }

      // O servidor normaliza slug, espaços e hifens e devolve as linhas com id e
      // ordem. Espelhar a resposta evita que a tela mostre uma coisa e o banco outra.
      if (result.data && typeof result.data === 'object') {
        setCampos(preencherDaLinha(result.data));
      }

      setServicos(servicosDaResposta(result.servicos));
      setGaleria(galeriaDaResposta(result.galeria));
      setPendencia(typeof result.pendencia === 'string' ? result.pendencia : '');

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

  const atualizarServico = (indice: number, campo: keyof ServicoEdicao, valor: string) => {
    setServicos((atual) => atual.map((item, i) => (i === indice ? { ...item, [campo]: valor } : item)));
    setMensagem('');
  };

  const atualizarGaleria = (indice: number, campo: keyof GaleriaEdicao, valor: string) => {
    setGaleria((atual) => atual.map((item, i) => (i === indice ? { ...item, [campo]: valor } : item)));
    setMensagem('');
  };

  // Preview usa a mesma função do endpoint: o link mostrado é o link que vai ser salvo.
  const slugPrevia = gerarSlug(campos.slug_estetica);

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
          <label htmlFor="slug_estetica" className="block text-sm text-slate-300 mb-2">
            {rotulos.slug_estetica}
          </label>
          <input
            id="slug_estetica"
            type="text"
            value={campos.slug_estetica}
            onChange={(event) => atualizar('slug_estetica', event.target.value)}
            placeholder="estetica-do-bruno"
            className={inputClass}
          />
          {slugPrevia ? (
            <p className="text-xs text-slate-400 mt-2">
              Seu site está em{' '}
              <a
                href={`/site/${slugPrevia}`}
                target="_blank"
                rel="noopener"
                className="font-mono text-emerald-400 underline hover:text-emerald-300 transition-colors"
              >
                /site/{slugPrevia}
              </a>
            </p>
          ) : (
            <p className="text-xs text-slate-400 mt-2">
              Pode escrever o nome inteiro que a gente transforma no link. Sem preencher, sua página não fica pública.
            </p>
          )}
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

        <div className="border-t border-slate-800 pt-8">
          <h3 className="font-display text-xl font-bold uppercase tracking-tight">Serviços</h3>
          <p className="text-sm text-slate-400 mt-2">
            Cada item vira um card na sua página. Máximo de {LIMITE_SERVICOS}.
          </p>

          <div className="mt-5 space-y-4">
            {servicos.length === 0 && <p className="text-sm text-slate-400">Nenhum serviço cadastrado ainda.</p>}

            {servicos.map((servico, indice) => (
              <div key={indice} className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                <div className="flex items-start justify-between gap-3">
                  <span className="text-sm text-slate-300 font-semibold">Serviço {indice + 1}</span>
                  <button
                    type="button"
                    onClick={() => setServicos((atual) => atual.filter((_, i) => i !== indice))}
                    className="text-sm text-slate-400 hover:text-red-400 transition-colors"
                  >
                    Remover
                  </button>
                </div>

                <div className="mt-3 space-y-3">
                  <div>
                    <label htmlFor={`servico-${indice}-nome`} className="block text-xs text-slate-300 mb-2">
                      Nome
                    </label>
                    <input
                      id={`servico-${indice}-nome`}
                      type="text"
                      value={servico.nome}
                      onChange={(event) => atualizarServico(indice, 'nome', event.target.value)}
                      placeholder="Vitrificação"
                      className={inputClass}
                    />
                  </div>

                  <div>
                    <label htmlFor={`servico-${indice}-preco`} className="block text-xs text-slate-300 mb-2">
                      Preço
                    </label>
                    <input
                      id={`servico-${indice}-preco`}
                      type="text"
                      value={servico.preco}
                      onChange={(event) => atualizarServico(indice, 'preco', event.target.value)}
                      placeholder="R$ 880"
                      className={inputClass}
                    />
                  </div>

                  <div>
                    <label htmlFor={`servico-${indice}-descricao`} className="block text-xs text-slate-300 mb-2">
                      Descrição
                    </label>
                    <textarea
                      id={`servico-${indice}-descricao`}
                      rows={2}
                      value={servico.descricao}
                      onChange={(event) => atualizarServico(indice, 'descricao', event.target.value)}
                      placeholder="Proteção cerâmica com garantia."
                      className={inputClass}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <button
            type="button"
            disabled={servicos.length >= LIMITE_SERVICOS}
            onClick={() => setServicos((atual) => [...atual, { ...SERVICO_VAZIO }])}
            className="mt-4 w-full rounded-lg border border-dashed border-slate-700 py-3 text-sm font-semibold text-slate-300 hover:border-emerald-500 hover:text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            + Adicionar serviço
          </button>
        </div>

        <div className="border-t border-slate-800 pt-8">
          <h3 className="font-display text-xl font-bold uppercase tracking-tight">Galeria</h3>
          <p className="text-sm text-slate-400 mt-2">
            Informe a URL de cada foto (Link público do Google Drive, seu CDN, etc.). Máximo de {LIMITE_GALERIA}.
          </p>

          <div className="mt-5 space-y-4">
            {galeria.length === 0 && <p className="text-sm text-slate-400">Nenhum antes e depois cadastrado ainda.</p>}

            {galeria.map((item, indice) => (
              <div key={indice} className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                <div className="flex items-start justify-between gap-3">
                  <span className="text-sm text-slate-300 font-semibold">Foto {indice + 1}</span>
                  <button
                    type="button"
                    onClick={() => setGaleria((atual) => atual.filter((_, i) => i !== indice))}
                    className="text-sm text-slate-400 hover:text-red-400 transition-colors"
                  >
                    Remover
                  </button>
                </div>

                <div className="mt-3 space-y-3">
                  <div>
                    <label htmlFor={`galeria-${indice}-antes`} className="block text-xs text-slate-300 mb-2">
                      URL do antes
                    </label>
                    <input
                      id={`galeria-${indice}-antes`}
                      type="text"
                      value={item.antes_url}
                      onChange={(event) => atualizarGaleria(indice, 'antes_url', event.target.value)}
                      placeholder="https://..."
                      className={inputClass}
                    />
                  </div>

                  <div>
                    <label htmlFor={`galeria-${indice}-depois`} className="block text-xs text-slate-300 mb-2">
                      URL do depois
                    </label>
                    <input
                      id={`galeria-${indice}-depois`}
                      type="text"
                      value={item.depois_url}
                      onChange={(event) => atualizarGaleria(indice, 'depois_url', event.target.value)}
                      placeholder="https://..."
                      className={inputClass}
                    />
                  </div>

                  <div>
                    <label htmlFor={`galeria-${indice}-legenda`} className="block text-xs text-slate-300 mb-2">
                      Legenda
                    </label>
                    <input
                      id={`galeria-${indice}-legenda`}
                      type="text"
                      value={item.legenda}
                      onChange={(event) => atualizarGaleria(indice, 'legenda', event.target.value)}
                      placeholder="Golf GTI — vitrificação"
                      className={inputClass}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <button
            type="button"
            disabled={galeria.length >= LIMITE_GALERIA}
            onClick={() => setGaleria((atual) => [...atual, { ...GALERIA_VAZIA }])}
            className="mt-4 w-full rounded-lg border border-dashed border-slate-700 py-3 text-sm font-semibold text-slate-300 hover:border-emerald-500 hover:text-white transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            + Adicionar foto
          </button>
        </div>

        {pendencia && (
          <p role="status" className="text-sm text-amber-300">
            {pendencia}
          </p>
        )}

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
