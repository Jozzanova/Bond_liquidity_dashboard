// Cloudflare Worker in front of the static site.
// Serves /api/fx (today's ECB reference rates, cached for 30 minutes) and hands everything else to the static assets.

const ECB = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml';
const TTL = 1800;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === '/api/fx') return fx(ctx);
    return env.ASSETS.fetch(request);
  },
};

async function fx(ctx) {
  const key = new Request('https://bond-liquidity.jskjeltorp.workers.dev/api/fx');
  let cache = null;
  try { cache = caches.default; const hit = await cache.match(key); if (hit) return hit; } catch (e) { cache = null; }
  try {
    const r = await fetch(ECB, { cf: { cacheTtl: TTL, cacheEverything: true }, headers: { 'user-agent': 'bond-liquidity-dashboard/1.0 (+https://bond-liquidity.jskjeltorp.workers.dev)' } });
    if (!r.ok) throw new Error('ECB answered ' + r.status);
    const xml = await r.text();
    const date = (xml.match(/time=['"](\d{4}-\d{2}-\d{2})['"]/) || [])[1];
    const per_eur = { EUR: 1 };
    for (const m of xml.matchAll(/currency=['"]([A-Z]{3})['"]\s+rate=['"]([\d.]+)['"]/g)) per_eur[m[1]] = +m[2];
    if (!date || !per_eur.USD) throw new Error('unexpected ECB file');
    const res = new Response(JSON.stringify({ date, per_eur, source: 'ECB euro foreign exchange reference rates', source_url: ECB, fetched: new Date().toISOString() }),
      { headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'public, max-age=' + TTL } });
    if (cache) ctx.waitUntil(cache.put(key, res.clone()));
    return res;
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e && e.message || e) }), { status: 502, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
  }
}
