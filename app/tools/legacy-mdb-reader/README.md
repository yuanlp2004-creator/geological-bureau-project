# GeoSpectrum legacy Access reader

This process is intentionally isolated from the FastAPI runtime. It is built as
`win-x86` because SpecDirect method libraries require the 32-bit Jet 4.0
provider. FastAPI always invokes it against an operating-system temporary copy;
the original `.MTD` file is never opened by Jet.

Build on Windows with the .NET 8 SDK:

```powershell
dotnet publish .\GeoSpectrum.LegacyReader.csproj -c Release -r win-x86
```

`read_access.ps1` is the source-equivalent 32-bit Windows PowerShell fallback
used by development and acceptance environments where the .NET SDK or an x86
.NET runtime is not installed. Both readers emit the same versioned JSON
contract and preserve BLOB length, SHA-256 and base64 bytes.
