import {h, icon, mount} from '../../lib/dom.mjs';

const LABELS = {pending: 'Pending', running: 'Running', succeeded: 'Verified', failed: 'Failed', blocked: 'Blocked'};
const CLASSES = {pending: '', running: 'info', succeeded: 'ok', failed: 'error', blocked: 'warn'};

export function renderProgress(container, operations, {planned = false, fault, verified = false, outputs = {}} = {}) {
  mount(container, h('div', {class: 'runner-section-heading'},
    h('h3', {}, 'Workflow'), h('span', {class: `badge ${verified ? 'ok' : ''}`},
      verified ? 'Run verified' : planned ? 'Plan ready' : `${operations.length} operations`)),
  h('p', {class: 'hint'}, planned && !verified
    ? 'Host planning checks inputs and dependencies. Native validation completes during execution.'
    : 'Operation states come from the workflow evidence. Connections show verified artifact and value handoffs.'),
  h('ol', {class: 'runner-diagram', 'aria-label': 'Operation progress'}, operations.map((operation, index) =>
    h('li', {class: `runner-operation ${operation.status}`, 'data-operation': operation.id},
      h('div', {class: 'runner-operation-icon'}, icon(operation.status === 'succeeded' ? 'check' : 'adaptor')),
      h('div', {class: 'runner-operation-content'},
        h('div', {class: 'runner-operation-title'}, h('strong', {}, operation.id),
          h('span', {class: `badge ${CLASSES[operation.status] || ''}`},
            planned && operation.status === 'pending' ? 'Planned' : LABELS[operation.status] || operation.status)),
        h('div', {class: 'hint'}, operation.version || 'Workflow operation'),
        h('div', {class: 'runner-dependencies'}, operation.dependencies.length
          ? operation.dependencies.map((source) => h('span', {class: 'runner-dependency'},
            icon('chevron-right'), `From ${source}`))
          : h('span', {class: 'hint'}, 'Independent input'))),
      h('span', {class: 'runner-order', 'aria-hidden': 'true'}, String(index + 1).padStart(2, '0'))))),
  Object.keys(outputs).length ? h('div', {class: 'runner-expected'},
    h('span', {class: 'section-title'}, 'Expected outputs'),
    h('div', {class: 'runner-expected-list'}, Object.entries(outputs).map(([name, output]) =>
      h('span', {class: 'badge', title: `${output.operation} · artifact ${output.artifact}`},
        `${name} · ${output.kind}`)))) : null,
  fault ? h('div', {class: 'runner-fault', role: 'alert'}, h('strong', {}, fault.code || 'Run failed'),
    h('p', {}, fault.message)) : null);
}
