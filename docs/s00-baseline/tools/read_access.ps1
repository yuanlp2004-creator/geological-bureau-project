param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

function Convert-ScalarValue {
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
        $probeCount = [Math]::Min(8, [Math]::Floor($Value.Length / 2))
        $firstWords = @()
        $lastWords = @()
        for ($i = 0; $i -lt $probeCount; $i++) {
            $firstWords += [BitConverter]::ToUInt16($Value, $i * 2)
            $lastWords += [BitConverter]::ToUInt16($Value, $Value.Length - (($probeCount - $i) * 2))
        }
        return [ordered]@{
            kind = 'blob'
            byte_length = $Value.Length
            sha256 = ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
            first_uint16_le = $firstWords
            last_uint16_le = $lastWords
        }
    }
    if ($Value -is [bool]) {
        return $Value
    }
    if ($Value -is [string]) {
        return $Value
    }
    if ($Value -is [IFormattable]) {
        return $Value.ToString($null, [Globalization.CultureInfo]::InvariantCulture)
    }
    return $Value.ToString()
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
    $tables = @()
    foreach ($tableRow in ($tableSchema | Sort-Object TABLE_NAME)) {
        $tableName = [string]$tableRow.TABLE_NAME
        if ($tableName.StartsWith('MSys', [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $escapedTable = $tableName.Replace(']', ']]')
        $columnSchema = $connection.GetOleDbSchemaTable(
            [System.Data.OleDb.OleDbSchemaGuid]::Columns,
            @($null, $null, $tableName, $null)
        )
        $columns = @()
        foreach ($columnRow in ($columnSchema | Sort-Object ORDINAL_POSITION)) {
            $columns += [ordered]@{
                name = [string]$columnRow.COLUMN_NAME
                ordinal = [int]$columnRow.ORDINAL_POSITION
                ole_db_type = [string]$columnRow.DATA_TYPE
                max_length = if ($columnRow.CHARACTER_MAXIMUM_LENGTH -is [DBNull]) {
                    $null
                }
                else {
                    [int64]$columnRow.CHARACTER_MAXIMUM_LENGTH
                }
            }
        }

        $countCommand = $connection.CreateCommand()
        $countCommand.CommandText = "SELECT COUNT(*) FROM [$escapedTable]"
        $rowCount = [int64]$countCommand.ExecuteScalar()
        $countCommand.Dispose()

        $firstRow = [ordered]@{}
        if ($rowCount -gt 0) {
            $rowCommand = $connection.CreateCommand()
            $rowCommand.CommandText = "SELECT TOP 1 * FROM [$escapedTable]"
            $reader = $rowCommand.ExecuteReader([System.Data.CommandBehavior]::SequentialAccess)
            try {
                if ($reader.Read()) {
                    for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                        $firstRow[$reader.GetName($i)] = Convert-ScalarValue $reader.GetValue($i)
                    }
                }
            }
            finally {
                $reader.Close()
                $reader.Dispose()
                $rowCommand.Dispose()
            }
        }

        $tables += [ordered]@{
            name = $tableName
            row_count = $rowCount
            columns = $columns
            first_row = $firstRow
        }
    }

    [ordered]@{
        file = [IO.Path]::GetFileName($resolved)
        provider = 'Microsoft.Jet.OLEDB.4.0'
        mode = 'Read'
        tables = $tables
    } | ConvertTo-Json -Depth 12 -Compress
}
finally {
    if ($connection.State -ne [System.Data.ConnectionState]::Closed) {
        $connection.Close()
    }
    $connection.Dispose()
}
