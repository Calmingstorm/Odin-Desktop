<script setup lang="ts">
import type { PaletteCommand } from '../commands'

defineProps<{ commands: PaletteCommand[]; selected: number }>()
const emit = defineEmits<{ pick: [index: number] }>()
</script>

<template>
  <ul class="palette" role="listbox" aria-label="Commands">
    <li v-for="(c, index) in commands" :key="c.name" role="option" :aria-selected="index === selected">
      <button type="button" :class="['palette-item', { selected: index === selected }]" @mousedown.prevent="emit('pick', index)">
        <code class="palette-usage">{{ c.usage }}</code>
        <span class="palette-affects">{{ c.affects }}</span>
      </button>
    </li>
    <li v-if="!commands.length" class="palette-empty">No command by that name. Enter sends it to Odin as a message.</li>
  </ul>
</template>
