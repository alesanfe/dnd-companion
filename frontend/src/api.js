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
  roll: (expression) =>
    req('/api/dice/roll', {
      method: 'POST',
      body: JSON.stringify({ expression }),
    }),
  /** Cambio de estado vía operación idempotente. */
  applyOp: (char, operationType, payload) =>
    req('/api/operations', {
      method: 'POST',
      body: JSON.stringify({
        operation_id: crypto.randomUUID(),
        entity_id: char.id,
        entity_version: char.version,
        client_id: CLIENT_ID,
        user_id: 'local',
        operation_type: operationType,
        payload,
      }),
    }),
}
