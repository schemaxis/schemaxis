// Copyright (C) 2026 David L. F. Gaden.
import {atPointer} from '../../editor/fill-data.mjs';

/** Check host-derived literal collection bounds without editing the document. */
export function assertCollectionCapacity(limit, documentValue, count = 1) {
  if (limit === undefined) return;
  if (!limit || Object.keys(limit).sort().join(',') !== 'maxItems,path'
      || typeof limit.path !== 'string' || !limit.path.startsWith('/') || /[{}]/.test(limit.path)
      || !Number.isSafeInteger(limit.maxItems) || limit.maxItems < 0
      || !Number.isSafeInteger(count) || count < 0) throw Error('Invalid collection limit. Reload the adaptor catalogue.');
  const split = limit.path.lastIndexOf('/');
  const parent = atPointer(documentValue, limit.path.slice(0, split));
  if (!parent || typeof parent !== 'object' || Array.isArray(parent))
    throw Error(`The collection at ${limit.path} is unavailable. Complete its parent before adding an item.`);
  const key = limit.path.slice(split + 1).replaceAll('~1', '/').replaceAll('~0', '~');
  const values = Object.hasOwn(parent, key) ? parent[key] : [];
  if (!Array.isArray(values)) throw Error(`The collection at ${limit.path} must be an array before adding an item.`);
  if (values.length + count > limit.maxItems) {
    const bound = `The collection at ${limit.path} allows at most ${limit.maxItems} item${limit.maxItems === 1 ? '' : 's'}.`;
    if (count === 0)
      throw Error(`${bound} This input already contains ${values.length}; correct its item count in the input before applying settings. No items have been removed.`);
    const recovery = limit.maxItems === 1 && values.length === 1
      ? "Open the existing item's Edit settings instead; Add will not replace it."
      : 'Reduce the collection count in the input before adding more items. Add will not replace existing items.';
    throw Error(`${bound} ${recovery}`);
  }
}

/** Recheck the actual insertion immediately before the editor transaction. */
export function assertInsertionCapacity(configured, documentValue) {
  if (configured.collectionLimit === undefined) return;
  const count = configured.inserts.filter(entry => entry.at === configured.collectionLimit.path + '/-')
    .reduce((total, entry) => total + entry.values.length, 0);
  assertCollectionCapacity(configured.collectionLimit, documentValue, count);
}
