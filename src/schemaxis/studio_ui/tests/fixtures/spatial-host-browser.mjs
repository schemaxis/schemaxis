// Copyright (C) 2026 David L. F. Gaden.
import {readFile} from 'node:fs/promises';

// Production Studio deliberately does not serve tests. Inject only the fixture.
const source = (await readFile(new URL('./spatial-host.mjs', import.meta.url), 'utf8'))
  .replace("import {entries, preview, ownerAt} from '../../windows/variables/model.mjs';", "const {entries, preview, ownerAt} = await import('/windows/variables/model.mjs');")
  .replace("import {literalSpatial} from '../../windows/spatial/model.mjs';", "const {literalSpatial} = await import('/windows/spatial/model.mjs');")
  .replace('export function installSpatialHost', 'function installSpatialHost');
export async function stubSpatialHost(session, options = {}) {
  await session.evaluate(`(async () => { ${source}\n window.hostFixture = installSpatialHost(studio.api, ${JSON.stringify(options)}); })()`);
}
