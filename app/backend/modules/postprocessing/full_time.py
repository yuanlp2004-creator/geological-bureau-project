"""Export a whole CMT file or acquisition task at fixed measured peak positions."""
from collections import defaultdict
from functools import cache
import hashlib
from io import BytesIO
import json
from pathlib import Path

from ...db import utc_now
from ..acquisition import AcquisitionError, AcquisitionService
from ..legacy_migration import LegacyMigrationError
from ..methods import MethodDomainError
from ..spectrum_calibration import acquired_locations, legacy_location, locate_peaks
from ..spectrum_migration import SpectrumMigrationService
from ..spectrum_observation import acquired_exposure_frames, legacy_exposure_frames, LegacyObservationError
from .errors import PostProcessingError
from .serialization import _json


class FullTimeExport:
    def __init__(self, database, methods):
        self.database = database
        self.methods = methods
        self.acquisition = AcquisitionService(database)

    def _batches(self):
        groups = defaultdict(list)
        with self.database.read() as db:
            sources = SpectrumMigrationService.source_records(db, ('cmt',), include_ignition=True)
        for row in sorted(sources, key=lambda row: (row['source_sha256'], row['record_index'], row['id'])):
            key = 'raw:' + row['source_sha256']
            groups[key].append({
                'id': row['id'], 'burn_count': int(json.loads(row['ignition_json']).get('burn_count') or 0),
                'name': row['source_filename'] or f"CMT · {row['source_sha256'][:12]}",
            })
        for sample in reversed(self.acquisition.spectrum_records()):
            if sample['task_kind'] == 'sample' and sample['storage_mode'] == 'full_interval':
                groups[f"task:{sample['task_id']}"].append({
                    'id': sample['id'], 'burn_count': sample['burn_frame_count'], 'name': sample['task_name'],
                })
        return groups

    def options(self):
        current = self.methods.current()
        version = current.get('referenced_version')
        return {
            'current_method': {'id': version['id'], 'name': current['title'], 'version': version['version']} if version else None,
            'sources': [{'id': key, 'name': rows[0]['name'], 'kind': 'cmt' if key.startswith('raw:') else 'sample',
                         'record_count': len(rows), 'burn_count': min(row['burn_count'] for row in rows)}
                        for key, rows in self._batches().items()],
        }

    def export(self, payload, actor):
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell

        source, start, end = (payload[key] for key in ('source_id', 'start_frame', 'end_frame'))
        records = self._batches().get(source)
        if not records:
            raise PostProcessingError('full_time_source_missing', '未找到可导出的全时批次', status_code=404)
        if not 1 <= start <= end <= min(row['burn_count'] for row in records):
            raise PostProcessingError('full_time_interval_invalid', '曝光区间超出整批记录共同保存的燃烧帧')
        legacy = source.startswith('raw:')
        current = self.methods.current() if legacy else {}
        version = current.get('referenced_version')
        if legacy and (version is None or version['id'] != payload.get('method_version_id')):
            raise PostProcessingError('full_time_method_required', '请打开当前方法并刷新后再导出 CMT', status_code=409)

        workbook = Workbook(write_only=True)
        information = workbook.create_sheet('批次信息')
        frames = workbook.create_sheet('逐帧强度')
        peaks = workbook.create_sheet('谱线峰位')
        frames.freeze_panes = 'D2'
        peaks.freeze_panes = 'D2'

        def append(sheet, values):
            # A sample name or filename may begin with '='. Keep all labels as text.
            cells = []
            for value in values:
                cell = WriteOnlyCell(sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)

        peaks.append(['记录', '样品编号', '谱线', '波长 (nm)', '转角 (°)', 'CCD', '峰位', '区间背景', '状态'])
        method_id = None
        method_name = current.get('title')
        lines = []
        missed = 0
        found = 0
        digests = hashlib.sha256()
        try:
            for number, record in enumerate(records, 1):
                if legacy:
                    with self.database.read() as db:
                        row = SpectrumMigrationService.source_record(db, record['id'])
                    if row['format'] != 'cmt' or source != 'raw:' + row['source_sha256']:
                        raise PostProcessingError('full_time_source_changed', '导出期间 CMT 批次发生变化，请刷新后重试', status_code=409)
                    sample_name = row['sample_name'] or row['band_name']
                    layout = json.loads(row['layout_json'])
                    indices = layout.get('ccd_indices') or list(range(row['ccd_count']))
                    layout.update(ccd_count=row['ccd_count'], points_per_ccd=row['points_per_ccd'])
                    locate = lambda line: legacy_location(layout, line.get('actual_wavelength_nm') or line['wavelength_nm'])
                    decode = lambda slot: legacy_exposure_frames(row, slot)
                    band_label = lambda slot: (None, indices[slot])
                    group_for_slot = lambda slot: None
                    label = row['band_id'] if row['band_id'] is not None else number
                    digests.update(row['source_sha256'].encode('ascii'))
                else:
                    snapshot = self.acquisition.spectrum_snapshot(record['id'], include_frames=True)
                    sample = snapshot['sample']
                    sample_name = sample['sample_name']
                    label = int(sample['repeat_index']) + 1
                    version, method_name, positions = self._sample_method(snapshot, method_id, version, method_name)
                    locate = lambda line: positions.get(line['id'])
                    decode = lambda slot: acquired_exposure_frames(snapshot, slot)
                    bands = snapshot['bands']
                    band_label = lambda slot: (bands[slot].get('angle_deg'), bands[slot]['ccd_index'])
                    group_for_slot = lambda slot: bands[slot].get('turn_index')
                    digests.update(sample['result_sha256'].encode('ascii'))
                if method_id is None:
                    method_id = version['id']
                    lines = [line for line in version['lines'] if line['enabled']]
                    output_lines = [line for line in lines if not line.get('reference_baseline')]
                    if not output_lines:
                        raise PostProcessingError('full_time_lines_missing', '方法中没有可导出的有效谱线')
                    frames.append(['记录', '样品编号', '燃烧帧', '燃烧时间 (s)',
                                   *[f"{line['element']} {line['wavelength_nm']:g} nm" for line in output_lines]])
                read_frames = cache(decode)
                mean = cache(lambda slot, _: read_frames(slot).mean(start, end))
                columns = {}
                cycle = None
                for line, target, peak in locate_peaks(lines, locate, mean, group_for_slot=group_for_slot):
                    if line.get('reference_baseline'):
                        continue
                    angle, ccd = band_label(target[0]) if target else (None, None)
                    background = None
                    if target and peak is not None:
                        slot = target[0]
                        series = read_frames(slot)
                        cycle = series.burn_cycle
                        columns[line['id']] = series.intensities(peak, start, end)
                        if offset := int(line.get('background_offset_points', 0)):
                            values = mean(slot, None)
                            width = min(7, len(values))
                            left = max(0, min(peak + offset - width // 2, len(values) - width))
                            background = min(values[left:left + width])
                        found += 1
                    else:
                        missed += 1
                    append(peaks, [label, sample_name, line['element'], line['wavelength_nm'], angle,
                                   ccd + 1 if ccd is not None else None, peak + 1 if peak is not None else None,
                                   background, '已定位' if peak is not None else '未检出有效峰' if target else '谱线超出记录布局'])
                for index, frame in enumerate(range(start, end + 1)):
                    append(frames, [label, sample_name, frame, frame * cycle if cycle is not None else None,
                                    *[columns[line['id']][index] if line['id'] in columns else None for line in output_lines]])
            if not found:
                raise PostProcessingError('full_time_peaks_missing', '整批记录中没有找到有效谱线峰，请检查方法和曝光区间')
            for row in [
                ['来源', records[0]['name']], ['方法', method_name], ['方法版本', version['version']],
                ['方法版本 ID', method_id], ['起始帧', start], ['结束帧', end], ['记录数', len(records)],
                ['未检出或越界的谱线数', missed], ['来源标识', source],
            ]:
                append(information, row)
            output = BytesIO()
            workbook.save(output)
        except (AcquisitionError, LegacyMigrationError, MethodDomainError, LegacyObservationError) as exc:
            raise PostProcessingError('full_time_frames_invalid', f"第 {number} 条记录：{exc}") from exc
        finally:
            for sheet in workbook.worksheets:
                if not sheet.closed:
                    sheet.close()
                # openpyxl normally removes its staging XML on save; failed batches also need cleanup.
                if sheet._writer is not None and Path(sheet._writer.out).is_file():
                    sheet._writer.cleanup()
        content = output.getvalue()
        if len(content) > 64 * 1024 * 1024:
            raise PostProcessingError('full_time_workbook_too_large', '工作簿超过桌面保存的 64 MiB 限制，请缩小曝光区间')
        with self.database.write() as db:
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,details_json,created_at) "
                       "VALUES (?,'postprocessing.full_time.export','postprocessing',?,?)",
                       (actor, _json(payload | {'record_count': len(records), 'method_version_id': method_id,
                                               'source_digest': digests.hexdigest(), 'sha256': hashlib.sha256(content).hexdigest()}), utc_now()))
        return content

    def _sample_method(self, snapshot, expected_id, version, name):
        version_id = snapshot['sample'].get('method_version_id')
        if version_id is None or (expected_id is not None and version_id != expected_id):
            raise PostProcessingError('full_time_method_required', '批次没有统一的已发布方法版本')
        with self.database.read() as db:
            if version is None:
                method = self.methods.bind_snapshots(db).by_id(version_id, published_only=True)
                if method is None:
                    raise PostProcessingError('full_time_method_required', '采集绑定的方法版本不存在')
                version, name = method.print_version(), method.method.name
            positions = {}
            if not snapshot.get('turns'):
                locator = self.methods.bind_geometry(db, version['conditions'])
                positions = {line['id']: locator.locate(line.get('actual_wavelength_nm') or line['wavelength_nm'])
                             for line in version['lines']}
        return version, name, acquired_locations(snapshot, positions)
