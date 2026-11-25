"""The fixed child entry point for the trusted launcher.

It reads one length-prefixed LaunchStart frame from stdin, runs the reviewed
built-in adapter for the exact provider and format in the child context, and
writes one bounded ChildResult frame to stdout. It writes nothing else to stdout
and never prints raw values or context to stderr.
"""
from __future__ import annotations

import os
import sys

MAX_FRAME = 4 + 16 * 1024 + 1024 * 1024 + 10 * 1024 * 1024


def run(frame):
    """Return the packed ChildResult frame for one LaunchStart frame."""
    from kurafolio.data_sources import contract_v1 as source
    from kurafolio.ingestion.codec import sha256, validate
    from kurafolio.ingestion.contracts import MAX_MINIMAL, IngestionError
    from kurafolio.ingestion.runner_client import pack_result, unpack_input
    from kurafolio import source_v2
    from kurafolio.source_builtin import registrations

    metadata, context_bytes, raw = unpack_input(frame, schema='LaunchStart')
    primitive = source.load_json(context_bytes, limit=1024 * 1024)
    if primitive.get('payload_kind') != 'parser_v2':
        raise IngestionError('import_evidence_unsupported')
    binding = source.decode(source_v2.ParseContext, primitive['parser_context'])
    matches = [registered.adapter for registered in registrations()
               if metadata['format_version'] in registered.adapter.info.export_versions]
    if len(matches) != 1:
        raise IngestionError('import_evidence_unsupported')
    adapter = matches[0]
    batch = adapter.normalize(raw, export_version=metadata['format_version'],
                              context=binding)
    payload = source_v2.canonical_json(batch).encode()
    if not 0 < len(payload) <= MAX_MINIMAL:
        raise IngestionError('import_limit')
    header = validate({'version': 1, 'job_id': metadata['job_id'],
                       'member_id': metadata['member_id'], 'fence': metadata['fence'],
                       'installation_id': metadata['installation_id'],
                       'image_digest': metadata['image_digest'],
                       'wrapper_profile_digest': metadata['wrapper_profile_digest'],
                       'raw_sha256': metadata['raw_sha256'],
                       'context_sha256': metadata['context_sha256'],
                       'payload_sha256': sha256(payload), 'payload_bytes': len(payload),
                       'payload_kind': 'parser_v2', 'outcome': 'ok'}, 'ChildResult')
    return pack_result(header, payload, child=True)


def main():
    frame = sys.stdin.buffer.read(MAX_FRAME + 1)
    if len(frame) > MAX_FRAME:
        return 2
    try:
        result = run(frame)
    except Exception:
        return 2
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    os._exit(main())
