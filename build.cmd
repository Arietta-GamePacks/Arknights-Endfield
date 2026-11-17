@echo off
rem Build the settings-model provider: single-file, framework-dependent (.NET 10 required).
rem Intermediate output goes to ..\build-out\ so the pack folder stays clean for signing.
setlocal
dotnet publish "%~dp0settings-provider.csproj" -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -o "%~dp0" || exit /b 1
echo settings-provider.exe updated.
