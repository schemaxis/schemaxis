// Packaged help browser. Large references load one operation/topic at a time.
import {h, icon} from '../../lib/dom.mjs';
import {searchTopics, contextTopic, decodePage} from './model.mjs';
import {renderPage} from './render.mjs';

export const helpWindow = {
  type: 'help', title: 'Help', icon: 'help', singleton: true,
  create(ctx, params = {}) {
    let index, disposed = false, request = 0, cursor = -1, limit = 60, current;
    const history = []; const cache = new Map();
    const search = h('input', {class: 'input', type: 'search', placeholder: 'Search help, operations and $ syntax',
      'aria-label': 'Search help', onInput: () => { limit = 60; results(); }});
    const group = h('select', {class: 'input', 'aria-label': 'Help category', onChange: () => { limit = 60; results(); }});
    const list = h('nav', {class: 'help-results', 'aria-label': 'Help topics'});
    const count = h('div', {class: 'help-result-count', role: 'status'});
    const reader = h('div', {class: 'help-reader', tabindex: '0', 'aria-label': 'Help content'});
    const toc = h('nav', {class: 'help-toc', 'aria-label': 'On this page'});
    const sourceTitle = h('span', {});
    const sectionSelect = h('select', {class: 'input', 'aria-label': 'Jump to help section',
      onChange: () => jump(sectionSelect.value)});
    const source = h('div', {class: 'help-source'}, sourceTitle, sectionSelect);
    const status = h('span', {role: 'status'});
    const back = h('button', {class: 'button small', disabled: true, 'aria-label': 'Previous help topic', onClick: () => travel(-1)}, 'Back');
    const forward = h('button', {class: 'button small', disabled: true, 'aria-label': 'Next help topic', onClick: () => travel(1)}, 'Forward');
    const shortcuts = h('div', {class: 'help-shortcuts'});
    const element = h('div', {class: 'window-body help-window'},
      h('div', {class: 'window-header'}, icon('help'), h('div', {class: 'titles'}, h('h2', {}, 'Schemaxis Studio Help'),
        h('div', {class: 'subtitle'}, 'Guides, operation contracts, examples and shared authoring syntax')), back, forward, status),
      h('div', {class: 'help-layout'}, h('aside', {class: 'help-sidebar'}, search, group, shortcuts, count, list),
        h('section', {class: 'help-content'}, source, reader), h('aside', {class: 'help-outline'}, h('h3', {}, 'On this page'), toc)));

    const ready = ctx.api.get('/help/index.json').then((data) => {
      if (disposed) return;
      index = data;
      group.append(h('option', {value: ''}, 'All help topics'),
        ...[...new Set(index.entries.map((entry) => entry.group))].sort().map((name) => h('option', {value: name}, name)));
      shortcuts.append(h('button', {class: 'button small', onClick: () => navigate({topic: index.home})}, 'Studio guide'),
        h('button', {class: 'button small', onClick: () => navigate({topic: index.shared})}, '$ reference'),
        h('button', {class: 'button small', onClick: () => navigate({topic: index.paraview})}, 'ParaView guide'));
      results();
    }).catch((error) => {
      if (!disposed) { status.textContent = 'Help could not load.'; ctx.notify.error(error, {title: 'Help unavailable'}); }
    });

    function results() {
      if (!index || disposed) return;
      const matches = searchTopics(index.entries, search.value, group.value);
      count.textContent = `${matches.length} topics${matches.length > limit ? ` · showing ${limit}` : ''}`;
      list.replaceChildren(...matches.slice(0, limit).map((entry) => h('button', {
        class: 'help-topic', 'aria-current': current?.id === entry.id ? 'page' : undefined,
        onClick: () => navigate({topic: entry.id})}, h('strong', {}, entry.title), h('small', {}, entry.group),
        h('span', {}, entry.summary))));
      if (!matches.length) list.append(h('p', {}, 'No matching topics. Try an operation, option name or $ command.'));
      if (matches.length > limit) list.append(h('button', {class: 'button small', onClick: () => { limit += 60; results(); }}, 'Show more topics'));
    }

    function jump(anchor) {
      const heading = [...reader.querySelectorAll('[id]')].find((item) => item.id === `help-${anchor}`);
      if (heading) { heading.scrollIntoView({block: 'start'}); heading.focus({preventScroll: true}); }
    }

    async function show(target, {record = true, scroll = 0} = {}) {
      const token = ++request;
      reader.setAttribute('aria-busy', 'true'); status.textContent = 'Loading topic…';
      try {
        let page = cache.get(target.id);
        if (!page) { page = await decodePage(await ctx.api.get(`/help/${target.id}.json`)); cache.set(target.id, page); }
        if (disposed || token !== request) return;
        if (record) {
          if (cursor >= 0) history[cursor].scroll = reader.scrollTop;
          history.splice(cursor + 1);
          history.push({...target, scroll: 0}); cursor = history.length - 1;
        }
        current = page; params.topic = target.id; params.anchor = target.anchor || '';
        ctx.windows.persist();
        sourceTitle.textContent = `${page.title} · ${page.source}`;
        reader.replaceChildren(renderPage(page, (next) => show(next), ctx.notify));
        sectionSelect.replaceChildren(h('option', {value: ''}, 'Jump to section…'),
          ...page.headings.filter((item) => item.level <= 3).map((item) => h('option', {value: item.anchor}, item.title.replace(/[`*]/g, ''))));
        toc.replaceChildren(...page.headings.filter((item) => item.level <= 3).map((item) => h('button', {
          class: `help-section level-${item.level}`, onClick: () => jump(item.anchor)}, item.title.replace(/[`*]/g, ''))));
        reader.scrollTop = scroll;
        if (target.anchor) jump(target.anchor);
        back.disabled = cursor <= 0; forward.disabled = cursor >= history.length - 1;
        status.textContent = ''; results();
      } catch (error) {
        if (!disposed && token === request) { status.textContent = 'Topic could not load.'; ctx.notify.error(error, {title: 'Help topic unavailable'}); }
      } finally {
        if (!disposed && token === request) reader.setAttribute('aria-busy', 'false');
      }
    }

    function travel(delta) {
      const next = cursor + delta;
      if (next < 0 || next >= history.length) return;
      history[cursor].scroll = reader.scrollTop; cursor = next;
      show({...history[cursor], anchor: ''}, {record: false, scroll: history[cursor].scroll});
    }

    async function navigate(detail = {}) {
      await ready;
      if (!index || disposed) return;
      const entry = detail.topic ? index.entries.find((item) => item.id === detail.topic) : contextTopic(index, detail);
      await show({id: entry?.id || index.home, anchor: detail.anchor || ''});
    }
    navigate(params);
    return {element, navigate, dispose: () => { disposed = true; request++; }};
  },
};
