; Rubber Band (GPL) is NOT part of the installer. If the user ticks the task
; "Rubber Band (GPL) herunterladen", setup downloads this wheel (pylibrb, the
; Python binding with the library built in), checks its SHA-256 and unpacks it to
; {app}\rubberband. The app finds it there (loopstation/audio/stretch.py).
;
; Source: PyPI, pylibrb 0.1.2, cp312-abi3 (the bundle runs Python 3.12) for Windows x64.
; To change the version: take url, size and sha256 from
; https://pypi.org/pypi/pylibrb/<version>/json and update all values here.
; tests/test_rubberband_installer.py checks the shape of these values.
; The /D overrides exist so the CI can prove the failure path (wrong hash).

#ifndef RubberBandUrl
  #define RubberBandUrl "https://files.pythonhosted.org/packages/f8/e0/5cbac14c76f8e3cf151c2b6444fe340eeaf9f3097016a5ad205bbc4e753f/pylibrb-0.1.2-cp312-abi3-win_amd64.whl"
#endif
#ifndef RubberBandSha256
  #define RubberBandSha256 "8ab810bd58581da194b4c4bfb8883033dc122a63842ba8d27e2faad084761fe6"
#endif
#define RubberBandVersion "0.1.2"
#define RubberBandSize "1,9 MB"
