import { useState } from 'react';
import type { SubmitEvent } from 'react';
import { entra, registra } from '../lib/api';

type Props = {
  /** Rótulo do plano escolhido na vitrine ('Essencial', 'Profissional', 'Premium'); vazio = sem plano. */
  plano?: string;
  /** 'cadastro' abre o formulário em modo criação de conta; omitido = login, como em /login. */
  modo?: 'login' | 'cadastro';
};

export default function AuthForm({ plano = '', modo = 'login' }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLogin, setIsLogin] = useState(modo !== 'cadastro');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    // Nada de olhar `response.status` aqui: `entra`/`registra` nunca atiram e nunca
    // devolvem texto cru — o que a tela mostra é sempre o `error` que o Django escreveu
    // em pt-BR (inclusive nos 401 e nos erros que o DRF gera sozinho).
    const resultado = isLogin ? await entra(email, password) : await registra(email, password);

    if (!resultado.ok) {
      setError(resultado.error);
      setLoading(false);
      return;
    }

    // Registro e login saem da API com o cookie do token já gravado (HttpOnly,
    // SameSite=None no domínio da API), então cair no painel não é "suposição": o
    // GET de /dashboard vai achar a sessão. Não há confirmação de e-mail no Django —
    // o `needsConfirmation` do Supabase morreu junto com o provedor.
    window.location.href = '/dashboard';
  };

  const inputClass =
    'bg-slate-950 border border-slate-700 text-white rounded-lg p-3 w-full focus:ring-2 focus:ring-emerald-500 placeholder:text-slate-400';

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-md w-full mx-auto shadow-2xl">
      <h1 className="font-display text-4xl font-bold uppercase tracking-tight text-center">
        {isLogin ? (
          'Acesse sua conta'
        ) : plano ? (
          `Criar conta para o Plano ${plano}`
        ) : (
          'Crie sua conta'
        )}
      </h1>

      <form onSubmit={handleSubmit} className="mt-8 space-y-4">
        <div>
          <label htmlFor="email" className="block text-sm text-slate-300 mb-2">
            E-mail
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="voce@exemplo.com"
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm text-slate-300 mb-2">
            Senha
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete={isLogin ? 'current-password' : 'new-password'}
            // 8 é o piso da API (core/serializers.py, validate_senha). No login não
            // vale bloquear no teclado: conta migrada do Supabase pode ter senha de 6,
            // e a checagem é da API — se ela negar, a mensagem aparece.
            minLength={isLogin ? undefined : 8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={isLogin ? 'Sua senha' : 'Mínimo 8 caracteres'}
            className={inputClass}
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="bg-[#075E54] hover:bg-[#064a42] text-white font-bold py-3 rounded-lg w-full transition disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading ? 'Aguarde…' : isLogin ? 'Entrar' : 'Cadastrar'}
        </button>
      </form>

      <button
        type="button"
        onClick={() => {
          setIsLogin((value) => !value);
          setError('');
        }}
        className="mt-6 w-full text-center text-sm font-semibold text-emerald-400 hover:text-emerald-300 transition-colors"
      >
        {isLogin ? 'Criar uma conta grátis' : 'Já tenho conta'}
      </button>
    </div>
  );
}
