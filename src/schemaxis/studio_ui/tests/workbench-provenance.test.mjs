import assert from 'node:assert/strict';
import {test} from 'node:test';
import {sha256, staleReason, verifiedArtifact} from '../windows/workbench/provenance.mjs';

test('output reads compare actual bytes with the retained receipt before returning data', async () => {
  const bytes = new TextEncoder().encode('verified output\n');
  const digest = await sha256(bytes);
  const api = {url: () => 'data:text/plain,verified%20output%0A'};
  const artifact = {file: 'result.txt', sha256: digest};
  assert.equal((await verifiedArtifact(api, artifact)).digest, digest);
  await assert.rejects(verifiedArtifact({url: () => 'data:text/plain,tampered'}, artifact),
    (error) => error.code === 'VERIFICATION_FAILED');
  await assert.rejects(verifiedArtifact(api, {file: 'result.txt'}),
    (error) => error.code === 'VERIFICATION_FAILED');
});

test('reference status compares captured revisions and refreshed content digests', () => {
  const reference = {origin: 'native', document: 'a', revision: 8, digest: 'original', resource: 'native:a:image'};
  const record = {id: 'a', revision: 8};
  assert.equal(staleReason(reference, record, new Map()), '');
  assert.match(staleReason(reference, {...record, revision: 9}, new Map()), /authored input changed/);
  assert.match(staleReason(reference, {id: 'b', revision: 8}, new Map()), /authored input changed/);
  assert.match(staleReason(reference, record, new Map([[reference.resource, 'changed']])), /content changed/);
  const sample = {...reference, origin: 'sample'};
  assert.equal(staleReason(sample, {id: 'b', revision: 9}, new Map()), '');
});
