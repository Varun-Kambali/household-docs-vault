// Writes src/api/schema.d.ts from the API's own description (`vault openapi`, which prints
// app.openapi()). Run `npm run types` after an API model or route changes; `npm run types:check`
// fails when the file is out of date, and CI runs it.

import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import openapiTS, { astToString } from 'openapi-typescript'
import * as prettier from 'prettier'

const here = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(here, '../..')
const OUT = path.resolve(here, '../src/api/schema.d.ts')

const BANNER = `// Generated from the API by web/scripts/generate-types.ts. Do not edit by hand:
// change the API, then run \`npm run types\` in web/.
`

function apiDescription(): string {
  return execFileSync('uv', ['run', '--quiet', 'vault', 'openapi'], {
    cwd: REPO,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
}

async function generate(): Promise<string> {
  const text = BANNER + astToString(await openapiTS(apiDescription()))
  const options = await prettier.resolveConfig(OUT)
  return prettier.format(text, { ...options, filepath: OUT })
}

async function main(): Promise<void> {
  const text = await generate()
  if (process.argv.includes('--check')) {
    const current = await readFile(OUT, 'utf8').catch(() => '')
    if (current !== text) {
      console.error('src/api/schema.d.ts is out of date with the API: run npm run types')
      process.exit(1)
    }
    console.log('src/api/schema.d.ts matches the API')
    return
  }
  await writeFile(OUT, text)
  console.log(`wrote ${path.relative(process.cwd(), OUT)}`)
}

await main()
