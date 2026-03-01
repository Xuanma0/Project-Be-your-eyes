# Android Build Runner (Quest3)

## One-command build

From repo root (or double-click in Explorer):

```bat
tools\unity\build_quest3_android.cmd
```

## Unity executable resolution

The script resolves `Unity.exe` in this order:

1. `UNITY_EXE` environment variable
2. `D:\6000.3.10f1\Editor\Unity.exe`
3. `C:\Program Files\Unity\Hub\Editor\6000.3.10f1\Editor\Unity.exe`
4. `D:\Unity\Editor\Unity.exe`

If not found, the script exits with code `2` and prints how to set `UNITY_EXE`.

The script also verifies `Data/PlaybackEngines/AndroidPlayer` exists under the selected editor.
If missing, install Android Build Support (SDK/NDK/OpenJDK) for that editor and rerun.

## Output

- APK: `Builds/Quest3/BYES_Quest3Smoke_<VERSION>.apk`
- Build log: `Builds/logs/unity_build_quest3_android_v4.99.log`
- Summary: `Builds/logs/unity_build_quest3_android_v4.99.summary.txt`

## VERSION file compatibility

On Windows + IL2CPP, the root `VERSION` file can shadow the C++ `<version>` header during Android compile.
The script temporarily renames `VERSION` before Unity build and restores it immediately after build.

## Log parsing

After Unity batch build, `tools/unity/parse_unity_build_log.py` runs automatically and extracts:

- earliest true error line (`error CS*`, `fatal error:`, `ld.lld:`, `undefined symbol/reference`, `BuildFailedException`)
- ±80 lines context around root cause
- Bee Android failure counts

If summary says root cause not found, open Unity `Editor.log` for full diagnostics.
