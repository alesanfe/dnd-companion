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

export async function markOp(id, status) {
  await db.pending_ops.update(id, { status })
}
