const MODULE_ID = "lang-pl-crucible";

const HEROISM_VALUE_PATH = "system.resources.heroism.value";

const SOCKET_NAME = `module.${MODULE_ID}`;
const SOCKET_TIMEOUT_MS = 60000;
const PENDING_GM_REQUESTS = new Map();
const HEROISM_REROLL_REJECTED = "HEROISM_REROLL_REJECTED";

function isHeroismRerollEnabled() {
  try {
    return game.settings.get(MODULE_ID, "heroism-reroll-enabled");
  } catch (_err) {
    return true;
  }
}

registerHeroismRerollChatStyling();

Hooks.once("ready", () => {
  if (game.system.id !== "crucible") return;

  registerHeroismRerollSocket();
  styleExistingHeroismRerollChatMessages();

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
  if (!message) return false;

  const rolls = getRerollableCrucibleRolls(message);
  if (!rolls.length) return false;

  if (!message.getFlag("crucible", "action")) return false;
  if (message.getFlag(MODULE_ID, "rerolled")) return false;

  if (!isMessageConfirmedForHeroism(message, li)) return false;

  const actor = getActorForHeroismMessage(message, rolls[0]);
  if (!actor) return false;

  if (!canControlHeroismActor(actor, message)) return false;

  const heroism = getHeroism(actor);
  return Number.isFinite(heroism) && heroism > 0;
}

function isMessageConfirmedForHeroism(message, li) {
  const messageElement = getMessageElementFromContext(li);

  /*
   * Jeżeli DOM pokazuje przycisk potwierdzenia, karta jest niepotwierdzona.
   * To jest jedyny twardy przypadek, w którym ukrywamy opcję.
   */
  const hasConfirmControl =
    messageElement?.querySelector?.("[data-action='confirmAction']")
    || messageElement?.querySelector?.("[data-action=\"confirmAction\"]")
    || messageElement?.querySelector?.("[data-action='confirm']")
    || messageElement?.querySelector?.("[data-action=\"confirm\"]")
    || messageElement?.textContent?.includes("Potwierdź")
    || messageElement?.textContent?.includes("Confirm");

  if (hasConfirmControl) return false;

  /*
   * Jeżeli widać ikonę potwierdzenia, karta jest potwierdzona.
   */
  const hasConfirmedIcon =
    messageElement?.querySelector?.(".message-header .confirmed")
    || messageElement?.querySelector?.(".message-header .fa-hexagon-check");

  if (hasConfirmedIcon) return true;

  /*
   * Nie blokuj gracza tylko dlatego, że jego DOM wiadomości nie zawiera ikony.
   * Wystarczy, że wiadomość jest akcją Crucible i nie ma widocznego przycisku potwierdzenia.
   */
  return Boolean(message?.getFlag("crucible", "action"));
}

function getMessageElementFromContext(li) {
  const element = normalizeElement(li);
  if (!element) return null;

  if (element.matches?.("[data-message-id]")) return element;

  return element.closest?.("[data-message-id]") ?? null;
}

async function rerollFromContext(li) {
  if (!isHeroismRerollEnabled()) {
    return ui.notifications.warn("Przerzuty za Punkty Heroizmu są obecnie wyłączone w ustawieniach modułu.");
  }

  const message = getMessageFromContext(li);
  if (!message) return ui.notifications.warn("Nie znaleziono wiadomości czatu.");

  if (!message.getFlag("crucible", "action")) {
    return ui.notifications.warn("Ten tryb przerzutu działa tylko na wiadomościach akcji Crucible.");
  }

  if (!isMessageConfirmedForHeroism(message, li)) {
    return ui.notifications.warn("Nie można przerzucić niepotwierdzonej akcji. Najpierw potwierdź akcję w czacie.");
  }

  const actor = getActorForHeroismMessage(message, getFirstCrucibleRoll(message));
  if (!actor) return ui.notifications.warn("Nie znaleziono aktora przypisanego do akcji.");

  if (!canControlHeroismActor(actor, message)) {
    return ui.notifications.warn("Nie masz uprawnień do wydania Heroizmu tego aktora.");
  }

  const currentHeroism = getHeroism(actor);
  if (!Number.isFinite(currentHeroism)) {
    return ui.notifications.error(`Nie znaleziono wartości Heroizmu pod ścieżką ${HEROISM_VALUE_PATH}.`);
  }

  if (currentHeroism < 1) {
    return ui.notifications.warn(`${actor.name} nie ma dostępnych Punktów Heroizmu.`);
  }

  const ActionClass = getCrucibleActionClass();
  if (!ActionClass) {
    return ui.notifications.error("Nie znaleziono klasy CrucibleAction w API systemu Crucible.");
  }

  const previousTargets = captureUserTargets();
  let spent = false;
  let reversed = false;

  try {
    const originalAction = ActionClass.fromChatMessage(message);
    if (!originalAction) {
      return ui.notifications.warn("Nie udało się odtworzyć akcji z wiadomości czatu.");
    }

    await actor.update({
      [HEROISM_VALUE_PATH]: currentHeroism - 1
    });
    spent = true;

    /*
     * Cofamy starą potwierdzoną akcję tym samym mechanizmem,
     * którego używa Crucible przy wycofaniu. To powinno cofnąć
     * obrażenia, efekty, aktualizacje aktorów i inne eventy akcji.
     */
    await confirmCrucibleActionMessage(message, {
      action: originalAction,
      reverse: true,
      requireApproval: !game.user.isGM
    });
    reversed = true;

    /*
     * Przywracamy cele z oryginalnej akcji jako aktualne targety.
     * Dialog Crucible nadal pozwoli zmienić konfigurację przed rzutem.
     */
    restoreTargetsFromAction(originalAction);

    /*
     * Uruchamiamy pełny cykl CrucibleAction#use().
     * To jest kluczowe dla efektów warunkowych, np. Płonący po krytyku.
     */
    const replayAction = await originalAction.use({
      token: getActionTokenDocument(originalAction, message),
      dialog: true,
      chatMessageOptions: {
        flags: {
          [MODULE_ID]: {
            heroismReroll: true,
            originalMessageId: message.id,
            actorId: actor.id,
            userId: game.user.id,
            timestamp: Date.now()
          }
        }
      }
    });

    if (!replayAction) {
      await confirmCrucibleActionMessage(message, {
        action: ActionClass.fromChatMessage(message),
        reverse: false,
        requireApproval: false
      });
      reversed = false;

      await actor.update({
        [HEROISM_VALUE_PATH]: currentHeroism
      });
      spent = false;

      ui.notifications.warn("Przerzut anulowany. Oryginalna akcja została przywrócona, a Punkt Heroizmu zwrócony.");
      return;
    }

    try {
      await setOriginalMessageRerolledFlag(message, actor);
    } catch (err) {
      console.warn(`${MODULE_ID} | Nie udało się oznaczyć oryginalnej wiadomości jako przerzuconej`, err);
    }

    await ChatMessage.create({
      speaker: message.speaker ?? ChatMessage.getSpeaker({ actor }),
      content: buildHeroismRerollChatContent({
        message,
        actor,
        status: "accepted"
      }),
      flags: {
        [MODULE_ID]: {
          type: "heroism-reroll-note",
          status: "accepted",
          originalMessageId: message.id,
          actorId: actor.id,
          userId: game.user.id,
          timestamp: Date.now()
        }
      }
    });

  } catch (err) {
    const rejectedByGM = err?.code === HEROISM_REROLL_REJECTED;

    if (!rejectedByGM) {
      console.error(`${MODULE_ID} | Heroism action replay failed`, err);
    }

    if (reversed) {
      try {
        await confirmCrucibleActionMessage(message, {
          action: ActionClass.fromChatMessage(message),
          reverse: false,
          requireApproval: false
        });
      } catch (restoreErr) {
        console.error(`${MODULE_ID} | Nie udało się przywrócić oryginalnej akcji po błędzie`, restoreErr);
      }
    }

    if (spent) {
      try {
        await actor.update({
          [HEROISM_VALUE_PATH]: currentHeroism
        });
      } catch (refundErr) {
        console.error(`${MODULE_ID} | Nie udało się zwrócić Punktu Heroizmu po błędzie`, refundErr);
      }
    }

    if (!rejectedByGM) {
      ui.notifications.error("Nie udało się wykonać przerzutu przez ponowne uruchomienie akcji. Szczegóły są w konsoli.");
    }
  } finally {
    restoreUserTargets(previousTargets);
  }
}

function getCrucibleActionClass() {
  return game.system?.api?.models?.CrucibleAction
    ?? game.crucible?.api?.models?.CrucibleAction
    ?? globalThis.crucible?.api?.models?.CrucibleAction
    ?? null;
}

function getActorForActionMessage(message) {
  const actorUuid = message.getFlag("crucible", "actor");

  if (actorUuid) {
    try {
      const actor = foundry.utils.fromUuidSync?.(actorUuid) ?? fromUuidSync(actorUuid);
      if (actor) return actor;
    } catch (_err) { }
  }

  return ChatMessage.getSpeakerActor(message.speaker);
}

function getActorForHeroismMessage(message, roll = null) {
  return getActorForActionMessage(message)
    ?? getActorFromMessageSpeaker(message)
    ?? getActorForRoll(message, roll)
    ?? null;
}

function getActorFromMessageSpeaker(message) {
  if (!message?.speaker) return null;

  const speakerActor = ChatMessage.getSpeakerActor?.(message.speaker);
  if (speakerActor) return speakerActor;

  const scene = message.speaker.scene ? game.scenes.get(message.speaker.scene) : null;
  const tokenDocument = scene && message.speaker.token ? scene.tokens.get(message.speaker.token) : null;

  return tokenDocument?.actor ?? null;
}

function getTokenDocumentFromMessage(message) {
  const tokenUuid = message.getFlag("crucible", "token");

  if (tokenUuid) {
    try {
      const token = foundry.utils.fromUuidSync?.(tokenUuid) ?? fromUuidSync(tokenUuid);
      if (token) return token;
    } catch (_err) {}
  }

  const scene = message.speaker?.scene ? game.scenes.get(message.speaker.scene) : null;
  if (!scene || !message.speaker?.token) return null;

  return scene.tokens.get(message.speaker.token) ?? null;
}

function getActionTokenDocument(action, message) {
  if (action?.token) return action.token;

  const tokenUuid = message.getFlag("crucible", "token");
  if (!tokenUuid) return null;

  try {
    return foundry.utils.fromUuidSync?.(tokenUuid) ?? fromUuidSync(tokenUuid);
  } catch (_err) {
    return null;
  }
}

function captureUserTargets() {
  return Array.from(game.user.targets ?? [])
    .map(token => token.document?.uuid ?? token.id)
    .filter(Boolean);
}

function restoreUserTargets(tokenRefs) {
  setUserTargets(tokenRefs ?? []);
}

function restoreTargetsFromAction(action) {
  const tokenRefs = [];

  for (const target of action?.targets?.values?.() ?? []) {
    const token =
      target.token?.object
      ?? getCanvasTokenFromUuid(target.token?.uuid)
      ?? getCanvasTokenFromUuid(target.document?.uuid)
      ?? getCanvasTokenFromActor(target.actor ?? target)
      ?? null;

    const ref = token?.document?.uuid ?? token?.id;
    if (ref) tokenRefs.push(ref);
  }

  if (!tokenRefs.length) return;

  setUserTargets(tokenRefs);
}

function setUserTargets(tokenRefs) {
  if (!canvas?.tokens) return;

  const wanted = new Set((tokenRefs ?? []).filter(Boolean));

  for (const token of canvas.tokens.placeables ?? []) {
    const refs = [
      token.id,
      token.document?.id,
      token.document?.uuid,
      token.actor?.id,
      token.actor?.uuid
    ].filter(Boolean);

    const shouldTarget = refs.some(ref => wanted.has(ref));
    const isTargeted = game.user.targets?.has(token) ?? false;

    if (shouldTarget === isTargeted) continue;

    token.setTarget(shouldTarget, {
      user: game.user,
      releaseOthers: false,
      groupSelection: true
    });
  }
}

function getCanvasTokenFromUuid(uuid) {
  if (!uuid || !canvas?.tokens) return null;

  try {
    const document = foundry.utils.fromUuidSync?.(uuid) ?? fromUuidSync(uuid);
    return document?.object
      ?? canvas.tokens.placeables?.find(token => token.document?.uuid === uuid)
      ?? null;
  } catch (_err) {
    return canvas.tokens.placeables?.find(token => token.document?.uuid === uuid) ?? null;
  }
}

function getCanvasTokenFromActor(actor) {
  if (!actor || !canvas?.tokens) return null;

  const actorUuid = actor.uuid;
  const actorId = actor.id;

  return canvas.tokens.placeables?.find(token => {
    return token.actor?.uuid === actorUuid || token.actor?.id === actorId;
  }) ?? null;
}

async function confirmCrucibleActionMessage(message, {
  action = null,
  reverse = false,
  requireApproval = reverse
} = {}) {
  const ActionClass = getCrucibleActionClass();
  if (!ActionClass) throw new Error("Nie znaleziono klasy CrucibleAction.");

  if (game.user.isGM) {
    await ActionClass.confirmMessage(message, {
      action,
      reverse
    });
    return;
  }

  await requestPrimaryGM("confirmActionMessage", {
    messageId: message.id,
    reverse,
    requireApproval
  });
}

function registerHeroismRerollSocket() {
  if (!game.socket) return;

  game.socket.on(SOCKET_NAME, async payload => {
    if (!payload?.type) return;

    if (payload.type === "gmResponse") {
      handleGMResponse(payload);
      return;
    }

    if (!game.user.isGM || !isPrimaryActiveGM()) return;
    if (payload.gmId && payload.gmId !== game.user.id) return;

    try {
      if (payload.type === "setRerolledFlag") {
        const message = game.messages.get(payload.messageId);
        if (!message) throw new Error("Nie znaleziono wiadomości do oznaczenia jako przerzuconej.");

        const actor = getActorForHeroismMessage(message, getFirstCrucibleRoll(message));
        const requestingUser = game.users.get(payload.requestingUserId);

        if (actor && requestingUser && !canUserControlHeroismActor(requestingUser, actor, message)) {
          throw new Error(`Użytkownik ${requestingUser.name} nie ma uprawnień właściciela do aktora "${actor.name}".`);
        }

        await message.setFlag(MODULE_ID, "rerolled", {
          mode: "replay-action",
          actorId: payload.actorId,
          userId: payload.requestingUserId,
          timestamp: Date.now()
        });

        sendGMResponse(payload, {
          ok: true,
          result: true
        });

        return;
      }

      if (payload.type !== "confirmActionMessage") return;

      const message = game.messages.get(payload.messageId);
      if (!message) throw new Error("Nie znaleziono wiadomości akcji do potwierdzenia/cofnięcia.");

      const actor = getActorForHeroismMessage(message, getFirstCrucibleRoll(message));
      const requestingUser = game.users.get(payload.requestingUserId);

      if (actor && requestingUser && !canUserControlHeroismActor(requestingUser, actor, message)) {
        throw new Error(`Użytkownik ${requestingUser.name} nie ma uprawnień właściciela do aktora "${actor.name}".`);
      }

      if (payload.requireApproval !== false) {
        const approved = await showGMHeroismRerollDialog({
          message,
          actor,
          requestingUser,
          reverse: Boolean(payload.reverse)
        });

        if (!approved) {
          await ChatMessage.create({
            speaker: message.speaker ?? ChatMessage.getSpeaker({ actor }),
            content: buildHeroismRerollChatContent({
              message,
              actor,
              status: "rejected"
            }),
            flags: {
              [MODULE_ID]: {
                type: "heroism-reroll-note",
                status: "rejected",
                originalMessageId: message.id,
                actorId: actor?.id,
                userId: payload.requestingUserId,
                gmId: game.user.id,
                timestamp: Date.now()
              }
            }
          });

          sendGMResponse(payload, {
            ok: false,
            code: HEROISM_REROLL_REJECTED,
            error: "MG odrzucił prośbę o przerzut za Heroizm."
          });

          return;
        }
      }

      const ActionClass = getCrucibleActionClass();
      if (!ActionClass) throw new Error("Nie znaleziono klasy CrucibleAction.");

      const action = ActionClass.fromChatMessage(message);

      await ActionClass.confirmMessage(message, {
        action,
        reverse: Boolean(payload.reverse)
      });

      sendGMResponse(payload, {
        ok: true,
        result: true
      });
    } catch (err) {
      console.error(`${MODULE_ID} | Socket request failed`, err);

      sendGMResponse(payload, {
        ok: false,
        error: err.message ?? String(err)
      });
    }
  });
}

function sendGMResponse(requestPayload, response) {
  if (!requestPayload?.requestId || !requestPayload?.requestingUserId) return;

  game.socket.emit(SOCKET_NAME, {
    type: "gmResponse",
    requestId: requestPayload.requestId,
    requestingUserId: requestPayload.requestingUserId,
    gmId: game.user.id,
    ...response
  });
}

function canUserControlHeroismActor(user, actor, message = null) {
  if (!user || !actor) return false;
  if (user.isGM) return true;

  if (actor.testUserPermission?.(user, "OWNER")) return true;

  const tokenDocument = message ? getTokenDocumentFromMessage(message) : null;

  if (tokenDocument?.actor?.id === actor.id || tokenDocument?.actor?.uuid === actor.uuid) {
    if (tokenDocument.actor?.testUserPermission?.(user, "OWNER")) return true;
  }

  if (user.character) {
    if (user.character.id === actor.id) return true;
    if (user.character.uuid === actor.uuid) return true;
    if (user.character.name === actor.name) return true;
  }

  return false;
}

async function showGMHeroismRerollDialog({ message, actor, requestingUser, reverse = true } = {}) {
  const DialogV2 = foundry.applications?.api?.DialogV2;
  if (!DialogV2) throw new Error("Nie znaleziono foundry.applications.api.DialogV2.");

  const actionData = message.getFlag("crucible", "action") ?? {};
  const actionName = actionData.name ?? actionData.title ?? "akcja";
  const actorName = actor?.name ?? "aktor";
  const userName = requestingUser?.name ?? "gracz";

  const operation = reverse
    ? "cofnięcie potwierdzonej akcji i pozwolenie graczowi wykonać ją ponownie"
    : "ponownie zastosować cofniętą akcję";

  const confirmed = await DialogV2.confirm({
    window: {
      title: "Przerzut za Heroizm"
    },
    content: [
      `<p><strong>${escapeHtml(userName)}</strong> chce użyć przerzutu za Heroizm.</p>`,
      `<p><strong>Aktor:</strong> ${escapeHtml(actorName)}</p>`,
      `<p>Operacja: ${escapeHtml(operation)}.</p>`,
      `<p>Po zatwierdzeniu stara akcja zostanie cofnięta, a gracz uruchomi ją ponownie.</p>`
    ].join(""),
    yes: {
      label: "Potwierdź"
    },
    no: {
      label: "Anuluj"
    },
    modal: true,
    rejectClose: false
  });

  return confirmed === true;
}

function handleGMResponse(payload) {
  if (payload.requestingUserId !== game.user.id) return;

  const pending = PENDING_GM_REQUESTS.get(payload.requestId);
  if (!pending) return;

  window.clearTimeout(pending.timeout);
  PENDING_GM_REQUESTS.delete(payload.requestId);

  if (!payload.ok) {
    const error = new Error(payload.error ?? "MG nie wykonał żądania socketu.");
    error.code = payload.code;
    pending.reject(error);
    return;
  }

  pending.resolve(payload.result);
}

function isPrimaryActiveGM() {
  return getPrimaryActiveGM()?.id === game.user.id;
}

function getPrimaryActiveGM() {
  return game.users
    .filter(user => user.active && user.isGM)
    .sort((a, b) => a.id.localeCompare(b.id))[0] ?? null;
}

function requestPrimaryGM(type, data = {}) {
  const gm = getPrimaryActiveGM();

  if (!gm) {
    return Promise.reject(new Error("Nie znaleziono aktywnego MG. Cofnięcie starej akcji wymaga aktywnego MG."));
  }

  const requestId = foundry.utils.randomID();

  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      PENDING_GM_REQUESTS.delete(requestId);
      reject(new Error("Przekroczono limit czasu oczekiwania na odpowiedź MG."));
    }, SOCKET_TIMEOUT_MS);

    PENDING_GM_REQUESTS.set(requestId, {
      resolve,
      reject,
      timeout
    });

    game.socket.emit(SOCKET_NAME, {
      type,
      requestId,
      requestingUserId: game.user.id,
      gmId: gm.id,
      ...data
    });
  });
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

function canControlHeroismActor(actor, message = null) {
  if (game.user.isGM) return true;
  if (!actor) return false;

  if (actor.testUserPermission?.(game.user, "OWNER")) return true;

  const tokenDocument = message ? getTokenDocumentFromMessage(message) : null;

  if (tokenDocument?.actor?.id === actor.id || tokenDocument?.actor?.uuid === actor.uuid) {
    if (tokenDocument.actor?.testUserPermission?.(game.user, "OWNER")) return true;
  }

  const assigned = getUserAssignedActors(game.user);

  return assigned.some(assignedActor => {
    return assignedActor?.id === actor.id
      || assignedActor?.uuid === actor.uuid
      || assignedActor?.name === actor.name;
  });
}

function getUserAssignedActors(user) {
  const actors = [];

  if (user.character) actors.push(user.character);

  for (const actor of game.actors ?? []) {
    if (actor.testUserPermission?.(user, "OWNER")) {
      actors.push(actor);
    }
  }

  return actors;
}

function getMessageFromContext(li) {
  const messageElement = getMessageElementFromContext(li);
  const messageId = messageElement?.dataset?.messageId;

  return messageId ? game.messages.get(messageId) : null;
}

function normalizeElement(li) {
  if (li instanceof HTMLElement) return li;
  if (li?.[0] instanceof HTMLElement) return li[0];
  if (li?.currentTarget instanceof HTMLElement) return li.currentTarget;
  return null;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value ?? "");
  return div.innerHTML;
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

function buildHeroismRerollChatContent({ message, actor, status = "accepted" }) {
  const actionData = message.getFlag("crucible", "action") ?? {};

  const actionId = actionData.id
    ?? actionData.slug
    ?? "heroism.reroll";

  const actionName = actionData.name
    ?? actionData.title
    ?? "Przerzut za Heroizm";

  const actionImg = actionData.img
    ?? actor?.img
    ?? "icons/svg/d20.svg";

  const rejected = status === "rejected";

  const rollClass = rejected
    ? "crucible dice-roll standard-check failure line-item"
    : "crucible dice-roll standard-check success line-item";

  const outcome = rejected ? "Heroizm" : "Heroizm";
  const result = rejected ? "0" : "1";
  const target = rejected ? "odmowa" : "wydano";

  const description = rejected
    ? "MG odrzucił prośbę o przerzut za Heroizm. Punkt Heroizmu nie został wydany albo został zwrócony."
    : "Wydano <strong>1 Punkt Heroizmu</strong>. Oryginalna akcja została cofnięta i uruchomiona ponownie. Potwierdź nową kartę akcji, aby zastosować nowe obrażenia i efekty.";

  const tags = rejected
    ? [
        `<span class="tag" data-crucible-tooltip="tag" data-tag="heroism">Przerzut za Heroizm</span>`,
        `<span class="tag" data-crucible-tooltip="tag" data-tag="rejected">Odrzucono</span>`
      ]
    : [
        `<span class="tag" data-crucible-tooltip="tag" data-tag="heroism">1 Punkt Heroizmu</span>`,
        `<span class="tag" data-crucible-tooltip="tag" data-tag="reroll">Przerzut</span>`
      ];

  return [
    `<div class="crucible action-roll heroism-reroll" data-action-id="${escapeAttribute(actionId)}" data-heroism-status="${escapeAttribute(status)}">`,

      `<section class="action line-item">`,
        `<header class="action-header">`,
          `<img class="icon" src="${escapeAttribute(actionImg)}" alt="${escapeAttribute(actionName)}">`,
          `<div class="title">`,
            `<h4>Przerzut za Heroizm</h4>`,
            `<div class="tags" data-tag-type="activation">`,
              tags.join(""),
            `</div>`,
          `</div>`,
        `</header>`,

        `<div class="description">`,
          description,
        `</div>`,
      `</section>`,

      `<section class="action-sections">`,
        `<section class="action-target">`,
          `<div class="${rollClass}" data-action="expandRoll">`,
            `<div class="dice-result">`,
              `<h4 class="dice-total check-result">`,
                `<span class="outcome">${outcome}</span>`,
                `<span class="result hex">${result}</span>`,
                `<span class="target">${target}</span>`,
              `</h4>`,
            `</div>`,
          `</div>`,
        `</section>`,
      `</section>`,

    `</div>`
  ].join("");
}

function registerHeroismRerollChatStyling() {
  Hooks.on("renderChatMessageHTML", (message, html, _context) => {
    styleHeroismRerollChatMessage(message, html);
  });

  Hooks.on("renderChatMessage", (message, html, _context) => {
    styleHeroismRerollChatMessage(message, html);
  });

  Hooks.on("renderChatLog", () => {
    styleExistingHeroismRerollChatMessages();
  });
}

function styleExistingHeroismRerollChatMessages() {
  for (const element of document.querySelectorAll("li.chat-message")) {
    const messageId = element.dataset.messageId;
    const message = messageId ? game.messages?.get(messageId) : null;

    const isHeroismNote =
      message?.getFlag?.(MODULE_ID, "type") === "heroism-reroll-note"
      || Boolean(element.querySelector(".heroism-reroll"));

    if (!isHeroismNote) continue;

    applyHeroismRerollCrucibleClasses(element);
  }
}

function styleHeroismRerollChatMessage(message, html) {
  const element = normalizeRenderedChatElement(html);
  if (!element) return;

  const chatMessage = getRenderedChatMessageElement(element);
  if (!chatMessage) return;

  const isHeroismNote =
    message?.getFlag?.(MODULE_ID, "type") === "heroism-reroll-note"
    || Boolean(chatMessage.querySelector(".heroism-reroll"))
    || chatMessage.classList.contains("heroism-reroll");

  if (!isHeroismNote) return;

  applyHeroismRerollCrucibleClasses(chatMessage);
}

function applyHeroismRerollCrucibleClasses(chatMessage) {
  chatMessage.classList.add("crucible");

  const content = chatMessage.querySelector(".message-content");

  if (content) {
    content.classList.add("themed", "theme-dark");
  }

  const metadata = chatMessage.querySelector(".message-header .message-metadata");

  if (metadata) {
    metadata.querySelector(".confirmed[data-heroism-reroll-icon]")?.remove();
    metadata.querySelector(".unconfirmed[data-heroism-reroll-icon]")?.remove();

    metadata.prepend(createHeroismRerollHeaderIcon(chatMessage));
  }
}

function getRenderedChatMessageElement(element) {
  if (!element) return null;

  if (element.matches?.("li.chat-message")) return element;

  return element.closest?.("li.chat-message")
    ?? element.querySelector?.("li.chat-message")
    ?? null;
}

function normalizeRenderedChatElement(html) {
  if (html instanceof HTMLElement) return html;
  if (html?.[0] instanceof HTMLElement) return html[0];
  if (html?.jquery && html[0] instanceof HTMLElement) return html[0];
  return null;
}

function createHeroismRerollHeaderIcon(chatMessage) {
  const rejected =
    chatMessage.querySelector(".heroism-reroll[data-heroism-status='rejected']")
    || chatMessage.querySelector(".heroism-reroll .dice-roll.failure");

  const icon = document.createElement("i");

  if (rejected) {
    icon.classList.add("unconfirmed", "fa-solid", "fa-hexagon-xmark");
  } else {
    icon.classList.add("confirmed", "fa-solid", "fa-hexagon-check");
  }

  icon.dataset.tooltip = "Przerzut za Heroizm";
  icon.dataset.heroismRerollIcon = "true";

  return icon;
}

async function setOriginalMessageRerolledFlag(message, actor) {
  const data = {
    mode: "replay-action",
    actorId: actor.id,
    userId: game.user.id,
    timestamp: Date.now()
  };

  if (game.user.isGM) {
    await message.setFlag(MODULE_ID, "rerolled", data);
    return;
  }

  await requestPrimaryGM("setRerolledFlag", {
    messageId: message.id,
    actorId: actor.id
  });
}