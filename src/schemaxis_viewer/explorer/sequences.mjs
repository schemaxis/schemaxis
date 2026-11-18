// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Automatic numbered and lettered sequences in ordinary filenames.
//
// Files form a numbered sequence when, within one folder, they are identical
// apart from their digit runs (file1outU.png, file2outU.png, file10outU.png).
// Letter runs are literal, so file1outP.png and file2outU.png stay apart.
// A lettered sequence (phase-A, phase-B, phase-AA) is recognised only for
// three or more files whose short capital-letter run is the varying part;
// any digits that also vary must step evenly with the letters (file-AAA-0,
// file-AAB-1, file-AAC-2).

const TOKEN = /((?<=[_=])-?\d+(?:\.\d+)?|\d+(?:\.\d+)?)|([A-Z]{1,3}(?![A-Za-z]))|([A-Z]+(?![a-z])|[A-Z]?[a-z]+)|([^A-Za-z\d-]+|-)/g;

export function tokenize(name) {
  const tokens = [];
  for (const match of name.matchAll(TOKEN)) {
    const type = match[1] !== undefined ? 'num' : match[2] !== undefined ? 'caps' : match[3] !== undefined ? 'word' : 'sep';
    tokens.push({text: match[0], type});
  }
  return tokens;
}

export function alphabeticRank(text) {
  let rank = 0;
  for (const char of text) rank = rank * 26 + char.charCodeAt(0) - 64;
  return rank;
}

function shapeKey(entry, lettered) {
  let key = entry.folder + '\u0000';
  for (const token of entry.tokens) {
    if (token.type === 'num') key += '\u0001#';
    else if (lettered && token.type === 'caps') key += '\u0001@';
    else key += token.text;
  }
  return key;
}

function varyingSlots(members, type) {
  const slots = [];
  members[0].tokens.forEach(function collect(token, index) {
    if (token.type !== type) return;
    const values = new Set(members.map(member => member.tokens[index].text));
    if (values.size > 1) slots.push(index);
  });
  return slots;
}

function slotValue(token) {
  return token.type === 'caps' ? alphabeticRank(token.text) : Number(token.text);
}

function compareTuples(a, b) {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

function familyLabel(members, shown) {
  return members[0].tokens.map(function render(token, index) {
    if (!shown.includes(index)) return token.text;
    const texts = members.map(member => member.tokens[index]);
    texts.sort((a, b) => slotValue(a) - slotValue(b));
    return `[${texts[0].text}–${texts.at(-1).text}]`;
  }).join('');
}

function assign(result, members, varying, shown = varying) {
  const tuples = new Map(members.map(member => [member, varying.map(index => slotValue(member.tokens[index]))]));
  members.sort((a, b) => compareTuples(tuples.get(a), tuples.get(b)));
  const label = familyLabel(members, shown);
  const family = 'auto:' + members[0].folder + '\u0000' + label;
  members.forEach(function store(member, rank) {
    const values = varying.map(index => {
      const token = member.tokens[index];
      return token.type === 'caps' ? token.text : Number(token.text);
    });
    result.set(member.id, {family, label, rank, size: members.length, values});
  });
}

function constantStep(members, slot) {
  const step = Number(members[1].tokens[slot].text) - Number(members[0].tokens[slot].text);
  if (!(step > 0)) return false;
  for (let i = 2; i < members.length; i++) {
    if (Number(members[i].tokens[slot].text) - Number(members[i - 1].tokens[slot].text) !== step) return false;
  }
  return true;
}

function buckets(entries, lettered) {
  const map = new Map();
  for (const entry of entries) {
    const key = shapeKey(entry, lettered);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(entry);
  }
  return map;
}

export function detectSequences(files) {
  const entries = files.map(file => ({...file, tokens: tokenize(file.name)}));
  const result = new Map();
  for (const members of buckets(entries, false).values()) {
    if (members.length < 2) continue;
    const varying = varyingSlots(members, 'num');
    if (varying.length) assign(result, members, varying);
  }
  const remaining = entries.filter(entry => !result.has(entry.id) && entry.tokens.some(token => token.type === 'caps'));
  for (const members of buckets(remaining, true).values()) {
    if (members.length < 3) continue;
    const letters = varyingSlots(members, 'caps');
    if (!letters.length) continue;
    const ranks = new Set(members.map(member => letters.map(index => member.tokens[index].text).join('\u0000')));
    if (ranks.size !== members.length) continue;
    members.sort((a, b) => compareTuples(letters.map(i => slotValue(a.tokens[i])), letters.map(i => slotValue(b.tokens[i]))));
    const digits = varyingSlots(members, 'num');
    if (!digits.every(slot => constantStep(members, slot))) continue;
    assign(result, members, letters, [...letters, ...digits]);
  }
  return result;
}
