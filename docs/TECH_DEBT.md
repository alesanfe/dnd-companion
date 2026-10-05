# Registro de deuda técnica

Deudas **conscientes**: decisiones tomadas a sabiendas de su coste.
Cada entrada indica riesgo, coste de no corregir y plan. Revisar por
release.

| ID | Deuda | Tipo | Riesgo | Plan |
|---|---|---|---|---|
| TD-1 | Cobertura frontend baja (18 tests vs 299 de backend) | testing | regresiones de UI detectadas por uso, no por suite | capturas por `tools/screenshots.mjs` + tests por bug — subir vitest al tocar cada página |
| TD-2 | Import de 5etools solo local (NON-FREE) | licencias/datos | el compendio completo no se puede redistribuir; cada usuario importa el suyo | por diseño legal: `data/` gitignored + `is_redistributable` por entidad — documentado en AGENTS.md |
| TD-3 | Conflictos de optimistic locking se resuelven a mano (reintentar/descartar) | datos | ediciones concurrentes pisan trabajo si el usuario elige mal | resolución asistida en Ajustes; merge por campo automático es una feature, no un quick fix |
| TD-4 | i18n parcial (ES/EN según superficie) | i18n | textos mezclados en algunas vistas | extraer cadenas al tocar cada página; no un sweep único |
| TD-5 | Sin firma de artefactos de release | seguridad/cadena | imagen Docker tampered indetectable | mitigado por builds reproducibles en CI + tags firmados; firma real requiere infra de claves |
| TD-6 | Bus factor = 1 | personas | si el mantenedor desaparece, el proyecto se congela | mitigado por documentación densa; sin solución de repo |

## Regla

Toda excepción a una política documentada se registra aquí con su
justificación. Una deuda sin entrada = un bug oculto.
