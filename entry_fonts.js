// Use the same font stack in main entries, split lookups and the scan popup.
function applyEntryFonts(values) {
  const root = document.documentElement.style;
  for (const key of ['font_headword','font_reading','font_definition','font_example','font_frequency','font_pitch']) {
    if (Number.isFinite(values[key])) root.setProperty('--'+key.replaceAll('_','-'),values[key]+'px');
  }
  if (typeof values.font_family === 'string') {
    if (values.font_family) {
      // JSON quoting keeps spaces and punctuation inside a single CSS family name.
      root.setProperty('--entry-font-family', JSON.stringify(values.font_family)+', "Noto Sans CJK JP", "Noto Sans CJK SC", "Noto Sans CJK TC", sans-serif');
    } else root.removeProperty('--entry-font-family');
  }
}
