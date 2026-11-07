const KINDS = new Set(['program', 'log', 'settings']);
const UPSERT = `INSERT INTO records (kind,id,data,updated_at,deleted,server_time)
  VALUES (?1,?2,?3,?4,?5,?6)
  ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at,
    deleted=excluded.deleted, server_time=excluded.server_time
  WHERE excluded.updated_at > records.updated_at`;

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let d = 0; for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
let ready = false;
async function ensureSchema(env) {
  if (ready) return;
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS records (
      kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
      updated_at INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
      server_time INTEGER NOT NULL, PRIMARY KEY (kind, id))`),
    env.DB.prepare('CREATE INDEX IF NOT EXISTS idx_server_time ON records(server_time)')
  ]);
  ready = true;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/sync') {
      if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
      // Safety net: Cloudflare Access adds this header. Set ALLOW_NO_AUTH=1 only for local dev.
      // Allowed if: Cloudflare Access signed the request, OR the caller sends the SYNC_KEY secret as a Bearer token.
      const auth = request.headers.get('Authorization') || '';
      const secret = (env.SYNC_KEY || '').trim(), token = auth.replace(/^Bearer\s+/i, '').trim();
      const keyOk = !!secret && safeEqual(token, secret);
      if (!keyOk && !request.headers.get('Cf-Access-Jwt-Assertion') && env.ALLOW_NO_AUTH !== '1')
        return Response.json({ error: !env.SYNC_KEY ? 'SYNC_KEY is not set on the Worker (secret missing or not deployed)'
          : !auth ? 'No passcode was sent by the app'
          : 'Passcode does not match the SYNC_KEY secret' }, { status: 401 });
      return sync(request, env);
    }
    return env.ASSETS.fetch(request);
  }
};

async function sync(request, env) {
  let body;
  try { body = await request.json(); } catch { return new Response('Bad JSON', { status: 400 }); }
  await ensureSchema(env);
  const { since = 0, changes = [], pull = true } = body;
  const now = Date.now();
  const stmts = [];
  for (const r of Array.isArray(changes) ? changes : []) {
    if (!r || !KINDS.has(r.kind) || typeof r.id !== 'string' || !Number.isFinite(r.updatedAt)) continue;
    const json = JSON.stringify(r);
    if (json.length > 1_000_000) continue; // D1 row size guard
    stmts.push(env.DB.prepare(UPSERT).bind(r.kind, r.id, json, r.updatedAt, r.deleted ? 1 : 0, now));
  }
  for (let i = 0; i < stmts.length; i += 100) await env.DB.batch(stmts.slice(i, i + 100));
  if (!pull) return Response.json({ serverTime: now, records: [] });
  const { results } = await env.DB.prepare('SELECT data FROM records WHERE server_time > ?1')
    .bind(Math.max(0, Number(since) - 2000)).all();
  return Response.json({ serverTime: now, records: results.map(r => JSON.parse(r.data)) });
}
