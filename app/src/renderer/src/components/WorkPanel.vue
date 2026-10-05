<script setup lang="ts">
import { computed } from 'vue'
import { select, state } from '../store'
import { actionLabel, controlWork, grouped, isActive, loadWork, work, workKey } from '../stores/work'

const groups = computed(() => grouped())

function titleOf(conversationId: string): string | null {
  return state.conversations.find((c) => c.id === conversationId)?.title ?? null
}

function started(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <section class="work-panel" aria-label="Running work">
    <header class="work-head">
      <strong>Work</strong>
      <span class="work-hint">Agents, tasks, loops, processes and schedules, with the controls Odin offers for each.</span>
      <button class="ghost" title="Fetch the list again" @click="loadWork">Refresh</button>
      <button class="ghost" title="Close" @click="work.open = false">✕</button>
    </header>
    <p v-if="work.error" class="warn">{{ work.error }}</p>
    <p v-else-if="work.loaded && !groups.length" class="work-empty">Nothing is running.</p>
    <div v-for="group in groups" :key="group.kind" class="work-group">
      <h3>{{ group.label }} <span class="work-count">{{ group.items.length }}</span></h3>
      <article v-for="item in group.items" :key="workKey(item)" :class="['work-item', { done: !isActive(item) }]">
        <div class="work-line">
          <span :class="['work-state', item.state]">{{ item.state }}</span>
          <strong class="work-title">{{ item.title }}</strong>
          <span class="work-actions">
            <button
              v-for="action in item.actions"
              :key="action"
              class="ghost"
              :disabled="work.busy[workKey(item)]"
              @click="controlWork(item, action)"
            >
              {{ actionLabel(action) }}
            </button>
          </span>
        </div>
        <div class="work-meta">
          <span v-if="item.detail">{{ item.detail }}</span>
          <span v-if="item.started_at">started {{ started(item.started_at) }}</span>
          <button
            v-if="item.conversation_id && titleOf(item.conversation_id)"
            class="work-link"
            @click="select(item.conversation_id)"
          >
            in {{ titleOf(item.conversation_id) }}
          </button>
        </div>
        <p v-if="work.notes[workKey(item)]" class="work-note" role="status">{{ work.notes[workKey(item)] }}</p>
      </article>
    </div>
  </section>
</template>
