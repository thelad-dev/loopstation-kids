; Rubber Band (GPL) is NOT part of the installer. If the user ticks the task
; "Rubber Band (GPL) herunterladen", setup downloads this wheel (pylibrb, the
; Python binding with the library built in), checks its SHA-256 and unpacks it to
; {app}\rubberband. The app finds it there (loopstation/audio/stretch.py).
;
; Source: PyPI, pylibrb 0.1.2, cp311 (the Python of the bundle) for Windows x64.
; To change the version: take url, size and sha256 from
; https://pypi.org/pypi/pylibrb/<version>/json and update all values here.
; tests/test_rubberband_installer.py checks the shape of these values.
; The /D overrides exist so the CI can prove the failure path (wrong hash).

#ifndef RubberBandUrl
  #define RubberBandUrl "https://files.pythonhosted.org/packages/03/5f/5a2858df85e4dc9095c38dd4d97b76f1706e10334c7e57c967c2baf74325/pylibrb-0.1.2-cp311-cp311-win_amd64.whl"
#endif
#ifndef RubberBandSha256
  #define RubberBandSha256 "0815af8a5e8ad2c10f85f70fa5906943ac8f70b823f4e40c9e80d70c292399f9"
#endif
#define RubberBandVersion "0.1.2"
#define RubberBandSize "1,9 MB"
