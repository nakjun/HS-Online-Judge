const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const tokenizer = script.slice(script.indexOf('const pythonKeywords='), script.indexOf('const codeEditor='));
const context = vm.createContext({});
vm.runInContext(tokenizer, context);
const tokens = source => context.pythonTokens(source);
for (const source of [
  'if True:\n    print(123) # comment',
  'text = """hello\nworld"""',
  'text = "<script>alert(1)</script>"',
  "text = 'unfinished",
  '값 = 0xff\n\tprint(값)\n',
  's = "escaped \\" quote"',
]) assert.equal(tokens(source).map(token => token.text).join(''), source);
assert.equal(tokens('if')[0].kind, 'keyword');
assert.equal(tokens('print')[0].kind, 'builtin');
assert.equal(tokens('123')[0].kind, 'number');
assert.equal(tokens('# if print 123')[0].kind, 'comment');
assert.equal(tokens('"if print 123"')[0].kind, 'string');
assert.equal(tokens('"""hello\nworld"""')[0].kind, 'string');
console.log('Syntax highlighting checks passed.');
