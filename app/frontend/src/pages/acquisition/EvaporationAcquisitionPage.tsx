import { AcquisitionWorkspace } from './AcquisitionWorkspace'
import type { Props } from './acquisitionView'

export function EvaporationAcquisitionPage(props: Props) {
  return <AcquisitionWorkspace {...props} taskKind="evaporation" />
}
