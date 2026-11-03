// Copyright (C) 2026 David L F Gaden
"use strict";
const { observeFolder } = require("./observer.js");
document.getElementById("observe").addEventListener("click", async () => {
    const button = document.getElementById("observe"), status = document.getElementById("status");
    button.disabled = true;
    try {
        const uxp = require("uxp"), ppro = require("premierepro");
        const folder = await uxp.storage.localFileSystem.getFolder();
        if (!folder) { status.textContent = "Folder selection cancelled."; return; }
        status.textContent = "Reading the active sequence twice…";
        await observeFolder(folder, ppro, uxp);
        status.textContent = "Observation written. Schemaxis checks the declared sequence contract.";
    } catch (error) { status.textContent = "Observation failed: " + String(error.message || error); }
    finally { button.disabled = false; }
});
