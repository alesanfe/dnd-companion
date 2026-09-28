import { enqueueOp, pendingOps, markOp } from './db.js'
import { getToken, currentUser } from './session.js'

const CLIENT_ID = crypto.randomUUID()

/* Alias ES→EN para que el FTS (contenido en inglés) encuentre
   términos comunes escritos en español. Frase exacta primero,
   luego palabra a palabra. */
const ES_PHRASES = {
  'bola de fuego': 'fireball', 'misil mágico': 'magic missile',
  'mano de mago': 'mage hand', 'rayo de escarcha': 'ray of frost',
  'proyectil de fuego': 'fire bolt', 'paso brumoso': 'misty step',
  'curar heridas': 'cure wounds', 'palabra curativa': 'healing word',
  'armadura de mago': 'mage armor', 'invisibilidad': 'invisibility',
  'volar': 'fly', 'teletransporte': 'teleport', 'escudo': 'shield',
  'bola de nieve': 'snowball swarm', 'luz': 'light',
  'orientación divina': 'guidance', 'taumaturgia': 'thaumaturgy',
  'druida': 'druid', 'pícaro': 'rogue', 'pícara': 'rogue',
}
const ES_WORDS = {
  guerrero: 'fighter', guerrera: 'fighter', mago: 'wizard',
  maga: 'wizard', clérigo: 'cleric', clériga: 'cleric',
  bárbaro: 'barbarian', bárbara: 'barbarian', paladín: 'paladin',
  paladina: 'paladin', explorador: 'ranger', exploradora: 'ranger',
  monje: 'monk', brujo: 'warlock', bruja: 'warlock', bardo: 'bard',
  hechicero: 'sorcerer', hechicera: 'sorcerer', dragón: 'dragon',
  goblin: 'goblin', trasgo: 'goblin', orco: 'orc', orca: 'orc',
  esqueleto: 'skeleton', zombi: 'zombie', vampiro: 'vampire',
  licantropo: 'werewolf', ogro: 'ogre', gigante: 'giant',
  demonio: 'demon', diablo: 'devil', elfo: 'elf', elfa: 'elf',
  enano: 'dwarf', enana: 'dwarf', mediano: 'halfling', gnomo: 'gnome',
  espada: 'sword', daga: 'dagger', arco: 'bow', hacha: 'axe',
  martillo: 'hammer', lanza: 'spear', ballesta: 'crossbow',
  armadura: 'armor', coraza: 'plate', cuero: 'leather',
  escamas: 'scale', malla: 'chain', poción: 'potion',
  pergamin: 'scroll', pergamino: 'scroll', anillo: 'ring',
  amuleto: 'amulet', capa: 'cloak', vara: 'rod', varita: 'wand',
  conjuro: 'spell', monstruo: 'monster', objeto: 'item',
  dote: 'feat', rasgo: 'trait', condición: 'condition',
}
function esTranslate(q) {
  const low = q.toLowerCase().trim()
  if (ES_PHRASES[low]) return ES_PHRASES[low]
  return low.split(/\s+/).map((w) => ES_WORDS[w] || w).join(' ')
}

function authHeaders() {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...opts,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    // detail puede ser string, dict o lista de errores 422 — el
    // usuario debe ver texto, no un blob JSON
    let msg = res.statusText
    if (typeof err.detail === 'string') msg = err.detail
    else if (Array.isArray(err.detail))
      msg = err.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    else if (err.detail) msg = JSON.stringify(err.detail)
    const e = new Error(msg)
    e.status = res.status
    throw e
  }
  return res.json()
}

/** Reenvía operaciones encoladas mientras estuvimos offline. */
export async function flushQueue() {
  const pending = await pendingOps()
  for (const op of pending) {
    try {
      // la entity_version se guardó al encolar: offline pasaron minutos
      // y otras ops pueden haberla movido — reenviarla tal cual
      // provocaría 'conflict' seguro, así que se refresca antes
      const url = op.payload.entity_kind === 'combat'
        ? `/api/combat/${op.payload.entity_id}`
        : `/api/characters/${op.payload.entity_id}`
      const cur = await fetch(url, { headers: authHeaders() })
      if (cur.ok)
        op.payload.entity_version = (await cur.json()).version
      const r = await fetch('/api/operations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(op.payload),
      })
      await markOp(op.id, r.ok ? 'synced' : 'rejected')
    } catch {
      return // sigue offline; reintentar luego
    }
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', flushQueue)
  // ops encoladas de una sesión anterior: sin esto solo salían al
  // próximo evento 'online' — al reabrir ya-online se quedaban
  // enterradas en IndexedDB
  if (navigator.onLine) flushQueue()
}

export const api = {
  register: (username, password) =>
    req('/api/auth/register', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  login: (username, password) =>
    req('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  me: () => req('/api/auth/me'),
  logout: () => req('/api/auth/logout', { method: 'POST' }),
  patchCharacter: (id, body) =>
    req(`/api/characters/${id}`, {
      method: 'PATCH', body: JSON.stringify(body) }),
  patchEntity: (campaignId, entityId, body) =>
    req(`/api/campaigns/${campaignId}/entities/${entityId}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  listSessions: (campaignId) =>
    req(`/api/campaigns/${campaignId}/sessions`),
  createSession: (campaignId, body) =>
    req(`/api/campaigns/${campaignId}/sessions`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  patchSession: (campaignId, sessionId, body) =>
    req(`/api/campaigns/${campaignId}/sessions/${sessionId}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  getCampaign: (id) => req(`/api/campaigns/${id}`),
  deleteCharacter: (id) =>
    req(`/api/characters/${id}`, { method: 'DELETE' }),
  deleteEntity: (campaignId, entityId) =>
    req(`/api/campaigns/${campaignId}/entities/${entityId}`,
        { method: 'DELETE' }),
  exportVtt: (campaignId) =>
    req(`/api/campaigns/${campaignId}/export-vtt`),
  addParty: (combatId) =>
    req(`/api/combat/${combatId}/add-party`, { method: 'POST' }),
  timeline: (campaignId) =>
    req(`/api/campaigns/${campaignId}/timeline`),
  listCharacters: (campaignId) =>
    req('/api/characters' +
        (campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}`
                    : '')),
  getCharacter: (id) => req(`/api/characters/${id}`),
  createCharacter: (name, ruleset = 'dnd5e-2014') =>
    req('/api/characters', {
      method: 'POST',
      body: JSON.stringify({ name, ruleset }),
    }),
  derivedStat: (id, stat, base = 10) =>
    req(`/api/characters/${id}/derived/${stat}?base=${base}`),
  search: (q, entityType, source, forClass) =>
    req(`/api/content/search?q=${encodeURIComponent(esTranslate(q))}` +
        (entityType ? `&entity_type=${entityType}` : '') +
        (source ? `&source=${encodeURIComponent(source)}` : '') +
        (forClass ? `&for_class=${encodeURIComponent(forClass)}` : '')),
  contentSources: () => req('/api/content/sources'),
  createHomebrew: (body) =>
    req('/api/content/homebrew', {
      method: 'POST', body: JSON.stringify(body) }),
  statblockPreview: (id) =>
    req(`/api/content/${encodeURIComponent(id)}/statblock`),
  entityRender: (id) =>
    req(`/api/content/${encodeURIComponent(id)}/render`),
  contentOptions: (entityType, ruleset = 'dnd5e-2014',
                   allSources = false) =>
    req(`/api/content/options?entity_type=${entityType}` +
        `&ruleset=${ruleset}` +
        (allSources ? '&all_sources=true' : '')),
  derivedAll: (id) => req(`/api/characters/${id}/derived`),
  getEntity: (id) => req(`/api/content/${encodeURIComponent(id)}`),
  compareEditions: (index) =>
    req(`/api/content/compare?index=${encodeURIComponent(index)}`),
  listCampaigns: () => req('/api/campaigns'),
  campaignEvents: (campaignId, limit = 100) =>
    req(`/api/campaigns/${campaignId}/events?limit=${limit}`),
  pendingRolls: (campaignId, characterIds) =>
    req(`/api/campaigns/${campaignId}/roll-requests/pending` +
        `?character_ids=${characterIds.join(',')}`),
  exportCampaign: (campaignId) =>
    req(`/api/campaigns/${campaignId}/export`),
  importCampaign: (bundle) =>
    req('/api/campaigns/import',
        { method: 'POST', body: JSON.stringify(bundle) }),
  startScene: (campaignId, sceneId) =>
    req(`/api/campaigns/${campaignId}/scenes/${sceneId}/start`,
        { method: 'POST' }),
  characterAttack: (characterId, itemName, mode = 'normal',
                    targetAc = null) =>
    req(`/api/operations/character/${characterId}/attack` +
        `?item_name=${encodeURIComponent(itemName)}&mode=${mode}` +
        (targetAc ? `&target_ac=${targetAc}` : ''), { method: 'POST' }),
  characterRoll: (characterId, expression, rollType = 'check',
                  useInspiration = false, secret = false) =>
    req(`/api/operations/character/${characterId}/roll` +
        `?expression=${encodeURIComponent(expression)}&roll_type=${rollType}` +
        `&use_inspiration=${useInspiration}&secret=${secret}`,
        { method: 'POST' }),
  roll: (expression) =>
    req('/api/dice/roll', {
      method: 'POST',
      body: JSON.stringify({ expression }),
    }),
  createFromOptions: (body) =>
    req('/api/characters/create-from-options', {
      method: 'POST', body: JSON.stringify(body),
    }),
  createCampaign: (name, ruleset = 'dnd5e-2014') =>
    req('/api/campaigns', {
      method: 'POST', body: JSON.stringify({ name, ruleset }),
    }),
  joinCampaign: (invite_code) =>
    req('/api/campaigns/join', {
      method: 'POST', body: JSON.stringify({ invite_code }),
    }),
  campaignState: (id) => req(`/api/campaigns/${id}/state`),
  createCombat: (name, campaign_id, ruleset = 'dnd5e-2014') =>
    req('/api/combat', {
      method: 'POST', body: JSON.stringify({ name, campaign_id, ruleset }),
    }),
  listCombats: (campaignId, status) =>
    req(`/api/combat?campaign_id=${campaignId}` +
        (status ? `&status=${status}` : '')),
  getCombat: (id, reveal = true) =>
    req(`/api/combat/${id}?reveal_hp=${reveal}`),
  deleteCombat: (id) =>
    req(`/api/combat/${id}`, { method: 'DELETE' }),
  awardXp: (id) =>
    req(`/api/combat/${id}/award-xp`, { method: 'POST' }),
  listPackages: () => req('/api/packages'),
  installPackage: (pkg) =>
    req('/api/packages/install',
        { method: 'POST', body: JSON.stringify(pkg) }),
  /** Cambio de estado vía operación idempotente. Si no hay red,
      encola en IndexedDB y se reenvía al volver (offline-first). */
  applyOp: async (entity, operationType, payload, kind = 'character') => {
    const op = {
      operation_id: crypto.randomUUID(),
      entity_id: entity.id,
      entity_version: entity.version,
      client_id: CLIENT_ID,
      user_id: currentUser()?.user_id || 'local',
      operation_type: operationType,
      entity_kind: kind,
      payload,
    }
    try {
      return await req('/api/operations', {
        method: 'POST', body: JSON.stringify(op),
      })
    } catch (e) {
      if (e.name === 'TypeError' || !navigator.onLine) {
        await enqueueOp({ entity_id: entity.id, payload: op })
        return { queued: true, version: entity.version }
      }
      throw e
    }
  },
  opHistory: (entityId) => req(`/api/operations?entity_id=${entityId}`),
  opConflicts: () => req('/api/operations/conflicts'),
  retryConflict: (opId) =>
    req(`/api/operations/conflicts/${opId}/retry`, { method: 'POST' }),
  dismissConflict: (opId) =>
    req(`/api/operations/conflicts/${opId}/dismiss`, { method: 'POST' }),
  undoOp: (opId) => req(`/api/operations/undo/${opId}`, { method: 'POST' }),
  exportCharacter: (id) => req(`/api/characters/${id}/export`),
  importCharacter: (character) => req('/api/characters/import', {
    method: 'POST', body: JSON.stringify({ character }),
  }),
  combatDifficulty: (combatId) =>
    req(`/api/encounters/for-combat/${combatId}`),
  commandSearch: (q, source) =>
    req(`/api/content/command?q=${encodeURIComponent(q)}` +
        (source ? `&source=${encodeURIComponent(source)}` : '')),
  characterActions: (id) => req(`/api/characters/${id}/actions`),
  rulesTables: () => req('/api/rules/tables'),
  rulesAsk: (question, ruleset) =>
    req('/api/rules/ask', {
      method: 'POST',
      body: JSON.stringify({ question, ruleset }),
    }),
  encounterDifficulty: (party_levels, monster_crs) =>
    req('/api/encounters/difficulty', {
      method: 'POST',
      body: JSON.stringify({ party_levels, monster_crs }),
    }),
  listEntities: (campaignId, kind, viewer = 'dm') =>
    req(`/api/campaigns/${campaignId}/entities?viewer=${viewer}` +
        (kind ? `&kind=${kind}` : '')),
  createEntity: (campaignId, body) =>
    req(`/api/campaigns/${campaignId}/entities`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  revealEntity: (campaignId, entityId) =>
    req(`/api/campaigns/${campaignId}/entities/${entityId}/reveal`,
        { method: 'POST' }),
  createRelationship: (campaignId, body) =>
    req(`/api/campaigns/${campaignId}/relationships`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  listMembers: (campaignId) =>
    req(`/api/campaigns/${campaignId}/members`),
  deleteRelationship: (campaignId, relId) =>
    req(`/api/campaigns/${campaignId}/relationships/${relId}`,
        { method: 'DELETE' }),
  listRelationships: (campaignId, entityId, viewer = 'dm') =>
    req(`/api/campaigns/${campaignId}/relationships?viewer=${viewer}` +
        (entityId ? `&entity_id=${entityId}` : '')),
  requestRoll: (campaignId, body) =>
    req(`/api/campaigns/${campaignId}/roll-request`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  transferItem: (fromId, toId, itemId, quantity) =>
    req('/api/inventory/transfer', {
      method: 'POST',
      body: JSON.stringify({
        transfer_id: crypto.randomUUID(),
        from_character: fromId, to_character: toId,
        item_id: itemId, quantity,
      }),
    }),
}
