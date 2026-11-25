export type Theme = 'light' | 'dark'

type ThemeStoreOptions = {
  storage: {
    getItem: (key: string) => string | null
    setItem: (key: string, value: Theme) => void
  }
  applyTheme: (theme: Theme) => void
}

export function resolveTheme(themePreference: Theme | null, settingsTheme: string | null): Theme {
  return themePreference ?? (settingsTheme === 'dark' ? 'dark' : 'light')
}

function preferenceKey(userId: number) {
  return `geospectrum:theme:${userId}`
}

export function createThemeStore({ storage, applyTheme }: ThemeStoreOptions) {
  const listeners = new Set<() => void>()
  let activeUserId: number | null = null
  let themePreference: Theme | null = null
  let settingsTheme: string | null = null
  let theme: Theme = 'light'

  function syncTheme() {
    const nextTheme = activeUserId === null ? 'light' : resolveTheme(themePreference, settingsTheme)
    const changed = theme !== nextTheme
    theme = nextTheme
    applyTheme(theme)
    if (changed) listeners.forEach(listener => listener())
  }

  syncTheme()

  return {
    getSnapshot: () => theme,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    activateUser(userId: number) {
      activeUserId = userId
      themePreference = null
      settingsTheme = null
      try {
        const value = storage.getItem(preferenceKey(userId))
        if (value === 'light' || value === 'dark') themePreference = value
      } catch {
        // Storage can be unavailable in a restricted browser context.
      }
      syncTheme()
    },
    deactivate() {
      activeUserId = null
      themePreference = null
      settingsTheme = null
      syncTheme()
    },
    setSettingsTheme(value: string | null) {
      if (activeUserId === null) return
      settingsTheme = value
      syncTheme()
    },
    toggleTheme() {
      if (activeUserId === null) return
      themePreference = theme === 'dark' ? 'light' : 'dark'
      try {
        storage.setItem(preferenceKey(activeUserId), themePreference)
      } catch {
        // Keep the selected theme in memory for the current session.
      }
      syncTheme()
    }
  }
}
