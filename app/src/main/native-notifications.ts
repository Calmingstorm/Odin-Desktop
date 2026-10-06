// Electron's native notification adapter. OS acceptance is not human appearance or a read watermark.
import { Notification } from 'electron'

export function showNativeNotification(
  notification: { title: string; body: string; onClick: () => void },
  live: Set<Notification>,
  icon: string
): Promise<'shown' | 'failed'> {
  return new Promise((resolve) => {
    let os: Notification | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let terminal = false
    let accepted = false
    const failed = (): void => {
      if (terminal) return
      terminal = true
      clearTimeout(timer)
      if (os) {
        live.delete(os)
        os.removeAllListeners()
        try { os.close() } catch { /* Closing an unaccepted native object is best effort, not a read receipt. */ }
      }
      resolve('failed')
    }
    try {
      if (!Notification.isSupported()) return failed()
      os = new Notification({ title: notification.title, body: notification.body, icon })
      // Electron drops handlers when nothing references the notification.
      live.add(os)
      if (live.size > 50) live.delete(live.values().next().value as Notification)
      timer = setTimeout(failed, 5000)
      os.once('show', () => {
        if (terminal) return
        terminal = true
        accepted = true
        clearTimeout(timer)
        resolve('shown')
      })
      os.once('failed', failed)
      os.on('click', () => {
        if (!accepted) return
        live.delete(os!)
        os!.removeAllListeners()
        notification.onClick()
      })
      os.on('close', () => live.delete(os!))
      os.show()
    } catch {
      // Constructor/show failures settle exactly like the native failure event, not an unhandled rejection.
      failed()
    }
  })
}
