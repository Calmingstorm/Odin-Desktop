// A model of pinned Electron 44.5.1's Windows login items (shell/browser/browser_win.cc and
// shell/common/command_line_util_win.cc) over a fake HKCU and HKLM Run key and StartupApproved, for tests that need its
// actual answers rather than a canned object:
// - a written Run value is FormatCommandLineString(path, args): one pair of surrounding quotes stripped from the path,
//   then the path and each argument quoted when they contain a space, backslash or quote (AddQuoteForArg);
// - openAtLogin compares the Run value named for the AppUserModelID with that same formatting of the query;
// - launch items match a Run value whose program, parsed as a command line (Chromium's CommandLine::FromString), equals
//   the query path parsed the same way (case-insensitively); their args are the positional arguments, never switches;
// - an item is enabled unless StartupApproved holds a value other than 0 or 2 for its name.

const quoteForArg = (arg: string): string => (/[ \\"]/.test(arg) ? `"${arg}"` : arg)

export function formatCommandLine(path: string, args: readonly string[]): string {
  const exe = path.length >= 2 && path.startsWith('"') && path.endsWith('"') ? path.slice(1, -1) : path
  return [quoteForArg(exe), ...args.map(quoteForArg)].join(' ')
}

/** Chromium's parse of a Windows command line, for the cases these tests use: the program, then positional args. */
export function parseCommandLine(text: string): { program: string; args: string[] } {
  const tokens = text.match(/"[^"]*"|\S+/g) ?? []
  const unquote = (token: string): string => token.replace(/^"(.*)"$/, '$1')
  const [program = '', ...rest] = tokens.map(unquote)
  return { program, args: rest.filter((token) => !/^(--|-|\/)/.test(token)) }
}

export interface LoginItemsState {
  run: Record<string, string>
  machine?: Record<string, string>
  approved?: Record<string, number>
}

export function electronLoginItems(state: LoginItemsState, { execPath, isPackaged = true, aumid }: {
  execPath: string; isPackaged?: boolean; aumid: string
}) {
  const machine = state.machine ?? {}
  const approved = (state.approved ??= {})
  const items = (values: Record<string, string>, scope: string, lookup: string) =>
    Object.entries(values).flatMap(([name, command]) => {
      const parsed = parseCommandLine(command)
      if (parsed.program.toLowerCase() !== lookup.toLowerCase()) return []
      const flag = approved[name]
      return [{ name, path: parsed.program, args: parsed.args, scope,
        enabled: flag === undefined || flag === 0 || flag === 2 }]
    })
  return {
    isPackaged,
    execPath,
    getLoginItemSettings(options: { path: string; args: string[] }) {
      const lookup = parseCommandLine(options.path).program
      return {
        openAtLogin: state.run[aumid] === formatCommandLine(options.path, options.args),
        launchItems: [...items(state.run, 'user', lookup), ...items(machine, 'machine', lookup)]
      }
    },
    setLoginItemSettings(settings: { openAtLogin: boolean; enabled: boolean; name: string; path: string; args: string[] }) {
      if (settings.openAtLogin) {
        state.run[settings.name] = formatCommandLine(settings.path, settings.args)
        if (settings.enabled) delete approved[settings.name]
        else approved[settings.name] = 3
      } else {
        delete approved[settings.name]
        delete state.run[settings.name]
      }
    }
  }
}
