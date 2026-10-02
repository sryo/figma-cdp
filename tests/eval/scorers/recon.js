// Read-only question: the page is unchanged and the answer names every frame with its size
// and text-layer count.
var page = await targetPage();
var answer = String(EVAL.answer || '');
var frames = EVAL.seed.frames;
function has(s) { return answer.indexOf(String(s)) !== -1; }
var m = {
  mutated: hash(page.children.map(signature).join(';')) === EVAL.seed.hash ? 0 : 1,
  extraPages: evalPages().length - 1,
  answerNames: share(frames.filter(function (f) { return has(f.name); }).length, frames.length),
  answerSizes: share(frames.filter(function (f) { return has(f.w) && has(f.h); }).length, frames.length),
  answerTextCounts: share(frames.filter(function (f) { return new RegExp('\\b' + f.texts + '\\b').test(answer); }).length, frames.length),
};
return {
  metrics: m,
  lower: ['mutated', 'extraPages'],
  passed: m.mutated === 0 && m.extraPages === 0 && m.answerNames === 1 && m.answerSizes === 1 && m.answerTextCounts === 1,
};
