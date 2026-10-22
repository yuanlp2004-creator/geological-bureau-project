export function calculationProfileLabel(profile: string): string {
  if (profile === 'legacy_2_0_2') return '旧版兼容'
  if (profile === 'modern_v1') return '新版定量（支持峰面积）'
  return profile
}
