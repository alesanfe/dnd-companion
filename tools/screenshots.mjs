#!/usr/bin/env node
/**
 * Regenera las capturas de docs/assets/ contra la app en marcha.
 *
 * Uso:
 *   npm i -g playwright   # o npx playwright
 *   $env:BASE_URL="http://localhost:5173"   # por defecto
 *   node tools/screenshots.mjs
 *
 * Espera backend + frontend corriendo. La semilla de demo
 * (campaña "La Ciénaga Sombría", combate, mapa con niebla) se crea
 * con tools/seed_demo.py la primera vez.
 */
import { chromium } from 'playwright';

const BASE = process.env.BASE_URL || 'http://localhost:5173';
const OUT = new URL('../docs/assets/', import.meta.url).pathname
  .replace(/^\/([A-Z]:)/, '$1');
const CAMPAIGN_ID = process.env.CAMPAIGN_ID ||
  '2575ee25263c4e6d986927c12e13e6c8';
const CHAR_2024 = process.env.CHAR_2024 ||
  '4e9e68fab9584ba98ab6649ba4d257f5';
const CHAR_2014 = process.env.CHAR_2014 ||
  '74ff9cdf5dfb437b803f1e903133fabf';
const ENTITY = process.env.ENTITY || 'srd-2014:fireball';

const desktop = { width: 1440, height: 900 };
const mobile = { width: 390, height: 844 };

const isVisible = (loc) => loc.first()
  .isVisible({ timeout: 2500 }).catch(() => false);

async function dismissTour(page) {
  const skip = page.getByRole('button', { name: /saltar|skip/i });
  if (await isVisible(skip)) await skip.click();
}

async function shot(page, name, path, { waitMs = 1000 } = {}) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
  await dismissTour(page);
  await page.waitForTimeout(waitMs);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`ok ${name}`);
}

async function dmPage(ctx, name, tabName) {
  const page = await ctx.newPage();
  await page.goto(`${BASE}/dm`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const tab = page.getByRole('tab', { name: tabName });
  if (await isVisible(tab)) await tab.first().click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`ok ${name}`);
  return page;
}

const SHOTS = [
  ['home', '/'],
  ['character-list', '/characters'],
  ['character-sheet', `/character/${CHAR_2024}`],
  ['character-sheet-2014', `/character/${CHAR_2014}`],
  ['character-actions', `/character/${CHAR_2024}/acciones`],
  ['character-spells', `/character/${CHAR_2014}/magia`],
  ['wizard', '/new'],
  ['settings', '/settings'],
];

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: desktop });
  // campaña activa para DmBoard + tour de ficha ya hecho
  await ctx.addInitScript((c) => {
    localStorage.setItem('dnd-last-campaign', JSON.stringify(c));
  }, { id: CAMPAIGN_ID, name: 'Campaña', at: Date.now() });
  const page = await ctx.newPage();

  for (const [name, path] of SHOTS) await shot(page, name, path);

  // inventario en pestaña Mochila
  await shot(page, 'character-inventory', `/character/${CHAR_2024}/inventario`);
  const mochila = page.getByRole('tab', { name: /mochila/i });
  if (await isVisible(mochila)) {
    await mochila.click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/character-inventory.png` });
  }

  // compendio filtrado por tipo spell + texto
  await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' });
  const sel = page.locator('select').first();
  await sel.selectOption({ label: 'spell' }).catch(() => {});
  await page.locator('input[type="text"], input[type="search"], input:not([type])')
    .first().fill('fireball');
  await page.getByRole('button', { name: /buscar|search/i }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/compendium.png` });
  console.log('ok compendium');

  // entidad + paleta de comandos
  await shot(page, 'content-entity', `/content/${ENTITY}`);
  await shot(page, 'command-palette', `/character/${CHAR_2024}`, { waitMs: 300 });
  await page.keyboard.press('Control+k');
  await page.waitForTimeout(600);
  const pal = page.locator('input[placeholder*="uscar"], input[placeholder*="earch"]');
  if (await isVisible(pal)) {
    await pal.first().fill('fire');
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/command-palette.png` });
    console.log('ok command-palette');
  }

  // campaña (pestaña Mundo)
  await shot(page, 'campaign-board', `/campaign/${CAMPAIGN_ID}`, { waitMs: 800 });
  const mundo = page.getByRole('button', { name: /mundo/i })
    .or(page.getByRole('tab', { name: /mundo/i }));
  if (await isVisible(mundo)) {
    await mundo.first().click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/campaign-board.png` });
  }

  await page.close();
  await dmPage(ctx, 'dm-board', /sesión|session/i);
  await dmPage(ctx, 'dm-combat', /combate|combat/i);
  const mapPage = await dmPage(ctx, 'dm-map', /^mapa$|^map$/i);

  // vista jugador del mapa
  const pv = mapPage.getByRole('button', { name: /vista jugador|player view/i });
  if (await isVisible(pv)) {
    await pv.click();
    await page.waitForTimeout(1000);
    await mapPage.screenshot({ path: `${OUT}/dm-map-player.png` });
    console.log('ok dm-map-player');
  }

  await ctx.close();

  // móvil (PWA)
  const mctx = await browser.newContext({ viewport: mobile,
                                        isMobile: true, hasTouch: true });
  const mp = await mctx.newPage();
  await mp.goto(`${BASE}/character/${CHAR_2024}`, { waitUntil: 'networkidle' });
  await dismissTour(mp);
  await mp.waitForTimeout(800);
  await mp.screenshot({ path: `${OUT}/sheet-mobile.png` });
  console.log('ok sheet-mobile');

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
