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


def registered_manifests() -> tuple[ModuleManifest, ...]:
    return (CORE_MANIFEST, ABOUT_MANIFEST, AUTH_MANIFEST, METHOD_MANIFEST, LEGACY_MIGRATION_MANIFEST, SAMPLE_QUEUE_MANIFEST, SPECTRUM_MIGRATION_MANIFEST, RESULT_MIGRATION_MANIFEST, SPECTRUM_VIEWER_MANIFEST)


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
