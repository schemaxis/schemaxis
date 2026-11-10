import {chooseValue} from './panel.mjs';

/** Connect the same picker to saved editors, dirty drafts and repeated fill markers. */
export function bindVariables(ctx, editor, {snapshot, changed = () => {}, label = 'Current document · edits remain in this draft until saved.'} = {}) {
  const local = async () => {
    const version = editor.getTextVersion(), root = editor.getDocument();
    return {root, label, commit: async value => {
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
  editor.setOption('chooseValue', pick);
  editor.setOption('variablesContext', context);
  return {context, pick};
}
