// Copyright (C) 2026 David L F Gaden
// A reference names the bytes and authored revision loaded into its viewer.
import {ApiError} from '../../lib/api.mjs';

export async function sha256(bytes) {
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash), (value) => value.toString(16).padStart(2, '0')).join('');
}

export async function verifiedArtifact(api, artifact, signal) {
  const response = await fetch(api.url('/api/file', {path: artifact.file, sha256: artifact.sha256}),
    {signal, cache: 'no-store', referrerPolicy: 'no-referrer'});
  if (!response.ok) {
    let fault;
    try { fault = (await response.json()).fault; } catch { /* Preserve useful HTTP failures. */ }
    throw new ApiError(fault || {code: 'FILE_READ_FAILED', message: `Cannot read output (HTTP ${response.status}).`});
  }
  const bytes = await response.arrayBuffer();
  const digest = await sha256(bytes);
  if (!artifact.sha256 || digest !== artifact.sha256) {
    throw new ApiError({code: 'VERIFICATION_FAILED', message: 'This output changed after verification. Run it again.'});
  }
  return {bytes, digest, contentType: response.headers.get('Content-Type')};
}

export function staleReason(reference, record, digests) {
  if (reference.origin !== 'sample' && reference.document
      && (reference.document !== record?.id || reference.revision !== record?.revision)) {
    return 'The authored input changed after this reference was captured.';
  }
  if (reference.resource && reference.digest && digests.has(reference.resource)
      && digests.get(reference.resource) !== reference.digest) {
    return 'The loaded content changed after this reference was captured.';
  }
  return '';
}
