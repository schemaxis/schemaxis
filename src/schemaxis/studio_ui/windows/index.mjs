// Registry of Studio window types.

import {startWindow} from './start.mjs';
import {settingsWindow} from './settings.mjs';
import {designerWindow} from './designer/designer.mjs';
import {workbenchWindow} from './workbench/workbench.mjs';
import {runnerWindow} from './runner/runner.mjs';
import {schemaEditorWindow} from './schema-editor.mjs';
import {installDocumentActions} from './documents.mjs';
import {helpWindow} from './help/help.mjs';
import {setupWindow} from './setup.mjs';
import {schedulesWindow} from './schedules.mjs';

export function registerWindows(ctx) {
  for (const type of [startWindow, settingsWindow, designerWindow, workbenchWindow, runnerWindow,
    schemaEditorWindow, setupWindow, schedulesWindow, helpWindow]) {
    ctx.windows.register(type);
  }
  installDocumentActions(ctx);
}
