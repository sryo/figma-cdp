// A live page imported through the capture path: the "[cap:0] <title>" root with the page's
// text as text layers and auto layout inferred from flow.
var page = await targetPage();
var root = page.children.filter(function (n) { return /^\[cap:0\]/.test(n.name); })[0] || null;
var all = root ? [root].concat(root.findAll()) : [];
var m = Object.assign(await quality([page]), {
  rootFound: root && root.name === '[cap:0] Example Domain' ? 1 : 0,
  copy: copyMatch(['Example Domain'], all),
  anyAutoLayout: all.some(function (n) { return n.layoutMode && n.layoutMode !== 'NONE'; }) ? 1 : 0,
});
return { metrics: m, lower: QUALITY_LOWER, passed: m.rootFound === 1 && m.copy === 1 && m.anyAutoLayout === 1 };
