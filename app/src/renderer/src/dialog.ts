// One modal at a time: confirmations and short text prompts, answered through a promise. ConfirmDialog.vue renders it.
import { reactive } from 'vue'

export interface DialogRequest {
  title: string
  message: string
  confirmLabel: string
  danger?: boolean
  input?: { value: string; label: string; maxLength?: number }
}

interface OpenDialog extends DialogRequest {
  resolve: (answer: string | true | null) => void
}

export const dialog = reactive({ current: null as OpenDialog | null })

/** Resolves `true` (or the entered text, for a prompt) when confirmed, and `null` when cancelled. */
export function ask(request: DialogRequest): Promise<string | true | null> {
  dialog.current?.resolve(null)
  return new Promise((resolve) => {
    dialog.current = {
      ...request,
      resolve: (answer) => {
        dialog.current = null
        resolve(answer)
      }
    }
  })
}
