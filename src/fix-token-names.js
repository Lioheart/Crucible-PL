async function fixTokenNames() {
  // Tylko GM powinien mieć możliwość masowej edycji
  if (!game.user.isGM) return ui.notifications.error("Tylko Mistrz Gry może to zrobić!");

  for (const scene of game.scenes) {
    const updates = [];
    
    for (const token of scene.tokens) {
      // Pobieramy aktora bezpośrednio z dokumentu tokena
      const actor = token.actor; 
      if (!actor) continue;

      if (token.name !== actor.name) {
        updates.push({ _id: token.id, name: actor.name });
      }
    }

    if (updates.length > 0) {
      await scene.updateEmbeddedDocuments("Token", updates);
      console.log(`Zaktualizowano ${updates.length} tokenów na scenie: ${scene.name}`);
    }
  }
  ui.notifications.info("Synchronizacja zakończona pomyślnie.");
}

function addFixTokenButton(html) {
  // Nie pokazuj przycisku, jeśli użytkownik nie jest GM
  if (!game.user.isGM) return;

  const root = html[0] ?? html;
  const footer = root.querySelector(".directory-footer");
  if (!footer || footer.querySelector(".fix-tokens-btn")) return;

  const button = document.createElement("button");
  button.classList.add("fix-tokens-btn");
  button.innerHTML = `<i class="fas fa-sync-alt"></i> Popraw nazwy tokenów`;
  button.dataset.tooltip = "Synchronizuje nazwy WSZYSTKICH tokenów na WSZYSTKICH scenach z nazwami ich aktorów.";
  button.dataset.tooltipDirection = "UP";

  button.addEventListener("click", async (event) => {
    event.preventDefault();
    // Wyłączenie przycisku na czas pracy, aby uniknąć spamu kliknięć
    button.disabled = true;
    await fixTokenNames();
    button.disabled = false;
  });

  footer.appendChild(button);
}

Hooks.on("renderCompendiumDirectory", (app, html) => addFixTokenButton(html));
Hooks.on("renderActorDirectory", (app, html) => addFixTokenButton(html));