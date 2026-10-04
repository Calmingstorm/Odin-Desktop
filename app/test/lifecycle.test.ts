import { describe, expect, it } from 'vitest'
import { decideSecondInstance, decideWindowClose, parseLaunchFlags } from '../src/main/lifecycle'

describe('lifecycle (D3)', () => {
  it('closing the window hides it and keeps Odin running', () => {
    expect(decideWindowClose({ quitting: false, trayAvailable: true, noTrayNoticeShown: false })).toEqual({
      action: 'hide',
      showNoTrayNotice: false
    })
  })

  it('without a tray, the first close shows the still-running notice once', () => {
    expect(decideWindowClose({ quitting: false, trayAvailable: false, noTrayNoticeShown: false }).showNoTrayNotice).toBe(true)
    expect(decideWindowClose({ quitting: false, trayAvailable: false, noTrayNoticeShown: true }).showNoTrayNotice).toBe(false)
  })

  it('only Exit lets the window actually close', () => {
    expect(decideWindowClose({ quitting: true, trayAvailable: false, noTrayNoticeShown: false })).toEqual({
      action: 'allow',
      showNoTrayNotice: false
    })
  })

  it('a second launch focuses the app; --exit stops it', () => {
    expect(decideSecondInstance(['/opt/odin-desktop/odin'])).toBe('focus')
    expect(decideSecondInstance(['/opt/odin-desktop/odin', '--exit'])).toBe('exit')
  })

  it('parses launch flags', () => {
    expect(parseLaunchFlags(['x', '--hidden'])).toEqual({ exit: false, hidden: true, smokeTest: false })
  })
})
