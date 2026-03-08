const crucibleItemSheets = [
    "CrucibleAncestryItemSheet",
    "CrucibleBackgroundItemSheet",
    "CrucibleTalentItemSheet",
    "CrucibleSpellItemSheet",
    "CrucibleTaxonomyItemSheet",
    "CrucibleAccessoryItemSheet",
    "CrucibleLootItemSheet",
    "CrucibleArmorItemSheet",
    "CrucibleConsumableItemSheet",
    "CrucibleToolItemSheet",
    "CrucibleWeaponItemSheet"
];

crucibleItemSheets.forEach(sheet => {
    Hooks.on(`render${sheet}`, (app, html) => addOriginalNameCrucible(app, html));
});

async function addOriginalNameCrucible(app, html) {

    // opcja w settings
    if (!game.settings.get("lang-pl-crucible", "dual-language-names")) return;

    const document = app.document;

    const originalName = document?.flags?.babele?.originalName;
    if (!originalName) return;

    const root = html instanceof HTMLElement ? html : html[0];
    if (!root) return;

    const title = root.querySelector("h1.title");
    if (!title) return;

    const translatedNameInput = title.querySelector('input[name="name"]');
    if (!translatedNameInput) return;

    const translatedName = translatedNameInput.value;

    if (originalName === translatedName) return;

    // unikamy duplikatu
    if (root.querySelector(".original-name")) return;

    const engNameHtml = `
    <div class="original-name" style="font-size:0.9em; opacity:0.8;">
    ${originalName}
    </div>`;

    title.insertAdjacentHTML("afterend", engNameHtml);
}
