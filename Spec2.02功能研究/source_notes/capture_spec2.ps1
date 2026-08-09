param(
  [string]$ShotName,
  [string]$Keys,
  [string]$KeysAfter,
  [int]$ClickX = -1,
  [int]$ClickY = -1,
  [int]$WaitMs = 500,
  [string]$OutputDir,
  [switch]$FocusOnly,
  [switch]$CaptureOnly
)

$ErrorActionPreference = 'Stop'

$native = @'
using System;
using System.Runtime.InteropServices;
public static class SpecCaptureNative {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);
  public static IntPtr FindOwnedWindow(int pid, IntPtr main) {
    IntPtr result = IntPtr.Zero;
    EnumWindows((hWnd, lParam) => {
      uint windowPid;
      GetWindowThreadProcessId(hWnd, out windowPid);
      if (windowPid == (uint)pid && hWnd != main && IsWindowVisible(hWnd) && GetWindow(hWnd, 4) == main) {
        result = hWnd;
        return false;
      }
      return true;
    }, IntPtr.Zero);
    return result;
  }
}
'@
Add-Type -TypeDefinition $native -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

[SpecCaptureNative]::SetProcessDPIAware() | Out-Null
$app = Get-Process -Name 'SpecDirect' -ErrorAction Stop | Select-Object -First 1
$target = $app.MainWindowHandle
if ($CaptureOnly) {
  $owned = [SpecCaptureNative]::FindOwnedWindow($app.Id, $app.MainWindowHandle)
  if ($owned -ne [IntPtr]::Zero) { $target = $owned }
}
if (-not $CaptureOnly) {
  [SpecCaptureNative]::ShowWindow($app.MainWindowHandle, 3) | Out-Null
  [SpecCaptureNative]::SetForegroundWindow($app.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 200
}
else {
  [SpecCaptureNative]::SetForegroundWindow($target) | Out-Null
  Start-Sleep -Milliseconds 200
}

if ($Keys) {
  [System.Windows.Forms.SendKeys]::SendWait($Keys)
  Start-Sleep -Milliseconds $WaitMs
}

if ($KeysAfter) {
  [System.Windows.Forms.SendKeys]::SendWait($KeysAfter)
  Start-Sleep -Milliseconds $WaitMs
}

if ($ClickX -ge 0 -and $ClickY -ge 0) {
  [SpecCaptureNative]::SetCursorPos($ClickX, $ClickY) | Out-Null
  [SpecCaptureNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
  [SpecCaptureNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds $WaitMs
}

if (-not $FocusOnly -and $ShotName) {
  if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $dir = Join-Path (Split-Path -Parent $PSScriptRoot) 'screenshots'
  } else {
    $dir = $OutputDir
  }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $path = Join-Path $dir ($ShotName + '.png')
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
  $graphics = [System.Drawing.Graphics]::FromImage($bmp)
  $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose()
  $bmp.Dispose()
  [pscustomobject]@{ Path = $path; Width = $bounds.Width; Height = $bounds.Height; Bytes = (Get-Item -LiteralPath $path).Length }
}
