import { useState } from 'react';
import type { SubmitEvent } from 'react';

export default function AuthForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLogin, setIsLogin] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    setMessage('');

    const endpoint = isLogin ? '/api/auth/login' : '/api/auth/signup';

    let result: Record<string, unknown>;

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      result = await response.json();
    } catch {
      setError('Não foi possível falar com o servidor. Tente novamente.');
      setLoading(false);
      return;
    }

    if (!result.ok) {
      setError(String(result.error ?? 'Não foi possível concluir.'));
      setLoading(false);
      return;
    }

    if (result.needsConfirmation) {
      setMessage('Criamos sua conta. Confirme o e-mail para entrar.');
      setLoading(false);
      return;
    }

    window.location.href = '/dashboard';
  };

  const inputClass =
    'bg-slate-950 border border-slate-700 text-white rounded-lg p-3 w-full focus:ring-2 focus:ring-emerald-500 placeholder:text-slate-400';

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 max-w-md w-full mx-auto shadow-2xl">
      <h1 className="font-display text-4xl font-bold uppercase tracking-tight text-center">
        {isLogin ? 'Acesse sua conta' : 'Crie sua conta'}
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
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Mínimo 6 caracteres"
            className={inputClass}
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}

        {message && <p className="text-sm text-emerald-400">{message}</p>}

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
          setMessage('');
        }}
        className="mt-6 w-full text-center text-sm font-semibold text-emerald-400 hover:text-emerald-300 transition-colors"
      >
        {isLogin ? 'Criar uma conta grátis' : 'Já tenho conta'}
      </button>
    </div>
  );
}
