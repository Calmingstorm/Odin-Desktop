<script setup lang="ts">
// The app's outline icons: 24-unit strokes in the current text colour. Always decorative; the control carries the name.
import { computed } from 'vue'

type IconName = 'rune' | 'chats' | 'work' | 'settings' | 'sun' | 'moon'

const props = withDefaults(defineProps<{ name: IconName; size?: number; stroke?: number }>(), { size: 20, stroke: 2 })

// Each icon is a list of path data; `c:x,y,r` is a circle.
const ICONS: Record<IconName, string[]> = {
  // Odin's mark: the Ansuz rune.
  rune: ['M8 3v18', 'M8 4.5l8 5', 'M8 10.5l8 5'],
  chats: ['M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H9.5L4 20Z'],
  work: ['M3 12h4l2.5-6.5 5 13 2.5-6.5H21'],
  settings: ['M4 7h9', 'M17 7h3', 'M4 17h3', 'M11 17h9', 'c:15,7,2', 'c:9,17,2'],
  sun: ['c:12,12,4', 'M12 2.5v2', 'M12 19.5v2', 'M2.5 12h2', 'M19.5 12h2', 'M5.3 5.3l1.4 1.4', 'M17.3 17.3l1.4 1.4',
    'M5.3 18.7l1.4-1.4', 'M17.3 6.7l1.4-1.4'],
  moon: ['M20 14.6A8.5 8.5 0 1 1 9.4 4a6.6 6.6 0 0 0 10.6 10.6Z']
}

const shapes = computed(() => ICONS[props.name].map((shape) => {
  if (!shape.startsWith('c:')) return { kind: 'path' as const, d: shape }
  const [cx, cy, r] = shape.slice(2).split(',').map(Number)
  return { kind: 'circle' as const, cx, cy, r }
}))
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="stroke"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <template v-for="(shape, index) in shapes" :key="index">
      <path v-if="shape.kind === 'path'" :d="shape.d" />
      <circle v-else :cx="shape.cx" :cy="shape.cy" :r="shape.r" />
    </template>
  </svg>
</template>
