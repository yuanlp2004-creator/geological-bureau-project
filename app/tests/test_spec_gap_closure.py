"""Spec2.02 gap closure: numeric rules, real sample chains, immutable outputs."""
import copy
import hashlib
import json
import math
import struct
from pathlib import Path

import pytest

from backend.config import AppConfig
from backend.db import Database, utc_now
from backend.runtime import Runtime
from backend.modules.acquisition import AcquisitionService, AcquisitionError
from backend.modules.acquisition_import import AcquisitionRecordImporter, ImportedAcquisition, ImportedBand
from backend.modules.analysis import AnalysisError, evaluate_curve, fit_curve
from backend.modules.analysis.candidate import calculate_candidate
from backend.modules.analysis.legacy_curves import merge_legacy_lines
from backend.modules.analysis.rules import _base_curve_points
from backend.modules.methods import MethodService, MethodDomainError
from backend.modules.postprocessing import PostProcessingError
from backend.modules.postprocessing.legacy_calculation import LegacyIntensity, recalculate_legacy
from backend.modules.reports import ReportError
from backend.modules.spectral_lines import SpectralLineService, canonical_lines, exposure_interval
from backend.schemas.methods import MethodCreate, MethodUpdate, SpectralLineInput
from tests.test_s16_analysis import _finish
from tests.test_s18_postprocessing import _fixture, _seed_method_curve
from tests.test_s09_result_migration import source_file
from tests.test_legacy_migration import sources as legacy_sources


def test_reference_offset_and_theoretical_reset(tmp_path):
    database, runtime, method, _, _, _, _ = _sample_chain(tmp_path)
    conditions = method['published_version']['conditions']
    with database.read() as db:
        locator = runtime.methods_service().bind_geometry(db, conditions)
        actual = locator.wavelength_at(0, 402)
    offset = runtime.methods_service().reference_offset({**conditions, 'actual_reference_wavelength_nm': actual})
    assert offset['point_delta'] == 2 and offset['wavelength_delta_nm'] > 0
    changed = runtime.methods_service().update(method['id'], MethodUpdate(conditions={'reference_wavelength_nm': actual}), 1)
    assert changed['version']['conditions']['actual_reference_wavelength_nm'] == actual
    assert changed['published_version']['content_sha256'] == method['published_version']['content_sha256']


def test_existing_legacy_method_upgrade_preserves_source_and_published_version(tmp_path, legacy_sources):
    from backend.auth import AuthService
    from backend.modules.legacy_migration import LegacyMigrationService, LegacyMigrationError
    database = Database(tmp_path / 'existing-legacy.sqlite3')
    database.initialize()
    AuthService(database).bootstrap('legacy-operator', 'correct-horse')
    migration = LegacyMigrationService(database)
    assert migration.diagnostics()['available']
    before = {key: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for key, path in legacy_sources.items()}
    staged = migration.stage(*(str(legacy_sources[key]) for key in ('mtd', 'cfg', 'opt')), 1)
    migration.commit(staged['id'], 1)
    with database.write() as db:
        row = db.execute('SELECT * FROM method_versions ORDER BY id LIMIT 1').fetchone()
        previous = json.loads(row['payload_json'])
        previous['legacy_migration'].pop('evidence', None)
        previous['legacy_migration'].pop('modified_at', None)
        for key in ('legacy_exposure_mode', 'legacy_exposure_interval'): previous['conditions'].pop(key, None)
        for line in previous['lines']:
            for key in ('exposure_start_frame', 'exposure_end_frame'): line.pop(key, None)
            for point in line.get('standard_points', []):
                for key in ('original_intensity', 'adjusted_intensity', 'intensity_valid'): point.pop(key, None)
        raw = json.dumps(previous, ensure_ascii=False)
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (?,2,'published',?,?)", (row['method_id'], raw, utc_now()))
        db.execute('UPDATE methods SET current_version=2 WHERE id=?', (row['method_id'],))
        method_id = row['method_id']
    upgraded = migration.upgrade_method_semantics(method_id, 1)
    assert upgraded['version']['state'] == 'draft' and upgraded['current_version'] == 2
    assert upgraded['published_version']['content_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert all('exposure_start_frame' in line for line in upgraded['version']['lines'] if line['line_type'] != 'baseline')
    assert any(point.get('intensity_valid') for line in upgraded['version']['lines'] for point in line.get('standard_points', []))
    assert migration.upgrade_method_semantics(method_id, 1)['latest_version'] == upgraded['latest_version']
    assert before == {key: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for key, path in legacy_sources.items()}
    legacy_sources['mtd'].write_bytes(legacy_sources['mtd'].read_bytes() + b'test-changed-copy')
    with pytest.raises(LegacyMigrationError, match='MTD 已变化'):
        migration.upgrade_method_semantics(method_id, 1)


def test_legacy_gaussian_failure_and_background_switch():
    line = {'id': 'A', 'line_type': 'analysis', 'element': 'Cu', 'wavelength_nm': 300,
            'scan_width_points': 9, 'peak_width_points': 3, 'peak_mode': 'gaussian'}
    actual = calculate_candidate(line, [line], 0, 0, 0, 4, [10.] * 9, {}, {}, 'legacy_2_0_2', None)
    assert actual['peak_height'] == 10 and actual['quantitative_signal'] == 10
    assert actual['intermediates']['gaussian']['fallback'] == 'searched_peak_height'
    with pytest.raises(AnalysisError, match='高斯'):
        calculate_candidate(line, [line], 0, 0, 0, 4, [10.] * 9, {}, {}, 'modern_v1', None)
    line.update(peak_mode='max_single_point', internal_standard_mode='line', internal_standard_line_id='IS')
    prior = {'IS': {'peak_height': 100, 'background': 20, 'net_signal': 80, 'quantitative_signal': 80}}
    actual = calculate_candidate(line, [line], 0, 0, 0, 4, [200.] * 9, {}, prior, 'legacy_2_0_2', None)
    assert actual['quantitative_signal'] == 2
    source = LegacyIntensity('hash', [{'element': 'Cu', 'wavelength_nm': 300, 'back': 0},
        {'element': 'Fe', 'wavelength_nm': 301, 'back': 2}], [{'name': 'N1'}], [[(200, 0)], [(100, 20)]], 1)
    internal = {'id': 'IS', 'line_type': 'internal_standard', 'element': 'Fe', 'wavelength_nm': 301}
    evaluator = {'A': {'curve_snapshot_id': 1, 'coordinate_type': 'normal', 'fit': {'kind': 'polynomial', 'coefficients': [0, 1, 0, 0]}}}
    assert recalculate_legacy(source, [line, internal], evaluator, 'legacy_2_0_2')['lines'][0]['quantitative_signal'] == 2


def test_legacy_curve_bounds_smoothing_and_degenerate_fallback():
    x = [10, 20, 30, 40]
    linear = fit_curve(x, [1, 2, 3, 4], 'linear', calculation_profile='legacy_2_0_2')
    assert evaluate_curve(linear, 100) == 4
    assert evaluate_curve(linear, 1) == pytest.approx(.1)
    quadratic = fit_curve(x, [1, 4, 9, 16], 'quadratic', calculation_profile='legacy_2_0_2')
    assert evaluate_curve(quadratic, 1) == pytest.approx(1 / 3, rel=1e-7)
    assert evaluate_curve(quadratic, 100) == 16
    logarithmic = fit_curve(x, [1, 2, 3, 4], 'cubic', 'logarithmic', calculation_profile='legacy_2_0_2')
    assert logarithmic['source_point_count'] == 4 and len(logarithmic['x']) == 16 and logarithmic['smoothed']
    assert evaluate_curve(logarithmic, 1) == pytest.approx(math.exp(-1.10), rel=1e-7)
    assert evaluate_curve(logarithmic, 25) == pytest.approx(2.5, rel=2e-4)
    repeated = fit_curve([1, 1, 2, 2], [1, 2, 3, 4], 'cubic', calculation_profile='legacy_2_0_2')
    assert repeated['linear_fallback'] and evaluate_curve(repeated, 1.5) == pytest.approx(2.5)
    assert evaluate_curve(fit_curve(x, [1, 2, 3, 4], 'linear'), 100) == pytest.approx(10)


def test_standards_reuse_whole_set_and_legacy_merge():
    line = {'id': 'L', 'standard_points': [{'name': f'S{i}', 'value': i, 'active': True} for i in range(1, 5)]}
    saved = [{'name': f'S{i}', 'standard_value': i, 'original_intensity': i * 10,
              'adjusted_intensity': i * 11, 'active': i != 2} for i in range(1, 5)]
    groups = [{'line_id': 'L', 'sample_kind': 'standard', 'sample_name': f'S{i}', 'acquisition_task_id': i,
               'statistics': {'mean': i * 100, 'effective_count': 1}} for i in range(1, 5)]
    reused = _base_curve_points(line, groups[:2], saved)
    assert [point['adjusted_intensity'] for point in reused] == [11, 22, 33, 44]
    assert [point['original_intensity'] for point in reused] == [10, 20, 30, 40] and not reused[1]['active']
    assert [point['adjusted_intensity'] for point in _base_curve_points(line, groups, saved)] == [100, 200, 300, 400]
    line['standard_points'][0]['value'] = 1.5
    assert _base_curve_points(line, groups[:2], saved)[0]['adjusted_intensity'] is None
    low = {'line_id': 'low', 'value': 20, 'legacy_switch_content': 9}
    high = {'line_id': 'high', 'value': 50, 'legacy_switch_content': 90}
    assert merge_legacy_lines([low, high])['line_id'] == 'high'
    assert merge_legacy_lines([{**low, 'value': 5}, high])['line_id'] == 'low'


def _sample_chain(tmp_path, exposure_mode='line_interval'):
    database = Database(tmp_path / 'spec-gap.sqlite3')
    database.initialize()
    from backend.auth import AuthService
    AuthService(database).bootstrap('spec-gap-operator', 'correct-horse')
    runtime = Runtime(AppConfig(data_dir=tmp_path), database=database)
    methods = runtime.methods_service()
    with database.read() as db:
        coefficients = json.loads(db.execute("SELECT coefficients_json FROM dispersion_calibrations WHERE name='default'").fetchone()[0])
    wave = lambda point: methods._step_to_wave(point, coefficients)
    method = methods.create(MethodCreate(name='Spec gap closure', conditions={
        'selected_ccds': [0], 'reference_wavelength_nm': wave(400), 'actual_reference_wavelength_nm': wave(400),
        'frame_count': 3, 'dark_frame_count': 1, 'pre_excitation_seconds': 2, 'sampling_period_seconds': 1.5,
        'sample_repeats': 2, 'standard_repeats': 3, 'control_repeats': 4, 'rsd_enabled': False,
        'calculation_profile': 'legacy_2_0_2', 'exposure_mode': exposure_mode,
        'angle_exposures': [{'angle_deg': 0, 'storage_mode': 'averaged', 'start_frame': 1, 'end_frame': 3}]
    }), 1)
    line = SpectralLineInput(element='Cu', wavelength_nm=wave(900), lower_peak=100,
        exposure_start_frame=1, exposure_end_frame=2, background_offset_points=20,
        standard_points=[{'name': f'S{i}', 'value': i, 'original_intensity': i * 90,
                         'adjusted_intensity': i * 100, 'intensity_valid': True} for i in range(1, 5)])
    method = runtime.spectral_lines_service().create(method['id'], line, 1)
    method = methods.publish(method['id'], 1)
    version = method['published_version']['id']
    line_id = next(line['id'] for line in method['published_version']['lines'] if line['line_type'] == 'analysis')
    burns = []
    for amplitude in [900, 600, 9000]:
        points = [30] * 2048
        points[402] = 1200
        points[901:904] = [amplitude // 3, amplitude, amplitude // 3]
        burns.append(points)
    with database.write() as db:
        task_id, sample_id = AcquisitionRecordImporter().bind(db).import_record(ImportedAcquisition(
            name='known frames', layout_id=1, method_version_id=version, method_id=method['id'], method_version=method['current_version'],
            sample_name='N1', original_sample_name='N1', source_record_id='golden', source_sha256='golden-hash', measure_time=None,
            interval_start=1, frame_count=3, bands=[ImportedBand(0, 2048, burns, [[20] * 2048])], actor_user_id=1, created_at=utc_now(),
            burn_cycle_seconds=1.5, dark_cycle_seconds=2, sampling_period_seconds=1.5, pre_excitation_seconds=2))
    analysis = runtime.analysis_service()
    run = _finish(analysis, analysis.create_run({'acquisition_sample_ids': [sample_id], 'method_version_id': version}))
    assert run['status'] == 'completed'
    return database, runtime, method, line_id, task_id, sample_id, run


@pytest.mark.parametrize('mode,signal,storage', [
    ('simple_mean', 2313.333251953125, 'averaged'),
    ('line_interval', 480, 'full_interval'),
])
def test_exposure_mode_controls_storage_and_actual_line_calculation(tmp_path, mode, signal, storage):
    database, runtime, method, line_id, task_id, sample_id, run = _sample_chain(tmp_path, mode)
    row = next(row for row in run['line_results'] if row['line_id'] == line_id)
    assert row['quantitative_signal'] == pytest.approx(signal, abs=1e-5)
    assert row['intermediates']['exposure_interval'] == ([1, 2] if mode == 'line_interval' else None)
    measured = runtime.analysis_service().measurement_results(runtime.acquisition_service().measurement_snapshot(task_id))
    assert measured['rows'][0]['quantitative_signal'] == pytest.approx(signal, abs=1e-5)
    task = runtime.acquisition_service().create_task({
        'method_id': method['id'], 'sample_name': 'U002', 'use_method_conditions': True, 'repeat_count': 1,
        'storage_mode': 'full_interval' if mode == 'simple_mean' else 'averaged',
    })
    assert task['storage_mode'] == storage
    assert exposure_interval({'line_type': 'analysis'}, method['published_version']['conditions']) == (
        (1, 3) if mode == 'line_interval' else None
    )
    old_version = method['published_version']
    switched = runtime.methods_service().update(method['id'], MethodUpdate(conditions={
        'exposure_mode': 'simple_mean' if mode == 'line_interval' else 'line_interval',
    }), 1)
    assert switched['version']['state'] == 'draft'
    assert switched['published_version']['id'] == old_version['id']
    assert switched['published_version']['content_sha256'] == old_version['content_sha256']
    assert switched['published_version']['conditions']['exposure_mode'] == mode
    # 未声明新模式的旧快照仍沿用既有逐线/旧总开关解释。
    old_conditions = {'frame_count': 3, 'legacy_exposure_mode': True}
    assert exposure_interval({'line_type': 'analysis', 'exposure_start_frame': 1, 'exposure_end_frame': 2}, old_conditions) == (1, 2)


def test_exposure_mode_validation_and_single_frame_simple_mean(tmp_path):
    database = Database(tmp_path / 'exposure-validation.sqlite3')
    database.initialize()
    methods = MethodService(database)
    for index, invalid in enumerate(([], {}, 'unknown', False)):
        method = methods.create(MethodCreate(name=f'invalid-mode-{index}', conditions={'exposure_mode': invalid}), 1)
        assert any(issue['field'] == 'exposure_mode' for issue in method['version']['validation_errors'])
        with pytest.raises(MethodDomainError):
            methods.publish(method['id'], 1)
    condition = {'exposure_mode': 'simple_mean', 'frame_count': 1,
        'angle_exposures': [{'angle_deg': 0, 'storage_mode': 'averaged', 'start_frame': 1, 'end_frame': 1}]}
    method = methods.create(MethodCreate(name='single-frame', conditions=condition), 1)
    assert method['version']['validation_errors'] == []
    published = methods.publish(method['id'], 1)
    invalid = methods.update(method['id'], MethodUpdate(conditions={'exposure_mode': 'line_interval'}), 1)
    assert any(issue['field'] == 'frame_count' for issue in invalid['version']['validation_errors'])
    assert invalid['published_version']['content_sha256'] == published['published_version']['content_sha256']


def test_interval_defaults_cached_curve_report_and_daily_positions(tmp_path):
    database, runtime, method, line_id, task_id, sample_id, run = _sample_chain(tmp_path)
    result = next(row for row in run['line_results'] if row['line_id'] == line_id)
    assert result['peak_position'] == 902
    assert result['peak_height'] == pytest.approx(490) and result['quantitative_signal'] == pytest.approx(480)
    acquisition = runtime.acquisition_service()
    measured = runtime.analysis_service().measurement_results(acquisition.measurement_snapshot(task_id))
    assert measured['rows'][0]['quantitative_signal'] == result['quantitative_signal']
    for kind, name, repeats in [('test', 'N2', 2), ('standard', 'S1', 3), ('test', 'D1', 4)]:
        task = acquisition.create_task({'method_id': method['id'], 'sample_kind': kind, 'sample_name': name, 'use_method_conditions': True, 'use_method_intervals': True})
        assert task['repeat_count'] == repeats and task['pre_excitation_seconds'] == 2
        assert task['sampling_period_seconds'] == 1.5 and task['burn_frame_count'] == 3 and task['dark_frame_count'] == 1
        assert task['storage_mode'] == 'full_interval'
    override = acquisition.create_task({'method_id': method['id'], 'sample_name': 'N3', 'repeat_count': 7, 'use_method_conditions': True})
    assert override['repeat_count'] == 7
    interval_task = acquisition.create_task({'method_id': method['id'], 'sample_name': 'N4', 'repeat_count': 1,
        'use_method_conditions': True, 'use_method_intervals': True})
    interval_task = acquisition.start(interval_task['id'])
    for _ in range(20):
        if interval_task['status'] == 'completed': break
        interval_task = acquisition.step(interval_task['id'])
    assert interval_task['status'] == 'completed'
    assert interval_task['samples'][0]['bands'][0]['storage_mode'] == 'full_interval'
    with database.read() as db:
        assert AcquisitionService.interval_band(db, interval_task['samples'][0]['id'], 0, (1, 2))['interval'] == (1, 2)
    standalone = acquisition.create_task({'task_kind': 'evaporation', 'use_method_conditions': True, 'pre_excitation_seconds': 1, 'sampling_period_seconds': 1})
    assert standalone['pre_excitation_seconds'] == 1 and standalone['method_id'] is None
    analysis = runtime.analysis_service()
    run = analysis.build_quality(run['id'])
    run = analysis.fit_standard_curve(run['id'], line_id, {})
    curve = run['curves']['lines'][0]['snapshots'][-1]
    assert [point['adjusted_intensity'] for point in curve['points']] == [100, 200, 300, 400]
    assert [point['original_intensity'] for point in curve['points']] == [90, 180, 270, 360]
    analysis.publish_standard_curve(run['id'], line_id, curve['id'], 'golden')
    run = analysis.merge_results(run['id'], 'golden')
    report = runtime.reports_service().create({'analysis_run_ids': [run['id']]})
    assert report['model']['rows'][0]['calculated_value'] == 4
    before = methods_hash = method['published_version']['content_sha256']
    preview = analysis.calibration_preview(run['id'], 0)
    assert preview['save_allowed'] and len(preview['positions']) == 2
    draft = analysis.save_calibration(run['id'], 0, 1)
    assert draft['version']['state'] == 'draft' and draft['published_version']['content_sha256'] == before
    assert analysis.save_calibration(run['id'], 0, 1)['latest_version'] == draft['latest_version']
    restored = analysis.save_calibration(run['id'], 0, 1, mode='theoretical')
    assert restored['version']['conditions']['actual_reference_wavelength_nm'] == method['published_version']['conditions']['reference_wavelength_nm']
    recovered = analysis.save_calibration(run['id'], 0, 1, mode='stored')
    assert recovered['published_version']['content_sha256'] == methods_hash
    runtime.methods_service().update(method['id'], MethodUpdate(conditions={'pre_excitation_seconds': 3}), 1)
    with pytest.raises(MethodDomainError, match='已有更新'):
        analysis.save_calibration(run['id'], 0, 1)
    with database.read() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_time_series_fixed_peak_cycles_background_and_integrity(tmp_path):
    database, runtime, _, line_id, _, sample_id, run = _sample_chain(tmp_path)
    analysis, acquisition = runtime.analysis_service(), runtime.acquisition_service()
    series = analysis.time_series(run['id'], 0, acquisition)
    assert [row['intensity'] for row in series['rows']] == pytest.approx([590, 390, 5990, 6970 / 3])
    assert [row['background'] for row in series['rows']] == [10, None, None, None]
    assert {row['point'] for row in series['rows']} == {903}
    assert len(analysis.time_series(run['id'], 0, acquisition, False)['rows']) == 3
    content, digest = analysis.export_time_series(run['id'], 0, acquisition, True, 1)
    assert content.startswith(b'\xef\xbb\xbf') and hashlib.sha256(content).hexdigest() == digest
    original_snapshot = acquisition.spectrum_snapshot
    def corrupt_snapshot(*args, **kwargs):
        detached = original_snapshot(*args, **kwargs)
        detached['frames'][0]['points'][902] += 1
        return detached
    acquisition.spectrum_snapshot = corrupt_snapshot
    with pytest.raises(AnalysisError, match='SHA-256'):
        analysis.time_series(run['id'], 0, acquisition)


@pytest.mark.parametrize('mode', ['averaged', 'full_interval'])
def test_edt_conversion_preserves_dark_cycles_and_storage(tmp_path, mode):
    database, service = _fixture(tmp_path)
    ignition = {'burn_count': 3, 'dark_count': 1, 'pre_burn': 3, 'burn_cyc': 1.5, 'dark_cyc': 2}
    with database.write() as db:
        db.execute('UPDATE spectrum_bands SET ignition_json=?, dark_adcs_blob=? WHERE id=1', (json.dumps(ignition), struct.pack('<6H', *[2] * 6)))
    converted = service.convert_edt({'record_ids': ['raw:1'], 'target_ccd_layout_id': 2, 'target_ccd_indices': [0], 'start_frame': 1, 'end_frame': 2, 'storage_mode': mode})
    acquisition = AcquisitionService(database)
    snapshot = acquisition.spectrum_snapshot(converted['sample_ids'][0], include_frames=True)
    assert snapshot['bands'][0]['mean_points'] == pytest.approx([.1, 2 / 3, 4 / 3])
    assert snapshot['sample']['dark_frame_count'] == 1 and snapshot['sample']['dark_cycle_seconds'] == 2
    assert snapshot['sample']['storage_mode'] == mode
    assert len(snapshot['frames']) == (3 if mode == 'full_interval' else 0)
    with database.read() as db:
        task = db.execute('SELECT * FROM acquisition_tasks WHERE id=?', (converted['task_ids'][0],)).fetchone()
        assert task['pre_excitation_seconds'] == 3 and task['burn_cycle_seconds'] == 1.5
        assert bytes(db.execute('SELECT dark_adcs_blob FROM spectrum_bands WHERE id=1').fetchone()[0]) == struct.pack('<6H', *[2] * 6)


def test_real_dat_formal_report_pdf_and_provenance(tmp_path):
    database = Database(tmp_path / 'dat-report.sqlite3')
    database.initialize()
    runtime = Runtime(AppConfig(data_dir=tmp_path), database=database)
    results = runtime.result_migration_service()
    original = source_file('dat')
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    staged = results.stage(str(original), None)
    results.commit(staged['id'], None)
    reports = runtime.reports_service()
    assert len(reports.legacy_sources()) == 1
    no_unit = reports.create({'legacy_result_ids': [1]})
    assert len(no_unit['model']['rows']) == 270
    assert all(row['unit'] == '' for row in no_unit['model']['rows'])
    assert '原文件未记录单位' in no_unit['model']['provenance_note']
    assert '原文件未记录单位' in reports.preview(no_unit['id'])
    for value in (None, '', '   '):
        blank = reports.create({'legacy_result_ids': [1], 'legacy_unit': value})
        assert all(row['unit'] == '' for row in blank['model']['rows'])
        assert blank['model']['rows'][0]['calculated_value'] == no_unit['model']['rows'][0]['calculated_value']
    reports.confirm(no_unit['id'])
    for output_format in ('excel', 'pdf'):
        exported = reports.export(no_unit['id'], {'format': output_format, 'output_directory': str(tmp_path / 'outputs'), 'filename': 'unit-not-recorded-' + output_format})
        content = Path(exported['path']).read_bytes()
        assert content.startswith(b'%PDF-') if output_format == 'pdf' else b'Workbook' in content
    report = reports.create({'legacy_result_ids': [1], 'legacy_unit': 'ug/g', 'arrangement': 'exchange'})
    assert all(row['unit'] == 'ug/g' for row in report['model']['rows'])
    assert len(report['model']['rows']) == 270 and report['source_run_ids'] == []
    assert report['model']['source_kind'] == 'legacy_dat' and report['model']['legacy_sources'][0]['source_sha256'] == before
    assert all(row['curve_snapshot_id'] is None and row['wavelength_nm'] is None for row in report['model']['rows'])
    assert '旧 DAT 不含方法' in reports.preview(report['id'])
    reports.confirm(report['id'])
    output = reports.export(report['id'], {'format': 'pdf', 'output_directory': str(tmp_path / 'outputs'), 'filename': 'legacy-report'})
    assert Path(output['path']).read_bytes().startswith(b'%PDF-')
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    with database.write() as db:
        db.execute("UPDATE result_matrices SET matrix_sha256='tampered' WHERE id=1")
    with pytest.raises(ReportError, match='SHA-256'):
        reports.create({'legacy_result_ids': [1], 'legacy_unit': 'ug/g'})


@pytest.mark.parametrize('mutation', ['element', 'wavelength', 'mode', 'count', 'interval'])
def test_pdt_strict_signature_rejects_mismatch(tmp_path, mutation):
    database, service = _fixture(tmp_path)
    _, version_id, _ = _seed_method_curve(database)
    with database.read() as db:
        method = service.methods.bind_snapshots(db).by_id(version_id).payload
    lines = canonical_lines(method['lines'], method['conditions'])
    source_lines = [{'element': row['element'], 'wavelength_nm': row['wavelength_nm']} for row in lines]
    payload = {'line_count': len(lines), 'band_count': 1, 'lines': source_lines, 'sample_rows': [{'name': 'N'}]}
    if mutation == 'element': source_lines[-1]['element'] = 'cu'
    if mutation == 'wavelength': source_lines[-1]['wavelength_nm'] += .001
    if mutation == 'mode': payload['header'] = 0x0A73
    if mutation == 'count': payload['line_count'] += 1
    if mutation == 'interval':
        method['conditions'].update(exposure_mode='line_interval', legacy_exposure_mode=True, frame_count=3, legacy_exposure_interval=[1, 3])
        payload.update(header=0x0A73, exposure_segments=[{'left': 1, 'right': 2} for _ in lines])
    row = {'format': 'pdt', 'source_sha256': 'source', 'payload_json': json.dumps(payload), 'matrix_blob': struct.pack('<' + 'ff' * len(lines), *([10, 1] * len(lines)))}
    with pytest.raises(PostProcessingError) as error:
        service.recalculation._recalculate_legacy_result(row, method, {}, 'legacy_2_0_2')
    assert error.value.code == {'element': 'postprocessing_pdt_line_mismatch', 'wavelength': 'postprocessing_pdt_line_mismatch',
        'mode': 'postprocessing_pdt_mode_mismatch', 'count': 'postprocessing_result_matrix_invalid', 'interval': 'postprocessing_pdt_line_mismatch'}[mutation]


def test_pdt_older_method_requires_separate_recorded_confirmation(tmp_path):
    database, service = _fixture(tmp_path)
    method_id, version_id, curve_id = _seed_method_curve(database, legacy_modified_at='2026-10-01T00:00:00+00:00')
    with database.read() as db:
        method = service.methods.bind_snapshots(db).by_id(version_id).payload
    lines = canonical_lines(method['lines'], method['conditions'])
    metadata = {'method_target_id': method_id, 'measure_time': '2026-08-01T00:00:00+00:00',
        'line_count': len(lines), 'band_count': 1, 'sample_rows': [{'name': 'N1'}],
        'lines': [{'element': line['element'], 'wavelength_nm': line['wavelength_nm'], 'back': 1} for line in lines]}
    blob = struct.pack('<' + 'ff' * len(lines), *([20, 1] * len(lines)))
    with database.write() as db:
        db.execute("INSERT INTO result_migration_runs(id,fingerprint,format,status,source_json,parser_json,staging_json,report_json,created_at,updated_at) VALUES ('older-pdt','older-pdt','pdt','committed','{}','{}','{}','{}',?,?)", (utc_now(), utc_now()))
        db.execute("INSERT INTO result_matrices(import_run_id,source_sha256,record_index,format,payload_json,matrix_blob,matrix_sha256) VALUES ('older-pdt','original',0,'pdt',?,?,?)", (json.dumps(metadata), blob, hashlib.sha256(blob).hexdigest()))
    request = {'source_record_ids': ['result:1'], 'method_version_id': version_id, 'curve_snapshot_ids': [curve_id], 'calculation_profile': 'legacy_2_0_2'}
    blocked = service.recalculate(request)
    assert blocked['status'] == 'blocked' and blocked['result']['blocked'][0]['code'] == 'postprocessing_older_pdt_confirmation_required'
    confirmed = service.recalculate({**request, 'allow_older_method': True})
    assert confirmed['status'] == 'completed' and confirmed['report']['allow_older_method'] is True
    assert blocked['input_sha256'] != confirmed['input_sha256']
    with database.read() as db:
        assert bytes(db.execute('SELECT matrix_blob FROM result_matrices WHERE id=1').fetchone()[0]) == blob


def test_two_line_intervals_recalculate_the_same_internal_standard(tmp_path):
    database, runtime, original, line_id, task_id, _, _ = _sample_chain(tmp_path)
    lines_service, methods = runtime.spectral_lines_service(), runtime.methods_service()
    conditions = original['published_version']['conditions']
    with database.read() as db:
        locator = methods.bind_geometry(db, conditions)
        internal_wave, second_wave = locator.wavelength_at(0, 800), locator.wavelength_at(0, 950)
    internal = lines_service.create(original['id'], SpectralLineInput(line_type='internal_standard', element='Fe', wavelength_nm=internal_wave, lower_peak=100), 1)
    internal_id = internal['changed_line_id']
    main = next(line for line in original['published_version']['lines'] if line['id'] == line_id)
    value = {key: value for key, value in main.items() if key in SpectralLineInput.model_fields}
    value.update(internal_standard_mode='line', internal_standard_line_id=internal_id)
    lines_service.update(original['id'], line_id, SpectralLineInput(**value), 1)
    lines_service.create(original['id'], SpectralLineInput(**{**value, 'element': 'Zn', 'wavelength_nm': second_wave,
        'actual_wavelength_nm': second_wave, 'exposure_start_frame': 2, 'exposure_end_frame': 3}), 1)
    published = methods.publish(original['id'], 1)
    frames = runtime.acquisition_service().frames(task_id, include_points=True)
    burns = [frame['points'] for frame in frames if frame['phase'] == 'burn']
    darks = [frame['points'] for frame in frames if frame['phase'] == 'dark']
    for index, frame in enumerate(burns):
        frame[801:804] = [20, [300, 600, 1500][index], 20]
        frame[951:954] = frame[901:904]
    with database.write() as db:
        _, sample = AcquisitionRecordImporter().bind(db).import_record(ImportedAcquisition(name='interval internal', layout_id=1,
            method_id=published['id'], method_version=published['current_version'], method_version_id=published['published_version']['id'],
            sample_name='N2', original_sample_name='N2', source_record_id='test', source_sha256='test', measure_time=None,
            interval_start=1, frame_count=3, bands=[ImportedBand(0, 2048, burns, darks)], actor_user_id=1, created_at=utc_now(), burn_cycle_seconds=1.5, dark_cycle_seconds=2))
    analysis = runtime.analysis_service()
    run = _finish(analysis, analysis.create_run({'acquisition_sample_ids': [sample]}))
    assert run['status'] == 'completed'
    results = [row for row in run['line_results'] if row['line_type'] == 'analysis']
    assert [row['quantitative_signal'] for row in results] == pytest.approx([480 / 290, 3180 / 690], rel=1e-6)
    assert [row['intermediates']['exposure_interval'] for row in results] == [[1, 2], [2, 3]]
