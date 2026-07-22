# Inference Latency Benchmark Report

**Date**: 2026-07-20 13:04:24
**System**: Darwin arm64

---

## Gas Inference (XGBoost + IsoForest)

> Skipped: Failed to load or initialize gas pipeline: 
XGBoost Library (libxgboost.dylib) could not be loaded.
Likely causes:
  * OpenMP runtime is not installed
    - vcomp140.dll or libgomp-1.dll for Windows
    - libomp.dylib for Mac OSX
    - libgomp.so for Linux and other UNIX-like OSes
    Mac OSX users: Run `brew install libomp` to install OpenMP runtime.

  * You are running 32-bit Python on a 64-bit OS

Error message(s): ["dlopen(/Users/tarunkumar/Library/Python/3.9/lib/python/site-packages/xgboost/lib/libxgboost.dylib, 0x0006): Library not loaded: @rpath/libomp.dylib\n  Referenced from: <89AD948E-E564-3266-867D-7AF89D6488F0> /Users/tarunkumar/Library/Python/3.9/lib/python/site-packages/xgboost/lib/libxgboost.dylib\n  Reason: tried: '/opt/homebrew/opt/libomp/lib/libomp.dylib' (no such file), '/System/Volumes/Preboot/Cryptexes/OS/opt/homebrew/opt/libomp/lib/libomp.dylib' (no such file), '/opt/homebrew/opt/libomp/lib/libomp.dylib' (no such file), '/System/Volumes/Preboot/Cryptexes/OS/opt/homebrew/opt/libomp/lib/libomp.dylib' (no such file)"]


---

## YOLO Detection (YOLOv8-nano)

| Resolution | Frames | p50 (ms) | p95 (ms) | p99 (ms) | FPS |
|---|---|---|---|---|---|
| 640x480 | 30 | 38.4 | 57.0 | 91.25 | 23.9 |
| 1280x720 | 30 | 30.43 | 31.6 | 31.75 | 32.9 |

---

## YOLO + ByteTrack Tracking

| Metric | Value |
|---|---|
| Resolution | 640x480 |
| Frames | 30 |
| p50 | 37.94 ms |
| p95 | 39.1 ms |
| p99 | 40.61 ms |
| FPS | 26.3 |

---

## Multi-Camera Throughput Estimate

| Metric | Value |
|---|---|
| Target FPS | 15 |
| Single Frame | 37.94 ms |
| Frame Budget | 66.67 ms |
| Max Cameras (sequential) | 1 |

> With async/threaded processing, effective count is higher
