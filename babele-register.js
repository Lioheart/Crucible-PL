Hooks.once("init", () => {
  if (!game.modules.get("babele")?.active) return;

  game.babele.register({
    module: "lang-pl-crucible",
    lang: "pl",
    dir: "lang/pl/compendium"
  });

  game.settings.register("lang-pl-crucible", "dual-language-names", {
    name: "Wyświetl nazwy po polsku i angielsku",
    hint: 'Oprócz nazwy polskiej wyświetlaj nazwę oryginalną (o ile się różni).',
    scope: "world",
    type: Boolean,
    default: true,
    config: true,
  });

  game.babele.registerConverters({

    actions_converter: (actions, translations) => {
      if (!Array.isArray(actions) || !translations) return actions;

      for (const action of actions) {

        const translation =
        translations[action.id] ??
        translations[action.name];

        if (!translation) continue;

        if (translation.name) action.name = translation.name;
        if (translation.description) action.description = translation.description;
        if (translation.condition) action.condition = translation.condition;

        if (Array.isArray(action.effects) && Array.isArray(translation.effects)) {

          for (let i = 0; i < action.effects.length; i++) {
            const effect = action.effects[i];
            const effectTranslation = translation.effects[i];
            if (!effectTranslation) continue;

            if (effectTranslation.name) effect.name = effectTranslation.name;

            if (effectTranslation.description) {
              effect.system ??= {};
              effect.system.description = effectTranslation.description;
            }
          }

        }
      }

      return actions;
    }

  });
});

// Hooks.on("preCreateItem", (item, context) => {
// 	const sourceId =
// 	context?.fromCompendium?.uuid ||
// 	item.flags?.core?.sourceId ||
// 	item._stats?.compendiumSource ||
// 	item._source?._stats?.compendiumSource;
//
// 	const originalName = item.flags?.babele?.originalName;
//
// 	if (!sourceId || !originalName) return;
//
// 	item.updateSource({
// 		"flags.lang-pl-crucible.id": sourceId,
// 		"flags.lang-pl-crucible.originalName": originalName
// 	});
// });

