import { AcquisitionWorkspace } from './AcquisitionWorkspace'
import type { Props } from './acquisitionView'

export function SampleAcquisitionPage(props: Props) {
  return <AcquisitionWorkspace {...props} taskKind="sample" />
}
