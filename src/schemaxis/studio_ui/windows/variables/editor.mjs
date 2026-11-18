// Copyright (C) 2026 David L. F. Gaden.
import {chooseValue} from './panel.mjs';
import {ownerAt} from './model.mjs';
import {replacing} from '../../editor/fill-data.mjs';
import {escapeSegment} from '../../editor/json-pointer.mjs';
import {spatialAction, spatialRequest} from '../spatial/host.mjs';

/** Connect the same picker to saved editors, dirty drafts and repeated fill markers. */
export function bindVariables(ctx, editor, {snapshot, changed = () => {}, label = 'Current document · edits remain in this draft until saved.'} = {}) {
  const local = async () => {
    const version = editor.getTextVersion(), root = editor.getDocument();
    return {root, label, revision: version, commit: async value => {
      if (editor.getTextVersion() !== version) throw Error('The input changed while the value picker was open. Reopen it to use the current draft.');
      editor.replaceDocument(value); changed();
    }};
  };
  const context = snapshot || local;
  const pick = async ({pointer = editor.getCursor().pointer, pointers = [pointer]} = {}) => ctx.call(async () => {
    const owner = await context();
    const result = await chooseValue(ctx, {root: owner.root, pointer: (owner.base || '') + pointer,
      pointers: pointers.map(p => (owner.base || '') + p)});
    if (result) await owner.commit(result.document);
  }, {title: 'Could not set the value'});
  editor.setOption('checkSpatialValue', async ({value, pointers, axis}) => {
    const owner = await context(), base = owner.base || '';
    let root = owner.root;
    for (const pointer of pointers) root = replacing(root, base + pointer, value);
    if (axis) {
      const scope = ownerAt(root, base + pointers[0]);
      let target = root;
      for (const segment of scope.base.split('/').slice(1)) target = target[segment.replaceAll('~1', '/').replaceAll('~0', '~')];
      root = replacing(root, scope.base + '/sweeps', [...(target.sweeps || []), axis]);
    }
    async function check(value, pointer) {
      if (typeof value?.$expr === 'string') {
        const scope = ownerAt(root, pointer);
        return spatialAction(ctx.api, 'spatial_check', spatialRequest(root, scope.base, undefined,
          {expression: value.$expr, destination: pointer.slice(scope.base.length)}));
      }
      if (value && typeof value === 'object') {
        for (const [key, child] of Object.entries(value)) {
          const result = await check(child, pointer + '/' + escapeSegment(key));
          if (!result.ok) return result;
        }
      }
      return {ok: true};
    }
    for (const pointer of pointers) {
      const result = await check(value, base + pointer);
      if (!result.ok) return result;
    }
    return {ok: true};
  });
  editor.setOption('chooseValue', pick);
  editor.setOption('variablesContext', context);
  return {context, pick};
}
