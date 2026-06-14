const MODULE_ID = "lang-pl-crucible";

const HEROISM_VALUE_PATH = "system.resources.heroism.value";

function isHeroismRerollEnabled() {
  try {
    return game.settings.get(MODULE_ID, "heroism-reroll-enabled");
  } catch (_err) {
    return true;
  }
}

Hooks.once("ready", () => {
  if (game.system.id !== "crucible") return;

  console.log(
    `${MODULE_ID} | Heroism reroll ready; enabled: ${isHeroismRerollEnabled()}`
  );
});

Hooks.on("getChatMessageContextOptions", (_app, options) => {
  if (game.system.id !== "crucible") return;

  options.push({
    label: "Przerzuć za Heroizm",
    name: "Przerzuć za Heroizm",
    icon: '<i class="fa-solid fa-arrows-rotate fa-fw"></i>',

    visible: li => canRerollFromContext(li),
    condition: li => canRerollFromContext(li),

    onClick: async (_event, li) => rerollFromContext(li),
    callback: async li => rerollFromContext(li)
  });
});

function canRerollFromContext(li) {
  if (!isHeroismRerollEnabled()) return false;
  const message = getMessageFromContext(li);
  if (!message?.isRoll) return false;
  if (!message.rolls?.length) return false;
  if (message.getFlag(MODULE_ID, "rerolled")) return false;
  if (!isMessageConfirmedForHeroism(message, li)) return false;

const rolls = getRerollableCrucibleRolls(message);
  if (!rolls.length) return false;

  const actor = getActorForRoll(message, rolls[0]);
  if (!actor) return false;

  if (!canControlActor(actor)) return false;

  const heroism = getHeroism(actor);
  return Number.isFinite(heroism) && heroism > 0;
}

function isMessageConfirmedForHeroism(message, li) {
  /*
   * Crucible oznacza potwierdzone akcje ikoną .confirmed w nagłówku wiadomości.
   * Niepotwierdzona akcja ma przycisk "Potwierdź" oraz/lub ikonę stanu niepotwierdzonego.
   *
   * Dla zwykłych rzutów bez bloku akcji nie blokujemy przerzutu, bo mogą nie mieć
   * mechaniki potwierdzania.
   */

  const element = normalizeElement(li);
  const content = message?.content ?? "";

  const hasActionBlock =
    Boolean(element?.querySelector?.(".crucible.action-roll"))
    || content.includes("crucible action-roll");

  if (!hasActionBlock) return true;

  const hasConfirmedIcon =
    Boolean(element?.querySelector?.(".message-header .confirmed"))
    || content.includes("class=\"confirmed")
    || content.includes("class='confirmed");

  if (hasConfirmedIcon) return true;

  const hasUnconfirmedMarker =
    Boolean(element?.querySelector?.(".message-header .unconfirmed"))
    || Boolean(element?.querySelector?.(".message-header .fa-hexagon-xmark"))
    || Boolean(element?.querySelector?.("[data-action='confirmAction']"))
    || Boolean(element?.querySelector?.("[data-action=\"confirmAction\"]"))
    || Boolean(element?.querySelector?.("button"))
    || content.includes("confirmAction")
    || content.includes("Potwierdź")
    || content.includes("Confirm");

  if (hasUnconfirmedMarker) return false;

  /*
   * Jeżeli to jest karta akcji, ale nie znaleziono potwierdzenia,
   * traktujemy ją ostrożnie jako niepotwierdzoną.
   */
  return false;
}

async function rerollFromContext(li) {
  if (!isHeroismRerollEnabled()) {
    return ui.notifications.warn("Przerzuty za Punkty Heroizmu są obecnie wyłączone w ustawieniach modułu.");
  }
  const message = getMessageFromContext(li);
  if (!message) return ui.notifications.warn("Nie znaleziono wiadomości czatu.");

  if (!isMessageConfirmedForHeroism(message, li)) {
    return ui.notifications.warn("Nie można przerzucić niepotwierdzonej akcji. Najpierw potwierdź akcję w czacie.");
  }

  const rolls = getRerollableCrucibleRolls(message);

  if (!rolls.length) return ui.notifications.warn("Ta wiadomość nie zawiera obsługiwanego rzutu Crucible.");

  const actor = getActorForRoll(message, rolls[0]);
  if (!actor) return ui.notifications.warn("Nie znaleziono aktora przypisanego do rzutu.");

  if (!canControlActor(actor)) {
    return ui.notifications.warn("Nie masz uprawnień do wydania Heroizmu tego aktora.");
  }

  const currentHeroism = getHeroism(actor);
  if (!Number.isFinite(currentHeroism)) {
    return ui.notifications.error(`Nie znaleziono wartości Heroizm pod ścieżką ${HEROISM_VALUE_PATH}.`);
  }

  if (currentHeroism < 1) {
    return ui.notifications.warn(`${actor.name} nie ma dostępnych Punktów Heroizmu.`);
  }

  let spent = false;
  let resourceRollback = null;

  try {
    await actor.update({
      [HEROISM_VALUE_PATH]: currentHeroism - 1
    });
    spent = true;

    const rerolls = [];

    for (const oldRoll of rolls) {
      const newRoll = await createReroll(oldRoll);
      rerolls.push(newRoll);
    }

    const attackCount = rerolls.filter(r => isAttackRoll(r, r.data ?? {})).length;

    for (let i = 0; i < rerolls.length; i++) {
      rerolls[i].data.index = i;

      if (isAttackRoll(rerolls[i], rerolls[i].data ?? {})) {
        rerolls[i].data.newTarget = attackCount > 1;
      }
    }

    const resourceChange = await applyRerollAttackResourcesForRolls(rolls, rerolls);
    resourceRollback = resourceChange?.rollback ?? null;

    const actionHtml = getOriginalActionHtml(message, li);
    const oldFlavor = message.flavor ?? rolls[0].options?.flavor ?? "";

    const flavor = [
      actionHtml || oldFlavor,
      `<hr>`,
      `<p><strong>Przerzut za Heroizm</strong></p>`,
      formatRerollTotals(rolls, rerolls),
      formatResourceChange(resourceChange)
    ].filter(Boolean).join("");

    const newMessage = await ChatMessage.create({
      speaker: message.speaker ?? ChatMessage.getSpeaker({ actor }),
      flavor,
      rolls: rerolls,
      ...(CONST.CHAT_MESSAGE_STYLES?.ROLL != null ? { style: CONST.CHAT_MESSAGE_STYLES.ROLL } : {}),
      flags: {
        [MODULE_ID]: {
          type: "heroism-reroll",
          originalMessageId: message.id,
          originalRollTotals: rolls.map(r => Number.isFinite(r.total) ? r.total : null),
          newRollTotals: rerolls.map(r => Number.isFinite(r.total) ? r.total : null),
          actorId: actor.id,
          userId: game.user.id,
          timestamp: Date.now()
        }
      }
    }, {
      messageMode: rolls[0].data?.messageMode
    });

    await message.setFlag(MODULE_ID, "rerolled", {
      rerollMessageId: newMessage.id,
      actorId: actor.id,
      userId: game.user.id,
      timestamp: Date.now()
    });

    ui.notifications.info(`${actor.name}: wydano 1 Punkt Heroizmu i wykonano przerzut dla ${rolls.length} ${rolls.length === 1 ? "rzutu" : "rzutów"}.`);
  } catch (err) {
    console.error(`${MODULE_ID} | Reroll failed`, err);

    if (resourceRollback) {
      await resourceRollback();
    }

    if (spent) {
      await actor.update({
        [HEROISM_VALUE_PATH]: currentHeroism
      });
    }

    ui.notifications.error("Nie udało się wykonać przerzutu za Heroizm. Szczegóły są w konsoli.");
  }
}

async function createReroll(oldRoll) {
  const diceApi = game.crucible?.api?.dice ?? crucible?.api?.dice;
  const StandardCheck = diceApi?.StandardCheck;
  const AttackRoll = diceApi?.AttackRoll;

  if (!StandardCheck) throw new Error("Brak crucible.api.dice.StandardCheck.");

  const oldData = foundry.utils.deepClone(oldRoll.data ?? {});
  const oldDamage = foundry.utils.deepClone(oldData.damage ?? {});

  const isAttack = isAttackRoll(oldRoll, oldData) && AttackRoll;
  const RollClass = isAttack ? AttackRoll : StandardCheck;

  delete oldData.result;
  delete oldData.damage;

  const reroll = new RollClass(oldData);
  await reroll.evaluate({
    allowInteractive: oldData.messageMode !== "blind"
  });

  if (isAttack) {
    await resolveAttackReroll(reroll, oldData, oldDamage, AttackRoll);
  }

  return reroll;
}

async function resolveAttackReroll(reroll, rollData, oldDamage, AttackRoll) {
  const RESULTS = AttackRoll.RESULT_TYPES;

  const actor = game.actors.get(rollData.actorId);
  const targetDocument = rollData.target ? await fromUuid(rollData.target) : null;
  const target = targetDocument?.actor ?? targetDocument ?? null;

  const defenseType = rollData.defenseType || "physical";

  if (target?.testDefense instanceof Function) {
    reroll.data.result = target.testDefense(defenseType, reroll);
  } else {
    reroll.data.result = Number.isFinite(rollData.dc) && reroll.total > rollData.dc
      ? RESULTS.HIT
      : RESULTS.MISS;
  }

  if (!Object.values(RESULTS).includes(reroll.data.result)) {
    reroll.data.result = RESULTS.MISS;
    delete reroll.data.damage;
    return;
  }

  if (reroll.data.result < RESULTS.GLANCE) {
    delete reroll.data.damage;
    return;
  }

  reroll.data.damage = buildRerollDamageData({
    actor,
    target,
    rollData,
    oldDamage,
    reroll
  });
}

async function getTargetActorFromUuid(uuid) {
  if (!uuid) return null;

  try {
    const document = await fromUuid(uuid);
    return document?.actor ?? document ?? null;
  } catch (err) {
    console.warn(`${MODULE_ID} | Nie udało się pobrać celu ataku`, err);
    return null;
  }
}

function getCurrentDefenseDC(target, defenseType, fallback) {
  if (!target) return fallback;

  if (defenseType === "physical") {
    return target.defenses?.physical?.total
      ?? target.system?.defenses?.physical?.total
      ?? fallback;
  }

  if (target.defenses?.[defenseType]) {
    return target.defenses[defenseType].total ?? fallback;
  }

  if (target.skills?.[defenseType]) {
    return target.skills[defenseType].passive ?? fallback;
  }

  return fallback;
}

function getBaseDamage(actor, rollData, oldDamage) {
  if (Number.isFinite(oldDamage.base)) return oldDamage.base;

  const item = rollData.itemId ? actor?.items?.get(rollData.itemId) : null;
  const weaponBase = Number(item?.system?.damage?.weapon);

  if (Number.isFinite(weaponBase)) return weaponBase;

  return 0;
}

function getBonusDamage(actor, rollData, oldDamage) {
  if (Number.isFinite(oldDamage.bonus)) return oldDamage.bonus;

  const item = rollData.itemId ? actor?.items?.get(rollData.itemId) : null;
  const weaponBonus = Number(item?.system?.damage?.bonus ?? 0);
  const rollBonus = Number(rollData.damageBonus ?? 0);

  return weaponBonus + rollBonus;
}

function getNumeric(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }

  return 0;
}

function getFirstCrucibleRoll(message) {
  return getRerollableCrucibleRolls(message)[0] ?? null;
}

function getRerollableCrucibleRolls(message) {
  const rolls = (message.rolls ?? []).filter(isCrucibleRoll);

  /*
   * Jeżeli wiadomość zawiera kilka AttackRoll, jest to zwykle jedna akcja
   * przeciwko wielu celom. W takim przypadku przerzucamy wszystkie ataki,
   * a nie tylko pierwszy wpis z tablicy message.rolls.
   */
  const attackRolls = rolls.filter(roll => isAttackRoll(roll, roll.data ?? {}));
  return attackRolls.length ? attackRolls : rolls;
}

function isCrucibleRoll(roll) {
  const data = roll?.data;
  if (!data?.actorId) return false;

  const className = roll.constructor?.name;
  if (className === "StandardCheck") return true;
  if (className === "AttackRoll") return true;

  return ("totalBoons" in data) || ("totalBanes" in data) || ("dc" in data);
}

function isAttackRoll(roll, data) {
  if (roll.constructor?.name === "AttackRoll") return true;

  return Boolean(
    data?.target
    || data?.defenseType
    || data?.damageType
    || data?.damage
    || data?.itemId
  );
}

function getActorForRoll(message, roll) {
  const actorId = roll.data?.actorId ?? message.speaker?.actor;

  let actor = actorId ? game.actors.get(actorId) : null;
  if (actor) return actor;

  const sceneId = message.speaker?.scene;
  const tokenId = message.speaker?.token;

  if (sceneId && tokenId) {
    const scene = game.scenes.get(sceneId);
    const token = scene?.tokens.get(tokenId);
    actor = token?.actor;
  }

  return actor ?? null;
}

function getHeroism(actor) {
  return Number(foundry.utils.getProperty(actor, HEROISM_VALUE_PATH));
}

function canControlActor(actor) {
  return game.user.isGM || actor.testUserPermission(game.user, "OWNER");
}

function getMessageFromContext(li) {
  const element = normalizeElement(li);
  const messageId = element?.dataset?.messageId
    ?? element?.closest?.("[data-message-id]")?.dataset?.messageId;

  return messageId ? game.messages.get(messageId) : null;
}

function normalizeElement(li) {
  if (li instanceof HTMLElement) return li;
  if (li?.[0] instanceof HTMLElement) return li[0];
  if (li?.currentTarget instanceof HTMLElement) return li.currentTarget;
  return null;
}

async function applyRerollAttackResources(oldRoll, newRoll) {
  return applyRerollAttackResourcesForRolls([oldRoll], [newRoll]);
}

async function applyRerollAttackResourcesForRolls(oldRolls, newRolls) {
  const pairs = [];

  for (let i = 0; i < oldRolls.length; i++) {
    const oldRoll = oldRolls[i];
    const newRoll = newRolls[i];

    if (!oldRoll || !newRoll) continue;
    if (!isAttackRoll(oldRoll, oldRoll.data ?? {})) continue;

    const target = await getTargetActorFromRollData(oldRoll.data ?? newRoll.data ?? {});

    if (!target) {
      pairs.push({
        oldRoll,
        newRoll,
        target: null,
        warning: "Nie znaleziono celu ataku, więc PW nie zostało zmienione."
      });
      continue;
    }

    if (!(game.user.isGM || target.testUserPermission(game.user, "OWNER"))) {
      throw new Error(
        `Brak uprawnień do zmiany zasobów celu "${target.name}". ` +
        `Uruchom przerzut jako MG albo dodaj obsługę socketu MG.`
      );
    }

    pairs.push({ oldRoll, newRoll, target });
  }

  if (!pairs.length) return null;

  const snapshots = [];
  const uniqueTargets = new Map();

  for (const pair of pairs) {
    if (!pair.target) continue;
    const key = pair.target.uuid ?? pair.target.id;

    if (!uniqueTargets.has(key)) {
      uniqueTargets.set(key, pair.target);
      snapshots.push(snapshotActorResources(pair.target));
    }
  }

  const rollback = async () => {
    for (let i = snapshots.length - 1; i >= 0; i--) {
      await snapshots[i]();
    }
  };

  const results = [];
  const warnings = [];

  try {
    for (const pair of pairs) {
      if (!pair.target) {
        warnings.push(pair.warning);
        continue;
      }

      const restored = await restorePreviousAttackDamage(pair.target, pair.oldRoll.data?.damage);
      const applied = await applyNewAttackDamage(pair.target, pair.newRoll.data?.damage);

      results.push({
        targetName: pair.target.name,
        targetUuid: pair.target.uuid,
        oldTotal: Number.isFinite(pair.oldRoll.total) ? pair.oldRoll.total : null,
        newTotal: Number.isFinite(pair.newRoll.total) ? pair.newRoll.total : null,
        restored,
        applied
      });
    }

    return {
      targets: results,
      warnings,
      rollback
    };
  } catch (err) {
    await rollback();
    throw err;
  }
}

async function getTargetActorFromRollData(rollData) {
  if (!rollData?.target) return null;

  try {
    const document = await fromUuid(rollData.target);
    return document?.actor ?? document ?? null;
  } catch (err) {
    console.warn(`${MODULE_ID} | Nie udało się znaleźć celu ataku`, err);
    return null;
  }
}

function snapshotActorResources(actor) {
  const updates = {};

  for (const [id, resource] of Object.entries(actor.system.resources ?? {})) {
    updates[`system.resources.${id}.value`] = resource.value;
  }

  return async () => actor.update(updates, { scrollingText: false });
}

async function restorePreviousAttackDamage(target, damage) {
  const total = getDamageTotal(damage);
  const resource = damage?.resource ?? "health";
  const restoration = Boolean(damage?.restoration);

  if (!total) {
    return {
      resource,
      total: 0,
      restoration
    };
  }

  if (!restoration && ["health", "morale"].includes(resource)) {
    await restoreActiveDamageWithReserve(target, resource, total);
  } else {
    const oldDelta = getSignedResourceDelta(damage);
    await applyResourceDeltaDirect(target, resource, -oldDelta);
  }

  return {
    resource,
    total,
    restoration
  };
}

async function applyNewAttackDamage(target, damage) {
  const total = getDamageTotal(damage);
  const resource = damage?.resource ?? "health";
  const restoration = Boolean(damage?.restoration);

  if (!total) {
    return {
      resource,
      total: 0,
      restoration
    };
  }

  const delta = getSignedResourceDelta(damage);

  if (target.alterResources instanceof Function) {
    await target.alterResources({
      [resource]: delta
    });
  } else {
    await applyResourceDeltaDirect(target, resource, delta);
  }

  return {
    resource,
    total,
    restoration,
    delta
  };
}

function getDamageTotal(damage) {
  const total = Number(damage?.total ?? 0);
  if (!Number.isFinite(total)) return 0;
  return Math.max(0, total);
}

function getSignedResourceDelta(damage) {
  const total = getDamageTotal(damage);
  const resource = damage?.resource ?? "health";
  const restoration = Boolean(damage?.restoration);

  const reserveResource = ["wounds", "madness"].includes(resource);

  if (restoration) {
    return reserveResource ? -total : total;
  }

  return reserveResource ? total : -total;
}

async function restoreActiveDamageWithReserve(actor, activeResource, total) {
  const resources = actor.system.resources ?? {};
  const reserveResource = activeResource === "health"
    ? "wounds"
    : activeResource === "morale"
      ? "madness"
      : null;

  let remaining = total;
  const updates = {};

  const active = resources[activeResource];
  if (!active) return;

  const activeValue = Number(active.value ?? 0);

  if (
    reserveResource
    && actor.system.usesReserveResources
    && resources[reserveResource]
    && activeValue <= 0
  ) {
    const reserve = resources[reserveResource];
    const reserveValue = Number(reserve.value ?? 0);
    const reserveMax = Number(reserve.max ?? 999999);

    const reserveRestore = Math.min(remaining, reserveValue);

    if (reserveRestore > 0) {
      updates[`system.resources.${reserveResource}.value`] = Math.clamp(
        reserveValue - reserveRestore,
        0,
        reserveMax
      );

      remaining -= reserveRestore;
    }
  }

  if (remaining > 0) {
    const activeMax = Number(active.max ?? 999999);

    updates[`system.resources.${activeResource}.value`] = Math.clamp(
      activeValue + remaining,
      0,
      activeMax
    );
  }

  if (Object.keys(updates).length) {
    await actor.update(updates);
  }
}

async function applyResourceDeltaDirect(actor, resourceName, delta) {
  const resource = actor.system.resources?.[resourceName];
  if (!resource) return;

  const value = Number(resource.value ?? 0);
  const max = Number(resource.max ?? 999999);

  await actor.update({
    [`system.resources.${resourceName}.value`]: Math.clamp(value + delta, 0, max)
  });
}

function formatResourceChange(change) {
  if (!change) return "";

  const parts = [];

  if (change.warning) {
    parts.push(`<p><em>${escapeHtml(change.warning)}</em></p>`);
  }

  for (const warning of change.warnings ?? []) {
    parts.push(`<p><em>${escapeHtml(warning)}</em></p>`);
  }

  const targets = change.targets ?? [];

  if (targets.length === 1) {
    const target = targets[0];
    const restored = formatDamageEffect(target.restored);
    const applied = formatDamageEffect(target.applied);

    parts.push([
      `<p>Przywrócono poprzedni efekt: <strong>${restored}</strong>.</p>`,
      `<p>Zastosowano nowy efekt: <strong>${applied}</strong>.</p>`
    ].join(""));
  } else if (targets.length > 1) {
    const rows = targets.map(target => {
      const restored = formatDamageEffect(target.restored);
      const applied = formatDamageEffect(target.applied);

      return `<li><strong>${escapeHtml(target.targetName ?? "cel")}</strong>: przywrócono ${restored}; zastosowano ${applied}.</li>`;
    });

    parts.push([
      `<p><strong>Cele objęte przerzutem:</strong> ${targets.length}</p>`,
      `<ul>${rows.join("")}</ul>`
    ].join(""));
  }

  return parts.join("");
}

function formatDamageEffect(effect) {
  if (!effect || !effect.total) return "0";

  const type = effect.restoration ? "przywrócenia" : "obrażeń";
  return `${effect.total} ${type}`;
}

function formatRerollTotals(oldRolls, newRolls) {
  if (oldRolls.length === 1) {
    const oldTotal = Number.isFinite(oldRolls[0].total) ? oldRolls[0].total : "—";
    const newTotal = Number.isFinite(newRolls[0].total) ? newRolls[0].total : "—";

    return `<p>Poprzedni wynik: <strong>${oldTotal}</strong>. Nowy wynik: <strong>${newTotal}</strong>.</p>`;
  }

  const rows = oldRolls.map((oldRoll, index) => {
    const newRoll = newRolls[index];
    const oldTotal = Number.isFinite(oldRoll.total) ? oldRoll.total : "—";
    const newTotal = Number.isFinite(newRoll?.total) ? newRoll.total : "—";
    const targetName = getRollTargetName(oldRoll);

    return `<li><strong>${escapeHtml(targetName)}</strong>: ${oldTotal} → ${newTotal}</li>`;
  });

  return [
    `<p>Przerzucono wyniki dla <strong>${oldRolls.length}</strong> celów.</p>`,
    `<ul>${rows.join("")}</ul>`
  ].join("");
}

function getRollTargetName(roll) {
  const uuid = roll?.data?.target;
  if (!uuid) return "cel";

  try {
    const document = foundry.utils.fromUuidSync?.(uuid);
    const actor = document?.actor ?? document;
    return actor?.name ?? uuid;
  } catch (_err) {
    return uuid;
  }
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value ?? "");
  return div.innerHTML;
}

function buildRerollDamageData({ actor, target, rollData, oldDamage = {}, reroll }) {
  const item = rollData.itemId ? actor?.items?.get(rollData.itemId) : null;

  const resource = rollData.resource
    ?? oldDamage.resource
    ?? "health";

  const damageType = getValidDamageType(
    rollData.damageType,
    oldDamage.type,
    item?.system?.damageType,
    item?.system?.damage?.type,
    item?.system?.damage?.damageType,
    item?.system?.damage?.kind,
    "slashing"
  );

  const restoration = Boolean(oldDamage.restoration);

  const base = getFirstFiniteNumber(
    oldDamage.base,
    item?.system?.damage?.weapon,
    item?.system?.damage?.base,
    0
  );

  const bonus = getFirstFiniteNumber(
    oldDamage.bonus,
    Number(item?.system?.damage?.bonus ?? 0) + Number(rollData.damageBonus ?? 0),
    rollData.damageBonus,
    0
  );

  const multiplier = getFirstFiniteNumber(
    rollData.multiplier,
    oldDamage.multiplier,
    1
  );

  const resistance = damageType && target?.getResistance instanceof Function
    ? target.getResistance(resource, damageType, restoration)
    : 0;

  const damage = {
    overflow: Number.isFinite(reroll.overflow) ? reroll.overflow : 0,
    multiplier,
    base,
    bonus,
    resistance,
    resource,
    restoration
  };

  if (damageType) {
    damage.type = damageType;
  }

  damage.total = computeCrucibleDamageSafe(damage);

  if (!Number.isFinite(damage.total)) {
    damage.total = 0;
  }

  damage.total = Math.max(0, damage.total);

  return damage;
}

function getFirstFiniteNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }

  return 0;
}

function computeCrucibleDamageSafe(damage) {
  const computeDamage =
    game.crucible?.api?.models?.CrucibleAction?.computeDamage
    ?? globalThis.crucible?.api?.models?.CrucibleAction?.computeDamage;

  if (computeDamage instanceof Function) {
    return computeDamage(damage);
  }

  let multiplier = damage.multiplier ?? 1;

  if ((damage.overflow ?? 0) < 0) {
    multiplier = Math.max(multiplier, 1);
  }

  const preMitigation =
    ((damage.overflow ?? 0) * multiplier)
    + (damage.base ?? 0)
    + (damage.bonus ?? 0);

  if (preMitigation <= 0) return 0;

  const postMitigation = damage.restoration
    ? preMitigation
    : preMitigation - (damage.resistance ?? 0);

  return Math.clamp(postMitigation, 0, 2 * preMitigation);
}

function getOriginalActionHtml(message, li) {
  const element = normalizeElement(li);

  const renderedAction = element?.querySelector?.(
    ".message-content > .crucible.action-roll, .message-content .crucible.action-roll"
  );

  if (renderedAction) return renderedAction.outerHTML;

  const wrapper = document.createElement("div");
  wrapper.innerHTML = message.content ?? "";

  const action = wrapper.querySelector(".crucible.action-roll");
  return action?.outerHTML ?? "";
}

function getValidDamageType(...candidates) {
  const damageTypes = getCrucibleDamageTypes();

  for (const candidate of candidates) {
    const type = normalizeDamageType(candidate);
    if (!type) continue;

    if (damageTypes?.[type]) {
      return type;
    }

    if (!damageTypes && isKnownCrucibleDamageType(type)) {
      return type;
    }
  }

  const fallback = damageTypes
    ? Object.keys(damageTypes)[0]
    : undefined;

  return fallback ?? undefined;
}

function getCrucibleDamageTypes() {
  return globalThis.SYSTEM?.DAMAGE_TYPES
    ?? CONFIG?.CRUCIBLE?.DAMAGE_TYPES
    ?? CONFIG?.Crucible?.damageTypes
    ?? game.crucible?.config?.damageTypes
    ?? null;
}

function normalizeDamageType(value) {
  if (!value) return null;

  if (typeof value === "object") {
    value = value.id ?? value.type ?? value.value ?? value.slug ?? value.key;
  }

  if (typeof value !== "string") return null;

  const type = value.trim().toLowerCase();

  const aliases = {
    cut: "slashing",
    cutting: "slashing",
    ciete: "slashing",
    "cięte": "slashing",

    pierce: "piercing",
    pierced: "piercing",
    klute: "piercing",
    "kłute": "piercing",

    blunt: "bludgeoning",
    crushing: "bludgeoning",
    obuchowe: "bludgeoning",

    electric: "electricity",
    lightning: "electricity",

    flame: "fire",
    frost: "cold",

    necrotic: "void",
    radiant: "radiant"
  };

  return aliases[type] ?? type;
}

function isKnownCrucibleDamageType(type) {
  return [
    "acid",
    "bludgeoning",
    "cold",
    "corruption",
    "electricity",
    "fire",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "spiritual",
    "void"
  ].includes(type);
}