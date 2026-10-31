// Records tests/design/inventory.txt: the VARS lines of figma_lib.js's own __fx.inventory() scan
// over tests/figma_stub.js seeded by seed_vars.js.
//
//   node tests/design/record_inventory.js > tests/design/inventory.txt
const fs = require('fs');
const path = require('path');
const { createFigma } = require('../figma_stub');

global.figma = createFigma();
global.window = global;
(0, eval)(fs.readFileSync(path.join(__dirname, 'seed_vars.js'), 'utf8'));
(0, eval)(fs.readFileSync(path.join(__dirname, '..', '..', 'figma_lib.js'), 'utf8'));
window.__fx.inventory({ match: '^VARS ', maxChars: 100000 }).then((r) => process.stdout.write(r.text + '\n'));
