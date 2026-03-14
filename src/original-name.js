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

// ładowanie CSS tylko gdy opcja jest włączona
Hooks.once("ready", () => {

    if (!game.settings.get("lang-pl-crucible", "dual-language-names")) return;

    const id = "lang-pl-crucible-original-name-css";
    if (document.getElementById(id)) return;

    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = "modules/lang-pl-crucible/styles/original-name.css";

    document.head.appendChild(link);
});

crucibleItemSheets.forEach(sheet => {
    Hooks.on(`render${sheet}`, (app, html) => addOriginalNameCrucible(app, html));
});

async function addOriginalNameCrucible(app, html) {

    if (!game.settings.get("lang-pl-crucible", "dual-language-names")) return;

    const documentData = app.document;
    const originalName = documentData?.flags?.babele?.originalName;
    if (!originalName) return;

    const root = html instanceof HTMLElement ? html : html[0];
    if (!root) return;

    const title = root.querySelector("h1.title");
    if (!title) return;

    const translatedNameInput = title.querySelector('input[name="name"]');
    if (!translatedNameInput) return;

    const translatedName = translatedNameInput.value;

    if (originalName === translatedName) return;

    if (root.querySelector(".original-name")) return;

    const engNameHtml = `
    <div class="original-name">
    ${originalName}
    </div>
    `;

    title.insertAdjacentHTML("afterend", engNameHtml);
}
