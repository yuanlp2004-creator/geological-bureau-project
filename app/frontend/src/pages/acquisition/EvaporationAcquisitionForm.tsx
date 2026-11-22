import { PreliminaryCaptureFields, type PreliminaryCaptureProps } from './PreliminaryCaptureFields'
import type { FormEvent } from 'react'

type Props = Omit<PreliminaryCaptureProps, 'kind'> & { create: (event: FormEvent) => Promise<void>; formId: string }

export function EvaporationAcquisitionForm({ create, formId, ...props }: Props) {
  return <form id={formId} className="acquisition-form preliminary-form" onSubmit={create}>
    <PreliminaryCaptureFields {...props} kind="evaporation" />
  </form>
}
