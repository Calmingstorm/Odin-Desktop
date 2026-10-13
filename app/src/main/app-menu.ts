// The application menu and the Exit shortcut that works even while the renderer is busy. Linux and Windows keep their
// menu as it was; macOS gets its own (the app menu with Quit ⌘Q, Edit, View and Window), where Electron's roles give
// the standard Cmd shortcuts. Quit there goes through before-quit, which runs Exit with its cleanup.
import type { MenuItemConstructorOptions } from 'electron'

export interface MenuActions {
  closeWindow: () => void
  exit: () => void
}

const EDIT: MenuItemConstructorOptions = { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] }
const VIEW: MenuItemConstructorOptions = { label: 'View', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }] }

export function applicationMenu(system: NodeJS.Platform, actions: MenuActions): MenuItemConstructorOptions[] {
  if (system !== 'darwin') {
    return [
      {
        label: 'Odin',
        submenu: [
          { label: 'Close Window', accelerator: 'Ctrl+W', click: actions.closeWindow },
          { type: 'separator' },
          { label: 'Exit Odin', accelerator: 'Ctrl+Q', click: actions.exit }
        ]
      },
      EDIT,
      VIEW
    ]
  }
  return [
    {
      label: 'Odin',
      submenu: [
        { role: 'about', label: 'About Odin' },
        { type: 'separator' },
        { role: 'hide', label: 'Hide Odin' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { label: 'Quit Odin', accelerator: 'Cmd+Q', click: actions.exit }
      ]
    },
    EDIT,
    VIEW,
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        { label: 'Close Window', accelerator: 'Cmd+W', click: actions.closeWindow }
      ]
    }
  ]
}

export interface KeyInput { type: string; key: string; control: boolean; alt: boolean; meta: boolean }

/** Exit's shortcut, read before the page sees the key: Ctrl+Q, or ⌘Q on macOS. */
export function isExitShortcut(input: KeyInput, system: NodeJS.Platform): boolean {
  const darwin = system === 'darwin'
  const modifier = darwin ? input.meta && !input.control : input.control && !input.meta
  return input.type === 'keyDown' && modifier && !input.alt && input.key.toLowerCase() === 'q'
}
