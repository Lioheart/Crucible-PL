Hooks.on("renderActorSheet5eNPC", async (document, html) => {
    await addOriginalNameDnD(document, html);
});

Hooks.on("renderItemSheet5e", async (document, html) => {
    await addOriginalNameDnD(document, html);
});

async function addOriginalNameDnD(document, html) {
    // Sprawdzamy, czy opcja jest aktywna
    if (!game.settings.get("dnd5e_pl", "dual-language-names")) return;

    const originalname = document.document?.flags?.babele?.originalName;
    if (!originalname) {
        console.log("Brak originalName w flagach Babele.");
        return;
    }

    // Obsługa DOM bez jQuery
    const root = html instanceof HTMLElement ? html : html[0];
    if (!root || !(root instanceof HTMLElement)) {
        console.warn("Nieprawidłowy obiekt HTML:", html);
        return;
    }

    const nameElement = root.querySelector(".document-name");
    if (!nameElement) {
        console.warn("Nie znaleziono .document-name.");
        return;
    }

    const translatedname = nameElement.textContent.trim();

    if (originalname !== translatedname) {
        const engnamehtml = `
            <div class="english-name">
                <h3 class="item-name">${originalname}</h3>
            </div>`;

        nameElement.insertAdjacentHTML("afterend", engnamehtml);
    }
}
