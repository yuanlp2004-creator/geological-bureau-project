import { useSyncExternalStore } from 'react'
import { createThemeStore } from './themeStoreCore'

export const themeStore = createThemeStore({
  storage: {
    getItem: key => window.localStorage.getItem(key),
    setItem: (key, value) => window.localStorage.setItem(key, value)
  },
  applyTheme: theme => {
    document.documentElement.dataset.theme = theme
  }
})

export function useTheme() {
  return useSyncExternalStore(themeStore.subscribe, themeStore.getSnapshot)
}
