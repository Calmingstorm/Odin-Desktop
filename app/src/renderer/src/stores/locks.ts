// One lock per thing, shared by every place that acts on it, by key (`schedule:<id>`, `host:<alias>`, `tool:<name>`, …).
// An action with no answer yet holds its thing everywhere, so nothing runs twice under two commands from two places.
import { reactive } from 'vue'

export const busy = reactive<Record<string, boolean | undefined>>({})
