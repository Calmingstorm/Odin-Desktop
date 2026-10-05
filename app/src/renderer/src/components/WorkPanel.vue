<script setup lang="ts">
import { loadWork, work } from '../stores/work'
import WorkList from './WorkList.vue'
</script>

<template>
  <section class="work-panel" aria-label="Running work">
    <header class="work-head">
      <strong>Work</strong>
      <span class="work-hint">Agents, tasks, loops, processes and schedules, with the controls Odin offers for each.</span>
      <button class="ghost" title="Fetch the list again" @click="loadWork">Refresh</button>
      <button class="ghost" title="Close" @click="work.open = false">✕</button>
    </header>
    <WorkList />
  </section>
</template>
