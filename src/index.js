const KINDS = new Set(['program', 'log', 'settings']);
const UPSERT = `INSERT INTO records (kind,id,data,updated_at,deleted,server_time)
  VALUES (?1,?2,?3,?4,?5,?6)
  ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at,
    deleted=excluded.deleted, server_time=excluded.server_time
  WHERE excluded.updated_at > records.updated_at`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/sync') {
      if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });
      // Safety net: Cloudflare Access adds this header. Set ALLOW_NO_AUTH=1 only for local dev.
      if (!request.headers.get('Cf-Access-Jwt-Assertion') && env.ALLOW_NO_AUTH !== '1')
        return new Response('Sign-in required', { status: 401 });
      return sync(request, env);
    }
    return env.ASSETS.fetch(request);
  }
};

async function sync(request, env) {
  let body;
  try { body = await request.json(); } catch { return new Response('Bad JSON', { status: 400 }); }
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
