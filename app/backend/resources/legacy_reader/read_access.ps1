param(
    [string]$Path,
    [string]$OutputDirectory,
    [switch]$Probe
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

if ($Probe) {
    $provider = 'Microsoft.Jet.OLEDB.4.0'
    $available = $false
    try {
        $enumerator = [System.Data.OleDb.OleDbEnumerator]::GetRootEnumerator()
        while ($enumerator.Read()) {
            if ([string]::Equals([string]$enumerator['SOURCES_NAME'], $provider, [StringComparison]::OrdinalIgnoreCase)) {
                $available = $true
                break
            }
        }
        $enumerator.Close()
    }
    catch {
        $available = $false
    }
    [ordered]@{
        available = $available
        provider = $provider
        process_bits = [IntPtr]::Size * 8
        message = $(if ($available) { '32-bit Jet 4.0 provider is available.' } else { '32-bit Jet 4.0 provider is not installed.' })
    } | ConvertTo-Json -Compress
    if (-not $available) { exit 3 }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Path)) {
    throw 'Path is required unless -Probe is used.'
}

function Convert-LegacyValue {
    param([object]$Value)

    if ($null -eq $Value -or $Value -is [DBNull]) {
        return $null
    }
    if ($Value -is [DateTime]) {
        return $Value.ToString('o', [Globalization.CultureInfo]::InvariantCulture)
    }
    if ($Value -is [byte[]]) {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = $sha.ComputeHash($Value)
        }
        finally {
            $sha.Dispose()
        }
        return [ordered]@{
            kind = 'blob'
            byte_length = $Value.Length
            sha256 = ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
            base64 = [Convert]::ToBase64String($Value)
        }
    }
    if ($Value -is [bool] -or $Value -is [string]) {
        return $Value
    }
    if ($Value -is [IFormattable]) {
        return [ordered]@{
            kind = 'number'
            value = $Value.ToString($null, [Globalization.CultureInfo]::InvariantCulture)
        }
    }
    return [string]$Value
}

function Write-BlobFile {
    param(
        [System.Data.OleDb.OleDbDataReader]$Reader,
        [int]$Ordinal,
        [string]$Directory,
        [string]$Name
    )

    $length = [long]$Reader.GetBytes($Ordinal, 0, $null, 0, 0)
    $target = Join-Path $Directory $Name
    $stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $sha = [Security.Cryptography.SHA256]::Create()
    $buffer = New-Object byte[] (1024 * 1024)
    $offset = [long]0
    $digest = $null
    try {
        while ($offset -lt $length) {
            $wanted = [int][Math]::Min($buffer.Length, $length - $offset)
            $read = [int]$Reader.GetBytes($Ordinal, $offset, $buffer, 0, $wanted)
            if ($read -le 0) { throw "Unexpected end of BLOB at ordinal $Ordinal." }
            $stream.Write($buffer, 0, $read)
            [void]$sha.TransformBlock($buffer, 0, $read, $null, 0)
            $offset += $read
        }
        [void]$sha.TransformFinalBlock($buffer, 0, 0)
        $digest = $sha.Hash
        $stream.Flush()
    }
    finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    return [ordered]@{
        kind = 'blob_file'
        byte_length = $length
        sha256 = ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
        file = $Name
    }
}

$resolved = (Resolve-Path -LiteralPath $Path).Path
$connection = New-Object System.Data.OleDb.OleDbConnection
$connection.ConnectionString = "Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$resolved;Mode=Read;"

try {
    $connection.Open()
    $tableSchema = $connection.GetOleDbSchemaTable(
        [System.Data.OleDb.OleDbSchemaGuid]::Tables,
        @($null, $null, $null, 'TABLE')
    )
    $tables = [ordered]@{}
    $streaming = -not [string]::IsNullOrWhiteSpace($OutputDirectory)
    $rowWriter = $null
    if ($streaming) {
        $resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
        [IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
        $rowWriter = New-Object IO.StreamWriter((Join-Path $resolvedOutput 'rows.jsonl'), $false, (New-Object Text.UTF8Encoding($false)))
    }
    foreach ($tableRow in ($tableSchema | Sort-Object TABLE_NAME)) {
        $tableName = [string]$tableRow.TABLE_NAME
        if ($tableName.StartsWith('MSys', [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $escapedTable = $tableName.Replace(']', ']]')
        $safeTable = [Text.RegularExpressions.Regex]::Replace($tableName, '[^A-Za-z0-9_-]', '_')
        $command = $connection.CreateCommand()
        $command.CommandText = "SELECT * FROM [$escapedTable]"
        $reader = $command.ExecuteReader([System.Data.CommandBehavior]::SequentialAccess)
        $rows = @()
        $rowIndex = 0
        try {
            while ($reader.Read()) {
                $row = [ordered]@{}
                for ($index = 0; $index -lt $reader.FieldCount; $index++) {
                    if ($streaming -and $reader.GetFieldType($index) -eq [byte[]] -and -not $reader.IsDBNull($index)) {
                        $blobName = ('blob-{0}-{1:D6}-{2:D4}.bin' -f $safeTable, $rowIndex, $index)
                        $row[$reader.GetName($index)] = Write-BlobFile $reader $index $resolvedOutput $blobName
                    }
                    else {
                        $row[$reader.GetName($index)] = Convert-LegacyValue $reader.GetValue($index)
                    }
                }
                if ($streaming) {
                    $rowWriter.WriteLine(([ordered]@{ table = $tableName; row_index = $rowIndex; values = $row } | ConvertTo-Json -Depth 16 -Compress))
                }
                else {
                    $rows += $row
                }
                $rowIndex++
            }
        }
        finally {
            $reader.Close()
            $reader.Dispose()
            $command.Dispose()
        }
        if ($streaming) {
            $tables[$tableName] = $rowIndex
        }
        else {
            $tables[$tableName] = @($rows)
        }
    }
    if ($streaming) {
        $rowWriter.Flush()
        $rowWriter.Dispose()
        $rowWriter = $null
        [ordered]@{
            format_version = 2
            provider = 'Microsoft.Jet.OLEDB.4.0'
            mode = 'Read'
            file = [IO.Path]::GetFileName($resolved)
            rows_file = 'rows.jsonl'
            table_counts = $tables
        } | ConvertTo-Json -Depth 16 -Compress
    }
    else {
        [ordered]@{
            format_version = 1
            provider = 'Microsoft.Jet.OLEDB.4.0'
            mode = 'Read'
            file = [IO.Path]::GetFileName($resolved)
            tables = $tables
        } | ConvertTo-Json -Depth 16 -Compress
    }
}
finally {
    if ($null -ne $rowWriter) { $rowWriter.Dispose() }
    if ($connection.State -ne [System.Data.ConnectionState]::Closed) {
        $connection.Close()
    }
    $connection.Dispose()
}
