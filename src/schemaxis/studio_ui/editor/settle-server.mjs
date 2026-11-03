// Copyright (C) 2026 David L F Gaden
// Background validation stays local to the editor: no typing toasts or Problems entries.
export function backgroundValidation(editor, validate, {delay = 1000} = {}) {
  let timer;
  let disposed = false;
  let version = -1;
  let due = 0;
  let sent = -1;
  const unsubscribe = editor.onSettledState((state) => {
    if (state.version !== version) {
      version = state.version;
      due = Date.now() + delay;
      clearTimeout(timer);
    }
    if (!state.canValidate || sent === version) return;
    clearTimeout(timer);
    const requested = version;
    timer = setTimeout(async () => {
      if (disposed || requested !== editor.getTextVersion() || !editor.getSettledState().canValidate) return;
      sent = requested;
      const source = editor.getValue();
      try {
        const diagnostics = await validate(source);
        if (!disposed && diagnostics) editor.setDiagnostics(diagnostics, {version: requested, explicit: false});
      } catch (error) {
        if (!disposed) {
          editor.setDiagnostics([{...(error.fault || error), message: error.message, source: 'server'}],
            {version: requested, explicit: false});
        }
      }
    }, Math.max(0, due - Date.now()));
  });
  return () => {
    disposed = true;
    clearTimeout(timer);
    unsubscribe();
  };
}

export function reportDiagnostics(ctx, editor, {title = 'Input needs attention', document, show = () => {}} = {}) {
  const diagnostics = editor.flushDiagnostics();
  const version = editor.getTextVersion();
  if (diagnostics.length) {
    ctx.notify.group(diagnostics, {title, source: {document}, actions: (item) => [{label: 'Show in input', run: () => {
      const target = [...(ctx.windows?.instances?.values() || [])]
        .find((instance) => instance.element.contains(editor.element));
      if (target) ctx.windows.activate(target.key);
      show();
      if (version === editor.getTextVersion() || !editor.revealPointer(item.pointer || '')) {
        editor.revealOffset(item.from, item.to);
      }
    }}]});
  }
  return diagnostics;
}
