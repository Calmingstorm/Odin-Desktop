<script setup lang="ts">
import { isBusy, newConversation, select, state } from '../store'
</script>

<template>
  <nav aria-label="Conversations">
    <div class="sidebar-head">
      <span class="brand">Odin</span>
      <button class="ghost" title="New conversation" @click="newConversation">+ New</button>
    </div>
    <ul class="conversations">
      <li v-for="c in state.conversations" :key="c.id">
        <button :class="['conv', { active: c.id === state.activeId }]" @click="select(c.id)">
          <span class="conv-title">{{ c.title }}</span>
          <span v-if="isBusy(c.id)" class="busy-dot" title="Odin is working in this conversation" />
        </button>
      </li>
    </ul>
  </nav>
</template>
