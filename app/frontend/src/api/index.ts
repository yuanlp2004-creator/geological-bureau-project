/** Backwards-compatible public API; request implementations live in business modules. */
import { authApi } from './auth'
import { methodsApi } from './methods'
import { legacySourcesApi } from './legacySources'
import { legacyMigrationApi } from './legacyMigration'
import { spectrumMigrationApi } from './spectrumMigration'
import { resultMigrationApi } from './resultMigration'
import { spectrumViewerApi } from './spectrumViewer'
import { postprocessingApi } from './postprocessing'
import { sampleQueuesApi } from './sampleQueues'
import { systemApi } from './system'
import { maintenanceApi } from './maintenance'
import { devicesApi } from './devices'
import { dispersionApi } from './dispersion'
import { acquisitionApi } from './acquisition'
import { hardwareAcquisitionApi } from './hardwareAcquisition'
import { mercuryCalibrationApi } from './mercuryCalibration'
import { analysisApi } from './analysis'
import { reportsApi } from './reports'

export { ApiError } from './client'
export { eventSocketUrl } from './events'
export { saveFile, savePdfFile, selectLegacyDirectory } from '../platform/files'
export type { EventSeverity, RuntimeEvent, Settings, Capability, About, Diagnostics } from './system'
export type { LegacySourceKind, LegacySource, LegacySourceScan } from './legacySources'
export type { MethodPrintSettings, PrinterOption, PrintJob, MethodValidationIssue, AngleExposure, MethodConditions, MethodVersion, StandardPoint, LineDetectability, SpectralLineInput, SpectralLine, SpectralLineOptions, MethodLineCollection, MethodRecord, CurrentMethodState, CcdLayoutOption, DispersionOption, MethodOptions } from './methods'
export type { BackupRecord, MaintenanceStatus, HelpTopic } from './maintenance'
export type { DeviceProfile, DeviceCcd, DeviceEvent, DeviceDiagnostics, DeviceDebugResult } from './devices'
export type { DispersionState, DispersionLine, DispersionCalibrationVersion, DispersionTask, DispersionFrame, DispersionOptions } from './dispersion'
export type { AcquisitionState, AcquisitionSample, AcquisitionMessage, AcquisitionTask, AcquisitionFrame, AcquisitionOptions, AcquisitionAnalysis } from './acquisition'
export type { HardwareTaskState, HardwarePlanStep, HardwareTask, HardwareOptions } from './hardwareAcquisition'
export type { MercuryReferenceLine, MercuryAlignmentVersion, MercurySessionLine, MercurySession, MercuryOptions } from './mercuryCalibration'
export type { AnalysisStatus, AnalysisSampleOption, AnalysisOptions, AnalysisLineResult, AnalysisCheckpoint, AnalysisQcMember, AnalysisQcGroup, AnalysisQcSnapshot, AnalysisCurvePoint, AnalysisCurveSnapshot, AnalysisCurveLine, AnalysisRun } from './analysis'
export type { ReportTemplate, ReportRow, Report, ReportExport } from './reports'
export type { LegacyMigrationDiagnostic, LegacyMigrationIssue, LegacyMigrationRun } from './legacyMigration'
export type { SpectrumMigrationDiagnostic, SpectrumMigrationRun } from './spectrumMigration'
export type { ResultMigrationDiagnostic, ResultMigrationRun } from './resultMigration'
export type { SpectrumRecordSummary, SpectrumPoint, SpectrumRecord } from './spectrumViewer'
export type { PostProcessingRecord, PostProcessingRecalculationOptions, PostProcessingInterval, PostProcessingRun, PostProcessingExport } from './postprocessing'
export type { SampleQueueItem, SampleQueue } from './sampleQueues'
export type { AuthUser, ManagedUser, ManagedRole, AuditEvent } from './auth'

export const api = {
  ...authApi,
  ...methodsApi,
  ...legacySourcesApi,
  ...legacyMigrationApi,
  ...spectrumMigrationApi,
  ...resultMigrationApi,
  ...spectrumViewerApi,
  ...postprocessingApi,
  ...sampleQueuesApi,
  ...systemApi,
  ...maintenanceApi,
  ...devicesApi,
  ...dispersionApi,
  ...acquisitionApi,
  ...hardwareAcquisitionApi,
  ...mercuryCalibrationApi,
  ...analysisApi,
  ...reportsApi,
}
