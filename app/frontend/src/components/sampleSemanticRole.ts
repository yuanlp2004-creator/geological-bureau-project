export type SampleSemanticRole = 'standard' | 'control' | 'neutral'

export const sampleRoleLabels = { standard: '标样', control: '管理样', neutral: '' } satisfies Record<SampleSemanticRole, string>

type MethodStandardLine = {
  standard_points?: readonly { name: string; value: number; active: boolean }[]
}

export function extractMethodStandardNames(lines: readonly MethodStandardLine[] = []): ReadonlySet<string> {
  const names = new Set<string>()
  for (const line of lines) {
    for (const point of line.standard_points ?? []) {
      if (point?.active !== true || !Number.isFinite(point.value) || typeof point.name !== 'string') continue
      const name = point.name.trim()
      if (name) names.add(name)
    }
  }
  return names
}

export type SampleRoleEvidence = {
  explicitManagementTask?: boolean
  qualityManagementSample?: boolean
  sourceKind?: string
  sampleNumbering?: boolean
}

export function acquisitionSourceKind(source?: { sample_kind: string; sample_name: string }): string | undefined {
  // The acquisition repository also coerces S-prefixed names to 'standard'.
  // Those flags need independent evidence from the method's standard points.
  return source?.sample_kind === 'standard' && !/^s/i.test(source.sample_name.trim()) ? 'standard' : undefined
}

export function resolveSampleSemanticRole({
  name, methodStandardNames, explicitManagementTask, qualityManagementSample, sourceKind, sampleNumbering,
}: SampleRoleEvidence & { name: string; methodStandardNames?: ReadonlySet<string> }): SampleSemanticRole {
  const trimmed = name.trim()
  // The numbered quality branch infers both flags from the assigned name.
  if (explicitManagementTask === true || (!sampleNumbering && qualityManagementSample === true)) return 'control'
  if ((!sampleNumbering && sourceKind === 'standard') || (trimmed && methodStandardNames?.has(trimmed))) return 'standard'
  return 'neutral'
}
