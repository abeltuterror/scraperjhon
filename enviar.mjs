// Envía datos.json al endpoint de Convocape
// Uso: node pasado/enviar.mjs

import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const API_URL = 'https://www.convocape.com/api/convocatorias'
const API_KEY = 'mi-clave-secreta-2024'
const BATCH_SIZE = 200  // registros por request

// ── Cargar datos ──────────────────────────────────────────────
const raw = readFileSync(join(__dirname, 'public/datos.json'), 'utf-8')
const datos = JSON.parse(raw)
console.log(`✓ Cargados ${datos.length} registros de datos_sin_fechas_vacias.json`)

// ── Enviar en batches ─────────────────────────────────────────
let totalSaved = 0
let totalErrors = 0
const batches = Math.ceil(datos.length / BATCH_SIZE)

for (let i = 0; i < batches; i++) {
  const batch = datos.slice(i * BATCH_SIZE, (i + 1) * BATCH_SIZE)
  const batchNum = i + 1

  process.stdout.write(`Batch ${batchNum}/${batches} (${batch.length} registros)... `)

  try {
    const res = await fetch(API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`,
      },
      body: JSON.stringify(batch),
    })

    const json = await res.json()

    if (!res.ok) {
      console.log(`ERROR ${res.status}:`, JSON.stringify(json))
      totalErrors += batch.length
      continue
    }

    totalSaved += json.saved ?? 0
    if (json.errors?.length) {
      console.log(`⚠ ${json.saved} guardados, ${json.errors.length} con error`)
      totalErrors += json.errors.length
    } else {
      console.log(`✓ ${json.saved} guardados`)
    }

  } catch (err) {
    console.log(`ERROR de red: ${err.message}`)
    console.log('  → ¿Está corriendo "npm run dev"?')
    totalErrors += batch.length
  }
}

// ── Resumen ───────────────────────────────────────────────────
console.log('\n─────────────────────────────')
console.log(`Total guardados : ${totalSaved}`)
console.log(`Total con error : ${totalErrors}`)
console.log('─────────────────────────────')
