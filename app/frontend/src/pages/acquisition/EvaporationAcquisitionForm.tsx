import { Flame } from 'lucide-react'
import { AcquisitionSetupFields, AcquisitionTimingFields } from './AcquisitionConditionFields'
import type { FormEvent } from 'react'
import type { AcquisitionConditionsProps } from './AcquisitionConditionFields'

type Props = AcquisitionConditionsProps & { create: (event: FormEvent) => Promise<void>; saveConditions: () => Promise<void>; formId?: string; hideSubmit?: boolean }

export function EvaporationAcquisitionForm(props: Props) {
  return (
    <section className="surface acquisition-create">
      <div className="surface-heading">
        <h2>建立蒸发摄谱任务</h2>
        <Flame size={17} />
      </div>
      <form id={props.formId} className="acquisition-form" onSubmit={props.create}>
        <AcquisitionSetupFields {...props} />
        <AcquisitionTimingFields {...props} conditionsLocked={false} />
        <p className="acquisition-management-note">每次实验保存完整时间序列，供蒸发曲线和有效区间研究。</p>
        <button className="secondary-button" type="button" onClick={() => void props.saveConditions()}
          disabled={!props.canWrite || props.busy}>保存激发条件</button>
        {!props.hideSubmit && <button className="primary-button acquisition-create-button" type="submit"
          disabled={!props.canWrite || props.busy || !props.profileId}>
          <Flame size={15} />创建任务
        </button>}
      </form>
    </section>
  )
}
