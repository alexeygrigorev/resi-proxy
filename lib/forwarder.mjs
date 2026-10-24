// Adapted from bot-skills/box-proxies/scripts/hetzner/start.mjs.
import { Server } from 'proxy-chain';
import { readFileSync, writeFileSync, renameSync } from 'node:fs';
const dir = process.env.RESI_INSTANCE_DIR;
const config = JSON.parse(readFileSync(`${dir}/config.json`, 'utf8'));
function failure(code) {
  // Never log library exceptions, request URLs, auth headers or upstream URLs.
  const record = { time: Date.now() / 1000, code };
  writeFileSync(`${dir}/failure.json.tmp`, JSON.stringify(record), { mode: 0o600 });
  renameSync(`${dir}/failure.json.tmp`, `${dir}/failure.json`);
  console.error(code);
}
const server = new Server({
  port: config.port, host: '127.0.0.1', verbose: false,
  prepareRequestFunction: () => ({
    requestAuthentication: false,
    upstreamProxyUrl: readFileSync(`${dir}/upstream.url`, 'utf8').trim(),
  }),
});
server.on('requestFailed', () => failure('UPSTREAM_REQUEST_FAILED'));
server.on('tunnelConnectFailed', ({ response, head }) => {
  const diagnostic = `${response.statusMessage} ${JSON.stringify(response.headers)} ${head?.toString()}`;
  failure(diagnostic.includes('NO_RAY') ? 'NO_RAY: no IP available for requested geo' :
    `UPSTREAM_HTTP_${response.statusCode}${response.statusCode === 400 ? ': possible NO_RAY (no IP available for geo)' : ''}`);
});
server.on('error', () => { failure('FORWARDER_ERROR'); process.exit(1); });
server.listen(() => console.log(`resi-proxy listening on 127.0.0.1:${config.port}`));
for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => server.close(true, () => process.exit(0)));
