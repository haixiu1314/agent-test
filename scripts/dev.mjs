/** Start the backend and Vite in one terminal; stop only children owned by this launcher. */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = path.join(root, '.venv/Scripts/python.exe');
const runner = path.join(root, 'scripts/run_module.py');
const fixture = process.argv.includes('--fixture');
const children = new Set();
let stopping = false;

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  const kills = [...children].map(child => new Promise(resolve => {
    if (process.platform === 'win32') {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      killer.once('error', resolve); killer.once('exit', resolve);
    } else { child.kill('SIGTERM'); resolve(); }
  }));
  Promise.all(kills).then(() => process.exit(code));
}
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

function run(name, executable, args, cwd = root, persistent = false) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { cwd, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'], env: { ...process.env, PYTHONUNBUFFERED: '1' } });
    children.add(child);
    child.once('error', () => { children.delete(child); reject(new Error(`${name} could not start.`)); });
    child.once('exit', code => {
      children.delete(child);
      if (stopping) return;
      if (persistent) { console.error(`${name} exited (${code}). Stopping this dev session.`); stop(code || 1); }
      else if (code === 0) resolve();
      else reject(new Error(`${name} failed (${code}).`));
    });
    if (persistent) child.once('spawn', resolve);
  });
}

async function requirePort(port) {
  await new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', () => reject(new Error(`Port ${port} is occupied. Stop your previous dev session before retrying.`)));
    server.listen(port, '127.0.0.1', () => server.close(resolve));
  });
}

async function ready(url, options = {}) {
  for (let attempt = 0; attempt < 120 && !stopping; attempt++) {
    try { const response = await fetch(url, { ...options, signal: AbortSignal.timeout(1500) }); if (response.ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`Service did not become ready: ${url}`);
}

try {
  for (const required of [python, path.join(root, '.env'), path.join(root, 'frontend/node_modules/vite/bin/vite.js')]) {
    if (!existsSync(required)) throw new Error(`Missing prerequisite: ${required}`);
  }
  for (const port of fixture ? [8000, 5173, 8001] : [8000, 5173]) await requirePort(port);
  console.log('\nAgentTestLab: checking database and applying migrations...');
  await run('Database preflight', python, [runner, 'scripts/dev_preflight.py']);
  await run('Backend', python, [runner, 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8000', '--log-config', 'logging.json'], path.join(root, 'backend'), true);
  await ready('http://127.0.0.1:8000/health/ready');
  if (fixture) {
    await run('NON-AI protocol fixture', python, [runner, 'scripts/protocol_target.py'], root, true);
    await ready('http://127.0.0.1:8001/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input: 'startup readiness', mode: 'v1' }) });
  }
  const viteArgs = ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1'];
  if (!process.argv.includes('--no-open')) viteArgs.push('--open');
  await run('Frontend', process.execPath, viteArgs, path.join(root, 'frontend'), true);
  await ready('http://127.0.0.1:5173/');
  console.log('\nAgentTestLab ready\n  Web:      http://127.0.0.1:5173\n  API docs: http://127.0.0.1:8000/docs\n  Health:   http://127.0.0.1:8000/health/ready');
  if (fixture) console.log('  NON-AI fixture: http://127.0.0.1:8001 (POST only)');
  console.log('  Stop frontend/backend together: Ctrl+C\n');
  if (process.argv.includes('--smoke')) stop(0);
} catch (error) { console.error(`\nStartup failed: ${error.message}`); stop(1); }
