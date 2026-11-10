import { spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const root = resolve(frontend, '..')
const destination = resolve(frontend, 'src/api/generated/schema.d.ts')

try {
  if (process.argv.slice(2).some((argument) => argument !== '--check')) {
    throw new Error('Usage: node scripts/generate-api.mjs [--check]')
  }
  const result = spawnSync('uv', ['run', '--no-sync', 'python', '-m', 'aifreeradar.export_openapi'], {
    cwd: root, shell: false, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
  })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(result.stderr.trim() || 'OpenAPI export failed.')
  if (!result.stdout.trim()) throw new Error('OpenAPI export produced no JSON.')
  const schema = JSON.parse(result.stdout)
  if (!schema || typeof schema !== 'object' || typeof schema.openapi !== 'string' || !schema.paths) {
    throw new Error('OpenAPI export did not produce an OpenAPI document.')
  }
  const content = astToString(await openapiTS(schema))
  if (!content.trim()) throw new Error('OpenAPI type generation produced no output.')
  if (process.argv.includes('--check')) {
    const current = await readFile(destination, 'utf8')
    if (current !== content) throw new Error('API types have drifted. Run pnpm --dir frontend api:generate.')
  } else {
    await mkdir(dirname(destination), { recursive: true })
    await writeFile(destination, content, 'utf8')
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
