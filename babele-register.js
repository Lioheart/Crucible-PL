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
    requiresReload: false,
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

  const cloneRawData = (value) => {
    if (!value || typeof value !== "object") return value;

    const source =
      value._source && typeof value._source === "object"
        ? value._source
        : value;

    if (globalThis.foundry?.utils?.deepClone) {
      return globalThis.foundry.utils.deepClone(source);
    }

    return structuredClone(source);
  };

  const cloneEffectData = (effect) => {
    return cloneRawData(effect);
  };

  const cloneItemData = (item) => {
    const source = cloneRawData(item);

    if (!source || typeof source !== "object") {
      return source;
    }

    /*
     * W item._source.effects mogą znajdować się wyłącznie identyfikatory.
     * Rzeczywiste osadzone ActiveEffect są dostępne w item.effects.
     *
     * Pobieramy dokumenty efektów, ale kopiujemy wyłącznie ich _source,
     * żeby nie wywoływać getterów systemowych ani fromUuidSync.
     */
    let embeddedEffects = [];

    try {
      embeddedEffects = asArray(item?.effects).filter(
        (effect) =>
          effect &&
          typeof effect === "object"
      );
    } catch (error) {
      console.warn(
        "Crucible PL | Nie udało się odczytać osadzonych efektów itemu",
        item?.name,
        error
      );
    }

    if (embeddedEffects.length) {
      source.effects = embeddedEffects.map(cloneEffectData);
    } else if (Array.isArray(source.effects)) {
      /*
       * Jeśli wejściem jest już zwykły obiekt zawierający pełne efekty,
       * również kopiujemy je bezpiecznie.
       *
       * Jeżeli znajdują się tam tylko identyfikatory tekstowe, zostawiamy
       * oryginalną tablicę bez zmian, aby nie usuwać danych mechanicznych.
       */
      const sourceEffectObjects = source.effects.filter(
        (effect) =>
          effect &&
          typeof effect === "object"
      );

      if (sourceEffectObjects.length) {
        source.effects = sourceEffectObjects.map(cloneEffectData);
      }
    }

    return source;
  };

  const asEffectSourceArray = (effects) => {
    return asArray(effects)
      .filter(
        (effect) =>
          effect &&
          typeof effect === "object"
      )
      .map(cloneEffectData);
  };

  const asItemSourceArray = (items) => {
    return asArray(items)
      .filter(
        (item) =>
          item &&
          typeof item === "object"
      )
      .map(cloneItemData);
  };

  const asSourceArray = (collection) => {
    return asArray(collection).map((entry) => cloneRawData(entry));
  };

  const stripTierSuffix = (value) => {
    if (typeof value !== "string") return value;
    return value.replace(/\s+(I|II|III|IV|V|VI|VII|VIII|IX|X|[1-9][0-9]*)$/i, "").trim();
  };

  const normalizeKey = (value) => {
    if (typeof value !== "string") return null;
    const stripped = stripTierSuffix(value).trim();
    return stripped || null;
  };

  const collectLookupKeys = (source) => {
    if (!source || typeof source !== "object") return [];
    const raw = [
      source.id,
      source._id,
      source.name,
      source.label,
      source.system?.identifier,
      source.system?.id,
      source.system?.slug
    ];

    const keys = [];
    for (const value of raw) {
      const normalized = normalizeKey(value);
      if (normalized && !keys.includes(normalized)) keys.push(normalized);
    }
    return keys;
  };

  const translationMatches = (entry, key) => {
    if (!entry || typeof entry !== "object") return false;

    const raw = [
      entry.id,
      entry._id,
      entry.name,
      entry.label,
      entry.identifier,
      entry.system?.identifier,
      entry.system?.id,
      entry.system?.slug
    ];

    return raw.some((value) => normalizeKey(value) === key);
  };

  const findTranslation = (source, translations, index = -1) => {
    if (!source || !translations) return null;

    const keys = collectLookupKeys(source);

    if (Array.isArray(translations)) {
      for (const key of keys) {
        const found = translations.find((entry) => translationMatches(entry, key));
        if (found) return found;
      }
      return translations[index] ?? null;
    }

    if (typeof translations === "object") {
      for (const key of keys) {
        if (translations[key]) return translations[key];
      }

      for (const key of keys) {
        const found = Object.values(translations).find((entry) => translationMatches(entry, key));
        if (found) return found;
      }

      if (index >= 0) {
        const fallback = Object.values(translations)[index];
        if (fallback && typeof fallback === "object") return fallback;
      }
    }

    return null;
  };

  const normalizeDescriptionContainer = (value) => {
    if (typeof value === "string") return { public: value, private: "" };
    if (!value || typeof value !== "object" || Array.isArray(value)) return { public: "", private: "" };
    return value;
  };

  const crucibleDescriptionConverter = (value, translation) => {
    if (translation === undefined || translation === null) return value;

    if (typeof value === "string") {
      if (typeof translation === "string") return translation;

      if (
        translation &&
        typeof translation === "object" &&
        !Array.isArray(translation)
      ) {
        return translation.public ?? translation.private ?? value;
      }

      return value;
    }

    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value)
    ) {
      const result = cloneRawData(value);

      if (typeof translation === "string") {
        result.public = translation;
        return result;
      }

      if (
        translation &&
        typeof translation === "object" &&
        !Array.isArray(translation)
      ) {
        if (translation.public !== undefined) {
          result.public = translation.public;
        }

        if (translation.private !== undefined) {
          result.private = translation.private;
        }

        return result;
      }

      return result;
    }

    return translation;
  };

  const activeEffectChangesConverter = (changes, translations) => {
    if (!changes || !translations) return changes;

    const arr = asArray(changes);

    for (const change of arr) {
      if (!change || typeof change !== "object") continue;

      const key = change.key;
      if (typeof key !== "string" || !key) continue;

      let translatedValue;

      if (Array.isArray(translations)) {
        const translation = translations.find((entry) =>
          entry && typeof entry === "object" && entry.key === key
        );

        if (translation) {
          translatedValue = translation.value;
        }
      } else if (typeof translations === "object") {
        const translation = translations[key];

        if (
          translation &&
          typeof translation === "object" &&
          !Array.isArray(translation)
        ) {
          translatedValue = translation.value;
        } else {
          translatedValue = translation;
        }
      }

      if (translatedValue !== undefined) {
        change.value = translatedValue;
      }
    }

    return arr;
  };

  const embeddedEffectsConverter = (effects, translations) => {
    if (!effects || !translations) return effects;

    const arr = asEffectSourceArray(effects);

    for (const [index, effect] of arr.entries()) {
      if (!effect || typeof effect !== "object") continue;

      const translation = findTranslation(effect, translations, index);
      if (!translation || typeof translation !== "object") continue;

      if (translation.name !== undefined) {
        effect.name = translation.name;
      }

      if (translation.label !== undefined) {
        effect.label = translation.label;
      }

      if (translation.description !== undefined) {
        effect.description = translation.description;
      }

      if (translation.changes !== undefined) {
        if (Array.isArray(effect.changes)) {
          effect.changes = activeEffectChangesConverter(
            effect.changes,
            translation.changes
          );
        }

        if (Array.isArray(effect.system?.changes)) {
          effect.system.changes = activeEffectChangesConverter(
            effect.system.changes,
            translation.changes
          );
        }
      }
    }

    return arr;
  };

  const embeddedAffixesConverter = (effects, translations) => {
    return itemEffectsConverter(effects, translations);
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

  const itemEffectsConverter = (effects, translations) => {
    if (!effects || !translations) return effects;

    const arr = asEffectSourceArray(effects);

    for (const [index, effect] of arr.entries()) {
      if (!effect || typeof effect !== "object") continue;

      const translation = findTranslation(effect, translations, index);
      if (!translation || typeof translation !== "object") continue;

      if (translation.name !== undefined) {
        effect.name = translation.name;
      }

      if (translation.label !== undefined) {
        effect.label = translation.label;
      }

      if (translation.description !== undefined) {
        effect.description = translation.description;
      }

      if (translation.adjective !== undefined) {
        effect.system ??= {};
        effect.system.adjective = translation.adjective;
      }

      if (translation.changes !== undefined) {
        if (Array.isArray(effect.changes)) {
          effect.changes = activeEffectChangesConverter(
            effect.changes,
            translation.changes
          );
        }

        if (Array.isArray(effect.system?.changes)) {
          effect.system.changes = activeEffectChangesConverter(
            effect.system.changes,
            translation.changes
          );
        }
      }

      if (translation.actions !== undefined) {
        if (Array.isArray(effect.system?.actions)) {
          effect.system.actions = actionsConverter(
            effect.system.actions,
            translation.actions
          );
        }

        if (Array.isArray(effect.actions)) {
          effect.actions = actionsConverter(
            effect.actions,
            translation.actions
          );
        }
      }

      if (translation.effects !== undefined) {
        if (effect.effects) {
          effect.effects = embeddedEffectsConverter(
            effect.effects,
            translation.effects
          );
        }

        if (effect.system?.effects) {
          effect.system.effects = embeddedEffectsConverter(
            effect.system.effects,
            translation.effects
          );
        }
      }
    }

    return arr;
  };

  const embeddedItemsConverter = (items, translations) => {
    if (!items || !translations || typeof translations !== "object") {
      return items;
    }

    const arr = asItemSourceArray(items);

    for (const [index, item] of arr.entries()) {
      if (!item || typeof item !== "object") continue;

      const itemTranslation = findTranslation(
        item,
        translations,
        index
      );

      if (!itemTranslation || typeof itemTranslation !== "object") {
        continue;
      }

      if (itemTranslation.name !== undefined) {
        item.name = itemTranslation.name;
      }

      if (itemTranslation.description !== undefined) {
        item.system ??= {};

        if (
          typeof itemTranslation.description === "object" &&
          itemTranslation.description !== null &&
          !Array.isArray(itemTranslation.description)
        ) {
          item.system.description = normalizeDescriptionContainer(
            item.system.description
          );

          if (itemTranslation.description.public !== undefined) {
            item.system.description.public =
              itemTranslation.description.public;
          }

          if (itemTranslation.description.private !== undefined) {
            item.system.description.private =
              itemTranslation.description.private;
          }
        } else {
          item.system.description = itemTranslation.description;
        }
      }

      if (
        itemTranslation.actions &&
        Array.isArray(item.system?.actions)
      ) {
        item.system.actions = actionsConverter(
          item.system.actions,
          itemTranslation.actions
        );
      }

      if (
        itemTranslation.effects &&
        Array.isArray(item.effects)
      ) {
        item.effects = itemEffectsConverter(
          item.effects,
          itemTranslation.effects
        );
      }
    }

    return arr;
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

    if (translations.effects) {
      if (obj.effects) {
        obj.effects = itemEffectsConverter(obj.effects, translations.effects);
      } else if (obj.system?.effects) {
        obj.system.effects = itemEffectsConverter(obj.system.effects, translations.effects);
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
    embeddedEffectsConverter: embeddedEffectsConverter,
    item_effects_converter: itemEffectsConverter,
    itemEffectsConverter: itemEffectsConverter,
    embedded_affixes_converter: embeddedAffixesConverter,
    embedded_object_with_actions_converter: embeddedObjectWithActionsConverter,
    embedded_biography_converter: embeddedBiographyConverter,
    nested_object_converter: nestedObjectConverter,
    categories_converter: categoriesConverter,
    active_effect_changes_converter: activeEffectChangesConverter,
    crucible_description_converter: crucibleDescriptionConverter,
  });
});