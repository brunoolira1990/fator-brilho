// Aplica um arquivo .sql no banco do Supabase pela conexão direta
// (SUPABASE_DB_URL), sem depender de colar nada no painel web.
//
// O ganho é o controle da execução: o arquivo inteiro vai como um único pedido ao
// Postgres, que trata isso como transação implícita — se qualquer statement
// falhar, nada fica aplicado pela metade. E a migração vira algo versionado e
// repetível (`npm run db:migrate`), não um passo manual na cabeça de alguém.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import dotenv from 'dotenv';
import pg from 'pg';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.resolve(DIR, '..');
const ARQUIVO_SQL = path.join(RAIZ, 'supabase-services-gallery.sql');

// Caminho absoluto: o .env é lido de onde o script estiver sendo chamado.
const carregado = dotenv.config({ path: path.join(RAIZ, '.env') });

if (carregado.error) {
  console.error(`Não foi possível ler o .env: ${carregado.error.code}`);
  process.exit(1);
}

const connectionString = process.env.SUPABASE_DB_URL;

if (!connectionString) {
  console.error('Falta SUPABASE_DB_URL no .env. Sem ela não há como conectar.');
  process.exit(1);
}

let alvo;

try {
  alvo = new URL(connectionString);
} catch {
  console.error('SUPABASE_DB_URL não é uma URI de Postgres válida.');
  process.exit(1);
}

// A senha nunca vai para o console; só o endereço do projeto, para você conferir
// que está mexendo no banco certo.
const destino = `${alvo.hostname}:${alvo.port || '5432'}/${alvo.pathname.slice(1)}`;

// TLS com a verificação de cadeia desligada, e é assim que tem de ser para o
// Pooler do Supabase: ele apresenta um certificado assinado por uma CA interna
// ("self-signed certificate in certificate chain"), que o Node não conhece, então
// rejectUnauthorized: true derruba a conexão. O tráfego continua criptografado —
// o que deixa de acontecer é a validação da cadeia de certificados raiz, neste
// ambiente de desenvolvimento. Para rodar isso fora de dev, fixe a CA do Supabase
// em vez de desligar a verificação.
const opcoes = { connectionString, ssl: { rejectUnauthorized: false } };

let client;

try {
  console.log(`Conectando ao banco... (${destino})`);
  client = new pg.Client(opcoes);
  await client.connect();

  const sql = readFileSync(ARQUIVO_SQL, 'utf8');
  console.log(`Executando SQL... (${path.basename(ARQUIVO_SQL)}, ${sql.length} bytes, ${sql.split('\n').length} linhas)`);
  await client.query(sql);

  console.log('Sucesso!');
} catch (erro) {
  console.error(`Falhou: ${erro.message}`);

  if (/ECONNREFUSED|ETIMEDOUT|ENOTFOUND|ENOENT|EAI_/i.test(erro.code ?? '')) {
    console.error('A rede não alcançou o host. A conexão "direta" do Supabase é IPv6-only; em rede sem IPv6 use a URI do Pooler ("Session", porta 5432) na SUPABASE_DB_URL.');
  }

  if (/certificate|SSL/i.test(erro.message)) {
    console.error('O aperto de mão TLS falhou. A verificação de cadeia já está desligada aqui; se aparecer de novo, confira o host da SUPABASE_DB_URL e a porta (Pooler = 5432).');
  }

  process.exitCode = 1;
} finally {
  await client?.end();
}
