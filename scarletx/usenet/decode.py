from __future__ import annotations

from . import worker as _worker

decode_yenc_native = _worker.decode_yenc_native
decode_yenc_to_file = _worker.decode_yenc_to_file
decode_yenc_to_target = _worker.decode_yenc_to_target
DecodedSegment = _worker.DecodedSegment

__all__ = ('decode_yenc_native', 'decode_yenc_to_file', 'decode_yenc_to_target', 'DecodedSegment')
