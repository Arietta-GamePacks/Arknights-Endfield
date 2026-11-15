@echo off
rem 编译设置模型 provider：单文件 exe 落在包根目录（框架依赖，目标机需 .NET 10 运行时，与宿主同款要求）。
rem 中间产物在 ..\build-out\（包目录保持干净，签名不哈希构建垃圾）。
setlocal
dotnet publish "%~dp0settings-provider.csproj" -c Release -r win-x64 --self-contained false -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true -o "%~dp0" || exit /b 1
echo settings-provider.exe 已更新。
