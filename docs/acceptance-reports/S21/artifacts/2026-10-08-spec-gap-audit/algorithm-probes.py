"""Small non-mutating numeric probes for the SpecDirect parity audit."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(root / 'app'))

from backend.modules.analysis.algorithms import fit_curve, evaluate_curve
from backend.modules.analysis.candidate import calculate_candidate
from backend.modules.analysis.errors import AnalysisError
from backend.modules.analysis.rules import _base_curve_points
from backend.modules.postprocessing.legacy_calculation import LegacyIntensity, recalculate_legacy

evidence = root / 'docs/acceptance-reports/S21/artifacts/2026-10-08-spec-gap-audit'
evidence.mkdir(parents=True, exist_ok=True)
checks = []
line = {'id': 'A', 'element': 'A', 'line_type': 'analysis', 'wavelength_nm': 280.0,
        'scan_width_points': 9, 'peak_width_points': 3, 'peak_mode': 'gaussian',
        'background_offset_points': 0, 'internal_standard_mode': 'none'}
try:
    calculate_candidate(line, [line], 0, 0, 0, 4.0, [10.0] * 9, {}, {}, 'legacy_2_0_2', None)
    raise AssertionError('Expected current gaussian failure policy')
except AnalysisError as exc:
    assert exc.code == 'analysis_gaussian_fit_failed'
    checks.append({'id': 'gaussian_fallback', 'input': [10.0] * 9, 'profile': 'legacy_2_0_2',
                   'current': exc.code, 'legacy_source_rule': 'retain the searched peak height, 10.0'})

fit = fit_curve([10, 20, 30, 40], [1, 2, 3, 4], 'linear')
above = evaluate_curve(fit, 100.0)
assert abs(above - 10.0) < 1e-6
checks.append({'id': 'upper_curve_boundary', 'intensities': [10, 20, 30, 40], 'contents': [1, 2, 3, 4],
               'sample_intensity': 100.0, 'current': above, 'legacy_source_rule_result': 4.0})
quad = fit_curve([10, 20, 30, 40], [1, 4, 9, 16], 'quadratic')
below = evaluate_curve(quad, 1.0)
assert abs(below - 0.01) < 1e-6
checks.append({'id': 'lower_curve_boundary', 'sample_intensity': 1.0,
               'current': below, 'legacy_source_rule_result': 1.0 / 3.0})
log_fit = fit_curve([10, 20, 40, 80], [1, 3, 8, 20], 'quadratic', 'logarithmic')
assert len(log_fit['x']) == 4
checks.append({'id': 'logarithmic_smoothing', 'current_fit_point_count': len(log_fit['x']),
               'legacy_source_rule': 'nonlinear logarithmic fit with fewer than 16 points uses 16 interpolated and smoothed points'})

internal = {'id': 'I', 'element': 'I', 'line_type': 'internal_standard', 'wavelength_nm': 281.0,
            'background_offset_points': 2}
analysis = {**line, 'peak_mode': 'max_single_point', 'internal_standard_mode': 'line',
            'internal_standard_line_id': 'I', 'lower_peak': 100}
candidate = calculate_candidate(analysis, [internal, analysis], 0, 1, 0, 4.0,
                                [10, 10, 10, 30, 200, 20, 10, 10, 10], {},
                                {'I': {'net_signal': 80, 'quantitative_signal': 80}}, 'legacy_2_0_2', None)
assert abs(candidate['quantitative_signal'] - 2.5) < 1e-5
checks.append({'id': 'internal_background_switch', 'analysis_peak': 200, 'analysis_back_position': 0,
               'internal_peak': 100, 'internal_background': 20, 'internal_back_position': 2,
               'current_candidate_ratio': candidate['quantitative_signal'], 'legacy_source_rule_result': 2.0})
identity = fit_curve([1, 2, 3, 4], [1, 2, 3, 4], 'linear')
source = LegacyIntensity('probe', [{'element': 'A', 'wavelength_nm': 280.0, 'back': 0},
                                  {'element': 'I', 'wavelength_nm': 281.0, 'back': 2}],
                         [{'sample_name': 'probe'}], [[(200.0, 0.0)], [(100.0, 20.0)]], 1)
recalc = recalculate_legacy(source, [analysis, internal],
                           {'A': {'fit': identity, 'coordinate_type': 'normal', 'curve_snapshot_id': 1}},
                           'legacy_2_0_2')
assert abs(recalc['lines'][0]['quantitative_signal'] - 2.5) < 1e-5
checks.append({'id': 'internal_background_recalculation', 'current': recalc['lines'][0]['quantitative_signal'],
               'legacy_source_rule_result': 2.0})

points = _base_curve_points({'id': 'A', 'standard_points': [
    {'name': f'S{i}', 'value': i, 'active': True, 'raw_black': i * 10.0, 'current_black': i * 10.0}
    for i in range(1, 5)]}, [])
assert all(point['adjusted_intensity'] is None for point in points)
checks.append({'id': 'stored_standard_reuse', 'current_intensities': [p['adjusted_intensity'] for p in points],
               'legacy_source_rule': 'when fewer than four current standards are selected, load the prior Valid standard set'})

source_files = [
 'Spec2.02功能研究/01_功能树_源码整理版.md', 'Spec2.02功能研究/05_下拉选项与参数使用链.md',
 'Spec2.02功能研究/06_业务流程与参数消费矩阵.md', 'Spec2.02功能研究/10_缺漏复查与功能补充.md',
 'Spec2.02功能研究/12_系统功能复核与补充.md', 'Spec Source/Source/Common/uFitMode.pas',
 'Spec Source/Source/Common/uAnaThread.pas', 'Spec Source/Source/Main/mmAnalyze/FmAnaCheck.pas',
 'Spec Source/Source/Main/mmAnalyze/FmAnaCurve.pas', 'app/backend/modules/analysis/algorithms.py',
 'app/backend/modules/analysis/candidate.py', 'app/backend/modules/analysis/curves.py',
 'app/backend/modules/analysis/rules.py', 'app/backend/modules/postprocessing/legacy_calculation.py',
 'app/backend/modules/legacy_migration/records.py', 'app/backend/modules/legacy_migration/normalization.py',
 'app/backend/modules/acquisition/repository.py', 'app/backend/modules/postprocessing/recalculation.py',
 'app/backend/modules/postprocessing/exporting.py', 'app/backend/modules/postprocessing/conversion.py',
 'app/backend/modules/acquisition_import.py', 'app/backend/modules/reports/service.py',
 'app/backend/schemas/methods.py', 'app/backend/schemas/reports.py',
 'app/frontend/src/pages/methods/MethodGeometry.tsx', 'app/frontend/src/pages/methods/MethodsPage.tsx',
 'app/frontend/src/pages/acquisition/SampleAcquisitionPage.tsx', 'app/frontend/src/pages/analysis/AnalysisSpectrum.tsx'
]
result = {'date': '2026-10-08', 'status': 'numeric_differences_reproduced', 'probe_count': len(checks),
          'scope': 'pure numeric probes, not full workflow or hardware acceptance', 'checks': checks,
          'source_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in source_files}}
(evidence / 'algorithm-probes.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'numeric_probe_count': len(checks), 'differences_reproduced': True}, ensure_ascii=False))
