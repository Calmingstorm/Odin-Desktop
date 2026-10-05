/// <reference types="vite/client" />
import type { OdinApi } from '../../shared/api'

declare global {
  interface Window {
    odin: OdinApi
  }
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

export {}
