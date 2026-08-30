# ScarletX 0.3.5 Local

## Post-processing reliability hotfix

- Direct playable video posts now bypass unnecessary PAR2 verification and archive extraction.
- PAR2 metadata recovery reads only the small base PAR2 metadata region instead of loading every recovery volume into memory.
- FFprobe fallback is bounded to the largest unresolved payloads instead of probing every hash-named support file serially.
- PAR2 verification is capped at 3 minutes; PAR2 repair and archive extraction are capped at 10 minutes each.
- Active repair/extract tools are terminated immediately when Cancel is pressed.
- Activity now shows the current post-processing stage and keeps Cancel available during post-processing.
- Interrupted `postprocessing` jobs are re-queued on restart and reuse already downloaded segment files.
- A healthy direct video is promoted immediately to the completed/import path rather than spending minutes re-validating PAR2 support data.
