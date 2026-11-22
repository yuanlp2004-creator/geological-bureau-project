"""Compose existing public services for the two legacy condition dialogs."""
from fastapi import HTTPException
from uuid import uuid4
from ..modules.devices import DeviceError
from ..modules.methods import MethodDomainError
from ..schemas.preliminary import PreliminaryCaptureCreate
from ..schemas.dispersion import DispersionTaskCreate
from ..schemas.system import PreliminaryConditions


def create_preliminary_session(kind, payload: PreliminaryCaptureCreate, runtime, session):
    profile = runtime.devices_service().current_profile()
    if not profile:
        raise HTTPException(422, detail={'code': 'current_device_required', 'message': '请先在设备参数选择并保存当前设备'})
    methods = runtime.methods_service()
    method = methods.current()
    if not method['method_id'] or not method['actions']['can_acquire']:
        raise HTTPException(422, detail={'code': 'current_method_required', 'message': '请先打开可用于摄谱的当前方法'})
    try:
        with runtime.database.read() as db:
            plan = methods.preliminary_turns(db, method['referenced_version']['id'])
    except MethodDomainError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc
    multiple = len(plan['angles']) > 1
    if profile['transport'] == 'serial':
        permission = 'dispersion.execute' if kind == 'dispersion' else 'acquisition.execute'
        if permission not in session.permissions:
            raise HTTPException(403, detail='permission denied')
        if multiple:
            raise HTTPException(409, detail={'code': 'hardware_protocol_unavailable',
                                            'message': '真实自动转角协议尚未确认，不能执行多转角摄谱'})
        try:
            runtime.devices_service().test_connection(profile['id'], actor_user_id=session.user_id)
        except DeviceError as exc:
            raise HTTPException(exc.status_code, detail=exc.detail()) from exc
    conditions = {key: value for key, value in payload.model_dump().items() if key not in {'name', 'save_conditions'}}
    common = {**conditions, 'name': payload.name, 'device_profile_id': profile['id'],
              'method_id': method['method_id'], 'method_version': method['version'], 'ccd_layout_id': plan['layout_id']}
    if kind == 'evaporation':
        values = {**common, 'task_kind': 'evaporation', 'sample_name': payload.name,
                  'burn_frame_count': payload.frame_count, 'storage_mode': 'full_interval', 'repeat_count': 1,
                  'burn_cycle_seconds': payload.sampling_period_seconds, 'dark_cycle_seconds': payload.sampling_period_seconds}
        service = runtime.acquisition_service()
        source = 'acquisition'
        default_ccds = plan['selected_ccds']
    else:
        values = DispersionTaskCreate.model_validate(common).model_dump()
        service = runtime.dispersion_service()
        source = 'dispersion'
        default_ccds = [index for index in plan['layout']['ccd_indices'] if index in profile['ccd_indices']]
    layout = plan['layout']
    if (not default_ccds or any(layout[key] != profile[key] for key in ('frame_count', 'ccds_per_frame', 'points_per_ccd'))
            or abs(layout['point_width'] - profile['point_width_um']) >= 1e-6):
        raise HTTPException(422, detail={'code': 'device_layout_missing', 'message': '当前设备与方法的CCD布局不匹配，请先核对设备参数'})
    group = uuid4().hex
    with runtime.database.write() as connection:
        first_id = None
        for index, angle in enumerate(plan['angles']):
            indices = angle.get('ccd_indices') or default_ccds
            if not set(indices) <= set(profile['ccd_indices']):
                raise HTTPException(422, detail={'code': 'ccd_profile_selection_invalid', 'message': '方法转角选择了当前设备未安装的CCD'})
            turn = {'group': group, 'turn_index': index, 'angle_deg': angle['angle_deg'], 'multiple': multiple,
                    'method_content_sha256': plan['method_content_sha256']}
            if kind == 'dispersion':
                turn['reference_coefficients'] = angle.get('reference_coefficients', layout['ws_cof'])
            task = service.create_task({**values, 'ccd_indices': indices}, session.user_id, connection=connection, capture_turn=turn)
            if first_id is None:
                first_id = task['id']
        if payload.save_conditions:
            runtime.service.save_preliminary_conditions(kind, PreliminaryConditions.model_validate(conditions),
                                                        session.user_id, connection=connection)
    return runtime.messages.task(service.get_task(first_id), source=source, category='acquisition')
