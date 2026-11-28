const compatibilityGroups = new Set(['hardware-acquisition', 'mercury-calibration', 'results'])
const availableCompatibilityKeys = ['hardware-acquisition.read', 'hardware-acquisition.execute', 'mercury-calibration.read']

export function isCompatibilityPermission(key: string): boolean {
  return compatibilityGroups.has(key.split('.')[0])
}

export function isAvailablePermission(key: string): boolean {
  return !isCompatibilityPermission(key) || availableCompatibilityKeys.includes(key)
}

export function selectablePermissions(keys: string[], retainedKeys: string[] = []): string[] {
  return [...new Set([...keys.filter(isAvailablePermission), ...retainedKeys])]
}
