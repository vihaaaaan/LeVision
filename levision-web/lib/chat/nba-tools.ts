import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

type CliPayload = {
  matched?: boolean
  answer?: string | null
  error?: string
}

export type NbaToolOutcome =
  | { kind: 'no_match' }
  | { kind: 'answer'; answer: string }
  | { kind: 'error'; error: string }

function toBool(value: string | undefined, defaultValue: boolean): boolean {
  if (value == null) {
    return defaultValue
  }
  const text = value.trim().toLowerCase()
  return ['1', 'true', 'yes', 'on'].includes(text)
}

function shouldTryNbaTools(query: string): boolean {
  const text = query.trim()
  if (!text) {
    return false
  }

  const mode = (process.env.LEVISION_NBA_TOOLS_MATCH_MODE || 'hint')
    .trim()
    .toLowerCase()

  if (mode === 'always') {
    return true
  }

  const lower = text.toLowerCase()
  const keywords = [
    'nba',
    'points',
    'assists',
    'rebounds',
    'steals',
    'blocks',
    'turnovers',
    'play-by-play',
    'play by play',
    'season',
    'game log',
    'last ',
    'past ',
    'recent ',
    'yesterday',
    'today',
    'event ',
    'game id',
  ]
  return keywords.some((keyword) => lower.includes(keyword))
}

function resolveRepoRoot(): string {
  const cwd = process.cwd()
  const candidates = [cwd, path.resolve(cwd, '..')]
  for (const candidate of candidates) {
    const scriptPath = path.join(candidate, 'nba_pipeline', 'chat_tools_cli.py')
    if (fs.existsSync(scriptPath)) {
      return candidate
    }
  }
  return path.resolve(cwd, '..')
}

function parseCliPayload(stdout: string): CliPayload {
  const output = stdout.trim()
  if (!output) {
    return {}
  }

  try {
    return JSON.parse(output) as CliPayload
  } catch {
    const lines = output
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    const lastLine = lines[lines.length - 1]
    if (!lastLine) {
      return {}
    }
    return JSON.parse(lastLine) as CliPayload
  }
}

export async function runNbaToolQuery(query: string): Promise<NbaToolOutcome> {
  if (!toBool(process.env.LEVISION_ENABLE_NBA_TOOLS, true)) {
    return { kind: 'no_match' }
  }

  if (!query.trim() || !shouldTryNbaTools(query)) {
    return { kind: 'no_match' }
  }

  const repoRoot = resolveRepoRoot()
  const scriptPath = path.join(repoRoot, 'nba_pipeline', 'chat_tools_cli.py')
  if (!fs.existsSync(scriptPath)) {
    return { kind: 'error', error: 'NBA tools are not installed on the backend.' }
  }

  const pythonBin = process.env.LEVISION_PYTHON_BIN || 'python3'
  const timeoutMs = Number(process.env.LEVISION_NBA_TOOL_TIMEOUT_MS || '300000')

  try {
    const { stdout } = await execFileAsync(
      pythonBin,
      ['-m', 'nba_pipeline.chat_tools_cli', '--query', query, '--json'],
      {
        cwd: repoRoot,
        timeout: timeoutMs,
        maxBuffer: 8 * 1024 * 1024,
      }
    )

    const payload = parseCliPayload(stdout)
    if (!payload.matched) {
      return { kind: 'no_match' }
    }
    if (payload.answer) {
      return { kind: 'answer', answer: payload.answer }
    }
    if (payload.error) {
      return { kind: 'error', error: payload.error }
    }

    return {
      kind: 'error',
      error: 'NBA tool matched the query but returned no answer.',
    }
  } catch (error) {
    const details =
      error instanceof Error && error.message
        ? error.message
        : 'unknown tool failure'
    return {
      kind: 'error',
      error: `NBA tool execution failed: ${details}`,
    }
  }
}
