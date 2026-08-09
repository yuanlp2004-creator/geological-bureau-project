param(
  [Parameter(Mandatory=$true)][string]$MenuKey,
  [string[]]$ItemKeys = @(),
  [string]$PostKeys = '',
  [Parameter(Mandatory=$true)][string]$OutputName,
  [switch]$StopAfter
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies @('System.Drawing','System.Windows.Forms') -TypeDefinition @'
using System;
using System.Text;
using System.Drawing;
using System.Drawing.Imaging;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Collections.Generic;
public static class SpecCapture {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int ht, uint flags);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L; public int T; public int R; public int B; }
  public static IntPtr[] WindowsForPid(uint wantedPid) {
    var a = new List<IntPtr>();
    EnumWindows(delegate(IntPtr h, IntPtr l) { uint pid; GetWindowThreadProcessId(h, out pid); if(pid == wantedPid && IsWindowVisible(h)) a.Add(h); return true; }, IntPtr.Zero);
    return a.ToArray();
  }
  public static void Center(IntPtr h, int screenW, int screenH) {
    RECT r; GetWindowRect(h, out r); int w = r.R-r.L, ht = r.B-r.T;
    SetWindowPos(h, IntPtr.Zero, (screenW-w)/2, (screenH-ht-48)/2, w, ht, 0x0040);
    SetForegroundWindow(h);
  }
  public static void CaptureScreen(string path) {
    var b = Screen.PrimaryScreen.Bounds;
    using(var bmp = new Bitmap(b.Width,b.Height)) using(var g = Graphics.FromImage(bmp)) { g.CopyFromScreen(b.Left,b.Top,0,0,bmp.Size,CopyPixelOperation.SourceCopy); bmp.Save(path, ImageFormat.Png); }
  }
  public static void Click(int x, int y) {
    SetCursorPos(x, y); mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero); mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
  }
}
'@

[SpecCapture]::SetProcessDPIAware() | Out-Null
$root = (Get-Location).Path
$exeDir = Join-Path $root 'Spec2.02'
$resultDir = [string]::Concat('Spec2.02', [char]0x529f, [char]0x80fd, [char]0x7814, [char]0x7a76, '_20260802')
$outDir = Join-Path (Join-Path $root $resultDir) 'screenshots'
$p = Get-Process -Name SpecDirect -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) {
  $p = Start-Process -FilePath (Join-Path $exeDir 'SpecDirect.exe') -WorkingDirectory $exeDir -PassThru
  Start-Sleep -Seconds 3
}
[SpecCapture]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[SpecCapture]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
$menuX = @{m=75; e=165; a=300; d=380; t=475; h=550}[$MenuKey]
if ($null -eq $menuX) { throw "Unsupported menu key: $MenuKey" }
[SpecCapture]::Click($menuX, 44)
Start-Sleep -Milliseconds 450
foreach ($key in $ItemKeys) {
  [System.Windows.Forms.SendKeys]::SendWait($key)
  Start-Sleep -Milliseconds 650
}
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
foreach ($h in [SpecCapture]::WindowsForPid([uint32]$p.Id)) {
  if ($h -ne $p.MainWindowHandle) { [SpecCapture]::Center($h, $screen.Width, $screen.Height) }
}
Start-Sleep -Milliseconds 500
if ($PostKeys -ne '') {
  [System.Windows.Forms.SendKeys]::SendWait($PostKeys)
  Start-Sleep -Milliseconds 1200
  foreach ($h in [SpecCapture]::WindowsForPid([uint32]$p.Id)) {
    if ($h -ne $p.MainWindowHandle) { [SpecCapture]::Center($h, $screen.Width, $screen.Height) }
  }
  Start-Sleep -Milliseconds 300
}
$path = Join-Path $outDir ($OutputName + '.png')
[SpecCapture]::CaptureScreen($path)
$img = [System.Drawing.Image]::FromFile($path)
try { if ($img.Width -ne 2880 -or $img.Height -ne 1800) { throw "Unexpected size $($img.Width)x$($img.Height)" } }
finally { $img.Dispose() }
Write-Output ("{0} | {1}x{2}" -f $path, 2880, 1800)
if ($StopAfter) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
