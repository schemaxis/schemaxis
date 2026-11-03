// Copyright (C) 2026 David L F Gaden
// Theme application and setting writes shared by the shell and Settings window.

export function applyTheme(theme) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.dispatchEvent(new CustomEvent('themechange', {detail: {dark}}));
}

export async function setSetting(ctx, values) {
  const result = await ctx.call(() => ctx.api.post('/api/settings', {action: 'write', values, role: ctx.role()}),
    {title: 'Setting not saved'});
  if (result) {
    ctx.store.set({settings: result});
    applyTheme(result.values.theme);
  }
  return result;
}
