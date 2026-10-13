/**
 * Loopback reverse proxy for the ONT admin UI.
 *
 * e2e allows a plain-HTTP base URL only on a loopback host, so the runner
 * opens http://127.0.0.1:{port}/admin/login.asp and this process forwards
 * that path to the device (ONT_ORIGIN, default http://192.168.1.1).
 * It listens on 127.0.0.1 only and forwards to that single origin.
 */
import http from 'node:http';
import https from 'node:https';

const HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'proxy-connection',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
]);

const METHODS = new Set(['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH']);

function readPort() {
  const index = process.argv.indexOf('--port');
  const raw = index === -1 ? '' : process.argv[index + 1];
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    console.error('usage: node scripts/ont-proxy.mjs --port <1-65535>');
    process.exit(1);
  }
  return port;
}

function readOrigin() {
  const raw = process.env.ONT_ORIGIN ?? 'http://192.168.1.1';
  let url;
  try {
    url = new URL(raw);
  } catch {
    console.error(`ONT_ORIGIN is not a URL: ${raw}`);
    process.exit(1);
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    console.error(`ONT_ORIGIN must be http or https: ${raw}`);
    process.exit(1);
  }
  if (url.username !== '' || url.password !== '') {
    console.error('ONT_ORIGIN must not include userinfo');
    process.exit(1);
  }
  return url;
}

const port = readPort();
const origin = readOrigin();
const transport = origin.protocol === 'https:' ? https : http;
const upstreamPort = origin.port === ''
  ? (origin.protocol === 'https:' ? 443 : 80)
  : Number(origin.port);

function publicOrigin() {
  return `http://127.0.0.1:${port}`;
}

function originsToRewrite() {
  const values = new Set([origin.origin]);
  if (origin.port === '') {
    const explicit = origin.protocol === 'https:' ? 443 : 80;
    values.add(`${origin.protocol}//${origin.hostname}:${explicit}`);
  }
  return [...values];
}

/** ASCII-only replacement. Latin-1 keeps GB2312/GBK bytes intact. */
function rewriteText(value) {
  const pub = publicOrigin();
  const pubHost = `127.0.0.1:${port}`;
  let text = value;
  for (const from of originsToRewrite()) text = text.split(from).join(pub);
  text = text.split(`//${origin.host}`).join(`//${pubHost}`);
  return text;
}

function rewriteCookie(cookie) {
  return cookie
    .replace(/;\s*domain=[^;]*/gi, '')
    .replace(/;\s*secure\b/gi, '');
}

function isText(contentType) {
  const type = contentType.split(';')[0].trim();
  return /^(text\/|application\/(?:xhtml\+xml|xml|json|javascript|x-javascript|ecmascript)|application\/.*\+json)/i.test(type);
}

function filterRequestHeaders(incoming) {
  const headers = {};
  for (const [name, value] of Object.entries(incoming)) {
    if (value === undefined || HOP.has(name.toLowerCase()) || name.toLowerCase() === 'host') continue;
    headers[name] = value;
  }
  headers.host = origin.host;
  headers['accept-encoding'] = 'identity';
  return headers;
}

function filterResponseHeaders(incoming) {
  /** @type {Record<string, string | string[] | undefined>} */
  const headers = {};
  for (const [name, value] of Object.entries(incoming)) {
    if (value === undefined) continue;
    const lower = name.toLowerCase();
    if (HOP.has(lower)) continue;
    if (lower === 'set-cookie') {
      const list = Array.isArray(value) ? value : [String(value)];
      headers[name] = list.map((item) => rewriteCookie(item));
      continue;
    }
    if (typeof value === 'string') {
      headers[name] = rewriteText(value);
      continue;
    }
    if (Array.isArray(value)) {
      headers[name] = value.map((item) => rewriteText(String(item)));
      continue;
    }
  }
  return headers;
}

const server = http.createServer((req, res) => {
  const rawUrl = req.url ?? '/';
  if (!METHODS.has(req.method ?? '') || !rawUrl.startsWith('/')) {
    res.writeHead(400, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('only same-origin path requests are forwarded');
    return;
  }

  const upstream = transport.request({
    protocol: origin.protocol,
    hostname: origin.hostname,
    port: upstreamPort,
    method: req.method,
    path: rawUrl,
    headers: filterRequestHeaders(req.headers),
    signal: AbortSignal.timeout(8_000),
  }, (up) => {
    const headers = filterResponseHeaders(up.headers);
    const encoding = String(up.headers['content-encoding'] ?? 'identity');
    const type = String(up.headers['content-type'] ?? '');
    if (encoding.toLowerCase() !== 'identity' || !isText(type)) {
      res.writeHead(up.statusCode ?? 502, headers);
      up.pipe(res);
      return;
    }
    const chunks = [];
    up.on('data', (chunk) => chunks.push(chunk));
    up.on('end', () => {
      const body = Buffer.from(rewriteText(Buffer.concat(chunks).toString('latin1')), 'latin1');
      delete headers['content-length'];
      delete headers['content-encoding'];
      res.writeHead(up.statusCode ?? 502, headers);
      res.end(body);
    });
  });

  upstream.on('error', (error) => {
    if (res.headersSent) {
      res.destroy(error);
      return;
    }
    res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
    res.end(`ONT unreachable: ${error.message}`);
  });
  req.pipe(upstream);
});

server.listen(port, '127.0.0.1', () => {
  console.log(`ONT proxy http://127.0.0.1:${port} -> ${origin.origin}`);
});
