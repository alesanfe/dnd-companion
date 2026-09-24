const CLIENT_ID = crypto.randomUUID()

async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ? JSON.stringify(err.detail) : res.statusText)
  }
  return res.json()
}

export const api = {
  listCharacters: () => req('/api/characters'),
  getCharacter: (id) => req(`/api/characters/${id}`),
  createCharacter: (name, ruleset = 'dnd5e-2014') =>
    req('/api/characters', {
      method: 'POST',
      body: JSON.stringify({ name, ruleset }),
    }),
  derivedStat: (id, stat, base = 10) =>
    req(`/api/characters/${id}/derived/${stat}?base=${base}`),
  search: (q, entityType) =>
    req(`/api/content/search?q=${encodeURIComponent(q)}` +
        (entityType ? `&entity_type=${entityType}` : '')),
  contentOptions: (entityType, ruleset = 'dnd5e-2014') =>
    req(`/api/content/options?entity_type=${entityType}&ruleset=${ruleset}`),
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
  /** Cambio de estado vía operación idempotente. */
  applyOp: (entity, operationType, payload, kind = 'character') =>
    req('/api/operations', {
      method: 'POST',
      body: JSON.stringify({
        operation_id: crypto.randomUUID(),
        entity_id: entity.id,
        entity_version: entity.version,
        client_id: CLIENT_ID,
        user_id: 'local',
        operation_type: operationType,
        entity_kind: kind,
        payload,
      }),
    }),
}
