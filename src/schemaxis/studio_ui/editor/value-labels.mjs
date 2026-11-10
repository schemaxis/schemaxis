// User-facing names; the JSON spelling remains available for source authors.
export const VALUE_LABELS = {
  $document: ['Use a saved value', 'Reuse an authored value in this document or workflow.'],
  $expr: ['Calculate a value', 'Combine authored values with arithmetic or structured composition.'],
  $value: ['Use a function', 'Call a registered function with named arguments.'],
  $result: ['Use an operation’s result', 'Read JSON from an earlier, verified workflow operation.'],
  $axis: ['Use a sweep value', 'Use the current sample of a named sweep; this need not be a spatial axis.'],
  $analytic: ['Create a sequence', 'Generate a finite list of values or camera positions.'],
  $observe: ['Use object metadata', 'Read updated upstream metadata, such as geometry bounds.'],
  $sample: ['Sample field data', 'Read a numeric tuple or component from upstream data.'],
  $calc: ['Calculate during a run', 'Calculate with values available during each graph visit.'],
  $call: ['Use a function during a run', 'Call a registered function with runtime arguments.'],
  $artifact: ['Use an output file', 'Select an artifact from an earlier, verified workflow operation.'],
};
export const valueLabel = key => `${VALUE_LABELS[key]?.[0] || key} (${key === '$result' ? '$value · result' : key})`;
