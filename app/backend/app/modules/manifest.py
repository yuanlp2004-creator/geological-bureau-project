from __future__ import annotations

from dataclasses import asdict, dataclass, field


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

    def to_dict(self) -> dict:
        result = asdict(self)
        for key in ("permissions", "audit_actions", "dependencies", "capabilities"):
            result[key] = list(result[key])
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
)

METHOD_MANIFEST = ModuleManifest(
    key="methods", version="0.5.0", title="方法、谱线与参数打印", api_prefix="/api/v1",
    route="/methods", permissions=("methods.read", "methods.write"),
    audit_actions=("method.create", "method.rename", "method.metadata.update", "method.update", "method.publish", "method.pause", "method.resume", "method.delete", "method.copy", "method.open", "spectral_line.create", "spectral_line.update", "spectral_line.toggle", "spectral_line.delete", "spectral_line.reorder", "method.print.settings", "method.preview", "method.pdf.export", "method.print"),
    dependencies=("core", "auth"), capabilities=("method-lifecycle", "method-conditions", "ccd-layouts", "spectral-lines", "wavelength-detectability", "standard-points", "method-html-preview", "method-pdf", "system-printers", "virtual-pdf-printer"),
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
)

SAMPLE_QUEUE_MANIFEST = ModuleManifest(
    key="sample-queues", version="0.1.0", title="样品队列", api_prefix="/api/v1",
    route="/samples", permissions=("samples.read", "samples.write"),
    audit_actions=("sample_queue.create", "sample_queue.update", "sample_queue.rename", "sample_queue.sam_import", "sample_queue.sam_export"),
    dependencies=("core", "auth"), capabilities=("queue-entry", "sam-read-write", "repeat-expansion", "post-acquisition-rename"),
)

SPECTRUM_MIGRATION_MANIFEST = ModuleManifest(
    key="spectrum-migration", version="0.1.0", title="旧谱数据迁移", api_prefix="/api/v1",
    route="/spectrum-migration", permissions=("spectrum-migration.read", "spectrum-migration.write"),
    audit_actions=("spectrum_migration.stage", "spectrum_migration.commit"),
    dependencies=("core", "auth"), capabilities=("cdt-cmt-edt-wdt", "read-only-access", "array-shape-validation", "atomic-single-file-import", "hash-idempotency"),
)

RESULT_MIGRATION_MANIFEST = ModuleManifest(
    key="result-migration", version="0.1.0", title="Result matrix migration", api_prefix="/api/v1",
    route="/result-migration", permissions=("result-migration.read", "result-migration.write"),
    audit_actions=("result_migration.stage", "result_migration.commit"),
    dependencies=("core", "auth"), capabilities=("pdt-dat", "binary-parser", "orphan-results", "read-only-staging", "atomic-single-file-import", "hash-idempotency"),
)

SPECTRUM_VIEWER_MANIFEST = ModuleManifest(
    key="spectrum-viewer", version="0.1.0", title="Spectrum viewer", api_prefix="/api/v1",
    route="/spectra", permissions=("spectra.read", "spectra.export"),
    audit_actions=("spectrum.view", "spectrum.export", "spectrum.print"),
    dependencies=("core", "auth", "spectrum-migration", "result-migration"),
    capabilities=("published-spectrum-query", "ccd-coordinate-conversion", "raw-frame-detail", "reversible-view-state", "print-visible-range"),
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
)

ANALYSIS_MANIFEST = ModuleManifest(
    key="analysis",
    version="0.1.0",
    title="定量分析与慢进干预",
    api_prefix="/api/v1",
    route="/analysis",
    permissions=("analysis.read", "analysis.execute", "analysis.intervene"),
    audit_actions=("analysis.run.create", "analysis.run.start", "analysis.run.cancel", "analysis.run.failed", "analysis.intervention.accept", "analysis.intervention.discard"),
    dependencies=("core", "auth", "methods", "acquisition"),
    capabilities=("reference-correction", "line-location", "maximum-and-gaussian", "three-internal-standard-modes", "legacy-and-modern-profiles", "single-and-multi-sample-matrix", "slow-mode-checkpoints", "audited-intervention", "replayable-input"),
)


def registered_manifests() -> tuple[ModuleManifest, ...]:
    return (CORE_MANIFEST, ABOUT_MANIFEST, AUTH_MANIFEST, METHOD_MANIFEST, LEGACY_MIGRATION_MANIFEST, SAMPLE_QUEUE_MANIFEST, SPECTRUM_MIGRATION_MANIFEST, RESULT_MIGRATION_MANIFEST, SPECTRUM_VIEWER_MANIFEST, DEVICE_MANIFEST, DISPERSION_MANIFEST, ACQUISITION_MANIFEST, HARDWARE_ACQUISITION_MANIFEST, MERCURY_CALIBRATION_MANIFEST, ANALYSIS_MANIFEST)


def validate_manifests(manifests: tuple[ModuleManifest, ...] | list[ModuleManifest]) -> None:
    keys: set[str] = set()
    routes: set[str] = set()
    permissions: set[str] = set()
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
    for manifest in manifests:
        missing = set(manifest.dependencies).difference(keys)
        if missing:
            raise ValueError(f"{manifest.key} depends on unregistered module(s): {sorted(missing)}")
