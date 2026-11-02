// node render.mjs in.html out.pdf — HTML → PDF (A4) через Playwright/Chromium.
// Ищет Playwright и локально, и глобально (через require). Если Chromium не найден:
// CHROMIUM_PATH=/путь/к/chromium node render.mjs ...
import { resolve } from 'node:path';
import { createRequire } from 'node:module';

async function loadPlaywright() {
  try { return await import('playwright'); } catch {}
  const require = createRequire(import.meta.url);
  try { return require('playwright'); } catch {}
  const { execSync } = await import('node:child_process');
  const root = execSync('npm root -g').toString().trim();
  return require(root + '/playwright');
}

const pw = await loadPlaywright();
const opts = process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {};
const browser = await pw.chromium.launch(opts);
const page = await browser.newPage();
await page.goto('file://' + resolve(process.argv[2]), { waitUntil: 'networkidle' });
await page.pdf({ path: process.argv[3], format: 'A4', printBackground: true });
await browser.close();
