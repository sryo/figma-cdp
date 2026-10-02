// A library page holding the Button set and the Input component, plus the color tokens as
// variables. The login screen should be built from these, on the run's own page.
await loadFonts();
var tokens = seedTokens();
var lib = await libraryPage();
var buttons = buildButtonSet(lib, tokens.vars);
var input = buildInput(lib, tokens.vars);
input.x = 0; input.y = 200;
return { buttonSetId: buttons.id, inputId: input.id, variables: tokens.ids };
