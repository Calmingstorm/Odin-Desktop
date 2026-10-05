// The MCP server form: what it shows for a server, and Odin's body it sends. Blank keeps what is stored; clearing the
// arguments or the tool list is a choice of its own, and header and variable values are write-only patches.
import type { McpSave, McpServer } from '../../shared/api'

export interface Form {
  create: boolean
  name: string
  transport: 'stdio' | 'http'
  command: string
  args: string
  url: string
  cwd: string
  timeout: string
  allowlist: string
  /** Clear what is stored: the arguments, or the list of tools (then every tool is offered). */
  clearArgs: boolean
  allTools: boolean
  /** Names whose stored values go; values are never shown. */
  removeHeaders: string[]
  removeEnv: string[]
  headers: Array<{ key: string; value: string }>
  env: Array<{ key: string; value: string }>
  headerKeys: string[]
  envKeys: string[]
}

export function blank(server?: McpServer): Form {
  return {
    create: !server,
    name: server?.name ?? '',
    transport: server?.transport ?? 'stdio',
    command: '',
    args: '',
    url: '',
    cwd: '',
    timeout: '',
    allowlist: '',
    clearArgs: false,
    allTools: false,
    removeHeaders: [],
    removeEnv: [],
    headers: [],
    env: [],
    headerKeys: server?.header_keys ?? [],
    envKeys: server?.env_keys ?? []
  }
}

/** Odin's body: only what the form filled in; anything left blank keeps its current value. */
export function mcpBody(f: Form): McpSave | string {
  const change: McpSave = { name: f.name.trim(), create: f.create, transport: f.transport }
  if (f.command.trim()) change.command = f.command.trim()
  if (f.args.trim()) change.args = f.args.split('\n').map((a) => a.trim()).filter(Boolean)
  if (f.url.trim()) change.url = f.url.trim()
  if (f.cwd.trim()) change.cwd = f.cwd.trim()
  if (f.timeout.trim()) {
    const seconds = Number(f.timeout)
    if (!(seconds > 0)) return 'The timeout is a number of seconds above zero.'
    change.timeout_seconds = seconds
  }
  if (f.allowlist.trim()) change.tool_allowlist = f.allowlist.split('\n').map((t) => t.trim()).filter(Boolean)
  // Blank keeps what is stored; clearing is a choice of its own.
  if (f.clearArgs) change.args = []
  if (f.allTools) change.tool_allowlist = null
  const headers = Object.fromEntries(f.headers.filter((h) => h.key.trim()).map((h) => [h.key.trim(), h.value]))
  const env = Object.fromEntries(f.env.filter((e) => e.key.trim()).map((e) => [e.key.trim(), e.value]))
  if (Object.keys(headers).length) change.headers_set = headers
  if (Object.keys(env).length) change.env_set = env
  if (f.removeHeaders.length) change.headers_remove = f.removeHeaders
  if (f.removeEnv.length) change.env_remove = f.removeEnv
  return change
}
