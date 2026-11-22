import { PreliminaryCaptureFields, type PreliminaryCaptureProps } from '../acquisition/PreliminaryCaptureFields'

type Props = Omit<PreliminaryCaptureProps, 'kind'>

export function DispersionSetup(props: Props) {
  return <div className="dispersion-setup preliminary-form"><PreliminaryCaptureFields {...props} kind="dispersion" /></div>
}
