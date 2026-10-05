// The settings menu's management sections: built-in tools, skills and MCP servers, each in the shape of the Odin route
// it maps to (protocol.md, Management domains). Every action says what the core answered.
import { reactive } from 'vue'
import type {
  McpSave,
  McpStatus,
  McpTool,
  Result,
  SkillDetail,
  SkillSummary,
  SkillValidation,
  ToolInventory,
  ToolTimeouts
} from '../../../shared/api'
import { adoptSkill, type Loaded, type SkillEditor } from '../skill-editor'
import { isUnknownOutcome, onLateReceipt } from '../store'
import { busy } from './locks'

export const management = reactive({
  tools: null as ToolInventory | null,
  timeouts: null as ToolTimeouts | null,
  skills: [] as SkillSummary[],
  /** The skill editor: an existing skill, or a new one with a name of its own. */
  editor: null as SkillEditor | null,
  /** The detail read for the editor's skill, its settings as edited, and what validation or a test said about it. */
  skill: null as SkillDetail | null,
  skillConfig: {} as Record<string, unknown>,
  validation: null as SkillValidation | null,
  testResult: null as { result: string; is_error: boolean } | null,
  mcp: null as McpStatus | null,
  mcpTools: {} as Record<string, McpTool[] | undefined>,
  /** What the last action on each thing did, by key: `tool:<name>`, `skill:<name>`, `mcp:<name>` or a section. */
  notes: {} as Record<string, string | undefined>,
  /** Shared with the work list, which acts on schedules too. */
  busy,
  error: ''
})

export function failure(result: Result<unknown>): string {
  return result.ok ? '' : result.error.message
}

/** Commands that never answered, by ID: each keeps its thing busy until its late receipt settles it. */
const uncertain = new Map<string, { key: string; done: (answer: unknown) => string; refresh?: () => Promise<void> }>()

/**
 * Runs one action at a time per key, notes what the core said, then refreshes what it changed. A command with no
 * answer keeps its key busy, and is never sent again under a new ID; its late receipt settles it as an answer would.
 */
export async function act<T>(key: string, run: () => Promise<Result<T>>, done: (answer: T) => string, refresh?: () => Promise<void>): Promise<boolean> {
  if (management.busy[key]) return false
  management.busy[key] = true
  const result = await run()
  if (!result.ok && isUnknownOutcome(result.error) && result.error.command_id) {
    uncertain.set(result.error.command_id, { key, done: done as (answer: unknown) => string, refresh })
    management.notes[key] = "Waiting for Odin to confirm. It's never sent twice."
    return false
  }
  management.busy[key] = false
  management.notes[key] = result.ok ? done(result.result) : failure(result)
  if (refresh) await refresh()
  return result.ok
}

onLateReceipt((receipt) => {
  const pending = uncertain.get(receipt.id)
  if (!pending || (!receipt.settled.ok && isUnknownOutcome(receipt.settled.error))) return
  uncertain.delete(receipt.id)
  management.busy[pending.key] = false
  management.notes[pending.key] = receipt.settled.ok ? pending.done(receipt.settled.result) : receipt.settled.error.message
  void pending.refresh?.()
})

// ---- Tools -----------------------------------------------------------------------------------------------------------

/**
 * Reads and switches each answer with the whole tool inventory. The core handles them in the order they are sent, so
 * an answer is shown only if its request came after the one already shown.
 */
let inventorySent = 0
let inventoryShown = 0

function showInventory(sent: number, inventory: ToolInventory): void {
  if (sent < inventoryShown) return
  inventoryShown = sent
  management.tools = inventory
}

export async function loadTools(): Promise<void> {
  const sent = ++inventorySent
  const [tools, timeouts] = await Promise.all([window.odin.toolsList({}), window.odin.toolsTimeoutsGet({})])
  management.error = !tools.ok ? tools.error.message : !timeouts.ok ? timeouts.error.message : ''
  if (tools.ok) showInventory(sent, tools.result)
  if (timeouts.ok) management.timeouts = timeouts.result
}

export async function setToolEnabled(name: string, enabled: boolean): Promise<void> {
  const sent = ++inventorySent
  await act(`tool:${name}`, () => window.odin.toolsSetEnabled({ name, enabled }), (inventory) => {
    showInventory(sent, inventory)
    return enabled ? 'On.' : 'Off: Odin no longer sees this tool.'
  })
}

export async function saveTimeouts(change: { default_timeout?: number; overrides?: Record<string, number> }): Promise<boolean> {
  return act('timeouts', () => window.odin.toolsTimeoutsSet(change), (timeouts) => {
    management.timeouts = timeouts
    return 'Saved. New calls use them; calls already running keep theirs.'
  })
}

// ---- Skills ----------------------------------------------------------------------------------------------------------

export async function loadSkills(): Promise<void> {
  const result = await window.odin.skillsList({})
  management.error = failure(result)
  if (result.ok) management.skills = result.result
}

/** Each time the editor is given to another skill, a new one or nothing. Work begun for an earlier one stays there. */
let editorEpoch = 0
/** Each read of a skill's detail: only the newest is shown. */
let skillAsked = 0
/** What the editor last loaded, so a reread replaces only what the user hasn't changed since. */
let loaded: Loaded | null = null

export async function openSkill(name: string): Promise<void> {
  editorEpoch += 1
  await readSkill(name)
}

/** Reads a skill into the editor, keeping what the user changed in it since the last load. */
async function readSkill(name: string): Promise<void> {
  const mine = ++skillAsked
  management.validation = null
  management.testResult = null
  const result = await window.odin.skillsGet({ name })
  if (mine !== skillAsked) return
  if (!result.ok) {
    management.notes[`skill:${name}`] = result.error.message
    return
  }
  const adopted = adoptSkill(management.editor, loaded, JSON.stringify(management.skillConfig), result.result)
  management.skill = result.result
  management.editor = adopted.editor
  if (adopted.replaceConfig) management.skillConfig = { ...result.result.config }
  loaded = adopted.loaded
}

export function newSkill(code: string): void {
  closeSkill()
  management.editor = { name: '', code, create: true }
}

export function closeSkill(): void {
  editorEpoch += 1
  skillAsked += 1
  loaded = null
  management.editor = null
  management.skill = null
  management.skillConfig = {}
  management.validation = null
  management.testResult = null
}

export async function validateSkill(code: string): Promise<SkillValidation | null> {
  const result = await window.odin.skillsValidate({ code })
  management.validation = result.ok ? result.result : { valid: false, errors: [failure(result)], warnings: [], metadata: null, definition_keys: [] }
  return result.ok ? result.result : null
}

/**
 * Creates or updates the editor's skill. A new one is validated first, so its problems show before anything is saved.
 * Once saved, now or by a late receipt, the skill is read back into the editor if the editor still holds it.
 */
export async function saveSkill(): Promise<boolean> {
  const draft = management.editor
  const name = draft?.name.trim()
  if (!draft || !name) return false
  const { code, create } = draft
  const epoch = editorEpoch
  const report = await validateSkill(code)
  if (!report?.valid) return false
  // A new skill's code counts as loaded once sent, so code typed while it is created stays.
  if (create && epoch === editorEpoch) loaded = { name, code, config: JSON.stringify(management.skillConfig) }
  return act(`skill:${name}`, () => window.odin.skillsSave({ name, code, create }), (answer) => {
    if (epoch === editorEpoch && management.editor?.name.trim() === name) void readSkill(name)
    return answer.result
  }, loadSkills)
}

export async function testSkill(name: string): Promise<void> {
  management.testResult = null
  await act(`skill:${name}`, () => window.odin.skillsTest({ name }), (answer) => {
    management.testResult = answer
    return answer.is_error ? 'The test run failed.' : 'Ran with empty input.'
  }, loadSkills)
}

export async function setSkillEnabled(name: string, enabled: boolean): Promise<void> {
  await act(`skill:${name}`, () => window.odin.skillsSetEnabled({ name, enabled }), (answer) => answer.result, loadSkills)
}

/** Once deleted, now or by a late receipt, the editor closes if it shows that skill. */
export async function deleteSkill(name: string): Promise<void> {
  await act(`skill:${name}`, () => window.odin.skillsDelete({ name }), (answer) => {
    if (management.editor && !management.editor.create && management.editor.name === name) closeSkill()
    return answer.result
  }, loadSkills)
}

/** Once saved, the skill is read back into the editor if the editor still holds it. */
export async function saveSkillConfig(name: string, config: Record<string, unknown>): Promise<boolean> {
  const epoch = editorEpoch
  return act(`skill-config:${name}`, () => window.odin.skillsConfigSet({ name, config }), () => {
    if (epoch === editorEpoch) void readSkill(name)
    return 'Saved.'
  })
}

// ---- MCP servers -----------------------------------------------------------------------------------------------------

/**
 * Reads, switches and limits each answer with the whole MCP status. The core handles them in the order they are sent,
 * so a status is shown only if its request came after the one already shown.
 */
let mcpSent = 0
let mcpShown = 0

function showMcp(sent: number, status: McpStatus): void {
  if (sent < mcpShown) return
  mcpShown = sent
  management.mcp = status
}

export async function loadMcp(): Promise<void> {
  const sent = ++mcpSent
  const result = await window.odin.mcpStatus({})
  management.error = failure(result)
  if (result.ok) showMcp(sent, result.result)
}

function mcpOutcome(answer: { state: string; last_error: string }): string {
  return answer.last_error ? `${answer.state}: ${answer.last_error}` : `Now ${answer.state}.`
}

/** Odin's per-server switch answers the whole status: show it, and say how the server is now. */
export function setMcpEnabled(name: string, enabled: boolean): Promise<boolean> {
  const sent = ++mcpSent
  return act(`mcp:${name}`, () => window.odin.mcpSetEnabled({ name, enabled }), (status) => {
    showMcp(sent, status)
    const server = status.servers.find((s) => s.name === name)
    return server ? mcpOutcome(server) : 'Saved.'
  })
}
export const reconnectMcp = (name: string): Promise<boolean> =>
  act(`mcp:${name}`, () => window.odin.mcpReconnect({ name }), mcpOutcome, loadMcp)
export const refreshMcpTools = (name: string): Promise<boolean> =>
  act(`mcp:${name}`, () => window.odin.mcpRefreshTools({ name }), mcpOutcome, loadMcp)
export const deleteMcp = (name: string): Promise<boolean> =>
  act(`mcp:${name}`, () => window.odin.mcpDelete({ name }), () => 'Removed.', loadMcp)

export async function saveMcp(change: McpSave): Promise<boolean> {
  return act(`mcp:${change.name}`, () => window.odin.mcpSave(change), mcpOutcome, loadMcp)
}

export async function loadMcpTools(name: string): Promise<void> {
  const result = await window.odin.mcpTools({ name })
  if (result.ok) management.mcpTools[name] = result.result.tools
  else management.notes[`mcp:${name}`] = result.error.message
}

/** Odin's global switch answers only what it saved, so the status is read again for the servers and their tools. */
export async function setMcpGlobal(enabled: boolean): Promise<void> {
  await act(
    'mcp',
    () => window.odin.mcpSetGlobalEnabled({ enabled }),
    (answer) => (answer.enabled ? `MCP is on: ${answer.connected_count} servers connected.` : 'MCP is off: no server runs and no MCP tool is offered.'),
    loadMcp
  )
}

export async function setMcpLimits(limits: { max_published_tools_per_server?: number; max_published_tools_global?: number }): Promise<void> {
  const sent = ++mcpSent
  await act('mcp-limits', () => window.odin.mcpSetLimits(limits), (status) => {
    showMcp(sent, status)
    return 'Saved.'
  })
}
