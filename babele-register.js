Hooks.once("init", () => {
  if (!game.modules.get("babele")?.active) return;

  game.babele.register({
    module: "lang-pl-crucible",
    lang: "pl",
    dir: "lang/pl/compendium"
  });

  game.settings.register("lang-pl-crucible", "dual-language-names", {
    name: "Wyświetl nazwy po polsku i angielsku",
    hint: "Oprócz nazwy polskiej wyświetlaj nazwę oryginalną (o ile się różni).",
    scope: "world",
    type: Boolean,
    default: false,
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
    },

    adventure_items_converter: (items, translations) => {
      if (!Array.isArray(items) || !translations) return items;

      return items.map(item => {
        const itemTranslation = translations[item.name];
        if (!itemTranslation) return item;

        if (itemTranslation.name) {
          item.name = itemTranslation.name;
        }

        if (itemTranslation.description) {
          item.system ??= {};

          if (typeof itemTranslation.description === "object" && itemTranslation.description !== null) {
            item.system.description ??= {};

            if (itemTranslation.description.public) {
              item.system.description.public = itemTranslation.description.public;
            }

            if (itemTranslation.description.private) {
              item.system.description.private = itemTranslation.description.private;
            }
          } else {
            item.system.description = itemTranslation.description;
          }
        }

        if (itemTranslation.actions && Array.isArray(item.system?.actions)) {
          item.system.actions = game.babele.converters.actions_converter(
            item.system.actions,
            itemTranslation.actions
          );
        }

        return item;
      });
    },

    categories_converter: (categories, translations) => {
      if (!Array.isArray(categories) || !translations) return categories;

      return categories.map(item => {
        const translation = translations[item._id];
        if (translation?.name) {
          item.name = translation.name;
        }
        return item;
      });
    },

    nested_object_converter: (obj, translations) => {
      if (!obj || !translations || typeof translations !== "object") return obj;

      for (const key of Object.keys(translations)) {
        if (translations[key] !== undefined) {
          obj[key] = translations[key];
        }
      }

      return obj;
    }

  });
});
