// Reusable HTTP/SSE peer for contract tests and the isolated Electron smoke.
// Never a replacement for Odin's provider client, tool loop, or config loader.
import { createServer } from 'node:http'
import { mkdirSync, readlinkSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

export const REPLY = 'Canned provider reply: real core contract.'
export const TOOL_REPLY = 'Canned provider reply: harmless tool completed.'
export const FILE_CONTENT = 'Real core posted file contract.\n'
export const PAGED_TEXT = Array.from({ length: 900 }, (_, index) => `Evidence line ${String(index).padStart(4, '0')}: ${'canned evidence '.repeat(7)}\n`).join('')
export const IMAGE_BYTES = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=', 'base64')

export async function startCannedProvider({ root }) {
  const outer = process.env.ODIN_REAL_CORE_OUTER_PID_NS
  if (!outer || readlinkSync('/proc/self/ns/pid') === outer || process.getuid() === 0 ||
      !process.env.ODIN_REAL_CORE_ROOT || process.env.HOME !== process.env.ODIN_REAL_CORE_ROOT ||
      !resolve(root).startsWith(`${resolve(process.env.ODIN_REAL_CORE_ROOT)}/`)) {
    throw new Error('Canned provider requires the unprivileged PID-isolated disposable HOME.')
  }
  mkdirSync(root, { recursive: true, mode: 0o700 })
  const imagePath = join(root, 'canned-image.png')
  writeFileSync(imagePath, IMAGE_BYTES, { mode: 0o600 })
  const evidencePath = join(root, 'canned-evidence.txt')
  writeFileSync(evidencePath, PAGED_TEXT, { mode: 0o600 })
  const requests = []
  const held = new Map()
  const released = new Set()
  let callSequence = 0
  const release = (token) => {
    released.add(token)
    for (const send of held.get(token) ?? []) send()
    held.delete(token)
  }
  const server = createServer(async (req, res) => {
    try {
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      const body = JSON.parse(Buffer.concat(chunks).toString() || '{}')
      if (req.method === 'POST' && req.url === '/release') {
        release(body.token)
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); return
      }
      if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
        res.writeHead(404); res.end(); return
      }
      const messages = body.messages ?? []
      const lastUserIndex = messages.findLastIndex((message) => message.role === 'user')
      const raw = messages[lastUserIndex]?.content ?? ''
      const text = typeof raw === 'string' ? raw : raw.map((part) => part.text ?? '').join('\n')
      const token = text.match(/\[(reply|tool|paged-tool|artifact|fail|hold-stop|hold-steer)\]/)?.[0] ?? '[reply]'
      const afterUser = messages.slice(lastUserIndex + 1)
      const tools = afterUser.filter((message) => message.role === 'tool')
      requests.push({ token, body })
      if (token === '[fail]') {
        res.writeHead(400, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: { code: 'canned_failure', message: 'Canned provider failure on demand.' } })); return
      }
      const tool = (name, args) => ({ index: 0, id: `canned_call_${++callSequence}`, type: 'function',
        function: { name, arguments: JSON.stringify(args) } })
      let delta = { content: REPLY }
      if (token === '[tool]' || token === '[hold-steer]') {
        delta = tools.length ? { content: TOOL_REPLY } : { tool_calls: [tool('parse_time', { expression: 'in 2 hours' })] }
      }
      if (token === '[paged-tool]') {
        // read_file has a dedicated line-continuation envelope rather than the
        // generic retained output seam. cat is effect-free on this canned file.
        delta = tools.length ? { content: TOOL_REPLY } : { tool_calls: [tool('run_command', { host: 'localhost', command: `cat '${evidencePath}'` })] }
      }
      if (token === '[artifact]') {
        delta = tools.length === 0 ? { tool_calls: [tool('generate_file', { filename: 'contract.txt', content: FILE_CONTENT })] }
          : tools.length === 1 ? { tool_calls: [tool('post_file', { host: 'localhost', path: imagePath, caption: 'Canned image contract.' })] }
            : { content: 'Canned provider reply: file and image posted.' }
      }
      const send = () => {
        if (res.destroyed || res.writableEnded) return
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
        const frame = (value) => res.write(`data: ${JSON.stringify(value)}\n\n`)
        frame({ id: 'canned-completion', object: 'chat.completion.chunk', model: 'canned-contract',
          choices: [{ index: 0, delta: { role: 'assistant', ...delta }, finish_reason: null }] })
        frame({ choices: [{ index: 0, delta: {}, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] })
        frame({ choices: [], usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 } })
        res.end('data: [DONE]\n\n')
      }
      // Hold first generation only. Release lets the real mailbox consume
      // steering at the tool safe boundary. Stop cancels the actual HTTP call.
      if (token.startsWith('[hold-') && tools.length === 0 && !released.has(token)) {
        const pending = held.get(token) ?? []; pending.push(send); held.set(token, pending)
        res.once('close', () => { held.set(token, (held.get(token) ?? []).filter((item) => item !== send)) })
      } else send()
    } catch {
      if (!res.headersSent) res.writeHead(400)
      res.end()
    }
  })
  await new Promise((accept, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', accept) })
  const baseUrl = `http://127.0.0.1:${server.address().port}/v1`
  const configPath = join(root, 'canned-provider.json')
  writeFileSync(configPath, JSON.stringify({
    openai_codex: { enabled: false }, ollama: { enabled: false },
    openai_compatible: { enabled: true, api_key: 'canned-local-test-only', base_url: baseUrl,
      model: 'canned-contract', preset: 'custom', reasoning_dialect: 'none', reasoning_effort: 'none',
      max_tokens: 4096, request_timeout_seconds: 60, stream_stall_timeout_seconds: 30,
      model_profiles: { 'canned-contract': { total_window_tokens: 131072, max_output_tokens: 4096 } } },
    llm_provider: { model: 'compat:canned-contract' }, browser: { enabled: false },
    tools: { hosts: { localhost: { address: '127.0.0.1', username: 'unused-test-only' } }, default_host: 'localhost' }
  }), { mode: 0o600 })
  return { baseUrl, configPath, imagePath, requests, release,
    async close() { server.closeAllConnections(); await new Promise((accept) => server.close(accept)) } }
}
