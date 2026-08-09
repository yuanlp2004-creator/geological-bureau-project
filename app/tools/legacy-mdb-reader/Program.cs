using System.Data;
using System.Data.OleDb;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;

const string Provider = "Microsoft.Jet.OLEDB.4.0";

if (args.Contains("--probe", StringComparer.OrdinalIgnoreCase))
{
    var available = OleDbEnumerator.GetRootEnumerator().AsEnumerable()
        .Any(row => string.Equals(row.Field<string>("SOURCES_NAME"), Provider, StringComparison.OrdinalIgnoreCase));
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        available,
        provider = Provider,
        process_bits = IntPtr.Size * 8,
        message = available ? "32-bit Jet 4.0 provider is available." : "32-bit Jet 4.0 provider is not installed."
    }));
    return available ? 0 : 3;
}

var pathIndex = Array.FindIndex(args, item => item.Equals("--path", StringComparison.OrdinalIgnoreCase));
if (pathIndex < 0 || pathIndex + 1 >= args.Length)
{
    Console.Error.WriteLine("Usage: GeoSpectrum.LegacyReader --path <temporary-copy.mtd> | --probe");
    return 2;
}

var path = Path.GetFullPath(args[pathIndex + 1]);
if (!File.Exists(path))
{
    Console.Error.WriteLine($"File not found: {path}");
    return 2;
}

var tables = new SortedDictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
await using var connection = new OleDbConnection($"Provider={Provider};Data Source={path};Mode=Read;");
await connection.OpenAsync();
var schema = connection.GetOleDbSchemaTable(OleDbSchemaGuid.Tables, new object?[] { null, null, null, "TABLE" });
if (schema is null) throw new InvalidDataException("Jet did not return table metadata.");

foreach (DataRow tableRow in schema.Rows.Cast<DataRow>().OrderBy(row => row.Field<string>("TABLE_NAME")))
{
    var tableName = tableRow.Field<string>("TABLE_NAME") ?? "";
    if (tableName.StartsWith("MSys", StringComparison.OrdinalIgnoreCase)) continue;
    var rows = new List<Dictionary<string, object?>>();
    await using var command = connection.CreateCommand();
    command.CommandText = $"SELECT * FROM [{tableName.Replace("]", "]]", StringComparison.Ordinal)}]";
    await using var reader = await command.ExecuteReaderAsync(CommandBehavior.SequentialAccess);
    while (await reader.ReadAsync())
    {
        var row = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < reader.FieldCount; index++)
            row[reader.GetName(index)] = Encode(reader.GetValue(index));
        rows.Add(row);
    }
    tables[tableName] = rows;
}

Console.WriteLine(JsonSerializer.Serialize(new
{
    format_version = 1,
    provider = Provider,
    mode = "Read",
    file = Path.GetFileName(path),
    tables
}));
return 0;

static object? Encode(object? value) => value switch
{
    null or DBNull => null,
    DateTime date => date.ToString("O", CultureInfo.InvariantCulture),
    byte[] bytes => new
    {
        kind = "blob",
        byte_length = bytes.Length,
        sha256 = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
        base64 = Convert.ToBase64String(bytes)
    },
    bool or string => value,
    IFormattable number => new { kind = "number", value = number.ToString(null, CultureInfo.InvariantCulture) },
    _ => value.ToString()
};
