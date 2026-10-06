<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NotificationChange } from '../../../../shared/api'
import ReleaseNotice from '../../components/ReleaseNotice.vue'
import { setAutostart, state } from '../../store'

// The app's own settings, kept by the app rather than the core: startup and desktop notifications (D13).
const notifications = computed(() => state.notifications)
const notificationError = ref('')

async function change(update: NotificationChange): Promise<void> {
  const result = await window.odin.setNotifications(update)
  if (result.ok) state.notifications = result.result.notifications
  notificationError.value = result.ok ? '' : result.error.message
}

function quiet(key: 'start' | 'end', event: Event): void {
  const value = (event.target as HTMLInputElement).value
  if (/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) void change({ quietHours: { [key]: value } })
}
</script>

<template>
  <ReleaseNotice />
  <section class="panel app-settings" aria-label="This app">
    <header class="panel-head">
      <h3>This app</h3>
      <span class="panel-hint">Local app settings, kept on this computer and available independently of core settings.</span>
    </header>
    <p class="panel-hint">Start at login is opt-in and initially off. Closing the window keeps work running. Exit stops Odin.</p>
    <p class="panel-hint">Notification previews are on by default. Change previews or quiet hours below, or mute a conversation from its menu.</p>
    <label class="field-input toggle">
      <input data-testid="start-at-login" type="checkbox" :checked="state.autostart" @change="setAutostart(($event.target as HTMLInputElement).checked)" />
      Start Odin when you log in
    </label>
    <template v-if="notifications">
      <label class="field-input toggle">
        <input type="checkbox" :checked="notifications.enabled" @change="change({ enabled: ($event.target as HTMLInputElement).checked })" />
        Desktop notifications
      </label>
      <label class="field-input toggle">
        <input
          type="checkbox"
          :checked="notifications.previews"
          data-testid="notification-previews"
          :disabled="!notifications.enabled"
          @change="change({ previews: ($event.target as HTMLInputElement).checked })"
        />
        Show message previews in notifications
      </label>
      <div class="field-input toggle">
        <label for="quiet-hours-enabled">Quiet hours</label>
        <input
          id="quiet-hours-enabled"
          type="checkbox"
          :checked="notifications.quietHours.enabled"
          data-testid="notification-quiet-hours"
          :disabled="!notifications.enabled"
          @change="change({ quietHours: { enabled: ($event.target as HTMLInputElement).checked } })"
        />
        <label for="quiet-hours-start">Quiet hours start</label>
        <input id="quiet-hours-start" type="time" :value="notifications.quietHours.start" :disabled="!notifications.quietHours.enabled" @change="quiet('start', $event)" />
        <label for="quiet-hours-end">Quiet hours end</label>
        <input id="quiet-hours-end" type="time" :value="notifications.quietHours.end" :disabled="!notifications.quietHours.enabled" @change="quiet('end', $event)" />
      </div>
      <p v-if="notificationError" class="warn" role="status">{{ notificationError }}</p>
      <p class="panel-hint">Muted conversations: {{ notifications.muted.length }}. Mute or unmute one from its ⋯ menu.</p>
    </template>
  </section>
</template>
