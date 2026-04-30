function normalizeCharacterDetail(c) {
  const out = { ...c };
  if (c.runtime_layers && typeof c.runtime_layers === 'object') {
    for (const [k, v] of Object.entries(c.runtime_layers)) {
      out['rl__' + k] = v;
    }
  }
  out.tags = tagsToFormValue(c.tags);
  out.is_visible = c.is_visible ? 1 : 0;
  out.import_locked = c.import_locked ? 1 : 0;
  out.affection_enabled = c.affection_enabled ? 1 : 0;
  return out;
}
