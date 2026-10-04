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
 *
 * Cobertura: las vistas base (SHOTS), pestañas de ficha y campaña,
 * temas (claro/sepia/alto contraste/dislexia/print), estados con
 * sesión iniciada (usuario demo auto-registrado), pasos del wizard,
 * errores, diálogos del mapa, vistas móviles y el barrido
 * responsive de docs/assets/resp/.
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

/** Pestaña con nombre ambiguo entre tablist y botones. */
async function clickTab(page, name) {
  const t = page.getByRole('tab', { name })
    .or(page.getByRole('button', { name }));
  if (await isVisible(t)) {
    await t.first().click();
    await page.waitForTimeout(1200);
    return true;
  }
  return false;
}

async function dmPage(ctx, name, tabName) {
  const page = await ctx.newPage();
  await page.goto(`${BASE}/dm`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await clickTab(page, tabName);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`ok ${name}`);
  return page;
}

/** Campaña activa en DmBoard + tour de ficha ya hecho. */
function seedInit(ctx) {
  return ctx.addInitScript((c) => {
    localStorage.setItem('dnd-last-campaign', JSON.stringify(c));
  }, { id: CAMPAIGN_ID, name: 'Campaña', at: Date.now() });
}

const SHOTS = [
  ['home', '/'],
  ['character-list', '/characters'],
  ['character-sheet', `/character/${CHAR_2024}`],
  ['character-sheet-2014', `/character/${CHAR_2014}`],
  ['character-actions', `/character/${CHAR_2024}/acciones`],
  ['character-spells', `/character/${CHAR_2014}/magia`],
  ['character-features', `/character/${CHAR_2024}/rasgos`],
  ['character-backstory', `/character/${CHAR_2024}/historia`],
  ['character-activity', `/character/${CHAR_2024}/actividad`],
  // alias legado: el PNG se llamó "history" pero muestra Actividad
  ['character-history', `/character/${CHAR_2024}/actividad`],
  ['wizard', '/new'],
  ['settings', '/settings'],
  ['settings-login', '/settings'],
  ['campaign-list', '/campaigns'],
  ['not-found', '/ruta-que-no-existe'],
  ['error-404-char', '/character/0000000000000000000000000000dead'],
];

/** Crea (o recupera) el usuario demo y devuelve {token, user_id}. */
async function ensureUser(ctx) {
  const creds = { username: 'capturas', password: 'capturas-demo-1234' };
  let r = await ctx.request.post(`${BASE}/api/auth/login`, { data: creds })
    .catch(() => null);
  if (!r?.ok())
    r = await ctx.request.post(`${BASE}/api/auth/register`, { data: creds })
      .catch(() => null);
  if (!r?.ok()) return null;
  return { ...(await r.json()), username: creds.username };
}

/** Clic genérico en una opción del wizard (radio-card o botón). */
async function pick(page, name) {
  const opt = page.getByRole('radio', { name })
    .or(page.getByRole('button', { name }));
  if (await isVisible(opt)) await opt.first().click();
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: desktop });
  await seedInit(ctx);
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

  // comparador de ediciones: marcar los dos primeros resultados
  const cmp = page.getByRole('checkbox', { name: /comparar|compare/i });
  if (await cmp.first().isVisible({ timeout: 2500 }).catch(() => false)) {
    await cmp.nth(0).check();
    await cmp.nth(1).check();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/compare.png` });
    console.log('ok compare');
  }

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

  // subida de nivel desplegada sobre la ficha
  await shot(page, 'level-up', `/character/${CHAR_2024}`);
  const lvl = page.getByRole('button', { name: /subir de nivel|level up/i });
  if (await isVisible(lvl)) {
    await lvl.first().click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/level-up.png` });
    console.log('ok level-up');
  }

  // campaña: Mundo, Mapa y Sesiones
  await shot(page, 'campaign-board', `/campaign/${CAMPAIGN_ID}`, { waitMs: 800 });
  if (await clickTab(page, /mundo|world/i)) {
    await page.screenshot({ path: `${OUT}/campaign-board.png` });
  }
  if (await clickTab(page, /^mapa$|^map$/i)) {
    await page.screenshot({ path: `${OUT}/campaign-mapa.png` });
    console.log('ok campaign-mapa');
  }
  if (await clickTab(page, /sesiones|sessions/i)) {
    await page.screenshot({ path: `${OUT}/campaign-sesiones.png` });
    console.log('ok campaign-sesiones');
  }

  // settings: tarjeta de métricas y conflictos de sync
  await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const met = page.getByRole('heading', { name: /uso local|local usage/i });
  if (await isVisible(met)) {
    await met.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/settings-metrics.png` });
    console.log('ok settings-metrics');
  }
  const sync = page.locator('#sync');
  if (await isVisible(sync)) {
    await sync.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/settings-conflicts.png` });
    console.log('ok settings-conflicts');
  }

  // wizard: pasos 1-4 (Clase → Revisión) tras nombrar el personaje
  await page.goto(`${BASE}/new`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const nameIn = page.getByLabel(/nombre/i)
    .or(page.locator('input').first());
  await nameIn.fill('Kaelen Sombrío');
  await page.getByRole('button', { name: /siguiente|next/i }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/wizard-step2.png` });
  console.log('ok wizard-step2');
  await pick(page, /^Rogue/);
  await page.getByRole('button', { name: /siguiente|next/i }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/wizard-step3.png` });
  console.log('ok wizard-step3');
  await pick(page, /^Human/);
  await pick(page, /^Soldier/);
  await page.getByRole('button', { name: /siguiente|next/i }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/wizard-step4.png` });
  console.log('ok wizard-step4');
  await page.getByRole('button', {
    name: /asignación recomendada|recommended/i }).first().click()
    .catch(() => {});
  await page.getByRole('button', { name: /revisar|review/i }).click()
    .catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/wizard-step5.png` });
  console.log('ok wizard-step5');

  await page.close();
  await dmPage(ctx, 'dm-board', /sesión|session/i);
  await dmPage(ctx, 'dm-combat', /combate|combat/i);
  await dmPage(ctx, 'dm-campaign', /campaña|campaign/i);
  const mapPage = await dmPage(ctx, 'dm-map', /^mapa$|^map$/i);

  // diálogo de token nuevo sobre el mapa
  const addTok = mapPage.getByRole('button', {
    name: /añadir token|add token/i });
  if (await isVisible(addTok)) {
    await addTok.first().click();
    await mapPage.waitForTimeout(600);
    await mapPage.screenshot({ path: `${OUT}/dm-map-dialog.png` });
    console.log('ok dm-map-dialog');
    await mapPage.getByRole('button', { name: /cancelar|cancel/i })
      .first().click().catch(() => {});
  }

  // vista jugador del mapa
  const pv = mapPage.getByRole('button', { name: /vista jugador|player view/i });
  if (await isVisible(pv)) {
    await pv.click();
    await mapPage.waitForTimeout(1000);
    await mapPage.screenshot({ path: `${OUT}/dm-map-player.png` });
    console.log('ok dm-map-player');
  }

  // temas y accesibilidad: preferencias en localStorage
  for (const [name, key, val] of [
    ['sheet-light', 'dc.theme', 'light'],
    ['sheet-sepia', 'dc.theme', 'sepia'],
    ['sheet-hc', 'dc.theme', 'hc'],
    ['sheet-dyslexia', 'dc.dyslexia', 'on'],
  ]) {
    const tctx = await browser.newContext({ viewport: desktop });
    await tctx.addInitScript(([k, v]) => localStorage.setItem(k, v), [key, val]);
    const tp = await tctx.newPage();
    await shot(tp, name, `/character/${CHAR_2024}`);
    await tctx.close();
  }

  // vista de impresión
  {
    const pctx = await browser.newContext({ viewport: desktop });
    const pp = await pctx.newPage();
    await pp.emulateMedia({ media: 'print' });
    await shot(pp, 'sheet-print', `/character/${CHAR_2024}`);
    await pctx.close();
  }

  // sesión iniciada: usuario demo auto-registrado
  const auth = await ensureUser(ctx);
  if (auth?.token) {
    const lctx = await browser.newContext({ viewport: desktop });
    await lctx.addInitScript((a) => {
      localStorage.setItem('dc.token', a.token);
      localStorage.setItem('dc.user', JSON.stringify(
        { user_id: a.user_id, username: a.username }));
    }, auth);
    const lp = await lctx.newPage();
    await shot(lp, 'settings-logged', '/settings');
    await shot(lp, 'character-sheet-logged', `/character/${CHAR_2024}`);
    await lctx.close();
  } else {
    console.log('aviso: sin usuario demo, omito settings-logged/' +
      'character-sheet-logged');
  }

  await ctx.close();

  // móvil (PWA)
  const mctx = await browser.newContext({ viewport: mobile,
                                        isMobile: true, hasTouch: true });
  await seedInit(mctx);
  const mp = await mctx.newPage();
  await mp.goto(`${BASE}/character/${CHAR_2024}`, { waitUntil: 'networkidle' });
  await dismissTour(mp);
  await mp.waitForTimeout(800);
  await mp.screenshot({ path: `${OUT}/sheet-mobile.png` });
  console.log('ok sheet-mobile');

  // FAB del nav móvil
  await mp.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await mp.waitForTimeout(600);
  const fab = mp.locator('.fab');
  if (await isVisible(fab)) {
    await fab.first().click();
    await mp.waitForTimeout(500);
    await mp.screenshot({ path: `${OUT}/fab-menu.png` });
    console.log('ok fab-menu');
  }

  // wizard móvil: entrada y paso Clase
  await mp.goto(`${BASE}/new`, { waitUntil: 'networkidle' });
  await mp.waitForTimeout(800);
  await mp.screenshot({ path: `${OUT}/wizard-390.png` });
  console.log('ok wizard-390');
  const mName = mp.getByLabel(/nombre/i).or(mp.locator('input').first());
  await mName.fill('Kaelen Sombrío');
  await mp.getByRole('button', { name: /siguiente|next/i }).click();
  await mp.waitForTimeout(800);
  await mp.screenshot({ path: `${OUT}/wizard-390-class.png` });
  console.log('ok wizard-390-class');
  await mctx.close();

  // barrido responsive de docs/assets/resp/
  const RESP_PAGES = [
    ['home', '/'],
    ['compendium', '/search'],
    ['sheet', `/character/${CHAR_2024}`],
    ['dm-map', '/dm'],
  ];
  for (const w of [320, 390, 768, 1024, 1366, 1920]) {
    const rctx = await browser.newContext({
      viewport: { width: w, height: 800 } });
    await seedInit(rctx);
    const rp = await rctx.newPage();
    for (const [name, path] of RESP_PAGES) {
      await rp.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
      await dismissTour(rp);
      if (name === 'dm-map') await clickTab(rp, /^mapa$|^map$/i);
      await rp.waitForTimeout(900);
      await rp.screenshot({ path: `${OUT}/resp/${name}-${w}.png` });
    }
    console.log(`ok resp ${w}px`);
    await rctx.close();
  }

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
