<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ReleaseNotice } from '../../../shared/api'
import { state } from '../store'

const notice = ref<ReleaseNotice | null>(null)
const busy = ref(false)
const error = ref('')
const text = computed(() => {
  if (busy.value) return 'Checking for updates…'
  if (!notice.value) return 'Not checked. Check GitHub for published stable versions.'
  const n = notice.value
  switch (n.state) {
    case 'cannot-check-private': return "Can't check for updates. The repository may be private or access is denied. Anonymous checks cannot read private releases."
    case 'offline': return "Can't check for updates. Offline or GitHub could not be reached."
    case 'rate-limited': return "Can't check for updates. GitHub has rate-limited anonymous requests. Try again later."
    case 'malformed': return "Can't check for updates. GitHub returned invalid release metadata."
    case 'unavailable': return "Can't check for updates. GitHub release metadata is unavailable or incomplete."
    case 'invalid-current-version': return "Can't check for updates. This app does not have a stable version number."
    case 'no-release': return 'No published stable release is available. This is not an up-to-date check.'
    case 'equal': return `Up to date with the latest published stable release (${n.latestVersion}).`
    case 'older': return `This app is newer than the latest published stable release (${n.latestVersion}).`
    case 'newer': return `A new version is available: ${n.latestVersion}.`
  }
})

async function check(): Promise<void> {
  if (busy.value) return
  busy.value = true
  notice.value = null
  error.value = ''
  try {
    const result = await window.odin.checkReleases()
    if (result.ok) notice.value = result.result
    else error.value = result.error.message
  } catch { error.value = "Can't check for updates. The app operation failed." }
  finally { busy.value = false }
}

async function open(): Promise<void> {
  try {
    const result = await window.odin.openRelease()
    error.value = result.ok ? '' : result.error.message
  } catch { error.value = 'Could not open the release page.' }
}
</script>

<template>
  <section class="panel" aria-label="App version and updates">
    <h3>App version and updates</h3>
    <p>Installed app version: {{ notice?.currentVersion ?? state.app.appVersion ?? 'Unavailable' }}</p>
    <p id="release-notice-status" role="status" aria-live="polite" aria-atomic="true">{{ error || text }}</p>
    <button class="ghost" :disabled="busy" aria-describedby="release-notice-status" @click="check">Check for updates</button>
    <a v-if="notice?.releaseUrl && !busy" :href="notice.releaseUrl" @click.prevent="open">Open release page in browser</a>
    <p class="panel-hint">Checks are anonymous and manual. No credentials, download, installer or automatic update.
      Upgrade .deb through your package manager or replace the AppImage yourself.</p>
  </section>
</template>
