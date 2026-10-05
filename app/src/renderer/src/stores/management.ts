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

export const management = reactive({
  tools: null as ToolInventory | null,
  timeouts: null as ToolTimeouts | null,
  skills: [] as SkillSummary[],
  /** The skill open in the editor, and what validation or a test said about it. */
  skill: null as SkillDetail | null,
  validation: null as SkillValidation | null,
  testResult: null as { result: string; is_error: boolean } | null,
  mcp: null as McpStatus | null,
  mcpTools: {} as Record<string, McpTool[] | undefined>,
  /** What the last action on each thing did, by key: `tool:<name>`, `skill:<name>`, `mcp:<name>` or a section. */
  notes: {} as Record<string, string | undefined>,
  busy: {} as Record<string, boolean | undefined>,
  error: ''
})

export function failure(result: Result<unknown>): string {
  return result.ok ? '' : result.error.message
}

/** Runs one action at a time per key, notes what the core said, then refreshes what it changed. */
export async function act<T>(key: string, run: () => Promise<Result<T>>, done: (answer: T) => string, refresh?: () => Promise<void>): Promise<boolean> {
  if (management.busy[key]) return false
  management.busy[key] = true
  const result = await run()
  management.busy[key] = false
  management.notes[key] = result.ok ? done(result.result) : failure(result)
  if (refresh) await refresh()
  return result.ok
}

// ---- Tools -----------------------------------------------------------------------------------------------------------

export async function loadTools(): Promise<void> {
  const [tools, timeouts] = await Promise.all([window.odin.toolsList({}), window.odin.toolsTimeoutsGet({})])
  management.error = !tools.ok ? tools.error.message : !timeouts.ok ? timeouts.error.message : ''
  if (tools.ok) management.tools = tools.result
  if (timeouts.ok) management.timeouts = timeouts.result
}

export async function setToolEnabled(name: string, enabled: boolean): Promise<void> {
  await act(`tool:${name}`, () => window.odin.toolsSetEnabled({ name, enabled }), (inventory) => {
    management.tools = inventory
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

export async function openSkill(name: string): Promise<void> {
  management.validation = null
  management.testResult = null
  const result = await window.odin.skillsGet({ name })
  if (result.ok) management.skill = result.result
  else management.notes[`skill:${name}`] = result.error.message
}

export function closeSkill(): void {
  management.skill = null
  management.validation = null
  management.testResult = null
}

export async function validateSkill(code: string): Promise<SkillValidation | null> {
  const result = await window.odin.skillsValidate({ code })
  management.validation = result.ok ? result.result : { valid: false, errors: [failure(result)], warnings: [], metadata: null, definition_keys: [] }
  return result.ok ? result.result : null
}

/** Creates or updates a skill. A new one is validated first, so its problems show before anything is saved. */
export async function saveSkill(name: string, code: string, create: boolean): Promise<boolean> {
  const report = await validateSkill(code)
  if (!report?.valid) return false
  const saved = await act(`skill:${name}`, () => window.odin.skillsSave({ name, code, create }), (answer) => answer.result, loadSkills)
  if (saved) await openSkill(name)
  return saved
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

export async function deleteSkill(name: string): Promise<void> {
  const deleted = await act(`skill:${name}`, () => window.odin.skillsDelete({ name }), (answer) => answer.result, loadSkills)
  if (deleted && management.skill?.name === name) closeSkill()
}

export async function saveSkillConfig(name: string, config: Record<string, unknown>): Promise<boolean> {
  return act(`skill-config:${name}`, () => window.odin.skillsConfigSet({ name, config }), () => 'Saved.', () => openSkill(name))
}

// ---- MCP servers -----------------------------------------------------------------------------------------------------

export async function loadMcp(): Promise<void> {
  const result = await window.odin.mcpStatus({})
  management.error = failure(result)
  if (result.ok) management.mcp = result.result
}

function mcpOutcome(answer: { state: string; last_error: string }): string {
  return answer.last_error ? `${answer.state}: ${answer.last_error}` : `Now ${answer.state}.`
}

export const setMcpEnabled = (name: string, enabled: boolean): Promise<boolean> =>
  act(`mcp:${name}`, () => window.odin.mcpSetEnabled({ name, enabled }), mcpOutcome, loadMcp)
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

export async function setMcpGlobal(enabled: boolean): Promise<void> {
  await act('mcp', () => window.odin.mcpSetGlobalEnabled({ enabled }), (status) => {
    management.mcp = status
    return enabled ? 'MCP is on.' : 'MCP is off: no server runs and no MCP tool is offered.'
  })
}

export async function setMcpLimits(limits: { max_published_tools_per_server?: number; max_published_tools_global?: number }): Promise<void> {
  await act('mcp-limits', () => window.odin.mcpSetLimits(limits), (status) => {
    management.mcp = status
    return 'Saved.'
  })
}
