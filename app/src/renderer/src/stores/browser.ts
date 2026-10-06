// Browser health is a read, not a driver/CDP probe and not a retry command.
import { reactive } from 'vue'
import type { HealthReport } from '../../../shared/api'

export const browser = reactive({
  status: null as NonNullable<HealthReport['browser']> | null,
  loaded: false,
  error: '',
  busy: false
})

let latest = 0
export async function loadBrowserStatus(): Promise<void> {
  const mine = ++latest
  browser.busy = true
  try {
    const answer = await window.odin.healthGet({})
    if (mine !== latest) return
    if (!answer.ok) {
      browser.error = answer.error.message
      return
    }
    browser.status = answer.result.browser ?? null
    browser.error = ''
    browser.loaded = true
  } catch {
    if (mine === latest) browser.error = 'Browser status could not be read.'
  } finally {
    if (mine === latest) browser.busy = false
  }
}

export function browserRetryNote(status: NonNullable<HealthReport['browser']>): string {
  if (status.retry_available === true && !status.ready) {
    return 'The core can retry qualification on the next browser tool use. Retry availability is not browser readiness.'
  }
  if (status.ready) return 'The core reports the browser ready. Refresh only reads this status.'
  return 'No next-use retry is reported. Refresh only reads status; it does not launch or qualify a browser.'
}
