// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {searchAdaptors, searchAdd} from '../lib/search.mjs';
import {searchTopics, contextTopic} from '../windows/help/model.mjs';

const root = fileURLToPath(new URL('../../../..', import.meta.url));
const script = `
import json, tempfile
from schemaxis.capabilities import CapabilityCatalogue
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.studio_server import StudioApplication
c = CapabilityCatalogue()
providers = [p for p in c._metadata if c._metadata[p].get('searchCases')]
with tempfile.TemporaryDirectory() as tmp:
    session = AdaptorConsoleSession(tmp, provider='workflow-design')
    app = StudioApplication(session)
    try:
        print(json.dumps({'adaptors': app.adaptors()['adaptors'], 'providers': {
            p: {'cases': c._metadata[p]['searchCases'], 'add': app.studio_adaptor(p)['addCatalogue']['items']}
            for p in providers}}))
    finally:
        app.close()
        session.close()
`;
const run = spawnSync(process.env.STUDIO_PYTHON || 'python3', ['-c', script], {
  cwd: root, env: {...process.env, PYTHONPATH: `${root}/src`}, encoding: 'utf8', timeout: 60000,
  maxBuffer: 16 * 1024 * 1024,
});
assert.equal(run.status, 0, run.stderr);
const data = JSON.parse(run.stdout);
const index = JSON.parse(readFileSync(new URL('../help/index.json', import.meta.url)));

for (const [provider, material] of Object.entries(data.providers)) {
  for (const c of material.cases.filter(c => c.status === 'reviewed')) {
    test(`${provider}: ${c.kind} phrase ${JSON.stringify(c.query)} on production Studio surfaces`, () => {
      const observed = {
        adaptor: searchAdaptors(data.adaptors, c.query).map(i => `app/${i.id}`),
        add: searchAdd(material.add, c.query).map(i => i.capabilityId).filter(Boolean),
        help: searchTopics(index.entries, c.query).map(i => i.capabilityId).filter(Boolean),
      };
      for (const surface of ['adaptor', 'add', 'help']) {
        if (!c.expected[surface]) continue;
        for (const id of c.expected[surface]) assert.ok(observed[surface].includes(id), `${surface} missing ${id}`);
        for (const id of c.excluded?.[surface] || []) assert.ok(!observed[surface].includes(id), `${surface} misleading ${id}`);
      }
    });
  }
  test(`${provider}: every Add operation resolves its own packaged contextual Help`, () => {
    for (const item of material.add.filter(i => i.operation)) {
      const topic = contextTopic(index, {provider, operation: item.operation});
      assert.equal(topic.capabilityId, item.capabilityId);
      assert.equal(topic.operation, item.operation);
      assert.ok(readFileSync(new URL(`../help/${topic.id}.json`, import.meta.url)).length);
    }
  });
}

test('Add title ordering and contiguous phrase matching remain explicit', () => {
  const items = [{title:'mesh detail'}, {title:'mesh'}, {title:'volume mesh'}, {title:'volume other mesh'}];
  assert.deepEqual(searchAdd(items, 'mesh').map(i => i.title), ['mesh','mesh detail','volume mesh','volume other mesh']);
  assert.deepEqual(searchAdd(items, 'volume mesh').map(i => i.title), ['volume mesh']);
});
