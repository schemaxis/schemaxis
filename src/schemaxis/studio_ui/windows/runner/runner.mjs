// Copyright (C) 2026 David L F Gaden
// Case Runner: values-only authoring over the shared template and workflow APIs.
import {h, icon, mount} from '../../lib/dom.mjs';
import {Store} from '../../lib/store.mjs';
import {confirmDialog} from '../../shell/dialog.mjs';
import {ApiError} from '../../lib/api.mjs';
import {collectValues, parameterField} from './parameters.mjs';
import {renderProgress} from './progress.mjs';
import {createResultsFrame} from '../results.mjs';

export const runnerWindow = {
  type: 'runner',
  title: 'Case Runner',
  icon: 'play',
  singleton: true,
  create(ctx, params = {}) {
    const state = new Store({template: null, values: null, plan: null, job: null, snapshot: null, busy: false,
      dirty: false, savedFilename: null, caseDigest: null});
    let disposed = false;
    let pollTimer = null;
    let outputsKey = null;
    const templatePath = h('input', {class: 'input', placeholder: 'Template directory or template.json',
      'aria-label': 'Template directory', value: params.path || ''});
    const casePath = h('input', {class: 'input', placeholder: 'cases/my-case.json', 'aria-label': 'Case file path'});
    const form = h('form', {class: 'runner-form', onSubmit: (event) => event.preventDefault()});
    const parameterFields = h('div', {class: 'runner-fields'});
    const outputDirectory = h('input', {class: 'input', name: 'outputDirectory',
      placeholder: 'Automatic: runs/case-…', 'aria-label': 'Output directory'});
    const workers = h('input', {class: 'input', type: 'number', min: 1, max: 64, step: 1,
      value: String(ctx.setting('execution.workers') || 1), 'aria-label': 'Parallel workers'});
    const namingPattern = h('input', {class: 'input',
      placeholder: ctx.setting('output.namingPattern') || '{index}-{operation}-{output}{ext}',
      'aria-label': 'Output naming pattern'});
    const namingWidth = h('input', {class: 'input', type: 'number', min: 1, max: 12, step: 1,
      placeholder: String(ctx.setting('output.indexWidth') || 6), 'aria-label': 'Output index width'});
    const bodyFields = h('fieldset', {class: 'runner-fieldset', disabled: true}, parameterFields,
      h('section', {class: 'runner-options'}, h('h3', {}, 'Run options'),
        field('Output directory', outputDirectory, 'Relative paths are inside the Studio workspace.'),
        field('Parallel workers', workers, 'The workflow scheduler honours application resource limits.'),
        h('details', {}, h('summary', {}, 'Output naming'),
          field('Naming pattern', namingPattern, 'Leave blank to use the Studio default.'),
          field('Index digits', namingWidth, 'Leave blank to use the managed default.'))));
    form.append(bodyFields);
    const title = h('strong', {}, 'Case Runner');
    const subtitle = h('span', {class: 'hint'}, 'Choose a workflow template to begin');
    const status = h('span', {class: 'badge'}, 'No template');
    const diagram = h('section', {class: 'runner-flow'});
    const planDetails = h('details', {class: 'runner-plan-details'});
    const outputList = h('div', {class: 'runner-output-list'});
    const viewerHost = h('div', {class: 'runner-output-browser'});
    let resultsViewer = null;
    const outputsPanel = h('section', {class: 'runner-outputs', hidden: true},
      h('div', {class: 'runner-section-heading'}, h('h3', {}, 'Outputs'),
        h('span', {class: 'hint'}, 'All run files · local collection viewer')), outputList, viewerHost);
    const inspectButton = button('Inspect template', 'folder', () => inspect());
    const loadButton = button('Load case', 'folder', () => load());
    const saveButton = button('Save case', 'file', () => save());
    const planButton = button('Plan', 'flow', () => prepare('plan'));
    const runButton = button('Run', 'play', () => prepare('run'), 'primary');
    const cancelButton = button('Cancel run', 'close', () => cancel());
    cancelButton.hidden = true;

    async function action(titleText, work) {
      if (state.get().busy) {
        return;
      }
      state.set({busy: true});
      try {
        return await work();
      } catch (error) {
        ctx.notify.error(error, {title: titleText});
        return undefined;
      } finally {
        if (!disposed) {
          state.set({busy: false});
        }
      }
    }

    function caseValues() {
      if (!form.reportValidity()) {
        throw new ApiError({code: 'INVALID_CASE', message: 'Correct the highlighted field before continuing.'});
      }
      const current = state.get();
      const values = collectValues(form, current.template.template, current.template.identity);
      const run = {workers: Number(workers.value)};
      if (outputDirectory.value.trim()) {
        run.outputDirectory = outputDirectory.value.trim();
      }
      if (namingPattern.value || namingWidth.value) {
        run.naming = {};
        if (namingPattern.value) {
          run.naming.pattern = namingPattern.value;
        }
        if (namingWidth.value) {
          run.naming.indexWidth = Number(namingWidth.value);
        }
      }
      return {...values, run};
    }

    function inspect() {
      return action('Cannot inspect template', async () => {
        if (!(await discardChanges())) return;
        const result = await ctx.api.post('/api/cases', {action: 'inspect_template', path: templatePath.value});
        if (disposed) {
          return;
        }
        state.set({template: result, values: result.values, plan: null, job: null, snapshot: null,
          dirty: false, savedFilename: null, caseDigest: null});
        templatePath.value = result.path;
        templatePath.title = result.path;
        // Long absolute paths: show the end (bundle and file), which identifies the template.
        requestAnimationFrame(() => {
          templatePath.scrollLeft = templatePath.scrollWidth;
        });
        casePath.value = `cases/${result.template.id}.json`;
      });
    }

    function load() {
      return action('Cannot load case', async () => {
        if (!(await discardChanges())) return;
        const result = await ctx.api.post('/api/cases', {action: 'load', path: state.get().template.path,
          filename: casePath.value});
        if (!disposed) {
          state.set({values: result.values, plan: result.bound, job: null, snapshot: null, dirty: false,
            savedFilename: result.filename, caseDigest: result.caseDigest});
          casePath.value = result.filename;
          ctx.notify.ok('Case loaded', {body: result.filename});
        }
      });
    }

    function save() {
      return action('Cannot save case', async () => {
        const result = await ctx.api.post('/api/cases', {action: 'save', path: state.get().template.path,
          filename: casePath.value, values: caseValues(),
          caseDigest: casePath.value === state.get().savedFilename ? state.get().caseDigest : undefined});
        if (!disposed) {
          casePath.value = result.filename;
          state.set({dirty: false, savedFilename: result.filename, caseDigest: result.caseDigest});
          ctx.notify.ok('Case saved', {body: result.filename});
        }
      });
    }

    function prepare(kind) {
      return action(kind === 'run' ? 'Cannot start case' : 'Cannot plan case', async () => {
        const result = await ctx.api.post('/api/cases', {action: kind, path: state.get().template.path,
          values: caseValues()});
        if (disposed) {
          return;
        }
        if (kind === 'plan') {
          state.set({plan: result, snapshot: null, job: null});
          ctx.notify.ok('Plan ready', {body: `${result.operations.length} operations checked without launching apps.`});
        } else {
          state.set({job: result.job, snapshot: {status: 'running', directory: result.directory,
            operations: state.get().template.operations}});
          ctx.store.set({panelOpen: true, panelTab: 'jobs'});
          ctx.refresh();
          await poll(result.job);
        }
      });
    }

    async function poll(job) {
      if (disposed || state.get().job !== job) {
        return;
      }
      try {
        const snapshot = await ctx.api.get(`/api/jobs/${encodeURIComponent(job)}`);
        if (disposed || state.get().job !== job) {
          return;
        }
        if (snapshot.status === 'succeeded') {
          try {
            snapshot.result = await ctx.api.post('/api/cases', {action: 'outputs', job});
          } catch (error) {
            ctx.notify.error(error, {title: 'Cannot verify case outputs'});
            state.set({snapshot: {...snapshot, status: 'failed', verified: false, result: null,
              fault: error.fault || {message: error.message}}});
            return;
          }
        }
        state.set({snapshot});
        if (snapshot.status === 'running') {
          pollTimer = setTimeout(() => poll(job), 650);
        } else if (snapshot.status === 'succeeded') {
          if (snapshot.result?.namingFault) {
            ctx.notify.error(snapshot.result.namingFault, {title: 'Run verified; output naming failed'});
          }
          ctx.notify.ok('Case verified', {body: `${snapshot.result?.outputs?.length || 0} outputs are ready.`});
          ctx.refresh();
        } else {
          ctx.notify.error(snapshot.fault || {message: 'The case job is no longer available.'},
            {title: 'Case did not complete'});
          ctx.refresh();
        }
      } catch (error) {
        if (!disposed) {
          ctx.notify.error(error, {title: 'Cannot refresh case progress'});
          pollTimer = setTimeout(() => poll(job), 3000);
        }
      }
    }

    function cancel() {
      return action('Cannot cancel run', async () => {
        await ctx.api.post('/api/cancel', {job: state.get().job});
        ctx.notify.info('Cancellation requested', {body: 'Waiting for the application to stop safely.'});
      });
    }

    function renderParameters(current) {
      const template = current.template?.template;
      mount(parameterFields, template ? [h('h3', {}, 'Parameters'),
        ...Object.entries(template.parameters).map(([id, spec]) => parameterField(id, spec,
          Object.hasOwn(current.values.values, id) ? current.values.values[id] : spec.default)),
        !Object.keys(template.parameters).length ? h('p', {class: 'hint'}, 'This template has no parameters.') : null]
        : h('div', {class: 'empty-state'}, icon('gear'), h('h3', {}, 'Case parameters'),
          h('p', {}, 'Template parameters and their constraints appear here.')));
      const run = current.values?.run || {};
      outputDirectory.value = run.outputDirectory || '';
      workers.value = String(run.workers || ctx.setting('execution.workers') || 1);
      namingPattern.value = run.naming?.pattern || '';
      namingWidth.value = run.naming?.indexWidth || '';
    }

    function render(current, previous) {
      const running = current.snapshot?.status === 'running';
      const disabled = current.busy || running;
      inspectButton.disabled = disabled;
      templatePath.disabled = disabled;
      bodyFields.disabled = !current.template || disabled;
      for (const control of [loadButton, saveButton, planButton, runButton, casePath]) {
        control.disabled = !current.template || disabled;
      }
      cancelButton.hidden = !running;
      cancelButton.disabled = current.busy;
      if (current.template !== previous?.template || current.values !== previous?.values) {
        renderParameters(current);
      }
      title.textContent = current.template?.template.title || 'Case Runner';
      subtitle.textContent = current.template
        ? `${current.template.template.id} · revision ${current.template.template.revision}`
        : 'Choose a workflow template to begin';
      const verified = current.snapshot?.verified === true;
      status.className = `badge ${verified ? 'ok' : running ? 'info' : ''}`;
      status.textContent = current.busy ? 'Working…' : running ? 'Running' : verified ? 'Verified'
        : current.snapshot?.status === 'failed' ? 'Failed' : current.plan ? 'Planned'
          : current.template ? 'Ready' : 'No template';
      if (current.template) {
        renderProgress(diagram, current.snapshot?.operations || current.plan?.operations || current.template.operations,
          {planned: !!current.plan, verified, fault: current.snapshot?.fault,
            outputs: current.template.template.outputs});
      } else {
        mount(diagram, h('div', {class: 'empty-state runner-welcome'}, icon('play'),
          h('h2', {}, 'Run a workflow, one case at a time'),
          h('p', {}, 'Inspect a template bundle, enter its parameters, then plan and run it.'),
          h('p', {class: 'hint'}, 'A case file records your values and run options for repeatable results.')));
      }
      planDetails.hidden = !current.plan;
      if (current.plan !== previous?.plan) {
        mount(planDetails, h('summary', {}, 'Plan details'),
          h('pre', {}, JSON.stringify(current.plan?.plan, null, 2)));
      }
      const outputs = current.snapshot?.result?.outputs;
      outputsPanel.hidden = !outputs;
      if (outputs !== outputsKey) {
        outputsKey = outputs;
        resultsViewer?.dispose();
        resultsViewer = null;
        mount(viewerHost);
        mount(outputList, outputs ? h('button', {class: 'button small', onClick: () => ctx.openResults?.({collection: 'job-' + current.job})}, 'Open in Results') : null);
        if (outputs) {
          resultsViewer = createResultsFrame(ctx, 'job-' + current.job);
          viewerHost.append(resultsViewer.element);
        }
      }
    }

    form.addEventListener('input', () => {
      state.set({plan: null, snapshot: null, job: null, dirty: true});
    });
    const discardChanges = () => !state.get().dirty || confirmDialog('Discard unsaved case?',
      'These parameter values and run options have not been saved to a case file.', {confirm: 'Discard'});
    templatePath.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        inspect();
      }
    });
    const unsubscribe = state.subscribe(render);
    render(state.get());
    const element = h('div', {class: 'window-body runner'},
      h('header', {class: 'window-header'}, h('div', {class: 'runner-header-mark'}, icon('play')),
        h('div', {class: 'runner-heading'}, title, subtitle), status,
        h('div', {class: 'actions'}, planButton, runButton, cancelButton)),
      h('div', {class: 'runner-template-bar'}, templatePath, inspectButton),
      h('div', {class: 'runner-main'}, h('aside', {class: 'runner-sidebar'},
        h('section', {class: 'runner-case-file'}, h('h3', {}, 'Case file'), casePath,
          h('div', {class: 'runner-case-actions'}, loadButton, saveButton),
          h('p', {class: 'hint'}, 'Save inside the Studio workspace.')), form),
      h('main', {class: 'runner-results'}, diagram, planDetails, outputsPanel)));
    element.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && state.get().template) {
        event.preventDefault();
        event.stopPropagation();
        save();
      }
    });
    if (params.path) {
      inspect();
    }
    return {element, isDirty: () => state.get().dirty, canClose: discardChanges, dispose() {
      disposed = true;
      clearTimeout(pollTimer);
      unsubscribe();
      resultsViewer?.dispose();
    }};
  },
};

function button(label, iconName, action, extra = '') {
  return h('button', {class: `button ${extra}`, type: 'button', onClick: action}, icon(iconName), label);
}

function field(label, input, help) {
  return h('div', {class: 'field'}, h('label', {}, label), input, h('div', {class: 'hint'}, help));
}
