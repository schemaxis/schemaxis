// Copyright (C) 2026 David L F Gaden
// Public schema API for the Studio JSON editor.
//
//   schemasAt(rootSchema, documentValue, pointer, {editing?, includeMarkers?}) -> schema nodes
//   completions(rootSchema, ast, offset) -> completion items
//   hover(rootSchema, ast, offset) -> {title, description, type, default, enum, constraints, required, range} | null
//   validate(rootSchema, value, {skip?, maxErrors?}) -> [{pointer, message, severity}]
//   SchemaRegistry, resolveSchemaContext, completionsFor, hoverFor, validateDocument (multi-schema)

import {pointerAt} from './json-pointer.mjs';
import {documentValue} from './json-parse.mjs';
import {completionsAt} from './schema-complete.mjs';
import {hoverAt} from './schema-hover.mjs';

export {schemasAt, isMarkerInstance, contextFor} from './schema-core.mjs';
export {validate} from './schema-validate.mjs';
export {completionsAt, skeleton} from './schema-complete.mjs';
export {hoverAt} from './schema-hover.mjs';
export {
  SchemaRegistry, resolveSchemaContext, completionsFor, hoverFor, validateDocument,
} from './schema-registry.mjs';

/** Completion items at a text offset of a parsed document. */
export function completions(rootSchema, ast, offset) {
  return completionsAt(rootSchema, documentValue(ast), pointerAt(ast, offset), ast.text);
}

/** Hover information at a text offset of a parsed document. */
export function hover(rootSchema, ast, offset) {
  return hoverAt(rootSchema, documentValue(ast), pointerAt(ast, offset));
}
