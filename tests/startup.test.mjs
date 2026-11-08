import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
function command(executable, args, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { cwd: root, windowsHide: true, env });
    let output = '';
    child.stdout.on('data', chunk => output += chunk);
    child.stderr.on('data', chunk => output += chunk);
    child.once('error', reject);
    child.once('exit', code => resolve({ code, output }));
  });
}
async function listen(server, port) {
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
}
test('occupied port refuses startup and preserves the existing listener', async () => {
  const existing = createServer();
  await listen(existing, 5173);
  try {
    const result = await command(process.execPath, ['scripts/dev.mjs', '--smoke', '--no-open']);
    assert.equal(result.code, 1);
    assert.match(result.output, /Port 5173 is occupied/);
    assert.equal(existing.listening, true);
  } finally { await new Promise(resolve => existing.close(resolve)); }
});
test('actual backend + Vite + fixture become ready and release owned ports', { timeout: 120000 }, async () => {
  const result = await command(process.execPath, ['scripts/dev.mjs', '--fixture', '--smoke', '--no-open']);
  assert.equal(result.code, 0, result.output);
  assert.match(result.output, /AgentTestLab ready/);
  assert.match(result.output, /http:\/\/127.0.0.1:5173/);
  assert.match(result.output, /http:\/\/127.0.0.1:8000\/docs/);
  assert.match(result.output, /NON-AI fixture/);
  for (const port of [8000, 5173, 8001]) {
    const probe = createServer();
    await listen(probe, port);
    await new Promise(resolve => probe.close(resolve));
  }
});
test('failed database login does not echo connection credentials', async () => {
  const secret = 'startup-test-secret-do-not-echo';
  const result = await command(path.join(root, '.venv/Scripts/python.exe'), ['scripts/run_module.py', 'scripts/dev_preflight.py'], {
    ...process.env, DATABASE_URL: `mysql+pymysql://bad:${secret}@localhost:1/missing`,
  });
  assert.equal(result.code, 1);
  assert.match(result.output, /Database unavailable/);
  assert.ok(!result.output.includes(secret));
});
