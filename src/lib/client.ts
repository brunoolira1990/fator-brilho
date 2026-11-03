import fs from 'node:fs';
import path from 'node:path';
import { ClientDataSchema, type ClientData } from './schema';

export function getClientData(slug?: string): ClientData {
  const clientSlug = slug || process.env.CLIENT_SLUG || 'estetica-exemplo';
  const dataPath = path.resolve(process.cwd(), 'clients', clientSlug, 'data.json');

  if (!fs.existsSync(dataPath)) {
    throw new Error(`❌ Arquivo de dados não encontrado: ${clientSlug}`);
  }

  const rawData = JSON.parse(fs.readFileSync(dataPath, 'utf-8'));
  const parsedData = ClientDataSchema.safeParse(rawData);

  if (!parsedData.success) {
    console.error(parsedData.error.format());
    throw new Error(`Dados inválidos`);
  }

  return parsedData.data;
}
