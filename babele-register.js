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

      return actions.map(action => {

        const translation =
        translations[action.id] ??
        translations[action.name];

        if (!translation) return action;

        // tłumaczenie głównych pól
        if (translation.name) action.name = translation.name;
        if (translation.description) action.description = translation.description;
        if (translation.condition) action.condition = translation.condition;

        // tłumaczenie efektów
        if (Array.isArray(action.effects) && Array.isArray(translation.effects)) {

          action.effects = action.effects.map((effect, index) => {

            const effectTranslation = translation.effects[index];
            if (!effectTranslation) return effect;

            if (effectTranslation.name) effect.name = effectTranslation.name;

            if (effectTranslation.description) {
              if (!effect.system) effect.system = {};
              effect.system.description = effectTranslation.description;
            }

            return effect;
          });

        }

        return action;
      });
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
// 		"flags.dnd5e_pl.id": sourceId,
// 		"flags.dnd5e_pl.originalName": originalName
// 	});
// });

