// The seeded Customers screen holds four plain rows of one structure and a plain header; the
// Team screen (team.html) uses the same row and header. Graded on spotting the pattern:
//   newRowsInstanced   share of the Team rows that are instances
//   rowSplit           components the rows (both screens) instance, beyond one
//   oldRowsLinked      share of the seeded rows now instances of (or being) the Team rows'
//                      component
//   newRawRows         Team rows drawn as plain frames: a third copy of the structure
//   rawRowCopies       plain-frame rows left on both screens
//   headerInstanced    the Team header is an instance; headerLinked: of the seeded header's
//                      component
//   oldCopyKept        share of the seeded screen's strings still on it
// plus nestedShare/variantMatch/sizingMatch over both screens' usages, copy, inventedCopy and
// quality().
var pages = evalPages();
var page = await targetPage();
var oldS = EVAL.seed.screen, team = EVAL.expect.screens.team;
var read = await readScreens(page, [oldS, team], EVAL.expect);
function of(screen, c) { return read.recs.filter(function (r) { return r.screen === screen && r.u.c === c; }); }
function ownerId(r) { return r && r.owner ? r.owner.id : null; }
function regionNodes(screen) {
  var f = read.screens.filter(function (x) { return x.screen === screen; })[0];
  return f && f.region ? [f.region].concat(f.region.findAll ? f.region.findAll() : []) : [];
}
var oldRows = of(oldS, 'ListItem'), newRows = of(team, 'ListItem');
var counts = {}, owners = {};
newRows.forEach(function (r) { if (ownerId(r)) counts[ownerId(r)] = (counts[ownerId(r)] || 0) + 1; });
oldRows.concat(newRows).forEach(function (r) { if (ownerId(r)) owners[ownerId(r)] = 1; });
var rowOwner = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0] || null;
var oldHeader = of(oldS, 'AppHeader')[0], newHeader = of(team, 'AppHeader')[0];
var cm = await componentMetrics(read, EVAL.expect, pages);
var strings = Object.keys(setOf(oldS.strings.concat(team.strings)));
var m = Object.assign(await quality(pages), {
  screensFound: share(read.screens.filter(function (f) { return f.region; }).length, 2),
  newRowsInstanced: share(newRows.filter(function (r) { return r.inst; }).length, newRows.length),
  rowSplit: Math.max(0, Object.keys(owners).length - 1),
  oldRowsLinked: share(oldRows.filter(function (r) { return rowOwner && ownerId(r) === rowOwner; }).length, oldRows.length),
  newRawRows: newRows.filter(function (r) { return r.region && !r.inst; }).length,
  rawRowCopies: oldRows.concat(newRows).filter(function (r) { return r.region && !r.inst; }).length,
  headerInstanced: newHeader && newHeader.inst ? 1 : 0,
  headerLinked: newHeader && ownerId(newHeader) && ownerId(newHeader) === ownerId(oldHeader) ? 1 : 0,
  oldCopyKept: copyMatch(oldS.strings, regionNodes(oldS)),
  copy: copyMatch(team.strings, regionNodes(team)),
  inventedCopy: inventedCopy(read, strings),
  nestedShare: cm.nestedShare,
  variantMatch: cm.variantMatch,
  sizingMatch: cm.sizingMatch,
});
return {
  metrics: m,
  lower: QUALITY_LOWER.concat(['rowSplit', 'newRawRows', 'rawRowCopies', 'inventedCopy']),
  passed: m.screensFound === 1 && m.newRowsInstanced === 1 && m.rowSplit === 0 && m.headerInstanced === 1 &&
    m.oldCopyKept === 1 && m.copy >= 0.95,
};
