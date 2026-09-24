import { enqueueOp, pendingOps, markOp } from './db.js'
import { getToken, currentUser } from './session.js'

const CLIENT_ID = crypto.randomUUID()

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
    throw new Error(err.detail ? JSON.stringify(err.detail) : res.statusText)
  }
  return res.json()
}

/** Reenvía operaciones encoladas mientras estuvimos offline. */
export async function flushQueue() {
  const pending = await pendingOps()
  for (const op of pending) {
    try {
      const r = await fetch('/api/operations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
  timeline: (campaignId) =>
    req(`/api/campaigns/${campaignId}/timeline`),
  listCharacters: () => req('/api/characters'),
  getCharacter: (id) => req(`/api/characters/${id}`),
  createCharacter: (name, ruleset = 'dnd5e-2014') =>
    req('/api/characters', {
      method: 'POST',
      body: JSON.stringify({ name, ruleset }),
    }),
  derivedStat: (id, stat, base = 10) =>
    req(`/api/characters/${id}/derived/${stat}?base=${base}`),
  search: (q, entityType, source) =>
    req(`/api/content/search?q=${encodeURIComponent(q)}` +
        (entityType ? `&entity_type=${entityType}` : '') +
        (source ? `&source=${encodeURIComponent(source)}` : '')),
  contentSources: () => req('/api/content/sources'),
  statblockPreview: (id) =>
    req(`/api/content/${encodeURIComponent(id)}/statblock`),
  contentOptions: (entityType, ruleset = 'dnd5e-2014') =>
    req(`/api/content/options?entity_type=${entityType}&ruleset=${ruleset}`),
  derivedAll: (id) => req(`/api/characters/${id}/derived`),
  getEntity: (id) => req(`/api/content/${encodeURIComponent(id)}`),
  campaignEvents: (campaignId, limit = 100) =>
    req(`/api/campaigns/${campaignId}/events?limit=${limit}`),
  exportCampaign: (campaignId) =>
    req(`/api/campaigns/${campaignId}/export`),
  startScene: (campaignId, sceneId) =>
    req(`/api/campaigns/${campaignId}/scenes/${sceneId}/start`,
        { method: 'POST' }),
  characterAttack: (characterId, itemName) =>
    req(`/api/operations/character/${characterId}/attack` +
        `?item_name=${encodeURIComponent(itemName)}`, { method: 'POST' }),
  characterRoll: (characterId, expression, rollType = 'check',
                  useInspiration = false) =>
    req(`/api/operations/character/${characterId}/roll` +
        `?expression=${encodeURIComponent(expression)}&roll_type=${rollType}` +
        `&use_inspiration=${useInspiration}`,
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
  getCombat: (id, reveal = true) =>
    req(`/api/combat/${id}?reveal_hp=${reveal}`),
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
  undoOp: (opId) => req(`/api/operations/undo/${opId}`, { method: 'POST' }),
  exportCharacter: (id) => req(`/api/characters/${id}/export`),
  importCharacter: (character) => req('/api/characters/import', {
    method: 'POST', body: JSON.stringify({ character }),
  }),
  commandSearch: (q) =>
    req(`/api/content/command?q=${encodeURIComponent(q)}`),
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
  listRelationships: (campaignId, entityId) =>
    req(`/api/campaigns/${campaignId}/relationships` +
        (entityId ? `?entity_id=${entityId}` : '')),
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
