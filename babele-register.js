Hooks.once("babele.init", (babele) => {
  if (!game.modules.get("babele")?.active) return;

  babele.register({
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
    restricted: true,
    requiresReload: true,
  });

  const asArray = (collection) => {
    if (!collection) return [];
    if (Array.isArray(collection)) return collection;
    if (collection instanceof Map) return Array.from(collection.values());
    if (Array.isArray(collection.contents)) return collection.contents;
    if (typeof collection[Symbol.iterator] === "function" && typeof collection !== "string") {
      return Array.from(collection);
    }
    if (typeof collection === "object") return Object.values(collection);
    return [];
  };

  const findTranslation = (source, translations, index = -1) => {
    if (!source || !translations) return null;

    const keys = [source.id, source._id, source.name, source.label].filter(Boolean);

    if (Array.isArray(translations)) {
      for (const key of keys) {
        const found = translations.find((entry) =>
          entry && typeof entry === "object" &&
          (entry.id === key || entry._id === key || entry.name === key || entry.label === key)
        );
        if (found) return found;
      }
      return translations[index] ?? null;
    }

    if (typeof translations === "object") {
      for (const key of keys) {
        if (translations[key]) return translations[key];
      }
    }

    return null;
  };

  const normalizeDescriptionContainer = (value) => {
    if (typeof value === "string") return { public: value, private: "" };
    if (!value || typeof value !== "object" || Array.isArray(value)) return { public: "", private: "" };
    return value;
  };

  const embeddedEffectsConverter = (effects, translations) => {
    if (!effects || !translations) return effects;

    const arr = asArray(effects);
    for (const [index, effect] of arr.entries()) {
      if (!effect) continue;

      const translation = findTranslation(effect, translations, index);
      if (!translation || typeof translation !== "object") continue;

      if (translation.name !== undefined) effect.name = translation.name;
      if (translation.label !== undefined) effect.label = translation.label;

      if (translation.description !== undefined) {
        effect.description = translation.description;
        effect.system ??= {};
        effect.system.description = translation.description;
      }
    }

    return effects;
  };

  const actionsConverter = (actions, translations) => {
    if (!actions || !translations) return actions;

    const arr = asArray(actions);
    for (const [index, action] of arr.entries()) {
      if (!action) continue;

      const translation = findTranslation(action, translations, index);
      if (!translation || typeof translation !== "object") continue;

      if (translation.name !== undefined) action.name = translation.name;

      if (translation.description !== undefined) {
        action.description = translation.description;
        action.system ??= {};
        action.system.description = translation.description;
      }

      if (translation.condition !== undefined) {
        action.condition = translation.condition;
        action.system ??= {};
        action.system.condition = translation.condition;
      }

      if (translation.effects !== undefined) {
        if (action.effects) {
          action.effects = embeddedEffectsConverter(action.effects, translation.effects);
        } else if (action.system?.effects) {
          action.system.effects = embeddedEffectsConverter(action.system.effects, translation.effects);
        }
      }
    }

    return actions;
  };

  const embeddedItemsConverter = (items, translations) => {
    if (!items || !translations || typeof translations !== "object") return items;

    const arr = asArray(items);
    for (const [index, item] of arr.entries()) {
      if (!item) continue;

      const itemTranslation = findTranslation(item, translations, index);
      if (!itemTranslation || typeof itemTranslation !== "object") continue;

      if (itemTranslation.name !== undefined) item.name = itemTranslation.name;

      if (itemTranslation.description !== undefined) {
        item.system ??= {};

        if (
          typeof itemTranslation.description === "object" &&
          itemTranslation.description !== null &&
          !Array.isArray(itemTranslation.description)
        ) {
          item.system.description = normalizeDescriptionContainer(item.system.description);

          if (itemTranslation.description.public !== undefined) {
            item.system.description.public = itemTranslation.description.public;
          }
          if (itemTranslation.description.private !== undefined) {
            item.system.description.private = itemTranslation.description.private;
          }
        } else {
          item.system.description = itemTranslation.description;
        }
      }

      if (itemTranslation.actions && item.system?.actions) {
        item.system.actions = actionsConverter(item.system.actions, itemTranslation.actions);
      }

      if (itemTranslation.effects && item.effects) {
        item.effects = embeddedEffectsConverter(item.effects, itemTranslation.effects);
      }
    }

    return items;
  };

  const embeddedObjectWithActionsConverter = (obj, translations) => {
    if (!obj || typeof obj !== "object" || Array.isArray(obj) || !translations || typeof translations !== "object") {
      return obj;
    }

    if (translations.name !== undefined) obj.name = translations.name;
    if (translations.description !== undefined) obj.description = translations.description;
    if (translations.caption !== undefined) obj.caption = translations.caption;

    if (translations.actions) {
      if (obj.actions) {
        obj.actions = actionsConverter(obj.actions, translations.actions);
      } else if (obj.system?.actions) {
        obj.system.actions = actionsConverter(obj.system.actions, translations.actions);
      }
    }

    return obj;
  };

  const embeddedBiographyConverter = (obj, translations) => {
    if (!obj || !translations || typeof translations !== "object") return obj;

    if (typeof obj === "string") {
      return translations.public ?? translations.private ?? obj;
    }

    if (typeof obj !== "object" || Array.isArray(obj)) return obj;

    for (const [key, value] of Object.entries(translations)) {
      if (value !== undefined) obj[key] = value;
    }

    return obj;
  };

  const nestedObjectConverter = (obj, translations) => {
    if (!obj || typeof obj !== "object" || Array.isArray(obj) || !translations || typeof translations !== "object") {
      return obj;
    }

    for (const [key, value] of Object.entries(translations)) {
      if (value !== undefined) obj[key] = value;
    }

    return obj;
  };

  const categoriesConverter = (categories, translations) => {
    if (!categories || !translations) return categories;

    const arr = asArray(categories);
    for (const [index, item] of arr.entries()) {
      if (!item) continue;
      const translation = findTranslation(item, translations, index);
      if (translation?.name !== undefined) item.name = translation.name;
    }

    return categories;
  };

  babele.registerConverters({
    actions_converter: actionsConverter,
    adventure_items_converter: embeddedItemsConverter,
    embedded_items_converter: embeddedItemsConverter,
    embedded_effects_converter: embeddedEffectsConverter,
    embedded_object_with_actions_converter: embeddedObjectWithActionsConverter,
    embedded_biography_converter: embeddedBiographyConverter,
    nested_object_converter: nestedObjectConverter,
    categories_converter: categoriesConverter
  });
});