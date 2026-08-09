param(
  [ValidateSet('List', 'Close')]
  [string]$Action = 'List',
  [string]$TitleLike,
  [string]$ButtonLike
)

$ErrorActionPreference = 'Stop'

$native = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class SpecUiNative {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  public delegate bool EnumChildProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumChildProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int maxCount);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  public static string Text(IntPtr hWnd) {
    var value = new StringBuilder(512);
    GetWindowText(hWnd, value, value.Capacity);
    return value.ToString();
  }
  public static string Class(IntPtr hWnd) {
    var value = new StringBuilder(256);
    GetClassName(hWnd, value, value.Capacity);
    return value.ToString();
  }
}
'@
Add-Type -TypeDefinition $native -ErrorAction SilentlyContinue

$app = Get-Process -Name 'SpecDirect' -ErrorAction Stop | Select-Object -First 1
$main = $app.MainWindowHandle
$windows = New-Object System.Collections.Generic.List[object]
[SpecUiNative]::EnumWindows({
  param($hWnd, $lParam)
  $windowPid = 0
  [SpecUiNative]::GetWindowThreadProcessId($hWnd, [ref]$windowPid) | Out-Null
  if ($windowPid -eq $app.Id -and [SpecUiNative]::IsWindowVisible($hWnd) -and $hWnd -ne $main) {
    $windows.Add([pscustomobject]@{ Handle = $hWnd; Title = [SpecUiNative]::Text($hWnd); Class = [SpecUiNative]::Class($hWnd) })
  }
  return $true
}, [IntPtr]::Zero) | Out-Null

if ($Action -eq 'List') {
  $windows
  exit
}

$target = $windows | Where-Object { [string]::IsNullOrWhiteSpace($TitleLike) -or $_.Title -like "*$TitleLike*" } | Select-Object -First 1
if (-not $target) { throw 'No matching SpecDirect child window was found.' }

$button = $null
[SpecUiNative]::EnumChildWindows($target.Handle, {
  param($hWnd, $lParam)
  if ($script:button -eq $null -and ([SpecUiNative]::Class($hWnd) -eq 'TButton' -or [SpecUiNative]::Class($hWnd) -eq 'Button')) {
    $text = [SpecUiNative]::Text($hWnd)
    if ([string]::IsNullOrWhiteSpace($ButtonLike) -or $text -like "*$ButtonLike*") {
      $script:button = $hWnd
    }
  }
  return $true
}, [IntPtr]::Zero) | Out-Null

if ($script:button) {
  [SpecUiNative]::SetForegroundWindow($target.Handle) | Out-Null
  [SpecUiNative]::SendMessage($script:button, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
} else {
  [SpecUiNative]::PostMessage($target.Handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
}
Start-Sleep -Milliseconds 400
