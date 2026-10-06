/// <reference types="vite/client" />
import type { PiankeApi } from '../../preload/index'

declare global {
  interface Window {
    pianke: PiankeApi
  }
}
export {}
