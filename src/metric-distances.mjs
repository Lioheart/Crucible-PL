const MODULE_ID = "lang-pl-crucible";
const SETTING_ENABLE_RULER_METERS = "enableRulerMeters";

let rulerObserver = null;

function feetToMeters(feet) {
    const raw = feet * 0.3048;
    const rounded = Math.round(raw * 2) / 2;
    const maximumFractionDigits = rounded % 1 === 0 ? 0 : 1;

    return `${rounded.toLocaleString("pl-PL", { maximumFractionDigits })}\u00A0m`;
}

function registerMetricSettings() {
    game.settings.register(MODULE_ID, SETTING_ENABLE_RULER_METERS, {
        name: "Wyświetlaj metry na linijce ruchu",
        hint: "Pokazuje przybliżoną odległość w metrach obok wartości w stopach podczas mierzenia ruchu tokena.",
        scope: "client",
        config: true,
        type: Boolean,
        default: true
    });
}

function enrichFeet([fullMatch, valueString]) {
    const feet = Number.parseFloat(valueString);
    if (Number.isNaN(feet)) return new Text(fullMatch);

    const metersLabel = feetToMeters(feet);
    const feetLabel = feet === 1 ? "stopa" : "stóp";

    const tag = document.createElement("enriched-content");
    tag.classList.add("condition", "lang-pl-crucible-no-icon");
    tag.textContent = `${feet}\u00A0${feetLabel}`;

    tag.dataset.tooltipHtml = `
    ### ${feet}\u00A0${feetLabel}

    ≈\u00A0${metersLabel}
    `;

    tag.dataset.tooltipClass = "crucible crucible-tooltip";
    tag.dataset.tooltipDirection = "UP";

    return tag;
}

function registerFeetEnricher() {
    CONFIG.TextEditor.enrichers ??= [];

    if (CONFIG.TextEditor.enrichers.some(e => e.id === "langPlCrucibleFeet")) return;

    CONFIG.TextEditor.enrichers.push({
        id: "langPlCrucibleFeet",
        pattern: /@\[feet ([\d.]+)]/g,
                                     enricher: enrichFeet
    });

    console.log(`${MODULE_ID} | Zarejestrowano enricher @[feet N].`);
}

function registerRulerObserver() {
    if (!game.settings.get(MODULE_ID, SETTING_ENABLE_RULER_METERS)) return;

    Hooks.once("canvasReady", startRulerObserver);

    if (canvas?.ready) startRulerObserver();
}

function startRulerObserver() {
    if (!game.settings.get(MODULE_ID, SETTING_ENABLE_RULER_METERS)) return;

    const hud = document.getElementById("hud");
    if (!hud) {
        console.warn(`${MODULE_ID} | Nie znaleziono #hud. Nie uruchomiono obserwatora linijki.`);
        return;
    }

    if (rulerObserver) rulerObserver.disconnect();

    rulerObserver = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (node instanceof HTMLElement) processWaypointLabels(node);
            }
        }
    });

    rulerObserver.observe(hud, {
        childList: true,
        subtree: true
    });

    console.log(`${MODULE_ID} | Uruchomiono obserwator metrów na linijce.`);
}

function processWaypointLabels(root) {
    const labels = root.classList?.contains("waypoint-label")
    ? [root]
    : Array.from(root.querySelectorAll(".waypoint-label"));

    for (const label of labels) injectMetersInLabel(label);
}

function injectMetersInLabel(label) {
    if (!game.settings.get(MODULE_ID, SETTING_ENABLE_RULER_METERS)) return;

    const measureEl = label.querySelector(".total-measurement:not(.total-cost)");
    if (!measureEl || label.querySelector(".lang-pl-crucible-meters")) return;

    const rawText = Array.from(measureEl.childNodes)
    .filter(n => n.nodeType === Node.TEXT_NODE)
    .map(n => n.textContent)
    .join("")
    .trim();

    const feet = Number.parseFloat(
        rawText
        .replace(/\s|\u00A0/g, "")
        .replace(",", ".")
    );

    if (Number.isNaN(feet) || feet <= 0) return;

    const span = document.createElement("span");
    span.className = "lang-pl-crucible-meters";
    span.textContent = `\u00A0(≈\u00A0${feetToMeters(feet)})`;

    measureEl.appendChild(span);
}

Hooks.once("init", () => {
    registerMetricSettings();
    registerFeetEnricher();
});

Hooks.once("setup", () => {
    registerRulerObserver();
});
