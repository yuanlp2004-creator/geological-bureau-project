"""后处理公共应用服务，显式组合转换、重算与导出。"""

from __future__ import annotations

import sqlite3
from typing import Any
from ..analysis.contracts import RecalculationAnalysis
from ..methods import MethodService
from ..acquisition_import import AcquisitionRecordImporter
from ...db import Database
from .conversion import ConversionService
from .exporting import ExportService
from .recalculation import RecalculationService
from .repository import PostProcessingRepository



class PostProcessingService:
    def __init__(self, database: Database, *, analysis: RecalculationAnalysis, methods: MethodService, acquisitions: AcquisitionRecordImporter):
        self.database = database
        self.methods = methods
        self.repository = PostProcessingRepository(database, methods=methods)
        self.conversion = ConversionService(database, self.repository, methods=methods, acquisitions=acquisitions)
        self.recalculation = RecalculationService(database, self.repository, analysis=analysis, methods=methods)
        self.exporting = ExportService(database, self.repository)

    _id = staticmethod(PostProcessingRepository._id)

    _split = staticmethod(PostProcessingRepository._split)

    def edt_records(self, limit: int=200) -> list[dict[str, Any]]:
        return self.repository.edt_records(limit)

    def _raw(self, identifier: str, db: sqlite3.Connection | None=None) -> sqlite3.Row:
        return self.repository._raw(identifier, db)

    _raw_frames = staticmethod(PostProcessingRepository._raw_frames)

    def interval(self, record_id: str, *, ccd: int=0, start_frame: int=1, end_frame: int | None=None, phase: str='burn') -> dict[str, Any]:
        return self.repository.interval(record_id, ccd=ccd, start_frame=start_frame, end_frame=end_frame, phase=phase)

    _conversion_dict = staticmethod(PostProcessingRepository._conversion_dict)

    def conversions(self, limit: int=50) -> list[dict[str, Any]]:
        return self.repository.conversions(limit)

    def recalculation_options(self, limit: int=300) -> dict[str, Any]:
        return self.repository.recalculation_options(limit)

    _recalc_dict = staticmethod(PostProcessingRepository._recalc_dict)

    def recalculations(self, limit: int=50) -> list[dict[str, Any]]:
        return self.repository.recalculations(limit)

    _export_dict = staticmethod(PostProcessingRepository._export_dict)

    def exports(self, limit: int=50) -> list[dict[str, Any]]:
        return self.repository.exports(limit)

    def _target_layout(self, db: sqlite3.Connection, layout_id: int, source_points: int, selected: list[int] | None) -> tuple[sqlite3.Row, list[int]]:
        return self.conversion._target_layout(db, layout_id, source_points, selected)

    def convert_edt(self, payload: dict[str, Any], actor_user_id: int | None=None) -> dict[str, Any]:
        return self.conversion.convert_edt(payload, actor_user_id)

    _method_lines = staticmethod(RecalculationService._method_lines)

    def _recalculate_legacy_result(self, row: sqlite3.Row, method_payload: dict[str, Any], evaluators: dict[str, dict[str, Any]], calculation_profile: str) -> dict[str, Any]:
        return self.recalculation._recalculate_legacy_result(row, method_payload, evaluators, calculation_profile)

    def recalculate(self, payload: dict[str, Any], actor_user_id: int | None=None) -> dict[str, Any]:
        return self.recalculation.recalculate(payload, actor_user_id)

    def _rows_for_export(self, record_ids: list[str], kind: str, db: sqlite3.Connection) -> tuple[list[str], list[list[Any]]]:
        return self.exporting._rows_for_export(record_ids, kind, db)

    _encode = staticmethod(ExportService._encode)

    _atomic_write = staticmethod(ExportService._atomic_write)

    def export(self, payload: dict[str, Any], actor_user_id: int | None=None) -> dict[str, Any]:
        return self.exporting.export(payload, actor_user_id)

