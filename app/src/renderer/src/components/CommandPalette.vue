<script setup lang="ts">
import type { PaletteCommand } from '../commands'

defineProps<{ commands: PaletteCommand[]; selected: number }>()
const emit = defineEmits<{ pick: [index: number] }>()
</script>

<template>
  <ul v-if="commands.length" id="command-palette" class="palette" role="listbox" aria-label="Commands">
    <li v-for="(c, index) in commands" :id="`command-option-${c.name}`" :key="c.name" role="option" :aria-selected="index === selected" :class="['palette-item', { selected: index === selected }]" @mousedown.prevent @click="emit('pick', index)">
        <code class="palette-usage">{{ c.usage }}</code>
        <span class="palette-affects">{{ c.affects }}</span>
    </li>
  </ul>
  <p v-else class="palette palette-empty" role="status">No command by that name. Enter sends it to Odin as a message.</p>
</template>
