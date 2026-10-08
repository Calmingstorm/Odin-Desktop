<script setup lang="ts">
import { ref } from 'vue'
import State from './State.vue'
import Records from './Records.vue'
const active = ref('memory')
</script>
<template>
  <nav class="settings-subnav" aria-label="Data and privacy subsections">
    <button class="ghost" :aria-current="active === 'memory' ? 'page' : undefined" @click="active = 'memory'">Memory and knowledge</button>
    <button class="ghost" :aria-current="active === 'records' ? 'page' : undefined" @click="active = 'records'">Usage, logs and audit</button>
  </nav>
  <State v-if="active === 'memory'" />
  <Records v-else />
</template>
