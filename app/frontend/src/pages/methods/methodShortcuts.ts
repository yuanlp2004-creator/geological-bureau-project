export type MethodShortcutAction = 'create' | 'open' | 'copy'

export type MethodShortcutRequest = {
  id: number
  action: MethodShortcutAction
}
