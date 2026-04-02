document.addEventListener("DOMContentLoaded", function () {
    const header = document.querySelector(".site-header");
    const menuToggle = document.querySelector("[data-menu-toggle]");
    const mainNav = document.querySelector("[data-main-nav]");

    function syncHeaderShadow() {
        if (!header) {
            return;
        }
        header.classList.toggle("is-scrolled", window.scrollY > 8);
    }

    syncHeaderShadow();
    window.addEventListener("scroll", syncHeaderShadow, { passive: true });

    if (header && menuToggle && mainNav) {
        function closeMenu() {
            header.classList.remove("menu-open");
            menuToggle.setAttribute("aria-expanded", "false");
        }

        menuToggle.addEventListener("click", function () {
            const isOpen = header.classList.toggle("menu-open");
            menuToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });

        mainNav.querySelectorAll(".nav-link").forEach(function (link) {
            link.addEventListener("click", closeMenu);
        });

        window.addEventListener("resize", function () {
            if (window.innerWidth > 980) {
                closeMenu();
            }
        });
    }

    document.querySelectorAll("[data-accordion-trigger]").forEach(function (trigger) {
        trigger.addEventListener("click", function () {
            const item = trigger.closest("[data-accordion-item]");
            if (item) {
                item.classList.toggle("is-open");
            }
        });
    });

    const chatRoot = document.querySelector("[data-chat-root]");
    if (chatRoot) {
        const scenarios = JSON.parse(chatRoot.dataset.scenarios || "[]");
        const defaultTitle = chatRoot.dataset.defaultTitle || "Напишите вопрос своими словами";
        const defaultSummary = chatRoot.dataset.defaultSummary || "Можно выбрать тему кнопками выше или просто описать проблему.";
        const storageKey = "jkh40-chat-state-v1";
        const explicitScenario = (chatRoot.dataset.selectedScenario || "").trim();
        const titleNode = chatRoot.querySelector("[data-scenario-title]");
        const summaryNode = chatRoot.querySelector("[data-scenario-summary]");
        const messagesNode = chatRoot.querySelector("[data-chat-messages]");
        const tabs = chatRoot.querySelectorAll("[data-scenario-tab]");
        const form = chatRoot.querySelector("[data-chat-form]");
        const input = chatRoot.querySelector("[data-chat-input]");
        const submitButton = chatRoot.querySelector("[data-chat-submit]");
        const initialQuery = (chatRoot.dataset.initialQuery || "").trim();
        const chatEndpoint = chatRoot.dataset.chatEndpoint || "/api/chat/message";
        let currentScenario = null;
        let currentNode = null;
        let waitingForInput = false;
        let initialQueryHandled = false;
        let requestInFlight = false;
        let pendingScenarioMatch = null;

        function saveChatState() {
            try {
                window.sessionStorage.setItem(storageKey, JSON.stringify({
                    html: messagesNode.innerHTML,
                    currentScenarioSlug: currentScenario ? currentScenario.slug : "",
                    currentNodeKey: currentNode ? Object.keys(currentScenario && currentScenario.nodes ? currentScenario.nodes : {}).find(function (key) {
                        return currentScenario.nodes[key] === currentNode;
                    }) || "" : "",
                    waitingForInput: waitingForInput,
                    pendingScenarioMatch: pendingScenarioMatch,
                    title: titleNode.textContent,
                    summary: summaryNode.textContent,
                    placeholder: input.placeholder
                }));
            } catch (error) {
            }
        }

        function disableRestoredChoices() {
            messagesNode.querySelectorAll(".live-choice").forEach(function (button) {
                button.disabled = true;
                button.classList.add("is-disabled");
            });
        }

        function restoreChatState() {
            try {
                const raw = window.sessionStorage.getItem(storageKey);
                if (!raw) {
                    return false;
                }
                const state = JSON.parse(raw);
                if (!state || !state.html) {
                    return false;
                }

                messagesNode.innerHTML = state.html;
                disableRestoredChoices();

                currentScenario = scenarios.find(function (item) {
                    return item.slug === state.currentScenarioSlug;
                }) || null;
                currentNode = currentScenario && state.currentNodeKey ? currentScenario.nodes[state.currentNodeKey] || null : null;
                waitingForInput = Boolean(state.waitingForInput);
                pendingScenarioMatch = state.pendingScenarioMatch || null;

                if (explicitScenario) {
                    titleNode.textContent = state.title || defaultTitle;
                    summaryNode.textContent = state.summary || defaultSummary;
                    tabs.forEach(function (tab) {
                        tab.classList.toggle("is-active", currentScenario && tab.dataset.scenarioSlug === currentScenario.slug);
                    });
                } else {
                    titleNode.textContent = defaultTitle;
                    summaryNode.textContent = defaultSummary;
                    tabs.forEach(function (tab) {
                        tab.classList.remove("is-active");
                    });
                }

                setInputState(waitingForInput, state.placeholder || "Напишите проблему обычными словами");
                scrollChatToEnd();
                return true;
            } catch (error) {
                return false;
            }
        }

        function scrollChatToEnd() {
            messagesNode.scrollTop = messagesNode.scrollHeight;
        }

        function createRow(role, contentNode) {
            const row = document.createElement("div");
            row.className = "chat-row role-" + role + " kind-bubble";
            row.appendChild(contentNode);
            return row;
        }

        function appendBubble(role, text) {
            const bubble = document.createElement("div");
            bubble.className = "chat-bubble";
            bubble.textContent = text;
            messagesNode.appendChild(createRow(role, bubble));
            scrollChatToEnd();
            saveChatState();
        }

        function appendActionButtons(actionsList) {
            const actions = document.createElement("div");
            actions.className = "chat-actions live-actions";

            actionsList.forEach(function (actionItem) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "mini-action outline live-choice";
                button.textContent = actionItem.label;
                button.addEventListener("click", function () {
                    appendBubble("user", actionItem.label);
                    disableActiveChoices();
                    actionItem.onClick();
                });
                actions.appendChild(button);
            });

            const row = document.createElement("div");
            row.className = "chat-row role-assistant kind-actions";
            row.appendChild(actions);
            messagesNode.appendChild(row);
            scrollChatToEnd();
            saveChatState();
        }

        function appendChoices(choices) {
            appendActionButtons(choices.map(function (choice) {
                return {
                    label: choice.label,
                    onClick: function () {
                        moveToNode(choice.next);
                    }
                };
            }));
        }

        function appendResult(result) {
            const card = document.createElement("div");
            card.className = "chat-result-card";
            const title = document.createElement("h3");
            title.textContent = result.title;
            const text = document.createElement("p");
            text.textContent = result.text;
            card.appendChild(title);
            card.appendChild(text);

            if (Array.isArray(result.links) && result.links.length) {
                const links = document.createElement("div");
                links.className = "chat-result-links";
                result.links.forEach(function (item) {
                    const link = document.createElement("a");
                    link.className = "text-link";
                    link.href = item.href;
                    link.textContent = item.label;
                    links.appendChild(link);
                });
                card.appendChild(links);
            }

            const row = document.createElement("div");
            row.className = "chat-row role-assistant kind-result";
            row.appendChild(card);
            messagesNode.appendChild(row);
            scrollChatToEnd();
            saveChatState();
        }

        function appendKnowledgeResult(result) {
            const card = document.createElement("div");
            card.className = "chat-result-card";
            const title = document.createElement("h3");
            title.textContent = result.title;
            const text = document.createElement("p");
            text.textContent = result.answer;
            card.appendChild(title);
            card.appendChild(text);

            if (result.matched && result.scenario) {
                const note = document.createElement("p");
                note.className = "result-note";
                note.textContent = "Нашёл ближайший сценарий и готовый ответ по вашему запросу.";
                card.appendChild(note);
            }

            if (Array.isArray(result.links) && result.links.length) {
                const links = document.createElement("div");
                links.className = "chat-result-links";
                result.links.forEach(function (item) {
                    const link = document.createElement("a");
                    link.className = "text-link";
                    link.href = item.href;
                    link.textContent = item.label;
                    links.appendChild(link);
                });
                card.appendChild(links);
            }

            const row = document.createElement("div");
            row.className = "chat-row role-assistant kind-result";
            row.appendChild(card);
            messagesNode.appendChild(row);
            scrollChatToEnd();
            saveChatState();

            if (result.matched) {
                appendBubble("assistant", "Можете задать следующий вопрос.");
                return;
            }

            appendBubble("assistant", "Попробуйте задать вопрос ещё раз короче и точнее.");
        }

        function syncScenarioHeader() {
            if (!currentScenario) {
                titleNode.textContent = defaultTitle;
                summaryNode.textContent = defaultSummary;
                tabs.forEach(function (tab) {
                    tab.classList.remove("is-active");
                });
                saveChatState();
                return;
            }

            titleNode.textContent = currentScenario.title;
            summaryNode.textContent = currentScenario.summary;
            tabs.forEach(function (tab) {
                tab.classList.toggle("is-active", tab.dataset.scenarioSlug === currentScenario.slug);
            });
            saveChatState();
        }

        function disableActiveChoices() {
            messagesNode.querySelectorAll(".live-choice").forEach(function (button) {
                button.disabled = true;
                button.classList.add("is-disabled");
            });
        }

        function setInputState(enabled, placeholder) {
            waitingForInput = enabled;
            input.disabled = requestInFlight;
            submitButton.disabled = requestInFlight;
            input.placeholder = placeholder || "Напишите проблему обычными словами";
            if (enabled) {
                input.focus();
            } else if (!requestInFlight) {
                input.value = "";
            }
        }

        function setRequestState(loading) {
            requestInFlight = loading;
            if (loading) {
                input.disabled = true;
                submitButton.disabled = true;
                submitButton.textContent = "Ищу ответ...";
                return;
            }
            input.disabled = false;
            submitButton.disabled = false;
            submitButton.textContent = "Отправить";
        }

        function moveToNode(nodeKey) {
            if (!currentScenario) {
                return;
            }
            currentNode = currentScenario.nodes[nodeKey];
            if (!currentNode) {
                return;
            }

            appendBubble("assistant", currentNode.prompt);

            if (currentNode.input_placeholder) {
                setInputState(true, currentNode.input_placeholder);
                return;
            }

            setInputState(false);

            if (currentNode.choices) {
                appendChoices(currentNode.choices);
                return;
            }

            if (currentNode.result) {
                appendResult(currentNode.result);
            }
            saveChatState();
        }

        function startNeutralChat(resetMessages) {
            currentScenario = null;
            currentNode = null;
            pendingScenarioMatch = null;
            if (resetMessages) {
                messagesNode.innerHTML = "";
            }
            syncScenarioHeader();
            setInputState(false, "Напишите проблему обычными словами");
            if (resetMessages) {
                appendBubble("assistant", "Добрый день! Напишите свой вопрос своими словами или выберите тему выше. Я постараюсь подсказать, с чего лучше начать.");
            }
            saveChatState();
        }

        function chooseScenario(slug) {
            currentScenario = scenarios.find(function (item) {
                return item.slug === slug;
            }) || scenarios[0];

            if (!currentScenario) {
                return;
            }

            messagesNode.innerHTML = "";
            syncScenarioHeader();
            setInputState(false);
            pendingScenarioMatch = null;

            appendBubble("assistant", "Добрый день! Можно либо идти по кнопкам, либо просто написать проблему своими словами. Я попробую найти ближайший готовый ответ.");
            moveToNode(currentScenario.start_node);
            saveChatState();
        }

        function continueMatchedScenario() {
            if (!pendingScenarioMatch || !pendingScenarioMatch.scenario) {
                return;
            }

            currentScenario = scenarios.find(function (item) {
                return item.slug === pendingScenarioMatch.scenario;
            }) || currentScenario;

            pendingScenarioMatch = null;
            currentNode = null;
            syncScenarioHeader();
            setInputState(false, "Напишите проблему обычными словами");
            moveToNode(currentScenario.start_node);
            saveChatState();
        }

        function askScenarioConfirmation(result) {
            pendingScenarioMatch = result;
            appendBubble("assistant", "Правильно ли я понял, что вопрос про: " + result.title + "?");
            appendActionButtons([
                {
                    label: "Да, верно",
                    onClick: function () {
                        continueMatchedScenario();
                    }
                },
                {
                    label: "Нет, не совсем",
                    onClick: function () {
                        pendingScenarioMatch = null;
                        appendBubble("assistant", "Хорошо. Тогда напишите вопрос чуть иначе или выберите нужный сценарий кнопками выше.");
                        saveChatState();
                    }
                }
            ]);
        }

        function submitFreeText(value, silentPrefill) {
            const query = (value || "").trim();
            if (!query || requestInFlight) {
                return;
            }

            if (!silentPrefill) {
                appendBubble("user", query);
            }
            setRequestState(true);

            fetch(chatEndpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ query: query })
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("bad response");
                    }
                    return response.json();
                })
                .then(function (payload) {
                    if (payload.matched && payload.scenario) {
                        askScenarioConfirmation(payload);
                        return;
                    }
                    appendKnowledgeResult(payload);
                })
                .catch(function () {
                    appendBubble("assistant", "С ответом что-то пошло не так. Попробуйте ещё раз чуть короче или перейдите в базу знаний.");
                })
                .finally(function () {
                    input.value = "";
                    setRequestState(false);
                    input.placeholder = waitingForInput ? (currentNode && currentNode.input_placeholder) || "Введите ответ" : "Напишите проблему обычными словами";
                });
        }

        tabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                chooseScenario(tab.dataset.scenarioSlug);
            });
        });

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            const value = input.value.trim();
            if (!value) {
                input.focus();
                return;
            }

            if (waitingForInput) {
                appendBubble("user", value);
                const nextNode = currentNode.next;
                setInputState(false);
                moveToNode(nextNode);
                saveChatState();
                return;
            }

            submitFreeText(value, false);
        });

        if (!restoreChatState()) {
            if (explicitScenario) {
                chooseScenario(explicitScenario);
            } else {
                startNeutralChat(true);
            }
        }

        if (initialQuery && !initialQueryHandled) {
            initialQueryHandled = true;
            window.setTimeout(function () {
                submitFreeText(initialQuery, false);
            }, 120);
        }
    }

    const consentModal = document.querySelector("[data-consent-modal]");
    const acceptConsent = document.querySelector("[data-consent-accept]");
    if (consentModal && acceptConsent) {
        if (window.sessionStorage.getItem("recalc-consent") === "accepted") {
            consentModal.classList.add("is-hidden");
        }

        acceptConsent.addEventListener("click", function () {
            window.sessionStorage.setItem("recalc-consent", "accepted");
            consentModal.classList.add("is-hidden");
        });
    }

    const previewPdfButton = document.querySelector("[data-preview-pdf]");
    const pdfForm = document.querySelector("[data-pdf-form]");
    if (previewPdfButton && pdfForm) {
        previewPdfButton.addEventListener("click", function () {
            const data = new URLSearchParams(new FormData(pdfForm));
            window.open(previewPdfButton.dataset.previewUrl + "?" + data.toString(), "_blank");
        });
    }

    function splitByThresholds(amount, thresholds) {
        const first = Math.min(amount, thresholds[0]);
        const second = Math.min(Math.max(amount - thresholds[0], 0), thresholds[1] - thresholds[0]);
        const third = Math.max(amount - thresholds[1], 0);
        return [first, second, third];
    }

    function currency(value) {
        return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
    }

    const calculatorRoot = document.querySelector("[data-tariff-calculator]");
    if (calculatorRoot) {
        const config = JSON.parse(calculatorRoot.dataset.calculatorConfig || "{}");
        const periods = Array.isArray(config.periods) ? config.periods : [];
        const services = Array.isArray(config.services) ? config.services : [];
        const serviceButtons = calculatorRoot.querySelectorAll("[data-service-slug]");
        const headingNode = calculatorRoot.querySelector("[data-service-heading]");
        const summaryNode = calculatorRoot.querySelector("[data-service-summary]");
        const formArea = calculatorRoot.querySelector("[data-calculator-form-area]");
        const resultNode = calculatorRoot.querySelector("[data-calculator-result]");
        const guidesNode = document.querySelector("[data-calculator-guides]");
        const submitButton = calculatorRoot.querySelector("[data-calculator-submit]");

        if (services.length) {
            const state = {};
            let activeServiceSlug = services[0].slug;

            function clone(value) {
                return JSON.parse(JSON.stringify(value));
            }

            function escapeHtml(value) {
                return String(value)
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/\"/g, "&quot;");
            }

            function getService(slug) {
                return services.find(function (item) {
                    return item.slug === slug;
                }) || services[0];
            }

            function getPeriodMeta(periodKey) {
                return periods.find(function (period) {
                    return period.key === periodKey;
                }) || periods[0];
            }

            function periodInputDefaults(defaults) {
                const values = {};
                periods.forEach(function (period) {
                    values[period.key] = {
                        quantity: defaults.quantity || 0,
                        people: defaults.people || 3,
                        area: defaults.area || 60,
                    };
                });
                return values;
            }

            function normalizeState(service) {
                const defaults = clone(service.defaults || {});
                if (service.type === "electricity") {
                    defaults.period_values = defaults.period_values || {};
                    periods.forEach(function (period) {
                        if (!defaults.period_values[period.key]) {
                            defaults.period_values[period.key] = {
                                consumption: 450,
                                day: 200,
                                night: 250,
                                peak: 120,
                                semipeak: 180,
                                night_three: 150,
                                people: 3,
                                odn: 0,
                            };
                        }
                    });
                    return defaults;
                }

                defaults.period_values = defaults.period_values || periodInputDefaults(defaults);
                return defaults;
            }

            services.forEach(function (service) {
                state[service.slug] = normalizeState(service);
            });

            function currentService() {
                return getService(activeServiceSlug);
            }

            function currentState() {
                return state[activeServiceSlug];
            }

            function previewLink(file) {
                if (!file) {
                    return "#";
                }
                if (file.toLowerCase().endsWith(".docx")) {
                    return "/documents/preview?file=" + encodeURIComponent(file);
                }
                return "/static/" + file.split("/").map(encodeURIComponent).join("/");
            }

            function choiceButton(group, value, label, active) {
                return "<button type=\"button\" class=\"calculator-choice-button" + (active ? " is-active" : "") + "\" data-choice-group=\"" + group + "\" data-choice-value=\"" + value + "\">" + escapeHtml(label) + "</button>";
            }

            function choiceGroup(label, group, options, selected) {
                return [
                    "<div class=\"calculator-choice-group\">",
                    "<p class=\"calculator-choice-label\">" + escapeHtml(label) + "</p>",
                    "<div class=\"calculator-choice-grid\">",
                    options.map(function (option) {
                        return choiceButton(group, option.key, option.label, option.key === selected);
                    }).join(""),
                    "</div>",
                    "</div>"
                ].join("");
            }

            function numberField(periodKey, field, label, value, placeholder, hint) {
                return [
                    "<label class=\"calculator-number-field\">",
                    "<span>" + escapeHtml(label) + "</span>",
                    hint ? "<small>" + escapeHtml(hint) + "</small>" : "",
                    "<input type=\"number\" step=\"0.01\" min=\"0\" data-period-key=\"" + periodKey + "\" data-field=\"" + field + "\" value=\"" + escapeHtml(value) + "\" placeholder=\"" + escapeHtml(placeholder || "") + "\">",
                    "</label>"
                ].join("");
            }

            function renderElectricityPeriods(service, serviceState) {
                return periods.map(function (period) {
                    const values = serviceState.period_values[period.key];
                    const isMeter = serviceState.input_method === "meter";
                    const isZone = serviceState.mode === "zone";
                    const isThreeZone = isZone && serviceState.zone_mode === "three_zone";
                    const fields = [];

                    if (isMeter && !isZone) {
                        fields.push(numberField(period.key, "consumption", "Объём по прибору учёта", values.consumption, "кВт·ч", ""));
                    }

                    if (isMeter && isZone && !isThreeZone) {
                        fields.push(numberField(period.key, "day", "Объём по прибору учёта", values.day, "кВт·ч", "Дневная зона (7:00 до 23:00)"));
                        fields.push(numberField(period.key, "night", "Объём по прибору учёта", values.night, "кВт·ч", "Ночная зона (23:00 до 7:00)"));
                    }

                    if (isMeter && isThreeZone) {
                        fields.push(numberField(period.key, "peak", "Объём по прибору учёта", values.peak, "кВт·ч", "Пиковая зона"));
                        fields.push(numberField(period.key, "semipeak", "Объём по прибору учёта", values.semipeak, "кВт·ч", "Полупиковая зона"));
                        fields.push(numberField(period.key, "night_three", "Объём по прибору учёта", values.night_three, "кВт·ч", "Ночная зона"));
                    }

                    if (!isMeter) {
                        fields.push(numberField(period.key, "people", "Количество человек в квартире", values.people, "Кол-во", ""));
                    }

                    if (serviceState.odn_mode === "with_odn") {
                        fields.push(numberField(period.key, "odn", "Общедомовые нужды", values.odn, "кВт·ч", "Добавляем ориентировочно по базовой ставке"));
                    }

                    return [
                        "<div class=\"calculator-period-card\">",
                        "<h3>" + escapeHtml(getPeriodMeta(period.key).label) + "</h3>",
                        "<p class=\"calculator-period-subtitle\">Жилое помещение</p>",
                        "<div class=\"calculator-period-fields\">",
                        fields.join(""),
                        "</div>",
                        "</div>"
                    ].join("");
                }).join("");
            }

            function renderResourcePeriods(service, serviceState) {
                return periods.map(function (period) {
                    const values = serviceState.period_values[period.key];
                    const fields = [];

                    if (service.slug === "heating") {
                        fields.push(numberField(period.key, "area", "Площадь помещения", values.area, "м²", ""));
                    } else if (service.slug === "waste") {
                        fields.push(numberField(period.key, "area", "Площадь помещения", values.area, "м²", ""));
                    } else if (service.slug === "gas" && serviceState.usage === "heating") {
                        fields.push(numberField(period.key, "quantity", "Объём по прибору учёта", values.quantity, service.unit, ""));
                    } else if (serviceState.input_method === "norm") {
                        fields.push(numberField(period.key, "people", "Количество человек в квартире", values.people, "Кол-во", ""));
                    } else {
                        fields.push(numberField(period.key, "quantity", "Объём по прибору учёта", values.quantity, service.unit, ""));
                    }

                    if (service.slug === "waste") {
                        fields.push("<p class=\"calculator-inline-note\">Для квартиры в Калуге считаем по площади. Для частного дома нужен отдельный тарифный режим.</p>");
                    }

                    if (service.slug === "gas" && serviceState.usage === "heating") {
                        fields.push("<p class=\"calculator-inline-note\">Для газа с отоплением в материалах есть ставка, но нет отдельного норматива на человека, поэтому расчёт идёт по объёму.</p>");
                    }

                    return [
                        "<div class=\"calculator-period-card\">",
                        "<h3>" + escapeHtml(getPeriodMeta(period.key).label) + "</h3>",
                        "<div class=\"calculator-period-fields\">",
                        fields.join(""),
                        "</div>",
                        "</div>"
                    ].join("");
                }).join("");
            }

            function renderGuides(service) {
                if (!guidesNode) {
                    return;
                }
                guidesNode.innerHTML = (service.documents || []).map(function (documentItem) {
                    return [
                        "<article class=\"info-card slim-card calculator-guide-card\">",
                        "<h3>" + escapeHtml(documentItem.title) + "</h3>",
                        "<p>" + escapeHtml(service.summary || "Подробный материал по расчёту и разбору квитанции.") + "</p>",
                        "<a href=\"" + previewLink(documentItem.file) + "\">Открыть источник</a>",
                        "</article>"
                    ].join("");
                }).join("");
            }

            function renderForm() {
                const service = currentService();
                const serviceState = currentState();
                const heatingProfile = service.slug === "electricity" && String(serviceState.profile || "").indexOf("heating_") === 0;
                const formParts = [];

                headingNode.textContent = service.label;
                summaryNode.textContent = service.summary || "";
                submitButton.disabled = service.type === "placeholder";
                submitButton.classList.toggle("is-disabled", service.type === "placeholder");

                if (service.type === "electricity") {
                    formParts.push(choiceGroup("Тип жилья", "profile", service.profiles, serviceState.profile));
                    formParts.push(choiceGroup("Тариф", "mode", [
                        { key: "single", label: "Одноставочный" },
                        { key: "zone", label: "Зонный тариф" }
                    ], serviceState.mode));

                    if (serviceState.mode === "zone" && !heatingProfile) {
                        formParts.push(choiceGroup("Зонный режим", "zone_mode", [
                            { key: "two_zone", label: "Двухзонный" },
                            { key: "three_zone", label: "Трёхзонный" }
                        ], serviceState.zone_mode));
                    }

                    formParts.push(choiceGroup("ОДН", "odn_mode", [
                        { key: "with_odn", label: "ОДН" },
                        { key: "without_odn", label: "Без ОДН" }
                    ], serviceState.odn_mode));

                    formParts.push(choiceGroup("Расчёт", "input_method", [
                        { key: "meter", label: "Счётчик" },
                        { key: "norm", label: "Норматив" }
                    ], serviceState.input_method));

                    formParts.push([
                        "<label class=\"calculator-checkbox-line\">",
                        "<input type=\"checkbox\" data-flag=\"large_family\"" + (serviceState.large_family ? " checked" : "") + ">",
                        "<span>Многодетная семья: считать весь объём по первому диапазону</span>",
                        "</label>"
                    ].join(""));

                    if (heatingProfile) {
                        formParts.push("<p class=\"calculator-inline-note\">Для электроотопления показываем одноставочный расчёт, потому что в присланных материалах зонные ставки отдельно не приведены.</p>");
                    }

                    if (service.note) {
                        formParts.push("<p class=\"calculator-inline-note\">" + escapeHtml(service.note) + "</p>");
                    }

                    formParts.push("<div class=\"calculator-period-grid\">" + renderElectricityPeriods(service, serviceState) + "</div>");
                } else if (service.type === "resource") {
                    if (service.input_mode === "meter_or_norm" && !(service.slug === "gas" && serviceState.usage === "heating")) {
                        formParts.push(choiceGroup("Основа расчёта", "input_method", [
                            { key: "meter", label: "Счётчик" },
                            { key: "norm", label: "Норматив" }
                        ], serviceState.input_method));
                    }

                    if (Array.isArray(service.usage_options)) {
                        formParts.push(choiceGroup("Вариант услуги", "usage", service.usage_options, serviceState.usage));
                    }

                    if (Array.isArray(service.payment_modes)) {
                        formParts.push(choiceGroup("Как оплачиваете", "payment_mode", service.payment_modes, serviceState.payment_mode));
                    }

                    formParts.push("<div class=\"calculator-period-grid\">" + renderResourcePeriods(service, serviceState) + "</div>");
                } else {
                    formParts.push("<div class=\"calculator-placeholder\"><p>Для твёрдого топлива пока собрали только материалы и пояснения. Если пришлёшь пример квитанции, мы добавим и этот расчёт.</p></div>");
                }

                formArea.innerHTML = formParts.join("");
                renderGuides(service);
            }

            function normalizeNumber(value, fallback) {
                const parsed = Number(value);
                return Number.isFinite(parsed) ? parsed : fallback;
            }

            function electricityProfileForZones(profile) {
                if (profile === "heating_electric") {
                    return "electric";
                }
                return "gas";
            }

            function tierSum(parts, rates) {
                return parts.reduce(function (sum, part, index) {
                    return sum + part * (rates[index] || 0);
                }, 0);
            }

            function calculateElectricityPeriod(service, serviceState, periodKey) {
                const periodConfig = service.periods[periodKey];
                const values = serviceState.period_values[periodKey];
                const isMeter = serviceState.input_method === "meter";
                const profile = serviceState.profile;
                const effectiveMode = serviceState.mode === "zone" && String(profile).indexOf("heating_") !== 0
                    ? serviceState.zone_mode
                    : "single";
                let sourceProfile = profile;
                let total = 0;
                let totalVolume = 0;

                if (effectiveMode !== "single") {
                    sourceProfile = electricityProfileForZones(profile);
                }

                if (effectiveMode === "single") {
                    const source = periodConfig.single[sourceProfile];
                    const thresholds = source.thresholds;
                    const consumption = isMeter ? normalizeNumber(values.consumption, 0) : normalizeNumber(values.people, 1) * (service.norms.single[sourceProfile] || 90);
                    totalVolume = consumption;

                    if (serviceState.large_family) {
                        total = consumption * source.rates[0];
                    } else {
                        total = tierSum(splitByThresholds(consumption, thresholds), source.rates);
                    }

                    if (serviceState.odn_mode === "with_odn") {
                        total += normalizeNumber(values.odn, 0) * source.rates[0];
                    }

                    return {
                        total: total,
                        basis: isMeter ? "По счётчику" : "По нормативу",
                        quantity: totalVolume,
                    };
                }

                if (effectiveMode === "two_zone") {
                    const source = periodConfig.two_zone[sourceProfile];
                    const thresholds = source.thresholds;
                    let day = 0;
                    let night = 0;
                    if (isMeter) {
                        day = normalizeNumber(values.day, 0);
                        night = normalizeNumber(values.night, 0);
                    } else {
                        const norm = service.norms.two_zone[sourceProfile] || { day: 38, night: 32 };
                        day = normalizeNumber(values.people, 1) * norm.day;
                        night = normalizeNumber(values.people, 1) * norm.night;
                    }
                    totalVolume = day + night;
                    if (serviceState.large_family) {
                        total = day * source.day[0] + night * source.night[0];
                    } else {
                        const parts = splitByThresholds(totalVolume, thresholds);
                        const dayRatio = totalVolume ? day / totalVolume : 0;
                        const nightRatio = totalVolume ? night / totalVolume : 0;
                        parts.forEach(function (part, index) {
                            total += part * dayRatio * source.day[index] + part * nightRatio * source.night[index];
                        });
                    }
                    if (serviceState.odn_mode === "with_odn") {
                        total += normalizeNumber(values.odn, 0) * periodConfig.single[sourceProfile].rates[0];
                    }

                    return {
                        total: total,
                        basis: isMeter ? "По счётчику" : "По нормативу",
                        quantity: totalVolume,
                    };
                }

                const source = periodConfig.three_zone[sourceProfile];
                const thresholds = source.thresholds;
                let peak = 0;
                let semipeak = 0;
                let night = 0;
                if (isMeter) {
                    peak = normalizeNumber(values.peak, 0);
                    semipeak = normalizeNumber(values.semipeak, 0);
                    night = normalizeNumber(values.night_three, 0);
                } else {
                    const norm = service.norms.three_zone[sourceProfile] || { peak: 20, semipeak: 28, night: 22 };
                    peak = normalizeNumber(values.people, 1) * norm.peak;
                    semipeak = normalizeNumber(values.people, 1) * norm.semipeak;
                    night = normalizeNumber(values.people, 1) * norm.night;
                }
                totalVolume = peak + semipeak + night;
                if (serviceState.large_family) {
                    total = peak * source.peak[0] + semipeak * source.semipeak[0] + night * source.night[0];
                } else {
                    const parts = splitByThresholds(totalVolume, thresholds);
                    const peakRatio = totalVolume ? peak / totalVolume : 0;
                    const semipeakRatio = totalVolume ? semipeak / totalVolume : 0;
                    const nightRatio = totalVolume ? night / totalVolume : 0;
                    parts.forEach(function (part, index) {
                        total += part * peakRatio * source.peak[index] + part * semipeakRatio * source.semipeak[index] + part * nightRatio * source.night[index];
                    });
                }
                if (serviceState.odn_mode === "with_odn") {
                    total += normalizeNumber(values.odn, 0) * periodConfig.single[sourceProfile].rates[0];
                }

                return {
                    total: total,
                    basis: isMeter ? "По счётчику" : "По нормативу",
                    quantity: totalVolume,
                };
            }

            function calculateResourcePeriod(service, serviceState, periodKey) {
                const periodConfig = service.periods[periodKey];
                const values = serviceState.period_values[periodKey];
                let total = 0;
                let volume = 0;
                let basis = "";

                if (service.calculation === "linear") {
                    volume = serviceState.input_method === "norm"
                        ? normalizeNumber(values.people, 1) * service.norm_value
                        : normalizeNumber(values.quantity, 0);
                    total = volume * periodConfig.rate;
                    basis = serviceState.input_method === "norm" ? normalizeNumber(values.people, 1) + " чел." : currency(volume) + " " + service.unit;
                }

                if (service.calculation === "hot_water") {
                    volume = serviceState.input_method === "norm"
                        ? normalizeNumber(values.people, 1) * service.norm_value
                        : normalizeNumber(values.quantity, 0);
                    total = volume * periodConfig.water_rate + volume * periodConfig.heat_norm * periodConfig.heat_rate;
                    basis = serviceState.input_method === "norm" ? normalizeNumber(values.people, 1) + " чел." : currency(volume) + " " + service.unit;
                }

                if (service.calculation === "gas") {
                    volume = serviceState.input_method === "norm" && serviceState.usage !== "heating"
                        ? normalizeNumber(values.people, 1) * service.norm_value
                        : normalizeNumber(values.quantity, 0);
                    total = volume * (serviceState.usage === "heating" ? periodConfig.heating_rate : periodConfig.stove_rate);
                    basis = serviceState.input_method === "norm" && serviceState.usage !== "heating"
                        ? normalizeNumber(values.people, 1) + " чел."
                        : currency(volume) + " " + service.unit;
                }

                if (service.calculation === "heating") {
                    volume = normalizeNumber(values.area, 0) * service.norm_value;
                    total = volume * periodConfig.rate;
                    if (serviceState.payment_mode === "year_round") {
                        total = total * (service.season_months || 7) / 12;
                    }
                    basis = currency(normalizeNumber(values.area, 0)) + " м²";
                }

                if (service.calculation === "waste") {
                    volume = normalizeNumber(values.area, 0) * service.norm_value;
                    total = volume * periodConfig.rate;
                    basis = currency(normalizeNumber(values.area, 0)) + " м²";
                }

                return {
                    total: total,
                    basis: basis,
                    quantity: volume,
                };
            }

            function calculateActiveService() {
                const service = currentService();
                const serviceState = currentState();
                if (service.type === "placeholder") {
                    return {
                        title: "Результат",
                        intro: "Для этого раздела пока доступно только разъяснение. Как только появится точная формула, мы добавим и этот расчёт.",
                        rows: [],
                    };
                }

                const rows = periods.map(function (period) {
                    const periodResult = service.type === "electricity"
                        ? calculateElectricityPeriod(service, serviceState, period.key)
                        : calculateResourcePeriod(service, serviceState, period.key);
                    return {
                        label: period.label,
                        total: periodResult.total,
                        basis: periodResult.basis,
                        quantity: periodResult.quantity,
                    };
                });

                return {
                    title: "Результат",
                    intro: "Стоимость коммунальной услуги в сопоставимых условиях:",
                    rows: rows,
                };
            }

            function renderResult() {
                const result = calculateActiveService();
                const service = currentService();
                const serviceState = currentState();
                const details = [];

                if (service.type === "electricity") {
                    const profile = (service.profiles || []).find(function (item) {
                        return item.key === serviceState.profile;
                    });
                    details.push({ label: "Тип жилья", value: profile ? profile.label : serviceState.profile });
                    details.push({ label: "Режим", value: serviceState.mode === "zone" && String(serviceState.profile).indexOf("heating_") !== 0 ? (serviceState.zone_mode === "three_zone" ? "Трёхзонный" : "Двухзонный") : "Одноставочный" });
                    details.push({ label: "Основа", value: serviceState.input_method === "meter" ? "Счётчик" : "Норматив" });
                    details.push({ label: "ОДН", value: serviceState.odn_mode === "with_odn" ? "Добавлены" : "Не учитываются" });
                    if (serviceState.large_family) {
                        details.push({ label: "Льгота", value: "Многодетная семья" });
                    }
                }

                if (service.type === "resource" && service.slug === "gas") {
                    details.push({ label: "Вариант", value: serviceState.usage === "heating" ? "Отопление и плита" : "Только плита" });
                }

                if (service.type === "resource" && service.slug === "heating") {
                    details.push({ label: "Режим оплаты", value: serviceState.payment_mode === "year_round" ? "Равномерно за год" : "Только в сезон" });
                }

                resultNode.innerHTML = [
                    "<h3>" + escapeHtml(result.title) + "</h3>",
                    "<div class=\"calculator-result-list\">",
                    result.rows.map(function (row) {
                        return "<p>Сумма за " + escapeHtml(row.label) + ": <strong>" + currency(row.total) + " руб.</strong></p>";
                    }).join(""),
                    "</div>",
                    details.length ? "<div class=\"calculator-result-meta\">" + details.map(function (detail) {
                        return "<div class=\"result-row\"><span>" + escapeHtml(detail.label) + "</span><strong>" + escapeHtml(detail.value) + "</strong></div>";
                    }).join("") + "</div>" : ""
                ].join("");
            }

            calculatorRoot.addEventListener("click", function (event) {
                const serviceButton = event.target.closest("[data-service-slug]");
                if (serviceButton && calculatorRoot.contains(serviceButton)) {
                    activeServiceSlug = serviceButton.dataset.serviceSlug;
                    renderAll();
                    return;
                }

                const choiceButtonNode = event.target.closest("[data-choice-group]");
                if (!choiceButtonNode || !formArea.contains(choiceButtonNode)) {
                    return;
                }

                const service = currentService();
                const serviceState = currentState();
                const group = choiceButtonNode.dataset.choiceGroup;
                const value = choiceButtonNode.dataset.choiceValue;
                serviceState[group] = value;

                if (service.slug === "electricity" && group === "profile" && String(value).indexOf("heating_") === 0) {
                    serviceState.mode = "single";
                }
                if (service.slug === "gas" && group === "usage" && value === "heating") {
                    serviceState.input_method = "meter";
                }

                renderAll();
            });

            formArea.addEventListener("input", function (event) {
                const input = event.target.closest("[data-field]");
                if (!input) {
                    return;
                }
                const serviceState = currentState();
                const periodKey = input.dataset.periodKey;
                const field = input.dataset.field;
                if (!serviceState.period_values[periodKey]) {
                    serviceState.period_values[periodKey] = {};
                }
                serviceState.period_values[periodKey][field] = input.value;
            });

            formArea.addEventListener("change", function (event) {
                const checkbox = event.target.closest("[data-flag]");
                if (!checkbox) {
                    return;
                }
                const serviceState = currentState();
                serviceState[checkbox.dataset.flag] = checkbox.checked;
                renderResult();
            });

            submitButton.addEventListener("click", function () {
                renderResult();
            });

            function renderAll() {
                serviceButtons.forEach(function (button) {
                    button.classList.toggle("is-active", button.dataset.serviceSlug === activeServiceSlug);
                });
                renderForm();
                renderResult();
            }

            renderAll();
        }
    }
});
