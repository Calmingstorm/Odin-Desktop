// The skill editor across reloads: a skill's detail is read again after saving its code or its settings, and that
// must never throw away what the user changed in the editor since the last load.

export interface SkillEditor {
  name: string
  code: string
  create: boolean
}

/** What the editor last loaded for its skill. */
export interface Loaded {
  name: string
  code: string
  config: string
}

export interface Adopted {
  /** The editor to show: its code replaced for another skill, or when untouched since it was loaded. */
  editor: SkillEditor
  /** Whether the settings shown are replaced: only for another skill, or when untouched since loaded. */
  replaceConfig: boolean
  loaded: Loaded
}

/**
 * The editor once a skill's detail is read. A new skill being created counts as the same skill once its name is the
 * one created, with the code it sent as what was loaded: code typed since then stays, and the editor leaves create mode.
 */
export function adoptSkill(
  current: SkillEditor | null,
  loaded: Loaded | null,
  configShown: string,
  skill: { name: string; code?: string | null; config: Record<string, unknown> }
): Adopted {
  const code = skill.code ?? ''
  const same = Boolean(current && current.name.trim() === skill.name && loaded?.name === skill.name)
  const keepCode = same && current!.code !== loaded!.code
  return {
    editor: { name: skill.name, code: keepCode ? current!.code : code, create: false },
    replaceConfig: !same || configShown === loaded!.config,
    loaded: { name: skill.name, code, config: JSON.stringify(skill.config) }
  }
}
