import Dexie from 'dexie'

// Cola offline: operaciones pendientes de sincronizar.
// pending|synced|rejected|conflict
export const db = new Dexie('dnd-companion')

db.version(1).stores({
  pending_ops: '++id, entity_id, status, created_at',
  char_cache: 'id, updated_at',
})

export async function enqueueOp(op) {
  await db.pending_ops.add({ ...op, status: 'pending',
                             created_at: Date.now() })
}

export async function pendingOps() {
  return db.pending_ops.where('status').equals('pending').toArray()
}

/** Ops rechazadas por el servidor al reenviar — el usuario debe ver
    qué se perdió, no solo lo pendiente (antes se perdían en silencio
    hasta la poda). */
export async function deadOps() {
  return db.pending_ops.where('status').equals('rejected').toArray()
}

export async function markOp(id, status) {
  await db.pending_ops.update(id, { status })
  // nada lee las filas 'synced'/'discarded' — borrarlas o IndexedDB
  // crece sin límite con cada flush
  if (status === 'synced' || status === 'discarded')
    await db.pending_ops.delete(id)
}

/** Poda de ops muertas (>30d): las 'rejected' tampoco las muestra
    nadie, así que no merecen quedarse para siempre. */
export async function pruneOps() {
  const cutoff = Date.now() - 30 * 86400e3
  await db.pending_ops
    .filter((o) => o.status !== 'pending' && o.created_at < cutoff)
    .delete()
}

/** Descarta una op encolada (el usuario decide no reenviarla). */
export async function dropOp(id) {
  await db.pending_ops.delete(id)
}
