// Three top-level frames with known sizes and text counts, and a fingerprint of the page so
// the scorer can tell whether the session changed anything.
await loadFonts();
var page = await targetPage();
var spec = [
  { name: 'Onboarding / Step 1', w: 375, h: 812, texts: ['Find your sound', 'Pick three artists you love', 'Continue'] },
  { name: 'Onboarding / Step 2', w: 375, h: 812, texts: ['Turn on notifications', 'Skip'] },
  { name: 'Paywall', w: 390, h: 844, texts: ['Lumen Plus', 'Ad-free listening', 'Offline downloads', 'Start free trial'] },
];
spec.forEach(function (s, i) {
  var f = mkFrame(page, s.name, 'VERTICAL', { gap: 12, pad: [24, 24, 24, 24], fill: 'surface' });
  f.resize(s.w, s.h);
  f.primaryAxisSizingMode = 'FIXED';
  f.counterAxisSizingMode = 'FIXED';
  f.x = i * 440;
  s.texts.forEach(function (t) { mkText(f, t, { size: 16 }); });
});
return {
  frames: spec.map(function (s) { return { name: s.name, w: s.w, h: s.h, texts: s.texts.length }; }),
  hash: hash(page.children.map(signature).join(';')),
};
