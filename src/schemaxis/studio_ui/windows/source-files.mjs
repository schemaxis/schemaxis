// Browser-local file selection and export shared by source windows.
import {h} from '../lib/dom.mjs';
import {openDialog} from '../shell/dialog.mjs';

export function downloadText(filename, text) {
  const url = URL.createObjectURL(new Blob([text], {type: /\.ya?ml$/i.test(filename) ? 'application/yaml' : 'application/json'}));
  h('a', {href: url, download: filename}).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function chooseTextFile(accept) {
  return new Promise((resolve) => {
    const input = h('input', {type: 'file', accept, hidden: true});
    const finish = (value) => {
      input.remove();
      resolve(value);
    };
    input.addEventListener('cancel', () => finish(null), {once: true});
    input.addEventListener('change', async () => {
      const file = input.files[0];
      if (!file) return finish(null);
      if (file.size > 1024 * 1024) {
        await openDialog({title: 'File too large', content: h('p', {}, 'Input files may contain at most one MiB.'),
          actions: [{label: 'Close', primary: true, run: () => true}]});
        return finish(null);
      }
      finish({name: file.name, text: await file.text()});
    }, {once: true});
    document.body.append(input);
    input.click();
  });
}

export async function confirmDiscard() {
  return Boolean(await openDialog({title: 'Discard unsaved changes?',
    content: h('p', {}, 'Changes in this editor have not been saved to the workspace.'),
    actions: [{label: 'Keep editing', run: () => null}, {label: 'Discard changes', run: () => true}]}));
}
