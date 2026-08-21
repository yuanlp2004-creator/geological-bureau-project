from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class NavigationEntry:
    key: str
    group: str
    section_label: str
    label: str
    description: str
    page: str
    order: int
    required_any: tuple[str, ...]
    view: str | None = None
    status: str = "normal"
    required_context: str = "none"

    def to_dict(self) -> dict:
        result = asdict(self)
        result["required_any"] = list(self.required_any)
        return result


def nav(
    key: str,
    group: str,
    section_label: str,
    label: str,
    description: str,
    page: str,
    order: int,
    required_any: tuple[str, ...],
    *,
    view: str | None = None,
    status: str = "normal",
    required_context: str = "none",
) -> NavigationEntry:
    return NavigationEntry(
        key=key,
        group=group,
        section_label=section_label,
        label=label,
        description=description,
        page=page,
        order=order,
        required_any=required_any,
        view=view,
        status=status,
        required_context=required_context,
    )


@dataclass(frozen=True)
class ModuleManifest:
    key: str
    version: str
    title: str
    api_prefix: str
    route: str
    enabled: bool = True
    permissions: tuple[str, ...] = ()
    audit_actions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    navigation_entries: tuple[NavigationEntry, ...] = ()

    def to_dict(self) -> dict:
        result = asdict(self)
        for key in ("permissions", "audit_actions", "dependencies", "capabilities"):
            result[key] = list(result[key])
        result["navigation_entries"] = [entry.to_dict() for entry in self.navigation_entries]
        return result


CORE_MANIFEST = ModuleManifest(
    key="core",
    version="0.1.0",
    title="运行基础",
    api_prefix="/api/v1",
    route="/workspace",
    permissions=("settings.read", "settings.write", "runtime-events.read", "runtime-events.write"),
    audit_actions=("settings.update", "settings.reset", "runtime_event.create", "runtime_event.clear"),
    capabilities=("health", "settings", "runtime-events"),
    navigation_entries=(
        nav("workspace.overview", "workspace", "", "工作台概览", "系统状态、当前方法与运行消息", "workspace", 10, ("runtime-events.read",)),
        nav("system.settings", "system", "系统配置与维护", "软件设置", "目录、显示、打印、时间与日志选项", "settings", 10, ("settings.read",)),
    ),
)

ABOUT_MANIFEST = ModuleManifest(
    key="about-diagnostics",
    version="0.1.0",
    title="关于与诊断",
    api_prefix="/api/v1",
    route="/about",
    permissions=("about.read",),
    audit_actions=("about.view",),
    dependencies=("core",),
    capabilities=("about", "capabilities"),
    navigation_entries=(
        nav("help.about", "help", "", "关于与诊断", "版本、模块清单和本地服务诊断", "about", 20, ("about.read",)),
    ),
)

AUTH_MANIFEST = ModuleManifest(
    key="auth",
    version="0.1.0",
    title="Identity and audit",
    api_prefix="/api/v1",
    route="/users",
    permissions=("users.read", "users.write", "roles.write", "audit.read"),
    audit_actions=("bootstrap", "login", "user.create", "user.permission.change", "role.permission.change", "role.permission.migrate"),
    dependencies=("core",),
    capabilities=("local-authentication", "role-management", "audit"),
    navigation_entries=(
        nav("system.users", "system", "身份与审计", "用户与权限", "本地账户、角色与授权", "users", 30, ("users.read",)),
        nav("system.audit", "system", "身份与审计", "审计记录", "登录、权限与业务事件查询", "audit", 40, ("audit.read",)),
    ),
)

METHOD_MANIFEST = ModuleManifest(
    key="methods", version="0.5.0", title="方法、谱线与参数打印", api_prefix="/api/v1",
    route="/methods", permissions=("methods.read", "methods.write"),
    audit_actions=("method.create", "method.rename", "method.metadata.update", "method.update", "method.publish", "method.pause", "method.resume", "method.delete", "method.copy", "method.open", "spectral_line.create", "spectral_line.update", "spectral_line.toggle", "spectral_line.delete", "spectral_line.reorder", "method.print.settings", "method.preview", "method.pdf.export", "method.print"),
    dependencies=("core", "auth"), capabilities=("method-lifecycle", "method-conditions", "ccd-layouts", "spectral-lines", "wavelength-detectability", "standard-points", "method-html-preview", "method-pdf", "system-printers", "virtual-pdf-printer"),
    navigation_entries=(
        nav("methods.lifecycle", "methods", "方法文件", "方法库与当前方法", "新建、打开、版本、发布与当前方法", "methods", 10, ("methods.read",), view="lifecycle"),
        nav("methods.print-settings", "methods", "方法文件", "页面与打印机设置", "纸张、边距、布局与系统打印机", "methods", 20, ("methods.read",), view="print-settings"),
        nav("conditions.parameters", "conditions", "条件配置", "方法参数", "CCD、色散、激发、重复与转角条件", "methods", 10, ("methods.read",), view="conditions", required_context="current_method"),
        nav("conditions.lines", "conditions", "条件配置", "分析谱线", "谱线、内标、峰值、拟合与标准点", "methods", 20, ("methods.read",), view="lines", required_context="current_method"),
        nav("conditions.print-preview", "conditions", "条件配置", "参数预览与打印", "方法条件、谱线和标准点输出", "methods", 30, ("methods.read",), view="print-preview", required_context="current_method"),
    ),
)

LEGACY_MIGRATION_MANIFEST = ModuleManifest(
    key="legacy-migration",
    version="0.1.0",
    title="旧方法与配置迁移",
    api_prefix="/api/v1",
    route="/migration",
    permissions=("migration.read", "migration.write"),
    audit_actions=("legacy_migration.stage", "legacy_migration.commit"),
    dependencies=("core", "auth", "methods"),
    capabilities=("jet-access-win-x86", "read-only-staging", "atomic-commit", "idempotent-import"),
    navigation_entries=(
        nav("tools.legacy-methods", "tools", "旧版兼容迁移", "旧方法与配置迁移", "DIRECT.MTD、CFG 与 OPT 只读迁移", "migration", 30, ("migration.read",)),
    ),
)

SAMPLE_QUEUE_MANIFEST = ModuleManifest(
    key="sample-queues", version="0.1.0", title="样品队列", api_prefix="/api/v1",
    route="/samples", permissions=("samples.read", "samples.write"),
    audit_actions=("sample_queue.create", "sample_queue.update", "sample_queue.rename", "sample_queue.sam_import", "sample_queue.sam_export"),
    dependencies=("core", "auth"), capabilities=("queue-entry", "sam-read-write", "repeat-expansion", "post-acquisition-rename"),
    navigation_entries=(
        nav("analysis-tests.samples", "analysis-tests", "准备", "样号与样品队列", "预录样号、重复展开与 SAM", "samples", 10, ("samples.read",), required_context="current_method"),
    ),
)

SPECTRUM_MIGRATION_MANIFEST = ModuleManifest(
    key="spectrum-migration", version="0.1.0", title="旧谱数据迁移", api_prefix="/api/v1",
    route="/spectrum-migration", permissions=("spectrum-migration.read", "spectrum-migration.write"),
    audit_actions=("spectrum_migration.stage", "spectrum_migration.commit"),
    dependencies=("core", "auth"), capabilities=("cdt-cmt-edt-wdt", "read-only-access", "array-shape-validation", "atomic-single-file-import", "hash-idempotency"),
    navigation_entries=(
        nav("tools.legacy-spectra", "tools", "旧版兼容迁移", "旧谱数据迁移", "CDT、CMT、EDT 与 WDT 只读迁移", "spectrum-migration", 40, ("spectrum-migration.read",)),
    ),
)

RESULT_MIGRATION_MANIFEST = ModuleManifest(
    key="result-migration", version="0.1.0", title="Result matrix migration", api_prefix="/api/v1",
    route="/result-migration", permissions=("result-migration.read", "result-migration.write"),
    audit_actions=("result_migration.stage", "result_migration.commit"),
    dependencies=("core", "auth"), capabilities=("pdt-dat", "binary-parser", "orphan-results", "read-only-staging", "atomic-single-file-import", "hash-idempotency"),
    navigation_entries=(
        nav("tools.legacy-results", "tools", "旧版兼容迁移", "旧结果迁移", "DAT 与 PDT 结果矩阵只读迁移", "result-migration", 50, ("result-migration.read",)),
    ),
)

SPECTRUM_VIEWER_MANIFEST = ModuleManifest(
    key="spectrum-viewer", version="0.1.0", title="Spectrum viewer", api_prefix="/api/v1",
    route="/spectra", permissions=("spectra.read", "spectra.export"),
    audit_actions=("spectrum.view", "spectrum.export", "spectrum.print"),
    dependencies=("core", "auth", "spectrum-migration", "result-migration"),
    capabilities=("published-spectrum-query", "ccd-coordinate-conversion", "raw-frame-detail", "reversible-view-state", "print-visible-range"),
    navigation_entries=(
        nav("analysis-tests.spectra", "analysis-tests", "查看与分析", "谱图查看", "多样品、转角、CCD、定位与缩放", "spectra", 40, ("spectra.read",), required_context="current_method"),
    ),
)

DEVICE_MANIFEST = ModuleManifest(
    key="devices",
    version="0.1.0",
    title="设备与实时调试",
    api_prefix="/api/v1",
    route="/acquisition",
    permissions=("devices.read", "devices.write", "devices.execute"),
    audit_actions=("device_profile.create", "device_profile.update", "device.connect", "device.connect.failed", "device.disconnect", "device.debug.start", "device.debug.failed", "device.debug.step", "device.debug.stop", "device.debug.fault"),
    dependencies=("core", "auth"),
    capabilities=("device-adapter-contract", "acq-simulator", "device-profiles", "connection-diagnostics", "realtime-debug", "ccd-curve-interaction"),
    navigation_entries=(
        nav("tools.devices", "tools", "设备与光学校准", "设备参数与实时调试", "设备档案、通信诊断与实时 CCD", "acquisition", 10, ("devices.read",)),
    ),
)

DISPERSION_MANIFEST = ModuleManifest(
    key="dispersion",
    version="0.1.0",
    title="色散采集与校准",
    api_prefix="/api/v1",
    route="/dispersion",
    permissions=("dispersion.read", "dispersion.write", "dispersion.execute"),
    audit_actions=("dispersion.task.create", "dispersion.task.start", "dispersion.task.pause", "dispersion.task.resume", "dispersion.task.stop.request", "dispersion.task.stop", "dispersion.task.failed", "dispersion.frame.capture", "dispersion.line.create", "dispersion.line.delete", "dispersion.line.locate", "dispersion.line.move", "dispersion.line.position.save", "dispersion.line.position.restore", "dispersion.calibration.fit", "dispersion.calibration.publish", "dispersion.calibration.bind"),
    dependencies=("core", "auth", "methods", "devices"),
    capabilities=("dispersion-acquisition-state", "burn-dark-frame-storage", "known-line-location", "position-save-restore", "pixel-wavelength-fit", "immutable-calibration-version", "method-revision-binding"),
    navigation_entries=(
        nav("analysis-tests.dispersion", "analysis-tests", "摄谱与校准", "色散摄谱与校准", "色散采集、谱线定位、拟合与发布", "dispersion", 20, ("dispersion.read",)),
    ),
)

ACQUISITION_MANIFEST = ModuleManifest(
    key="acquisition",
    version="0.1.0",
    title="蒸发与样品采集",
    api_prefix="/api/v1",
    route="/sample-acquisition",
    permissions=("acquisition.read", "acquisition.write", "acquisition.execute"),
    audit_actions=("acquisition.task.create", "acquisition.task.start", "acquisition.task.pause", "acquisition.task.resume", "acquisition.task.stop", "acquisition.task.failed", "acquisition.frame.capture", "acquisition.task.completed", "acquisition.repeat.start", "acquisition.interval.mark", "acquisition.sample.rename"),
    dependencies=("core", "auth", "methods", "sample-queues", "devices"),
    capabilities=("evaporation-full-frame", "sample-queue-link", "average-float32", "full-interval-storage", "interval-curve-analysis", "repeat-and-preheat", "post-acquisition-rename"),
    navigation_entries=(
        nav("analysis-tests.acquisition", "analysis-tests", "摄谱与校准", "蒸发与样品摄谱", "平均或全时采集、重复与安全收尾", "sample-acquisition", 30, ("acquisition.read",), required_context="current_method"),
    ),
)

HARDWARE_ACQUISITION_MANIFEST = ModuleManifest(
    key="hardware-acquisition",
    version="0.1.0",
    title="真实设备与自动转角",
    api_prefix="/api/v1",
    route="/hardware-acquisition",
    permissions=("hardware-acquisition.read", "hardware-acquisition.write", "hardware-acquisition.execute"),
    audit_actions=("hardware.task.create", "hardware.task.start", "hardware.task.deferred", "hardware.turn.request", "hardware.turn.response", "hardware.frame.capture", "hardware.anomaly.detected", "hardware.decision.retry", "hardware.decision.correct", "hardware.decision.manual", "hardware.decision.accept", "hardware.task.pause", "hardware.task.resume", "hardware.task.stop", "hardware.task.safety_stop", "hardware.task.completed"),
    dependencies=("core", "auth", "methods", "devices"),
    capabilities=("turn-plan-short-to-long", "key-band-priority", "hardware-trace", "arc-baseline-anomaly", "finite-retry", "manual-takeover", "safe-stop", "serial-protocol-gate"),
    navigation_entries=(
        nav("analysis-tests.hardware", "analysis-tests", "摄谱与校准", "自动转角采集", "关键波段优先、异常闭环与安全停止", "hardware-acquisition", 35, ("hardware-acquisition.read",), status="deferred_external", required_context="current_method"),
    ),
)

MERCURY_CALIBRATION_MANIFEST = ModuleManifest(
    key="mercury-calibration",
    version="0.1.0",
    title="汞灯调试与光学校准",
    api_prefix="/api/v1",
    route="/mercury-calibration",
    permissions=("mercury-calibration.read", "mercury-calibration.write", "mercury-calibration.execute"),
    audit_actions=("mercury.session.create", "mercury.session.start", "mercury.session.deferred", "mercury.frame.capture", "mercury.calibration.suggest", "mercury.calibration.apply", "mercury.calibration.rollback", "mercury.session.stop", "mercury.session.safe_off"),
    dependencies=("core", "auth", "devices", "dispersion"),
    capabilities=("curated-mercury-lines", "synthetic-spectrum", "peak-offset", "optical-correction-suggestion", "immutable-alignment-version", "rollback", "safe-off", "serial-protocol-gate"),
    navigation_entries=(
        nav("tools.mercury", "tools", "设备与光学校准", "汞灯与光学校准", "汞线峰位、校正建议、回滚与安全关闭", "mercury-calibration", 20, ("mercury-calibration.read",), status="deferred_external"),
    ),
)

ANALYSIS_MANIFEST = ModuleManifest(
    key="analysis",
    version="0.2.0",
    title="定量分析、重复质控与标准曲线",
    api_prefix="/api/v1",
    route="/analysis",
    permissions=("analysis.read", "analysis.execute", "analysis.intervene", "analysis.quality", "analysis.curve", "analysis.print"),
    audit_actions=("analysis.run.create", "analysis.run.start", "analysis.run.cancel", "analysis.run.failed", "analysis.intervention.accept", "analysis.intervention.discard", "analysis.qc.recalculate", "analysis.qc.accept", "analysis.qc.exclude", "analysis.qc.restore", "analysis.curve.set_fit", "analysis.curve.set_coordinate", "analysis.curve.set_active", "analysis.curve.adjust", "analysis.curve.restore", "analysis.curve.restore_all", "analysis.curve.fit", "analysis.curve.publish", "analysis.results.merge", "analysis.curve.preview", "analysis.curve.print"),
    dependencies=("core", "auth", "methods", "acquisition"),
    capabilities=("reference-correction", "line-location", "maximum-and-gaussian", "three-internal-standard-modes", "legacy-and-modern-profiles", "single-and-multi-sample-matrix", "slow-mode-checkpoints", "audited-intervention", "replayable-input", "repeat-qc-statistics", "audited-repeat-exclusion", "four-curve-fits", "normal-and-log-coordinates", "curve-adjustment-history", "immutable-curve-snapshots", "snapshot-bound-results", "result-merge", "curve-image-and-text-print"),
    navigation_entries=(
        nav("analysis-tests.raw", "analysis-tests", "查看与分析", "定量分析与慢进", "定量运行、峰位谱图与人工调整", "analysis", 50, ("analysis.read",), view="raw", required_context="current_method"),
        nav("analysis-tests.quality", "analysis-tests", "查看与分析", "重复性质控", "均值、极差、RSD、接受与剔除", "analysis", 60, ("analysis.read",), view="quality", required_context="current_method"),
        nav("analysis-tests.curve", "analysis-tests", "查看与分析", "标准曲线与样品结果", "拟合、标准点、曲线发布与合并结果", "analysis", 70, ("analysis.read",), view="curve", required_context="current_method"),
    ),
)

POSTPROCESSING_MANIFEST = ModuleManifest(
    key="postprocessing",
    version="0.1.0",
    title="全时处理、重算与矩阵导出",
    api_prefix="/api/v1",
    route="/postprocessing",
    permissions=("postprocessing.read", "postprocessing.write", "postprocessing.execute", "postprocessing.export"),
    audit_actions=("postprocessing.interval.view", "postprocessing.interval.export", "postprocessing.edt.convert", "postprocessing.recalculate", "postprocessing.export"),
    dependencies=("core", "auth", "spectrum-migration", "result-migration", "methods", "analysis", "acquisition"),
    capabilities=("full-interval-view", "interval-detail-export", "edt-selection-conversion", "version-bound-recompute", "text-csv-excel-matrix-export", "atomic-output", "idempotent-batch"),
    navigation_entries=(
        nav("data.interval", "data", "全时与重算", "全时区间处理", "区间查看、明细平均导出与 EDT 转换", "postprocessing", 10, ("postprocessing.read",), view="interval", required_context="page_scoped"),
        nav("data.recalculate", "data", "全时与重算", "结果重算与矩阵导出", "版本绑定重算、强度和结果矩阵", "postprocessing", 20, ("postprocessing.read",), view="recalculate-export", required_context="page_scoped"),
    ),
)

REPORTS_MANIFEST = ModuleManifest(
    key="reports", version="0.1.0", title="报告预览、打印与多格式导出", api_prefix="/api/v1",
    route="/reports", permissions=("reports.read", "reports.write", "reports.export"),
    audit_actions=("report.create", "report.preview", "report.confirm", "report.export"),
    dependencies=("core", "auth", "analysis"),
    capabilities=("versioned-report-model", "template-rendering", "standard-exchange-arrangement", "batch-selection", "text-csv-excel-pdf-print", "atomic-output", "audit-trail"),
    navigation_entries=(
        nav("data.reports", "data", "报告", "分析报告", "编号、模板、预览、打印与多格式导出", "reports", 30, ("reports.read",), required_context="page_scoped"),
    ),
)

MAINTENANCE_MANIFEST = ModuleManifest(
    key="maintenance", version="0.1.0", title="备份维护与离线帮助", api_prefix="/api/v1",
    route="/maintenance", permissions=("maintenance.read", "maintenance.write", "help.read"),
    audit_actions=("maintenance.backup", "maintenance.verify", "maintenance.restore.rehearsal", "maintenance.checkpoint", "maintenance.optimize", "maintenance.reclaim", "maintenance.retention", "maintenance.logs", "maintenance.temp", "help.view"),
    dependencies=("core", "auth"),
    capabilities=("online-backup", "backup-verify", "restore-rehearsal", "retention", "wal-checkpoint", "optimize", "controlled-reclaim", "log-rotation", "temp-cleanup", "offline-help", "about-diagnostics"),
    navigation_entries=(
        nav("system.maintenance", "system", "系统配置与维护", "备份与维护", "备份、恢复演练、空间和日志维护", "maintenance", 20, ("maintenance.read",)),
        nav("help.offline", "help", "", "离线帮助", "业务流程、错误码与旧格式兼容", "help", 10, ("help.read",)),
    ),
)


def registered_manifests() -> tuple[ModuleManifest, ...]:
    core_manifests = (CORE_MANIFEST, ABOUT_MANIFEST, AUTH_MANIFEST, METHOD_MANIFEST, LEGACY_MIGRATION_MANIFEST, SAMPLE_QUEUE_MANIFEST, SPECTRUM_MIGRATION_MANIFEST, RESULT_MIGRATION_MANIFEST, SPECTRUM_VIEWER_MANIFEST, DEVICE_MANIFEST, DISPERSION_MANIFEST, ACQUISITION_MANIFEST, HARDWARE_ACQUISITION_MANIFEST, MERCURY_CALIBRATION_MANIFEST, ANALYSIS_MANIFEST, POSTPROCESSING_MANIFEST, REPORTS_MANIFEST, MAINTENANCE_MANIFEST)
    from .extensions import discover_test_extensions

    return core_manifests + tuple(extension.module_manifest() for extension in discover_test_extensions())


def validate_manifests(manifests: tuple[ModuleManifest, ...] | list[ModuleManifest]) -> None:
    keys: set[str] = set()
    routes: set[str] = set()
    permissions: set[str] = set()
    navigation_keys: set[str] = set()
    allowed_groups = {"workspace", "methods", "conditions", "analysis-tests", "data", "tools", "system", "help"}
    allowed_contexts = {"none", "current_method", "current_method_exp_seg", "page_scoped"}
    allowed_statuses = {"normal", "deferred_external", "test_only"}
    allowed_views = {
        "methods": {"lifecycle", "conditions", "lines", "print-settings", "print-preview"},
        "analysis": {"raw", "quality", "curve", "standards", "samples"},
        "postprocessing": {"interval", "recalculate-export"},
    }
    for manifest in manifests:
        if manifest.key in keys:
            raise ValueError(f"duplicate module key: {manifest.key}")
        if manifest.route in routes:
            raise ValueError(f"duplicate module route: {manifest.route}")
        keys.add(manifest.key)
        routes.add(manifest.route)
        overlap = permissions.intersection(manifest.permissions)
        if overlap:
            raise ValueError(f"duplicate permission key: {sorted(overlap)[0]}")
        permissions.update(manifest.permissions)
        for entry in manifest.navigation_entries:
            if entry.key in navigation_keys:
                raise ValueError(f"duplicate navigation key: {entry.key}")
            navigation_keys.add(entry.key)
            if entry.group not in allowed_groups:
                raise ValueError(f"invalid navigation group: {entry.group}")
            if entry.required_context not in allowed_contexts:
                raise ValueError(f"invalid navigation context: {entry.required_context}")
            if entry.status not in allowed_statuses:
                raise ValueError(f"invalid navigation status: {entry.status}")
            if not entry.required_any or set(entry.required_any).difference(manifest.permissions):
                raise ValueError(f"invalid navigation permission for {entry.key}")
            if entry.view is not None and entry.view not in allowed_views.get(entry.page, set()):
                raise ValueError(f"invalid navigation view for {entry.key}: {entry.view}")
    for manifest in manifests:
        missing = set(manifest.dependencies).difference(keys)
        if missing:
            raise ValueError(f"{manifest.key} depends on unregistered module(s): {sorted(missing)}")
