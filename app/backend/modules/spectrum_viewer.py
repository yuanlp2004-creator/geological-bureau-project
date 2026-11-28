from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import struct
from typing import Any


from ..db import Database
from .spectrum_pdf import render_spectrum_pdf, _SPECTRUM_PDF_COLORS


def point_details_text(details: dict, orientation: str) -> str:
    """Clipboard export uses the same verified raw values as the detail view and PDF."""
    header = f"{details['sample_name']}\tCCD{details['ccd_index'] + 1}\t点{details['point_index'] + 1}\t{details.get('wavelength_nm') or ''}"
    if orientation == 'vertical':
        return '\n'.join([header, '阶段\t积分序号\t原始强度 ADC',
            *[f"{'燃烧' if row['phase'] == 'burn' else '空白'}\t{row['integration']}\t{row['value']}" for row in details['rows']]])
    if orientation == 'horizontal':
        return '\t'.join([header,
            *[f"{'燃烧' if row['phase'] == 'burn' else '空白'}{row['integration']}\t{row['value']}" for row in details['rows']]])
    raise SpectrumViewerError('spectrum_copy_orientation_invalid', '复制方向无效', status_code=422)


class SpectrumViewerError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 404, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _finite(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _sample_band_frames(snapshot: dict, band: dict, phase: str) -> list[dict]:
    # 独立转角各自拥有一个任务，只有共用采集任务的多转角谱带需要按转角再筛选帧。
    turn_index = band.get("turn_index")
    return [row for row in snapshot["frames"]
            if row["ccd_index"] == band["ccd_index"] and row["phase"] == phase
            and (turn_index is None or row.get("turn_index") == turn_index)]


def _wave(step: float, coefficients: list[float]) -> float | None:
    if len(coefficients) < 3:
        return None
    a, b, c = (float(item) for item in coefficients[:3])
    if not all(math.isfinite(item) for item in (a, b, c)):
        return None
    if a == 0:
        return _finite((step - c) / b) if b else None
    discriminant = b * b - 4.0 * a * (c - step)
    if discriminant < 0:
        return None
    return _finite((math.sqrt(discriminant) - b) / (2.0 * a))


class SpectrumViewerService:
    """Read-side query service for published S08/S09 spectrum records.

    The service never rewrites migration tables or recalculates analysis values.
    It exposes complete stored points for the selected CCD/line and loads raw
    acquisition frames only when explicitly requested by the viewer.
    """

    def __init__(self, database: Database):
        self.database = database

    def list(
        self, *, kind: str = "all", limit: int = 100, angle_deg: float | None = None, offset: int = 0,
        query: str = "", scope: str = "all", group: str = "",
    ) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = self._catalog_rows(
                db, scope=scope, kind=kind, query=query, angle_deg=angle_deg, group=group,
                limit=max(1, min(int(limit), 200)), offset=max(0, offset),
            )
            records = []
            for row in rows:
                record = {key: row[key] for key in ('id', 'kind', 'format', 'source_sha256', 'sample_name', 'band_name')}
                if row['kind'] != 'result':
                    record['angle_deg'] = row['angle']
                if row['kind'] == 'sample':
                    record.update(task_id=row['task_id'], task_name=row['task_name'], task_kind=row['task_kind'])
                    collection = _json(row['collection'], None)
                    if collection:
                        record.update(file_group_key='prepared:' + collection['id'], file_group_name=collection['name'])
                    elif row['turn_group'] is not None:
                        record.update(file_group_key='evaporation:' + row['turn_group'], turn_index=row['turn_index'])
                elif row['format'] == 'dispersion':
                    record['task_name'] = row['task_name']
                record.update(_json(row['summary'], {}))
                records.append(record)
            return records

    @staticmethod
    def _catalog_rows(db, *, scope, kind, query, angle_deg, group="", limit=None, offset=0):
        from .acquisition import AcquisitionService
        from .dispersion import DispersionService
        from .postprocessing import prepared_collection_index_sql

        if kind not in {'all', 'raw', 'result', 'sample'}:
            raise SpectrumViewerError("spectrum_kind_invalid", "kind must be all, raw, or result", status_code=422)
        if scope not in {'all', 'evaporation'}:
            raise SpectrumViewerError('spectrum_scope_invalid', '查看范围无效', status_code=422)

        term = query.strip().casefold()
        db.create_function('catalog_angle', 1, _finite, deterministic=True)
        db.create_function('catalog_turn_name', 2, lambda name, angle: f"{name} · {angle:g}°", deterministic=True)
        db.create_function('catalog_digest', 1, lambda hashes: hashlib.sha256(hashes.encode('ascii')).hexdigest(),
                           deterministic=True)
        db.create_function('catalog_search', 5, lambda identifier, name, names, band, digest:
                           ' '.join(str(value or '') for value in
                                    (identifier, name, _json(names, []), band, digest)).casefold(), deterministic=True)

        branches = []
        page = limit is not None
        params = {'term': term, 'angle': angle_deg, 'group': group, 'limit': limit, 'offset': offset}
        if page:
            params['source_limit'] = min(offset + limit, 2**63 - 1)
            params['offset'] = min(offset, 2**63 - 1)

        def add(source, prefix, rank, *, where=(), summary, **fields):
            record_kind = 'raw' if prefix == 'dispersion' else prefix
            columns = {
                'id': f"'{prefix}:' || id", 'sort_id': 'id', 'kind': f"'{record_kind}'", 'rank': str(rank),
                'format': 'format', 'source_sha256': 'source_sha256', 'file_key': f"'{record_kind}:' || source_sha256",
                'task_id': 'NULL', 'task_name': 'NULL', 'task_kind': 'NULL', 'file_group_name': 'NULL',
                'sample_name': 'sample_name', 'sample_names': 'NULL', 'band_name': 'NULL', 'angle': 'NULL',
                'collection': 'NULL', 'turn_group': 'NULL', 'turn_index': 'NULL',
            } | fields
            output = ['id', 'sort_id', 'kind', 'rank', 'format', 'source_sha256',
                      'task_id', 'task_name', 'task_kind']
            if page:
                columns['summary'] = summary
                output += ['sample_name', 'band_name', 'angle', 'collection', 'turn_group', 'turn_index', 'summary']
            else:
                output += ['file_key', 'file_group_name']
            filters = list(where)
            if angle_deg is not None:
                filters.append(f"abs(({columns['angle']}) - :angle) <= 0.000001")
            if term:
                values = ', '.join(columns[key] for key in ('id', 'sample_name', 'sample_names', 'band_name', 'source_sha256'))
                filters.append(f'instr(catalog_search({values}), :term) > 0')
            if group:
                keys = f"({columns['file_key']}) = :group"
                if prefix == 'sample':
                    keys += " OR 'task:' || task_id = :group"
                filters.append(f'({keys})')
            fields_sql = ', '.join(f'{columns[key]} AS {key}' for key in output)
            restriction = ' WHERE ' + ' AND '.join(filters) if filters else ''
            # A global page cannot use a row below offset+limit within any one source.
            # Keep each indexed ID scan bounded before the cross-source merge.
            bound = ' ORDER BY sort_id DESC LIMIT :source_limit' if page else ''
            branches.append(f'SELECT * FROM (SELECT {fields_sql} FROM {source}{restriction}{bound})')

        if kind in {'all', 'raw'}:
            details = "CASE WHEN json_valid(details_json) THEN details_json END"
            ignition = "CASE WHEN json_valid(ignition_json) THEN ignition_json END"
            add('spectrum_bands', 'raw', 0, where=("format='edt'",) if scope == 'evaporation' else (),
                band_name="coalesce(nullif(band_name, ''), long_name)",
                angle=f"catalog_angle(json_extract({details}, '$.angle_deg'))",
                summary=f"""json_object('record_index', record_index, 'band_id', band_id, 'sample_no', sample_no,
                    'measure_time', measure_time, 'frame_count', frame_count,
                    'burn_count', coalesce(json_extract({ignition}, '$.burn_count'), 0),
                    'ccd_count', ccd_count, 'points_per_ccd', points_per_ccd,
                    'available', json_object('mean', json(iif(mean_blob IS NULL, 'false', 'true')),
                        'burn', json(iif(burn_adcs_blob IS NULL, 'false', 'true')),
                        'dark', json(iif(dark_adcs_blob IS NULL, 'false', 'true'))))""")
        if scope == 'all' and kind in {'all', 'result'} and angle_deg is None:
            payload = 'CASE WHEN json_valid(payload_json) THEN payload_json END'

            def field(key):
                return f"json_extract({payload}, '$.{key}')"

            names = field('sample_names')
            add('result_matrices', 'result', 1, sample_name=field('sample_names[0]'), sample_names=names,
                summary=f"""json_object('record_index', record_index, 'sample_names', json(coalesce({names}, '[]')),
                    'measure_time', {field('measure_time')}, 'line_count', coalesce({field('line_count')}, 0),
                    'band_count', coalesce({field('band_count')}, 0), 'sample_count', coalesce({field('sample_count')}, 0),
                    'matrix_kind', {field('matrix_kind')}, 'method_match_status', {field('method_match_status')})""")
        if kind in {'all', 'sample'}:
            collection = f"({prepared_collection_index_sql()})"
            prepared_key = f"'prepared:' || json_extract({collection}, '$.id')"
            prepared_name = f"json_extract({collection}, '$.name')"
            turn_group = "json_extract(capture_turn_json, '$.group')"
            angle = "json_extract(capture_turn_json, '$.angle_deg')"
            add(f'({AcquisitionService.spectrum_index_sql()}) sample', 'sample', 2,
                where=("task_kind='evaporation'",) if scope == 'evaporation' else (),
                format="'acquisition'", source_sha256='result_sha256', task_id='task_id', task_name='task_name',
                task_kind='task_kind', file_group_name=prepared_name,
                collection=collection, turn_group=turn_group, turn_index="json_extract(capture_turn_json, '$.turn_index')",
                file_key=f"coalesce({prepared_key}, 'evaporation:' || {turn_group}, 'task:' || task_id)",
                band_name=f"CASE WHEN capture_turn_json IS NOT NULL THEN catalog_turn_name(coalesce(nullif(sample_name, ''), task_name), {angle}) END",
                angle=angle,
                summary=f"""json_object('record_index', id, 'repeat_index', repeat_index,
                    'storage_mode', storage_mode, 'method_id', method_id,
                    'method_version', method_version, 'measure_time',
                    coalesce(nullif(json_extract(simulator_json, '$.measure_time'), ''), completed_at),
                    'frame_count', frame_count, 'burn_count', frame_count,
                    'ccd_count', json_array_length(ccd_indices_json), 'points_per_ccd', points_per_ccd,
                    'available', json_object('mean', json('true'), 'burn', json(iif(storage_mode='full_interval', 'true', 'false')),
                        'dark', json(iif(storage_mode='full_interval', 'true', 'false'))))""")
        if scope == 'all' and kind in {'all', 'raw'}:
            turn_group = """CASE WHEN json_extract(condition_json, '$.capture_turn.multiple')
                THEN nullif(json_extract(condition_json, '$.capture_turn.group'), '') END"""
            angle = "json_extract(condition_json, '$.capture_turn.angle_deg')"
            file_key = f"'dispersion:' || coalesce({turn_group}, id)"
            add(f'({DispersionService.spectrum_index_sql()})', 'dispersion', 3,
                format="'dispersion'", source_sha256='catalog_digest(frame_hashes)', task_name='name',
                sample_name='name', file_key=file_key, angle=angle,
                band_name=f"CASE WHEN ({turn_group}) IS NOT NULL THEN catalog_turn_name(name, {angle}) ELSE name END",
                summary=f"""json_object('record_index', id, 'file_group_key', {file_key},
                    'measure_time', completed_at, 'turn_index', json_extract(condition_json, '$.capture_turn.turn_index'),
                    'frame_count', frame_count, 'burn_count', frame_count, 'ccd_count', json_array_length(ccd_indices_json),
                    'points_per_ccd', points_per_ccd, 'available', json_object('mean', json('true'), 'burn', json('true'),
                    'dark', json(iif(dark_frame_count > 0, 'true', 'false'))))""")
        if not branches:
            return ()
        bound = ' LIMIT :limit OFFSET :offset' if page else ''
        return db.execute(' UNION ALL '.join(branches) + ' ORDER BY sort_id DESC, kind, rank' + bound, params)

    @staticmethod
    def file_group(record: dict) -> str:
        return record.get('file_group_key') or (f"task:{record['task_id']}" if record.get('task_id') else f"{record['kind']}:{record['source_sha256']}")

    def files(self, *, scope: str = 'all', kind: str = 'all', query: str = '', angle_deg: float | None = None) -> list[dict]:
        """List logical files with the first matching record and a count."""
        from .spectrum_migration import SpectrumMigrationService

        groups: dict[str, dict] = {}
        with self.database.read() as db:
            rows = self._catalog_rows(db, scope=scope, kind=kind, query=query, angle_deg=angle_deg)
            for row in rows:
                key = row['file_key']
                if key not in groups:
                    item = {field: row[field] for field in ('id', 'kind', 'format', 'source_sha256', 'task_id', 'task_name', 'task_kind')}
                    item['task_name'] = row['file_group_name'] or row['task_name']
                    groups[key] = item | {'key': key, 'record_count': 0}
                groups[key]['record_count'] += 1
            names = SpectrumMigrationService.file_names(db)
        return [item | {'source_filename': names.get(item['source_sha256'])} for item in groups.values()]

    def _dispersion(self, identifier: int, *, ccd: int, detail: str, phase: str, frame: int,
                    exposure_start: int | None, exposure_end: int | None) -> dict[str, Any]:
        from .dispersion import DispersionError, DispersionService

        try:
            snapshot = DispersionService(self.database).spectrum_snapshot(identifier, ccd)
        except DispersionError as exc:
            raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc
        record, layout = snapshot["record"], snapshot["layout"]
        physical_ccd = layout["ccd_indices"][ccd]
        left_step = physical_ccd * layout["points_per_ccd"] + sum(layout["gap_points"][:physical_ccd])

        def points(values):
            return [{"point_index": index, "step": left_step + index, "value": value,
                     "wavelength_nm": _wave(left_step + index, layout["ws_cof"])}
                    for index, value in enumerate(values)]

        burn_count = record["frame_count"]
        start = exposure_start if exposure_start is not None else 1
        end = exposure_end if exposure_end is not None else burn_count
        if (exposure_start is None) != (exposure_end is None) or not 1 <= start <= end <= burn_count:
            raise SpectrumViewerError("spectrum_exposure_invalid", "曝光区间超出保存帧范围", status_code=422)
        burns = [row for row in snapshot["frames"] if row["phase"] == "burn" and start - 1 <= row["frame_index"] < end]
        if [row["frame_index"] for row in burns] != list(range(start - 1, end)):
            raise SpectrumViewerError("spectrum_frames_unavailable", "色散谱带缺少所选区间的原始帧", status_code=409)
        if any(len(row["points"]) != layout["points_per_ccd"] for row in snapshot["frames"]):
            raise SpectrumViewerError("spectrum_frame_shape_invalid", "色散原始帧与 CCD 布局不一致", status_code=409)
        values = [sum(values) / len(burns) for values in zip(*(row["points"] for row in burns))]
        ccd_data = {"position": ccd, "index": physical_ccd, "points": points(values)}
        frame_detail = None
        if detail == "frame":
            if phase not in {"burn", "dark"}:
                raise SpectrumViewerError("spectrum_phase_invalid", "阶段必须是 burn 或 dark", status_code=422)
            frames = [row for row in snapshot["frames"] if row["phase"] == phase]
            if not 0 <= frame < len(frames) or frames[frame]["frame_index"] != frame:
                raise SpectrumViewerError("spectrum_frame_invalid", "所选色散原始帧不存在", status_code=422)
            frame_detail = {"phase": phase, "index": frame, "frame_count": len(frames),
                            "ccd": {**ccd_data, "points": points(frames[frame]["points"])}}
        turn = record["condition"].get("capture_turn") or {}
        return {
            "id": f"dispersion:{identifier}", "kind": "raw", "format": "dispersion",
            "source_sha256": record["source_sha256"], "record_index": identifier, "sample_name": record["name"],
            "band_name": record["name"], "measure_time": record["completed_at"], "angle_deg": turn.get("angle_deg"),
            "layout": layout, "ccd": ccd_data, "frame_detail": frame_detail,
            "exposure_segment": {"start": start, "end": end, "count": len(burns)},
            "ignition": {"pre_burn": record["pre_excitation_seconds"], "burn_cyc": record["sampling_period_seconds"],
                         "dark_cyc": record["sampling_period_seconds"], "burn_count": burn_count,
                         "dark_count": record["dark_frame_count"]},
        }

    def _sample(
        self,
        identifier: int,
        *,
        ccd: int,
        detail: str,
        phase: str,
        frame: int,
        exposure_start: int | None,
        exposure_end: int | None,
        snapshot: dict | None = None,
    ) -> dict[str, Any]:
        from .acquisition import AcquisitionService, AcquisitionError

        try:
            if snapshot is None:
                snapshot = AcquisitionService(self.database).spectrum_snapshot(
                    identifier, band_position=ccd,
                    include_frames=detail == "frame" or exposure_start is not None or exposure_end is not None,
                )
        except AcquisitionError as exc:
            raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc
        sample, bands = snapshot["sample"], snapshot["bands"]
        observation_lines = []
        if snapshot.get('turns'):
            observation_lines = [{**line, 'turn_index': turn['turn_index'], 'angle_deg': turn['angle_deg'],
                'exposure_start_frame': line['exposure_interval'][0] if line['exposure_interval'] else None,
                'exposure_end_frame': line['exposure_interval'][1] if line['exposure_interval'] else None}
                for turn in snapshot['turns']['plan'] for line in turn['lines']]
        elif sample.get('method_version_id'):
            from .methods import MethodService
            methods = MethodService(self.database)
            with self.database.read() as connection:
                version = methods.bind_snapshots(connection).by_id(sample['method_version_id'], published_only=True)
                if version:
                    locator = methods.bind_geometry(connection, version.payload['conditions'])
                    for item in version.print_version()['lines']:
                        wave = item.get('actual_wavelength_nm') or item['wavelength_nm']
                        position = locator.locate(wave)
                        observation_lines.append({key:item.get(key) for key in ('id','element','wavelength_nm','exposure_start_frame','exposure_end_frame')} |
                            {'ccd_index':position.ccd_index if position else None, 'point_index':int(round(position.point)) if position else None})
        if not 0 <= ccd < len(bands):
            raise SpectrumViewerError(
                "spectrum_ccd_invalid", "CCD 超出实际采集布局", status_code=422, details={"ccd_count": len(bands)}
            )
        band = bands[ccd]
        source_layout = _json(sample.get('simulator_json'), {}).get('source_layout')
        physical_index = int(band['ccd_index'])
        left_step = (physical_index * len(band['mean_points']) + sum(source_layout.get('gap_points', [])[:physical_index])) if source_layout else 0
        points = lambda values: [
            {"point_index": index, "step": left_step + index,
             "wavelength_nm": band['wavelengths_nm'][index] if band.get('wavelengths_nm') else _wave(left_step + index, source_layout.get('ws_cof', [])) if source_layout else None, "value": value}
            for index, value in enumerate(values)
        ]
        values = band["mean_points"]
        frames = [row for row in _sample_band_frames(snapshot, band, phase) if row.get("points")]
        frame_detail = None
        exposure = None
        if detail == "frame" or exposure_start is not None or exposure_end is not None:
            if not frames:
                raise SpectrumViewerError(
                    "spectrum_frames_unavailable", "该样品未保存此阶段的完整原始帧，仅可查看固化均值", status_code=409
                )
            if any(row['damaged'] or len(row['points']) != len(values) for row in frames):
                raise SpectrumViewerError('spectrum_frame_integrity_failed', '原始帧损坏或与 CCD 布局不一致', status_code=409)
            if detail == "frame":
                if not 0 <= frame < len(frames):
                    raise SpectrumViewerError("spectrum_frame_invalid", "帧序号超出范围", status_code=422)
                frame_detail = {
                    "phase": phase,
                    "index": frame,
                    "frame_count": len(frames),
                    "ccd": {"position": ccd, "index": band["ccd_index"], "points": points(frames[frame]["points"])},
                }
            else:
                if (
                    exposure_start is None
                    or exposure_end is None
                    or not 1 <= exposure_start <= exposure_end <= len(frames)
                ):
                    raise SpectrumViewerError("spectrum_exposure_invalid", "曝光区间超出保存帧范围", status_code=422)
                chosen = frames[exposure_start - 1 : exposure_end]
                values = [sum(row["points"][i] for row in chosen) / len(chosen) for i in range(len(values))]
                exposure = {"start": exposure_start, "end": exposure_end, "count": len(chosen)}
        return {
            "id": f"sample:{identifier}",
            "kind": "sample",
            "format": "acquisition",
            "source_sha256": sample["result_sha256"],
            "record_index": identifier,
            "observation_lines": [line for line in observation_lines if line.get('turn_index') == band.get('turn_index')],
            "sample_name": sample["sample_name"],
            **{key: sample[key] for key in ('task_id', 'task_name', 'task_kind', 'repeat_index', 'storage_mode', 'method_id', 'method_version')},
            "measure_time": _json(sample.get('simulator_json'), {}).get('measure_time') or sample["completed_at"],
            "angle_deg": band.get('angle_deg'),
            "turn_index": band.get('turn_index'),
            "coordinate_system": f"ccd_pixel:{band['ccd_index']}" + (f":angle:{band['angle_deg']}" if 'angle_deg' in band else ''),
            "layout": {"ccd_count": len(bands), "ccd_indices": [item['ccd_index'] for item in bands],
                       'band_labels': [f"{item['angle_deg']:g}° · CCD {item['ccd_index'] + 1}" if 'angle_deg' in item else f"CCD {item['ccd_index'] + 1}" for item in bands],
                       'band_turn_indices': [item.get('turn_index') for item in bands],
                       "points_per_ccd": len(values), "point_width_um": snapshot['point_width_um']},
            "ignition": {
                "pre_burn": sample["pre_excitation_seconds"],
                "burn_cyc": sample["burn_cycle_seconds"],
                "dark_cyc": sample["dark_cycle_seconds"],
                "burn_count": json.loads(sample["simulator_json"] or "{}").get(
                    "source_frame_count", sample["burn_frame_count"]
                ),
                "dark_count": sample["dark_frame_count"],
            },
            "ccd": {"position": ccd, "index": band["ccd_index"], "points": points(values)},
            "frame_detail": frame_detail,
            "exposure_segment": exposure,
        }

    def get(
        self,
        record_id: str,
        *,
        ccd: int = 0,
        line: int = 0,
        detail: str = "summary",
        phase: str = "burn",
        frame: int = 0,
        exposure_start: int | None = None,
        exposure_end: int | None = None,
        intensity_mode: str = "stored",
        verify_source: bool = False,
    ) -> dict[str, Any]:
        if intensity_mode not in {'stored','legacy_2_0_2'}:
            raise SpectrumViewerError('spectrum_intensity_mode_invalid','强度显示口径无效',status_code=422)
        kind, identifier = self._parse_record_id(record_id)
        if detail not in {"summary", "frame"}:
            raise SpectrumViewerError("spectrum_detail_invalid", "detail must be summary or frame", status_code=422)
        if kind == "dispersion":
            return self._dispersion(identifier, ccd=ccd, detail=detail, phase=phase, frame=frame,
                                    exposure_start=exposure_start, exposure_end=exposure_end)
        if kind == "sample":
            return self._sample(
                identifier,
                ccd=ccd,
                detail=detail,
                phase=phase,
                frame=frame,
                exposure_start=exposure_start,
                exposure_end=exposure_end,
            )
        with self.database.read() as db:
            if kind == "raw":
                interval = exposure_start is not None or exposure_end is not None
                legacy_mean = intensity_mode == 'legacy_2_0_2' and detail != 'frame'
                row = self._raw_row(db, identifier, burn=legacy_mean or interval or (detail == 'frame' and phase == 'burn'),
                                    dark=legacy_mean or (detail == 'frame' and phase == 'dark'))
                if row is None:
                    raise SpectrumViewerError("spectrum_record_not_found", "Spectrum record was not found")
                from .postprocessing import prepared_working_layout
                return self._raw(
                    row,
                    ccd=ccd,
                    detail=detail,
                    phase=phase,
                    frame=frame,
                    exposure_start=exposure_start,
                    exposure_end=exposure_end,
                    intensity_mode=intensity_mode,
                    working_layout=prepared_working_layout(self.database, row['source_sha256']),
                    verify_source=verify_source,
                )
            row = db.execute("SELECT * FROM result_matrices WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise SpectrumViewerError("spectrum_record_not_found", "Result matrix was not found")
            return self._result(row, line=line)

    @staticmethod
    def _parse_record_id(record_id: str) -> tuple[str, int]:
        try:
            kind, identifier = record_id.split(":", 1)
            identifier = int(identifier)
            if kind in {"raw", "result", "sample", "dispersion"} and identifier > 0:
                return kind, identifier
        except (ValueError, AttributeError):
            pass
        raise SpectrumViewerError(
            "spectrum_record_invalid", "record id must be raw:<id> or result:<id>", status_code=422
        )

    @staticmethod
    def _raw_row(db, identifier, *, burn=False, dark=False):
        burn_column = 'burn_adcs_blob' if burn else 'NULL AS burn_adcs_blob'
        dark_column = 'dark_adcs_blob' if dark else 'NULL AS dark_adcs_blob'
        return db.execute(f"""SELECT id, format, source_sha256, record_index, band_id, sample_name, sample_no,
            band_name, long_name, measure_time, real_ref_step, ccd_count, points_per_ccd, layout_json,
            ignition_json, details_json, bad_frame_indices_json, mean_blob, mean_sha256, burn_sha256, dark_sha256,
            {burn_column}, {dark_column} FROM spectrum_bands WHERE id=?""", (identifier,)).fetchone()

    @staticmethod
    def _raw(
        row: Any,
        *,
        ccd: int,
        detail: str,
        phase: str,
        frame: int,
        exposure_start: int | None,
        exposure_end: int | None,
        intensity_mode: str = "stored",
        working_layout: dict | None = None,
        verify_source: bool = False,
    ) -> dict[str, Any]:
        stored_layout = _json(row["layout_json"], {})
        if stored_layout.get('endianness', 'little') != 'little':
            raise SpectrumViewerError("spectrum_frame_endianness_invalid", "谱图字节序不受支持", status_code=409)
        layout = working_layout or stored_layout
        ignition = _json(row["ignition_json"], {})
        indices = [int(item) for item in layout.get("ccd_indices", [])]
        points_per_ccd = int(row["points_per_ccd"])
        ccd_count = int(row["ccd_count"])
        if not 0 <= ccd < ccd_count:
            raise SpectrumViewerError(
                "spectrum_ccd_invalid",
                "CCD selection is outside the installed CCD range",
                status_code=422,
                details={"ccd_count": ccd_count},
            )
        gaps = [float(item) for item in layout.get("gap_points", [])]
        coefficients = [float(item) for item in layout.get("ws_cof", [])]
        physical_index = indices[ccd] if ccd < len(indices) else ccd
        left_step = physical_index * points_per_ccd + sum(gaps[:physical_index])
        mean_blob = bytes(row["mean_blob"] or b"")
        expected_mean = ccd_count * points_per_ccd
        if mean_blob and len(mean_blob) != expected_mean * 4:
            raise SpectrumViewerError(
                "spectrum_mean_shape_invalid", "Stored mean data does not match its CCD layout", status_code=500
            )
        legacy_mean = intensity_mode == 'legacy_2_0_2' and detail != 'frame' and row['burn_adcs_blob']
        if verify_source and mean_blob and not legacy_mean and exposure_start is None and (
            row['mean_sha256'] and hashlib.sha256(mean_blob).hexdigest() != row['mean_sha256']
        ):
            raise SpectrumViewerError("spectrum_mean_integrity_failed", "平均强度 SHA-256 校验失败", status_code=409)

        def points(values: list[float] | tuple[float, ...], *, include_adc: bool = False) -> list[dict[str, Any]]:
            result = []
            for point_index, value in enumerate(values):
                step = left_step + point_index
                item: dict[str, Any] = {
                    "point_index": point_index,
                    "step": step,
                    "wavelength_nm": _wave(step, coefficients),
                    "value": float(value),
                }
                if include_adc:
                    item["adc"] = int(value)
                result.append(item)
            return result

        selected = struct.unpack_from(f"<{points_per_ccd}f", mean_blob, ccd * points_per_ccd * 4) if mean_blob and not legacy_mean else []
        bad_frames = _json(row["bad_frame_indices_json"], [])

        def verify_phase(chosen_phase, blob, start, stop):
            if not verify_source:
                return
            digest = row[f'{chosen_phase}_sha256']
            if (digest and hashlib.sha256(blob).hexdigest() != digest) or any(
                item.get('phase') == chosen_phase and start <= int(item['index']) < stop for item in bad_frames
            ):
                raise SpectrumViewerError('spectrum_frame_integrity_failed', '原始帧损坏或 SHA-256 校验失败', status_code=409)

        exposure_segment = None
        if exposure_start is not None or exposure_end is not None:
            if exposure_start is None or exposure_end is None:
                raise SpectrumViewerError(
                    "spectrum_exposure_invalid",
                    "exposure_start and exposure_end must be provided together",
                    status_code=422,
                )
            burn_count = int(ignition.get("burn_count") or 0)
            if not 1 <= exposure_start <= exposure_end <= burn_count:
                raise SpectrumViewerError(
                    "spectrum_exposure_invalid",
                    "Exposure interval is outside the stored burn frames",
                    status_code=422,
                    details={"burn_count": burn_count},
                )
            if not legacy_mean:
                burn_blob = bytes(row["burn_adcs_blob"] or b"")
                if len(burn_blob) != burn_count * expected_mean * 2:
                    raise SpectrumViewerError(
                        "spectrum_frame_shape_invalid", "Stored raw frames do not match their layout", status_code=500
                    )
                verify_phase('burn', burn_blob, exposure_start - 1, exposure_end)
                totals = [0] * points_per_ccd
                for index in range(exposure_start - 1, exposure_end):
                    offset = (index * expected_mean + ccd * points_per_ccd) * 2
                    for point, value in enumerate(struct.unpack_from(f"<{points_per_ccd}H", burn_blob, offset)):
                        totals[point] += value
                divisor = exposure_end - exposure_start + 1
                selected = [total / divisor for total in totals]
                exposure_segment = {"start": exposure_start, "end": exposure_end, "count": divisor}
        if legacy_mean:
            from .spectrum_observation import legacy_observation_points, LegacyObservationError
            try:
                selected, exposure_segment = legacy_observation_points(row, ccd, exposure_start, exposure_end)
            except LegacyObservationError as exc:
                raise SpectrumViewerError('spectrum_legacy_view_invalid', str(exc), status_code=422) from exc
        details = _json(row["details_json"], {})
        result: dict[str, Any] = {
            "id": f"raw:{int(row['id'])}",
            "kind": "raw",
            "intensity_mode": intensity_mode,
            "format": row["format"],
            "source_sha256": row["source_sha256"],
            "record_index": int(row["record_index"]),
            "band_id": row["band_id"],
            "sample_name": row["sample_name"],
            "sample_no": row["sample_no"],
            "band_name": row["band_name"] or row["long_name"],
            "measure_time": row["measure_time"],
            "reference_step": row["real_ref_step"],
            "angle_deg": _finite(details.get("angle_deg")),
            "exposure_segment": exposure_segment,
            "layout": {**layout, "ccd_indices": indices, "ccd_count": ccd_count, "points_per_ccd": points_per_ccd},
            "ignition": ignition,
            "bad_frame_indices": bad_frames,
            "ccd": {"position": ccd, "index": physical_index, "points": points(selected)},
            "frame_detail": None,
        }
        if detail == "frame":
            if phase not in {"burn", "dark"}:
                raise SpectrumViewerError("spectrum_phase_invalid", "phase must be burn or dark", status_code=422)
            blob = bytes((row["burn_adcs_blob"] if phase == "burn" else row["dark_adcs_blob"]) or b"")
            count = int(ignition.get(f"{phase}_count") or 0)
            expected = count * expected_mean * 2
            if count <= 0 or not blob:
                raise SpectrumViewerError(
                    "spectrum_frame_unavailable", "The requested raw frame is not stored", status_code=404
                )
            if len(blob) != expected:
                raise SpectrumViewerError(
                    "spectrum_frame_shape_invalid", "Stored raw frames do not match their layout", status_code=500
                )
            if not 0 <= frame < count:
                raise SpectrumViewerError(
                    "spectrum_frame_invalid",
                    "Frame selection is outside the available range",
                    status_code=422,
                    details={"frame_count": count},
                )
            offset = (frame * expected_mean + ccd * points_per_ccd) * 2
            if exposure_segment is None or phase != 'burn':
                verify_phase(phase, blob, frame, frame + 1)
            elif verify_source and any(item.get('phase') == phase and int(item['index']) == frame for item in bad_frames):
                raise SpectrumViewerError('spectrum_frame_integrity_failed', '所选原始帧已标记损坏', status_code=409)
            values = struct.unpack_from(f"<{points_per_ccd}H", blob, offset)
            result["frame_detail"] = {
                "phase": phase,
                "index": frame,
                "frame_count": count,
                "ccd": {"position": ccd, "index": physical_index, "points": points(list(values), include_adc=True)},
            }
        return result

    def calibrate(self, record_id: str, ccd: int, scope: str, interval: tuple[int, int] | None) -> dict:
        from functools import cache
        from .acquisition import AcquisitionError, AcquisitionService
        from .methods import MethodDomainError, MethodService
        from .postprocessing import prepared_working_layout
        from .spectral_lines import reference_baseline
        from .spectrum_calibration import acquired_locations, legacy_location, locate_peaks
        from .spectrum_observation import acquired_exposure_frames, legacy_exposure_source, LegacyObservationError

        kind, identifier = self._parse_record_id(record_id)
        if kind == 'result':
            raise SpectrumViewerError('spectrum_raw_required', '校线需要 CCD 谱图', status_code=422)
        methods = MethodService(self.database)
        if kind in {'raw', 'dispersion'}:
            if kind == 'raw':
                with self.database.read() as db:
                    row = self._raw_row(db, identifier, burn=True, dark=True)
                if row is None:
                    raise SpectrumViewerError('spectrum_record_not_found', '谱图记录不存在')
                working = prepared_working_layout(self.database, row['source_sha256'])
                layout = (working or _json(row['layout_json'], {})) | {
                    'ccd_count': row['ccd_count'], 'points_per_ccd': row['points_per_ccd']
                }
                if not 0 <= ccd < row['ccd_count']:
                    raise SpectrumViewerError('spectrum_ccd_invalid', 'CCD 超出原始积分布局', status_code=422)
                source = cache(lambda: legacy_exposure_source(row))
            else:
                start, end = interval or (None, None)
                active = self.get(record_id, ccd=ccd, exposure_start=start, exposure_end=end)
                layout = active['layout']
            version = methods.current().get('referenced_version')
            if version is None and scope == 'reference' and layout.get('reference_wavelength_nm'):
                wave = layout['reference_wavelength_nm']
                version = {'lines': [reference_baseline({
                    'reference_wavelength_nm': wave, 'actual_reference_wavelength_nm': wave
                }) | {'reference_baseline': True}]}
            if version is None:
                raise SpectrumViewerError('spectrum_calibration_method_required', '请先打开已发布的光谱方法', status_code=422)
            lines = version['lines']

            def locate(line):
                return legacy_location(layout, line.get('actual_wavelength_nm') or line['wavelength_nm'])

            def values_for(slot, exposure):
                start, end = exposure or (None, None)
                if kind == 'raw':
                    if row['burn_adcs_blob']:
                        try:
                            frames = source()(slot)
                            return frames.mean(*(exposure or (1, len(frames.burns))))
                        except LegacyObservationError as exc:
                            raise SpectrumViewerError('spectrum_calibration_frames_invalid', str(exc), status_code=422) from exc
                    data = self._raw(row, ccd=slot, detail='summary', phase='burn', frame=0, exposure_start=start,
                                     exposure_end=end, working_layout=working, verify_source=True)
                else:
                    data = active if slot == ccd else self.get(record_id, ccd=slot, exposure_start=start, exposure_end=end)
                return [point['value'] for point in data['ccd']['points']]

            def wavelength_at(slot, point):
                index = (layout.get('ccd_indices') or list(range(layout['ccd_count'])))[slot]
                step = index * layout['points_per_ccd'] + sum(layout.get('gap_points', [])[:index]) + point
                return _wave(step, layout.get('ws_cof', []))
        else:
            acquisition = AcquisitionService(self.database)
            try:
                snapshot = acquisition.spectrum_snapshot(identifier, include_frames=interval is not None)
                with self.database.read() as connection:
                    version_id = snapshot['sample'].get('method_version_id')
                    version = methods.bind_snapshots(connection).by_id(version_id, published_only=True) if version_id else None
                    if version is None:
                        raise SpectrumViewerError('spectrum_calibration_method_required', '该采集记录没有已发布的方法版本', status_code=422)
                    lines = version.print_version()['lines']
                    positions = {}
                    if not snapshot.get('turns'):
                        locator = methods.bind_geometry(connection, version.payload['conditions'])
                        positions = {line['id']: locator.locate(line.get('actual_wavelength_nm') or line['wavelength_nm'])
                                     for line in lines}
                    locations = acquired_locations(snapshot, positions)
                bands = snapshot['bands']
                if not 0 <= ccd < len(bands):
                    raise SpectrumViewerError('spectrum_ccd_invalid', 'CCD 超出实际采集布局', status_code=422)
                slots = {slot for slot, band in enumerate(bands) if band.get('turn_index') == bands[ccd].get('turn_index')}
                lines = [line for line in lines if line['id'] in locations and locations[line['id']][0] in slots]
            except (AcquisitionError, MethodDomainError) as exc:
                raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc

            def locate(line):
                return locations.get(line['id'])

            def values_for(slot, exposure):
                if not exposure:
                    return bands[slot]['mean_points']
                try:
                    return acquired_exposure_frames(snapshot, slot).mean(*exposure)
                except LegacyObservationError as exc:
                    raise SpectrumViewerError('spectrum_calibration_frames_invalid', str(exc), status_code=422) from exc

            def wavelength_at(slot, point):
                wavelengths = bands[slot].get('wavelengths_nm')
                return wavelengths[point] if wavelengths else None

        lines = [line for line in lines if line.get('enabled') and (scope == 'all' or line.get('reference_baseline'))]
        if not lines:
            raise SpectrumViewerError('spectrum_calibration_lines_missing', '当前谱图没有可校正的参考线或方法谱线', status_code=422)
        positions = []
        for line, target, peak in locate_peaks(lines, locate, values_for, lambda _: interval):
            slot, point = target if target else (None, None)
            wavelength = wavelength_at(slot, peak) if peak is not None else None
            positions.append({'id': line['id'], 'element': line['element'], 'reference': bool(line.get('reference_baseline')),
                              'ccd': slot, 'point': peak, 'wavelength_nm': wavelength,
                              'offset_points': peak - point if peak is not None else None,
                              'reference_shift': line['wavelength_nm'] - wavelength
                              if wavelength is not None and line.get('reference_baseline') else None})
        return {'positions': positions}

    def concentrations(self, record_id: str) -> dict[str, Any]:
        from functools import cache

        from .acquisition import AcquisitionError, AcquisitionService
        from .analysis import AnalysisError, AnalysisService
        from .methods import MethodService
        from .postprocessing import prepared_working_layout
        from .spectrum_calibration import legacy_location
        from .spectrum_observation import LegacyObservationError, legacy_exposure_source

        kind, _, number = record_id.partition(":")
        try:
            identifier = int(number)
        except ValueError:
            identifier = 0
        if kind not in {"raw", "sample"} or identifier <= 0:
            raise SpectrumViewerError("spectrum_concentration_record_invalid", "请选择一条样品谱图记录", status_code=422)

        methods = MethodService(self.database)
        analysis = AnalysisService(self.database, methods=methods)
        try:
            if kind == "sample":
                sample = AcquisitionService(self.database).spectrum_snapshot(identifier)["sample"]
                if sample["task_kind"] != "sample":
                    raise SpectrumViewerError("spectrum_concentration_record_invalid", "请选择一条样品谱图记录", status_code=422)
                return analysis.concentration_preview(sample["method_version_id"], sample_id=identifier)

            with self.database.read() as db:
                row = db.execute("SELECT * FROM spectrum_bands WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise SpectrumViewerError("spectrum_record_not_found", "谱图记录不存在")
            if row["format"] not in {"cdt", "cmt"}:
                raise SpectrumViewerError("spectrum_concentration_record_invalid", "请选择一条样品谱图记录", status_code=422)

            layout = _json(row["layout_json"], {}) | (prepared_working_layout(self.database, row["source_sha256"]) or {})
            point_count = row["points_per_ccd"]

            def locate(line):
                target = legacy_location(layout, line.get("actual_wavelength_nm") or line["wavelength_nm"])
                return (None, *target) if target is not None else None

            source = cache(lambda: legacy_exposure_source(row))

            @cache
            def frames(ccd):
                return source()(ccd)

            def values_for(_turn, ccd, interval):
                if row["burn_adcs_blob"]:
                    try:
                        exposure = frames(ccd)
                        return exposure.mean(*(interval or (1, len(exposure.burns))))
                    except LegacyObservationError as exc:
                        raise AnalysisError("spectrum_concentration_frames_invalid", str(exc)) from exc
                if interval is not None:
                    raise AnalysisError("spectrum_concentration_frames_missing", "谱图只有平均强度，无法按方法的曝光区间计算")
                mean = row["mean_blob"] or b""
                if not mean:
                    return []
                if len(mean) != row["ccd_count"] * point_count * 4 or (
                    row["mean_sha256"] and hashlib.sha256(mean).hexdigest() != row["mean_sha256"]
                ):
                    raise AnalysisError("spectrum_concentration_mean_invalid", "谱图平均强度校验失败")
                return list(struct.unpack_from(f"<{point_count}f", mean, ccd * point_count * 4))

            version_id, warning = self._legacy_concentration_method(methods, layout)
            preview = analysis.concentration_preview(version_id, source=(locate, values_for))
            return {**preview, 'method_notice': warning} if warning else preview
        except (AcquisitionError, AnalysisError) as exc:
            raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc

    def _legacy_concentration_method(self, methods, layout: dict[str, Any]) -> tuple[int, str | None]:
        from .methods import MethodDomainError

        current_id = (methods.current().get('referenced_version') or {}).get('id')
        with self.database.read() as db:
            current = methods.bind_snapshots(db).by_id(current_id, published_only=True) if current_id else None
            if current is None or current.method.status == 'deleted':
                raise SpectrumViewerError('spectrum_concentration_method_required',
                                          '请先在「光谱方法」打开已发布的方法，再展开记录查看参考含量', status_code=422)
            label = f'{current.method.name}（版本 {current.version}）'
            try:
                geometry = methods.bind_geometry(db, current.payload['conditions'])
            except MethodDomainError as exc:
                raise SpectrumViewerError('spectrum_concentration_layout_incompatible',
                                          f'当前方法 {label} 的色散布局不可用：{exc.message}', status_code=422) from exc
            if not geometry.accepts_legacy_layout(layout):
                raise SpectrumViewerError('spectrum_concentration_layout_incompatible',
                                          f'当前方法 {label} 与该记录的 CCD 或色散布局不相容，请打开适用的已发布方法',
                                          status_code=422)
            legacy_id = layout.get('legacy_method_id') or None
            current_legacy_id = current.payload.get('legacy_migration', {}).get('legacy_method_id')
            notice = (f'记录的旧方法编号为 {legacy_id}，参考含量按当前打开的方法估算。'
                      if legacy_id is not None and str(legacy_id) != str(current_legacy_id) else None)
            return current.version_id, notice

    def point_details(self, record_id: str, *, ccd: int, point: int | None) -> dict[str, Any]:
        """Verified integrations for one point, or the whole CCD for interactive observation."""
        from base64 import b64encode

        kind, identifier = self._parse_record_id(record_id)
        if kind == "dispersion":
            from .dispersion import DispersionError, DispersionService

            try:
                dispersion = DispersionService(self.database)
                snapshot = dispersion.spectrum_snapshot(identifier, ccd)
                return dispersion.point_details(identifier, snapshot['layout']['ccd_indices'][ccd], point, snapshot=snapshot)
            except DispersionError as exc:
                raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc
        if kind == "result":
            raise SpectrumViewerError("spectrum_raw_required", "结果矩阵不包含 CCD 原始积分值", status_code=422)
        if kind == "sample":
            from .acquisition import AcquisitionService, AcquisitionError

            try:
                snapshot = AcquisitionService(self.database).spectrum_snapshot(identifier, include_frames=True, band_position=ccd)
            except AcquisitionError as exc:
                if exc.code == 'acquisition_frame_integrity_failed':
                    raise SpectrumViewerError('spectrum_frame_integrity_failed', exc.message, status_code=409) from exc
                raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc
            record = self._sample(identifier, ccd=ccd, detail='summary', phase='burn', frame=0,
                                  exposure_start=None, exposure_end=None, snapshot=snapshot)
        else:
            from .postprocessing import prepared_working_layout

            with self.database.read() as db:
                raw = self._raw_row(db, identifier, burn=True, dark=True)
            if raw is None:
                raise SpectrumViewerError("spectrum_record_not_found", "Spectrum record was not found")
            working = prepared_working_layout(self.database, raw['source_sha256'])
            record = self._raw(raw, ccd=ccd, detail='summary', phase='burn', frame=0,
                               exposure_start=None, exposure_end=None, working_layout=working)
        point_values = record['ccd']['points']
        if not point_values and kind == 'raw':
            layout = record['layout']
            index = record['ccd']['index']
            left = index * layout['points_per_ccd'] + sum(layout.get('gap_points', [])[:index])
            point_values = [{'wavelength_nm': _wave(left + i, layout.get('ws_cof', []))}
                            for i in range(layout['points_per_ccd'])]
        count = len(point_values)
        if point is not None and not 0 <= point < count:
            raise SpectrumViewerError("spectrum_point_invalid", "点位超出当前 CCD", status_code=422)
        ignition = record.get("ignition") or {}
        rows = []
        frame_data = bytearray()
        phase_counts = {}
        if kind == "sample":
            selected_band = snapshot["bands"][ccd]
            for phase in ("burn", "dark"):
                frames = sorted(_sample_band_frames(snapshot, selected_band, phase), key=lambda item: item["frame_index"])
                expected = int(snapshot["sample"][f"{phase}_frame_count"])
                if [item["frame_index"] for item in frames] != list(range(expected)):
                    raise SpectrumViewerError("spectrum_frames_unavailable", "仅保存均值或分时帧不完整，不能生成原始明细", status_code=409)
                for frame in frames:
                    values = frame.get("points") or []
                    if frame.get("damaged") or len(values) != count:
                        raise SpectrumViewerError("spectrum_frame_integrity_failed", "原始帧损坏或 SHA-256 校验失败", status_code=409)
                    if point is None:
                        frame_data.extend(struct.pack(f"<{count}H", *values))
                    else:
                        rows.append({"phase": phase, "integration": frame["frame_index"] + 1, "value": values[point]})
                phase_counts[phase] = expected
        else:
            # Decode the selected column directly; avoid constructing a whole CCD for every frame.
            stride = int(raw["ccd_count"]) * int(raw["points_per_ccd"])
            for phase in ("burn", "dark"):
                total = int(ignition.get(f"{phase}_count") or 0)
                blob = bytes(raw[f"{phase}_adcs_blob"] or b"")
                if len(blob) != total * stride * 2:
                    raise SpectrumViewerError("spectrum_frames_unavailable", "未保存完整原始分时数据", status_code=409)
                expected_hash = raw[f'{phase}_sha256']
                if expected_hash and hashlib.sha256(blob).hexdigest() != expected_hash:
                    raise SpectrumViewerError('spectrum_frame_integrity_failed', '旧谱图原始帧 SHA-256 校验失败', status_code=409)
                for index in range(total):
                    start = (index * stride + ccd * count) * 2
                    if point is None:
                        frame_data.extend(blob[start:start + count * 2])
                    else:
                        value = struct.unpack_from("<H", blob, start + point * 2)[0]
                        rows.append({"phase": phase, "integration": index + 1, "value": value})
                phase_counts[phase] = total
        if not (rows or frame_data):
            raise SpectrumViewerError("spectrum_frames_unavailable", "该记录只有均值，没有原始积分明细", status_code=409)
        result = {"record_id": record_id, "sample_name": record.get("sample_name") or record.get("band_name") or record_id,
                  "ccd_index": record["ccd"]["index"],
                  "source_sha256": record["source_sha256"],
                  "pre_excitation_seconds": ignition.get("pre_burn"),
                  "burn_cycle_seconds": ignition.get("burn_cyc"), "dark_cycle_seconds": ignition.get("dark_cyc"),
                  "burn_count": phase_counts["burn"], "dark_count": phase_counts["dark"]}
        if point is None:
            return {**result, "point_count": count, "frames_base64": b64encode(frame_data).decode("ascii"),
                    "wavelengths_nm": [value.get("wavelength_nm") for value in point_values]}
        result.update(point_index=point, wavelength_nm=point_values[point].get("wavelength_nm"), rows=rows)
        result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return result

    def export_csv(
        self,
        record_id: str,
        *,
        ccd: int = 0,
        line: int = 0,
        detail: str = "summary",
        phase: str = "burn",
        frame: int = 0,
        exposure_start: int | None = None,
        exposure_end: int | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        reference_shift: float = 0.0,
        intensity_mode: str = "stored",
    ) -> tuple[bytes, str, int]:
        if (x_min is None) != (x_max is None) or (x_min is not None and x_max is not None and x_min > x_max):
            raise SpectrumViewerError(
                "spectrum_visible_range_invalid", "x_min and x_max must form an ordered visible range", status_code=422
            )
        record = self.get(
            record_id,
            ccd=ccd,
            line=line,
            detail=detail,
            phase=phase,
            frame=frame,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            intensity_mode=intensity_mode,
            verify_source=True,
        )
        if record["kind"] in {"raw", "sample"}:
            source_points = (record.get("frame_detail") or {}).get("ccd", {}).get("points") or record["ccd"]["points"]
        else:
            source_points = record["line"]["points"]
        rows: list[dict[str, Any]] = []
        for point in source_points:
            x = point.get("wavelength_nm")
            if x is None:
                x = point.get("step", point.get("x", point["point_index"]))
            x = float(x) + (reference_shift if record["kind"] in {"raw", "sample"} else 0.0)
            if x_min is not None and x_max is not None and not x_min <= x <= x_max:
                continue
            rows.append({**point, "x": x})
        fieldnames = [
            "point_index",
            "x",
            "wavelength_nm",
            "step",
            "value",
            "adc",
            "peak",
            "back",
            "sample_index",
            "repeat_index",
            "sample_name",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        content = ("\ufeff" + stream.getvalue()).encode("utf-8")
        return content, hashlib.sha256(content).hexdigest(), len(rows)

    def render_visible_pdf(
        self,
        record_id: str,
        *,
        selected_record_ids: list[str],
        ccd: int,
        line: int,
        mode: str,
        reference_shift: float,
        visible_x_min: float,
        visible_x_max: float,
        visible_y_min: float,
        visible_y_max: float,
        frame_phase: str = "burn",
        frame_index: int = 0,
        exposure_start: int | None = None,
        exposure_end: int | None = None,
        priority_record_id: str | None = None,
        print_scope: str = 'visible',
        print_layers: list[str] | None = None,
        print_scale: str = 'fit_long',
        paper: str = 'A4',
        intensity_mode: str = 'stored',
    ) -> tuple[bytes, dict[str, Any]]:
        if visible_x_min > visible_x_max or visible_y_min > visible_y_max:
            raise SpectrumViewerError(
                "spectrum_visible_range_invalid", "Visible ranges must be ordered", status_code=422
            )
        if mode not in {"mean", "peak", "back", "value", "frame"}:
            raise SpectrumViewerError("spectrum_print_mode_invalid", "Print mode is not supported", status_code=422)
        if (exposure_start is None) != (exposure_end is None):
            raise SpectrumViewerError(
                "spectrum_exposure_invalid", "Exposure interval must include both endpoints", status_code=422
            )

        ordered_ids = list(dict.fromkeys([record_id, *selected_record_ids]))[:8]
        curves: list[dict[str, Any]] = []
        for index, item_id in enumerate(ordered_ids):
            is_active = item_id == record_id
            detail = "frame" if is_active and mode == "frame" else "summary"
            item_exposure_start = exposure_start if detail == "summary" else None
            item_exposure_end = exposure_end if detail == "summary" else None
            try:
                record = self.get(
                    item_id,
                    ccd=ccd,
                    line=line,
                    detail=detail,
                    phase=frame_phase,
                    frame=frame_index,
                    exposure_start=item_exposure_start,
                    exposure_end=item_exposure_end,
                    intensity_mode=intensity_mode,
                    verify_source=True,
                )
            except SpectrumViewerError as exc:
                if exc.code != "spectrum_ccd_invalid":
                    raise
                clipped_ccd = max(0, min(ccd, int(exc.details["ccd_count"]) - 1))
                record = self.get(
                    item_id,
                    ccd=clipped_ccd,
                    line=line,
                    detail=detail,
                    phase=frame_phase,
                    frame=frame_index,
                    exposure_start=item_exposure_start,
                    exposure_end=item_exposure_end,
                    intensity_mode=intensity_mode,
                    verify_source=True,
                )

            coordinates = record.get(
                "coordinate_system", "legacy_wavelength" if record["kind"] == "raw" else "result_index"
            )
            if curves and coordinates != curves[0].get("coordinate_system"):
                raise SpectrumViewerError(
                    "spectrum_overlay_incompatible", "叠加来源的坐标和单位不可比，请分别查看", status_code=422
                )
            if record["kind"] in {"raw", "sample"}:
                source = (record.get("frame_detail") or {}).get("ccd", {}).get("points") or record["ccd"]["points"]
                label = record.get("sample_name") or record.get("band_name") or item_id
            else:
                source = record["line"]["points"]
                label = record["line"].get("element") or (record.get("sample_names") or [item_id])[0]
            points: list[tuple[float, float]] = []
            point_indices = []
            for point_index, point in enumerate(source):
                x = point.get("wavelength_nm")
                if x is None:
                    x = point.get("step", point.get("x", point_index))
                x = float(x) + (reference_shift if record["kind"] in {"raw", "sample"} else 0.0)
                if mode == "peak":
                    y = point.get("peak")
                elif mode == "back":
                    y = point.get("back")
                else:
                    y = point.get("value", point.get("peak", point.get("adc")))
                if y is not None and math.isfinite(x) and math.isfinite(float(y)):
                    points.append((x, float(y)))
                    point_indices.append(int(point.get('point_index', point_index)))
            curves.append(
                {
                    "coordinate_system": coordinates,
                    "id": item_id,
                    "label": str(label),
                    "points": points,
                    "color": _SPECTRUM_PDF_COLORS[index % len(_SPECTRUM_PDF_COLORS)],
                    "priority": (priority_record_id or record_id) == item_id,
                    "point_indices": point_indices,
                    # FmPrintCcd.PrintBlack scales against the whole CCD, with DefaultMaxAvg=5000.
                    "grayscale_max": max(5000.0, max((value for _, value in points), default=0.0)),
                    "point_width_um": record.get('layout', {}).get('point_width_um', record.get('layout', {}).get('point_width')),
                    "raw": record['kind'] in {'raw', 'sample'},
                }
            )
        layers = list(dict.fromkeys(print_layers if print_layers is not None else ['curve']))
        if not layers or set(layers) - {'curve', 'grayscale'}:
            raise SpectrumViewerError('spectrum_print_layers_invalid', '灰度谱带和峰形至少选择一项', status_code=422)
        if print_scope not in {'visible', 'ccd'} or print_scale not in {'fit_long', 'fit_short', 'ccd_10x'} or paper not in {'A4', 'A3', 'Letter'}:
            raise SpectrumViewerError('spectrum_print_options_invalid', '打印范围、比例或纸型无效', status_code=422)
        if ('grayscale' in layers or print_scale == 'ccd_10x' or print_scope == 'ccd') and any(not curve['raw'] for curve in curves):
            raise SpectrumViewerError('spectrum_raw_required', 'CCD 灰度和物理比例输出需要原始谱图', status_code=422)
        if print_scope == 'ccd':
            all_points = [point for curve in curves for point in curve['points']]
            if not all_points:
                raise SpectrumViewerError('spectrum_print_empty', '当前 CCD 没有可打印点', status_code=422)
            visible_x_min, visible_x_max = min(p[0] for p in all_points), max(p[0] for p in all_points)
            visible_y_min, visible_y_max = min(0, min(p[1] for p in all_points)), max(1, max(p[1] for p in all_points))
        physical_width_mm = None
        if print_scale == 'ccd_10x':
            widths = [float(curve.get('point_width_um') or 0) for curve in curves]
            if any(not math.isfinite(width) or width <= 0 for width in widths) or max(widths) - min(widths) > 1e-6:
                raise SpectrumViewerError('spectrum_point_width_unavailable', '未记录一致的 CCD 点宽，无法按十倍物理比例打印', status_code=422)
            for curve in curves:
                curve['points'] = [(index, value) for index, (x, value) in zip(curve['point_indices'], curve['points'], strict=True)
                                   if visible_x_min <= x <= visible_x_max]
            selected = [point for curve in curves for point in curve['points']]
            if not selected:
                raise SpectrumViewerError('spectrum_print_empty', '当前图像没有可打印点', status_code=422)
            visible_x_min, visible_x_max = min(p[0] for p in selected), max(p[0] for p in selected)
            # Old CalGraphicWidth counts inclusive CCD pixels, including both endpoints.
            physical_width_mm = (visible_x_max - visible_x_min + 1) * widths[0] * 10 / 1000
        try:
            content, metadata = render_spectrum_pdf(curves, record_id, mode, ccd, line, reference_shift,
                visible_x_min, visible_x_max, visible_y_min, visible_y_max,
                layers=layers, print_scale=print_scale, paper=paper, physical_width_mm=physical_width_mm)
        except ValueError as exc:
            raise SpectrumViewerError('spectrum_print_physical_size_exceeds_page', str(exc), status_code=422) from exc
        return content, {**metadata, 'print_scope': print_scope, 'print_layers': layers,
                         'print_scale': print_scale, 'paper': paper, 'physical_width_mm': physical_width_mm}

    @staticmethod
    def decode_result_matrix(row: Any, *, line: int) -> dict[str, Any]:
        payload = _json(row["payload_json"], {})
        line_count = int(payload.get("line_count") or 0)
        band_count = int(payload.get("band_count") or 0)
        if not 0 <= line < line_count:
            raise SpectrumViewerError(
                "spectrum_line_invalid",
                "Line selection is outside the result matrix",
                status_code=422,
                details={"line_count": line_count},
            )
        sample_rows = payload.get("sample_rows") or []
        lines = payload.get("lines") or []
        matrix = bytes(row["matrix_blob"] or b"")
        kind = payload.get("matrix_kind")
        expected = line_count * band_count * (8 if kind == "peak_back" else 4)
        if len(matrix) != expected:
            raise SpectrumViewerError(
                "result_matrix_shape_invalid", "Stored result matrix does not match its metadata", status_code=500
            )
        points: list[dict[str, Any]] = []
        metadata = lines[line] if line < len(lines) else {"index": line}
        if kind == "peak_back":
            for point_index in range(band_count):
                peak, back = struct.unpack_from("<ff", matrix, (line * band_count + point_index) * 8)
                sample = sample_rows[point_index] if point_index < len(sample_rows) else {}
                points.append(
                    {
                        "point_index": point_index,
                        "x": point_index,
                        "sample_index": sample.get("sample_index"),
                        "repeat_index": sample.get("repeat_index"),
                        "sample_name": sample.get("name"),
                        "peak": float(peak),
                        "back": float(back),
                    }
                )
        else:
            for point_index in range(band_count):
                (value,) = struct.unpack_from("<f", matrix, (line * band_count + point_index) * 4)
                sample = sample_rows[point_index] if point_index < len(sample_rows) else {}
                points.append(
                    {
                        "point_index": point_index,
                        "x": point_index,
                        "sample_index": sample.get("sample_index"),
                        "repeat_index": sample.get("repeat_index"),
                        "sample_name": sample.get("name"),
                        "value": float(value),
                    }
                )
        return {
            "id": f"result:{int(row['id'])}",
            "kind": "result",
            "format": row["format"],
            "source_sha256": row["source_sha256"],
            "record_index": int(row["record_index"]),
            "measure_time": payload.get("measure_time"),
            "sample_names": payload.get("sample_names") or [],
            "sample_reps": payload.get("sample_reps") or [],
            "sample_rows": sample_rows,
            "line_count": line_count,
            "band_count": band_count,
            "matrix_kind": kind,
            "matrix_order": payload.get("matrix_order"),
            "exposure_segments": payload.get("exposure_segments") or [],
            "line": {**metadata, "index": line, "points": points},
        }

    _result = decode_result_matrix
