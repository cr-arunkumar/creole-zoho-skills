#!/usr/bin/env node
// Deprecated alias. A separate file because npx collapses two bin names that share one script
// and would always pick this one; with its own file `npx zoho-skills` runs bin/zoho-skills.js.
"use strict";
process.env.ZOHO_SKILLS_BIN_ALIAS = "creole-zoho";
require("./zoho-skills.js");
